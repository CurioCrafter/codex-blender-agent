from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup, WindowManager

from .game_creator import EXECUTION_FRICTION_ITEMS
from .model_defaults import DEFAULT_REASONING_EFFORT
from .quick_prompts import quick_prompt_category_items
from .tutorial import walkthrough_items
from .visual_geometry import (
    DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES,
    DEFAULT_AUDIT_VIEW_COUNT,
    DEFAULT_CAMERA_FIT_MARGIN,
    DEFAULT_CANDIDATE_VIEW_COUNT,
    DEFAULT_CRITIC_SCORE_WEIGHT,
    DEFAULT_GEOMETRY_REVIEW_ENABLED,
    DEFAULT_GEOMETRY_SCORE_WEIGHT,
    DEFAULT_MESH_SAMPLES_PER_OBJECT,
    DEFAULT_MINIMUM_COVERAGE_SCORE,
    DEFAULT_SELECTED_CAPTURE_COUNT,
    DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES,
)
from .visual_review import DEFAULT_CAPTURE_MODE, DEFAULT_MAX_ITERATIONS, DEFAULT_SCREENSHOT_RESOLUTION, DEFAULT_TARGET_SCORE
from .workflow_examples import workflow_example_items


def _model_items(self, context):
    from .runtime import get_runtime

    snapshot = get_runtime().service.snapshot()
    if not snapshot.models:
        return [("__none__", "No models loaded", "Start the service to load models", 0)]
    return [
        (model.model_id, model.label, model.description or model.model_id, index)
        for index, model in enumerate(snapshot.models)
    ]


class CODEXBLENDERAGENT_Message(PropertyGroup):
    role: StringProperty(name="Role")
    phase: StringProperty(name="Phase")
    status: StringProperty(name="Status")
    text: StringProperty(name="Text")


class CODEXBLENDERAGENT_Attachment(PropertyGroup):
    path: StringProperty(name="Path", subtype="FILE_PATH")
    kind: StringProperty(name="Kind")


class CODEXBLENDERAGENT_ToolboxItem(PropertyGroup):
    item_id: StringProperty(name="ID")
    name: StringProperty(name="Name")
    category: StringProperty(name="Category")
    description: StringProperty(name="Description")


class CODEXBLENDERAGENT_AssetItem(PropertyGroup):
    item_id: StringProperty(name="ID")
    version_uid: StringProperty(name="Version UID")
    logical_uid: StringProperty(name="Logical UID")
    name: StringProperty(name="Name")
    category: StringProperty(name="Category")
    kind: StringProperty(name="Kind")
    status: StringProperty(name="Status")
    version: StringProperty(name="Version")
    license_spdx: StringProperty(name="License")
    catalog_path: StringProperty(name="Catalog")
    import_policy: StringProperty(name="Import Policy")
    dependency_health: StringProperty(name="Dependencies")
    validation_state: StringProperty(name="Validation")
    provenance_summary: StringProperty(name="Provenance")
    preview_path: StringProperty(name="Preview", subtype="FILE_PATH")
    path: StringProperty(name="Path", subtype="FILE_PATH")
    description: StringProperty(name="Description")


class CODEXBLENDERAGENT_ProjectItem(PropertyGroup):
    project_id: StringProperty(name="Project ID")
    name: StringProperty(name="Name")
    cwd: StringProperty(name="Workspace", subtype="DIR_PATH")
    summary: StringProperty(name="Summary")
    updated_at: StringProperty(name="Updated")


class CODEXBLENDERAGENT_ThreadItem(PropertyGroup):
    thread_id: StringProperty(name="Thread ID")
    project_id: StringProperty(name="Project ID")
    mode: StringProperty(name="Mode")
    title: StringProperty(name="Title")
    summary: StringProperty(name="Summary")
    status: StringProperty(name="Status")
    updated_at: StringProperty(name="Updated")
    message_count: IntProperty(name="Messages", default=0)
    unread: BoolProperty(name="Unread", default=False)


class CODEXBLENDERAGENT_ActionItem(PropertyGroup):
    action_id: StringProperty(name="Action ID")
    name: StringProperty(name="Name")
    operator: StringProperty(name="Operator")
    status: StringProperty(name="Status")
    description: StringProperty(name="Description")


class CODEXBLENDERAGENT_DashboardState(PropertyGroup):
    state_id: StringProperty(name="State ID")
    name: StringProperty(name="Name")
    value: StringProperty(name="Value")
    detail: StringProperty(name="Detail")


