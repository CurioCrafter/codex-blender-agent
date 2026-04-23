from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_GEOMETRY_REVIEW_ENABLED = True
DEFAULT_CANDIDATE_VIEW_COUNT = 48
DEFAULT_SELECTED_CAPTURE_COUNT = 8
DEFAULT_AUDIT_VIEW_COUNT = 3
DEFAULT_MESH_SAMPLES_PER_OBJECT = 256
DEFAULT_MINIMUM_COVERAGE_SCORE = 0.65
DEFAULT_GEOMETRY_SCORE_WEIGHT = 0.80
DEFAULT_CRITIC_SCORE_WEIGHT = 0.20
DEFAULT_CAMERA_FIT_MARGIN = 1.08
DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES = 20.0
DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES = 30.0

GEOMETRY_FLOOR = 0.72
COVERAGE_FLOOR = 0.65
FRAMING_FLOOR = 0.60
DEFECT_FLOOR = 0.70
SEMANTIC_ANCHOR_FLOOR = 0.74
_EPS = 1.0e-9


@dataclass(frozen=True)
class AABB:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @property
    def center(self) -> tuple[float, float, float]:
        return tuple((self.minimum[i] + self.maximum[i]) * 0.5 for i in range(3))

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(max(self.maximum[i] - self.minimum[i], 0.0) for i in range(3))

    @property
    def diagonal(self) -> float:
        return max(length(self.size), _EPS)

    @property
    def radius(self) -> float:
        return max(self.diagonal * 0.5, _EPS)

    @property
    def volume(self) -> float:
        x, y, z = self.size
        return max(x * y * z, 0.0)

    @property
    def corners(self) -> list[tuple[float, float, float]]:
        mn = self.minimum
        mx = self.maximum
        return [(x, y, z) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]


