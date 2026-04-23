from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from .attachments import classify_attachment
from .chat_surfaces import append_activity_event, read_prompt_draft, write_prompt_draft_body
from .game_creator import creator_context_payload
from .quick_prompts import get_quick_prompt, render_quick_prompt
from .prompt_expander import expand_prompt
from .runtime import get_runtime
from .studio_state import normalize_toolbox_group
from .tutorial import clamp_step_index, current_step, progress_label, step_count
from .workflow_examples import workflow_example_items
from .workflow_nodes import NODE_TYPES


def _sync_dashboard_collections(window_manager: bpy.types.WindowManager) -> None:
    context = getattr(bpy, "context", None)
    if context is not None and getattr(context, "window_manager", None) == window_manager:
        try:
            get_runtime().sync_window_manager(context, force=True)
        except Exception:
            # Keep lightweight action/state rows available even if deep sync fails.
            pass

    state_items = [
        ("connection", "Connection", window_manager.codex_blender_connection, ""),
        ("account", "Account", window_manager.codex_blender_account, window_manager.codex_blender_plan),
        ("project", "Project", window_manager.codex_blender_active_project_id, f"Row {max(window_manager.codex_blender_project_index, 0)}"),
        ("thread", "Thread", window_manager.codex_blender_active_thread_id, f"Row {max(window_manager.codex_blender_thread_index, 0)}"),
        ("activity", "Activity", window_manager.codex_blender_activity, ""),
        ("pending", "Turn", "Running" if window_manager.codex_blender_pending else "Idle", ""),
        ("redraw", "Transcript", "Paused" if window_manager.codex_blender_redraw_paused else "Live", ""),
    ]
    window_manager.codex_blender_dashboard_state.clear()
    for state_id, name, value, detail in state_items:
        entry = window_manager.codex_blender_dashboard_state.add()
        entry.state_id = state_id
        entry.name = name
        entry.value = value or ""
        entry.detail = detail or ""

    actions = [
        ("open_studio_workspace", "Open AI Studio", "codex_blender_agent.open_studio_workspace", "", "Open the AI Studio command center."),
        ("open_workflow_workspace", "Open Workflow", "codex_blender_agent.open_workflow_workspace", "", "Open the dedicated workflow/node workspace."),
        ("open_assets_workspace", "Open Assets", "codex_blender_agent.open_assets_workspace", "", "Open the dedicated assets workspace."),
        ("create_ai_workspaces", "Create AI Workspaces", "codex_blender_agent.create_ai_workspaces", "", "Create the opt-in AI Studio, Workflow, and Assets workspace suite."),
        ("diagnose_dashboard_workspace", "Diagnose Workspace", "codex_blender_agent.diagnose_dashboard_workspace", "", "Report workspace order, active workspace, and Studio tag state."),
        ("refresh_dashboard", "Refresh Studio", "codex_blender_agent.refresh_dashboard", "", "Resync projects, threads, and state from the backend."),
        ("send_npanel_chat", "Ask AI", "codex_blender_agent.send_npanel_chat", "", "Send the visible N-panel chat prompt."),
        ("start_visual_review_loop", "Improve with Screenshots", "codex_blender_agent.start_visual_review_loop", "", "Start the screenshot critique/improve loop from the prompt box."),
        ("stop_visual_review_loop", "Stop Visual Review", "codex_blender_agent.stop_visual_review_loop", "danger", "Stop the active visual self-review loop."),
        ("continue_visual_review_loop", "Continue Visual Review", "codex_blender_agent.continue_visual_review_loop", "", "Continue the selected visual self-review loop."),
        ("open_visual_review_run", "Open Visual Review", "codex_blender_agent.open_visual_review_run", "", "Open the active visual self-review run details."),
        ("capture_visual_review_viewpoints", "Capture Viewpoints", "codex_blender_agent.capture_visual_review_viewpoints", "", "Capture visual-review screenshots from planned viewpoints."),
        ("start_web_console", "Start Web Console", "codex_blender_agent.start_web_console", "", "Start the local browser console for automatic review observability."),
        ("open_web_console", "Open Web Console", "codex_blender_agent.open_web_console", "", "Open the local browser console for automatic review observability."),
        ("stop_web_console", "Stop Web Console", "codex_blender_agent.stop_web_console", "danger", "Stop the local browser console."),
        ("run_quick_prompt", "Quick Prompt", "codex_blender_agent.run_quick_prompt", "", "Run a built-in game-creation quick prompt."),
        ("explain_current_context", "Explain Context", "codex_blender_agent.explain_current_context", "", "Ask AI to explain the visible Blender context."),
        ("start_chat_tutorial", "Chat Tutorial", "codex_blender_agent.start_chat_tutorial", "", "Start a chat-guided tutorial."),
        ("ai_setup_workflow", "AI Setup Workflow", "codex_blender_agent.ai_setup_workflow", "", "Create an AI-managed unconnected workflow starter."),
        ("create_game_asset_from_prompt", "Create Game Asset", "codex_blender_agent.create_game_asset_from_prompt", "", "Route the prompt through the game asset fast lane."),
        ("send_prompt_from_text", "Send Draft", "codex_blender_agent.send_prompt_from_text", "", "Send the multiline Codex Prompt Draft text."),
        ("classify_prompt", "Classify Prompt", "codex_blender_agent.classify_prompt", "", "Classify the next prompt before sending or card creation."),
        ("send_prompt_literal", "Run Draft Script", "codex_blender_agent.send_prompt_literal", "", "Blender Run Script route for Codex Prompt Draft."),
        ("open_dashboard_chat", "Open Chat Draft", "codex_blender_agent.open_dashboard_chat", "", "Open the native Text Editor prompt draft."),
        ("compact_thread", "Compact Thread", "codex_blender_agent.compact_thread", "", "Keep the active thread lean by trimming stored messages."),
        ("pause_transcript_redraw", "Pause Redraw", "codex_blender_agent.pause_transcript_redraw", "", "Pause transcript UI updates when Blender is lagging."),
        ("register_asset_library", "Register Asset Library", "codex_blender_agent.register_asset_library", "", "Register or refresh the Codex Blender Agent asset library."),
        ("initialize_ai_assets_store", "Initialize AI Assets", "codex_blender_agent.initialize_ai_assets_store", "", "Create/open the SQLite AI Assets authority store."),
        ("migrate_ai_assets_store", "Migrate AI Assets", "codex_blender_agent.migrate_ai_assets_store", "", "Migrate legacy JSON asset/toolbox/pin data into SQLite."),
        ("verify_ai_assets", "Verify AI Assets", "codex_blender_agent.verify_ai_assets", "", "Run AI Assets diagnostics."),
        ("create_asset_publish_action", "Create Publish Card", "codex_blender_agent.create_asset_publish_action", "review", "Create a reviewable publish card for selected Blender content."),
        ("publish_asset_package", "Publish Package", "codex_blender_agent.publish_asset_package", "review", "Create a card to publish the selected asset version as a package."),
        ("import_asset_package", "Import Package", "codex_blender_agent.import_asset_package", "review", "Create a card to import an AI Assets package."),
        ("create_workflow_tree", "AI Workflow Graph", "codex_blender_agent.create_workflow_tree", "", "Create or open an orchestration graph in the Node Editor."),
        ("create_example_workflow_graph", "Example Workflow", "codex_blender_agent.create_example_workflow_graph", "", "Create a practical example workflow graph."),
        ("validate_workflow_graph", "Validate Workflow", "codex_blender_agent.validate_workflow_graph", "", "Validate the typed workflow graph before preview or run."),
        ("compile_workflow_graph", "Compile Workflow", "codex_blender_agent.compile_workflow_graph", "", "Compile the workflow graph into a run plan."),
        ("preview_workflow_graph", "Preview Workflow", "codex_blender_agent.preview_workflow_graph", "review", "Preview the workflow safely and create review cards for risky nodes."),
        ("start_workflow_run", "Start Workflow Run", "codex_blender_agent.start_workflow_run", "review", "Start a checkpointed workflow run."),
        ("publish_workflow_recipe", "Publish Recipe", "codex_blender_agent.publish_workflow_recipe", "review", "Publish the graph as a versioned recipe."),
        ("stop_turn", "Stop Turn", "codex_blender_agent.stop_turn", "danger", "Interrupt the currently running Codex turn."),
        ("steer_turn", "Guide Turn", "codex_blender_agent.steer_turn", "", "Send the prompt box text as turn guidance."),
        ("clear_local_messages", "Hide Messages", "codex_blender_agent.clear_local_messages", "", "Clear the visible transcript while keeping the active thread."),
        ("create_action_from_prompt", "Create Action", "codex_blender_agent.create_action_from_prompt", "review", "Turn the current prompt into a visible action card."),
        ("create_card_from_prompt", "Create Card", "codex_blender_agent.create_card_from_prompt", "review", "Classify and create a card from the current prompt."),
        ("preview_action", "Preview Action", "codex_blender_agent.preview_action", "review", "Mark the selected action as ready for review."),
        ("approve_action", "Approve Action", "codex_blender_agent.approve_action", "approved", "Approve and run or unblock the selected action."),
        ("stop_action", "Stop Action", "codex_blender_agent.stop_action", "danger", "Stop new mutating work for the selected running card."),
        ("cancel_action", "Cancel Action", "codex_blender_agent.cancel_action", "safe", "Cancel the selected action card."),
        ("recover_action", "Recover Action", "codex_blender_agent.recover_action", "safe", "Record recovery guidance for the selected action."),
        ("archive_action", "Archive Action", "codex_blender_agent.archive_action", "safe", "Archive the selected action from the working view."),
        ("inspect_ai_context", "Inspect Context", "codex_blender_agent.inspect_ai_context", "", "Refresh visible AI context chips."),
        ("view_action_changes", "View Changes", "codex_blender_agent.view_action_changes", "", "Open the selected action's intended and observed changes."),
        ("undo_last_ai_change", "Undo Last AI Change", "codex_blender_agent.undo_last_ai_change", "safe", "Use Blender Undo for the latest recoverable AI card."),
        ("reset_ai_context", "Reset Context", "codex_blender_agent.reset_ai_context", "safe", "Disable optional context chips and restore safe defaults."),
        ("open_action_details", "Open Action Details", "codex_blender_agent.open_action_details", "", "Open the selected action card detail payload."),
    ]
    window_manager.codex_blender_actions.clear()
    for action_id, name, operator, status, description in actions:
        entry = window_manager.codex_blender_actions.add()
        entry.action_id = action_id
        entry.name = name
        entry.operator = operator
        entry.status = status
        entry.description = description


def _selected_action_id(window_manager: bpy.types.WindowManager, explicit_id: str = "") -> str:
    if explicit_id:
        return explicit_id
    index = getattr(window_manager, "codex_blender_action_card_index", -1)
    cards = getattr(window_manager, "codex_blender_action_cards", [])
    if 0 <= index < len(cards):
        return cards[index].action_id
    if len(cards):
        return cards[0].action_id
    return ""


def _latest_workflow_run_id(context: bpy.types.Context) -> str:
    runs = get_runtime().list_workflow_runs(context)
    return str(runs[0].get("run_id", "")) if runs else ""


def _open_text_payload(context: bpy.types.Context, title: str, payload: dict) -> None:
    text = append_activity_event(title, payload)
    area = getattr(context, "area", None)
    if area is not None and text is not None:
        area.type = "TEXT_EDITOR"
        for space in area.spaces:
            if space.type == "TEXT_EDITOR":
                space.text = text
                space.show_word_wrap = True
                break


def _format_health_summary(result: dict) -> str:
    if result.get("ok"):
        if result.get("workspace_order_ok") is False:
            return "Health Check OK: workspace structure is valid. Tab ordering needs an interactive Create AI Workspaces repair pass."
        return "Health Check OK: AI workspaces, Layout preservation, and core surfaces verified."
    missing = result.get("missing_workspaces") or []
    inactive = result.get("inactive_workspaces") or []
    bad_areas = result.get("bad_area_workspaces") or []
    details = []
    if missing:
        details.append(f"missing={','.join(missing)}")
    if inactive:
        details.append(f"inactive={','.join(inactive)}")
    if bad_areas:
        details.append(f"bad_areas={','.join(bad_areas)}")
    if result.get("workspace_order_ok") is False:
        details.append("tab_order=repair")
    if result.get("last_exception"):
        details.append(str(result["last_exception"])[:120])
    return "Health Check needs repair: " + ("; ".join(details) if details else "see console diagnostic.")


def _call_operator_by_id(operator_id: str, properties: dict):
    namespace, name = operator_id.rsplit(".", 1)
    target = bpy.ops
    for part in namespace.split("."):
        target = getattr(target, part)
    return getattr(target, name)(**properties)


