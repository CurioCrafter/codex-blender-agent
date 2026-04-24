from __future__ import annotations

from typing import Any


LANES = ("setup", "ask", "build", "review", "assets", "recover")

LANE_DEFINITIONS: dict[str, dict[str, str]] = {
    "setup": {
        "label": "Setup",
        "summary": "Start Codex, confirm login, load models, and verify the local console.",
        "recovery": "Use Start / Refresh Models, Login / Re-login, or restart the service.",
    },
    "ask": {
        "label": "Ask",
        "summary": "Explain the scene, inspect selection, or plan before changing anything.",
        "recovery": "If answers are weak, refresh models and narrow the active scope.",
    },
    "build": {
        "label": "Build",
        "summary": "Create or modify Blender content through governed game-asset workflows.",
        "recovery": "Use Stop Turn, receipts, or Blender Undo if the result goes wrong.",
    },
    "review": {
        "label": "Review",
        "summary": "Check active cards, screenshots, validation reports, and tool output.",
        "recovery": "Open the web console, run visual review, or inspect the latest receipt.",
    },
    "assets": {
        "label": "Assets",
        "summary": "Save useful work as reusable AI Assets with provenance and validation.",
        "recovery": "Open Assets, initialize the store, then publish selected content through a review card.",
    },
    "recover": {
        "label": "Recover",
        "summary": "Undo or repair the last AI change and understand what happened.",
        "recovery": "Use Recover Last Change, action details, or Blender Undo before retrying.",
    },
}


def lane_payloads(current_lane: str = "ask") -> list[dict[str, Any]]:
    selected = normalize_lane(current_lane)
    return [
        {
            "id": lane_id,
            "selected": lane_id == selected,
            **LANE_DEFINITIONS[lane_id],
        }
        for lane_id in LANES
    ]


def normalize_lane(value: str) -> str:
    lane = (value or "").strip().lower()
    return lane if lane in LANE_DEFINITIONS else "ask"


def choose_lane(state: dict[str, Any]) -> str:
    if not state.get("online_access", True) or not state.get("service_running") or not state.get("model_ready"):
        return "setup"
    if state.get("failed_action_count", 0) or state.get("last_error"):
        return "recover"
    if state.get("pending") or state.get("active_tool_count", 0):
        return "review"
    if state.get("asset_focus"):
        return "assets"
    if state.get("has_selection") or state.get("has_prompt"):
        return "build"
    return "ask"


