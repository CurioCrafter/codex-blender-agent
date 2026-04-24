from __future__ import annotations

import time

from codex_blender_agent.observability import ObservabilityStore, sanitize_payload


def test_tool_event_lifecycle_tracks_active_and_recent_rows() -> None:
    store = ObservabilityStore(max_events=4)

    running = store.record_tool_event(
        tool_name="validate_gpt_asset",
        arguments={"selected_only": True, "api_token": "secret"},
        status="running",
        summary="selected_only=True",
        category="read_only",
        risk="low",
    )

    assert running["lifecycle_id"]
    assert store.active_tool_events()[0]["tool_name"] == "validate_gpt_asset"
    assert store.active_tool_events()[0]["arguments"]["api_token"] == "[redacted]"
    assert store.as_dict()["dirty"]["light"] is True

    completed = store.record_tool_event(
        tool_name="validate_gpt_asset",
        arguments={"selected_only": True},
        status="completed",
        result_summary="score 94",
        duration_seconds=1.2345,
        category="read_only",
        risk="low",
        lifecycle_id=running["lifecycle_id"],
    )

    assert completed["lifecycle_id"] == running["lifecycle_id"]
    assert completed["duration_seconds"] == 1.234
    assert store.active_tool_events() == []
    assert [row["status"] for row in store.recent_tool_events()] == ["running", "completed"]


def test_observability_caps_recent_events_and_records_sync_timing() -> None:
    store = ObservabilityStore(max_events=2)

    for index in range(3):
        store.record_tool_event(tool_name=f"tool_{index}", arguments={}, status="completed")

    assert [row["tool_name"] for row in store.recent_tool_events()] == ["tool_1", "tool_2"]
    store.record_sync("light", 0.001)
    time.sleep(0.001)
    store.record_sync("heavy", 0.002)
    payload = store.as_dict()

    assert payload["sync"]["light_count"] == 1
    assert payload["sync"]["heavy_count"] == 1
    assert payload["sync"]["last_light_duration_ms"] > 0
    assert payload["sync"]["last_heavy_duration_ms"] > 0
    assert payload["dirty"]["light"] is False
    assert payload["dirty"]["heavy"] is False


def test_sanitize_payload_redacts_secret_keys_and_compacts_values() -> None:
    payload = sanitize_payload(
        {
            "Authorization": "Bearer secret",
            "nested": {"password": "abc123", "text": "x" * 2000},
        },
        limit=64,
    )

    assert payload["Authorization"] == "[redacted]"
    assert payload["nested"]["password"] == "[redacted]"
    assert len(payload["nested"]["text"]) <= 64
