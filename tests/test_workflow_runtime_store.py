from __future__ import annotations

import json
import sqlite3

from codex_blender_agent.workflow_runtime_store import (
    WorkflowRuntimeStore,
    canonicalize_workflow_manifest,
    hash_workflow_manifest,
    serialize_workflow_manifest,
)


def _make_store(tmp_path):
    return WorkflowRuntimeStore(tmp_path / "authority", legacy_root=tmp_path / "legacy")


def test_workflow_runtime_store_initializes_schema_and_wal(tmp_path):
    store = _make_store(tmp_path)

    diagnostic = store.initialize()

    assert diagnostic["schema_version"] == "1"
    assert diagnostic["wal_enabled"] is True
    assert (tmp_path / "authority" / "workflow_runtime.db").exists()

    with sqlite3.connect(tmp_path / "authority" / "workflow_runtime.db") as con:
        tables = {row[0] for row in con.execute("select name from sqlite_master where type = 'table'")}

    assert {
        "meta",
        "workflow_graphs",
        "workflow_nodes",
        "workflow_links",
        "workflow_runs",
        "workflow_run_nodes",
        "workflow_checkpoints",
        "recipe_versions",
        "recipe_tests",
        "patch_proposals",
        "patch_events",
        "health_events",
    }.issubset(tables)


def test_workflow_runtime_manifest_hash_is_deterministic(tmp_path):
    store = _make_store(tmp_path)
    manifest_a = {
        "graph_id": "workflow:main",
        "name": "Main",
        "kind": "workflow",
        "nodes": [{"node_id": "b", "node_name": "B"}, {"node_id": "a", "node_name": "A"}],
        "links": [{"link_id": "link-1", "from_node": "a", "from_socket": "Flow", "to_node": "b", "to_socket": "Flow"}],
        "metadata": {"b": 2, "a": 1},
    }
    manifest_b = json.loads(json.dumps(manifest_a))
    manifest_b["metadata"] = {"a": 1, "b": 2}

    assert canonicalize_workflow_manifest(manifest_a) == canonicalize_workflow_manifest(manifest_b)
    assert serialize_workflow_manifest(manifest_a) == serialize_workflow_manifest(manifest_b)
    assert hash_workflow_manifest(manifest_a) == hash_workflow_manifest(manifest_b)
    assert store.hash_graph_manifest(manifest_a) == store.hash_graph_manifest(manifest_b)