class CODEXBLENDERAGENT_ContextChip(PropertyGroup):
    chip_id: StringProperty(name="Chip ID")
    label: StringProperty(name="Label")
    value: StringProperty(name="Value")
    kind: StringProperty(name="Kind")
    detail: StringProperty(name="Detail")
    enabled: BoolProperty(name="Enabled", default=True)


class CODEXBLENDERAGENT_ActionCard(PropertyGroup):
    action_id: StringProperty(name="Action ID")
    title: StringProperty(name="Title")
    kind: StringProperty(name="Kind")
    tool_name: StringProperty(name="Tool")
    status: StringProperty(name="Status")
    risk: StringProperty(name="Risk")
    risk_rationale: StringProperty(name="Risk Rationale")
    approval_policy: StringProperty(name="Approval Policy")
    affected_targets: StringProperty(name="Affected Targets")
    required_context: StringProperty(name="Required Context")
    scope_summary: StringProperty(name="Scope")
    outcome_summary: StringProperty(name="Outcome")
    preview_summary: StringProperty(name="Preview")
    plan_preview: StringProperty(name="Plan")
    tool_activity: StringProperty(name="Tool Activity")
    warnings: StringProperty(name="Warnings")
    result_summary: StringProperty(name="Result")
    recovery: StringProperty(name="Recovery")
    thread_id: StringProperty(name="Thread ID")
    updated_at: StringProperty(name="Updated")
    approval_required: BoolProperty(name="Approval Required", default=False)


class CODEXBLENDERAGENT_PinnedOutput(PropertyGroup):
    output_id: StringProperty(name="Output ID")
    title: StringProperty(name="Title")
    kind: StringProperty(name="Kind")
    summary: StringProperty(name="Summary")
    source_thread_id: StringProperty(name="Thread ID")
    action_id: StringProperty(name="Action ID")
    path: StringProperty(name="Path", subtype="FILE_PATH")
    updated_at: StringProperty(name="Updated")


class CODEXBLENDERAGENT_JobTimelineItem(PropertyGroup):
    event_id: StringProperty(name="Event ID")
    label: StringProperty(name="Label")
    status: StringProperty(name="Status")
    detail: StringProperty(name="Detail")
    created_at: StringProperty(name="Created")


class CODEXBLENDERAGENT_ToolActivityItem(PropertyGroup):
    event_id: StringProperty(name="Event ID")
    lifecycle_id: StringProperty(name="Lifecycle ID")
    tool_name: StringProperty(name="Tool")
    status: StringProperty(name="Status")
    category: StringProperty(name="Category")
    risk: StringProperty(name="Risk")
    summary: StringProperty(name="Summary")
    error: StringProperty(name="Error")
    created_at: StringProperty(name="Created")
    duration_seconds: FloatProperty(name="Duration", default=0.0, min=0.0)
    action_id: StringProperty(name="Action ID")


