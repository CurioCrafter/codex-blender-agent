from __future__ import annotations

import math
from typing import Any, Iterable

from .visual_geometry import (
    AABB,
    DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES,
    DEFAULT_AUDIT_VIEW_COUNT,
    DEFAULT_CAMERA_FIT_MARGIN,
    DEFAULT_CANDIDATE_VIEW_COUNT,
    DEFAULT_SELECTED_CAPTURE_COUNT,
    DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES,
    angle_degrees,
    build_geometry_digest,
    clamp,
    cross,
    dot,
    footprint_frame,
    length,
    normalize,
    record_bounds_points,
    scene_aabb,
    v_add,
    v_mul,
    v_sub,
    vector3,
)

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))
_EPS = 1.0e-9


def fibonacci_band_directions(
    count: int,
    *,
    elevation_min_degrees: float = 15.0,
    elevation_max_degrees: float = 70.0,
    phase: float = 0.0,
    up: Iterable[float] = (0.0, 0.0, 1.0),
) -> list[tuple[float, float, float]]:
    n = max(0, int(count))
    if n == 0:
        return []
    up_axis, t1, t2 = _basis_from_up(up)
    z_min = math.sin(math.radians(elevation_min_degrees))
    z_max = math.sin(math.radians(elevation_max_degrees))
    directions = []
    for index in range(n):
        z = z_min + ((index + 0.5) / n) * (z_max - z_min)
        phi = phase + index * GOLDEN_ANGLE
        r = math.sqrt(max(1.0 - z * z, 0.0))
        direction = v_add(v_add(v_mul(t1, r * math.cos(phi)), v_mul(t2, r * math.sin(phi))), v_mul(up_axis, z))
        directions.append(normalize(direction))
    return directions


def halton(index: int, base: int) -> float:
    result = 0.0
    factor = 1.0 / base
    value = max(int(index), 0)
    while value > 0:
        result += factor * (value % base)
        value //= base
        factor /= base
    return result


def halton_band_directions(
    count: int,
    *,
    start_index: int = 1,
    elevation_min_degrees: float = 20.0,
    elevation_max_degrees: float = 75.0,
    up: Iterable[float] = (0.0, 0.0, 1.0),
) -> list[tuple[float, float, float]]:
    up_axis, t1, t2 = _basis_from_up(up)
    z_min = math.sin(math.radians(elevation_min_degrees))
    z_max = math.sin(math.radians(elevation_max_degrees))
    output = []
    for offset in range(max(0, int(count))):
        k = start_index + offset
        phi = 2.0 * math.pi * halton(k, 2)
        z = z_min + (z_max - z_min) * halton(k, 3)
        r = math.sqrt(max(1.0 - z * z, 0.0))
        output.append(normalize(v_add(v_add(v_mul(t1, r * math.cos(phi)), v_mul(t2, r * math.sin(phi))), v_mul(up_axis, z))))
    return output


def pca_seed_directions(frame: dict[str, Any]) -> list[tuple[str, tuple[float, float, float]]]:
    axis_x = normalize(vector3(frame.get("axis_x"), (1.0, 0.0, 0.0)))
    axis_y = normalize(vector3(frame.get("axis_y"), (0.0, 1.0, 0.0)))
    up = normalize(vector3(frame.get("axis_z"), (0.0, 0.0, 1.0)))
    seeds = [
        ("pca_front", v_add(v_mul(axis_y, -1.0), v_mul(up, 0.32))),
        ("pca_back", v_add(axis_y, v_mul(up, 0.32))),
        ("pca_left", v_add(v_mul(axis_x, -1.0), v_mul(up, 0.28))),
        ("pca_right", v_add(axis_x, v_mul(up, 0.28))),
        ("pca_three_quarter", v_add(v_add(axis_x, v_mul(axis_y, -1.0)), v_mul(up, 0.45))),
        ("pca_top", up),
    ]
    return [(name, normalize(direction)) for name, direction in seeds]


def fit_camera_distance(
    points: Iterable[Iterable[float]],
    aim: Iterable[float],
    direction: Iterable[float],
    *,
    fov_degrees: float = 50.0,
    margin: float = DEFAULT_CAMERA_FIT_MARGIN,
    up: Iterable[float] = (0.0, 0.0, 1.0),
) -> float:
    aim_point = vector3(aim)
    d = normalize(direction, fallback=(0.0, -1.0, 0.3))
    right, cam_up = _camera_axes(d, up)
    tan_half = math.tan(math.radians(fov_degrees) * 0.5)
    best = 0.0
    for point in points:
        q = v_sub(vector3(point), aim_point)
        x = dot(right, q)
        y = dot(cam_up, q)
        z = dot(d, q)
        best = max(best, z + margin * abs(x) / max(tan_half, 0.001), z + margin * abs(y) / max(tan_half, 0.001))
    return max(best, 0.25)


