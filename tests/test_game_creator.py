from __future__ import annotations

from types import SimpleNamespace

from codex_blender_agent.game_creator import (
    ExecutionDecision,
    creator_context_payload,
    prompt_execution_decision,
    risk_lane_for_prompt,
    should_auto_start_visual_review,
    tool_execution_decision,
)
from codex_blender_agent.quick_prompts import (
    get_quick_prompt,
    list_quick_prompts,
    quick_prompt_categories,
    quick_prompt_payload,
    render_quick_prompt,
)
from codex_blender_agent.tool_policy import classify_tool


def test_quick_prompt_registry_covers_game_creator_categories():
    categories = quick_prompt_categories()
    assert categories == ("start", "create_asset", "materials", "level_art", "workflow", "fix", "export", "tutor")
    prompts = list_quick_prompts()
    assert len(prompts) >= 20
    assert get_quick_prompt("improve_with_screenshots").execution_mode == "visual_review"
    assert get_quick_prompt("game_ready_prop").category == "create_asset"
    assert {prompt.category for prompt in list_quick_prompts("workflow")} == {"workflow"}
    payload = quick_prompt_payload(get_quick_prompt("export_checklist"))
    assert payload["risk_lane"] == "informational"


def test_quick_prompt_rendering_uses_context_payload():
    rendered = render_quick_prompt("export_checklist", {"target_engine": "Unity"})
    assert "Unity" in rendered
    material = render_quick_prompt("stylized_material", {"style_hint": "PS1 horror"})
    assert "PS1 horror" in material


def test_game_creator_execution_policy_reduces_additive_card_friction():
    additive = {
        "intent": "change",
        "risk": "medium",
        "risk_axes": {"destructiveness": "property_edit", "scope": "selection", "externality": "scene_local"},
    }
    assert risk_lane_for_prompt(additive) == "additive"
    decision = prompt_execution_decision(additive, friction="fast", require_additive_approval=False)
    assert decision.requires_card is False
    assert decision.receipt_only is True

    strict = prompt_execution_decision(additive, friction="strict", require_additive_approval=False)
    assert strict.requires_card is True

    destructive = {
        "intent": "change",
        "risk": "high",
        "risk_axes": {"destructiveness": "destructive", "scope": "selection", "externality": "scene_local"},
    }
    assert prompt_execution_decision(destructive, friction="fast").requires_card is True

    local_automate = {
        "intent": "automate",
        "risk": "medium",
        "risk_axes": {"destructiveness": "property_edit", "scope": "selection", "externality": "scene_local"},
    }
    assert prompt_execution_decision(local_automate, friction="fast").requires_card is False

    project_wide = {
        "intent": "automate",
        "risk": "high",
        "risk_axes": {"destructiveness": "property_edit", "scope": "whole_scene", "externality": "scene_local"},
    }
    assert prompt_execution_decision(project_wide, friction="fast").requires_card is True


def test_tool_execution_policy_auto_receipts_local_mutation_only():
    create_cube = tool_execution_decision(classify_tool("create_primitive"), friction="fast")
    assert create_cube.requires_card is False
    assert create_cube.receipt_only is True

    export = tool_execution_decision(classify_tool("export_fbx"), friction="fast")
    assert export.requires_card is True
    assert export.receipt_only is False

    operator_bridge = tool_execution_decision(classify_tool("call_blender_operator"), friction="fast")
    assert operator_bridge.requires_card is True


def test_auto_visual_review_routing_only_for_scene_changing_non_gated_prompts():
    additive = {"intent": "change"}
    ask = {"intent": "ask"}
    automate = {"intent": "automate"}
    allowed = ExecutionDecision(False, True, "receipt")
    gated = ExecutionDecision(True, False, "card")

    assert should_auto_start_visual_review(additive, allowed, chat_mode="scene_agent", enabled=True) is True
    assert should_auto_start_visual_review(automate, allowed, chat_mode="scene_agent", enabled=True) is True
    assert should_auto_start_visual_review(ask, allowed, chat_mode="scene_agent", enabled=True) is False
    assert should_auto_start_visual_review(additive, gated, chat_mode="scene_agent", enabled=True) is False
    assert should_auto_start_visual_review(additive, allowed, chat_mode="chat_only", enabled=True) is False
    assert should_auto_start_visual_review(additive, allowed, chat_mode="scene_agent", enabled=False) is False
    assert should_auto_start_visual_review(automate, allowed, chat_mode="scene_agent", enabled=True, prompt="make a workflow recipe") is False


def test_creator_context_payload_is_safe_without_blender_types():
    context = SimpleNamespace(
        window_manager=SimpleNamespace(
            codex_blender_execution_friction="fast",
            codex_blender_active_scope="selection",
            codex_blender_target_engine="unreal",
            codex_blender_game_style="stylized low poly",
        ),
        scene=SimpleNamespace(name="LevelBlockout"),
        window=SimpleNamespace(workspace=SimpleNamespace(name="Layout")),
        area=SimpleNamespace(type="VIEW_3D"),
        active_object=SimpleNamespace(name="Crate"),
        selected_objects=[SimpleNamespace(name="Crate")],
    )

    payload = creator_context_payload(context)
    assert payload["mode"] == "game_creator"
    assert payload["selected_count"] == 1
    assert payload["target_engine"] == "unreal"
