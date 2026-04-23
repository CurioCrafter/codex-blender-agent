from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .ai_assets_store import AIAssetsError, AIAssetsStore, asset_version_to_legacy_item, default_catalog_for_kind


ASSET_CATEGORIES = [
    "model",
    "material",
    "rig",
    "pose",
    "node_system",
    "recipe",
    "prompt",
    "output",
    "image",
    "texture",
    "reference",
    "blend",
    "script",
    "audio",
    "video",
    "cache",
    "other",
]


class AssetStoreError(RuntimeError):
    pass


class AssetStore:
    """Compatibility facade over the v0.8 SQLite AI Assets authority store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "asset_library.json"
        self.assets_dir = self.root / "blender_asset_library" / "assets"
        self.authority = AIAssetsStore(self.root / "ai_assets", legacy_root=self.root)
        self.authority.initialize()
        self.authority.migrate_legacy()

    def list_entries(self, category: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        entries = [asset_version_to_legacy_item(item) for item in self.authority.list_asset_versions(kind=category, limit=1000)]
        if category:
            entries = [entry for entry in entries if entry.get("category") == category]
        if kind:
            entries = [entry for entry in entries if entry.get("kind") == kind]
        return sorted(entries, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_entry(self, item_id_or_name: str) -> dict[str, Any]:
        try:
            return asset_version_to_legacy_item(self.authority.get_asset_by_legacy_id_or_name(item_id_or_name))
        except AIAssetsError as exc:
            raise AssetStoreError(str(exc)) from exc

    def save_file(
        self,
        filepath: str | Path,
        name: str,
        category: str,
        description: str = "",
        tags: list[str] | str | None = None,
        copy_file: bool = True,
        entry_id: str | None = None,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
        is_generated: bool = False,
    ) -> dict[str, Any]:
        source = Path(filepath).expanduser()
        if not source.exists():
            raise AssetStoreError(f"Asset file does not exist: {source}")
        name = _required_name(name, "Asset name")
        category = _normalize_category(category)
        item_id = entry_id or _make_id(name)
        stored_path = source
        if copy_file:
            self.assets_dir.mkdir(parents=True, exist_ok=True)
            stored_path = self.assets_dir / f"{item_id}{source.suffix.lower()}"
            if source.resolve() != stored_path.resolve():
                shutil.copy2(source, stored_path)
        asset_kind = kind or _guess_kind(source)
        record = self.authority.upsert_asset_version(
            logical_uid=f"asset:{_safe_uid(item_id)}",
            version_uid=f"assetver:{_safe_uid(item_id)}@1.0.0",
            kind=category,
            title=name,
            status="draft",
            content_path=str(stored_path),
            description=description,
            tags=tags,
            metadata={
                **(metadata or {}),
                "legacy_id": item_id,
                "source_path": str(source),
                "is_library_copy": bool(copy_file),
                "is_generated": bool(is_generated),
                "legacy_kind": asset_kind,
            },
            blender={
                "library_id": "scratch",
                "catalog_path": default_catalog_for_kind(category),
                "blend_relpath": str(stored_path),
                "import_policy": "append",
            },
        )
        self.authority.export_legacy_assets(self.path)
        return asset_version_to_legacy_item(record)

    def reserve_asset_path(self, name: str, suffix: str, entry_id: str | None = None) -> tuple[str, Path]:
        item_id = entry_id or _make_id(_required_name(name, "Asset name"))
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        return item_id, self.assets_dir / f"{item_id}{normalized_suffix.lower()}"

    def save_generated_asset(
        self,
        filepath: str | Path,
        item_id: str,
        name: str,
        category: str,
        description: str = "",
        tags: list[str] | str | None = None,
        kind: str = "blend_bundle",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.save_file(
            filepath=filepath,
            name=name,
            category=category,
            description=description,
            tags=tags,
            copy_file=False,
            entry_id=item_id,
            kind=kind,
            metadata=metadata,
            is_generated=True,
        )

    def delete_entry(self, item_id_or_name: str) -> dict[str, Any]:
        try:
            asset = self.authority.delete_asset_version(item_id_or_name)
            self.authority.export_legacy_assets(self.path)
            return asset_version_to_legacy_item(asset)
        except AIAssetsError as exc:
            raise AssetStoreError(str(exc)) from exc


def summarize_assets(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No asset-library items stored yet."
    lines = []
    for entry in entries:
        tags = ", ".join(entry.get("tags", []))
        tag_suffix = f" tags=[{tags}]" if tags else ""
        lines.append(
            f"- {entry.get('id')}: {entry.get('name')} ({entry.get('category')}/{entry.get('kind')}) "
            f"path={entry.get('stored_path', '')} - {entry.get('description', '')}{tag_suffix}"
        )
    return "\n".join(lines)


def _normalize_category(category: str) -> str:
    value = (category or "other").strip().lower()
    return value if value in ASSET_CATEGORIES else "other"


def _guess_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".blend":
        return "blend"
    if suffix in {".fbx", ".obj", ".gltf", ".glb", ".stl", ".usd", ".usdz"}:
        return "model_file"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".exr", ".hdr"}:
        return "image_file"
    if suffix in {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml"}:
        return "text_file"
    if suffix in {".wav", ".mp3", ".ogg", ".flac"}:
        return "audio_file"
    if suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video_file"
    return "file"


def _make_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:36] or "asset"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def _safe_uid(value: str) -> str:
    return re.sub(r"[^a-z0-9_.@-]+", "-", value.lower()).strip("-") or "asset"


def _required_name(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AssetStoreError(f"{label} is required.")
    return text