def vector3(value: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        if isinstance(value, dict):
            return (float(value.get("x", default[0])), float(value.get("y", default[1])), float(value.get("z", default[2])))
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return (float(value[0]), float(value[1]), float(value[2]))
        if hasattr(value, "__iter__"):
            items = list(value)
            if len(items) >= 3:
                return (float(items[0]), float(items[1]), float(items[2]))
    except (TypeError, ValueError):
        return default
    return default


def v_add(a: Iterable[float], b: Iterable[float]) -> tuple[float, float, float]:
    aa = tuple(a)
    bb = tuple(b)
    return (float(aa[0]) + float(bb[0]), float(aa[1]) + float(bb[1]), float(aa[2]) + float(bb[2]))


def v_sub(a: Iterable[float], b: Iterable[float]) -> tuple[float, float, float]:
    aa = tuple(a)
    bb = tuple(b)
    return (float(aa[0]) - float(bb[0]), float(aa[1]) - float(bb[1]), float(aa[2]) - float(bb[2]))


def v_mul(a: Iterable[float], scalar: float) -> tuple[float, float, float]:
    aa = tuple(a)
    return (float(aa[0]) * scalar, float(aa[1]) * scalar, float(aa[2]) * scalar)


def dot(a: Iterable[float], b: Iterable[float]) -> float:
    aa = tuple(a)
    bb = tuple(b)
    return float(aa[0]) * float(bb[0]) + float(aa[1]) * float(bb[1]) + float(aa[2]) * float(bb[2])


def cross(a: Iterable[float], b: Iterable[float]) -> tuple[float, float, float]:
    aa = tuple(a)
    bb = tuple(b)
    return (
        float(aa[1]) * float(bb[2]) - float(aa[2]) * float(bb[1]),
        float(aa[2]) * float(bb[0]) - float(aa[0]) * float(bb[2]),
        float(aa[0]) * float(bb[1]) - float(aa[1]) * float(bb[0]),
    )


def length(a: Iterable[float]) -> float:
    return math.sqrt(max(dot(a, a), 0.0))


def normalize(a: Iterable[float], fallback: tuple[float, float, float] = (1.0, 0.0, 0.0)) -> tuple[float, float, float]:
    aa = tuple(float(v) for v in a)
    norm = length(aa)
    if norm <= _EPS:
        return fallback
    return (aa[0] / norm, aa[1] / norm, aa[2] / norm)


def clamp(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(min(number, maximum), minimum)


def normalized_score(value: float, low: float, high: float) -> float:
    if abs(high - low) <= _EPS:
        return 0.0
    return clamp((value - low) / (high - low), 0.0, 1.0)


def angle_degrees(a: Iterable[float], b: Iterable[float]) -> float:
    aa = normalize(a)
    bb = normalize(b)
    return math.degrees(math.acos(clamp(dot(aa, bb), -1.0, 1.0)))


def record_bounds_points(record: dict[str, Any]) -> list[tuple[float, float, float]]:
    bounds = record.get("bounds")
    if isinstance(bounds, list) and bounds:
        return [vector3(item) for item in bounds]
    location = vector3(record.get("location", (0.0, 0.0, 0.0)))
    dimensions = vector3(record.get("dimensions", (1.0, 1.0, 1.0)), default=(1.0, 1.0, 1.0))
    half = tuple(max(abs(v), 0.001) * 0.5 for v in dimensions)
    return [
        (location[0] + sx * half[0], location[1] + sy * half[1], location[2] + sz * half[2])
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
    ]


def aabb_from_points(points: Iterable[Iterable[float]], fallback: AABB | None = None) -> AABB:
    values = [vector3(point) for point in points]
    if not values:
        return fallback or AABB((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    return AABB(
        tuple(min(point[i] for point in values) for i in range(3)),
        tuple(max(point[i] for point in values) for i in range(3)),
    )


def scene_aabb(records: Iterable[dict[str, Any]]) -> AABB | None:
    points: list[tuple[float, float, float]] = []
    for record in records:
        points.extend(record_bounds_points(record))
    if not points:
        return None
    return aabb_from_points(points)


def footprint_frame(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    points: list[tuple[float, float, float]] = []
    for record in records:
        points.extend(record_bounds_points(record))
    if not points:
        return {
            "center": [0.0, 0.0, 0.0],
            "axis_x": [1.0, 0.0, 0.0],
            "axis_y": [0.0, 1.0, 0.0],
            "axis_z": [0.0, 0.0, 1.0],
            "eigenvalues": [0.0, 0.0],
            "stable": False,
        }
    center = tuple(sum(point[i] for point in points) / len(points) for i in range(3))
    xx = yy = xy = 0.0
    for point in points:
        dx = point[0] - center[0]
        dy = point[1] - center[1]
        xx += dx * dx
        yy += dy * dy
        xy += dx * dy
    xx /= len(points)
    yy /= len(points)
    xy /= len(points)
    trace = xx + yy
    det = xx * yy - xy * xy
    term = math.sqrt(max(trace * trace * 0.25 - det, 0.0))
    lambda1 = trace * 0.5 + term
    lambda2 = trace * 0.5 - term
    if abs(xy) > _EPS or abs(lambda1 - xx) > _EPS:
        axis_x = normalize((xy, lambda1 - xx, 0.0), fallback=(1.0, 0.0, 0.0))
    else:
        axis_x = (1.0, 0.0, 0.0) if xx >= yy else (0.0, 1.0, 0.0)
    if abs(axis_x[0]) >= abs(axis_x[1]):
        axis_x = v_mul(axis_x, -1.0) if axis_x[0] < 0 else axis_x
    else:
        axis_x = v_mul(axis_x, -1.0) if axis_x[1] < 0 else axis_x
    axis_z = (0.0, 0.0, 1.0)
    axis_y = normalize(cross(axis_z, axis_x), fallback=(0.0, 1.0, 0.0))
    stable = lambda1 > _EPS and abs(lambda1 - lambda2) / max(lambda1, _EPS) >= 0.08
    return {
        "center": [float(v) for v in center],
        "axis_x": [float(v) for v in axis_x],
        "axis_y": [float(v) for v in axis_y],
        "axis_z": [0.0, 0.0, 1.0],
        "eigenvalues": [float(lambda1), float(lambda2)],
        "stable": bool(stable),
    }


def object_cage(record: dict[str, Any], *, scene: AABB | None = None, index: int = 0) -> dict[str, Any]:
    bounds = aabb_from_points(record_bounds_points(record))
    dimensions = bounds.size
    diagonal = bounds.diagonal
    scene_diag = scene.diagonal if scene else diagonal
    name = str(record.get("name", "") or f"part_{index}")
    materials = [str(item) for item in record.get("material_names", []) or [] if str(item).strip()]
    return {
        "cage_id": f"cage_{_slug(name)}_{index:02d}",
        "part_id": f"part_{_slug(name)}_{index:02d}",
        "object_name": name,
        "source_type": str(record.get("type", "")),
        "center_world": [float(v) for v in bounds.center],
        "aabb_world": [[float(v) for v in bounds.minimum], [float(v) for v in bounds.maximum]],
        "corners_world": [[float(v) for v in point] for point in bounds.corners],
        "obb_center_world": [float(v) for v in bounds.center],
        "obb_extents": [float(v) * 0.5 for v in dimensions],
        "radius": float(bounds.radius),
        "diagonal": float(diagonal),
        "scene_scale_ratio": float(diagonal / max(scene_diag, _EPS)),
        "geometry": {
            "vertex_count": int(record.get("vertex_count", 0) or 0),
            "face_count": int(record.get("face_count", record.get("polygon_count", 0)) or 0),
            "material_slot_count": int(record.get("material_slot_count", len(materials)) or 0),
        },
        "materials": materials,
        "collections": [str(item) for item in record.get("collections", []) or []],
        "text_summary": _cage_summary(name, dimensions, materials),
    }


def build_part_cages(records: Iterable[dict[str, Any]], scene: AABB | None = None) -> list[dict[str, Any]]:
    records_list = list(records)
    scene_box = scene or scene_aabb(records_list)
    return [object_cage(record, scene=scene_box, index=i) for i, record in enumerate(records_list, start=1)]


def detect_generic_defects(
    records: Iterable[dict[str, Any]],
    *,
    coverage_by_part: dict[str, float] | None = None,
    scene: AABB | None = None,
) -> list[dict[str, Any]]:
    records_list = [dict(record) for record in records]
    scene_box = scene or scene_aabb(records_list)
    if scene_box is None:
        return [
            _defect(
                "defect_no_target_geometry",
                "no_target_geometry",
                "scene",
                "high",
                1.0,
                {"reason": "No visible target mesh/object bounds were available."},
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                "Create or select visible game-asset geometry before running visual self-review.",
                ["At least one visible non-camera object exists.", "Scene bounds are non-degenerate."],
            )
        ]

    cages = build_part_cages(records_list, scene_box)
    defects: list[dict[str, Any]] = []
    diagonals = [max(float(cage.get("diagonal", 0.0)), _EPS) for cage in cages]
    median_diag = _median(diagonals) or scene_box.diagonal
    scene_diag = scene_box.diagonal
    min_scene_z = scene_box.minimum[2]

    for cage in cages:
        bbox = cage["aabb_world"]
        minimum = vector3(bbox[0])
        maximum = vector3(bbox[1])
        diag = float(cage.get("diagonal", 0.0) or 0.0)
        ratio = diag / max(median_diag, _EPS)
        name = str(cage.get("object_name", cage.get("part_id", "")))
        target = str(cage.get("part_id", name))

        if ratio > 5.0 and len(cages) >= 3:
            defects.append(
                _defect(
                    f"defect_scale_outlier_large_{_slug(name)}",
                    "scale_outlier",
                    target,
                    "medium",
                    min(1.0, ratio / 8.0),
                    {"object": name, "diagonal": diag, "median_diagonal": median_diag, "ratio": ratio},
                    bbox,
                    "Check whether this part should be the scene anchor. If not, resize or isolate it before review.",
                    ["Part scale ratio is within expected scene range.", "No required small parts are hidden by the large outlier."],
                )
            )
        if ratio < 0.08 and len(cages) >= 2:
            defects.append(
                _defect(
                    f"defect_tiny_detail_{_slug(name)}",
                    "tiny_detail_missed",
                    target,
                    "low",
                    min(1.0, 0.08 / max(ratio, _EPS)),
                    {"object": name, "diagonal": diag, "median_diagonal": median_diag, "ratio": ratio},
                    bbox,
                    "Schedule a close detail review view or enlarge this feature if it is gameplay-critical.",
                    ["Tiny part has a dedicated close-up or is marked secondary.", "Projected detail size clears the review threshold."],
                )
            )

        ground_gap = minimum[2] - min_scene_z
        if ground_gap > max(scene_diag * 0.10, median_diag * 0.50, 0.25) and diag < scene_diag * 0.60:
            defects.append(
                _defect(
                    f"defect_floating_part_{_slug(name)}",
                    "floating_part",
                    target,
                    "medium",
                    min(1.0, ground_gap / max(scene_diag * 0.25, _EPS)),
                    {"object": name, "ground_gap": ground_gap, "scene_min_z": min_scene_z},
                    bbox,
                    "Attach this part to the nearest intended support, or mark it as intentionally suspended before accepting the pass.",
                    ["Part either contacts a support surface or is explicitly intentional.", "No new intersections are introduced."],
                )
            )

        material_slot_count = int(cage.get("geometry", {}).get("material_slot_count", 0) or 0)
        material_names = list(cage.get("materials", []) or [])
        if material_slot_count > 0 and not material_names:
            defects.append(
                _defect(
                    f"defect_material_slots_{_slug(name)}",
                    "inconsistent_material_slots",
                    target,
                    "low",
                    0.65,
                    {"object": name, "material_slot_count": material_slot_count, "material_names": material_names},
                    bbox,
                    "Assign clear realtime materials or remove empty material slots before asset promotion.",
                    ["Material slots have named materials.", "No visible part relies on an empty material slot."],
                )
            )

        size = v_sub(maximum, minimum)
        sorted_size = sorted(size)
        if sorted_size[-1] > _EPS and sorted_size[0] / sorted_size[-1] < 0.025 and diag > median_diag * 0.25:
            defects.append(
                _defect(
                    f"defect_weak_silhouette_{_slug(name)}",
                    "weak_silhouette",
                    target,
                    "low",
                    0.6,
                    {"object": name, "dimensions": list(size), "thinness": sorted_size[0] / max(sorted_size[-1], _EPS)},
                    bbox,
                    "Add a more oblique audit view or give this thin part enough thickness to read from gameplay cameras.",
                    ["Thin part is readable in at least one oblique view.", "No important side is only edge-on."],
                )
            )

    for index, left in enumerate(cages):
        left_box = _aabb_from_cage(left)
        for right in cages[index + 1 :]:
            right_box = _aabb_from_cage(right)
            overlap = aabb_overlap(left_box, right_box)
            if overlap <= _EPS:
                continue
            ratio = overlap / max(min(left_box.volume, right_box.volume), _EPS)
            if ratio >= 0.65:
                left_name = str(left.get("object_name", left.get("part_id", "")))
                right_name = str(right.get("object_name", right.get("part_id", "")))
                defects.append(
                    _defect(
                        f"defect_excessive_overlap_{_slug(left_name)}_{_slug(right_name)}",
                        "excessive_overlap",
                        f"{left.get('part_id')} + {right.get('part_id')}",
                        "high",
                        min(1.0, ratio),
                        {"left": left_name, "right": right_name, "overlap_volume": overlap, "overlap_ratio": ratio},
                        _bbox_union(left_box, right_box),
                        "Separate, boolean-clean, or intentionally merge the overlapping parts using the smallest local reversible edit.",
                        ["Overlap ratio falls below threshold or is documented as intentional.", "No new non-manifold or duplicate-shell defect appears."],
                    )
                )

    if coverage_by_part:
        for part_id, score in coverage_by_part.items():
            if float(score) < COVERAGE_FLOOR:
                cage = next((item for item in cages if item.get("part_id") == part_id or item.get("object_name") == part_id), None)
                defects.append(
                    _defect(
                        f"defect_undercovered_{_slug(part_id)}",
                        "undercovered_part",
                        str(part_id),
                        "medium",
                        1.0 - clamp(score, 0.0, 1.0),
                        {"coverage_score": clamp(score, 0.0, 1.0), "minimum": COVERAGE_FLOOR},
                        cage.get("aabb_world") if cage else [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                        "Add an optimization or detail view that exposes this part with enough projected area.",
                        ["Part coverage clears the minimum coverage score.", "No primary part is only seen from a single grazing angle."],
                    )
                )
    return _dedupe_defects(defects)


def build_geometry_digest(
    records: Iterable[dict[str, Any]],
    *,
    coverage_by_part: dict[str, float] | None = None,
    view_scores: list[dict[str, Any]] | None = None,
    critic_score: float = 0.0,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records_list = [dict(record) for record in records]
    scene_box = scene_aabb(records_list)
    cages = build_part_cages(records_list, scene_box) if scene_box else []
    defects = detect_generic_defects(records_list, coverage_by_part=coverage_by_part, scene=scene_box)
    metric_vector = metric_vector_from_analysis(
        records_list,
        defects,
        coverage_by_part=coverage_by_part,
        view_scores=view_scores,
    )
    score = hybrid_score(
        metric_vector,
        critic_score=critic_score,
        geometry_weight=clamp((settings or {}).get("geometry_score_weight", DEFAULT_GEOMETRY_SCORE_WEIGHT), 0.0, 1.0),
        critic_weight=clamp((settings or {}).get("critic_score_weight", DEFAULT_CRITIC_SCORE_WEIGHT), 0.0, 1.0),
    )
    gates = hard_gates(metric_vector, defects, target_score=clamp((settings or {}).get("target_score", 0.85), 0.0, 1.0), hybrid=score["hybrid_score"])
    return {
        "version": "0.13.1",
        "object_count": len(records_list),
        "scene_bounds": _aabb_payload(scene_box) if scene_box else None,
        "scene_cage": _scene_cage_payload(scene_box) if scene_box else None,
        "footprint_frame": footprint_frame(records_list),
        "part_cages": cages,
        "defects": defects,
        "coverage_by_part": coverage_by_part or _default_part_coverage(cages),
        "metric_vector": metric_vector,
        "scores": score,
        "hard_gates": gates,
        "summary": _geometry_summary(records_list, metric_vector, defects),
    }


def metric_vector_from_analysis(
    records: Iterable[dict[str, Any]],
    defects: Iterable[dict[str, Any]],
    *,
    coverage_by_part: dict[str, float] | None = None,
    view_scores: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    records_list = list(records)
    defects_list = list(defects)
    if not records_list:
        return {
            "geometry_score": 0.0,
            "coverage_score": 0.0,
            "framing_score": 0.0,
            "defect_score": 0.0,
            "semantic_anchor_score": 0.0,
        }
    severity_penalty = sum(_severity_weight(str(item.get("severity", "low"))) * clamp(item.get("confidence", 0.5), 0.0, 1.0) for item in defects_list)
    geometry_score = clamp(1.0 - severity_penalty / max(len(records_list) + 2.0, 2.0), 0.0, 1.0)
    defect_score = clamp(1.0 - severity_penalty / 3.0, 0.0, 1.0)
    if coverage_by_part:
        coverage_score = clamp(sum(clamp(value, 0.0, 1.0) for value in coverage_by_part.values()) / max(len(coverage_by_part), 1), 0.0, 1.0)
    elif view_scores:
        coverage_score = clamp(
            sum(clamp(item.get("score_components", {}).get("coverage", item.get("score", 0.0)), 0.0, 1.0) for item in view_scores) / max(len(view_scores), 1),
            0.0,
            1.0,
        )
    else:
        coverage_score = DEFAULT_MINIMUM_COVERAGE_SCORE
    framing_penalty = sum(0.12 for item in defects_list if str(item.get("type", "")) in {"clipping_risk", "weak_silhouette", "tiny_detail_missed"})
    framing_score = clamp(0.90 - framing_penalty, 0.0, 1.0)
    semantic_anchor = clamp(0.82 - 0.08 * sum(1 for item in defects_list if str(item.get("severity", "")) in {"high", "critical"}), 0.0, 1.0)
    return {
        "geometry_score": round(geometry_score, 4),
        "coverage_score": round(coverage_score, 4),
        "framing_score": round(framing_score, 4),
        "defect_score": round(defect_score, 4),
        "semantic_anchor_score": round(semantic_anchor, 4),
    }


def deterministic_score(metrics: dict[str, Any]) -> float:
    g = clamp(metrics.get("geometry_score", metrics.get("G", 0.0)), 0.0, 1.0)
    c = clamp(metrics.get("coverage_score", metrics.get("C", 0.0)), 0.0, 1.0)
    f = clamp(metrics.get("framing_score", metrics.get("F", 0.0)), 0.0, 1.0)
    d = clamp(metrics.get("defect_score", metrics.get("D", 0.0)), 0.0, 1.0)
    return round(0.575 * g + 0.175 * c + 0.100 * f + 0.150 * d, 4)


def hybrid_score(
    metrics: dict[str, Any],
    *,
    critic_score: float = 0.0,
    geometry_weight: float = DEFAULT_GEOMETRY_SCORE_WEIGHT,
    critic_weight: float = DEFAULT_CRITIC_SCORE_WEIGHT,
) -> dict[str, float]:
    det = deterministic_score(metrics)
    q = clamp(critic_score, 0.0, 1.0)
    total = max(geometry_weight + critic_weight, _EPS)
    return {
        "deterministic_score": det,
        "critic_score": round(q, 4),
        "hybrid_score": round((geometry_weight / total) * det + (critic_weight / total) * q, 4),
    }


def hard_gates(metrics: dict[str, Any], defects: Iterable[dict[str, Any]], *, target_score: float = 0.85, hybrid: float | None = None) -> dict[str, Any]:
    defects_list = list(defects)
    blocking = [item for item in defects_list if str(item.get("severity", "")) in {"high", "critical"}]
    h = deterministic_score(metrics) if hybrid is None else clamp(hybrid, 0.0, 1.0)
    gates = {
        "target_score_ok": h >= clamp(target_score, 0.0, 1.0),
        "geometry_ok": clamp(metrics.get("geometry_score", 0.0), 0.0, 1.0) >= GEOMETRY_FLOOR,
        "coverage_ok": clamp(metrics.get("coverage_score", 0.0), 0.0, 1.0) >= COVERAGE_FLOOR,
        "framing_ok": clamp(metrics.get("framing_score", 0.0), 0.0, 1.0) >= FRAMING_FLOOR,
        "defect_ok": clamp(metrics.get("defect_score", 0.0), 0.0, 1.0) >= DEFECT_FLOOR and not blocking,
        "semantic_ok": clamp(metrics.get("semantic_anchor_score", 0.0), 0.0, 1.0) >= SEMANTIC_ANCHOR_FLOOR,
        "blocking_defects": [str(item.get("defect_id", item.get("type", ""))) for item in blocking],
    }
    gates["can_complete"] = all(value for key, value in gates.items() if key != "blocking_defects")
    return gates


def protected_metric_regression(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    prev = previous.get("metric_vector", previous)
    cur = current.get("metric_vector", current)
    return bool(
        clamp(prev.get("geometry_score", 0.0), 0.0, 1.0) - clamp(cur.get("geometry_score", 0.0), 0.0, 1.0) > 0.015
        or clamp(prev.get("coverage_score", 0.0), 0.0, 1.0) - clamp(cur.get("coverage_score", 0.0), 0.0, 1.0) > 0.03
        or clamp(prev.get("defect_score", 0.0), 0.0, 1.0) - clamp(cur.get("defect_score", 0.0), 0.0, 1.0) > 0.03
        or clamp(prev.get("semantic_anchor_score", 0.0), 0.0, 1.0) - clamp(cur.get("semantic_anchor_score", 0.0), 0.0, 1.0) > 0.03
    )


def detect_plateau(history: list[dict[str, Any]], *, min_hybrid_gain: float = 0.02, min_det_gain: float = 0.015) -> bool:
    if len(history) < 3:
        return False
    b_now = max(clamp(item.get("hybrid_score", item.get("score", 0.0)), 0.0, 1.0) for item in history)
    b_prev = max(clamp(item.get("hybrid_score", item.get("score", 0.0)), 0.0, 1.0) for item in history[:-2])
    d_now = max(clamp(item.get("deterministic_score", item.get("scores", {}).get("deterministic_score", 0.0)), 0.0, 1.0) for item in history)
    d_prev = max(clamp(item.get("deterministic_score", item.get("scores", {}).get("deterministic_score", 0.0)), 0.0, 1.0) for item in history[:-2])
    sig_now = set(history[-1].get("issue_signature", []) or [])
    sig_prev = set(history[-2].get("issue_signature", []) or [])
    jaccard = len(sig_now & sig_prev) / max(len(sig_now | sig_prev), 1)
    return (b_now - b_prev) < min_hybrid_gain and (d_now - d_prev) < min_det_gain and jaccard >= 0.80


def sanitize_delta_prompt(delta: Any, *, goal: str = "", allow_destructive: bool = False) -> dict[str, Any] | None:
    if not isinstance(delta, dict):
        return None
    risky_parts = {"edits": delta.get("edits", []), "next_prompt": delta.get("next_prompt", ""), "summary": delta.get("summary", "")}
    raw = json.dumps(risky_parts, ensure_ascii=True, sort_keys=True).lower()
    destructive_terms = ("delete all", "overwrite", "external", "download", "publish", "run python", "execute python", "destructive")
    if not allow_destructive and any(term in raw for term in destructive_terms):
        return None
    if "preserve" not in delta or "forbid" not in delta:
        return None
    if _looks_like_full_rewrite(delta, goal):
        return None
    preserve = [str(item) for item in delta.get("preserve", []) or [] if str(item).strip()]
    forbid = [str(item) for item in delta.get("forbid", []) or [] if str(item).strip()]
    if not preserve or not forbid:
        return None
    budget = delta.get("budget", {}) if isinstance(delta.get("budget", {}), dict) else {}
    max_edits = int(delta.get("max_edits", budget.get("max_edits", 2)) or 2)
    edits = delta.get("edits", []) or []
    if not isinstance(edits, list):
        edits = [str(edits)]
    return {
        "mode": "patch",
        "owner_metric": str(delta.get("owner_metric", delta.get("mode", "geometry")) or "geometry"),
        "targets": [str(item) for item in delta.get("targets", []) or [] if str(item).strip()],
        "preserve": preserve,
        "forbid": forbid,
        "max_edits": max(1, min(max_edits, 3)),
        "edits": edits[: max(1, min(max_edits, 3))],
        "acceptance_tests": [str(item) for item in delta.get("acceptance_tests", delta.get("success_checks", [])) or [] if str(item).strip()],
    }


def delta_prompt_to_text(delta: dict[str, Any] | None, *, fallback: str = "") -> str:
    if not delta:
        return fallback
    parts = [
        "Apply a bounded visual-review patch.",
        f"Owner metric: {delta.get('owner_metric', 'geometry')}.",
    ]
    targets = ", ".join(delta.get("targets", []) or [])
    if targets:
        parts.append(f"Target defects: {targets}.")
    edits = delta.get("edits", []) or []
    if edits:
        parts.append("Edits: " + "; ".join(_compact(item) for item in edits[:3]) + ".")
    preserve = ", ".join(delta.get("preserve", []) or [])
    forbid = ", ".join(delta.get("forbid", []) or [])
    if preserve:
        parts.append(f"Preserve: {preserve}.")
    if forbid:
        parts.append(f"Forbid: {forbid}.")
    tests = "; ".join(delta.get("acceptance_tests", []) or [])
    if tests:
        parts.append(f"Pass when: {tests}.")
    return " ".join(parts)


def aabb_overlap(left: AABB, right: AABB) -> float:
    extents = []
    for index in range(3):
        low = max(left.minimum[index], right.minimum[index])
        high = min(left.maximum[index], right.maximum[index])
        extents.append(max(high - low, 0.0))
    return extents[0] * extents[1] * extents[2]


def _defect(
    defect_id: str,
    defect_type: str,
    target: str,
    severity: str,
    confidence: float,
    evidence: dict[str, Any],
    local_bbox: Any,
    remediation_hint: str,
    acceptance_tests: list[str],
) -> dict[str, Any]:
    return {
        "defect_id": defect_id,
        "type": defect_type,
        "target": target,
        "severity": severity,
        "confidence": round(clamp(confidence, 0.0, 1.0), 4),
        "evidence": evidence,
        "local_bbox": _bbox_payload(local_bbox),
        "remediation_hint": remediation_hint,
        "acceptance_tests": acceptance_tests,
    }


def _bbox_payload(value: Any) -> list[list[float]]:
    if isinstance(value, AABB):
        return [[float(item) for item in value.minimum], [float(item) for item in value.maximum]]
    if isinstance(value, list) and len(value) >= 2:
        return [[float(item) for item in vector3(value[0])], [float(item) for item in vector3(value[1])]]
    return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]


def _aabb_payload(value: AABB) -> dict[str, Any]:
    return {
        "minimum": [float(item) for item in value.minimum],
        "maximum": [float(item) for item in value.maximum],
        "center": [float(item) for item in value.center],
        "size": [float(item) for item in value.size],
        "diagonal": float(value.diagonal),
        "radius": float(value.radius),
    }


def _scene_cage_payload(value: AABB) -> dict[str, Any]:
    return {
        "cage_id": "scene_cage",
        "center_world": [float(item) for item in value.center],
        "aabb_world": [[float(item) for item in value.minimum], [float(item) for item in value.maximum]],
        "obb_extents": [float(item) * 0.5 for item in value.size],
        "radius": float(value.radius),
        "diagonal": float(value.diagonal),
    }


def _aabb_from_cage(cage: dict[str, Any]) -> AABB:
    bbox = cage.get("aabb_world", [[0, 0, 0], [0, 0, 0]])
    return AABB(vector3(bbox[0]), vector3(bbox[1]))


def _bbox_union(left: AABB, right: AABB) -> list[list[float]]:
    return [
        [min(left.minimum[index], right.minimum[index]) for index in range(3)],
        [max(left.maximum[index], right.maximum[index]) for index in range(3)],
    ]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) * 0.5


def _severity_weight(severity: str) -> float:
    return {"low": 0.18, "medium": 0.42, "high": 0.85, "critical": 1.0}.get(severity, 0.25)


def _dedupe_defects(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in defects:
        defect_id = str(item.get("defect_id", ""))
        if defect_id in seen:
            continue
        seen.add(defect_id)
        output.append(item)
    return output


def _default_part_coverage(cages: list[dict[str, Any]]) -> dict[str, float]:
    return {str(cage.get("part_id", cage.get("object_name", ""))): DEFAULT_MINIMUM_COVERAGE_SCORE for cage in cages}


def _geometry_summary(records: list[dict[str, Any]], metrics: dict[str, float], defects: list[dict[str, Any]]) -> str:
    if not records:
        return "No visible target geometry is available for visual review."
    high = [item for item in defects if str(item.get("severity", "")) in {"high", "critical"}]
    return (
        f"{len(records)} target object(s), geometry {metrics['geometry_score']:.2f}, "
        f"coverage {metrics['coverage_score']:.2f}, defects {metrics['defect_score']:.2f}, "
        f"{len(defects)} issue(s), {len(high)} blocking."
    )


def _cage_summary(name: str, size: tuple[float, float, float], materials: list[str]) -> str:
    sorted_size = sorted(size)
    if sorted_size[-1] <= _EPS:
        shape = "degenerate part"
    elif sorted_size[0] / sorted_size[-1] < 0.05:
        shape = "thin part"
    elif sorted_size[-1] / max(sorted_size[0], _EPS) > 3.0:
        shape = "elongated part"
    else:
        shape = "compact part"
    mat = f" with {len(materials)} material(s)" if materials else ""
    return f"{name}: {shape}{mat}"


def _looks_like_full_rewrite(delta: dict[str, Any], goal: str) -> bool:
    text = json.dumps(delta, ensure_ascii=True).lower()
    if any(term in text for term in ("start over", "rewrite the entire", "replace the scene", "new scene from scratch")):
        return True
    goal_tokens = {item for item in re.split(r"[^a-z0-9]+", goal.lower()) if len(item) > 3}
    delta_tokens = {item for item in re.split(r"[^a-z0-9]+", text) if len(item) > 3}
    if len(delta_tokens) > 120 and len(goal_tokens & delta_tokens) < max(1, len(goal_tokens) // 5):
        return True
    return False


def _compact(value: Any) -> str:
    if isinstance(value, dict):
        text = ", ".join(f"{key}={val}" for key, val in sorted(value.items()))
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:180] + ("..." if len(text) > 180 else "")


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "part"
