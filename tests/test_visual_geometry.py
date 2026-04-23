from __future__ import annotations

import math

from codex_blender_agent.visual_geometry import (
    build_geometry_digest,
    detect_generic_defects,
    detect_plateau,
    footprint_frame,
    hard_gates,
    hybrid_score,
    protected_metric_regression,
    sanitize_delta_prompt,
)


def _record(name, location, dimensions, **extra):
    return {"name": name, "type": "MESH", "location": location, "dimensions": dimensions, **extra}


def test_footprint_frame_tracks_rotated_bounds():
    angle = math.radians(45)
    axis = (math.cos(angle), math.sin(angle))
    perp = (-math.sin(angle), math.cos(angle))
    points = []
    for sx in (-2, 2):
        for sy in (-0.25, 0.25):
            for z in (-0.5, 0.5):
                points.append([axis[0] * sx + perp[0] * sy, axis[1] * sx + perp[1] * sy, z])
    frame = footprint_frame([{"name": "RotatedAsset", "bounds": points}])
    axis_x = frame["axis_x"]
    assert abs(abs(axis_x[0]) - abs(axis_x[1])) < 0.1
    assert frame["stable"] is True


def test_geometry_digest_empty_scene_is_clean_failure():
    digest = build_geometry_digest([])
    assert digest["object_count"] == 0
    assert digest["metric_vector"]["geometry_score"] == 0.0
    assert digest["defects"][0]["type"] == "no_target_geometry"
    assert digest["hard_gates"]["can_complete"] is False


def test_generic_defects_cover_overlap_floaters_tiny_and_materials():
    records = [
        _record("Base", [0, 0, 0], [4, 4, 1], material_slot_count=1, material_names=["Stone"]),
        _record("Overlap", [0, 0, 0], [3.8, 3.8, 0.9], material_slot_count=1, material_names=["Stone"]),
        _record("FloatingShard", [0, 0, 5], [0.4, 0.4, 0.4]),
        _record("TinyBolt", [3, 0, 0.6], [0.03, 0.03, 0.03], material_slot_count=1, material_names=[]),
    ]
    defects = detect_generic_defects(records)
    types = {item["type"] for item in defects}
    assert "excessive_overlap" in types
    assert "floating_part" in types
    assert "tiny_detail_missed" in types
    assert "inconsistent_material_slots" in types
    assert all("remediation_hint" in item and "acceptance_tests" in item for item in defects)


def test_hybrid_gates_do_not_let_high_critic_override_low_geometry():
    metrics = {
        "geometry_score": 0.55,
        "coverage_score": 0.9,
        "framing_score": 0.9,
        "defect_score": 0.9,
        "semantic_anchor_score": 0.9,
    }
    score = hybrid_score(metrics, critic_score=1.0)
    gates = hard_gates(metrics, [], target_score=0.85, hybrid=score["hybrid_score"])
    assert score["hybrid_score"] < 0.85
    assert gates["geometry_ok"] is False
    assert gates["can_complete"] is False


def test_protected_metric_regression_and_plateau_detection():
    old = {"geometry_score": 0.9, "coverage_score": 0.8, "defect_score": 0.9, "semantic_anchor_score": 0.82}
    new = {"geometry_score": 0.86, "coverage_score": 0.82, "defect_score": 0.86, "semantic_anchor_score": 0.78}
    assert protected_metric_regression(old, new) is True
    history = [
        {"score": 0.74, "hybrid_score": 0.74, "deterministic_score": 0.67, "issue_signature": ["crop:right"]},
        {"score": 0.79, "hybrid_score": 0.79, "deterministic_score": 0.73, "issue_signature": ["crop:right"]},
        {"score": 0.801, "hybrid_score": 0.801, "deterministic_score": 0.739, "issue_signature": ["crop:right"]},
        {"score": 0.807, "hybrid_score": 0.807, "deterministic_score": 0.742, "issue_signature": ["crop:right"]},
    ]
    assert detect_plateau(history) is True


def test_delta_sanitizer_accepts_patch_and_rejects_unsafe_rewrites():
    safe = sanitize_delta_prompt(
        {
            "owner_metric": "geometry",
            "targets": ["defect_floating_part"],
            "preserve": ["style", "object count"],
            "forbid": ["delete", "external import"],
            "max_edits": 1,
            "edits": [{"target": "FloatingShard", "op": "snap_to_support"}],
        },
        goal="make a castle",
    )
    assert safe is not None
    assert safe["mode"] == "patch"
    assert sanitize_delta_prompt({"edits": ["replace the scene"], "preserve": [], "forbid": []}, goal="make a castle") is None
    assert sanitize_delta_prompt({"preserve": ["style"], "forbid": ["none"], "edits": ["run python to delete all objects"]}) is None
