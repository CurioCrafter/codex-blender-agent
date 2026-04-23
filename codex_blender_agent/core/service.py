from __future__ import annotations

import copy
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..constants import CLIENT_NAME, CLIENT_TITLE, CLIENT_VERSION, DEFAULT_THREAD_INSTRUCTIONS
from ..service_errors import normalize_service_error
from .app_server import AppServerClient
from .launch import build_codex_app_server_command
from .prompting import compose_turn_text


@dataclass
class AccountInfo:
    auth_type: str
    email: str
    plan_type: str


@dataclass
class ModelInfo:
    model_id: str
    label: str
    description: str
    default_effort: str
    supports_images: bool
    is_default: bool


@dataclass
class ChatMessage:
    role: str
    text: str
    phase: str
    item_id: str = ""
    turn_id: str = ""
    thread_id: str = ""
    status: str = "completed"


@dataclass
class ServiceState:
    version: int = 0
    connection_state: str = "stopped"
    status_text: str = "Service stopped."
    account: AccountInfo | None = None
    models: list[ModelInfo] = field(default_factory=list)
    active_thread_id: str = ""
    active_turn_id: str = ""
    turn_in_progress: bool = False
    activity_text: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    last_error: str = ""
    last_error_title: str = ""
    last_error_severity: str = ""
    last_error_recovery: str = ""
    last_error_raw: str = ""
    last_error_retry: str = ""
    stream_recovering: bool = False
    server_logs: list[str] = field(default_factory=list)


