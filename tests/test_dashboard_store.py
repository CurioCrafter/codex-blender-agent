from __future__ import annotations

from codex_blender_agent.dashboard_store import DashboardStore, make_project_id, make_thread_id


def test_dashboard_store_creates_project_and_persists_external_thread_messages(tmp_path):
    store = DashboardStore(tmp_path)
    project_id = make_project_id(r"C:\Projects\Blender\Character Rig")

    project = store.ensure_project(project_id=project_id, name="Character Rig", cwd=r"C:\Projects\Blender\Character Rig")
    assert store.active_project_id() == project_id
    thread_id = make_thread_id()
    messages = [
        {"role": "user", "text": "Create a reusable rig cleanup workflow for this character."},
        {
            "role": "assistant",
            "text": "I can do that by separating deform bones from control bones and saving the steps as a toolbox recipe.",
        },
    ]

    record = store.save_thread(
        thread_id=thread_id,
        project_id=project["project_id"],
        mode="scene_agent",
        model="gpt-5",
        cwd=project["cwd"],
        messages=messages,
    )

    assert store.path.exists()
    assert (store.messages_dir / f"{thread_id}.json").exists()
    assert record["thread_id"] == thread_id
    assert record["project_id"] == project_id
    assert record["message_count"] == 2
    assert record["preview"]
    assert len(record["preview"]) <= 240

    context = store.get_thread_context(thread_id, limit=1)
    assert context["thread"]["thread_id"] == thread_id
    assert context["messages"] == messages[-1:]


def test_dashboard_store_tracks_active_rows_and_compacts_long_threads(tmp_path):
    store = DashboardStore(tmp_path)
    project_a = store.ensure_project(project_id="project-a", name="Project A", cwd=r"C:\A")
    project_b = store.ensure_project(project_id="project-b", name="Project B", cwd=r"C:\B")

    thread_a = make_thread_id()
    thread_b = make_thread_id()

    store.save_thread(
        thread_id=thread_a,
        project_id=project_a["project_id"],
        mode="scene_agent",
        model="gpt-5",
        cwd=project_a["cwd"],
        messages=[{"role": "user", "text": "Thread A one."}, {"role": "assistant", "text": "Thread A two."}],
        title="Thread A",
    )
    store.save_thread(
        thread_id=thread_b,
        project_id=project_b["project_id"],
        mode="toolbox",
        model="gpt-5",
        cwd=project_b["cwd"],
        messages=[
            {"role": "user", "text": "Thread B one."},
            {"role": "assistant", "text": "Thread B two."},
            {"role": "user", "text": "Thread B three."},
        ],
        title="Thread B",
    )

    store.set_active_project(project_b["project_id"])
    store.set_active_thread(thread_b)

    assert store.active_project_id() == project_b["project_id"]
    assert store.active_thread_id() == thread_b
    assert [project["project_id"] for project in store.list_projects()][0] == project_b["project_id"]
    assert [thread["thread_id"] for thread in store.list_threads(project_id=project_b["project_id"])] == [thread_b]
    assert [thread["thread_id"] for thread in store.list_threads(mode="scene_agent")] == [thread_a]

    compacted = store.compact_thread(thread_b, keep_last=1)
    assert compacted["thread_id"] == thread_b
    assert compacted["message_count"] == 1
    assert compacted["preview"]
    assert store.load_thread_messages(thread_b) == [{"role": "user", "text": "Thread B three."}]

    updated_project = store.write_project_note(project_b["project_id"], "Use this project for reusable toolchains.")
    assert updated_project["notes"] == "Use this project for reusable toolchains."
    context = store.get_thread_context(thread_b)
    assert context["thread"]["thread_id"] == thread_b
    assert context["thread"]["project_id"] == project_b["project_id"]
    assert context["messages"] == [{"role": "user", "text": "Thread B three."}]


def test_dashboard_store_persists_action_cards_outputs_and_timeline(tmp_path):
    store = DashboardStore(tmp_path)
    project = store.ensure_project(project_id="project-actions", name="Project Actions", cwd=r"C:\Project")

    card = store.save_action_card(
        project_id=project["project_id"],
        title="Apply material",
        prompt="Create and apply a warm clay material to the selected object.",
        plan="Create material, set base color, assign to selected mesh.",
        affected_targets=["Cube"],
        required_context=["selection"],
    )

    assert card["action_id"]
    assert card["approval_required"] is True
    assert store.list_action_cards(project_id=project["project_id"])[0]["action_id"] == card["action_id"]
    assert store.get_action_card(card["action_id"])["detail"]["plan"].startswith("Create material")

    updated = store.update_action_status(card["action_id"], "completed", result_summary="Material assigned.")
    assert updated["status"] == "completed"
    assert store.get_action_card(card["action_id"])["result_summary"] == "Material assigned."

    output = store.pin_output(title="Clay Material", summary="Warm clay material recipe.", project_id=project["project_id"])
    event = store.add_job_event("Material completed", "completed", "Assigned to Cube", project_id=project["project_id"])

    assert store.list_pinned_outputs(project_id=project["project_id"])[0]["output_id"] == output["output_id"]
    assert store.list_job_timeline(project_id=project["project_id"])[0]["event_id"] == event["event_id"]
