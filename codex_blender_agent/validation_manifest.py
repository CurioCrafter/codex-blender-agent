from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from .visual_geometry import AABB, aabb_from_points, clamp, record_bounds_points, scene_aabb, vector3


MANIFEST_SCHEMA_VERSION = "0.15.0"

ROLE_TERMS = {
    "support": {"base", "floor", "ground", "seat", "table", "wall", "keep", "tower", "roof", "platform", "foundation", "leg", "pillar", "post", "column"},
    "water_zone": {"moat", "water", "river", "lake", "pond", "trench"},
    "vegetation": {"tree", "oak", "pine", "shrub", "bush", "grass", "vegetation"},
    "detail": {"bolt", "screw", "handle", "button", "trim", "crenel", "merlon", "battlement", "hinge"},
    "opening": {"door", "gate", "window", "arch", "portcullis"},
}


@dataclass(frozen=True)
class AssetConstraint:
    constraint_id: str
    type: str
    source: str
    objects: tuple[str, ...] = ()
    target: str = ""
    role: str = ""
    tolerance: float | None = None
    axis: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "type": self.type,
            "source": self.source,
            "objects": list(self.objects),
            "target": self.target,
            "role": self.role,
            "tolerance": self.tolerance,
            "axis": self.axis,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class AssetIntentManifest:
    data: dict[str, Any]

    @classmethod
    def from_any(
        cls,
        payload: Any,
        *,
        records: Iterable[dict[str, Any]] | None = None,
        prompt: str = "",
    ) -> "AssetIntentManifest":
        return cls(normalize_asset_intent_manifest(payload, records=records, prompt=prompt))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def objects(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.data.get("objects", []) or [])

    @property
    def object_names(self) -> tuple[str, ...]:
        return tuple(
            str(item.get("name", "")).strip()
            for item in self.objects
            if str(item.get("name", "")).strip()
        )