class CodexService:
    def __init__(self, dynamic_tools: list[dict[str, Any]], tool_handler: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self._lock = threading.RLock()
        self._client: AppServerClient | None = None
        self._state = ServiceState()
        self._message_index: dict[str, int] = {}
        self._dynamic_tools = copy.deepcopy(dynamic_tools)
        self._tool_handler = tool_handler
        self._active_thread_loaded = False

    def snapshot(self) -> ServiceState:
        with self._lock:
            return copy.deepcopy(self._state)

    def is_running(self) -> bool:
        with self._lock:
            return self._client is not None and self._client.is_running

    def start(self, codex_command: str, codex_home: str, workspace_cwd: str, *, refresh_state: bool = True) -> None:
        if self.is_running():
            if refresh_state:
                self.refresh_account()
                self.refresh_models()
            self._set_status("Connected to Codex.")
            return

        self._set_connection("starting", "Starting Codex app-server...")
        env = None
        if codex_home:
            env = dict(os.environ)
            env["CODEX_HOME"] = codex_home

        command = build_codex_app_server_command(codex_command)
        client = AppServerClient(
            command=command,
            env=env,
            notification_handler=self._handle_notification,
            request_handler=self._handle_request,
            stderr_handler=self._handle_stderr,
        )

        try:
            client.start()
            client.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": CLIENT_NAME,
                        "title": CLIENT_TITLE,
                        "version": CLIENT_VERSION,
                    },
                    "capabilities": {
                        "experimentalApi": True,
                    },
                },
                timeout=15.0,
            )
        except Exception as exc:
            client.stop()
            self._set_error(f"Failed to start Codex app-server: {exc}")
            raise

        with self._lock:
            self._client = client
            self._state.connection_state = "connected"
            self._state.status_text = "Connected to Codex."
            self._touch_state()

        if refresh_state:
            self.refresh_account()
            self.refresh_models()
        self._set_status(f"Connected. Workspace: {workspace_cwd}")

    def has_loaded_thread(self) -> bool:
        with self._lock:
            return bool(self._state.active_thread_id and self._active_thread_loaded)

    def stop(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._state.connection_state = "stopped"
            self._state.status_text = "Service stopped."
            self._state.turn_in_progress = False
            self._state.active_thread_id = ""
            self._state.active_turn_id = ""
            self._state.activity_text = ""
            self._clear_error_state_locked()
            self._active_thread_loaded = False
            self._touch_state()

        if client is not None:
            client.stop()

    def refresh_account(self) -> None:
        client = self._require_client()
        result = client.call("account/read", {}, timeout=15.0)
        account_data = result.get("account")

        if not account_data:
            with self._lock:
                self._state.account = None
                self._state.status_text = "Connected. Not logged in."
                self._touch_state()
            return

        account = AccountInfo(
            auth_type=account_data.get("type", ""),
            email=account_data.get("email", ""),
            plan_type=account_data.get("planType", ""),
        )
        with self._lock:
            self._state.account = account
            self._state.status_text = f"Connected as {account.email or account.auth_type}."
            self._touch_state()

    def refresh_models(self) -> None:
        client = self._require_client()
        cursor: str | None = None
        models: list[ModelInfo] = []

        while True:
            result = client.call("model/list", {"cursor": cursor, "limit": 50}, timeout=20.0)
            for item in result.get("data", []):
                models.append(
                    ModelInfo(
                        model_id=item.get("id", ""),
                        label=item.get("displayName") or item.get("model", ""),
                        description=item.get("description", ""),
                        default_effort=item.get("defaultReasoningEffort", "medium"),
                        supports_images="image" in item.get("inputModalities", []),
                        is_default=bool(item.get("isDefault", False)),
                    )
                )
            cursor = result.get("nextCursor")
            if not cursor:
                break

        with self._lock:
            self._state.models = models
            self._touch_state()

    def start_chatgpt_login(self) -> str:
        client = self._require_client()
        result = client.call("account/login/start", {"type": "chatgpt"}, timeout=20.0)
        if result.get("type") != "chatgpt" or not result.get("authUrl"):
            raise RuntimeError("Codex did not return a ChatGPT browser login URL.")
        self._set_status("Finish the ChatGPT login in your browser.")
        return result["authUrl"]

    def new_thread(self) -> None:
        with self._lock:
            self._state.active_thread_id = ""
            self._state.active_turn_id = ""
            self._state.turn_in_progress = False
            self._state.activity_text = ""
            self._state.messages.clear()
            self._clear_error_state_locked()
            self._message_index.clear()
            self._active_thread_loaded = False
            self._state.status_text = "Ready for a new thread."
            self._touch_state()

    def restore_local_thread(self, thread_id: str, messages: list[dict[str, Any]]) -> None:
        restored_messages = [
            ChatMessage(
                role=item.get("role", ""),
                text=item.get("text", ""),
                phase=item.get("phase", ""),
                item_id=item.get("item_id", ""),
                turn_id=item.get("turn_id", ""),
                thread_id=item.get("thread_id", thread_id),
                status=item.get("status", "completed"),
            )
            for item in messages
        ]
        with self._lock:
            self._state.active_thread_id = thread_id
            self._state.messages = restored_messages
            self._message_index = {
                message.item_id: index
                for index, message in enumerate(restored_messages)
                if message.item_id
            }
            self._active_thread_loaded = False
            self._state.status_text = "Restored previous local transcript."
            self._state.activity_text = "Restored previous local transcript."
            self._touch_state()

    def read_thread_history(self, thread_id: str, limit: int = 100) -> list[dict[str, Any]]:
        client = self._require_client()
        result = client.call("thread/read", {"threadId": thread_id, "limit": limit}, timeout=30.0)
        return result.get("items", []) or result.get("thread", {}).get("items", [])

    def clear_local_messages(self) -> None:
        with self._lock:
            self._state.messages.clear()
            self._message_index.clear()
            self._state.activity_text = "Local transcript hidden."
            self._touch_state()

    def interrupt_turn(self) -> None:
        client = self._require_client()
        with self._lock:
            thread_id = self._state.active_thread_id
            turn_id = self._state.active_turn_id
            if not turn_id:
                turn_id = next((message.turn_id for message in reversed(self._state.messages) if message.turn_id), "")
        if not thread_id or not turn_id:
            self._set_turn_state(False, "No active turn to stop.")
            return
        client.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=10.0)
        with self._lock:
            self._state.status_text = "Stop requested."
            self._state.activity_text = "Stop requested for current turn."
            self._touch_state()

    def steer_turn(self, user_prompt: str) -> None:
        prompt = (user_prompt or "").strip()
        if not prompt:
            raise ValueError("Steering prompt is empty.")
        client = self._require_client()
        with self._lock:
            thread_id = self._state.active_thread_id
            turn_id = self._state.active_turn_id
            if not turn_id:
                turn_id = next((message.turn_id for message in reversed(self._state.messages) if message.turn_id), "")
        if not thread_id or not turn_id:
            raise RuntimeError("No active turn is available to guide.")
        client.call(
            "turn/steer",
            {
                "threadId": thread_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": f"User steering update:\n{prompt}", "text_elements": []}],
            },
            timeout=15.0,
        )
        self._set_activity(f"Sent steering update: {prompt[:220]}")

    def send_prompt(
        self,
        user_prompt: str,
        scene_digest: str,
        cwd: str,
        model: str,
        effort: str,
        image_paths: list[str] | None = None,
        attachment_context: str = "",
        chat_mode: str = "scene_agent",
    ) -> None:
        client = self._require_client()
        thread_id = self._ensure_thread(cwd=cwd, model=model)
        turn_text = compose_turn_text(user_prompt, scene_digest, chat_mode)
        if attachment_context.strip():
            turn_text = f"{turn_text}\n\nAttachments:\n{attachment_context.strip()}"
        inputs: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": turn_text,
                "text_elements": [],
            }
        ]
        for image_path in image_paths or []:
            inputs.append({"type": "localImage", "path": image_path})

        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": inputs,
            "effort": effort or None,
        }
        if model:
            params["model"] = model

        result = client.call("turn/start", params, timeout=30.0)
        turn_id = result.get("turn", {}).get("id", "")
        self._set_turn_state(True, "Running Codex turn...", turn_id=turn_id)

    def _ensure_thread(self, cwd: str, model: str) -> str:
        with self._lock:
            active_thread_id = self._state.active_thread_id
            active_thread_loaded = self._active_thread_loaded
            if active_thread_id and active_thread_loaded:
                return active_thread_id

        client = self._require_client()
        if active_thread_id and not active_thread_loaded:
            self._resume_thread(client, active_thread_id, cwd, model)
            return active_thread_id

        params: dict[str, Any] = {
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "personality": "pragmatic",
            "developerInstructions": DEFAULT_THREAD_INSTRUCTIONS,
            "dynamicTools": copy.deepcopy(self._dynamic_tools),
            "experimentalRawEvents": False,
            "persistExtendedHistory": True,
        }
        if model:
            params["model"] = model

        result = client.call("thread/start", params, timeout=30.0)
        thread_id = result.get("thread", {}).get("id", "")
        if not thread_id:
            raise RuntimeError("Codex did not return a thread id.")

        with self._lock:
            self._state.active_thread_id = thread_id
            self._active_thread_loaded = True
            self._touch_state()
        return thread_id

    def _resume_thread(self, client: AppServerClient, thread_id: str, cwd: str, model: str) -> None:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "personality": "pragmatic",
            "developerInstructions": DEFAULT_THREAD_INSTRUCTIONS,
            "persistExtendedHistory": True,
        }
        if model:
            params["model"] = model

        client.call("thread/resume", params, timeout=30.0)
        with self._lock:
            self._active_thread_loaded = True
            self._state.status_text = "Resumed previous Codex thread."
            self._touch_state()

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "thread/started":
            thread_id = params.get("thread", {}).get("id", "")
            if thread_id:
                with self._lock:
                    self._state.active_thread_id = thread_id
                    self._active_thread_loaded = True
                    self._touch_state()
            return

        if method == "turn/started":
            turn = params.get("turn", {})
            with self._lock:
                self._state.active_turn_id = turn.get("id", "")
                self._state.turn_in_progress = True
                self._state.activity_text = f"Turn started: {self._state.active_turn_id or 'running'}"
                self._clear_error_state_locked()
                self._touch_state()
            return

        if method == "item/started":
            self._handle_item_started(params)
            return

        if method == "item/agentMessage/delta":
            self._append_message_delta(params.get("itemId", ""), params.get("delta", ""))
            if params.get("delta"):
                self._set_activity(f"Assistant streaming: {params.get('delta', '')[-180:]}")
            return

        if method == "turn/plan/updated":
            plan = params.get("plan", [])
            in_progress = next((item.get("step", "") for item in plan if item.get("status") == "inProgress"), "")
            if in_progress:
                self._set_activity(f"Plan: {in_progress}")
            elif plan:
                self._set_activity(f"Plan updated: {plan[-1].get('step', '')}")
            return

        if method == "item/plan/delta":
            delta = params.get("delta", "")
            if delta:
                self._set_activity(f"Planning: {delta[-220:]}")
            return

        if method in {"item/reasoning/summaryTextDelta", "item/reasoning/textDelta"}:
            delta = params.get("delta", "")
            if delta:
                self._set_activity(f"Reasoning: {delta[-220:]}")
            return

        if method == "item/completed":
            self._handle_item_completed(params)
            return

        if method == "turn/completed":
            turn = params.get("turn", {})
            if turn.get("status") == "failed":
                self._set_error(turn.get("error", {}) or turn)
            elif turn.get("status") == "interrupted":
                self._set_turn_state(False, "Stopped.", turn_id="")
            else:
                self._set_turn_state(False, "Idle.", turn_id="")
            return

        if method in {"account/login/completed", "account/updated"}:
            threading.Thread(target=self._safe_refresh_account, daemon=True).start()
            return

        if method == "error":
            self._set_error(params)

    def _handle_item_started(self, params: dict[str, Any]) -> None:
        item = params.get("item", {})
        item_type = item.get("type")
        thread_id = params.get("threadId", "")
        turn_id = params.get("turnId", "")
        item_id = item.get("id", "")

        if item_type == "userMessage":
            text = self._extract_user_text(item.get("content", []))
            self._set_activity("User message sent.")
            self._append_message(ChatMessage("user", text, "input", item_id=item_id, turn_id=turn_id, thread_id=thread_id))
            return

        if item_type == "agentMessage":
            phase = item.get("phase") or "assistant"
            self._set_activity(f"Assistant streaming ({phase}).")
            self._append_message(
                ChatMessage(
                    "assistant",
                    item.get("text", ""),
                    phase,
                    item_id=item_id,
                    turn_id=turn_id,
                    thread_id=thread_id,
                    status="streaming",
                )
            )
            return

        if item_type == "dynamicToolCall":
            tool_name = item.get("tool", "tool")
            arguments = item.get("arguments", {})
            preview = self._format_tool_preview(tool_name, arguments)
            self._set_activity(preview)
            self._append_message(
                ChatMessage(
                    "tool",
                    preview,
                    "tool",
                    item_id=item_id,
                    turn_id=turn_id,
                    thread_id=thread_id,
                    status="streaming",
                )
            )

    def _handle_item_completed(self, params: dict[str, Any]) -> None:
        item = params.get("item", {})
        item_type = item.get("type")
        item_id = item.get("id", "")

        if item_type == "agentMessage":
            self._update_message(item_id, text=item.get("text", ""), status="completed")
            self._set_activity("Assistant message completed.")
            return

        if item_type == "dynamicToolCall":
            tool_name = item.get("tool", "tool")
            summary = self._dynamic_tool_result_summary(tool_name, item)
            status = "completed" if item.get("success", False) else "failed"
            self._update_message(item_id, text=summary, status=status)
            self._set_activity(summary[:500])

    def _handle_request(self, method: str, request_id: int, params: dict[str, Any]) -> None:
        client = self._require_client()
        if method == "item/tool/call":
            tool_name = params.get("tool", "")
            arguments = params.get("arguments", {})
            try:
                result = self._tool_handler(tool_name, arguments)
            except Exception as exc:
                result = {
                    "success": False,
                    "contentItems": [{"type": "inputText", "text": f"Blender tool error: {exc}"}],
                }
            client.respond_result(request_id, result)
            return

        if method in {"item/commandExecution/requestApproval", "execCommandApproval", "applyPatchApproval"}:
            client.respond_result(request_id, {"decision": "decline"})
            return

        if method == "item/fileChange/requestApproval":
            client.respond_result(request_id, {"decision": "decline"})
            return

        if method == "item/permissions/requestApproval":
            client.respond_result(request_id, {"permissions": {}, "scope": "turn"})
            return

        if method == "item/tool/requestUserInput":
            client.respond_result(request_id, {"answers": {}})
            return

        if method == "mcpServer/elicitation/request":
            client.respond_result(request_id, {"action": "decline", "content": None, "_meta": None})
            return

        client.respond_error(request_id, -32601, f"Unsupported server request: {method}")

    def _handle_stderr(self, line: str) -> None:
        if not line:
            return
        with self._lock:
            self._state.server_logs.append(line)
            self._state.server_logs = self._state.server_logs[-20:]
            self._touch_state()

    def _append_message(self, message: ChatMessage) -> None:
        with self._lock:
            self._message_index[message.item_id] = len(self._state.messages)
            self._state.messages.append(message)
            self._touch_state()

    def _append_message_delta(self, item_id: str, delta: str) -> None:
        if not item_id:
            return
        with self._lock:
            index = self._message_index.get(item_id)
            if index is None:
                return
            self._state.messages[index].text += delta
            self._touch_state()

    def _update_message(self, item_id: str, *, text: str | None = None, status: str | None = None) -> None:
        if not item_id:
            return
        with self._lock:
            index = self._message_index.get(item_id)
            if index is None:
                return
            message = self._state.messages[index]
            if text is not None:
                message.text = text
            if status is not None:
                message.status = status
            self._touch_state()

    def _set_connection(self, state: str, status_text: str) -> None:
        with self._lock:
            self._state.connection_state = state
            self._state.status_text = status_text
            self._touch_state()

    def _set_status(self, status_text: str) -> None:
        with self._lock:
            self._state.status_text = status_text
            self._touch_state()

    def _set_turn_state(self, pending: bool, status_text: str, turn_id: str | None = None) -> None:
        with self._lock:
            self._state.turn_in_progress = pending
            self._state.status_text = status_text
            if turn_id is not None:
                self._state.active_turn_id = turn_id
            if status_text:
                self._state.activity_text = status_text
            self._clear_error_state_locked()
            self._touch_state()

    def _set_error(self, message: Any) -> None:
        friendly = normalize_service_error(message)
        self._print_error_banner(friendly.title, friendly.summary)
        with self._lock:
            self._state.last_error = friendly.summary
            self._state.last_error_title = friendly.title
            self._state.last_error_severity = friendly.severity
            self._state.last_error_recovery = friendly.recovery
            self._state.last_error_raw = friendly.raw_detail
            self._state.last_error_retry = friendly.retry_label
            self._state.stream_recovering = friendly.recoverable
            self._state.status_text = friendly.title
            if friendly.recoverable:
                self._state.turn_in_progress = True
                self._state.activity_text = friendly.summary
            else:
                self._state.turn_in_progress = False
                self._state.active_turn_id = ""
                self._state.activity_text = friendly.summary
            self._touch_state()

    @staticmethod
    def _print_error_banner(title: str, detail: str = "") -> None:
        line = "=" * 78
        message = " ".join(str(detail or "").split())
        if len(message) > 360:
            message = message[:357] + "..."
        print(f"\n{line}\nCODEX STREAM: {str(title or 'ERROR').upper()}\n{message}\n{line}\n")

    def _clear_error_state_locked(self) -> None:
        self._state.last_error = ""
        self._state.last_error_title = ""
        self._state.last_error_severity = ""
        self._state.last_error_recovery = ""
        self._state.last_error_raw = ""
        self._state.last_error_retry = ""
        self._state.stream_recovering = False

    def _set_activity(self, text: str) -> None:
        with self._lock:
            self._state.activity_text = text
            self._touch_state()

    def _safe_refresh_account(self) -> None:
        try:
            self.refresh_account()
        except Exception as exc:
            self._set_error(f"Failed to refresh account state: {exc}")

    def _touch_state(self) -> None:
        self._state.version += 1

    def _require_client(self) -> AppServerClient:
        with self._lock:
            if self._client is None or not self._client.is_running:
                raise RuntimeError("Codex app-server is not running.")
            return self._client

    @staticmethod
    def _extract_user_text(content: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for item in content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _format_tool_preview(tool_name: str, arguments: dict[str, Any]) -> str:
        if not arguments:
            return f"Running {tool_name}."
        preview = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return f"Running {tool_name} with {preview}."

    @staticmethod
    def _dynamic_tool_result_summary(tool_name: str, item: dict[str, Any]) -> str:
        content_items = item.get("contentItems") or []
        text_parts = [entry.get("text", "") for entry in content_items if entry.get("type") == "inputText"]
        summary = "\n".join(part for part in text_parts if part).strip()
        if summary:
            return f"{tool_name}: {summary}"
        if item.get("success", False):
            return f"{tool_name} completed."
        return f"{tool_name} failed."
