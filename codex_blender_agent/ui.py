from __future__ import annotations

import textwrap

import bpy
from bpy.types import Panel, UIList

from .constants import ADDON_VERSION
from .quick_prompts import CATEGORY_LABELS, list_quick_prompts
from .service_errors import normalize_service_error
from .studio_state import action_status_label, risk_label
from .tutorial import current_step, get_walkthrough, progress_label
from .visual_tokens import (
    CardAction,
    empty_state,
    empty_state_payload,
    orientation_payload,
    primary_action_for_card,
    risk_token,
    secondary_actions_for_card,
    state_meta,
    status_copy,
    status_token,
    token,
)


def _message_title(role: str, phase: str, status: str) -> str:
    if role == "assistant" and phase:
        return f"Assistant ({phase})"
    if role == "tool":
        return f"Tool ({status})"
    if role == "user":
        return "You"
    return role.title()


def _compact_text(text: str, limit: int = 72) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _draw_wrapped_text(layout: bpy.types.UILayout, text: str, width: int = 74) -> None:
    if not text:
        layout.label(text="")
        return
    for paragraph in text.splitlines() or [""]:
        wrapped = textwrap.wrap(paragraph, width=width) or [""]
        for line in wrapped:
            layout.label(text=line)


def _draw_status_badge(layout: bpy.types.UILayout, label: str, token_key: str) -> None:
    visual = token(token_key)
    row = layout.row(align=True)
    row.alert = visual.alert
    row.label(text=label or visual.label, icon=visual.icon)


def _draw_guided_empty_state(layout: bpy.types.UILayout, surface: str, title: str) -> None:
    box = layout.box()
    payload = empty_state_payload(surface)
    _draw_status_badge(box, title or payload.title, "info")
    _draw_wrapped_text(box, payload.purpose, width=92)
    _draw_wrapped_text(box, payload.reason, width=92)
    row = box.row(align=True)
    if payload.next_action.lower().startswith("ask"):
        row.operator("codex_blender_agent.explain_current_context", text=payload.next_action, icon="TEXT")
    elif payload.next_action.lower().startswith("inspect"):
        row.operator("codex_blender_agent.inspect_ai_context", text=payload.next_action, icon="VIEWZOOM")
    elif payload.next_action.lower().startswith("preview"):
        row.operator("codex_blender_agent.preview_workflow_graph", text=payload.next_action, icon="HIDE_OFF")
    elif payload.next_action.lower().startswith("refresh"):
        row.operator("codex_blender_agent.refresh_assets", text=payload.next_action, icon="FILE_REFRESH")
    elif payload.next_action.lower().startswith("create"):
        row.operator("codex_blender_agent.create_action_from_prompt", text=payload.next_action, icon="TEXT")
    else:
        row.operator("codex_blender_agent.open_studio_workspace", text=payload.next_action, icon="WORKSPACE")
    if payload.tip:
        _draw_wrapped_text(box, f"Tip: {payload.tip}", width=92)


def _draw_orientation_strip(layout: bpy.types.UILayout, context: bpy.types.Context, surface: str, *, compact: bool = False) -> None:
    payload = orientation_payload(context, surface)
    box = layout.box()
    col = box.column(align=True)
    row = col.row(align=True)
    row.label(text=_compact_text(str(payload["location"]), 72 if not compact else 46), icon="INFO")
    if not compact:
        row.label(text=f"Scope: {payload['scope']}", icon="HIDE_OFF")
    col.label(text=f"AI sees: {_compact_text(str(payload['sees']), 92 if not compact else 48)}", icon="HIDE_OFF")
    row = col.row(align=True)
    if payload["running"]:
        row.label(text=f"Running: {_compact_text(str(payload['running']), 48)}", icon="TIME")
    else:
        row.label(text="Ready", icon="INFO")
    row.label(text=f"Pending review: {payload['review_count']}", icon="QUESTION")
    row.label(text=f"Changed: {payload['changed_count']}", icon="FILE_REFRESH")
    if payload["undo_available"]:
        row.operator("codex_blender_agent.undo_last_ai_change", text="Undo last change", icon="FILE_REFRESH")
    if payload["progress"] and payload["running"] and hasattr(col, "progress"):
        col.progress(factor=min(max(float(payload["progress"]), 0.0), 1.0), type="BAR", text=f"Running: {_compact_text(str(payload['running']), 56)}")
    if payload["error"]:
        error = col.box()
        severity = str(getattr(window_manager, "codex_blender_error_severity", "") or "failed")
        error.alert = severity not in {"reconnecting", "warning"}
        error.label(text="Reconnecting" if severity == "reconnecting" else "Failed", icon="FILE_REFRESH" if severity == "reconnecting" else "ERROR")
        _draw_wrapped_text(error, _friendly_error(str(payload["error"])), width=72 if compact else 96)


def _friendly_error(error_text: str) -> str:
    text = " ".join((error_text or "").split())
    if not text:
        return "The action failed. Review details and try again."
    if any(marker in text.lower() for marker in ("responsestreamdisconnected", "reconnecting", "websocket closed", "stream disconnected")):
        friendly = normalize_service_error(text)
        return f"{friendly.title}: {friendly.summary}"
    if "Traceback" in text or "KeyError" in text or "Exception" in text:
        return "The action failed before it could complete. Open details, fix the reported input, then retry."
    return text


_AUTOMATION_PHASE_LABELS = {
    "idle": "READY",
    "creator_running": "CREATING",
    "capturing": "SCREENSHOTTING",
    "critic_running": "CRITIQUING",
    "planning_next": "PATCHING",
    "complete": "DONE",
    "stopped": "STOPPED",
    "failed": "NEEDS ATTENTION",
}

_AUTOMATION_RUNNING_PHASES = {"creator_running", "capturing", "critic_running", "planning_next"}


def _automation_phase_label(phase: str) -> str:
    return _AUTOMATION_PHASE_LABELS.get(str(phase or "idle"), str(phase or "idle").replace("_", " ").upper())


def _draw_error_status(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, compact: bool = False) -> None:
    message = str(getattr(window_manager, "codex_blender_error", "") or "")
    if not message:
        return
    severity = str(getattr(window_manager, "codex_blender_error_severity", "") or "failed")
    title = str(getattr(window_manager, "codex_blender_error_title", "") or ("RECONNECTING" if severity == "reconnecting" else "NEEDS ATTENTION"))
    recovery = str(getattr(window_manager, "codex_blender_error_recovery", "") or "")
    box = layout.box()
    box.alert = severity not in {"reconnecting", "warning"}
    icon = "FILE_REFRESH" if severity == "reconnecting" else "ERROR"
    box.label(text=title, icon=icon)
    _draw_wrapped_text(box, message, width=72 if compact else 92)
    if recovery:
        _draw_wrapped_text(box, f"Next: {recovery}", width=72 if compact else 92)
    row = box.row(align=True)
    row.operator("codex_blender_agent.login", text="Login / Re-login", icon="URL")
    row.operator("codex_blender_agent.refresh_state", text="Refresh", icon="FILE_REFRESH")
    row.operator("codex_blender_agent.start_service", text="Restart Service", icon="PLAY")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        raw = str(getattr(window_manager, "codex_blender_error_raw", "") or "")
        if raw and raw != message:
            detail = box.box()
            detail.label(text="Raw details (Advanced)", icon="TEXT")
            _draw_wrapped_text(detail, _compact_text(raw, 420), width=72 if compact else 92)


def _draw_login_status_card(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, compact: bool = False) -> None:
    account = str(getattr(window_manager, "codex_blender_account", "") or "")
    plan = str(getattr(window_manager, "codex_blender_plan", "") or "")
    connection = str(getattr(window_manager, "codex_blender_connection", "") or "")
    if account:
        row = layout.box().row(align=True)
        label = f"Logged in: {_compact_text(account, 44 if compact else 72)}"
        if plan:
            label += f" ({plan})"
        row.label(text=label, icon="CHECKMARK")
        row.operator("codex_blender_agent.login", text="Re-login", icon="URL")
        row.operator("codex_blender_agent.refresh_state", text="Refresh", icon="FILE_REFRESH")
        return
    box = layout.box()
    box.label(text="ACCOUNT NEEDED", icon="USER")
    _draw_wrapped_text(
        box,
        "If castle creation keeps reconnecting or failing, first confirm the Codex app-server is running and ChatGPT login is complete.",
        width=72 if compact else 92,
    )
    if connection:
        box.label(text=f"Connection: {_compact_text(connection, 72 if compact else 92)}")
    row = box.row(align=True)
    row.operator("codex_blender_agent.login", text="Login / Re-login", icon="URL")
    row.operator("codex_blender_agent.start_service", text="Start Service", icon="PLAY")
    row.operator("codex_blender_agent.refresh_state", text="Refresh", icon="FILE_REFRESH")


def _draw_install_and_web_console_status(layout: bpy.types.UILayout, context: bpy.types.Context, *, compact: bool = False) -> None:
    window_manager = context.window_manager
    box = layout.box()
    header = box.row(align=True)
    header.label(text=f"Installed add-on: v{ADDON_VERSION}", icon="CHECKMARK")
    header.label(text=f"Port: {int(getattr(window_manager, 'codex_blender_web_console_port', 0) or 0)}")
    auto_started = bool(getattr(window_manager, "codex_blender_web_console_auto_started", False))
    header.label(text="Auto web: on" if auto_started else "Auto web: ready", icon="WORLD")
    row = box.row(align=True)
    running = bool(getattr(window_manager, "codex_blender_web_console_running", False))
    if running:
        row.operator("codex_blender_agent.open_web_console", text="Open Web Console", icon="URL")
        row.operator("codex_blender_agent.stop_web_console", text="Stop Web Console", icon="CANCEL")
        url = str(getattr(window_manager, "codex_blender_web_console_url", "") or "")
        if url:
            box.label(text=_compact_text(url, 72 if compact else 110), icon="WORLD")
    else:
        row.operator("codex_blender_agent.start_web_console", text="Start Web Console", icon="WORLD")
        row.operator("codex_blender_agent.open_web_console", text="Start + Open", icon="URL")
    error = str(getattr(window_manager, "codex_blender_web_console_error", "") or "")
    if error:
        alert = box.row()
        alert.alert = True
        alert.label(text=_compact_text(error, 92), icon="ERROR")