def normalize_asset_intent_manifest(
    manifest: dict[str, Any] | None,
    *,
    records: Iterable[dict[str, Any]] | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    """Return a stable, JSON-safe intent manifest.

    The validator works without this manifest, but when GPT or a user supplies
    one it becomes the authoritative source for contact/clearance/alignment
    intent. Missing sections are filled from geometry/name inference.
    """

    records_list = [dict(record) for record in (records or [])]
    raw = dict(manifest or {})
    inferred = bool(raw.get("inferred")) if "inferred" in raw else not bool(raw)
    objects = _normalize_objects(raw.get("objects"), records_list)
    constraints = _normalize_constraints(raw.get("constraints"), objects)
    allowed = _normalize_pair_list(raw.get("allowed_intersections") or raw.get("allowed_contacts"))
    forbidden = raw.get("forbidden_intersections", "all_other_pairs")
    required_contacts = _normalize_required_contacts(raw.get("required_contacts") or raw.get("must_touch"), objects)
    clearance_targets = _normalize_clearances(raw.get("clearance_targets") or raw.get("clearance_rules"))
    inferred_constraints = infer_constraints(records_list, known_constraints=constraints, required_contacts=required_contacts)
    payload = {
        "schema_version": str(raw.get("schema_version") or MANIFEST_SCHEMA_VERSION),
        "manifest_id": str(raw.get("manifest_id") or f"asset-intent-{uuid.uuid4().hex[:10]}"),
        "created_at": str(raw.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        "asset_name": str(raw.get("asset_name") or raw.get("name") or _asset_name_from_prompt(prompt) or "Generated Asset"),
        "unit": str(raw.get("unit") or raw.get("units") or "meters"),
        "source": str(raw.get("source") or ("inferred" if inferred else "gpt_intent")),
        "inferred": inferred,
        "prompt": str(raw.get("prompt") or prompt or ""),
        "objects": objects,
        "constraints": [constraint.as_dict() for constraint in constraints],
        "inferred_constraints": [constraint.as_dict() for constraint in inferred_constraints],
        "allowed_intersections": allowed,
        "forbidden_intersections": forbidden,
        "required_contacts": required_contacts,
        "clearance_targets": clearance_targets,
        "symmetry_groups": _json_safe(raw.get("symmetry_groups") or []),
        "expected_dimensions": _json_safe(raw.get("expected_dimensions") or {}),
        "origin_pivot_rules": _json_safe(raw.get("origin_pivot_rules") or raw.get("pivots") or []),
        "repair_policy": _normalize_repair_policy(raw.get("repair_policy")),
    }
    payload["constraint_graph"] = build_constraint_graph(records_list, payload)
    return payload


def parse_asset_intent_manifest(
    manifest: dict[str, Any] | str | None,
    *,
    records: Iterable[dict[str, Any]] | None = None,
    prompt: str = "",
) -> AssetIntentManifest:
    return AssetIntentManifest.from_any(manifest, records=records, prompt=prompt)


def infer_asset_intent_manifest(
    records: Iterable[dict[str, Any]] | None,
    *,
    prompt: str = "",
) -> AssetIntentManifest:
    return AssetIntentManifest.from_any({}, records=records, prompt=prompt)


def build_constraint_graph(records: Iterable[dict[str, Any]], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    records_list = [dict(record) for record in records]
    manifest = dict(manifest or {})
    nodes = []
    for record in records_list:
        name = str(record.get("name", "") or "object")
        box = _aabb_from_record(record)
        nodes.append(
            {
                "id": name,
                "label": name,
                "role": _role_for_record(record, manifest),
                "aabb": {"minimum": list(box.minimum), "maximum": list(box.maximum), "center": list(box.center), "size": list(box.size)},
                "source": "manifest" if _manifest_object(manifest, name) else "inferred",
            }
        )
    edges: list[dict[str, Any]] = []
    for constraint in manifest.get("constraints", []) or []:
        if isinstance(constraint, dict):
            objects = [str(item) for item in constraint.get("objects", []) or []]
            target = str(constraint.get("target", "") or "")
            if len(objects) >= 2:
                edges.append(_edge(objects[0], objects[1], str(constraint.get("type", "constraint")), "manifest", constraint))
            elif objects and target:
                edges.append(_edge(objects[0], target, str(constraint.get("type", "constraint")), "manifest", constraint))
    for contact in manifest.get("required_contacts", []) or []:
        if isinstance(contact, dict):
            source = str(contact.get("object", "") or "")
            targets = [str(item) for item in contact.get("targets", []) or contact.get("must_touch", []) or []]
            for target in targets:
                edges.append(_edge(source, target, "required_contact", "manifest", contact))
    for constraint in manifest.get("inferred_constraints", []) or []:
        if isinstance(constraint, dict):
            objects = [str(item) for item in constraint.get("objects", []) or []]
            if len(objects) >= 2:
                edges.append(_edge(objects[0], objects[1], str(constraint.get("type", "inferred_relation")), "inferred", constraint))
    deduped_edges = _dedupe_edges(edges)
    summary = {
        "node_count": len(nodes),
        "edge_count": len(deduped_edges),
        "relation_types": _count_by(deduped_edges, "type"),
        "source_kinds": _count_by(deduped_edges, "source_kind"),
    }
    return {
        "nodes": nodes,
        "edges": deduped_edges,
        "summary": summary,
        "node_count": summary["node_count"],
        "edge_count": summary["edge_count"],
        "relation_types": summary["relation_types"],
        "source_kinds": summary["source_kinds"],
    }


def infer_constraints(
    records: Iterable[dict[str, Any]],
    *,
    known_constraints: Iterable[AssetConstraint] | None = None,
    required_contacts: Iterable[dict[str, Any]] | None = None,
) -> list[AssetConstraint]:
    records_list = [dict(record) for record in records]
    if not records_list:
        return []
    boxes = [_aabb_from_record(record) for record in records_list]
    constraints: list[AssetConstraint] = []
    known_pairs = {
        tuple(sorted(constraint.objects[:2]))
        for constraint in (known_constraints or [])
        if len(constraint.objects) >= 2
    }
    known_pairs.update(
        tuple(sorted((str(contact.get("object", "")), str(target))))
        for contact in (required_contacts or [])
        if isinstance(contact, dict)
        for target in contact.get("targets", []) or []
    )
    for index, record in enumerate(records_list):
        name = str(record.get("name", f"object_{index}") or f"object_{index}")
        role = _role_from_text(_record_text(record))
        if role:
            constraints.append(
                AssetConstraint(
                    constraint_id=f"inferred_role_{_slug(name)}",
                    type="role_hint",
                    source="inferred",
                    objects=(name,),
                    role=role,
                    metadata={"text": _record_text(record)},
                )
            )
    for i in range(len(records_list)):
        for j in range(i + 1, len(records_list)):
            left = boxes[i]
            right = boxes[j]
            left_name = str(records_list[i].get("name", f"object_{i}") or f"object_{i}")
            right_name = str(records_list[j].get("name", f"object_{j}") or f"object_{j}")
            if tuple(sorted((left_name, right_name))) in known_pairs:
                continue
            xy_ratio = _xy_overlap_ratio(left, right)
            gap_lr = left.minimum[2] - right.maximum[2]
            gap_rl = right.minimum[2] - left.maximum[2]
            support_gap = max(min(left.diagonal, right.diagonal) * 0.08, 0.01)
            support_gap_limit_lr = max(support_gap, min(left.size[2], right.size[2]) * 0.5, 0.05)
            support_gap_limit_rl = max(support_gap, min(left.size[2], right.size[2]) * 0.5, 0.05)
            if xy_ratio > 0.05 and -support_gap <= gap_lr <= support_gap_limit_lr:
                support, child = _choose_support_candidate(
                    support_name=right_name,
                    support_box=right,
                    child_name=left_name,
                    child_box=left,
                    support_gap=support_gap,
                )
                if support:
                    constraints.append(_support_constraint(child, support, xy_ratio, gap_lr))
            elif xy_ratio > 0.05 and -support_gap <= gap_rl <= support_gap_limit_rl:
                support, child = _choose_support_candidate(
                    support_name=left_name,
                    support_box=left,
                    child_name=right_name,
                    child_box=right,
                    support_gap=support_gap,
                )
                if support:
                    constraints.append(_support_constraint(child, support, xy_ratio, gap_rl))
            if _is_zone_exclusion(left_name, right_name, _role_from_text(_record_text(records_list[i])), _role_from_text(_record_text(records_list[j]))):
                if _is_vegetation_name(left_name) and _is_zone_name(right_name):
                    constraints.append(
                        AssetConstraint(
                            constraint_id=f"inferred_zone_exclusion_{_slug(left_name)}_{_slug(right_name)}",
                            type="zone_exclusion",
                            source="inferred",
                            objects=(left_name, right_name),
                            metadata={"xy_overlap_ratio": xy_ratio, "reason": "vegetation inside moat/water zone"},
                        )
                    )
                elif _is_zone_name(left_name) and _is_vegetation_name(right_name):
                    constraints.append(
                        AssetConstraint(
                            constraint_id=f"inferred_zone_exclusion_{_slug(right_name)}_{_slug(left_name)}",
                            type="zone_exclusion",
                            source="inferred",
                            objects=(right_name, left_name),
                            metadata={"xy_overlap_ratio": xy_ratio, "reason": "vegetation inside moat/water zone"},
                        )
                    )
            elif _center_distance(left, right) <= max(left.diagonal, right.diagonal) * 0.08 and min(left.volume, right.volume) < max(left.volume, right.volume) * 0.35:
                constraints.append(
                    AssetConstraint(
                        constraint_id=f"inferred_centered_{_slug(left_name)}_{_slug(right_name)}",
                        type="centered_near",
                        source="inferred",
                        objects=(left_name, right_name),
                        metadata={"center_distance": _center_distance(left, right)},
                    )
                )
    return constraints


def manifest_allows_pair(manifest: dict[str, Any] | None, left: str, right: str) -> bool:
    if not manifest:
        return False
    pair = {left, right}
    for item in manifest.get("allowed_intersections", []) or []:
        if isinstance(item, (list, tuple)) and set(str(v) for v in item[:2]) == pair:
            return True
        if isinstance(item, dict) and {str(item.get("object", "")), str(item.get("target", ""))} == pair:
            return True
    return False


def manifest_required_contact_targets(manifest: dict[str, Any] | None, object_name: str) -> list[str]:
    if not manifest:
        return []
    targets: list[str] = []
    for item in manifest.get("required_contacts", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("object", "")) == object_name:
            targets.extend(str(target) for target in item.get("targets", []) or [])
    return [target for target in targets if target]


def _normalize_objects(raw: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        output = []
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("id") or f"object_{index}")
                output.append({**_json_safe(item), "name": name})
        if output:
            return output
    return [
        {
            "name": str(record.get("name", f"object_{index}") or f"object_{index}"),
            "role": _role_from_text(_record_text(record)) or "unknown",
            "source": "inferred",
        }
        for index, record in enumerate(records)
    ]


def _normalize_constraints(raw: Any, objects: list[dict[str, Any]]) -> list[AssetConstraint]:
    output: list[AssetConstraint] = []
    if not isinstance(raw, list):
        return output
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        constraint_type = str(item.get("type") or "constraint")
        names = [str(value) for value in item.get("objects", []) or [] if str(value)]
        if not names and item.get("object"):
            names = [str(item.get("object"))]
        output.append(
            AssetConstraint(
                constraint_id=str(item.get("constraint_id") or item.get("id") or f"manifest_constraint_{index:03d}"),
                type=constraint_type,
                source="manifest",
                objects=tuple(names),
                target=str(item.get("target", "") or item.get("supported_by", "") or ""),
                tolerance=_float_or_none(item.get("tolerance", item.get("clearance", None))),
                axis=str(item.get("axis", "") or item.get("local_axis", "") or ""),
                metadata={key: value for key, value in item.items() if key not in {"constraint_id", "id", "type", "objects", "object", "target", "tolerance", "clearance", "axis", "local_axis"}},
            )
        )
    return output


def _normalize_pair_list(raw: Any) -> list[Any]:
    if isinstance(raw, str) and raw in {"all", "all_pairs", "all_other_pairs"}:
        return raw
    if not isinstance(raw, list):
        return []
    output = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            output.append([str(item[0]), str(item[1])])
        elif isinstance(item, dict):
            output.append(_json_safe(item))
    return output


def _normalize_required_contacts(raw: Any, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output = []
    for item in raw:
        if isinstance(item, dict):
            source = str(item.get("object", "") or item.get("source", "") or "")
            targets = [str(value) for value in item.get("targets", []) or item.get("must_touch", []) or [] if str(value)]
            if source and targets:
                output.append({"object": source, "targets": targets, "tolerance": _float_or_none(item.get("tolerance"))})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            output.append({"object": str(item[0]), "targets": [str(item[1])], "tolerance": None})
    return output


def _normalize_clearances(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            output.append(
                {
                    "clearance_id": str(item.get("clearance_id") or item.get("id") or f"clearance_{index:03d}"),
                    "object": str(item.get("object", "") or ""),
                    "target": str(item.get("target", "") or ""),
                    "min_gap": _float_or_none(item.get("min_gap", item.get("minimum", None))),
                    "max_gap": _float_or_none(item.get("max_gap", item.get("maximum", None))),
                    "source": "manifest",
                }
            )
    return output


def _normalize_repair_policy(raw: Any) -> dict[str, Any]:
    policy = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "allow_safe_transforms": bool(policy.get("allow_safe_transforms", True)),
        "allow_local_cleanup": bool(policy.get("allow_local_cleanup", False)),
        "allow_destructive_mesh_ops": bool(policy.get("allow_destructive_mesh_ops", False)),
        "destructive_requires_approval": bool(policy.get("destructive_requires_approval", True)),
    }


def _support_constraint(child: str, support: str, xy_ratio: float, gap: float) -> AssetConstraint:
    return AssetConstraint(
        constraint_id=f"inferred_support_{_slug(child)}_on_{_slug(support)}",
        type="support_contact",
        source="inferred",
        objects=(support, child),
        metadata={"xy_overlap_ratio": xy_ratio, "vertical_gap": gap, "support": support, "child": child},
    )


def _support_likeness(name: str, box: AABB, text: str) -> float:
    score = 0.0
    lowered_name = name.lower()
    lowered_text = text.lower()
    if any(term in lowered_name for term in ROLE_TERMS["support"]):
        score += 2.0
    if any(term in lowered_text for term in ROLE_TERMS["support"]):
        score += 1.5
    flatness = 0.0
    if box.diagonal > 0:
        sorted_dims = sorted((abs(box.size[0]), abs(box.size[1]), abs(box.size[2])))
        flatness = 1.0 - clamp(sorted_dims[0] / max(sorted_dims[-1], 1.0e-9), 0.0, 1.0)
    score += flatness
    return score


def _choose_support_candidate(
    *,
    support_name: str,
    support_box: AABB,
    child_name: str,
    child_box: AABB,
    support_gap: float,
) -> tuple[str, str]:
    support_score = _support_likeness(support_name, support_box, _slug(support_name))
    child_score = _support_likeness(child_name, child_box, _slug(child_name))
    if _is_zone_name(support_name) or _is_zone_name(child_name) or _is_vegetation_name(support_name) or _is_vegetation_name(child_name):
        return "", ""
    if support_score <= 0.0 and child_score <= 0.0:
        return "", ""
    if support_score >= child_score:
        return support_name, child_name
    if child_score > support_score:
        return child_name, support_name
    return "", ""


def _manifest_object(manifest: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in manifest.get("objects", []) or []:
        if isinstance(item, dict) and str(item.get("name", "")) == name:
            return item
    return None


def _role_for_record(record: dict[str, Any], manifest: dict[str, Any]) -> str:
    item = _manifest_object(manifest, str(record.get("name", "")))
    if item and item.get("role"):
        return str(item.get("role"))
    return _role_from_text(_record_text(record)) or "unknown"


def _role_from_text(text: str) -> str:
    text = text.lower()
    for role, terms in ROLE_TERMS.items():
        if any(term in text for term in terms):
            return role
    return ""


def _record_text(record: dict[str, Any]) -> str:
    parts = [str(record.get("name", "")), str(record.get("type", ""))]
    parts.extend(str(item) for item in record.get("material_names", []) or [])
    parts.extend(str(item) for item in record.get("collections", []) or [])
    return " ".join(parts).lower()


def _aabb_from_record(record: dict[str, Any]) -> AABB:
    if record.get("bounds"):
        return aabb_from_points(record_bounds_points(record))
    location = vector3(record.get("location", (0, 0, 0)))
    dimensions = vector3(record.get("dimensions", (1, 1, 1)), default=(1, 1, 1))
    half = tuple(max(abs(dimensions[index]), 0.001) / 2.0 for index in range(3))
    return AABB(tuple(location[index] - half[index] for index in range(3)), tuple(location[index] + half[index] for index in range(3)))


def _xy_overlap_ratio(left: AABB, right: AABB) -> float:
    x = max(min(left.maximum[0], right.maximum[0]) - max(left.minimum[0], right.minimum[0]), 0.0)
    y = max(min(left.maximum[1], right.maximum[1]) - max(left.minimum[1], right.minimum[1]), 0.0)
    overlap = x * y
    left_area = max((left.maximum[0] - left.minimum[0]) * (left.maximum[1] - left.minimum[1]), 1.0e-9)
    right_area = max((right.maximum[0] - right.minimum[0]) * (right.maximum[1] - right.minimum[1]), 1.0e-9)
    return overlap / min(left_area, right_area)


def _center_distance(left: AABB, right: AABB) -> float:
    return sum((left.center[index] - right.center[index]) ** 2 for index in range(3)) ** 0.5


def _edge(source: str, target: str, relation: str, source_kind: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{relation}:{source}->{target}",
        "source": source,
        "target": target,
        "relation": relation,
        "constraint_source": source_kind,
        "confidence": 0.95 if source_kind == "manifest" else 0.65,
        "evidence": _json_safe(evidence),
    }


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for edge in edges:
        key = str(edge.get("id", ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(edge)
    return output


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "")).strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda row: row[0]))


def _asset_name_from_prompt(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return ""
    words = [word.strip(".,:;!?") for word in prompt.split()[:8]]
    return " ".join(words)[:80]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _slug(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in (value or "").strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "object"


def _is_zone_name(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ROLE_TERMS["water_zone"])


def _is_vegetation_name(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ROLE_TERMS["vegetation"])


def _is_zone_exclusion(left_name: str, right_name: str, left_role: str, right_role: str) -> bool:
    return (left_role == "vegetation" and right_role == "water_zone") or (left_role == "water_zone" and right_role == "vegetation") or (_is_vegetation_name(left_name) and _is_zone_name(right_name)) or (_is_zone_name(left_name) and _is_vegetation_name(right_name))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
