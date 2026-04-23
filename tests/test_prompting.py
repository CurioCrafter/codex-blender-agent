from __future__ import annotations

import pytest

from codex_blender_agent.core.prompting import compose_turn_text


def test_compose_turn_text_includes_prompt_and_scene_digest():
    text = compose_turn_text("Move the cube.", "Scene: Cube selected")
    assert "User request:\nMove the cube." in text
    assert "Blender scene summary at request time:\nScene: Cube selected" in text
    assert "Use the fewest targeted Blender tools needed." in text


def test_compose_turn_text_rejects_empty_prompt():
    with pytest.raises(ValueError):
        compose_turn_text("   ", "Scene: anything")
