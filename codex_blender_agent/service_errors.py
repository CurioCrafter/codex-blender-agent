from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any


_RETRY_RE = re.compile(r"reconnecting\D+(\d+)\s*/\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class FriendlyServiceError:
    title: str
    summary: str
    severity: str
    recovery: str
    raw_detail: str
    retry_attempt: int = 0
    retry_total: int = 0
    recoverable: bool = False

    @property
    def retry_label(self) -> str:
        if self.retry_attempt and self.retry_total:
            return f"{self.retry_attempt}/{self.retry_total}"
        return ""


def normalize_service_error(raw: Any) -> FriendlyServiceError:
    payload, raw_detail, raw_text = _coerce_payload(raw)
    message = str(payload.get("message") or payload.get("error") or raw_text or "Codex reported an error.").strip()
    nested = payload.get("codeErrorInfo") if isinstance(payload.get("codeErrorInfo"), dict) else {}
    if not nested and isinstance(payload.get("error"), dict):
        nested = payload["error"].get("codeErrorInfo") if isinstance(payload["error"].get("codeErrorInfo"), dict) else {}
    detail = str(
        nested.get("additionalDetails")
        or payload.get("additionalDetails")
        or payload.get("detail")
        or payload.get("details")
        or ""
    )
    combined = f"{message} {detail} {json.dumps(payload, ensure_ascii=True, sort_keys=True) if payload else raw_text}".lower()
    will_retry = _truthy(nested.get("willRetry")) or _truthy(payload.get("willRetry"))
    retry_attempt, retry_total = _retry_numbers(message)
    retry_exhausted = bool(retry_total and retry_attempt >= retry_total)
    is_reconnecting_message = "reconnecting" in message.lower()
    stream_disconnected = any(
        marker in combined
        for marker in (
            "responsestreamdisconnected",
            "stream disconnected",
            "websocket closed",
            "response.completed",
            "before completed response",
        )
    )

    if stream_disconnected and retry_exhausted:
        return FriendlyServiceError(
            title=f"RECONNECT FAILED {retry_attempt}/{retry_total}",
            summary="Codex stream disconnected before the response completed and all retry attempts were used.",
            severity="failed",
            recovery="Click Login / Re-login, then Refresh or Start Service. After the account is confirmed, retry the prompt.",
            raw_detail=raw_detail,
            retry_attempt=retry_attempt,
            retry_total=retry_total,
            recoverable=False,
        )

    if stream_disconnected and (will_retry or is_reconnecting_message):
        title = "RECONNECTING"
        if retry_attempt and retry_total:
            title = f"{title} {retry_attempt}/{retry_total}"
        return FriendlyServiceError(
            title=title,
            summary="Codex stream disconnected before the response completed. The app-server is retrying; waiting for the same turn to resume.",
            severity="reconnecting",
            recovery="No action needed yet. If retries fail, use Retry or Continue from the visual review run.",
            raw_detail=raw_detail,
            retry_attempt=retry_attempt,
            retry_total=retry_total,
            recoverable=True,
        )

    if is_reconnecting_message and retry_exhausted:
        return FriendlyServiceError(
            title=f"RECONNECT FAILED {retry_attempt}/{retry_total}",
            summary="Codex could not reconnect to the response stream before retry attempts were exhausted.",
            severity="failed",
            recovery="Click Login / Re-login, then Refresh or Start Service. After the account is confirmed, retry the prompt.",
            raw_detail=raw_detail,
            retry_attempt=retry_attempt,
            retry_total=retry_total,
            recoverable=False,
        )

    if is_reconnecting_message:
        title = "RECONNECTING"
        if retry_attempt and retry_total:
            title = f"{title} {retry_attempt}/{retry_total}"
        return FriendlyServiceError(
            title=title,
            summary="Codex is reconnecting to the response stream and will continue when the connection resumes.",
            severity="reconnecting",
            recovery="Wait for the retry to finish, or stop the turn if you want to cancel it.",
            raw_detail=raw_detail,
            retry_attempt=retry_attempt,
            retry_total=retry_total,
            recoverable=True,
        )

    if stream_disconnected:
        return FriendlyServiceError(
            title="STREAM INTERRUPTED",
            summary="The Codex stream stopped before the response completed.",
            severity="failed",
            recovery="Retry the last prompt, continue the visual review run if one exists, or stop the run and inspect the latest receipt.",
            raw_detail=raw_detail,
            recoverable=False,
        )

    compact = " ".join(message.split())
    if len(compact) > 220:
        compact = compact[:217] + "..."
    return FriendlyServiceError(
        title="CODEX ERROR",
        summary=compact or "Codex reported an error before the action could complete.",
        severity="failed",
        recovery="Review the message, then retry the prompt or continue from the latest receipt if the scene changed.",
        raw_detail=raw_detail,
        recoverable=False,
    )


def _coerce_payload(raw: Any) -> tuple[dict[str, Any], str, str]:
    if isinstance(raw, dict):
        return dict(raw), json.dumps(raw, ensure_ascii=True, sort_keys=True), ""
    raw_text = str(raw or "").strip()
    if not raw_text:
        return {}, "", ""
    raw_detail = raw_text
    text = raw_text
    if ":" in text and text.lower().startswith("codex turn failed"):
        text = text.split(":", 1)[1].strip()
    payload = _parse_mapping_text(text)
    if payload:
        return payload, raw_detail, raw_text
    return {"message": raw_text}, raw_detail, raw_text


def _parse_mapping_text(text: str) -> dict[str, Any]:
    candidates = [text]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.insert(0, text[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _retry_numbers(message: str) -> tuple[int, int]:
    match = _RETRY_RE.search(message or "")
    if not match:
        return 0, 0
    try:
        return int(match.group(1)), int(match.group(2))
    except ValueError:
        return 0, 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)
