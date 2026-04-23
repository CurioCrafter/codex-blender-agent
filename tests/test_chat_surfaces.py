from __future__ import annotations

from types import SimpleNamespace

from codex_blender_agent.chat_surfaces import render_activity_log, render_transcript
from codex_blender_agent import chat_surfaces


def test_render_transcript_has_stable_sections():
    snapshot = {
        "active_thread_id": "thread-123",
        "active_turn_id": "turn-456",
        "status_text": "Running",
        "activity_text": "Calling tool",
        "last_error": "",
        "messages": [
            {"role": "user", "phase": "input", "status": "completed", "text": "Make a cube."},
            {"role": "tool", "phase": "tool", "status": "completed", "text": "create_primitive completed."},
        ],
    }

    rendered = render_transcript(snapshot, "scene_agent")

    assert "Codex Blender Agent Transcript" in rendered
    assert "Mode: scene_agent" in rendered
    assert "Thread: thread-123" in rendered
    assert "1. USER [input]" in rendered
    assert "2. TOOL [tool] (completed)" in rendered


def test_render_activity_log_keeps_status_lightweight():
    snapshot = {
        "status_text": "Idle",
        "activity_text": "Ready",
        "last_error": "",
        "turn_in_progress": False,
        "active_thread_id": "thread-123",
        "active_turn_id": "",
        "server_logs": ["log a", "log b"],
    }

    rendered = render_activity_log(snapshot)

    assert "Codex Activity Log" in rendered
    assert "Pending: False" in rendered
    assert "thread-123" in rendered
    assert "log b" in rendered


def test_transcript_normalizes_reconnect_error_payload():
    raw = """{"message": "Reconnecting... 5/5", "codeErrorInfo": {"code": "responseStreamDisconnected", "additionalDetails": "stream disconnected before completed response: websocket closed by server before response.completed", "willRetry": true, "threadId": "thread-secret", "turnId": "turn-secret"}}"""
    snapshot = {
        "active_thread_id": "thread-123",
        "active_turn_id": "turn-456",
        "status_text": "RECONNECTING 5/5",
        "activity_text": "Trying to reconnect",
        "last_error": raw,
        "messages": [{"role": "tool", "phase": "tool", "status": "failed", "text": raw}],
    }

    rendered = render_transcript(snapshot, "scene_agent")

    assert "RECONNECTING 5/5" in rendered
    assert "all retry attempts were used" in rendered
    assert "Login / Re-login" in rendered
    assert "thread-secret" not in rendered
    assert "turn-secret" not in rendered
    assert "codeErrorInfo" not in rendered


def test_extract_prompt_draft_body_from_wrapper():
    wrapped = chat_surfaces.render_prompt_draft_template("create a castle\nwith a moat")

    assert "import bpy" in wrapped
    assert "send_prompt_literal" in wrapped
    assert chat_surfaces.extract_prompt_draft_body(wrapped) == "create a castle\nwith a moat"


def test_extract_prompt_draft_body_plain_text_fallback():
    assert chat_surfaces.extract_prompt_draft_body("create a castle") == "create a castle"


def test_prompt_draft_write_and_clear_preserve_wrapper(monkeypatch):
    class FakeText:
        def __init__(self):
            self.value = ""

        def as_string(self):
            return self.value

        def clear(self):
            self.value = ""

        def write(self, text):
            self.value += text

    class FakeTexts(dict):
        def new(self, name):
            text = FakeText()
            self[name] = text
            return text

    fake_bpy = SimpleNamespace(data=SimpleNamespace(texts=FakeTexts()))
    monkeypatch.setattr(chat_surfaces, "bpy", fake_bpy)

    prompt = fake_bpy.data.texts.new(chat_surfaces.PROMPT_TEXT)
    prompt.write("create a castle")
    assert chat_surfaces.read_prompt_draft() == "create a castle"

    chat_surfaces.write_prompt_draft_body("create a castle\nwith a moat")
    rendered = prompt.as_string()
    assert rendered.startswith("import bpy\n\nPROMPT = \"\"\"\\\n")
    assert "create a castle" in rendered
    assert "send_prompt_literal" in rendered
    assert chat_surfaces.read_prompt_draft() == "create a castle\nwith a moat"

    chat_surfaces.clear_prompt_draft()
    cleared = prompt.as_string()
    assert "send_prompt_literal" in cleared
    assert chat_surfaces.read_prompt_draft() == ""
