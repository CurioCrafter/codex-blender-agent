from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SAFE_ICONS = {
    "NONE",
    "INFO",
    "CHECKMARK",
    "ERROR",
    "CANCEL",
    "TIME",
    "TEXT",
    "NODETREE",
    "ASSET_MANAGER",
    "HIDE_OFF",
    "QUESTION",
    "PINNED",
    "FILE_REFRESH",
    "WORKSPACE",
    "VIEWZOOM",
    "TRASH",
    "FULLSCREEN_EXIT",
    "PAUSE",
    "CHECKBOX_HLT",
    "CHECKBOX_DEHLT",
    "LIGHT",
    "FULLSCREEN_ENTER",
}


@dataclass(frozen=True)
class VisualToken:
    key: str
    label: str
    icon: str
    alert: bool
    help: str


@dataclass(frozen=True)
class StateMeta:
    key: str
    label: str
    icon: str
    alert: bool
    enabled: bool
    help: str


@dataclass(frozen=True)
class EmptyStatePayload:
    surface: str
    title: str
    purpose: str
    reason: str
    next_action: str
    tip: str = ""


@dataclass(frozen=True)
class CardAction:
    operator: str
    label: str
    icon: str
    role: str = "primary"
    enabled: bool = True


TOKENS: dict[str, VisualToken] = {
    "accent": VisualToken("accent", "AI", "INFO", False, "Primary AI workspace or generated content."),
    "info": VisualToken("info", "Info", "INFO", False, "Helpful context or neutral activity."),
    "success": VisualToken("success", "Done", "CHECKMARK", False, "The operation completed successfully."),
    "warning": VisualToken("warning", "High impact", "ERROR", True, "Review the impact before continuing."),
    "danger": VisualToken("danger", "Danger", "CANCEL", True, "This failed or may be destructive."),
    "muted": VisualToken("muted", "Idle", "NONE", False, "Inactive or low-priority state."),
    "generated": VisualToken("generated", "Generated", "LIGHT", False, "AI-generated or AI-published output."),
    "review": VisualToken("review", "Review required", "HIDE_OFF", False, "The user should inspect this before approval."),
    "running": VisualToken("running", "Running", "TIME", False, "The model or tool is currently working."),
    "pinned": VisualToken("pinned", "Pinned", "PINNED", False, "Saved for later reference outside the transcript."),
    "changed": VisualToken("changed", "Changed", "FILE_REFRESH", False, "Scene, asset, or workflow data changed."),
    "unavailable": VisualToken("unavailable", "Unavailable", "NONE", False, "Unavailable until a prerequisite is fixed."),
    "create": VisualToken("create", "Create", "LIGHT", False, "Create new local game content."),
    "material": VisualToken("material", "Material", "LIGHT", False, "Material, shader, and surface work."),
    "level": VisualToken("level", "Level", "WORKSPACE", False, "Level art, blockout, and scene dressing work."),
    "asset": VisualToken("asset", "Asset", "ASSET_MANAGER", False, "Reusable game asset work."),
    "workflow": VisualToken("workflow", "Workflow", "NODETREE", False, "AI-managed workflow graph work."),
    "fix": VisualToken("fix", "Fix", "CHECKMARK", False, "Cleanup, repair, and game-readiness work."),
    "export": VisualToken("export", "Export", "ASSET_MANAGER", False, "Engine export and package preparation."),
    "learn": VisualToken("learn", "Learn", "QUESTION", False, "Tutorial, explanation, and contextual help."),
    "optimize": VisualToken("optimize", "Optimize", "CHECKMARK", False, "Realtime game optimization work."),
}

STATE_META: dict[str, StateMeta] = {
    "ready": StateMeta("ready", "Ready", "INFO", False, True, "Nothing is blocked or running."),
    "needs_input": StateMeta("needs_input", "Needs input", "QUESTION", False, True, "A prerequisite is missing."),
    "review_required": StateMeta("review_required", "Review required", "HIDE_OFF", False, True, "Approval is needed before work continues."),
    "running": StateMeta("running", "Running", "TIME", False, True, "Work is in progress."),
    "done": StateMeta("done", "Done", "CHECKMARK", False, True, "The action completed successfully."),
    "changed": StateMeta("changed", "Changed", "FILE_REFRESH", False, True, "Scene, asset, or workflow data changed."),
    "risk": StateMeta("risk", "High impact", "ERROR", True, True, "This may overwrite, delete, publish, or affect broad scope."),
    "failed": StateMeta("failed", "Failed", "ERROR", True, True, "The action failed and needs recovery or details."),
    "unavailable": StateMeta("unavailable", "Unavailable", "NONE", False, False, "Unavailable until a prerequisite is fixed."),
    "pinned": StateMeta("pinned", "Pinned", "PINNED", False, True, "Pinned for reuse outside the transcript."),
}

