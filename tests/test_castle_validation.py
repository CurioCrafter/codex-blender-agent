from __future__ import annotations

from codex_blender_agent.asset_validation import validate_records


def _record(name, location, dimensions, **extra):
    return {"name": name, "type": "MESH", "location": location, "dimensions": dimensions, **extra}


def _issue_by_type(report, issue_type: str):
    return next(issue for issue in report["issues"] if issue["type"] == issue_type)


def test_castle_validation_flags_tree_in_moat_zone_violation():
    records = [
        _record("CastleKeep", [0, 0, 0], [10, 10, 8]),
        _record("MoatRing", [0, 0, 0], [14, 14, 2]),
        _record("PineTree", [0.5, -0.25, 0.8], [1.2, 1.2, 3.0]),
    ]

    report = validate_records(records)
    issue = _issue_by_type(report, "castle_zone_violation")

    assert report["status"] == "completed"
    assert issue["objects"] == ["PineTree", "MoatRing"]
    assert issue["evidence"]["zone"] == "moat"
    assert issue["evidence"]["object"] == "PineTree"
    assert issue["evidence"]["xy_overlap_ratio"] > 0.2


def test_castle_validation_flags_oversized_moat():
    records = [
        _record("CastleKeep", [0, 0, 0], [10, 10, 8]),
        _record("MoatRing", [0, 0, 0], [22, 22, 1]),
    ]

    report = validate_records(records)
    issue = _issue_by_type(report, "castle_oversized_moat")

    assert report["status"] == "completed"
    assert issue["objects"] == ["MoatRing"]
    assert issue["evidence"]["moat_xy_area"] == 484.0
    assert issue["evidence"]["castle_body_xy_area"] == 100.0
    assert issue["evidence"]["ratio"] == 4.84


def test_castle_validation_flags_battlement_intersection_with_support_wall():
    records = [
        _record("CastleWall", [0, 0, 0], [10, 2, 4]),
        _record("CrownBattlement", [0, 0, 1.5], [8, 1.5, 3]),
    ]

    report = validate_records(records)
    issue = _issue_by_type(report, "castle_battlement_intersection")

    assert report["status"] == "completed"
    assert issue["objects"] == ["CrownBattlement", "CastleWall"]
    assert issue["evidence"]["penetration_depth_estimate"] == 2.0
    assert issue["evidence"]["xy_overlap_ratio"] == 1.0


def test_castle_validation_flags_unmerged_castle_blockout_repetition():
    records = [
        _record("CastleKeep", [0, 0, 0], [10, 10, 8]),
        _record("CrownBlock_A", [-3, 0, 4.5], [0.8, 0.8, 0.5], face_count=6, vertex_count=8),
        _record("CrownBlock_B", [-1, 0, 4.5], [0.8, 0.8, 0.5], face_count=6, vertex_count=8),
        _record("CrownBlock_C", [1, 0, 4.5], [0.8, 0.8, 0.5], face_count=6, vertex_count=8),
        _record("CrownBlock_D", [3, 0, 4.5], [0.8, 0.8, 0.5], face_count=6, vertex_count=8),
    ]

    report = validate_records(records)
    issue = _issue_by_type(report, "castle_unmerged_blockout")

    assert report["status"] == "completed"
    assert issue["objects"] == ["CrownBlock_A", "CrownBlock_B", "CrownBlock_C", "CrownBlock_D"]
    assert issue["evidence"]["candidate_count"] == 4
    assert issue["evidence"]["common_center_z_values"] == [4.5, 4.5, 4.5, 4.5]
