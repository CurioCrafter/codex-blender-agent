from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ChatHistoryStore:
    def __init__(self, root: Path, max_threads: int = 40, max_messages_per_thread: int = 500) -> None:
        self.root = Path(root)
        self.path = self.root / "chat_history.json"
        self.max_threads = max_threads
        self.max_messages_per_thread = max_messages_per_thread

    def load_latest(self, mode: str | None = None) -> dict[str, Any] | None:
        data = self._load()
        threads = data.get("threads", [])
        if mode:
            threads = [thread for thread in threads if thread.get("mode", "scene_agent") == mode]
        if not threads:
            return None
        return max(threads, key=lambda item: item.get("updated_at", ""))

    def save_thread(self, thread_id: str, cwd: str, model: str, messages: list[dict[str, Any]], mode: str = "scene_agent") -> None:
        if not thread_id:
            return

        data = self._load()
        threads = [
            thread
            for thread in data.get("threads", [])
            if not (thread.get("thread_id") == thread_id and thread.get("mode", "scene_agent") == mode)
        ]
        now = _now()
        previous = next(
            (
                thread
                for thread in data.get("threads", [])
                if thread.get("thread_id") == thread_id and thread.get("mode", "scene_agent") == mode
            ),
            {},
        )
        record = {
            "thread_id": thread_id,
            "mode": mode,
            "cwd": cwd,
            "model": model,
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
            "messages": messages[-self.max_messages_per_thread :],
        }
        threads.append(record)
        threads = sorted(threads, key=lambda item: item.get("updated_at", ""), reverse=True)[: self.max_threads]
        self._save({"threads": threads})

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"threads": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"threads": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
