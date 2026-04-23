from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import asdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import bpy
import mathutils
from bpy.app.handlers import persistent

from .ai_assets_store import AIAssetsStore, asset_version_to_legacy_item
from .asset_library import asset_library_root, diagnose_ai_asset_libraries, list_asset_libraries, mark_local_ids_as_assets, register_ai_asset_libraries, register_asset_library
from .asset_store import AssetStore, summarize_assets
from .addon_settings import get_addon_preferences
from .attachments import build_attachment_payload
from .chat_surfaces import (
    PROMPT_TEXT,
    append_activity_event,
    clear_prompt_draft,
    ensure_chat_text_blocks,
    read_prompt_draft,
    write_activity_log,
    write_prompt_draft_body,
    write_transcript,
)
from .constants import ADDON_ID, ADDON_VERSION, MAX_VISIBLE_MESSAGES, short_thread_id
from .core.service import CodexService
from .dashboard_store import DEFAULT_PROJECT_ID, DashboardStore, make_project_id
from .dispatcher import MainThreadDispatcher
from .asset_validation import validate_scene_asset
from .game_creator import creator_context_payload, prompt_execution_decision, should_auto_start_visual_review, tool_execution_decision
from .model_defaults import DEFAULT_REASONING_EFFORT, preferred_model_id, valid_reasoning_effort
from .quick_prompts import get_quick_prompt, list_quick_prompts, quick_prompt_payload, render_quick_prompt
from .scene_tools import execute_tool
from .storage import ChatHistoryStore
from .studio_state import (
    approval_policy_for_risk,
    build_risk_axes,
    classify_prompt_intent,
    compact_text,
    context_payload_from_chips,
    make_context_chip,
    normalize_action_status,
    normalize_scope,
    normalize_toolbox_group,
    risk_from_axes,
    transition_allowed,
)
from .surface_registry import list_blender_surfaces, list_cached_operator_namespaces
from .tool_policy import action_id_from_arguments, classify_tool, strip_action_metadata, summarize_arguments
from .toolbox import ToolboxStore, summarize_entries
from .tool_specs import get_dynamic_tool_specs
from .validation_manifest import build_constraint_graph, normalize_asset_intent_manifest
from .validation_repair import build_asset_repair_plan
from .visual_review import (
    DEFAULT_CAPTURE_MODE,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_SCREENSHOT_RESOLUTION,
    DEFAULT_TARGET_SCORE,
    MUTATION_BLOCKED_PHASES,
    PHASE_CAPTURING,
    PHASE_COMPLETE,
    PHASE_CREATOR_RUNNING,
    PHASE_CRITIC_RUNNING,
    PHASE_FAILED,
    PHASE_STOPPED,
    VisualReviewStore,
    build_critic_prompt,
    parse_critique,
    plan_viewpoints,
)
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
    build_geometry_digest,
    hard_gates,
    hybrid_score,
)
from .visual_view_planner import plan_geometry_review_viewpoints
from .web_console import WebConsoleServer
from .workflow_execution import (
    apply_workflow_patch as apply_workflow_patch_model,
    compile_workflow_graph as compile_workflow_graph_model,
    preview_workflow_graph as preview_workflow_graph_model,
    preview_workflow_patch as preview_workflow_patch_model,
    propose_workflow_patch as propose_workflow_patch_model,
    resume_workflow_run as resume_workflow_run_model,
    start_workflow_run as start_workflow_run_model,
    stop_workflow_run as stop_workflow_run_model,
    validate_workflow_graph as validate_workflow_graph_model,
    workflow_graph_manifest,
)
from .workflow_nodes import add_workflow_node, connect_workflow_nodes, create_workflow_graph, inspect_workflow_graph, list_workflow_graphs, run_workflow_graph, set_workflow_node_config
from .workflow_examples import get_workflow_example
from .workflow_recipes import validate_graph_patch_proposal, validate_recipe_metadata
from .workflow_runtime_store import WorkflowRuntimeStore
from .workspace import (
    dashboard_context,
    ensure_studio_workspace,
    diagnose_dashboard_workspace,
    ensure_assets_workspace,
    ensure_codex_suite_workspaces,
    ensure_dashboard_workspace,
    ensure_workflow_workspace,
    migrate_legacy_ai_workspaces,
    verify_workspace_suite,
)