def _register_window_manager_properties() -> None:
    WindowManager.codex_blender_prompt = StringProperty(
        name="Prompt",
        description="Ask Codex to inspect or edit the current Blender scene.",
        default="",
    )
    WindowManager.codex_blender_model = EnumProperty(
        name="Model",
        description="Codex/GPT model to use for the next turn.",
        items=_model_items,
    )
    WindowManager.codex_blender_effort = EnumProperty(
        name="Reasoning",
        description="Reasoning effort for the next turn.",
        items=[
            ("low", "Low", "Fast responses with lighter reasoning."),
            ("medium", "Medium", "Balanced default."),
            ("high", "High", "Deeper reasoning."),
            ("xhigh", "Extra High", "Maximum reasoning depth."),
        ],
        default=DEFAULT_REASONING_EFFORT,
    )
    WindowManager.codex_blender_include_scene_context = BoolProperty(
        name="Include scene summary",
        description="Send a compact scene digest with each request.",
        default=True,
    )
    WindowManager.codex_blender_chat_mode = EnumProperty(
        name="Chat mode",
        description="Keep separate thread/history lanes for different kinds of work.",
        items=[
            ("scene_agent", "Scene Agent", "Scene-aware Blender agent with edit tools."),
            ("chat_only", "Chat Only", "Normal chat lane without automatic scene context."),
            ("toolbox", "Toolbox", "Reusable systems, recipes, and workflow memory."),
            ("assets", "Assets", "Asset library storage and import/export work."),
        ],
        default="scene_agent",
    )
    WindowManager.codex_blender_intent = EnumProperty(
        name="Intent",
        description="How the composer should route the next prompt.",
        items=[
            ("auto", "Auto", "Classify the prompt automatically."),
            ("ask", "Ask", "Short explanation with no scene changes."),
            ("inspect", "Inspect", "Read-only scene inspection."),
            ("change", "Change", "Create a reviewable card before changing the scene."),
            ("automate", "Automate", "Create a reviewable card for multi-step work."),
            ("recover", "Recover", "Create or run recovery guidance."),
            ("export", "Export", "Create a high-risk card for file/output writes."),
        ],
        default="auto",
    )
    WindowManager.codex_blender_safety_preview_first = BoolProperty(name="Preview First", default=True)
    WindowManager.codex_blender_safety_non_destructive = BoolProperty(name="Non-Destructive", default=True)
    WindowManager.codex_blender_safety_duplicate_first = BoolProperty(name="Duplicate First", default=False)
    WindowManager.codex_blender_safety_no_deletes = BoolProperty(name="No Deletes", default=True)
    WindowManager.codex_blender_safety_require_approval = BoolProperty(name="Require Approval", default=False)
    WindowManager.codex_blender_safety_stop_checkpoints = BoolProperty(name="Stop At Checkpoints", default=True)
    WindowManager.codex_blender_game_creator_mode = BoolProperty(
        name="Game Creator Mode",
        description="Use the chat-first, low-friction game-creation interface by default.",
        default=True,
    )
    WindowManager.codex_blender_execution_friction = EnumProperty(
        name="Execution friction",
        description="How much review UI to put between chat and local Blender work.",
        items=list(EXECUTION_FRICTION_ITEMS),
        default="fast",
    )
    WindowManager.codex_blender_cards_as_receipts = BoolProperty(
        name="Cards as receipts",
        description="Record ordinary completed AI changes as receipts instead of requiring cards first.",
        default=True,
    )
    WindowManager.codex_blender_require_additive_approval = BoolProperty(
        name="Approve additive actions",
        description="Require approval even for local reversible/additive game-creation work.",
        default=False,
    )
    WindowManager.codex_blender_show_advanced_governance = BoolProperty(
        name="Show advanced governance",
        description="Show legacy safety chips, package controls, and detailed card-first governance in everyday panels.",
        default=False,
    )
    WindowManager.codex_blender_quick_prompt_category = EnumProperty(
        name="Quick prompt group",
        description="Filter game-creator quick prompts.",
        items=[("all", "All", "")] + quick_prompt_category_items(),
        default="start",
    )
    WindowManager.codex_blender_target_engine = EnumProperty(
        name="Target engine",
        description="Default game engine target for export and readiness prompts.",
        items=[
            ("generic", "Generic", ""),
            ("unity", "Unity", ""),
            ("unreal", "Unreal", ""),
            ("godot", "Godot", ""),
            ("web", "Web/GLB", ""),
        ],
        default="generic",
    )
    WindowManager.codex_blender_game_style = StringProperty(
        name="Game style",
        description="Optional style hint sent with quick prompts.",
        default="",
    )
    WindowManager.codex_blender_visual_review_enabled = BoolProperty(
        name="Visual self-review",
        description="Enable the screenshot, critique, and improve loop for game creation.",
        default=True,
    )
    WindowManager.codex_blender_visual_review_auto_after_scene_change = BoolProperty(
        name="Auto review scene changes",
        description="Automatically run visual and geometry self-review after scene-changing chat sends.",
        default=True,
    )
    WindowManager.codex_blender_visual_review_max_iterations = IntProperty(
        name="Max passes",
        description="Maximum creator/critic passes for Improve with screenshots.",
        default=DEFAULT_MAX_ITERATIONS,
        min=1,
        max=12,
    )
    WindowManager.codex_blender_visual_review_target_score = FloatProperty(
        name="Target score",
        description="Stop the visual self-review loop when this score is reached.",
        default=DEFAULT_TARGET_SCORE,
        min=0.0,
        max=1.0,
    )
    WindowManager.codex_blender_visual_review_resolution = IntProperty(
        name="Screenshot size",
        description="Square viewport screenshot resolution for visual self-review.",
        default=DEFAULT_SCREENSHOT_RESOLUTION,
        min=128,
        max=4096,
    )
    WindowManager.codex_blender_visual_review_capture_mode = EnumProperty(
        name="Capture mode",
        description="Screenshot capture method for visual self-review.",
        items=[("viewport", "Viewport", "Fast viewport/OpenGL screenshot capture")],
        default=DEFAULT_CAPTURE_MODE,
    )
    WindowManager.codex_blender_visual_review_active_run_id = StringProperty(name="Active visual review", default="")
    WindowManager.codex_blender_visual_review_phase = StringProperty(name="Visual review phase", default="idle")
    WindowManager.codex_blender_visual_review_current_pass = IntProperty(name="Visual review pass", default=0, min=0)
    WindowManager.codex_blender_visual_review_current_score = FloatProperty(name="Visual review score", default=0.0, min=0.0, max=1.0)
    WindowManager.codex_blender_visual_review_stop_requested = BoolProperty(name="Visual review stop requested", default=False)
    WindowManager.codex_blender_visual_review_auto_started = BoolProperty(name="Visual review auto started", default=False)
    WindowManager.codex_blender_asset_validation_latest_report_id = StringProperty(name="Latest validation report", default="")
    WindowManager.codex_blender_asset_validation_latest_summary = StringProperty(name="Latest validation summary", default="")
    WindowManager.codex_blender_asset_validation_latest_score = FloatProperty(name="Latest validation score", default=0.0, min=0.0, max=100.0)
    WindowManager.codex_blender_asset_validation_latest_issue_count = IntProperty(name="Latest validation issues", default=0, min=0)
    WindowManager.codex_blender_asset_validation_latest_critical_count = IntProperty(name="Latest critical validation issues", default=0, min=0)
    WindowManager.codex_blender_web_console_running = BoolProperty(name="Web console running", default=False)
    WindowManager.codex_blender_web_console_url = StringProperty(name="Web console URL", default="")
    WindowManager.codex_blender_web_console_port = IntProperty(name="Web console port", default=0, min=0)
    WindowManager.codex_blender_web_console_error = StringProperty(name="Web console error", default="")
    WindowManager.codex_blender_web_console_auto_started = BoolProperty(name="Web console auto-started", default=False)
    WindowManager.codex_blender_visual_review_automatic_geometry_review = BoolProperty(
        name="Automatic geometry review",
        description="Use geometry-aware view planning and deterministic metrics in Improve with screenshots.",
        default=DEFAULT_GEOMETRY_REVIEW_ENABLED,
    )
    WindowManager.codex_blender_visual_review_candidate_view_count = IntProperty(
        name="Candidate views",
        default=DEFAULT_CANDIDATE_VIEW_COUNT,
        min=8,
        max=256,
    )
    WindowManager.codex_blender_visual_review_selected_capture_count = IntProperty(
        name="Selected captures",
        default=DEFAULT_SELECTED_CAPTURE_COUNT,
        min=1,
        max=16,
    )
    WindowManager.codex_blender_visual_review_audit_view_count = IntProperty(
        name="Audit captures",
        default=DEFAULT_AUDIT_VIEW_COUNT,
        min=0,
        max=8,
    )
    WindowManager.codex_blender_visual_review_mesh_samples_per_object = IntProperty(
        name="Mesh samples per object",
        default=DEFAULT_MESH_SAMPLES_PER_OBJECT,
        min=16,
        max=4096,
    )
    WindowManager.codex_blender_visual_review_minimum_coverage_score = FloatProperty(
        name="Minimum coverage",
        default=DEFAULT_MINIMUM_COVERAGE_SCORE,
        min=0.0,
        max=1.0,
    )
    WindowManager.codex_blender_visual_review_geometry_score_weight = FloatProperty(
        name="Geometry score weight",
        default=DEFAULT_GEOMETRY_SCORE_WEIGHT,
        min=0.0,
        max=1.0,
    )
    WindowManager.codex_blender_visual_review_critic_score_weight = FloatProperty(
        name="Critic score weight",
        default=DEFAULT_CRITIC_SCORE_WEIGHT,
        min=0.0,
        max=1.0,
    )
    WindowManager.codex_blender_visual_review_camera_fit_margin = FloatProperty(
        name="Camera fit margin",
        default=DEFAULT_CAMERA_FIT_MARGIN,
        min=1.0,
        max=2.0,
    )
    WindowManager.codex_blender_visual_review_view_angular_separation_degrees = FloatProperty(
        name="Optimization view separation",
        default=DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES,
        min=0.0,
        max=90.0,
    )
    WindowManager.codex_blender_visual_review_audit_angular_separation_degrees = FloatProperty(
        name="Audit view separation",
        default=DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES,
        min=0.0,
        max=120.0,
    )
    WindowManager.codex_blender_visible_message_count = IntProperty(
        name="Visible messages",
        description="Number of recent transcript messages to draw. Lower values reduce Blender UI lag.",
        default=8,
        min=0,
        max=80,
    )
    WindowManager.codex_blender_show_transcript = BoolProperty(
        name="Show transcript",
        description="Draw transcript messages in the panel. Disable this when long messages make Blender sluggish.",
        default=True,
    )
    WindowManager.codex_blender_attachment_path = StringProperty(
        name="Attachment",
        description="Path to an image or file to include with the next chat message.",
        default="",
        subtype="FILE_PATH",
    )
    WindowManager.codex_blender_attachments = CollectionProperty(type=CODEXBLENDERAGENT_Attachment)
    WindowManager.codex_blender_connection = StringProperty(name="Connection", default="Service stopped.")
    WindowManager.codex_blender_account = StringProperty(name="Account", default="")
    WindowManager.codex_blender_plan = StringProperty(name="Plan", default="")
    WindowManager.codex_blender_thread = StringProperty(name="Thread", default="")
    WindowManager.codex_blender_activity = StringProperty(name="Activity", default="")
    WindowManager.codex_blender_pending = BoolProperty(name="Pending", default=False)
    WindowManager.codex_blender_error = StringProperty(name="Error", default="")
    WindowManager.codex_blender_error_title = StringProperty(name="Error title", default="")
    WindowManager.codex_blender_error_severity = StringProperty(name="Error severity", default="")
    WindowManager.codex_blender_error_recovery = StringProperty(name="Error recovery", default="")
    WindowManager.codex_blender_error_raw = StringProperty(name="Raw error", default="")
    WindowManager.codex_blender_error_retry = StringProperty(name="Error retry", default="")
    WindowManager.codex_blender_stream_recovering = BoolProperty(name="Stream recovering", default=False)
    WindowManager.codex_blender_dashboard_busy = BoolProperty(name="Dashboard busy", default=False)
    WindowManager.codex_blender_dashboard_progress = FloatProperty(name="Dashboard progress", default=0.0, min=0.0, max=1.0)
    WindowManager.codex_blender_redraw_paused = BoolProperty(name="Pause transcript redraw", default=False)
    WindowManager.codex_blender_active_project_id = StringProperty(name="Active project", default="")
    WindowManager.codex_blender_project_index = IntProperty(name="Project index", default=-1, min=-1)
    WindowManager.codex_blender_active_thread_id = StringProperty(name="Active thread", default="")
    WindowManager.codex_blender_thread_index = IntProperty(name="Thread index", default=-1, min=-1)
    WindowManager.codex_blender_action_index = IntProperty(name="Action index", default=-1, min=-1)
    WindowManager.codex_blender_dashboard_state_index = IntProperty(name="Dashboard state index", default=-1, min=-1)
    WindowManager.codex_blender_toolbox_index = IntProperty(name="Toolbox index", default=-1, min=-1)
    WindowManager.codex_blender_asset_index = IntProperty(name="Asset index", default=-1, min=-1)
    WindowManager.codex_blender_projects = CollectionProperty(type=CODEXBLENDERAGENT_ProjectItem)
    WindowManager.codex_blender_threads = CollectionProperty(type=CODEXBLENDERAGENT_ThreadItem)
    WindowManager.codex_blender_actions = CollectionProperty(type=CODEXBLENDERAGENT_ActionItem)
    WindowManager.codex_blender_dashboard_state = CollectionProperty(type=CODEXBLENDERAGENT_DashboardState)
    WindowManager.codex_blender_messages = CollectionProperty(type=CODEXBLENDERAGENT_Message)
    WindowManager.codex_blender_message_index = IntProperty(default=-1)
    WindowManager.codex_blender_toolbox_items = CollectionProperty(type=CODEXBLENDERAGENT_ToolboxItem)
    WindowManager.codex_blender_show_toolbox = BoolProperty(name="Show toolbox memory", default=True)
    WindowManager.codex_blender_toolbox_facet = EnumProperty(
        name="Toolbox group",
        description="Filter reusable toolbox recipes by production intent.",
        items=[
            ("all", "All", "Show all reusable systems and recipes."),
            ("generate", "Generate", "Creation recipes and generators."),
            ("modify", "Modify", "Scene, object, and mesh modification recipes."),
            ("materials", "Materials", "Material, shader, and texture recipes."),
            ("rig", "Rig", "Rigging and armature recipes."),
            ("animate", "Animate", "Animation and timeline recipes."),
            ("organize", "Organize", "Collection, naming, and scene organization recipes."),
            ("optimize", "Optimize", "Cleanup, performance, and quality recipes."),
            ("export", "Export", "Export and delivery recipes."),
            ("debug", "Debug", "Diagnostics, inspection, and repair recipes."),
        ],
        default="all",
    )
    WindowManager.codex_blender_asset_items = CollectionProperty(type=CODEXBLENDERAGENT_AssetItem)
    WindowManager.codex_blender_show_assets = BoolProperty(name="Show asset library", default=True)
    WindowManager.codex_blender_asset_name = StringProperty(name="Asset name", default="")
    WindowManager.codex_blender_ai_assets_search = StringProperty(name="Search AI Assets", default="")
    WindowManager.codex_blender_ai_assets_kind_filter = EnumProperty(
        name="Kind",
        description="Filter AI Assets by reusable asset kind.",
        items=[
            ("all", "All", "All asset kinds."),
            ("model", "Models", "Model, collection, prop, and environment assets."),
            ("material", "Materials", "Material assets."),
            ("rig", "Rigs", "Rig and armature assets."),
            ("pose", "Poses", "Pose assets."),
            ("node_system", "Node Systems", "Geometry, shader, and compositor node group assets."),
            ("recipe", "Recipes", "Reusable workflow recipes."),
            ("prompt", "Prompts", "Reusable AI prompts."),
            ("output", "Outputs", "Approved and published generated outputs."),
            ("other", "Other", "Other reusable records."),
        ],
        default="all",
    )
    WindowManager.codex_blender_ai_assets_status_filter = EnumProperty(
        name="Status",
        description="Filter AI Assets by lifecycle state.",
        items=[
            ("all", "All", "All statuses."),
            ("draft", "Draft", "Draft assets and migrated records."),
            ("approved", "Approved", "Reviewed assets ready for reuse."),
            ("published", "Published", "Published package assets."),
            ("imported", "Imported", "Imported package assets."),
            ("archived", "Archived", "Archived records."),
        ],
        default="all",
    )
    WindowManager.codex_blender_ai_assets_package_path = StringProperty(name="Package", default="", subtype="FILE_PATH")
    WindowManager.codex_blender_ai_assets_author = StringProperty(name="Author", default="")
    WindowManager.codex_blender_ai_assets_license = StringProperty(name="License SPDX", default="NOASSERTION")
    WindowManager.codex_blender_ai_assets_health = StringProperty(name="AI Assets Health", default="")
    WindowManager.codex_blender_asset_search = StringProperty(
        name="Search",
        description="Filter asset rows by name, category, type, path, or description.",
        default="",
    )
    WindowManager.codex_blender_asset_facet = EnumProperty(
        name="Asset facet",
        description="Filter asset rows by production category.",
        items=[
            ("all", "All", "Show all asset-library rows."),
            ("model", "Models", "Meshes, objects, props, characters, and scene blocks."),
            ("material", "Materials", "Materials, shaders, and texture records."),
            ("rig", "Rigs", "Armatures, controls, and rigging systems."),
            ("image", "Images", "Image, reference, texture, and preview files."),
            ("blend", "Blend Bundles", "Saved .blend asset bundles."),
            ("recipe", "Recipes", "Reusable recipes and generated systems."),
            ("other", "Other", "Rows that do not match a known facet."),
        ],
        default="all",
    )
    WindowManager.codex_blender_asset_show_versions = BoolProperty(
        name="Show versions",
        description="Show selected asset provenance and version guidance.",
        default=True,
    )
    WindowManager.codex_blender_asset_show_publish_queue = BoolProperty(
        name="Show publish queue",
        description="Show the selected-object publish controls.",
        default=True,
    )
    WindowManager.codex_blender_asset_show_diagnostics = BoolProperty(
        name="Show diagnostics",
        description="Show asset workspace health and refresh controls.",
        default=True,
    )
    WindowManager.codex_blender_active_scope = EnumProperty(
        name="AI Scope",
        description="What the assistant may treat as the primary editable context.",
        items=[
            ("selection", "Selection", "Current selected objects."),
            ("active_object", "Active Object", "Only the active Blender object."),
            ("collection", "Collection", "The active object's collection or current collection."),
            ("scene", "Scene", "The current scene."),
            ("project", "Project", "Project-level memory and assets."),
            ("visible_objects", "Visible Objects", "All visible objects in the current scene."),
            ("new_collection", "New Collection Only", "Stage new work in a fresh collection."),
        ],
        default="selection",
    )
    WindowManager.codex_blender_context_chips = CollectionProperty(type=CODEXBLENDERAGENT_ContextChip)
    WindowManager.codex_blender_context_chip_index = IntProperty(name="Context chip index", default=-1, min=-1)
    WindowManager.codex_blender_action_cards = CollectionProperty(type=CODEXBLENDERAGENT_ActionCard)
    WindowManager.codex_blender_action_card_index = IntProperty(name="Action card index", default=-1, min=-1)
    WindowManager.codex_blender_pinned_outputs = CollectionProperty(type=CODEXBLENDERAGENT_PinnedOutput)
    WindowManager.codex_blender_pinned_output_index = IntProperty(name="Pinned output index", default=-1, min=-1)
    WindowManager.codex_blender_job_timeline = CollectionProperty(type=CODEXBLENDERAGENT_JobTimelineItem)
    WindowManager.codex_blender_job_timeline_index = IntProperty(name="Timeline index", default=-1, min=-1)
    WindowManager.codex_blender_active_tool_events = CollectionProperty(type=CODEXBLENDERAGENT_ToolActivityItem)
    WindowManager.codex_blender_active_tool_event_index = IntProperty(name="Active tool index", default=-1, min=-1)
    WindowManager.codex_blender_recent_tool_events = CollectionProperty(type=CODEXBLENDERAGENT_ToolActivityItem)
    WindowManager.codex_blender_recent_tool_event_index = IntProperty(name="Recent tool index", default=-1, min=-1)
    WindowManager.codex_blender_live_sequence = IntProperty(name="Live sequence", default=0, min=0)
    WindowManager.codex_blender_addon_health_summary = StringProperty(
        name="Health summary",
        default="Health not checked yet.",
    )
    WindowManager.codex_blender_dashboard_empty_state = StringProperty(
        name="Dashboard empty state",
        default="Ask Codex for a plan or create an action from the prompt draft.",
    )
    WindowManager.codex_blender_tutorial_walkthrough = EnumProperty(
        name="Tutorial",
        description="Active guided walkthrough.",
        items=walkthrough_items(),
        default="first_run",
    )
    WindowManager.codex_blender_tutorial_step = IntProperty(name="Tutorial step", default=0, min=0)
    WindowManager.codex_blender_show_tutorial = BoolProperty(
        name="Show tutorial",
        description="Show in-panel guided tutorial cards.",
        default=True,
    )
    WindowManager.codex_blender_tutorial_completed = BoolProperty(
        name="Tutorial completed",
        description="Hide beginner tutorial cards unless reopened.",
        default=False,
    )
    WindowManager.codex_blender_tutorial_step_status = EnumProperty(
        name="Tutorial step status",
        description="Result of the last guided tutorial step check.",
        items=[
            ("idle", "Idle", "This step has not been run yet."),
            ("running", "Running", "The tutorial step is running."),
            ("passed", "Passed", "The tutorial step completed."),
            ("failed", "Failed", "The tutorial step needs recovery."),
        ],
        default="idle",
    )
    WindowManager.codex_blender_tutorial_step_message = StringProperty(
        name="Tutorial step message",
        description="Latest tutorial step result or recovery message.",
        default="Click Run Step to try the current tutorial step.",
    )
    WindowManager.codex_blender_tutorial_last_checked_step = StringProperty(
        name="Last checked tutorial step",
        description="Step ID that last wrote tutorial status.",
        default="",
    )
    WindowManager.codex_blender_workflow_example = EnumProperty(
        name="Workflow example",
        description="Example graph to create in the AI Workflow workspace.",
        items=workflow_example_items(),
        default="scene_inspector",
    )


