from __future__ import annotations

from codex_blender_agent.validation_repair import build_asset_repair_plan, generate_repair_plan, safe_repair_delta_prompt


def test_repair_plan_generates_safe_and_gated_steps():
    issues = [
        {
            "issue_id": "issue_floating_shard",
            "type": "floating_part",
            "severity": "high",
            "objects": ["FloatingShard"],
            "target": "FloatingShard",
            "evidence": {"ground_gap": 0.42},
            "suggested_fix": "Snap FloatingShard to its nearest support surface.",
            "acceptance_tests": ["Gap to support is within tolerance.", "No new interpenetration is introduced."],
            "source_kind": "direct_geometry",
        },
        {
            "issue_id": "issue_alignment_seat",
            "type": "axis_alignment",
            "severity": "medium",
            "objects": ["Seat"],
            "target": "Seat",
            "evidence": {"angle_error": 3.4},
            "suggested_fix": "Rotate Seat level with world up.",
            "acceptance_tests": ["Axis residual is within tolerance.", "Other parts remain unchanged."],
            "source_kind": "direct_geometry",
        },
        {
            "issue_id": "issue_overlap_crown",
            "type": "interpenetration",
            "severity": "critical",
            "objects": ["CrownBattlement", "CastleWall"],
            "target": "CrownBattlement",
            "evidence": {"triangle_pair_count": 86},
            "suggested_fix": "Separate the battlement from the wall or rebuild the local contact region.",
            "acceptance_tests": ["Overlap count drops to zero.", "No new floating part is introduced."],
            "source_kind": "direct_geometry",
        },
        {
            "issue_id": "issue_duplicate_panel",
            "type": "duplicate_surface_risk",
            "severity": "medium",
            "objects": ["PanelA", "PanelB"],
            "target": "PanelA",
            "evidence": {"center_distance": 0.002},
            "suggested_fix": "Remove the duplicate surface or rebuild the local geometry.",
            "acceptance_tests": ["Duplicate coincident face count is zero.", "No z-fighting remains."],
            "source_kind": "direct_geometry",
        },
    ]
    manifest = {
        "repair_policy": {
            "allow_safe_transforms": True,
            "allow_destructive_mesh_ops": False,
            "destructive_requires_approval": True,
        },
        "objects": [{"name": "FloatingShard"}, {"name": "Seat"}],
    }

    plan = generate_repair_plan(issues, manifest=manifest)
    # build_asset_repair_plan remains the low-level contract; the wrapper adds
    # decision and count fields for downstream consumers.
    raw_plan = build_asset_repair_plan({"issues": issues}, manifest=manifest)
    prompt = safe_repair_delta_prompt(plan, max_actions=2)

    safe_ops = {step["operation"] for step in plan["safe_steps"]}
    blocked_ops = {step["operation"] for step in plan["blocked_steps"]}

    assert raw_plan["counts"]["safe"] == 2
    assert raw_plan["counts"]["gated"] == 2
    assert plan["decision"] == "needs_approval"
    assert plan["safe_step_count"] == 2
    assert "snap_to_support" in safe_ops
    assert "align_axis" in safe_ops
    assert blocked_ops
    assert all(step["requires_approval"] is True for step in plan["blocked_steps"])
    assert all("preserve" in step and "forbid" in step for step in plan["safe_steps"] + plan["blocked_steps"])
    assert any("Destructive mesh operation" in step["reason"] for step in plan["blocked_steps"])
    assert prompt["mode"] == "patch"
    assert prompt["max_edits"] == 2


def test_safe_only_repair_plan_stays_safe():
    issues = [
        {
            "issue_id": "issue_origin",
            "type": "origin_error",
            "severity": "low",
            "objects": ["Wheel"],
            "target": "Wheel",
            "evidence": {"origin_error": 0.12},
            "acceptance_tests": ["Origin lies on the expected pivot.", "Rotation behaves correctly after the edit."],
        }
    ]

    plan = generate_repair_plan(issues, manifest={"repair_policy": {"allow_destructive_mesh_ops": False}})

    assert plan["decision"] == "safe"
    assert plan["safe_steps"][0]["operation"] == "set_origin"
    assert plan["blocked_steps"] == []
