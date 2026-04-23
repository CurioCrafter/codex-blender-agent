from __future__ import annotations

from codex_blender_agent.tutorial import (
    all_steps,
    clamp_step_index,
    current_step,
    get_walkthrough,
    progress_label,
    step_count,
    walkthrough_ids,
    walkthrough_items,
)


def test_tutorial_exposes_required_walkthroughs():
    assert walkthrough_ids() == (
        "first_run",
        "build_castle_safely",
        "workflow_graph_basics",
        "save_reuse_asset",
        "stop_and_recover",
    )
    assert [item[0] for item in walkthrough_items()] == list(walkthrough_ids())


def test_legacy_walkthrough_ids_still_resolve():
    assert get_walkthrough("ask_scene").walkthrough_id == "first_run"
    assert get_walkthrough("safe_change").walkthrough_id == "build_castle_safely"


def test_tutorial_steps_are_practical_and_complete():
    steps = list(all_steps())

    assert len(steps) >= 20
    for step in steps:
        assert step.step_id
        assert step.title
        assert step.body
        assert step.workspace in {"AI Studio", "Workflow", "Assets"}
        assert step.action
        assert step.expected
        assert step.recovery
        assert step.cta_operator
        assert step.completion
        assert len(step.body) <= 280
    assert any(step.sample_prompt for step in steps)


def test_first_run_tutorial_is_executable():
    walkthrough = get_walkthrough("first_run")

    assert len(walkthrough.steps) >= 8
    assert walkthrough.steps[0].cta_operator == "codex_blender_agent.open_studio_workspace"
    assert walkthrough.steps[1].cta_operator == "codex_blender_agent.start_service"
    assert walkthrough.steps[2].cta_operator == "codex_blender_agent.set_ai_scope"
    assert walkthrough.steps[3].sample_prompt
    assert walkthrough.steps[-1].completion == "health_checked"


def test_workflow_and_asset_walkthroughs_have_useful_examples():
    workflow = get_walkthrough("workflow_graph_basics")
    assets = get_walkthrough("save_reuse_asset")
    recovery = get_walkthrough("stop_and_recover")

    assert len(workflow.steps) >= 4
    assert len(assets.steps) >= 5
    assert len(recovery.steps) >= 5
    assert workflow.steps[1].sample_prompt
    assert assets.steps[2].sample_prompt
    assert recovery.steps[1].sample_prompt


def test_tutorial_step_clamping_and_progress_labels():
    assert step_count("workflow_graph_basics") == 4
    assert clamp_step_index("workflow_graph_basics", -20) == 0
    assert clamp_step_index("workflow_graph_basics", 99) == 3
    assert progress_label("workflow_graph_basics", 1) == "Step 2 of 4"


def test_unknown_walkthrough_falls_back_to_first():
    fallback = get_walkthrough("does_not_exist")

    assert fallback.walkthrough_id == "first_run"
    assert current_step("does_not_exist", 99).title == fallback.steps[-1].title
