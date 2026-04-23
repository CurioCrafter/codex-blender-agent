from __future__ import annotations

import time
import uuid
from typing import Any


SAFE_TRANSFORM_OPS = {
    "floating_part": "snap_to_support",
    "required_contact_failure": "snap_to_contact",
    "alignment_error": "align_axis",
    "axis_alignment": "align_axis",
    "origin_pivot_error": "set_origin",
    "origin_error": "set_origin",
    "centered_on": "center_on",
    "tiny_detail_missed": "schedule_closeup",
    "undercovered_part": "schedule_closeup",
    "scale_outlier": "bounded_rescale",
    "castle_oversized_moat": "bounded_rescale_zone",
    "castle_zone_violation": "move_out_of_zone",
}

DESTRUCTIVE_OPS = {
    "interpenetration": "separate_or_boolean_union",
    "excessive_overlap": "separate_or_boolean_union",
    "self_intersection": "local_rebuild",
    "non_manifold_topology": "topology_repair",
    "duplicate_surface_risk": "delete_duplicate_surface",
    "z_fighting_risk": "offset_or_merge_surface",
    "castle_battlement_intersection": "seat_or_boolean_union_battlement",
    "castle_unmerged_blockout": "join_or_boolean_rebuild",
    "containment_risk": "extract_contained_part",
}


def build_asset_repair_plan(
    validation_report: dict[str, Any] | None,
    *,
    manifest: dict[str, Any] | None = None,
    constraint_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = dict(validation_report or {})
    manifest = dict(manifest or {})
    policy = dict(manifest.get("repair_policy", {}) or {})
    allow_safe = bool(policy.get("allow_safe_transforms", True))
    allow_destructive = bool(policy.get("allow_destructive_mesh_ops", False))
    safe_actions: list[dict[str, Any]] = []
    gated_actions: list[dict[str, Any]] = []
    for issue in report.get("issues", []) or []:
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get("type", ""))
        action = _action_for_issue(issue)
        if issue_type in DESTRUCTIVE_OPS and not allow_destructive:
            gated_actions.append(_repair_action(issue, DESTRUCTIVE_OPS[issue_type], gated=True, reason="Destructive mesh operation requires explicit approval."))
            continue
        if issue_type in SAFE_TRANSFORM_OPS and allow_safe:
            safe_actions.append(_repair_action(issue, action, gated=False, reason="Safe bounded transform or review-planning action."))
            continue
        gated_actions.append(_repair_action(issue, action, gated=True, reason="No automatically safe repair is available for this issue type."))
    plan = {
        "repair_plan_id": f"asset-repair-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "ready" if safe_actions else ("gated" if gated_actions else "clean"),
        "summary": _summary(safe_actions, gated_actions),
        "validation_report_id": str(report.get("report_id", "")),
        "safe_actions": safe_actions,
        "gated_actions": gated_actions,
        "actions": safe_actions + gated_actions,
        "counts": {"safe": len(safe_actions), "gated": len(gated_actions), "total": len(safe_actions) + len(gated_actions)},
        "constraint_graph": constraint_graph or manifest.get("constraint_graph", {}),
        "policy": {
            "allow_safe_transforms": allow_safe,
            "allow_destructive_mesh_ops": allow_destructive,
            "destructive_requires_approval": bool(policy.get("destructive_requires_approval", True)),
        },
    }
    return plan


def safe_repair_delta_prompt(repair_plan: dict[str, Any], *, max_actions: int = 2) -> dict[str, Any]:
    actions = list(repair_plan.get("safe_actions", []) or [])[: max(int(max_actions), 0)]
    return {
        "mode": "patch",
        "owner_metric": "geometry",
        "targets": [str(action.get("issue_id", "")) for action in actions if str(action.get("issue_id", ""))],
        "preserve": ["asset identity", "style", "object count unless targeted", "materials unless targeted"],
        "forbid": ["global restyle", "external import", "destructive boolean/apply without approval", "delete unrelated objects"],
        "max_edits": len(actions),
        "edits": [
            {
                "target": action.get("target", ""),
                "op": action.get("operation", ""),
                "amount": action.get("bounded_amount", "smallest local correction that satisfies acceptance tests"),
                "issue_id": action.get("issue_id", ""),
            }
            for action in actions
        ],
        "acceptance_tests": [test for action in actions for test in action.get("acceptance_tests", [])][:8],
    }


