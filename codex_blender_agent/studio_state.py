from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


VALID_SCOPES = ("selection", "active_object", "collection", "scene", "project", "visible_objects", "new_collection")
INTENT_TYPES = ("ask", "inspect", "change", "automate", "recover", "export")
ACTION_KINDS = ("inspect", "change", "automate", "recover", "export")
RISK_LEVELS = ("low", "medium", "high", "critical")
ACTION_STATUSES = (
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
    # Legacy status retained for existing saved cards and Cancel UI.
    "cancelled",
)

LEGACY_STATUS_ALIASES = {
    "planning": "draft",
    "needs_approval": "awaiting_approval",
    "cancel": "cancelled",
}

RISK_AXIS_DEFAULTS = {
    "reversibility": "single_undo_reversible",
    "scope": "selection",
    "destructiveness": "additive",
    "uncertainty": "clear",
    "runtime_profile": "instant",
    "externality": "scene_local",
}

TOOLBOX_INTENT_GROUPS = (
    "Generate",
    "Modify",
    "Materials",
    "Rig",
    "Animate",
    "Organize",
    "Optimize",
    "Export",
    "Debug",
)

_HIGH_RISK_TERMS = {
    "delete",
    "remove",
    "overwrite",
    "replace all",
    "clear",
    "purge",
    "bake",
    "export",
    "execute python",
    "run python",
}

_CRITICAL_RISK_TERMS = {
    "execute python",
    "run python",
    "arbitrary python",
    "shell",
    "system command",
    "delete file",
    "remove file",
    "overwrite file",
    "install addon",
    "enable addon",
}

_MEDIUM_RISK_TERMS = {
    "create",
    "generate",
    "modify",
    "change",
    "set ",
    "apply",
    "append",
    "import",
    "rig",
    "animate",
    "keyframe",
    "material",
    "modifier",
    "node",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_action_id() -> str:
    return f"action-{uuid.uuid4().hex[:16]}"


def make_output_id() -> str:
    return f"output-{uuid.uuid4().hex[:16]}"


def make_event_id() -> str:
    return f"event-{uuid.uuid4().hex[:16]}"


def compact_text(text: str, limit: int = 160) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)] + "..."