def _draw_automation_status_panel(layout: bpy.types.UILayout, context: bpy.types.Context, *, compact: bool = False) -> None:
    window_manager = context.window_manager
    active_visual_run = str(getattr(window_manager, "codex_blender_visual_review_active_run_id", "") or "")
    visual_phase = str(getattr(window_manager, "codex_blender_visual_review_phase", "idle") or "idle")
    stream_recovering = bool(getattr(window_manager, "codex_blender_stream_recovering", False))
    pending = bool(getattr(window_manager, "codex_blender_pending", False))
    auto_enabled = bool(getattr(window_manager, "codex_blender_visual_review_auto_after_scene_change", True))
    active = stream_recovering or pending or (active_visual_run and visual_phase not in {"idle"})

    box = layout.box()
    header = box.row(align=True)
    if stream_recovering:
        header.label(text=str(getattr(window_manager, "codex_blender_error_title", "") or "RECONNECTING"), icon="FILE_REFRESH")
    elif active:
        phase_label = _automation_phase_label(visual_phase if active_visual_run else "creator_running")
        header.label(text=f"ACTIVE: {phase_label}", icon="CHECKMARK")
    elif auto_enabled:
        header.label(text="AUTO REVIEW READY", icon="CHECKMARK")
    else:
        header.label(text="AUTO REVIEW OFF", icon="INFO")

    if active_visual_run and visual_phase not in {"idle"}:
        pass_count = int(getattr(window_manager, "codex_blender_visual_review_current_pass", 0) or 0)
        max_passes = int(getattr(window_manager, "codex_blender_visual_review_max_iterations", 5) or 5)
        score = float(getattr(window_manager, "codex_blender_visual_review_current_score", 0.0) or 0.0)
        auto_started = bool(getattr(window_manager, "codex_blender_visual_review_auto_started", False))
        box.label(text=("Automatic scene review" if auto_started else "Manual visual review"), icon="CAMERA_DATA")
        box.label(text=f"{_automation_phase_label(visual_phase)} - pass {pass_count} / {max_passes} - score {score:.2f}")
        issue_count = int(getattr(window_manager, "codex_blender_asset_validation_latest_issue_count", 0) or 0)
        critical_count = int(getattr(window_manager, "codex_blender_asset_validation_latest_critical_count", 0) or 0)
        validation_score = float(getattr(window_manager, "codex_blender_asset_validation_latest_score", 0.0) or 0.0)
        if validation_score or issue_count or critical_count:
            box.label(text=f"VERIFYING: validation {validation_score:.1f}/100 - issues {issue_count} - critical {critical_count}", icon="VIEWZOOM")
        validation_summary = str(getattr(window_manager, "codex_blender_asset_validation_latest_summary", "") or "")
        if validation_summary:
            _draw_wrapped_text(box, _compact_text(validation_summary, 160), width=72 if compact else 92)
        row = box.row(align=True)
        if visual_phase in _AUTOMATION_RUNNING_PHASES:
            row.operator("codex_blender_agent.stop_visual_review_loop", text="Stop", icon="CANCEL")
        else:
            row.operator("codex_blender_agent.continue_visual_review_loop", text="Continue", icon="PLAY")
        row.operator("codex_blender_agent.open_web_console", text="Web Console", icon="URL")
        row.operator("codex_blender_agent.open_visual_review_run", text="Open run details", icon="FILE_FOLDER")
        qa = box.row(align=True)
        qa.operator("codex_blender_agent.validate_asset_now", text="VERIFY Now", icon="VIEWZOOM")
        qa.operator("codex_blender_agent.show_qa_overlays", text="Show QA", icon="OVERLAY").visible = True
        qa.operator("codex_blender_agent.show_qa_overlays", text="Hide QA", icon="HIDE_ON").visible = False
        qa.operator("codex_blender_agent.apply_safe_asset_repair", text="Safe Repair Plan", icon="TOOL_SETTINGS")
    elif pending:
        box.label(text=_compact_text(window_manager.codex_blender_activity or "Codex is working.", 120), icon="TIME")
        box.label(text="Pipeline: CREATING -> VERIFYING GEOMETRY -> SCREENSHOTTING -> CRITIQUING -> PATCHING")
        row = box.row(align=True)
        row.operator("codex_blender_agent.stop_turn", text="Stop", icon="CANCEL")
        row.operator("codex_blender_agent.open_web_console", text="Web Console", icon="URL")
    elif auto_enabled:
        box.label(text="Scene-changing Send starts the automatic creator -> VERIFYING -> critic loop.")
        row = box.row(align=True)
        row.operator("codex_blender_agent.validate_asset_now", text="VERIFY Now", icon="VIEWZOOM")
        row.operator("codex_blender_agent.open_web_console", text="Web Console", icon="URL")
    else:
        box.label(text="Manual review is available from Advanced.")

    _draw_error_status(box, window_manager, compact=compact)


