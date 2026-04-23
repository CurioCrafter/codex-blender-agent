from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .visual_geometry import AABB, clamp, vector3


@dataclass
class AlgorithmLedger:
    rows: list[dict[str, Any]] = field(default_factory=list)

    @contextmanager
    def check(
        self,
        check_id: str,
        label: str,
        *,
        inputs: dict[str, Any] | None = None,
        thresholds: dict[str, Any] | None = None,
        objects: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        row = {
            "id": check_id,
            "label": label,
            "status": "running",
            "duration_ms": 0.0,
            "inputs": inputs or {},
            "thresholds": thresholds or {},
            "objects": objects or [],
            "issue_count": 0,
            "evidence_refs": [],
            "error": "",
        }
        try:
            yield row
            row["status"] = row.get("status") if row.get("status") in {"skipped", "failed"} else "done"
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            raise
        finally:
            row["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            self.rows.append(_json_safe(row))

    def add(
        self,
        check_id: str,
        label: str,
        *,
        status: str = "done",
        inputs: dict[str, Any] | None = None,
        thresholds: dict[str, Any] | None = None,
        objects: list[str] | None = None,
        issue_count: int = 0,
        evidence_refs: list[str] | None = None,
        error: str = "",
        duration_ms: float = 0.0,
    ) -> dict[str, Any]:
        row = {
            "id": check_id,
            "label": label,
            "status": status,
            "duration_ms": round(float(duration_ms), 3),
            "inputs": inputs or {},
            "thresholds": thresholds or {},
            "objects": objects or [],
            "issue_count": int(issue_count),
            "evidence_refs": evidence_refs or [],
            "error": error,
        }
        self.rows.append(_json_safe(row))
        return row


def effective_tolerances(diagonal: float, settings: dict[str, Any] | None = None) -> dict[str, float]:
    settings = dict(settings or {})
    relative = float(settings.get("relative_tolerance", 0.002) or 0.002)
    scaled = max(float(diagonal), 0.0) * relative
    return {
        "epsilon": max(1.0e-6, scaled * 0.001),
        "contact": max(0.003, scaled),
        "penetration": max(0.004, scaled),
        "clearance": max(0.005, scaled),
        "z_fighting": max(0.0008, scaled * 0.25),
        "angle_degrees": float(settings.get("angle_tolerance_degrees", 1.0) or 1.0),
    }


def classify_aabb_pair(left: AABB, right: AABB, *, tolerances: dict[str, float]) -> dict[str, Any]:
    overlap = _overlap_volume(left, right)
    min_volume = max(min(left.volume, right.volume), 1.0e-9)
    ratio = overlap / min_volume
    center_distance = _distance(left.center, right.center)
    xy_ratio = _xy_overlap_ratio(left, right)
    z_touch_gap = min(abs(left.minimum[2] - right.maximum[2]), abs(right.minimum[2] - left.maximum[2]))
    classification = "separate"
    if ratio > 0.18:
        classification = "interpenetration"
    elif ratio > 0.04:
        classification = "excessive_overlap"
    elif overlap > 0.0:
        classification = "touching_or_minor_overlap"
    elif xy_ratio > 0.75 and center_distance <= max(tolerances["z_fighting"] * 8.0, min(left.diagonal, right.diagonal) * 0.015):
        classification = "z_fighting_risk"
    elif xy_ratio > 0.05 and z_touch_gap <= tolerances["contact"]:
        classification = "support_contact"
    return {
        "classification": classification,
        "overlap_volume": overlap,
        "overlap_ratio_of_smaller": ratio,
        "xy_overlap_ratio": xy_ratio,
        "center_distance": center_distance,
        "z_touch_gap": z_touch_gap,
    }


def triangle_area(a: Any, b: Any, c: Any) -> float:
    ax, ay, az = vector3(a)
    bx, by, bz = vector3(b)
    cx, cy, cz = vector3(c)
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    return 0.5 * max((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2 + (ux * vy - uy * vx) ** 2, 0.0) ** 0.5


def classify_triangle_pair(tri_a: tuple[Any, Any, Any], tri_b: tuple[Any, Any, Any], *, epsilon: float = 1.0e-6) -> dict[str, Any]:
    """Lightweight deterministic triangle pair classifier.

    This is intentionally conservative for v0.15 tests and reporting. Blender
    BVH supplies the candidate pairs; this function classifies obvious
    coplanar/degenerate/bounding overlap cases without adding external deps.
    """

    area_a = triangle_area(*tri_a)
    area_b = triangle_area(*tri_b)
    box_a = _aabb_from_points([vector3(point) for point in tri_a])
    box_b = _aabb_from_points([vector3(point) for point in tri_b])
    overlap = _overlap_volume(box_a, box_b)
    coplanar = _coplanar_hint(tri_a, tri_b, epsilon=epsilon)
    if area_a <= epsilon or area_b <= epsilon:
        kind = "degenerate"
    elif coplanar and _aabb_overlaps_2d(box_a, box_b, epsilon=epsilon):
        kind = "coplanar_overlap"
    elif overlap <= epsilon:
        kind = "separate"
    elif coplanar:
        kind = "coplanar_overlap"
    else:
        kind = "candidate_intersection"
    return {"classification": kind, "area_a": area_a, "area_b": area_b, "aabb_overlap_volume": overlap}


def score_issue_severity(issue_type: str, measured: float, tolerance: float) -> str:
    ratio = measured / max(tolerance, 1.0e-9)
    if issue_type in {"interpenetration", "self_intersection", "non_manifold_topology"} and ratio >= 3.0:
        return "critical"
    if ratio >= 2.0:
        return "high"
    if ratio >= 0.75:
        return "medium"
    return "low"


def _aabb_from_points(points: list[tuple[float, float, float]]) -> AABB:
    return AABB(
        tuple(min(point[index] for point in points) for index in range(3)),
        tuple(max(point[index] for point in points) for index in range(3)),
    )


def _overlap_volume(left: AABB, right: AABB) -> float:
    extents = [
        max(min(left.maximum[index], right.maximum[index]) - max(left.minimum[index], right.minimum[index]), 0.0)
        for index in range(3)
    ]
    return extents[0] * extents[1] * extents[2]


def _xy_overlap_ratio(left: AABB, right: AABB) -> float:
    x = max(min(left.maximum[0], right.maximum[0]) - max(left.minimum[0], right.minimum[0]), 0.0)
    y = max(min(left.maximum[1], right.maximum[1]) - max(left.minimum[1], right.minimum[1]), 0.0)
    overlap = x * y
    left_area = max((left.maximum[0] - left.minimum[0]) * (left.maximum[1] - left.minimum[1]), 1.0e-9)
    right_area = max((right.maximum[0] - right.minimum[0]) * (right.maximum[1] - right.minimum[1]), 1.0e-9)
    return overlap / min(left_area, right_area)


def _distance(a: Any, b: Any) -> float:
    aa = vector3(a)
    bb = vector3(b)
    return sum((aa[index] - bb[index]) ** 2 for index in range(3)) ** 0.5


def _aabb_overlaps_2d(left: AABB, right: AABB, *, epsilon: float = 0.0) -> bool:
    return (
        min(left.maximum[0], right.maximum[0]) + epsilon >= max(left.minimum[0], right.minimum[0])
        and min(left.maximum[1], right.maximum[1]) + epsilon >= max(left.minimum[1], right.minimum[1])
    )


def _coplanar_hint(tri_a: tuple[Any, Any, Any], tri_b: tuple[Any, Any, Any], *, epsilon: float) -> bool:
    a0, a1, a2 = [vector3(point) for point in tri_a]
    b0 = vector3(tri_b[0])
    ux, uy, uz = a1[0] - a0[0], a1[1] - a0[1], a1[2] - a0[2]
    vx, vy, vz = a2[0] - a0[0], a2[1] - a0[1], a2[2] - a0[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    norm = max((nx * nx + ny * ny + nz * nz) ** 0.5, epsilon)
    distance = abs((b0[0] - a0[0]) * nx + (b0[1] - a0[1]) * ny + (b0[2] - a0[2]) * nz) / norm
    return distance <= epsilon * 10.0


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
