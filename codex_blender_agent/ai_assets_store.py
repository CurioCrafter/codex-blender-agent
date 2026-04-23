from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .constants import ADDON_VERSION


AI_ASSETS_SCHEMA_VERSION = 1
DEFAULT_LICENSE = "NOASSERTION"
PLACEHOLDER_PREVIEW_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\xe2\xa3\x0b\x00\x00\x00\x00IEND\xaeB`\x82"
)

AI_ASSET_LIBRARY_DEFS = (
    ("core", "AI Assets - Core", "core"),
    ("project", "AI Assets - Project", "project"),
    ("scratch", "AI Assets - Scratch", "scratch"),
    ("published", "AI Assets - Published", "published"),
)

DEFAULT_CATALOG_PATHS = (
    "models/props",
    "models/characters",
    "models/environments",
    "materials/procedural",
    "materials/image_based",
    "materials/lookdev",
    "rigs/characters",
    "rigs/props",
    "poses/body",
    "poses/hands",
    "node_systems/geometry/generators",
    "node_systems/geometry/utilities",
    "node_systems/shader/surfaces",
    "node_systems/shader/utilities",
    "node_systems/compositor/lookdev",
    "recipes/modeling",
    "recipes/materials",
    "recipes/rigging",
    "recipes/pipeline",
    "prompts/modeling",
    "prompts/materials",
    "prompts/rigging",
    "outputs/approved",
    "outputs/published",
)


class AIAssetsError(RuntimeError):
    pass


class AIAssetsStore:
    """SQLite authority store for AI Assets."""

    def __init__(self, root: Path, legacy_root: Path | None = None) -> None:
        self.root = Path(root)
        self.legacy_root = Path(legacy_root) if legacy_root is not None else self.root.parent
        self.db_path = self.root / "ai_assets.db"
        self.backup_dir = self.root / "migration_backups"
        self.previews_dir = self.root / "previews"
        self.manifests_dir = self.root / "manifests"
        self.logs_dir = self.root / "logs"
        self.cache_dir = self.root / "cache"
        self.packages_dir = self.root / "packages"
        self.quarantine_dir = self.root / "quarantine"

    def initialize(self) -> dict[str, Any]:
        self._ensure_dirs()
        with self._connect() as con:
            self._create_schema(con)
            self._set_meta(con, "schema_version", str(AI_ASSETS_SCHEMA_VERSION))
            self._set_meta(con, "addon_version", ADDON_VERSION)
        return self.diagnose()

    def migrate_legacy(self) -> dict[str, Any]:
        self.initialize()
        migrated: dict[str, Any] = {"backups": [], "assets": 0, "toolbox": 0, "pins": 0, "actions": 0}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        with self._connect() as con:
            if self._get_meta(con, "legacy_migration_v1") == "complete":
                migrated["skipped"] = True
                return migrated
            self._set_meta(con, "legacy_migration_v1", "running")
            backup_root = self.backup_dir / f"legacy-{stamp}"
            backup_root.mkdir(parents=True, exist_ok=True)
            for filename in ("asset_library.json", "toolbox.json", "dashboard.json", "chat_history.json"):
                source = self.legacy_root / filename
                if source.exists():
                    target = backup_root / filename
                    shutil.copy2(source, target)
                    migrated["backups"].append(str(target))
        migrated["assets"] = self._migrate_asset_json(self.legacy_root / "asset_library.json")
        migrated["toolbox"] = self._migrate_toolbox_json(self.legacy_root / "toolbox.json")
        pins, actions = self._migrate_dashboard_json(self.legacy_root / "dashboard.json")
        with self._connect() as con:
            migrated["pins"] = pins
            migrated["actions"] = actions
            self._set_meta(con, "legacy_migration_v1", "complete")
            self._record_health(con, "info", "migration", "Legacy JSON migrated into SQLite.", migrated)
        return migrated

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
        for path in (
            self.root,
            self.backup_dir,
            self.previews_dir,
            self.manifests_dir,
            self.logs_dir,
            self.cache_dir,
            self.packages_dir,
            self.quarantine_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _create_schema(self, con: sqlite3.Connection) -> None:
        con.executescript(
            """
            create table if not exists meta(key text primary key, value text not null);
            create table if not exists asset_libraries(
                library_id text primary key, name text not null, path text not null,
                scope text not null, owned integer not null default 0,
                status text not null default 'active', created_at text not null, updated_at text not null
            );
            create table if not exists catalog_entries(
                catalog_uuid text not null, library_id text not null, path text not null,
                simple_name text not null, source text not null, status text not null,
                created_at text not null, updated_at text not null,
                primary key(catalog_uuid, library_id)
            );
            create table if not exists logical_assets(
                logical_uid text primary key, kind text not null, title text not null,
                description text not null, tags_json text not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists asset_versions(
                version_uid text primary key, logical_uid text not null, version text not null,
                kind text not null, title text not null, status text not null,
                license_spdx text not null, author text not null, description text not null,
                tags_json text not null, blender_json text not null, compatibility_json text not null,
                integrity_json text not null, metadata_json text not null, provenance_json text not null,
                qa_json text not null, import_policy text not null, catalog_uuid text not null,
                catalog_path text not null, preview_path text not null, content_path text not null,
                content_sha256 text not null, created_at text not null, updated_at text not null
            );
            create table if not exists blender_artifact_refs(
                ref_id text primary key, version_uid text not null, id_type text not null,
                datablock_name text not null, blend_relpath text not null, library_id text not null,
                catalog_uuid text not null, custom_props_json text not null
            );
            create table if not exists dependency_edges(
                edge_id text primary key, version_uid text not null, depends_on_uid text not null,
                dependency_kind text not null, status text not null, detail_json text not null
            );
            create table if not exists provenance_records(
                provenance_id text primary key, version_uid text not null, activity_id text not null,
                entity_json text not null, relations_json text not null, created_at text not null
            );
            create table if not exists qa_results(
                qa_id text primary key, version_uid text not null, state text not null,
                checks_json text not null, created_at text not null
            );
            create table if not exists output_snapshots(
                output_id text primary key, project_id text not null, thread_id text not null,
                action_id text not null, title text not null, summary text not null,
                kind text not null, path text not null, status text not null,
                metadata_json text not null, created_at text not null, updated_at text not null
            );
            create table if not exists pins(
                pin_id text primary key, target_type text not null, target_uid text not null,
                scope text not null, reason text not null, rank integer not null, freeze integer not null,
                project_id text not null, thread_id text not null, created_at text not null, updated_at text not null
            );
            create table if not exists toolbox_entries(
                item_id text primary key, name text not null, category text not null,
                description text not null, content_json text not null, tags_json text not null,
                runnable integer not null, required_context_json text not null,
                output_type text not null, approval_required integer not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists project_memory(
                memory_id text primary key, project_id text not null, kind text not null,
                title text not null, body text not null, metadata_json text not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists thread_memory(
                memory_id text primary key, thread_id text not null, project_id text not null,
                summary text not null, metadata_json text not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists action_card_lineage(
                action_id text primary key, project_id text not null, thread_id text not null,
                operation_type text not null, inputs_json text not null, outputs_json text not null,
                tool_refs_json text not null, remote_session_refs_json text not null, status text not null,
                errors_json text not null, provenance_activity_id text not null,
                created_at text not null, updated_at text not null
            );
            create table if not exists package_manifests(
                package_uid text primary key, version_uid text not null, path text not null,
                status text not null, manifest_json text not null, created_at text not null
            );
            create table if not exists health_events(
                event_id text primary key, level text not null, area text not null,
                message text not null, detail_json text not null, created_at text not null
            );
            create virtual table if not exists ai_assets_fts using fts5(
                title, body, kind, tags, version_uid unindexed
            );
            """
        )

    def _get_meta(self, con: sqlite3.Connection, key: str) -> str:
        row = con.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, con: sqlite3.Connection, key: str, value: str) -> None:
        con.execute(
            "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
            (key, value),
        )

    def _record_health(self, con: sqlite3.Connection, level: str, area: str, message: str, detail: dict[str, Any] | None = None) -> None:
        con.execute(
            "insert into health_events(event_id, level, area, message, detail_json, created_at) values(?, ?, ?, ?, ?, ?)",
            (f"health:{uuid.uuid4().hex[:16]}", level, area, message, _dumps(detail or {}), now_iso()),
        )

    def ensure_default_libraries(self, base_library_root: Path) -> list[dict[str, Any]]:
        self.initialize()
        rows: list[dict[str, Any]] = []
        base = Path(base_library_root)
        for library_id, name, scope in AI_ASSET_LIBRARY_DEFS:
            path = base / scope
            path.mkdir(parents=True, exist_ok=True)
            write_default_catalog_file(path / "blender_assets.cats.txt")
            rows.append(self.upsert_asset_library(library_id=library_id, name=name, path=str(path), scope=scope, owned=True))
        return rows

    def upsert_asset_library(
        self,
        *,
        library_id: str,
        name: str,
        path: str,
        scope: str = "external",
        owned: bool = False,
        status: str = "active",
    ) -> dict[str, Any]:
        self.initialize()
        now = now_iso()
        with self._connect() as con:
            con.execute(
                """
                insert into asset_libraries(library_id, name, path, scope, owned, status, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(library_id) do update set
                    name=excluded.name,
                    path=excluded.path,
                    scope=excluded.scope,
                    owned=excluded.owned,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (library_id, name, path, scope, 1 if owned else 0, status, now, now),
            )
            self.index_catalog_file(con, library_id, Path(path) / "blender_assets.cats.txt")
            return self.get_asset_library(library_id, con=con) or {}

    def list_asset_libraries(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as con:
            return [_row(row) for row in con.execute("select * from asset_libraries order by name").fetchall()]

    def get_asset_library(self, library_id: str, con: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        def _get(active: sqlite3.Connection) -> dict[str, Any] | None:
            row = active.execute("select * from asset_libraries where library_id = ?", (library_id,)).fetchone()
            return _row(row) if row else None

        if con is not None:
            return _get(con)
        self.initialize()
        with self._connect() as active:
            return _get(active)

    def index_catalog_file(self, con: sqlite3.Connection, library_id: str, catalog_path: Path) -> int:
        con.execute("delete from catalog_entries where library_id = ?", (library_id,))
        entries = parse_catalog_file(catalog_path)
        for entry in entries:
            con.execute(
                """
                insert into catalog_entries(catalog_uuid, library_id, path, simple_name, source, status, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(catalog_uuid, library_id) do update set
                    path=excluded.path,
                    simple_name=excluded.simple_name,
                    source=excluded.source,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    entry["catalog_uuid"],
                    library_id,
                    entry["path"],
                    entry["simple_name"],
                    str(catalog_path),
                    entry.get("status", "active"),
                    now_iso(),
                    now_iso(),
                ),
            )
        return len(entries)

    def list_catalog_entries(self, library_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        sql = "select * from catalog_entries"
        params: tuple[Any, ...] = ()
        if library_id:
            sql += " where library_id = ?"
            params = (library_id,)
        sql += " order by path"
        with self._connect() as con:
            return [_row(row) for row in con.execute(sql, params).fetchall()]

    def upsert_asset_version(self, **kwargs: Any) -> dict[str, Any]:
        self.initialize()
        kind = _clean(kwargs.get("kind") or "other")
        title = _clean(kwargs.get("title") or kwargs.get("name") or "Untitled Asset")
        logical_uid = _clean(kwargs.get("logical_uid")) or f"asset:{slugify(title)}"
        version = _clean(kwargs.get("version") or "1.0.0")
        version_uid = _clean(kwargs.get("version_uid")) or f"assetver:{slugify(logical_uid.split(':')[-1])}@{version}"
        content_path = _clean(kwargs.get("content_path") or kwargs.get("stored_path") or kwargs.get("source_path"))
        preview_path = _clean(kwargs.get("preview_path"))
        tags = normalize_tags(kwargs.get("tags"))
        license_spdx = _clean(kwargs.get("license_spdx") or kwargs.get("license") or DEFAULT_LICENSE)
        content_sha = kwargs.get("content_sha256") or (sha256_file(Path(content_path)) if content_path and Path(content_path).exists() else "")
        preview_sha = kwargs.get("preview_sha256") or (sha256_file(Path(preview_path)) if preview_path and Path(preview_path).exists() else "")
        metadata = _json_obj(kwargs.get("metadata"))
        blender = _json_obj(kwargs.get("blender"))
        compatibility = _json_obj(kwargs.get("compatibility") or {"blender_min": "4.5.0", "blender_tested": ["4.5.8"]})
        integrity = _json_obj(
            kwargs.get("integrity")
            or {
                "content_sha256": content_sha,
                "preview_sha256": preview_sha,
                "missing_dependencies": [],
                "dependency_count": 0,
            }
        )
        provenance = _json_obj(kwargs.get("provenance"))
        qa = _json_obj(kwargs.get("qa") or {"validation_state": "unchecked", "preview_generated": bool(preview_path)})
        catalog_path = _clean(kwargs.get("catalog_path") or blender.get("catalog_path") or default_catalog_for_kind(kind))
        catalog_uuid = _clean(kwargs.get("catalog_uuid") or blender.get("catalog_uuid") or stable_uuid(catalog_path))
        import_policy = _clean(kwargs.get("import_policy") or blender.get("import_policy") or default_import_policy(kind))
        description = _clean(kwargs.get("description") or metadata.get("description") or "")
        author = _clean(kwargs.get("author") or metadata.get("author") or "")
        status = _clean(kwargs.get("status") or "draft")
        now = now_iso()

        with self._connect() as con:
            con.execute(
                """
                insert into logical_assets(logical_uid, kind, title, description, tags_json, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?)
                on conflict(logical_uid) do update set
                    kind=excluded.kind, title=excluded.title, description=excluded.description,
                    tags_json=excluded.tags_json, updated_at=excluded.updated_at
                """,
                (logical_uid, kind, title, description, _dumps(tags), now, now),
            )
            con.execute(
                """
                insert into asset_versions(
                    version_uid, logical_uid, version, kind, title, status, license_spdx, author,
                    description, tags_json, blender_json, compatibility_json, integrity_json,
                    metadata_json, provenance_json, qa_json, import_policy, catalog_uuid,
                    catalog_path, preview_path, content_path, content_sha256, created_at, updated_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(version_uid) do update set
                    logical_uid=excluded.logical_uid, version=excluded.version, kind=excluded.kind,
                    title=excluded.title, status=excluded.status, license_spdx=excluded.license_spdx,
                    author=excluded.author, description=excluded.description, tags_json=excluded.tags_json,
                    blender_json=excluded.blender_json, compatibility_json=excluded.compatibility_json,
                    integrity_json=excluded.integrity_json, metadata_json=excluded.metadata_json,
                    provenance_json=excluded.provenance_json, qa_json=excluded.qa_json,
                    import_policy=excluded.import_policy, catalog_uuid=excluded.catalog_uuid,
                    catalog_path=excluded.catalog_path, preview_path=excluded.preview_path,
                    content_path=excluded.content_path, content_sha256=excluded.content_sha256,
                    updated_at=excluded.updated_at
                """,
                (
                    version_uid,
                    logical_uid,
                    version,
                    kind,
                    title,
                    status,
                    license_spdx,
                    author,
                    description,
                    _dumps(tags),
                    _dumps(blender),
                    _dumps(compatibility),
                    _dumps(integrity),
                    _dumps(metadata),
                    _dumps(provenance),
                    _dumps(qa),
                    import_policy,
                    catalog_uuid,
                    catalog_path,
                    preview_path,
                    content_path,
                    content_sha,
                    now,
                    now,
                ),
            )
            self._upsert_fts(con, version_uid, title, description, kind, tags, provenance, metadata)
            self._upsert_artifact_ref(con, version_uid, blender, content_path, catalog_uuid)
            self._upsert_dependencies(con, version_uid, kwargs.get("dependencies") or integrity.get("dependencies") or [])
            self._upsert_provenance(con, version_uid, provenance)
            return self.get_asset_version(version_uid, con=con) or {}

    def list_asset_versions(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        library_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.initialize()
        clauses = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if library_id:
            clauses.append("json_extract(blender_json, '$.library_id') = ?")
            params.append(library_id)
        where = f" where {' and '.join(clauses)}" if clauses else ""
        with self._connect() as con:
            rows = con.execute(f"select * from asset_versions{where} order by updated_at desc limit ?", (*params, int(limit))).fetchall()
            return [self._asset_version_from_row(row) for row in rows]

    def get_asset_version(self, version_uid: str, con: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        def _get(active: sqlite3.Connection) -> dict[str, Any] | None:
            row = active.execute("select * from asset_versions where version_uid = ?", (version_uid,)).fetchone()
            return self._asset_version_from_row(row) if row else None

        if con is not None:
            return _get(con)
        self.initialize()
        with self._connect() as active:
            return _get(active)

    def get_asset_by_legacy_id_or_name(self, item_id_or_name: str) -> dict[str, Any]:
        needle = _clean(item_id_or_name).lower()
        if not needle:
            raise AIAssetsError("Asset id, version uid, or title is required.")
        self.initialize()
        with self._connect() as con:
            row = con.execute(
                """
                select * from asset_versions
                where lower(version_uid) = ?
                   or lower(logical_uid) = ?
                   or lower(json_extract(metadata_json, '$.legacy_id')) = ?
                   or lower(title) = ?
                order by updated_at desc limit 1
                """,
                (needle, needle, needle, needle),
            ).fetchone()
            if row:
                return self._asset_version_from_row(row)
        raise AIAssetsError(f"Asset item not found: {item_id_or_name}")

    def search(self, query: str = "", **facets: Any) -> list[dict[str, Any]]:
        self.initialize()
        q = _clean(query)
        limit = int(facets.get("limit", 50) or 50)
        with self._connect() as con:
            if q:
                try:
                    rows = con.execute(
                        """
                        select av.* from ai_assets_fts f
                        join asset_versions av on av.version_uid = f.version_uid
                        where ai_assets_fts match ?
                        order by rank limit ?
                        """,
                        (fts_query(q), limit),
                    ).fetchall()
                except sqlite3.Error:
                    like = f"%{q.lower()}%"
                    rows = con.execute(
                        """
                        select * from asset_versions
                        where lower(title) like ? or lower(description) like ? or lower(tags_json) like ?
                        order by updated_at desc limit ?
                        """,
                        (like, like, like, limit),
                    ).fetchall()
            else:
                rows = con.execute("select * from asset_versions order by updated_at desc limit ?", (limit,)).fetchall()
        results = [self._asset_version_from_row(row) for row in rows]
        if facets.get("kind"):
            results = [item for item in results if item.get("kind") == facets["kind"]]
        if facets.get("status"):
            results = [item for item in results if item.get("status") == facets["status"]]
        return results

    def validate_asset_version(self, version_uid: str) -> dict[str, Any]:
        asset = self.get_asset_version(version_uid)
        if not asset:
            raise AIAssetsError(f"Asset version not found: {version_uid}")
        errors: list[str] = []
        warnings: list[str] = []
        for field in ("version_uid", "logical_uid", "kind", "title", "version", "catalog_path", "import_policy"):
            if not asset.get(field):
                errors.append(f"Missing {field}.")
        if not asset.get("license_spdx") or asset.get("license_spdx") == DEFAULT_LICENSE:
            errors.append("License SPDX ID is incomplete.")
        if not asset.get("description"):
            warnings.append("Description is empty.")
        content_path = Path(asset.get("content_path", ""))
        if not asset.get("content_path") or not content_path.exists():
            errors.append("Content payload is missing.")
        preview_path = Path(asset.get("preview_path", ""))
        if asset.get("status") in {"approved", "published"} and (not asset.get("preview_path") or not preview_path.exists()):
            errors.append("Approved or published assets require a preview.")
        elif not asset.get("preview_path"):
            warnings.append("Preview is missing.")
        missing_dependencies = self._missing_dependencies(version_uid)
        if missing_dependencies:
            errors.append("One or more dependencies are missing.")
        state = "failed" if errors else ("incomplete" if warnings else "passed")
        qa = {"validation_state": state, "errors": errors, "warnings": warnings, "validated_at": now_iso()}
        asset["qa"] = qa
        asset["integrity"] = {**_json_obj(asset.get("integrity")), "missing_dependencies": missing_dependencies}
        with self._connect() as con:
            con.execute(
                "insert into qa_results(qa_id, version_uid, state, checks_json, created_at) values(?, ?, ?, ?, ?)",
                (f"qa:{uuid.uuid4().hex}", version_uid, state, _dumps(qa), now_iso()),
            )
            self._record_health(con, "error" if errors else "info", "validation", f"Asset validation {state}: {asset.get('title', version_uid)}", qa)
        self.upsert_asset_version(**asset)
        return qa

    def generate_preview_placeholder(self, version_uid: str) -> dict[str, Any]:
        asset = self.get_asset_version(version_uid)
        if not asset:
            raise AIAssetsError(f"Asset version not found: {version_uid}")
        self.previews_dir.mkdir(parents=True, exist_ok=True)
        preview_path = self.previews_dir / f"{slugify(version_uid)}.png"
        if not preview_path.exists():
            preview_path.write_bytes(PLACEHOLDER_PREVIEW_PNG)
        asset["preview_path"] = str(preview_path)
        asset["preview_sha256"] = sha256_file(preview_path)
        asset["integrity"] = {**_json_obj(asset.get("integrity")), "preview_sha256": asset["preview_sha256"]}
        asset["qa"] = {**_json_obj(asset.get("qa")), "preview_generated": True, "preview_kind": "placeholder", "preview_generated_at": now_iso()}
        updated = self.upsert_asset_version(**asset)
        with self._connect() as con:
            self._record_health(
                con,
                "warning",
                "preview",
                f"Generated placeholder preview for {asset.get('title', version_uid)}.",
                {"version_uid": version_uid, "preview_path": str(preview_path)},
            )
        return updated

    def create_output_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        self.initialize()
        output_id = _clean(kwargs.get("output_id")) or f"out:{uuid.uuid4().hex[:16]}"
        now = now_iso()
        record = {
            "output_id": output_id,
            "project_id": _clean(kwargs.get("project_id")),
            "thread_id": _clean(kwargs.get("thread_id")),
            "action_id": _clean(kwargs.get("action_id")),
            "title": _clean(kwargs.get("title") or "Output Snapshot"),
            "summary": _clean(kwargs.get("summary")),
            "kind": _clean(kwargs.get("kind") or "result"),
            "path": _clean(kwargs.get("path")),
            "status": _clean(kwargs.get("status") or "draft"),
            "metadata_json": _dumps(_json_obj(kwargs.get("metadata"))),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as con:
            con.execute(
                """
                insert into output_snapshots(output_id, project_id, thread_id, action_id, title, summary, kind, path, status, metadata_json, created_at, updated_at)
                values(:output_id, :project_id, :thread_id, :action_id, :title, :summary, :kind, :path, :status, :metadata_json, :created_at, :updated_at)
                on conflict(output_id) do update set
                    project_id=excluded.project_id, thread_id=excluded.thread_id, action_id=excluded.action_id,
                    title=excluded.title, summary=excluded.summary, kind=excluded.kind, path=excluded.path,
                    status=excluded.status, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                record,
            )
        return {**record, "metadata": _loads(record["metadata_json"])}

    def promote_output_snapshot(self, output_id: str, **metadata: Any) -> dict[str, Any]:
        self.initialize()
        with self._connect() as con:
            row = con.execute("select * from output_snapshots where output_id = ?", (output_id,)).fetchone()
            if row is None:
                raise AIAssetsError(f"Output snapshot not found: {output_id}")
            output = _row(row)
        title = metadata.get("title") or output.get("title") or "Promoted Output"
        asset = self.upsert_asset_version(
            logical_uid=metadata.get("logical_uid") or f"asset:{slugify(title)}",
            version_uid=metadata.get("version_uid"),
            kind=metadata.get("kind") or output.get("kind") or "other",
            title=title,
            description=metadata.get("description") or output.get("summary") or "",
            content_path=metadata.get("content_path") or output.get("path") or "",
            status=metadata.get("status") or "draft",
            tags=metadata.get("tags") or [],
            metadata={"promoted_from_output": output_id, **_json_obj(metadata.get("metadata"))},
            provenance={
                "output_id": output_id,
                "project_id": output.get("project_id", ""),
                "thread_id": output.get("thread_id", ""),
                "action_card_id": output.get("action_id", ""),
                "wasGeneratedBy": output.get("action_id", ""),
                "generated_at": output.get("created_at", ""),
            },
        )
        with self._connect() as con:
            con.execute("update output_snapshots set status = ?, updated_at = ? where output_id = ?", ("promoted", now_iso(), output_id))
        return asset

    def pin_target(
        self,
        *,
        target_type: str,
        target_uid: str,
        scope: str = "project",
        reason: str = "",
        rank: int = 0,
        freeze: bool = False,
        project_id: str = "",
        thread_id: str = "",
    ) -> dict[str, Any]:
        self.initialize()
        pin_id = f"pin:{uuid.uuid4().hex[:16]}"
        now = now_iso()
        record = {
            "pin_id": pin_id,
            "target_type": target_type,
            "target_uid": target_uid,
            "scope": scope,
            "reason": reason,
            "rank": int(rank),
            "freeze": 1 if freeze else 0,
            "project_id": project_id,
            "thread_id": thread_id,
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as con:
            con.execute(
                """
                insert into pins(pin_id, target_type, target_uid, scope, reason, rank, freeze, project_id, thread_id, created_at, updated_at)
                values(:pin_id, :target_type, :target_uid, :scope, :reason, :rank, :freeze, :project_id, :thread_id, :created_at, :updated_at)
                """,
                record,
            )
        return {**record, "freeze": bool(record["freeze"])}

    def list_pins(self, target_type: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        clauses = []
        params: list[Any] = []
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f" where {' and '.join(clauses)}" if clauses else ""
        with self._connect() as con:
            rows = con.execute(f"select * from pins{where} order by rank desc, updated_at desc", params).fetchall()
            return [{**_row(row), "freeze": bool(_row(row).get("freeze"))} for row in rows]

    def upsert_toolbox_entry(self, **kwargs: Any) -> dict[str, Any]:
        self.initialize()
        item_id = _clean(kwargs.get("item_id") or kwargs.get("id")) or f"toolbox:{slugify(kwargs.get('name') or 'item')}-{uuid.uuid4().hex[:8]}"
        now = now_iso()
        content = kwargs.get("content")
        record = {
            "item_id": item_id,
            "name": _clean(kwargs.get("name") or "Toolbox Item"),
            "category": _clean(kwargs.get("category") or "system"),
            "description": _clean(kwargs.get("description")),
            "content_json": _dumps(content),
            "tags_json": _dumps(normalize_tags(kwargs.get("tags"))),
            "runnable": 1 if _recipe_runnable(content) else 0,
            "required_context_json": _dumps(kwargs.get("required_context") or []),
            "output_type": _clean(kwargs.get("output_type")),
            "approval_required": 1 if kwargs.get("approval_required", True) else 0,
            "created_at": _clean(kwargs.get("created_at")) or now,
            "updated_at": now,
        }
        with self._connect() as con:
            con.execute(
                """
                insert into toolbox_entries(item_id, name, category, description, content_json, tags_json, runnable, required_context_json, output_type, approval_required, created_at, updated_at)
                values(:item_id, :name, :category, :description, :content_json, :tags_json, :runnable, :required_context_json, :output_type, :approval_required, :created_at, :updated_at)
                on conflict(item_id) do update set
                    name=excluded.name, category=excluded.category, description=excluded.description,
                    content_json=excluded.content_json, tags_json=excluded.tags_json, runnable=excluded.runnable,
                    required_context_json=excluded.required_context_json, output_type=excluded.output_type,
                    approval_required=excluded.approval_required, updated_at=excluded.updated_at
                """,
                record,
            )
            self._upsert_fts(con, item_id, record["name"], record["description"], "toolbox", normalize_tags(kwargs.get("tags")), {}, {"content": content})
        return self.get_toolbox_entry(item_id) or {}

    def list_toolbox_entries(self, category: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as con:
            if category:
                rows = con.execute("select * from toolbox_entries where category = ? order by updated_at desc", (category,)).fetchall()
            else:
                rows = con.execute("select * from toolbox_entries order by updated_at desc").fetchall()
            return [self._toolbox_from_row(row) for row in rows]

    def get_toolbox_entry(self, item_id_or_name: str) -> dict[str, Any] | None:
        needle = _clean(item_id_or_name).lower()
        self.initialize()
        with self._connect() as con:
            row = con.execute("select * from toolbox_entries where lower(item_id) = ? or lower(name) = ? limit 1", (needle, needle)).fetchone()
            return self._toolbox_from_row(row) if row else None

    def delete_toolbox_entry(self, item_id_or_name: str) -> dict[str, Any]:
        entry = self.get_toolbox_entry(item_id_or_name)
        if not entry:
            raise AIAssetsError(f"Toolbox item not found: {item_id_or_name}")
        with self._connect() as con:
            con.execute("delete from toolbox_entries where item_id = ?", (entry["item_id"],))
            con.execute("delete from ai_assets_fts where version_uid = ?", (entry["item_id"],))
        return entry

    def delete_asset_version(self, item_id_or_name: str, *, delete_payload: bool = True) -> dict[str, Any]:
        asset = self.get_asset_by_legacy_id_or_name(item_id_or_name)
        with self._connect() as con:
            con.execute("update asset_versions set status = ?, updated_at = ? where version_uid = ?", ("archived", now_iso(), asset["version_uid"]))
        path = Path(asset.get("content_path", ""))
        if delete_payload and path.exists() and _is_relative_to(path, self.legacy_root / "blender_asset_library"):
            path.unlink()
        return asset

    def publish_package(self, version_uid: str, package_dir: Path | None = None) -> dict[str, Any]:
        asset = self.get_asset_version(version_uid)
        if not asset:
            raise AIAssetsError(f"Asset version not found: {version_uid}")
        if not asset.get("preview_path") or not Path(asset.get("preview_path", "")).exists():
            asset = self.generate_preview_placeholder(version_uid)
        validation = self.validate_asset_version(version_uid)
        if validation["validation_state"] == "failed":
            raise AIAssetsError("Asset package validation failed: " + "; ".join(validation["errors"]))
        package_uid = f"pkg:{slugify(asset['title'])}@{asset['version']}-{uuid.uuid4().hex[:8]}"
        package_dir = Path(package_dir or self.packages_dir)
        package_dir.mkdir(parents=True, exist_ok=True)
        package_path = package_dir / f"{slugify(package_uid)}.zip"
        manifest = self.package_manifest(asset, package_uid)
        try:
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("ai_assets_manifest.json", _dumps(manifest, indent=2))
                zf.writestr("provenance.json", _dumps(asset.get("provenance", {}), indent=2))
                zf.writestr("CHANGELOG.md", f"# {asset['title']}\n\n- Published {now_iso()} from {version_uid}.\n")
                zf.writestr("LICENSE.txt", asset.get("license_spdx") or DEFAULT_LICENSE)
                zf.writestr("blender_assets.cats.txt", catalog_text_for(asset.get("catalog_uuid", ""), asset.get("catalog_path", "")))
                content_path = Path(asset.get("content_path", ""))
                if content_path.exists():
                    zf.write(content_path, "bundle_file.blend" if content_path.suffix.lower() == ".blend" else f"payload/{content_path.name}")
                preview_path = Path(asset.get("preview_path", ""))
                if preview_path.exists():
                    zf.write(preview_path, f"previews/{preview_path.name}")
        except Exception as exc:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            failed = self.quarantine_dir / package_path.name
            if package_path.exists():
                shutil.move(str(package_path), failed)
            with self._connect() as con:
                self._record_health(con, "error", "package", f"Package publish failed: {asset['title']}", {"error": str(exc), "quarantine": str(failed)})
            raise
        manifest["package_path"] = str(package_path)
        with self._connect() as con:
            con.execute(
                "insert into package_manifests(package_uid, version_uid, path, status, manifest_json, created_at) values(?, ?, ?, ?, ?, ?)",
                (package_uid, version_uid, str(package_path), "published", _dumps(manifest), now_iso()),
            )
            con.execute("update asset_versions set status = ?, updated_at = ? where version_uid = ?", ("published", now_iso(), version_uid))
            self._record_health(con, "info", "package", f"Published package for {asset['title']}.", {"package": str(package_path)})
        return manifest

    def import_package(self, package_path: Path, library_id: str = "published") -> dict[str, Any]:
        self.initialize()
        package_path = Path(package_path)
        if not package_path.exists():
            raise AIAssetsError(f"Package does not exist: {package_path}")
        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                manifest = json.loads(zf.read("ai_assets_manifest.json").decode("utf-8"))
                package_uid = manifest.get("package_uid") or f"pkg:{uuid.uuid4().hex[:16]}"
                target_dir = self.packages_dir / "imported" / slugify(package_uid)
                target_dir.mkdir(parents=True, exist_ok=True)
                zf.extractall(target_dir)
        except Exception as exc:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = self.quarantine_dir / package_path.name
            shutil.copy2(package_path, target)
            with self._connect() as con:
                self._record_health(con, "error", "package", "Package import failed.", {"package": str(package_path), "error": str(exc), "quarantine": str(target)})
            raise AIAssetsError(f"Package import failed: {exc}") from exc
        payload = target_dir / "bundle_file.blend"
        asset = manifest.get("asset", {})
        asset["content_path"] = str(payload if payload.exists() else target_dir)
        blender = _json_obj(asset.get("blender"))
        blender["library_id"] = library_id
        asset["blender"] = blender
        asset["status"] = "imported"
        imported = self.upsert_asset_version(**asset)
        with self._connect() as con:
            con.execute(
                """
                insert into package_manifests(package_uid, version_uid, path, status, manifest_json, created_at)
                values(?, ?, ?, ?, ?, ?)
                on conflict(package_uid) do update set
                    version_uid=excluded.version_uid,
                    path=excluded.path,
                    status=excluded.status,
                    manifest_json=excluded.manifest_json
                """,
                (package_uid, imported["version_uid"], str(package_path), "imported", _dumps(manifest), now_iso()),
            )
            self._record_health(con, "info", "package", f"Imported package {package_uid}.", {"package": str(package_path), "target": str(target_dir)})
        return {"package_uid": package_uid, "asset": imported, "extract_dir": str(target_dir)}

    def package_manifest(self, asset: dict[str, Any], package_uid: str) -> dict[str, Any]:
        return {
            "schema": "codex-ai-assets-package-v1",
            "package_uid": package_uid,
            "created_at": now_iso(),
            "addon_version": ADDON_VERSION,
            "asset": asset,
            "hashes": {
                "content_sha256": asset.get("content_sha256", ""),
                "preview_sha256": asset.get("integrity", {}).get("preview_sha256", ""),
            },
        }

    def diagnose(self) -> dict[str, Any]:
        self._ensure_dirs()
        result: dict[str, Any] = {
            "storage_root": str(self.root),
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "schema_version": "",
            "wal_enabled": False,
            "fts5_available": False,
            "asset_versions": 0,
            "libraries": 0,
            "catalog_entries": 0,
            "toolbox_entries": 0,
            "pins": 0,
            "missing_previews": 0,
            "missing_payloads": 0,
            "health_events": [],
        }
        if not self.db_path.exists():
            return result
        with self._connect() as con:
            result["schema_version"] = self._get_meta(con, "schema_version") or ""
            result["wal_enabled"] = str(con.execute("pragma journal_mode").fetchone()[0]).lower() == "wal"
            try:
                con.execute("create virtual table if not exists _fts_probe using fts5(value)")
                result["fts5_available"] = True
            except sqlite3.Error:
                result["fts5_available"] = False
            for key, table in (
                ("asset_versions", "asset_versions"),
                ("libraries", "asset_libraries"),
                ("catalog_entries", "catalog_entries"),
                ("toolbox_entries", "toolbox_entries"),
                ("pins", "pins"),
            ):
                result[key] = con.execute(f"select count(*) from {table}").fetchone()[0]
            rows = con.execute("select content_path, preview_path, status from asset_versions").fetchall()
            for row in rows:
                item = _row(row)
                if item.get("content_path") and not Path(item["content_path"]).exists():
                    result["missing_payloads"] += 1
                if item.get("status") in {"approved", "published"} and (not item.get("preview_path") or not Path(item["preview_path"]).exists()):
                    result["missing_previews"] += 1
            health = con.execute("select * from health_events order by created_at desc limit 20").fetchall()
            result["health_events"] = [_row(row) for row in health]
        return result

    def export_legacy_assets(self, path: Path | None = None) -> Path:
        self.initialize()
        path = Path(path or (self.manifests_dir / "asset_library_export.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        items = [asset_version_to_legacy_item(item) for item in self.list_asset_versions(limit=1000)]
        path.write_text(_dumps({"items": items}, indent=2), encoding="utf-8")
        return path

    def _migrate_asset_json(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            with self._connect() as con:
                self._record_health(con, "error", "migration", "Could not parse legacy asset_library.json.", {"path": str(path)})
            return 0
        count = 0
        raw_items = data.get("items")
        if raw_items is None:
            raw_items = data.get("assets", [])
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            legacy_id = _clean(item.get("id")) or f"legacy-{uuid.uuid4().hex[:8]}"
            self.upsert_asset_version(
                logical_uid=f"asset:{slugify(legacy_id)}",
                version_uid=f"assetver:{slugify(legacy_id)}@1.0.0",
                kind=item.get("category") or item.get("kind") or "other",
                title=item.get("name") or legacy_id,
                status="draft",
                version="1.0.0",
                content_path=item.get("stored_path") or item.get("source_path") or "",
                description=item.get("description", ""),
                tags=item.get("tags", []),
                metadata={
                    **_json_obj(item.get("metadata")),
                    "legacy_id": legacy_id,
                    "legacy_kind": item.get("kind", ""),
                    "legacy_record": item,
                },
                blender={
                    "library_id": "scratch",
                    "catalog_path": default_catalog_for_kind(item.get("category") or item.get("kind") or "other"),
                    "blend_relpath": _clean(item.get("stored_path")),
                    "import_policy": "append",
                },
                provenance={"wasDerivedFrom": item.get("source_path", ""), "migrated_from": str(path), "generated_at": item.get("created_at", "")},
                qa={"validation_state": "unchecked", "migration": "legacy_json"},
            )
            count += 1
        return count

    def _migrate_toolbox_json(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            with self._connect() as con:
                self._record_health(con, "error", "migration", "Could not parse legacy toolbox.json.", {"path": str(path)})
            return 0
        count = 0
        for item in data.get("items", []):
            if isinstance(item, dict):
                self.upsert_toolbox_entry(
                    item_id=item.get("id"),
                    name=item.get("name"),
                    category=item.get("category"),
                    description=item.get("description"),
                    content=item.get("content"),
                    tags=item.get("tags"),
                    created_at=item.get("created_at"),
                )
                count += 1
        return count

    def _migrate_dashboard_json(self, path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            with self._connect() as con:
                self._record_health(con, "error", "migration", "Could not parse legacy dashboard.json.", {"path": str(path)})
            return 0, 0
        pins = 0
        for output in data.get("pinned_outputs", []):
            if not isinstance(output, dict):
                continue
            snapshot = self.create_output_snapshot(
                output_id=output.get("output_id"),
                project_id=output.get("project_id", ""),
                thread_id=output.get("source_thread_id", ""),
                action_id=output.get("action_id", ""),
                title=output.get("title", ""),
                summary=output.get("summary", ""),
                kind=output.get("kind", "result"),
                path=output.get("path", ""),
                status="pinned",
            )
            self.pin_target(target_type="output_snapshot", target_uid=snapshot["output_id"], scope="project", reason=output.get("summary", ""), project_id=output.get("project_id", ""), thread_id=output.get("source_thread_id", ""))
            pins += 1
        actions = 0
        for action in data.get("actions", []):
            if not isinstance(action, dict) or not action.get("action_id"):
                continue
            now = now_iso()
            with self._connect() as con:
                con.execute(
                    """
                    insert into action_card_lineage(action_id, project_id, thread_id, operation_type, inputs_json, outputs_json, tool_refs_json, remote_session_refs_json, status, errors_json, provenance_activity_id, created_at, updated_at)
                    values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(action_id) do nothing
                    """,
                    (
                        action.get("action_id"),
                        action.get("project_id", ""),
                        action.get("thread_id", ""),
                        action.get("kind", "action"),
                        _dumps(action),
                        _dumps({}),
                        _dumps([action.get("tool_name", "")] if action.get("tool_name") else []),
                        _dumps([]),
                        action.get("status", ""),
                        _dumps([]),
                        f"activity:{action.get('action_id')}",
                        action.get("created_at") or now,
                        action.get("updated_at") or now,
                    ),
                )
            actions += 1
        return pins, actions

    def _upsert_fts(
        self,
        con: sqlite3.Connection,
        version_uid: str,
        title: str,
        description: str,
        kind: str,
        tags: list[str],
        provenance: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        con.execute("delete from ai_assets_fts where version_uid = ?", (version_uid,))
        body = " ".join([description, _dumps(provenance), _dumps(metadata)])
        con.execute(
            "insert into ai_assets_fts(title, body, kind, tags, version_uid) values(?, ?, ?, ?, ?)",
            (title, body, kind, " ".join(tags), version_uid),
        )

    def _upsert_artifact_ref(self, con: sqlite3.Connection, version_uid: str, blender: dict[str, Any], content_path: str, catalog_uuid: str) -> None:
        datablock_name = _clean(blender.get("datablock_name") or blender.get("name"))
        if not datablock_name:
            return
        ref_id = f"ref:{version_uid}:{slugify(datablock_name)}"
        con.execute(
            """
            insert into blender_artifact_refs(ref_id, version_uid, id_type, datablock_name, blend_relpath, library_id, catalog_uuid, custom_props_json)
            values(?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(ref_id) do update set
                id_type=excluded.id_type, datablock_name=excluded.datablock_name,
                blend_relpath=excluded.blend_relpath, library_id=excluded.library_id,
                catalog_uuid=excluded.catalog_uuid, custom_props_json=excluded.custom_props_json
            """,
            (
                ref_id,
                version_uid,
                _clean(blender.get("id_type") or "OBJECT"),
                datablock_name,
                _clean(blender.get("blend_relpath") or content_path),
                _clean(blender.get("library_id") or "scratch"),
                catalog_uuid,
                _dumps(blender.get("custom_properties") or {}),
            ),
        )

    def _upsert_dependencies(self, con: sqlite3.Connection, version_uid: str, dependencies: list[Any]) -> None:
        con.execute("delete from dependency_edges where version_uid = ?", (version_uid,))
        for dependency in dependencies:
            if isinstance(dependency, str):
                dep = {"depends_on_uid": dependency, "dependency_kind": "asset", "status": "unknown"}
            elif isinstance(dependency, dict):
                dep = dependency
            else:
                continue
            depends_on = _clean(dep.get("depends_on_uid") or dep.get("uid") or dep.get("path"))
            if not depends_on:
                continue
            edge_id = f"dep:{version_uid}:{slugify(depends_on)}"
            con.execute(
                "insert into dependency_edges(edge_id, version_uid, depends_on_uid, dependency_kind, status, detail_json) values(?, ?, ?, ?, ?, ?)",
                (edge_id, version_uid, depends_on, _clean(dep.get("dependency_kind") or "asset"), _clean(dep.get("status") or "unknown"), _dumps(dep)),
            )

    def _upsert_provenance(self, con: sqlite3.Connection, version_uid: str, provenance: dict[str, Any]) -> None:
        if not provenance:
            return
        activity_id = _clean(provenance.get("action_card_id") or provenance.get("activity_id") or provenance.get("wasGeneratedBy")) or f"activity:{version_uid}"
        con.execute(
            """
            insert into provenance_records(provenance_id, version_uid, activity_id, entity_json, relations_json, created_at)
            values(?, ?, ?, ?, ?, ?)
            on conflict(provenance_id) do update set entity_json=excluded.entity_json, relations_json=excluded.relations_json
            """,
            (f"prov:{version_uid}", version_uid, activity_id, _dumps({"version_uid": version_uid}), _dumps(provenance), now_iso()),
        )

    def _missing_dependencies(self, version_uid: str) -> list[str]:
        with self._connect() as con:
            rows = con.execute("select depends_on_uid from dependency_edges where version_uid = ? and status in ('missing', 'unknown')", (version_uid,)).fetchall()
            return [row[0] for row in rows]

    def _asset_version_from_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        item = _row(row)
        for key in ("tags_json", "blender_json", "compatibility_json", "integrity_json", "metadata_json", "provenance_json", "qa_json"):
            target = key[:-5] if key.endswith("_json") else key
            item[target] = _loads(item.pop(key, ""))
        return item

    def _toolbox_from_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        item = _row(row)
        item["id"] = item.get("item_id", "")
        item["content"] = _loads(item.pop("content_json", ""))
        item["tags"] = _loads(item.pop("tags_json", ""))
        item["required_context"] = _loads(item.pop("required_context_json", ""))
        item["runnable"] = bool(item.get("runnable"))
        item["approval_required"] = bool(item.get("approval_required"))
        return item


def parse_catalog_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.upper().startswith("VERSION"):
            continue
        parts = line.split(":")
        if len(parts) < 3:
            entries.append({"catalog_uuid": f"malformed:{uuid.uuid4().hex[:8]}", "path": line, "simple_name": "", "status": "malformed"})
            continue
        catalog_uuid, catalog_path, simple_name = parts[0], ":".join(parts[1:-1]), parts[-1]
        status = "uncataloged" if catalog_uuid == "00000000-0000-0000-0000-000000000000" else "active"
        entries.append({"catalog_uuid": catalog_uuid, "path": catalog_path, "simple_name": simple_name, "status": status})
    return entries


def write_default_catalog_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["VERSION 1"]
    for catalog_path in DEFAULT_CATALOG_PATHS:
        lines.append(f"{stable_uuid(catalog_path)}:{catalog_path}:{catalog_path.rsplit('/', 1)[-1]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def catalog_text_for(catalog_uuid: str, catalog_path: str) -> str:
    path = catalog_path or "outputs/published"
    simple = path.rsplit("/", 1)[-1]
    return f"VERSION 1\n{catalog_uuid or stable_uuid(path)}:{path}:{simple}\n"


def asset_version_to_legacy_item(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    legacy_kind = metadata.get("legacy_kind") or asset.get("kind", "other")
    return {
        "id": metadata.get("legacy_id") or asset.get("version_uid", ""),
        "version_uid": asset.get("version_uid", ""),
        "logical_uid": asset.get("logical_uid", ""),
        "name": asset.get("title", ""),
        "category": asset.get("kind", "other"),
        "kind": legacy_kind,
        "status": asset.get("status", ""),
        "version": asset.get("version", ""),
        "license_spdx": asset.get("license_spdx", ""),
        "catalog_path": asset.get("catalog_path", ""),
        "import_policy": asset.get("import_policy", ""),
        "dependency_health": "missing" if asset.get("integrity", {}).get("missing_dependencies") else "ok",
        "validation_state": asset.get("qa", {}).get("validation_state", ""),
        "provenance_summary": provenance_summary(asset.get("provenance", {})),
        "preview_path": asset.get("preview_path", ""),
        "description": asset.get("description", ""),
        "source_path": asset.get("content_path", ""),
        "stored_path": asset.get("content_path", ""),
        "is_library_copy": bool(metadata.get("is_library_copy", False)),
        "is_generated": bool(metadata.get("is_generated", True)),
        "tags": asset.get("tags", []),
        "metadata": metadata,
        "created_at": asset.get("created_at", ""),
        "updated_at": asset.get("updated_at", ""),
    }


def provenance_summary(provenance: dict[str, Any]) -> str:
    if not provenance:
        return "No provenance recorded."
    action = provenance.get("action_card_id") or provenance.get("wasGeneratedBy") or ""
    project = provenance.get("project_id") or ""
    thread = provenance.get("thread_id") or ""
    parts = []
    if action:
        parts.append(f"generated by {action}")
    if project:
        parts.append(f"project {project}")
    if thread:
        parts.append(f"thread {thread}")
    return ", ".join(parts) or "Provenance recorded."


def default_catalog_for_kind(kind: str) -> str:
    normalized = (kind or "").lower()
    if "material" in normalized:
        return "materials/procedural"
    if "rig" in normalized or "armature" in normalized:
        return "rigs/props"
    if "pose" in normalized:
        return "poses/body"
    if "node" in normalized:
        return "node_systems/geometry/utilities"
    if "recipe" in normalized or "workflow" in normalized:
        return "recipes/pipeline"
    if "prompt" in normalized:
        return "prompts/modeling"
    return "models/props"


def default_import_policy(kind: str) -> str:
    normalized = (kind or "").lower()
    if "rig" in normalized or "kit" in normalized:
        return "link_override"
    return "append"


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"codex-blender-agent:{value}"))


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    if tags is None:
        return []
    raw = re.split(r"[,#]", tags) if isinstance(tags, str) else tags
    return sorted({str(tag).strip().lower() for tag in raw if str(tag).strip()})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"[^a-z0-9_.@-]+", "-", text).strip("-")[:96] or "item"


def fts_query(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9_@.-]+", value)
    return " OR ".join(words) if words else value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _dumps(value: Any, indent: int | None = None) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True, sort_keys=True, indent=indent)


def _loads(value: Any) -> Any:
    if value in ("", None):
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}


def _json_obj(value: Any) -> dict[str, Any]:
    loaded = _loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _row(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _recipe_runnable(content: Any) -> bool:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return False
    steps = content.get("steps") if isinstance(content, dict) else content
    return isinstance(steps, list) and bool(steps)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False
