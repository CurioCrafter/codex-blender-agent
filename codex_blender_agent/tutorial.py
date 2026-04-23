from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class TutorialStep:
    step_id: str
    title: str
    body: str
    workspace: str
    action: str
    expected: str
    recovery: str
    cta_operator: str = ""
    cta_properties: tuple[tuple[str, Any], ...] = ()
    completion: str = ""
    sample_prompt: str = ""


@dataclass(frozen=True)
class Walkthrough:
    walkthrough_id: str
    title: str
    description: str
    steps: tuple[TutorialStep, ...]


def _step(
    step_id: str,
    title: str,
    body: str,
    workspace: str,
    action: str,
    expected: str,
    recovery: str,
    *,
    cta_operator: str = "",
    cta_properties: tuple[tuple[str, Any], ...] = (),
    completion: str = "",
    sample_prompt: str = "",
) -> TutorialStep:
    return TutorialStep(
        step_id=step_id,
        title=title,
        body=body,
        workspace=workspace,
        action=action,
        expected=expected,
        recovery=recovery,
        cta_operator=cta_operator,
        cta_properties=cta_properties,
        completion=completion,
        sample_prompt=sample_prompt,
    )


WALKTHROUGHS: tuple[Walkthrough, ...] = (
    Walkthrough(
        walkthrough_id="first_run",
        title="First AI Studio Run",
        description="Walk through AI Studio, service, scope, workflow, assets, and health checks in order.",
        steps=(
            _step(
                "first_run_open_dashboard",
                "Open AI Studio",
                "AI Studio is the home surface. It shows service state, scene readiness, action cards, pinned outputs, and live activity.",
                "AI Studio",
                "Click Run Step to open AI Studio and make it the starting surface.",
                "AI Studio becomes visible and the tutorial card appears in the Studio card rail.",
                "Use Fix Step to repair the AI Studio workspace and reopen it.",
                cta_operator="codex_blender_agent.open_studio_workspace",
                completion="workspace:AI Studio",
            ),
            _step(
                "first_run_start_service",
                "Start Codex service",
                "The service uses your local Codex login and app-server session. Blender online access must be enabled for service start.",
                "AI Studio",
                "Click Run Step to start the local Codex service.",
                "The connection status changes away from stopped and AI Studio activity updates.",
                "Enable Blender online access or sign in to Codex outside Blender, then try again.",
                cta_operator="codex_blender_agent.start_service",
                completion="service_started",
            ),
            _step(
                "first_run_choose_scope",
                "Choose visible scope",
                "Scope and context chips make the model's working context explicit instead of hidden in chat.",
                "AI Studio",
                "Click Run Step to set AI Scope to Selection and refresh visible context.",
                "The scope switches to Selection and the visible context chips reflect the current selection.",
                "Select an object first, then use Refresh Studio if the chips look stale.",
                cta_operator="codex_blender_agent.set_ai_scope",
                cta_properties=(("scope", "selection"),),
                completion="scope:selection",
            ),
            _step(
                "first_run_create_action",
                "Create an action card",
                "Chat negotiates; cards act. Scene-changing work must become a visible card before any Blender mutation runs.",
                "AI Studio",
                "Click Run Step to seed a safe sample prompt and create an action card.",
                "A reviewable action card appears in AI Studio.",
                "If no card appears, enter a prompt manually and click Create Action.",
                cta_operator="codex_blender_agent.create_action_from_prompt",
                completion="action_card_exists",
                sample_prompt="Inspect the selected object and prepare a safe improvement plan. Do not change the scene yet.",
            ),
            _step(
                "first_run_open_workflow",
                "Open Workflow",
                "Workflow is the orchestration surface. It should feel different from AI Studio and focus on nodes, preview, and run controls.",
                "Workflow",
                "Click Run Step to open Workflow and create the starter graph.",
                "Workflow becomes visible and the Codex AI Workflow graph exists.",
                "Use Repair AI Workspace if the Node Editor is missing.",
                cta_operator="codex_blender_agent.open_workflow_workspace",
                completion="workspace:Workflow",
            ),
            _step(
                "first_run_preview_graph",
                "Preview the graph",
                "Previewing a graph should be inspectable and should surface risky nodes before they mutate Blender data.",
                "Workflow",
                "Click Run Step to preview the starter graph.",
                "Workflow node status fields update and AI Studio activity records the preview.",
                "If preview fails, inspect the selected node's last error and try again.",
                cta_operator="codex_blender_agent.run_workflow_graph",
                cta_properties=(("preview_only", True),),
                completion="workflow_previewed",
            ),
            _step(
                "first_run_open_assets",
                "Open Assets",
                "Assets owns reusable bundles, toolbox systems, imported files, catalogs, and diagnostics.",
                "Assets",
                "Click Run Step to open Assets and register the asset library.",
                "Assets becomes visible and the asset library path is registered or diagnosed.",
                "If registration fails, use Health Check and confirm file permissions.",
                cta_operator="codex_blender_agent.open_assets_workspace",
                completion="workspace:Assets",
            ),
            _step(
                "first_run_health_check",
                "Run health check",
                "Health Check verifies workspace integrity, Layout preservation, node menu wiring, text blocks, and asset status.",
                "AI Studio",
                "Click Run Step to verify the AI workspace suite.",
                "The activity line reports whether the suite is OK and lists missing pieces if not.",
                "Use Repair AI Workspace on any surface reported as missing or broken.",
                cta_operator="codex_blender_agent.verify_workspace_suite",
                completion="health_checked",
            ),
        ),
    ),
    Walkthrough(
        walkthrough_id="build_castle_safely",
        title="Build A Castle Safely",
        description="Turn a castle request into a reviewable action card before any scene mutation.",
        steps=(
            _step(
                "castle_open_dashboard",
                "Open AI Studio",
                "Use AI Studio as the control room for scope, approvals, and recovery.",
                "AI Studio",
                "Click the AI Studio launcher or tab before editing anything.",
                "The AI Studio surface is visible and ready for scope selection.",
                "If the workspace is missing, use Diagnose Workspace and repair it first.",
                cta_operator="codex_blender_agent.open_studio_workspace",
                completion="workspace:AI Studio",
            ),
            _step(
                "castle_choose_scope",
                "Choose scope",
                "Castle blockout work should start with a narrow scope so the model only touches the intended objects or collection.",
                "AI Studio",
                "Set scope to Selection or Collection, then confirm the chips.",
                "The visible scope and context chips match the intended target.",
                "Select the target object or collection before retrying.",
                cta_operator="codex_blender_agent.set_ai_scope",
                cta_properties=(("scope", "selection"),),
                completion="scope:selection",
            ),
            _step(
                "castle_create_card",
                "Create the castle plan",
                "A castle request should become an inspectable action card with plan, risk, affected targets, and recovery.",
                "AI Studio",
                "Type a castle request and click Create Action.",
                "An action card appears with a readable plan preview and risk label.",
                "If the card does not appear, rewrite the prompt with a smaller target and try again.",
                cta_operator="codex_blender_agent.create_action_from_prompt",
                completion="action_card_exists",
                sample_prompt="Create a small medieval castle blockout around the selected area. Show me the plan first and do not delete anything.",
            ),
            _step(
                "castle_preview",
                "Preview the action",
                "Preview should explain scope, risk, and intended tool work without committing a scene change.",
                "AI Studio",
                "Select the card and click Preview.",
                "The card moves to Preview Ready or Awaiting Approval and shows the target and plan clearly.",
                "Use Cancel if the targets or plan are wrong.",
                cta_operator="codex_blender_agent.preview_action",
                completion="action_card_exists",
            ),
            _step(
                "castle_approve",
                "Approve only the safe plan",
                "Approve only if the affected items and recovery path are acceptable.",
                "AI Studio",
                "Click Approve after confirming the scope, risk, and recovery path are safe.",
                "The action transitions into the approved or running state and the result summary updates.",
                "Use Recover or Blender Undo if the result is not acceptable.",
                cta_operator="codex_blender_agent.approve_action",
                completion="action_card_exists",
            ),
            _step(
                "castle_recover",
                "Recover if needed",
                "Recovery should be visible and immediate when the plan changes or the output is wrong.",
                "AI Studio",
                "Click Recover or Stop Turn if the castle workflow is going off course.",
                "The card records recovery guidance and the system stays controllable.",
                "If the action already ran, use Blender Undo or checkpoint recovery.",
                cta_operator="codex_blender_agent.recover_action",
                completion="action_card_exists",
            ),
        ),
    ),
    Walkthrough(
        walkthrough_id="workflow_graph_basics",
        title="Workflow Graph Basics",
        description="Learn the node graph workflow: create, inspect, preview, and review.",
        steps=(
            _step(
                "workflow_open",
                "Open Workflow",
                "Workflow should be node-first, not a copy of AI Studio.",
                "Workflow",
                "Click the Workflow launcher or tab.",
                "The node-orchestration workspace is visible.",
                "Use Repair AI Workspace if the Node Editor is missing.",
                cta_operator="codex_blender_agent.open_workflow_workspace",
                completion="workspace:Workflow",
            ),
            _step(
                "workflow_create_example",
                "Create an example graph",
                "A starter graph should show how snapshot, selection, tool, and approval nodes work together.",
                "Workflow",
                "Click Create Starter Graph to build the default example graph.",
                "The Codex AI Workflow graph exists and contains starter nodes.",
                "If the graph is missing, create it again and inspect the selected node.",
                cta_operator="codex_blender_agent.create_workflow_tree",
                completion="workflow_graph_exists",
                sample_prompt="Build a simple workflow graph that snapshots the scene, inspects selection, then reviews a tool call before running anything risky.",
            ),
            _step(
                "workflow_preview",
                "Preview the graph",
                "Previewing a graph should explain what each node will do before running it.",
                "Workflow",
                "Click Preview Graph and inspect the selected node status.",
                "Node status/result fields update and any risky tool calls become reviewable in AI Studio.",
                "If preview fails, inspect the node error and recreate the starter graph.",
                cta_operator="codex_blender_agent.run_workflow_graph",
                cta_properties=(("preview_only", True),),
                completion="workflow_previewed",
            ),
            _step(
                "workflow_review",
                "Review the result",
                "Workflow runs should send useful actions back to AI Studio so they can be approved, pinned, or recovered.",
                "AI Studio",
                "Open AI Studio and review the created action cards.",
                "AI Studio shows action cards and live activity for the workflow run.",
                "If nothing appears, refresh AI Studio and preview the graph again.",
                cta_operator="codex_blender_agent.open_studio_workspace",
                completion="action_card_exists",
            ),
        ),
    ),
    Walkthrough(
        walkthrough_id="save_reuse_asset",
        title="Save And Reuse Asset",
        description="Save selected objects into the asset workspace and reuse them in another scene.",
        steps=(
            _step(
                "asset_open",
                "Open Assets",
                "Assets is the reuse workspace for bundles, catalogs, and imported files.",
                "Assets",
                "Click the Assets launcher or tab.",
                "The asset-focused workspace is visible.",
                "Repair the asset workspace if the Properties or File Browser areas are missing.",
                cta_operator="codex_blender_agent.open_assets_workspace",
                completion="workspace:Assets",
            ),
            _step(
                "asset_register",
                "Register the asset library",
                "A registered asset library makes save and reuse operations predictable and searchable.",
                "Assets",
                "Click Register Asset Library if the library path is not already available.",
                "The local asset library path becomes registered and visible in diagnostics.",
                "If registration fails, confirm file permissions and use Health Check.",
                cta_operator="codex_blender_agent.register_asset_library",
                completion="asset_library_registered",
            ),
            _step(
                "asset_save",
                "Save the selection",
                "Selected objects should become a reusable .blend bundle with metadata and provenance.",
                "Assets",
                "Select one or more objects, enter a clear asset name, then click Save Selected.",
                "The saved asset appears in the asset list and can be reused later.",
                "If no objects are selected, choose a target and save again.",
                cta_operator="codex_blender_agent.save_selected_asset",
                sample_prompt="Save the selected cube as a reusable asset named Castle Blockout Base.",
                completion="asset_saved",
            ),
            _step(
                "asset_refresh_import",
                "Refresh and import",
                "Refreshing should reveal the saved item, and import should bring it back into a fresh scene.",
                "Assets",
                "Click Refresh Assets, select the saved item, then click Import Selected.",
                "The asset list updates and the object appears in the current scene again.",
                "If the item is missing, refresh again or verify the saved asset name.",
                cta_operator="codex_blender_agent.import_selected_asset",
                completion="asset_imported",
            ),
            _step(
                "asset_toolbox_action",
                "Turn reuse into a workflow",
                "Reusable assets should also be able to become toolbox actions for repeatable workflows.",
                "Assets",
                "Select a toolbox item and click Create Toolbox Action.",
                "A reviewable action card is created for the reusable system.",
                "If the item is experimental, inspect it before promoting it to repeat use.",
                cta_operator="codex_blender_agent.create_toolbox_action",
                completion="toolbox_action_created",
            ),
        ),
    ),
    Walkthrough(
        walkthrough_id="stop_and_recover",
        title="Stop And Recover",
        description="Learn how to interrupt, steer, cancel, and recover a running or failed turn.",
        steps=(
            _step(
                "recover_open_dashboard",
                "Open AI Studio",
                "Recovery controls live where the current prompt, action cards, and activity are visible.",
                "AI Studio",
                "Open AI Studio before starting a non-destructive prompt.",
                "AI Studio shows Stop, Steer, Cancel, and Recover controls in context.",
                "If AI Studio is missing, repair the workspace and try again.",
                cta_operator="codex_blender_agent.open_studio_workspace",
                completion="workspace:AI Studio",
            ),
            _step(
                "recover_start_prompt",
                "Start a prompt safely",
                "Use a non-destructive prompt so you can practice interruption and recovery without changing scene data.",
                "AI Studio",
                "Type a short explanation request and click Send Draft or Send.",
                "The activity strip shows Codex working and the transcript begins to update.",
                "If the prompt is wrong, edit the draft and send again.",
                cta_operator="codex_blender_agent.send_prompt_from_text",
                sample_prompt="Explain what is selected and suggest safe improvements. Do not change the scene.",
                completion="prompt_sent",
            ),
            _step(
                "recover_stop",
                "Stop the turn",
                "Stop Turn should interrupt the current response without killing the service.",
                "AI Studio",
                "Click Stop Turn while the model is running.",
                "The activity indicates the turn stopped and the UI remains responsive.",
                "If the model is already idle, start a new prompt first and try again.",
                cta_operator="codex_blender_agent.stop_turn",
                completion="turn_stopped",
            ),
            _step(
                "recover_steer",
                "Steer the running turn",
                "If the turn is still active, Guide Running Turn can change direction without restarting everything.",
                "AI Studio",
                "Add a short steering note and click Guide Running Turn.",
                "The activity shows that the turn received steering guidance.",
                "If the turn is not running, send a new prompt and try again.",
                cta_operator="codex_blender_agent.steer_turn",
                sample_prompt="Focus on the selected object only and keep the change non-destructive.",
                completion="turn_steered",
            ),
            _step(
                "recover_cancel",
                "Cancel the action",
                "Pending scene-changing work should be cancellable before execution.",
                "AI Studio",
                "Select the action card and click Cancel.",
                "The card changes to a cancelled or recovered state instead of running blindly.",
                "If the action already ran, use Blender Undo or a checkpoint copy.",
                cta_operator="codex_blender_agent.cancel_action",
                completion="action_card_exists",
            ),
        ),
    ),
)