def _set_tutorial_status(window_manager: bpy.types.WindowManager, step_id: str, status: str, message: str) -> None:
    window_manager.codex_blender_tutorial_last_checked_step = step_id
    window_manager.codex_blender_tutorial_step_status = status
    window_manager.codex_blender_tutorial_step_message = message
    window_manager.codex_blender_activity = message


def _prepare_tutorial_step_context(context: bpy.types.Context, step) -> None:
    wm = context.window_manager
    if step.sample_prompt:
        wm.codex_blender_prompt = step.sample_prompt
        write_prompt_draft_body(step.sample_prompt)
    if step.cta_operator == "codex_blender_agent.save_selected_asset":
        if not getattr(context, "selected_objects", []):
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
            if context.object:
                context.object.name = "Tutorial Reusable Cube"
        if not wm.codex_blender_asset_name.strip():
            wm.codex_blender_asset_name = "Tutorial Reusable Asset"
    if step.cta_operator == "codex_blender_agent.import_selected_asset":
        bpy.ops.codex_blender_agent.refresh_assets()
        if len(wm.codex_blender_asset_items) and wm.codex_blender_asset_index < 0:
            wm.codex_blender_asset_index = 0


def _open_step_workspace(context: bpy.types.Context, workspace_name: str):
    if workspace_name in {"AI Workflow", "Workflow"}:
        return bpy.ops.codex_blender_agent.open_workflow_workspace()
    if workspace_name in {"AI Assets", "Assets"}:
        return bpy.ops.codex_blender_agent.open_assets_workspace()
    return bpy.ops.codex_blender_agent.open_studio_workspace()


def _check_tutorial_completion(context: bpy.types.Context, completion: str) -> dict:
    wm = context.window_manager
    value = completion or ""
    if value.startswith("workspace:"):
        expected = value.split(":", 1)[1]
        active = context.window.workspace.name if context.window and context.window.workspace else ""
        workspace = bpy.data.workspaces.get(expected)
        requested = ""
        try:
            from . import workspace as workspace_module

            requested = getattr(workspace_module, "LAST_REQUESTED_WORKSPACE", "")
        except Exception:
            requested = ""
        complete = active == expected or (workspace is not None and requested == expected)
        state = "active" if active == expected else "created/requested" if complete else "not active"
        return {"complete": complete, "message": f"Tutorial check: {expected} is {state}; active workspace is {active or 'None'}."}
    if value.startswith("scope:"):
        expected = value.split(":", 1)[1]
        complete = getattr(wm, "codex_blender_active_scope", "") == expected
        return {"complete": complete, "message": f"Tutorial check: scope is {wm.codex_blender_active_scope}; expected {expected}."}
    if value == "service_started":
        connection = getattr(wm, "codex_blender_connection", "")
        complete = bool(connection and "stopped" not in connection.lower())
        return {"complete": complete, "message": f"Tutorial check: service state is {connection or 'unknown'}."}
    if value == "action_card_exists":
        complete = len(getattr(wm, "codex_blender_action_cards", [])) > 0
        return {"complete": complete, "message": f"Tutorial check: {len(wm.codex_blender_action_cards)} action card(s) visible."}
    if value == "workflow_previewed":
        graph = bpy.data.node_groups.get("Codex AI Workflow")
        previewed = 0
        if graph is not None:
            previewed = sum(1 for node in graph.nodes if str(node.get("status", "")) in {"preview", "previewed", "completed"})
        return {"complete": previewed > 0, "message": f"Tutorial check: {previewed} workflow node(s) have preview/run status."}
    if value == "workflow_graph_exists":
        complete = bpy.data.node_groups.get("Codex AI Workflow") is not None
        return {"complete": complete, "message": "Tutorial check: Codex AI Workflow graph exists." if complete else "Tutorial check: graph missing."}
    if value == "asset_library_registered":
        complete = len(getattr(wm, "codex_blender_asset_items", [])) >= 0
        return {"complete": complete, "message": "Tutorial check: asset library command completed; use Health Check for full diagnostics."}
    if value == "asset_saved":
        complete = len(getattr(wm, "codex_blender_asset_items", [])) > 0
        return {"complete": complete, "message": f"Tutorial check: {len(wm.codex_blender_asset_items)} asset item(s) visible."}
    if value == "asset_imported":
        complete = len(getattr(bpy.data, "objects", [])) > 0
        return {"complete": complete, "message": f"Tutorial check: current scene has {len(bpy.data.objects)} object(s)."}
    if value == "toolbox_action_created":
        complete = len(getattr(wm, "codex_blender_action_cards", [])) > 0
        return {"complete": complete, "message": f"Tutorial check: {len(wm.codex_blender_action_cards)} action card(s) visible."}
    if value == "prompt_sent":
        activity = getattr(wm, "codex_blender_activity", "")
        complete = "prompt" in activity.lower() or bool(getattr(wm, "codex_blender_pending", False))
        return {"complete": complete, "message": activity or "Tutorial check: prompt has not been sent yet."}
    if value == "turn_stopped":
        complete = not bool(getattr(wm, "codex_blender_pending", False))
        return {"complete": complete, "message": "Tutorial check: no turn is currently marked as running."}
    if value == "turn_steered":
        activity = getattr(wm, "codex_blender_activity", "")
        complete = "steer" in activity.lower() or "guidance" in activity.lower()
        return {"complete": complete, "message": activity or "Tutorial check: no steering activity recorded yet."}
    if value == "health_checked":
        return {"complete": "Health Check" in getattr(wm, "codex_blender_activity", ""), "message": getattr(wm, "codex_blender_activity", "Health check not run.")}
    return {"complete": True, "message": "Tutorial check: no completion predicate required."}