class BlenderAddonRuntime:
    def __init__(self) -> None:
        self.dispatcher = MainThreadDispatcher()
        self.service = CodexService(
            dynamic_tools=get_dynamic_tool_specs(),
            tool_handler=self._dispatch_tool_call,
        )
        self._last_synced_version = -1
        self._active_chat_mode = ""
        self._last_dashboard_signature = ""
        self._current_action_id = ""
        self._stopping_actions: set[str] = set()
        self._auto_receipt_actions: set[str] = set()
        self._visual_review_active_run_id = ""
        self._visual_review_last_turn_in_progress = False
        self._web_console: WebConsoleServer | None = None
        self._web_console_cache: dict[str, Any] = {}
        self._web_console_sequence = 0
        self._prompt_events: list[dict[str, Any]] = []
        self._automation_events: list[dict[str, Any]] = []
        self._console_log_rows: list[dict[str, Any]] = []
        self._web_console_auto_started = False
        self._last_scene_object_names: set[str] = set()
        self._last_stream_recovering = False

    def start(self, context: bpy.types.Context, *, refresh_service_state: bool = False) -> None:
        was_running = self.service.is_running()
        if not was_running:
            self.record_automation_event(
                context,
                actor="runtime",
                phase="service_starting",
                status="running",
                label="SERVICE STARTING",
                summary="Starting the local Codex app-server before submitting the turn.",
                update_cache=True,
            )
        elif refresh_service_state:
            self.record_automation_event(
                context,
                actor="runtime",
                phase="service_refreshing",
                status="running",
                label="SERVICE REFRESHING",
                summary="Refreshing Codex account and model state.",
                update_cache=True,
            )
        _require_online_access()
        preferences = self._preferences(context)
        try:
            self.service.start(
                codex_command=preferences.codex_command,
                codex_home=preferences.codex_home,
                workspace_cwd=self.resolve_workspace_root(context),
                refresh_state=refresh_service_state,
            )
        except Exception as exc:
            self.record_automation_event(
                context,
                actor="runtime",
                phase="service_start_failed",
                status="failed",
                label="SERVICE START FAILED",
                summary=str(exc),
                update_cache=True,
            )
            raise
        if not was_running:
            self.record_automation_event(
                context,
                actor="runtime",
                phase="service_ready",
                status="completed",
                label="SERVICE READY",
                summary="Codex app-server is ready for the turn.",
                update_cache=False,
            )
        self._dashboard_store(context).ensure_project(
            project_id=self._current_project_id(context),
            name=self._current_project_name(context),
            cwd=self.resolve_workspace_root(context),
        )
        self._ensure_chat_mode(context, self._current_chat_mode(context))
        self._update_web_console_cache(context)

    def stop(self) -> None:
        self.service.stop()

    def start_web_console(self, context: bpy.types.Context, *, auto_started: bool = False) -> dict[str, Any]:
        if self._web_console is None:
            self._web_console = WebConsoleServer(
                state_provider=lambda: dict(self._web_console_cache),
                control_handler=self._handle_web_console_control_from_thread,
            )
        self._update_web_console_cache(context)
        status = self._web_console.start()
        self._sync_web_console_window_manager(context)
        self._update_web_console_cache(context)
        if not status.running and status.error:
            self.record_automation_event(
                context,
                actor="web_console",
                phase="web_console_start_failed",
                status="failed",
                label="WEB CONSOLE START FAILED",
                summary=status.error,
                update_cache=False,
            )
            raise RuntimeError(f"Web console could not start: {status.error}")
        if auto_started:
            self._web_console_auto_started = True
        self.record_automation_event(
            context,
            actor="web_console",
            phase="web_console_started",
            status="completed",
            label="WEB CONSOLE STARTED",
            summary=status.url or "Web console started.",
            artifacts={"auto_started": bool(auto_started), "port": status.port},
            update_cache=False,
        )
        print(f"\n{'=' * 78}\nCODEX AUTO REVIEW CONSOLE: {status.url or 'not running'}\n{'=' * 78}\n")
        self._update_web_console_cache(context)
        return status.as_public_dict()

    def stop_web_console(self, context: bpy.types.Context | None = None) -> dict[str, Any]:
        if self._web_console is None:
            if context is not None:
                self._sync_web_console_window_manager(context)
            return {"running": False, "url": "", "host": "127.0.0.1", "port": 0, "error": "", "auto_started": False}
        status = self._web_console.stop()
        self._web_console_auto_started = False
        if context is not None:
            self.record_automation_event(
                context,
                actor="web_console",
                phase="web_console_stopped",
                status="completed",
                label="WEB CONSOLE STOPPED",
                summary="Local web console server stopped.",
                update_cache=False,
            )
            self._sync_web_console_window_manager(context)
            self._update_web_console_cache(context)
        state = status.as_public_dict()
        state["auto_started"] = False
        return state

    def open_web_console(self, context: bpy.types.Context) -> str:
        status = self.start_web_console(context)
        url = str(status.get("url", ""))
        if not url:
            raise RuntimeError("Web console is not running.")
        return url

    def web_console_state(self, context: bpy.types.Context | None = None) -> dict[str, Any]:
        if context is not None:
            self._update_web_console_cache(context)
        if self._web_console is None:
            return {"running": False, "url": "", "host": "127.0.0.1", "port": 0, "error": "", "auto_started": False}
        state = self._web_console.status().as_public_dict()
        state["auto_started"] = bool(self._web_console_auto_started)
        return state

    def _event_timestamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _next_event_id(self, prefix: str) -> str:
        self._web_console_sequence += 1
        return f"{prefix}-{int(time.time() * 1000)}-{self._web_console_sequence}"

    def _trim_events(self, rows: list[dict[str, Any]], limit: int = 300) -> list[dict[str, Any]]:
        return rows[-max(1, int(limit)) :]

    def record_prompt_event(
        self,
        context: bpy.types.Context | None,
        kind: str,
        prompt: str,
        *,
        run_id: str = "",
        label: str = "",
        source: str = "",
        expanded_from: str = "",
        route: str = "",
        update_cache: bool = True,
    ) -> dict[str, Any]:
        event = {
            "event_id": self._next_event_id("prompt"),
            "kind": str(kind or "prompt"),
            "label": label or str(kind or "prompt").replace("_", " ").upper(),
            "prompt": str(prompt or ""),
            "expanded_from": str(expanded_from or ""),
            "source": str(source or "n_panel"),
            "route": str(route or ""),
            "run_id": str(run_id or ""),
            "created_at": self._event_timestamp(),
        }
        self._prompt_events = self._trim_events([*self._prompt_events, event])
        self._append_console_log(
            context,
            "prompt",
            event["label"],
            status="completed",
            summary=prompt,
            run_id=run_id,
            payload={"kind": event["kind"], "route": event["route"], "source": event["source"]},
        )
        if context is not None and run_id:
            self._append_event_to_run(context, run_id, "prompt_events", event)
        if context is not None and update_cache:
            self._update_web_console_cache(context)
        return event

    def record_automation_event(
        self,
        context: bpy.types.Context | None,
        *,
        actor: str,
        phase: str,
        status: str,
        label: str,
        summary: str = "",
        run_id: str = "",
        related_objects: list[str] | None = None,
        related_screenshots: list[str] | None = None,
        validation_report_id: str = "",
        artifacts: dict[str, Any] | None = None,
        update_cache: bool = True,
    ) -> dict[str, Any]:
        event = {
            "event_id": self._next_event_id("event"),
            "actor": str(actor or "runtime"),
            "phase": str(phase or ""),
            "status": str(status or ""),
            "label": str(label or phase or "EVENT").upper(),
            "summary": compact_text(str(summary or ""), 500),
            "related_objects": list(related_objects or []),
            "related_screenshots": list(related_screenshots or []),
            "validation_report_id": str(validation_report_id or ""),
            "artifacts": dict(artifacts or {}),
            "run_id": str(run_id or ""),
            "created_at": self._event_timestamp(),
        }
        self._automation_events = self._trim_events([*self._automation_events, event])
        self._append_console_log(
            context,
            "automation",
            event["label"],
            status=event["status"],
            summary=event["summary"],
            run_id=run_id,
            payload={"actor": event["actor"], "phase": event["phase"], **dict(artifacts or {})},
        )
        if context is not None and run_id:
            self._append_event_to_run(context, run_id, "automation_events", event)
        if context is not None and update_cache:
            self._update_web_console_cache(context)
        return event

    def _append_event_to_run(self, context: bpy.types.Context, run_id: str, field: str, event: dict[str, Any]) -> None:
        if not run_id:
            return
        try:
            store = self._visual_review_store(context)
            manifest = store.load_run(run_id)
            rows = [dict(item) for item in manifest.get(field, []) or [] if isinstance(item, dict)]
            if not any(str(item.get("event_id", "")) == str(event.get("event_id", "")) for item in rows):
                rows.append(dict(event))
            manifest[field] = self._trim_events(rows)
            store.save_run(manifest)
        except Exception:
            pass

    def _append_event_to_manifest(self, manifest: dict[str, Any], field: str, event: dict[str, Any]) -> None:
        rows = [dict(item) for item in manifest.get(field, []) or [] if isinstance(item, dict)]
        if not any(str(item.get("event_id", "")) == str(event.get("event_id", "")) for item in rows):
            rows.append(dict(event))
        manifest[field] = self._trim_events(rows)

    def _dedupe_events(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id", ""))
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            result.append(dict(item))
        result.sort(key=lambda item: str(item.get("created_at") or item.get("started_at") or ""))
        return self._trim_events(result)

    def _console_log_path(self, context: bpy.types.Context) -> Path:
        return self._storage_root(context) / "logs" / "web_console.jsonl"

    def _append_console_log(
        self,
        context: bpy.types.Context | None,
        event_type: str,
        label: str,
        *,
        status: str = "",
        summary: str = "",
        run_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "event_id": self._next_event_id("log"),
            "created_at": self._event_timestamp(),
            "type": str(event_type or "event"),
            "label": str(label or event_type or "EVENT").upper(),
            "status": str(status or ""),
            "summary": compact_text(str(summary or ""), 800),
            "run_id": str(run_id or ""),
            "payload": _json_safe_web(dict(payload or {})),
        }
        self._console_log_rows = self._trim_events([*self._console_log_rows, row], limit=500)
        if context is not None:
            try:
                path = self._console_log_path(context)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
            except Exception:
                pass
        return row

    def _recent_console_logs(self, context: bpy.types.Context | None, *, limit: int = 120) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if context is not None:
            try:
                path = self._console_log_path(context)
                if path.exists():
                    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit)) :]:
                        try:
                            parsed = json.loads(line)
                        except Exception:
                            parsed = {"created_at": "", "type": "raw", "label": "RAW LOG", "summary": line}
                        if isinstance(parsed, dict):
                            rows.append(parsed)
            except Exception:
                pass
        rows.extend(self._console_log_rows[-max(1, int(limit)) :])
        deduped = self._dedupe_events([row for row in rows if isinstance(row, dict)])
        return deduped[-max(1, int(limit)) :]

    def _startup_trace(self, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        markers = {
            "USER PROMPT RECEIVED",
            "ROUTING PROMPT",
            "STARTING AUTO REVIEW",
            "SERVICE STARTING",
            "THREAD STARTING",
            "CREATOR TURN SUBMITTING",
            "CREATING",
            "WEB CONSOLE STARTED",
            "WEB CONSOLE START FAILED",
        }
        return [
            dict(row)
            for row in logs
            if str(row.get("label", "")).upper() in markers or str(row.get("type", "")) in {"prompt", "automation", "web_console", "backend_error"}
        ][-60:]

    def refresh(self, context: bpy.types.Context) -> None:
        self.start(context, refresh_service_state=False)
        self.service.refresh_account()
        self.service.refresh_models()
        self._update_web_console_cache(context)

    def login(self, context: bpy.types.Context) -> str:
        self.start(context, refresh_service_state=False)
        return self.service.start_chatgpt_login()

    def interrupt_turn(self) -> None:
        self.service.interrupt_turn()

    def steer_turn(self, prompt: str) -> None:
        self.service.steer_turn(prompt)

    def new_thread(self, context: bpy.types.Context | None = None) -> None:
        self.service.new_thread()

    def clear_local_messages(self) -> None:
        self.service.clear_local_messages()
        self._last_synced_version = -1

    def setup_dashboard_workspace(self, context: bpy.types.Context):
        workspaces = ensure_codex_suite_workspaces(context, mode="setup")
        ensure_chat_text_blocks()
        self._last_synced_version = -1
        return workspaces

    def create_ai_workspaces(self, context: bpy.types.Context) -> dict[str, Any]:
        workspaces = ensure_codex_suite_workspaces(context, mode="setup")
        result = verify_workspace_suite(context)
        result["created_workspaces"] = [workspace.name for workspace in workspaces]
        return result

    def migrate_legacy_ai_workspaces(self, context: bpy.types.Context) -> dict[str, Any]:
        result = migrate_legacy_ai_workspaces(context)
        self._last_dashboard_signature = ""
        return result

    def install_workspace_templates(self, context: bpy.types.Context) -> dict[str, Any]:
        return self.create_ai_workspaces(context)

    def verify_workspace_suite(self, context: bpy.types.Context) -> dict[str, Any]:
        return verify_workspace_suite(context)

    def repair_ai_workspace(self, context: bpy.types.Context, surface: str = "dashboard") -> dict[str, Any]:
        workspace = self.open_ai_workspace(context, surface)
        result = verify_workspace_suite(context)
        result["repaired_surface"] = surface
        result["active_after_repair"] = workspace.name
        return result

    def open_ai_workspace(self, context: bpy.types.Context, surface: str = "dashboard"):
        surface_value = (surface or "dashboard").strip().lower()
        if surface_value == "workflow":
            return self.open_workflow_workspace(context)
        if surface_value == "assets":
            return self.open_assets_workspace(context)
        return self.open_studio_workspace(context)

    def open_dashboard_workspace(self, context: bpy.types.Context):
        return self.open_studio_workspace(context)

    def open_studio_workspace(self, context: bpy.types.Context):
        workspace = ensure_studio_workspace(context, mode="open")
        self.refresh_dashboard(context)
        return workspace

    def open_workflow_workspace(self, context: bpy.types.Context):
        workspace = ensure_workflow_workspace(context, mode="open")
        self.create_workflow_graph("Codex AI Workflow", with_default_nodes=False)
        self.refresh_dashboard(context)
        return workspace

    def open_assets_workspace(self, context: bpy.types.Context):
        workspace = ensure_assets_workspace(context, mode="open")
        self.register_asset_library(context)
        self.refresh_dashboard(context)
        return workspace

    def diagnose_dashboard_workspace(self, context: bpy.types.Context) -> dict[str, Any]:
        return diagnose_dashboard_workspace(context)

    def refresh_dashboard(self, context: bpy.types.Context) -> None:
        self._dashboard_store(context).ensure_project(
            project_id=self._current_project_id(context),
            name=self._current_project_name(context),
            cwd=self.resolve_workspace_root(context),
        )
        self._last_dashboard_signature = ""
        self._last_synced_version = -1
        self._sync_window_manager(context.window_manager, force=True)

    def select_project(self, context: bpy.types.Context, index: int) -> None:
        projects = self._dashboard_store(context).list_projects()
        if index < 0 or index >= len(projects):
            raise IndexError("Project index out of range.")
        project_id = projects[index]["project_id"]
        self._dashboard_store(context).set_active_project(project_id)
        context.window_manager.codex_blender_active_project_id = project_id
        context.window_manager.codex_blender_project_index = index
        self._last_dashboard_signature = ""
        self._last_synced_version = -1

    def select_thread(self, context: bpy.types.Context, index: int) -> None:
        project_id = self._active_project_id(context)
        mode = self._current_chat_mode(context)
        threads = self._dashboard_store(context).list_threads(project_id=project_id, mode=mode)
        if index < 0 or index >= len(threads):
            raise IndexError("Thread index out of range.")
        thread = threads[index]
        messages = self._dashboard_store(context).load_thread_messages(thread["thread_id"])
        self.service.restore_local_thread(thread["thread_id"], messages)
        self._active_chat_mode = thread.get("mode", mode)
        context.window_manager.codex_blender_thread_index = index
        context.window_manager.codex_blender_active_thread_id = thread["thread_id"]
        self._last_dashboard_signature = ""
        self._last_synced_version = -1

    def compact_active_thread(self, context: bpy.types.Context) -> None:
        thread_id = self.service.snapshot().active_thread_id or context.window_manager.codex_blender_active_thread_id
        if not thread_id:
            return
        compacted = self._dashboard_store(context).compact_thread(thread_id, keep_last=context.window_manager.codex_blender_visible_message_count)
        if compacted.get("thread_id") == self.service.snapshot().active_thread_id:
            messages = self._dashboard_store(context).load_thread_messages(thread_id)
            self.service.restore_local_thread(thread_id, messages)
        self._last_dashboard_signature = ""
        self._last_synced_version = -1

    def pause_transcript_redraw(self, context: bpy.types.Context) -> None:
        context.window_manager.codex_blender_redraw_paused = not context.window_manager.codex_blender_redraw_paused

    def set_ai_scope(self, context: bpy.types.Context, scope: str) -> str:
        normalized = normalize_scope(scope)
        context.window_manager.codex_blender_active_scope = normalized
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        return normalized

    def toggle_context_chip(self, context: bpy.types.Context, chip_id: str) -> dict[str, Any]:
        chips = context.window_manager.codex_blender_context_chips
        for chip in chips:
            if chip.chip_id == chip_id:
                chip.enabled = not chip.enabled
                self._last_dashboard_signature = ""
                return {"chip_id": chip_id, "enabled": bool(chip.enabled)}
        raise KeyError(f"Context chip not found: {chip_id}")

    def register_asset_library(self, context: bpy.types.Context) -> dict[str, Any]:
        if self._current_action_id:
            legacy = register_asset_library(self._storage_root(context))
            ai_libraries = register_ai_asset_libraries(self._storage_root(context))
            self._ai_assets_store(context).migrate_legacy()
            return {"legacy": legacy, "ai_libraries": ai_libraries}
        title = "Register Asset Library"
        prompt = "Register the Codex Blender Agent asset library so AI Assets can save and reuse bundles."
        arguments: dict[str, Any] = {}
        card = self.create_asset_action_card(
            context,
            title=title,
            prompt=prompt,
            plan="Register the local Codex Blender Agent directory as Blender's asset library before writing or importing assets.",
            tool_name="register_blender_asset_library",
            arguments=arguments,
            kind="export",
            asset_name="Codex Blender Agent",
            asset_category="blend",
            asset_kind="library",
            affected_targets=["Codex Blender Agent asset library"],
            required_context=["AI Assets workspace", "Asset libraries"],
            preview_summary="Preview only: register or refresh the local asset library path before mutation.",
            recovery="If registration fails, use Health Check and verify Blender asset library support in preferences.",
        )
        self.preview_action(context, card["action_id"])
        return card

    def list_asset_context(self, context: bpy.types.Context) -> dict[str, Any]:
        return self._asset_context(context)

    def create_asset_action_card(
        self,
        context: bpy.types.Context,
        *,
        title: str,
        prompt: str = "",
        plan: str = "",
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
        kind: str = "change",
        risk: str = "",
        risk_rationale: str = "",
        status: str = "awaiting_approval",
        asset_name: str = "",
        asset_category: str = "",
        asset_kind: str = "",
        affected_targets: list[str] | None = None,
        required_context: list[str] | None = None,
        preview_summary: str = "",
        outcome_summary: str = "",
        recovery: str = "",
    ) -> dict[str, Any]:
        policy = classify_tool(tool_name)
        card_kind = kind or ("export" if policy.category == "external_write" else "change")
        targets = list(affected_targets or [])
        if not targets and asset_name:
            targets = [asset_name]
        if not targets:
            targets = [getattr(context.window_manager, "codex_blender_active_scope", "selection")]
        required = list(required_context or [])
        if not required:
            required = ["AI Assets workspace"]
            if asset_category:
                required.append(f"{asset_category.title()} assets")
        scope_summary = self._asset_scope_summary(context, asset_name=asset_name, asset_category=asset_category, asset_kind=asset_kind)
        return self.create_action_card(
            context,
            title=title,
            kind=card_kind,
            prompt=prompt,
            plan=plan or f"Prepare {tool_name or 'an asset action'} from AI Assets before mutating the library or scene.",
            tool_name=tool_name,
            arguments=arguments or {},
            affected_targets=targets,
            required_context=required,
            risk=risk or policy.risk,
            risk_rationale=risk_rationale or f"{tool_name or 'This asset action'} uses the AI Assets workspace and should be reviewed before execution.",
            status=status,
            scope_summary=scope_summary,
            outcome_summary=outcome_summary or compact_text(prompt or plan or title, 220),
            preview_summary=preview_summary or "Preview not generated yet. Use Preview to inspect the asset action before approval.",
            short_plan=[
                "Confirm the asset scope and selected targets.",
                "Preview the asset action before approving any write or import.",
                "Approve only after the visible card matches the user's intent.",
            ],
            approval_policy=approval_policy_for_risk(policy.risk),
            recovery=recovery or "Cancel the card before approval, or use Blender Undo if the scene changed.",
        )

    def _run_card_bound_tool(self, context: bpy.types.Context, action_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        card = self.get_action_detail(context, action_id)
        policy = classify_tool(tool_name)
        if policy.risk == "critical" and not self._critical_actions_enabled(context):
            raise RuntimeError(f"{tool_name} is critical-risk and expert tools/Python execution are not enabled.")
        if normalize_action_status(card.get("status", ""), card.get("risk", "low")) != "awaiting_approval":
            self.update_action_status(context, action_id, "awaiting_approval", result_summary=f"Awaiting approval for {tool_name}.")
        self.update_action_status(context, action_id, "approved", result_summary=f"Approved {tool_name}.")
        self.update_action_status(context, action_id, "running", result_summary=f"Running {tool_name}.")
        with self._action_execution(action_id):
            try:
                result = self._execute_dynamic_tool(context, tool_name, {**arguments, "action_id": action_id})
            except Exception as exc:
                self.update_action_status(
                    context,
                    action_id,
                    "failed",
                    result_summary=f"{tool_name} failed.",
                    recovery="Use Blender Undo if partial changes occurred, or inspect the tool activity log for details.",
                    warnings=[str(exc)],
                )
                raise
        self.update_action_status(
            context,
            action_id,
            "completed",
            result_summary=compact_text(str(result), 240),
            recovery="Use Blender Undo first. If later actions make undo unsafe, inspect the action card's observed change ledger.",
        )
        return result

    def send_prompt(
        self,
        context: bpy.types.Context,
        prompt: str,
        include_scene_context: bool,
        model: str,
        effort: str,
        attachments: list[str] | None = None,
        chat_mode: str = "scene_agent",
        auto_create_action: bool = True,
    ) -> dict[str, Any]:
        if auto_create_action:
            self.record_automation_event(
                context,
                actor="user",
                phase="prompt_received",
                status="completed",
                label="USER PROMPT RECEIVED",
                summary=prompt,
                update_cache=False,
            )
            self.record_automation_event(
                context,
                actor="runtime",
                phase="routing_prompt",
                status="running",
                label="ROUTING PROMPT",
                summary="Classifying prompt and choosing chat, approval, or automatic review route.",
                update_cache=True,
            )
        self._ensure_chat_mode(context, chat_mode)
        classification = self.classify_prompt(context, prompt)
        if auto_create_action and chat_mode != "chat_only":
            intent = classification["intent"]
            decision = prompt_execution_decision(
                classification,
                friction=self._game_creator_friction(context),
                require_additive_approval=self._require_additive_approval(context),
            )
            if intent in {"change", "automate", "recover", "export"} and decision.requires_card:
                card = self.create_action_from_prompt(context, prompt, classification=classification)
                self.record_prompt_event(
                    context,
                    "submitted",
                    prompt,
                    label="USER PROMPT SUBMITTED",
                    source="n_panel",
                    route="review_card",
                    update_cache=False,
                )
                self.record_automation_event(
                    context,
                    actor="runtime",
                    phase="approval_card",
                    status="completed",
                    label="REVIEW CARD CREATED",
                    summary=prompt,
                    artifacts={"card_id": card.get("action_id", "")},
                    update_cache=False,
                )
                self.record_automation_event(
                    context,
                    actor="runtime",
                    phase="waiting_for_approval",
                    status="needs_attention",
                    label="WAITING FOR APPROVAL",
                    summary=f"Prompt routed to an approval card: {card.get('title', 'AI Action')}",
                    artifacts={"card_id": card.get("action_id", "")},
                    update_cache=False,
                )
                self._dashboard_store(context).add_job_event(
                    label="Review card created",
                    status=card.get("status", "draft"),
                    detail=f"{decision.reason}: {card.get('title', 'AI Action')}",
                    project_id=self._active_project_id(context),
                )
                self._last_dashboard_signature = ""
                self._sync_window_manager(context.window_manager, force=True)
                self._update_web_console_cache(context)
                return {"routed": "card", "card": card, "classification": classification}
            if should_auto_start_visual_review(
                classification,
                decision,
                chat_mode=chat_mode,
                enabled=self._auto_visual_review_enabled(context),
                prompt=prompt,
            ):
                self.record_automation_event(
                    context,
                    actor="runtime",
                    phase="starting_auto_review",
                    status="running",
                    label="STARTING AUTO REVIEW",
                    summary=prompt,
                    update_cache=True,
                )
                manifest = self.start_visual_review_loop(context, prompt, auto_started=True)
                return {"routed": "visual_review", "run": manifest, "classification": classification}
        self.start(context)
        model = self._resolve_model_choice(context, model)
        effort = self._resolve_effort_choice(context, effort)
        scene_digest = ""
        if include_scene_context and chat_mode != "chat_only":
            from .scene_summary import build_scene_digest

            scene_digest = build_scene_digest(context)
        attachment_payload = build_attachment_payload(attachments or [])
        if auto_create_action:
            self.record_prompt_event(
                context,
                "submitted",
                prompt,
                label="USER PROMPT SUBMITTED",
                source="n_panel",
                route="chat",
                update_cache=False,
            )
            self.record_automation_event(
                context,
                actor="user",
                phase="sending_chat",
                status="running",
                label="SENDING CHAT",
                summary=prompt,
                update_cache=False,
            )
        if not self.service.has_loaded_thread():
            self.record_automation_event(
                context,
                actor="runtime",
                phase="thread_starting",
                status="running",
                label="THREAD STARTING",
                summary="Creating or resuming the Codex thread for this Blender scene.",
                update_cache=True,
            )
        prompt_prefix = prompt.lstrip()[:120].lower()
        if "creator phase of an autonomous blender game-art visual self-review loop" in prompt_prefix:
            submit_label = "CREATOR TURN SUBMITTING"
            submit_phase = "creator_turn_submitting"
        elif "critic phase" in prompt_prefix or "structured critic" in prompt_prefix:
            submit_label = "CRITIC TURN SUBMITTING"
            submit_phase = "critic_turn_submitting"
        else:
            submit_label = "CODEX TURN SUBMITTING"
            submit_phase = "turn_submitting"
        self.record_automation_event(
            context,
            actor="runtime",
            phase=submit_phase,
            status="running",
            label=submit_label,
            summary=compact_text(prompt, 260),
            update_cache=True,
        )
        self.service.send_prompt(
            user_prompt=prompt,
            scene_digest=scene_digest,
            cwd=self.resolve_workspace_root(context),
            model=model,
            effort=effort,
            image_paths=attachment_payload.image_paths,
            attachment_context=attachment_payload.text_context,
            chat_mode=chat_mode,
        )
        self._dashboard_store(context).add_job_event(
            label="Game creator chat sent",
            status="running",
            detail=compact_text(prompt, 260),
            project_id=self._active_project_id(context),
        )
        self._update_web_console_cache(context)
        return {"routed": "chat", "classification": classification}

    def classify_prompt(self, context: bpy.types.Context, prompt: str, tool_name: str = "") -> dict[str, Any]:
        window_manager = context.window_manager
        override = getattr(window_manager, "codex_blender_intent", "auto")
        intent = classify_prompt_intent(prompt) if override in {"", "auto"} else override
        selected = list(getattr(context, "selected_objects", []) or [])
        active_scope = getattr(window_manager, "codex_blender_active_scope", "selection")
        attachments = list(getattr(window_manager, "codex_blender_attachments", []) or [])
        ambiguous = intent in {"change", "automate"} and not selected and active_scope in {"selection", "active_object"}
        policy = classify_tool(tool_name) if tool_name else None
        axes = build_risk_axes(
            prompt=prompt,
            tool_name=tool_name,
            target_count=len(selected),
            active_scope=active_scope,
            external_write=bool(policy and policy.category == "external_write") or intent == "export",
            critical=bool(policy and policy.category == "critical"),
            ambiguous=ambiguous,
            long_running=intent == "automate",
        )
        risk, rationale = risk_from_axes(axes)
        return {
            "intent": intent,
            "kind": "inspect" if intent in {"ask", "inspect"} else intent,
            "risk": risk,
            "risk_rationale": rationale,
            "risk_axes": axes,
            "active_scope": active_scope,
            "target_count": len(selected),
            "targets": [obj.name for obj in selected[:30]],
            "attachments": [item.path for item in attachments],
            "ambiguous": ambiguous,
            "approval_policy": approval_policy_for_risk(risk),
        }

    def send_prompt_from_text(self, context: bpy.types.Context) -> None:
        prompt = read_prompt_draft()
        if not prompt:
            raise RuntimeError(f"{PROMPT_TEXT} is empty.")
        window_manager = context.window_manager
        model = window_manager.codex_blender_model
        if model == "__none__":
            model = ""
        route = self.send_prompt(
            context=context,
            prompt=prompt,
            include_scene_context=window_manager.codex_blender_include_scene_context,
            model=model,
            effort=window_manager.codex_blender_effort,
            attachments=[item.path for item in window_manager.codex_blender_attachments],
            chat_mode=window_manager.codex_blender_chat_mode,
        )
        clear_prompt_draft()
        window_manager.codex_blender_attachments.clear()
        if isinstance(route, dict) and route.get("routed") == "card":
            card = route.get("card", {})
            window_manager.codex_blender_activity = f"Prompt draft created review card: {card.get('title', 'AI Action')}"
        elif isinstance(route, dict) and route.get("routed") == "visual_review":
            window_manager.codex_blender_activity = "Prompt draft started automatic visual/geometry review."
        return route

    def clear_prompt_draft(self) -> None:
        clear_prompt_draft()

    def reset_prompt_draft_template(self, prompt: str = "") -> None:
        write_prompt_draft_body(prompt)

    def refresh_chat_transcript(self, context: bpy.types.Context):
        ensure_chat_text_blocks()
        snapshot = self.service.snapshot()
        transcript = write_transcript(snapshot, self._current_chat_mode(context))
        write_activity_log(snapshot)
        return transcript

    def open_dashboard_chat(self, context: bpy.types.Context):
        texts = ensure_chat_text_blocks()
        self.refresh_chat_transcript(context)
        area = getattr(context, "area", None)
        if area is not None:
            area.type = "TEXT_EDITOR"
            for space in area.spaces:
                if space.type == "TEXT_EDITOR":
                    space.text = texts.get("prompt") or bpy.data.texts.get(PROMPT_TEXT)
                    space.show_word_wrap = True
                    break
        return texts

    def workflow_graphs(self) -> list[dict[str, Any]]:
        return list_workflow_graphs()

    def create_workflow_graph(self, name: str = "", with_default_nodes: bool = False) -> dict[str, Any]:
        graph = create_workflow_graph(name or "Codex AI Workflow", with_default_nodes=with_default_nodes)
        payload = inspect_workflow_graph(graph.name)
        self._persist_workflow_graph_if_possible(bpy.context, payload)
        return payload

    def create_workflow_from_intent(self, context: bpy.types.Context, prompt: str = "", graph_name: str = "Codex AI Workflow") -> dict[str, Any]:
        graph = create_workflow_graph(graph_name or "Codex AI Workflow", with_default_nodes=False)
        if not graph.nodes:
            nodes = [
                add_workflow_node(graph.name, "workflow_input", label="Workflow Input", location=(-720.0, 160.0)),
                add_workflow_node(graph.name, "assistant_prompt", label="Describe intent", location=(-360.0, 160.0)),
                add_workflow_node(graph.name, "preview_tap", label="Preview plan", location=(0.0, 160.0)),
                add_workflow_node(graph.name, "workflow_output", label="Workflow Output", location=(360.0, 160.0)),
            ]
            nodes[1]["memory_query"] = prompt or "Use the N-panel chat prompt as the workflow intent."
            nodes[1]["description"] = "AI-created starter workflow. Nodes are intentionally unconnected until the plan is clear."
        self._dashboard_store(context).add_job_event(
            label="AI workflow setup",
            status="completed",
            detail=compact_text(prompt or "Created an unconnected AI workflow starter.", 260),
            project_id=self._active_project_id(context),
        )
        payload = inspect_workflow_graph(graph.name)
        payload["explanation"] = "Created an unconnected workflow starter so the AI can explain or connect steps after the intent is clear."
        payload["intent"] = prompt
        self._persist_workflow_graph_if_possible(context, payload)
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        return payload

    def explain_workflow_graph(self, context: bpy.types.Context, graph_name: str = "Codex AI Workflow") -> dict[str, Any]:
        payload = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        node_types = [node.get("node_type", "") for node in payload.get("nodes", [])]
        return {
            "graph": payload.get("name", graph_name),
            "node_count": len(payload.get("nodes", [])),
            "link_count": len(payload.get("links", [])),
            "node_types": node_types,
            "summary": "This is an AI orchestration graph. Use chat to ask the AI to connect, simplify, or turn it into a reusable recipe.",
        }

    def add_workflow_node(self, graph_name: str, node_type: str, label: str = "") -> dict[str, Any]:
        node = add_workflow_node(graph_name or "Codex AI Workflow", node_type, label=label)
        payload = inspect_workflow_graph(node.id_data.name)
        self._persist_workflow_graph_if_possible(bpy.context, payload)
        return payload

    def create_example_workflow_graph(self, context: bpy.types.Context, example_id: str) -> dict[str, Any]:
        example = get_workflow_example(example_id)
        graph = create_workflow_graph("Codex AI Workflow", with_default_nodes=False)
        for node in list(graph.nodes):
            graph.nodes.remove(node)
        created = []
        for spec in example.node_specs:
            node = add_workflow_node(graph.name, spec.node_type, label=spec.label, location=spec.location)
            node["tool_name"] = spec.tool_name
            node["arguments_json"] = spec.arguments_json
            node["memory_query"] = spec.memory_query
            node["approval_required"] = bool(spec.approval_required)
            node["description"] = spec.description
            node["required_context"] = spec.required_context
            node["output_type"] = spec.output_type
            created.append(node)
        for source, target in zip(created, created[1:]):
            try:
                graph.links.new(source.outputs[0], target.inputs[0])
            except Exception:
                pass
        append_activity_event(f"Created workflow example: {example.title}", {"example_id": example.example_id, "nodes": len(created)})
        self._dashboard_store(context).add_job_event(
            label=f"Workflow example: {example.title}",
            status="completed",
            detail=compact_text(example.description, 260),
            project_id=self._active_project_id(context),
        )
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        payload = inspect_workflow_graph(graph.name)
        self._persist_workflow_graph_if_possible(context, payload)
        return payload

    def validate_workflow_graph(self, context: bpy.types.Context, graph_name: str = "") -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        result = validate_workflow_graph_model(graph, auto_create_roots=True)
        self._persist_workflow_graph_if_possible(context, result.get("manifest", graph), status="ready" if result.get("ok") else "draft")
        return result

    def compile_workflow_graph(self, context: bpy.types.Context, graph_name: str = "") -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        result = compile_workflow_graph_model(graph, auto_create_roots=True)
        self._persist_workflow_graph_if_possible(context, result.get("manifest", graph), status="ready" if result.get("ok") else "blocked")
        return result

    def preview_workflow_node(self, context: bpy.types.Context, graph_name: str = "", node_name: str = "") -> dict[str, Any]:
        preview = self.preview_workflow_graph(context, graph_name)
        if not node_name:
            return preview
        for step in preview.get("preview_steps", []):
            if step.get("node_name") == node_name or step.get("label") == node_name:
                return {"graph_name": preview.get("graph_name", ""), "node": step, "preview_only": True}
        raise RuntimeError(f"Workflow node not found in preview: {node_name}")

    def preview_workflow_graph(self, context: bpy.types.Context, graph_name: str = "") -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        preview = preview_workflow_graph_model(graph, auto_create_roots=True)
        store = self._workflow_store(context)
        manifest = preview.get("manifest", workflow_graph_manifest(graph))
        graph_id = _workflow_graph_id(str(preview.get("graph_name") or graph.get("name", "Codex AI Workflow")))
        store.upsert_graph(graph_id, str(preview.get("graph_name") or graph.get("name", "Codex AI Workflow")), manifest, status="previewed")
        run = store.create_run(
            graph_id=graph_id,
            graph_manifest=manifest,
            preview_only=True,
            run_label=f"Preview {preview.get('graph_name', graph.get('name', 'Workflow'))}",
            status="completed" if preview.get("ok") else "completed_with_warnings",
            run_data=preview,
        )
        store.update_run_status(run["run_id"], run["status"], result_summary=build_workflow_preview_summary(preview), run_data=preview, completed=True)
        self._create_workflow_preview_cards_from_plan(context, preview, run_id=run["run_id"])
        append_activity_event("Workflow graph preview", {"run_id": run["run_id"], "preview": preview})
        return {"run": store.get_run(run["run_id"]), **preview}

    def start_workflow_run(self, context: bpy.types.Context, graph_name: str = "") -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        approved_cards = self._approved_workflow_cards(context)
        model_run = start_workflow_run_model(graph, approved_cards=approved_cards)
        store = self._workflow_store(context)
        compiled = model_run.get("compiled", {})
        manifest = compiled.get("manifest", workflow_graph_manifest(graph))
        graph_id = _workflow_graph_id(str(compiled.get("graph_name") or graph.get("name", "Codex AI Workflow")))
        store.upsert_graph(graph_id, str(compiled.get("graph_name") or graph.get("name", "Codex AI Workflow")), manifest, status="running")
        run = store.create_run(
            graph_id=graph_id,
            graph_manifest=manifest,
            preview_only=False,
            run_label=f"Run {compiled.get('graph_name', graph.get('name', 'Workflow'))}",
            status=model_run.get("state", "queued"),
            run_data=model_run,
            run_id=model_run.get("run_id"),
        )
        self._record_workflow_plan_nodes(store, run["run_id"], compiled)
        if model_run.get("state") == "waiting_approval":
            self._create_workflow_preview_cards_from_plan(context, compiled, run_id=run["run_id"])
            return {"run": store.get_run(run["run_id"]), "blocked": True, "message": "Workflow run is waiting for approval cards.", "compiled": compiled}
        try:
            legacy_result = self.run_workflow_graph(context, graph_name or "Codex AI Workflow", preview_only=False)
        except Exception as exc:
            failed = store.update_run_status(run["run_id"], "failed", error_summary=str(exc), run_data={**model_run, "error": str(exc)}, completed=True)
            return {"run": failed, "error": str(exc), "compiled": compiled}
        completed = store.update_run_status(run["run_id"], "completed", result_summary=f"Workflow completed with {len(legacy_result.get('results', []))} node result(s).", run_data={**model_run, "legacy_result": legacy_result}, completed=True)
        return {"run": completed, "result": legacy_result, "compiled": compiled}

    def resume_workflow_run(self, context: bpy.types.Context, run_id: str) -> dict[str, Any]:
        store = self._workflow_store(context)
        run = store.get_run(run_id)
        updated_model = resume_workflow_run_model(run.get("run_data", {}), current_snapshot_hash=run.get("snapshot_hash", ""))
        status = updated_model.get("state", "running")
        return store.update_run_status(run_id, status, result_summary=f"Workflow run {status}.", run_data=updated_model)

    def stop_workflow_run(self, context: bpy.types.Context, run_id: str, reason: str = "") -> dict[str, Any]:
        store = self._workflow_store(context)
        run = store.get_run(run_id)
        stopped = stop_workflow_run_model(run.get("run_data", {}), reason=reason or "Stopped by user.")
        return store.update_run_status(run_id, stopped.get("state", "paused"), result_summary=stopped.get("stop_reason", reason), run_data=stopped)

    def list_workflow_runs(self, context: bpy.types.Context, graph_id: str = "") -> list[dict[str, Any]]:
        return self._workflow_store(context).list_runs(graph_id or None)

    def get_workflow_run_detail(self, context: bpy.types.Context, run_id: str) -> dict[str, Any]:
        store = self._workflow_store(context)
        run = store.get_run(run_id)
        return {**run, "nodes": store.list_run_nodes(run_id), "checkpoints": store.list_checkpoints(run_id)}

    def publish_workflow_recipe(self, context: bpy.types.Context, graph_name: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        manifest = workflow_graph_manifest(graph)
        graph_hash = self._workflow_store(context).hash_graph_manifest(manifest)
        metadata = self._default_recipe_metadata(graph, graph_hash, metadata or {})
        validation = validate_recipe_metadata(metadata)
        if not validation.ok:
            raise RuntimeError("Recipe metadata invalid: " + "; ".join(validation.issues))
        normalized = validation.normalized
        graph_id = _workflow_graph_id(str(graph.get("name", "Codex AI Workflow")))
        self._workflow_store(context).upsert_graph(graph_id, str(graph.get("name", "Codex AI Workflow")), manifest, status="ready")
        recipe = self._workflow_store(context).publish_recipe(
            recipe_id=str(normalized["recipe_id"]),
            version=str(normalized["version"]),
            name=str(normalized["display_name"]),
            graph_id=graph_id,
            manifest=manifest,
            input_schema=dict(normalized.get("input_schema", {})),
            output_schema=dict(normalized.get("output_schema", {})),
            required_tools=list(normalized.get("required_tools", [])),
            risk_profile=str(normalized.get("risk_profile", "read_only")),
            author=str(normalized.get("author", "")),
            changelog=str(normalized.get("changelog", "")),
            preview_path=str(normalized.get("preview_image", "")),
            tests=list(normalized.get("tests", [])),
            tags=list(normalized.get("tags", [])),
            catalog_path=str(normalized.get("catalog_path", "")),
            compatibility=dict(normalized.get("compatibility_range", {})),
            status="approved",
        )
        return {"recipe": recipe, "metadata_validation": validation.__dict__, "manifest_hash": validation.manifest_hash}

    def list_workflow_recipes(self, context: bpy.types.Context, recipe_id: str = "") -> list[dict[str, Any]]:
        return self._workflow_store(context).list_recipe_versions(recipe_id or None)

    def get_workflow_recipe_detail(self, context: bpy.types.Context, recipe_version_uid: str) -> dict[str, Any]:
        store = self._workflow_store(context)
        recipe = store.get_recipe_version(recipe_version_uid)
        return {**recipe, "tests": store.list_recipe_tests(recipe_version_uid)}

    def propose_workflow_patch(self, context: bpy.types.Context, graph_name: str = "", operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        operations = list(operations or [])
        proposal = propose_workflow_patch_model(graph, operations)
        recipe_validation = validate_graph_patch_proposal({"graph_id": graph.get("name", ""), "operations": operations}, graph_state=graph)
        graph_id = _workflow_graph_id(str(graph.get("name", "Codex AI Workflow")))
        stored = self._workflow_store(context).create_patch_proposal(
            graph_id=graph_id,
            base_graph_hash=str(proposal.get("graph_hash", "")),
            proposal_kind="ai_patch",
            summary=str(proposal.get("diff", {}).get("summary", "")) or f"{len(operations)} workflow patch operation(s).",
            proposal={"operations": operations, "execution": proposal, "recipe_validation": recipe_validation.__dict__},
            diff=dict(proposal.get("diff", {})),
            contract_diff={"issues": list(recipe_validation.issues)},
            staging_graph=dict(proposal.get("validation", {}).get("patched_graph", {})),
            status="draft" if proposal.get("ok") else "failed",
        )
        return {"proposal": proposal, "recipe_validation": recipe_validation.__dict__, "stored": stored}

    def preview_workflow_patch(self, context: bpy.types.Context, graph_name: str = "", operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        graph = inspect_workflow_graph(graph_name or "Codex AI Workflow")
        return preview_workflow_patch_model(graph, list(operations or []))

    def apply_workflow_patch(self, context: bpy.types.Context, graph_name: str = "", operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        graph_name = graph_name or "Codex AI Workflow"
        graph = inspect_workflow_graph(graph_name)
        result = apply_workflow_patch_model(graph, list(operations or []))
        self._apply_workflow_patch_to_blender_graph(graph_name, list(operations or []))
        patched_graph = inspect_workflow_graph(graph_name)
        self._persist_workflow_graph_if_possible(context, patched_graph, status="patched")
        return {**result, "graph": patched_graph}

    def run_workflow_graph(self, context: bpy.types.Context, graph_name: str = "", preview_only: bool = True) -> dict[str, Any]:
        graph_name = graph_name or "Codex AI Workflow"

        def tool_runner(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            if tool_name == "run_workflow_graph":
                raise RuntimeError("Workflow graphs cannot recursively run themselves.")
            policy = classify_tool(tool_name)
            if policy.requires_action and not action_id_from_arguments(args):
                card = self.create_action_card(
                    context,
                    title=f"Workflow tool: {tool_name}",
                    kind="automate",
                    prompt=f"Workflow graph {graph_name} requested {tool_name}.",
                    plan=f"Run {tool_name} with arguments {args}.",
                    tool_name=tool_name,
                    arguments=args,
                    affected_targets=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                    required_context=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                    risk=policy.risk,
                    status="awaiting_approval",
                    preview_summary=f"Workflow run blocked until this {policy.category} tool is approved.",
                    tool_activity=[{"tool": tool_name, "phase": "workflow", "status": "blocked"}],
                )
                raise RuntimeError(f"Workflow node {tool_name} needs approval in action card {card.get('action_id')}.")
            return self._execute_dynamic_tool(context, tool_name, args)

        def memory_reader(query: str) -> dict[str, Any]:
            thread_id = query.strip() or self.service.snapshot().active_thread_id or self._dashboard_store(context).active_thread_id()
            if not thread_id:
                return {"thread": {}, "messages": []}
            return self._dashboard_store(context).get_thread_context(thread_id, limit=20)

        def toolbox_runner(item_id_or_name: str) -> dict[str, Any]:
            return self._execute_dynamic_tool(context, "run_toolbox_system", {"item_id_or_name": item_id_or_name})

        def asset_searcher(args: dict[str, Any]) -> dict[str, Any]:
            return self._execute_dynamic_tool(context, "list_asset_items", args)

        result = run_workflow_graph(
            graph_name,
            preview_only=preview_only,
            tool_runner=tool_runner,
            memory_reader=memory_reader,
            toolbox_runner=toolbox_runner,
            asset_searcher=asset_searcher,
            prompt_reader=read_prompt_draft,
        )
        append_activity_event("Workflow graph preview" if preview_only else "Workflow graph run", result)
        if preview_only:
            self._create_workflow_preview_actions(context, result)
        return result

    def pump(self) -> None:
        self.dispatcher.drain()
        context = bpy.context
        window_manager = getattr(context, "window_manager", None)
        if window_manager is None:
            return
        snapshot = self.service.snapshot()
        if self.service.is_running():
            if not snapshot.turn_in_progress and self._current_chat_mode(context) != self._active_chat_mode:
                self._ensure_chat_mode(context, self._current_chat_mode(context))
        self._pump_visual_review(context, snapshot)
        self._sync_window_manager(window_manager)

    def sync_window_manager(self, context: bpy.types.Context, *, force: bool = True) -> None:
        window_manager = getattr(context, "window_manager", None)
        if window_manager is not None:
            self._sync_window_manager(window_manager, force=force)

    def resolve_workspace_root(self, context: bpy.types.Context) -> str:
        preferences = self._preferences(context)
        if bpy.data.filepath:
            return str(Path(bpy.data.filepath).resolve().parent)
        if preferences.workspace_root:
            return str(Path(preferences.workspace_root).expanduser())
        return str(Path(os.path.expanduser("~")).resolve())

    def refresh_toolbox_items(self, context: bpy.types.Context) -> list[dict[str, Any]]:
        return self._toolbox_store(context).list_entries()

    def delete_toolbox_item(self, context: bpy.types.Context, item_id: str) -> None:
        self._toolbox_store(context).delete_entry(item_id)

    def refresh_asset_items(self, context: bpy.types.Context) -> list[dict[str, Any]]:
        query = str(getattr(context.window_manager, "codex_blender_ai_assets_search", "") or "")
        kind = str(getattr(context.window_manager, "codex_blender_ai_assets_kind_filter", "") or "")
        status = str(getattr(context.window_manager, "codex_blender_ai_assets_status_filter", "") or "")
        if kind == "all":
            kind = ""
        if status == "all":
            status = ""
        if query or kind or status:
            return [asset_version_to_legacy_item(item) for item in self._ai_assets_store(context).search(query, kind=kind or None, status=status or None, limit=100)]
        return self._asset_store(context).list_entries()

    def delete_asset_item(self, context: bpy.types.Context, item_id: str) -> None:
        self._asset_store(context).delete_entry(item_id)

    def initialize_ai_assets_store(self, context: bpy.types.Context) -> dict[str, Any]:
        result = self._ai_assets_store(context).initialize()
        self._last_dashboard_signature = ""
        return result

    def migrate_ai_assets_store(self, context: bpy.types.Context) -> dict[str, Any]:
        result = self._ai_assets_store(context).migrate_legacy()
        self._last_dashboard_signature = ""
        return result

    def diagnose_ai_assets(self, context: bpy.types.Context) -> dict[str, Any]:
        result = diagnose_ai_asset_libraries(self._storage_root(context))
        result["authority"] = self._ai_assets_store(context).diagnose()
        return result

    def create_asset_publish_action(
        self,
        context: bpy.types.Context,
        *,
        name: str = "",
        kind: str = "model",
        description: str = "",
        tags: Any = None,
    ) -> dict[str, Any]:
        asset_name = (name or context.window_manager.codex_blender_asset_name or "Reusable Asset").strip()
        if kind == "all":
            kind = "model"
        arguments = {
            "name": asset_name,
            "category": kind or "model",
            "description": description or "Saved from selected Blender objects.",
            "tags": tags or [],
            "object_names": [obj.name for obj in context.selected_objects],
            "mark_as_blender_assets": True,
        }
        card = self.create_asset_action_card(
            context,
            title=f"Publish Asset: {asset_name}",
            prompt=f"Promote selected Blender content into a reusable AI Assets version named {asset_name}.",
            plan="Review the selection, catalog destination, metadata, dependencies, and write target before saving the asset bundle.",
            tool_name="save_selection_to_asset_library",
            arguments=arguments,
            kind="export",
            asset_name=asset_name,
            asset_category=kind or "model",
            asset_kind="blend_bundle",
            affected_targets=[obj.name for obj in context.selected_objects] or ["selection"],
            required_context=["Selection", "AI Assets workspace", "Asset metadata"],
            preview_summary="Preview only: create an asset version from the current selection after approval.",
            outcome_summary="A reusable asset version will be written to the AI Assets library and indexed in SQLite.",
            recovery="Cancel before approval. After approval, use the card recovery notes and remove the generated asset version if needed.",
        )
        self.preview_action(context, card["action_id"])
        return card

    def save_selected_asset_from_ui(self, context: bpy.types.Context, name: str) -> dict[str, Any]:
        arguments = {
            "name": name,
            "category": "model",
            "description": "Saved from selected Blender objects.",
            "object_names": [obj.name for obj in context.selected_objects],
            "mark_as_blender_assets": True,
        }
        if self._current_action_id:
            self.register_asset_library(context)
            return self._save_selected_objects_asset(context, arguments)
        card = self.create_asset_action_card(
            context,
            title=f"Save Asset: {name}",
            prompt=f"Save selected Blender objects as a reusable asset bundle named {name}.",
            plan="Create a visible action card, preview the selected objects, and then save the bundle into the registered asset library.",
            tool_name="save_selection_to_asset_library",
            arguments=arguments,
            kind="export",
            asset_name=name,
            asset_category="model",
            asset_kind="blend_bundle",
            affected_targets=[obj.name for obj in context.selected_objects] or ["selection"],
            required_context=["Selection", "AI Assets workspace"],
            preview_summary="Preview only: save the current selection as a reusable asset bundle.",
            recovery="Cancel before approval or use Blender Undo if the bundle was written and needs to be reverted.",
        )
        self.preview_action(context, card["action_id"])
        return card

    def import_selected_asset_from_ui(self, context: bpy.types.Context, link: bool = False) -> dict[str, Any]:
        items = context.window_manager.codex_blender_asset_items
        index = context.window_manager.codex_blender_asset_index
        if index < 0 or index >= len(items):
            raise RuntimeError("Select an asset item first.")
        item = items[index]
        arguments = {"item_id_or_name": item.item_id or item.name, "link": bool(link)}
        if self._current_action_id:
            result = self._import_asset_item(context, item.item_id or item.name, link=link)
            self._dashboard_store(context).add_job_event(
                label=f"Imported asset: {item.name or item.item_id}",
                status="completed",
                detail=compact_text(str(result), 260),
                project_id=self._active_project_id(context),
            )
            self._last_dashboard_signature = ""
            self._sync_window_manager(context.window_manager, force=True)
            return result
        card = self.create_asset_action_card(
            context,
            title=f"Import Asset: {item.name or item.item_id}",
            prompt=f"Append or link the selected asset {item.name or item.item_id} into the current scene.",
            plan="Create a visible action card, preview the selected asset, then import or link it into the scene.",
            tool_name="append_asset_from_library",
            arguments=arguments,
            kind="change",
            asset_name=item.name or item.item_id,
            asset_category=item.category or "other",
            asset_kind=item.kind or "file",
            affected_targets=[item.name or item.item_id],
            required_context=["Selected asset item", "AI Assets workspace"],
            preview_summary="Preview only: append or link the selected asset into the current Blender scene.",
            recovery="Cancel before approval or use Blender Undo if the import changes need to be rolled back.",
        )
        self.preview_action(context, card["action_id"])
        return card

    def create_action_from_prompt(self, context: bpy.types.Context, prompt: str, title: str = "", classification: dict[str, Any] | None = None) -> dict[str, Any]:
        targets = [obj.name for obj in getattr(context, "selected_objects", [])]
        active_scope = getattr(context.window_manager, "codex_blender_active_scope", "selection")
        classification = classification or self.classify_prompt(context, prompt)
        status = "needs_clarification" if classification.get("ambiguous") else "draft"
        scope_summary = f"{classification.get('target_count', 0)} selected target(s); active scope: {active_scope}."
        if classification.get("attachments"):
            scope_summary += f" {len(classification.get('attachments', []))} active attachment(s)."
        safety = self._safety_preferences(context)
        assumptions = [
            f"Intent: {classification.get('intent', 'ask')}",
            f"Scope chip: {active_scope}",
        ] + [label for label, enabled in safety.items() if enabled]
        card = self.create_action_card(
            context,
            title=title or _title_for_intent(classification.get("intent", ""), prompt),
            kind=classification.get("kind", ""),
            prompt=prompt,
            plan="Review card created because this request may affect broad, destructive, external, or uncertain state. Use chat for ordinary game-creation work; approve only if this plan matches the intended scope.",
            affected_targets=targets or [active_scope],
            required_context=[active_scope],
            risk=classification.get("risk", ""),
            risk_rationale=classification.get("risk_rationale", ""),
            risk_axes=classification.get("risk_axes", {}),
            status=status,
            scope_summary=scope_summary,
            outcome_summary=compact_text(prompt, 220),
            assumptions=assumptions,
            dependencies=["Enabled context chips", "User approval before mutation"],
            preview_summary="Preview has not been generated yet.",
            short_plan=[
                "Confirm the visible game-creation scope.",
                "Review the target, risk, and intended tool activity.",
                "Approve only if the proposal matches what should change.",
            ],
            approval_policy=classification.get("approval_policy", ""),
            recovery="Cancel before approval, stop during execution, or use Blender Undo after a completed change.",
        )
        return card

    def create_action_card(
        self,
        context: bpy.types.Context,
        *,
        title: str = "",
        kind: str = "",
        prompt: str = "",
        plan: str = "",
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
        affected_targets: Any = None,
        required_context: Any = None,
        risk: str = "",
        risk_rationale: str = "",
        risk_axes: dict[str, str] | None = None,
        status: str = "",
        scope_summary: str = "",
        outcome_summary: str = "",
        assumptions: Any = None,
        dependencies: Any = None,
        preview_summary: str = "",
        short_plan: Any = None,
        full_plan: str = "",
        approval_policy: str = "",
        tool_activity: Any = None,
        warnings: Any = None,
        parent_action_id: str = "",
        child_action_ids: Any = None,
        plan_revision: int = 0,
        plan_diff: str = "",
        change_ledger: Any = None,
        result_summary: str = "",
        recovery: str = "",
    ) -> dict[str, Any]:
        store = self._dashboard_store(context)
        card = store.save_action_card(
            project_id=self._active_project_id(context),
            thread_id=self.service.snapshot().active_thread_id or store.active_thread_id(),
            title=title,
            kind=kind,
            prompt=prompt,
            plan=plan,
            tool_name=tool_name,
            arguments=arguments or {},
            affected_targets=affected_targets or [],
            required_context=required_context or [],
            risk=risk,
            risk_rationale=risk_rationale,
            risk_axes=risk_axes or {},
            status=status,
            scope_summary=scope_summary,
            outcome_summary=outcome_summary,
            assumptions=assumptions or [],
            dependencies=dependencies or [],
            preview_summary=preview_summary,
            short_plan=short_plan or [],
            full_plan=full_plan,
            approval_policy=approval_policy,
            tool_activity=tool_activity or [],
            warnings=warnings or [],
            parent_action_id=parent_action_id,
            child_action_ids=child_action_ids or [],
            plan_revision=plan_revision,
            plan_diff=plan_diff,
            change_ledger=change_ledger or [],
            result_summary=result_summary,
            recovery=recovery,
        )
        store.add_job_event(
            label=f"Action: {card.get('title', 'AI Action')}",
            status=card.get("status", "draft"),
            detail=card.get("plan_preview", "") or card.get("prompt_preview", ""),
            project_id=self._active_project_id(context),
        )
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        return card

    def list_action_cards(self, context: bpy.types.Context, status: str = "") -> list[dict[str, Any]]:
        return self._dashboard_store(context).list_action_cards(
            project_id=self._active_project_id(context),
            status=status or None,
        )

    def get_action_detail(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        card = self._dashboard_store(context).get_action_card(action_id)
        if card is None:
            raise KeyError(f"Action card not found: {action_id}")
        return card

    def update_action_status(
        self,
        context: bpy.types.Context,
        action_id: str,
        status: str,
        result_summary: str = "",
        recovery: str = "",
        plan: str = "",
        **updates: Any,
    ) -> dict[str, Any]:
        existing = self._dashboard_store(context).get_action_card(action_id)
        if existing is not None and not transition_allowed(existing.get("status", ""), status):
            raise RuntimeError(f"Illegal action transition: {existing.get('status', '')} -> {status}.")
        card = self._dashboard_store(context).update_action_status(action_id, status, result_summary, recovery, plan, **updates)
        self._dashboard_store(context).add_job_event(
            label=f"Action {status}: {card.get('title', 'AI Action')}",
            status=status,
            detail=result_summary or recovery or card.get("plan_preview", ""),
            project_id=self._active_project_id(context),
        )
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        return card

    def preview_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        card = self.get_action_detail(context, action_id)
        detail = card.get("detail", {})
        policy = classify_tool(card.get("tool_name", ""))
        preview = self._build_preview_summary(context, card, policy)
        return self.update_action_status(
            context,
            action_id,
            "preview_ready",
            result_summary="Preview prepared. Review scope, risk, and planned tool activity before approval.",
            preview_summary=preview,
            detail={
                **detail,
                "preview_summary": preview,
                "short_plan": detail.get("short_plan") or [
                    "Review affected targets.",
                    "Approve to enter a card-bound execution.",
                    "Use Stop or Recover if the result diverges.",
                ],
            },
        )

    def approve_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        card = self.get_action_detail(context, action_id)
        tool_name = str(card.get("tool_name", "")).strip()
        if not tool_name:
            detail = card.get("detail", {})
            if detail.get("workflow_run_id") or detail.get("workflow_node_name"):
                if normalize_action_status(card.get("status", "")) != "awaiting_approval":
                    self.update_action_status(context, action_id, "awaiting_approval", result_summary="Workflow approval is ready for review.")
                return self.update_action_status(
                    context,
                    action_id,
                    "approved",
                    result_summary=f"Approved workflow node {detail.get('workflow_node_name', 'step')}. Resume or start the workflow run from Workflow.",
                    recovery="If upstream inputs change, regenerate the workflow preview before resuming.",
                    detail={**detail, "decision_history": [*detail.get("decision_history", []), {"decision": "approved", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]},
                )
            return self.update_action_status(
                context,
                action_id,
                "awaiting_approval",
                result_summary="This card has no concrete tool call yet. Use chat or a workflow preview to attach a tool-backed plan before execution.",
                recovery="Cancel the card or ask Codex to convert it into specific safe tool calls.",
            )
        if card.get("risk") == "critical" and not self._critical_actions_enabled(context):
            return self.update_action_status(
                context,
                action_id,
                "awaiting_approval",
                result_summary="Critical-risk action blocked. Enable expert tools and use a more explicit plan before running.",
                warnings=["Critical tool blocked by default."],
            )
        if normalize_action_status(card.get("status", "")) != "awaiting_approval":
            self.update_action_status(context, action_id, "awaiting_approval", result_summary=f"Awaiting approval for {tool_name}.")
        self.update_action_status(context, action_id, "approved", result_summary=f"Approved {tool_name}.")
        self.update_action_status(context, action_id, "running", result_summary=f"Running {tool_name}.")
        detail = card.get("detail", {})
        with self._action_execution(action_id):
            try:
                result = self._execute_dynamic_tool(context, tool_name, {**dict(detail.get("arguments") or {}), "action_id": action_id})
            except Exception as exc:
                return self.update_action_status(
                    context,
                    action_id,
                    "failed",
                    result_summary=f"{tool_name} failed.",
                    recovery="Use Blender Undo if partial changes occurred, or inspect the tool activity log for details.",
                    detail={"tool_activity": [*detail.get("tool_activity", []), _tool_step_record(tool_name, "commit", "failed", {}, error=str(exc))]},
                    warnings=[str(exc)],
                )
        updated = self.get_action_detail(context, action_id)
        updated_detail = updated.get("detail", {})
        return self.update_action_status(
            context,
            action_id,
            "completed",
            result_summary=compact_text(str(result), 240),
            recovery="Use Blender Undo first. If later actions make undo unsafe, use this card's observed change ledger for guided recovery.",
            detail=updated_detail,
        )

    def cancel_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        return self.update_action_status(
            context,
            action_id,
            "cancelled",
            result_summary="Action cancelled before execution. No card-bound mutation was committed.",
            preview_summary="Preview cleared.",
        )

    def recover_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        return self.update_action_status(
            context,
            action_id,
            "recovered",
            result_summary="Recovery noted. Use Blender Undo or restore a checkpoint if the scene changed.",
            recovery="Try Blender Undo first. If the card is stale, inspect observed changes and restore from a checkpoint copy.",
        )

    def stop_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        self._stopping_actions.add(action_id)
        return self.update_action_status(
            context,
            action_id,
            "stopping",
            result_summary="Stop requested. New mutating tool calls for this card are blocked.",
            recovery="If a step already completed, use Recover or Blender Undo after the card pauses.",
        )

    def pause_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        return self.update_action_status(context, action_id, "paused", result_summary="Action paused at a safe checkpoint.")

    def resume_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        self._stopping_actions.discard(action_id)
        return self.update_action_status(context, action_id, "running", result_summary="Action resumed.")

    def archive_action(self, context: bpy.types.Context, action_id: str) -> dict[str, Any]:
        return self.update_action_status(context, action_id, "archived", result_summary="Action archived from the working dashboard.")

    @contextmanager
    def _action_execution(self, action_id: str):
        previous = self._current_action_id
        self._current_action_id = action_id
        try:
            yield
        finally:
            self._current_action_id = previous

    def _authorize_tool_action(self, context: bpy.types.Context, tool_name: str, arguments: dict[str, Any], policy) -> str:
        action_id = action_id_from_arguments(arguments) or self._current_action_id
        if not action_id:
            decision = tool_execution_decision(
                policy,
                friction=self._game_creator_friction(context),
                require_additive_approval=self._require_additive_approval(context),
            )
            if decision.receipt_only and self._cards_as_receipts(context):
                card = self.create_action_card(
                    context,
                    title=f"AI game action: {tool_name}",
                    kind="change",
                    prompt=f"Run {tool_name} from Game Creator chat.",
                    plan=f"{decision.reason} Tool arguments: {summarize_arguments(arguments)}",
                    tool_name=tool_name,
                    arguments=arguments,
                    affected_targets=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                    required_context=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                    risk=policy.risk,
                    risk_rationale=decision.reason,
                    status="running",
                    scope_summary=f"Game Creator fast mode; scope: {getattr(context.window_manager, 'codex_blender_active_scope', 'selection')}.",
                    outcome_summary=f"Running local Blender tool {tool_name}.",
                    preview_summary="Fast mode records this as a receipt instead of blocking on approval.",
                    tool_activity=[_tool_step_record(tool_name, "commit", "running", arguments)],
                    approval_policy="Auto-run local reversible work in Game Creator fast mode.",
                    recovery="Use Blender Undo first, then open this receipt for details if needed.",
                )
                action_id = str(card.get("action_id", ""))
                self._auto_receipt_actions.add(action_id)
            else:
                raise RuntimeError(f"{tool_name} is a {policy.category} tool and requires an approved running action card.")
        if action_id in self._stopping_actions:
            raise RuntimeError(f"Action {action_id} is stopping; no new mutating tool calls are allowed.")
        card = self.get_action_detail(context, action_id)
        status = normalize_action_status(card.get("status", ""), card.get("risk", "low"))
        if status != "running":
            raise RuntimeError(f"Action {action_id} must be running before {tool_name} can mutate Blender; current status is {status}.")
        if policy.risk == "critical" and not self._critical_actions_enabled(context):
            raise RuntimeError(f"{tool_name} is critical-risk and expert tools/Python execution are not enabled.")
        return action_id

    def _record_action_step(self, context: bpy.types.Context, action_id: str, step: dict[str, Any]) -> dict[str, Any]:
        card = self.get_action_detail(context, action_id)
        detail = dict(card.get("detail", {}))
        activity = list(detail.get("tool_activity", []))
        activity.append(step)
        detail["tool_activity"] = activity[-100:]
        if step.get("status") == "completed":
            ledger = list(detail.get("change_ledger", []))
            ledger.append(
                {
                    "tool": step.get("tool", ""),
                    "phase": step.get("phase", ""),
                    "summary": step.get("summary", ""),
                    "finished_at": step.get("ended_at", ""),
                }
            )
            detail["change_ledger"] = ledger[-100:]
        return self.update_action_status(
            context,
            action_id,
            card.get("status", "running"),
            result_summary=card.get("result_summary", ""),
            recovery=card.get("recovery", ""),
            detail=detail,
            tool_activity=activity,
        )

    def _record_action_warning(self, context: bpy.types.Context, action_id: str, warning: str) -> dict[str, Any]:
        card = self.get_action_detail(context, action_id)
        detail = dict(card.get("detail", {}))
        warnings = list(detail.get("warnings", []))
        warnings.append(warning)
        detail["warnings"] = warnings[-50:]
        return self.update_action_status(context, action_id, card.get("status", "running"), detail=detail, warnings=warnings)

    def _build_preview_summary(self, context: bpy.types.Context, card: dict[str, Any], policy) -> str:
        targets = card.get("affected_targets", []) or [getattr(context.window_manager, "codex_blender_active_scope", "selection")]
        tool_name = card.get("tool_name", "")
        if tool_name:
            args = card.get("detail", {}).get("arguments", {})
            return f"Preview only: {tool_name} is classified as {policy.category}. It would target {', '.join(targets)} with {summarize_arguments(args)}."
        return f"Preview only: review {card.get('kind', 'change')} request for {', '.join(targets)}. No concrete Blender tool is attached yet."

    def _critical_actions_enabled(self, context: bpy.types.Context) -> bool:
        prefs = self._preferences(context)
        return bool(getattr(prefs, "enable_expert_tools", False) or getattr(prefs, "enable_python_execution", False))

    def pin_output_to_thread(
        self,
        context: bpy.types.Context,
        *,
        title: str,
        summary: str,
        kind: str = "result",
        action_id: str = "",
        path: str = "",
    ) -> dict[str, Any]:
        output = self._dashboard_store(context).pin_output(
            title=title,
            summary=summary,
            kind=kind,
            source_thread_id=self.service.snapshot().active_thread_id or self._dashboard_store(context).active_thread_id(),
            action_id=action_id,
            path=path,
            project_id=self._active_project_id(context),
        )
        self._last_dashboard_signature = ""
        self._sync_window_manager(context.window_manager, force=True)
        return output

    def update_chat_text_block(self, context: bpy.types.Context):
        return self.refresh_chat_transcript(context)

    def start_visual_review_loop(
        self,
        context: bpy.types.Context,
        prompt: str = "",
        *,
        max_iterations: int | None = None,
        target_score: float | None = None,
        resolution: int | None = None,
        auto_started: bool = False,
    ) -> dict[str, Any]:
        window_manager = context.window_manager
        source_prompt = (prompt or getattr(window_manager, "codex_blender_prompt", "") or "").strip()
        if not source_prompt:
            source_prompt = "Create or improve this scene for a game-art goal, then self-review it from multiple viewpoints."
        max_iterations = max(1, int(max_iterations or getattr(window_manager, "codex_blender_visual_review_max_iterations", DEFAULT_MAX_ITERATIONS) or DEFAULT_MAX_ITERATIONS))
        target_score = float(target_score if target_score is not None else getattr(window_manager, "codex_blender_visual_review_target_score", DEFAULT_TARGET_SCORE))
        resolution = max(128, int(resolution or getattr(window_manager, "codex_blender_visual_review_resolution", DEFAULT_SCREENSHOT_RESOLUTION) or DEFAULT_SCREENSHOT_RESOLUTION))
        self.start(context)
        self._visual_review_console_banner("AUTO REVIEW QUEUED" if auto_started else "VISUAL REVIEW QUEUED", source_prompt)
        action = self.create_action_card(
            context,
            title="Auto review: scene change" if auto_started else "Improve with screenshots",
            kind="automate",
            prompt=source_prompt,
            plan="Create or improve the scene, validate evaluated geometry, capture viewport screenshots, critique the result, and repeat until the score or iteration cap is reached.",
            risk="medium",
            risk_rationale="Autonomous additive scene editing with local geometry validation and screenshot capture.",
            status="running",
            scope_summary=self._visual_review_scope_summary(context),
            outcome_summary="Automatic visual and geometry self-review loop started." if auto_started else "Visual self-review loop started.",
            preview_summary="Evaluated geometry validation and screenshots will run after each creator pass.",
            short_plan=[
                "Creator pass edits the scene from the prompt.",
                "Runtime validates evaluated geometry and captures planned viewport viewpoints.",
                "Critic pass reviews screenshots and validation reports without mutating the scene.",
                "Loop repeats with the critic's next prompt until complete.",
            ],
            approval_policy="Fast mode: local additive work runs with a receipt; destructive/external tools still require approval.",
            recovery="Press Stop to interrupt the current turn. Use Blender Undo for local edits, then open the run manifest for screenshots and critiques.",
        )
        manifest = self._visual_review_store(context).create_run(
            prompt=source_prompt,
            max_iterations=max_iterations,
            target_score=target_score,
            resolution=resolution,
            capture_mode=getattr(window_manager, "codex_blender_visual_review_capture_mode", DEFAULT_CAPTURE_MODE) or DEFAULT_CAPTURE_MODE,
            thread_id=self.service.snapshot().active_thread_id,
            action_id=str(action.get("action_id", "")),
        )
        manifest["geometry_settings"] = self._visual_review_geometry_settings(context)
        manifest["auto_started"] = bool(auto_started)
        manifest["automation_label"] = "Auto review running" if auto_started else "Manual visual review"
        submitted_event = self.record_prompt_event(
            context,
            "submitted",
            source_prompt,
            run_id="",
            label="USER PROMPT SUBMITTED",
            source="n_panel",
            route="visual_review",
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "prompt_events", submitted_event)
        queued_event = self.record_automation_event(
            context,
            actor="user",
            phase="queued",
            status="completed",
            label="USER PROMPT SUBMITTED",
            summary=source_prompt,
            run_id="",
            related_objects=[item.get("name", "") for item in self._visual_review_object_records(context, selected_only=True)[:12]],
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "automation_events", queued_event)
        self._visual_review_store(context).save_run(manifest)
        self._visual_review_active_run_id = str(manifest.get("run_id", ""))
        self._sync_visual_review_window_manager(context, manifest)
        self._record_visual_review_step(context, manifest, "creator_prompt", "running", f"Creator pass 1 started: {compact_text(source_prompt, 180)}")
        creator_prompt = self._visual_review_creator_prompt(manifest)
        manifest["last_creator_prompt"] = creator_prompt
        creator_event = self.record_prompt_event(
            context,
            "creator_prompt_sent",
            creator_prompt,
            run_id="",
            label="CREATOR PROMPT SENT",
            source="runtime",
            route="creator",
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "prompt_events", creator_event)
        self._visual_review_store(context).save_run(manifest)
        self.send_prompt(
            context=context,
            prompt=creator_prompt,
            include_scene_context=True,
            model=getattr(window_manager, "codex_blender_model", ""),
            effort=getattr(window_manager, "codex_blender_effort", ""),
            attachments=[item.path for item in getattr(window_manager, "codex_blender_attachments", [])],
            chat_mode="scene_agent",
            auto_create_action=False,
        )
        self._visual_review_last_turn_in_progress = True
        window_manager.codex_blender_prompt = ""
        window_manager.codex_blender_attachments.clear()
        return manifest

    def stop_visual_review_loop(self, context: bpy.types.Context, run_id: str = "") -> dict[str, Any]:
        run_id = run_id or self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
        if not run_id:
            raise RuntimeError("No active visual review run.")
        manifest = self._visual_review_store(context).request_stop(run_id)
        self._sync_visual_review_window_manager(context, manifest)
        try:
            if self.service.snapshot().turn_in_progress:
                self.service.interrupt_turn()
        except Exception:
            pass
        self._record_visual_review_step(context, manifest, "stop", "completed", "Visual review loop stopped by the user.")
        action_id = str(manifest.get("action_id", ""))
        if action_id:
            try:
                self.update_action_status(
                    context,
                    action_id,
                    "completed_with_warnings",
                    result_summary="Visual self-review stopped before reaching the target score.",
                    recovery="Open the run to inspect screenshots and continue if the scene still needs work.",
                )
            except Exception:
                pass
        return manifest

    def continue_visual_review_loop(self, context: bpy.types.Context, run_id: str = "") -> dict[str, Any]:
        run_id = run_id or self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
        if not run_id:
            raise RuntimeError("No visual review run selected.")
        store = self._visual_review_store(context)
        manifest = store.load_run(run_id)
        if self.service.snapshot().turn_in_progress:
            raise RuntimeError("A Codex turn is already running.")
        manifest["stop_requested"] = False
        manifest["status"] = PHASE_CREATOR_RUNNING
        manifest["phase"] = PHASE_CREATOR_RUNNING
        manifest["stop_reason"] = ""
        store.save_run(manifest)
        self._visual_review_active_run_id = run_id
        self._sync_visual_review_window_manager(context, manifest)
        self._record_visual_review_step(context, manifest, "creator_prompt", "running", f"Continuing visual review: {compact_text(str(manifest.get('current_prompt', '')), 180)}")
        creator_prompt = self._visual_review_creator_prompt(manifest)
        manifest["last_creator_prompt"] = creator_prompt
        creator_event = self.record_prompt_event(
            context,
            "creator_prompt_sent",
            creator_prompt,
            run_id="",
            label="CREATOR PROMPT SENT",
            source="runtime",
            route="creator",
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "prompt_events", creator_event)
        store.save_run(manifest)
        self.send_prompt(
            context=context,
            prompt=creator_prompt,
            include_scene_context=True,
            model=getattr(context.window_manager, "codex_blender_model", ""),
            effort=getattr(context.window_manager, "codex_blender_effort", ""),
            chat_mode="scene_agent",
            auto_create_action=False,
        )
        self._visual_review_last_turn_in_progress = True
        return manifest

    def capture_visual_review_viewpoints(self, context: bpy.types.Context, run_id: str = "") -> dict[str, Any]:
        run_id = run_id or self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
        if run_id:
            manifest = self._visual_review_store(context).load_run(run_id)
            output_dir = self._visual_review_store(context).captures_dir(run_id, int(manifest.get("current_iteration", 1)))
            resolution = int(manifest.get("resolution", DEFAULT_SCREENSHOT_RESOLUTION))
        else:
            output_dir = self._visual_review_store(context).root / "_manual_capture"
            resolution = int(getattr(context.window_manager, "codex_blender_visual_review_resolution", DEFAULT_SCREENSHOT_RESOLUTION))
        return self._execute_dynamic_tool(
            context,
            "capture_scene_viewpoints",
            {
                "output_dir": str(output_dir),
                "resolution": resolution,
                "max_viewpoints": int(self._visual_review_geometry_settings(context).get("selected_capture_count", 8)),
                "selected_only": bool(getattr(context.window_manager, "codex_blender_active_scope", "selection") == "selection"),
                "use_geometry_planner": True,
                "geometry_settings": self._visual_review_geometry_settings(context),
            },
        )

    def visual_review_context(self, context: bpy.types.Context) -> dict[str, Any]:
        run_id = self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
        active = {}
        if run_id:
            try:
                active = self._visual_review_store(context).load_run(run_id)
            except Exception as exc:
                active = {"run_id": run_id, "status": PHASE_FAILED, "phase": PHASE_FAILED, "error": str(exc)}
        latest_pass = _latest_pass(active)
        capture = dict(latest_pass.get("capture", {}) or active.get("pending_capture", {}) or {})
        latest_validation = self._latest_asset_validation_report(context)
        observability = self._web_observability_payload(context, active, latest_pass, capture, latest_validation)
        return {
            "enabled": bool(getattr(context.window_manager, "codex_blender_visual_review_enabled", True)),
            "auto_after_scene_change": self._auto_visual_review_enabled(context),
            "active_run_id": run_id,
            "active_run": active,
            "asset_intent_manifest": self.get_asset_intent_manifest(context, run_id=run_id),
            "constraint_graph": self.get_asset_constraint_graph(context, run_id=run_id),
            "repair_plan": self.get_asset_repair_plan(context, run_id=run_id),
            "latest_validation_report": latest_validation,
            "settings": {
                "max_iterations": getattr(context.window_manager, "codex_blender_visual_review_max_iterations", DEFAULT_MAX_ITERATIONS),
                "target_score": getattr(context.window_manager, "codex_blender_visual_review_target_score", DEFAULT_TARGET_SCORE),
                "resolution": getattr(context.window_manager, "codex_blender_visual_review_resolution", DEFAULT_SCREENSHOT_RESOLUTION),
                "capture_mode": getattr(context.window_manager, "codex_blender_visual_review_capture_mode", DEFAULT_CAPTURE_MODE),
                "geometry": self._visual_review_geometry_settings(context),
            },
            "recent_runs": self.list_visual_review_runs(context, limit=5),
            **observability,
        }

    # Asset intent and repair helpers live alongside visual-review state.
    def _scene_asset_intent_manifest(self, context: bpy.types.Context) -> dict[str, Any]:
        scene = getattr(context, "scene", None)
        if scene is None:
            return {}
        for key in ("codex_blender_asset_intent_manifest", "codex_blender_asset_intent_manifest_json"):
            value = None
            try:
                value = getattr(scene, key)
            except Exception:
                value = None
            if isinstance(value, dict):
                return value
            if isinstance(value, str) and value.strip():
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
            getter = getattr(scene, "get", None)
            if callable(getter):
                try:
                    value = getter(key, None)
                except Exception:
                    value = None
                if isinstance(value, dict):
                    return value
                if isinstance(value, str) and value.strip():
                    try:
                        parsed = json.loads(value)
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        return parsed
        return {}

    def _store_scene_asset_intent_manifest(self, context: bpy.types.Context, manifest: dict[str, Any]) -> None:
        scene = getattr(context, "scene", None)
        if scene is None:
            return
        payload = _json_safe_web(manifest)
        try:
            setattr(scene, "codex_blender_asset_intent_manifest", payload)
        except Exception:
            pass
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        try:
            setattr(scene, "codex_blender_asset_intent_manifest_json", serialized)
        except Exception:
            pass
        setter = getattr(scene, "__setitem__", None)
        if callable(setter):
            try:
                setter("codex_blender_asset_intent_manifest_json", serialized)
            except Exception:
                pass

    def _infer_asset_intent_manifest(self, context: bpy.types.Context) -> dict[str, Any]:
        report = self._latest_asset_validation_report(context)
        objects = list(report.get("objects", []) or [])
        issues = list(report.get("issues", []) or [])
        inferred = {
            "source": "inferred",
            "objects": [],
            "constraints": [],
            "required_contacts": [],
            "forbidden_intersections": [],
        }
        for item in objects[:32]:
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            inferred["objects"].append({"name": name, "role": "inferred", "expected_dimensions": item.get("dimensions", [])})
        for issue in issues[:32]:
            issue_type = str(issue.get("type", "") or "")
            objects_in_issue = [str(obj) for obj in issue.get("objects", []) or [] if str(obj).strip()]
            if issue_type in {"floating_part", "required_contact_failure"} and objects_in_issue:
                inferred["required_contacts"].append({"objects": objects_in_issue, "relation": "supported_by"})
            elif issue_type in {"interpenetration", "excessive_overlap", "castle_battlement_intersection", "castle_zone_violation"} and objects_in_issue:
                inferred["forbidden_intersections"].append({"objects": objects_in_issue, "relation": "must_not_intersect"})
        return inferred

    def _build_constraint_graph(self, manifest: dict[str, Any], report: dict[str, Any], *, selected_only: bool = False) -> dict[str, Any]:
        objects = list(report.get("objects", []) or [])
        issues = list(report.get("issues", []) or [])
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for item in manifest.get("objects", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            nodes.append({"id": name, "kind": "manifest_object", "role": str(item.get("role", "") or ""), "anchors": _json_safe_web(item.get("anchors", {}))})
        if not nodes:
            nodes = [{"id": str(item.get("name", "") or f"object_{index}"), "kind": "geometry_object"} for index, item in enumerate(objects)]
        for constraint in manifest.get("constraints", []) or []:
            if isinstance(constraint, dict):
                edges.append(
                    {
                        "id": constraint.get("id") or f"constraint_{len(edges) + 1}",
                        "kind": str(constraint.get("type", "constraint") or "constraint"),
                        "source": constraint.get("object", constraint.get("source", "")),
                        "targets": list(constraint.get("supported_by", constraint.get("targets", [])) or []),
                        "tolerance": _json_safe_web(constraint.get("tolerance", {})),
                        "source_type": "manifest",
                    }
                )
        for issue in issues:
            issue_type = str(issue.get("type", "") or "")
            objects_in_issue = [str(obj) for obj in issue.get("objects", []) or [] if str(obj).strip()]
            if not objects_in_issue:
                continue
            relation = None
            if issue_type in {"floating_part", "required_contact_failure"}:
                relation = "supported_by"
            elif issue_type in {"interpenetration", "excessive_overlap", "castle_battlement_intersection"}:
                relation = "must_not_intersect"
            elif issue_type in {"z_fighting_risk", "duplicate_surface_risk"}:
                relation = "avoid_overlap"
            if relation:
                edges.append(
                    {
                        "id": issue.get("issue_id", issue.get("defect_id", f"edge_{len(edges) + 1}")),
                        "kind": relation,
                        "source": objects_in_issue[0],
                        "targets": objects_in_issue[1:] or [objects_in_issue[0]],
                        "source_type": "validation",
                        "severity": issue.get("severity", "low"),
                        "confidence": issue.get("confidence", 0.5),
                    }
                )
        return {"selected_only": bool(selected_only), "node_count": len(nodes), "edge_count": len(edges), "nodes": nodes, "edges": edges}

    def _build_safe_repair_plan(self, manifest: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        issues = list(report.get("issues", []) or [])
        safe_repairs: list[dict[str, Any]] = []
        gated_repairs: list[dict[str, Any]] = []
        for issue in issues[:64]:
            issue_type = str(issue.get("type", "") or "")
            objects = [str(obj) for obj in issue.get("objects", []) or [] if str(obj).strip()]
            fix = str(issue.get("suggested_fix", "") or issue.get("remediation_hint", "") or "")
            entry = {
                "issue_id": issue.get("issue_id", issue.get("defect_id", "")),
                "issue_type": issue_type,
                "objects": objects,
                "suggested_fix": fix,
                "acceptance_tests": list(issue.get("acceptance_tests", []) or []),
            }
            if issue_type in {"floating_part", "required_contact_failure", "scale_outlier", "origin_error", "bad_alignment", "castle_zone_violation"}:
                entry["operation"] = "safe_transform"
                safe_repairs.append(entry)
            elif issue_type in {"z_fighting_risk", "duplicate_surface_risk"}:
                entry["operation"] = "safe_offset_or_cleanup"
                safe_repairs.append(entry)
            else:
                entry["operation"] = "gated_mesh_repair"
                gated_repairs.append(entry)
        return {
            "source": "validation_report",
            "validation_report_id": str(report.get("report_id", "")),
            "goal": str(manifest.get("goal", manifest.get("original_prompt", "")) or ""),
            "safe_repairs": safe_repairs,
            "gated_repairs": gated_repairs,
            "summary": {"safe_count": len(safe_repairs), "gated_count": len(gated_repairs)},
        }

    def _store_scene_safe_asset_repair(self, context: bpy.types.Context, plan: dict[str, Any], applied_repairs: list[dict[str, Any]]) -> None:
        scene = getattr(context, "scene", None)
        if scene is None:
            return
        payload = {"repair_plan": _json_safe_web(plan), "applied_repairs": _json_safe_web(applied_repairs)}
        try:
            setattr(scene, "codex_blender_last_safe_asset_repair", payload)
        except Exception:
            pass
        try:
            setattr(scene, "codex_blender_last_safe_asset_repair_json", json.dumps(payload, ensure_ascii=True, sort_keys=True))
        except Exception:
            pass

    def _handle_web_console_control_from_thread(self, action: str) -> dict[str, Any]:
        if threading.current_thread() is threading.main_thread():
            return self._handle_web_console_control(bpy.context, action)
        return self.dispatcher.submit(lambda: self._handle_web_console_control(bpy.context, action)).wait(timeout=20.0)

    def _handle_web_console_control(self, context: bpy.types.Context, action: str) -> dict[str, Any]:
        action = (action or "").strip().lower()
        if action == "stop_review":
            run_id = self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
            if run_id:
                self.stop_visual_review_loop(context, run_id)
                self._update_web_console_cache(context)
                return {"ok": True, "action": action, "run_id": run_id}
            if self.service.snapshot().turn_in_progress:
                self.interrupt_turn()
                self._update_web_console_cache(context)
                return {"ok": True, "action": action, "run_id": "", "interrupted_turn": True}
            return {"ok": False, "action": action, "error": "No active review or turn is running."}
        if action == "continue_review":
            manifest = self.continue_visual_review_loop(context)
            self._update_web_console_cache(context)
            return {"ok": True, "action": action, "run_id": manifest.get("run_id", "")}
        if action == "validate_now":
            settings = self._visual_review_geometry_settings(context)
            selected_only = bool(getattr(context.window_manager, "codex_blender_active_scope", "selection") == "selection")
            result = self._execute_dynamic_tool(
                context,
                "validate_gpt_asset",
                {
                    "selected_only": selected_only,
                    "run_id": self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", ""),
                    "settings": settings,
                },
            )
            payload = self._tool_json_payload(result)
            self._update_web_console_cache(context)
            return {
                "ok": True,
                "action": action,
                "report_id": str(payload.get("report_id", "")),
                "status": str(payload.get("status", "")),
                "validation_report": payload,
            }
        if action == "plan_viewpoints":
            settings = self._visual_review_geometry_settings(context)
            selected_only = bool(getattr(context.window_manager, "codex_blender_active_scope", "selection") == "selection")
            result = self._execute_dynamic_tool(
                context,
                "plan_visual_review_viewpoints",
                {
                    "selected_only": selected_only,
                    "settings": settings,
                },
            )
            payload = self._tool_json_payload(result)
            self._update_web_console_cache(context)
            return {
                "ok": True,
                "action": action,
                "plan": payload,
            }
        if action == "apply_safe_repair":
            payload = self.apply_safe_asset_repair(
                context,
                run_id=self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", ""),
            )
            return {"ok": True, "action": action, **payload}
        if action in {"show_overlays", "clear_overlays"}:
            scene = getattr(context, "scene", None)
            if scene is not None:
                try:
                    scene["codex_qa_overlays_visible"] = action == "show_overlays"
                except Exception:
                    pass
            self._update_web_console_cache(context)
            return {"ok": True, "action": action, "visible": action == "show_overlays", "note": "Overlay visibility flag updated; Blender overlay object creation remains in the validation adapter."}
        if action == "refresh_state":
            self.sync_window_manager(context, force=True)
            self._update_web_console_cache(context)
            return {"ok": True, "action": action}
        return {"ok": False, "action": action, "error": f"Unsupported action: {action}"}

    def _sync_web_console_window_manager(self, context: bpy.types.Context) -> None:
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return
        state = self.web_console_state(None)
        if hasattr(wm, "codex_blender_web_console_running"):
            wm.codex_blender_web_console_running = bool(state.get("running", False))
        if hasattr(wm, "codex_blender_web_console_url"):
            wm.codex_blender_web_console_url = str(state.get("url", ""))
        if hasattr(wm, "codex_blender_web_console_port"):
            wm.codex_blender_web_console_port = int(state.get("port", 0) or 0)
        if hasattr(wm, "codex_blender_web_console_error"):
            wm.codex_blender_web_console_error = str(state.get("error", ""))
        if hasattr(wm, "codex_blender_web_console_auto_started"):
            wm.codex_blender_web_console_auto_started = bool(state.get("auto_started", False))

    def _update_web_console_cache(self, context: bpy.types.Context) -> dict[str, Any]:
        self._web_console_sequence += 1
        sequence = self._web_console_sequence
        try:
            snapshot = self.service.snapshot()
            recovering = bool(getattr(snapshot, "stream_recovering", False))
            if recovering and not self._last_stream_recovering:
                self.record_automation_event(
                    None,
                    actor="service",
                    phase="reconnecting",
                    status="running",
                    label="RECONNECTING",
                    summary=getattr(snapshot, "last_error_recovery", "") or snapshot.last_error or "Codex stream is reconnecting.",
                    update_cache=False,
                )
            elif self._last_stream_recovering and not recovering:
                self.record_automation_event(
                    None,
                    actor="service",
                    phase="reconnecting",
                    status="completed",
                    label="STREAM CONNECTED",
                    summary="Codex stream recovery completed.",
                    update_cache=False,
                )
            self._last_stream_recovering = recovering
        except Exception:
            pass
        try:
            payload = self._build_web_console_payload(context)
        except Exception as exc:
            self._append_console_log(
                context,
                "backend_error",
                "LIVE STATE BUILD FAILED",
                status="failed",
                summary=str(exc),
                payload={"traceback": traceback.format_exc(limit=8)},
            )
            payload = self._fallback_web_console_payload(context, exc)
        payload["sequence"] = sequence
        payload["generated_at"] = self._event_timestamp()
        self._web_console_cache = _json_safe_web(payload)
        self._sync_web_console_window_manager(context)
        return self._web_console_cache

    def _backend_error_payload(self, exc: Exception) -> dict[str, Any]:
        return {
            "title": "Live state builder failed",
            "summary": compact_text(str(exc), 500),
            "severity": "error",
            "recovery": "The web console is still running. Refresh the console, restart the service, continue the review, or stop the run if this repeats.",
            "raw": traceback.format_exc(limit=8),
        }

    def _fallback_web_console_payload(self, context: bpy.types.Context, exc: Exception) -> dict[str, Any]:
        try:
            snapshot = self.service.snapshot()
            service = {
                "status": snapshot.status_text,
                "account": snapshot.account.email if snapshot.account else "",
                "plan": snapshot.account.plan_type if snapshot.account else "",
                "thread": short_thread_id(snapshot.active_thread_id),
                "turn_in_progress": bool(snapshot.turn_in_progress),
                "stream_recovering": bool(getattr(snapshot, "stream_recovering", False)),
                "error_title": getattr(snapshot, "last_error_title", ""),
                "error_summary": snapshot.last_error,
                "error_recovery": getattr(snapshot, "last_error_recovery", ""),
            }
            activity = snapshot.activity_text
            active = bool(snapshot.turn_in_progress)
        except Exception:
            service = {"status": "Runtime state unavailable.", "turn_in_progress": False, "stream_recovering": False}
            activity = ""
            active = False
        web_state = self.web_console_state(None)
        logs = self._recent_console_logs(context)
        backend_error = self._backend_error_payload(exc)
        return {
            "error": backend_error["summary"],
            "backend_error": backend_error,
            "version": ADDON_VERSION,
            "module_file": str(Path(__file__).resolve()),
            "storage_root": str(self._storage_root(context)),
            "web_console": web_state,
            "service": service,
            "automation": {
                "active": active,
                "phase": "backend_error",
                "phase_label": "NEEDS ATTENTION",
                "run_id": self._visual_review_active_run_id,
                "pass": 0,
                "max_passes": 0,
                "score": 0.0,
                "activity": activity or backend_error["summary"],
                "auto_started": False,
                "stop_reason": "",
            },
            "prompt_events": list(self._prompt_events),
            "automation_events": list(self._automation_events),
            "logs": logs,
            "startup_trace": self._startup_trace(logs),
            "scene_snapshot": {},
            "visual_review": {"active_run": {}, "recent_runs": [], "runs": {"active_run_id": self._visual_review_active_run_id}},
            "validation": {},
            "checks": [],
            "screenshots": [],
            "view_planner": {},
            "algorithms": [],
            "intent_manifest": {},
            "constraints": {},
            "repair_plan": {},
            "overlays": {},
            "runs": {"active_run_id": self._visual_review_active_run_id, "active": {}, "recent": [], "index": {}},
            "critic": {},
            "timeline": [],
        }

    def _build_web_console_payload(self, context: bpy.types.Context) -> dict[str, Any]:
        snapshot = self.service.snapshot()
        wm = context.window_manager
        run_id = self._visual_review_active_run_id or getattr(wm, "codex_blender_visual_review_active_run_id", "")
        run: dict[str, Any] = {}
        if run_id:
            try:
                run = self._visual_review_store(context).load_run(run_id)
            except Exception as exc:
                run = {"run_id": run_id, "phase": PHASE_FAILED, "status": PHASE_FAILED, "error": str(exc), "passes": []}
        latest_pass = _latest_pass(run)
        capture = dict(latest_pass.get("capture", {}) or run.get("pending_capture", {}) or {})
        validation = dict(latest_pass.get("asset_validation_report", {}) or capture.get("asset_validation_report", {}) or self._latest_asset_validation_report(context) or {})
        backend_error: dict[str, Any] = {}
        try:
            observability = self._web_observability_payload(context, run, latest_pass, capture, validation)
        except Exception as exc:
            backend_error = self._backend_error_payload(exc)
            self._append_console_log(
                context,
                "backend_error",
                "OBSERVABILITY BUILD FAILED",
                status="failed",
                summary=str(exc),
                run_id=run_id,
                payload={"traceback": traceback.format_exc(limit=8)},
            )
            observability = {
                "runs": {"active_run_id": run_id, "active": run, "recent": [], "index": {run_id: run} if run_id else {}},
                "algorithms": [],
                "intent_manifest": {},
                "constraints": {},
                "repair_plan": {},
                "overlays": {},
                "screenshots": [],
                "timeline": _web_timeline(run),
            }
        screenshots = list(observability.get("screenshots", []) or [])
        timeline = list(observability.get("timeline", []) or [])
        action_id = str(run.get("action_id", ""))
        if action_id:
            try:
                card = self.get_action_detail(context, action_id)
                detail = card.get("detail", {}) if isinstance(card.get("detail", {}), dict) else {}
                timeline.extend(detail.get("tool_activity", []) or [])
            except Exception:
                pass
        phase = str(run.get("phase", run.get("status", "idle")) if run else ("reconnecting" if getattr(snapshot, "stream_recovering", False) else "idle"))
        phase_label = _web_phase_label(phase, recovering=bool(getattr(snapshot, "stream_recovering", False)))
        checks = _web_checks(validation, latest_pass, capture, screenshots=screenshots)
        web_state = self._web_console.status().as_public_dict() if self._web_console is not None else {"running": False, "url": "", "host": "127.0.0.1", "port": 0, "error": ""}
        web_state["auto_started"] = bool(self._web_console_auto_started)
        visual_root = self._visual_review_store(context).root
        runs = dict(observability.get("runs", {}) or {})
        runs["active_run_id"] = run_id
        if run_id:
            index = dict(runs.get("index", {}) or {})
            index.setdefault(run_id, run)
            runs["index"] = index
        prompt_events = self._dedupe_events(list(run.get("prompt_events", []) or []) + list(self._prompt_events))
        timeline_events = [
            {
                "event_id": str(item.get("event_id", "") or f"timeline-{index}"),
                "actor": "runtime",
                "phase": str(item.get("phase", "")),
                "status": str(item.get("status", "")),
                "label": str(item.get("phase_label", "") or item.get("phase", "EVENT")).upper(),
                "summary": str(item.get("summary", "")),
                "run_id": run_id,
                "created_at": str(item.get("started_at", "") or item.get("ended_at", "")),
                "artifacts": {"source": "timeline"},
            }
            for index, item in enumerate(timeline)
            if isinstance(item, dict)
        ]
        automation_events = self._dedupe_events(
            list(run.get("automation_events", []) or []) + list(self._automation_events) + timeline_events
        )
        scene_snapshot = self._scene_snapshot_payload(context, validation)
        logs = self._recent_console_logs(context)
        return {
            "version": ADDON_VERSION,
            "module_file": str(Path(__file__).resolve()),
            "storage_root": str(self._storage_root(context)),
            "allowed_screenshot_roots": [str(visual_root), str(Path(capture.get("output_dir", "") or visual_root))],
            "web_console": web_state,
            "backend_error": backend_error,
            "logs": logs,
            "startup_trace": self._startup_trace(logs),
            "service": {
                "status": snapshot.status_text,
                "account": snapshot.account.email if snapshot.account else "",
                "plan": snapshot.account.plan_type if snapshot.account else "",
                "thread": short_thread_id(snapshot.active_thread_id),
                "turn_in_progress": bool(snapshot.turn_in_progress),
                "stream_recovering": bool(getattr(snapshot, "stream_recovering", False)),
                "error_title": getattr(snapshot, "last_error_title", ""),
                "error_summary": snapshot.last_error,
                "error_recovery": getattr(snapshot, "last_error_recovery", ""),
            },
            "automation": {
                "active": bool(snapshot.turn_in_progress or (run and phase not in {"idle", PHASE_COMPLETE, PHASE_STOPPED, PHASE_FAILED})),
                "phase": phase,
                "phase_label": phase_label,
                "run_id": run_id,
                "pass": int(run.get("current_iteration", 0) or 0) if run else 0,
                "max_passes": int(run.get("max_iterations", getattr(wm, "codex_blender_visual_review_max_iterations", 5)) or 5),
                "score": float(run.get("current_score", 0.0) or 0.0) if run else 0.0,
                "activity": snapshot.activity_text or str(run.get("automation_label", "")),
                "auto_started": bool(run.get("auto_started", False)) if run else False,
                "stop_reason": str(run.get("stop_reason", "")) if run else "",
            },
            "prompt_events": prompt_events,
            "automation_events": automation_events,
            "scene_snapshot": scene_snapshot,
            "visual_review": {
                "active_run": run,
                "recent_runs": self.list_visual_review_runs(context, limit=8),
                "runs": runs,
            },
            "validation": validation,
            "checks": checks,
            "screenshots": screenshots,
            "view_planner": {
                "view_scores": latest_pass.get("view_scores", capture.get("view_scores", [])),
                "coverage_by_part": latest_pass.get("coverage_by_part", capture.get("coverage_by_part", {})),
                "optimization_viewpoints": capture.get("optimization_viewpoints", []),
                "audit_viewpoints": capture.get("audit_viewpoints", []),
                "diagnostics": capture.get("planner_diagnostics", capture.get("diagnostics", [])),
            },
            "algorithms": observability.get("algorithms", []),
            "intent_manifest": observability.get("intent_manifest", {}),
            "constraints": observability.get("constraints", {}),
            "repair_plan": observability.get("repair_plan", {}),
            "overlays": observability.get("overlays", {}),
            "runs": runs,
            "critic": {
                "prompt": str(run.get("last_critic_prompt", "")),
                "raw": str(latest_pass.get("critic_raw", "")),
                "summary": str(latest_pass.get("summary", "")),
                "issues": list(latest_pass.get("issues", []) or []),
                "issue_signature": list(latest_pass.get("issue_signature", []) or []),
                "viewpoint_notes": list(latest_pass.get("viewpoint_notes", []) or []),
                "delta_prompt": latest_pass.get("delta_prompt", {}),
                "next_prompt": str(latest_pass.get("next_prompt", "")),
                "pairwise_vs_best": latest_pass.get("pairwise_vs_best", {}),
            },
            "timeline": timeline[-150:],
        }

    def list_visual_review_runs(self, context: bpy.types.Context, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._visual_review_store(context).list_runs(limit=limit)

    def get_visual_review_run(self, context: bpy.types.Context, run_id: str) -> dict[str, Any]:
        if not run_id:
            raise RuntimeError("run_id is required.")
        return self._visual_review_store(context).load_run(run_id)

    def get_asset_intent_manifest(self, context: bpy.types.Context, *, run_id: str = "") -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        run: dict[str, Any] = {}
        if run_id:
            try:
                run = self._visual_review_store(context).load_run(run_id)
            except Exception:
                run = {}
        raw_manifest = {}
        if isinstance(run.get("asset_intent_manifest"), dict):
            raw_manifest = dict(run.get("asset_intent_manifest") or {})
        if not raw_manifest:
            raw_manifest = self._scene_asset_intent_manifest(context)
        latest_validation = self._latest_asset_validation_report(context)
        records = list(latest_validation.get("objects", []) or [])
        if not records:
            try:
                records = self._visual_review_object_records(context, selected_only=False)
            except Exception:
                records = []
        if not raw_manifest and isinstance(latest_validation.get("intent_manifest"), dict):
            raw_manifest = dict(latest_validation.get("intent_manifest") or {})
        return normalize_asset_intent_manifest(raw_manifest, records=records, prompt=str(run.get("original_prompt", "")))

    def set_asset_intent_manifest(self, context: bpy.types.Context, manifest: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
        records = self._visual_review_object_records(context, selected_only=False)
        normalized = normalize_asset_intent_manifest(manifest, records=records, prompt=str(manifest.get("prompt", "")))
        self._store_scene_asset_intent_manifest(context, normalized)
        if run_id:
            try:
                store = self._visual_review_store(context)
                run = store.load_run(run_id)
                run["asset_intent_manifest"] = normalized
                store.save_run(run)
            except Exception:
                pass
        self._update_web_console_cache(context)
        return normalized

    def get_asset_constraint_graph(self, context: bpy.types.Context, *, run_id: str = "") -> dict[str, Any]:
        manifest = self.get_asset_intent_manifest(context, run_id=run_id)
        report = self._latest_asset_validation_report(context)
        if isinstance(report.get("constraint_graph"), dict) and report.get("constraint_graph", {}).get("nodes"):
            return dict(report.get("constraint_graph") or {})
        records = list(report.get("objects", []) or [])
        if not records:
            records = self._visual_review_object_records(context, selected_only=False)
        return build_constraint_graph(records, manifest)

    def get_asset_repair_plan(self, context: bpy.types.Context, *, run_id: str = "") -> dict[str, Any]:
        report = self._latest_asset_validation_report(context)
        if not report and run_id:
            try:
                run = self._visual_review_store(context).load_run(run_id)
                latest = _latest_pass(run)
                report = dict(latest.get("asset_validation_report", {}) or {})
            except Exception:
                report = {}
        if isinstance(report.get("repair_plan"), dict):
            return dict(report.get("repair_plan") or {})
        manifest = self.get_asset_intent_manifest(context, run_id=run_id)
        return build_asset_repair_plan(report, manifest=manifest, constraint_graph=self.get_asset_constraint_graph(context, run_id=run_id))

    def apply_safe_asset_repair(self, context: bpy.types.Context, repair_plan: dict[str, Any] | None = None, *, run_id: str = "") -> dict[str, Any]:
        plan = dict(repair_plan or {}) or self.get_asset_repair_plan(context, run_id=run_id)
        safe_actions = list(plan.get("safe_actions", []) or [])
        receipt = {
            "status": "queued_for_creator_delta" if safe_actions else "no_safe_actions",
            "run_id": run_id,
            "repair_plan_id": str(plan.get("repair_plan_id", "")),
            "safe_action_count": len(safe_actions),
            "applied_repairs": [],
            "note": "v0.15.0 records safe repair intent for the next bounded creator patch; destructive mesh edits remain gated.",
        }
        self._store_scene_safe_asset_repair(context, plan, [])
        self._update_web_console_cache(context)
        return receipt

    def list_asset_validation_reports(self, context: bpy.types.Context, *, limit: int = 20) -> list[dict[str, Any]]:
        root = self._asset_validation_reports_dir(context)
        if not root.exists():
            return []
        rows = []
        for path in root.glob("*.json"):
            try:
                import json

                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    rows.append(data)
            except Exception:
                rows.append({"report_id": path.stem, "status": "corrupt", "path": str(path)})
        rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return rows[: max(int(limit), 1)]

    def get_asset_validation_report(self, context: bpy.types.Context, report_id: str = "") -> dict[str, Any]:
        if not report_id:
            latest = self._latest_asset_validation_report(context)
            if latest:
                return latest
            raise RuntimeError("No asset validation report is available.")
        path = self._asset_validation_reports_dir(context) / f"{report_id}.json"
        if not path.exists():
            raise KeyError(f"Asset validation report not found: {report_id}")
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Asset validation report is not an object: {path}")
        return data

    def _pump_visual_review(self, context: bpy.types.Context, snapshot) -> None:
        run_id = self._visual_review_active_run_id or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
        transition_finished = self._visual_review_last_turn_in_progress and not snapshot.turn_in_progress
        self._visual_review_last_turn_in_progress = bool(snapshot.turn_in_progress)
        if not run_id:
            return
        try:
            manifest = self._visual_review_store(context).load_run(run_id)
        except Exception:
            return
        self._sync_visual_review_window_manager(context, manifest)
        if not transition_finished:
            return
        phase = str(manifest.get("phase", manifest.get("status", "")))
        try:
            if phase == PHASE_CREATOR_RUNNING:
                self._advance_visual_review_after_creator(context, manifest)
            elif phase == PHASE_CRITIC_RUNNING:
                self._advance_visual_review_after_critic(context, manifest, snapshot)
        except Exception as exc:
            manifest["status"] = PHASE_FAILED
            manifest["phase"] = PHASE_FAILED
            manifest["stop_reason"] = "runtime_error"
            manifest["error"] = str(exc)
            self._visual_review_store(context).save_run(manifest)
            self._sync_visual_review_window_manager(context, manifest)
            action_id = str(manifest.get("action_id", ""))
            if action_id:
                try:
                    self.update_action_status(
                        context,
                        action_id,
                        "failed",
                        result_summary=f"Visual review failed: {compact_text(str(exc), 180)}",
                        recovery="Open the run manifest, inspect screenshots, then retry or continue from the current prompt.",
                    )
                except Exception:
                    pass

    def _advance_visual_review_after_creator(self, context: bpy.types.Context, manifest: dict[str, Any]) -> None:
        store = self._visual_review_store(context)
        run_id = str(manifest.get("run_id", ""))
        iteration = int(manifest.get("current_iteration", 1))
        manifest["phase"] = PHASE_CAPTURING
        manifest["status"] = PHASE_CAPTURING
        store.save_run(manifest)
        self._sync_visual_review_window_manager(context, manifest)
        self._record_visual_review_step(context, manifest, "viewport_capture", "running", f"Capturing pass {iteration} screenshots.")
        capture = self._execute_dynamic_tool(
            context,
            "capture_scene_viewpoints",
            {
                "output_dir": str(store.captures_dir(run_id, iteration)),
                "resolution": int(manifest.get("resolution", DEFAULT_SCREENSHOT_RESOLUTION)),
                "max_viewpoints": int(self._visual_review_geometry_settings(context).get("selected_capture_count", 8)),
                "selected_only": bool(getattr(context.window_manager, "codex_blender_active_scope", "selection") == "selection"),
                "use_geometry_planner": True,
                "geometry_settings": {**dict(manifest.get("geometry_settings") or self._visual_review_geometry_settings(context)), "intent_manifest": dict(manifest.get("asset_intent_manifest") or self.get_asset_intent_manifest(context, run_id=run_id))},
            },
        )
        capture_payload = self._tool_json_payload(capture)
        validation_report = capture_payload.get("asset_validation_report") if isinstance(capture_payload.get("asset_validation_report"), dict) else {}
        if validation_report:
            saved_validation = self._save_asset_validation_report(context, validation_report, run_id=run_id)
            capture_payload["asset_validation_report"] = saved_validation
            capture_payload["validation_report_id"] = str(saved_validation.get("report_id", ""))
            validation_event = self.record_automation_event(
                context,
                actor="validator",
                phase="verifying_geometry",
                status="completed",
                label="VERIFYING GEOMETRY",
                summary=str(saved_validation.get("validation_summary", "Geometry validation completed.")),
                run_id="",
                validation_report_id=str(saved_validation.get("report_id", "")),
                update_cache=False,
            )
            self._append_event_to_manifest(manifest, "automation_events", validation_event)
        screenshots = [
            str(item.get("path", ""))
            for item in capture_payload.get("captures", [])
            if str(item.get("path", "")).strip()
        ]
        manifest["pending_capture"] = capture_payload
        manifest["phase"] = PHASE_CRITIC_RUNNING
        manifest["status"] = PHASE_CRITIC_RUNNING
        store.save_run(manifest)
        self._sync_visual_review_window_manager(context, manifest)
        self._record_visual_review_step(context, manifest, "viewport_capture", "completed", f"Captured {len(screenshots)} viewpoint screenshot(s).")
        critic_prompt = build_critic_prompt(manifest, screenshots, str(capture_payload.get("scene_digest", "")), geometry_payload=capture_payload)
        manifest["last_critic_prompt"] = critic_prompt
        manifest["last_capture_payload"] = capture_payload
        critic_event = self.record_prompt_event(
            context,
            "critic_prompt_sent",
            critic_prompt,
            run_id="",
            label="CRITIC PROMPT SENT",
            source="runtime",
            route="critic",
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "prompt_events", critic_event)
        store.save_run(manifest)
        self._update_web_console_cache(context)
        self._record_visual_review_step(context, manifest, "critic_prompt", "running", f"Critic pass {iteration} started with {len(screenshots)} screenshot(s).")
        self.send_prompt(
            context=context,
            prompt=critic_prompt,
            include_scene_context=False,
            model=getattr(context.window_manager, "codex_blender_model", ""),
            effort=getattr(context.window_manager, "codex_blender_effort", ""),
            attachments=screenshots,
            chat_mode="scene_agent",
            auto_create_action=False,
        )
        self._visual_review_last_turn_in_progress = True

    def _advance_visual_review_after_critic(self, context: bpy.types.Context, manifest: dict[str, Any], snapshot) -> None:
        store = self._visual_review_store(context)
        run_id = str(manifest.get("run_id", ""))
        critique = parse_critique(self._latest_assistant_text(snapshot))
        capture = dict(manifest.get("pending_capture") or {})
        screenshots = [
            str(item.get("path", ""))
            for item in capture.get("captures", [])
            if str(item.get("path", "")).strip()
        ]
        metric_vector = dict(capture.get("metric_vector") or capture.get("geometry_digest", {}).get("metric_vector") or {})
        defects = list(capture.get("defects") or capture.get("geometry_digest", {}).get("defects") or [])
        validation_report = dict(capture.get("asset_validation_report") or {})
        geometry_settings = dict(manifest.get("geometry_settings") or self._visual_review_geometry_settings(context))
        score_payload = hybrid_score(
            metric_vector,
            critic_score=float(critique.get("critic_score", critique.get("score", 0.0)) or 0.0),
            geometry_weight=float(geometry_settings.get("geometry_score_weight", DEFAULT_GEOMETRY_SCORE_WEIGHT) or DEFAULT_GEOMETRY_SCORE_WEIGHT),
            critic_weight=float(geometry_settings.get("critic_score_weight", DEFAULT_CRITIC_SCORE_WEIGHT) or DEFAULT_CRITIC_SCORE_WEIGHT),
        ) if metric_vector else {"hybrid_score": float(critique.get("score", 0.0) or 0.0), "deterministic_score": 0.0, "critic_score": float(critique.get("score", 0.0) or 0.0)}
        hard_gate_payload = hard_gates(
            metric_vector,
            defects,
            target_score=float(manifest.get("target_score", DEFAULT_TARGET_SCORE) or DEFAULT_TARGET_SCORE),
            hybrid=float(score_payload.get("hybrid_score", 0.0)),
        ) if metric_vector else {}
        pass_data = {
            "iteration": int(manifest.get("current_iteration", len(manifest.get("passes", [])) + 1)),
            "score": float(score_payload.get("hybrid_score", critique.get("score", 0.0)) or 0.0),
            "critic_score": float(critique.get("critic_score", critique.get("score", 0.0)) or 0.0),
            "deterministic_score": float(score_payload.get("deterministic_score", 0.0) or 0.0),
            "hybrid_score": float(score_payload.get("hybrid_score", 0.0) or 0.0),
            "metric_vector": metric_vector,
            "hard_gates": hard_gate_payload or dict(capture.get("hard_gates") or {}),
            "view_scores": list(capture.get("view_scores", []) or []),
            "coverage_by_part": dict(capture.get("coverage_by_part", {}) or {}),
            "defects": defects,
            "asset_validation_report": validation_report,
            "validation_report_id": str(capture.get("validation_report_id", validation_report.get("report_id", "")) or ""),
            "validation_metrics": dict(capture.get("validation_metrics", validation_report.get("metric_vector", {})) or {}),
            "validation_issues": list(capture.get("validation_issues", validation_report.get("issues", [])) or []),
            "geometry_digest": dict(capture.get("geometry_digest", {}) or {}),
            "geometry_score_weight": float(geometry_settings.get("geometry_score_weight", DEFAULT_GEOMETRY_SCORE_WEIGHT) or DEFAULT_GEOMETRY_SCORE_WEIGHT),
            "critic_score_weight": float(geometry_settings.get("critic_score_weight", DEFAULT_CRITIC_SCORE_WEIGHT) or DEFAULT_CRITIC_SCORE_WEIGHT),
            "satisfied": bool(critique.get("satisfied", False)),
            "issues": list(critique.get("issues", []) or []),
            "issue_signature": list(critique.get("issue_signature", []) or []),
            "delta_prompt": critique.get("delta_prompt", {}),
            "pairwise_vs_best": dict(critique.get("pairwise_vs_best", {}) or {}),
            "summary": str(critique.get("summary", "")),
            "next_prompt": str(critique.get("next_prompt", "")),
            "viewpoint_notes": list(critique.get("viewpoint_notes", []) or []),
            "screenshots": screenshots,
            "capture": capture,
            "capture_failed": bool(capture.get("capture_failed", False)),
            "creator_prompt": str(manifest.get("last_creator_prompt", "")),
            "critic_prompt": str(manifest.get("last_critic_prompt", "")),
            "critic_response": critique,
            "critic_raw": str(critique.get("raw", "")),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest.pop("pending_capture", None)
        store.save_run(manifest)
        manifest = store.append_pass(run_id, pass_data)
        if str(pass_data.get("next_prompt", "")).strip() or pass_data.get("delta_prompt"):
            delta_event = self.record_prompt_event(
                context,
                "delta_prompt_created",
                str(pass_data.get("next_prompt", "")),
                run_id="",
                label="DELTA PROMPT CREATED",
                source="critic",
                route="next_creator_pass",
                update_cache=False,
            )
            delta_event["delta_prompt"] = pass_data.get("delta_prompt", {})
            self._append_event_to_manifest(manifest, "prompt_events", delta_event)
            store.save_run(manifest)
        self._sync_visual_review_window_manager(context, manifest)
        self._record_visual_review_step(
            context,
            manifest,
            "critic_review",
            "completed",
            f"Pass {pass_data['iteration']} scored {pass_data['score']:.2f}. {compact_text(pass_data['summary'], 180)}",
        )
        phase = str(manifest.get("phase", ""))
        action_id = str(manifest.get("action_id", ""))
        if phase in {PHASE_COMPLETE, PHASE_STOPPED, PHASE_FAILED}:
            status = "completed" if phase == PHASE_COMPLETE else "completed_with_warnings"
            if action_id:
                try:
                    self.update_action_status(
                        context,
                        action_id,
                        status,
                        result_summary=f"Visual self-review finished at score {float(manifest.get('current_score', 0.0)):.2f}: {manifest.get('stop_reason', phase)}.",
                        recovery="Use Blender Undo for recent edits, open screenshots to inspect each pass, or continue the run if more work is needed.",
                    )
                except Exception:
                    pass
            return
        if not str(manifest.get("current_prompt", "")).strip():
            manifest["status"] = PHASE_STOPPED
            manifest["phase"] = PHASE_STOPPED
            manifest["stop_reason"] = "missing_next_prompt"
            store.save_run(manifest)
            self._sync_visual_review_window_manager(context, manifest)
            return
        self._record_visual_review_step(
            context,
            manifest,
            "creator_prompt",
            "running",
            f"Creator pass {manifest.get('current_iteration', 0)} started from critic feedback.",
        )
        creator_prompt = self._visual_review_creator_prompt(manifest)
        manifest["last_creator_prompt"] = creator_prompt
        creator_event = self.record_prompt_event(
            context,
            "creator_prompt_sent",
            creator_prompt,
            run_id="",
            label="CREATOR PROMPT SENT",
            source="runtime",
            route="creator",
            update_cache=False,
        )
        self._append_event_to_manifest(manifest, "prompt_events", creator_event)
        store.save_run(manifest)
        self.send_prompt(
            context=context,
            prompt=creator_prompt,
            include_scene_context=True,
            model=getattr(context.window_manager, "codex_blender_model", ""),
            effort=getattr(context.window_manager, "codex_blender_effort", ""),
            chat_mode="scene_agent",
            auto_create_action=False,
        )
        self._visual_review_last_turn_in_progress = True

    def _visual_review_creator_prompt(self, manifest: dict[str, Any]) -> str:
        iteration = int(manifest.get("current_iteration", 1))
        return (
            "You are the creator phase of an autonomous Blender game-art visual self-review loop.\n"
            "Make useful additive or reversible scene improvements with the available structured Blender tools. "
            "Do not wait for a workflow graph. Do not ask for permission unless the action is destructive, external, credentialed, or arbitrary-code.\n\n"
            "After this creator pass, the backend will automatically VERIFY evaluated geometry, part contacts, overlaps, support, topology, planned screenshots, and hard gates. "
            "Validation-first defects outrank screenshot polish. If an asset intent manifest exists, preserve its required contacts, anchors, clearance rules, and forbidden intersections.\n\n"
            "Stop after the scene-editing pass so the runtime can capture and critique the result.\n\n"
            f"Original goal: {manifest.get('original_prompt', '')}\n"
            f"Asset intent manifest: {json.dumps(manifest.get('asset_intent_manifest', {}), ensure_ascii=True, sort_keys=True)}\n"
            f"Current pass: {iteration} of {manifest.get('max_iterations', DEFAULT_MAX_ITERATIONS)}\n"
            f"Current creator prompt:\n{manifest.get('current_prompt', '')}\n\n"
            "Stop when this pass is complete. The runtime will queue geometry validation, viewport screenshots, and the critic turn automatically."
        )

    def _visual_review_blocks_tool(self, tool_name: str) -> bool:
        run_id = self._visual_review_active_run_id or getattr(getattr(bpy.context, "window_manager", None), "codex_blender_visual_review_active_run_id", "")
        if not run_id:
            return False
        try:
            manifest = self._visual_review_store(bpy.context).load_run(run_id)
        except Exception:
            return False
        if str(manifest.get("phase", "")) not in MUTATION_BLOCKED_PHASES:
            return False
        policy = classify_tool(tool_name)
        return bool(policy.requires_action or policy.category in {"mutating", "external_write", "critical"})

    def _record_visual_review_step(self, context: bpy.types.Context, manifest: dict[str, Any], phase: str, status: str, summary: str) -> None:
        banner = {
            "creator_prompt": "CREATING",
            "viewport_capture": "VERIFYING GEOMETRY / SCREENSHOTTING",
            "critic_prompt": "CRITIQUING",
            "critic_review": "SCORING",
            "stop": "STOPPED",
        }.get(phase, "AUTO REVIEW")
        self._visual_review_console_banner(banner, summary)
        step = {
            "tool": "visual_review_loop",
            "phase": phase,
            "phase_label": banner,
            "status": status,
            "summary": summary,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if status in {"completed", "failed"} else "",
            "rollback_available": True,
        }
        try:
            event = self.record_automation_event(
                context,
                actor="runtime" if phase not in {"creator_prompt", "critic_prompt"} else ("codex_creator" if phase == "creator_prompt" else "codex_critic"),
                phase=phase,
                status=status,
                label=banner,
                summary=summary,
                run_id="",
                validation_report_id=str(manifest.get("validation_report_id", "")),
                update_cache=False,
            )
            self._append_event_to_manifest(manifest, "automation_events", event)
            timeline = list(manifest.get("timeline", []) or [])
            timeline.append(step)
            manifest["timeline"] = timeline[-200:]
            self._visual_review_store(context).save_run(manifest)
            self._update_web_console_cache(context)
        except Exception:
            pass
        action_id = str(manifest.get("action_id", ""))
        if not action_id:
            return
        try:
            self._record_action_step(context, action_id, step)
        except Exception:
            pass

    def _sync_visual_review_window_manager(self, context: bpy.types.Context, manifest: dict[str, Any]) -> None:
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return
        run_id = str(manifest.get("run_id", ""))
        wm.codex_blender_visual_review_active_run_id = run_id
        wm.codex_blender_visual_review_phase = str(manifest.get("phase", manifest.get("status", PHASE_STOPPED)))
        wm.codex_blender_visual_review_current_pass = int(manifest.get("current_iteration", len(manifest.get("passes", [])) or 0) or 0)
        wm.codex_blender_visual_review_current_score = float(manifest.get("current_score", 0.0) or 0.0)
        wm.codex_blender_visual_review_stop_requested = bool(manifest.get("stop_requested", False))
        if hasattr(wm, "codex_blender_visual_review_auto_started"):
            wm.codex_blender_visual_review_auto_started = bool(manifest.get("auto_started", False))
        latest_pass = list(manifest.get("passes", []) or [])[-1] if manifest.get("passes") else {}
        validation = latest_pass.get("asset_validation_report", {}) if isinstance(latest_pass, dict) else {}
        if hasattr(wm, "codex_blender_asset_validation_latest_report_id"):
            wm.codex_blender_asset_validation_latest_report_id = str(validation.get("report_id", latest_pass.get("validation_report_id", "")) or "")
        if hasattr(wm, "codex_blender_asset_validation_latest_score"):
            wm.codex_blender_asset_validation_latest_score = float(validation.get("asset_score", 0.0) or 0.0)
        if hasattr(wm, "codex_blender_asset_validation_latest_summary"):
            wm.codex_blender_asset_validation_latest_summary = compact_text(str(validation.get("validation_summary", "")), 180)
        if hasattr(wm, "codex_blender_asset_validation_latest_issue_count"):
            wm.codex_blender_asset_validation_latest_issue_count = int(validation.get("issue_count", 0) or 0)
        if hasattr(wm, "codex_blender_asset_validation_latest_critical_count"):
            wm.codex_blender_asset_validation_latest_critical_count = int(validation.get("critical_count", 0) or 0)
        self._visual_review_active_run_id = run_id if wm.codex_blender_visual_review_phase not in {PHASE_COMPLETE, PHASE_STOPPED, PHASE_FAILED} else run_id
        self._update_web_console_cache(context)

    def _visual_review_store(self, context: bpy.types.Context) -> VisualReviewStore:
        return VisualReviewStore(self._storage_root(context) / "visual_reviews")

    def _asset_validation_reports_dir(self, context: bpy.types.Context) -> Path:
        root = self._storage_root(context) / "asset_validation_reports"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _save_asset_validation_report(self, context: bpy.types.Context, report: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
        import json

        payload = dict(report or {})
        report_id = str(payload.get("report_id", "") or f"asset-validation-{int(time.time())}")
        payload["report_id"] = report_id
        if run_id:
            payload["visual_review_run_id"] = run_id
        path = self._asset_validation_reports_dir(context) / f"{report_id}.json"
        payload["path"] = str(path)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        wm = getattr(context, "window_manager", None)
        if wm is not None:
            if hasattr(wm, "codex_blender_asset_validation_latest_report_id"):
                wm.codex_blender_asset_validation_latest_report_id = report_id
            if hasattr(wm, "codex_blender_asset_validation_latest_score"):
                wm.codex_blender_asset_validation_latest_score = float(payload.get("asset_score", 0.0) or 0.0)
            if hasattr(wm, "codex_blender_asset_validation_latest_summary"):
                wm.codex_blender_asset_validation_latest_summary = compact_text(str(payload.get("validation_summary", "")), 180)
            if hasattr(wm, "codex_blender_asset_validation_latest_issue_count"):
                wm.codex_blender_asset_validation_latest_issue_count = int(payload.get("issue_count", 0) or 0)
            if hasattr(wm, "codex_blender_asset_validation_latest_critical_count"):
                wm.codex_blender_asset_validation_latest_critical_count = int(payload.get("critical_count", 0) or 0)
        return payload

    def _latest_asset_validation_report(self, context: bpy.types.Context) -> dict[str, Any]:
        reports = self.list_asset_validation_reports(context, limit=1)
        return reports[0] if reports else {}

    def _validation_records_from_report(self, validation: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for index, item in enumerate(list(validation.get("objects", []) or [])):
            if not isinstance(item, dict):
                continue
            aabb = dict(item.get("aabb", {}) or {})
            center = list(aabb.get("center", []))
            size = list(aabb.get("size", []))
            if len(center) != 3:
                center = [0.0, 0.0, 0.0]
            if len(size) != 3:
                size = [1.0, 1.0, 1.0]
            records.append(
                {
                    "name": str(item.get("name", f"object_{index}") or f"object_{index}"),
                    "type": str(item.get("type", "MESH") or "MESH"),
                    "location": [float(value) for value in center],
                    "dimensions": [float(value) for value in size],
                    "material_names": list(item.get("materials", item.get("material_names", [])) or []),
                    "collections": list(item.get("collections", []) or []),
                    "vertex_count": int(item.get("vertex_count", 0) or 0),
                    "face_count": int(item.get("face_count", 0) or 0),
                }
            )
        return records

    def _build_intent_manifest_payload(
        self,
        *,
        run: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        records = self._validation_records_from_report(validation)
        prompt = str(run.get("original_prompt", "") or run.get("current_prompt", "") or "")
        raw_manifest = dict(run.get("intent_manifest", {}) or {})
        if not raw_manifest:
            inferred_objects = [
                {
                    "name": record.get("name", f"object_{index}"),
                    "role": "support" if "support" in str(record.get("type", "")).lower() else "unknown",
                    "source": "inferred",
                }
                for index, record in enumerate(records)
            ]
            raw_manifest = {
                "asset_name": prompt[:80] or "Visual Review Asset",
                "prompt": prompt,
                "source": "inferred",
                "objects": inferred_objects,
                "allowed_intersections": run.get("allowed_intersections", []) or [],
                "forbidden_intersections": run.get("forbidden_intersections", "all_other_pairs"),
                "required_contacts": run.get("required_contacts", []) or [],
                "clearance_targets": run.get("clearance_targets", []) or [],
                "repair_policy": run.get("repair_policy", {}) or {
                    "allow_safe_transforms": True,
                    "allow_local_cleanup": False,
                    "allow_destructive_mesh_ops": False,
                    "destructive_requires_approval": True,
                },
            }
        manifest = normalize_asset_intent_manifest(raw_manifest, records=records, prompt=prompt)
        manifest["constraint_graph"] = build_constraint_graph(records, manifest)
        return manifest

    def _web_algorithm_ledger(
        self,
        validation: dict[str, Any],
        latest_pass: dict[str, Any],
        capture: dict[str, Any],
        run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        summary = dict(validation.get("snapshot_summary", {}) or {})
        hard_gates = dict(validation.get("hard_gates", {}) or {})
        issue_count = int(validation.get("issue_count", 0) or 0)
        critical_count = int(validation.get("critical_count", 0) or 0)
        screenshot_count = len(_web_screenshots(run, latest_pass, capture))
        validation_issues = list(validation.get("issues", []) or latest_pass.get("validation_issues", []) or capture.get("validation_issues", []) or [])
        issue_types: dict[str, int] = {}
        for item in validation_issues:
            if isinstance(item, dict):
                issue_type = str(item.get("type", "unknown"))
                issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
        existing_ledger = [dict(item) for item in validation.get("algorithm_ledger", []) or [] if isinstance(item, dict)]
        rows = [
            {
                "id": "evaluated_geometry",
                "label": "Evaluated geometry snapshot",
                "status": "done" if summary.get("evaluated_mesh_count", 0) else "waiting",
                "duration_ms": None,
                "inputs": {
                    "objects": int(validation.get("object_count", 0) or 0),
                    "meshes": int(summary.get("evaluated_mesh_count", 0) or 0),
                    "triangles": int(summary.get("triangle_count", 0) or 0),
                },
                "thresholds": {"target_score": float(run.get("target_score", DEFAULT_TARGET_SCORE) or DEFAULT_TARGET_SCORE)},
                "objects": [item.get("name", "") for item in validation.get("objects", []) or [] if isinstance(item, dict)],
                "issue_count": issue_count,
                "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                "error": "",
            },
            {
                "id": "bvh_broadphase",
                "label": "AABB sweep-and-prune broadphase",
                "status": "done" if int(validation.get("object_count", 0) or 0) >= 2 else "waiting",
                "duration_ms": None,
                "inputs": {"clearance": validation.get("metric_vector", {}).get("validation_clearance", 0.0)},
                "thresholds": {"candidate_pairs": len(validation_issues)},
                "objects": [],
                "issue_count": issue_count,
                "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                "error": "",
            },
            {
                "id": "contact_support",
                "label": "Support/contact / floating analysis",
                "status": "blocked" if any(str(issue.get("type", "")) in {"floating_part", "required_contact_failure"} for issue in validation_issues if isinstance(issue, dict)) else "done",
                "duration_ms": None,
                "inputs": {"contact_tolerance": validation.get("metric_vector", {}).get("contact_tolerance", 0.0)},
                "thresholds": {"minimum_support": True},
                "objects": [],
                "issue_count": sum(1 for issue in validation_issues if isinstance(issue, dict) and str(issue.get("type", "")) in {"floating_part", "required_contact_failure"}),
                "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                "error": "",
            },
            {
                "id": "containment_overlap",
                "label": "Containment / overlap / z-fighting analysis",
                "status": "blocked" if any(str(issue.get("type", "")) in {"interpenetration", "excessive_overlap", "containment_risk", "z_fighting_risk", "castle_battlement_intersection", "castle_zone_violation"} for issue in validation_issues if isinstance(issue, dict)) else "done",
                "duration_ms": None,
                "inputs": {"issue_types": sorted(issue_types)},
                "thresholds": dict(hard_gates),
                "objects": [],
                "issue_count": sum(issue_types.values()),
                "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                "error": "",
            },
            {
                "id": "view_planning",
                "label": "PCA/Fibonacci/Halton view planning",
                "status": "done" if screenshot_count else "waiting",
                "duration_ms": None,
                "inputs": {"candidate_views": int(run.get("geometry_settings", {}).get("candidate_view_count", DEFAULT_CANDIDATE_VIEW_COUNT) or DEFAULT_CANDIDATE_VIEW_COUNT)},
                "thresholds": {"selected_captures": int(run.get("geometry_settings", {}).get("selected_capture_count", DEFAULT_SELECTED_CAPTURE_COUNT) or DEFAULT_SELECTED_CAPTURE_COUNT)},
                "objects": [],
                "issue_count": 0,
                "evidence_refs": [str(item.get("path", "")) for item in _web_screenshots(run, latest_pass, capture)[:8] if str(item.get("path", ""))],
                "error": "",
            },
            {
                "id": "critic_parse",
                "label": "Critic JSON parse and patch planning",
                "status": "done" if latest_pass.get("critic_response") or latest_pass.get("critic_raw") else "waiting",
                "duration_ms": None,
                "inputs": {"critic_score": float(latest_pass.get("critic_score", latest_pass.get("score", 0.0)) or 0.0)},
                "thresholds": {"target_score": float(run.get("target_score", DEFAULT_TARGET_SCORE) or DEFAULT_TARGET_SCORE)},
                "objects": [],
                "issue_count": len(list(latest_pass.get("issues", []) or [])),
                "evidence_refs": [str(latest_pass.get("validation_report_id", ""))] if latest_pass.get("validation_report_id") else [],
                "error": "",
            },
            {
                "id": "hybrid_score",
                "label": "Hybrid score and hard-gate evaluation",
                "status": "done" if validation else "waiting",
                "duration_ms": None,
                "inputs": {
                    "geometry_score": float(latest_pass.get("deterministic_score", 0.0) or 0.0),
                    "critic_score": float(latest_pass.get("critic_score", latest_pass.get("score", 0.0)) or 0.0),
                },
                "thresholds": {"target_score": float(run.get("target_score", DEFAULT_TARGET_SCORE) or DEFAULT_TARGET_SCORE)},
                "objects": [],
                "issue_count": issue_count,
                "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                "error": "",
            },
        ]
        for issue_type, count in sorted(issue_types.items()):
            rows.append(
                {
                    "id": f"issue_{issue_type}",
                    "label": issue_type.replace("_", " "),
                    "status": "blocked" if issue_type in {"interpenetration", "containment_risk", "castle_battlement_intersection", "castle_zone_violation"} else "warn",
                    "duration_ms": None,
                    "inputs": {"count": count},
                    "thresholds": {},
                    "objects": [],
                    "issue_count": count,
                    "evidence_refs": [str(validation.get("report_id", ""))] if validation.get("report_id") else [],
                    "error": "",
                }
            )
        if existing_ledger:
            seen = {str(item.get("id", "")) for item in existing_ledger}
            rows = existing_ledger + [item for item in rows if str(item.get("id", "")) not in seen]
        return rows

    def _web_repair_plan(
        self,
        intent_manifest: dict[str, Any],
        validation: dict[str, Any],
        latest_pass: dict[str, Any],
        capture: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(validation.get("repair_plan"), dict) and validation.get("repair_plan"):
            return dict(validation.get("repair_plan") or {})
        issues = list(validation.get("top_issues", []) or validation.get("issues", []) or latest_pass.get("issues", []) or capture.get("validation_issues", []) or [])
        safe_actions: list[dict[str, Any]] = []
        blocked_operations: list[dict[str, Any]] = []
        for issue in issues[:10]:
            if not isinstance(issue, dict):
                continue
            issue_type = str(issue.get("type", ""))
            targets = list(issue.get("objects", []) or [])
            target = str(issue.get("target", targets[0] if targets else "scene"))
            action: dict[str, Any] | None = None
            blocked_reason = ""
            if issue_type in {"floating_part", "required_contact_failure"}:
                action = {"target": target, "op": "snap_to_support", "reason": "Restore contact or grounding without editing unrelated geometry."}
            elif issue_type in {"interpenetration", "excessive_overlap", "castle_battlement_intersection"}:
                action = {"target": target, "op": "separate_or_trim", "reason": "Remove intersection while preserving local shape."}
                blocked_reason = "Destructive mesh operations remain gated."
            elif issue_type in {"containment_risk"}:
                action = {"target": target, "op": "unbury_or_expose", "reason": "Move the hidden part back into view or onto its intended contact."}
            elif issue_type in {"z_fighting_risk", "duplicate_surface_risk"}:
                action = {"target": target, "op": "offset_or_merge_duplicates", "reason": "Separate near-coplanar surfaces or delete duplicate copies."}
                blocked_reason = "Merge/delete operations require policy approval."
            elif issue_type in {"scale_outlier", "tiny_detail_missed"}:
                action = {"target": target, "op": "adjust_scale_or_capture_detail", "reason": "Bring the part into reviewable size range."}
            elif issue_type in {"inconsistent_material_slots"}:
                action = {"target": target, "op": "normalize_material_slots", "reason": "Make slots consistent before further review."}
            if action:
                safe_actions.append(
                    {
                        "issue_id": str(issue.get("issue_id", issue.get("defect_id", ""))),
                        "issue_type": issue_type,
                        "severity": str(issue.get("severity", "low")),
                        "action": action,
                        "acceptance_tests": list(issue.get("acceptance_tests", []) or []),
                    }
                )
                if blocked_reason:
                    blocked_operations.append(
                        {
                            "issue_id": str(issue.get("issue_id", issue.get("defect_id", ""))),
                            "operation": action["op"],
                            "reason": blocked_reason,
                        }
                    )
        policy = dict(intent_manifest.get("repair_policy", {}) or {})
        return {
            "status": "proposed" if safe_actions else "idle",
            "policy": policy,
            "safe_actions": safe_actions,
            "blocked_operations": blocked_operations,
            "validation_report_id": str(validation.get("report_id", "")),
            "validation_score": float(validation.get("asset_score", 0.0) or 0.0),
            "top_issue_count": len(issues),
            "notes": "Safe transform repairs first; destructive geometry edits stay policy-gated.",
        }

    def _web_overlays(
        self,
        intent_manifest: dict[str, Any],
        validation: dict[str, Any],
        latest_pass: dict[str, Any],
        capture: dict[str, Any],
        screenshots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        issue_markers = []
        for issue in list(validation.get("issues", []) or [])[:24]:
            if not isinstance(issue, dict):
                continue
            issue_markers.append(
                {
                    "issue_id": str(issue.get("issue_id", issue.get("defect_id", ""))),
                    "type": str(issue.get("type", "")),
                    "severity": str(issue.get("severity", "low")),
                    "objects": list(issue.get("objects", []) or []),
                    "local_bbox": issue.get("local_bbox"),
                    "label": str(issue.get("suggested_fix", issue.get("remediation_hint", ""))),
                }
            )
        return {
            "visible": bool(issue_markers or screenshots),
            "issue_markers": issue_markers,
            "support_footprints": [
                {
                    "object": str(item.get("name", "")),
                    "role": str(item.get("role", "")),
                    "source": str(item.get("source", "inferred")),
                }
                for item in list(intent_manifest.get("objects", []) or [])[:24]
                if isinstance(item, dict)
            ],
            "screenshot_refs": [
                {
                    "path": str(item.get("path", "")),
                    "view_id": str(item.get("view_id", "")),
                    "kind": str(item.get("kind", "")),
                    "pass_index": int(item.get("pass_index", 0) or 0),
                }
                for item in screenshots[:24]
            ],
            "view_guides": list(capture.get("optimization_viewpoints", []) or [])[:16] + list(capture.get("audit_viewpoints", []) or [])[:16],
            "constraint_edges": len(list(intent_manifest.get("constraint_graph", {}).get("edges", []) or [])),
            "constraint_nodes": len(list(intent_manifest.get("constraint_graph", {}).get("nodes", []) or [])),
        }

    def _web_runs_payload(self, run: dict[str, Any], recent_runs: list[dict[str, Any]]) -> dict[str, Any]:
        index: dict[str, Any] = {}
        active_run_id = str(run.get("run_id", "") or "")
        if active_run_id:
            index[active_run_id] = run
        for item in recent_runs:
            if isinstance(item, dict):
                run_id = str(item.get("run_id", "") or "")
                if run_id:
                    index.setdefault(run_id, item)
        return {
            "active_run_id": active_run_id,
            "active": run,
            "recent": recent_runs,
            "index": index,
        }

    def _web_observability_payload(
        self,
        context: bpy.types.Context,
        run: dict[str, Any],
        latest_pass: dict[str, Any],
        capture: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        runs = self._web_runs_payload(run, self.list_visual_review_runs(context, limit=8))
        intent_manifest = self._build_intent_manifest_payload(run=run, validation=validation)
        screenshots = _web_screenshots(run, latest_pass, capture)
        algorithms = self._web_algorithm_ledger(validation, latest_pass, capture, run)
        repair_plan = self._web_repair_plan(intent_manifest, validation, latest_pass, capture)
        overlays = self._web_overlays(intent_manifest, validation, latest_pass, capture, screenshots)
        return {
            "runs": runs,
            "algorithms": algorithms,
            "intent_manifest": intent_manifest,
            "constraints": intent_manifest.get("constraint_graph", {}),
            "repair_plan": repair_plan,
            "overlays": overlays,
            "screenshots": screenshots,
            "timeline": _web_timeline(run),
        }

    def _auto_visual_review_enabled(self, context: bpy.types.Context) -> bool:
        wm = getattr(context, "window_manager", None)
        prefs = self._preferences(context)
        enabled = bool(getattr(wm, "codex_blender_visual_review_enabled", getattr(prefs, "visual_review_enabled", True)))
        auto_enabled = bool(
            getattr(
                wm,
                "codex_blender_visual_review_auto_after_scene_change",
                getattr(prefs, "visual_review_auto_after_scene_change", True),
            )
        )
        return enabled and auto_enabled

    def _visual_review_console_banner(self, stage: str, detail: str = "") -> None:
        line = "=" * 78
        message = compact_text(str(detail or ""), 360)
        print(f"\n{line}\nCODEX AUTO REVIEW: {stage.upper()}\n{message}\n{line}\n")
        try:
            append_activity_event(f"CODEX AUTO REVIEW: {stage.upper()}", {"detail": message})
        except Exception:
            pass

    def _visual_review_geometry_settings(self, context: bpy.types.Context) -> dict[str, Any]:
        wm = getattr(context, "window_manager", None)
        prefs = self._preferences(context)

        def value(name: str, default: Any) -> Any:
            wm_name = f"codex_blender_visual_review_{name}"
            if wm is not None and hasattr(wm, wm_name):
                return getattr(wm, wm_name)
            pref_name = f"visual_review_{name}"
            if hasattr(prefs, pref_name):
                return getattr(prefs, pref_name)
            return default

        return {
            "automatic_geometry_review": bool(value("automatic_geometry_review", DEFAULT_GEOMETRY_REVIEW_ENABLED)),
            "candidate_view_count": int(value("candidate_view_count", DEFAULT_CANDIDATE_VIEW_COUNT)),
            "selected_capture_count": int(value("selected_capture_count", DEFAULT_SELECTED_CAPTURE_COUNT)),
            "audit_view_count": int(value("audit_view_count", DEFAULT_AUDIT_VIEW_COUNT)),
            "mesh_samples_per_object": int(value("mesh_samples_per_object", DEFAULT_MESH_SAMPLES_PER_OBJECT)),
            "minimum_coverage_score": float(value("minimum_coverage_score", DEFAULT_MINIMUM_COVERAGE_SCORE)),
            "geometry_score_weight": float(value("geometry_score_weight", DEFAULT_GEOMETRY_SCORE_WEIGHT)),
            "critic_score_weight": float(value("critic_score_weight", DEFAULT_CRITIC_SCORE_WEIGHT)),
            "camera_fit_margin": float(value("camera_fit_margin", DEFAULT_CAMERA_FIT_MARGIN)),
            "view_angular_separation_degrees": float(value("view_angular_separation_degrees", DEFAULT_VIEW_ANGULAR_SEPARATION_DEGREES)),
            "audit_angular_separation_degrees": float(value("audit_angular_separation_degrees", DEFAULT_AUDIT_ANGULAR_SEPARATION_DEGREES)),
            "target_score": float(value("target_score", DEFAULT_TARGET_SCORE)),
        }

    def _visual_review_scope_summary(self, context: bpy.types.Context) -> str:
        records = self._visual_review_object_records(context, selected_only=True)
        if records:
            return f"{len(records)} selected object(s): " + ", ".join(item.get("name", "") for item in records[:8])
        records = self._visual_review_object_records(context, selected_only=False)
        return f"{len(records)} visible scene object(s)"

    def _visual_review_object_records(self, context: bpy.types.Context, *, selected_only: bool = False) -> list[dict[str, Any]]:
        source = list(getattr(context, "selected_objects", []) or []) if selected_only else []
        if not source:
            scene = getattr(context, "scene", None)
            source = [obj for obj in getattr(scene, "objects", []) if getattr(obj, "type", "") not in {"CAMERA", "LIGHT"} and not obj.hide_get()]
        records: list[dict[str, Any]] = []
        for obj in source:
            bounds = []
            try:
                bounds = [[float(value) for value in (obj.matrix_world @ mathutils.Vector(corner))] for corner in obj.bound_box]
            except Exception:
                bounds = []
            material_names = []
            material_slot_count = 0
            try:
                material_slot_count = len(getattr(obj, "material_slots", []) or [])
                material_names = [
                    slot.material.name
                    for slot in getattr(obj, "material_slots", []) or []
                    if getattr(slot, "material", None) is not None
                ]
            except Exception:
                material_names = []
            collections = []
            try:
                collections = [collection.name for collection in getattr(obj, "users_collection", []) or []]
            except Exception:
                collections = []
            vertex_count = 0
            face_count = 0
            try:
                data = getattr(obj, "data", None)
                vertex_count = len(getattr(data, "vertices", []) or [])
                face_count = len(getattr(data, "polygons", []) or [])
            except Exception:
                vertex_count = 0
                face_count = 0
            records.append(
                {
                    "name": getattr(obj, "name", ""),
                    "type": getattr(obj, "type", ""),
                    "location": [float(value) for value in getattr(obj, "location", (0.0, 0.0, 0.0))],
                    "dimensions": [float(value) for value in getattr(obj, "dimensions", (1.0, 1.0, 1.0))],
                    "bounds": bounds,
                    "material_names": material_names,
                    "material_slot_count": material_slot_count,
                    "collections": collections,
                    "vertex_count": vertex_count,
                    "face_count": face_count,
                }
            )
        return records

    def _scene_snapshot_payload(self, context: bpy.types.Context, validation: dict[str, Any] | None = None) -> dict[str, Any]:
        validation = validation or {}
        scene = getattr(context, "scene", None)
        selected = list(getattr(context, "selected_objects", []) or [])
        visible_records = self._visual_review_object_records(context, selected_only=False)
        selected_names = [str(getattr(obj, "name", "")) for obj in selected if str(getattr(obj, "name", ""))]
        current_names = {str(item.get("name", "")) for item in visible_records if str(item.get("name", ""))}
        added = sorted(current_names - self._last_scene_object_names)
        removed = sorted(self._last_scene_object_names - current_names)
        self._last_scene_object_names = set(current_names)
        material_names: set[str] = set()
        for record in visible_records:
            for material in record.get("material_names", []) or []:
                if str(material):
                    material_names.add(str(material))
        top_issues = list(validation.get("top_issues", []) or validation.get("issues", []) or [])[:8]
        return {
            "scene_name": str(getattr(scene, "name", "Scene") if scene is not None else "Scene"),
            "captured_at": self._event_timestamp(),
            "visible_object_count": len(visible_records),
            "selected_object_count": len(selected_names),
            "mesh_object_count": sum(1 for item in visible_records if str(item.get("type", "")) == "MESH"),
            "material_count": len(material_names),
            "selected_objects": selected_names,
            "objects": visible_records[:80],
            "materials": sorted(material_names)[:80],
            "changes": {
                "added": added[:30],
                "removed": removed[:30],
                "changed": [],
            },
            "latest_validation_score": float(validation.get("asset_score", 0.0) or 0.0),
            "latest_validation_report_id": str(validation.get("report_id", "")),
            "top_issues": top_issues,
        }

    def _tool_json_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        import json

        for item in result.get("contentItems", []) or []:
            text = str(item.get("text", ""))
            if not text.strip():
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _latest_assistant_text(self, snapshot) -> str:
        for message in reversed(getattr(snapshot, "messages", []) or []):
            if getattr(message, "role", "") == "assistant":
                return str(getattr(message, "text", "") or "")
        return ""

    def _dispatch_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._visual_review_blocks_tool(tool_name):
            return {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": (
                            f"{tool_name} is blocked during the visual-review critic phase. "
                            "Critic turns may inspect and plan, but cannot mutate the Blender scene."
                        ),
                    }
                ],
            }
        if threading.current_thread() is threading.main_thread():
            return self._execute_dynamic_tool(bpy.context, tool_name, arguments)
        return self.dispatcher.submit(lambda: self._execute_dynamic_tool(bpy.context, tool_name, arguments)).wait()

    def _sync_window_manager(self, window_manager: bpy.types.WindowManager, force: bool = False) -> None:
        snapshot = self.service.snapshot()
        dashboard_signature = self._dashboard_signature(bpy.context)
        if snapshot.version == self._last_synced_version and dashboard_signature == self._last_dashboard_signature and not force:
            return

        window_manager.codex_blender_dashboard_busy = snapshot.turn_in_progress or self.dispatcher.pending_count > 0
        window_manager.codex_blender_dashboard_progress = 0.25 if snapshot.turn_in_progress else 0.0
        window_manager.codex_blender_connection = snapshot.status_text
        window_manager.codex_blender_account = snapshot.account.email if snapshot.account else ""
        window_manager.codex_blender_plan = snapshot.account.plan_type if snapshot.account else ""
        window_manager.codex_blender_thread = short_thread_id(snapshot.active_thread_id)
        window_manager.codex_blender_pending = snapshot.turn_in_progress
        window_manager.codex_blender_activity = snapshot.activity_text
        window_manager.codex_blender_error = snapshot.last_error
        if hasattr(window_manager, "codex_blender_error_title"):
            window_manager.codex_blender_error_title = getattr(snapshot, "last_error_title", "")
        if hasattr(window_manager, "codex_blender_error_severity"):
            window_manager.codex_blender_error_severity = getattr(snapshot, "last_error_severity", "")
        if hasattr(window_manager, "codex_blender_error_recovery"):
            window_manager.codex_blender_error_recovery = getattr(snapshot, "last_error_recovery", "")
        if hasattr(window_manager, "codex_blender_error_raw"):
            window_manager.codex_blender_error_raw = getattr(snapshot, "last_error_raw", "")
        if hasattr(window_manager, "codex_blender_error_retry"):
            window_manager.codex_blender_error_retry = getattr(snapshot, "last_error_retry", "")
        if hasattr(window_manager, "codex_blender_stream_recovering"):
            window_manager.codex_blender_stream_recovering = bool(getattr(snapshot, "stream_recovering", False))

        valid_model_ids = [model.model_id for model in snapshot.models]
        if valid_model_ids:
            current_model = getattr(window_manager, "codex_blender_model", "")
            if current_model not in valid_model_ids:
                default_model = preferred_model_id(snapshot.models)
                window_manager.codex_blender_model = default_model
        current_effort = getattr(window_manager, "codex_blender_effort", "")
        resolved_effort = valid_reasoning_effort(current_effort)
        if resolved_effort != current_effort:
            window_manager.codex_blender_effort = resolved_effort

        if not getattr(window_manager, "codex_blender_redraw_paused", False):
            window_manager.codex_blender_messages.clear()
            for message in snapshot.messages[-MAX_VISIBLE_MESSAGES:]:
                entry = window_manager.codex_blender_messages.add()
                entry.role = message.role
                entry.phase = message.phase
                entry.status = message.status
                entry.text = _preview(message.text)

        self._last_synced_version = snapshot.version
        self._last_dashboard_signature = dashboard_signature
        self._persist_thread_snapshot(window_manager, snapshot)
        if not getattr(window_manager, "codex_blender_redraw_paused", False) or force:
            self.refresh_chat_transcript(bpy.context)
        else:
            ensure_chat_text_blocks()
            write_activity_log(snapshot)
        self._sync_dashboard_items(window_manager)
        self._sync_toolbox_items(window_manager)
        self._sync_asset_items(window_manager)
        self._sync_studio_items(window_manager)
        self._update_web_console_cache(bpy.context)

    def _execute_dynamic_tool(self, context: bpy.types.Context, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(arguments or {})
        policy = classify_tool(tool_name)
        preview_workflow = tool_name == "run_workflow_graph" and bool(arguments.get("preview_only", True))
        action_id = ""
        if policy.requires_action and not preview_workflow:
            action_id = self._authorize_tool_action(context, tool_name, arguments, policy)
            arguments["action_id"] = action_id
            self._record_action_step(context, action_id, _tool_step_record(tool_name, "commit", "running", arguments))
        started = time.perf_counter()
        try:
            result = self._execute_dynamic_tool_body(context, tool_name, arguments)
        except Exception as exc:
            if action_id:
                self._record_action_step(context, action_id, _tool_step_record(tool_name, "commit", "failed", arguments, started=started, error=str(exc)))
                if action_id in self._auto_receipt_actions:
                    self.update_action_status(
                        context,
                        action_id,
                        "failed",
                        result_summary=f"{tool_name} failed: {compact_text(str(exc), 180)}",
                        recovery="Use Undo if anything changed, adjust the prompt or selection, then retry.",
                    )
                    self._auto_receipt_actions.discard(action_id)
            raise
        if action_id:
            self._record_action_step(context, action_id, _tool_step_record(tool_name, "commit", "completed", arguments, started=started, result=result))
            if action_id in self._auto_receipt_actions:
                self.update_action_status(
                    context,
                    action_id,
                    "completed",
                    result_summary=f"{tool_name} completed in Game Creator fast mode.",
                    recovery="Use Blender Undo for the latest local change, or open details to inspect the receipt.",
                )
                self._auto_receipt_actions.discard(action_id)
        return result

    def _resolve_model_choice(self, context: bpy.types.Context, requested_model: str) -> str:
        snapshot = self.service.snapshot()
        valid_model_ids = [model.model_id for model in snapshot.models]
        requested = (requested_model or "").strip()
        if requested and requested != "__none__" and requested in valid_model_ids:
            return requested
        if not valid_model_ids:
            return "" if requested == "__none__" else requested
        selected = preferred_model_id(snapshot.models)
        if selected:
            try:
                context.window_manager.codex_blender_model = selected
            except Exception:
                pass
        return selected

    def _resolve_effort_choice(self, context: bpy.types.Context, requested_effort: str) -> str:
        resolved = valid_reasoning_effort(requested_effort) or DEFAULT_REASONING_EFFORT
        try:
            context.window_manager.codex_blender_effort = resolved
        except Exception:
            pass
        return resolved

    def _execute_dynamic_tool_body(self, context: bpy.types.Context, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name in {"list_dashboard_context", "list_studio_context"}:
            return _tool_success(_json_text(self._dashboard_context(context)))

        if tool_name == "list_asset_context":
            return _tool_success(_json_text(self.list_asset_context(context)))

        if tool_name == "list_ai_scope":
            return _tool_success(_json_text(self._ai_scope_payload(context)))

        if tool_name == "list_active_context_chips":
            return _tool_success(_json_text(self._ai_scope_payload(context).get("enabled_chips", [])))

        if tool_name == "list_context_chips":
            return _tool_success(_json_text(self._build_context_chips(context)))

        if tool_name == "classify_user_intent":
            return _tool_success(_json_text(self.classify_prompt(context, str(arguments.get("prompt", "")), str(arguments.get("tool_name", "")))))

        if tool_name == "get_game_creator_context":
            payload = creator_context_payload(context)
            payload["quick_prompt_categories"] = [prompt.category for prompt in list_quick_prompts()]
            return _tool_success(_json_text(payload))

        if tool_name == "get_visual_review_context":
            return _tool_success(_json_text(self.visual_review_context(context)))

        if tool_name == "get_asset_intent_manifest":
            return _tool_success(_json_text(self.get_asset_intent_manifest(context, run_id=str(arguments.get("run_id", "")))))

        if tool_name == "set_asset_intent_manifest":
            manifest = arguments.get("manifest", {}) if isinstance(arguments.get("manifest"), dict) else {}
            return _tool_success(_json_text(self.set_asset_intent_manifest(context, manifest, run_id=str(arguments.get("run_id", "")))))

        if tool_name == "get_asset_constraint_graph":
            return _tool_success(
                _json_text(
                    self.get_asset_constraint_graph(
                        context,
                        run_id=str(arguments.get("run_id", "")),
                    )
                )
            )

        if tool_name == "get_asset_repair_plan":
            return _tool_success(
                _json_text(
                    self.get_asset_repair_plan(
                        context,
                        run_id=str(arguments.get("run_id", "")),
                    )
                )
            )

        if tool_name == "apply_safe_asset_repair":
            repair_plan = arguments.get("repair_plan", {}) if isinstance(arguments.get("repair_plan"), dict) else {}
            payload = self.apply_safe_asset_repair(context, repair_plan, run_id=str(arguments.get("run_id", "")))
            return _tool_success(_json_text(payload))

        if tool_name == "get_visual_geometry_context":
            records = self._visual_review_object_records(context, selected_only=bool(arguments.get("selected_only", False)))
            payload = build_geometry_digest(records, settings=self._visual_review_geometry_settings(context))
            latest_validation = self._latest_asset_validation_report(context)
            return _tool_success(_json_text({"objects": records, "geometry": payload, "latest_validation_report": latest_validation}))

        if tool_name == "analyze_visual_geometry":
            records = self._visual_review_object_records(context, selected_only=bool(arguments.get("selected_only", False)))
            return _tool_success(_json_text(build_geometry_digest(records, settings=self._visual_review_geometry_settings(context))))

        if tool_name == "validate_gpt_asset":
            selected_only = bool(arguments.get("selected_only", False))
            settings = self._visual_review_geometry_settings(context)
            if isinstance(arguments.get("settings"), dict):
                settings.update(arguments.get("settings") or {})
            manifest = self.get_asset_intent_manifest(context, run_id=str(arguments.get("run_id", "")))
            report = validate_scene_asset(context, selected_only=selected_only, settings=settings, intent_manifest=manifest)
            report = self._save_asset_validation_report(context, report, run_id=str(arguments.get("run_id", "")))
            return _tool_success(_json_text(report))

        if tool_name == "get_asset_validation_report":
            return _tool_success(_json_text(self.get_asset_validation_report(context, str(arguments.get("report_id", "")))))

        if tool_name == "list_asset_validation_reports":
            return _tool_success(_json_text(self.list_asset_validation_reports(context, limit=int(arguments.get("limit", 20) or 20))))

        if tool_name == "plan_geometry_review_viewpoints":
            selected_only = bool(arguments.get("selected_only", False))
            records = self._visual_review_object_records(context, selected_only=selected_only)
            settings = self._visual_review_geometry_settings(context)
            if isinstance(arguments.get("settings"), dict):
                settings.update(arguments.get("settings") or {})
            return _tool_success(_json_text(plan_geometry_review_viewpoints(records, settings=settings)))

        if tool_name == "get_visual_review_metrics":
            run_id = str(arguments.get("run_id", "")) or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
            manifest = self._visual_review_store(context).load_run(run_id) if run_id else {}
            latest = list(manifest.get("passes", []) or [])[-1] if manifest.get("passes") else {}
            return _tool_success(
                _json_text(
                    {
                        "run_id": run_id,
                        "current_score": manifest.get("current_score", 0.0),
                        "latest_metric_vector": latest.get("metric_vector", {}),
                        "latest_hard_gates": latest.get("hard_gates", {}),
                        "latest_defects": latest.get("defects", []),
                        "latest_view_scores": latest.get("view_scores", []),
                    }
                )
            )

        if tool_name == "list_visual_review_runs":
            limit = int(arguments.get("limit", 20) or 20)
            return _tool_success(_json_text(self.list_visual_review_runs(context, limit=limit)))

        if tool_name == "get_visual_review_run":
            return _tool_success(_json_text(self.get_visual_review_run(context, str(arguments.get("run_id", "")))))

        if tool_name == "plan_visual_review_viewpoints":
            selected_only = bool(arguments.get("selected_only", False))
            max_detail_views = int(arguments.get("max_detail_views", 4) or 4)
            records = self._visual_review_object_records(context, selected_only=selected_only)
            settings = self._visual_review_geometry_settings(context)
            if isinstance(arguments.get("settings"), dict):
                settings.update(arguments.get("settings") or {})
            geometry_plan = plan_geometry_review_viewpoints(records, settings=settings)
            legacy_views = plan_viewpoints(records, max_detail_views=max_detail_views)
            return _tool_success(_json_text({"objects": records, "viewpoints": geometry_plan.get("selected_viewpoints") or legacy_views, "legacy_viewpoints": legacy_views, **geometry_plan}))

        if tool_name == "record_visual_review_iteration":
            run_id = str(arguments.get("run_id", "")) or getattr(context.window_manager, "codex_blender_visual_review_active_run_id", "")
            if not run_id:
                raise RuntimeError("run_id is required.")
            critique = dict(arguments.get("critique") or {}) if isinstance(arguments.get("critique"), dict) else {}
            manifest = self._visual_review_store(context).append_pass(
                run_id,
                {
                    "iteration": int(arguments.get("iteration", 0) or 0),
                    "screenshots": list(arguments.get("screenshots") or []),
                    "critique": arguments.get("critique", {}),
                    "score": float(arguments.get("score", critique.get("score", 0.0)) or 0.0),
                    "next_prompt": str(arguments.get("next_prompt", critique.get("next_prompt", ""))),
                    "summary": str(arguments.get("summary", critique.get("summary", ""))),
                    "stop_reason": str(arguments.get("stop_reason", "")),
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
            self._sync_visual_review_window_manager(context, manifest)
            return _tool_success(_json_text(manifest))

        if tool_name == "list_quick_prompts":
            prompts = [quick_prompt_payload(prompt) for prompt in list_quick_prompts(str(arguments.get("category", "")))]
            return _tool_success(_json_text(prompts))

        if tool_name == "run_quick_prompt":
            prompt_id = str(arguments.get("prompt_id", ""))
            payload = creator_context_payload(context)
            prompt = get_quick_prompt(prompt_id)
            rendered = render_quick_prompt(prompt_id, payload)
            return _tool_success(_json_text({**quick_prompt_payload(prompt), "rendered_prompt": rendered, "context": payload}))

        if tool_name == "create_workflow_from_intent":
            return _tool_success(
                _json_text(
                    self.create_workflow_from_intent(
                        context,
                        prompt=str(arguments.get("prompt", "")),
                        graph_name=str(arguments.get("graph_name", "Codex AI Workflow")),
                    )
                )
            )

        if tool_name == "explain_workflow_graph":
            return _tool_success(_json_text(self.explain_workflow_graph(context, str(arguments.get("graph_name", "Codex AI Workflow")))))

        if tool_name == "simplify_workflow_graph":
            detail = self.explain_workflow_graph(context, str(arguments.get("graph_name", "Codex AI Workflow")))
            detail["simplification_plan"] = [
                "Keep chat as the primary user surface.",
                "Keep only nodes that capture context, ask the assistant, preview a result, or publish an asset.",
                "Move raw validation, card, and package details behind advanced controls.",
            ]
            return _tool_success(_json_text(detail))

        if tool_name == "create_game_asset_plan":
            payload = creator_context_payload(context)
            asset_type = str(arguments.get("asset_type", "") or "prop")
            target_engine = str(arguments.get("target_engine", "") or payload.get("target_engine", "generic"))
            plan = {
                "asset_type": asset_type,
                "target_engine": target_engine,
                "selection": payload.get("selected_objects", []),
                "steps": [
                    "Check scale, transforms, origin, and naming.",
                    "Create or clean realtime-friendly materials.",
                    "Create variants only by duplicating or using reversible edits.",
                    "Draft asset metadata and export-readiness notes.",
                    "Record a receipt or high-risk approval card depending on the chosen action.",
                ],
            }
            return _tool_success(_json_text(plan))

        if tool_name == "apply_game_asset_action":
            action = str(arguments.get("action", ""))
            return _tool_success(
                _json_text(
                    {
                        "action": action,
                        "status": "planned",
                        "message": "Use structured Blender tools for the concrete change; fast mode will auto-record local reversible edits as receipts.",
                        "arguments": dict(arguments.get("arguments") or {}),
                    }
                )
            )

        if tool_name == "explain_addon_step":
            payload = creator_context_payload(context)
            topic = str(arguments.get("topic", "") or "current context")
            return _tool_success(
                _json_text(
                    {
                        "topic": topic,
                        "context": payload,
                        "answer": "Use the N-panel chat first. Pick a quick prompt for assets, materials, workflows, fixes, exports, or tutoring. Open Workflow or Assets only when you want to inspect the generated graph or reusable library state.",
                    }
                )
            )

        if tool_name == "list_action_cards":
            cards = self.list_action_cards(context, str(arguments.get("status", "")))
            return _tool_success(_json_text(cards))

        if tool_name == "get_action_detail":
            return _tool_success(_json_text(self.get_action_detail(context, str(arguments.get("action_id", "")))))

        if tool_name == "create_action_card":
            requested_status = str(arguments.get("status", ""))
            if normalize_action_status(requested_status) in {"approved", "running", "stopping"}:
                requested_status = "awaiting_approval"
            card = self.create_action_card(
                context,
                title=str(arguments.get("title", "")),
                kind=str(arguments.get("kind", "")),
                prompt=str(arguments.get("prompt", "")),
                plan=str(arguments.get("plan", "")),
                tool_name=str(arguments.get("tool_name", "")),
                arguments=dict(arguments.get("arguments") or {}),
                affected_targets=arguments.get("affected_targets", []),
                required_context=arguments.get("required_context", []),
                risk=str(arguments.get("risk", "")),
                risk_rationale=str(arguments.get("risk_rationale", "")),
                risk_axes=dict(arguments.get("risk_axes") or {}),
                status=requested_status,
                scope_summary=str(arguments.get("scope_summary", "")),
                outcome_summary=str(arguments.get("outcome_summary", "")),
                assumptions=arguments.get("assumptions", []),
                dependencies=arguments.get("dependencies", []),
                preview_summary=str(arguments.get("preview_summary", "")),
                short_plan=arguments.get("short_plan", []),
                full_plan=str(arguments.get("full_plan", "")),
                approval_policy=str(arguments.get("approval_policy", "")),
                result_summary=str(arguments.get("result_summary", "")),
                recovery=str(arguments.get("recovery", "")),
            )
            return _tool_success(_json_text(card))

        if tool_name == "create_asset_action_card":
            requested_status = str(arguments.get("status", "awaiting_approval"))
            if normalize_action_status(requested_status) in {"approved", "running", "stopping"}:
                requested_status = "awaiting_approval"
            card = self.create_asset_action_card(
                context,
                title=str(arguments.get("title", "")),
                prompt=str(arguments.get("prompt", "")),
                plan=str(arguments.get("plan", "")),
                tool_name=str(arguments.get("tool_name", "")),
                arguments=dict(arguments.get("arguments") or {}),
                kind=str(arguments.get("kind", "change")),
                risk=str(arguments.get("risk", "")),
                risk_rationale=str(arguments.get("risk_rationale", "")),
                status=requested_status,
                asset_name=str(arguments.get("asset_name", "")),
                asset_category=str(arguments.get("asset_category", "")),
                asset_kind=str(arguments.get("asset_kind", "")),
                affected_targets=arguments.get("affected_targets", []),
                required_context=arguments.get("required_context", []),
                preview_summary=str(arguments.get("preview_summary", "")),
                outcome_summary=str(arguments.get("outcome_summary", "")),
                recovery=str(arguments.get("recovery", "")),
            )
            return _tool_success(_json_text(card))

        if tool_name == "update_action_card_plan":
            requested_status = normalize_action_status(str(arguments.get("status", "preview_ready")))
            if requested_status in {"approved", "running", "stopping"}:
                requested_status = "awaiting_approval"
            card = self.update_action_status(
                context,
                str(arguments.get("action_id", "")),
                requested_status,
                plan=str(arguments.get("plan", "")),
                preview_summary=str(arguments.get("preview_summary", "")),
                detail={
                    "short_plan": arguments.get("short_plan", []),
                    "full_plan": str(arguments.get("full_plan", "")) or str(arguments.get("plan", "")),
                    "plan_diff": str(arguments.get("plan_diff", "")),
                    "plan_revision": int(arguments.get("plan_revision", 1) or 1),
                },
            )
            return _tool_success(_json_text(card))

        if tool_name == "update_action_status":
            requested_status = normalize_action_status(str(arguments.get("status", "")))
            if requested_status in {"approved", "running", "stopping"} and not self._current_action_id:
                raise RuntimeError("Model tools cannot approve or start card execution. The user must approve the action card from the UI.")
            card = self.update_action_status(
                context,
                str(arguments.get("action_id", "")),
                requested_status,
                result_summary=str(arguments.get("result_summary", "")),
                recovery=str(arguments.get("recovery", "")),
                plan=str(arguments.get("plan", "")),
            )
            return _tool_success(_json_text(card))

        if tool_name == "preview_action_card":
            card = self.preview_action(context, str(arguments.get("action_id", "")))
            return _tool_success(_json_text(card))

        if tool_name == "request_action_approval":
            card = self.update_action_status(
                context,
                str(arguments.get("action_id", "")),
                "awaiting_approval",
                result_summary=str(arguments.get("summary", "Awaiting user approval.")),
            )
            return _tool_success(_json_text(card))

        if tool_name == "record_action_step":
            card = self._record_action_step(
                context,
                str(arguments.get("action_id", "")),
                {
                    "tool": str(arguments.get("tool", "")),
                    "phase": str(arguments.get("phase", "info")),
                    "status": str(arguments.get("status", "completed")),
                    "summary": str(arguments.get("summary", "")),
                    "targets": arguments.get("targets", []),
                },
            )
            return _tool_success(_json_text(card))

        if tool_name == "record_action_warning":
            card = self._record_action_warning(context, str(arguments.get("action_id", "")), str(arguments.get("warning", "")))
            return _tool_success(_json_text(card))

        if tool_name == "record_action_result":
            card = self.update_action_status(
                context,
                str(arguments.get("action_id", "")),
                str(arguments.get("status", "completed")),
                result_summary=str(arguments.get("result_summary", "")),
                recovery=str(arguments.get("recovery", "")),
            )
            return _tool_success(_json_text(card))

        if tool_name == "record_action_failure":
            card = self.update_action_status(
                context,
                str(arguments.get("action_id", "")),
                "failed",
                result_summary=str(arguments.get("error", "")),
                recovery=str(arguments.get("recovery", "Use Blender Undo or inspect the tool activity log.")),
                warnings=[str(arguments.get("error", ""))],
            )
            return _tool_success(_json_text(card))

        if tool_name == "pin_output_to_thread":
            output = self.pin_output_to_thread(
                context,
                title=str(arguments.get("title", "")),
                summary=str(arguments.get("summary", "")),
                kind=str(arguments.get("kind", "result")),
                action_id=str(arguments.get("action_id", "")),
                path=str(arguments.get("path", "")),
            )
            return _tool_success(_json_text(output))

        if tool_name == "list_blender_surfaces":
            return _tool_success(_json_text(list_blender_surfaces(context)))

        if tool_name == "list_cached_operator_namespaces":
            return _tool_success(_json_text(list_cached_operator_namespaces(int(arguments.get("limit_per_namespace", 80)))))

        if tool_name == "get_thread_context":
            context_payload = self._dashboard_store(context).get_thread_context(
                str(arguments.get("thread_id", "")),
                int(arguments.get("limit", 20)),
            )
            return _tool_success(_json_text(context_payload))

        if tool_name == "write_project_note":
            project_id = str(arguments.get("project_id") or self._active_project_id(context))
            project = self._dashboard_store(context).write_project_note(project_id, str(arguments.get("note", "")))
            return _tool_success(f"Updated project note for {project.get('name', project_id)}.")

        if tool_name in {"diagnose_dashboard_workspace", "diagnose_ai_studio_workspace"}:
            return _tool_success(_json_text(self.diagnose_dashboard_workspace(context)))

        if tool_name == "search_ai_assets":
            results = self._ai_assets_store(context).search(
                str(arguments.get("query", "")),
                kind=arguments.get("kind"),
                status=arguments.get("status"),
                limit=int(arguments.get("limit", 30) or 30),
            )
            return _tool_success(_json_text(results))

        if tool_name == "list_ai_asset_libraries":
            return _tool_success(_json_text(self._ai_assets_store(context).list_asset_libraries()))

        if tool_name == "list_asset_versions":
            results = self._ai_assets_store(context).list_asset_versions(
                kind=arguments.get("kind") or None,
                status=arguments.get("status") or None,
                library_id=arguments.get("library_id") or None,
                limit=int(arguments.get("limit", 50) or 50),
            )
            return _tool_success(_json_text(results))

        if tool_name == "get_asset_version_detail":
            version_uid = str(arguments.get("version_uid", ""))
            item = self._ai_assets_store(context).get_asset_version(version_uid)
            if item is None:
                raise RuntimeError(f"Asset version not found: {version_uid}")
            return _tool_success(_json_text(item))

        if tool_name == "list_asset_dependencies":
            version_uid = str(arguments.get("version_uid", ""))
            item = self._ai_assets_store(context).get_asset_version(version_uid)
            if item is None:
                raise RuntimeError(f"Asset version not found: {version_uid}")
            return _tool_success(_json_text(item.get("integrity", {}).get("missing_dependencies", [])))

        if tool_name == "list_asset_provenance":
            version_uid = str(arguments.get("version_uid", ""))
            item = self._ai_assets_store(context).get_asset_version(version_uid)
            if item is None:
                raise RuntimeError(f"Asset version not found: {version_uid}")
            return _tool_success(_json_text(item.get("provenance", {})))

        if tool_name == "diagnose_ai_assets":
            return _tool_success(_json_text(self.diagnose_ai_assets(context)))

        if tool_name == "list_toolbox_items":
            entries = self._toolbox_store(context).list_entries(arguments.get("category"))
            return _tool_success(summarize_entries(entries))

        if tool_name == "get_toolbox_item":
            item = self._toolbox_store(context).get_entry(str(arguments.get("item_id_or_name", "")))
            return _tool_success(_json_text(item))

        if tool_name == "save_toolbox_item":
            item = self._toolbox_store(context).save_entry(
                name=str(arguments.get("name", "")),
                category=str(arguments.get("category", "system")),
                description=str(arguments.get("description", "")),
                content=arguments.get("content"),
                tags=arguments.get("tags"),
                entry_id=arguments.get("item_id"),
            )
            return _tool_success(f"Saved toolbox item {item['id']}: {item['name']}.")

        if tool_name == "run_toolbox_system":
            action_id = action_id_from_arguments(arguments) or self._current_action_id
            results = self._toolbox_store(context).run_recipe(
                str(arguments.get("item_id_or_name", "")),
                lambda scene_tool, scene_args: self._execute_dynamic_tool(context, scene_tool, {**dict(scene_args or {}), "action_id": action_id}),
            )
            return _tool_success(_json_text(results))

        if tool_name == "list_asset_items":
            entries = self._asset_store(context).list_entries(arguments.get("category"), arguments.get("kind"))
            return _tool_success(summarize_assets(entries))

        if tool_name == "get_asset_item":
            item = self._asset_store(context).get_entry(str(arguments.get("item_id_or_name", "")))
            return _tool_success(_json_text(item))

        if tool_name == "save_asset_file":
            item = self._asset_store(context).save_file(
                filepath=str(arguments.get("filepath", "")),
                name=str(arguments.get("name", "")),
                category=str(arguments.get("category", "other")),
                description=str(arguments.get("description", "")),
                tags=arguments.get("tags"),
                copy_file=bool(arguments.get("copy_file", True)),
                entry_id=arguments.get("item_id"),
            )
            return _tool_success(f"Saved asset item {item['id']}: {item['name']} at {item['stored_path']}.")

        if tool_name == "save_selected_objects_asset":
            item = self._save_selected_objects_asset(context, arguments)
            return _tool_success(f"Saved selected-object asset {item['id']}: {item['name']} at {item['stored_path']}.")

        if tool_name == "import_asset_item":
            result = self._import_asset_item(context, str(arguments.get("item_id_or_name", "")), bool(arguments.get("link", False)))
            return _tool_success(_json_text(result))

        if tool_name == "register_blender_asset_library":
            result = self.register_asset_library(context)
            return _tool_success(_json_text(result))

        if tool_name == "list_blender_asset_libraries":
            return _tool_success(_json_text(list_asset_libraries()))

        if tool_name == "save_selection_to_asset_library":
            self.register_asset_library(context)
            library_args = dict(arguments)
            library_args["mark_as_blender_assets"] = True
            item = self._save_selected_objects_asset(context, library_args)
            return _tool_success(f"Saved selection to dashboard asset library as {item['id']}: {item['name']}.")

        if tool_name == "append_asset_from_library":
            result = self._import_asset_item(context, str(arguments.get("item_id_or_name", "")), bool(arguments.get("link", False)))
            return _tool_success(_json_text(result))

        if tool_name == "create_asset_publish_action":
            card = self.create_asset_publish_action(
                context,
                name=str(arguments.get("name", "")),
                kind=str(arguments.get("kind", "model")),
                description=str(arguments.get("description", "")),
                tags=arguments.get("tags"),
            )
            return _tool_success(_json_text(card))

        if tool_name == "promote_output_snapshot":
            result = self._ai_assets_store(context).promote_output_snapshot(str(arguments.get("output_id", "")), **dict(arguments.get("metadata", {}) or {}))
            return _tool_success(_json_text(result))

        if tool_name == "validate_asset_version":
            result = self._ai_assets_store(context).validate_asset_version(str(arguments.get("version_uid", "")))
            return _tool_success(_json_text(result))

        if tool_name == "publish_asset_package":
            result = self._ai_assets_store(context).publish_package(str(arguments.get("version_uid", "")), Path(arguments.get("package_dir", "")) if arguments.get("package_dir") else None)
            return _tool_success(_json_text(result))

        if tool_name == "import_asset_package":
            result = self._ai_assets_store(context).import_package(Path(str(arguments.get("package_path", ""))), str(arguments.get("library_id", "published")))
            return _tool_success(_json_text(result))

        if tool_name == "pin_asset_version":
            result = self._ai_assets_store(context).pin_target(
                target_type="asset_version",
                target_uid=str(arguments.get("version_uid", "")),
                scope=str(arguments.get("scope", "project")),
                reason=str(arguments.get("reason", "")),
                project_id=self._active_project_id(context),
                thread_id=self._dashboard_store(context).active_thread_id(),
            )
            return _tool_success(_json_text(result))

        if tool_name == "fork_asset_version":
            source = self._ai_assets_store(context).get_asset_version(str(arguments.get("version_uid", "")))
            if source is None:
                raise RuntimeError(f"Asset version not found: {arguments.get('version_uid', '')}")
            source["version"] = str(arguments.get("new_version", "1.0.1"))
            source["version_uid"] = f"{source['logical_uid']}@{source['version']}"
            source["status"] = "draft"
            source["provenance"] = {**dict(source.get("provenance", {})), "wasDerivedFrom": [arguments.get("version_uid", "")]}
            result = self._ai_assets_store(context).upsert_asset_version(**source)
            return _tool_success(_json_text(result))

        if tool_name == "append_asset_version":
            result = self._import_asset_item(context, str(arguments.get("version_uid", "")), link=False)
            return _tool_success(_json_text(result))

        if tool_name == "link_asset_version":
            result = self._import_asset_item(context, str(arguments.get("version_uid", "")), link=True)
            return _tool_success(_json_text(result))

        if tool_name == "list_workflow_graphs":
            return _tool_success(_json_text(self.workflow_graphs()))

        if tool_name == "create_workflow_graph":
            result = self.create_workflow_graph(
                name=str(arguments.get("name", "")),
                with_default_nodes=bool(arguments.get("with_default_nodes", False)),
            )
            return _tool_success(_json_text(result))

        if tool_name == "add_workflow_node":
            result = self.add_workflow_node(
                graph_name=str(arguments.get("graph_name", "")),
                node_type=str(arguments.get("node_type", "")),
                label=str(arguments.get("label", "")),
            )
            return _tool_success(_json_text(result))

        if tool_name == "connect_workflow_nodes":
            result = connect_workflow_nodes(
                str(arguments.get("graph_name", "")),
                str(arguments.get("from_node", "")),
                str(arguments.get("from_socket", "")),
                str(arguments.get("to_node", "")),
                str(arguments.get("to_socket", "")),
            )
            return _tool_success(_json_text(result))

        if tool_name == "set_workflow_node_config":
            config = dict(arguments.get("config") or {})
            for key in ("tool_name", "arguments_json", "memory_query", "approval_required"):
                if key in arguments:
                    config[key] = arguments[key]
            result = set_workflow_node_config(
                str(arguments.get("graph_name", "")),
                str(arguments.get("node_name", "")),
                config,
            )
            return _tool_success(_json_text(result))

        if tool_name == "inspect_workflow_graph":
            result = inspect_workflow_graph(
                str(arguments.get("graph_name", "")),
                include_results=bool(arguments.get("include_results", True)),
            )
            return _tool_success(_json_text(result))

        if tool_name == "run_workflow_graph":
            result = self.run_workflow_graph(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                preview_only=bool(arguments.get("preview_only", True)),
            )
            return _tool_success(_json_text(result))

        if tool_name == "validate_workflow_graph":
            result = self.validate_workflow_graph(context, graph_name=str(arguments.get("graph_name", "")))
            return _tool_success(_json_text(result))

        if tool_name == "compile_workflow_graph":
            result = self.compile_workflow_graph(context, graph_name=str(arguments.get("graph_name", "")))
            return _tool_success(_json_text(result))

        if tool_name == "preview_workflow_node":
            result = self.preview_workflow_node(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                node_name=str(arguments.get("node_name", "")),
            )
            return _tool_success(_json_text(result))

        if tool_name == "preview_workflow_graph":
            result = self.preview_workflow_graph(context, graph_name=str(arguments.get("graph_name", "")))
            return _tool_success(_json_text(result))

        if tool_name == "start_workflow_run":
            result = self.start_workflow_run(context, graph_name=str(arguments.get("graph_name", "")))
            return _tool_success(_json_text(result))

        if tool_name == "resume_workflow_run":
            result = self.resume_workflow_run(context, str(arguments.get("run_id", "")))
            return _tool_success(_json_text(result))

        if tool_name == "stop_workflow_run":
            result = self.stop_workflow_run(context, str(arguments.get("run_id", "")), reason=str(arguments.get("reason", "")))
            return _tool_success(_json_text(result))

        if tool_name == "list_workflow_runs":
            result = self.list_workflow_runs(context, graph_id=str(arguments.get("graph_id", "")))
            return _tool_success(_json_text(result))

        if tool_name == "get_workflow_run_detail":
            result = self.get_workflow_run_detail(context, str(arguments.get("run_id", "")))
            return _tool_success(_json_text(result))

        if tool_name == "publish_workflow_recipe":
            result = self.publish_workflow_recipe(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                metadata=dict(arguments.get("metadata") or {}),
            )
            return _tool_success(_json_text(result))

        if tool_name == "list_workflow_recipes":
            result = self.list_workflow_recipes(context, recipe_id=str(arguments.get("recipe_id", "")))
            return _tool_success(_json_text(result))

        if tool_name == "get_workflow_recipe_detail":
            result = self.get_workflow_recipe_detail(context, str(arguments.get("recipe_version_uid", "")))
            return _tool_success(_json_text(result))

        if tool_name == "propose_workflow_patch":
            result = self.propose_workflow_patch(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                operations=list(arguments.get("operations") or []),
            )
            return _tool_success(_json_text(result))

        if tool_name == "preview_workflow_patch":
            result = self.preview_workflow_patch(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                operations=list(arguments.get("operations") or []),
            )
            return _tool_success(_json_text(result))

        if tool_name == "apply_workflow_patch":
            result = self.apply_workflow_patch(
                context,
                graph_name=str(arguments.get("graph_name", "")),
                operations=list(arguments.get("operations") or []),
            )
            return _tool_success(_json_text(result))

        return execute_tool(context, tool_name, strip_action_metadata(arguments))

    def _dashboard_context(self, context: bpy.types.Context) -> dict[str, Any]:
        snapshot = self.service.snapshot()
        store = self._dashboard_store(context)
        project_id = self._active_project_id(context)
        active_thread_id = snapshot.active_thread_id or store.active_thread_id()
        projects = store.list_projects()
        threads = store.list_threads(project_id=project_id, mode=self._current_chat_mode(context))
        active_project = next((project for project in projects if project.get("project_id") == project_id), None)
        active_thread = next((thread for thread in threads if thread.get("thread_id") == active_thread_id), None)
        window_manager = context.window_manager

        return {
            "workspace": dashboard_context(context),
            "chat_mode": self._current_chat_mode(context),
            "active_project_id": project_id,
            "active_project": active_project or {},
            "active_thread_id": active_thread_id,
            "active_thread": active_thread or {},
            "scope": self._ai_scope_payload(context),
            "actions": {
                "awaiting_approval": len(store.list_action_cards(project_id=project_id, status="awaiting_approval")),
                "running": len(store.list_action_cards(project_id=project_id, status="running")),
                "failed": len(store.list_action_cards(project_id=project_id, status="failed")),
                "recent": store.list_action_cards(project_id=project_id)[:8],
            },
            "recent_outputs": store.list_pinned_outputs(project_id=project_id, limit=8),
            "service": {
                "status": snapshot.status_text,
                "activity": snapshot.activity_text,
                "turn_in_progress": snapshot.turn_in_progress,
                "error": {
                    "title": getattr(snapshot, "last_error_title", ""),
                    "summary": snapshot.last_error,
                    "severity": getattr(snapshot, "last_error_severity", ""),
                    "recovery": getattr(snapshot, "last_error_recovery", ""),
                    "retry": getattr(snapshot, "last_error_retry", ""),
                    "stream_recovering": bool(getattr(snapshot, "stream_recovering", False)),
                },
                "model": getattr(window_manager, "codex_blender_model", ""),
                "account": snapshot.account.email if snapshot.account else "",
            },
            "game_creator": {
                **creator_context_payload(context),
                "cards_as_receipts": self._cards_as_receipts(context),
                "require_additive_approval": self._require_additive_approval(context),
            },
            "visual_review": self.visual_review_context(context),
            "ui": {
                "visible_message_count": getattr(window_manager, "codex_blender_visible_message_count", 0),
                "show_transcript": getattr(window_manager, "codex_blender_show_transcript", True),
                "redraw_paused": getattr(window_manager, "codex_blender_redraw_paused", False),
                "messages_drawn": len(getattr(window_manager, "codex_blender_messages", [])),
            },
            "counts": {
                "projects": len(projects),
                "threads_in_mode": len(threads),
                "toolbox_items": len(self._toolbox_store(context).list_entries()),
                "asset_items": len(self._asset_store(context).list_entries()),
                "registered_asset_libraries": len(list_asset_libraries()),
            },
        }

    def _ai_scope_payload(self, context: bpy.types.Context) -> dict[str, Any]:
        window_manager = context.window_manager
        active_scope = getattr(window_manager, "codex_blender_active_scope", "selection")
        return context_payload_from_chips(active_scope, self._build_context_chips(context))

    def _safety_preferences(self, context: bpy.types.Context) -> dict[str, bool]:
        wm = context.window_manager
        return {
            "Preview First": bool(getattr(wm, "codex_blender_safety_preview_first", True)),
            "Non-Destructive": bool(getattr(wm, "codex_blender_safety_non_destructive", True)),
            "Duplicate First": bool(getattr(wm, "codex_blender_safety_duplicate_first", False)),
            "No Deletes": bool(getattr(wm, "codex_blender_safety_no_deletes", True)),
            "Require Approval": bool(getattr(wm, "codex_blender_safety_require_approval", False)),
            "Stop At Checkpoints": bool(getattr(wm, "codex_blender_safety_stop_checkpoints", True)),
        }

    def _build_context_chips(self, context: bpy.types.Context) -> list[dict[str, Any]]:
        window_manager = context.window_manager
        previous_enabled = {
            chip.chip_id: bool(chip.enabled)
            for chip in getattr(window_manager, "codex_blender_context_chips", [])
        }
        selected = list(getattr(context, "selected_objects", []) or [])
        active = getattr(context, "active_object", None)
        scene = getattr(context, "scene", None)
        collection = getattr(context, "collection", None)
        attachments = list(getattr(window_manager, "codex_blender_attachments", []) or [])
        chips = [
            make_context_chip("intent", "Intent", getattr(window_manager, "codex_blender_intent", "auto"), "intent", True),
            make_context_chip("selection", "Selection", f"{len(selected)} object(s)", "scope", previous_enabled.get("selection", True), ", ".join(obj.name for obj in selected[:8])),
            make_context_chip("active_object", "Active Object", active.name if active else "None", "scope", previous_enabled.get("active_object", True), getattr(active, "type", "") if active else ""),
            make_context_chip("collection", "Collection", collection.name if collection else "None", "scope", previous_enabled.get("collection", True)),
            make_context_chip("scene", "Scene", scene.name if scene else "None", "scope", previous_enabled.get("scene", True), f"Frame {scene.frame_current}" if scene else ""),
            make_context_chip("mode", "Mode", getattr(context, "mode", "OBJECT"), "state", previous_enabled.get("mode", True)),
            make_context_chip("timeline", "Timeline", f"{scene.frame_start}-{scene.frame_end}" if scene else "None", "state", previous_enabled.get("timeline", True)),
            make_context_chip("material", "Material", active.active_material.name if active and active.active_material else "None", "data", previous_enabled.get("material", True)),
            make_context_chip("attachments", "Attachments", f"{len(attachments)} file(s)", "input", previous_enabled.get("attachments", True), ", ".join(item.path for item in attachments[:4])),
            make_context_chip("project", "Project", self._active_project_id(context), "memory", previous_enabled.get("project", True)),
        ]
        for label, enabled in self._safety_preferences(context).items():
            chip_id = "safety_" + label.lower().replace(" ", "_")
            chips.append(make_context_chip(chip_id, label, "On" if enabled else "Off", "safety", previous_enabled.get(chip_id, enabled)))
        for index, output in enumerate(self._dashboard_store(context).list_pinned_outputs(project_id=self._active_project_id(context), limit=3), start=1):
            chips.append(make_context_chip(f"pinned_output_{index}", "Pinned Output", output.get("title", ""), "memory", previous_enabled.get(f"pinned_output_{index}", True), output.get("summary", "")))
        return chips

    def _storage_root(self, context: bpy.types.Context) -> Path:
        path = bpy.utils.user_resource("CONFIG", path="codex_blender_agent", create=True)
        if path:
            return Path(path)
        return Path(os.path.expanduser("~")) / ".codex_blender_agent"

    def _ai_assets_store(self, context: bpy.types.Context) -> AIAssetsStore:
        preferences = self._preferences(context)
        override = str(getattr(preferences, "ai_assets_storage_root", "") or "").strip()
        if override:
            root = Path(override).expanduser()
        else:
            root = self._storage_root(context) / "ai_assets"
            extension_path_user = getattr(bpy.utils, "extension_path_user", None)
            if callable(extension_path_user):
                try:
                    candidate = extension_path_user(__package__ or ADDON_ID, path="ai_assets", create=True)
                    if candidate:
                        root = Path(candidate)
                except Exception:
                    root = self._storage_root(context) / "ai_assets"
        return AIAssetsStore(root, legacy_root=self._storage_root(context))

    def _chat_history_store(self, context: bpy.types.Context) -> ChatHistoryStore:
        return ChatHistoryStore(self._storage_root(context))

    def _toolbox_store(self, context: bpy.types.Context) -> ToolboxStore:
        return ToolboxStore(self._storage_root(context))

    def _asset_store(self, context: bpy.types.Context) -> AssetStore:
        return AssetStore(self._storage_root(context))

    def _dashboard_store(self, context: bpy.types.Context) -> DashboardStore:
        return DashboardStore(self._storage_root(context))

    def _ensure_chat_mode(self, context: bpy.types.Context, mode: str) -> None:
        mode = mode or "scene_agent"
        if self._active_chat_mode == mode:
            return
        snapshot = self.service.snapshot()
        if snapshot.turn_in_progress:
            raise RuntimeError("Cannot switch chat mode while a Codex turn is running.")
        if self._active_chat_mode and (snapshot.active_thread_id or snapshot.messages):
            self._persist_thread_snapshot(context.window_manager, snapshot, mode=self._active_chat_mode)
        self.service.new_thread()
        self._active_chat_mode = mode
        self._last_synced_version = -1
        record = self._chat_history_store(context).load_latest(mode)
        if record and record.get("thread_id"):
            self.service.restore_local_thread(record["thread_id"], record.get("messages", []))

    def _delete_mode_history(self, context: bpy.types.Context, mode: str) -> None:
        store = self._chat_history_store(context)
        data = store._load()
        data["threads"] = [thread for thread in data.get("threads", []) if thread.get("mode", "scene_agent") != mode]
        store._save(data)

    def _current_chat_mode(self, context: bpy.types.Context) -> str:
        window_manager = getattr(context, "window_manager", None)
        if window_manager is None:
            return "scene_agent"
        return getattr(window_manager, "codex_blender_chat_mode", "scene_agent") or "scene_agent"

    def _game_creator_friction(self, context: bpy.types.Context) -> str:
        window_manager = getattr(context, "window_manager", None)
        prefs = self._preferences(context)
        value = getattr(window_manager, "codex_blender_execution_friction", "") if window_manager else ""
        return value or getattr(prefs, "execution_friction", "fast") or "fast"

    def _require_additive_approval(self, context: bpy.types.Context) -> bool:
        window_manager = getattr(context, "window_manager", None)
        prefs = self._preferences(context)
        return bool(
            getattr(window_manager, "codex_blender_require_additive_approval", False)
            or getattr(prefs, "require_additive_approval", False)
            or getattr(window_manager, "codex_blender_safety_require_approval", False)
        )

    def _cards_as_receipts(self, context: bpy.types.Context) -> bool:
        window_manager = getattr(context, "window_manager", None)
        prefs = self._preferences(context)
        return bool(
            getattr(window_manager, "codex_blender_cards_as_receipts", True)
            and getattr(prefs, "cards_as_receipts", True)
        )

    def _current_project_id(self, context: bpy.types.Context) -> str:
        cwd = self.resolve_workspace_root(context)
        return make_project_id(cwd) if cwd else DEFAULT_PROJECT_ID

    def _current_project_name(self, context: bpy.types.Context) -> str:
        if bpy.data.filepath:
            return Path(bpy.data.filepath).stem
        cwd = Path(self.resolve_workspace_root(context))
        return cwd.name or "Current Blender Project"

    def _asset_scope_summary(
        self,
        context: bpy.types.Context,
        *,
        asset_name: str = "",
        asset_category: str = "",
        asset_kind: str = "",
    ) -> str:
        store = self._asset_store(context)
        libraries = list_asset_libraries()
        parts = [
            f"{len(store.list_entries())} stored asset item(s)",
            f"{len(libraries)} registered library/libraries",
        ]
        if asset_name:
            parts.insert(0, f"Asset: {asset_name}")
        if asset_category:
            parts.append(f"Category: {asset_category}")
        if asset_kind:
            parts.append(f"Kind: {asset_kind}")
        return "; ".join(parts)

    def _asset_context(self, context: bpy.types.Context) -> dict[str, Any]:
        store = self._asset_store(context)
        dashboard = self._dashboard_store(context)
        window_manager = context.window_manager
        asset_items = list(getattr(window_manager, "codex_blender_asset_items", []) or [])
        asset_index = getattr(window_manager, "codex_blender_asset_index", -1)
        selected_asset = {}
        if 0 <= asset_index < len(asset_items):
            item = asset_items[asset_index]
            selected_asset = {
                "item_id": getattr(item, "item_id", ""),
                "name": getattr(item, "name", ""),
                "category": getattr(item, "category", ""),
                "kind": getattr(item, "kind", ""),
                "path": getattr(item, "path", ""),
                "description": getattr(item, "description", ""),
            }
        recent_cards = [
            {
                "action_id": card.get("action_id", ""),
                "title": card.get("title", ""),
                "status": card.get("status", ""),
                "tool_name": card.get("tool_name", ""),
                "result_summary": card.get("result_summary", ""),
                "updated_at": card.get("updated_at", ""),
            }
            for card in dashboard.list_action_cards(project_id=self._active_project_id(context))
            if card.get("tool_name", "") in {
                "save_asset_file",
                "save_selected_objects_asset",
                "save_selection_to_asset_library",
                "register_blender_asset_library",
                "import_asset_item",
                "append_asset_from_library",
            }
        ][:8]
        libraries = list_asset_libraries()
        return {
            "workspace": getattr(context.window.workspace, "name", "") if getattr(context, "window", None) else "",
            "active_project_id": self._active_project_id(context),
            "asset_library_root": str(asset_library_root(Path(self._storage_root(context)))),
            "registered_libraries": libraries,
            "asset_item_count": len(store.list_entries()),
            "selected_asset": selected_asset,
            "recent_asset_actions": recent_cards,
            "pinned_outputs": dashboard.list_pinned_outputs(project_id=self._active_project_id(context), limit=5),
            "toolbox_count": len(self._toolbox_store(context).list_entries()),
            "selected_object_count": len(getattr(context, "selected_objects", []) or []),
            "execution_policy": "Fast Game Creator Mode records local reversible asset work as receipts; destructive, external, package, and broad import/publish work still uses approval cards.",
        }

    def _save_selected_objects_asset(self, context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip()
        if not name:
            raise RuntimeError("Asset name is required.")
        object_names = [str(name) for name in arguments.get("object_names", []) if str(name).strip()]
        objects = [bpy.data.objects.get(name) for name in object_names] if object_names else list(context.selected_objects)
        objects = [obj for obj in objects if obj is not None]
        if not objects:
            raise RuntimeError("No objects were selected or resolved for the asset.")
        store = self._asset_store(context)
        item_id, filepath = store.reserve_asset_path(name, ".blend", arguments.get("item_id"))
        marked_assets = []
        if arguments.get("mark_as_blender_assets", False):
            marked_assets = mark_local_ids_as_assets(objects)
        logical_uid = f"asset:{item_id}"
        version_uid = f"assetver:{item_id}@1.0.0"
        provenance_activity_id = self._current_action_id or str(arguments.get("action_id", ""))
        for obj in objects:
            try:
                obj["codex_ai_assets_logical_uid"] = logical_uid
                obj["codex_ai_assets_version_uid"] = version_uid
                obj["codex_ai_assets_provenance_activity_id"] = provenance_activity_id
                obj["codex_ai_assets_addon_version"] = ADDON_VERSION
            except Exception:
                continue
        bpy.data.libraries.write(str(filepath), set(objects), path_remap="RELATIVE_ALL", fake_user=True, compress=True)
        return store.save_generated_asset(
            filepath=filepath,
            item_id=item_id,
            name=name,
            category=str(arguments.get("category", "model")),
            description=str(arguments.get("description", "")),
            tags=arguments.get("tags"),
            kind="blend_bundle",
            metadata={
                "object_names": [obj.name for obj in objects],
                "marked_assets": marked_assets,
                "action_id": provenance_activity_id,
                "logical_uid": logical_uid,
                "version_uid": version_uid,
                "datablock_count": len(objects),
                "thread_id": self.service.snapshot().active_thread_id or "",
                "project_id": self._active_project_id(context),
                "source": "tool" if str(arguments.get("action_id", "")).strip() else "ui",
            },
        )

    def _import_asset_item(self, context: bpy.types.Context, item_id_or_name: str, link: bool = False) -> dict[str, Any]:
        item = self._asset_store(context).get_entry(item_id_or_name)
        path = Path(item.get("stored_path") or item.get("source_path", "")).expanduser()
        if not path.exists():
            raise RuntimeError(f"Asset file does not exist: {path}")
        suffix = path.suffix.lower()
        if suffix == ".blend":
            object_filter = set(item.get("metadata", {}).get("object_names", []))
            with bpy.data.libraries.load(str(path), link=link) as (data_from, data_to):
                data_to.objects = [name for name in data_from.objects if not object_filter or name in object_filter]
            linked = []
            for obj in data_to.objects:
                if obj is not None:
                    context.collection.objects.link(obj)
                    linked.append(obj.name)
            return {
                "asset": item,
                "imported_objects": linked,
                "action_id": item.get("metadata", {}).get("action_id", ""),
                "thread_id": item.get("metadata", {}).get("thread_id", ""),
                "project_id": item.get("metadata", {}).get("project_id", ""),
            }
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".exr", ".hdr"}:
            image = bpy.data.images.load(str(path), check_existing=True)
            return {
                "asset": item,
                "loaded_image": image.name,
                "action_id": item.get("metadata", {}).get("action_id", ""),
                "thread_id": item.get("metadata", {}).get("thread_id", ""),
                "project_id": item.get("metadata", {}).get("project_id", ""),
            }
        if suffix in {".fbx", ".obj", ".gltf", ".glb"}:
            payload = execute_tool(context, "import_file", {"filepath": str(path), "file_type": suffix.lstrip(".")})
            return {
                "asset": item,
                "import_result": payload,
                "action_id": item.get("metadata", {}).get("action_id", ""),
                "thread_id": item.get("metadata", {}).get("thread_id", ""),
                "project_id": item.get("metadata", {}).get("project_id", ""),
            }
        return {
            "asset": item,
            "message": f"Asset type {suffix or 'unknown'} is stored but not directly importable.",
            "action_id": item.get("metadata", {}).get("action_id", ""),
            "thread_id": item.get("metadata", {}).get("thread_id", ""),
            "project_id": item.get("metadata", {}).get("project_id", ""),
        }

    def _restore_latest_thread(self, context: bpy.types.Context) -> None:
        if self._active_chat_mode:
            return
        record = self._chat_history_store(context).load_latest(self._current_chat_mode(context))
        if record and record.get("thread_id"):
            self.service.restore_local_thread(record["thread_id"], record.get("messages", []))
        self._active_chat_mode = self._current_chat_mode(context)

    def _persist_thread_snapshot(self, window_manager: bpy.types.WindowManager, snapshot, mode: str | None = None) -> None:
        if snapshot.turn_in_progress or not snapshot.active_thread_id or not snapshot.messages:
            return
        context = bpy.context
        messages = [asdict(message) for message in snapshot.messages]
        project_id = self._active_project_id(context)
        chat_mode = mode or getattr(window_manager, "codex_blender_chat_mode", "scene_agent")
        self._chat_history_store(context).save_thread(
            snapshot.active_thread_id,
            self.resolve_workspace_root(context),
            getattr(window_manager, "codex_blender_model", ""),
            messages,
            mode=chat_mode,
        )
        self._dashboard_store(context).save_thread(
            thread_id=snapshot.active_thread_id,
            project_id=project_id,
            mode=chat_mode,
            model=getattr(window_manager, "codex_blender_model", ""),
            cwd=self.resolve_workspace_root(context),
            messages=messages,
        )

    def _active_project_id(self, context: bpy.types.Context) -> str:
        window_manager = getattr(context, "window_manager", None)
        if window_manager is not None and getattr(window_manager, "codex_blender_active_project_id", ""):
            return window_manager.codex_blender_active_project_id
        return self._current_project_id(context)

    def _dashboard_signature(self, context: bpy.types.Context) -> str:
        store = self._dashboard_store(context)
        project_count = len(store.list_projects())
        thread_count = len(store.list_threads(project_id=self._active_project_id(context), mode=self._current_chat_mode(context)))
        action_count = len(store.list_action_cards(project_id=self._active_project_id(context)))
        output_count = len(store.list_pinned_outputs(project_id=self._active_project_id(context)))
        event_count = len(store.list_job_timeline(project_id=self._active_project_id(context)))
        return f"{project_count}:{thread_count}:{action_count}:{output_count}:{event_count}:{self._active_project_id(context)}:{self._current_chat_mode(context)}"

    def _sync_dashboard_items(self, window_manager: bpy.types.WindowManager) -> None:
        context = bpy.context
        store = self._dashboard_store(context)
        active_project_id = self._active_project_id(context)
        projects = store.list_projects()
        window_manager.codex_blender_projects.clear()
        for index, project in enumerate(projects):
            entry = window_manager.codex_blender_projects.add()
            entry.project_id = project.get("project_id", "")
            entry.name = project.get("name", "")
            entry.cwd = project.get("cwd", "")
            entry.summary = project.get("notes", "")
            entry.updated_at = project.get("updated_at", "")
            if entry.project_id == active_project_id:
                window_manager.codex_blender_project_index = index
        if not getattr(window_manager, "codex_blender_active_project_id", ""):
            window_manager.codex_blender_active_project_id = active_project_id

        mode = self._current_chat_mode(context)
        threads = store.list_threads(project_id=active_project_id, mode=mode)
        active_thread_id = self.service.snapshot().active_thread_id or store.active_thread_id()
        window_manager.codex_blender_threads.clear()
        for index, thread in enumerate(threads):
            entry = window_manager.codex_blender_threads.add()
            entry.thread_id = thread.get("thread_id", "")
            entry.project_id = thread.get("project_id", "")
            entry.mode = thread.get("mode", "")
            entry.title = thread.get("title", "")
            entry.summary = thread.get("preview", "")
            entry.status = thread.get("status", "")
            entry.updated_at = thread.get("updated_at", "")
            entry.message_count = int(thread.get("message_count", 0))
            entry.unread = bool(thread.get("unread", False))
            if entry.thread_id == active_thread_id:
                window_manager.codex_blender_thread_index = index
                window_manager.codex_blender_active_thread_id = entry.thread_id

    def _sync_toolbox_items(self, window_manager: bpy.types.WindowManager) -> None:
        context = bpy.context
        items = self._toolbox_store(context).list_entries()
        window_manager.codex_blender_toolbox_items.clear()
        for item in items[:30]:
            entry = window_manager.codex_blender_toolbox_items.add()
            entry.item_id = item.get("id", "")
            entry.name = item.get("name", "")
            entry.category = normalize_toolbox_group(item.get("category", ""), item.get("name", ""))
            entry.description = item.get("description", "")

    def _sync_asset_items(self, window_manager: bpy.types.WindowManager) -> None:
        context = bpy.context
        items = self.refresh_asset_items(context)
        window_manager.codex_blender_asset_items.clear()
        for item in items[:30]:
            entry = window_manager.codex_blender_asset_items.add()
            entry.item_id = item.get("id", "")
            entry.version_uid = item.get("version_uid", "")
            entry.logical_uid = item.get("logical_uid", "")
            entry.name = item.get("name", "")
            entry.category = item.get("category", "")
            entry.kind = item.get("kind", "")
            entry.status = item.get("status", "")
            entry.version = item.get("version", "")
            entry.license_spdx = item.get("license_spdx", "")
            entry.catalog_path = item.get("catalog_path", "")
            entry.import_policy = item.get("import_policy", "")
            entry.dependency_health = item.get("dependency_health", "")
            entry.validation_state = item.get("validation_state", "")
            entry.provenance_summary = item.get("provenance_summary", "")
            entry.preview_path = item.get("preview_path", "")
            entry.path = item.get("stored_path", "")
            entry.description = item.get("description", "")

    def _create_workflow_preview_actions(self, context: bpy.types.Context, result: dict[str, Any]) -> None:
        for item in result.get("results", []):
            node_type = item.get("type", "")
            node_name = item.get("node", "")
            node_result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
            tool_name = str(node_result.get("tool", ""))
            if node_type not in {"tool_call", "toolbox_recipe", "publish_asset", "approval_gate"} and not tool_name:
                continue
            if node_type == "approval_gate" and not node_result.get("blocked"):
                continue
            title = f"Workflow: {node_name or node_type}"
            plan = f"Previewed workflow node {node_name or node_type}."
            policy = classify_tool(tool_name) if tool_name else classify_tool(node_type)
            if tool_name:
                plan = f"Run Blender tool {tool_name} with arguments {node_result.get('arguments', {})}."
            self.create_action_card(
                context,
                title=title,
                kind="automate",
                prompt=f"Workflow preview generated by {result.get('graph', 'Codex AI Workflow')}.",
                plan=plan,
                tool_name=tool_name,
                arguments=node_result.get("arguments", {}) if isinstance(node_result.get("arguments", {}), dict) else {},
                affected_targets=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                required_context=[getattr(context.window_manager, "codex_blender_active_scope", "selection")],
                risk=policy.risk,
                status="awaiting_approval" if tool_name else "draft",
                preview_summary=f"Workflow preview only. {plan}",
                tool_activity=[{"tool": tool_name or node_type, "phase": "preview", "status": "preview_ready"}],
            )

    def _workflow_store(self, context: bpy.types.Context) -> WorkflowRuntimeStore:
        root = self._storage_root(context) / "workflow_runtime"
        store = WorkflowRuntimeStore(root, legacy_root=self._storage_root(context))
        store.initialize()
        return store

    def _persist_workflow_graph_if_possible(self, context: bpy.types.Context | None, graph: dict[str, Any], status: str = "draft") -> None:
        if not graph:
            return
        try:
            context = context or bpy.context
            manifest = workflow_graph_manifest(graph)
            name = str(graph.get("graph_name") or graph.get("name") or manifest.get("name") or "Codex AI Workflow")
            graph_id = _workflow_graph_id(name)
            self._workflow_store(context).upsert_graph(graph_id, name, manifest, status=status)
        except Exception as exc:
            print(f"Codex Blender Agent workflow graph persistence failed: {exc}")

    def _approved_workflow_cards(self, context: bpy.types.Context) -> list[dict[str, Any]]:
        cards = self.list_action_cards(context)
        approved = []
        for card in cards:
            if normalize_action_status(card.get("status", "")) in {"approved", "running"}:
                detail = card.get("detail", {}) if isinstance(card.get("detail", {}), dict) else {}
                approved.append(
                    {
                        **card,
                        "snapshot_hash": detail.get("snapshot_hash", ""),
                        "graph_hash": detail.get("graph_hash", ""),
                    }
                )
        return approved

    def _record_workflow_plan_nodes(self, store: WorkflowRuntimeStore, run_id: str, compiled: dict[str, Any]) -> None:
        for step in compiled.get("steps", []) or []:
            node_id = f"{run_id}:{step.get('node_name', step.get('label', 'node'))}"
            store.record_run_node(
                run_id,
                node_id,
                node_name=str(step.get("node_name", "")),
                node_type=str(step.get("node_type", "")),
                state="waiting_approval" if step.get("blocked") else "queued",
                risk_level=str(step.get("tool_policy", {}).get("risk", "none") or ("write" if step.get("requires_action_card") else "none")),
                warning_count=int(step.get("warning_count", 0) or 0),
                result_summary=str(step.get("last_result_summary", "")),
                error_summary=str(step.get("last_error_summary", "")),
                action_card_ref=str(step.get("action_card_ref", "")),
                detail=step,
            )

    def _create_workflow_preview_cards_from_plan(self, context: bpy.types.Context, plan: dict[str, Any], *, run_id: str = "") -> None:
        graph_name = str(plan.get("graph_name") or plan.get("name") or "Codex AI Workflow")
        graph_hash = str(plan.get("graph_hash") or "")
        steps = plan.get("preview_steps") or plan.get("steps") or []
        created = 0
        for step in steps:
            if not step.get("requires_action_card") and not step.get("blocked"):
                continue
            node_name = str(step.get("node_name") or step.get("label") or "Workflow step")
            node_type = str(step.get("node_type") or "")
            tool_name = str(step.get("tool_name") or "")
            policy = step.get("tool_policy", {}) if isinstance(step.get("tool_policy", {}), dict) else {}
            risk = str(policy.get("risk") or ("high" if node_type == "publish_asset" else "medium"))
            preview_summary = str(step.get("preview_summary") or step.get("block_reason") or "Workflow preview generated a reviewable step.")
            card = self.create_action_card(
                context,
                title=f"Workflow approval: {node_name}",
                kind="automate" if node_type != "publish_asset" else "export",
                prompt=f"Workflow graph {graph_name} requires review before executing {node_name}.",
                plan=preview_summary,
                tool_name=tool_name,
                arguments={},
                affected_targets=[node_name],
                required_context=[graph_name],
                risk=risk if risk in {"low", "medium", "high", "critical"} else "medium",
                risk_rationale=str(step.get("block_reason") or "Action-card approval is required before this workflow node can execute."),
                status="awaiting_approval",
                scope_summary=f"Workflow node: {node_name}",
                outcome_summary=f"Approve to allow {node_name} to resume in run {run_id or 'the next workflow run'}.",
                assumptions=[f"Graph hash: {graph_hash}" if graph_hash else "Workflow preview is current."],
                preview_summary=preview_summary,
                short_plan=[
                    "Review this workflow node proposal.",
                    "Approve the card if the scope and risk are acceptable.",
                    "Resume the workflow run from the Workflow workspace.",
                ],
                full_plan=str(step),
                approval_policy="Explicit workflow approval",
                tool_activity=[{"tool": tool_name or node_type, "phase": "preview", "status": "awaiting_approval"}],
                recovery="Cancel this card or regenerate the workflow preview if upstream inputs changed.",
                plan_revision=1,
                change_ledger=[],
            )
            detail = card.get("detail", {})
            self._dashboard_store(context).update_action_status(
                card["action_id"],
                card.get("status", "awaiting_approval"),
                card.get("result_summary", ""),
                card.get("recovery", ""),
                detail.get("plan", ""),
                detail={
                    **detail,
                    "workflow_run_id": run_id,
                    "workflow_graph_name": graph_name,
                    "workflow_node_name": node_name,
                    "workflow_node_type": node_type,
                    "snapshot_hash": str(step.get("snapshot_hash", "")),
                    "graph_hash": graph_hash,
                    "resume_token": f"{run_id}:{node_name}" if run_id else node_name,
                    "editable_fields_schema": {"type": "object", "properties": {}},
                    "decision_history": [],
                },
            )
            created += 1
        if created:
            self._last_dashboard_signature = ""
            self._sync_window_manager(context.window_manager, force=True)

    def _default_recipe_metadata(self, graph: dict[str, Any], graph_hash: str, metadata: dict[str, Any]) -> dict[str, Any]:
        name = str(graph.get("name") or "Codex AI Workflow")
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "codex_workflow"
        required_tools = sorted({str(node.get("tool_name", "")).strip() for node in graph.get("nodes", []) if str(node.get("tool_name", "")).strip()})
        base = {
            "recipe_id": f"recipe:{safe}",
            "display_name": name,
            "version": "1.0.0",
            "graph_hash": graph_hash,
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {"type": "object", "properties": {}},
            "required_tools": required_tools or ["workflow_runtime"],
            "risk_profile": "write" if required_tools else "read_only",
            "author": "Codex Blender Agent",
            "changelog": "Initial v0.10 workflow recipe publication.",
            "preview_image": "previews/workflow_recipe.png",
            "tests": [{"name": "compile", "state": "passed"}],
            "tags": ["workflow", "recipe", "ai-studio"],
            "catalog_path": "recipes/pipeline",
            "compatibility_range": {"addon_min": ADDON_VERSION, "blender_min": "4.5.0"},
        }
        base.update({key: value for key, value in metadata.items() if value not in (None, "", [], {})})
        base["graph_hash"] = graph_hash
        return base

    def _apply_workflow_patch_to_blender_graph(self, graph_name: str, operations: list[dict[str, Any]]) -> None:
        tree = create_workflow_graph(graph_name or "Codex AI Workflow", with_default_nodes=False)
        for operation in operations:
            op = str(operation.get("op", "")).strip().lower().replace("-", "_").replace(" ", "_")
            if op == "add_node":
                node_data = dict(operation.get("node", operation) or {})
                node_type = str(node_data.get("node_type") or operation.get("node_type") or "preview_tap")
                label = str(node_data.get("label") or node_data.get("name") or operation.get("label") or "")
                location = node_data.get("location") or operation.get("location")
                add_workflow_node(tree.name, node_type, label=label, location=tuple(location) if isinstance(location, (list, tuple)) and len(location) >= 2 else None)
                continue
            if op == "remove_node":
                node_name = str(operation.get("name") or operation.get("node_name") or "").strip()
                node = tree.nodes.get(node_name)
                if node is not None:
                    tree.nodes.remove(node)
                continue
            if op == "set_property":
                node_name = str(operation.get("name") or operation.get("node_name") or "").strip()
                key = str(operation.get("property") or operation.get("key") or "").strip()
                if node_name and key:
                    node = tree.nodes.get(node_name)
                    if node is not None:
                        value = operation.get("value")
                        if key in {"tool_name", "arguments_json", "memory_query", "status", "last_result", "last_error", "node_type", "approval_required"}:
                            set_workflow_node_config(tree.name, node_name, {key: value})
                        else:
                            node[key] = value
                continue
            if op == "move_node":
                node_name = str(operation.get("name") or operation.get("node_name") or "").strip()
                node = tree.nodes.get(node_name)
                location = operation.get("location", [])
                if node is not None and isinstance(location, (list, tuple)) and len(location) >= 2:
                    node.location.x = float(location[0])
                    node.location.y = float(location[1])
                continue
            if op == "add_link":
                link = dict(operation.get("link", operation) or {})
                connect_workflow_nodes(
                    tree.name,
                    str(link.get("from_node", "")),
                    str(link.get("from_socket", "Flow")),
                    str(link.get("to_node", "")),
                    str(link.get("to_socket", "Flow")),
                )
                continue
            if op == "remove_link":
                link = dict(operation.get("link", operation) or {})
                for existing in list(tree.links):
                    if (
                        existing.from_node.name == str(link.get("from_node", ""))
                        and existing.from_socket.name == str(link.get("from_socket", "Flow"))
                        and existing.to_node.name == str(link.get("to_node", ""))
                        and existing.to_socket.name == str(link.get("to_socket", "Flow"))
                    ):
                        tree.links.remove(existing)
                continue
            if op == "wrap_as_recipe":
                tree["recipe_wrap_requested"] = True

    def _sync_studio_items(self, window_manager: bpy.types.WindowManager) -> None:
        context = bpy.context
        store = self._dashboard_store(context)
        active_project_id = self._active_project_id(context)

        chips = self._build_context_chips(context)
        window_manager.codex_blender_context_chips.clear()
        for chip in chips:
            entry = window_manager.codex_blender_context_chips.add()
            entry.chip_id = chip.get("chip_id", "")
            entry.label = chip.get("label", "")
            entry.value = chip.get("value", "")
            entry.kind = chip.get("kind", "")
            entry.detail = chip.get("detail", "")
            entry.enabled = bool(chip.get("enabled", True))

        window_manager.codex_blender_action_cards.clear()
        for card in store.list_action_cards(project_id=active_project_id)[:30]:
            entry = window_manager.codex_blender_action_cards.add()
            entry.action_id = card.get("action_id", "")
            entry.title = card.get("title", "")
            entry.kind = card.get("kind", "")
            entry.tool_name = card.get("tool_name", "")
            entry.status = card.get("status", "")
            entry.risk = card.get("risk", "")
            entry.risk_rationale = card.get("risk_rationale", "")
            entry.approval_policy = card.get("approval_policy", "")
            entry.affected_targets = ", ".join(card.get("affected_targets", []))
            entry.required_context = ", ".join(card.get("required_context", []))
            entry.scope_summary = card.get("scope_summary", "")
            entry.outcome_summary = card.get("outcome_summary", "")
            entry.preview_summary = card.get("preview_summary", "")
            entry.plan_preview = card.get("plan_preview", "")
            entry.tool_activity = card.get("tool_activity", "")
            entry.warnings = ", ".join(card.get("warnings", []))
            entry.result_summary = card.get("result_summary", "")
            entry.recovery = card.get("recovery", "")
            entry.thread_id = card.get("thread_id", "")
            entry.updated_at = card.get("updated_at", "")
            entry.approval_required = bool(card.get("approval_required", False))

        window_manager.codex_blender_pinned_outputs.clear()
        for output in store.list_pinned_outputs(project_id=active_project_id, limit=30):
            entry = window_manager.codex_blender_pinned_outputs.add()
            entry.output_id = output.get("output_id", "")
            entry.title = output.get("title", "")
            entry.kind = output.get("kind", "")
            entry.summary = output.get("summary", "")
            entry.source_thread_id = output.get("source_thread_id", "")
            entry.action_id = output.get("action_id", "")
            entry.path = output.get("path", "")
            entry.updated_at = output.get("updated_at", "")

        window_manager.codex_blender_job_timeline.clear()
        for event in store.list_job_timeline(project_id=active_project_id, limit=30):
            entry = window_manager.codex_blender_job_timeline.add()
            entry.event_id = event.get("event_id", "")
            entry.label = event.get("label", "")
            entry.status = event.get("status", "")
            entry.detail = event.get("detail", "")
            entry.created_at = event.get("created_at", "")

    @staticmethod
    def _preferences(context: bpy.types.Context):
        return get_addon_preferences(context, fallback=True)


_RUNTIME: BlenderAddonRuntime | None = None
_TIMER_REGISTERED = False
_AUTO_SETUP_TIMER_REGISTERED = False
_WEB_CONSOLE_AUTO_START_TIMER_REGISTERED = False


def get_runtime() -> BlenderAddonRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = BlenderAddonRuntime()
    return _RUNTIME


def _workflow_graph_id(name: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in (name or "workflow")).strip("_")
    while "__" in safe:
        safe = safe.replace("__", "_")
    return f"workflow:{safe or 'codex_ai_workflow'}"


def build_workflow_preview_summary(preview: dict[str, Any]) -> str:
    steps = preview.get("preview_steps") or preview.get("steps") or []
    blocked = sum(1 for step in steps if step.get("blocked") or step.get("requires_action_card"))
    warnings = len(preview.get("validation", {}).get("warnings", []) or [])
    if blocked:
        return f"Workflow preview prepared {len(steps)} step(s); {blocked} step(s) require action-card approval."
    if warnings:
        return f"Workflow preview prepared {len(steps)} step(s) with {warnings} warning(s)."
    return f"Workflow preview prepared {len(steps)} safe step(s)."


def _latest_pass(run: dict[str, Any]) -> dict[str, Any]:
    passes = list(run.get("passes", []) or []) if isinstance(run, dict) else []
    latest = passes[-1] if passes and isinstance(passes[-1], dict) else {}
    return dict(latest)


def _web_phase_label(phase: str, *, recovering: bool = False) -> str:
    if recovering:
        return "RECONNECTING"
    return {
        PHASE_CREATOR_RUNNING: "CREATING",
        PHASE_CAPTURING: "VERIFYING GEOMETRY / SCREENSHOTTING",
        PHASE_CRITIC_RUNNING: "CRITIQUING",
        "planning_next": "PATCHING",
        PHASE_COMPLETE: "DONE",
        PHASE_STOPPED: "NEEDS ATTENTION",
        PHASE_FAILED: "NEEDS ATTENTION",
        "idle": "READY",
    }.get(phase, str(phase or "READY").replace("_", " ").upper())


def _web_screenshots(run: dict[str, Any], latest_pass: dict[str, Any], capture: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    output: list[dict[str, Any]] = []
    passes = list(run.get("passes", []) or []) if isinstance(run, dict) else []

    def add_capture(
        *,
        item: dict[str, Any],
        view_scores: dict[str, dict[str, Any]],
        pass_index: int,
        pass_id: str,
        pass_phase: str,
        pass_score: Any,
        source: str,
    ) -> None:
        if not isinstance(item, dict):
            return
        path = str(item.get("path", "") or "")
        view_id = str(item.get("view_id", item.get("id", item.get("label", ""))) or "")
        label = str(item.get("label", view_id or f"view_{pass_index:02d}"))
        key = (path, view_id or label, str(pass_index))
        if key in seen:
            return
        seen.add(key)
        score = view_scores.get(view_id, {})
        output.append(
            {
                "index": len(output) + 1,
                "path": path,
                "view_id": view_id or label,
                "label": label,
                "kind": str(item.get("kind", score.get("kind", ""))),
                "method": str(item.get("method", "")),
                "score": item.get("score", score.get("score", "")),
                "score_components": score.get("score_components", {}),
                "notes": str(item.get("notes", "")),
                "viewpoint": item.get("viewpoint", {}),
                "pass_index": pass_index,
                "pass_id": pass_id,
                "phase": pass_phase,
                "pass_score": pass_score,
                "source": source,
            }
        )

    for pass_index, pass_data in enumerate(passes, start=1):
        if not isinstance(pass_data, dict):
            continue
        pass_id = str(pass_data.get("pass_id", pass_data.get("id", f"pass_{pass_index:02d}")))
        pass_phase = str(pass_data.get("phase", pass_data.get("phase_label", "")))
        pass_score = pass_data.get("score", pass_data.get("current_score", ""))
        pass_view_scores = {
            str(item.get("id", "")): dict(item)
            for item in list(pass_data.get("view_scores", []) or [])
            if isinstance(item, dict)
        }
        captures = list(pass_data.get("screenshots", []) or [])
        capture_payload = pass_data.get("capture", {})
        if isinstance(capture_payload, dict):
            captures.extend(list(capture_payload.get("captures", []) or []))
        if not captures:
            captures = [{"path": path} for path in list(pass_data.get("screenshot_paths", []) or [])]
        for item in captures:
            if isinstance(item, dict):
                add_capture(
                    item=item,
                    view_scores=pass_view_scores,
                    pass_index=pass_index,
                    pass_id=pass_id,
                    pass_phase=pass_phase,
                    pass_score=pass_score,
                    source="pass",
                )

    if not output:
        captures = list(capture.get("captures", []) or [])
        if not captures:
            captures = [{"path": path} for path in latest_pass.get("screenshots", []) or []]
        view_scores = {
            str(item.get("id", "")): dict(item)
            for item in list(latest_pass.get("view_scores", capture.get("view_scores", [])) or [])
            if isinstance(item, dict)
        }
        pass_index = int(latest_pass.get("iteration", latest_pass.get("pass_index", 0)) or 0) or 1
        for item in captures:
            if isinstance(item, dict):
                add_capture(
                    item=item,
                    view_scores=view_scores,
                    pass_index=pass_index,
                    pass_id=str(latest_pass.get("pass_id", latest_pass.get("id", f"pass_{pass_index:02d}"))),
                    pass_phase=str(latest_pass.get("phase", latest_pass.get("phase_label", ""))),
                    pass_score=latest_pass.get("score", latest_pass.get("current_score", "")),
                    source="latest",
                )

    return output


def _web_timeline(run: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = list(run.get("timeline", []) or []) if isinstance(run, dict) else []
    if timeline:
        return [dict(item) for item in timeline if isinstance(item, dict)]
    rows = []
    for item in run.get("passes", []) or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "phase": "pass",
                "status": "completed",
                "summary": item.get("summary", ""),
                "iteration": item.get("iteration", 0),
                "score": item.get("score", 0.0),
                "ended_at": item.get("recorded_at", ""),
            }
        )
    return rows


def _web_checks(
    validation: dict[str, Any],
    latest_pass: dict[str, Any],
    capture: dict[str, Any],
    *,
    screenshots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    issues = list(validation.get("issues", []) or latest_pass.get("validation_issues", []) or capture.get("validation_issues", []) or [])
    screenshot_rows = list(screenshots or [])
    issue_types: dict[str, int] = {}
    critical = 0
    high = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get("type", "unknown"))
        issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
        severity = str(issue.get("severity", ""))
        critical += 1 if severity == "critical" else 0
        high += 1 if severity == "high" else 0
    checks = [
        {"id": "evaluated_geometry", "label": "Evaluated geometry snapshot", "status": "done" if validation else "waiting", "count": int(validation.get("object_count", 0) or 0)},
        {"id": "view_planning", "label": "PCA/Fibonacci/Halton view planning", "status": "done" if latest_pass.get("view_scores") or capture.get("view_scores") else "waiting", "count": len(latest_pass.get("view_scores", capture.get("view_scores", [])) or [])},
        {"id": "validation_issues", "label": "Validation issues", "status": "blocked" if critical else ("warn" if high or issues else "ok"), "count": len(issues)},
        {"id": "screenshots", "label": "Viewport screenshots", "status": "done" if screenshot_rows else "waiting", "count": len(screenshot_rows)},
    ]
    for issue_type, count in sorted(issue_types.items()):
        status = "blocked" if issue_type in {"interpenetration", "containment_risk", "castle_battlement_intersection", "castle_zone_violation"} else "warn"
        checks.append({"id": f"issue_{issue_type}", "label": issue_type.replace("_", " "), "status": status, "count": count})
    return checks


def _json_safe_web(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_web(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_web(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _timer_callback() -> float:
    get_runtime().pump()
    return 0.25


def register_timer() -> None:
    global _TIMER_REGISTERED
    if _TIMER_REGISTERED:
        return
    bpy.app.timers.register(_timer_callback, persistent=True)
    _TIMER_REGISTERED = True
    register_auto_workspace_setup()
    schedule_web_console_auto_start()


def unregister_timer() -> None:
    global _TIMER_REGISTERED, _AUTO_SETUP_TIMER_REGISTERED, _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED
    runtime = get_runtime()
    runtime.stop_web_console(bpy.context if getattr(bpy, "context", None) is not None else None)
    runtime.stop()
    if _TIMER_REGISTERED and bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.unregister(_timer_callback)
    _TIMER_REGISTERED = False
    if _AUTO_SETUP_TIMER_REGISTERED and bpy.app.timers.is_registered(_auto_setup_timer):
        bpy.app.timers.unregister(_auto_setup_timer)
    _AUTO_SETUP_TIMER_REGISTERED = False
    if _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED and bpy.app.timers.is_registered(_web_console_auto_start_timer):
        bpy.app.timers.unregister(_web_console_auto_start_timer)
    _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED = False
    if _load_post_auto_setup in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_auto_setup)


def register_auto_workspace_setup() -> None:
    # v0.9 keeps AI workspaces opt-in. The handler remains for users who
    # explicitly re-enable the legacy preference, but it no longer creates
    # or switches workspaces by default on add-on registration.
    if _load_post_auto_setup not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_auto_setup)
    schedule_auto_workspace_setup()


def schedule_auto_workspace_setup() -> None:
    global _AUTO_SETUP_TIMER_REGISTERED
    if _AUTO_SETUP_TIMER_REGISTERED:
        return
    bpy.app.timers.register(_auto_setup_timer, first_interval=0.5, persistent=True)
    _AUTO_SETUP_TIMER_REGISTERED = True


def schedule_web_console_auto_start() -> None:
    global _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED
    if _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED:
        return
    bpy.app.timers.register(_web_console_auto_start_timer, first_interval=0.75, persistent=True)
    _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED = True


def _web_console_auto_start_timer() -> float | None:
    global _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED
    context = bpy.context
    if getattr(context, "window", None) is None or getattr(context, "window_manager", None) is None:
        return 0.5
    runtime = get_runtime()
    try:
        preferences = get_addon_preferences(context, fallback=True)
        if getattr(preferences, "web_console_auto_start", True):
            runtime.start_web_console(context, auto_started=True)
        else:
            runtime.record_automation_event(
                context,
                actor="web_console",
                phase="web_console_auto_start_skipped",
                status="skipped",
                label="WEB CONSOLE AUTO START SKIPPED",
                summary="Auto-start is disabled in add-on preferences.",
                update_cache=False,
            )
    except Exception as exc:
        runtime.record_automation_event(
            context,
            actor="web_console",
            phase="web_console_start_failed",
            status="failed",
            label="WEB CONSOLE START FAILED",
            summary=str(exc),
            update_cache=False,
        )
        try:
            context.window_manager.codex_blender_web_console_error = str(exc)
        except Exception:
            pass
        print(f"Codex Blender Agent web console auto-start failed: {exc}")
    _WEB_CONSOLE_AUTO_START_TIMER_REGISTERED = False
    return None


def _auto_setup_timer() -> float | None:
    global _AUTO_SETUP_TIMER_REGISTERED
    context = bpy.context
    if getattr(context, "window", None) is None:
        return 0.5
    try:
        preferences = get_addon_preferences(context, fallback=True)
        if getattr(preferences, "auto_setup_dashboard_workspace", False):
            get_runtime().setup_dashboard_workspace(context)
    except Exception as exc:
        print(f"Codex Blender Agent dashboard setup failed: {exc}")
    _AUTO_SETUP_TIMER_REGISTERED = False
    return None


@persistent
def _load_post_auto_setup(_dummy) -> None:
    schedule_auto_workspace_setup()
    schedule_web_console_auto_start()


def _tool_success(text: str) -> dict[str, Any]:
    return {"success": True, "contentItems": [{"type": "inputText", "text": text}]}


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)


def _preview(text: str, limit: int = 320) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)] + "..."


def _title_for_intent(intent: str, prompt: str) -> str:
    prefix = {
        "ask": "Ask about",
        "inspect": "Inspect",
        "change": "Change",
        "automate": "Automate",
        "recover": "Recover",
        "export": "Export",
    }.get(intent or "change", "Review")
    return f"{prefix}: {compact_text(prompt, 54)}" if prompt else f"{prefix} AI action"


def _tool_step_record(
    tool_name: str,
    phase: str,
    status: str,
    arguments: dict[str, Any],
    *,
    started: float | None = None,
    result: Any = None,
    error: str = "",
) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    elapsed = 0.0 if started is None else max(time.perf_counter() - started, 0.0)
    record = {
        "tool": tool_name,
        "phase": phase,
        "status": status,
        "arguments_summary": summarize_arguments(arguments),
        "started_at": now,
        "ended_at": now if status in {"completed", "failed"} else "",
        "duration_seconds": round(elapsed, 3),
        "rollback_available": True,
    }
    if result is not None:
        record["summary"] = compact_text(str(result), 260)
    if error:
        record["error"] = compact_text(error, 260)
        record["summary"] = compact_text(error, 260)
    return record


def _require_online_access() -> None:
    if getattr(bpy.app, "online_access", True):
        return
    raise RuntimeError("Blender online access is disabled. Enable online access before starting the Codex service.")