STATUS_TO_STATE = {
    "ready": "ready",
    "draft": "ready",
    "planning": "ready",
    "needs_input": "needs_input",
    "needs_clarification": "needs_input",
    "needs_approval": "review_required",
    "review": "review_required",
    "review_required": "review_required",
    "preview_ready": "review_required",
    "preview_visible": "review_required",
    "awaiting_approval": "review_required",
    "approved": "review_required",
    "running": "running",
    "stopping": "running",
    "paused": "needs_input",
    "completed": "done",
    "completed_with_warnings": "changed",
    "done": "done",
    "changed": "changed",
    "failed": "failed",
    "risk": "risk",
    "cancelled": "unavailable",
    "recovered": "done",
    "stale": "needs_input",
    "archived": "unavailable",
    "pinned": "pinned",
    "unavailable": "unavailable",
}

STATUS_TO_TOKEN = {
    status: {
        "ready": "info",
        "needs_input": "info",
        "review_required": "review",
        "running": "running",
        "done": "success",
        "changed": "changed",
        "risk": "warning",
        "failed": "danger",
        "unavailable": "unavailable",
        "pinned": "pinned",
    }[state]
    for status, state in STATUS_TO_STATE.items()
}

RISK_TO_TOKEN = {
    "low": "info",
    "medium": "warning",
    "high": "danger",
    "critical": "danger",
}

SURFACE_EMPTY_STATES: dict[str, EmptyStatePayload] = {
    "dashboard": EmptyStatePayload(
        "dashboard",
        "No actions yet",
        "AI Studio shows current context, running work, review cards, and recovery paths.",
        "Nothing is queued because no AI task has been started in this file.",
        "Inspect context",
        "Start by checking what the AI can see before making changes.",
    ),
    "studio": EmptyStatePayload(
        "studio",
        "No actions yet",
        "AI Studio shows current context, running work, review cards, and recovery paths.",
        "Nothing is queued because no AI task has been started in this file.",
        "Inspect context",
        "Use Workflow for graph execution and Assets for reusable outputs.",
    ),
    "workflow": EmptyStatePayload(
        "workflow",
        "No workflow run yet",
        "Workflow builds, previews, validates, and runs typed orchestration graphs.",
        "No graph run is active for the current file.",
        "Preview graph",
        "Preview is read-only; risky nodes create review cards before execution.",
    ),
    "assets": EmptyStatePayload(
        "assets",
        "No asset selected",
        "Assets manages reusable libraries, versions, previews, provenance, and imports.",
        "No asset version is selected or indexed for the current filter.",
        "Refresh assets",
        "Generated outputs become reusable only after promotion and review.",
    ),
    "transcript": EmptyStatePayload(
        "transcript",
        "No transcript selected",
        "Transcript detail keeps raw chat and tool history available for audit.",
        "No thread detail is selected for review.",
        "Open AI Studio",
        "Cards and pins are the working context; transcript is the archive.",
    ),
    "action_cards": EmptyStatePayload(
        "action_cards",
        "No receipts yet",
        "Receipts hold completed AI changes, high-risk approvals, and recovery paths.",
        "No AI game-creation action has produced a receipt or approval yet.",
        "Ask AI",
        "Fast mode keeps ordinary creation in chat and records receipts after changes.",
    ),
    "context_chips": EmptyStatePayload(
        "context_chips",
        "No visible context yet",
        "Context chips show exactly what the AI may use for this turn.",
        "The dashboard has not captured selection, file, attachment, or pinned context yet.",
        "Inspect context",
        "Disabled chips remain visible but are excluded from model context.",
    ),
}

EMPTY_STATE_ALIASES = {
    "context": "context_chips",
    "cards": "action_cards",
    "actions": "action_cards",
}

STATUS_COPY = {
    "ready": "Ready",
    "needs_input": "Needs input",
    "review_required": "Review required",
    "running": "Running",
    "done": "Done",
    "changed": "Changed",
    "risk": "High impact",
    "failed": "Failed",
    "unavailable": "Unavailable",
    "pinned": "Pinned",
}

