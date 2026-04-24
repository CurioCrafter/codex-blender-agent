from __future__ import annotations

from codex_blender_agent.command_center import available_workflows, command_center_payload, explanation_context, readiness_checklist


def test_readiness_checklist_blocks_without_service_or_models() -> None:
    checks = {item["id"]: item for item in readiness_checklist({"service_running": False, "model_ready": False, "online_access": True})}

    assert checks["service"]["status"] == "blocked"
    assert checks["models"]["status"] == "blocked"
    assert "Start / Refresh Models" in checks["models"]["recovery"]


def test_available_workflows_reflect_no_selection_and_no_model() -> None:
    actions = {item["id"]: item for item in available_workflows({"model_ready": False, "service_running": False})}

    assert actions["refresh_models"]["enabled"] is True
    assert actions["explain_scene"]["enabled"] is False
    assert actions["fix_selected"]["enabled"] is False
    assert actions["fix_selected"]["reason"]


def test_available_workflows_enable_selected_mesh_workflows() -> None:
    actions = {
        item["id"]: item
        for item in available_workflows(
            {
                "model_ready": True,
                "service_running": True,
                "has_selection": True,
                "selected_mesh_count": 1,
                "has_prompt": False,
                "action_count": 1,
            }
        )
    }

    assert actions["fix_selected"]["enabled"] is True
    assert actions["make_game_asset"]["enabled"] is True
    assert actions["review_with_screenshots"]["enabled"] is True
    assert actions["save_reusable_asset"]["enabled"] is True
    assert actions["recover_last_change"]["enabled"] is True


def test_available_workflows_enable_image_brief_from_attachment() -> None:
    actions = {
        item["id"]: item
        for item in available_workflows(
            {
                "model_ready": True,
                "service_running": True,
                "has_selection": False,
                "has_prompt": False,
                "has_attachments": True,
            }
        )
    }

    assert actions["generate_reference_image"]["enabled"] is True


def test_command_center_payload_includes_lanes_and_explanations() -> None:
    payload = command_center_payload(
        {
            "model_state": {"model_ready": True, "selected_label": "GPT Test", "model_count": 1},
            "model_ready": True,
            "service_running": True,
            "active_scope": "selection",
            "has_selection": True,
            "selected_count": 1,
            "web_console_running": True,
        }
    )

    assert payload["title"] == "AI Command Center"
    assert payload["current_lane"] == "build"
    assert any(item["id"] == "build" and item["selected"] for item in payload["lanes"])
    assert payload["explanations"]["panels"]["AI Command Center"]
    assert any(item["label"] == "Fix Selected" for item in payload["available_workflows"])


def test_explanation_context_names_visible_panels() -> None:
    context = explanation_context(model_state={"model_ready": False}, active_scope="scene", current_lane="setup")

    assert "Readiness Checklist" in context["panels"]
    assert context["scope"]["current"] == "scene"
    assert context["lane"]["label"] == "Setup"