WALKTHROUGH_ALIASES = {
    "ask_scene": "first_run",
    "safe_change": "build_castle_safely",
}


def walkthrough_ids() -> tuple[str, ...]:
    return tuple(item.walkthrough_id for item in WALKTHROUGHS)


def walkthrough_items() -> list[tuple[str, str, str]]:
    return [(item.walkthrough_id, item.title, item.description) for item in WALKTHROUGHS]


def get_walkthrough(walkthrough_id: str) -> Walkthrough:
    lookup = WALKTHROUGH_ALIASES.get(walkthrough_id, walkthrough_id)
    for walkthrough in WALKTHROUGHS:
        if walkthrough.walkthrough_id == lookup:
            return walkthrough
    return WALKTHROUGHS[0]


def clamp_step_index(walkthrough_id: str, step_index: int) -> int:
    walkthrough = get_walkthrough(walkthrough_id)
    if not walkthrough.steps:
        return 0
    return max(0, min(int(step_index), len(walkthrough.steps) - 1))


def current_step(walkthrough_id: str, step_index: int) -> TutorialStep:
    walkthrough = get_walkthrough(walkthrough_id)
    return walkthrough.steps[clamp_step_index(walkthrough_id, step_index)]


def step_count(walkthrough_id: str) -> int:
    return len(get_walkthrough(walkthrough_id).steps)


def progress_label(walkthrough_id: str, step_index: int) -> str:
    count = step_count(walkthrough_id)
    current = clamp_step_index(walkthrough_id, step_index) + 1
    return f"Step {current} of {count}"


def all_steps() -> Iterable[TutorialStep]:
    for walkthrough in WALKTHROUGHS:
        yield from walkthrough.steps


def find_step(step_id: str) -> TutorialStep | None:
    for step in all_steps():
        if step.step_id == step_id:
            return step
    return None
