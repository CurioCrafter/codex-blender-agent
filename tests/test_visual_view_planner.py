from __future__ import annotations

import math

from codex_blender_agent.visual_geometry import angle_degrees
from codex_blender_agent.visual_view_planner import (
    fibonacci_band_directions,
    fit_camera_distance,
    halton_band_directions,
    plan_geometry_review_viewpoints,
)


def _record(name, location, dimensions):
    return {"name": name, "type": "MESH", "location": location, "dimensions": dimensions}


def test_fibonacci_and_halton_are_deterministic():
    fib_a = fibonacci_band_directions(8, phase=0.123)
    fib_b = fibonacci_band_directions(8, phase=0.123)
    halton_a = halton_band_directions(8, start_index=3)
    halton_b = halton_band_directions(8, start_index=3)
    assert fib_a == fib_b
    assert halton_a == halton_b
    assert all(abs(math.sqrt(sum(v * v for v in direction)) - 1.0) < 1e-6 for direction in fib_a + halton_a)


def test_fit_distance_keeps_box_in_front_of_camera():
    points = [
        (x, y, z)
        for x in (-1.0, 1.0)
        for y in (-0.5, 0.5)
        for z in (-0.5, 0.5)
    ]
    distance = fit_camera_distance(points, (0, 0, 0), (0, -1, 0.25), fov_degrees=50, margin=1.08)
    assert distance > 1.0


def test_geometry_planner_selects_optimization_and_audit_views_with_separation():
    plan = plan_geometry_review_viewpoints(
        [
            _record("MainProp", [0, 0, 0], [2, 1, 1]),
            _record("SmallDetail", [1.5, 0, 0.2], [0.2, 0.2, 0.2]),
        ],
        settings={"candidate_view_count": 24, "selected_capture_count": 8, "audit_view_count": 3},
    )
    assert len(plan["selected_viewpoints"]) == 8
    assert len(plan["optimization_viewpoints"]) == 5
    assert len(plan["audit_viewpoints"]) == 3
    assert plan["geometry_digest"]["object_count"] == 2
    assert plan["view_scores"]
    for audit in plan["audit_viewpoints"]:
        assert all(angle_degrees(audit["direction"], opt["direction"]) >= 30.0 for opt in plan["optimization_viewpoints"])


def test_empty_plan_returns_no_target_geometry_defect():
    plan = plan_geometry_review_viewpoints([])
    assert plan["selected_viewpoints"] == []
    assert plan["defects"][0]["type"] == "no_target_geometry"
