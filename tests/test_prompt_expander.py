from __future__ import annotations

from codex_blender_agent.prompt_expander import expand_prompt


def test_expand_prompt_turns_short_castle_prompt_into_full_brief():
    expanded = expand_prompt("make castle")

    assert expanded.startswith("User request: make castle")
    assert "Create or refine a game-ready castle asset" in expanded
    assert "Castle-specific checks" in expanded
    assert "automatic validation and screenshot review" in expanded
    assert "non-destructive" in expanded


def test_expand_prompt_handles_fix_prompt_with_preservation_rules():
    expanded = expand_prompt("fix the castle crown intersection")

    assert "Diagnose the evaluated scene first" in expanded
    assert "repair the smallest safe set of changes" in expanded
    assert "Preserve the main silhouette" in expanded
    assert "Castle-specific checks" in expanded
    assert "battlements should not interpenetrate support walls" in expanded


def test_expand_prompt_uses_scene_context_hints():
    expanded = expand_prompt(
        "build a tower",
        scene_context={
            "scene_name": "Castle_Blockout",
            "active_object": "Keep",
            "selected_objects": ["Keep", "Tower_A"],
            "visible_object_count": 12,
            "materials": ["Stone", "Wood"],
        },
    )

    assert "Scene: Castle_Blockout" in expanded
    assert "Active object: Keep" in expanded
    assert "Selected objects: Keep, Tower_A" in expanded
    assert "Materials: Stone, Wood" in expanded


def test_expand_prompt_is_deterministic_and_handles_empty_prompt():
    first = expand_prompt("   ", scene_context="Stone keep in a moat")
    second = expand_prompt("   ", scene_context="Stone keep in a moat")

    assert first == second
    assert "Create a game-ready Blender asset." in first
    assert "Scene context hints" in first
    assert "moat" in first.lower()
