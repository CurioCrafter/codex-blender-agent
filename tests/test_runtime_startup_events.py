from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _method_source(source: str, name: str) -> str:
    start = source.index(f"    def {name}(")
    end = source.find("\n    def ", start + 1)
    return source[start:] if end == -1 else source[start:end]


def _function_source(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.find("\ndef ", start + 1)
    return source[start:] if end == -1 else source[start:end]


def test_send_prompt_records_visible_startup_events_before_routing() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    send_prompt = _method_source(runtime_source, "send_prompt")

    received = send_prompt.index("USER PROMPT RECEIVED")
    routing = send_prompt.index("ROUTING PROMPT")
    ensure_mode = send_prompt.index("self._ensure_chat_mode")
    auto_review = send_prompt.index("STARTING AUTO REVIEW")
    approval = send_prompt.index("WAITING FOR APPROVAL")
    chat = send_prompt.index("SENDING CHAT")

    assert received < routing < ensure_mode
    assert approval < send_prompt.index("return {\"routed\": \"card\"")
    assert auto_review < send_prompt.index("self.start_visual_review_loop")
    assert chat < send_prompt.index("self.service.send_prompt")

    thread_starting = send_prompt.index("THREAD STARTING")
    creator_submitting = send_prompt.index("CREATOR TURN SUBMITTING")
    service_send = send_prompt.index("self.service.send_prompt")
    assert chat < thread_starting < creator_submitting < service_send


def test_runtime_start_records_service_start_visibility_before_blocking_start() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    start_method = _method_source(runtime_source, "start")

    service_starting = start_method.index("SERVICE STARTING")
    online_access = start_method.index("_require_online_access")
    service_start = start_method.index("self.service.start")
    service_ready = start_method.index("SERVICE READY")

    assert service_starting < online_access < service_start < service_ready


def test_web_checks_uses_canonical_screenshot_list_instead_of_stale_helper_arity() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    web_checks = runtime_source[runtime_source.index("def _web_checks(") : runtime_source.index("\ndef _json_safe_web", runtime_source.index("def _web_checks("))]

    assert "_web_screenshots(latest_pass, capture)" not in web_checks
    assert "screenshots: list[dict[str, Any]] | None = None" in web_checks
    assert "screenshot_rows = list(screenshots or [])" in web_checks
    assert '"count": len(screenshot_rows)' in web_checks


def test_web_console_auto_start_is_registered_and_load_persistent() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    register_timer = _function_source(runtime_source, "register_timer")
    load_post = runtime_source[runtime_source.index("def _load_post_auto_setup") : runtime_source.index("\ndef _tool_success", runtime_source.index("def _load_post_auto_setup"))]

    assert "schedule_web_console_auto_start()" in register_timer
    assert "schedule_web_console_auto_start()" in load_post
    assert "WEB CONSOLE STARTED" in runtime_source
    assert "WEB CONSOLE START FAILED" in runtime_source


def test_dynamic_tool_dispatch_records_visible_tool_events() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    dispatch = _method_source(runtime_source, "_dispatch_tool_call")
    observed = _method_source(runtime_source, "_execute_observed_dynamic_tool")
    recorder = _method_source(runtime_source, "_record_ai_tool_event")

    assert "_execute_observed_dynamic_tool" in dispatch
    assert '_record_ai_tool_event(context, tool_name, args, "running")' in observed
    assert '"completed" if bool(result.get("success", False)) else "failed"' in observed
    assert "Tool {status}: {tool_name}" in recorder
    assert "add_job_event" in recorder
    assert "record_automation_event" in recorder
    assert "self._sync_window_manager(context.window_manager, force=True)" not in recorder
    assert "_request_live_sync(heavy=False)" in recorder
    assert "record_tool_event" in recorder


def test_model_refresh_is_independent_from_prompt_submission() -> None:
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    operators_source = (ROOT / "codex_blender_agent" / "operators.py").read_text(encoding="utf-8")
    refresh_model_state = _method_source(runtime_source, "refresh_model_state")
    operator = operators_source[
        operators_source.index("class CODEXBLENDERAGENT_OT_refresh_model_state") : operators_source.index(
            "\n\nclass CODEXBLENDERAGENT_OT_run_recommended_workflow"
        )
    ]

    assert "self.service.refresh_models()" in refresh_model_state
    assert "self.service.send_prompt" not in refresh_model_state
    assert "codex_blender_prompt" not in operator
    assert "get_runtime().refresh_model_state(context)" in operator
