from __future__ import annotations

import pytest

from codex_blender_agent.workflow_execution import (
    WorkflowExecutionError,
    apply_workflow_patch,
    build_workflow_plan_summary,
    compile_workflow_graph,
    ensure_workflow_root_nodes,
    get_workflow_node_spec,
    is_action_card_stale,
    is_snapshot_stale,
    list_workflow_node_categories,
    list_workflow_node_types,
    node_can_preview,
    node_execution_policy,
    node_preview_mode,
    node_requires_action_card,
    normalize_recipe_pin_mode,
    normalize_workflow_graph,
    normalize_workflow_node_type,
    preview_workflow_graph,
    preview_workflow_patch,
    propose_workflow_patch,
    result_is_success,
    retain_last_good_result,
    resume_workflow_run,
    select_recipe_version,
    socket_types_compatible,
    start_workflow_run,
    stop_workflow_run,
    transition_workflow_node_state,
    transition_workflow_run_state,
    validate_workflow_graph,
    validate_workflow_patch,
    workflow_add_menu_entries,
    workflow_graph_diff,
    workflow_graph_hash,
    workflow_graph_manifest,
)


def _approval_graph() -> dict[str, object]:
    return {
        "name": "Action First",
        "nodes": [
            {"name": "Workflow Input", "node_type": "workflow_input"},
            {"name": "Delete", "node_type": "tool_call", "tool_name": "delete_object"},
            {"name": "Workflow Output", "node_type": "workflow_output"},
        ],
        "links": [
            {"from_node": "Workflow Input", "from_socket": "Flow", "to_node": "Delete", "to_socket": "Flow"},
            {"from_node": "Delete", "from_socket": "Flow", "to_node": "Workflow Output", "to_socket": "Flow"},
        ],
    }


def _preview_graph() -> dict[str, object]:
    return {
        "name": "Previewable",
        "nodes": [
            {"name": "Workflow Input", "node_type": "workflow_input"},
            {"name": "Preview", "node_type": "preview_tap"},
            {"name": "Workflow Output", "node_type": "workflow_output"},
        ],
        "links": [
            {"from_node": "Workflow Input", "from_socket": "Flow", "to_node": "Preview", "to_socket": "Any"},
            {"from_node": "Preview", "from_socket": "Any", "to_node": "Workflow Output", "to_socket": "Flow"},
        ],
    }


def test_registry_aliases_and_categories_are_stable():
    assert normalize_workflow_node_type("toolbox recipe") == "recipe_call"
    spec = get_workflow_node_spec("toolbox_recipe")
    assert spec.node_type == "recipe_call"
    assert "Recipes" in list_workflow_node_categories()
    assert "workflow_input" in list_workflow_node_types()
    assert any(entry["node_type"] == "recipe_call" for entry in workflow_add_menu_entries())


def test_socket_compatibility_model_is_explicit():
    assert socket_types_compatible("Flow", "Flow") is True
    assert socket_types_compatible("Any", "Artifact") is True
    assert socket_types_compatible("Scalar", "Flow") is False


def test_root_nodes_are_added_without_mutating_layout():
    graph = ensure_workflow_root_nodes({})
    assert [node["node_type"] for node in graph["nodes"]] == ["workflow_input", "workflow_output"]
    normalized = normalize_workflow_graph({})
    assert normalized["name"] == "Codex AI Workflow"


def test_validation_reports_invalid_links_and_action_card_requirements():
    graph = {
        "name": "Invalid",
        "nodes": [
            {"name": "Workflow Input", "node_type": "workflow_input"},
            {"name": "Value", "node_type": "value"},
            {"name": "Workflow Output", "node_type": "workflow_output"},
            {"name": "Delete", "node_type": "tool_call", "tool_name": "delete_object"},
        ],
        "links": [
            {"from_node": "Workflow Input", "from_socket": "Flow", "to_node": "Workflow Output", "to_socket": "Flow"},
            {"from_node": "Value", "from_socket": "Scalar", "to_node": "Workflow Output", "to_socket": "Flow"},
        ],
    }

    validation = validate_workflow_graph(graph)
    assert validation["ok"] is False
    assert any(issue["code"] == "socket_type_mismatch" for issue in validation["errors"])
    assert any(issue["code"] == "action_card_required" for issue in validation["errors"])

    policy = node_execution_policy({"name": "Delete", "node_type": "tool_call", "tool_name": "delete_object"})
    assert policy["requires_action_card"] is True
    assert policy["allowed"] is False


def test_action_card_policy_allows_approved_execution():
    node = {
        "name": "Delete",
        "node_type": "tool_call",
        "tool_name": "delete_object",
        "action_card_ref": "card-1",
    }
    policy = node_execution_policy(
        node,
        approved_cards=[{"action_id": "card-1", "status": "approved"}],
    )
    assert policy["requires_action_card"] is True
    assert policy["allowed"] is True
    assert policy["approved_card_status"] == "approved"
    assert policy["tool_policy"]["category"] == "mutating"
    assert node_requires_action_card(node) is True


