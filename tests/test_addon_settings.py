from __future__ import annotations

from codex_blender_agent.addon_settings import FallbackPreferences, addon_module_candidates


def test_addon_module_candidates_include_extension_module():
    candidates = addon_module_candidates()

    assert "codex_blender_agent" in candidates
    assert "bl_ext.user_default.codex_blender_agent" in candidates


def test_fallback_preferences_are_safe_defaults():
    preferences = FallbackPreferences()

    assert preferences.codex_command
    assert preferences.codex_home
    assert preferences.auto_setup_dashboard_workspace is False
    assert preferences.enable_operator_bridge is True
    assert preferences.enable_python_execution is False