CARD_PRIMARY_ACTIONS = {
    "draft": CardAction("codex_blender_agent.preview_action", "Preview", "HIDE_OFF"),
    "needs_clarification": CardAction("codex_blender_agent.inspect_ai_context", "Inspect context", "VIEWZOOM"),
    "preview_ready": CardAction("codex_blender_agent.view_action_changes", "Review changes", "VIEWZOOM"),
    "preview_visible": CardAction("codex_blender_agent.approve_action", "Approve", "CHECKMARK"),
    "awaiting_approval": CardAction("codex_blender_agent.approve_action", "Approve", "CHECKMARK"),
    "approved": CardAction("codex_blender_agent.approve_action", "Approve", "CHECKMARK"),
    "running": CardAction("codex_blender_agent.stop_action", "Stop", "CANCEL"),
    "stopping": CardAction("codex_blender_agent.stop_action", "Stop", "CANCEL", enabled=False),
    "paused": CardAction("codex_blender_agent.resume_action", "Resume", "TIME"),
    "completed": CardAction("codex_blender_agent.view_action_changes", "View changes", "FILE_REFRESH"),
    "completed_with_warnings": CardAction("codex_blender_agent.view_action_changes", "View changes", "FILE_REFRESH"),
    "failed": CardAction("codex_blender_agent.recover_action", "Recover action", "FILE_REFRESH"),
    "recovered": CardAction("codex_blender_agent.open_action_details", "Open details", "TEXT"),
    "stale": CardAction("codex_blender_agent.preview_action", "Regenerate preview", "HIDE_OFF"),
    "pinned": CardAction("codex_blender_agent.open_action_details", "Open details", "TEXT"),
    "archived": CardAction("codex_blender_agent.open_action_details", "Open details", "TEXT"),
    "cancelled": CardAction("codex_blender_agent.open_action_details", "Open details", "TEXT"),
}

CARD_SECONDARY_ACTIONS = {
    "draft": (
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "secondary"),
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
    ),
    "needs_clarification": (
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "secondary"),
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
    ),
    "preview_ready": (
        CardAction("codex_blender_agent.approve_action", "Approve", "CHECKMARK", "secondary"),
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
    ),
    "preview_visible": (
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "quiet"),
    ),
    "awaiting_approval": (
        CardAction("codex_blender_agent.view_action_changes", "Review changes", "VIEWZOOM", "secondary"),
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
    ),
    "approved": (
        CardAction("codex_blender_agent.view_action_changes", "Review changes", "VIEWZOOM", "secondary"),
        CardAction("codex_blender_agent.cancel_action", "Cancel", "CANCEL", "quiet"),
    ),
    "running": (
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "secondary"),
    ),
    "paused": (
        CardAction("codex_blender_agent.recover_action", "Recover action", "FILE_REFRESH", "secondary"),
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "quiet"),
    ),
    "completed": (
        CardAction("codex_blender_agent.undo_last_ai_change", "Undo last change", "FILE_REFRESH", "secondary"),
        CardAction("codex_blender_agent.pin_thread_output", "Pin result", "PINNED", "quiet"),
    ),
    "completed_with_warnings": (
        CardAction("codex_blender_agent.recover_action", "Recover action", "FILE_REFRESH", "secondary"),
        CardAction("codex_blender_agent.pin_thread_output", "Pin result", "PINNED", "quiet"),
    ),
    "failed": (
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "secondary"),
        CardAction("codex_blender_agent.archive_action", "Archive", "TRASH", "quiet"),
    ),
    "stale": (
        CardAction("codex_blender_agent.recover_action", "Recover action", "FILE_REFRESH", "secondary"),
        CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "quiet"),
    ),
}

VAGUE_TOP_LEVEL_LABELS = {"Run", "Process", "Continue", "Execute", "Run Task", "Start Run"}


def token(key: str) -> VisualToken:
    return TOKENS.get(key, TOKENS["info"])


def state_key(status_or_state: str) -> str:
    value = (status_or_state or "").strip().lower().replace("-", "_").replace(" ", "_")
    return STATUS_TO_STATE.get(value, value if value in STATE_META else "ready")


def state_meta(status_or_state: str) -> StateMeta:
    return STATE_META[state_key(status_or_state)]


def status_copy(status: str) -> str:
    return STATUS_COPY.get(state_key(status), state_meta(status).label)


def status_token(status: str) -> VisualToken:
    normalized = (status or "").strip().lower().replace("-", "_").replace(" ", "_")
    return token(STATUS_TO_TOKEN.get(normalized, STATUS_TO_TOKEN.get(state_key(status), "info")))


def risk_token(risk: str) -> VisualToken:
    return token(RISK_TO_TOKEN.get((risk or "").strip().lower(), "info"))


def empty_state(surface: str) -> str:
    payload = empty_state_payload(surface)
    return " ".join(part for part in (payload.purpose, payload.reason, payload.next_action, payload.tip) if part)


def empty_state_payload(surface: str, reason: str = "") -> EmptyStatePayload:
    key = (surface or "dashboard").strip().lower().replace("-", "_").replace(" ", "_")
    key = EMPTY_STATE_ALIASES.get(key, key)
    payload = SURFACE_EMPTY_STATES.get(key, SURFACE_EMPTY_STATES["dashboard"])
    if reason:
        return EmptyStatePayload(payload.surface, payload.title, payload.purpose, reason, payload.next_action, payload.tip)
    return payload


