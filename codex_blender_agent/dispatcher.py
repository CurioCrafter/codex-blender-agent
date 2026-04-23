from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DispatchResult:
    result_queue: "queue.Queue[Any]" = field(default_factory=queue.Queue)

    def set_result(self, value: Any) -> None:
        self.result_queue.put((True, value))

    def set_error(self, exc: Exception) -> None:
        self.result_queue.put((False, exc))

    def wait(self, timeout: float = 60.0) -> Any:
        ok, value = self.result_queue.get(timeout=timeout)
        if ok:
            return value
        raise value


class MainThreadDispatcher:
    def __init__(self, max_seconds_per_tick: float = 0.025, max_tasks_per_tick: int = 16) -> None:
        self.max_seconds_per_tick = max_seconds_per_tick
        self.max_tasks_per_tick = max_tasks_per_tick
        self._queue: "queue.Queue[tuple[Callable[[], Any], DispatchResult | None]]" = queue.Queue()

    def submit(self, fn: Callable[[], Any]) -> DispatchResult:
        result = DispatchResult()
        self._queue.put((fn, result))
        return result

    def submit_fire_and_forget(self, fn: Callable[[], Any]) -> None:
        self._queue.put((fn, None))

    def drain(self) -> int:
        deadline = time.monotonic() + self.max_seconds_per_tick
        processed = 0
        while processed < self.max_tasks_per_tick and time.monotonic() < deadline:
            try:
                fn, result = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                value = fn()
            except Exception as exc:
                if result is not None:
                    result.set_error(exc)
            else:
                if result is not None:
                    result.set_result(value)
            processed += 1
        return processed

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
