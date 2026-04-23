from __future__ import annotations

from codex_blender_agent.tool_policy import action_id_from_arguments, classify_tool, strip_action_metadata


def test_tool_policy_splits_read_only_mutating_external_and_critical_tools():
    assert classify_tool("get_scene_summary").category == "read_only"
    assert classify_tool("add_modifier").category == "mutating"
    assert classify_tool("add_modifier").requires_action is True
    assert classify_tool("save_selection_to_asset_library").category == "external_write"
    assert classify_tool("search_ai_assets").category == "read_only"
    assert classify_tool("create_asset_publish_action").category == "action_store"
    assert classify_tool("append_asset_version").category == "mutating"
    assert classify_tool("publish_asset_package").category == "external_write"
    assert classify_tool("capture_scene_viewpoints").category == "preview_safe"
    assert classify_tool("capture_scene_viewpoints").requires_action is False
    assert classify_tool("analyze_visual_geometry").category == "read_only"
    assert classify_tool("validate_gpt_asset").category == "read_only"
    assert classify_tool("get_asset_intent_manifest").category == "read_only"
    assert classify_tool("get_asset_constraint_graph").category == "read_only"
    assert classify_tool("get_asset_repair_plan").category == "read_only"
    assert classify_tool("set_asset_intent_manifest").category == "action_store"
    assert classify_tool("set_asset_intent_manifest").requires_action is False
    assert classify_tool("apply_safe_asset_repair").category == "mutating"
    assert classify_tool("apply_safe_asset_repair").requires_action is True
    assert classify_tool("get_asset_validation_report").category == "read_only"
    assert classify_tool("list_asset_validation_reports").category == "read_only"
    assert classify_tool("plan_geometry_review_viewpoints").category == "read_only"
    assert classify_tool("record_visual_review_iteration").category == "action_store"
    assert classify_tool("execute_blender_python").category == "critical"
    assert classify_tool("execute_blender_python").requires_expert is True


def test_action_metadata_is_internal_to_runtime_dispatch():
    args = {"object_name": "Cube", "action_id": "action-123", "__action_id": "ignored"}

    assert action_id_from_arguments(args) == "action-123"
    assert strip_action_metadata(args) == {"object_name": "Cube"}