def _draw_status(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    status = layout.box()
    row = status.row(align=True)
    connection_token = "running" if window_manager.codex_blender_pending else "success" if "stopped" not in window_manager.codex_blender_connection.lower() else "muted"
    visual = token(connection_token)
    row.label(text=window_manager.codex_blender_connection, icon=visual.icon)
    if window_manager.codex_blender_pending:
        row.operator("codex_blender_agent.stop_turn", text="Stop Turn", icon="CANCEL")
    row.operator("codex_blender_agent.pause_transcript_redraw", text="Pause" if not window_manager.codex_blender_redraw_paused else "Resume")
    row.operator("codex_blender_agent.open_studio_workspace", text="AI Studio", icon="WORKSPACE")
    row.operator("codex_blender_agent.refresh_dashboard", text="", icon="FILE_REFRESH")
    if window_manager.codex_blender_dashboard_busy:
        status.prop(window_manager, "codex_blender_dashboard_progress", text="Progress", slider=True)
    if window_manager.codex_blender_account:
        account_line = window_manager.codex_blender_account
        if window_manager.codex_blender_plan:
            account_line = f"{account_line} ({window_manager.codex_blender_plan})"
        status.label(text=account_line)
    if window_manager.codex_blender_thread:
        status.label(text=f"Thread: {window_manager.codex_blender_thread}")
    if window_manager.codex_blender_activity:
        status.label(text="Activity:")
        _draw_wrapped_text(status, window_manager.codex_blender_activity, width=90)
    _draw_error_status(layout, window_manager)


def _draw_tutorial_card(layout: bpy.types.UILayout, context: bpy.types.Context, *, compact: bool = False) -> None:
    window_manager = context.window_manager
    if window_manager.codex_blender_tutorial_completed and not window_manager.codex_blender_show_tutorial:
        row = layout.row(align=True)
        row.operator("codex_blender_agent.open_tutorial", text="Tutorial", icon="INFO")
        row.operator("codex_blender_agent.open_quickstart_doc", text="Quickstart", icon="TEXT")
        return
    if not window_manager.codex_blender_show_tutorial:
        row = layout.row(align=True)
        row.operator("codex_blender_agent.open_tutorial", text="Show Tutorial", icon="INFO")
        row.operator("codex_blender_agent.open_quickstart_doc", text="Quickstart", icon="TEXT")
        return

    walkthrough = get_walkthrough(window_manager.codex_blender_tutorial_walkthrough)
    step = current_step(window_manager.codex_blender_tutorial_walkthrough, window_manager.codex_blender_tutorial_step)
    box = layout.box()
    header = box.row(align=True)
    header.label(text=f"Tutorial: {walkthrough.title}", icon="INFO")
    header.operator("codex_blender_agent.complete_tutorial", text="", icon="CANCEL")
    box.prop(window_manager, "codex_blender_tutorial_walkthrough", text="")
    box.label(text=progress_label(window_manager.codex_blender_tutorial_walkthrough, window_manager.codex_blender_tutorial_step))
    _draw_status_badge(box, step.title, "accent")
    status_key = {
        "passed": "success",
        "failed": "danger",
        "running": "running",
    }.get(window_manager.codex_blender_tutorial_step_status, "muted")
    _draw_status_badge(box, f"Step Status: {window_manager.codex_blender_tutorial_step_status.title()}", status_key)
    if window_manager.codex_blender_tutorial_step_message:
        _draw_wrapped_text(box, window_manager.codex_blender_tutorial_step_message, width=72 if compact else 96)
    _draw_wrapped_text(box, step.body, width=72 if compact else 96)
    if not compact:
        detail = box.box()
        detail.label(text=f"Workspace: {step.workspace}", icon="WORKSPACE")
        detail.label(text=f"Do: {_compact_text(step.action, 96)}")
        detail.label(text=f"Expect: {_compact_text(step.expected, 96)}")
        detail.label(text=f"Recover: {_compact_text(step.recovery, 96)}")
    row = box.row(align=True)
    row.operator("codex_blender_agent.open_tutorial_target", text="Open Target", icon="WORKSPACE")
    row.operator("codex_blender_agent.run_tutorial_step", text="Run Step", icon="CHECKMARK")
    row.operator("codex_blender_agent.check_tutorial_step", text="Check", icon="VIEWZOOM")
    row.operator("codex_blender_agent.fix_tutorial_step", text="Fix Step", icon="TOOL_SETTINGS")
    row = box.row(align=True)
    row.operator("codex_blender_agent.previous_tutorial_step", text="Back")
    row.operator("codex_blender_agent.next_tutorial_step", text="Next")
    row.operator("codex_blender_agent.reset_tutorial", text="Reset")
    row.operator("codex_blender_agent.open_quickstart_doc", text="Quickstart", icon="TEXT")


def _draw_state_rail(layout: bpy.types.UILayout, context: bpy.types.Context, *, compact: bool = False) -> None:
    window_manager = context.window_manager
    box = layout.box()
    header = box.row(align=True)
    header.label(text="AI Studio")
    if window_manager.codex_blender_pending:
        header.operator("codex_blender_agent.stop_turn", text="Stop", icon="CANCEL")
    else:
        header.operator("codex_blender_agent.refresh_dashboard", text="", icon="FILE_REFRESH")

    project = window_manager.codex_blender_active_project_id or "Current Project"
    thread = window_manager.codex_blender_active_thread_id or "No active thread"
    selected_count = len(getattr(context, "selected_objects", []) or [])
    pending_actions = sum(1 for card in window_manager.codex_blender_action_cards if card.status in {"needs_clarification", "preview_ready", "preview_visible", "awaiting_approval", "approved", "running", "stopping", "paused"})

    box.label(text=f"Project: {_compact_text(project, 42)}")
    box.label(text=f"Thread: {_compact_text(thread, 42)}")
    box.label(text=f"Selected: {selected_count} object(s)")
    box.label(text=f"Pending Actions: {pending_actions}")
    box.prop(window_manager, "codex_blender_active_scope", text="Scope")

    row = box.row(align=True)
    row.operator("codex_blender_agent.open_studio_workspace", text="Studio", icon="WORKSPACE")
    row.operator("codex_blender_agent.open_workflow_workspace", text="Workflow", icon="NODETREE")
    row.operator("codex_blender_agent.open_assets_workspace", text="Assets", icon="ASSET_MANAGER")
    row = box.row(align=True)
    row.operator("codex_blender_agent.open_tutorial", text="Tutorial", icon="INFO")
    row.operator("codex_blender_agent.open_quickstart_doc", text="Quickstart", icon="TEXT")
    row = box.row(align=True)
    row.operator("codex_blender_agent.verify_workspace_suite", text="Health", icon="CHECKMARK")
    row.operator("codex_blender_agent.create_ai_workspaces", text="Create Suite", icon="WORKSPACE")
    row = box.row(align=True)
    row.operator("codex_blender_agent.create_action_from_prompt", text="Create Action", icon="TEXT")
    row.operator("codex_blender_agent.recover_action", text="Recover", icon="FILE_REFRESH")
    if not compact:
        box.label(text="State is visible here; details live in the AI workspaces.")


def _draw_context_pack(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, rows: int = 5) -> None:
    box = _draw_list_header(layout, "What AI sees", None, "VIEWZOOM")
    box.label(text="Enabled chips are sent. Disabled chips stay visible but excluded.")
    box.template_list(
        "CODEXBLENDERAGENT_UL_context_chips",
        "",
        window_manager,
        "codex_blender_context_chips",
        window_manager,
        "codex_blender_context_chip_index",
        rows=rows,
    )
    if len(window_manager.codex_blender_context_chips):
        index = window_manager.codex_blender_context_chip_index
        if index < 0:
            index = 0
        if 0 <= index < len(window_manager.codex_blender_context_chips):
            chip = window_manager.codex_blender_context_chips[index]
            detail = box.box()
            detail.label(text=f"{chip.label}: {chip.value}")
            if chip.detail:
                _draw_wrapped_text(detail, chip.detail, width=90)
            op = detail.operator("codex_blender_agent.toggle_context_chip", text="Disable" if chip.enabled else "Enable")
            op.chip_id = chip.chip_id
    else:
        _draw_guided_empty_state(box, "context_chips", "No visible context yet")


def _card_field(card: object, name: str, default: str = "") -> str:
    return str(getattr(card, name, default) or default)


def _card_summary(card: object) -> str:
    for field in ("outcome_summary", "result_summary", "preview_summary", "plan_preview", "risk_rationale"):
        value = _card_field(card, field)
        if value:
            return value
    return "Review scope, impact, and recovery before taking action."


def _draw_card_action(layout: bpy.types.UILayout, action: CardAction, card: object) -> None:
    row = layout.row(align=True)
    row.enabled = bool(action.enabled)
    operator = row.operator(action.operator, text=action.label, icon=action.icon)
    action_id = _card_field(card, "action_id")
    try:
        operator.action_id = action_id
    except Exception:
        pass
    if action.operator == "codex_blender_agent.pin_thread_output":
        try:
            operator.title = _card_field(card, "title") or "Pinned AI output"
            operator.summary = _card_field(card, "result_summary") or _card_field(card, "plan_preview") or _card_field(card, "title")
            operator.kind = _card_field(card, "kind", "result") or "result"
        except Exception:
            pass


def _draw_recovery_footer(layout: bpy.types.UILayout, card: object) -> None:
    recovery = _card_field(card, "recovery")
    if not recovery:
        status = _card_field(card, "status")
        if status in {"completed", "completed_with_warnings"}:
            recovery = "Use View changes, Pin result, or Undo last change if this is still the latest AI edit."
        elif status in {"failed", "stale"}:
            recovery = "Open details, recover the card, or regenerate the preview before approving."
        else:
            recovery = "Cancel before approval, Stop while running, or Recover after failure."
    footer = layout.box()
    footer.label(text="Recovery", icon="FILE_REFRESH")
    _draw_wrapped_text(footer, recovery, width=96)


def _draw_action_cards(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, rows: int = 6) -> None:
    box = _draw_list_header(layout, "Receipts and high-risk approvals", "codex_blender_agent.create_action_from_prompt", "TEXT")
    if len(window_manager.codex_blender_action_cards) == 0:
        _draw_guided_empty_state(box, "action_cards", "No receipts yet")
        return
    box.template_list(
        "CODEXBLENDERAGENT_UL_action_cards",
        "",
        window_manager,
        "codex_blender_action_cards",
        window_manager,
        "codex_blender_action_card_index",
        rows=rows,
    )
    index = window_manager.codex_blender_action_card_index
    if index < 0:
        index = 0
    if 0 <= index < len(window_manager.codex_blender_action_cards):
        card = window_manager.codex_blender_action_cards[index]
        detail = box.box()
        row = detail.row(align=True)
        meta = state_meta(card.status)
        row.alert = meta.alert
        row.label(text=status_copy(card.status), icon=meta.icon)
        if card.updated_at:
            row.label(text=_compact_text(card.updated_at, 32))
        detail.label(text=_compact_text(card.title or card.action_id or "AI action", 96))
        _draw_wrapped_text(detail, _card_summary(card), width=96)
        risk_visual = risk_token(card.risk)
        risk_row = detail.row(align=True)
        risk_row.alert = risk_visual.alert
        risk_row.label(text=f"{risk_label(card.risk)} risk", icon=risk_visual.icon)
        if card.approval_required:
            risk_row.label(text="Review required", icon="HIDE_OFF")
        if card.kind:
            detail.label(text=f"Kind: {card.kind.title()}")
        if card.tool_name:
            detail.label(text=f"Tool: {card.tool_name}")
        context_box = detail.box()
        context_box.label(text="Scope and context", icon="HIDE_OFF")
        if card.scope_summary:
            _draw_wrapped_text(context_box, f"Scope: {card.scope_summary}", width=96)
        elif card.affected_targets:
            context_box.label(text=f"Scope: {_compact_text(card.affected_targets, 86)}")
        if card.required_context:
            context_box.label(text=f"AI sees: {_compact_text(card.required_context, 86)}")
        if card.outcome_summary:
            detail.label(text="Outcome", icon="CHECKMARK")
            _draw_wrapped_text(detail, card.outcome_summary, width=96)
        if card.risk_rationale:
            detail.label(text="Impact", icon="FILE_REFRESH")
            _draw_wrapped_text(detail, card.risk_rationale, width=96)
        if card.approval_policy:
            detail.label(text=f"Approval: {_compact_text(card.approval_policy, 96)}")
        if card.preview_summary:
            detail.label(text="Preview", icon="HIDE_OFF")
            _draw_wrapped_text(detail, card.preview_summary, width=96)
        if card.plan_preview:
            detail.label(text="Plan", icon="TEXT")
            _draw_wrapped_text(detail, card.plan_preview, width=96)
        if card.tool_activity:
            detail.label(text="Tool activity", icon="TIME")
            _draw_wrapped_text(detail, card.tool_activity, width=96)
        if card.warnings:
            warn = detail.row()
            warn.alert = True
            warn.label(text=f"Warnings: {_compact_text(card.warnings, 96)}", icon="ERROR")
        if card.result_summary:
            detail.label(text="Result", icon="CHECKMARK")
            _draw_wrapped_text(detail, card.result_summary, width=96)
        primary = primary_action_for_card(card)
        _draw_card_action(detail, primary, card)
        secondary = detail.row(align=True)
        for action in secondary_actions_for_card(card):
            secondary.enabled = bool(action.enabled)
            operator = secondary.operator(action.operator, text=action.label, icon=action.icon)
            try:
                operator.action_id = card.action_id
            except Exception:
                pass
            if action.operator == "codex_blender_agent.pin_thread_output":
                try:
                    operator.title = card.title
                    operator.summary = card.result_summary or card.plan_preview or card.title
                    operator.kind = card.kind or "result"
                except Exception:
                    pass
        _draw_recovery_footer(detail, card)


def _draw_recent_outputs(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    box = _draw_list_header(layout, "Pinned Outputs", "codex_blender_agent.pin_thread_output", "PINNED")
    if len(window_manager.codex_blender_pinned_outputs) == 0:
        box.label(text="Pinned outputs survive transcript clutter.")
        box.label(text="Pin useful plans, results, assets, or explanations.")
        return
    box.template_list(
        "CODEXBLENDERAGENT_UL_pinned_outputs",
        "",
        window_manager,
        "codex_blender_pinned_outputs",
        window_manager,
        "codex_blender_pinned_output_index",
        rows=4,
    )


def _draw_job_timeline(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    box = _draw_list_header(layout, "Live Activity", None, "TIME")
    if window_manager.codex_blender_dashboard_busy:
        box.prop(window_manager, "codex_blender_dashboard_progress", text="Progress", slider=True)
    if len(window_manager.codex_blender_job_timeline) == 0:
        box.label(text="No AI jobs yet. This timeline shows what Codex is doing now.")
        if window_manager.codex_blender_activity:
            _draw_wrapped_text(box, window_manager.codex_blender_activity, width=96)
        return
    box.template_list(
        "CODEXBLENDERAGENT_UL_job_timeline",
        "",
        window_manager,
        "codex_blender_job_timeline",
        window_manager,
        "codex_blender_job_timeline_index",
        rows=5,
    )


def _draw_workflow_explainer(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = layout.box()
    _draw_status_badge(box, "Workflow: Chat -> Plan -> Graph -> Result", "workflow")
    selected_count = len(getattr(context, "selected_objects", []) or [])
    pending = [card for card in window_manager.codex_blender_action_cards if card.status in {"needs_clarification", "preview_ready", "preview_visible", "awaiting_approval", "approved", "running", "stopping", "paused"}]
    high_risk = [card for card in pending if card.risk == "high"]
    box.label(text=f"Current workspace: {getattr(context.window.workspace, 'name', 'Unknown') if context.window else 'Unknown'}")
    box.label(text=f"Active scope: {window_manager.codex_blender_active_scope}; selected objects: {selected_count}")
    box.label(text=f"What AI sees: {len(window_manager.codex_blender_context_chips)} visible context chip(s)")
    box.label(text="Next: ask AI to create, explain, or simplify the workflow.")
    risk_row = box.row(align=True)
    risk_row.alert = bool(high_risk)
    risk_row.label(text=f"Pending risk: {len(high_risk)} high-risk card(s)", icon="ERROR" if high_risk else "CHECKMARK")
    box.label(text="Recovery: Stop Turn, Blender Undo, receipt details, or workflow repair.")


def _draw_workflow_guide(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    box = layout.box()
    _draw_status_badge(box, "AI-managed workflow graph", "workflow")
    box.label(text="Start from chat. Let AI set up the graph, then inspect or edit nodes when useful.")
    box.label(text="New graphs are blank or unconnected by default; examples are explicit.")
    box.label(text="Use Shift+A for manual advanced editing inside the AI Workflow tree.")
    row = box.row(align=True)
    row.operator("codex_blender_agent.ai_setup_workflow", text="AI setup workflow", icon="NODETREE")
    row.operator("codex_blender_agent.create_blank_workflow_tree", text="Blank graph", icon="NODETREE")
    row.operator("codex_blender_agent.validate_workflow_graph", text="Validate graph", icon="CHECKMARK")
    row.operator("codex_blender_agent.preview_workflow_graph", text="Preview graph", icon="HIDE_OFF")
    if getattr(context.window_manager, "codex_blender_show_advanced_governance", False):
        row.operator("codex_blender_agent.start_workflow_run", text="Start workflow", icon="PLAY")
    examples = box.row(align=True)
    examples.label(text="Examples:")
    op = examples.operator("codex_blender_agent.create_example_workflow_graph", text="Scene Inspector")
    op.example_id = "scene_inspector"
    op = examples.operator("codex_blender_agent.create_example_workflow_graph", text="Castle")
    op.example_id = "safe_castle_blockout"
    op = examples.operator("codex_blender_agent.create_example_workflow_graph", text="Save Asset")
    op.example_id = "save_selection_asset"


def _draw_asset_guide(layout: bpy.types.UILayout) -> None:
    box = layout.box()
    _draw_status_badge(box, "Game asset fast lane", "asset")
    box.label(text="1. Ask AI to create, clean, variant, or export selected game assets")
    box.label(text="2. Use Assets for reusable library inspection and publishing")
    box.label(text="3. Keep package governance in Advanced unless you need it")
    box.operator("codex_blender_agent.create_game_asset_from_prompt", text="Create game asset", icon="ASSET_MANAGER")


def _draw_controls(layout: bpy.types.UILayout) -> None:
    controls = layout.box()
    row = controls.row(align=True)
    row.operator("codex_blender_agent.start_service", text="Start")
    row.operator("codex_blender_agent.stop_service", text="Stop Service")
    row.operator("codex_blender_agent.refresh_state", text="Refresh")
    row = controls.row(align=True)
    row.operator("codex_blender_agent.login", text="Login")
    row.operator("codex_blender_agent.new_thread", text="New Thread")
    row.operator("codex_blender_agent.open_studio_workspace", text="Studio")
    row.operator("codex_blender_agent.open_workflow_workspace", text="Workflow")
    row.operator("codex_blender_agent.open_assets_workspace", text="Assets")
    row = controls.row(align=True)
    row.operator("codex_blender_agent.diagnose_dashboard_workspace", text="Diagnose Workspace")
    row.operator("codex_blender_agent.open_dashboard_chat", text="Prompt Draft")


def _draw_options(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    options = layout.box()
    row = options.row(align=True)
    row.prop(window_manager, "codex_blender_chat_mode")
    row.prop(window_manager, "codex_blender_include_scene_context")
    row = options.row(align=True)
    row.prop(window_manager, "codex_blender_model")
    row.prop(window_manager, "codex_blender_effort")
    row = options.row(align=True)
    row.prop(window_manager, "codex_blender_show_transcript")
    row.prop(window_manager, "codex_blender_visible_message_count")
    row.prop(window_manager, "codex_blender_redraw_paused")
    options.operator("codex_blender_agent.clear_local_messages", text="Hide Current Messages")


def _draw_prompt(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    prompt_box = layout.box()
    prompt_box.label(text="Ask AI", icon="TEXT")
    intent = prompt_box.row(align=True)
    intent.prop(window_manager, "codex_blender_intent")
    intent.operator("codex_blender_agent.classify_prompt", text="Classify")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        safety = prompt_box.box()
        safety.label(text="Advanced governance")
        row = safety.row(align=True)
        row.prop(window_manager, "codex_blender_safety_preview_first", text="Preview First")
        row.prop(window_manager, "codex_blender_safety_non_destructive", text="Non-Destructive")
        row.prop(window_manager, "codex_blender_safety_no_deletes", text="No Deletes")
        row = safety.row(align=True)
        row.prop(window_manager, "codex_blender_safety_duplicate_first", text="Duplicate First")
        row.prop(window_manager, "codex_blender_safety_require_approval", text="Require Approval")
        row.prop(window_manager, "codex_blender_safety_stop_checkpoints", text="Stop At Checkpoints")
    prompt_box.prop(window_manager, "codex_blender_prompt", text="Prompt")
    prompt_box.prop(window_manager, "codex_blender_attachment_path", text="Attach")
    attachment_row = prompt_box.row(align=True)
    attachment_row.operator("codex_blender_agent.add_attachment", text="Add Attachment")
    attachment_row.operator("codex_blender_agent.clear_attachments", text="Clear")
    for index, attachment in enumerate(window_manager.codex_blender_attachments):
        row = prompt_box.row(align=True)
        row.label(text=f"{attachment.kind}: {attachment.path}")
        op = row.operator("codex_blender_agent.remove_attachment", text="X")
        op.index = index
    send_row = prompt_box.row()
    if window_manager.codex_blender_pending:
        send_row.operator("codex_blender_agent.steer_turn", text="Guide Running Turn")
        send_row.operator("codex_blender_agent.stop_turn", text="Stop Turn", icon="CANCEL")
    else:
        send_row.operator("codex_blender_agent.send_npanel_chat", text="Send")
        send_row.operator("codex_blender_agent.send_prompt_from_text", text="Send Draft")
    draft_row = prompt_box.row(align=True)
    draft_row.operator("codex_blender_agent.open_dashboard_chat", text="Open Multiline Draft")
    draft_row.operator("codex_blender_agent.clear_prompt_draft", text="Clear Draft")
    draft_row.operator("codex_blender_agent.reset_prompt_draft_template", text="Reset Runnable Draft")
    draft_row.operator("codex_blender_agent.refresh_chat_transcript", text="Refresh Transcript")


def _draw_list_header(layout: bpy.types.UILayout, title: str, operator_idname: str | None = None, icon: str = "NONE") -> bpy.types.UILayout:
    box = layout.box()
    header = box.row(align=True)
    header.label(text=title)
    if operator_idname:
        header.operator(operator_idname, text="", icon=icon)
    return box


_ASSET_FACET_TERMS = {
    "model": ("model", "mesh", "object", "prop", "character", "environment", "assembly", "scene block"),
    "material": ("material", "shader", "texture", "pbr", "stylized", "surface"),
    "rig": ("rig", "armature", "bone", "control"),
    "image": ("image", "preview", "reference", "png", "jpg", "jpeg", "exr", "tif", "tiff"),
    "blend": ("blend", ".blend", "bundle"),
    "recipe": ("recipe", "toolbox", "system", "workflow", "plan"),
}

_TOOLBOX_FACET_TERMS = {
    "generate": ("generate", "create", "build", "make", "spawn"),
    "modify": ("modify", "edit", "transform", "mesh", "object"),
    "materials": ("material", "shader", "texture", "surface", "pbr"),
    "rig": ("rig", "armature", "bone", "retarget"),
    "animate": ("animate", "animation", "keyframe", "timeline", "motion"),
    "organize": ("organize", "collection", "name", "rename", "catalog"),
    "optimize": ("optimize", "cleanup", "reduce", "decimate", "repair"),
    "export": ("export", "fbx", "gltf", "usd", "roblox"),
    "debug": ("debug", "diagnose", "inspect", "validate", "test"),
}


def _item_blob(item: object, fields: tuple[str, ...]) -> str:
    return " ".join(str(getattr(item, field, "") or "") for field in fields).lower()


def _matches_search(blob: str, query: str) -> bool:
    terms = [term.strip().lower() for term in (query or "").split() if term.strip()]
    return all(term in blob for term in terms)


def _matches_facet(blob: str, facet: str, facet_terms: dict[str, tuple[str, ...]]) -> bool:
    if not facet or facet == "all":
        return True
    if facet == "other":
        return not any(term in blob for terms in facet_terms.values() for term in terms)
    return any(term in blob for term in facet_terms.get(facet, ()))


def _asset_matches_ui(item: object, window_manager: bpy.types.WindowManager) -> bool:
    blob = _item_blob(
        item,
        (
            "name",
            "item_id",
            "version_uid",
            "logical_uid",
            "category",
            "catalog_path",
            "kind",
            "status",
            "license_spdx",
            "path",
            "description",
            "provenance_summary",
        ),
    )
    query = window_manager.codex_blender_ai_assets_search or window_manager.codex_blender_asset_search
    if not _matches_search(blob, query):
        return False
    kind = getattr(window_manager, "codex_blender_ai_assets_kind_filter", "")
    if kind and kind != "all" and str(getattr(item, "kind", "") or getattr(item, "category", "")) != kind:
        return False
    status = getattr(window_manager, "codex_blender_ai_assets_status_filter", "")
    if status and status != "all" and str(getattr(item, "status", "")) != status:
        return False
    return _matches_facet(blob, window_manager.codex_blender_asset_facet, _ASSET_FACET_TERMS)


def _toolbox_matches_ui(item: object, window_manager: bpy.types.WindowManager) -> bool:
    blob = _item_blob(item, ("name", "item_id", "category", "description"))
    return _matches_facet(blob, window_manager.codex_blender_toolbox_facet, _TOOLBOX_FACET_TERMS)


def _selected_collection_item(collection: object, index: int):
    if index < 0:
        index = 0
    if 0 <= index < len(collection):
        return collection[index]
    return None


def _visible_asset_count(window_manager: bpy.types.WindowManager) -> int:
    return sum(1 for item in window_manager.codex_blender_asset_items if _asset_matches_ui(item, window_manager))


def _visible_toolbox_count(window_manager: bpy.types.WindowManager) -> int:
    return sum(1 for item in window_manager.codex_blender_toolbox_items if _toolbox_matches_ui(item, window_manager))


def _asset_catalog_count(window_manager: bpy.types.WindowManager) -> int:
    catalogs = {str(item.category or "Uncataloged").strip() for item in window_manager.codex_blender_asset_items}
    return len(catalogs) if catalogs else 0


def _path_backed_asset_count(window_manager: bpy.types.WindowManager) -> int:
    return sum(1 for item in window_manager.codex_blender_asset_items if str(item.path or "").strip())


def _draw_assets_workspace_header(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = layout.box()
    _draw_status_badge(box, "Assets: Game-ready library", "asset")
    _draw_wrapped_text(
        box,
        "Use chat for common asset creation. Use this workspace to search, inspect, reuse, publish, and recover reusable assets.",
        width=96,
    )
    row = box.row(align=True)
    row.label(text=f"Assets: {_visible_asset_count(window_manager)}/{len(window_manager.codex_blender_asset_items)} visible")
    row.label(text=f"Catalogs: {_asset_catalog_count(window_manager)}")
    row.label(text=f"Recipes: {_visible_toolbox_count(window_manager)}/{len(window_manager.codex_blender_toolbox_items)} visible")
    row.label(text=f"Pins: {len(window_manager.codex_blender_pinned_outputs)}")
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.create_game_asset_from_prompt", text="Create game asset", icon="ASSET_MANAGER")
    controls.operator("codex_blender_agent.refresh_assets", text="Refresh", icon="FILE_REFRESH")
    controls.operator("codex_blender_agent.verify_ai_assets", text="Health", icon="CHECKMARK")
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.refresh_toolbox", text="Refresh recipes", icon="FILE_REFRESH")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        controls.operator("codex_blender_agent.initialize_ai_assets_store", text="Initialize", icon="ASSET_MANAGER")
        controls.operator("codex_blender_agent.migrate_ai_assets_store", text="Migrate", icon="FILE_REFRESH")
        controls.operator("codex_blender_agent.repair_ai_assets", text="Repair", icon="TOOL_SETTINGS")
        controls.operator("codex_blender_agent.register_asset_library", text="Register Library", icon="ASSET_MANAGER")


def _draw_asset_library_catalogs(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, full: bool) -> None:
    box = _draw_list_header(layout, "Libraries & Catalogs", "codex_blender_agent.refresh_asset_index", "FILE_REFRESH")
    box.prop(window_manager, "codex_blender_show_assets", text="Show asset browser rows")
    filter_row = box.row(align=True)
    filter_row.prop(window_manager, "codex_blender_ai_assets_search", text="Search")
    filter_row.prop(window_manager, "codex_blender_ai_assets_kind_filter", text="Kind")
    filter_row.prop(window_manager, "codex_blender_ai_assets_status_filter", text="Status")
    legacy = box.row(align=True)
    legacy.prop(window_manager, "codex_blender_asset_facet", text="Legacy Facet")
    legacy.operator("codex_blender_agent.index_asset_libraries", text="Index Libraries", icon="FILE_REFRESH")
    meta = box.row(align=True)
    meta.label(text=f"Visible: {_visible_asset_count(window_manager)}")
    meta.label(text=f"Total: {len(window_manager.codex_blender_asset_items)}")
    meta.label(text=f"Path-backed: {_path_backed_asset_count(window_manager)}")
    if not window_manager.codex_blender_show_assets:
        box.label(text="Asset rows are hidden. Search/facet state is preserved.")
        return
    if len(window_manager.codex_blender_asset_items) == 0:
        _draw_guided_empty_state(box, "assets", "No assets indexed yet")
        box.operator("codex_blender_agent.refresh_assets", text="Refresh Asset Index", icon="FILE_REFRESH")
        return
    row = box.row(align=True)
    row.template_list(
        "CODEXBLENDERAGENT_UL_assets",
        "",
        window_manager,
        "codex_blender_asset_items",
        window_manager,
        "codex_blender_asset_index",
        rows=9 if full else 5,
    )
    actions = row.column(align=True)
    actions.operator("codex_blender_agent.refresh_assets", text="", icon="FILE_REFRESH")
    import_op = actions.operator("codex_blender_agent.append_asset_version", text="", icon="ASSET_MANAGER")
    link_op = actions.operator("codex_blender_agent.link_asset_version", text="", icon="HIDE_OFF")
    compat_import = actions.operator("codex_blender_agent.import_selected_asset", text="", icon="IMPORT")
    compat_import.link = False
    import_op = actions.operator("codex_blender_agent.import_selected_asset", text="", icon="ASSET_MANAGER")
    import_op.link = False
    selected = _selected_collection_item(window_manager.codex_blender_asset_items, window_manager.codex_blender_asset_index)
    if selected and selected.item_id:
        delete_op = actions.operator("codex_blender_agent.delete_asset_item", text="", icon="TRASH")
        delete_op.item_id = selected.item_id


def _draw_asset_versions(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    box = _draw_list_header(layout, "Asset Versions & Provenance", None, "ASSET_MANAGER")
    box.prop(window_manager, "codex_blender_asset_show_versions", text="Show selected asset detail")
    if not window_manager.codex_blender_asset_show_versions:
        return
    selected = _selected_collection_item(window_manager.codex_blender_asset_items, window_manager.codex_blender_asset_index)
    if selected is None:
        box.label(text="Select an asset row to inspect bundle path, category, and provenance.")
        return
    header = box.row(align=True)
    header.label(text=_compact_text(selected.name or selected.item_id or "Selected Asset", 54), icon="ASSET_MANAGER")
    header.label(text=_compact_text(selected.kind or "asset", 18))
    if selected.category:
        box.label(text=f"Catalog: {selected.category}")
    if selected.catalog_path:
        box.label(text=f"Catalog Path: {_compact_text(selected.catalog_path, 100)}")
    if selected.status or selected.version:
        box.label(text=f"Lifecycle: {selected.status or 'unknown'} / {selected.version or 'unversioned'}")
    if selected.license_spdx:
        box.label(text=f"License: {selected.license_spdx}")
    if selected.import_policy:
        box.label(text=f"Import Policy: {selected.import_policy}")
    if selected.validation_state or selected.dependency_health:
        status = box.row(align=True)
        status.label(text=f"QA: {selected.validation_state or 'unchecked'}")
        status.label(text=f"Dependencies: {selected.dependency_health or 'unknown'}")
    if selected.path:
        box.label(text=f"Bundle: {_compact_text(selected.path, 100)}")
    else:
        warn = box.row()
        warn.alert = True
        warn.label(text="No bundle path was mirrored for this row.", icon="ERROR")
    if selected.description:
        box.label(text="Summary:")
        _draw_wrapped_text(box, selected.description, width=96)
    if selected.provenance_summary:
        box.label(text="Provenance:")
        _draw_wrapped_text(box, selected.provenance_summary, width=96)
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.validate_asset_version", text="Validate", icon="CHECKMARK")
    controls.operator("codex_blender_agent.generate_asset_preview", text="Generate Preview", icon="RENDER_STILL")
    controls.operator("codex_blender_agent.pin_asset_version", text="Pin", icon="PINNED")
    controls.operator("codex_blender_agent.fork_asset_version", text="Fork", icon="DUPLICATE")
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.publish_asset_package", text="Publish Package", icon="EXPORT")
    controls.operator("codex_blender_agent.append_asset_version", text="Append", icon="ASSET_MANAGER")
    controls.operator("codex_blender_agent.link_asset_version", text="Link", icon="HIDE_OFF")
    _draw_wrapped_text(
        box,
        "Version metadata is shown from the mirrored asset row. Refresh assets after publishing to pick up newer bundles and store-side provenance.",
        width=96,
    )


def _draw_publish_queue(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = _draw_list_header(layout, "Publish Queue", None, "ASSET_MANAGER")
    box.prop(window_manager, "codex_blender_asset_show_publish_queue", text="Show publish controls")
    if not window_manager.codex_blender_asset_show_publish_queue:
        return
    selected_count = len(getattr(context, "selected_objects", []) or [])
    status_key = "success" if selected_count else "warning"
    _draw_status_badge(box, f"Selected objects: {selected_count}", status_key)
    box.label(text="Draft publish name")
    row = box.row(align=True)
    row.prop(window_manager, "codex_blender_asset_name", text="")
    row.operator("codex_blender_agent.create_game_asset_from_prompt", text="AI create asset", icon="ASSET_MANAGER")
    row.operator("codex_blender_agent.save_selected_asset", text="Save asset", icon="ASSET_MANAGER")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        row.operator("codex_blender_agent.create_asset_publish_action", text="Publish card", icon="TEXT")
        row.operator("codex_blender_agent.register_asset_library", text="", icon="ASSET_MANAGER")
    meta = box.row(align=True)
    meta.prop(window_manager, "codex_blender_ai_assets_author", text="Author")
    meta.prop(window_manager, "codex_blender_ai_assets_license", text="License")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        package = box.row(align=True)
        package.prop(window_manager, "codex_blender_ai_assets_package_path", text="Package")
        package.operator("codex_blender_agent.import_asset_package", text="Import Package", icon="IMPORT")
        package.operator("codex_blender_agent.promote_output_to_asset", text="Promote Output", icon="PINNED")
    if selected_count:
        box.label(text="Output: .blend bundle mirrored into the Codex Blender Agent asset library.")
    else:
        box.label(text="Select one or more objects before publishing a reusable bundle.")


def _draw_toolbox_recipes(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, *, full: bool) -> None:
    box = _draw_list_header(layout, "Toolbox Recipes & Reusable Systems", "codex_blender_agent.refresh_toolbox", "FILE_REFRESH")
    box.prop(window_manager, "codex_blender_show_toolbox", text="Show toolbox recipes")
    row = box.row(align=True)
    row.prop(window_manager, "codex_blender_toolbox_facet", text="Group")
    row.label(text=f"Visible: {_visible_toolbox_count(window_manager)}/{len(window_manager.codex_blender_toolbox_items)}")
    if not window_manager.codex_blender_show_toolbox:
        box.label(text="Toolbox recipes are hidden. Group filter is preserved.")
        return
    if len(window_manager.codex_blender_toolbox_items) == 0:
        _draw_guided_empty_state(box, "assets", "No toolbox recipes yet")
        box.operator("codex_blender_agent.refresh_toolbox", text="Refresh Toolbox", icon="FILE_REFRESH")
        return
    list_row = box.row(align=True)
    list_row.template_list(
        "CODEXBLENDERAGENT_UL_toolbox",
        "",
        window_manager,
        "codex_blender_toolbox_items",
        window_manager,
        "codex_blender_toolbox_index",
        rows=9 if full else 5,
    )
    actions = list_row.column(align=True)
    actions.operator("codex_blender_agent.refresh_toolbox", text="", icon="FILE_REFRESH")
    actions.operator("codex_blender_agent.create_toolbox_action", text="", icon="TEXT")
    selected = _selected_collection_item(window_manager.codex_blender_toolbox_items, window_manager.codex_blender_toolbox_index)
    if selected and selected.item_id:
        delete_op = actions.operator("codex_blender_agent.delete_toolbox_item", text="", icon="TRASH")
        delete_op.item_id = selected.item_id
    if selected is not None:
        detail = box.box()
        _draw_status_badge(detail, "Selected Recipe", "generated")
        detail.label(text=_compact_text(selected.name or selected.item_id or "Recipe", 72))
        detail.label(text=f"Group: {selected.category or 'Uncategorized'}")
        if selected.description:
            _draw_wrapped_text(detail, selected.description, width=96)
        detail.operator("codex_blender_agent.create_toolbox_action", text="Create Reviewable Action", icon="TEXT")


def _draw_asset_pins_memory(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    box = _draw_list_header(layout, "Pins & Memory", "codex_blender_agent.pin_thread_output", "PINNED")
    box.label(text="Pinned outputs are the durable working memory for useful plans, assets, and results.")
    if len(window_manager.codex_blender_pinned_outputs) == 0:
        box.label(text="No pins yet. Pin action results from the dashboard or selected asset/recipe notes.")
        return
    box.template_list(
        "CODEXBLENDERAGENT_UL_pinned_outputs",
        "",
        window_manager,
        "codex_blender_pinned_outputs",
        window_manager,
        "codex_blender_pinned_output_index",
        rows=5,
    )


def _draw_asset_diagnostics(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager) -> None:
    box = _draw_list_header(layout, "Diagnostics & Health", None, "VIEWZOOM")
    box.prop(window_manager, "codex_blender_asset_show_diagnostics", text="Show diagnostics")
    if not window_manager.codex_blender_asset_show_diagnostics:
        return
    rows = box.column(align=True)
    rows.label(text=f"Asset rows: {len(window_manager.codex_blender_asset_items)}")
    rows.label(text=f"Toolbox rows: {len(window_manager.codex_blender_toolbox_items)}")
    rows.label(text=f"Pinned outputs: {len(window_manager.codex_blender_pinned_outputs)}")
    rows.label(text=f"Catalog groups: {_asset_catalog_count(window_manager)}")
    rows.label(text=f"Path-backed rows: {_path_backed_asset_count(window_manager)}")
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.verify_ai_assets", text="Run Health Check", icon="CHECKMARK")
    controls.operator("codex_blender_agent.repair_ai_assets", text="Repair", icon="TOOL_SETTINGS")
    controls.operator("codex_blender_agent.refresh_asset_index", text="Refresh Index", icon="FILE_REFRESH")
    if window_manager.codex_blender_ai_assets_health:
        box.label(text="Last Health Payload:")
        _draw_wrapped_text(box, window_manager.codex_blender_ai_assets_health, width=96)
    _draw_error_status(box, window_manager)
    controls = box.row(align=True)
    controls.operator("codex_blender_agent.verify_workspace_suite", text="Health Check", icon="CHECKMARK")
    controls.operator("codex_blender_agent.diagnose_dashboard_workspace", text="Workspace Diagnose", icon="VIEWZOOM")
    controls.operator("codex_blender_agent.refresh_dashboard", text="Sync UI", icon="FILE_REFRESH")


def _draw_workspace_launcher(layout: bpy.types.UILayout) -> None:
    box = layout.box()
    box.label(text="AI Studio Workspaces")
    row = box.row(align=True)
    row.operator("codex_blender_agent.open_studio_workspace", text="AI Studio", icon="WORKSPACE")
    row.operator("codex_blender_agent.open_workflow_workspace", text="Workflow", icon="NODETREE")
    row.operator("codex_blender_agent.open_assets_workspace", text="Assets", icon="ASSET_MANAGER")
    row = box.row(align=True)
    row.operator("codex_blender_agent.create_ai_workspaces", text="Create Suite")
    row.operator("codex_blender_agent.verify_workspace_suite", text="Health")
    row.operator("codex_blender_agent.migrate_legacy_ai_workspaces", text="Migrate Legacy")


def _draw_thread_navigation(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, full: bool) -> None:
    projects_box = _draw_list_header(layout, "Projects", "codex_blender_agent.refresh_dashboard", "FILE_REFRESH")
    row = projects_box.row(align=True)
    row.template_list("CODEXBLENDERAGENT_UL_projects", "", window_manager, "codex_blender_projects", window_manager, "codex_blender_project_index", rows=5 if full else 3)
    project_ops = row.column(align=True)
    project_ops.operator("codex_blender_agent.select_project", text="", icon="CHECKMARK")
    project_ops.operator("codex_blender_agent.open_dashboard_workspace", text="", icon="TEXT")

    threads_box = _draw_list_header(layout, "Threads", "codex_blender_agent.compact_thread", "FULLSCREEN_EXIT")
    row = threads_box.row(align=True)
    row.template_list("CODEXBLENDERAGENT_UL_threads", "", window_manager, "codex_blender_threads", window_manager, "codex_blender_thread_index", rows=7 if full else 4)
    thread_ops = row.column(align=True)
    thread_ops.operator("codex_blender_agent.select_thread", text="", icon="CHECKMARK")
    thread_ops.operator("codex_blender_agent.compact_thread", text="", icon="TRASH")

    state_box = _draw_list_header(layout, "Current State", "codex_blender_agent.pause_transcript_redraw", "PAUSE")
    state_box.template_list("CODEXBLENDERAGENT_UL_dashboard_state", "", window_manager, "codex_blender_dashboard_state", window_manager, "codex_blender_dashboard_state_index", rows=4 if full else 3)


def _draw_workflow_controls(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    workflow_box = _draw_list_header(layout, "AI-managed workflow", "codex_blender_agent.ai_setup_workflow", "NODETREE")
    workflow_box.label(text="Ask AI to build or explain the graph. Manual node editing is advanced.")
    example_row = workflow_box.row(align=True)
    example_row.prop(window_manager, "codex_blender_workflow_example", text="")
    op = example_row.operator("codex_blender_agent.create_example_workflow_graph", text="Create Example")
    op.example_id = window_manager.codex_blender_workflow_example
    row = workflow_box.row(align=True)
    row.operator("codex_blender_agent.ai_setup_workflow", text="AI setup workflow")
    row.operator("codex_blender_agent.create_blank_workflow_tree", text="Blank graph")
    row.operator("codex_blender_agent.inspect_workflow_graph", text="Explain/inspect")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        row = workflow_box.row(align=True)
        for node_type, label in (("workflow_input", "Input"), ("workflow_output", "Output"), ("value", "Value"), ("preview_tap", "Preview")):
            op = row.operator("codex_blender_agent.add_workflow_node", text=label)
            op.node_type = node_type
        row = workflow_box.row(align=True)
        for node_type, label in (("scene_snapshot", "Snapshot"), ("selection", "Selection"), ("context_merge", "Merge"), ("thread_memory", "Memory")):
            op = row.operator("codex_blender_agent.add_workflow_node", text=label)
            op.node_type = node_type
        row = workflow_box.row(align=True)
        for node_type, label in (("assistant_prompt", "Prompt"), ("assistant_call", "Call"), ("asset_search", "Asset Search"), ("publish_asset", "Publish")):
            op = row.operator("codex_blender_agent.add_workflow_node", text=label)
            op.node_type = node_type
        row = workflow_box.row(align=True)
        for node_type, label in (("tool_call", "Tool"), ("approval_gate", "Approval"), ("route", "Route"), ("for_each", "For Each"), ("join", "Join"), ("recipe_call", "Recipe")):
            op = row.operator("codex_blender_agent.add_workflow_node", text=label)
            op.node_type = node_type
    row = workflow_box.row(align=True)
    row.operator("codex_blender_agent.validate_workflow_graph", text="Validate")
    row.operator("codex_blender_agent.compile_workflow_graph", text="Compile")
    row.operator("codex_blender_agent.preview_workflow_graph", text="Preview")
    row.operator("codex_blender_agent.start_workflow_run", text="Start Run")
    row = workflow_box.row(align=True)
    row.operator("codex_blender_agent.resume_workflow_run", text="Resume")
    row.operator("codex_blender_agent.stop_workflow_run", text="Stop")
    row.operator("codex_blender_agent.publish_workflow_recipe", text="Publish Recipe")
    row.operator("codex_blender_agent.propose_workflow_patch", text="Propose Patch")


def _draw_memory_assets(layout: bpy.types.UILayout, context: bpy.types.Context, full: bool) -> None:
    window_manager = context.window_manager
    _draw_asset_library_catalogs(layout, window_manager, full=full)
    _draw_asset_versions(layout, window_manager)
    _draw_publish_queue(layout, context)
    _draw_toolbox_recipes(layout, window_manager, full=full)
    _draw_asset_pins_memory(layout, window_manager)
    _draw_asset_diagnostics(layout, window_manager)


def _draw_transcript(layout: bpy.types.UILayout, window_manager: bpy.types.WindowManager, full: bool) -> None:
    transcript = _draw_list_header(layout, "Transcript", "codex_blender_agent.clear_local_messages", "TRASH")
    transcript.prop(window_manager, "codex_blender_show_transcript", text="Show transcript")
    if not window_manager.codex_blender_show_transcript:
        transcript.label(text="Transcript hidden. Activity still updates above.")
        return

    visible_count = int(window_manager.codex_blender_visible_message_count)
    if visible_count <= 0:
        transcript.label(text="Visible message count is 0.")
        return

    transcript.template_list("CODEXBLENDERAGENT_UL_messages", "", window_manager, "codex_blender_messages", window_manager, "codex_blender_message_index", rows=6 if full else 4)
    selected_index = window_manager.codex_blender_message_index
    messages = window_manager.codex_blender_messages
    if 0 <= selected_index < len(messages):
        message = messages[selected_index]
    else:
        message = messages[-1] if len(messages) else None
    if message is None:
        transcript.label(text="No messages yet.")
        transcript.label(text="Ask Codex to inspect or edit the scene.")
        return
    detail = transcript.box()
    detail.label(text=_message_title(message.role, message.phase, message.status))
    _draw_wrapped_text(detail, _friendly_error(message.text), width=118 if full else 84)


def _draw_studio_continue_session(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = _draw_list_header(layout, "Continue current session", None, "PLAY")
    if len(window_manager.codex_blender_action_cards):
        card = window_manager.codex_blender_action_cards[0]
        box.label(text=_compact_text(card.title or card.action_id or "Latest action", 72))
        box.label(text=f"{action_status_label(card.status)} | {risk_label(card.risk)} risk")
    elif window_manager.codex_blender_active_thread_id:
        box.label(text=f"Thread: {_compact_text(window_manager.codex_blender_active_thread_id, 64)}")
    else:
        box.label(text="No active AI session yet.")
    row = box.row(align=True)
    row.operator("codex_blender_agent.open_workflow_workspace", text="Open Workflow", icon="NODETREE")
    row.operator("codex_blender_agent.open_assets_workspace", text="Open Assets", icon="ASSET_MANAGER")
    row.operator("codex_blender_agent.open_last_result", text="Open last result", icon="PINNED")


def _draw_studio_start_recipes(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = _draw_list_header(layout, "Start from recipe", None, "TEXT")
    box.label(text="Start from chat. Recipes are optional inspection/reuse surfaces.")
    row = box.row(align=True)
    op = row.operator("codex_blender_agent.create_example_workflow_graph", text="Scene Cleanup")
    op.example_id = "scene_inspector"
    op = row.operator("codex_blender_agent.create_example_workflow_graph", text="Castle Blockout")
    op.example_id = "safe_castle_blockout"
    op = row.operator("codex_blender_agent.create_example_workflow_graph", text="Save Asset")
    op.example_id = "save_selection_asset"
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        row = box.row(align=True)
        row.operator("codex_blender_agent.ai_setup_workflow", text="Workflow setup", icon="NODETREE")
        row.operator("codex_blender_agent.create_blank_workflow_tree", text="Blank graph", icon="NODETREE")
    if window_manager.codex_blender_prompt:
        box.label(text=f"Draft prompt: {_compact_text(window_manager.codex_blender_prompt, 88)}")


def _draw_studio_readiness(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    box = _draw_list_header(layout, "Scene readiness", None, "CHECKMARK")
    selected_count = len(getattr(context, "selected_objects", []) or [])
    box.label(text=f"Scene: {getattr(context.scene, 'name', 'Scene') if context.scene else 'None'}")
    box.label(text=f"Scope: {window_manager.codex_blender_active_scope}; selected objects: {selected_count}")
    chips = len(window_manager.codex_blender_context_chips)
    box.label(text=f"Context chips: {chips} visible")
    if len(window_manager.codex_blender_attachments):
        box.label(text=f"Attachments: {len(window_manager.codex_blender_attachments)}")
    row = box.row(align=True)
    row.operator("codex_blender_agent.set_ai_scope", text="Use selection").scope = "selection"
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        row.operator("codex_blender_agent.use_selection_in_workflow", text="Bind to Workflow", icon="NODETREE")
    _draw_context_pack(box, window_manager, rows=3)


def _draw_game_creator_composer(layout: bpy.types.UILayout, context: bpy.types.Context, *, compact: bool = False) -> None:
    window_manager = context.window_manager
    box = layout.box()
    header = box.row(align=True)
    header.label(text="Ask AI", icon="TEXT")
    header.label(text=f"Mode: {getattr(window_manager, 'codex_blender_execution_friction', 'fast').title()}")
    box.prop(window_manager, "codex_blender_prompt", text="")
    model_row = box.row(align=True)
    model_row.prop(window_manager, "codex_blender_model", text="Model")
    model_row.prop(window_manager, "codex_blender_effort", text="Reasoning")
    if not compact:
        row = box.row(align=True)
        row.prop(window_manager, "codex_blender_target_engine", text="")
        row.prop(window_manager, "codex_blender_game_style", text="Style")
    prompt_actions = box.row(align=True)
    prompt_actions.operator("codex_blender_agent.expand_prompt", text="Expand Prompt", icon="FULLSCREEN_ENTER")
    row = box.row(align=True)
    if window_manager.codex_blender_pending:
        row.operator("codex_blender_agent.steer_turn", text="Guide turn", icon="TEXT")
        row.operator("codex_blender_agent.stop_turn", text="Stop", icon="CANCEL")
        row.operator("codex_blender_agent.continue_visual_review_loop", text="Continue Review", icon="PLAY")
    else:
        row.operator("codex_blender_agent.send_npanel_chat", text="Send", icon="TEXT")
        row.operator("codex_blender_agent.explain_current_context", text="Explain context", icon="QUESTION")
    control = box.row(align=True)
    control.operator("codex_blender_agent.open_web_console", text="Web Console", icon="URL")
    control.operator("codex_blender_agent.open_visual_review_run", text="Run details", icon="FILE_FOLDER")
    control.operator("codex_blender_agent.login", text="Login / Re-login", icon="USER")
    control.operator("codex_blender_agent.start_service", text="Restart Service", icon="FILE_REFRESH")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        review = box.row(align=True)
        review.operator("codex_blender_agent.start_visual_review_loop", text="Manual screenshot review", icon="CAMERA_DATA")
        review.prop(window_manager, "codex_blender_visual_review_max_iterations", text="Passes")
        review.prop(window_manager, "codex_blender_visual_review_target_score", text="Score")
    if len(window_manager.codex_blender_attachments):
        box.label(text=f"Attachments: {len(window_manager.codex_blender_attachments)}")
    if not compact:
        attach = box.row(align=True)
        attach.prop(window_manager, "codex_blender_attachment_path", text="")
        attach.operator("codex_blender_agent.add_attachment", text="Attach")


def _draw_quick_prompts(layout: bpy.types.UILayout, context: bpy.types.Context, *, limit: int = 8) -> None:
    window_manager = context.window_manager
    box = layout.box()
    header = box.row(align=True)
    header.label(text="Quick starts", icon="LIGHT")
    header.prop(window_manager, "codex_blender_quick_prompt_category", text="")
    prompts = list_quick_prompts(window_manager.codex_blender_quick_prompt_category)
    if not prompts:
        box.label(text="No quick prompts in this group.")
        return
    for prompt in prompts[:limit]:
        visual = token(prompt.color_token)
        row = box.row(align=True)
        row.label(text=CATEGORY_LABELS.get(prompt.category, prompt.category.title()), icon=visual.icon)
        op = row.operator("codex_blender_agent.run_quick_prompt", text=prompt.label, icon=prompt.icon)
        op.prompt_id = prompt.id
    if len(prompts) > limit:
        box.label(text=f"{len(prompts) - limit} more prompt(s). Choose a narrower group.")


def _draw_current_task_summary(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    _draw_automation_status_panel(layout, context)
    box = layout.box()
    box.label(text="Current task", icon="TIME" if window_manager.codex_blender_pending else "INFO")
    if window_manager.codex_blender_pending:
        box.label(text=_compact_text(window_manager.codex_blender_activity or "AI is working.", 92))
        box.operator("codex_blender_agent.stop_turn", text="Stop", icon="CANCEL")
    elif window_manager.codex_blender_activity:
        _draw_wrapped_text(box, _compact_text(window_manager.codex_blender_activity, 140), width=86)
    else:
        box.label(text="Ready. Ask AI or choose a quick start.")
    if len(window_manager.codex_blender_action_cards):
        card = window_manager.codex_blender_action_cards[0]
        box.label(text=f"Last receipt: {_compact_text(card.title or card.action_id, 72)}", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.operator("codex_blender_agent.open_last_result", text="Open result", icon="PINNED")
        row.operator("codex_blender_agent.undo_last_ai_change", text="Undo", icon="FILE_REFRESH")


def _draw_launcher_ui(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    if _is_workspace_kind(context, "studio"):
        _draw_dashboard_home(layout, context)
        return

    box = layout.box()
    box.label(text="Codex Game Creator", icon="LIGHT")
    _draw_orientation_strip(box, context, "launcher", compact=True)
    _draw_login_status_card(layout, window_manager, compact=True)
    _draw_install_and_web_console_status(layout, context, compact=True)
    _draw_game_creator_composer(layout, context, compact=True)
    _draw_quick_prompts(layout, context, limit=6)
    _draw_current_task_summary(layout, context)
    row = box.row(align=True)
    row.operator("codex_blender_agent.open_studio_workspace", text="AI Studio", icon="WORKSPACE")
    row.operator("codex_blender_agent.open_assets_workspace", text="Assets", icon="ASSET_MANAGER")
    row.operator("codex_blender_agent.open_last_result", text="Last result", icon="PINNED")
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        setup = layout.box()
        setup.label(text="Advanced")
        row = setup.row(align=True)
        row.operator("codex_blender_agent.open_workflow_workspace", text="Workflow", icon="NODETREE")
        row.operator("codex_blender_agent.ai_setup_workflow", text="Workflow setup", icon="NODETREE")
        row = setup.row(align=True)
        row.operator("codex_blender_agent.create_ai_workspaces", text="Create AI Workspaces", icon="WORKSPACE")
        row.operator("codex_blender_agent.verify_workspace_suite", text="Health", icon="CHECKMARK")
        row = setup.row(align=True)
        row.operator("codex_blender_agent.create_action_from_prompt", text="Create review card", icon="TEXT")
        row.operator("codex_blender_agent.recover_action", text="Recover action", icon="FILE_REFRESH")


def _draw_dashboard_home(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    window_manager = context.window_manager
    _draw_orientation_strip(layout, context, "studio")
    _draw_login_status_card(layout, window_manager)
    _draw_install_and_web_console_status(layout, context)
    _draw_game_creator_composer(layout, context)
    _draw_quick_prompts(layout, context, limit=10)
    _draw_current_task_summary(layout, context)
    _draw_studio_continue_session(layout, context)
    _draw_studio_start_recipes(layout, context)
    _draw_studio_readiness(layout, context)
    _draw_recent_outputs(layout, window_manager)
    if getattr(window_manager, "codex_blender_show_tutorial", False):
        _draw_tutorial_card(layout, context)
    if getattr(window_manager, "codex_blender_show_advanced_governance", False):
        _draw_action_cards(layout, window_manager, rows=4)
        _draw_job_timeline(layout, window_manager)
    system = _draw_list_header(layout, "System status", None, "INFO")
    system.label(text=f"Connection: {_compact_text(window_manager.codex_blender_connection, 76)}")
    _draw_error_status(system, window_manager)
    row = system.row(align=True)
    row.operator("codex_blender_agent.refresh_dashboard", text="Refresh Studio", icon="FILE_REFRESH")
    row.operator("codex_blender_agent.verify_workspace_suite", text="Health", icon="CHECKMARK")


def _draw_chat_ui(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    _draw_dashboard_home(layout, context)


def _draw_workflow_ui(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    _draw_orientation_strip(layout, context, "workflow")
    header = layout.box()
    _draw_status_badge(header, "Workflow: AI builds, you inspect", "workflow")
    row = header.row(align=True)
    row.operator("codex_blender_agent.open_studio_workspace", text="Back to chat", icon="WORKSPACE")
    row.operator("codex_blender_agent.open_assets_workspace", text="Publish to Assets", icon="ASSET_MANAGER")
    _draw_workflow_guide(layout, context)
    _draw_workflow_controls(layout, context)
    box = layout.box()
    box.label(text="Ask AI to explain, connect, simplify, or turn this graph into a recipe.")
    row = box.row(align=True)
    row.operator("codex_blender_agent.ai_setup_workflow", text="AI setup")
    row.operator("codex_blender_agent.open_thread_detail", text="Thread detail")


def _draw_assets_ui(layout: bpy.types.UILayout, context: bpy.types.Context) -> None:
    _draw_orientation_strip(layout, context, "assets")
    _draw_assets_workspace_header(layout, context)
    _draw_memory_assets(layout, context, full=True)


def _workspace_kind(context: bpy.types.Context) -> str:
    workspace = context.window.workspace if context.window else None
    kind = str(workspace.get("codex_workspace_kind", "")) if workspace else ""
    return "studio" if kind == "dashboard" else kind


def _is_workspace_kind(context: bpy.types.Context, kind: str) -> bool:
    return _workspace_kind(context) == kind


class CODEXBLENDERAGENT_UL_projects(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_projects"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.name or item.project_id or "Project", 28))
        if item.cwd:
            row.label(text=_compact_text(item.cwd, 36))
        if item.summary:
            row.label(text=_compact_text(item.summary, 44))


class CODEXBLENDERAGENT_UL_threads(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_threads"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.title or item.thread_id or "Thread", 28))
        if item.status:
            row.label(text=_compact_text(item.status, 16))
        if item.message_count:
            row.label(text=f"{item.message_count} msgs")
        if item.summary:
            row.label(text=_compact_text(item.summary, 48))


class CODEXBLENDERAGENT_UL_messages(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_messages"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_message_title(item.role, item.phase, item.status))
        row.label(text=_compact_text(_friendly_error(item.text), 96))


class CODEXBLENDERAGENT_UL_actions(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_actions"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.name or item.action_id or "Action", 28))
        if item.status:
            row.label(text=_compact_text(item.status, 16))
        if item.description:
            row.label(text=_compact_text(item.description, 60))


class CODEXBLENDERAGENT_UL_toolbox(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_toolbox"

    def filter_items(self, context, data, propname):
        window_manager = context.window_manager
        items = getattr(data, propname)
        flags = [
            self.bitflag_filter_item if _toolbox_matches_ui(item, window_manager) else 0
            for item in items
        ]
        return flags, []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.name or item.item_id or "Toolbox", 28), icon="TEXT")
        if item.category:
            row.label(text=_compact_text(item.category, 20))
        if item.description:
            row.label(text=_compact_text(item.description, 60))


class CODEXBLENDERAGENT_UL_assets(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_assets"

    def filter_items(self, context, data, propname):
        window_manager = context.window_manager
        items = getattr(data, propname)
        flags = [
            self.bitflag_filter_item if _asset_matches_ui(item, window_manager) else 0
            for item in items
        ]
        return flags, []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.name or item.item_id or "Asset", 28), icon="ASSET_MANAGER")
        lifecycle = " / ".join(part for part in (item.kind or item.category, item.status, item.version) if part)
        if lifecycle:
            row.label(text=_compact_text(lifecycle, 36))
        if item.catalog_path or item.category:
            row.label(text=_compact_text(item.catalog_path or item.category, 42))
        health = " / ".join(part for part in (item.validation_state, item.dependency_health, item.license_spdx) if part)
        if health:
            row.label(text=_compact_text(health, 42))
        elif item.path:
            row.label(text=_compact_text(item.path, 42))
        else:
            row.label(text="No payload")


class CODEXBLENDERAGENT_UL_dashboard_state(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_dashboard_state"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.name or item.state_id or "State", 24))
        if item.value:
            row.label(text=_compact_text(item.value, 32))
        if item.detail:
            row.label(text=_compact_text(item.detail, 48))


class CODEXBLENDERAGENT_UL_context_chips(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_context_chips"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=item.label or item.chip_id, icon="CHECKBOX_HLT" if item.enabled else "CHECKBOX_DEHLT")
        row.label(text=_compact_text(item.value, 40))
        if item.kind:
            row.label(text=_compact_text(item.kind, 14))


class CODEXBLENDERAGENT_UL_action_cards(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_action_cards"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        visual = status_token(item.status)
        row.alert = visual.alert
        row.label(text=_compact_text(item.title or item.action_id or "AI Action", 32), icon=visual.icon)
        row.label(text=action_status_label(item.status))
        risk_visual = risk_token(item.risk)
        row.label(text=f"{risk_label(item.risk)} Risk", icon=risk_visual.icon)
        if item.affected_targets:
            row.label(text=_compact_text(item.affected_targets, 36))


class CODEXBLENDERAGENT_UL_pinned_outputs(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_pinned_outputs"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=_compact_text(item.title or item.output_id or "Output", 34), icon="PINNED")
        if item.kind:
            row.label(text=_compact_text(item.kind, 14))
        if item.summary:
            row.label(text=_compact_text(item.summary, 64))


class CODEXBLENDERAGENT_UL_job_timeline(UIList):
    bl_idname = "CODEXBLENDERAGENT_UL_job_timeline"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        visual = status_token(item.status)
        row.alert = visual.alert
        row.label(text=_compact_text(item.label or item.event_id or "Event", 34), icon=visual.icon)
        if item.status:
            row.label(text=_compact_text(item.status, 16))
        if item.detail:
            row.label(text=_compact_text(item.detail, 68))


class CODEXBLENDERAGENT_PT_panel(Panel):
    bl_label = "Codex AI Studio"
    bl_idname = "CODEXBLENDERAGENT_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI"

    def draw(self, context: bpy.types.Context) -> None:
        _draw_launcher_ui(self.layout, context)


class CODEXBLENDERAGENT_PT_text_editor_chat(Panel):
    bl_label = "Codex Transcript Detail"
    bl_idname = "CODEXBLENDERAGENT_PT_text_editor_chat"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "AI"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _is_workspace_kind(context, "studio")

    def draw(self, context: bpy.types.Context) -> None:
        _draw_chat_ui(self.layout, context)


class CODEXBLENDERAGENT_PT_text_editor_threads(Panel):
    bl_label = "Projects & Threads"
    bl_idname = "CODEXBLENDERAGENT_PT_text_editor_threads"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "AI"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _is_workspace_kind(context, "studio")

    def draw(self, context: bpy.types.Context) -> None:
        _draw_thread_navigation(self.layout, context.window_manager, full=True)


class CODEXBLENDERAGENT_PT_node_workflow(Panel):
    bl_label = "Workflow Inspector"
    bl_idname = "CODEXBLENDERAGENT_PT_node_workflow"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "AI"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _is_workspace_kind(context, "workflow")

    def draw(self, context: bpy.types.Context) -> None:
        _draw_workflow_ui(self.layout, context)


class CODEXBLENDERAGENT_PT_properties_assets(Panel):
    bl_label = "Assets Library & Provenance"
    bl_idname = "CODEXBLENDERAGENT_PT_properties_assets"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _is_workspace_kind(context, "assets")

    def draw(self, context: bpy.types.Context) -> None:
        _draw_assets_ui(self.layout, context)


CLASSES = (
    CODEXBLENDERAGENT_UL_projects,
    CODEXBLENDERAGENT_UL_threads,
    CODEXBLENDERAGENT_UL_messages,
    CODEXBLENDERAGENT_UL_actions,
    CODEXBLENDERAGENT_UL_toolbox,
    CODEXBLENDERAGENT_UL_assets,
    CODEXBLENDERAGENT_UL_dashboard_state,
    CODEXBLENDERAGENT_UL_context_chips,
    CODEXBLENDERAGENT_UL_action_cards,
    CODEXBLENDERAGENT_UL_pinned_outputs,
    CODEXBLENDERAGENT_UL_job_timeline,
    CODEXBLENDERAGENT_PT_panel,
    CODEXBLENDERAGENT_PT_text_editor_chat,
    CODEXBLENDERAGENT_PT_text_editor_threads,
    CODEXBLENDERAGENT_PT_node_workflow,
    CODEXBLENDERAGENT_PT_properties_assets,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
