from __future__ import annotations

from codex_blender_agent.asset_validation import aabb_overlap_volume, sweep_and_prune, validate_records


def _record(name, location, dimensions, **extra):
    return {"name": name, "type": "MESH", "location": location, "dimensions": dimensions, **extra}


def test_sweep_and_prune_selects_overlapping_aabb_pairs():
    records = [
        _record("A", [0, 0, 0], [2, 2, 2]),
        _record("B", [0.5, 0, 0], [2, 2, 2]),
        _record("C", [8, 0, 0], [1, 1, 1]),
    ]

    assert sweep_and_prune(records) == [(0, 1)]
    assert aabb_overlap_volume([-1, -1, -1], [1, 1, 1], [0, -1, -1], [2, 1, 1]) == 4


def test_validation_report_schema_and_issue_types():
    records = [
        _record("Base", [0, 0, 0], [4, 4, 1], material_slot_count=1, material_names=["Stone"]),
        _record("Overlap", [0, 0, 0], [3.8, 3.8, 0.9], material_slot_count=1, material_names=["Stone"]),
        _record("FloatingShard", [0, 0, 5], [0.4, 0.4, 0.4]),
        _record("TinyBolt", [3, 0, 0.6], [0.03, 0.03, 0.03], material_slot_count=1, material_names=[]),
        _record("BadMesh", [6, 0, 0], [1, 1, 1], degenerate_face_count=2, loose_edge_count=1),
    ]

    report = validate_records(records)
    issue_types = {issue["type"] for issue in report["issues"]}

    assert report["status"] == "completed"
    assert "excessive_overlap" in issue_types or "interpenetration" in issue_types
    assert "floating_part" in issue_types
    assert "tiny_detail_missed" in issue_types
    assert "inconsistent_material_slots" in issue_types
    assert "degenerate_geometry" in issue_types
    assert "loose_geometry" in issue_types
    assert report["metric_vector"]["geometry_score"] < 1.0
    assert report["hard_gates"]["can_complete"] is False
    assert report["manifest_status"] == "inferred"
    assert report["intent_manifest"]["schema_version"] == "0.15.0"
    assert report["constraint_graph"]["nodes"]
    assert report["algorithm_ledger"]
    assert report["repair_plan"]["counts"]["total"] >= 1
    assert all(
        {"issue_id", "type", "severity", "objects", "evidence", "suggested_fix", "confidence", "acceptance_tests", "source", "algorithm_ids"} <= set(issue)
        for issue in report["issues"]
    )


def test_manifest_required_contact_and_allowed_intersection_change_issue_source():
    records = [
        _record("Seat", [0, 0, 1.0], [2, 2, 0.2]),
        _record("Leg", [0, 0, 0.25], [0.2, 0.2, 0.2]),
        _record("Pin", [0, 0, 1.0], [0.3, 0.3, 0.3]),
    ]
    report = validate_records(
        records,
        intent_manifest={
            "objects": [{"name": "Seat", "role": "support"}, {"name": "Leg", "role": "support_leg"}],
            "required_contacts": [{"object": "Leg", "targets": ["Seat"], "tolerance": 0.01}],
            "allowed_intersections": [["Pin", "Seat"]],
        },
    )
    issue_by_type = {issue["type"]: issue for issue in report["issues"]}

    assert report["manifest_status"] == "provided"
    assert issue_by_type["required_contact_failure"]["source"] == "manifest"
    assert "excessive_allowed_penetration" in issue_by_type


def test_empty_validation_report_is_clean_no_target_geometry():
    report = validate_records([])

    assert report["status"] == "no_target_geometry"
    assert report["object_count"] == 0
    assert report["issues"][0]["type"] == "no_target_geometry"
    assert report["hard_gates"]["can_complete"] is False
