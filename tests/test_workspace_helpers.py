from __future__ import annotations

from codex_blender_agent.workspace import (
    ASSETS_WORKSPACE_NAME,
    STUDIO_WORKSPACE_NAME,
    WORKFLOW_WORKSPACE_NAME,
    canonical_workspace_name,
    operator_finished,
    workspace_diagnostic_payload,
)


def test_operator_finished_handles_blender_status_sets():
    assert operator_finished({"FINISHED"}) is True
    assert operator_finished({"CANCELLED"}) is False
    assert operator_finished("FINISHED") is True


def test_workspace_diagnostic_payload_reports_order_and_tag():
    payload = workspace_diagnostic_payload(
        workspace_names=["Layout", "Scripting", "AI Studio", "Workflow", "Assets"],
        active_name="Layout",
        tagged=True,
        last_result={"operator": "append_activate", "finished": True},
    )

    assert payload["studio_exists"] is True
    assert payload["studio_index"] == 2
    assert payload["studio_tagged"] is True
    assert payload["dashboard_exists"] is True
    assert payload["last_operator_result"]["finished"] is True


def test_workspace_names_are_canonical_v09_names():
    assert STUDIO_WORKSPACE_NAME == "AI Studio"
    assert WORKFLOW_WORKSPACE_NAME == "Workflow"
    assert ASSETS_WORKSPACE_NAME == "Assets"
    assert canonical_workspace_name("AI Dashboard") == "AI Studio"
    assert canonical_workspace_name("AI Workflow") == "Workflow"
    assert canonical_workspace_name("AI Assets") == "Assets"
