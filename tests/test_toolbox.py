from __future__ import annotations

from codex_blender_agent.toolbox import ToolboxStore, parse_recipe_steps


def test_toolbox_store_saves_and_lists_entries(tmp_path):
    store = ToolboxStore(tmp_path)
    item = store.save_entry(
        name="Roblox deform-only export",
        category="workflow",
        description="Export only mesh and deform rig bones.",
        content={"steps": []},
        tags=["roblox", "fbx"],
    )
    entries = store.list_entries()
    assert entries[0]["id"] == item["id"]
    assert entries[0]["tags"] == ["fbx", "roblox"]


def test_parse_recipe_steps_accepts_json_recipe():
    steps = parse_recipe_steps('{"steps":[{"tool":"create_primitive","arguments":{"primitive":"cube"}}]}')
    assert steps[0]["tool"] == "create_primitive"
