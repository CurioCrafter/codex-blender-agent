from __future__ import annotations

import ast
import re
from typing import Any

from .service_errors import normalize_service_error

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - imported outside Blender for tests
    bpy = None


TRANSCRIPT_TEXT = "Codex Chat Transcript"
PROMPT_TEXT = "Codex Prompt Draft"
ACTIVITY_TEXT = "Codex Activity Log"
_PROMPT_DRAFT_OPEN = 'PROMPT = """\\\n'
_PROMPT_DRAFT_CLOSE = '\n"""\n'
_PROMPT_DRAFT_PATTERN = re.compile(r'PROMPT\s*=\s*"""\s*\\?\n(?P<body>.*?)\n"""', re.DOTALL)


def ensure_chat_text_blocks() -> dict[str, Any]:
    if bpy is None:
        return {}
    prompt = _ensure_text(PROMPT_TEXT)
    if not prompt.as_string().strip():
        prompt.clear()
        prompt.write(render_prompt_draft_template(""))
    return {
        "transcript": _ensure_text(TRANSCRIPT_TEXT),
        "prompt": prompt,
        "activity": _ensure_text(ACTIVITY_TEXT),
    }


def read_prompt_draft() -> str:
    if bpy is None:
        return ""
    text = _ensure_text(PROMPT_TEXT)
    return extract_prompt_draft_body(text.as_string())


def render_prompt_draft_template(prompt: str = "") -> str:
    body = _escape_prompt_draft_body(prompt)
    return (
        "import bpy\n\n"
        f"{_PROMPT_DRAFT_OPEN}"
        f"{body}"
        f"{_PROMPT_DRAFT_CLOSE}"
        "bpy.ops.codex_blender_agent.send_prompt_literal(prompt=PROMPT)\n"
    )


def extract_prompt_draft_body(text: str) -> str:
    value = text or ""
    match = _PROMPT_DRAFT_PATTERN.search(value)
    if match:
        body = match.group("body")
        try:
            return ast.literal_eval(f'"""\\\n{body}\n"""').rstrip("\n")
        except Exception:
            return _unescape_prompt_draft_body(body).rstrip("\n")
    return value.strip()


def write_prompt_draft_body(prompt: str) -> Any:
    if bpy is None:
        return None
    text = _ensure_text(PROMPT_TEXT)
    text.clear()
    text.write(render_prompt_draft_template(prompt))
    return text


def reset_prompt_draft_template(prompt: str = "") -> str:
    return render_prompt_draft_template(prompt)


def clear_prompt_draft() -> None:
    if bpy is None:
        return
    write_prompt_draft_body("")


def write_transcript(snapshot: Any, chat_mode: str) -> Any:
    if bpy is None:
        return None
    text = _ensure_text(TRANSCRIPT_TEXT)
    text.clear()
    text.write(render_transcript(snapshot, chat_mode))
    return text


def write_activity_log(snapshot: Any) -> Any:
    if bpy is None:
        return None
    text = _ensure_text(ACTIVITY_TEXT)
    text.clear()
    text.write(render_activity_log(snapshot))
    return text


def append_activity_event(title: str, payload: Any | None = None) -> Any:
    if bpy is None:
        return None
    text = _ensure_text(ACTIVITY_TEXT)
    existing = text.as_string()
    if existing and not existing.endswith("\n"):
        text.write("\n")
    text.write(f"\n{title}\n")
    text.write("-" * min(len(title), 100) + "\n")
    if payload is not None:
        text.write(_format_payload(payload) + "\n")
    return text


def render_activity_log(snapshot: Any) -> str:
    error = _friendly_error_payload(snapshot)
    lines = [
        "Codex Activity Log",
        f"Status: {_field(snapshot, 'status_text')}",
        f"Activity: {_field(snapshot, 'activity_text')}",
        f"Error: {error['summary']}",
        f"Pending: {_field(snapshot, 'turn_in_progress')}",
        f"Thread: {_field(snapshot, 'active_thread_id')}",
        f"Turn: {_field(snapshot, 'active_turn_id')}",
    ]
    server_logs = list(_field(snapshot, "server_logs", []) or [])
    if server_logs:
        lines.extend(["", "Recent app-server logs", "----------------------"])
        lines.extend(str(line) for line in server_logs[-12:])
    return "\n".join(lines).rstrip() + "\n"


def render_transcript(snapshot: Any, chat_mode: str) -> str:
    messages = list(_field(snapshot, "messages", []) or [])
    lines = [
        "Codex Blender Agent Transcript",
        f"Mode: {chat_mode or 'scene_agent'}",
        f"Thread: {_field(snapshot, 'active_thread_id')}",
        f"Turn: {_field(snapshot, 'active_turn_id')}",
        f"Status: {_field(snapshot, 'status_text')}",
        f"Activity: {_field(snapshot, 'activity_text')}",
        "",
    ]
    error = _friendly_error_payload(snapshot)
    if error["summary"]:
        section = error["title"] or "ERROR"
        lines.extend([section, "-" * min(len(section), 100), str(error["summary"])])
        if error["recovery"]:
            lines.extend(["", f"Next: {error['recovery']}"])
        lines.append("")
    if not messages:
        lines.extend(["No messages yet.", "Write a prompt in Codex Prompt Draft and use Send Draft."])
        return "\n".join(lines)
    for index, message in enumerate(messages, start=1):
        role = str(_field(message, "role", "message") or "message").upper()
        phase = _field(message, "phase") or _field(message, "status") or ""
        status = _field(message, "status") or ""
        title = f"{index}. {role}"
        if phase:
            title += f" [{phase}]"
        if status and status != phase:
            title += f" ({status})"
        lines.extend([title, "-" * min(len(title), 100)])
        lines.append(_friendly_message_text(str(_field(message, "text") or "")))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _ensure_text(name: str):
    text = bpy.data.texts.get(name)
    if text is None:
        text = bpy.data.texts.new(name)
    return text


def _field(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _friendly_error_payload(snapshot: Any) -> dict[str, str]:
    summary = str(_field(snapshot, "last_error", "") or "")
    if not summary:
        return {"title": "", "summary": "", "recovery": ""}
    title = str(_field(snapshot, "last_error_title", "") or "")
    recovery = str(_field(snapshot, "last_error_recovery", "") or "")
    if title or recovery:
        return {"title": title or "ERROR", "summary": summary, "recovery": recovery}
    friendly = normalize_service_error(summary)
    return {"title": friendly.title, "summary": friendly.summary, "recovery": friendly.recovery}


def _friendly_message_text(text: str) -> str:
    value = str(text or "")
    lower = value.lower()
    if not any(marker in lower for marker in ("responsestreamdisconnected", "reconnecting", "websocket closed", "stream disconnected")):
        return value
    friendly = normalize_service_error(value)
    if friendly.severity == "failed":
        return f"{friendly.title}: {friendly.summary}\nNext: {friendly.recovery}"
    return f"{friendly.title}: {friendly.summary}"


def _format_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _escape_prompt_draft_body(prompt: str) -> str:
    value = (prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _unescape_prompt_draft_body(prompt: str) -> str:
    value = prompt or ""
    value = value.replace('\\"', '"')
    value = value.replace('\\\\', '\\')
    return value
