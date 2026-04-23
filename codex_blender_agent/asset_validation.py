from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from .validation_core import AlgorithmLedger, classify_aabb_pair, effective_tolerances
from .validation_manifest import (
    build_constraint_graph,
    manifest_allows_pair,
    manifest_required_contact_targets,
    normalize_asset_intent_manifest,
)
from .validation_repair import build_asset_repair_plan, safe_repair_delta_prompt
from .visual_geometry import AABB, aabb_from_points, clamp, hard_gates as visual_hard_gates
from .visual_geometry import metric_vector_from_analysis, record_bounds_points, scene_aabb, vector3


DEFAULT_CONTACT_TOLERANCE = 0.003
DEFAULT_PENETRATION_TOLERANCE = 0.004
DEFAULT_CLEARANCE_TOLERANCE = 0.005
DEFAULT_Z_FIGHTING_TOLERANCE = 0.0008
DEFAULT_RELATIVE_TOLERANCE = 0.002

ISSUE_SEVERITY_WEIGHTS = {"low": 0.25, "medium": 0.55, "high": 0.85, "critical": 1.15}
VALIDATION_BLOCKING_TYPES = {
    "interpenetration",
    "excessive_overlap",
    "excessive_allowed_penetration",
    "containment_risk",
    "required_contact_failure",
    "self_intersection",
    "non_manifold_topology",
    "castle_battlement_intersection",
    "castle_zone_violation",
}


@dataclass(frozen=True)
class AssetIssue:
    issue_id: str
    type: str
    severity: str
    objects: tuple[str, ...]
    evidence: dict[str, Any]
    suggested_fix: str
    confidence: float = 0.75
    location: tuple[float, float, float] | None = None
    local_bbox: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    acceptance_tests: tuple[str, ...] = ()
    target: str = ""
    source: str = "inferred"
    algorithm_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        issue_id = self.issue_id or f"issue_{self.type}"
        target = self.target or (self.objects[0] if self.objects else "scene")
        return {
            "issue_id": issue_id,
            "defect_id": issue_id,
            "type": self.type,
            "severity": _normalize_severity(self.severity),
            "confidence": round(clamp(self.confidence, 0.0, 1.0), 4),
            "objects": list(self.objects),
            "target": target,
            "location": [float(v) for v in self.location] if self.location is not None else None,
            "evidence": _json_safe(self.evidence),
            "suggested_fix": self.suggested_fix,
            "remediation_hint": self.suggested_fix,
            "local_bbox": _bbox_payload(self.local_bbox),
            "acceptance_tests": list(self.acceptance_tests),
            "source": self.source,
            "algorithm_ids": list(self.algorithm_ids),
        }


@dataclass
class MeshSnapshot:
    name: str
    type: str
    verts_world: list[tuple[float, float, float]]
    tris: list[tuple[int, int, int]]
    aabb_min: tuple[float, float, float]
    aabb_max: tuple[float, float, float]
    surface_area: float = 0.0
    volume_estimate: float | None = None
    material_names: tuple[str, ...] = ()
    material_slot_count: int = 0
    collections: tuple[str, ...] = ()
    vertex_count: int = 0
    face_count: int = 0
    loose_edge_count: int = 0
    non_manifold_edge_count: int = 0
    boundary_edge_count: int = 0
    degenerate_face_count: int = 0
    duplicate_face_count: int = 0
    object_id: str = ""
    matrix_world: tuple[tuple[float, float, float, float], ...] = ()
    origin_world: tuple[float, float, float] = (0.0, 0.0, 0.0)
    triangle_normals: tuple[tuple[float, float, float], ...] = ()
    mesh_hash: str = ""
    component_count: int = 1
    bvh: Any = None

    @property
    def aabb(self) -> AABB:
        return AABB(self.aabb_min, self.aabb_max)

    def to_record(self) -> dict[str, Any]:
        box = self.aabb
        return {
            "name": self.name,
            "type": self.type,
            "location": [float(v) for v in box.center],
            "dimensions": [float(v) for v in box.size],
            "bounds": [[float(v) for v in point] for point in box.corners],
            "material_names": list(self.material_names),
            "material_slot_count": int(self.material_slot_count),
            "collections": list(self.collections),
            "vertex_count": int(self.vertex_count or len(self.verts_world)),
            "face_count": int(self.face_count or len(self.tris)),
            "surface_area": float(self.surface_area),
            "volume_estimate": float(self.volume_estimate) if self.volume_estimate is not None else None,
            "loose_edge_count": int(self.loose_edge_count),
            "non_manifold_edge_count": int(self.non_manifold_edge_count),
            "boundary_edge_count": int(self.boundary_edge_count),
            "degenerate_face_count": int(self.degenerate_face_count),
            "duplicate_face_count": int(self.duplicate_face_count),
            "object_id": self.object_id,
            "origin_world": list(self.origin_world),
            "mesh_hash": self.mesh_hash,
            "component_count": int(self.component_count),
        }


def make_report_id() -> str:
    return f"asset-validation-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def aabb_overlap_volume(left_min: Iterable[float], left_max: Iterable[float], right_min: Iterable[float], right_max: Iterable[float]) -> float:
    left_min_v = vector3(left_min)
    left_max_v = vector3(left_max)
    right_min_v = vector3(right_min)
    right_max_v = vector3(right_max)
    extents = [
        max(min(left_max_v[index], right_max_v[index]) - max(left_min_v[index], right_min_v[index]), 0.0)
        for index in range(3)
    ]
    return extents[0] * extents[1] * extents[2]


def aabb_intersects(left: AABB, right: AABB, *, clearance: float = 0.0) -> bool:
    return all(left.minimum[i] <= right.maximum[i] + clearance and right.minimum[i] <= left.maximum[i] + clearance for i in range(3))


def sweep_and_prune(items: Iterable[Any], *, clearance: float = 0.0) -> list[tuple[int, int]]:
    boxes = [_aabb_from_any(item) for item in items]
    endpoints: list[tuple[float, int, int]] = []
    for index, box in enumerate(boxes):
        endpoints.append((box.minimum[0] - clearance, 0, index))
        endpoints.append((box.maximum[0] + clearance, 1, index))
    endpoints.sort(key=lambda row: (row[0], row[1]))
    active: set[int] = set()
    pairs: set[tuple[int, int]] = set()
    for _, event, index in endpoints:
        if event == 0:
            for other in active:
                if aabb_intersects(boxes[index], boxes[other], clearance=clearance):
                    pairs.add(tuple(sorted((index, other))))
            active.add(index)
        else:
            active.discard(index)
    return sorted(pairs)


