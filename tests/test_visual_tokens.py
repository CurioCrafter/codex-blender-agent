from __future__ import annotations

from types import SimpleNamespace

from codex_blender_agent.studio_state import action_status_label, risk_label
from codex_blender_agent.visual_tokens import (
    VAGUE_TOP_LEVEL_LABELS,
    empty_state,
    empty_state_payload,
    orientation_payload,
    primary_action_for_card,
    risk_token,
    secondary_actions_for_card,
    state_meta,
    status_copy,
    status_token,
    token,
    validate_icons,
)


def test_visual_tokens_use_safe_icon_set():
    assert validate_icons() == []


def test_status_tokens_map_to_readable_semantic_states():
    assert status_token("completed").label == "Done"
    assert status_token("needs_approval").label == "Review required"
    assert status_copy("awaiting_approval") == "Review required"
    assert status_copy("completed_with_warnings") == "Changed"
    assert state_meta("running").alert is False
    assert state_meta("stale").label == "Needs input"
    assert status_token("failed").alert is True
    assert status_token("unknown").label == "Info"


def test_risk_tokens_pair_color_semantics_with_text_labels():
    assert risk_token("low").label == "Info"
    assert risk_token("medium").alert is True
    assert risk_token("high").label == "Danger"
    assert risk_label("high") == "High"


def test_action_status_labels_match_ui_copy():
    assert action_status_label("needs_approval") == "Awaiting Approval"
    assert action_status_label("running") == "Running"
    assert action_status_label("invalid") == "Draft"


def test_empty_states_teach_primary_workflows():
    assert "context" in empty_state("dashboard").lower()
    assert "preview" in empty_state("workflow").lower()
    assert "asset" in empty_state("assets").lower()
    payload = empty_state_payload("action_cards")
    assert payload.purpose
    assert payload.reason
    assert payload.next_action
    assert payload.tip
    assert token("missing").label == "Info"
    assert token("create").label == "Create"
    assert token("workflow").icon == "NODETREE"
    assert token("learn").alert is False


def test_card_primary_actions_are_state_aware_and_single_primary():
    assert primary_action_for_card({"status": "draft"}).label == "Preview"
    assert primary_action_for_card({"status": "awaiting_approval"}).label == "Approve"
    assert primary_action_for_card({"status": "running"}).label == "Stop"
    assert primary_action_for_card({"status": "completed"}).label == "View changes"
    assert primary_action_for_card({"status": "failed"}).label == "Recover action"

    secondary = secondary_actions_for_card({"status": "running"})
    assert [action.label for action in secondary] == ["Details"]


def test_non_alert_states_do_not_burn_risk_channel():
    for state in ("ready", "needs_input", "review_required", "running", "done", "changed", "pinned"):
        assert state_meta(state).alert is False
    assert state_meta("risk").alert is True
    assert state_meta("failed").alert is True


def test_orientation_payload_answers_core_questions_without_blender():
    wm = SimpleNamespace(
        codex_blender_active_scope="selection",
        codex_blender_dashboard_progress=0.5,
        codex_blender_connection="Ready.",
        codex_blender_error="",
        codex_blender_context_chips=[
            SimpleNamespace(label="Selection", enabled=True),
            SimpleNamespace(label="Hidden objects excluded", enabled=False),
        ],
        codex_blender_action_cards=[
            {"status": "running", "title": "Analyze material"},
            {"status": "awaiting_approval", "title": "Publish asset"},
            {"status": "completed", "title": "Created preview"},
        ],
    )
    context = SimpleNamespace(
        window_manager=wm,
        scene=SimpleNamespace(name="Scene"),
        window=SimpleNamespace(workspace=SimpleNamespace(name="Workflow")),
        area=SimpleNamespace(type="NODE_EDITOR"),
        space_data=SimpleNamespace(type="NODE_EDITOR"),
        active_object=SimpleNamespace(name="Cube"),
        selected_objects=[SimpleNamespace(name="Cube")],
        mode="OBJECT",
    )

    payload = orientation_payload(context, "workflow")

    assert payload["location"].startswith("Workflow")
    assert payload["scope"] == "Selection"
    assert "1 selected" in payload["sees"]
    assert payload["running"] == "Analyze material"
    assert payload["review_count"] == 1
    assert payload["changed_count"] == 1
    assert payload["undo_available"] is True


def test_top_level_action_labels_avoid_known_vague_copy():
    labels = {
        primary_action_for_card({"status": "draft"}).label,
        primary_action_for_card({"status": "running"}).label,
        primary_action_for_card({"status": "awaiting_approval"}).label,
        primary_action_for_card({"status": "completed"}).label,
        primary_action_for_card({"status": "failed"}).label,
    }

    assert labels.isdisjoint(VAGUE_TOP_LEVEL_LABELS)