def readiness_checklist(state: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(state.get("active_scope") or "selection")
    asset_count = int(state.get("asset_count") or 0)
    workspace = str(state.get("workspace") or "Current Blender workspace")
    return [
        _check(
            "online_access",
            "Online access",
            bool(state.get("online_access", True)),
            "Blender can start and talk to the local Codex app-server.",
            "Enable Blender online access, then refresh models.",
        ),
        _check(
            "service",
            "Codex service",
            bool(state.get("service_running")),
            str(state.get("service_status") or "Local Codex app-server connection."),
            "Click Start / Refresh Models.",
        ),
        _check(
            "login",
            "Login",
            bool(state.get("account")),
            str(state.get("account") or "ChatGPT login not confirmed."),
            "Use Login / Re-login, then Refresh Models.",
        ),
        _check(
            "models",
            "Model availability",
            bool(state.get("model_ready")),
            str(state.get("selected_model_label") or state.get("unavailable_reason") or "No model loaded yet."),
            "Click Start / Refresh Models before writing the prompt.",
        ),
        _check(
            "web_console",
            "Web console",
            bool(state.get("web_console_running")),
            "Live browser console is available." if state.get("web_console_running") else "Web console is stopped.",
            "Start Web Console when you want a larger live view.",
            warn_only=True,
        ),
        _check(
            "scope",
            "Active scope",
            bool(scope),
            f"AI scope is {scope}; selected objects: {int(state.get('selected_count') or 0)}.",
            "Use scope chips if the AI should focus on selection or whole scene.",
        ),
        _check(
            "assets",
            "Asset library",
            asset_count > 0 or bool(state.get("asset_library_ready")),
            f"{asset_count} visible asset record(s)." if asset_count else "No visible asset records yet.",
            "Open Assets or save selected content as a reusable asset.",
            warn_only=True,
        ),
        _check(
            "workspace",
            "Workspace health",
            bool(workspace),
            workspace,
            "Create AI Workspaces if the Studio, Workflow, or Assets tabs are missing.",
            warn_only=True,
        ),
    ]


def explanation_context(
    *,
    model_state: dict[str, Any] | None = None,
    active_scope: str = "selection",
    current_lane: str = "ask",
    active_tool: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = dict(model_state or {})
    lane = normalize_lane(current_lane)
    tool = dict(active_tool or {})
    tool_name = str(tool.get("tool_name") or "")
    return {
        "panels": {
            "AI Command Center": "The main workflow surface: setup, ask, build, review, assets, and recovery in one place.",
            "Readiness Checklist": "Shows whether the service, login, model list, web console, scope, and asset store are ready.",
            "Ask AI": "Choose model and reasoning first, then type the prompt and send it.",
            "AI Flight Recorder": "Shows the current step, running tool, elapsed time, affected area, and next expected step.",
            "What AI Can Do Now": "Context-aware workflow buttons that are safe or useful for the current scene state.",
        },
        "status_legend": [
            {"status": "ready", "label": "Ready", "meaning": "Available now."},
            {"status": "warning", "label": "Needs setup", "meaning": "Usable, but a setup step will improve reliability."},
            {"status": "blocked", "label": "Blocked", "meaning": "Cannot run until the listed recovery step is done."},
            {"status": "running", "label": "Running", "meaning": "Codex or a Blender tool is currently working."},
        ],
        "risk_legend": [
            {"risk": "low", "meaning": "Read-only, planning, or reversible local setup."},
            {"risk": "medium", "meaning": "May change objects or materials but should stay reviewable and recoverable."},
            {"risk": "high", "meaning": "Writes files, imports data, or broad scene operations; review card expected."},
            {"risk": "critical", "meaning": "Arbitrary execution or destructive work; advanced explicit approval required."},
        ],
        "scope": {
            "current": active_scope or "selection",
            "meaning": _scope_meaning(active_scope),
            "recovery": "Switch scope or selection before sending if the AI is looking at the wrong target.",
        },
        "model": {
            "selected": model.get("selected_model") or "",
            "label": model.get("selected_label") or "",
            "ready": bool(model.get("model_ready")),
            "meaning": _model_meaning(model),
            "recovery": model.get("unavailable_reason") or "Use Start / Refresh Models if the list is empty.",
        },
        "lane": {
            "current": lane,
            **LANE_DEFINITIONS[lane],
        },
        "active_tool": {
            "tool_name": tool_name,
            "meaning": _tool_meaning(tool),
            "recovery": "If this stalls, open the web console, stop the turn, or recover the latest action card.",
        },
    }


def available_workflows(state: dict[str, Any]) -> list[dict[str, Any]]:
    model_ready = bool(state.get("model_ready"))
    service_running = bool(state.get("service_running"))
    has_selection = bool(state.get("has_selection"))
    selected_mesh_count = int(state.get("selected_mesh_count") or 0)
    has_prompt = bool(state.get("has_prompt"))
    has_attachments = bool(state.get("has_attachments"))
    action_count = int(state.get("action_count") or 0)
    active = bool(state.get("pending") or state.get("active_tool_count", 0))
    base_block = "Refresh models first." if not model_ready else ""
    scene_ready = service_running and model_ready and not active

    actions = [
        _workflow(
            "refresh_models",
            "setup",
            "Start / Refresh Models",
            "codex_blender_agent.run_recommended_workflow",
            "Start Codex and load the model list before prompting.",
            True,
            "",
            "low",
        ),
        _workflow(
            "explain_scene",
            "ask",
            "Explain Scene",
            "codex_blender_agent.run_recommended_workflow",
            "Ask what the AI sees, what is selected, and what to do next.",
            scene_ready,
            base_block or ("Wait for the running turn to finish." if active else ""),
            "low",
        ),
        _workflow(
            "fix_selected",
            "build",
            "Fix Selected",
            "codex_blender_agent.run_recommended_workflow",
            "Clean selected objects for game use: names, scale, origins, materials, and export readiness.",
            scene_ready and has_selection,
            "Select a mesh or object first." if not has_selection else base_block,
            "medium",
        ),
        _workflow(
            "make_game_asset",
            "build",
            "Make Game Asset",
            "codex_blender_agent.run_recommended_workflow",
            "Turn the current selection or prompt into a game-ready prop workflow.",
            scene_ready and (has_selection or has_prompt),
            "Select an object or type a prompt." if not (has_selection or has_prompt) else base_block,
            "medium",
        ),
        _workflow(
            "generate_reference_image",
            "assets",
            "Generate Reference Image",
            "codex_blender_agent.run_recommended_workflow",
            "Create a pinned image-generation brief for concept, modeling, or texture reference.",
            scene_ready and (has_prompt or has_selection or has_attachments),
            "Type a short visual request, select an object, or attach a reference.",
            "low",
        ),
        _workflow(
            "review_with_screenshots",
            "review",
            "Review With Screenshots",
            "codex_blender_agent.run_recommended_workflow",
            "Run the visual review loop with geometry checks, screenshots, and critic feedback.",
            scene_ready and (has_selection or selected_mesh_count > 0 or has_prompt),
            "Select or describe what should be reviewed.",
            "medium",
        ),
        _workflow(
            "save_reusable_asset",
            "assets",
            "Save As Reusable Asset",
            "codex_blender_agent.run_recommended_workflow",
            "Create a reviewable AI Assets publish card for the current selection.",
            has_selection,
            "Select the object(s) you want to save.",
            "high",
        ),
        _workflow(
            "recover_last_change",
            "recover",
            "Recover Last Change",
            "codex_blender_agent.run_recommended_workflow",
            "Open recovery for the latest action card or use Blender Undo for the last AI change.",
            bool(action_count),
            "No AI action card is available yet.",
            "low",
        ),
        _workflow(
            "open_web_console",
            "review",
            "Open Live Console",
            "codex_blender_agent.run_recommended_workflow",
            "Open the browser dashboard for current tool calls, health, screenshots, and logs.",
            True,
            "",
            "low",
        ),
    ]
    return actions


def command_center_payload(state: dict[str, Any]) -> dict[str, Any]:
    lane = choose_lane(state)
    model_state = dict(state.get("model_state") or {})
    active_tool = dict(state.get("active_tool") or {})
    return {
        "title": "AI Command Center",
        "current_lane": lane,
        "lanes": lane_payloads(lane),
        "model_state": model_state,
        "readiness_checklist": readiness_checklist({**state, **model_state}),
        "available_workflows": available_workflows({**state, **model_state}),
        "explanations": explanation_context(
            model_state=model_state,
            active_scope=str(state.get("active_scope") or "selection"),
            current_lane=lane,
            active_tool=active_tool,
        ),
    }


def _check(
    check_id: str,
    label: str,
    ok: bool,
    detail: str,
    recovery: str,
    *,
    warn_only: bool = False,
) -> dict[str, Any]:
    status = "ready" if ok else ("warning" if warn_only else "blocked")
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "ready": bool(ok),
        "detail": detail,
        "recovery": "" if ok else recovery,
    }


def _workflow(
    action_id: str,
    lane: str,
    label: str,
    operator: str,
    description: str,
    enabled: bool,
    reason: str,
    risk: str,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "lane": normalize_lane(lane),
        "label": label,
        "operator": operator,
        "description": description,
        "enabled": bool(enabled),
        "status": "ready" if enabled else "blocked",
        "reason": "" if enabled else reason,
        "risk": risk,
    }


def _scope_meaning(scope: str) -> str:
    normalized = (scope or "selection").strip().lower()
    if normalized == "selection":
        return "The selected objects are treated as the primary target."
    if normalized == "scene":
        return "The whole scene can be inspected and planned against."
    if normalized == "workspace":
        return "The AI Studio workspace, memory, and visible panels matter most."
    return "The enabled context chips define what the AI should prioritize."


def _model_meaning(model: dict[str, Any]) -> str:
    if model.get("model_ready"):
        label = model.get("selected_label") or model.get("selected_model") or "selected model"
        effort = model.get("reasoning_effort") or "default"
        return f"{label} is ready; reasoning effort is {effort}."
    return "No model has been loaded yet; prompting will be less predictable until models are refreshed."


def _tool_meaning(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool_name") or "")
    if not name:
        return "No tool is running right now."
    status = str(tool.get("status") or "running")
    category = str(tool.get("category") or "tool")
    summary = str(tool.get("summary") or "")
    return f"{name} is {status} in the {category} lane. {summary}".strip()
