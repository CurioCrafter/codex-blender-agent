from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from .constants import ADDON_VERSION
except Exception:  # pragma: no cover
    ADDON_VERSION = "0.0.0"


WORKFLOW_RUNTIME_SCHEMA_VERSION = 1
LEGACY_WORKFLOW_FILENAMES = (
    "workflow.json",
    "workflow_runtime.json",
    "workflow_graphs.json",
    "workflow_recipes.json",
    "workflow_patches.json",
)


class WorkflowRuntimeStoreError(RuntimeError):
    pass


class WorkflowRuntimeStore:
    def __init__(self, root: Path, legacy_root: Path | None = None) -> None:
        self.root = Path(root)
        self.legacy_root = Path(legacy_root) if legacy_root is not None else self.root.parent
        self.db_path = self.root / "workflow_runtime.db"
        self.backup_dir = self.root / "migration_backups"
        self.runs_dir = self.root / "runs"
        self.checkpoints_dir = self.root / "checkpoints"
        self.manifests_dir = self.root / "manifests"
        self.recipes_dir = self.root / "recipes"
        self.patches_dir = self.root / "patches"
        self.logs_dir = self.root / "logs"
        self.cache_dir = self.root / "cache"

    def initialize(self) -> dict[str, Any]:
        self._ensure_dirs()
        with self._connect() as con:
            self._create_schema(con)
            self._set_meta(con, "schema_version", str(WORKFLOW_RUNTIME_SCHEMA_VERSION))
            self._set_meta(con, "addon_version", ADDON_VERSION)
        return self.diagnose()

    def migrate_legacy(self) -> dict[str, Any]:
        self.initialize()
        migrated = {"backups": [], "graphs": 0, "nodes": 0, "links": 0, "runs": 0, "run_nodes": 0, "checkpoints": 0, "recipes": 0, "tests": 0, "patches": 0}
        stamp = _now_stamp()
        with self._connect() as con:
            if self._get_meta(con, "legacy_migration_v1") == "complete":
                migrated["skipped"] = True
                return migrated
            self._set_meta(con, "legacy_migration_v1", "running")
            backup_root = self.backup_dir / f"legacy-{stamp}"
            backup_root.mkdir(parents=True, exist_ok=True)
            for filename in LEGACY_WORKFLOW_FILENAMES:
                source = self.legacy_root / filename
                if source.exists():
                    target = backup_root / filename
                    shutil.copy2(source, target)
                    migrated["backups"].append(str(target))

        for filename in LEGACY_WORKFLOW_FILENAMES:
            source = self.legacy_root / filename
            if not source.exists():
                continue
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._record_fatal_migration_error(source, exc)
                continue
            summary = self._migrate_legacy_payload(payload)
            for key, value in summary.items():
                if key in migrated:
                    migrated[key] += value

        with self._connect() as con:
            self._set_meta(con, "legacy_migration_v1", "complete")
            self._record_health(con, "info", "migration", "Legacy workflow JSON migrated into SQLite.", migrated)
        return migrated

    def diagnose(self) -> dict[str, Any]:
        with self._connect() as con:
            journal_mode = str(con.execute("pragma journal_mode").fetchone()[0]).lower()
            return {
                "db_path": str(self.db_path),
                "schema_version": self._get_meta(con, "schema_version"),
                "addon_version": self._get_meta(con, "addon_version"),
                "wal_enabled": journal_mode == "wal",
                "graph_count": self._scalar(con, "select count(*) from workflow_graphs"),
                "node_count": self._scalar(con, "select count(*) from workflow_nodes"),
                "run_count": self._scalar(con, "select count(*) from workflow_runs"),
                "run_node_count": self._scalar(con, "select count(*) from workflow_run_nodes"),
                "checkpoint_count": self._scalar(con, "select count(*) from workflow_checkpoints"),
                "recipe_count": self._scalar(con, "select count(*) from recipe_versions"),
                "patch_count": self._scalar(con, "select count(*) from patch_proposals"),
                "backup_dir": str(self.backup_dir),
                "manifests_dir": str(self.manifests_dir),
                "runs_dir": str(self.runs_dir),
                "checkpoints_dir": str(self.checkpoints_dir),
            }

    def canonicalize_graph_manifest(self, manifest: Any) -> Any:
        return _canonicalize_value(manifest)

    def serialize_graph_manifest(self, manifest: Any) -> str:
        return json.dumps(self.canonicalize_graph_manifest(manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def hash_graph_manifest(self, manifest: Any) -> str:
        return hashlib.sha256(self.serialize_graph_manifest(manifest).encode("utf-8")).hexdigest()

    def upsert_graph(self, graph_id: str, name: str, manifest: dict[str, Any] | None, *, kind: str = "workflow", status: str = "draft") -> dict[str, Any]:
        graph_id = _required_text(graph_id, "graph_id")
        name = _required_text(name, "name")
        manifest = dict(manifest or {})
        manifest.setdefault("graph_id", graph_id)
        manifest.setdefault("name", name)
        manifest.setdefault("kind", kind)
        manifest_json = self.serialize_graph_manifest(manifest)
        graph_hash = self.hash_graph_manifest(manifest)
        now = _now()
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_graphs(graph_id, name, kind, status, graph_hash, manifest_json, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(graph_id) do update set
                    name=excluded.name,
                    kind=excluded.kind,
                    status=excluded.status,
                    graph_hash=excluded.graph_hash,
                    manifest_json=excluded.manifest_json,
                    updated_at=excluded.updated_at
                """,
                (graph_id, name, kind, status, graph_hash, manifest_json, now, now),
            )
            self._sync_graph_nodes(con, graph_id, manifest.get("nodes", []))
            self._sync_graph_links(con, graph_id, manifest.get("links", []))
        return self.get_graph(graph_id)

    def get_graph(self, graph_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_graphs where graph_id = ?", (_required_text(graph_id, "graph_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Graph not found: {graph_id}")
        payload = dict(row)
        payload["manifest"] = json.loads(payload.pop("manifest_json") or "{}")
        payload["nodes"] = self.list_graph_nodes(graph_id)
        payload["links"] = self.list_graph_links(graph_id)
        return payload

    def list_graphs(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from workflow_graphs order by updated_at desc, name asc").fetchall()
        return [self._graph_row_to_dict(row) for row in rows]

    def upsert_graph_node(self, graph_id: str, node_id: str, *, node_name: str, node_type: str, state: str = "draft", freshness: str = "clean", risk_level: str = "none", warning_count: int = 0, last_run_id: str = "", last_result_summary: str = "", last_error_summary: str = "", action_card_ref: str = "", node_data: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        payload = _canonicalize_value(node_data or {})
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_nodes(
                    node_id, graph_id, node_name, node_type, state, freshness, risk_level,
                    warning_count, last_run_id, last_result_summary, last_error_summary,
                    action_card_ref, node_data_json, created_at, updated_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(node_id) do update set
                    graph_id=excluded.graph_id,
                    node_name=excluded.node_name,
                    node_type=excluded.node_type,
                    state=excluded.state,
                    freshness=excluded.freshness,
                    risk_level=excluded.risk_level,
                    warning_count=excluded.warning_count,
                    last_run_id=excluded.last_run_id,
                    last_result_summary=excluded.last_result_summary,
                    last_error_summary=excluded.last_error_summary,
                    action_card_ref=excluded.action_card_ref,
                    node_data_json=excluded.node_data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    _required_text(node_id, "node_id"),
                    _required_text(graph_id, "graph_id"),
                    _required_text(node_name, "node_name"),
                    _required_text(node_type, "node_type"),
                    _required_text(state, "state"),
                    _required_text(freshness, "freshness"),
                    _required_text(risk_level, "risk_level"),
                    int(warning_count),
                    last_run_id or "",
                    last_result_summary or "",
                    last_error_summary or "",
                    action_card_ref or "",
                    json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return self.get_graph_node(node_id)

    def get_graph_node(self, node_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_nodes where node_id = ?", (_required_text(node_id, "node_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Graph node not found: {node_id}")
        payload = dict(row)
        payload["node_data"] = json.loads(payload.pop("node_data_json") or "{}")
        return payload

    def list_graph_nodes(self, graph_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from workflow_nodes where graph_id = ? order by updated_at desc, node_name asc", (_required_text(graph_id, "graph_id"),)).fetchall()
        return [self._graph_node_row_to_dict(row) for row in rows]

    def upsert_graph_link(self, graph_id: str, *, from_node: str, from_socket: str, to_node: str, to_socket: str, link_id: str | None = None, link_data: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        link_id = link_id or _make_id("link")
        payload = _canonicalize_value(link_data or {})
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_links(link_id, graph_id, from_node, from_socket, to_node, to_socket, link_data_json, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(link_id) do update set
                    graph_id=excluded.graph_id,
                    from_node=excluded.from_node,
                    from_socket=excluded.from_socket,
                    to_node=excluded.to_node,
                    to_socket=excluded.to_socket,
                    link_data_json=excluded.link_data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    link_id,
                    _required_text(graph_id, "graph_id"),
                    _required_text(from_node, "from_node"),
                    _required_text(from_socket, "from_socket"),
                    _required_text(to_node, "to_node"),
                    _required_text(to_socket, "to_socket"),
                    json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return self.get_graph_link(link_id)

    def get_graph_link(self, link_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_links where link_id = ?", (_required_text(link_id, "link_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Graph link not found: {link_id}")
        payload = dict(row)
        payload["link_data"] = json.loads(payload.pop("link_data_json") or "{}")
        return payload

    def list_graph_links(self, graph_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from workflow_links where graph_id = ? order by updated_at desc, from_node asc, to_node asc", (_required_text(graph_id, "graph_id"),)).fetchall()
        return [self._graph_link_row_to_dict(row) for row in rows]

    def create_run(self, *, graph_id: str, graph_manifest: dict[str, Any] | None = None, preview_only: bool = True, snapshot_hash: str = "", input_hash: str = "", run_label: str = "", status: str = "queued", action_card_ref: str = "", run_data: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
        run_id = run_id or _make_id("run")
        now = _now()
        graph_manifest = graph_manifest or self.get_graph(graph_id).get("manifest", {})
        graph_hash = self.hash_graph_manifest(graph_manifest)
        payload = _canonicalize_value(run_data or {})
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_runs(
                    run_id, graph_id, graph_hash, status, preview_only, snapshot_hash, input_hash,
                    run_label, action_card_ref, result_summary, error_summary, run_data_json,
                    created_at, updated_at, completed_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    graph_id=excluded.graph_id,
                    graph_hash=excluded.graph_hash,
                    status=excluded.status,
                    preview_only=excluded.preview_only,
                    snapshot_hash=excluded.snapshot_hash,
                    input_hash=excluded.input_hash,
                    run_label=excluded.run_label,
                    action_card_ref=excluded.action_card_ref,
                    run_data_json=excluded.run_data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    _required_text(graph_id, "graph_id"),
                    graph_hash,
                    _required_text(status, "status"),
                    1 if preview_only else 0,
                    snapshot_hash or "",
                    input_hash or "",
                    run_label or "",
                    action_card_ref or "",
                    "",
                    "",
                    json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                    "",
                ),
            )
        return self.get_run(run_id)

    def update_run_status(self, run_id: str, status: str, *, result_summary: str = "", error_summary: str = "", action_card_ref: str | None = None, run_data: dict[str, Any] | None = None, completed: bool | None = None) -> dict[str, Any]:
        current = self.get_run(run_id)
        updated_data = _canonicalize_value(run_data or current.get("run_data", {}))
        now = _now()
        completed_at = current.get("completed_at", "")
        if completed or status in {"completed", "completed_with_warnings", "failed", "cancelled", "recovered"}:
            completed_at = completed_at or now
        with self._connect() as con:
            con.execute(
                """
                update workflow_runs set
                    status = ?, result_summary = ?, error_summary = ?, action_card_ref = coalesce(?, action_card_ref),
                    run_data_json = ?, updated_at = ?, completed_at = ?
                where run_id = ?
                """,
                (
                    _required_text(status, "status"),
                    result_summary or "",
                    error_summary or "",
                    action_card_ref,
                    json.dumps(updated_data, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    now,
                    completed_at,
                    _required_text(run_id, "run_id"),
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_runs where run_id = ?", (_required_text(run_id, "run_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Run not found: {run_id}")
        payload = dict(row)
        payload["run_data"] = json.loads(payload.pop("run_data_json") or "{}")
        payload["nodes"] = self.list_run_nodes(run_id)
        payload["checkpoints"] = self.list_checkpoints(run_id)
        return payload

    def list_runs(self, graph_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from workflow_runs"
        params: tuple[Any, ...] = ()
        if graph_id:
            query += " where graph_id = ?"
            params = (_required_text(graph_id, "graph_id"),)
        query += " order by updated_at desc, created_at desc"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [self._run_row_to_dict(row) for row in rows]

    def record_run_node(self, run_id: str, node_id: str, *, node_name: str, node_type: str, state: str, freshness: str = "clean", risk_level: str = "none", warning_count: int = 0, start_at: str | None = None, end_at: str | None = None, duration_ms: int = 0, result_summary: str = "", error_summary: str = "", action_card_ref: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        start_at = start_at or now
        end_at = end_at or ""
        payload = _canonicalize_value(detail or {})
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_run_nodes(
                    run_id, node_id, node_name, node_type, state, freshness, risk_level,
                    warning_count, start_at, end_at, duration_ms, result_summary,
                    error_summary, action_card_ref, detail_json
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id, node_id) do update set
                    node_name=excluded.node_name,
                    node_type=excluded.node_type,
                    state=excluded.state,
                    freshness=excluded.freshness,
                    risk_level=excluded.risk_level,
                    warning_count=excluded.warning_count,
                    start_at=excluded.start_at,
                    end_at=excluded.end_at,
                    duration_ms=excluded.duration_ms,
                    result_summary=excluded.result_summary,
                    error_summary=excluded.error_summary,
                    action_card_ref=excluded.action_card_ref,
                    detail_json=excluded.detail_json
                """,
                (
                    _required_text(run_id, "run_id"),
                    _required_text(node_id, "node_id"),
                    _required_text(node_name, "node_name"),
                    _required_text(node_type, "node_type"),
                    _required_text(state, "state"),
                    _required_text(freshness, "freshness"),
                    _required_text(risk_level, "risk_level"),
                    int(warning_count),
                    start_at,
                    end_at,
                    int(duration_ms),
                    result_summary or "",
                    error_summary or "",
                    action_card_ref or "",
                    json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                ),
            )
        return self.get_run_node(run_id, node_id)

    def get_run_node(self, run_id: str, node_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_run_nodes where run_id = ? and node_id = ?", (_required_text(run_id, "run_id"), _required_text(node_id, "node_id"))).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Run node not found: {run_id}/{node_id}")
        payload = dict(row)
        payload["detail"] = json.loads(payload.pop("detail_json") or "{}")
        return payload

    def list_run_nodes(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from workflow_run_nodes where run_id = ? order by start_at asc, node_name asc", (_required_text(run_id, "run_id"),)).fetchall()
        return [self._run_node_row_to_dict(row) for row in rows]

    def create_checkpoint(self, run_id: str, *, label: str, state: dict[str, Any], node_id: str = "", snapshot_hash: str = "", resume_token: str | None = None, checkpoint_id: str | None = None) -> dict[str, Any]:
        checkpoint_id = checkpoint_id or _make_id("checkpoint")
        now = _now()
        resume_token = resume_token or f"resume-{uuid.uuid4().hex[:16]}"
        state_json = json.dumps(_canonicalize_value(state), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        with self._connect() as con:
            con.execute(
                """
                insert into workflow_checkpoints(checkpoint_id, run_id, node_id, label, snapshot_hash, state_json, resume_token, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(checkpoint_id) do update set
                    run_id=excluded.run_id,
                    node_id=excluded.node_id,
                    label=excluded.label,
                    snapshot_hash=excluded.snapshot_hash,
                    state_json=excluded.state_json,
                    resume_token=excluded.resume_token
                """,
                (checkpoint_id, _required_text(run_id, "run_id"), node_id or "", _required_text(label, "label"), snapshot_hash or "", state_json, resume_token, now),
            )
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from workflow_checkpoints where checkpoint_id = ?", (_required_text(checkpoint_id, "checkpoint_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Checkpoint not found: {checkpoint_id}")
        payload = dict(row)
        payload["state"] = json.loads(payload.pop("state_json") or "{}")
        return payload

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from workflow_checkpoints where run_id = ? order by created_at asc", (_required_text(run_id, "run_id"),)).fetchall()
        return [self._checkpoint_row_to_dict(row) for row in rows]

    def publish_recipe(
        self,
        *,
        recipe_id: str,
        version: str,
        name: str,
        graph_id: str,
        manifest: dict[str, Any],
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        required_tools: list[str] | None = None,
        risk_profile: str = "low",
        author: str = "",
        changelog: str = "",
        preview_path: str = "",
        tests: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        catalog_path: str = "",
        compatibility: dict[str, Any] | None = None,
        status: str = "draft",
        recipe_version_uid: str | None = None,
    ) -> dict[str, Any]:
        major, minor, patch = _parse_semver(version)
        recipe_version_uid = recipe_version_uid or f"recipever:{_safe_uid(recipe_id)}@{version}"
        now = _now()
        manifest_json = self.serialize_graph_manifest(manifest)
        with self._connect() as con:
            con.execute(
                """
                insert into recipe_versions(
                    recipe_version_uid, recipe_id, version, major, minor, patch, name, graph_id,
                    graph_hash, manifest_json, input_schema_json, output_schema_json,
                    required_tools_json, risk_profile, author, changelog, preview_path,
                    tests_json, tags_json, catalog_path, compatibility_json, status,
                    created_at, updated_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(recipe_version_uid) do update set
                    recipe_id=excluded.recipe_id,
                    version=excluded.version,
                    major=excluded.major,
                    minor=excluded.minor,
                    patch=excluded.patch,
                    name=excluded.name,
                    graph_id=excluded.graph_id,
                    graph_hash=excluded.graph_hash,
                    manifest_json=excluded.manifest_json,
                    input_schema_json=excluded.input_schema_json,
                    output_schema_json=excluded.output_schema_json,
                    required_tools_json=excluded.required_tools_json,
                    risk_profile=excluded.risk_profile,
                    author=excluded.author,
                    changelog=excluded.changelog,
                    preview_path=excluded.preview_path,
                    tests_json=excluded.tests_json,
                    tags_json=excluded.tags_json,
                    catalog_path=excluded.catalog_path,
                    compatibility_json=excluded.compatibility_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    recipe_version_uid,
                    _required_text(recipe_id, "recipe_id"),
                    _required_text(version, "version"),
                    major,
                    minor,
                    patch,
                    _required_text(name, "name"),
                    _required_text(graph_id, "graph_id"),
                    self.hash_graph_manifest(manifest),
                    manifest_json,
                    _json_dump(input_schema or {}),
                    _json_dump(output_schema or {}),
                    _json_dump(required_tools or []),
                    _required_text(risk_profile, "risk_profile"),
                    author or "",
                    changelog or "",
                    preview_path or "",
                    _json_dump(tests or []),
                    _json_dump(tags or []),
                    catalog_path or "",
                    _json_dump(compatibility or {}),
                    _required_text(status, "status"),
                    now,
                    now,
                ),
            )
        return self.get_recipe_version(recipe_version_uid)

    def list_recipe_versions(self, recipe_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from recipe_versions"
        params: tuple[Any, ...] = ()
        if recipe_id:
            query += " where recipe_id = ?"
            params = (_required_text(recipe_id, "recipe_id"),)
        query += " order by major desc, minor desc, patch desc, updated_at desc"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [self._recipe_row_to_dict(row) for row in rows]

    def get_recipe_version(self, recipe_version_uid: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from recipe_versions where recipe_version_uid = ?", (_required_text(recipe_version_uid, "recipe_version_uid"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Recipe version not found: {recipe_version_uid}")
        return self._recipe_row_to_dict(row)

    def record_recipe_test(
        self,
        recipe_version_uid: str,
        *,
        name: str,
        state: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error_summary: str = "",
        test_id: str | None = None,
    ) -> dict[str, Any]:
        test_id = test_id or _make_id("test")
        now = _now()
        with self._connect() as con:
            con.execute(
                """
                insert into recipe_tests(test_id, recipe_version_uid, name, state, input_json, output_json, error_summary, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(test_id) do update set
                    recipe_version_uid=excluded.recipe_version_uid,
                    name=excluded.name,
                    state=excluded.state,
                    input_json=excluded.input_json,
                    output_json=excluded.output_json,
                    error_summary=excluded.error_summary,
                    updated_at=excluded.updated_at
                """,
                (
                    test_id,
                    _required_text(recipe_version_uid, "recipe_version_uid"),
                    _required_text(name, "name"),
                    _required_text(state, "state"),
                    _json_dump(input_data or {}),
                    _json_dump(output_data or {}),
                    error_summary or "",
                    now,
                    now,
                ),
            )
        return self.get_recipe_test(test_id)

    def get_recipe_test(self, test_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from recipe_tests where test_id = ?", (_required_text(test_id, "test_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Recipe test not found: {test_id}")
        return self._recipe_test_row_to_dict(row)

    def list_recipe_tests(self, recipe_version_uid: str | None = None) -> list[dict[str, Any]]:
        query = "select * from recipe_tests"
        params: tuple[Any, ...] = ()
        if recipe_version_uid:
            query += " where recipe_version_uid = ?"
            params = (_required_text(recipe_version_uid, "recipe_version_uid"),)
        query += " order by created_at asc"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [self._recipe_test_row_to_dict(row) for row in rows]

    def create_patch_proposal(
        self,
        *,
        graph_id: str,
        base_graph_hash: str,
        proposal_kind: str,
        summary: str,
        proposal: dict[str, Any],
        diff: dict[str, Any] | None = None,
        contract_diff: dict[str, Any] | None = None,
        staging_graph: dict[str, Any] | None = None,
        status: str = "draft",
        patch_id: str | None = None,
    ) -> dict[str, Any]:
        patch_id = patch_id or _make_id("patch")
        now = _now()
        with self._connect() as con:
            con.execute(
                """
                insert into patch_proposals(
                    patch_id, graph_id, base_graph_hash, proposal_kind, status, summary,
                    proposal_json, diff_json, contract_diff_json, staging_graph_json,
                    created_at, updated_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(patch_id) do update set
                    graph_id=excluded.graph_id,
                    base_graph_hash=excluded.base_graph_hash,
                    proposal_kind=excluded.proposal_kind,
                    status=excluded.status,
                    summary=excluded.summary,
                    proposal_json=excluded.proposal_json,
                    diff_json=excluded.diff_json,
                    contract_diff_json=excluded.contract_diff_json,
                    staging_graph_json=excluded.staging_graph_json,
                    updated_at=excluded.updated_at
                """,
                (
                    patch_id,
                    _required_text(graph_id, "graph_id"),
                    _required_text(base_graph_hash, "base_graph_hash"),
                    _required_text(proposal_kind, "proposal_kind"),
                    _required_text(status, "status"),
                    _required_text(summary, "summary"),
                    _json_dump(proposal),
                    _json_dump(diff or {}),
                    _json_dump(contract_diff or {}),
                    _json_dump(staging_graph or {}),
                    now,
                    now,
                ),
            )
        return self.get_patch_proposal(patch_id)

    def update_patch_proposal_status(self, patch_id: str, status: str, *, message: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        with self._connect() as con:
            con.execute("update patch_proposals set status = ?, updated_at = ? where patch_id = ?", (_required_text(status, "status"), now, _required_text(patch_id, "patch_id")))
            if message:
                con.execute(
                    "insert into patch_events(event_id, patch_id, kind, message, detail_json, created_at) values(?, ?, ?, ?, ?, ?)",
                    (_make_id("event"), _required_text(patch_id, "patch_id"), _required_text(status, "status"), message, _json_dump(detail or {}), now),
                )
        return self.get_patch_proposal(patch_id)

    def append_patch_event(self, patch_id: str, kind: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._connect() as con:
            con.execute(
                "insert into patch_events(event_id, patch_id, kind, message, detail_json, created_at) values(?, ?, ?, ?, ?, ?)",
                (_make_id("event"), _required_text(patch_id, "patch_id"), _required_text(kind, "kind"), _required_text(message, "message"), _json_dump(detail or {}), _now()),
            )
        return self.list_patch_events(patch_id)[-1]

    def get_patch_proposal(self, patch_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("select * from patch_proposals where patch_id = ?", (_required_text(patch_id, "patch_id"),)).fetchone()
        if row is None:
            raise WorkflowRuntimeStoreError(f"Patch proposal not found: {patch_id}")
        payload = dict(row)
        payload["proposal"] = json.loads(payload.pop("proposal_json") or "{}")
        payload["diff"] = json.loads(payload.pop("diff_json") or "{}")
        payload["contract_diff"] = json.loads(payload.pop("contract_diff_json") or "{}")
        payload["staging_graph"] = json.loads(payload.pop("staging_graph_json") or "{}")
        payload["events"] = self.list_patch_events(patch_id)
        return payload

    def list_patch_proposals(self, graph_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from patch_proposals"
        params: tuple[Any, ...] = ()
        if graph_id:
            query += " where graph_id = ?"
            params = (_required_text(graph_id, "graph_id"),)
        query += " order by updated_at desc, created_at desc"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [self._patch_row_to_dict(row) for row in rows]

    def list_patch_events(self, patch_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("select * from patch_events where patch_id = ? order by created_at asc", (_required_text(patch_id, "patch_id"),)).fetchall()
        return [self._patch_event_row_to_dict(row) for row in rows]

    def _create_schema(self, con: sqlite3.Connection) -> None:
        con.executescript(
            """
            create table if not exists meta(key text primary key, value text not null);
            create table if not exists workflow_graphs(
                graph_id text primary key, name text not null, kind text not null,
                status text not null, graph_hash text not null, manifest_json text not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists workflow_nodes(
                node_id text primary key, graph_id text not null, node_name text not null,
                node_type text not null, state text not null, freshness text not null,
                risk_level text not null, warning_count integer not null default 0,
                last_run_id text not null default '', last_result_summary text not null default '',
                last_error_summary text not null default '', action_card_ref text not null default '',
                node_data_json text not null, created_at text not null, updated_at text not null,
                foreign key(graph_id) references workflow_graphs(graph_id) on delete cascade
            );
            create table if not exists workflow_links(
                link_id text primary key, graph_id text not null, from_node text not null,
                from_socket text not null, to_node text not null, to_socket text not null,
                link_data_json text not null, created_at text not null, updated_at text not null,
                foreign key(graph_id) references workflow_graphs(graph_id) on delete cascade
            );
            create table if not exists workflow_runs(
                run_id text primary key, graph_id text not null, graph_hash text not null,
                status text not null, preview_only integer not null default 1,
                snapshot_hash text not null default '', input_hash text not null default '',
                run_label text not null default '', action_card_ref text not null default '',
                result_summary text not null default '', error_summary text not null default '',
                run_data_json text not null, created_at text not null, updated_at text not null,
                completed_at text not null default '',
                foreign key(graph_id) references workflow_graphs(graph_id) on delete cascade
            );
            create table if not exists workflow_run_nodes(
                run_id text not null, node_id text not null, node_name text not null,
                node_type text not null, state text not null, freshness text not null,
                risk_level text not null, warning_count integer not null default 0,
                start_at text not null, end_at text not null default '',
                duration_ms integer not null default 0, result_summary text not null default '',
                error_summary text not null default '', action_card_ref text not null default '',
                detail_json text not null, primary key(run_id, node_id),
                foreign key(run_id) references workflow_runs(run_id) on delete cascade
            );
            create table if not exists workflow_checkpoints(
                checkpoint_id text primary key, run_id text not null, node_id text not null default '',
                label text not null, snapshot_hash text not null default '', state_json text not null,
                resume_token text not null, created_at text not null,
                foreign key(run_id) references workflow_runs(run_id) on delete cascade
            );
            create table if not exists recipe_versions(
                recipe_version_uid text primary key, recipe_id text not null, version text not null,
                major integer not null, minor integer not null, patch integer not null,
                name text not null, graph_id text not null, graph_hash text not null,
                manifest_json text not null, input_schema_json text not null, output_schema_json text not null,
                required_tools_json text not null, risk_profile text not null, author text not null,
                changelog text not null, preview_path text not null, tests_json text not null,
                tags_json text not null, catalog_path text not null, compatibility_json text not null,
                status text not null, created_at text not null, updated_at text not null,
                foreign key(graph_id) references workflow_graphs(graph_id) on delete cascade
            );
            create table if not exists recipe_tests(
                test_id text primary key, recipe_version_uid text not null, name text not null,
                state text not null, input_json text not null, output_json text not null,
                error_summary text not null default '', created_at text not null, updated_at text not null,
                foreign key(recipe_version_uid) references recipe_versions(recipe_version_uid) on delete cascade
            );
            create table if not exists patch_proposals(
                patch_id text primary key, graph_id text not null, base_graph_hash text not null,
                proposal_kind text not null, status text not null, summary text not null,
                proposal_json text not null, diff_json text not null, contract_diff_json text not null,
                staging_graph_json text not null, created_at text not null, updated_at text not null,
                foreign key(graph_id) references workflow_graphs(graph_id) on delete cascade
            );
            create table if not exists patch_events(
                event_id text primary key, patch_id text not null, kind text not null,
                message text not null, detail_json text not null, created_at text not null,
                foreign key(patch_id) references patch_proposals(patch_id) on delete cascade
            );
            create table if not exists health_events(
                event_id text primary key, level text not null, area text not null,
                message text not null, detail_json text not null, created_at text not null
            );
            """
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._ensure_dirs()
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("pragma journal_mode=WAL")
        con.execute("pragma foreign_keys=ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _ensure_dirs(self) -> None:
        for path in (self.root, self.backup_dir, self.runs_dir, self.checkpoints_dir, self.manifests_dir, self.recipes_dir, self.patches_dir, self.logs_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _get_meta(self, con: sqlite3.Connection, key: str) -> str:
        row = con.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, con: sqlite3.Connection, key: str, value: str) -> None:
        con.execute("insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value", (key, value))

    def _scalar(self, con: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
        row = con.execute(query, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _record_health(self, con: sqlite3.Connection, level: str, area: str, message: str, detail: dict[str, Any] | None = None) -> None:
        con.execute(
            "insert into health_events(event_id, level, area, message, detail_json, created_at) values(?, ?, ?, ?, ?, ?)",
            (_make_id("health"), level, area, message, _json_dump(detail or {}), _now()),
        )

    def _record_fatal_migration_error(self, source: Path, exc: Exception) -> None:
        with self._connect() as con:
            self._record_health(con, "error", "migration", f"Failed to migrate {source.name}", {"error": str(exc)})

    def _sync_graph_nodes(self, con: sqlite3.Connection, graph_id: str, nodes: Any) -> int:
        count = 0
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            con.execute(
                """
                insert into workflow_nodes(
                    node_id, graph_id, node_name, node_type, state, freshness, risk_level,
                    warning_count, last_run_id, last_result_summary, last_error_summary,
                    action_card_ref, node_data_json, created_at, updated_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(node_id) do update set
                    graph_id=excluded.graph_id,
                    node_name=excluded.node_name,
                    node_type=excluded.node_type,
                    state=excluded.state,
                    freshness=excluded.freshness,
                    risk_level=excluded.risk_level,
                    warning_count=excluded.warning_count,
                    last_run_id=excluded.last_run_id,
                    last_result_summary=excluded.last_result_summary,
                    last_error_summary=excluded.last_error_summary,
                    action_card_ref=excluded.action_card_ref,
                    node_data_json=excluded.node_data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    _required_text(str(node.get("node_id") or node.get("id") or node.get("name") or _make_id("node")), "node_id"),
                    _required_text(graph_id, "graph_id"),
                    _required_text(str(node.get("node_name") or node.get("name") or node.get("label") or "Node"), "node_name"),
                    _required_text(str(node.get("node_type") or node.get("type") or "value"), "node_type"),
                    _required_text(str(node.get("state") or "draft"), "state"),
                    _required_text(str(node.get("freshness") or "clean"), "freshness"),
                    _required_text(str(node.get("risk_level") or "none"), "risk_level"),
                    int(node.get("warning_count", 0) or 0),
                    str(node.get("last_run_id") or ""),
                    str(node.get("last_result_summary") or ""),
                    str(node.get("last_error_summary") or ""),
                    str(node.get("action_card_ref") or ""),
                    _json_dump(node),
                    _now(),
                    _now(),
                ),
            )
            count += 1
        return count

    def _sync_graph_links(self, con: sqlite3.Connection, graph_id: str, links: Any) -> int:
        count = 0
        for link in links or []:
            if not isinstance(link, dict):
                continue
            con.execute(
                """
                insert into workflow_links(link_id, graph_id, from_node, from_socket, to_node, to_socket, link_data_json, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(link_id) do update set
                    graph_id=excluded.graph_id,
                    from_node=excluded.from_node,
                    from_socket=excluded.from_socket,
                    to_node=excluded.to_node,
                    to_socket=excluded.to_socket,
                    link_data_json=excluded.link_data_json,
                    updated_at=excluded.updated_at
                """,
                (
                    _required_text(str(link.get("link_id") or link.get("id") or _make_id("link")), "link_id"),
                    _required_text(graph_id, "graph_id"),
                    _required_text(str(link.get("from_node") or ""), "from_node"),
                    _required_text(str(link.get("from_socket") or ""), "from_socket"),
                    _required_text(str(link.get("to_node") or ""), "to_node"),
                    _required_text(str(link.get("to_socket") or ""), "to_socket"),
                    _json_dump(link),
                    _now(),
                    _now(),
                ),
            )
            count += 1
        return count

    def _migrate_legacy_payload(self, payload: Any) -> dict[str, int]:
        if not isinstance(payload, dict):
            return {"graphs": 0, "nodes": 0, "links": 0, "runs": 0, "run_nodes": 0, "checkpoints": 0, "recipes": 0, "tests": 0, "patches": 0}
        summary = {"graphs": 0, "nodes": 0, "links": 0, "runs": 0, "run_nodes": 0, "checkpoints": 0, "recipes": 0, "tests": 0, "patches": 0}
        for graph in _as_list(payload.get("graphs")):
            graph_id = str(graph.get("graph_id") or graph.get("id") or graph.get("name") or _make_id("graph"))
            name = str(graph.get("name") or graph_id)
            self.upsert_graph(graph_id, name, graph.get("manifest") or graph, kind=str(graph.get("kind") or "workflow"), status=str(graph.get("status") or "draft"))
            summary["graphs"] += 1
            summary["nodes"] += len(_as_list(graph.get("nodes")))
            summary["links"] += len(_as_list(graph.get("links")))
        for run in _as_list(payload.get("runs")):
            graph_id = str(run.get("graph_id") or run.get("workflow_id") or "workflow")
            run_record = self.create_run(
                graph_id=graph_id,
                graph_manifest=run.get("manifest"),
                preview_only=bool(run.get("preview_only", True)),
                snapshot_hash=str(run.get("snapshot_hash") or ""),
                input_hash=str(run.get("input_hash") or ""),
                run_label=str(run.get("run_label") or run.get("label") or ""),
                status=str(run.get("status") or "queued"),
                action_card_ref=str(run.get("action_card_ref") or ""),
                run_data=run,
                run_id=str(run.get("run_id") or run.get("id") or _make_id("run")),
            )
            summary["runs"] += 1
            for node in _as_list(run.get("nodes")):
                self.record_run_node(
                    run_record["run_id"],
                    str(node.get("node_id") or node.get("id") or node.get("name") or _make_id("node")),
                    node_name=str(node.get("node_name") or node.get("name") or "Node"),
                    node_type=str(node.get("node_type") or node.get("type") or "value"),
                    state=str(node.get("state") or "completed"),
                    freshness=str(node.get("freshness") or "clean"),
                    risk_level=str(node.get("risk_level") or "none"),
                    warning_count=int(node.get("warning_count", 0) or 0),
                    start_at=str(node.get("start_at") or _now()),
                    end_at=str(node.get("end_at") or ""),
                    duration_ms=int(node.get("duration_ms", 0) or 0),
                    result_summary=str(node.get("result_summary") or ""),
                    error_summary=str(node.get("error_summary") or ""),
                    action_card_ref=str(node.get("action_card_ref") or ""),
                    detail=node,
                )
                summary["run_nodes"] += 1
            for checkpoint in _as_list(run.get("checkpoints")):
                self.create_checkpoint(
                    run_record["run_id"],
                    label=str(checkpoint.get("label") or "Checkpoint"),
                    state=checkpoint.get("state") or checkpoint,
                    node_id=str(checkpoint.get("node_id") or ""),
                    snapshot_hash=str(checkpoint.get("snapshot_hash") or ""),
                    resume_token=str(checkpoint.get("resume_token") or ""),
                    checkpoint_id=str(checkpoint.get("checkpoint_id") or checkpoint.get("id") or _make_id("checkpoint")),
                )
                summary["checkpoints"] += 1
        for recipe in _as_list(payload.get("recipes")):
            self.publish_recipe(
                recipe_id=str(recipe.get("recipe_id") or recipe.get("id") or _make_id("recipe")),
                version=str(recipe.get("version") or "1.0.0"),
                name=str(recipe.get("name") or "Recipe"),
                graph_id=str(recipe.get("graph_id") or "workflow"),
                manifest=recipe.get("manifest") or recipe,
                input_schema=recipe.get("input_schema") if isinstance(recipe.get("input_schema"), dict) else {},
                output_schema=recipe.get("output_schema") if isinstance(recipe.get("output_schema"), dict) else {},
                required_tools=_as_list(recipe.get("required_tools")),
                risk_profile=str(recipe.get("risk_profile") or "low"),
                author=str(recipe.get("author") or ""),
                changelog=str(recipe.get("changelog") or ""),
                preview_path=str(recipe.get("preview_path") or ""),
                tests=_as_list(recipe.get("tests")),
                tags=_as_list(recipe.get("tags")),
                catalog_path=str(recipe.get("catalog_path") or ""),
                compatibility=recipe.get("compatibility") if isinstance(recipe.get("compatibility"), dict) else {},
                status=str(recipe.get("status") or "draft"),
                recipe_version_uid=str(recipe.get("recipe_version_uid") or recipe.get("version_uid") or _make_id("recipever")),
            )
            summary["recipes"] += 1
            summary["tests"] += len(_as_list(recipe.get("tests")))
        for patch in _as_list(payload.get("patches")):
            self.create_patch_proposal(
                graph_id=str(patch.get("graph_id") or "workflow"),
                base_graph_hash=str(patch.get("base_graph_hash") or ""),
                proposal_kind=str(patch.get("proposal_kind") or patch.get("kind") or "edit"),
                summary=str(patch.get("summary") or patch.get("title") or "Patch proposal"),
                proposal=patch.get("proposal") if isinstance(patch.get("proposal"), dict) else patch,
                diff=patch.get("diff") if isinstance(patch.get("diff"), dict) else {},
                contract_diff=patch.get("contract_diff") if isinstance(patch.get("contract_diff"), dict) else {},
                staging_graph=patch.get("staging_graph") if isinstance(patch.get("staging_graph"), dict) else {},
                status=str(patch.get("status") or "draft"),
                patch_id=str(patch.get("patch_id") or patch.get("id") or _make_id("patch")),
            )
            summary["patches"] += 1
        return summary

    def _graph_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["manifest"] = json.loads(payload.pop("manifest_json") or "{}")
        return payload

    def _graph_node_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["node_data"] = json.loads(payload.pop("node_data_json") or "{}")
        return payload

    def _graph_link_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["link_data"] = json.loads(payload.pop("link_data_json") or "{}")
        return payload

    def _run_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["run_data"] = json.loads(payload.pop("run_data_json") or "{}")
        payload["nodes"] = self.list_run_nodes(payload["run_id"])
        payload["checkpoints"] = self.list_checkpoints(payload["run_id"])
        return payload

    def _run_node_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["detail"] = json.loads(payload.pop("detail_json") or "{}")
        return payload

    def _checkpoint_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["state"] = json.loads(payload.pop("state_json") or "{}")
        return payload

    def _recipe_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["manifest"] = json.loads(payload.pop("manifest_json") or "{}")
        payload["input_schema"] = json.loads(payload.pop("input_schema_json") or "{}")
        payload["output_schema"] = json.loads(payload.pop("output_schema_json") or "{}")
        payload["required_tools"] = json.loads(payload.pop("required_tools_json") or "[]")
        payload["tests"] = json.loads(payload.pop("tests_json") or "[]")
        payload["tags"] = json.loads(payload.pop("tags_json") or "[]")
        payload["compatibility"] = json.loads(payload.pop("compatibility_json") or "{}")
        return payload

    def _recipe_test_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["input"] = json.loads(payload.pop("input_json") or "{}")
        payload["output"] = json.loads(payload.pop("output_json") or "{}")
        return payload

    def _patch_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["proposal"] = json.loads(payload.pop("proposal_json") or "{}")
        payload["diff"] = json.loads(payload.pop("diff_json") or "{}")
        payload["contract_diff"] = json.loads(payload.pop("contract_diff_json") or "{}")
        payload["staging_graph"] = json.loads(payload.pop("staging_graph_json") or "{}")
        payload["events"] = self.list_patch_events(payload["patch_id"])
        return payload

    def _patch_event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["detail"] = json.loads(payload.pop("detail_json") or "{}")
        return payload


def canonicalize_workflow_manifest(manifest: Any) -> Any:
    return _canonicalize_value(manifest)


def serialize_workflow_manifest(manifest: Any) -> str:
    return json.dumps(canonicalize_workflow_manifest(manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def hash_workflow_manifest(manifest: Any) -> str:
    return hashlib.sha256(serialize_workflow_manifest(manifest).encode("utf-8")).hexdigest()


def _canonicalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _canonicalize_value(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_value(item) for item in value]
    if isinstance(value, set):
        return [_canonicalize_value(item) for item in sorted(value, key=lambda item: json.dumps(_canonicalize_value(item), ensure_ascii=True, sort_keys=True, separators=(",", ":")))]
    if hasattr(value, "__dict__"):
        return _canonicalize_value(vars(value))
    return str(value)


def _json_dump(value: Any) -> str:
    return json.dumps(_canonicalize_value(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowRuntimeStoreError(f"Missing required value for {field_name}.")
    return text


def _make_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_uid(value: str) -> str:
    text = _required_text(value, "uid")
    return "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in text)


def _parse_semver(version: str) -> tuple[int, int, int]:
    text = _required_text(version, "version")
    if text.startswith("v"):
        text = text[1:]
    core = text.split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3:
        raise WorkflowRuntimeStoreError(f"Invalid semantic version: {version!r}")
    try:
        major, minor, patch = (int(part) for part in parts)
    except ValueError as exc:  # pragma: no cover - defensive
        raise WorkflowRuntimeStoreError(f"Invalid semantic version: {version!r}") from exc
    return major, minor, patch
