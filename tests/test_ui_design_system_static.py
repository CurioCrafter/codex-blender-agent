from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_source(text: str, name: str) -> str:
    start = text.index(f"def {name}")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    stops = [value for value in (next_def, next_class) if value != -1]
    end = min(stops) if stops else len(text)
    return text[start:end]


def test_view3d_launcher_is_chat_first_static_contract():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    launcher = _function_source(ui_source, "_draw_launcher_ui")

    assert "template_list" not in launcher
    assert "_draw_tutorial_card" not in launcher
    assert "_draw_memory_assets" not in launcher
    assert "_draw_transcript" not in launcher
    assert "codex_blender_asset_items" not in launcher
    assert "_draw_game_creator_composer" in launcher
    assert "_draw_live_ai_feed" in launcher
    assert "_draw_codex_capability_panel" in launcher
    assert "_draw_quick_prompts" in launcher
    assert "_draw_current_task_summary" in launcher
    default_launcher = launcher.split("codex_blender_show_advanced_governance", 1)[0]
    assert "create_action_from_prompt" not in launcher.split("show_advanced_governance", 1)[0]
    assert "ai_setup_workflow" not in default_launcher
    assert "use_selection_in_workflow" not in default_launcher
    assert "open_workflow_workspace" not in default_launcher


def test_automation_status_panel_is_prominent_static_contract():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    current_task = _function_source(ui_source, "_draw_current_task_summary")
    automation_panel = _function_source(ui_source, "_draw_automation_status_panel")
    login_card = _function_source(ui_source, "_draw_login_status_card")
    launcher = _function_source(ui_source, "_draw_launcher_ui")

    assert "_draw_automation_status_panel" in current_task
    assert "ACTIVE:" in automation_panel
    assert "VERIFYING" in automation_panel
    assert "Open run details" in automation_panel
    assert "codex_blender_asset_validation_latest_issue_count" in automation_panel
    assert "Login / Re-login" in login_card
    assert "codex_blender_agent.login" in login_card
    assert "_draw_login_status_card" in launcher


def test_game_creator_composer_exposes_model_choice_static_contract():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    composer = _function_source(ui_source, "_draw_game_creator_composer")

    assert "codex_blender_prompt" in composer
    assert "codex_blender_model" in composer
    assert "codex_blender_effort" in composer
    assert "expand_prompt" in composer


def test_launcher_and_composer_expose_web_console_controls_and_version_status_static_contract():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    launcher = _function_source(ui_source, "_draw_launcher_ui")
    composer = _function_source(ui_source, "_draw_game_creator_composer")
    install_status = _function_source(ui_source, "_draw_install_and_web_console_status")

    assert "_draw_install_and_web_console_status" in launcher
    assert "Start Web Console" in install_status
    assert "Open Web Console" in install_status
    assert "Stop Web Console" in install_status
    assert "Installed add-on: v{ADDON_VERSION}" in install_status
    assert "Web Console" in composer
    assert "open_web_console" in composer


def test_v11_ui_operator_ids_are_registered_static_contract():
    operators = (ROOT / "codex_blender_agent" / "operators.py").read_text(encoding="utf-8")

    for idname in (
        "codex_blender_agent.inspect_ai_context",
        "codex_blender_agent.view_action_changes",
        "codex_blender_agent.undo_last_ai_change",
        "codex_blender_agent.reset_ai_context",
        "codex_blender_agent.open_action_details",
        "codex_blender_agent.send_npanel_chat",
        "codex_blender_agent.expand_prompt",
        "codex_blender_agent.run_quick_prompt",
        "codex_blender_agent.ai_setup_workflow",
        "codex_blender_agent.create_game_asset_from_prompt",
        "codex_blender_agent.create_image_generation_brief",
    ):
        assert idname in operators


def test_dashboard_exposes_live_ai_feed_and_codex_capabilities_static_contract():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    live_feed = _function_source(ui_source, "_draw_live_ai_feed")
    capabilities = _function_source(ui_source, "_draw_codex_capability_panel")
    dashboard_home = _function_source(ui_source, "_draw_dashboard_home")

    assert "What AI Is Doing" in live_feed
    assert "codex_blender_job_timeline" in live_feed
    assert "codex_blender_active_tool_events" in live_feed
    assert "Currently Running Tool" in live_feed
    assert "create_image_generation_brief" in live_feed
    assert "Codex Tool Upgrades" in capabilities
    assert "Generate Image Brief" in capabilities
    assert "_draw_live_ai_feed" in dashboard_home
    assert "_draw_codex_capability_panel" in dashboard_home
    assert "Live health" in ui_source


def test_action_card_draw_uses_design_system_actions():
    ui_source = (ROOT / "codex_blender_agent" / "ui.py").read_text(encoding="utf-8")
    draw_cards = _function_source(ui_source, "_draw_action_cards")

    assert "primary_action_for_card(card)" in draw_cards
    assert "secondary_actions_for_card(card)" in draw_cards
    assert "preview_action" not in draw_cards
    assert "approve_action" not in draw_cards
    assert "archive_action" not in draw_cards