def validate_records(
    records: Iterable[dict[str, Any]],
    *,
    coverage_by_part: dict[str, float] | None = None,
    settings: dict[str, Any] | None = None,
    intent_manifest: dict[str, Any] | None = None,
    source: str = "records",
) -> dict[str, Any]:
    records_list = [dict(record) for record in records]
    scene_box = scene_aabb(records_list)
    normalized_manifest = normalize_asset_intent_manifest(intent_manifest, records=records_list, prompt=str((settings or {}).get("prompt", "")))
    ledger = AlgorithmLedger()
    if scene_box is None:
        issue = AssetIssue(
            issue_id="issue_no_target_geometry",
            type="no_target_geometry",
            severity="high",
            objects=(),
            target="scene",
            evidence={"reason": "No visible evaluated mesh/object bounds were available."},
            suggested_fix="Create or select visible game-asset geometry before running automatic review.",
            confidence=1.0,
            acceptance_tests=("At least one visible mesh/object exists.", "Scene bounds are non-degenerate."),
        ).as_dict()
        ledger.add("collect_geometry", "Collect evaluated target geometry", status="failed", issue_count=1, evidence_refs=[issue["issue_id"]], error="no_target_geometry")
        return _build_report([], [issue], coverage_by_part=coverage_by_part, source=source, settings=settings, intent_manifest=normalized_manifest, algorithm_ledger=ledger.rows)
    issues: list[dict[str, Any]] = []
    with ledger.check("collect_geometry", "Collect evaluated target geometry", inputs={"source": source}, thresholds={}) as row:
        row["issue_count"] = 0
        row["objects"] = [str(record.get("name", "")) for record in records_list]
    before = len(issues)
    issues.extend(_topology_issues_from_records(records_list))
    _record_check(ledger, "topology_integrity", "Topology integrity", issues[before:])
    before = len(issues)
    issues.extend(_pair_issues_from_records(records_list, scene_box, settings=settings, intent_manifest=normalized_manifest))
    _record_check(ledger, "pair_overlap_containment", "Pair overlap / containment / z-fighting", issues[before:])
    before = len(issues)
    issues.extend(_support_and_scale_issues(records_list, scene_box, intent_manifest=normalized_manifest))
    _record_check(ledger, "support_scale_origin", "Support, scale, and origin sanity", issues[before:])
    before = len(issues)
    issues.extend(_manifest_constraint_issues(records_list, scene_box, normalized_manifest))
    _record_check(ledger, "intent_constraints", "Intent manifest and inferred constraints", issues[before:])
    before = len(issues)
    issues.extend(_castle_and_zone_issues(records_list, scene_box, settings=settings))
    _record_check(ledger, "castle_fortification_prior", "Castle/fortification prior", issues[before:])
    before = len(issues)
    issues.extend(_coverage_issues(records_list, coverage_by_part or {}))
    _record_check(ledger, "coverage_by_part", "Coverage by part", issues[before:])
    return _build_report(records_list, _dedupe_issues(issues), coverage_by_part=coverage_by_part, source=source, settings=settings, intent_manifest=normalized_manifest, algorithm_ledger=ledger.rows)


def validate_snapshots(
    snapshots: Iterable[MeshSnapshot],
    *,
    coverage_by_part: dict[str, float] | None = None,
    settings: dict[str, Any] | None = None,
    intent_manifest: dict[str, Any] | None = None,
    source: str = "evaluated_scene",
) -> dict[str, Any]:
    snapshot_list = list(snapshots)
    records = [snapshot.to_record() for snapshot in snapshot_list]
    report = validate_records(records, coverage_by_part=coverage_by_part, settings=settings, intent_manifest=intent_manifest, source=source)
    issues = list(report.get("issues", []) or [])
    issues.extend(_bvh_overlap_issues(snapshot_list))
    issues.extend(_self_intersection_issues(snapshot_list))
    ledger = list(report.get("algorithm_ledger", []) or [])
    _record_check_obj(ledger, "bvh_triangle_overlap", "BVH triangle overlap", [issue for issue in issues if "bvh" in str(issue.get("issue_id", ""))])
    _record_check_obj(ledger, "self_intersection", "Self-intersection candidates", [issue for issue in issues if str(issue.get("type", "")) == "self_intersection"])
    report = _build_report(records, _dedupe_issues(issues), coverage_by_part=coverage_by_part, source=source, settings=settings, intent_manifest=report.get("intent_manifest") or intent_manifest, algorithm_ledger=ledger)
    report["snapshot_summary"] = {
        "source": source,
        "evaluated_mesh_count": len(snapshot_list),
        "triangle_count": sum(len(snapshot.tris) for snapshot in snapshot_list),
        "vertex_count": sum(len(snapshot.verts_world) for snapshot in snapshot_list),
    }
    return report


