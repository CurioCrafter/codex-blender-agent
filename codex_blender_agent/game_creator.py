from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EXECUTION_FRICTION_ITEMS = (
    ("fast", "Fast", "Run local reversible game-creation actions with receipts instead of review gates."),
    ("balanced", "Balanced", "Ask for review before broader edits, exports, or uncertain changes."),
    ("strict", "Strict", "Use the legacy card-first approval model for mutating work."),
)

RISK_LANES = ("informational", "additive", "broad", "destructive", "external", "critical")
AUTO_VISUAL_REVIEW_INTENTS = {"change", "automate"}


@dataclass(frozen=True)
class ExecutionDecision:
    requires_card: bool
    receipt_only: bool
    reason: str


def normalize_friction(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in {"fast", "balanced", "strict"} else "fast"


def risk_lane_for_prompt(classification: dict[str, Any]) -> str:
    intent = str(classification.get("intent", "") or "")
    risk = str(classification.get("risk", "") or "low")
    axes = classification.get("risk_axes", {}) if isinstance(classification.get("risk_axes", {}), dict) else {}
    externality = str(axes.get("externality", ""))
    destructiveness = str(axes.get("destructiveness", ""))
    scope = str(axes.get("scope", ""))
    if risk == "critical" or externality == "critical_side_effect":
        return "critical"
    if intent == "export" or externality in {"external_write", "asset_library_write"}:
        return "external"
    if risk == "high" or destructiveness == "destructive":
        return "destructive"
    if scope in {"many_objects", "whole_scene", "project", "visible_objects"}:
        return "broad"
    if intent in {"change", "automate", "recover"} or risk == "medium":
        return "additive"
    return "informational"


def prompt_execution_decision(
    classification: dict[str, Any],
    *,
    friction: str = "fast",
    require_additive_approval: bool = False,
) -> ExecutionDecision:
    lane = risk_lane_for_prompt(classification)
    mode = normalize_friction(friction)
    if lane == "informational":
        return ExecutionDecision(False, False, "Informational prompts stay in chat.")
    if mode == "strict":
        return ExecutionDecision(True, False, "Strict mode keeps the legacy card-first path.")
    if lane == "additive" and not require_additive_approval:
        return ExecutionDecision(False, True, "Fast game-creation mode runs reversible local changes with receipts.")
    if mode == "fast" and lane == "broad":
        return ExecutionDecision(True, False, "Broad or batch changes still get a lightweight review card.")
    return ExecutionDecision(True, False, "This prompt can affect files, many objects, or destructive state.")


def should_auto_start_visual_review(
    classification: dict[str, Any],
    decision: ExecutionDecision,
    *,
    chat_mode: str = "scene_agent",
    enabled: bool = True,
    prompt: str = "",
) -> bool:
    if not enabled or chat_mode == "chat_only":
        return False
    if decision.requires_card:
        return False
    intent = str(classification.get("intent", "") or "")
    text = (prompt or "").lower()
    if intent == "automate" and any(term in text for term in ("workflow", "recipe", "tutorial")):
        return False
    return intent in AUTO_VISUAL_REVIEW_INTENTS


def tool_execution_decision(
    policy: Any,
    *,
    friction: str = "fast",
    require_additive_approval: bool = False,
) -> ExecutionDecision:
    mode = normalize_friction(friction)
    category = str(getattr(policy, "category", "") or "")
    risk = str(getattr(policy, "risk", "") or "low")
    name = str(getattr(policy, "name", "") or "")
    if not bool(getattr(policy, "requires_action", False)):
        return ExecutionDecision(False, False, "Read-only or action-store tool.")
    if category == "critical" or risk == "critical":
        return ExecutionDecision(True, False, "Critical tools require explicit approval.")
    if category == "external_write" or risk == "high":
        return ExecutionDecision(True, False, "External, broad, or high-risk tools require approval.")
    if name == "call_blender_operator":
        return ExecutionDecision(True, False, "Generic operator calls stay review-gated.")
    if mode == "strict":
        return ExecutionDecision(True, False, "Strict mode keeps card-first mutation.")
    if category == "mutating" and risk == "medium" and not require_additive_approval:
        return ExecutionDecision(False, True, "Fast mode auto-runs local reversible Blender edits and records a receipt.")
    if mode == "fast" and category == "mutating" and risk == "low":
        return ExecutionDecision(False, True, "Fast mode auto-runs low-risk local Blender edits and records a receipt.")
    return ExecutionDecision(True, False, "Balanced mode reviews mutating work.")


def creator_context_payload(context: Any) -> dict[str, Any]:
    wm = getattr(context, "window_manager", None)
    scene = getattr(context, "scene", None)
    selected = list(getattr(context, "selected_objects", []) or [])
    active = getattr(context, "active_object", None)
    workspace = getattr(getattr(context, "window", None), "workspace", None)
    area = getattr(context, "area", None)
    return {
        "mode": "game_creator",
        "friction": normalize_friction(str(getattr(wm, "codex_blender_execution_friction", "fast") if wm else "fast")),
        "scope": str(getattr(wm, "codex_blender_active_scope", "selection") if wm else "selection"),
        "scene": getattr(scene, "name", "Scene") if scene else "",
        "workspace": getattr(workspace, "name", "") if workspace else "",
        "area": getattr(area, "type", "") if area else "",
        "active_object": getattr(active, "name", "") if active else "",
        "selected_objects": [getattr(obj, "name", "") for obj in selected[:50]],
        "selected_count": len(selected),
        "target_engine": str(getattr(wm, "codex_blender_target_engine", "generic") if wm else "generic"),
        "style_hint": str(getattr(wm, "codex_blender_game_style", "") if wm else ""),
    }
