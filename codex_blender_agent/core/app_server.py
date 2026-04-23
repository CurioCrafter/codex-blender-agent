from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


class JSONRPCError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass
class _PendingRequest:
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    failure: BaseException | None = None


class AppServerClient:
    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        notification_handler: Callable[[str, dict[str, Any]], None] | None = None,
        request_handler: Callable[[str, int, dict[str, Any]], None] | None = None,
        stderr_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._command = list(command)
        self._env = env
        self._notification_handler = notification_handler
        self._request_handler = request_handler
        self._stderr_handler = stderr_handler
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _PendingRequest] = {}
        self._id_lock = threading.Lock()
        self._next_id = 1
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running:
            return

        self._stop_event.clear()
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=self._env,
        )

        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            raise RuntimeError("Failed to create app-server pipes.")

        self._stdout_thread = threading.Thread(target=self._read_stdout, name="codex-app-server-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="codex-app-server-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

        self._fail_pending(RuntimeError("Codex app-server stopped."))
        self._process = None

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        request_id = self._allocate_id()
        pending = _PendingRequest()
        with self._pending_lock:
            self._pending[request_id] = pending

        self._write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": {} if params is None else params,
            }
        )

        if not pending.event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"Timed out waiting for {method}.")

        if pending.failure is not None:
            raise pending.failure

        response = pending.response or {}
        if "error" in response:
            error = response["error"]
            raise JSONRPCError(error.get("code", -32000), error.get("message", "Unknown JSON-RPC error"), error.get("data"))

        return response.get("result", {})

    def respond_result(self, request_id: int, result: dict[str, Any]) -> None:
        self._write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_error(self, request_id: int, code: int, message: str, data: Any | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            payload["error"]["data"] = data
        self._write_message(payload)

    def _allocate_id(self) -> int:
        with self._id_lock:
            request_id = self._next_id
            self._next_id += 1
            return request_id

    def _write_message(self, payload: dict[str, Any]) -> None:
        if not self.is_running or self._process is None or self._process.stdin is None:
            raise RuntimeError("Codex app-server is not running.")

        encoded = json.dumps(payload, ensure_ascii=True)
        with self._write_lock:
            self._process.stdin.write(encoded + "\n")
            self._process.stdin.flush()

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    if self._stderr_handler is not None:
                        self._stderr_handler(f"Failed to decode app-server JSON: {exc}: {line}")
                    continue
                self._handle_message(message)
        finally:
            if not self._stop_event.is_set():
                self._fail_pending(RuntimeError("Codex app-server connection closed."))

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return

        for line in process.stderr:
            if self._stderr_handler is not None:
                self._stderr_handler(line.rstrip())

    def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            request_id = message.get("id")
            if isinstance(request_id, int):
                with self._pending_lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None:
                    pending.response = message
                    pending.event.set()
            return

        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return

        if "id" in message:
            request_id = message.get("id")
            if isinstance(request_id, int) and self._request_handler is not None:
                self._request_handler(method, request_id, params)
            return

        if self._notification_handler is not None:
            self._notification_handler(method, params)

    def _fail_pending(self, failure: BaseException) -> None:
        with self._pending_lock:
            pending_items = list(self._pending.values())
            self._pending.clear()

        for pending in pending_items:
            pending.failure = failure
            pending.event.set()
