from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_TOOLS = {
    "get_scene_summary",
    "get_selection",
    "get_object_details",
    "list_blender_data",
    "get_blender_property",
    "list_blender_operators",
    "inspect_blender_operator",
    "check_blender_operator_poll",
    "list_dashboard_context",
    "list_ai_scope",
    "list_active_context_chips",
    "list_context_chips",
    "list_action_cards",
    "get_action_detail",
    "classify_user_intent",
    "list_blender_surfaces",
    "list_cached_operator_namespaces",
    "get_thread_context",
    "list_toolbox_items",
    "get_toolbox_item",
    "list_asset_items",
    "get_asset_item",
    "list_asset_context",
    "search_ai_assets",
    "list_ai_asset_libraries",
    "list_asset_versions",
    "get_asset_version_detail",
    "list_asset_dependencies",
    "list_asset_provenance",
    "diagnose_ai_assets",
    "list_blender_asset_libraries",
    "list_workflow_graphs",
    "inspect_workflow_graph",
    "run_quick_prompt",
    "explain_workflow_graph",
    "simplify_workflow_graph",
    "create_game_asset_plan",
    "apply_game_asset_action",
    "explain_addon_step",
    "get_visual_review_context",
    "get_visual_geometry_context",
    "analyze_visual_geometry",
    "validate_gpt_asset",
    "get_asset_intent_manifest",
    "get_asset_constraint_graph",
    "get_asset_repair_plan",
    "get_asset_validation_report",
    "list_asset_validation_reports",
    "plan_geometry_review_viewpoints",
    "get_visual_review_metrics",
    "list_visual_review_runs",
    "get_visual_review_run",
    "plan_visual_review_viewpoints",
}

ACTION_STORE_TOOLS = {
    "create_action_card",
    "create_asset_action_card",
    "update_action_card_plan",
    "update_action_status",
    "preview_action_card",
    "request_action_approval",
    "record_action_step",
    "record_action_warning",
    "record_action_result",
    "record_action_failure",
    "record_visual_review_iteration",
    "set_asset_intent_manifest",
    "pin_output_to_thread",
    "write_project_note",
    "diagnose_dashboard_workspace",
    "create_asset_publish_action",
    "promote_output_snapshot",
    "validate_asset_version",
    "pin_asset_version",
    "fork_asset_version",
}

MUTATING_SCENE_TOOLS = {
    "create_primitive",
    "create_mesh_object",
    "create_empty",
    "rename_object",
    "duplicate_object",
    "set_transform",
    "set_custom_property",
    "set_blender_property",
    "set_object_visibility",
    "set_parent",
    "create_vertex_group",
    "assign_vertex_group",
    "delete_object",
    "create_collection",
    "move_object_to_collection",
    "create_material",
    "assign_material",
    "add_modifier",
    "remove_modifier",
    "apply_modifier",
    "create_light",
    "create_camera",
    "insert_keyframe",
    "set_frame_range",
    "add_armature_bone",
    "set_bone_deform",
    "delete_armature_bones",
    "set_pose_bone_transform",
    "import_file",
    "call_blender_operator",
    "run_toolbox_system",
    "import_asset_item",
    "append_asset_from_library",
    "append_asset_version",
    "link_asset_version",
    "run_workflow_graph",
    "apply_safe_asset_repair",
}

EXTERNAL_WRITE_TOOLS = {
    "export_fbx",
    "import_file",
    "save_asset_file",
    "save_selected_objects_asset",
    "save_selection_to_asset_library",
    "register_blender_asset_library",
    "publish_asset_package",
    "import_asset_package",
    "save_checkpoint_copy",
}

CRITICAL_TOOLS = {
    "execute_blender_python",
}

PREVIEW_SAFE_TOOLS = READ_ONLY_TOOLS | ACTION_STORE_TOOLS | {
    "create_workflow_graph",
    "add_workflow_node",
    "connect_workflow_nodes",
    "set_workflow_node_config",
    "capture_scene_viewpoints",
}

ACTION_METADATA_KEYS = ("action_id", "__action_id", "_action_id")


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    category: str
    risk: str
    requires_action: bool
    requires_expert: bool = False


def classify_tool(name: str) -> ToolPolicy:
    tool_name = (name or "").strip()
    if tool_name in CRITICAL_TOOLS:
        return ToolPolicy(tool_name, "critical", "critical", True, True)
    if tool_name in EXTERNAL_WRITE_TOOLS:
        return ToolPolicy(tool_name, "external_write", "high", True)
    if tool_name in MUTATING_SCENE_TOOLS:
        risk = "high" if tool_name == "call_blender_operator" else "medium"
        return ToolPolicy(tool_name, "mutating", risk, True)
    if tool_name in ACTION_STORE_TOOLS:
        return ToolPolicy(tool_name, "action_store", "low", False)
    if tool_name in PREVIEW_SAFE_TOOLS:
        return ToolPolicy(tool_name, "read_only" if tool_name in READ_ONLY_TOOLS else "preview_safe", "low", False)
    if tool_name.startswith("list_") or tool_name.startswith("get_") or tool_name.startswith("inspect_") or tool_name.startswith("check_"):
        return ToolPolicy(tool_name, "read_only", "low", False)
    return ToolPolicy(tool_name, "mutating", "medium", True)


def action_id_from_arguments(arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    for key in ACTION_METADATA_KEYS:
        value = str(args.get(key, "")).strip()
        if value:
            return value
    return ""


def strip_action_metadata(arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = dict(arguments or {})
    for key in ACTION_METADATA_KEYS:
        args.pop(key, None)
    return args


def summarize_arguments(arguments: dict[str, Any] | None, limit: int = 240) -> str:
    args = strip_action_metadata(arguments or {})
    text = ", ".join(f"{key}={value!r}" for key, value in sorted(args.items()))
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."