def _unregister_window_manager_properties() -> None:
    names = [
        "codex_blender_prompt",
        "codex_blender_model",
        "codex_blender_effort",
        "codex_blender_include_scene_context",
        "codex_blender_chat_mode",
        "codex_blender_intent",
        "codex_blender_safety_preview_first",
        "codex_blender_safety_non_destructive",
        "codex_blender_safety_duplicate_first",
        "codex_blender_safety_no_deletes",
        "codex_blender_safety_require_approval",
        "codex_blender_safety_stop_checkpoints",
        "codex_blender_game_creator_mode",
        "codex_blender_execution_friction",
        "codex_blender_cards_as_receipts",
        "codex_blender_require_additive_approval",
        "codex_blender_show_advanced_governance",
        "codex_blender_quick_prompt_category",
        "codex_blender_target_engine",
        "codex_blender_game_style",
        "codex_blender_visual_review_enabled",
        "codex_blender_visual_review_auto_after_scene_change",
        "codex_blender_visual_review_max_iterations",
        "codex_blender_visual_review_target_score",
        "codex_blender_visual_review_resolution",
        "codex_blender_visual_review_capture_mode",
        "codex_blender_visual_review_active_run_id",
        "codex_blender_visual_review_phase",
        "codex_blender_visual_review_current_pass",
        "codex_blender_visual_review_current_score",
        "codex_blender_visual_review_stop_requested",
        "codex_blender_visual_review_auto_started",
        "codex_blender_asset_validation_latest_report_id",
        "codex_blender_asset_validation_latest_summary",
        "codex_blender_asset_validation_latest_score",
        "codex_blender_asset_validation_latest_issue_count",
        "codex_blender_asset_validation_latest_critical_count",
        "codex_blender_web_console_running",
        "codex_blender_web_console_url",
        "codex_blender_web_console_port",
        "codex_blender_web_console_error",
        "codex_blender_web_console_auto_started",
        "codex_blender_visual_review_automatic_geometry_review",
        "codex_blender_visual_review_candidate_view_count",
        "codex_blender_visual_review_selected_capture_count",
        "codex_blender_visual_review_audit_view_count",
        "codex_blender_visual_review_mesh_samples_per_object",
        "codex_blender_visual_review_minimum_coverage_score",
        "codex_blender_visual_review_geometry_score_weight",
        "codex_blender_visual_review_critic_score_weight",
        "codex_blender_visual_review_camera_fit_margin",
        "codex_blender_visual_review_view_angular_separation_degrees",
        "codex_blender_visual_review_audit_angular_separation_degrees",
        "codex_blender_visible_message_count",
        "codex_blender_show_transcript",
        "codex_blender_attachment_path",
        "codex_blender_attachments",
        "codex_blender_connection",
        "codex_blender_account",
        "codex_blender_plan",
        "codex_blender_thread",
        "codex_blender_activity",
        "codex_blender_pending",
        "codex_blender_error",
        "codex_blender_error_title",
        "codex_blender_error_severity",
        "codex_blender_error_recovery",
        "codex_blender_error_raw",
        "codex_blender_error_retry",
        "codex_blender_stream_recovering",
        "codex_blender_dashboard_busy",
        "codex_blender_dashboard_progress",
        "codex_blender_redraw_paused",
        "codex_blender_active_project_id",
        "codex_blender_project_index",
        "codex_blender_active_thread_id",
        "codex_blender_thread_index",
        "codex_blender_action_index",
        "codex_blender_dashboard_state_index",
        "codex_blender_toolbox_index",
        "codex_blender_asset_index",
        "codex_blender_projects",
        "codex_blender_threads",
        "codex_blender_actions",
        "codex_blender_dashboard_state",
        "codex_blender_messages",
        "codex_blender_message_index",
        "codex_blender_toolbox_items",
        "codex_blender_show_toolbox",
        "codex_blender_toolbox_facet",
        "codex_blender_asset_items",
        "codex_blender_show_assets",
        "codex_blender_asset_name",
        "codex_blender_ai_assets_search",
        "codex_blender_ai_assets_kind_filter",
        "codex_blender_ai_assets_status_filter",
        "codex_blender_ai_assets_package_path",
        "codex_blender_ai_assets_author",
        "codex_blender_ai_assets_license",
        "codex_blender_ai_assets_health",
        "codex_blender_asset_search",
        "codex_blender_asset_facet",
        "codex_blender_asset_show_versions",
        "codex_blender_asset_show_publish_queue",
        "codex_blender_asset_show_diagnostics",
        "codex_blender_active_scope",
        "codex_blender_context_chips",
        "codex_blender_context_chip_index",
        "codex_blender_action_cards",
        "codex_blender_action_card_index",
        "codex_blender_pinned_outputs",
        "codex_blender_pinned_output_index",
        "codex_blender_job_timeline",
        "codex_blender_job_timeline_index",
        "codex_blender_active_tool_events",
        "codex_blender_active_tool_event_index",
        "codex_blender_recent_tool_events",
        "codex_blender_recent_tool_event_index",
        "codex_blender_live_sequence",
        "codex_blender_addon_health_summary",
        "codex_blender_dashboard_empty_state",
        "codex_blender_tutorial_walkthrough",
        "codex_blender_tutorial_step",
        "codex_blender_show_tutorial",
        "codex_blender_tutorial_completed",
        "codex_blender_tutorial_step_status",
        "codex_blender_tutorial_step_message",
        "codex_blender_tutorial_last_checked_step",
        "codex_blender_workflow_example",
    ]
    for name in names:
        if hasattr(WindowManager, name):
            delattr(WindowManager, name)


CLASSES = (
    CODEXBLENDERAGENT_Message,
    CODEXBLENDERAGENT_Attachment,
    CODEXBLENDERAGENT_ToolboxItem,
    CODEXBLENDERAGENT_AssetItem,
    CODEXBLENDERAGENT_ProjectItem,
    CODEXBLENDERAGENT_ThreadItem,
    CODEXBLENDERAGENT_ActionItem,
    CODEXBLENDERAGENT_DashboardState,
    CODEXBLENDERAGENT_ContextChip,
    CODEXBLENDERAGENT_ActionCard,
    CODEXBLENDERAGENT_PinnedOutput,
    CODEXBLENDERAGENT_JobTimelineItem,
    CODEXBLENDERAGENT_ToolActivityItem,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_window_manager_properties()


def unregister() -> None:
    _unregister_window_manager_properties()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