def generate_repair_plan(
    issues: Any,
    *,
    manifest: dict[str, Any] | None = None,
    constraint_graph: dict[str, Any] | None = None,
    max_actions: int | None = None,
) -> dict[str, Any]:
    report = {"issues": [dict(item) for item in issues or []]}
    manifest_data = _normalize_manifest_for_policy(manifest)
    plan = build_asset_repair_plan(report, manifest=manifest_data, constraint_graph=constraint_graph)
    safe_actions = [_annotate_repair_step(action, requires_approval=False) for action in (plan.get("safe_actions", []) or [])]
    gated_actions = [_annotate_repair_step(action, requires_approval=True) for action in (plan.get("gated_actions", []) or [])]
    if max_actions is not None:
        safe_actions = safe_actions[: max(int(max_actions), 0)]
    decision = "clean"
    if safe_actions and gated_actions:
        decision = "needs_approval"
    elif safe_actions:
        decision = "safe"
    elif gated_actions:
        decision = "blocked"
    plan.update(
        {
            "decision": decision,
            "issue_count": len(report["issues"]),
            "safe_steps": safe_actions,
            "blocked_steps": gated_actions,
            "safe_step_count": len(safe_actions),
            "blocked_step_count": len(gated_actions),
            "preserve": _unique_strings([item for action in safe_actions + gated_actions for item in action.get("preserve", []) or []]),
            "forbid": _unique_strings([item for action in safe_actions + gated_actions for item in action.get("forbid", []) or []]),
        }
    )
    return plan


def _action_for_issue(issue: dict[str, Any]) -> str:
    issue_type = str(issue.get("type", ""))
    return SAFE_TRANSFORM_OPS.get(issue_type) or DESTRUCTIVE_OPS.get(issue_type) or "manual_review"


def _repair_action(issue: dict[str, Any], operation: str, *, gated: bool, reason: str) -> dict[str, Any]:
    target = str(issue.get("target") or ", ".join(str(item) for item in issue.get("objects", []) or []) or "scene")
    return {
        "action_id": f"repair_{operation}_{str(issue.get('issue_id', issue.get('defect_id', 'issue')))}",
        "issue_id": str(issue.get("issue_id", issue.get("defect_id", ""))),
        "issue_type": str(issue.get("type", "")),
        "operation": operation,
        "target": target,
        "objects": list(issue.get("objects", []) or []),
        "severity": str(issue.get("severity", "low")),
        "confidence": float(issue.get("confidence", 0.5) or 0.5),
        "gated": gated,
        "safe": not gated,
        "reason": reason,
        "bounded_amount": _bounded_amount(issue, operation),
        "suggested_fix": str(issue.get("suggested_fix") or issue.get("remediation_hint") or ""),
        "acceptance_tests": list(issue.get("acceptance_tests", []) or []),
        "preserve": ["external silhouette outside local bbox", "materials unless directly targeted", "repeat/symmetry peers"],
        "forbid": ["global remesh", "external import", "delete unrelated geometry", "destructive apply without approval"],
    }


def _bounded_amount(issue: dict[str, Any], operation: str) -> str:
    evidence = issue.get("evidence", {}) if isinstance(issue.get("evidence", {}), dict) else {}
    if operation in {"snap_to_support", "snap_to_contact"}:
        gap = evidence.get("ground_gap", evidence.get("vertical_gap", evidence.get("gap", "")))
        return f"close gap {gap}" if gap != "" else "move only until intended contact is reached"
    if operation in {"align_axis", "set_origin"}:
        return "minimal transform correction within tolerance"
    if operation == "schedule_closeup":
        return "add issue-targeted close-up viewpoint"
    return "smallest local correction that satisfies acceptance tests"


def _summary(safe_actions: list[dict[str, Any]], gated_actions: list[dict[str, Any]]) -> str:
    if not safe_actions and not gated_actions:
        return "No validation repair actions are needed."
    return f"Repair planner found {len(safe_actions)} safe action(s) and {len(gated_actions)} gated action(s)."


def _annotate_repair_step(action: dict[str, Any], *, requires_approval: bool) -> dict[str, Any]:
    step = dict(action)
    step["requires_approval"] = bool(requires_approval)
    step["kind"] = "gated_destructive" if requires_approval else "safe_transform"
    step.setdefault("source_kind", "direct_geometry")
    return step


def _normalize_manifest_for_policy(manifest: dict[str, Any] | None) -> dict[str, Any]:
    manifest = dict(manifest or {})
    policy = dict(manifest.get("repair_policy", {}) or {})
    if "allow_destructive" in policy and "allow_destructive_mesh_ops" not in policy:
        policy["allow_destructive_mesh_ops"] = bool(policy.get("allow_destructive", False))
    if "allow_safe_transforms" not in policy:
        policy["allow_safe_transforms"] = True
    if "destructive_requires_approval" not in policy:
        policy["destructive_requires_approval"] = True
    manifest["repair_policy"] = policy
    return manifest


def _unique_strings(values: Any) -> list[str]:
    items: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in items:
            items.append(text)
    return items
