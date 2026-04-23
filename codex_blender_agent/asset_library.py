from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy

from .ai_assets_store import AI_ASSET_LIBRARY_DEFS, AIAssetsStore, parse_catalog_file, write_default_catalog_file


ASSET_LIBRARY_NAME = "Codex Blender Agent"


def asset_library_root(config_root: Path) -> Path:
    return Path(config_root) / "blender_asset_library"


def ai_assets_root(config_root: Path) -> Path:
    return Path(config_root) / "ai_assets"


def ai_asset_libraries_root(config_root: Path) -> Path:
    return asset_library_root(config_root) / "libraries"


def register_asset_library(config_root: Path, name: str = ASSET_LIBRARY_NAME) -> dict[str, Any]:
    path = asset_library_root(config_root)
    path.mkdir(parents=True, exist_ok=True)
    libraries = getattr(bpy.context.preferences.filepaths, "asset_libraries", None)
    if libraries is None:
        return {"registered": False, "name": name, "path": str(path), "reason": "asset_libraries API unavailable"}

    for library in libraries:
        if library.name == name:
            library.path = str(path)
            return {"registered": True, "name": library.name, "path": library.path}

    try:
        library = libraries.new(name=name, directory=str(path))
    except TypeError:
        library = libraries.new(name, str(path))
    return {"registered": True, "name": library.name, "path": library.path}


def register_ai_asset_libraries(config_root: Path) -> dict[str, Any]:
    """Register AI-owned Blender asset libraries and mirror them into SQLite."""
    root = ai_asset_libraries_root(config_root)
    store = AIAssetsStore(ai_assets_root(config_root), legacy_root=Path(config_root))
    authority_rows = store.ensure_default_libraries(root)
    results = []
    libraries = getattr(bpy.context.preferences.filepaths, "asset_libraries", None)
    if libraries is None:
        return {"registered": False, "reason": "asset_libraries API unavailable", "libraries": authority_rows}
    for library_id, name, scope in AI_ASSET_LIBRARY_DEFS:
        path = root / scope
        write_default_catalog_file(path / "blender_assets.cats.txt")
        found = None
        for library in libraries:
            if library.name == name:
                found = library
                break
        if found is not None:
            found.path = str(path)
            results.append({"registered": True, "library_id": library_id, "name": found.name, "path": found.path})
            continue
        try:
            library = libraries.new(name=name, directory=str(path))
        except TypeError:
            library = libraries.new(name, str(path))
        results.append({"registered": True, "library_id": library_id, "name": library.name, "path": library.path})
    return {"registered": True, "libraries": results, "authority": authority_rows}


def list_asset_libraries() -> list[dict[str, Any]]:
    libraries = getattr(bpy.context.preferences.filepaths, "asset_libraries", None)
    if libraries is None:
        return []
    return [{"name": library.name, "path": library.path} for library in libraries]


def diagnose_ai_asset_libraries(config_root: Path) -> dict[str, Any]:
    store = AIAssetsStore(ai_assets_root(config_root), legacy_root=Path(config_root))
    diagnostics = store.diagnose()
    blender_libraries = list_asset_libraries()
    configured = store.list_asset_libraries() if diagnostics.get("db_exists") else []
    missing_paths = [item for item in configured if item.get("path") and not Path(item["path"]).exists()]
    malformed_catalogs = []
    for item in configured:
        path = Path(item.get("path", "")) / "blender_assets.cats.txt"
        malformed_catalogs.extend(entry for entry in parse_catalog_file(path) if entry.get("status") == "malformed")
    return {
        "store": diagnostics,
        "blender_libraries": blender_libraries,
        "configured_libraries": configured,
        "missing_library_paths": missing_paths,
        "malformed_catalogs": malformed_catalogs,
    }


def mark_local_ids_as_assets(ids: list[Any]) -> list[str]:
    marked = []
    for datablock in ids:
        if datablock is None or not hasattr(datablock, "asset_mark"):
            continue
        try:
            datablock.asset_mark()
            marked.append(datablock.name)
        except Exception:
            continue
    return marked
