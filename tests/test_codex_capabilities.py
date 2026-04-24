from __future__ import annotations

from codex_blender_agent.codex_capabilities import build_image_generation_brief, list_codex_capabilities, render_image_generation_brief
from codex_blender_agent.tool_policy import classify_tool
from codex_blender_agent.tool_specs import get_dynamic_tool_specs


def test_codex_capabilities_include_image_generation_bridge() -> None:
    capabilities = {item["id"]: item for item in list_codex_capabilities()}

    assert "image_generation" in capabilities
    assert "create_image_generation_brief" in capabilities["image_generation"]["tool_names"]
    assert "register_generated_image_asset" in capabilities["image_generation"]["tool_names"]
    assert capabilities["image_generation"]["status"] == "handoff_ready"


def test_image_generation_brief_is_actionable_and_renderable() -> None:
    brief = build_image_generation_brief(
        prompt="Create a hand-painted stone tower texture sheet with moss in the cracks.",
        purpose="texture",
        style="stylized medieval",
        target_engine="Godot",
        reference_paths=[r"C:\refs\tower.png"],
        scene_context={"active_object": "Tower", "selected_objects": ["Tower", "Wall"], "scope": "selection"},
    )

    assert brief["request_id"].startswith("img-")
    assert brief["purpose"] == "texture"
    assert "Godot" in brief["handoff_prompt"]
    assert "Tower, Wall" in brief["handoff_prompt"]
    assert r"C:\refs\tower.png" in brief["handoff_prompt"]
    assert "register_generated_image_asset" in " ".join(brief["next_steps"])

    rendered = render_image_generation_brief(brief)
    assert "## Handoff Prompt" in rendered
    assert "Create a hand-painted stone tower texture sheet" in rendered


def test_image_generation_tools_have_expected_policy_and_specs() -> None:
    names = {tool["name"]: tool for tool in get_dynamic_tool_specs()}

    assert "list_codex_capabilities" in names
    assert "create_image_generation_brief" in names
    assert "register_generated_image_asset" in names
    assert names["create_image_generation_brief"]["inputSchema"]["required"] == ["prompt"]
    assert classify_tool("list_codex_capabilities").requires_action is False
    assert classify_tool("list_live_ai_activity").requires_action is False
    assert classify_tool("run_addon_health_check").requires_action is False
    assert classify_tool("list_model_state").requires_action is False
    assert classify_tool("refresh_model_state").requires_action is False
    assert classify_tool("list_ui_explanation_context").requires_action is False
    assert classify_tool("list_available_workflows").requires_action is False
    assert classify_tool("create_image_generation_brief").requires_action is False
    assert classify_tool("register_generated_image_asset").requires_action is True
    assert classify_tool("register_generated_image_asset").category == "external_write"