def card_status(card: Any) -> str:
    value = _field(card, "status", "draft")
    return (value or "draft").strip().lower().replace("-", "_").replace(" ", "_")


def primary_action_for_card(card: Any) -> CardAction:
    status = card_status(card)
    if status == "needs_approval":
        status = "awaiting_approval"
    return CARD_PRIMARY_ACTIONS.get(status, CARD_PRIMARY_ACTIONS["draft"])


def secondary_actions_for_card(card: Any) -> tuple[CardAction, ...]:
    status = card_status(card)
    if status == "needs_approval":
        status = "awaiting_approval"
    return CARD_SECONDARY_ACTIONS.get(status, (CardAction("codex_blender_agent.open_action_details", "Details", "TEXT", "secondary"),))


def orientation_payload(context: Any, surface: str = "studio") -> dict[str, Any]:
    wm = getattr(context, "window_manager", None)
    scene = getattr(context, "scene", None)
    window = getattr(context, "window", None)
    workspace = getattr(window, "workspace", None) if window else None
    area = getattr(context, "area", None)
    space_data = getattr(context, "space_data", None)
    active_object = getattr(context, "active_object", None)
    selected_objects = list(getattr(context, "selected_objects", []) or [])
    chips = list(getattr(wm, "codex_blender_context_chips", []) or []) if wm else []
    actions = list(getattr(wm, "codex_blender_action_cards", []) or []) if wm else []
    pending_statuses = {
        "needs_clarification",
        "preview_ready",
        "preview_visible",
        "awaiting_approval",
        "needs_approval",
        "approved",
        "running",
        "stopping",
        "paused",
        "failed",
        "stale",
    }
    changed_count = sum(1 for card in actions if card_status(card) in {"completed", "completed_with_warnings", "recovered"})
    running = next((card for card in actions if card_status(card) in {"running", "stopping"}), None)
    location_parts = [
        _name(workspace, "Layout"),
        _space_label(getattr(area, "type", "") or getattr(space_data, "type", "")),
    ]
    mode = getattr(context, "mode", "")
    if mode:
        location_parts.append(str(mode).replace("_", " ").title())
    target = _name(active_object, "")
    if target:
        location_parts.append(f"Target: {target}")
    scope = str(getattr(wm, "codex_blender_active_scope", "selection") or "selection") if wm else "selection"
    sees = _visible_context_summary(selected_objects, chips, scene)
    return {
        "surface": surface or "studio",
        "location": " - ".join(part for part in location_parts if part),
        "scope": scope.replace("_", " ").title(),
        "target": target,
        "sees": sees,
        "running": _field(running, "title", "") if running else "",
        "progress": float(getattr(wm, "codex_blender_dashboard_progress", 0.0) or 0.0) if wm else 0.0,
        "pending_count": sum(1 for card in actions if card_status(card) in pending_statuses),
        "review_count": sum(1 for card in actions if card_status(card) in {"preview_ready", "preview_visible", "awaiting_approval", "needs_approval", "approved"}),
        "changed_count": changed_count,
        "undo_available": changed_count > 0,
        "connection": str(getattr(wm, "codex_blender_connection", "") or "") if wm else "",
        "error": str(getattr(wm, "codex_blender_error", "") or "") if wm else "",
    }


def validate_icons() -> list[str]:
    icons = [item.icon for item in TOKENS.values()]
    icons.extend(item.icon for item in STATE_META.values())
    icons.extend(action.icon for action in CARD_PRIMARY_ACTIONS.values())
    for actions in CARD_SECONDARY_ACTIONS.values():
        icons.extend(action.icon for action in actions)
    return sorted({icon for icon in icons if icon not in SAFE_ICONS})


def _field(obj: Any, name: str, default: Any = "") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _name(obj: Any, default: str = "") -> str:
    return str(getattr(obj, "name", "") or default)


def _space_label(value: str) -> str:
    normalized = (value or "").replace("_", " ").strip().title()
    return normalized or "Blender"


def _visible_context_summary(selected_objects: list[Any], chips: list[Any], scene: Any) -> str:
    selected_count = len(selected_objects)
    enabled_chips = [chip for chip in chips if bool(_field(chip, "enabled", True))]
    parts: list[str] = []
    if selected_count:
        parts.append(f"{selected_count} selected")
    elif scene is not None:
        parts.append(f"Scene: {_name(scene, 'Scene')}")
    if enabled_chips:
        labels = [_field(chip, "label", "") for chip in enabled_chips[:3]]
        parts.append(", ".join(str(label) for label in labels if label))
    if not parts:
        parts.append("Current file only")
    return " + ".join(parts)
