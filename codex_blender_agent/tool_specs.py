from __future__ import annotations

from copy import deepcopy


VECTOR3_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}

VECTOR4_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 4,
    "maxItems": 4,
}

JSON_OBJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
}

PRIMITIVE_TYPES = [
    "cube",
    "plane",
    "uv_sphere",
    "ico_sphere",
    "cylinder",
    "cone",
    "torus",
    "monkey",
]

DATA_BLOCK_TYPES = [
    "objects",
    "meshes",
    "materials",
    "armatures",
    "collections",
    "images",
    "actions",
    "cameras",
    "lights",
    "curves",
    "grease_pencils",
    "lattices",
    "node_groups",
    "scenes",
    "texts",
    "worlds",
]
TOOLBOX_CATEGORIES = [
    "mesh",
    "material",
    "rig",
    "animation",
    "workflow",
    "script",
    "note",
    "system",
    "generate",
    "modify",
    "materials",
    "animate",
    "organize",
    "optimize",
    "export",
    "debug",
]
ASSET_CATEGORIES = [
    "model",
    "material",
    "rig",
    "pose",
    "node_system",
    "recipe",
    "prompt",
    "output",
    "image",
    "texture",
    "reference",
    "blend",
    "script",
    "audio",
    "video",
    "cache",
    "other",
]
EMPTY_TYPES = ["PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE", "SPHERE", "CONE", "IMAGE"]
VERTEX_GROUP_MODES = ["ADD", "REPLACE", "SUBTRACT"]
OPERATOR_EXECUTION_CONTEXTS = ["EXEC_DEFAULT", "INVOKE_DEFAULT", "EXEC_REGION_WIN", "INVOKE_REGION_WIN"]
WORKFLOW_NODE_TYPES = [
    "workflow_input",
    "workflow_output",
    "value",
    "context_merge",
    "scene_snapshot",
    "selection",
    "thread_memory",
    "assistant_prompt",
    "assistant_call",
    "asset_search",
    "tool_call",
    "approval_gate",
    "route",
    "for_each",
    "join",
    "preview_tap",
    "recipe_call",
    "toolbox_recipe",
    "publish_asset",
]

ACTION_STATUSES = [
    "draft",
    "needs_clarification",
    "preview_ready",
    "preview_visible",
    "awaiting_approval",
    "approved",
    "running",
    "stopping",
    "paused",
    "completed",
    "completed_with_warnings",
    "failed",
    "recovered",
    "stale",
    "pinned",
    "archived",
    "cancelled",
]

ACTION_RISKS = ["low", "medium", "high", "critical"]
ACTION_INTENTS = ["ask", "inspect", "change", "automate", "recover", "export"]