def validate_scene_asset(
    context: Any,
    *,
    selected_only: bool = False,
    settings: dict[str, Any] | None = None,
    coverage_by_part: dict[str, float] | None = None,
    intent_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        snapshots = collect_evaluated_mesh_snapshots(context, selected_only=selected_only, settings=settings)
        if snapshots:
            if intent_manifest is None:
                intent_manifest = _scene_intent_manifest(context)
            return validate_snapshots(snapshots, coverage_by_part=coverage_by_part, settings=settings, intent_manifest=intent_manifest, source="evaluated_scene")
    except Exception as exc:
        records = _fallback_object_records(context, selected_only=selected_only)
        report = validate_records(records, coverage_by_part=coverage_by_part, settings=settings, intent_manifest=intent_manifest or _scene_intent_manifest(context), source="fallback_bounds")
        report["adapter_error"] = str(exc)
        return report
    return validate_records([], coverage_by_part=coverage_by_part, settings=settings, intent_manifest=intent_manifest or _scene_intent_manifest(context), source="evaluated_scene")


def collect_evaluated_mesh_snapshots(context: Any, *, selected_only: bool = False, settings: dict[str, Any] | None = None) -> list[MeshSnapshot]:
    import mathutils
    from mathutils.bvhtree import BVHTree

    depsgraph = context.evaluated_depsgraph_get()
    snapshots: list[MeshSnapshot] = []
    for obj in _candidate_mesh_objects(context, selected_only=selected_only):
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = None
        try:
            mesh = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        except TypeError:
            mesh = obj_eval.to_mesh()
        if mesh is None:
            continue
        try:
            mesh.calc_loop_triangles()
            matrix = obj_eval.matrix_world.copy()
            verts_world = [tuple(float(v) for v in (matrix @ vertex.co)) for vertex in mesh.vertices]
            tris = [tuple(int(v) for v in loop_tri.vertices) for loop_tri in mesh.loop_triangles]
            if not verts_world or not tris:
                continue
            topology = _topology_stats_from_tris(
                verts_world,
                tris,
                mesh_edges=[tuple(edge.vertices) for edge in getattr(mesh, "edges", [])],
            )
            triangle_normals = tuple(_triangle_normal(verts_world[tri[0]], verts_world[tri[1]], verts_world[tri[2]]) for tri in tris[:4096])
            mesh_hash = _mesh_hash(verts_world, tris)
            bvh = BVHTree.FromPolygons([mathutils.Vector(point) for point in verts_world], tris, all_triangles=True, epsilon=1.0e-6)
            material_names: list[str] = []
            material_slot_count = 0
            try:
                material_slot_count = len(getattr(obj, "material_slots", []) or [])
                material_names = [slot.material.name for slot in getattr(obj, "material_slots", []) or [] if getattr(slot, "material", None)]
            except Exception:
                material_names = []
            collections = []
            try:
                collections = [collection.name for collection in getattr(obj, "users_collection", []) or []]
            except Exception:
                collections = []
            box = aabb_from_points(verts_world)
            snapshots.append(
                MeshSnapshot(
                    name=str(getattr(obj, "name", "")),
                    type=str(getattr(obj, "type", "MESH")),
                    verts_world=verts_world,
                    tris=tris,
                    aabb_min=box.minimum,
                    aabb_max=box.maximum,
                    surface_area=float(topology["surface_area"]),
                    volume_estimate=float(topology["volume_estimate"]),
                    material_names=tuple(material_names),
                    material_slot_count=material_slot_count,
                    collections=tuple(str(name) for name in collections),
                    vertex_count=len(verts_world),
                    face_count=len(tris),
                    loose_edge_count=int(topology["loose_edge_count"]),
                    non_manifold_edge_count=int(topology["non_manifold_edge_count"]),
                    boundary_edge_count=int(topology["boundary_edge_count"]),
                    degenerate_face_count=int(topology["degenerate_face_count"]),
                    duplicate_face_count=int(topology["duplicate_face_count"]),
                    object_id=str(getattr(obj, "name_full", getattr(obj, "name", ""))),
                    matrix_world=tuple(tuple(float(value) for value in row) for row in matrix),
                    origin_world=tuple(float(value) for value in matrix.translation),
                    triangle_normals=triangle_normals,
                    mesh_hash=mesh_hash,
                    component_count=int(topology.get("component_count", 1) or 1),
                    bvh=bvh,
                )
            )
        finally:
            try:
                obj_eval.to_mesh_clear()
            except Exception:
                pass
    return snapshots


def _candidate_mesh_objects(context: Any, *, selected_only: bool = False) -> list[Any]:
    selected = list(getattr(context, "selected_objects", []) or [])
    source = selected if selected_only and selected else []
    if not source:
        scene = getattr(context, "scene", None)
        source = list(getattr(scene, "objects", []) or [])
    objects = []
    for obj in source:
        try:
            hidden = bool(obj.hide_get())
        except Exception:
            hidden = False
        if not hidden and getattr(obj, "type", "") == "MESH":
            objects.append(obj)
    return objects


def _fallback_object_records(context: Any, *, selected_only: bool = False) -> list[dict[str, Any]]:
    source = list(getattr(context, "selected_objects", []) or []) if selected_only and getattr(context, "selected_objects", None) else []
    if not source:
        scene = getattr(context, "scene", None)
        source = [obj for obj in getattr(scene, "objects", []) or [] if getattr(obj, "type", "") not in {"CAMERA", "LIGHT"}]
    records = []
    for obj in source:
        try:
            import mathutils

            bounds = [[float(value) for value in (obj.matrix_world @ mathutils.Vector(corner))] for corner in obj.bound_box]
        except Exception:
            bounds = []
        material_names: list[str] = []
        material_slot_count = 0
        try:
            material_slot_count = len(getattr(obj, "material_slots", []) or [])
            material_names = [slot.material.name for slot in getattr(obj, "material_slots", []) or [] if getattr(slot, "material", None)]
        except Exception:
            pass
        records.append(
            {
                "name": str(getattr(obj, "name", "")),
                "type": str(getattr(obj, "type", "")),
                "location": [float(value) for value in getattr(obj, "location", (0.0, 0.0, 0.0))],
                "dimensions": [float(value) for value in getattr(obj, "dimensions", (1.0, 1.0, 1.0))],
                "bounds": bounds,
                "material_names": material_names,
                "material_slot_count": material_slot_count,
                "collections": [str(getattr(collection, "name", "")) for collection in getattr(obj, "users_collection", []) or []],
                "vertex_count": len(getattr(getattr(obj, "data", None), "vertices", []) or []),
                "face_count": len(getattr(getattr(obj, "data", None), "polygons", []) or []),
            }
        )
    return records


def _topology_stats_from_tris(
    verts: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
    *,
    mesh_edges: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    edge_counts: dict[tuple[int, int], int] = {}
    duplicate_faces: dict[tuple[tuple[float, float, float], ...], int] = {}
    surface_area = 0.0
    signed_volume = 0.0
    degenerate = 0
    for tri in tris:
        a, b, c = (verts[tri[0]], verts[tri[1]], verts[tri[2]])
        area = _triangle_area(a, b, c)
        surface_area += area
        if area <= 1.0e-10:
            degenerate += 1
        signed_volume += _signed_tetra_volume(a, b, c)
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted(edge))
            edge_counts[key] = edge_counts.get(key, 0) + 1
        face_key = tuple(sorted(_rounded_point(verts[index], places=5) for index in tri))
        duplicate_faces[face_key] = duplicate_faces.get(face_key, 0) + 1
    mesh_edge_set = {tuple(sorted(edge)) for edge in (mesh_edges or [])}
    component_count = _connected_component_count(edge_counts)
    return {
        "surface_area": float(surface_area),
        "volume_estimate": abs(float(signed_volume)),
        "loose_edge_count": len([edge for edge in mesh_edge_set if edge not in edge_counts]),
        "non_manifold_edge_count": sum(1 for count in edge_counts.values() if count > 2),
        "boundary_edge_count": sum(1 for count in edge_counts.values() if count == 1),
        "degenerate_face_count": int(degenerate),
        "duplicate_face_count": sum(max(count - 1, 0) for count in duplicate_faces.values()),
        "component_count": component_count,
    }


def _topology_issues_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for record in records:
        name = str(record.get("name", "object") or "object")
        box = _aabb_from_any(record)
        degenerate = int(record.get("degenerate_face_count", 0) or 0)
        loose = int(record.get("loose_edge_count", 0) or 0)
        non_manifold = int(record.get("non_manifold_edge_count", 0) or 0)
        duplicate = int(record.get("duplicate_face_count", 0) or 0)
        counts = {
            "degenerate_face_count": degenerate,
            "loose_edge_count": loose,
            "non_manifold_edge_count": non_manifold,
            "duplicate_face_count": duplicate,
        }
        if degenerate:
            issues.append(_issue(f"issue_degenerate_faces_{_slug(name)}", "degenerate_geometry", "high" if degenerate > 5 else "medium", [name], box, counts, "Collapse or retriangulate zero-area faces in the local defective region.", ["Degenerate face count is zero.", "No new non-manifold edges are introduced."], confidence=0.9))
        if loose:
            issues.append(_issue(f"issue_loose_geometry_{_slug(name)}", "loose_geometry", "medium", [name], box, counts, "Remove loose vertices/edges that are not part of visible asset surfaces.", ["Loose edge count is zero in the target region.", "Visible silhouette remains stable."], confidence=0.85))
        if non_manifold:
            issues.append(_issue(f"issue_non_manifold_{_slug(name)}", "non_manifold_topology", "critical" if non_manifold > 3 else "high", [name], box, counts, "Split, dissolve, or locally rebuild non-manifold edges without global remeshing.", ["Non-manifold edge count drops to zero.", "External silhouette changes minimally."], confidence=0.9))
        if duplicate:
            issues.append(_issue(f"issue_duplicate_faces_{_slug(name)}", "duplicate_surface_risk", "high" if duplicate > 4 else "medium", [name], box, counts, "Delete redundant coincident faces or merge the duplicate local surface.", ["Duplicate coincident face count is zero.", "No z-fighting remains in validation views."], confidence=0.8))
    return issues


def _pair_issues_from_records(
    records: list[dict[str, Any]],
    scene_box: AABB,
    *,
    settings: dict[str, Any] | None = None,
    intent_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    tol = _effective_tolerance(scene_box, settings)
    boxes = [_aabb_from_any(record) for record in records]
    for i, j in sweep_and_prune(records, clearance=max(tol["clearance"], tol["z_fighting"])):
        left = boxes[i]
        right = boxes[j]
        left_name = str(records[i].get("name", f"object_{i}") or f"object_{i}")
        right_name = str(records[j].get("name", f"object_{j}") or f"object_{j}")
        classified = classify_aabb_pair(left, right, tolerances=effective_tolerances(scene_box.diagonal, settings))
        overlap = float(classified["overlap_volume"])
        overlap_ratio = float(classified["overlap_ratio_of_smaller"])
        allowed_contact = manifest_allows_pair(intent_manifest, left_name, right_name)
        if overlap_ratio > 0.04:
            issue_type = "excessive_allowed_penetration" if allowed_contact else ("interpenetration" if overlap_ratio > 0.18 else "excessive_overlap")
            severity = "medium" if allowed_contact and overlap_ratio <= 0.18 else ("critical" if overlap_ratio > 0.45 else ("high" if overlap_ratio > 0.18 else "medium"))
            issues.append(
                _issue(
                    f"issue_{issue_type}_{_slug(left_name)}_{_slug(right_name)}",
                    issue_type,
                    severity,
                    [left_name, right_name],
                    _combined_box(left, right),
                    {"overlap_volume": overlap, "overlap_ratio_of_smaller": overlap_ratio, "aabb_only": True, "allowed_contact": allowed_contact, **classified},
                    "Reduce penetration below the allowed contact tolerance." if allowed_contact else "Separate the parts or convert the contact into a deliberate flush attachment with penetration below tolerance.",
                    ["No forbidden overlap remains.", f"Estimated penetration is <= {tol['penetration']:.4f}."],
                    confidence=0.82 if allowed_contact else 0.72,
                    source="manifest" if allowed_contact else "direct_geometry",
                    algorithm_ids=("pair_overlap_containment",),
                )
            )
        if _center_inside(left.center, right) and left.volume < right.volume * 0.35:
            issues.append(_containment_issue(left_name, right_name, left, right))
        elif _center_inside(right.center, left) and right.volume < left.volume * 0.35:
            issues.append(_containment_issue(right_name, left_name, right, left))
        if _looks_like_duplicate_surface(left, right, tol):
            issues.append(
                _issue(
                    f"issue_z_fighting_{_slug(left_name)}_{_slug(right_name)}",
                    "z_fighting_risk",
                    "medium",
                    [left_name, right_name],
                    _combined_box(left, right),
                    {"center_distance": _distance(left.center, right.center), "xy_overlap_ratio": _xy_overlap_ratio(left, right)},
                    "Delete one duplicate surface, merge the panels, or offset intentional decals by a safe render clearance.",
                    ["No near-coplanar duplicate surface remains.", "The affected viewport views no longer show z-fighting risk."],
                    confidence=0.7,
                )
            )
    return issues


def _support_and_scale_issues(records: list[dict[str, Any]], scene_box: AABB, *, intent_manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    boxes = [_aabb_from_any(record) for record in records]
    diagonals = sorted(box.diagonal for box in boxes)
    median_diag = diagonals[len(diagonals) // 2] if diagonals else scene_box.diagonal
    min_scene_z = min(box.minimum[2] for box in boxes)
    for index, (record, box) in enumerate(zip(records, boxes)):
        name = str(record.get("name", f"object_{index}") or f"object_{index}")
        ratio = box.diagonal / max(median_diag, 1.0e-9)
        if ratio > 5.0 and len(records) >= 3:
            issues.append(_issue(f"issue_scale_outlier_large_{_slug(name)}", "scale_outlier", "medium", [name], box, {"diagonal": box.diagonal, "median_diagonal": median_diag, "ratio": ratio}, "Check whether this part should be the scene anchor; otherwise rescale or isolate it.", ["Part scale ratio is within expected scene range.", "Smaller required parts remain visible and reviewable."], confidence=min(1.0, ratio / 8.0), algorithm_ids=("support_scale_origin",)))
        if ratio < 0.08 and len(records) >= 2:
            issues.append(_issue(f"issue_tiny_detail_{_slug(name)}", "tiny_detail_missed", "low", [name], box, {"diagonal": box.diagonal, "median_diagonal": median_diag, "ratio": ratio}, "Add a dedicated close-up review view or enlarge this feature if it is gameplay-critical.", ["Tiny part has a close-up or is marked secondary.", "Projected detail size clears review threshold."], confidence=min(1.0, 0.08 / max(ratio, 1.0e-9)), algorithm_ids=("support_scale_origin",)))
        bottom_gap = box.minimum[2] - min_scene_z
        if bottom_gap > max(scene_box.diagonal * 0.08, median_diag * 0.45, 0.18) and box.diagonal < scene_box.diagonal * 0.70 and not _has_support_below(index, boxes):
            required_targets = manifest_required_contact_targets(intent_manifest, name)
            issues.append(_issue(f"issue_floating_part_{_slug(name)}", "floating_part", "high" if bottom_gap > scene_box.diagonal * 0.25 else "medium", [name], box, {"ground_gap": bottom_gap, "scene_min_z": min_scene_z, "support_detected": False, "required_contact_targets": required_targets}, "Attach this part to the nearest intended support, lower it to contact, or mark it as intentionally suspended.", ["Part contacts a support surface or is explicitly intentional.", "No new intersections are introduced."], confidence=0.86 if required_targets else 0.78, source="manifest" if required_targets else "inferred", algorithm_ids=("support_scale_origin",)))
        material_slot_count = int(record.get("material_slot_count", 0) or 0)
        material_names = [str(item) for item in record.get("material_names", []) or [] if str(item).strip()]
        if material_slot_count > 0 and not material_names:
            issues.append(_issue(f"issue_material_slots_{_slug(name)}", "inconsistent_material_slots", "low", [name], box, {"material_slot_count": material_slot_count, "material_names": material_names}, "Assign clear realtime materials or remove empty material slots before asset promotion.", ["Every material slot is assigned or removed.", "Object has a simple game-ready material label."], confidence=0.65))
        origin = record.get("origin_world")
        if origin:
            p = vector3(origin)
            if not all(box.minimum[axis] - 1.0e-6 <= p[axis] <= box.maximum[axis] + 1.0e-6 for axis in range(3)):
                issues.append(_issue(f"issue_origin_pivot_{_slug(name)}", "origin_pivot_error", "low", [name], box, {"origin_world": list(p), "aabb": {"minimum": list(box.minimum), "maximum": list(box.maximum)}}, "Move the object origin/pivot into the asset bounds or to the authored hinge/snap anchor.", ["Origin is inside the object bounds or matches an explicit pivot rule.", "Transform remains stable for reuse."], confidence=0.7, algorithm_ids=("support_scale_origin",)))
    return issues


def _coverage_issues(records: list[dict[str, Any]], coverage_by_part: dict[str, float]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not coverage_by_part:
        return issues
    names = {_slug(str(record.get("name", ""))): str(record.get("name", "")) for record in records}
    for part, score in coverage_by_part.items():
        value = clamp(score, 0.0, 1.0)
        if value >= 0.50:
            continue
        part_slug = _slug(str(part))
        target = names.get(part_slug, str(part))
        issues.append(
            AssetIssue(
                issue_id=f"issue_undercovered_part_{part_slug}",
                type="undercovered_part",
                severity="medium" if value < 0.35 else "low",
                objects=(target,),
                target=str(part),
                evidence={"coverage_score": value, "part": str(part)},
                suggested_fix="Plan an additional review view focused on this part before accepting visual quality.",
                confidence=0.72,
                acceptance_tests=("Part coverage score reaches the configured minimum.", "A screenshot clearly shows the undercovered part."),
            ).as_dict()
        )
    return issues


def _manifest_constraint_issues(records: list[dict[str, Any]], scene_box: AABB, manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not manifest:
        return []
    records_by_name = {str(record.get("name", "")): record for record in records}
    boxes = {name: _aabb_from_any(record) for name, record in records_by_name.items()}
    tol = _effective_tolerance(scene_box, {})
    issues: list[dict[str, Any]] = []
    for contact in manifest.get("required_contacts", []) or []:
        if not isinstance(contact, dict):
            continue
        source = str(contact.get("object", "") or "")
        if source not in boxes:
            continue
        source_box = boxes[source]
        max_gap = float(contact.get("tolerance") or tol["contact"])
        for target in [str(item) for item in contact.get("targets", []) or []]:
            target_box = boxes.get(target)
            if target_box is None:
                continue
            vertical_gap = min(abs(source_box.minimum[2] - target_box.maximum[2]), abs(target_box.minimum[2] - source_box.maximum[2]))
            xy_ratio = _xy_overlap_ratio(source_box, target_box)
            if vertical_gap > max_gap or xy_ratio < 0.02:
                issues.append(
                    _issue(
                        f"issue_required_contact_{_slug(source)}_{_slug(target)}",
                        "required_contact_failure",
                        "high",
                        [source, target],
                        _combined_box(source_box, target_box),
                        {"vertical_gap": vertical_gap, "xy_overlap_ratio": xy_ratio, "tolerance": max_gap, "manifest_source": "required_contacts"},
                        f"Snap {source} to its required contact target {target} with gap <= {max_gap:.4f}.",
                        ["Required contact gap is within tolerance.", "No excessive penetration is introduced."],
                        confidence=0.95,
                        source="manifest",
                        algorithm_ids=("intent_constraints",),
                    )
                )
    expected = manifest.get("expected_dimensions", {}) if isinstance(manifest.get("expected_dimensions", {}), dict) else {}
    for name, dims in expected.items():
        if name not in boxes or not isinstance(dims, (list, tuple)) or len(dims) < 3:
            continue
        expected_dims = vector3(dims, default=(0.0, 0.0, 0.0))
        actual = boxes[name].size
        errors = [
            abs(actual[index] - expected_dims[index]) / max(abs(expected_dims[index]), 1.0e-9)
            for index in range(3)
            if abs(expected_dims[index]) > 1.0e-9
        ]
        max_error = max(errors or [0.0])
        if max_error > 0.35:
            issues.append(
                _issue(
                    f"issue_expected_dimensions_{_slug(name)}",
                    "scale_outlier",
                    "medium" if max_error < 0.75 else "high",
                    [name],
                    boxes[name],
                    {"expected_dimensions": list(expected_dims), "actual_dimensions": list(actual), "max_relative_error": max_error},
                    "Resize this part toward the manifest expected dimensions without changing unrelated parts.",
                    ["Part dimensions are within manifest tolerance.", "Attached/supporting parts remain connected."],
                    confidence=0.9,
                    source="manifest",
                    algorithm_ids=("intent_constraints",),
                )
            )
    return issues


_CASTLE_TERMS = {"castle", "fort", "fortress", "tower", "wall", "keep", "battlement", "crenel", "merlon", "parapet", "gate", "moat", "bridge"}
_MOAT_TERMS = {"moat", "water", "trench", "river", "lake"}
_TREE_TERMS = {"tree", "oak", "pine", "vegetation", "shrub", "bush"}
_SUPPORT_TERMS = {"wall", "keep", "tower", "base", "roof", "building", "castle", "bastion"}
_BATTLEMENT_TERMS = {"battlement", "crenel", "merlon", "parapet", "crown", "tooth"}


def _castle_and_zone_issues(records: list[dict[str, Any]], scene_box: AABB, *, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not _castle_prior_active(records):
        return issues
    tol = _effective_tolerance(scene_box, settings)
    boxes = [_aabb_from_any(record) for record in records]
    names = [str(record.get("name", f"object_{index}") or f"object_{index}") for index, record in enumerate(records)]
    moat_indices = [index for index, record in enumerate(records) if _record_has_term(record, _MOAT_TERMS) and not _record_has_term(record, _TREE_TERMS)]
    tree_indices = [index for index, record in enumerate(records) if _record_has_term(record, _TREE_TERMS)]
    support_indices = [index for index, record in enumerate(records) if _record_has_term(record, _SUPPORT_TERMS)]
    battlement_indices = [index for index, record in enumerate(records) if _record_has_term(record, _BATTLEMENT_TERMS)]
    tower_indices = [index for index, record in enumerate(records) if "tower" in _record_text(record)]

    for moat_index in moat_indices:
        moat_box = boxes[moat_index]
        for tree_index in tree_indices:
            tree_box = boxes[tree_index]
            if _xy_overlap_ratio(tree_box, moat_box) > 0.20 and tree_box.center[2] <= moat_box.maximum[2] + max(tree_box.size[2] * 0.65, tol["contact"]):
                issues.append(
                    _issue(
                        f"issue_castle_zone_tree_in_moat_{_slug(names[tree_index])}_{_slug(names[moat_index])}",
                        "castle_zone_violation",
                        "high",
                        [names[tree_index], names[moat_index]],
                        _combined_box(tree_box, moat_box),
                        {"zone": "moat", "object": names[tree_index], "xy_overlap_ratio": _xy_overlap_ratio(tree_box, moat_box)},
                        "Move vegetation or props out of the moat/water zone unless the prompt explicitly asked for an obstruction there.",
                        ["Moat zone is clear of unrelated props.", "Bridge/gate access remains readable from audit views."],
                        confidence=0.82,
                    )
                )

    castle_body = _union_box([boxes[index] for index in range(len(boxes)) if index not in moat_indices + tree_indices])
    if castle_body is not None:
        body_area = _xy_area(castle_body)
        for moat_index in moat_indices:
            moat_box = boxes[moat_index]
            moat_area = _xy_area(moat_box)
            if body_area > 0 and moat_area / body_area > 2.8:
                issues.append(
                    _issue(
                        f"issue_castle_oversized_moat_{_slug(names[moat_index])}",
                        "castle_oversized_moat",
                        "medium",
                        [names[moat_index]],
                        moat_box,
                        {"moat_xy_area": moat_area, "castle_body_xy_area": body_area, "ratio": moat_area / body_area},
                        "Reduce moat footprint or increase castle footprint so the moat supports the asset instead of dominating it.",
                        ["Moat-to-castle area ratio is within a plausible range.", "Castle remains the primary visual subject."],
                        confidence=0.78,
                    )
                )

    for battlement_index in battlement_indices:
        battlement_box = boxes[battlement_index]
        for support_index in support_indices:
            if support_index == battlement_index:
                continue
            support_box = boxes[support_index]
            if _xy_overlap_ratio(battlement_box, support_box) < 0.08:
                continue
            penetration = support_box.maximum[2] - battlement_box.minimum[2]
            if penetration > max(tol["penetration"] * 4.0, min(battlement_box.size[2], support_box.size[2]) * 0.16):
                issues.append(
                    _issue(
                        f"issue_castle_battlement_intersection_{_slug(names[battlement_index])}_{_slug(names[support_index])}",
                        "castle_battlement_intersection",
                        "high",
                        [names[battlement_index], names[support_index]],
                        _combined_box(battlement_box, support_box),
                        {"penetration_depth_estimate": penetration, "xy_overlap_ratio": _xy_overlap_ratio(battlement_box, support_box)},
                        "Re-seat the crown/battlement on the top surface, then boolean-union/apply or leave a clean flush contact with no deep intersection.",
                        ["Battlement bottom sits on the support top within tolerance.", "No crown segment intersects the wall or tower body."],
                        confidence=0.84,
                    )
                )

    blockout_candidates = [
        index
        for index, record in enumerate(records)
        if _looks_like_blockout_piece(record, boxes[index]) and (index in battlement_indices or _record_has_term(record, {"cube", "block", "stone"}))
    ]
    if len(blockout_candidates) >= 4:
        block_boxes = [boxes[index] for index in blockout_candidates]
        z_values = [round(box.center[2], 2) for box in block_boxes]
        if max(z_values.count(value) for value in set(z_values)) >= 4:
            issue_box = _union_box(block_boxes) or scene_box
            issues.append(
                _issue(
                    "issue_castle_unmerged_blockout_repetition",
                    "castle_unmerged_blockout",
                    "medium",
                    [names[index] for index in blockout_candidates[:8]],
                    issue_box,
                    {"candidate_count": len(blockout_candidates), "common_center_z_values": z_values[:16]},
                    "If these cubes are intended as one crown/parapet, boolean-union/apply or create one clean repeated mesh strip before final acceptance.",
                    ["Repeated crown/blockout pieces are intentionally modular or joined into clean topology.", "No duplicate/coplanar/intersection warning remains for the crown."],
                    confidence=0.72,
                )
            )

    if 0 < len(tower_indices) < 4 and _record_has_any_name(records, {"castle", "fort", "fortress"}):
        issue_box = _union_box([boxes[index] for index in tower_indices]) or scene_box
        issues.append(
            _issue(
                "issue_castle_tower_count_or_symmetry",
                "castle_tower_count_or_symmetry",
                "low",
                [names[index] for index in tower_indices],
                issue_box,
                {"tower_count": len(tower_indices), "expected_pattern": "four-corner symmetry if the asset reads as a classic castle"},
                "Check whether the castle needs balanced corner towers or explicitly asymmetric composition.",
                ["Tower count/symmetry matches the intended castle design.", "Audit views show all major corners clearly."],
                confidence=0.62,
            )
        )

    return issues


def _bvh_overlap_issues(snapshots: list[MeshSnapshot]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for i, j in sweep_and_prune(snapshots, clearance=0.0):
        left = snapshots[i]
        right = snapshots[j]
        if left.bvh is None or right.bvh is None:
            continue
        try:
            overlaps = left.bvh.overlap(right.bvh)
        except Exception:
            overlaps = []
        if not overlaps:
            continue
        count = len(overlaps)
        severity = "critical" if count > 250 else ("high" if count > 25 else "medium")
        issues.append(
            _issue(
                f"issue_bvh_interpenetration_{_slug(left.name)}_{_slug(right.name)}",
                "interpenetration",
                severity,
                [left.name, right.name],
                _combined_box(left.aabb, right.aabb),
                {"triangle_pair_count": count, "source": "BVHTree.overlap"},
                "Resolve intersecting evaluated triangles by separating, trimming, or locally rebuilding the contact region.",
                ["BVH triangle overlap count is zero or below intentional-contact tolerance.", "No new floating part is introduced."],
                confidence=0.92,
                source="direct_geometry",
                algorithm_ids=("bvh_triangle_overlap",),
            )
        )
    return issues


def _self_intersection_issues(snapshots: list[MeshSnapshot]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.bvh is None or len(snapshot.tris) < 2:
            continue
        try:
            overlaps = snapshot.bvh.overlap(snapshot.bvh)
        except Exception:
            overlaps = []
        suspicious = 0
        for tri_a, tri_b in overlaps[:5000]:
            if tri_a >= tri_b or set(snapshot.tris[tri_a]) & set(snapshot.tris[tri_b]):
                continue
            suspicious += 1
            if suspicious >= 20:
                break
        if suspicious:
            issues.append(_issue(f"issue_self_intersection_{_slug(snapshot.name)}", "self_intersection", "high" if suspicious >= 5 else "medium", [snapshot.name], snapshot.aabb, {"non_adjacent_overlap_candidates": suspicious, "source": "BVHTree.self_overlap"}, "Locally separate or retriangulate self-crossing surfaces without replacing the whole asset.", ["No non-adjacent self-overlap candidates remain.", "Topology cleanup does not change intentional openings."], confidence=0.68, source="direct_geometry", algorithm_ids=("self_intersection",)))
    return issues


def _build_report(
    records: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    coverage_by_part: dict[str, float] | None = None,
    source: str = "records",
    settings: dict[str, Any] | None = None,
    intent_manifest: dict[str, Any] | None = None,
    algorithm_ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues = _dedupe_issues(issues)
    manifest = normalize_asset_intent_manifest(intent_manifest, records=records, prompt=str((settings or {}).get("prompt", "")))
    constraint_graph = build_constraint_graph(records, manifest)
    metrics = metric_vector_from_analysis(records, issues, coverage_by_part=coverage_by_part)
    gates = visual_hard_gates(metrics, issues, target_score=float((settings or {}).get("target_score", 0.85) or 0.85))
    critical = [issue for issue in issues if str(issue.get("severity")) == "critical"]
    forbidden = [
        issue
        for issue in issues
        if str(issue.get("type")) in {"interpenetration", "excessive_overlap", "excessive_allowed_penetration", "containment_risk", "z_fighting_risk", "castle_battlement_intersection", "castle_zone_violation"}
        and str(issue.get("severity")) in {"high", "critical"}
    ]
    contact_failures = [
        issue
        for issue in issues
        if str(issue.get("type")) in {"floating_part", "required_contact_failure"} and str(issue.get("severity")) in {"high", "critical"}
    ]
    gates.update(
        {
            "no_critical_validation_issue": not critical,
            "no_forbidden_or_excessive_intersection": not forbidden,
            "no_required_contact_failure": not contact_failures,
        }
    )
    gates["can_complete"] = bool(gates.get("can_complete")) and all(
        gates[key] for key in ("no_critical_validation_issue", "no_forbidden_or_excessive_intersection", "no_required_contact_failure")
    )
    issue_score = sum(
        ISSUE_SEVERITY_WEIGHTS.get(str(issue.get("severity", "low")), 0.25) * clamp(issue.get("confidence", 0.5), 0.0, 1.0)
        for issue in issues
    )
    asset_score = round(clamp(1.0 - issue_score / max(len(records) + 2.0, 2.0), 0.0, 1.0) * 100.0, 2)
    ordered = sorted(issues, key=lambda item: (-ISSUE_SEVERITY_WEIGHTS.get(str(item.get("severity", "low")), 0.25), str(item.get("issue_id", ""))))
    report = {
        "report_id": make_report_id(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "status": "no_target_geometry" if not records else "completed",
        "object_count": len(records),
        "issue_count": len(issues),
        "critical_count": len(critical),
        "asset_score": asset_score,
        "metric_vector": metrics,
        "hard_gates": gates,
        "issues": ordered,
        "top_issues": ordered[:8],
        "issue_signature": [f"{issue.get('type')}:{issue.get('target') or ','.join(issue.get('objects', []))}" for issue in ordered],
        "validation_summary": _validation_summary(records, ordered, asset_score),
        "objects": [_record_summary(record) for record in records],
        "intent_manifest": manifest,
        "manifest_status": "inferred" if manifest.get("inferred") else "provided",
        "constraint_graph": constraint_graph,
        "algorithm_ledger": list(algorithm_ledger or []),
    }
    report["repair_plan"] = build_asset_repair_plan(report, manifest=manifest, constraint_graph=constraint_graph)
    report["repair_delta_prompt"] = safe_repair_delta_prompt(report["repair_plan"])
    return report


def _issue(
    issue_id: str,
    issue_type: str,
    severity: str,
    objects: list[str],
    box: AABB,
    evidence: dict[str, Any],
    suggested_fix: str,
    acceptance_tests: list[str],
    *,
    confidence: float = 0.75,
    source: str = "inferred",
    algorithm_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    return AssetIssue(
        issue_id=issue_id,
        type=issue_type,
        severity=severity,
        objects=tuple(objects),
        target=objects[0] if objects else "scene",
        location=box.center,
        local_bbox=(box.minimum, box.maximum),
        evidence=evidence,
        suggested_fix=suggested_fix,
        confidence=confidence,
        acceptance_tests=tuple(acceptance_tests),
        source=source,
        algorithm_ids=tuple(algorithm_ids),
    ).as_dict()


def _containment_issue(inner_name: str, outer_name: str, inner: AABB, outer: AABB) -> dict[str, Any]:
    return _issue(
        f"issue_containment_{_slug(inner_name)}_inside_{_slug(outer_name)}",
        "containment_risk",
        "high",
        [inner_name, outer_name],
        _combined_box(inner, outer),
        {"inner_volume": inner.volume, "outer_volume": outer.volume},
        "Move the contained part to its intended surface/contact point or expose it with a deliberate visible attachment.",
        ["Contained part is visible from planned review views.", "No part is fully buried inside another object."],
        confidence=0.76,
    )


def _aabb_from_any(item: Any) -> AABB:
    if isinstance(item, MeshSnapshot):
        return item.aabb
    if isinstance(item, AABB):
        return item
    if isinstance(item, dict):
        if "aabb_min" in item and "aabb_max" in item:
            return AABB(vector3(item.get("aabb_min")), vector3(item.get("aabb_max")))
        return aabb_from_points(record_bounds_points(item))
    minimum = getattr(item, "aabb_min", None)
    maximum = getattr(item, "aabb_max", None)
    if minimum is not None and maximum is not None:
        return AABB(vector3(minimum), vector3(maximum))
    return AABB((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))


def _combined_box(left: AABB, right: AABB) -> AABB:
    return AABB(
        tuple(min(left.minimum[i], right.minimum[i]) for i in range(3)),
        tuple(max(left.maximum[i], right.maximum[i]) for i in range(3)),
    )


def _center_inside(point: Iterable[float], box: AABB) -> bool:
    p = vector3(point)
    return all(box.minimum[i] <= p[i] <= box.maximum[i] for i in range(3))


def _has_support_below(index: int, boxes: list[AABB]) -> bool:
    target = boxes[index]
    for other_index, other in enumerate(boxes):
        if other_index == index:
            continue
        vertical_gap = target.minimum[2] - other.maximum[2]
        max_gap = max(target.diagonal * 0.12, DEFAULT_CONTACT_TOLERANCE * 4.0)
        if -DEFAULT_PENETRATION_TOLERANCE <= vertical_gap <= max_gap and _xy_overlap_ratio(target, other) > 0.05:
            return True
    return False


def _xy_overlap_ratio(left: AABB, right: AABB) -> float:
    x = max(min(left.maximum[0], right.maximum[0]) - max(left.minimum[0], right.minimum[0]), 0.0)
    y = max(min(left.maximum[1], right.maximum[1]) - max(left.minimum[1], right.minimum[1]), 0.0)
    overlap = x * y
    left_area = max((left.maximum[0] - left.minimum[0]) * (left.maximum[1] - left.minimum[1]), 1.0e-9)
    right_area = max((right.maximum[0] - right.minimum[0]) * (right.maximum[1] - right.minimum[1]), 1.0e-9)
    return overlap / min(left_area, right_area)


def _xy_area(box: AABB) -> float:
    return max((box.maximum[0] - box.minimum[0]) * (box.maximum[1] - box.minimum[1]), 0.0)


def _union_box(boxes: list[AABB]) -> AABB | None:
    if not boxes:
        return None
    return AABB(
        tuple(min(box.minimum[i] for box in boxes) for i in range(3)),
        tuple(max(box.maximum[i] for box in boxes) for i in range(3)),
    )


def _record_text(record: dict[str, Any]) -> str:
    parts = [str(record.get("name", "")), str(record.get("type", ""))]
    parts.extend(str(item) for item in record.get("material_names", []) or [])
    parts.extend(str(item) for item in record.get("collections", []) or [])
    return " ".join(parts).lower()


def _record_has_term(record: dict[str, Any], terms: set[str]) -> bool:
    text = _record_text(record)
    return any(term in text for term in terms)


def _record_has_any_name(records: list[dict[str, Any]], terms: set[str]) -> bool:
    return any(any(term in str(record.get("name", "")).lower() for term in terms) for record in records)


def _castle_prior_active(records: list[dict[str, Any]]) -> bool:
    text = " ".join(_record_text(record) for record in records)
    if any(term in text for term in _CASTLE_TERMS):
        return True
    wall_like = sum(1 for record in records if _record_has_term(record, {"wall", "stone", "block"}))
    tall_like = sum(1 for record in records if vector3(record.get("dimensions", (1, 1, 1)), default=(1, 1, 1))[2] > max(vector3(record.get("dimensions", (1, 1, 1)), default=(1, 1, 1))[:2]) * 1.4)
    return wall_like >= 3 and tall_like >= 2


def _looks_like_blockout_piece(record: dict[str, Any], box: AABB) -> bool:
    dims = sorted(max(value, 1.0e-9) for value in box.size)
    cube_ratio = dims[-1] / dims[0]
    low_poly = int(record.get("face_count", 0) or 0) <= 24 or int(record.get("vertex_count", 0) or 0) <= 16
    return cube_ratio <= 2.2 and low_poly


def _looks_like_duplicate_surface(left: AABB, right: AABB, tol: dict[str, float]) -> bool:
    if _xy_overlap_ratio(left, right) < 0.75:
        return False
    center_distance = _distance(left.center, right.center)
    near_center = center_distance <= max(tol["z_fighting"] * 8.0, min(left.diagonal, right.diagonal) * 0.015)
    thin_axis = min(min(left.size), min(right.size))
    near_thin = thin_axis <= max(tol["z_fighting"] * 4.0, min(left.diagonal, right.diagonal) * 0.01)
    return near_center or (near_thin and center_distance <= max(left.diagonal, right.diagonal) * 0.04)


def _effective_tolerance(scene_box: AABB, settings: dict[str, Any] | None) -> dict[str, float]:
    relative = float((settings or {}).get("relative_tolerance", DEFAULT_RELATIVE_TOLERANCE) or DEFAULT_RELATIVE_TOLERANCE)
    scaled = scene_box.diagonal * relative
    return {
        "contact": max(DEFAULT_CONTACT_TOLERANCE, scaled),
        "penetration": max(DEFAULT_PENETRATION_TOLERANCE, scaled),
        "clearance": max(DEFAULT_CLEARANCE_TOLERANCE, scaled),
        "z_fighting": max(DEFAULT_Z_FIGHTING_TOLERANCE, scaled * 0.25),
    }


def _triangle_area(a: Iterable[float], b: Iterable[float], c: Iterable[float]) -> float:
    ax, ay, az = vector3(a)
    bx, by, bz = vector3(b)
    cx, cy, cz = vector3(c)
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    return 0.5 * math.sqrt(max((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2 + (ux * vy - uy * vx) ** 2, 0.0))


def _signed_tetra_volume(a: Iterable[float], b: Iterable[float], c: Iterable[float]) -> float:
    ax, ay, az = vector3(a)
    bx, by, bz = vector3(b)
    cx, cy, cz = vector3(c)
    return (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6.0


def _distance(a: Iterable[float], b: Iterable[float]) -> float:
    aa = vector3(a)
    bb = vector3(b)
    return math.sqrt(sum((aa[i] - bb[i]) ** 2 for i in range(3)))


def _rounded_point(point: Iterable[float], *, places: int = 5) -> tuple[float, float, float]:
    return tuple(round(value, places) for value in vector3(point))


def _bbox_payload(value: tuple[tuple[float, float, float], tuple[float, float, float]] | None) -> list[list[float]]:
    if value is None:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return [[float(v) for v in vector3(value[0])], [float(v) for v in vector3(value[1])]]


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    box = _aabb_from_any(record)
    return {
        "name": str(record.get("name", "")),
        "type": str(record.get("type", "")),
        "aabb": {
            "minimum": list(box.minimum),
            "maximum": list(box.maximum),
            "center": list(box.center),
            "size": list(box.size),
        },
        "vertex_count": int(record.get("vertex_count", 0) or 0),
        "face_count": int(record.get("face_count", 0) or 0),
        "materials": [str(item) for item in record.get("material_names", []) or []],
        "collections": [str(item) for item in record.get("collections", []) or []],
    }


def _validation_summary(records: list[dict[str, Any]], issues: list[dict[str, Any]], asset_score: float) -> str:
    if not records:
        return "VERIFYING found no target geometry to validate."
    if not issues:
        return f"VERIFYING completed: {len(records)} object(s), no validation issues, score {asset_score:.1f}."
    top = ", ".join(str(issue.get("type", "")) for issue in issues[:4])
    return f"VERIFYING completed: {len(records)} object(s), {len(issues)} issue(s), score {asset_score:.1f}. Top: {top}."


def _record_check(ledger: AlgorithmLedger, check_id: str, label: str, issues: list[dict[str, Any]]) -> None:
    ledger.add(
        check_id,
        label,
        status="done",
        issue_count=len(issues),
        evidence_refs=[str(issue.get("issue_id", issue.get("defect_id", ""))) for issue in issues[:24]],
        objects=sorted({str(obj) for issue in issues for obj in issue.get("objects", []) or []})[:24],
    )


def _record_check_obj(rows: list[dict[str, Any]], check_id: str, label: str, issues: list[dict[str, Any]]) -> None:
    rows.append(
        {
            "id": check_id,
            "label": label,
            "status": "done",
            "duration_ms": 0.0,
            "inputs": {},
            "thresholds": {},
            "objects": sorted({str(obj) for issue in issues for obj in issue.get("objects", []) or []})[:24],
            "issue_count": len(issues),
            "evidence_refs": [str(issue.get("issue_id", issue.get("defect_id", ""))) for issue in issues[:24]],
            "error": "",
        }
    )


def _scene_intent_manifest(context: Any) -> dict[str, Any] | None:
    try:
        scene = getattr(context, "scene", None)
        for key in ("codex_asset_intent_manifest", "codex_blender_asset_intent_manifest", "codex_blender_asset_intent_manifest_json"):
            raw = scene.get(key) if scene is not None and hasattr(scene, "get") else None
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                return json.loads(raw)
    except Exception:
        return None
    return None


def _triangle_normal(a: Iterable[float], b: Iterable[float], c: Iterable[float]) -> tuple[float, float, float]:
    ax, ay, az = vector3(a)
    bx, by, bz = vector3(b)
    cx, cy, cz = vector3(c)
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(max(nx * nx + ny * ny + nz * nz, 1.0e-18))
    return (nx / length, ny / length, nz / length)


def _mesh_hash(verts: list[tuple[float, float, float]], tris: list[tuple[int, int, int]]) -> str:
    hasher = hashlib.sha1()
    for point in verts[:8192]:
        hasher.update(("{:.6f},{:.6f},{:.6f};".format(*point)).encode("ascii"))
    for tri in tris[:8192]:
        hasher.update((f"{tri[0]},{tri[1]},{tri[2]};").encode("ascii"))
    hasher.update(str((len(verts), len(tris))).encode("ascii"))
    return hasher.hexdigest()[:16]


def _connected_component_count(edge_counts: dict[tuple[int, int], int]) -> int:
    adjacency: dict[int, set[int]] = {}
    for a, b in edge_counts:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    unseen = set(adjacency)
    count = 0
    while unseen:
        count += 1
        stack = [unseen.pop()]
        while stack:
            node = stack.pop()
            for neighbor in adjacency.get(node, set()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
    return max(count, 1)


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for issue in issues:
        issue_id = str(issue.get("issue_id", issue.get("defect_id", "")))
        if not issue_id or issue_id in seen:
            continue
        seen.add(issue_id)
        output.append(issue)
    return output


def _normalize_severity(value: str) -> str:
    severity = (value or "low").strip().lower()
    return severity if severity in ISSUE_SEVERITY_WEIGHTS else "low"


def _slug(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in (value or "").strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "object"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
