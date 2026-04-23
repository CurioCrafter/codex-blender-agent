from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences

from .constants import ADDON_ID, default_codex_command, default_codex_home
from .game_creator import EXECUTION_FRICTION_ITEMS
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
from .visual_review import DEFAULT_MAX_ITERATIONS, DEFAULT_SCREENSHOT_RESOLUTION, DEFAULT_TARGET_SCORE


class CODEXBLENDERAGENT_Preferences(AddonPreferences):
    bl_idname = __package__ or ADDON_ID

    codex_command: StringProperty(
        name="Codex command",
        description="Path or command used to launch the local codex app-server.",
        default=default_codex_command(),
    )
    codex_home: StringProperty(
        name="CODEX_HOME",
        description="Codex state directory. Leave as default to reuse your normal CLI login cache.",
        default=default_codex_home(),
        subtype="DIR_PATH",
    )
    workspace_root: StringProperty(
        name="Workspace root",
        description="Fallback working directory for Codex threads when the current blend file is unsaved.",
        default="",
        subtype="DIR_PATH",
    )
    auto_setup_dashboard_workspace: BoolProperty(
        name="Auto-create AI workspaces on load (legacy)",
        description="Legacy compatibility switch. Off by default so Blender Layout is not mutated until Create AI Workspaces is clicked.",
        default=False,
    )
    enable_operator_bridge: BoolProperty(
        name="Enable full Blender operator bridge",
        description="Allow Codex to discover and call bpy.ops operators across Blender editors, modes, and tool surfaces.",
        default=True,
    )
    enable_python_execution: BoolProperty(
        name="Enable Python execution",
        description="Allow Codex to execute arbitrary Blender Python. This is more powerful than the operator bridge and should only be used for trusted sessions.",
        default=False,
    )
    enable_expert_tools: BoolProperty(
        name="Legacy expert override",
        description="Compatibility switch: enables both the full operator bridge and arbitrary Python execution.",
        default=False,
    )
    enable_experimental_asset_maintenance: BoolProperty(
        name="Enable experimental asset maintenance tools",
        description="Allow advanced bulk catalog maintenance and external-library repair tools. Off by default.",
        default=False,
    )
    enable_append_reuse_data_policy: BoolProperty(
        name="Enable Append Reuse Data import policy",
        description="Allow AI Assets to offer Blender's append/reuse-data import policy for carefully classified assets.",
        default=False,
    )
    game_creator_mode: BoolProperty(
        name="Game Creator Mode",
        description="Default to the chat-first game-creation UX instead of the legacy governance-first dashboard.",
        default=True,
    )
    execution_friction: EnumProperty(
        name="Execution friction",
        description="Default review level for local Blender game-creation work.",
        items=list(EXECUTION_FRICTION_ITEMS),
        default="fast",
    )
    cards_as_receipts: BoolProperty(
        name="Use cards as receipts",
        description="Record ordinary reversible changes after execution; reserve approval cards for high-risk work.",
        default=True,
    )
    require_additive_approval: BoolProperty(
        name="Require approval for additive actions",
        description="Restore approval gates for local reversible/additive actions.",
        default=False,
    )
    show_advanced_governance: BoolProperty(
        name="Show advanced governance UI",
        description="Expose legacy safety chips, package controls, raw diagnostics, and detailed card-first workflows.",
        default=False,
    )
    visual_review_enabled: BoolProperty(
        name="Enable visual self-review",
        description="Allow the N-panel screenshot critique/improve loop.",
        default=True,
    )
    visual_review_auto_after_scene_change: BoolProperty(
        name="Auto review scene-changing sends",
        description="Automatically run the geometry/screenshot self-review backend after normal scene-changing Send actions.",
        default=True,
    )
    web_console_auto_start: BoolProperty(
        name="Auto-start web console",
        description="Start the local review console server when the add-on loads. The browser is not opened automatically.",
        default=True,
    )
    visual_review_max_iterations: IntProperty(
        name="Default visual review passes",
        description="Default maximum creator/critic passes for screenshot self-review.",
        default=DEFAULT_MAX_ITERATIONS,
        min=1,
        max=12,
    )
    visual_review_target_score: FloatProperty(
        name="Default visual review target",
        description="Default target score for stopping screenshot self-review.",
        default=DEFAULT_TARGET_SCORE,
        min=0.0,
        max=1.0,
    )
    visual_review_resolution: IntProperty(
        name="Default screenshot size",
        description="Default square screenshot size for viewport visual self-review.",
        default=DEFAULT_SCREENSHOT_RESOLUTION,
        min=128,
        max=4096,
    )
    visual_review_automatic_geometry_review: BoolProperty(
        name="Automatic geometry review",
        description="Plan self-review screenshots and completion using deterministic scene geometry before GPT critique.",
        default=DEFAULT_GEOMETRY_REVIEW_ENABLED,
    )
    visual_review_candidate_view_count: IntProperty(name="Candidate views", default=DEFAULT_CANDIDATE_VIEW_COUNT, min=8, max=256)
    visual_review_selected_capture_count: IntProperty(name="Selected captures", default=DEFAULT_SELECTED_CAPTURE_COUNT, min=1, max=16)
    visual_review_audit_view_count: IntProperty(name="Audit captures", default=DEFAULT_AUDIT_VIEW_COUNT, min=0, max=8)
    visual_review_mesh_samples_per_object: IntProperty(name="Mesh samples per object", default=DEFAULT_MESH_SAMPLES_PER_OBJECT, min=16, max=4096)
    visual_review_minimum_coverage_score: FloatProperty(name="Minimum coverage score", default=DEFAULT_MINIMUM_COVERAGE_SCORE, min=0.0, max=1.0)
    visual_review_geometry_score_weight: FloatProperty(name="Geometry score weight", default=DEFAULT_GEOMETRY_SCORE_WEIGHT, min=0.0, max=1.0)
    visual_review_critic_score_weight: FloatProperty(name="Critic score weight", default=DEFAULT_CRITIC_SCORE_WEIGHT, min=0.0, max=1.0)
    visual_review_camera_fit_margin: FloatProperty(name="Camera fit margin", default=DEFAULT_CAMERA_FIT_MARGIN, min=1.0, max=2.0)
    visual_review_view_angular_separation_degrees: FloatProperty(name="Optimization view separation", default=DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES, min=0.0, max=90.0)
    visual_review_audit_angular_separation_degrees: FloatProperty(name="Audit view separation", default=DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES, min=0.0, max=120.0)
    ai_assets_storage_root: StringProperty(
        name="AI Assets storage root",
        description="Optional override for the AI Assets SQLite store, packages, manifests, previews, logs, and cache.",
        default="",
        subtype="DIR_PATH",
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Codex Blender Agent uses the local codex app-server.")
        layout.prop(self, "codex_command")
        layout.prop(self, "codex_home")
        layout.prop(self, "workspace_root")
        layout.prop(self, "auto_setup_dashboard_workspace")
        layout.prop(self, "enable_operator_bridge")
        layout.prop(self, "enable_python_execution")
        layout.prop(self, "enable_expert_tools")
        layout.prop(self, "enable_experimental_asset_maintenance")
        layout.prop(self, "enable_append_reuse_data_policy")
        layout.separator()
        layout.label(text="Game Creator")
        layout.prop(self, "game_creator_mode")
        layout.prop(self, "execution_friction")
        layout.prop(self, "cards_as_receipts")
        layout.prop(self, "require_additive_approval")
        layout.prop(self, "show_advanced_governance")
        layout.prop(self, "visual_review_enabled")
        layout.prop(self, "visual_review_auto_after_scene_change")
        layout.prop(self, "visual_review_max_iterations")
        layout.prop(self, "visual_review_target_score")
        layout.prop(self, "visual_review_resolution")
        layout.separator()
        layout.label(text="Visual Review Advanced")
        layout.prop(self, "visual_review_automatic_geometry_review")
        layout.prop(self, "visual_review_candidate_view_count")
        layout.prop(self, "visual_review_selected_capture_count")
        layout.prop(self, "visual_review_audit_view_count")
        layout.prop(self, "visual_review_mesh_samples_per_object")
        layout.prop(self, "visual_review_minimum_coverage_score")
        layout.prop(self, "visual_review_geometry_score_weight")
        layout.prop(self, "visual_review_critic_score_weight")
        layout.prop(self, "visual_review_camera_fit_margin")
        layout.prop(self, "visual_review_view_angular_separation_degrees")
        layout.prop(self, "visual_review_audit_angular_separation_degrees")
        layout.prop(self, "ai_assets_storage_root")


CLASSES = (CODEXBLENDERAGENT_Preferences,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
