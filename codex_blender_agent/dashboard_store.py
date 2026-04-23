from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .studio_state import action_row, make_action_card, make_event_id, make_output_id, normalize_action_status, now_iso


DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Current Blender Project"


class DashboardStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "dashboard.json"
        self.messages_dir = self.root / "dashboard_messages"
        self.action_details_dir = self.root / "dashboard_actions"

    def ensure_project(self, project_id: str = DEFAULT_PROJECT_ID, name: str = DEFAULT_PROJECT_NAME, cwd: str = "") -> dict[str, Any]:
        data = self._load()
        projects = data.get("projects", [])
        had_projects = bool(projects)
        existing = next((project for project in projects if project.get("project_id") == project_id), None)
        now = _now()
        if existing is None:
            existing = {
                "project_id": project_id,
                "name": name,
                "cwd": cwd,
                "asset_library_name": "Codex Blender Agent",
                "notes": "",
                "created_at": now,
                "updated_at": now,
            }
            projects.append(existing)
        else:
            existing["name"] = existing.get("name") or name
            existing["cwd"] = cwd or existing.get("cwd", "")
            existing["updated_at"] = now
        data["projects"] = projects
        if not had_projects or not data.get("active_project_id"):
            data["active_project_id"] = project_id
        self._save(data)
        return existing

    def list_projects(self) -> list[dict[str, Any]]:
        data = self._load()
        projects = data.get("projects", [])
        if not projects:
            projects = [self.ensure_project()]
        return sorted(projects, key=lambda project: project.get("updated_at", ""), reverse=True)

    def set_active_project(self, project_id: str) -> None:
        data = self._load()
        if not any(project.get("project_id") == project_id for project in data.get("projects", [])):
            raise KeyError(f"Project not found: {project_id}")
        data["active_project_id"] = project_id
        self._save(data)

    def active_project_id(self) -> str:
        data = self._load()
        return data.get("active_project_id") or DEFAULT_PROJECT_ID

    def save_thread(
        self,
        *,
        thread_id: str,
        project_id: str,
        mode: str,
        model: str,
        cwd: str,
        messages: list[dict[str, Any]],
        title: str | None = None,
    ) -> dict[str, Any]:
        if not thread_id:
            raise ValueError("thread_id is required.")
        data = self._load()
        self._ensure_project_in_data(data, project_id, cwd)
        threads = [thread for thread in data.get("threads", []) if thread.get("thread_id") != thread_id]
        previous = next((thread for thread in data.get("threads", []) if thread.get("thread_id") == thread_id), {})
        now = _now()
        summary = _summarize_messages(messages)
        record = {
            "thread_id": thread_id,
            "project_id": project_id,
            "mode": mode or "scene_agent",
            "model": model,
            "cwd": cwd,
            "title": title or previous.get("title") or _title_from_messages(messages),
            "summary": summary,
            "preview": _preview(summary),
            "message_count": len(messages),
            "unread": previous.get("unread", False),
            "status": "idle",
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
        }
        threads.append(record)
        data["threads"] = sorted(threads, key=lambda thread: thread.get("updated_at", ""), reverse=True)
        data["active_thread_id"] = thread_id
        self._save(data)
        self.save_thread_messages(thread_id, messages)
        return record

    def list_threads(self, project_id: str | None = None, mode: str | None = None) -> list[dict[str, Any]]:
        data = self._load()
        threads = data.get("threads", [])
        if project_id:
            threads = [thread for thread in threads if thread.get("project_id", DEFAULT_PROJECT_ID) == project_id]
        if mode:
            threads = [thread for thread in threads if thread.get("mode", "scene_agent") == mode]
        return sorted(threads, key=lambda thread: thread.get("updated_at", ""), reverse=True)

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        return next((thread for thread in self._load().get("threads", []) if thread.get("thread_id") == thread_id), None)

    def set_active_thread(self, thread_id: str) -> None:
        data = self._load()
        if not any(thread.get("thread_id") == thread_id for thread in data.get("threads", [])):
            raise KeyError(f"Thread not found: {thread_id}")
        data["active_thread_id"] = thread_id
        self._save(data)

    def active_thread_id(self) -> str:
        return self._load().get("active_thread_id", "")

    def save_thread_messages(self, thread_id: str, messages: list[dict[str, Any]]) -> None:
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        path = self.messages_dir / f"{_safe_id(thread_id)}.json"
        path.write_text(json.dumps({"thread_id": thread_id, "messages": messages}, ensure_ascii=True, indent=2), encoding="utf-8")

    def load_thread_messages(self, thread_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.messages_dir / f"{_safe_id(thread_id)}.json"
        if not path.exists():
            return []
        try:
            messages = json.loads(path.read_text(encoding="utf-8")).get("messages", [])
        except (OSError, json.JSONDecodeError):
            return []
        if limit is not None:
            return messages[-limit:]
        return messages

    def get_thread_context(self, thread_id: str, limit: int = 20) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread not found: {thread_id}")
        return {"thread": thread, "messages": self.load_thread_messages(thread_id, limit=limit)}

    def write_project_note(self, project_id: str, note: str) -> dict[str, Any]:
        data = self._load()
        self._ensure_project_in_data(data, project_id, "")
        now = _now()
        for project in data.get("projects", []):
            if project.get("project_id") == project_id:
                project["notes"] = note
                project["updated_at"] = now
                self._save(data)
                return project
        raise KeyError(f"Project not found: {project_id}")

    def compact_thread(self, thread_id: str, keep_last: int = 20) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread not found: {thread_id}")
        messages = self.load_thread_messages(thread_id)
        summary = _summarize_messages(messages)
        compacted = messages[-max(keep_last, 0) :]
        self.save_thread_messages(thread_id, compacted)
        data = self._load()
        for row in data.get("threads", []):
            if row.get("thread_id") == thread_id:
                row["summary"] = summary
                row["preview"] = _preview(summary)
                row["message_count"] = len(compacted)
                row["compacted_at"] = _now()
                row["updated_at"] = _now()
                self._save(data)
                return row
        return thread

    def save_action_card(self, **kwargs: Any) -> dict[str, Any]:
        data = self._load()
        existing = self.get_action_card(str(kwargs.get("action_id", ""))) if kwargs.get("action_id") else None
        if existing:
            detail = dict(existing.get("detail", {}))
            detail.update(kwargs.pop("detail", {}) or {})
            existing_detail = existing.get("detail", {})
            merged = {
                "action_id": existing.get("action_id", ""),
                "project_id": existing.get("project_id", ""),
                "thread_id": existing.get("thread_id", ""),
                "title": existing.get("title", ""),
                "kind": existing.get("kind", existing_detail.get("kind", "")),
                "prompt": detail.get("prompt", existing.get("prompt_preview", "")),
                "plan": detail.get("plan", existing.get("plan_preview", "")),
                "tool_name": existing.get("tool_name", ""),
                "arguments": detail.get("arguments", {}),
                "affected_targets": existing.get("affected_targets", []),
                "required_context": existing.get("required_context", []),
                "risk": existing.get("risk", ""),
                "risk_rationale": existing.get("risk_rationale", existing_detail.get("risk_rationale", "")),
                "risk_axes": existing_detail.get("risk_axes", {}),
                "status": existing.get("status", ""),
                "scope_summary": existing.get("scope_summary", existing_detail.get("scope_summary", "")),
                "outcome_summary": existing.get("outcome_summary", existing_detail.get("outcome_summary", "")),
                "assumptions": existing_detail.get("assumptions", []),
                "dependencies": existing_detail.get("dependencies", []),
                "preview_summary": existing.get("preview_summary", existing_detail.get("preview_summary", "")),
                "short_plan": existing_detail.get("short_plan", []),
                "full_plan": existing_detail.get("full_plan", detail.get("plan", "")),
                "approval_policy": existing.get("approval_policy", existing_detail.get("approval_policy", "")),
                "tool_activity": existing_detail.get("tool_activity", []),
                "warnings": existing.get("warnings", existing_detail.get("warnings", [])),
                "timestamps": existing_detail.get("timestamps", {}),
                "parent_action_id": existing_detail.get("parent_action_id", ""),
                "child_action_ids": existing_detail.get("child_action_ids", []),
                "plan_revision": existing_detail.get("plan_revision", 0),
                "plan_diff": existing_detail.get("plan_diff", ""),
                "change_ledger": existing_detail.get("change_ledger", []),
                "result_summary": existing.get("result_summary", ""),
                "recovery": existing.get("recovery", ""),
                "created_at": existing.get("created_at", ""),
            }
            merged.update({key: value for key, value in kwargs.items() if value is not None})
            card = make_action_card(**merged)
            card["created_at"] = existing.get("created_at", card["created_at"])
            card["updated_at"] = now_iso()
        else:
            card = make_action_card(**kwargs)
        self._save_action_detail(card)
        rows = [row for row in data.get("actions", []) if row.get("action_id") != card["action_id"]]
        rows.insert(0, action_row(card))
        data["actions"] = rows[:100]
        self._save(data)
        return card

    def list_action_cards(
        self,
        project_id: str | None = None,
        thread_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._load().get("actions", [])
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if thread_id:
            rows = [row for row in rows if row.get("thread_id") == thread_id]
        if status:
            normalized = normalize_action_status(status)
            rows = [row for row in rows if normalize_action_status(row.get("status", "")) == normalized]
        return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)

    def get_action_card(self, action_id: str) -> dict[str, Any] | None:
        if not action_id:
            return None
        row = next((item for item in self._load().get("actions", []) if item.get("action_id") == action_id), None)
        if row is None:
            return None
        detail = self._load_action_detail(action_id)
        merged = dict(row)
        merged["detail"] = detail.get("detail", {})
        merged["prompt_preview"] = detail.get("prompt_preview", row.get("prompt_preview", ""))
        for key in (
            "kind",
            "tool_name",
            "risk_rationale",
            "approval_policy",
            "scope_summary",
            "outcome_summary",
            "preview_summary",
            "tool_activity",
            "warnings",
        ):
            if key in detail:
                merged[key] = detail.get(key)
        return merged

    def update_action_status(
        self,
        action_id: str,
        status: str,
        result_summary: str = "",
        recovery: str = "",
        plan: str = "",
        **updates: Any,
    ) -> dict[str, Any]:
        card = self.get_action_card(action_id)
        if card is None:
            raise KeyError(f"Action card not found: {action_id}")
        detail = dict(card.get("detail", {}))
        if plan:
            detail["plan"] = plan
        detail.update(updates.pop("detail", {}) or {})
        detail_updates = {
            key: updates.pop(key)
            for key in list(updates.keys())
            if key in {
                "risk_axes",
                "assumptions",
                "dependencies",
                "short_plan",
                "full_plan",
                "tool_activity",
                "timestamps",
                "parent_action_id",
                "child_action_ids",
                "plan_revision",
                "plan_diff",
                "change_ledger",
            }
        }
        detail.update(detail_updates)
        normalized_status = normalize_action_status(status, card.get("risk", "low"))
        updated = self.save_action_card(
            action_id=action_id,
            project_id=card.get("project_id", ""),
            thread_id=card.get("thread_id", ""),
            title=card.get("title", ""),
            kind=updates.pop("kind", card.get("kind", detail.get("kind", ""))),
            prompt=detail.get("prompt", card.get("prompt_preview", "")),
            plan=detail.get("plan", card.get("plan_preview", "")),
            tool_name=card.get("tool_name", ""),
            arguments=detail.get("arguments", {}),
            affected_targets=card.get("affected_targets", []),
            required_context=card.get("required_context", []),
            risk=updates.pop("risk", card.get("risk", "low")),
            risk_rationale=updates.pop("risk_rationale", card.get("risk_rationale", detail.get("risk_rationale", ""))),
            risk_axes=detail.get("risk_axes", {}),
            status=normalized_status,
            scope_summary=updates.pop("scope_summary", card.get("scope_summary", detail.get("scope_summary", ""))),
            outcome_summary=updates.pop("outcome_summary", card.get("outcome_summary", detail.get("outcome_summary", ""))),
            assumptions=detail.get("assumptions", []),
            dependencies=detail.get("dependencies", []),
            preview_summary=updates.pop("preview_summary", card.get("preview_summary", detail.get("preview_summary", ""))),
            short_plan=detail.get("short_plan", []),
            full_plan=detail.get("full_plan", detail.get("plan", "")),
            approval_policy=updates.pop("approval_policy", card.get("approval_policy", detail.get("approval_policy", ""))),
            tool_activity=detail.get("tool_activity", []),
            warnings=updates.pop("warnings", card.get("warnings", detail.get("warnings", []))),
            timestamps=detail.get("timestamps", {}),
            parent_action_id=detail.get("parent_action_id", ""),
            child_action_ids=detail.get("child_action_ids", []),
            plan_revision=int(detail.get("plan_revision", 0) or 0),
            plan_diff=detail.get("plan_diff", ""),
            change_ledger=detail.get("change_ledger", []),
            result_summary=result_summary or card.get("result_summary", ""),
            recovery=recovery or card.get("recovery", ""),
            created_at=card.get("created_at", ""),
        )
        self.add_job_event(
            f"Action {normalize_action_status(card.get('status', ''))} -> {updated.get('status', normalized_status)}",
            updated.get("status", normalized_status),
            updated.get("title", action_id),
            project_id=updated.get("project_id", ""),
        )
        return updated

    def pin_output(
        self,
        *,
        title: str,
        summary: str,
        kind: str = "result",
        source_thread_id: str = "",
        action_id: str = "",
        path: str = "",
        project_id: str = "",
    ) -> dict[str, Any]:
        data = self._load()
        now = _now()
        output = {
            "output_id": make_output_id(),
            "project_id": project_id or data.get("active_project_id", DEFAULT_PROJECT_ID),
            "source_thread_id": source_thread_id,
            "action_id": action_id,
            "title": title or "Pinned Output",
            "kind": kind or "result",
            "summary": _preview(summary, 320),
            "path": path,
            "created_at": now,
            "updated_at": now,
        }
        outputs = data.get("pinned_outputs", [])
        outputs.insert(0, output)
        data["pinned_outputs"] = outputs[:100]
        self._save(data)
        return output

    def list_pinned_outputs(self, project_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        outputs = self._load().get("pinned_outputs", [])
        if project_id:
            outputs = [output for output in outputs if output.get("project_id") == project_id]
        return sorted(outputs, key=lambda output: output.get("updated_at", ""), reverse=True)[:limit]

    def add_job_event(self, label: str, status: str = "info", detail: str = "", project_id: str = "") -> dict[str, Any]:
        data = self._load()
        event = {
            "event_id": make_event_id(),
            "project_id": project_id or data.get("active_project_id", DEFAULT_PROJECT_ID),
            "label": label or "AI event",
            "status": status or "info",
            "detail": _preview(detail, 400),
            "created_at": _now(),
        }
        events = data.get("job_timeline", [])
        events.insert(0, event)
        data["job_timeline"] = events[:120]
        self._save(data)
        return event

    def list_job_timeline(self, project_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        events = self._load().get("job_timeline", [])
        if project_id:
            events = [event for event in events if event.get("project_id") == project_id]
        return sorted(events, key=lambda event: event.get("created_at", ""), reverse=True)[:limit]

    def _ensure_project_in_data(self, data: dict[str, Any], project_id: str, cwd: str) -> None:
        project_id = project_id or DEFAULT_PROJECT_ID
        if any(project.get("project_id") == project_id for project in data.get("projects", [])):
            return
        data.setdefault("projects", []).append(
            {
                "project_id": project_id,
                "name": DEFAULT_PROJECT_NAME,
                "cwd": cwd,
                "asset_library_name": "Codex Blender Agent",
                "notes": "",
                "created_at": _now(),
                "updated_at": _now(),
            }
        )

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_data()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_data()
        data.setdefault("projects", [])
        data.setdefault("threads", [])
        data.setdefault("actions", [])
        data.setdefault("pinned_outputs", [])
        data.setdefault("job_timeline", [])
        data.setdefault("active_project_id", DEFAULT_PROJECT_ID)
        data.setdefault("active_thread_id", "")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "projects": [],
            "threads": [],
            "actions": [],
            "pinned_outputs": [],
            "job_timeline": [],
            "active_project_id": DEFAULT_PROJECT_ID,
            "active_thread_id": "",
        }

    def _save_action_detail(self, card: dict[str, Any]) -> None:
        self.action_details_dir.mkdir(parents=True, exist_ok=True)
        path = self.action_details_dir / f"{_safe_id(card['action_id'])}.json"
        path.write_text(json.dumps(card, ensure_ascii=True, indent=2), encoding="utf-8")

    def _load_action_detail(self, action_id: str) -> dict[str, Any]:
        path = self.action_details_dir / f"{_safe_id(action_id)}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def make_project_id(cwd: str) -> str:
    if not cwd:
        return DEFAULT_PROJECT_ID
    slug = re.sub(r"[^a-z0-9]+", "-", cwd.lower()).strip("-")[-48:] or "project"
    return f"project-{slug}"


def make_thread_id() -> str:
    return f"local-{uuid.uuid4().hex[:16]}"


def _title_from_messages(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and message.get("text"):
            return _preview(message["text"], 48)
    return "New Thread"


def _summarize_messages(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return "Empty thread."
    parts = []
    for message in messages[-8:]:
        role = message.get("role", "message")
        text = _preview(message.get("text", ""), 160)
        if text:
            parts.append(f"{role}: {text}")
    return "\n".join(parts) or "No visible text."


def _preview(text: str, limit: int = 240) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)] + "..."


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:160]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
