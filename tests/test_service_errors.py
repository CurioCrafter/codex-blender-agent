from __future__ import annotations

from codex_blender_agent.core.service import CodexService
from codex_blender_agent.service_errors import normalize_service_error


RECONNECT_PAYLOAD = {
    "message": "Reconnecting... 2/5",
    "codeErrorInfo": {
        "additionalDetails": "stream disconnected before completed response: websocket closed by server before response.completed",
        "code": "responseStreamDisconnected",
        "willRetry": True,
        "threadId": "019dac2-7fca-77c1-9f9d-34aa84f6552",
        "turnId": "019bd631-920c-7da2-a084-291efe51167",
    },
}


def test_reconnect_error_is_recoverable_and_hides_ids() -> None:
    friendly = normalize_service_error(RECONNECT_PAYLOAD)

    assert friendly.title == "RECONNECTING 2/5"
    assert friendly.severity == "reconnecting"
    assert friendly.recoverable is True
    assert friendly.retry_label == "2/5"
    assert "019dac2" not in friendly.summary
    assert "019bd631" not in friendly.summary
    assert "retrying" in friendly.summary.lower()


def test_hard_stream_disconnect_gets_recovery_language() -> None:
    payload = {
        "message": "Response stream disconnected.",
        "codeErrorInfo": {
            "additionalDetails": "websocket closed by server before response.completed",
            "code": "responseStreamDisconnected",
            "willRetry": False,
        },
    }

    friendly = normalize_service_error(payload)

    assert friendly.title == "STREAM INTERRUPTED"
    assert friendly.severity == "failed"
    assert friendly.recoverable is False
    assert "Retry the last prompt" in friendly.recovery


def test_exhausted_reconnect_is_not_recoverable_even_if_payload_says_retry() -> None:
    payload = {
        "message": "Reconnecting... 5/5",
        "codeErrorInfo": {
            "additionalDetails": "stream disconnected before completed response: websocket closed by server before response.completed",
            "code": "responseStreamDisconnected",
            "willRetry": True,
        },
    }

    friendly = normalize_service_error(payload)

    assert friendly.title == "RECONNECT FAILED 5/5"
    assert friendly.severity == "failed"
    assert friendly.recoverable is False
    assert "Login / Re-login" in friendly.recovery


def test_malformed_error_has_friendly_fallback_and_raw_detail() -> None:
    friendly = normalize_service_error("not json but still an error")

    assert friendly.title == "CODEX ERROR"
    assert friendly.summary == "not json but still an error"
    assert friendly.raw_detail == "not json but still an error"


def test_recoverable_service_error_keeps_turn_pending() -> None:
    service = CodexService([], lambda _tool, _arguments: {})
    service._set_turn_state(True, "Turn started.", turn_id="turn-1")

    service._set_error(RECONNECT_PAYLOAD)
    snapshot = service.snapshot()

    assert snapshot.turn_in_progress is True
    assert snapshot.active_turn_id == "turn-1"
    assert snapshot.stream_recovering is True
    assert snapshot.last_error_title == "RECONNECTING 2/5"
    assert snapshot.last_error_severity == "reconnecting"


def test_hard_service_error_clears_pending_turn() -> None:
    service = CodexService([], lambda _tool, _arguments: {})
    service._set_turn_state(True, "Turn started.", turn_id="turn-1")

    service._set_error({"message": "Hard failure"})
    snapshot = service.snapshot()

    assert snapshot.turn_in_progress is False
    assert snapshot.active_turn_id == ""
    assert snapshot.stream_recovering is False
    assert snapshot.last_error_title == "CODEX ERROR"