class CODEXBLENDERAGENT_OT_start_service(Operator):
    bl_idname = "codex_blender_agent.start_service"
    bl_label = "Start Service"
    bl_description = "Start the local codex app-server and load account/model state."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().start(context, refresh_service_state=True)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_activity = "Enable Blender online access or run Codex login outside Blender, then start the service again."
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_service(Operator):
    bl_idname = "codex_blender_agent.stop_service"
    bl_label = "Stop Service"
    bl_description = "Stop the local codex app-server."

    def execute(self, context: bpy.types.Context):
        get_runtime().stop()
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_state(Operator):
    bl_idname = "codex_blender_agent.refresh_state"
    bl_label = "Refresh"
    bl_description = "Refresh account and model state from Codex."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().refresh(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_dashboard_workspace(Operator):
    bl_idname = "codex_blender_agent.open_dashboard_workspace"
    bl_label = "Open AI Studio Workspace"
    bl_description = "Compatibility alias: create or activate the AI Studio workspace."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_studio_workspace(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_studio_workspace(Operator):
    bl_idname = "codex_blender_agent.open_studio_workspace"
    bl_label = "Open AI Studio"
    bl_description = "Open the AI Studio command center without changing Blender's default Layout workspace."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_studio_workspace(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_workflow_workspace(Operator):
    bl_idname = "codex_blender_agent.open_workflow_workspace"
    bl_label = "Open Workflow Workspace"
    bl_description = "Create or activate the dedicated Workflow node workspace."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_workflow_workspace(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_assets_workspace(Operator):
    bl_idname = "codex_blender_agent.open_assets_workspace"
    bl_label = "Open Assets Workspace"
    bl_description = "Create or activate the dedicated Assets library workspace."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_assets_workspace(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_install_workspace_templates(Operator):
    bl_idname = "codex_blender_agent.install_workspace_templates"
    bl_label = "Create AI Workspaces"
    bl_description = "Create the opt-in AI Studio, Workflow, and Assets workspace suite without mutating Layout."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().install_workspace_templates(context)
            context.window_manager.codex_blender_activity = _format_health_summary(result)
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_ai_workspaces(CODEXBLENDERAGENT_OT_install_workspace_templates):
    bl_idname = "codex_blender_agent.create_ai_workspaces"
    bl_label = "Create AI Workspaces"
    bl_description = "Create the opt-in AI Studio, Workflow, and Assets workspace suite."


class CODEXBLENDERAGENT_OT_migrate_legacy_ai_workspaces(Operator):
    bl_idname = "codex_blender_agent.migrate_legacy_ai_workspaces"
    bl_label = "Migrate Legacy AI Workspaces"
    bl_description = "Safely rename legacy AI Dashboard/AI Workflow/AI Assets workspaces when no canonical workspace conflicts exist."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().migrate_legacy_ai_workspaces(context)
            context.window_manager.codex_blender_activity = (
                f"Workspace migration: renamed={len(result.get('renamed', []))} blocked={len(result.get('blocked', []))}"
            )
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_repair_ai_workspace(Operator):
    bl_idname = "codex_blender_agent.repair_ai_workspace"
    bl_label = "Repair AI Workspace"
    bl_description = "Repair and reopen one AI workspace surface."

    surface: EnumProperty(
        name="Surface",
        items=[
            ("studio", "AI Studio", "Repair AI Studio."),
            ("dashboard", "AI Studio (Legacy)", "Repair AI Studio through the old dashboard alias."),
            ("workflow", "Workflow", "Repair AI Workflow."),
            ("assets", "Assets", "Repair AI Assets."),
        ],
        default="studio",
    )

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().repair_ai_workspace(context, self.surface)
            context.window_manager.codex_blender_activity = _format_health_summary(result)
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_verify_workspace_suite(Operator):
    bl_idname = "codex_blender_agent.verify_workspace_suite"
    bl_label = "Health Check"
    bl_description = "Verify AI workspace integrity, Layout preservation, panel surfaces, and workflow node wiring."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().verify_workspace_suite(context)
            context.window_manager.codex_blender_activity = _format_health_summary(result)
            print("Codex Blender Agent health check:", result)
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if result.get("ok") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_ai_workspace(Operator):
    bl_idname = "codex_blender_agent.open_ai_workspace"
    bl_label = "Open AI Workspace"
    bl_description = "Open a named AI Studio workspace surface."

    surface: EnumProperty(
        name="Surface",
        items=[
            ("studio", "AI Studio", "Open AI Studio."),
            ("dashboard", "AI Studio (Legacy)", "Open AI Studio through the old dashboard alias."),
            ("workflow", "Workflow", "Open Workflow."),
            ("assets", "Assets", "Open Assets."),
        ],
        default="studio",
    )

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_ai_workspace(context, self.surface)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_use_selection_in_workflow(Operator):
    bl_idname = "codex_blender_agent.use_selection_in_workflow"
    bl_label = "Use Selection in Workflow"
    bl_description = "Set AI scope to the current selection and open the Workflow workspace."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().set_ai_scope(context, "selection")
            get_runtime().open_workflow_workspace(context)
            context.window_manager.codex_blender_activity = "Workflow is bound to the current selection scope."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_last_result(Operator):
    bl_idname = "codex_blender_agent.open_last_result"
    bl_label = "Open Last Result"
    bl_description = "Open the best workspace for the latest pinned output or completed action."

    def execute(self, context: bpy.types.Context):
        try:
            wm = context.window_manager
            if len(wm.codex_blender_pinned_outputs):
                get_runtime().open_assets_workspace(context)
                wm.codex_blender_activity = "Opened Assets for the latest pinned result."
            elif len(wm.codex_blender_action_cards):
                get_runtime().open_studio_workspace(context)
                wm.codex_blender_activity = "Opened AI Studio for the latest action card."
            else:
                get_runtime().open_studio_workspace(context)
                wm.codex_blender_activity = "No prior result found. AI Studio is ready for the next action."
            _sync_dashboard_collections(wm)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_result_in_workflow(Operator):
    bl_idname = "codex_blender_agent.open_result_in_workflow"
    bl_label = "Open Result in Workflow"
    bl_description = "Open Workflow to inspect or continue the selected result's process."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_workflow_workspace(context)
            context.window_manager.codex_blender_activity = "Opened Workflow for result inspection."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_result_in_assets(Operator):
    bl_idname = "codex_blender_agent.open_result_in_assets"
    bl_label = "Open Result in Assets"
    bl_description = "Open Assets to reuse, publish, or inspect provenance for the selected result."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_assets_workspace(context)
            context.window_manager.codex_blender_activity = "Opened Assets for result reuse and provenance."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_dashboard(Operator):
    bl_idname = "codex_blender_agent.refresh_dashboard"
    bl_label = "Refresh AI Studio"
    bl_description = "Refresh the Studio project, thread, and state collections."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().refresh_dashboard(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_diagnose_dashboard_workspace(Operator):
    bl_idname = "codex_blender_agent.diagnose_dashboard_workspace"
    bl_label = "Diagnose AI Studio Workspace"
    bl_description = "Report whether AI Studio exists, is tagged, preserves Layout, and has the expected native editors."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().diagnose_dashboard_workspace(context)
            message = f"AI Studio exists={result.get('studio_exists')} index={result.get('studio_index')} tagged={result.get('studio_tagged')}"
            context.window_manager.codex_blender_activity = message
            self.report({"INFO"}, message)
            print("Codex Blender Agent workspace diagnostic:", result)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_select_project(Operator):
    bl_idname = "codex_blender_agent.select_project"
    bl_label = "Select Project"
    bl_description = "Activate the selected Studio project."

    index: IntProperty(default=-1)

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        index = self.index if self.index >= 0 else window_manager.codex_blender_project_index
        if index < 0 and len(window_manager.codex_blender_projects):
            index = 0
        try:
            get_runtime().select_project(context, index)
            _sync_dashboard_collections(window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_select_thread(Operator):
    bl_idname = "codex_blender_agent.select_thread"
    bl_label = "Select Thread"
    bl_description = "Activate the selected Studio thread."

    index: IntProperty(default=-1)

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        index = self.index if self.index >= 0 else window_manager.codex_blender_thread_index
        if index < 0 and len(window_manager.codex_blender_threads):
            index = 0
        try:
            get_runtime().select_thread(context, index)
            _sync_dashboard_collections(window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_compact_thread(Operator):
    bl_idname = "codex_blender_agent.compact_thread"
    bl_label = "Compact Thread"
    bl_description = "Reduce the size of the active thread's stored transcript."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().compact_active_thread(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_pause_transcript_redraw(Operator):
    bl_idname = "codex_blender_agent.pause_transcript_redraw"
    bl_label = "Pause Transcript Redraw"
    bl_description = "Pause or resume transcript redraws to reduce UI lag."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().pause_transcript_redraw(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_set_ai_scope(Operator):
    bl_idname = "codex_blender_agent.set_ai_scope"
    bl_label = "Set AI Scope"
    bl_description = "Set the primary Blender scope the AI should inspect or edit."

    scope: EnumProperty(
        name="Scope",
        items=[
            ("selection", "Selection", "Current selected objects."),
            ("active_object", "Active Object", "Only the active object."),
            ("collection", "Collection", "Active collection."),
            ("scene", "Scene", "Current scene."),
            ("project", "Project", "Project memory and assets."),
        ],
        default="selection",
    )

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().set_ai_scope(context, self.scope)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_toggle_context_chip(Operator):
    bl_idname = "codex_blender_agent.toggle_context_chip"
    bl_label = "Toggle Context Chip"
    bl_description = "Include or exclude a visible context chip from AI context."

    chip_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().toggle_context_chip(context, self.chip_id)
            self.report({"INFO"}, f"{result['chip_id']}: {'enabled' if result['enabled'] else 'disabled'}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_tutorial(Operator):
    bl_idname = "codex_blender_agent.open_tutorial"
    bl_label = "Open Tutorial"
    bl_description = "Show the guided AI Studio tutorial card."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        wm.codex_blender_tutorial_walkthrough = "first_run"
        wm.codex_blender_show_tutorial = True
        wm.codex_blender_tutorial_completed = False
        wm.codex_blender_tutorial_step = 0
        _set_tutorial_status(wm, "first_run_open_dashboard", "idle", "Tutorial opened. Click Run Step to begin the AI Studio walkthrough.")
        try:
            get_runtime().open_studio_workspace(context)
            _sync_dashboard_collections(wm)
        except Exception as exc:
            _set_tutorial_status(wm, "first_run_open_dashboard", "failed", f"Tutorial could not open AI Studio: {exc}")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_next_tutorial_step(Operator):
    bl_idname = "codex_blender_agent.next_tutorial_step"
    bl_label = "Next Tutorial Step"
    bl_description = "Advance the active tutorial walkthrough."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        count = step_count(wm.codex_blender_tutorial_walkthrough)
        next_step = wm.codex_blender_tutorial_step + 1
        if next_step >= count:
            wm.codex_blender_tutorial_step = max(count - 1, 0)
            wm.codex_blender_tutorial_completed = True
            wm.codex_blender_show_tutorial = False
            _set_tutorial_status(wm, current_step(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step).step_id, "passed", "Tutorial completed.")
            self.report({"INFO"}, "Tutorial completed.")
        else:
            wm.codex_blender_tutorial_step = next_step
            step = current_step(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step)
            _set_tutorial_status(wm, step.step_id, "idle", f"Ready: {step.title}. Click Run Step.")
            self.report({"INFO"}, progress_label(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step))
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_previous_tutorial_step(Operator):
    bl_idname = "codex_blender_agent.previous_tutorial_step"
    bl_label = "Previous Tutorial Step"
    bl_description = "Go back one tutorial step."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        wm.codex_blender_tutorial_step = clamp_step_index(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step - 1)
        wm.codex_blender_show_tutorial = True
        step = current_step(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step)
        _set_tutorial_status(wm, step.step_id, "idle", f"Ready: {step.title}. Click Run Step.")
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_reset_tutorial(Operator):
    bl_idname = "codex_blender_agent.reset_tutorial"
    bl_label = "Reset Tutorial"
    bl_description = "Restart the active tutorial walkthrough from the first step."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        wm.codex_blender_tutorial_step = 0
        wm.codex_blender_show_tutorial = True
        wm.codex_blender_tutorial_completed = False
        step = current_step(wm.codex_blender_tutorial_walkthrough, 0)
        _set_tutorial_status(wm, step.step_id, "idle", f"Tutorial reset. Click Run Step for {step.title}.")
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_complete_tutorial(Operator):
    bl_idname = "codex_blender_agent.complete_tutorial"
    bl_label = "Complete Tutorial"
    bl_description = "Hide tutorial cards until reopened."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        wm.codex_blender_tutorial_completed = True
        wm.codex_blender_show_tutorial = False
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_quickstart_doc(Operator):
    bl_idname = "codex_blender_agent.open_quickstart_doc"
    bl_label = "Open Quickstart"
    bl_description = "Open the packaged quickstart tutorial document."

    def execute(self, context: bpy.types.Context):
        quickstart = Path(__file__).with_name("QUICKSTART.md")
        if not quickstart.exists():
            self.report({"WARNING"}, f"Quickstart not found: {quickstart}")
            return {"CANCELLED"}
        bpy.ops.wm.url_open(url=quickstart.resolve().as_uri())
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_tutorial_target(Operator):
    bl_idname = "codex_blender_agent.open_tutorial_target"
    bl_label = "Open Tutorial Target"
    bl_description = "Open the workspace required by the current tutorial step."

    def execute(self, context: bpy.types.Context):
        step = current_step(context.window_manager.codex_blender_tutorial_walkthrough, context.window_manager.codex_blender_tutorial_step)
        try:
            _open_step_workspace(context, step.workspace)
            _set_tutorial_status(context.window_manager, step.step_id, "idle", f"Opened {step.workspace}. Now click Run Step for: {step.title}.")
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            _set_tutorial_status(context.window_manager, step.step_id, "failed", f"Could not open {step.workspace}: {exc}")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_run_tutorial_step(Operator):
    bl_idname = "codex_blender_agent.run_tutorial_step"
    bl_label = "Run Tutorial Step"
    bl_description = "Run the primary action for the current guided tutorial step."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        step = current_step(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step)
        _set_tutorial_status(wm, step.step_id, "running", f"Running tutorial step: {step.title}")
        _prepare_tutorial_step_context(context, step)
        try:
            if step.cta_operator:
                result = _call_operator_by_id(step.cta_operator, dict(step.cta_properties))
                if "FINISHED" not in result:
                    message = f"{step.cta_operator} returned {result}. Use Fix Step or follow the recovery text."
                    _set_tutorial_status(wm, step.step_id, "failed", message)
                    self.report({"WARNING"}, message)
                    return {"CANCELLED"}
            else:
                _open_step_workspace(context, step.workspace)
            check = _check_tutorial_completion(context, step.completion)
            _set_tutorial_status(wm, step.step_id, "passed" if check["complete"] else "failed", check["message"])
            _sync_dashboard_collections(wm)
            self.report({"INFO" if check["complete"] else "WARNING"}, check["message"])
        except Exception as exc:
            wm.codex_blender_error = str(exc)
            _set_tutorial_status(wm, step.step_id, "failed", f"Failed: {exc}. Recovery: {step.recovery}")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_check_tutorial_step(Operator):
    bl_idname = "codex_blender_agent.check_tutorial_step"
    bl_label = "Check Tutorial Step"
    bl_description = "Check whether the current guided tutorial step is complete."

    def execute(self, context: bpy.types.Context):
        step = current_step(context.window_manager.codex_blender_tutorial_walkthrough, context.window_manager.codex_blender_tutorial_step)
        check = _check_tutorial_completion(context, step.completion)
        _set_tutorial_status(context.window_manager, step.step_id, "passed" if check["complete"] else "failed", check["message"])
        self.report({"INFO" if check["complete"] else "WARNING"}, check["message"])
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_fix_tutorial_step(Operator):
    bl_idname = "codex_blender_agent.fix_tutorial_step"
    bl_label = "Fix Tutorial Step"
    bl_description = "Open the target workspace, seed required fields, and show recovery guidance for the current tutorial step."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        step = current_step(wm.codex_blender_tutorial_walkthrough, wm.codex_blender_tutorial_step)
        try:
            _open_step_workspace(context, step.workspace)
            _prepare_tutorial_step_context(context, step)
            _set_tutorial_status(wm, step.step_id, "idle", f"Fix applied for {step.title}. Recovery: {step.recovery}")
            _sync_dashboard_collections(wm)
        except Exception as exc:
            _set_tutorial_status(wm, step.step_id, "failed", f"Fix failed: {exc}. Recovery: {step.recovery}")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_register_asset_library(Operator):
    bl_idname = "codex_blender_agent.register_asset_library"
    bl_label = "Register Asset Library"
    bl_description = "Register or refresh the Codex Blender Agent asset library."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().register_asset_library(context)
            _sync_dashboard_collections(context.window_manager)
            if isinstance(result, dict):
                if result.get("action_id"):
                    context.window_manager.codex_blender_activity = "Asset library registration card created. Approve it from AI Studio before Blender preferences are changed."
                    self.report({"INFO"}, "Asset library registration card created.")
                elif result.get("registered"):
                    self.report({"INFO"}, f"Asset library registered: {result.get('path', '')}")
                elif result.get("legacy") or result.get("ai_libraries"):
                    self.report({"INFO"}, "AI asset libraries registered.")
                else:
                    self.report({"WARNING"}, result.get("reason", "Asset library API unavailable."))
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_initialize_ai_assets_store(Operator):
    bl_idname = "codex_blender_agent.initialize_ai_assets_store"
    bl_label = "Initialize AI Assets Store"
    bl_description = "Create or open the SQLite AI Assets authority store."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().initialize_ai_assets_store(context)
            context.window_manager.codex_blender_ai_assets_health = str(result)
            context.window_manager.codex_blender_activity = "AI Assets store initialized."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_migrate_ai_assets_store(Operator):
    bl_idname = "codex_blender_agent.migrate_ai_assets_store"
    bl_label = "Migrate AI Assets Store"
    bl_description = "Back up legacy JSON stores and migrate AI Assets data into SQLite."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().migrate_ai_assets_store(context)
            context.window_manager.codex_blender_ai_assets_health = str(result)
            context.window_manager.codex_blender_activity = "AI Assets migration checked."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_verify_ai_assets(Operator):
    bl_idname = "codex_blender_agent.verify_ai_assets"
    bl_label = "Verify AI Assets"
    bl_description = "Run AI Assets storage, catalog, package, preview, dependency, and health diagnostics."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().diagnose_ai_assets(context)
            context.window_manager.codex_blender_ai_assets_health = str(result)
            context.window_manager.codex_blender_activity = "AI Assets diagnostics complete."
            _sync_dashboard_collections(context.window_manager)
            print("Codex AI Assets diagnostics:", result)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_repair_ai_assets(Operator):
    bl_idname = "codex_blender_agent.repair_ai_assets"
    bl_label = "Repair AI Assets"
    bl_description = "Initialize and migrate AI Assets, then create a review card for library registration."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().initialize_ai_assets_store(context)
            get_runtime().migrate_ai_assets_store(context)
            card = get_runtime().register_asset_library(context)
            context.window_manager.codex_blender_activity = f"AI Assets repair prepared card: {card.get('title', 'Register Asset Library')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_index_asset_libraries(Operator):
    bl_idname = "codex_blender_agent.index_asset_libraries"
    bl_label = "Index Asset Libraries"
    bl_description = "Refresh AI Assets library, catalog, and search indexes."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().migrate_ai_assets_store(context)
            bpy.ops.codex_blender_agent.refresh_assets()
            context.window_manager.codex_blender_activity = "AI Assets index refreshed."
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_asset_index(CODEXBLENDERAGENT_OT_index_asset_libraries):
    bl_idname = "codex_blender_agent.refresh_asset_index"
    bl_label = "Refresh Asset Index"
    bl_description = "Refresh the AI Assets search and visible asset-version index."


def _selected_asset_item(context: bpy.types.Context):
    items = context.window_manager.codex_blender_asset_items
    index = context.window_manager.codex_blender_asset_index
    if index < 0 or index >= len(items):
        return None
    return items[index]


def _selected_asset_version_uid(context: bpy.types.Context) -> str:
    item = _selected_asset_item(context)
    if item is None:
        return ""
    return item.version_uid or item.item_id


class CODEXBLENDERAGENT_OT_create_asset_publish_action(Operator):
    bl_idname = "codex_blender_agent.create_asset_publish_action"
    bl_label = "Create Publish Card"
    bl_description = "Create a reviewable AI Assets publish card for selected Blender content."

    def execute(self, context: bpy.types.Context):
        try:
            card = get_runtime().create_asset_publish_action(
                context,
                name=context.window_manager.codex_blender_asset_name,
                kind="model" if context.window_manager.codex_blender_ai_assets_kind_filter in {"", "all"} else context.window_manager.codex_blender_ai_assets_kind_filter,
                description="Publish selected Blender content into AI Assets.",
            )
            context.window_manager.codex_blender_activity = f"Created publish card: {card.get('title', '')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_promote_output_to_asset(Operator):
    bl_idname = "codex_blender_agent.promote_output_to_asset"
    bl_label = "Promote Output To Asset"
    bl_description = "Promote the selected/pinned output summary into a draft AI Assets version record."

    def execute(self, context: bpy.types.Context):
        wm = context.window_manager
        try:
            card_id = _selected_action_id(wm)
            card_title = ""
            card_summary = ""
            if card_id:
                detail = get_runtime().get_action_detail(context, card_id)
                card_title = str(detail.get("title", ""))
                card_summary = str(detail.get("result_summary") or detail.get("plan_preview") or detail.get("prompt") or "")
            title = wm.codex_blender_asset_name.strip() or card_title or "Promoted AI Output"
            store = get_runtime()._ai_assets_store(context)
            snapshot = store.create_output_snapshot(
                title=title,
                kind="output" if wm.codex_blender_ai_assets_kind_filter in {"", "all"} else wm.codex_blender_ai_assets_kind_filter,
                summary=card_summary or wm.codex_blender_activity or "Promoted from AI Studio workspace.",
                payload={"action_id": card_id, "activity": wm.codex_blender_activity},
                project_id=wm.codex_blender_active_project_id,
                action_id=card_id,
                status="review",
            )
            asset = store.promote_output_snapshot(
                snapshot["output_id"],
                kind="output" if wm.codex_blender_ai_assets_kind_filter in {"", "all"} else wm.codex_blender_ai_assets_kind_filter,
                title=title,
                status="draft",
                author=wm.codex_blender_ai_assets_author,
                license_spdx=wm.codex_blender_ai_assets_license,
                description=card_summary or "Promoted AI output snapshot.",
            )
            wm.codex_blender_activity = f"Promoted output snapshot into draft asset version: {asset.get('version_uid', '')}"
            bpy.ops.codex_blender_agent.refresh_assets()
            _sync_dashboard_collections(wm)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_validate_asset_version(Operator):
    bl_idname = "codex_blender_agent.validate_asset_version"
    bl_label = "Validate Asset Version"
    bl_description = "Validate metadata, payload, preview, dependency, and license readiness for the selected asset version."

    def execute(self, context: bpy.types.Context):
        version_uid = _selected_asset_version_uid(context)
        if not version_uid:
            self.report({"WARNING"}, "Select an asset version first.")
            return {"CANCELLED"}
        try:
            result = get_runtime()._ai_assets_store(context).validate_asset_version(version_uid)
            context.window_manager.codex_blender_activity = f"Asset validation: {result.get('validation_state', 'unknown')}"
            bpy.ops.codex_blender_agent.refresh_assets()
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_generate_asset_preview(Operator):
    bl_idname = "codex_blender_agent.generate_asset_preview"
    bl_label = "Generate Asset Preview"
    bl_description = "Request preview generation for the selected asset version. Uses Blender-native previews when available."

    def execute(self, context: bpy.types.Context):
        version_uid = _selected_asset_version_uid(context)
        if not version_uid:
            self.report({"WARNING"}, "Select an asset version first.")
            return {"CANCELLED"}
        try:
            result = get_runtime()._ai_assets_store(context).generate_preview_placeholder(version_uid)
            context.window_manager.codex_blender_activity = f"Generated AI Assets preview: {result.get('preview_path', '')}"
            bpy.ops.codex_blender_agent.refresh_assets()
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_publish_asset_package(Operator):
    bl_idname = "codex_blender_agent.publish_asset_package"
    bl_label = "Publish Package"
    bl_description = "Create a reviewable card to publish the selected asset version as a portable package."

    def execute(self, context: bpy.types.Context):
        version_uid = _selected_asset_version_uid(context)
        if not version_uid:
            self.report({"WARNING"}, "Select an asset version first.")
            return {"CANCELLED"}
        try:
            card = get_runtime().create_asset_action_card(
                context,
                title="Publish Asset Package",
                prompt=f"Publish asset version {version_uid} as a portable AI Assets package.",
                plan="Validate metadata, hashes, catalog, preview, dependencies, provenance, license, and package manifest before writing the package zip.",
                tool_name="publish_asset_package",
                arguments={"version_uid": version_uid},
                kind="export",
                affected_targets=[version_uid],
                required_context=["Selected asset version", "AI Assets package manifest"],
                preview_summary="Preview only: package zip will be written after approval.",
                recovery="If publishing fails, temp files are quarantined and the card remains recoverable.",
            )
            get_runtime().preview_action(context, card["action_id"])
            context.window_manager.codex_blender_activity = f"Created package publish card: {card.get('title', '')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_import_asset_package(Operator):
    bl_idname = "codex_blender_agent.import_asset_package"
    bl_label = "Import Package"
    bl_description = "Create a reviewable card to import a portable AI Assets package."

    def execute(self, context: bpy.types.Context):
        package_path = context.window_manager.codex_blender_ai_assets_package_path.strip()
        if not package_path:
            self.report({"WARNING"}, "Choose an AI Assets package zip first.")
            return {"CANCELLED"}
        try:
            card = get_runtime().create_asset_action_card(
                context,
                title="Import AI Assets Package",
                prompt=f"Import AI Assets package {package_path}.",
                plan="Validate manifest, hashes, catalog, package payload, provenance, and dependency records before import.",
                tool_name="import_asset_package",
                arguments={"package_path": package_path, "library_id": "published"},
                kind="export",
                affected_targets=[package_path],
                required_context=["Package zip", "AI Assets Published library"],
                preview_summary="Preview only: package contents will be extracted and indexed after approval.",
                recovery="If import fails, the package is copied to quarantine and diagnostics explain why.",
            )
            get_runtime().preview_action(context, card["action_id"])
            context.window_manager.codex_blender_activity = f"Created package import card: {card.get('title', '')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_pin_asset_version(Operator):
    bl_idname = "codex_blender_agent.pin_asset_version"
    bl_label = "Pin Asset Version"
    bl_description = "Pin the selected immutable asset version into AI Assets memory."

    def execute(self, context: bpy.types.Context):
        version_uid = _selected_asset_version_uid(context)
        if not version_uid:
            self.report({"WARNING"}, "Select an asset version first.")
            return {"CANCELLED"}
        try:
            get_runtime()._ai_assets_store(context).pin_target(
                target_type="asset_version",
                target_uid=version_uid,
                scope="project",
                reason="Pinned from AI Assets workspace.",
                project_id=context.window_manager.codex_blender_active_project_id,
            )
            context.window_manager.codex_blender_activity = f"Pinned asset version: {version_uid}"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_fork_asset_version(Operator):
    bl_idname = "codex_blender_agent.fork_asset_version"
    bl_label = "Fork Asset Version"
    bl_description = "Fork the selected asset version into a new draft version record."

    def execute(self, context: bpy.types.Context):
        version_uid = _selected_asset_version_uid(context)
        if not version_uid:
            self.report({"WARNING"}, "Select an asset version first.")
            return {"CANCELLED"}
        try:
            source = get_runtime()._ai_assets_store(context).get_asset_version(version_uid)
            if source is None:
                raise RuntimeError(f"Asset version not found: {version_uid}")
            source["version"] = "1.0.1"
            source["version_uid"] = f"{source['logical_uid']}@1.0.1"
            source["status"] = "draft"
            source["provenance"] = {**dict(source.get("provenance", {})), "wasDerivedFrom": [version_uid]}
            result = get_runtime()._ai_assets_store(context).upsert_asset_version(**source)
            context.window_manager.codex_blender_activity = f"Forked asset version: {result.get('version_uid', '')}"
            bpy.ops.codex_blender_agent.refresh_assets()
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_append_asset_version(Operator):
    bl_idname = "codex_blender_agent.append_asset_version"
    bl_label = "Append Asset Version"
    bl_description = "Create a reviewable card to append the selected asset version into the current scene."

    def execute(self, context: bpy.types.Context):
        return _create_asset_import_card(context, link=False)


class CODEXBLENDERAGENT_OT_link_asset_version(Operator):
    bl_idname = "codex_blender_agent.link_asset_version"
    bl_label = "Link Asset Version"
    bl_description = "Create a reviewable card to link the selected asset version into the current scene."

    def execute(self, context: bpy.types.Context):
        return _create_asset_import_card(context, link=True)


def _create_asset_import_card(context: bpy.types.Context, *, link: bool):
    version_uid = _selected_asset_version_uid(context)
    if not version_uid:
        return {"CANCELLED"}
    try:
        tool_name = "link_asset_version" if link else "append_asset_version"
        card = get_runtime().create_asset_action_card(
            context,
            title=("Link" if link else "Append") + " Asset Version",
            prompt=f"{'Link' if link else 'Append'} asset version {version_uid} into the current scene.",
            plan="Review import policy, dependencies, and affected scene collection before importing.",
            tool_name=tool_name,
            arguments={"version_uid": version_uid},
            kind="change",
            affected_targets=[version_uid],
            required_context=["Selected asset version", "Current scene collection"],
            preview_summary="Preview only: the selected asset version will be imported after approval.",
            recovery="Use Blender Undo after approved import if the result should be removed.",
        )
        get_runtime().preview_action(context, card["action_id"])
        context.window_manager.codex_blender_activity = f"Created import card: {card.get('title', '')}"
        _sync_dashboard_collections(context.window_manager)
    except Exception as exc:
        context.window_manager.codex_blender_error = str(exc)
        return {"CANCELLED"}
    return {"FINISHED"}


def _send_game_creator_prompt(context: bpy.types.Context, prompt: str, *, auto_create_action: bool = True) -> dict:
    window_manager = context.window_manager
    model = window_manager.codex_blender_model
    if model == "__none__":
        model = ""
    return get_runtime().send_prompt(
        context=context,
        prompt=prompt,
        include_scene_context=window_manager.codex_blender_include_scene_context,
        model=model,
        effort=window_manager.codex_blender_effort,
        attachments=[item.path for item in window_manager.codex_blender_attachments],
        chat_mode=window_manager.codex_blender_chat_mode,
        auto_create_action=auto_create_action,
    )


class CODEXBLENDERAGENT_OT_send_npanel_chat(Operator):
    bl_idname = "codex_blender_agent.send_npanel_chat"
    bl_label = "Ask AI"
    bl_description = "Send the N-panel chat prompt directly to the Game Creator assistant."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        prompt = window_manager.codex_blender_prompt.strip()
        if not prompt:
            self.report({"WARNING"}, "Type a game-creation prompt first.")
            return {"CANCELLED"}
        try:
            route = _send_game_creator_prompt(context, prompt, auto_create_action=True)
            if isinstance(route, dict) and route.get("routed") == "card":
                card = route.get("card", {})
                window_manager.codex_blender_activity = f"Review needed: {card.get('title', 'AI action')}"
            elif isinstance(route, dict) and route.get("routed") == "visual_review":
                window_manager.codex_blender_activity = "Auto review running: creator -> VERIFYING -> critic."
            else:
                window_manager.codex_blender_activity = "Sent game creator chat."
            window_manager.codex_blender_prompt = ""
            window_manager.codex_blender_attachments.clear()
            _sync_dashboard_collections(window_manager)
        except Exception as exc:
            window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_run_quick_prompt(Operator):
    bl_idname = "codex_blender_agent.run_quick_prompt"
    bl_label = "Run Quick Prompt"
    bl_description = "Render and send a built-in game-creation quick prompt."

    prompt_id: StringProperty(name="Prompt ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            prompt = get_quick_prompt(self.prompt_id)
            rendered = render_quick_prompt(self.prompt_id, creator_context_payload(context))
            if prompt.execution_mode == "workflow":
                get_runtime().create_workflow_from_intent(context, rendered)
                context.window_manager.codex_blender_activity = f"Created workflow starter: {prompt.label}"
            elif prompt.execution_mode == "visual_review":
                get_runtime().start_visual_review_loop(context, rendered)
                context.window_manager.codex_blender_activity = f"Started visual review: {prompt.label}"
            else:
                route = _send_game_creator_prompt(context, rendered, auto_create_action=True)
                if isinstance(route, dict) and route.get("routed") == "visual_review":
                    context.window_manager.codex_blender_activity = f"Auto review running: {prompt.label}"
                elif isinstance(route, dict) and route.get("routed") == "card":
                    card = route.get("card", {})
                    context.window_manager.codex_blender_activity = f"Quick prompt needs review: {card.get('title', 'AI action')}"
                else:
                    context.window_manager.codex_blender_activity = f"Sent quick prompt: {prompt.label}"
            context.window_manager.codex_blender_prompt = ""
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_start_visual_review_loop(Operator):
    bl_idname = "codex_blender_agent.start_visual_review_loop"
    bl_label = "Improve with Screenshots"
    bl_description = "Create or improve the scene, capture screenshots, critique them, and iterate."

    prompt: StringProperty(name="Prompt", default="")

    def execute(self, context: bpy.types.Context):
        try:
            prompt = self.prompt.strip() or context.window_manager.codex_blender_prompt.strip()
            get_runtime().start_visual_review_loop(context, prompt)
            context.window_manager.codex_blender_activity = "Started visual self-review loop."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_visual_review_loop(Operator):
    bl_idname = "codex_blender_agent.stop_visual_review_loop"
    bl_label = "Stop Visual Review"
    bl_description = "Stop the active visual self-review loop."

    run_id: StringProperty(name="Run ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().stop_visual_review_loop(context, self.run_id)
            context.window_manager.codex_blender_activity = "Stopped visual self-review loop."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_continue_visual_review_loop(Operator):
    bl_idname = "codex_blender_agent.continue_visual_review_loop"
    bl_label = "Continue Visual Review"
    bl_description = "Continue a stopped or incomplete visual self-review loop."

    run_id: StringProperty(name="Run ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().continue_visual_review_loop(context, self.run_id)
            context.window_manager.codex_blender_activity = "Continued visual self-review loop."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_visual_review_run(Operator):
    bl_idname = "codex_blender_agent.open_visual_review_run"
    bl_label = "Open Visual Review Run"
    bl_description = "Open the active visual self-review run manifest and screenshot folder in Studio."

    run_id: StringProperty(name="Run ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            run_id = self.run_id or context.window_manager.codex_blender_visual_review_active_run_id
            if run_id:
                run = get_runtime().get_visual_review_run(context, run_id)
                context.window_manager.codex_blender_activity = f"Visual review {run_id}: {run.get('phase', run.get('status', ''))}"
            bpy.ops.codex_blender_agent.open_studio_workspace()
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_capture_visual_review_viewpoints(Operator):
    bl_idname = "codex_blender_agent.capture_visual_review_viewpoints"
    bl_label = "Capture Viewpoints"
    bl_description = "Capture the planned visual-review viewport screenshots now."

    run_id: StringProperty(name="Run ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().capture_visual_review_viewpoints(context, self.run_id)
            context.window_manager.codex_blender_activity = "Captured visual-review viewpoints."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_start_web_console(Operator):
    bl_idname = "codex_blender_agent.start_web_console"
    bl_label = "Start Web Console"
    bl_description = "Start the local browser console that shows automatic review screenshots, checks, prompts, and critic output."

    def execute(self, context: bpy.types.Context):
        try:
            state = get_runtime().start_web_console(context)
            context.window_manager.codex_blender_activity = f"Web console running: {state.get('url', '')}"
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, "Started Codex Auto Review web console.")
        except Exception as exc:
            context.window_manager.codex_blender_web_console_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_web_console(Operator):
    bl_idname = "codex_blender_agent.open_web_console"
    bl_label = "Open Web Console"
    bl_description = "Open the local browser console for automatic review observability."

    def execute(self, context: bpy.types.Context):
        try:
            url = get_runtime().open_web_console(context)
            bpy.ops.wm.url_open(url=url)
            context.window_manager.codex_blender_activity = f"Opened web console: {url}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_web_console_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_web_console(Operator):
    bl_idname = "codex_blender_agent.stop_web_console"
    bl_label = "Stop Web Console"
    bl_description = "Stop the local automatic review web console."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().stop_web_console(context)
            context.window_manager.codex_blender_activity = "Stopped web console."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_web_console_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_validate_asset_now(Operator):
    bl_idname = "codex_blender_agent.validate_asset_now"
    bl_label = "Validate Asset Now"
    bl_description = "Run evaluated-geometry validation now and refresh the web console."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime()._handle_web_console_control(context, "validate_now")
            report_id = str(result.get("report_id", ""))
            context.window_manager.codex_blender_activity = f"VERIFYING complete: {report_id or result.get('status', 'validation report')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_show_qa_overlays(Operator):
    bl_idname = "codex_blender_agent.show_qa_overlays"
    bl_label = "Show QA Overlays"
    bl_description = "Mark QA validation overlays as visible for the current scene and web console."

    visible: BoolProperty(name="Visible", default=True)

    def execute(self, context: bpy.types.Context):
        action = "show_overlays" if self.visible else "clear_overlays"
        try:
            get_runtime()._handle_web_console_control(context, action)
            context.window_manager.codex_blender_activity = "QA overlays visible." if self.visible else "QA overlays hidden."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_apply_safe_asset_repair(Operator):
    bl_idname = "codex_blender_agent.apply_safe_asset_repair"
    bl_label = "Apply Safe Asset Repair"
    bl_description = "Queue safe validation repair intent for the next bounded creator patch; destructive fixes remain gated."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime()._handle_web_console_control(context, "apply_safe_repair")
            context.window_manager.codex_blender_activity = f"Repair planner: {result.get('status', result.get('action', 'queued'))}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_explain_current_context(Operator):
    bl_idname = "codex_blender_agent.explain_current_context"
    bl_label = "Explain Context"
    bl_description = "Ask AI to explain what it can see and what it can do next."

    def execute(self, context: bpy.types.Context):
        op = bpy.ops.codex_blender_agent.run_quick_prompt
        return op(prompt_id="explain_context")


class CODEXBLENDERAGENT_OT_start_chat_tutorial(Operator):
    bl_idname = "codex_blender_agent.start_chat_tutorial"
    bl_label = "Start Chat Tutorial"
    bl_description = "Start a conversational tutorial in the N-panel chat."

    def execute(self, context: bpy.types.Context):
        op = bpy.ops.codex_blender_agent.run_quick_prompt
        return op(prompt_id="teach_first_asset")


class CODEXBLENDERAGENT_OT_ai_setup_workflow(Operator):
    bl_idname = "codex_blender_agent.ai_setup_workflow"
    bl_label = "AI Setup Workflow"
    bl_description = "Create an unconnected AI-managed workflow starter from the current prompt."

    prompt: StringProperty(name="Prompt", default="")

    def execute(self, context: bpy.types.Context):
        prompt = self.prompt.strip() or context.window_manager.codex_blender_prompt.strip() or "Set up a simple game asset workflow."
        try:
            result = get_runtime().create_workflow_from_intent(context, prompt)
            context.window_manager.codex_blender_activity = f"Workflow starter: {result.get('name', 'Codex AI Workflow')}"
            bpy.ops.codex_blender_agent.open_workflow_workspace()
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_blank_workflow_tree(Operator):
    bl_idname = "codex_blender_agent.create_blank_workflow_tree"
    bl_label = "Create Blank Workflow"
    bl_description = "Create or open a blank AI Workflow graph without connected starter nodes."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().create_workflow_graph("Codex AI Workflow", with_default_nodes=False)
            context.window_manager.codex_blender_activity = "Opened blank AI Workflow graph."
            bpy.ops.codex_blender_agent.open_workflow_workspace()
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_game_asset_from_prompt(Operator):
    bl_idname = "codex_blender_agent.create_game_asset_from_prompt"
    bl_label = "Create Game Asset"
    bl_description = "Use the current prompt or selection to start the game asset fast lane."

    asset_type: StringProperty(name="Asset type", default="prop")

    def execute(self, context: bpy.types.Context):
        prompt = context.window_manager.codex_blender_prompt.strip()
        if not prompt:
            prompt = f"Turn the current selection into a game-ready {self.asset_type}. Check scale, origin, transforms, materials, naming, and export readiness."
        try:
            route = _send_game_creator_prompt(context, prompt, auto_create_action=True)
            if isinstance(route, dict) and route.get("routed") == "visual_review":
                context.window_manager.codex_blender_activity = f"Auto review running for game asset: {self.asset_type}"
            elif isinstance(route, dict) and route.get("routed") == "card":
                card = route.get("card", {})
                context.window_manager.codex_blender_activity = f"Game asset fast lane needs review: {card.get('title', 'AI action')}"
            else:
                context.window_manager.codex_blender_activity = f"Started game asset fast lane: {self.asset_type}"
            context.window_manager.codex_blender_prompt = ""
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_apply_last_ai_result(Operator):
    bl_idname = "codex_blender_agent.apply_last_ai_result"
    bl_label = "Apply Last AI Result"
    bl_description = "Open the latest result or receipt so it can be applied, inspected, or recovered."

    def execute(self, context: bpy.types.Context):
        return bpy.ops.codex_blender_agent.open_last_result()


class CODEXBLENDERAGENT_OT_set_game_creator_mode(Operator):
    bl_idname = "codex_blender_agent.set_game_creator_mode"
    bl_label = "Set Game Creator Mode"
    bl_description = "Toggle the chat-first Game Creator interface."

    enabled: BoolProperty(name="Enabled", default=True)

    def execute(self, context: bpy.types.Context):
        context.window_manager.codex_blender_game_creator_mode = bool(self.enabled)
        context.window_manager.codex_blender_activity = "Game Creator Mode enabled." if self.enabled else "Game Creator Mode disabled."
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_set_execution_friction(Operator):
    bl_idname = "codex_blender_agent.set_execution_friction"
    bl_label = "Set Execution Friction"
    bl_description = "Set how much review UI appears before local AI work."

    friction: EnumProperty(name="Friction", items=[("fast", "Fast", ""), ("balanced", "Balanced", ""), ("strict", "Strict", "")], default="fast")

    def execute(self, context: bpy.types.Context):
        context.window_manager.codex_blender_execution_friction = self.friction
        context.window_manager.codex_blender_activity = f"Execution friction: {self.friction}."
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_action_from_prompt(Operator):
    bl_idname = "codex_blender_agent.create_action_from_prompt"
    bl_label = "Create Action From Prompt"
    bl_description = "Convert the prompt box into an inspectable AI action card without hiding it in chat."

    def execute(self, context: bpy.types.Context):
        prompt = context.window_manager.codex_blender_prompt.strip()
        if not prompt:
            prompt = read_prompt_draft().strip()
        if not prompt:
            self.report({"WARNING"}, "Enter a prompt or write in Codex Prompt Draft first.")
            return {"CANCELLED"}
        try:
            card = get_runtime().create_action_from_prompt(context, prompt)
            context.window_manager.codex_blender_activity = f"Action card created: {card.get('title', '')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_card_from_prompt(CODEXBLENDERAGENT_OT_create_action_from_prompt):
    bl_idname = "codex_blender_agent.create_card_from_prompt"
    bl_label = "Create Card From Prompt"
    bl_description = "Classify the prompt and create a reviewable card before any scene-changing work."


class CODEXBLENDERAGENT_OT_classify_prompt(Operator):
    bl_idname = "codex_blender_agent.classify_prompt"
    bl_label = "Classify Prompt"
    bl_description = "Classify the prompt as Ask, Inspect, Change, Automate, Recover, or Export."

    def execute(self, context: bpy.types.Context):
        prompt = context.window_manager.codex_blender_prompt.strip() or read_prompt_draft().strip()
        if not prompt:
            self.report({"WARNING"}, "Enter a prompt or write in Codex Prompt Draft first.")
            return {"CANCELLED"}
        try:
            result = get_runtime().classify_prompt(context, prompt)
            context.window_manager.codex_blender_activity = (
                f"Intent: {result.get('intent', 'ask')} | Risk: {result.get('risk', 'low')} | "
                f"{result.get('risk_rationale', '')}"
            )
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_preview_action(Operator):
    bl_idname = "codex_blender_agent.preview_action"
    bl_label = "Preview Action"
    bl_description = "Mark the selected action card as ready for review and approval."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().preview_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_approve_action(Operator):
    bl_idname = "codex_blender_agent.approve_action"
    bl_label = "Approve Action"
    bl_description = "Approve the selected action card and run it if it has a concrete tool call."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().approve_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_cancel_action(Operator):
    bl_idname = "codex_blender_agent.cancel_action"
    bl_label = "Cancel Action"
    bl_description = "Cancel the selected AI action card."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().cancel_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_recover_action(Operator):
    bl_idname = "codex_blender_agent.recover_action"
    bl_label = "Recover Action"
    bl_description = "Record recovery guidance for the selected action card."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().recover_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_action(Operator):
    bl_idname = "codex_blender_agent.stop_action"
    bl_label = "Stop Action"
    bl_description = "Stop the selected running action at the next safe checkpoint."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().stop_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_pause_action(Operator):
    bl_idname = "codex_blender_agent.pause_action"
    bl_label = "Pause Action"
    bl_description = "Mark the selected action as paused."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().pause_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_resume_action(Operator):
    bl_idname = "codex_blender_agent.resume_action"
    bl_label = "Resume Action"
    bl_description = "Resume a paused action."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().resume_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_archive_action(Operator):
    bl_idname = "codex_blender_agent.archive_action"
    bl_label = "Archive Action"
    bl_description = "Archive the selected action from the active working view."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            get_runtime().archive_action(context, action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_inspect_ai_context(Operator):
    bl_idname = "codex_blender_agent.inspect_ai_context"
    bl_label = "Inspect AI Context"
    bl_description = "Refresh visible context chips without sending a model turn."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().sync_window_manager(context, force=True)
            chips = context.window_manager.codex_blender_context_chips
            context.window_manager.codex_blender_context_chip_index = 0 if len(chips) else -1
            enabled = sum(1 for chip in chips if chip.enabled)
            context.window_manager.codex_blender_activity = f"Context refreshed: {enabled} enabled chip(s) visible."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_view_action_changes(Operator):
    bl_idname = "codex_blender_agent.view_action_changes"
    bl_label = "View Action Changes"
    bl_description = "Open the selected action card's intended and observed change ledger."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            card = get_runtime().get_action_detail(context, action_id)
            detail = card.get("detail", {}) if isinstance(card.get("detail", {}), dict) else {}
            payload = {
                "action_id": action_id,
                "title": card.get("title", ""),
                "status": card.get("status", ""),
                "intended_changes": {
                    "scope": card.get("scope_summary", ""),
                    "targets": card.get("affected_targets", []),
                    "outcome": card.get("outcome_summary", ""),
                    "plan": detail.get("short_plan") or card.get("plan_preview", ""),
                },
                "observed_changes": detail.get("change_ledger") or card.get("change_ledger", []),
                "recovery": card.get("recovery", ""),
            }
            _open_text_payload(context, "Codex Action Changes", payload)
            context.window_manager.codex_blender_activity = f"Opened change ledger for {card.get('title', action_id)}."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_undo_last_ai_change(Operator):
    bl_idname = "codex_blender_agent.undo_last_ai_change"
    bl_label = "Undo Last AI Change"
    bl_description = "Use Blender Undo for the latest completed AI action when native undo is available."

    def execute(self, context: bpy.types.Context):
        cards = get_runtime().list_action_cards(context)
        latest = next((card for card in cards if card.get("status") in {"completed", "completed_with_warnings", "recovered"}), None)
        if latest is None:
            self.report({"WARNING"}, "No completed AI action is available for native undo.")
            return {"CANCELLED"}
        try:
            if not bpy.ops.ed.undo.poll():
                self.report({"WARNING"}, "Blender Undo is not available in the current context.")
                return {"CANCELLED"}
            bpy.ops.ed.undo()
            context.window_manager.codex_blender_activity = f"Requested Blender Undo for {latest.get('title', 'the latest AI action')}."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_reset_ai_context(Operator):
    bl_idname = "codex_blender_agent.reset_ai_context"
    bl_label = "Reset AI Context"
    bl_description = "Disable optional context chips and restore safe composer defaults."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        window_manager.codex_blender_activity = "AI context reset: optional chips disabled and safe defaults restored."
        _sync_dashboard_collections(window_manager)
        keep_kinds = {"scope", "selection", "scene", "mode", "object"}
        for chip in window_manager.codex_blender_context_chips:
            if (chip.kind or "").strip().lower() not in keep_kinds:
                chip.enabled = False
        window_manager.codex_blender_active_scope = "selection"
        window_manager.codex_blender_safety_preview_first = True
        window_manager.codex_blender_safety_non_destructive = True
        window_manager.codex_blender_safety_duplicate_first = False
        window_manager.codex_blender_safety_no_deletes = True
        window_manager.codex_blender_safety_require_approval = True
        window_manager.codex_blender_safety_stop_checkpoints = True
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_action_details(Operator):
    bl_idname = "codex_blender_agent.open_action_details"
    bl_label = "Open Action Details"
    bl_description = "Open the selected action card detail payload in the native Text Editor."

    action_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager, self.action_id)
        if not action_id:
            self.report({"WARNING"}, "Select an action card first.")
            return {"CANCELLED"}
        try:
            card = get_runtime().get_action_detail(context, action_id)
            _open_text_payload(context, "Codex Action Details", card)
            context.window_manager.codex_blender_activity = f"Opened action details for {card.get('title', action_id)}."
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_pin_thread_output(Operator):
    bl_idname = "codex_blender_agent.pin_thread_output"
    bl_label = "Pin Thread Output"
    bl_description = "Pin the selected action result or latest assistant output to the current thread."

    title: StringProperty(default="")
    summary: StringProperty(default="")
    kind: StringProperty(default="result")

    def execute(self, context: bpy.types.Context):
        action_id = _selected_action_id(context.window_manager)
        title = self.title or "Pinned AI Output"
        summary = self.summary or context.window_manager.codex_blender_activity or "Pinned from the current AI thread."
        try:
            get_runtime().pin_output_to_thread(context, title=title, summary=summary, kind=self.kind, action_id=action_id)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_thread_detail(Operator):
    bl_idname = "codex_blender_agent.open_thread_detail"
    bl_label = "Open Thread Detail"
    bl_description = "Open the transcript detail view for the selected or active thread."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_dashboard_chat(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_toolbox_action(Operator):
    bl_idname = "codex_blender_agent.create_toolbox_action"
    bl_label = "Create Toolbox Action"
    bl_description = "Create an action card from the selected toolbox recipe or system."

    def execute(self, context: bpy.types.Context):
        items = context.window_manager.codex_blender_toolbox_items
        index = context.window_manager.codex_blender_toolbox_index
        if index < 0 or index >= len(items):
            self.report({"WARNING"}, "Select a toolbox item first.")
            return {"CANCELLED"}
        item = items[index]
        try:
            get_runtime().create_action_card(
                context,
                title=f"Run {item.name or item.item_id}",
                prompt=item.description,
                plan="Run this reusable toolbox system through the safe tool registry.",
                tool_name="run_toolbox_system",
                arguments={"item_id_or_name": item.item_id or item.name},
                affected_targets=[context.window_manager.codex_blender_active_scope],
                required_context=[context.window_manager.codex_blender_active_scope],
                status="needs_approval",
            )
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_ai_surface(Operator):
    bl_idname = "codex_blender_agent.open_ai_surface"
    bl_label = "Open AI Surface"
    bl_description = "Open AI Studio, Workflow, Assets, or transcript detail."

    surface: EnumProperty(
        name="Surface",
        items=[
            ("studio", "AI Studio", "Open the AI Studio workspace."),
            ("dashboard", "AI Studio (Legacy)", "Open AI Studio through the old dashboard alias."),
            ("workflow", "Workflow", "Open the Workflow workspace."),
            ("assets", "Assets", "Open the Assets workspace."),
            ("thread", "Thread Detail", "Open the thread transcript detail."),
        ],
        default="studio",
    )

    def execute(self, context: bpy.types.Context):
        if self.surface == "workflow":
            return bpy.ops.codex_blender_agent.open_workflow_workspace()
        if self.surface == "assets":
            return bpy.ops.codex_blender_agent.open_assets_workspace()
        if self.surface == "thread":
            return bpy.ops.codex_blender_agent.open_thread_detail()
        return bpy.ops.codex_blender_agent.open_studio_workspace()


class CODEXBLENDERAGENT_OT_login(Operator):
    bl_idname = "codex_blender_agent.login"
    bl_label = "Login with ChatGPT"
    bl_description = "Start the official Codex ChatGPT browser login flow."

    def execute(self, context: bpy.types.Context):
        try:
            url = get_runtime().login(context)
            _sync_dashboard_collections(context.window_manager)
            bpy.ops.wm.url_open(url=url)
            self.report({"INFO"}, "Opened the Codex ChatGPT login page in your browser.")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_new_thread(Operator):
    bl_idname = "codex_blender_agent.new_thread"
    bl_label = "New Thread"
    bl_description = "Clear the current in-Blender conversation and start a new Codex thread on the next prompt."

    def execute(self, context: bpy.types.Context):
        get_runtime().new_thread(context)
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_turn(Operator):
    bl_idname = "codex_blender_agent.stop_turn"
    bl_label = "Stop Current Turn"
    bl_description = "Interrupt the currently running Codex turn without stopping the app-server."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().interrupt_turn()
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_clear_local_messages(Operator):
    bl_idname = "codex_blender_agent.clear_local_messages"
    bl_label = "Hide Messages"
    bl_description = "Clear the local visible transcript while keeping the active Codex thread."

    def execute(self, context: bpy.types.Context):
        get_runtime().clear_local_messages()
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_steer_turn(Operator):
    bl_idname = "codex_blender_agent.steer_turn"
    bl_label = "Guide Running Turn"
    bl_description = "Send the prompt box text as a steering update to the currently running Codex turn."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        prompt = window_manager.codex_blender_prompt.strip()
        if not prompt:
            self.report({"WARNING"}, "Enter guidance in the prompt box first.")
            return {"CANCELLED"}
        try:
            get_runtime().steer_turn(prompt)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        window_manager.codex_blender_prompt = ""
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_add_attachment(Operator):
    bl_idname = "codex_blender_agent.add_attachment"
    bl_label = "Add Attachment"
    bl_description = "Attach an image or file to the next Codex message."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        path = window_manager.codex_blender_attachment_path.strip()
        if not path:
            self.report({"WARNING"}, "Choose a file to attach first.")
            return {"CANCELLED"}
        existing = {item.path for item in window_manager.codex_blender_attachments}
        if path not in existing:
            item = window_manager.codex_blender_attachments.add()
            item.path = path
            item.kind = classify_attachment(path)
        window_manager.codex_blender_attachment_path = ""
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_remove_attachment(Operator):
    bl_idname = "codex_blender_agent.remove_attachment"
    bl_label = "Remove Attachment"
    bl_description = "Remove an attachment from the next Codex message."

    index: IntProperty(default=-1)

    def execute(self, context: bpy.types.Context):
        attachments = context.window_manager.codex_blender_attachments
        if self.index < 0 or self.index >= len(attachments):
            return {"CANCELLED"}
        attachments.remove(self.index)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_clear_attachments(Operator):
    bl_idname = "codex_blender_agent.clear_attachments"
    bl_label = "Clear Attachments"
    bl_description = "Clear all attachments from the next Codex message."

    def execute(self, context: bpy.types.Context):
        context.window_manager.codex_blender_attachments.clear()
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_send_prompt_from_text(Operator):
    bl_idname = "codex_blender_agent.send_prompt_from_text"
    bl_label = "Send Prompt Draft"
    bl_description = "Send the contents of the Codex Prompt Draft text block."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().send_prompt_from_text(context)
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_send_prompt_literal(Operator):
    bl_idname = "codex_blender_agent.send_prompt_literal"
    bl_label = "Send Prompt Literal"
    bl_description = "Send a literal prompt from the runnable Codex Prompt Draft text block."

    prompt: StringProperty(default="")
    create_action: BoolProperty(
        name="Create action card",
        description="Compatibility option. Fast Game Creator Mode only creates cards for high-risk prompts.",
        default=False,
    )

    def execute(self, context: bpy.types.Context):
        prompt = (self.prompt or "").strip()
        if not prompt:
            self.report({"WARNING"}, "Codex Prompt Draft is empty.")
            return {"CANCELLED"}
        wm = context.window_manager
        try:
            model = wm.codex_blender_model
            if model == "__none__":
                model = ""
            route = get_runtime().send_prompt(
                context=context,
                prompt=prompt,
                include_scene_context=wm.codex_blender_include_scene_context,
                model=model,
                effort=wm.codex_blender_effort,
                attachments=[item.path for item in wm.codex_blender_attachments],
                chat_mode=wm.codex_blender_chat_mode,
                auto_create_action=self.create_action,
            )
            get_runtime().clear_prompt_draft()
            wm.codex_blender_attachments.clear()
            if isinstance(route, dict) and route.get("routed") == "card":
                card = route.get("card", {})
                wm.codex_blender_activity = f"Prompt draft created review card: {card.get('title', 'AI Action')}"
            else:
                wm.codex_blender_activity = "Prompt draft sent to Codex."
            _sync_dashboard_collections(wm)
        except Exception as exc:
            wm.codex_blender_error = str(exc)
            wm.codex_blender_activity = "Prompt draft was not sent. Enable Blender online access or start Codex service, then try again."
            _sync_dashboard_collections(wm)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_clear_prompt_draft(Operator):
    bl_idname = "codex_blender_agent.clear_prompt_draft"
    bl_label = "Clear Prompt Draft"
    bl_description = "Clear the Codex Prompt Draft text block."

    def execute(self, context: bpy.types.Context):
        get_runtime().clear_prompt_draft()
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_reset_prompt_draft_template(Operator):
    bl_idname = "codex_blender_agent.reset_prompt_draft_template"
    bl_label = "Reset Prompt Draft Template"
    bl_description = "Reset Codex Prompt Draft to a runnable Blender Python wrapper."

    def execute(self, context: bpy.types.Context):
        get_runtime().reset_prompt_draft_template(context.window_manager.codex_blender_prompt)
        context.window_manager.codex_blender_activity = "Codex Prompt Draft reset. Use Send Draft or Blender Run Script."
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_chat_transcript(Operator):
    bl_idname = "codex_blender_agent.refresh_chat_transcript"
    bl_label = "Refresh Chat Transcript"
    bl_description = "Refresh the Codex Chat Transcript and Activity Log text blocks."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().refresh_chat_transcript(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_dashboard_chat(Operator):
    bl_idname = "codex_blender_agent.open_dashboard_chat"
    bl_label = "Open Prompt Draft"
    bl_description = "Switch the current area to the Codex Prompt Draft text block."

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().open_dashboard_chat(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_toolbox(Operator):
    bl_idname = "codex_blender_agent.refresh_toolbox"
    bl_label = "Refresh Toolbox"
    bl_description = "Refresh the visible toolbox memory list."

    def execute(self, context: bpy.types.Context):
        try:
            items = get_runtime().refresh_toolbox_items(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        toolbox_items = context.window_manager.codex_blender_toolbox_items
        toolbox_items.clear()
        for item in items[:30]:
            entry = toolbox_items.add()
            entry.item_id = item.get("id", "")
            entry.name = item.get("name", "")
            entry.category = normalize_toolbox_group(item.get("category", ""), item.get("name", ""))
            entry.description = item.get("description", "")
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_delete_toolbox_item(Operator):
    bl_idname = "codex_blender_agent.delete_toolbox_item"
    bl_label = "Delete Toolbox Item"
    bl_description = "Delete a stored toolbox memory item."

    item_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        if not self.item_id:
            return {"CANCELLED"}
        try:
            get_runtime().delete_toolbox_item(context, self.item_id)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        bpy.ops.codex_blender_agent.refresh_toolbox()
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_refresh_assets(Operator):
    bl_idname = "codex_blender_agent.refresh_assets"
    bl_label = "Refresh Assets"
    bl_description = "Refresh the visible asset library list."

    def execute(self, context: bpy.types.Context):
        try:
            items = get_runtime().refresh_asset_items(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        asset_items = context.window_manager.codex_blender_asset_items
        asset_items.clear()
        for item in items[:30]:
            entry = asset_items.add()
            entry.item_id = item.get("id", "")
            entry.name = item.get("name", "")
            entry.category = item.get("category", "")
            entry.kind = item.get("kind", "")
            entry.path = item.get("stored_path", "")
            entry.description = item.get("description", "")
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_delete_asset_item(Operator):
    bl_idname = "codex_blender_agent.delete_asset_item"
    bl_label = "Delete Asset Item"
    bl_description = "Delete a stored asset-library item."

    item_id: StringProperty(default="")

    def execute(self, context: bpy.types.Context):
        if not self.item_id:
            return {"CANCELLED"}
        try:
            get_runtime().delete_asset_item(context, self.item_id)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        bpy.ops.codex_blender_agent.refresh_assets()
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_save_selected_asset(Operator):
    bl_idname = "codex_blender_agent.save_selected_asset"
    bl_label = "Save Selected Asset"
    bl_description = "Save selected objects into the local Codex asset library as a .blend bundle."

    def execute(self, context: bpy.types.Context):
        name = context.window_manager.codex_blender_asset_name.strip()
        if not name:
            self.report({"WARNING"}, "Enter an asset name first.")
            return {"CANCELLED"}
        try:
            result = get_runtime().save_selected_asset_from_ui(context, name)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if isinstance(result, dict) and result.get("action_id"):
            context.window_manager.codex_blender_activity = "Save Selected created a publish card. Review and approve it from AI Studio before any asset file is written."
            self.report({"INFO"}, "Asset publish card created.")
        else:
            context.window_manager.codex_blender_asset_name = ""
            context.window_manager.codex_blender_activity = f"Saved selected asset: {result}"
        bpy.ops.codex_blender_agent.refresh_assets()
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_import_selected_asset(Operator):
    bl_idname = "codex_blender_agent.import_selected_asset"
    bl_label = "Import Selected Asset"
    bl_description = "Append/import the selected asset-library item into the current scene."

    link: BoolProperty(name="Link", default=False)

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().import_selected_asset_from_ui(context, link=self.link)
            if isinstance(result, dict) and result.get("action_id"):
                context.window_manager.codex_blender_activity = "Import created an action card. Review and approve it from AI Studio before the scene is changed."
                self.report({"INFO"}, "Asset import card created.")
            else:
                context.window_manager.codex_blender_activity = f"Imported asset: {result}"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        bpy.ops.codex_blender_agent.refresh_assets()
        _sync_dashboard_collections(context.window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_open_chat_view(Operator):
    bl_idname = "codex_blender_agent.open_chat_view"
    bl_label = "Open Chat View"
    bl_description = "Switch the current Blender area to a dedicated Text Editor chat/transcript view."

    def execute(self, context: bpy.types.Context):
        text = get_runtime().update_chat_text_block(context)
        _sync_dashboard_collections(context.window_manager)
        if context.area is not None:
            try:
                context.area.type = "TEXT_EDITOR"
                for space in context.area.spaces:
                    if space.type == "TEXT_EDITOR":
                        space.text = text
                        space.show_word_wrap = True
                        break
            except Exception as exc:
                self.report({"WARNING"}, f"Created transcript text, but could not switch area: {exc}")
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_add_workflow_node(Operator):
    bl_idname = "codex_blender_agent.add_workflow_node"
    bl_label = "Add Workflow Node"
    bl_description = "Add a node to the Codex AI Workflow graph."

    node_type: EnumProperty(
        name="Node Type",
        items=[(key, value["label"], value["label"]) for key, value in NODE_TYPES.items()],
        default="tool_call",
    )

    def execute(self, context: bpy.types.Context):
        try:
            get_runtime().create_workflow_graph("Codex AI Workflow", with_default_nodes=False)
            get_runtime().add_workflow_node("Codex AI Workflow", self.node_type)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_create_example_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.create_example_workflow_graph"
    bl_label = "Create Example Workflow Graph"
    bl_description = "Create a practical Codex AI Workflow example graph."

    example_id: EnumProperty(
        name="Example",
        description="Practical workflow example to build.",
        items=workflow_example_items(),
        default="scene_inspector",
    )

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().create_example_workflow_graph(context, self.example_id)
            context.window_manager.codex_blender_activity = f"Created workflow example: {result.get('name', 'Codex AI Workflow')}"
            _sync_dashboard_collections(context.window_manager)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_run_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.run_workflow_graph"
    bl_label = "Run Workflow Graph"
    bl_description = "Preview or run the Codex AI Workflow graph."

    preview_only: BoolProperty(name="Preview only", default=True)

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().run_workflow_graph(context, "Codex AI Workflow", preview_only=self.preview_only)
            context.window_manager.codex_blender_activity = f"Workflow results: {len(result.get('results', []))} node(s)."
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_validate_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.validate_workflow_graph"
    bl_label = "Validate Workflow Graph"
    bl_description = "Validate the v0.10 typed Workflow graph without execution."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().validate_workflow_graph(context, self.graph_name)
            context.window_manager.codex_blender_activity = f"Workflow validation: {'OK' if result.get('ok') else 'needs review'} ({result.get('node_count', 0)} nodes)."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if result.get("ok") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_compile_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.compile_workflow_graph"
    bl_label = "Compile Workflow Graph"
    bl_description = "Compile the v0.10 typed Workflow graph into a durable run plan."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().compile_workflow_graph(context, self.graph_name)
            context.window_manager.codex_blender_activity = f"Workflow compile: {len(result.get('steps', []))} step(s), blocked={bool(result.get('blocked'))}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if result.get("ok") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_preview_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.preview_workflow_graph"
    bl_label = "Preview Workflow Graph"
    bl_description = "Preview the v0.10 Workflow graph safely; risky steps create review cards."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().preview_workflow_graph(context, self.graph_name)
            context.window_manager.codex_blender_activity = f"Workflow preview: {len(result.get('preview_steps', []))} step(s); run {result.get('run', {}).get('run_id', '')}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if result.get("ok") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_start_workflow_run(Operator):
    bl_idname = "codex_blender_agent.start_workflow_run"
    bl_label = "Start Workflow Run"
    bl_description = "Start a checkpointed v0.10 Workflow run."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().start_workflow_run(context, self.graph_name)
            run = result.get("run", {})
            context.window_manager.codex_blender_activity = f"Workflow run {run.get('run_id', '')}: {run.get('status', run.get('state', 'queued'))}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if not result.get("error") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_resume_workflow_run(Operator):
    bl_idname = "codex_blender_agent.resume_workflow_run"
    bl_label = "Resume Workflow Run"
    bl_description = "Resume the latest or specified v0.10 Workflow run."

    run_id: StringProperty(name="Run ID", default="")

    def execute(self, context: bpy.types.Context):
        try:
            run_id = self.run_id or _latest_workflow_run_id(context)
            if not run_id:
                raise RuntimeError("No workflow run exists to resume.")
            result = get_runtime().resume_workflow_run(context, run_id)
            context.window_manager.codex_blender_activity = f"Workflow run {run_id}: {result.get('status', result.get('state', 'running'))}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_stop_workflow_run(Operator):
    bl_idname = "codex_blender_agent.stop_workflow_run"
    bl_label = "Stop Workflow Run"
    bl_description = "Stop the latest or specified v0.10 Workflow run at a safe checkpoint."

    run_id: StringProperty(name="Run ID", default="")
    reason: StringProperty(name="Reason", default="Stopped from Workflow UI.")

    def execute(self, context: bpy.types.Context):
        try:
            run_id = self.run_id or _latest_workflow_run_id(context)
            if not run_id:
                raise RuntimeError("No workflow run exists to stop.")
            result = get_runtime().stop_workflow_run(context, run_id, self.reason)
            context.window_manager.codex_blender_activity = f"Workflow run {run_id}: {result.get('status', result.get('state', 'paused'))}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_publish_workflow_recipe(Operator):
    bl_idname = "codex_blender_agent.publish_workflow_recipe"
    bl_label = "Publish Workflow Recipe"
    bl_description = "Publish the current Workflow graph as a versioned recipe record."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().publish_workflow_recipe(context, self.graph_name)
            recipe = result.get("recipe", {})
            context.window_manager.codex_blender_activity = f"Published workflow recipe: {recipe.get('recipe_version_uid', recipe.get('name', 'recipe'))}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_propose_workflow_patch(Operator):
    bl_idname = "codex_blender_agent.propose_workflow_patch"
    bl_label = "Propose Workflow Patch"
    bl_description = "Create a staged structured graph patch proposal without mutating the live graph."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")
    operations_json: StringProperty(name="Operations JSON", default='[{"op":"add_node","node":{"name":"Preview Tap","label":"Preview Tap","node_type":"preview_tap"}}]')

    def execute(self, context: bpy.types.Context):
        try:
            operations = json.loads(self.operations_json or "[]")
            if not isinstance(operations, list):
                raise RuntimeError("Workflow patch operations must be a JSON array.")
            result = get_runtime().propose_workflow_patch(context, self.graph_name, operations)
            stored = result.get("stored", {})
            context.window_manager.codex_blender_activity = f"Workflow patch proposal: {stored.get('patch_id', 'draft')}."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO" if result.get("proposal", {}).get("ok") else "WARNING"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_apply_workflow_patch(Operator):
    bl_idname = "codex_blender_agent.apply_workflow_patch"
    bl_label = "Apply Workflow Patch"
    bl_description = "Apply a validated structured graph patch to the live Workflow graph."

    graph_name: StringProperty(name="Graph", default="Codex AI Workflow")
    operations_json: StringProperty(name="Operations JSON", default='[{"op":"add_node","node":{"name":"Preview Tap","label":"Preview Tap","node_type":"preview_tap"}}]')

    def execute(self, context: bpy.types.Context):
        try:
            operations = json.loads(self.operations_json or "[]")
            if not isinstance(operations, list):
                raise RuntimeError("Workflow patch operations must be a JSON array.")
            result = get_runtime().apply_workflow_patch(context, self.graph_name, operations)
            context.window_manager.codex_blender_activity = f"Applied workflow patch: {len(result.get('diff', {}).get('added_nodes', []))} node(s) added."
            _sync_dashboard_collections(context.window_manager)
            self.report({"INFO"}, context.window_manager.codex_blender_activity)
        except Exception as exc:
            context.window_manager.codex_blender_error = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_inspect_workflow_graph(Operator):
    bl_idname = "codex_blender_agent.inspect_workflow_graph"
    bl_label = "Inspect Workflow Graph"
    bl_description = "Print the current Codex AI Workflow graph structure to the console."

    def execute(self, context: bpy.types.Context):
        try:
            result = get_runtime().workflow_graphs()
            context.window_manager.codex_blender_activity = f"Workflow graphs: {len(result)}"
            print("Codex Blender Agent workflow graphs:", result)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_send_prompt(Operator):
    bl_idname = "codex_blender_agent.send_prompt"
    bl_label = "Send"
    bl_description = "Send the current prompt to Codex."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        prompt = window_manager.codex_blender_prompt.strip()
        if not prompt:
            self.report({"WARNING"}, "Enter a prompt first.")
            return {"CANCELLED"}

        model = window_manager.codex_blender_model
        if model == "__none__":
            model = ""

        try:
            attachment_paths = [item.path for item in window_manager.codex_blender_attachments]
            route = get_runtime().send_prompt(
                context=context,
                prompt=prompt,
                include_scene_context=window_manager.codex_blender_include_scene_context,
                model=model,
                effort=window_manager.codex_blender_effort,
                attachments=attachment_paths,
                chat_mode=window_manager.codex_blender_chat_mode,
            )
            if isinstance(route, dict) and route.get("routed") == "card":
                card = route.get("card", {})
                window_manager.codex_blender_activity = f"Created review card: {card.get('title', 'AI Action')}"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        window_manager.codex_blender_prompt = ""
        window_manager.codex_blender_attachments.clear()
        _sync_dashboard_collections(window_manager)
        return {"FINISHED"}


class CODEXBLENDERAGENT_OT_expand_prompt(Operator):
    bl_idname = "codex_blender_agent.expand_prompt"
    bl_label = "Expand Prompt"
    bl_description = "Rewrite the current prompt into a fuller game-asset brief without changing the scene."

    def execute(self, context: bpy.types.Context):
        window_manager = context.window_manager
        prompt = window_manager.codex_blender_prompt.strip()
        selected_objects = list(getattr(context, "selected_objects", []) or [])
        scene_context = {
            "scene_name": getattr(getattr(context, "scene", None), "name", ""),
            "active_object": getattr(getattr(context, "active_object", None), "name", ""),
            "selected_objects": [obj.name for obj in selected_objects],
            "visible_object_count": len(getattr(getattr(context, "scene", None), "objects", []) or []),
            "materials": [
                slot.material.name
                for obj in selected_objects
                for slot in getattr(obj, "material_slots", []) or []
                if getattr(slot, "material", None) is not None and getattr(slot.material, "name", "")
            ],
        }
        expanded = expand_prompt(prompt, scene_context=scene_context)
        window_manager.codex_blender_prompt = expanded
        write_prompt_draft_body(expanded)
        window_manager.codex_blender_activity = "Expanded the prompt into a fuller game-asset brief."
        try:
            get_runtime().record_prompt_event(
                context,
                "expanded",
                expanded,
                label="PROMPT EXPANDED",
                source="n_panel",
                expanded_from=prompt,
                route="draft",
            )
        except Exception:
            pass
        _sync_dashboard_collections(window_manager)
        return {"FINISHED"}


CLASSES = (
    CODEXBLENDERAGENT_OT_start_service,
    CODEXBLENDERAGENT_OT_stop_service,
    CODEXBLENDERAGENT_OT_refresh_state,
    CODEXBLENDERAGENT_OT_open_dashboard_workspace,
    CODEXBLENDERAGENT_OT_open_studio_workspace,
    CODEXBLENDERAGENT_OT_open_workflow_workspace,
    CODEXBLENDERAGENT_OT_open_assets_workspace,
    CODEXBLENDERAGENT_OT_install_workspace_templates,
    CODEXBLENDERAGENT_OT_create_ai_workspaces,
    CODEXBLENDERAGENT_OT_migrate_legacy_ai_workspaces,
    CODEXBLENDERAGENT_OT_repair_ai_workspace,
    CODEXBLENDERAGENT_OT_verify_workspace_suite,
    CODEXBLENDERAGENT_OT_open_ai_workspace,
    CODEXBLENDERAGENT_OT_use_selection_in_workflow,
    CODEXBLENDERAGENT_OT_open_last_result,
    CODEXBLENDERAGENT_OT_open_result_in_workflow,
    CODEXBLENDERAGENT_OT_open_result_in_assets,
    CODEXBLENDERAGENT_OT_refresh_dashboard,
    CODEXBLENDERAGENT_OT_diagnose_dashboard_workspace,
    CODEXBLENDERAGENT_OT_select_project,
    CODEXBLENDERAGENT_OT_select_thread,
    CODEXBLENDERAGENT_OT_compact_thread,
    CODEXBLENDERAGENT_OT_pause_transcript_redraw,
    CODEXBLENDERAGENT_OT_set_ai_scope,
    CODEXBLENDERAGENT_OT_toggle_context_chip,
    CODEXBLENDERAGENT_OT_open_tutorial,
    CODEXBLENDERAGENT_OT_next_tutorial_step,
    CODEXBLENDERAGENT_OT_previous_tutorial_step,
    CODEXBLENDERAGENT_OT_reset_tutorial,
    CODEXBLENDERAGENT_OT_complete_tutorial,
    CODEXBLENDERAGENT_OT_open_quickstart_doc,
    CODEXBLENDERAGENT_OT_open_tutorial_target,
    CODEXBLENDERAGENT_OT_run_tutorial_step,
    CODEXBLENDERAGENT_OT_check_tutorial_step,
    CODEXBLENDERAGENT_OT_fix_tutorial_step,
    CODEXBLENDERAGENT_OT_register_asset_library,
    CODEXBLENDERAGENT_OT_initialize_ai_assets_store,
    CODEXBLENDERAGENT_OT_migrate_ai_assets_store,
    CODEXBLENDERAGENT_OT_verify_ai_assets,
    CODEXBLENDERAGENT_OT_repair_ai_assets,
    CODEXBLENDERAGENT_OT_index_asset_libraries,
    CODEXBLENDERAGENT_OT_refresh_asset_index,
    CODEXBLENDERAGENT_OT_create_asset_publish_action,
    CODEXBLENDERAGENT_OT_promote_output_to_asset,
    CODEXBLENDERAGENT_OT_validate_asset_version,
    CODEXBLENDERAGENT_OT_generate_asset_preview,
    CODEXBLENDERAGENT_OT_publish_asset_package,
    CODEXBLENDERAGENT_OT_import_asset_package,
    CODEXBLENDERAGENT_OT_pin_asset_version,
    CODEXBLENDERAGENT_OT_fork_asset_version,
    CODEXBLENDERAGENT_OT_append_asset_version,
    CODEXBLENDERAGENT_OT_link_asset_version,
    CODEXBLENDERAGENT_OT_send_npanel_chat,
    CODEXBLENDERAGENT_OT_run_quick_prompt,
    CODEXBLENDERAGENT_OT_start_visual_review_loop,
    CODEXBLENDERAGENT_OT_stop_visual_review_loop,
    CODEXBLENDERAGENT_OT_continue_visual_review_loop,
    CODEXBLENDERAGENT_OT_open_visual_review_run,
    CODEXBLENDERAGENT_OT_capture_visual_review_viewpoints,
    CODEXBLENDERAGENT_OT_start_web_console,
    CODEXBLENDERAGENT_OT_open_web_console,
    CODEXBLENDERAGENT_OT_stop_web_console,
    CODEXBLENDERAGENT_OT_validate_asset_now,
    CODEXBLENDERAGENT_OT_show_qa_overlays,
    CODEXBLENDERAGENT_OT_apply_safe_asset_repair,
    CODEXBLENDERAGENT_OT_explain_current_context,
    CODEXBLENDERAGENT_OT_start_chat_tutorial,
    CODEXBLENDERAGENT_OT_ai_setup_workflow,
    CODEXBLENDERAGENT_OT_create_blank_workflow_tree,
    CODEXBLENDERAGENT_OT_create_game_asset_from_prompt,
    CODEXBLENDERAGENT_OT_apply_last_ai_result,
    CODEXBLENDERAGENT_OT_set_game_creator_mode,
    CODEXBLENDERAGENT_OT_set_execution_friction,
    CODEXBLENDERAGENT_OT_classify_prompt,
    CODEXBLENDERAGENT_OT_create_action_from_prompt,
    CODEXBLENDERAGENT_OT_create_card_from_prompt,
    CODEXBLENDERAGENT_OT_preview_action,
    CODEXBLENDERAGENT_OT_approve_action,
    CODEXBLENDERAGENT_OT_cancel_action,
    CODEXBLENDERAGENT_OT_recover_action,
    CODEXBLENDERAGENT_OT_stop_action,
    CODEXBLENDERAGENT_OT_pause_action,
    CODEXBLENDERAGENT_OT_resume_action,
    CODEXBLENDERAGENT_OT_archive_action,
    CODEXBLENDERAGENT_OT_inspect_ai_context,
    CODEXBLENDERAGENT_OT_view_action_changes,
    CODEXBLENDERAGENT_OT_undo_last_ai_change,
    CODEXBLENDERAGENT_OT_reset_ai_context,
    CODEXBLENDERAGENT_OT_open_action_details,
    CODEXBLENDERAGENT_OT_pin_thread_output,
    CODEXBLENDERAGENT_OT_open_thread_detail,
    CODEXBLENDERAGENT_OT_create_toolbox_action,
    CODEXBLENDERAGENT_OT_open_ai_surface,
    CODEXBLENDERAGENT_OT_login,
    CODEXBLENDERAGENT_OT_new_thread,
    CODEXBLENDERAGENT_OT_stop_turn,
    CODEXBLENDERAGENT_OT_clear_local_messages,
    CODEXBLENDERAGENT_OT_steer_turn,
    CODEXBLENDERAGENT_OT_add_attachment,
    CODEXBLENDERAGENT_OT_remove_attachment,
    CODEXBLENDERAGENT_OT_clear_attachments,
    CODEXBLENDERAGENT_OT_send_prompt_from_text,
    CODEXBLENDERAGENT_OT_send_prompt_literal,
    CODEXBLENDERAGENT_OT_clear_prompt_draft,
    CODEXBLENDERAGENT_OT_reset_prompt_draft_template,
    CODEXBLENDERAGENT_OT_refresh_chat_transcript,
    CODEXBLENDERAGENT_OT_open_dashboard_chat,
    CODEXBLENDERAGENT_OT_expand_prompt,
    CODEXBLENDERAGENT_OT_refresh_toolbox,
    CODEXBLENDERAGENT_OT_delete_toolbox_item,
    CODEXBLENDERAGENT_OT_refresh_assets,
    CODEXBLENDERAGENT_OT_delete_asset_item,
    CODEXBLENDERAGENT_OT_save_selected_asset,
    CODEXBLENDERAGENT_OT_import_selected_asset,
    CODEXBLENDERAGENT_OT_open_chat_view,
    CODEXBLENDERAGENT_OT_add_workflow_node,
    CODEXBLENDERAGENT_OT_create_example_workflow_graph,
    CODEXBLENDERAGENT_OT_run_workflow_graph,
    CODEXBLENDERAGENT_OT_validate_workflow_graph,
    CODEXBLENDERAGENT_OT_compile_workflow_graph,
    CODEXBLENDERAGENT_OT_preview_workflow_graph,
    CODEXBLENDERAGENT_OT_start_workflow_run,
    CODEXBLENDERAGENT_OT_resume_workflow_run,
    CODEXBLENDERAGENT_OT_stop_workflow_run,
    CODEXBLENDERAGENT_OT_publish_workflow_recipe,
    CODEXBLENDERAGENT_OT_propose_workflow_patch,
    CODEXBLENDERAGENT_OT_apply_workflow_patch,
    CODEXBLENDERAGENT_OT_inspect_workflow_graph,
    CODEXBLENDERAGENT_OT_send_prompt,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
