from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


TERMINAL_TOOL_STATUSES = {"completed", "failed", "cancelled"}
SECRET_KEY_PARTS = ("token", "secret", "password", "api_key", "apikey", "authorization")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compact_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def sanitize_payload(value: Any, *, limit: int = 1200, depth: int = 0) -> Any:
    if depth > 5:
        return compact_text(value, 160)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in SECRET_KEY_PARTS):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = sanitize_payload(item, limit=limit, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item, limit=limit, depth=depth + 1) for item in list(value)[:80]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return compact_text(value, limit)
        return value
    return compact_text(value, min(limit, 240))


@dataclass
class SyncTiming:
    light_count: int = 0
    heavy_count: int = 0
    last_light_duration_ms: float = 0.0
    last_heavy_duration_ms: float = 0.0
    last_light_at: str = ""
    last_heavy_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "light_count": self.light_count,
            "heavy_count": self.heavy_count,
            "last_light_duration_ms": round(self.last_light_duration_ms, 3),
            "last_heavy_duration_ms": round(self.last_heavy_duration_ms, 3),
            "last_light_at": self.last_light_at,
            "last_heavy_at": self.last_heavy_at,
        }


@dataclass
class ObservabilityStore:
    max_events: int = 160
    sequence: int = 0
    dirty_light: bool = True
    dirty_heavy: bool = True
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    active_tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    sync_timing: SyncTiming = field(default_factory=SyncTiming)
    last_event_at: str = ""

    def mark_dirty(self, *, light: bool = True, heavy: bool = False) -> None:
        if light:
            self.dirty_light = True
        if heavy:
            self.dirty_heavy = True
        self.sequence += 1

    def clear_light_dirty(self) -> None:
        self.dirty_light = False

    def clear_heavy_dirty(self) -> None:
        self.dirty_heavy = False

    def record_sync(self, kind: str, duration_seconds: float) -> None:
        timestamp = now_iso()
        if kind == "heavy":
            self.sync_timing.heavy_count += 1
            self.sync_timing.last_heavy_duration_ms = max(duration_seconds, 0.0) * 1000.0
            self.sync_timing.last_heavy_at = timestamp
            self.clear_heavy_dirty()
        else:
            self.sync_timing.light_count += 1
            self.sync_timing.last_light_duration_ms = max(duration_seconds, 0.0) * 1000.0
            self.sync_timing.last_light_at = timestamp
            self.clear_light_dirty()

    def record_tool_event(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None,
        status: str,
        summary: str = "",
        result_summary: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
        category: str = "",
        risk: str = "",
        action_id: str = "",
        lifecycle_id: str = "",
    ) -> dict[str, Any]:
        normalized_status = (status or "running").strip().lower()
        if not lifecycle_id:
            lifecycle_id = f"tool-{self.sequence + 1:06d}"
        timestamp = now_iso()
        event = {
            "event_id": f"{lifecycle_id}-{normalized_status}",
            "lifecycle_id": lifecycle_id,
            "actor": "tool",
            "tool_name": str(tool_name or ""),
            "label": f"Tool {normalized_status}: {tool_name}",
            "status": normalized_status,
            "category": str(category or ""),
            "risk": str(risk or ""),
            "summary": compact_text(summary or result_summary or error or tool_name, 500),
            "arguments": sanitize_payload(arguments or {}, limit=700),
            "result_summary": compact_text(result_summary, 360),
            "error": compact_text(error, 360),
            "duration_seconds": round(max(float(duration_seconds or 0.0), 0.0), 3),
            "action_id": str(action_id or ""),
            "created_at": timestamp,
        }
        self.recent_events.append(event)
        if len(self.recent_events) > self.max_events:
            self.recent_events = self.recent_events[-self.max_events :]
        if normalized_status in TERMINAL_TOOL_STATUSES:
            self.active_tools.pop(lifecycle_id, None)
        else:
            self.active_tools[lifecycle_id] = dict(event)
        self.last_event_at = timestamp
        self.mark_dirty(light=True, heavy=False)
        return dict(event)

    def active_tool_events(self) -> list[dict[str, Any]]:
        rows = list(self.active_tools.values())
        rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return [dict(item) for item in rows]

    def recent_tool_events(self, *, limit: int = 80) -> list[dict[str, Any]]:
        return [dict(item) for item in self.recent_events[-max(1, int(limit)) :]]

    def event_tail(self, *, limit: int = 40) -> list[dict[str, Any]]:
        return self.recent_tool_events(limit=limit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "dirty": {"light": self.dirty_light, "heavy": self.dirty_heavy},
            "active_tool_count": len(self.active_tools),
            "recent_tool_event_count": len(self.recent_events),
            "last_event_at": self.last_event_at,
            "sync": self.sync_timing.as_dict(),
        }


class TimingScope:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed(self) -> float:
        return max(time.perf_counter() - self.started, 0.0)