_TOOL_SPECS = [
    {
        "name": "list_studio_context",
        "description": "Return compact AI Studio state: active project/thread, chat mode, open workspace areas, visible assets/toolbox counts, and current activity.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dashboard_context",
        "description": "Compatibility alias for list_studio_context.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_ai_scope",
        "description": "Return the visible AI scope and enabled context chips that define what the assistant may inspect or treat as primary context.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_context_chips",
        "description": "Return all visible context chips, including disabled chips, so the model can align with the user's visible context pack.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_active_context_chips",
        "description": "Return only enabled context chips. The assistant must not rely on disabled chips as active turn context.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_game_creator_context",
        "description": "Return the chat-first Game Creator context: selection, target engine, style hint, friction mode, and current Blender surface.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_quick_prompts",
        "description": "List built-in game-creation quick prompts grouped by start, asset, materials, level art, workflow, fix, export, and tutor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "run_quick_prompt",
        "description": "Render a built-in quick prompt against the current Game Creator context. This returns the prompt text for chat or planning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt_id": {"type": "string"},
            },
            "required": ["prompt_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_visual_review_context",
        "description": "Return the active screenshot self-review loop, settings, current phase, and recent runs.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_intent_manifest",
        "description": "Return the active asset intent manifest for the current scene or visual-review run, including inferred or user-provided contacts, anchors, and repair constraints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "set_asset_intent_manifest",
        "description": "Store or update the current asset intent manifest for the active scene or visual-review run. This records intent metadata for validation and repair planning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "manifest": JSON_OBJECT_SCHEMA,
            },
            "required": ["manifest"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_visual_geometry_context",
        "description": "Return the current visual-review geometry context: target object records, part cages, deterministic defects, metric vector, and hard gates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_visual_geometry",
        "description": "Run deterministic geometry-first review analysis without screenshots or scene mutation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "validate_gpt_asset",
        "description": "Run automatic evaluated-geometry asset validation on the selected objects or visible scene. Returns inferred contacts, overlaps, floaters, topology issues, metric vector, and hard gates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_only": {"type": "boolean"},
                "run_id": {"type": "string"},
                "settings": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_constraint_graph",
        "description": "Return the current asset constraint graph built from the intent manifest and inferred geometry relationships, including support, contact, alignment, and exclusion edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "selected_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_validation_report",
        "description": "Return the latest or requested automatic asset-validation report.",
        "inputSchema": {
            "type": "object",
            "properties": {"report_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_validation_reports",
        "description": "List recent automatic asset-validation reports tied to visual-review runs.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_repair_plan",
        "description": "Return a bounded safe repair plan derived from the latest validation issues and intent manifest. Destructive repairs remain gated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "selected_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_geometry_review_viewpoints",
        "description": "Plan scored optimization and held-out audit viewpoints from exact scene/object bounds for automatic visual self-review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_only": {"type": "boolean"},
                "settings": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_visual_review_metrics",
        "description": "Return the latest visual-review geometry metrics, hard gates, defects, and view scores for a run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_visual_review_runs",
        "description": "List recent visual self-review runs and their scores, phases, screenshots, and stop reasons.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_visual_review_run",
        "description": "Read one visual self-review run manifest including screenshots, critiques, scores, and next prompts.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_visual_review_viewpoints",
        "description": "Plan geometry-aware screenshot viewpoints from selected-object bounds or visible-scene bounds without capturing images. Returns scored optimization/audit views, geometry digest, and defects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_only": {"type": "boolean"},
                "max_detail_views": {"type": "integer", "minimum": 0, "maximum": 12},
                "settings": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_safe_asset_repair",
        "description": "Apply only safe, bounded asset repair actions derived from the repair plan. Destructive mesh edits remain policy-gated and should not be executed by this tool unless explicitly approved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "repair_plan": JSON_OBJECT_SCHEMA,
                "apply_all_safe": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "capture_scene_viewpoints",
        "description": "Capture viewport/OpenGL screenshots from planned or supplied review viewpoints into a local cache directory and attach automatic asset-validation metrics. This is preview-safe cache capture, not a persistent user export.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "resolution": {"type": "integer", "minimum": 128, "maximum": 4096},
                "max_viewpoints": {"type": "integer", "minimum": 1, "maximum": 16},
                "selected_only": {"type": "boolean"},
                "use_geometry_planner": {"type": "boolean"},
                "geometry_settings": {"type": "object", "additionalProperties": True},
                "viewpoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "kind": {"type": "string"},
                            "target": VECTOR3_SCHEMA,
                            "camera_location": VECTOR3_SCHEMA,
                            "focal_length": {"type": "number"},
                            "notes": {"type": "string"},
                        },
                        "required": ["id", "target", "camera_location"],
                        "additionalProperties": True,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "record_visual_review_iteration",
        "description": "Record a visual review pass into the run manifest. The runtime normally does this automatically after critic turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "iteration": {"type": "integer", "minimum": 1},
                "screenshots": {"type": "array", "items": {"type": "string"}},
                "critique": {"anyOf": [{"type": "object"}, {"type": "string"}]},
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "next_prompt": {"type": "string"},
                "summary": {"type": "string"},
                "stop_reason": {"type": "string"},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_workflow_from_intent",
        "description": "Create an unconnected AI Workflow starter graph from a game-creation intent so the graph is AI-managed instead of mandatory upfront.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "graph_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "explain_workflow_graph",
        "description": "Explain the current AI Workflow graph in plain language for game creators.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "simplify_workflow_graph",
        "description": "Return a non-mutating simplification plan for the current AI Workflow graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "create_game_asset_plan",
        "description": "Create a concise AI-managed plan for turning the current selection into a game-ready asset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_type": {"type": "string"},
                "target_engine": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_game_asset_action",
        "description": "Route a game-asset action through the configured execution friction policy. Local reversible changes may run with receipts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "explain_addon_step",
        "description": "Explain the next useful add-on step in chat form for the current game-creation context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "classify_user_intent",
        "description": "Classify a user prompt into ask, inspect, change, automate, recover, or export with visible risk axes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "tool_name": {"type": "string"},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_action_cards",
        "description": "List visible AI action cards for the active project, optionally filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_action_detail",
        "description": "Read one action card with its full stored prompt, plan, arguments, affected targets, result, and recovery detail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_action_card",
        "description": "Create an inspectable action card before risky scene-changing work. Use this to externalize plan, affected targets, approval state, and recovery path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "prompt": {"type": "string"},
                "plan": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments": {"type": "object"},
                "affected_targets": {"type": "array", "items": {"type": "string"}},
                "required_context": {"type": "array", "items": {"type": "string"}},
                "kind": {"type": "string", "enum": ["inspect", "change", "automate", "recover", "export"]},
                "risk": {"type": "string", "enum": ACTION_RISKS},
                "risk_rationale": {"type": "string"},
                "risk_axes": {"type": "object"},
                "status": {"type": "string", "enum": ACTION_STATUSES},
                "scope_summary": {"type": "string"},
                "outcome_summary": {"type": "string"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "dependencies": {"type": "array", "items": {"type": "string"}},
                "preview_summary": {"type": "string"},
                "short_plan": {"type": "array", "items": {"type": "string"}},
                "full_plan": {"type": "string"},
                "approval_policy": {"type": "string"},
                "result_summary": {"type": "string"},
                "recovery": {"type": "string"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_action_status",
        "description": "Update an existing action card after planning, approval, execution, failure, cancellation, or recovery.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "status": {"type": "string", "enum": ACTION_STATUSES},
                "result_summary": {"type": "string"},
                "recovery": {"type": "string"},
                "plan": {"type": "string"},
            },
            "required": ["action_id", "status"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_action_card_plan",
        "description": "Update an action card's visible operational plan, preview summary, plan revision, and plan diff without mutating Blender.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "status": {"type": "string", "enum": ACTION_STATUSES},
                "plan": {"type": "string"},
                "preview_summary": {"type": "string"},
                "short_plan": {"type": "array", "items": {"type": "string"}},
                "full_plan": {"type": "string"},
                "plan_revision": {"type": "integer", "minimum": 1},
                "plan_diff": {"type": "string"},
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_action_card",
        "description": "Prepare a non-mutating preview summary for an existing action card.",
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string"}},
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_action_approval",
        "description": "Move an action card into awaiting approval with a concise user-facing summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string"}, "summary": {"type": "string"}},
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_action_step",
        "description": "Record visible per-step tool activity on an action card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "tool": {"type": "string"},
                "phase": {"type": "string"},
                "status": {"type": "string"},
                "summary": {"type": "string"},
                "targets": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_action_warning",
        "description": "Attach a visible warning to an action card.",
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string"}, "warning": {"type": "string"}},
            "required": ["action_id", "warning"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_action_result",
        "description": "Record the final or partial result summary for an action card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "status": {"type": "string", "enum": ACTION_STATUSES},
                "result_summary": {"type": "string"},
                "recovery": {"type": "string"},
            },
            "required": ["action_id", "result_summary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_action_failure",
        "description": "Record a failed action-card step with a user-facing recovery path.",
        "inputSchema": {
            "type": "object",
            "properties": {"action_id": {"type": "string"}, "error": {"type": "string"}, "recovery": {"type": "string"}},
            "required": ["action_id", "error"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pin_output_to_thread",
        "description": "Pin an important result, artifact, recipe, or explanation to the current thread so it remains visible outside the raw transcript.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "kind": {"type": "string"},
                "action_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["title", "summary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_blender_surfaces",
        "description": "Return currently open Blender editor surfaces, common surface types, active object/mode, and selection so operator calls can target the right context.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_cached_operator_namespaces",
        "description": "Return cached bpy.ops namespaces and a compact sample of operator names for efficient operator targeting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit_per_namespace": {"type": "integer", "minimum": 1, "maximum": 250},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_thread_context",
        "description": "Read stored dashboard thread summary and recent full messages by thread id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["thread_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_project_note",
        "description": "Write or replace the current dashboard project's note/memory text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "diagnose_ai_studio_workspace",
        "description": "Report AI Studio workspace existence, order, active workspace, tag state, native editor layout, and Layout preservation.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "diagnose_dashboard_workspace",
        "description": "Compatibility alias for diagnose_ai_studio_workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_workflow_graphs",
        "description": "List Codex AI Workflow node graphs in the current Blender file.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_workflow_graph",
        "description": "Create or reuse a Codex AI Workflow graph. Default is blank; set with_default_nodes only for explicit legacy starter nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "with_default_nodes": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "add_workflow_node",
        "description": "Add a callable node to a Codex AI Workflow graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "node_type": {"type": "string", "enum": WORKFLOW_NODE_TYPES},
                "label": {"type": "string"},
            },
            "required": ["node_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "connect_workflow_nodes",
        "description": "Connect two Codex AI Workflow nodes by socket name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "from_node": {"type": "string"},
                "from_socket": {"type": "string"},
                "to_node": {"type": "string"},
                "to_socket": {"type": "string"},
            },
            "required": ["from_node", "to_node"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_workflow_node_config",
        "description": "Configure a workflow node with tool name, JSON arguments, memory query, and approval behavior.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "node_name": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments_json": {"type": "string"},
                "memory_query": {"type": "string"},
                "approval_required": {"type": "boolean"},
                "config": {"type": "object"},
            },
            "required": ["node_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_workflow_graph",
        "description": "Inspect a Codex AI Workflow graph including nodes, links, configuration, and recent results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "include_results": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "run_workflow_graph",
        "description": "Preview or run a Codex AI Workflow graph serially on Blender's main thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "preview_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "validate_workflow_graph",
        "description": "Validate a typed v0.10 Workflow graph for reachability, socket compatibility, approval requirements, cycles, and unsafe nodes without execution.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "compile_workflow_graph",
        "description": "Compile a typed v0.10 Workflow graph into a durable run plan without mutating Blender.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_workflow_node",
        "description": "Preview one workflow node's plan, risk, sockets, and dry-run availability without side effects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "node_name": {"type": "string"},
            },
            "required": ["node_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_workflow_graph",
        "description": "Run the v0.10 safe preview path for a Workflow graph; preview creates review cards for risky nodes but never mutates, publishes, or writes memory.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "start_workflow_run",
        "description": "Start a checkpointed workflow run. Risky nodes pause into action cards until the user approves them.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "resume_workflow_run",
        "description": "Resume a paused or waiting workflow run after approval, rejecting stale snapshot/card state when needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stop_workflow_run",
        "description": "Stop a workflow run at the next safe checkpoint and mark it paused or partial.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_workflow_runs",
        "description": "List durable v0.10 workflow runs from the SQLite authority store.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_workflow_run_detail",
        "description": "Read a workflow run with node states, checkpoints, card links, and execution payload.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish_workflow_recipe",
        "description": "Publish the current Workflow graph as a versioned recipe manifest in the workflow authority store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_workflow_recipes",
        "description": "List published Workflow recipe versions, optionally for one recipe id.",
        "inputSchema": {
            "type": "object",
            "properties": {"recipe_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_workflow_recipe_detail",
        "description": "Read a published Workflow recipe version with manifest metadata and tests.",
        "inputSchema": {
            "type": "object",
            "properties": {"recipe_version_uid": {"type": "string"}},
            "required": ["recipe_version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_workflow_patch",
        "description": "Create a staged AI graph-edit patch proposal from structured operations; does not mutate the live graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "operations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_workflow_patch",
        "description": "Preview the graph diff and contract diff for a structured workflow patch proposal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "operations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_workflow_patch",
        "description": "Apply a validated structured workflow patch to the live Blender node tree after explicit approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "operations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_scene_summary",
        "description": "Return a compact summary of the current Blender scene.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_selection",
        "description": "Return the currently selected Blender objects.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_data_blocks",
        "description": "List Blender data-blocks such as objects, meshes, materials, armatures, collections, actions, cameras, and lights.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {"type": "string", "enum": DATA_BLOCK_TYPES},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["data_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_object_details",
        "description": "Return detailed object data including transforms, mesh/material/modifier/parent/animation metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {"object_name": {"type": "string"}},
            "required": ["object_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_blender_property",
        "description": "Read an RNA property from a Blender data-block by data path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_type": {
                    "type": "string",
                    "description": "RNA target kind. Supports object, active_object, object_data, active_material, scene, world, view_layer, modifier, pose_bone, and most bpy.data collection names such as mesh, material, image, action, node_group, text, camera, light, collection.",
                },
                "target_name": {"type": "string"},
                "data_path": {"type": "string"},
            },
            "required": ["target_type", "data_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_blender_property",
        "description": "Set an RNA property on a Blender data-block by data path. Use this for structured data edits when a specialized tool does not exist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_type": {
                    "type": "string",
                    "description": "RNA target kind. Supports object, active_object, object_data, active_material, scene, world, view_layer, modifier, pose_bone, and most bpy.data collection names such as mesh, material, image, action, node_group, text, camera, light, collection.",
                },
                "target_name": {"type": "string"},
                "data_path": {"type": "string"},
                "value": {},
            },
            "required": ["target_type", "data_path", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_primitive",
        "description": "Create a Blender mesh primitive.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "primitive": {"type": "string", "enum": PRIMITIVE_TYPES},
                "name": {"type": "string"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
            },
            "required": ["primitive"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_mesh_object",
        "description": "Create a custom mesh object from vertices, edges, and faces.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "vertices": {"type": "array", "items": VECTOR3_SCHEMA, "minItems": 1},
                "edges": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}},
                "faces": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3}},
                "collection_name": {"type": "string"},
                "material_name": {"type": "string"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
            },
            "required": ["name", "vertices"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_empty",
        "description": "Create an empty/helper object for layout, rig controls, pivots, or organization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "empty_display_type": {"type": "string", "enum": EMPTY_TYPES},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rename_object",
        "description": "Rename an existing Blender object.",
        "inputSchema": {
            "type": "object",
            "properties": {"object_name": {"type": "string"}, "new_name": {"type": "string"}},
            "required": ["object_name", "new_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "duplicate_object",
        "description": "Duplicate an object, optionally duplicating its mesh data and assigning a new transform.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "new_name": {"type": "string"},
                "linked_data": {"type": "boolean"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
            },
            "required": ["object_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_transform",
        "description": "Set location, rotation, or scale for an existing Blender object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
            },
            "required": ["object_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_custom_property",
        "description": "Set a custom property on a Blender object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "property_name": {"type": "string"},
                "value": {},
            },
            "required": ["object_name", "property_name", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_object_visibility",
        "description": "Set viewport/render visibility and display type for an object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "hide_viewport": {"type": "boolean"},
                "hide_render": {"type": "boolean"},
                "display_type": {"type": "string", "enum": ["TEXTURED", "SOLID", "WIRE", "BOUNDS"]},
            },
            "required": ["object_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_parent",
        "description": "Set or clear an object's parent, including optional bone parenting and keep-transform behavior.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "child_name": {"type": "string"},
                "parent_name": {"type": "string"},
                "parent_type": {"type": "string", "enum": ["OBJECT", "ARMATURE", "BONE"]},
                "parent_bone": {"type": "string"},
                "keep_transform": {"type": "boolean"},
            },
            "required": ["child_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_vertex_group",
        "description": "Create or reuse a vertex group on a mesh object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "group_name": {"type": "string"},
                "replace_existing": {"type": "boolean"},
            },
            "required": ["object_name", "group_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "assign_vertex_group",
        "description": "Assign vertices to a mesh vertex group with a weight.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "group_name": {"type": "string"},
                "vertex_indices": {"type": "array", "items": {"type": "integer"}},
                "all_vertices": {"type": "boolean"},
                "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "mode": {"type": "string", "enum": VERTEX_GROUP_MODES},
            },
            "required": ["object_name", "group_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_object",
        "description": "Delete one or more Blender objects by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "required": ["object_names"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_collection",
        "description": "Create a collection and link it to the scene or another collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "parent_collection": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "move_object_to_collection",
        "description": "Move or link an object into a collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "collection_name": {"type": "string"},
                "unlink_from_other_collections": {"type": "boolean"},
            },
            "required": ["object_name", "collection_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_material",
        "description": "Create or update a material with common Principled BSDF properties.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "base_color": VECTOR4_SCHEMA,
                "metallic": {"type": "number"},
                "roughness": {"type": "number"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "assign_material",
        "description": "Assign an existing material to one or more objects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "material_name": {"type": "string"},
                "slot_index": {"type": "integer", "minimum": 0},
            },
            "required": ["object_names", "material_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_modifier",
        "description": "Add a modifier to an object and set simple modifier properties.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "modifier_type": {"type": "string"},
                "name": {"type": "string"},
                "properties": {"type": "object"},
            },
            "required": ["object_name", "modifier_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_modifier",
        "description": "Remove a modifier from an object.",
        "inputSchema": {
            "type": "object",
            "properties": {"object_name": {"type": "string"}, "modifier_name": {"type": "string"}},
            "required": ["object_name", "modifier_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_modifier",
        "description": "Apply a modifier to an object.",
        "inputSchema": {
            "type": "object",
            "properties": {"object_name": {"type": "string"}, "modifier_name": {"type": "string"}},
            "required": ["object_name", "modifier_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_light",
        "description": "Create a Blender light.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "light_type": {"type": "string", "enum": ["POINT", "SUN", "SPOT", "AREA"]},
                "location": VECTOR3_SCHEMA,
                "energy": {"type": "number"},
                "color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            },
            "required": ["name", "light_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_camera",
        "description": "Create a Blender camera and optionally make it active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "focal_length": {"type": "number"},
                "make_active": {"type": "boolean"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insert_keyframe",
        "description": "Insert a keyframe for an object data path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string"},
                "data_path": {"type": "string"},
                "frame": {"type": "number"},
            },
            "required": ["object_name", "data_path", "frame"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_frame_range",
        "description": "Set the scene frame start, end, and optionally current frame.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "frame_start": {"type": "integer"},
                "frame_end": {"type": "integer"},
                "frame_current": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_armature_summary",
        "description": "Inspect an armature, including bones, parent hierarchy, deform flags, and pose bones.",
        "inputSchema": {
            "type": "object",
            "properties": {"armature_name": {"type": "string"}},
            "required": ["armature_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_armature_bone",
        "description": "Add an edit bone to an armature, including head/tail, parent, and deform flag.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "armature_name": {"type": "string"},
                "bone_name": {"type": "string"},
                "head": VECTOR3_SCHEMA,
                "tail": VECTOR3_SCHEMA,
                "parent": {"type": "string"},
                "use_deform": {"type": "boolean"},
            },
            "required": ["armature_name", "bone_name", "head", "tail"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_bone_deform",
        "description": "Enable or disable deform export/use on one or more armature bones.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "armature_name": {"type": "string"},
                "bone_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "use_deform": {"type": "boolean"},
            },
            "required": ["armature_name", "bone_names", "use_deform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_armature_bones",
        "description": "Delete edit bones from an armature by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "armature_name": {"type": "string"},
                "bone_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "required": ["armature_name", "bone_names"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_pose_bone_transform",
        "description": "Set a pose bone transform for animation/rig manipulation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "armature_name": {"type": "string"},
                "bone_name": {"type": "string"},
                "location": VECTOR3_SCHEMA,
                "rotation_euler": VECTOR3_SCHEMA,
                "scale": VECTOR3_SCHEMA,
                "insert_keyframe": {"type": "boolean"},
                "frame": {"type": "number"},
            },
            "required": ["armature_name", "bone_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "import_file",
        "description": "Import common 3D files into Blender, including FBX, OBJ, and glTF/GLB.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "file_type": {"type": "string", "enum": ["auto", "fbx", "obj", "gltf", "glb"]},
            },
            "required": ["filepath"],
            "additionalProperties": False,
        },
    },
    {
        "name": "export_fbx",
        "description": "Export selected or named objects to FBX with explicit armature/export settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "object_names": {"type": "array", "items": {"type": "string"}},
                "use_selection": {"type": "boolean"},
                "add_leaf_bones": {"type": "boolean"},
                "use_armature_deform_only": {"type": "boolean"},
                "bake_anim": {"type": "boolean"},
                "object_types": {"type": "array", "items": {"type": "string"}},
                "axis_forward": {"type": "string"},
                "axis_up": {"type": "string"},
            },
            "required": ["filepath"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_blender_operators",
        "description": "Discover Blender bpy.ops operators by namespace/search text. Use this to find tools across Blender surfaces such as object, mesh, armature, pose, sculpt, UV, node, animation, render, import/export, and window-manager tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "search": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                "include_poll": {"type": "boolean"},
                "area_type": {"type": "string"},
                "region_type": {"type": "string"},
                "active_object": {"type": "string"},
                "selected_objects": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "switch_area_if_missing": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_blender_operator",
        "description": "Inspect one bpy.ops operator, including RNA metadata, properties, enum values, defaults, description, and current poll result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "area_type": {"type": "string"},
                "region_type": {"type": "string"},
                "active_object": {"type": "string"},
                "selected_objects": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "switch_area_if_missing": {"type": "boolean"},
            },
            "required": ["operator"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_blender_operator_poll",
        "description": "Check whether a bpy.ops operator can run in the requested context before calling it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "area_type": {"type": "string"},
                "region_type": {"type": "string"},
                "active_object": {"type": "string"},
                "selected_objects": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "switch_area_if_missing": {"type": "boolean"},
            },
            "required": ["operator"],
            "additionalProperties": False,
        },
    },
    {
        "name": "call_blender_operator",
        "description": "Call any bpy.ops operator by id with JSON properties and optional context setup. This is the universal bridge to Blender tools across all editor surfaces.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "properties": {"type": "object"},
                "execution_context": {"type": "string", "enum": OPERATOR_EXECUTION_CONTEXTS},
                "area_type": {"type": "string"},
                "region_type": {"type": "string"},
                "active_object": {"type": "string"},
                "selected_objects": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "switch_area_if_missing": {"type": "boolean"},
                "poll_first": {"type": "boolean"},
            },
            "required": ["operator"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_blender_python",
        "description": "Expert tool: execute Blender Python on the main thread. Requires Expert Tools enabled in add-on preferences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "undo",
        "description": "Undo one or more Blender operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_toolbox_items",
        "description": "List stored reusable Blender memories, mesh recipes, workflows, and systems.",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string", "enum": TOOLBOX_CATEGORIES}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_toolbox_item",
        "description": "Read one stored toolbox memory/system by id or name.",
        "inputSchema": {
            "type": "object",
            "properties": {"item_id_or_name": {"type": "string"}},
            "required": ["item_id_or_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_toolbox_item",
        "description": "Store a reusable mesh recipe, workflow, system, note, or script in the local visible toolbox memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string", "enum": TOOLBOX_CATEGORIES},
                "description": {"type": "string"},
                "content": {},
                "tags": {"type": "array", "items": {"type": "string"}},
                "item_id": {"type": "string"},
            },
            "required": ["name", "category", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_toolbox_system",
        "description": "Run a stored toolbox recipe made of safe Blender tool calls.",
        "inputSchema": {
            "type": "object",
            "properties": {"item_id_or_name": {"type": "string"}},
            "required": ["item_id_or_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_items",
        "description": "List stored asset-library items, including copied files, file references, and selected-object .blend bundles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ASSET_CATEGORIES},
                "kind": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_context",
        "description": "Return compact AI Assets state: registered libraries, stored asset items, selected asset row, pinned outputs, recent asset actions, and current card-first guidance.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_ai_assets",
        "description": "Search the SQLite AI Assets authority store with FTS and lifecycle facets. This is read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ASSET_CATEGORIES},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_ai_asset_libraries",
        "description": "List AI-owned asset libraries and their catalog/index state from the local authority store.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_versions",
        "description": "List immutable AI Assets versions by kind/status for reuse, validation, publishing, or import review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ASSET_CATEGORIES},
                "status": {"type": "string"},
                "library_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_version_detail",
        "description": "Read full metadata, Blender artifact refs, dependency health, provenance, QA, and package state for one AI Assets version.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_dependencies",
        "description": "List dependency edges for one AI Assets version.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_asset_provenance",
        "description": "List provenance entities, activities, and relations for one AI Assets version.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_asset_publish_action",
        "description": "Create a reviewable action card for promoting selected Blender content into an AI Assets version. Does not write files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ASSET_CATEGORIES},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "promote_output_snapshot",
        "description": "Promote an existing output snapshot into a draft immutable AI Assets version record.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["output_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "validate_asset_version",
        "description": "Validate an AI Assets version for required metadata, license, payload, preview, dependencies, and compatibility.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish_asset_package",
        "description": "Publish an approved AI Assets version as a portable package zip. Requires an approved running action card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "version_uid": {"type": "string"},
                "package_dir": {"type": "string"},
            },
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "import_asset_package",
        "description": "Import a portable AI Assets package into an AI-owned library after manifest/hash/catalog validation. Requires an approved running action card.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_path": {"type": "string"},
                "library_id": {"type": "string"},
            },
            "required": ["package_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pin_asset_version",
        "description": "Pin an immutable AI Assets version into project, thread, or toolbox memory without copying its payload.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "version_uid": {"type": "string"},
                "scope": {"type": "string", "enum": ["project", "thread", "toolbox"]},
                "reason": {"type": "string"},
            },
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fork_asset_version",
        "description": "Create a draft derived asset version record from an existing immutable version.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "version_uid": {"type": "string"},
                "new_version": {"type": "string"},
            },
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "append_asset_version",
        "description": "Append an AI Assets version into the current scene. Requires an approved running action card.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "link_asset_version",
        "description": "Link an AI Assets version into the current scene. Requires an approved running action card.",
        "inputSchema": {
            "type": "object",
            "properties": {"version_uid": {"type": "string"}},
            "required": ["version_uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "diagnose_ai_assets",
        "description": "Return storage, WAL, schema, migration, library, catalog, dependency, package, preview, pin, and online/offline diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_asset_item",
        "description": "Read one stored asset-library item by id or name.",
        "inputSchema": {
            "type": "object",
            "properties": {"item_id_or_name": {"type": "string"}},
            "required": ["item_id_or_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_asset_file",
        "description": "Store an external file in the local asset library, either by copying it into the library or registering a reference to its path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string", "enum": ASSET_CATEGORIES},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "copy_file": {"type": "boolean"},
                "item_id": {"type": "string"},
            },
            "required": ["filepath", "name", "category"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_selected_objects_asset",
        "description": "Save selected or named Blender objects as a reusable .blend asset bundle in the local asset library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string", "enum": ASSET_CATEGORIES},
                "description": {"type": "string"},
                "object_names": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "item_id": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "import_asset_item",
        "description": "Import or load a stored asset-library item into the current Blender scene when its file type is supported.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id_or_name": {"type": "string"},
                "link": {"type": "boolean"},
            },
            "required": ["item_id_or_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "register_blender_asset_library",
        "description": "Register or refresh the Codex Blender Agent directory as a Blender asset library.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_asset_action_card",
        "description": "Create an inspectable AI Assets action card before saving, importing, or publishing assets. Use this to make asset mutations card-first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "prompt": {"type": "string"},
                "plan": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments": {"type": "object"},
                "kind": {"type": "string", "enum": ["inspect", "change", "automate", "recover", "export"]},
                "risk": {"type": "string", "enum": ACTION_RISKS},
                "risk_rationale": {"type": "string"},
                "status": {"type": "string", "enum": ACTION_STATUSES},
                "asset_name": {"type": "string"},
                "asset_category": {"type": "string", "enum": ASSET_CATEGORIES},
                "asset_kind": {"type": "string"},
                "affected_targets": {"type": "array", "items": {"type": "string"}},
                "required_context": {"type": "array", "items": {"type": "string"}},
                "preview_summary": {"type": "string"},
                "outcome_summary": {"type": "string"},
                "recovery": {"type": "string"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_blender_asset_libraries",
        "description": "List Blender asset libraries currently registered in user preferences.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "save_selection_to_asset_library",
        "description": "Save selected or named Blender objects into the registered Codex Blender Agent asset library as a .blend bundle and mirrored metadata item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string", "enum": ASSET_CATEGORIES},
                "description": {"type": "string"},
                "object_names": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "item_id": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "append_asset_from_library",
        "description": "Append or link a stored dashboard asset-library item into the current Blender scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id_or_name": {"type": "string"},
                "link": {"type": "boolean"},
            },
            "required": ["item_id_or_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_checkpoint_copy",
        "description": "Save a checkpoint copy of the current Blender file without changing the active file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
]


def get_dynamic_tool_specs() -> list[dict]:
    return deepcopy(_TOOL_SPECS)
