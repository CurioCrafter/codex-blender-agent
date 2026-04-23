from __future__ import annotations

from codex_blender_agent.studio_state import (
    action_row,
    approval_required_for_risk,
    build_risk_axes,
    classify_prompt_intent,
    context_payload_from_chips,
    infer_action_risk,
    make_action_card,
    make_context_chip,
    normalize_action_status,
    normalize_scope,
    normalize_toolbox_group,
    risk_from_axes,
    transition_allowed,
)


def test_scope_and_context_payload_are_compact_and_visible():
    chips = [
        make_context_chip("selection", "Selection", "Cube, Sphere", "scope", True),
        make_context_chip("material", "Material", "Glass", "data", False),
    ]
    payload = context_payload_from_chips("scene", chips)

    assert normalize_scope("Active Object") == "active_object"
    assert payload["active_scope"] == "scene"
    assert [chip["chip_id"] for chip in payload["enabled_chips"]] == ["selection"]
    assert len(payload["all_chips"]) == 2


def test_action_card_risk_status_and_row_summary():
    card = make_action_card(
        title="Delete hidden controls",
        prompt="Delete the extra control bones before export.",
        affected_targets=["Rig"],
        required_context=["selection"],
    )

    assert card["risk"] == "high"
    assert card["status"] == "awaiting_approval"
    assert approval_required_for_risk(card["risk"]) is True

    row = action_row(card)
    assert row["action_id"] == card["action_id"]
    assert row["approval_required"] is True
    assert row["affected_targets"] == ["Rig"]
    assert row["risk_rationale"]


def test_prompt_intent_and_risk_axes_cover_action_first_routing():
    assert classify_prompt_intent("Explain the selected object. No changes.") == "ask"
    assert classify_prompt_intent("Inspect selected meshes for normals.") == "inspect"
    assert classify_prompt_intent("Add a bevel modifier, preview first.") == "change"
    assert classify_prompt_intent("Batch rename all selected objects.") == "automate"
    assert classify_prompt_intent("Recover the last AI action.") == "recover"
    assert classify_prompt_intent("Export FBX to this file.") == "export"

    axes = build_risk_axes(prompt="Delete all hidden objects", target_count=30, active_scope="scene")
    risk, rationale = risk_from_axes(axes)
    assert risk == "high"
    assert "High risk" in rationale

    critical_axes = build_risk_axes(prompt="Execute Python to delete files", critical=True)
    assert risk_from_axes(critical_axes)[0] == "critical"


def test_action_status_transitions_and_legacy_aliases():
    assert normalize_action_status("needs_approval") == "awaiting_approval"
    assert transition_allowed("draft", "preview_ready") is True
    assert transition_allowed("preview_ready", "awaiting_approval") is True
    assert transition_allowed("awaiting_approval", "approved") is True
    assert transition_allowed("completed", "running") is False


def test_toolbox_grouping_uses_artist_intent_labels():
    assert normalize_toolbox_group("material", "Create shader") == "Materials"
    assert normalize_toolbox_group("workflow", "Clean topology") == "Optimize"
    assert normalize_toolbox_group("system", "Diagnose scene") == "Debug"
    assert infer_action_risk("Explain the selected mesh") == "low"