def test_workflow_runtime_migrates_legacy_json_with_backups(tmp_path):
    store = _make_store(tmp_path)
    legacy = tmp_path / "legacy"
    legacy.mkdir()

    payload = {
        "graphs": [
            {
                "graph_id": "workflow:legacy",
                "name": "Legacy Workflow",
                "kind": "workflow",
                "status": "draft",
                "manifest": {
                    "graph_id": "workflow:legacy",
                    "name": "Legacy Workflow",
                    "kind": "workflow",
                    "nodes": [
                        {"node_id": "input", "node_name": "Workflow Input", "node_type": "workflow_input"},
                        {"node_id": "call", "node_name": "Assistant Call", "node_type": "assistant_call"},
                    ],
                    "links": [
                        {
                            "link_id": "link-legacy",
                            "from_node": "input",
                            "from_socket": "Flow",
                            "to_node": "call",
                            "to_socket": "Flow",
                        }
                    ],
                },
                "nodes": [
                    {"node_id": "input", "node_name": "Workflow Input", "node_type": "workflow_input"},
                    {"node_id": "call", "node_name": "Assistant Call", "node_type": "assistant_call"},
                ],
                "links": [
                    {
                        "link_id": "link-legacy",
                        "from_node": "input",
                        "from_socket": "Flow",
                        "to_node": "call",
                        "to_socket": "Flow",
                    }
                ],
            }
        ],
        "runs": [
            {
                "run_id": "run-legacy",
                "graph_id": "workflow:legacy",
                "manifest": {"graph_id": "workflow:legacy", "name": "Legacy Workflow", "kind": "workflow"},
                "preview_only": False,
                "snapshot_hash": "snapshot-hash",
                "input_hash": "input-hash",
                "run_label": "Legacy run",
                "status": "completed",
                "action_card_ref": "card-1",
                "nodes": [
                    {
                        "node_id": "call",
                        "node_name": "Assistant Call",
                        "node_type": "assistant_call",
                        "state": "completed",
                        "freshness": "clean",
                        "risk_level": "write",
                        "warning_count": 1,
                        "start_at": "2026-04-21T00:00:00Z",
                        "end_at": "2026-04-21T00:00:05Z",
                        "duration_ms": 5000,
                        "result_summary": "Done",
                        "error_summary": "",
                        "action_card_ref": "card-1",
                        "detail": {"phase": "commit"},
                    }
                ],
                "checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-1",
                        "label": "Before commit",
                        "state": {"phase": "preview"},
                        "node_id": "call",
                        "snapshot_hash": "snapshot-hash",
                        "resume_token": "resume-token",
                    }
                ],
            }
        ],
        "recipes": [
            {
                "recipe_id": "recipe:legacy-material",
                "version": "1.2.3",
                "name": "Legacy Material",
                "graph_id": "workflow:legacy",
                "manifest": {"recipe_id": "recipe:legacy-material", "version": "1.2.3"},
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "required_tools": ["tool.call"],
                "risk_profile": "write",
                "author": "Example Author",
                "changelog": "Initial",
                "preview_path": "previews/legacy.png",
                "tests": [{"name": "smoke", "state": "passed"}],
                "tags": ["material"],
                "catalog_path": "recipes/materials",
                "compatibility": {"blender_min": "4.5.8"},
                "status": "approved",
                "recipe_version_uid": "recipever:legacy-material@1.2.3",
            }
        ],
        "patches": [
            {
                "patch_id": "patch-1",
                "graph_id": "workflow:legacy",
                "base_graph_hash": "abc123",
                "proposal_kind": "edit",
                "summary": "Insert approval gate",
                "proposal": {"op": "add_node"},
                "diff": {"added": ["Approval Gate"]},
                "contract_diff": {"flow": ["call -> approval"]},
                "staging_graph": {"nodes": []},
                "status": "draft",
            }
        ],
    }
    (legacy / "workflow.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = store.migrate_legacy()
    second_pass = store.migrate_legacy()

    assert summary == {
        "backups": summary["backups"],
        "graphs": 1,
        "nodes": 2,
        "links": 1,
        "runs": 1,
        "run_nodes": 1,
        "checkpoints": 1,
        "recipes": 1,
        "tests": 1,
        "patches": 1,
    }
    assert summary["backups"]
    assert second_pass["skipped"] is True
    assert store.list_graphs()[0]["graph_id"] == "workflow:legacy"
    assert store.list_runs()[0]["run_id"] == "run-legacy"
    assert store.list_recipe_versions()[0]["recipe_version_uid"] == "recipever:legacy-material@1.2.3"
    assert store.list_patch_proposals()[0]["patch_id"] == "patch-1"
    assert any(path.is_dir() for path in store.backup_dir.iterdir())


def test_workflow_runtime_persists_graph_nodes_runs_checkpoints_and_node_state(tmp_path):
    store = _make_store(tmp_path)
    store.initialize()
    manifest = {
        "graph_id": "workflow:main",
        "name": "Main Workflow",
        "kind": "workflow",
        "nodes": [
            {"node_id": "input", "node_name": "Workflow Input", "node_type": "workflow_input"},
            {"node_id": "call", "node_name": "Assistant Call", "node_type": "assistant_call"},
        ],
        "links": [
            {
                "link_id": "link-1",
                "from_node": "input",
                "from_socket": "Flow",
                "to_node": "call",
                "to_socket": "Flow",
            }
        ],
    }

    graph = store.upsert_graph("workflow:main", "Main Workflow", manifest, kind="workflow", status="ready")
    node = store.upsert_graph_node(
        "workflow:main",
        "node-call",
        node_name="Assistant Call",
        node_type="assistant_call",
        state="running",
        freshness="dirty",
        risk_level="write",
        warning_count=2,
        last_run_id="run-1",
        last_result_summary="Queued",
        last_error_summary="",
        action_card_ref="card-1",
        node_data={"phase": "preview"},
    )
    link = store.upsert_graph_link(
        "workflow:main",
        from_node="input",
        from_socket="Flow",
        to_node="call",
        to_socket="Flow",
        link_id="link-1",
        link_data={"kind": "flow"},
    )
    run = store.create_run(
        graph_id="workflow:main",
        graph_manifest=manifest,
        preview_only=False,
        snapshot_hash="snapshot-hash",
        input_hash="input-hash",
        run_label="Primary run",
        status="queued",
        action_card_ref="card-1",
        run_data={"kind": "full"},
        run_id="run-1",
    )
    run_node = store.record_run_node(
        "run-1",
        "node-call",
        node_name="Assistant Call",
        node_type="assistant_call",
        state="running",
        freshness="dirty",
        risk_level="write",
        warning_count=1,
        start_at="2026-04-21T00:00:00Z",
        end_at="2026-04-21T00:00:05Z",
        duration_ms=5000,
        result_summary="Done",
        error_summary="",
        action_card_ref="card-1",
        detail={"phase": "commit"},
    )
    checkpoint = store.create_checkpoint(
        "run-1",
        label="Before commit",
        state={"phase": "preview"},
        node_id="node-call",
        snapshot_hash="snapshot-hash",
        resume_token="resume-token",
        checkpoint_id="checkpoint-1",
    )
    updated_run = store.update_run_status("run-1", "completed", result_summary="Finished", completed=True)

    assert graph["graph_id"] == "workflow:main"
    assert node["node_data"] == {"phase": "preview"}
    assert link["link_data"] == {"kind": "flow"}
    assert run["status"] == "queued"
    assert run_node["detail"] == {"phase": "commit"}
    assert checkpoint["state"] == {"phase": "preview"}
    assert updated_run["status"] == "completed"
    assert updated_run["completed_at"]
    assert store.get_run("run-1")["nodes"][0]["node_id"] == "node-call"
    assert store.get_run("run-1")["checkpoints"][0]["checkpoint_id"] == "checkpoint-1"
    assert store.get_graph("workflow:main")["nodes"][0]["node_id"] == "node-call"
    assert store.get_graph("workflow:main")["links"][0]["link_id"] == "link-1"


def test_workflow_runtime_persists_recipe_versions_and_tests(tmp_path):
    store = _make_store(tmp_path)
    store.initialize()
    store.upsert_graph("workflow:recipes", "Recipes", {"graph_id": "workflow:recipes", "name": "Recipes", "kind": "workflow"}, kind="workflow", status="ready")

    recipe = store.publish_recipe(
        recipe_id="recipe:wet-clay",
        version="1.2.3",
        name="Wet Clay",
        graph_id="workflow:recipes",
        manifest={"recipe_id": "recipe:wet-clay", "name": "Wet Clay", "steps": ["prompt", "call"]},
        input_schema={"type": "object", "properties": {"selection": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        required_tools=["tool.call"],
        risk_profile="write",
        author="Example Author",
        changelog="Initial release",
        preview_path="previews/wet-clay.png",
        tests=[{"name": "smoke", "state": "passed"}],
        tags=["clay", "material"],
        catalog_path="recipes/materials",
        compatibility={"blender_min": "4.5.8"},
        status="approved",
        recipe_version_uid="recipever:wet-clay@1.2.3",
    )
    recipe_test = store.record_recipe_test(
        recipe["recipe_version_uid"],
        name="smoke",
        state="passed",
        input_data={"selection": ["Cube"]},
        output_data={"result": "ok"},
    )

    assert recipe["version"] == "1.2.3"
    assert recipe["major"] == 1
    assert recipe["graph_hash"] == store.hash_graph_manifest({"recipe_id": "recipe:wet-clay", "name": "Wet Clay", "steps": ["prompt", "call"]})
    assert store.get_recipe_version(recipe["recipe_version_uid"])["name"] == "Wet Clay"
    assert store.list_recipe_versions("recipe:wet-clay")[0]["recipe_version_uid"] == "recipever:wet-clay@1.2.3"
    assert recipe_test["input"] == {"selection": ["Cube"]}
    assert recipe_test["output"] == {"result": "ok"}
    assert store.get_recipe_test(recipe_test["test_id"])["state"] == "passed"
    assert store.list_recipe_tests(recipe["recipe_version_uid"])[0]["test_id"] == recipe_test["test_id"]


def test_workflow_runtime_persists_patch_proposals_and_events(tmp_path):
    store = _make_store(tmp_path)
    store.initialize()
    store.upsert_graph("workflow:patches", "Patches", {"graph_id": "workflow:patches", "name": "Patches", "kind": "workflow"}, kind="workflow", status="ready")

    patch = store.create_patch_proposal(
        graph_id="workflow:patches",
        base_graph_hash="abc123",
        proposal_kind="edit",
        summary="Add preview tap",
        proposal={"op": "add_node", "node_type": "preview_tap"},
        diff={"added": ["Preview Tap"]},
        contract_diff={"inputs": ["Context"]},
        staging_graph={"nodes": []},
        status="draft",
        patch_id="patch-1",
    )
    first_event = store.append_patch_event("patch-1", "preview", "Preview rendered", {"nodes": 1})
    updated = store.update_patch_proposal_status("patch-1", "approved", message="Looks good", detail={"reviewer": "Example Reviewer"})

    assert patch["summary"] == "Add preview tap"
    assert first_event["kind"] == "preview"
    assert updated["status"] == "approved"
    assert store.get_patch_proposal("patch-1")["events"][-1]["kind"] == "approved"
    assert store.list_patch_proposals("workflow:patches")[0]["patch_id"] == "patch-1"
    assert [event["kind"] for event in store.list_patch_events("patch-1")] == ["preview", "approved"]