def plan_geometry_review_viewpoints(
    records: Iterable[dict[str, Any]],
    *,
    settings: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settings = dict(settings or {})
    records_list = [dict(record) for record in records]
    scene_box = scene_aabb(records_list)
    if scene_box is None:
        digest = build_geometry_digest(records_list, settings=settings)
        return {
            "viewpoints": [],
            "selected_viewpoints": [],
            "optimization_viewpoints": [],
            "audit_viewpoints": [],
            "candidates": [],
            "view_scores": [],
            "geometry_digest": digest,
            "defects": digest.get("defects", []),
            "metric_vector": digest.get("metric_vector", {}),
            "hard_gates": digest.get("hard_gates", {}),
            "diagnostics": ["no_target_geometry"],
        }

    candidate_count = max(8, int(settings.get("candidate_view_count", DEFAULT_CANDIDATE_VIEW_COUNT) or DEFAULT_CANDIDATE_VIEW_COUNT))
    selected_count = max(1, int(settings.get("selected_capture_count", DEFAULT_SELECTED_CAPTURE_COUNT) or DEFAULT_SELECTED_CAPTURE_COUNT))
    audit_count = max(0, min(int(settings.get("audit_view_count", DEFAULT_AUDIT_VIEW_COUNT) or DEFAULT_AUDIT_VIEW_COUNT), selected_count))
    opt_count = max(1, selected_count - audit_count)
    sep = float(settings.get("view_angular_separation_degrees", DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES) or DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES)
    audit_sep = float(settings.get("audit_angular_separation_degrees", DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES) or DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES)
    margin = float(settings.get("camera_fit_margin", DEFAULT_CAMERA_FIT_MARGIN) or DEFAULT_CAMERA_FIT_MARGIN)
    fov = float(settings.get("fov_degrees", 50.0) or 50.0)

    frame = footprint_frame(records_list)
    aim = vector3(frame.get("center"), scene_box.center)
    points: list[tuple[float, float, float]] = []
    for record in records_list:
        points.extend(record_bounds_points(record))
    radius = scene_box.radius
    history_dirs = [vector3(item.get("direction", (0.0, 0.0, 1.0))) for item in history or []]

    directions: list[tuple[str, str, tuple[float, float, float]]] = []
    for name, direction in pca_seed_directions(frame):
        directions.append((name, "seed", direction))
    for index, direction in enumerate(fibonacci_band_directions(candidate_count, phase=_phase_from_records(records_list), up=frame.get("axis_z", (0.0, 0.0, 1.0))), start=1):
        directions.append((f"fib_{index:02d}", "optimization", direction))

    candidates = []
    for name, kind, direction in directions:
        candidate = _candidate_from_direction(
            name,
            kind,
            direction,
            aim,
            points,
            radius=radius,
            fov_degrees=fov,
            margin=margin,
            history_dirs=history_dirs,
            scene_box=scene_box,
        )
        if not candidate.get("rejection_reason"):
            candidates.append(candidate)
    candidates.extend(
        _issue_targeted_candidates(
            records_list,
            frame=frame,
            fov_degrees=fov,
            margin=margin,
            history_dirs=history_dirs,
        )
    )

    candidates.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    optimization = _greedy_select(candidates, opt_count, sep, fill=True)

    audit_pool = []
    for index, direction in enumerate(halton_band_directions(candidate_count * 2, up=frame.get("axis_z", (0.0, 0.0, 1.0))), start=1):
        candidate = _candidate_from_direction(
            f"audit_{index:02d}",
            "audit",
            direction,
            aim,
            points,
            radius=radius,
            fov_degrees=fov,
            margin=margin,
            history_dirs=[vector3(view.get("direction")) for view in optimization],
            scene_box=scene_box,
        )
        if candidate.get("rejection_reason"):
            continue
        if all(angle_degrees(candidate.get("direction", (0, 0, 1)), opt.get("direction", (0, 0, 1))) >= audit_sep for opt in optimization):
            audit_pool.append(candidate)
    audit = _greedy_select(sorted(audit_pool, key=lambda item: float(item.get("score", 0.0)), reverse=True), audit_count, audit_sep, fill=False)
    selected = optimization + audit
    coverage_by_part = _coverage_by_part(records_list, selected)
    view_scores = [_view_score_payload(item) for item in selected]
    digest = build_geometry_digest(records_list, coverage_by_part=coverage_by_part, view_scores=view_scores, settings=settings)
    return {
        "viewpoints": selected,
        "selected_viewpoints": selected,
        "optimization_viewpoints": optimization,
        "audit_viewpoints": audit,
        "candidates": candidates[: min(len(candidates), 32)],
        "view_scores": view_scores,
        "coverage_by_part": coverage_by_part,
        "geometry_digest": digest,
        "defects": digest.get("defects", []),
        "metric_vector": digest.get("metric_vector", {}),
        "hard_gates": digest.get("hard_gates", {}),
        "diagnostics": [],
    }


def _candidate_from_direction(
    view_id: str,
    kind: str,
    direction: tuple[float, float, float],
    aim: tuple[float, float, float],
    points: list[tuple[float, float, float]],
    *,
    radius: float,
    fov_degrees: float,
    margin: float,
    history_dirs: list[tuple[float, float, float]],
    scene_box: AABB,
) -> dict[str, Any]:
    d = normalize(direction)
    distance = fit_camera_distance(points, aim, d, fov_degrees=fov_degrees, margin=margin)
    if not math.isfinite(distance) or distance <= 0.0:
        return {"id": view_id, "rejection_reason": "invalid_fit_distance"}
    if distance < radius * 0.35:
        return {"id": view_id, "rejection_reason": "camera_inside_target_cage"}
    camera_location = v_add(aim, v_mul(d, distance))
    fill = clamp((radius / max(distance, _EPS)) / max(math.tan(math.radians(fov_degrees) * 0.5), _EPS), 0.0, 1.0)
    if fill < 0.04:
        return {"id": view_id, "rejection_reason": "useless_projected_area"}
    novelty = 1.0
    if history_dirs:
        novelty = min(1.0, min(angle_degrees(d, prev) for prev in history_dirs) / 35.0)
    coverage = clamp(0.58 + 0.32 * novelty + 0.10 * min(1.0, fill / 0.35), 0.0, 1.0)
    projected_area = clamp(fill / 0.35, 0.0, 1.0) * (1.0 - max(fill - 0.80, 0.0))
    part_balance = 0.78 if kind == "audit" else 0.82
    composition = clamp(0.92 - abs(fill - 0.45) * 0.35, 0.0, 1.0)
    occlusion = 0.82
    cost = 0.85 if kind == "seed" else 0.75
    score = 0.30 * coverage + 0.20 * novelty + 0.15 * projected_area + 0.10 * part_balance + 0.10 * composition + 0.10 * occlusion + 0.05 * cost
    label = view_id.replace("_", " ").title()
    return {
        "id": view_id,
        "label": label,
        "kind": kind,
        "target": [float(v) for v in aim],
        "direction": [float(v) for v in d],
        "distance": float(distance),
        "camera_location": [float(v) for v in camera_location],
        "focal_length": 38.0 if kind != "audit" else 42.0,
        "score": round(score, 4),
        "score_components": {
            "coverage": round(coverage, 4),
            "novelty": round(novelty, 4),
            "projected_area": round(projected_area, 4),
            "part_balance": round(part_balance, 4),
            "composition": round(composition, 4),
            "occlusion": round(occlusion, 4),
            "cost": round(cost, 4),
        },
        "clip_range": _clip_range(points, aim, d, distance),
        "scene_radius": float(scene_box.radius),
        "notes": f"{kind} view selected by geometry-aware planner.",
    }


def _greedy_select(candidates: list[dict[str, Any]], count: int, separation_degrees: float, *, fill: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        direction = vector3(candidate.get("direction"), (0.0, 0.0, 1.0))
        if any(angle_degrees(direction, vector3(item.get("direction"))) < separation_degrees for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= count:
            break
    if fill and len(selected) < count:
        for candidate in candidates:
            if candidate in selected:
                continue
            selected.append(candidate)
            if len(selected) >= count:
                break
    return selected


def _issue_targeted_candidates(
    records: list[dict[str, Any]],
    *,
    frame: dict[str, Any],
    fov_degrees: float,
    margin: float,
    history_dirs: list[tuple[float, float, float]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    up = vector3(frame.get("axis_z"), (0.0, 0.0, 1.0))
    directions = [
        normalize(v_add((1.0, -1.0, 0.0), v_mul(up, 0.45))),
        normalize(v_add((-1.0, 1.0, 0.0), v_mul(up, 0.38))),
    ]
    detail_terms = {
        "battlement": "parapet/battlement close-up",
        "crenel": "crenellation close-up",
        "merlon": "crenellation close-up",
        "crown": "top crown close-up",
        "tower": "tower corner close-up",
        "gate": "gate/bridge close-up",
        "moat": "moat clearance close-up",
        "bridge": "bridge/gate access close-up",
        "tree": "zone placement close-up",
    }
    for index, record in enumerate(records, start=1):
        name = str(record.get("name", f"part_{index}"))
        lowered = _record_search_text(record)
        matched = next((label for term, label in detail_terms.items() if term in lowered), "")
        box = scene_aabb([record])
        if box is None:
            continue
        dims = vector3(record.get("dimensions", box.size), default=box.size)
        tiny = min(abs(v) for v in dims) / max(max(abs(v) for v in dims), _EPS) < 0.08 or box.diagonal < 0.35
        if not matched and not tiny:
            continue
        aim = box.center
        points = record_bounds_points(record)
        direction = directions[len(output) % len(directions)]
        candidate = _candidate_from_direction(
            f"detail_{_slug(name)}_{index:02d}",
            "detail",
            direction,
            aim,
            points,
            radius=max(box.radius, 0.35),
            fov_degrees=max(38.0, fov_degrees - 8.0),
            margin=max(margin, 1.12),
            history_dirs=history_dirs,
            scene_box=box,
        )
        if candidate.get("rejection_reason"):
            continue
        candidate["score"] = round(min(1.0, float(candidate.get("score", 0.0)) + 0.08), 4)
        candidate["label"] = f"Detail: {name}"
        candidate["object_name"] = name
        candidate["target_reason"] = matched or "tiny/undercovered detail close-up"
        candidate["notes"] = f"Targeted close-up for {matched or 'small detail'}."
        output.append(candidate)
    return output[:8]


def _coverage_by_part(records: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, float]:
    if not records:
        return {}
    view_count = max(len(selected), 1)
    base = clamp(0.52 + min(view_count, 8) * 0.035, 0.0, 0.88)
    output = {}
    for index, record in enumerate(records, start=1):
        name = str(record.get("name", f"part_{index}"))
        key = f"part_{_slug(name)}_{index:02d}"
        dims = vector3(record.get("dimensions", (1.0, 1.0, 1.0)), default=(1.0, 1.0, 1.0))
        thin_penalty = 0.08 if min(abs(v) for v in dims) / max(max(abs(v) for v in dims), 0.001) < 0.04 else 0.0
        output[key] = round(clamp(base - thin_penalty, 0.0, 1.0), 4)
    return output


def _view_score_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": view.get("id", ""),
        "kind": view.get("kind", ""),
        "score": view.get("score", 0.0),
        "score_components": dict(view.get("score_components", {}) or {}),
        "direction": list(view.get("direction", []) or []),
        "distance": view.get("distance", 0.0),
    }


def _clip_range(points: list[tuple[float, float, float]], aim: tuple[float, float, float], direction: tuple[float, float, float], distance: float) -> dict[str, float]:
    depths = [distance - dot(direction, v_sub(point, aim)) for point in points] or [distance]
    near = max(0.001, min(depths) * 0.80)
    far = max(max(depths) * 1.20, near + 0.1)
    return {"near": round(near, 4), "far": round(far, 4)}


def _camera_axes(direction: Iterable[float], up: Iterable[float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    d = normalize(direction)
    up_axis = normalize(up, fallback=(0.0, 0.0, 1.0))
    if length(cross(up_axis, d)) <= 0.001:
        up_axis = (0.0, 1.0, 0.0)
    right = normalize(cross(up_axis, d), fallback=(1.0, 0.0, 0.0))
    cam_up = normalize(cross(d, right), fallback=(0.0, 0.0, 1.0))
    return right, cam_up


def _basis_from_up(up: Iterable[float]) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    up_axis = normalize(up, fallback=(0.0, 0.0, 1.0))
    ref = (1.0, 0.0, 0.0) if abs(dot(up_axis, (1.0, 0.0, 0.0))) < 0.9 else (0.0, 1.0, 0.0)
    t1 = normalize(cross(ref, up_axis), fallback=(1.0, 0.0, 0.0))
    t2 = normalize(cross(up_axis, t1), fallback=(0.0, 1.0, 0.0))
    return up_axis, t1, t2


def _phase_from_records(records: list[dict[str, Any]]) -> float:
    text = "|".join(str(record.get("name", "")) for record in records)
    return (sum(ord(ch) for ch in text) % 997) / 997.0 * GOLDEN_ANGLE


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "part"


def _record_search_text(record: dict[str, Any]) -> str:
    parts = [str(record.get("name", ""))]
    parts.extend(str(item) for item in record.get("material_names", []) or [])
    parts.extend(str(item) for item in record.get("collections", []) or [])
    return " ".join(parts).lower()