def normalize_scope(scope: str) -> str:
    value = (scope or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in VALID_SCOPES else "selection"


def normalize_intent(intent: str) -> str:
    value = (intent or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in INTENT_TYPES else "ask"


def normalize_action_kind(kind: str) -> str:
    value = (kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in ACTION_KINDS else "change"


def classify_prompt_intent(prompt: str) -> str:
    text = (prompt or "").lower()
    if any(term in text for term in ("recover", "undo", "restore", "revert")):
        return "recover"
    if any(term in text for term in ("export", "save as", "write file", "render to", "fbx", "glb", "gltf")):
        return "export"
    if any(term in text for term in ("batch", "automate", "workflow", "repeatable", "for every", "all selected")):
        return "automate"
    if any(term in text for term in ("change", "create", "generate", "add ", "make ", "delete", "remove", "assign", "apply", "import", "append", "set ")):
        if "no changes" not in text and "do not change" not in text:
            return "change"
    if any(term in text for term in ("inspect", "check", "diagnose", "analyze", "analyse", "compare", "summarize issues")):
        return "inspect"
    return "ask"


def action_kind_from_intent(intent: str) -> str:
    normalized = normalize_intent(intent)
    if normalized in {"ask", "inspect"}:
        return "inspect"
    return normalized


def build_risk_axes(
    *,
    prompt: str = "",
    tool_name: str = "",
    target_count: int = 0,
    active_scope: str = "selection",
    external_write: bool = False,
    critical: bool = False,
    ambiguous: bool = False,
    long_running: bool = False,
) -> dict[str, str]:
    text = f"{prompt or ''} {tool_name or ''}".lower()
    scope = normalize_scope(active_scope)
    axes = dict(RISK_AXIS_DEFAULTS)
    if target_count > 1:
        axes["scope"] = "small_selection" if target_count <= 8 else "many_objects"
    if scope in {"scene", "project", "visible_objects"}:
        axes["scope"] = "whole_scene" if scope == "scene" else scope
    if any(term in text for term in ("delete", "remove", "overwrite", "replace all", "purge", "apply modifier", "bake", "join meshes")):
        axes["destructiveness"] = "destructive"
    elif any(term in text for term in ("create", "generate", "set ", "assign", "rename", "modify", "change", "apply", "material", "modifier")):
        axes["destructiveness"] = "property_edit"
    if any(term in text for term in ("duplicate", "non-destructive", "modifier", "preview")):
        axes["destructiveness"] = "additive"
    if ambiguous or any(term in text for term in ("this", "better", "fix it", "improve", "clean it")) and target_count == 0:
        axes["uncertainty"] = "target_ambiguity"
    if long_running or any(term in text for term in ("batch", "all", "whole scene", "render", "export", "bake")):
        axes["runtime_profile"] = "checkpointable"
    if external_write or any(term in text for term in ("export", "save", "write", "asset library", "append", "import")):
        axes["externality"] = "external_write" if any(term in text for term in ("export", "save", "write")) else "asset_library_write"
    if critical or any(term in text for term in _CRITICAL_RISK_TERMS):
        axes["reversibility"] = "effectively_irreversible"
        axes["externality"] = "critical_side_effect"
    elif axes["destructiveness"] == "destructive":
        axes["reversibility"] = "multi_step_recoverable"
    return axes


def risk_from_axes(axes: dict[str, str]) -> tuple[str, str]:
    if axes.get("externality") == "critical_side_effect" or axes.get("reversibility") == "effectively_irreversible":
        return "critical", "Critical risk: irreversible or outside normal scene recovery."
    if axes.get("destructiveness") == "destructive" or axes.get("scope") in {"many_objects", "whole_scene", "project"}:
        return "high", "High risk: broad scope or destructive scene edit."
    if axes.get("destructiveness") == "property_edit" or axes.get("externality") in {"asset_library_write", "external_write"} or axes.get("runtime_profile") == "checkpointable" or axes.get("uncertainty") != "clear":
        return "medium", "Medium risk: broader scope, uncertainty, long run, or asset/file side effect."
    return "low", "Low risk: local, reversible, and non-destructive."


def infer_action_risk(prompt: str, tool_name: str = "") -> str:
    text = f"{prompt or ''} {tool_name or ''}".lower()
    if any(term in text for term in _CRITICAL_RISK_TERMS):
        return "critical"
    if any(term in text for term in _HIGH_RISK_TERMS):
        return "high"
    if any(term in text for term in _MEDIUM_RISK_TERMS):
        return "medium"
    return "low"


def approval_required_for_risk(risk: str) -> bool:
    return risk in {"medium", "high", "critical"}


def normalize_action_status(status: str, risk: str = "low") -> str:
    value = (status or "").strip().lower().replace("-", "_").replace(" ", "_")
    value = LEGACY_STATUS_ALIASES.get(value, value)
    if value in ACTION_STATUSES:
        return value
    return "awaiting_approval" if approval_required_for_risk(risk) else "draft"


def action_status_label(status: str) -> str:
    labels = {
        "draft": "Draft",
        "needs_clarification": "Needs Clarification",
        "preview_ready": "Preview Ready",
        "preview_visible": "Preview Visible",
        "awaiting_approval": "Awaiting Approval",
        "approved": "Approved",
        "running": "Running",
        "stopping": "Stopping",
        "paused": "Paused",
        "completed": "Completed",
        "completed_with_warnings": "Completed With Warnings",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "recovered": "Recovered",
        "stale": "Stale",
        "pinned": "Pinned",
        "archived": "Archived",
    }
    return labels.get(normalize_action_status(status), "Draft")


def risk_label(risk: str) -> str:
    value = (risk or "").strip().lower()
    return value.title() if value in RISK_LEVELS else "Low"


def approval_policy_for_risk(risk: str) -> str:
    value = (risk or "").strip().lower()
    if value == "critical":
        return "Typed confirmation or expert mode required; blocked by default."
    if value == "high":
        return "Explicit approval with expanded impact review required."
    if value == "medium":
        return "Explicit approval required after preview."
    return "One-click approval after preview."


def transition_allowed(previous: str, next_status: str) -> bool:
    previous_value = normalize_action_status(previous)
    next_value = normalize_action_status(next_status)
    if previous_value == next_value:
        return True
    if previous_value in {"completed", "completed_with_warnings", "failed", "recovered", "archived", "cancelled"}:
        return next_value in {"pinned", "archived", "recovered", "stale"}
    allowed = {
        "draft": {"needs_clarification", "preview_ready", "preview_visible", "awaiting_approval", "archived", "cancelled"},
        "needs_clarification": {"draft", "preview_ready", "awaiting_approval", "archived", "cancelled"},
        "preview_ready": {"preview_visible", "awaiting_approval", "archived", "cancelled"},
        "preview_visible": {"awaiting_approval", "archived", "cancelled"},
        "awaiting_approval": {"approved", "archived", "cancelled", "preview_ready"},
        "approved": {"running", "archived", "cancelled"},
        "running": {"stopping", "paused", "completed", "completed_with_warnings", "failed"},
        "stopping": {"paused", "completed_with_warnings", "failed"},
        "paused": {"running", "recovered", "archived", "failed"},
        "stale": {"recovered", "archived"},
        "pinned": {"archived", "stale"},
    }
    return next_value in allowed.get(previous_value, set())


def normalize_targets(targets: Any) -> list[str]:
    if isinstance(targets, str):
        return [part.strip() for part in re.split(r"[,;\n]+", targets) if part.strip()]
    if isinstance(targets, (list, tuple)):
        return [str(item).strip() for item in targets if str(item).strip()]
    return []


def normalize_toolbox_group(category: str, name: str = "") -> str:
    value = f"{category or ''} {name or ''}".lower()
    if "material" in value or "shader" in value or "texture" in value:
        return "Materials"
    if "rig" in value or "armature" in value or "bone" in value:
        return "Rig"
    if "anim" in value or "keyframe" in value or "action" in value:
        return "Animate"
    if "export" in value or "fbx" in value or "render" in value:
        return "Export"
    if "optimize" in value or "cleanup" in value or "clean" in value:
        return "Optimize"
    if "debug" in value or "inspect" in value or "diagnose" in value:
        return "Debug"
    if "organize" in value or "collection" in value or "asset" in value:
        return "Organize"
    if "modify" in value or "edit" in value:
        return "Modify"
    return "Generate"


def make_context_chip(chip_id: str, label: str, value: str, kind: str, enabled: bool = True, detail: str = "") -> dict[str, Any]:
    return {
        "chip_id": chip_id,
        "label": label,
        "value": compact_text(value, 120),
        "kind": kind,
        "enabled": bool(enabled),
        "detail": compact_text(detail, 240),
    }


def context_payload_from_chips(active_scope: str, chips: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "active_scope": normalize_scope(active_scope),
        "enabled_chips": [chip for chip in chips if chip.get("enabled", True)],
        "all_chips": chips,
    }


def make_action_card(
    *,
    action_id: str | None = None,
    project_id: str = "",
    thread_id: str = "",
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
    timestamps: dict[str, str] | None = None,
    parent_action_id: str = "",
    child_action_ids: Any = None,
    plan_revision: int = 0,
    plan_diff: str = "",
    change_ledger: Any = None,
    result_summary: str = "",
    recovery: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> dict[str, Any]:
    axes = dict(risk_axes or build_risk_axes(prompt=prompt or title, tool_name=tool_name, target_count=len(normalize_targets(affected_targets))))
    inferred_risk, inferred_rationale = risk_from_axes(axes)
    if risk in RISK_LEVELS:
        inferred_risk = risk
    normalized_status = normalize_action_status(status, inferred_risk)
    now = now_iso()
    title_value = title.strip() or compact_text(prompt, 64) or "AI Action"
    created_value = created_at or now
    updated_value = updated_at or now
    timestamp_values = dict(timestamps or {})
    timestamp_values.setdefault("created_at", created_value)
    timestamp_values["updated_at"] = updated_value
    prompt_value = prompt or ""
    plan_value = plan or full_plan or ""
    short_plan_values = normalize_targets(short_plan) if not isinstance(short_plan, str) else normalize_targets(short_plan)
    return {
        "action_id": action_id or make_action_id(),
        "project_id": project_id,
        "thread_id": thread_id,
        "title": title_value,
        "kind": normalize_action_kind(kind or action_kind_from_intent(classify_prompt_intent(prompt_value or title_value))),
        "prompt_preview": compact_text(prompt, 240),
        "plan_preview": compact_text(plan_value or preview_summary, 280),
        "tool_name": tool_name,
        "affected_targets": normalize_targets(affected_targets),
        "required_context": normalize_targets(required_context),
        "risk": inferred_risk,
        "risk_rationale": compact_text(risk_rationale or inferred_rationale, 220),
        "status": normalized_status,
        "approval_required": approval_required_for_risk(inferred_risk),
        "approval_policy": compact_text(approval_policy or approval_policy_for_risk(inferred_risk), 180),
        "scope_summary": compact_text(scope_summary or ", ".join(normalize_targets(affected_targets)) or "Visible context chips define scope.", 220),
        "outcome_summary": compact_text(outcome_summary or result_summary or title_value, 240),
        "preview_summary": compact_text(preview_summary, 240),
        "tool_activity": compact_text(_tool_activity_summary(tool_activity), 220),
        "warnings": normalize_targets(warnings),
        "result_summary": compact_text(result_summary, 240),
        "recovery": compact_text(recovery, 240),
        "created_at": created_value,
        "updated_at": updated_value,
        "detail": {
            "prompt": prompt_value,
            "plan": plan_value,
            "kind": normalize_action_kind(kind or action_kind_from_intent(classify_prompt_intent(prompt_value or title_value))),
            "risk_axes": axes,
            "risk_rationale": risk_rationale or inferred_rationale,
            "scope_summary": scope_summary,
            "outcome_summary": outcome_summary,
            "assumptions": normalize_targets(assumptions),
            "dependencies": normalize_targets(dependencies),
            "preview_summary": preview_summary,
            "short_plan": short_plan_values or ([compact_text(plan_value, 180)] if plan_value else []),
            "full_plan": full_plan or plan_value,
            "approval_policy": approval_policy or approval_policy_for_risk(inferred_risk),
            "tool_activity": _normalize_tool_activity(tool_activity),
            "warnings": normalize_targets(warnings),
            "timestamps": timestamp_values,
            "parent_action_id": parent_action_id,
            "child_action_ids": normalize_targets(child_action_ids),
            "plan_revision": int(plan_revision or 0),
            "plan_diff": plan_diff,
            "change_ledger": _normalize_tool_activity(change_ledger),
            "arguments": arguments or {},
        },
    }


def action_row(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": card.get("action_id", ""),
        "project_id": card.get("project_id", ""),
        "thread_id": card.get("thread_id", ""),
        "title": card.get("title", "AI Action"),
        "kind": card.get("kind", "change"),
        "status": normalize_action_status(card.get("status", ""), card.get("risk", "low")),
        "risk": card.get("risk", "low"),
        "risk_rationale": card.get("risk_rationale", ""),
        "tool_name": card.get("tool_name", ""),
        "approval_required": bool(card.get("approval_required", False)),
        "approval_policy": card.get("approval_policy", ""),
        "affected_targets": card.get("affected_targets", []),
        "required_context": card.get("required_context", []),
        "scope_summary": compact_text(card.get("scope_summary", ""), 220),
        "outcome_summary": compact_text(card.get("outcome_summary", ""), 220),
        "preview_summary": compact_text(card.get("preview_summary", ""), 220),
        "plan_preview": compact_text(card.get("plan_preview", ""), 240),
        "tool_activity": compact_text(card.get("tool_activity", ""), 220),
        "warnings": card.get("warnings", []),
        "result_summary": compact_text(card.get("result_summary", ""), 220),
        "recovery": compact_text(card.get("recovery", ""), 220),
        "updated_at": card.get("updated_at", ""),
    }


def _normalize_tool_activity(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"summary": compact_text(str(item), 240)})
        return normalized
    if isinstance(value, dict):
        return [value]
    if value:
        return [{"summary": compact_text(str(value), 240)}]
    return []


def _tool_activity_summary(value: Any) -> str:
    activity = _normalize_tool_activity(value)
    if not activity:
        return "0 step(s) recorded."
    latest = activity[-1]
    label = latest.get("tool") or latest.get("summary") or latest.get("phase") or "step"
    return f"{len(activity)} step(s); latest: {compact_text(str(label), 120)}"