def test_preview_and_compile_keep_preview_only_workflow_pure():
    graph = _preview_graph()
    preview = preview_workflow_graph(graph)
    compiled = compile_workflow_graph(graph)

    assert preview["preview_only"] is True
    assert preview["preview_steps"][1]["execution_allowed"] is True
    assert preview["preview_steps"][1]["preview_summary"].startswith("Preview")
    assert compiled["ok"] is True
    assert compiled["requires_approval"] is False
    assert node_can_preview({"node_type": "assistant_prompt"}) is True
    assert node_preview_mode({"node_type": "preview_tap"}) == "static"


def test_start_resume_and_stop_track_run_state_and_staleness():
    run = start_workflow_run(_approval_graph(), current_snapshot_hash="snap-a")
    assert run["state"] == "waiting_approval"
    assert "Delete" in run["blocked_nodes"]

    resumed = resume_workflow_run(run, current_snapshot_hash="snap-b")
    assert resumed["state"] == "stale"
    assert resumed["stale_reason"]

    stopped = stop_workflow_run({"state": "running"}, reason="user stop")
    assert stopped["state"] == "paused"
    assert stopped["stop_reason"] == "user stop"


def test_state_transitions_cover_forward_and_invalid_edges():
    assert transition_workflow_node_state("draft", "ready") == "ready"
    assert transition_workflow_run_state("draft", "queued") == "queued"
    with pytest.raises(WorkflowExecutionError):
        transition_workflow_node_state("completed", "running")
    with pytest.raises(WorkflowExecutionError):
        transition_workflow_run_state("completed", "running")


def test_stale_detection_and_last_good_result_retention():
    assert is_snapshot_stale("snap-a", "snap-b") is True
    assert is_action_card_stale({"status": "approved", "snapshot_hash": "snap-a"}, current_snapshot_hash="snap-b") is True
    assert is_action_card_stale({"status": "completed", "snapshot_hash": "snap-a"}, current_snapshot_hash="snap-b") is False

    previous = {"state": "completed", "last_result_summary": "Good result"}
    current = {"state": "failed", "last_result_summary": ""}
    retained = retain_last_good_result(previous, current)
    assert retained["last_good_result"]["last_result_summary"] == "Good result"
    assert retained["last_result_summary"] == "Good result"
    assert result_is_success(retained["last_good_result"]) is True


def test_recipe_version_selection_respects_pin_modes():
    assert normalize_recipe_pin_mode("Latest Within Major") == "latest_within_major"
    compatible = select_recipe_version(["1.0.0", "1.2.0", "2.0.0"], requested_version="1.1.0")
    assert compatible["selected"] == "1.2.0"
    exact = select_recipe_version(["1.0.0", "1.2.0"], requested_version="1.2.0", pin_mode="exact")
    assert exact["selected"] == "1.2.0"
    latest = select_recipe_version(["1.0.0", "1.2.0", "2.0.0"], requested_version="1.0.0", pin_mode="latest_within_major")
    assert latest["selected"] == "1.2.0"


def test_patch_proposal_preview_and_apply_are_staged_and_diffed():
    base = {
        "name": "Patch Base",
        "nodes": [
            {"name": "Workflow Input", "node_type": "workflow_input"},
            {"name": "Workflow Output", "node_type": "workflow_output"},
        ],
        "links": [],
    }
    ops = [
        {"op": "add_node", "node": {"name": "Preview", "node_type": "preview_tap"}},
        {"op": "add_link", "link": {"from_node": "Workflow Input", "from_socket": "Flow", "to_node": "Preview", "to_socket": "Any"}},
        {"op": "add_link", "link": {"from_node": "Preview", "from_socket": "Any", "to_node": "Workflow Output", "to_socket": "Flow"}},
    ]

    proposal = propose_workflow_patch(base, ops)
    preview = preview_workflow_patch(base, ops)
    applied = apply_workflow_patch(base, ops)
    diff = workflow_graph_diff(base, applied["graph"])

    assert proposal["ok"] is True
    assert preview["preview_only"] is True
    assert "Preview" in proposal["diff"]["added_nodes"]
    assert applied["graph_hash"] == workflow_graph_hash(applied["graph"])
    assert "Preview" in diff["added_nodes"]
    assert validate_workflow_patch(base, ops)["ok"] is True
    assert build_workflow_plan_summary(proposal["validation"]) != ""


def test_manifest_hash_is_deterministic_for_normalized_graphs():
    graph = _preview_graph()
    manifest_a = workflow_graph_manifest(graph)
    manifest_b = workflow_graph_manifest(normalize_workflow_graph(graph))
    assert manifest_a == manifest_b
    assert workflow_graph_hash(graph) == workflow_graph_hash(normalize_workflow_graph(graph))
