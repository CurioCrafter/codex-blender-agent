from __future__ import annotations

import json
import sqlite3
import zipfile

from codex_blender_agent.ai_assets_store import AIAssetsStore, parse_catalog_file, write_default_catalog_file


def test_ai_assets_store_initializes_wal_schema_and_default_libraries(tmp_path):
    store = AIAssetsStore(tmp_path / "authority", legacy_root=tmp_path / "legacy")

    diagnostic = store.initialize()
    libraries = store.ensure_default_libraries(tmp_path / "libraries")

    assert diagnostic["schema_version"] == "1"
    assert diagnostic["wal_enabled"] is True
    assert (tmp_path / "authority" / "ai_assets.db").exists()
    assert {library["library_id"] for library in libraries} == {"core", "project", "scratch", "published"}

    with sqlite3.connect(tmp_path / "authority" / "ai_assets.db") as con:
        tables = {row[0] for row in con.execute("select name from sqlite_master where type in ('table', 'virtual table')")}
    assert "asset_versions" in tables
    assert "ai_assets_fts" in tables


def test_ai_assets_store_migrates_legacy_json_with_backups_and_fts(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    payload = legacy / "legacy.blend"
    payload.write_text("fake blend", encoding="utf-8")
    (legacy / "asset_library.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "legacy-castle",
                        "name": "Legacy Castle",
                        "category": "model",
                        "kind": "blend_bundle",
                        "stored_path": str(payload),
                        "description": "Stone castle blockout",
                        "tags": ["castle", "blockout"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (legacy / "toolbox.json").write_text(
        json.dumps({"items": [{"id": "recipe-castle", "name": "Castle Recipe", "category": "generate", "content": {"steps": []}}]}),
        encoding="utf-8",
    )
    store = AIAssetsStore(tmp_path / "authority", legacy_root=legacy)

    result = store.migrate_legacy()
    matches = store.search("castle")
    recipes = store.list_toolbox_entries()

    assert result["assets"] == 1
    assert result["toolbox"] == 1
    assert result["backups"]
    assert matches[0]["title"] == "Legacy Castle"
    assert matches[0]["metadata"]["legacy_kind"] == "blend_bundle"
    assert recipes[0]["name"] == "Castle Recipe"


def test_ai_assets_catalog_parser_and_writer(tmp_path):
    catalog = tmp_path / "blender_assets.cats.txt"

    write_default_catalog_file(catalog)
    entries = parse_catalog_file(catalog)

    assert entries
    assert any(entry["path"] == "models/props" for entry in entries)
    assert all(entry["catalog_uuid"] for entry in entries)


def test_ai_assets_validation_package_publish_and_import(tmp_path):
    payload = tmp_path / "asset.blend"
    preview = tmp_path / "asset.png"
    payload.write_text("fake blend", encoding="utf-8")
    preview.write_text("fake png", encoding="utf-8")
    store = AIAssetsStore(tmp_path / "authority", legacy_root=tmp_path / "legacy")
    asset = store.upsert_asset_version(
        logical_uid="asset:test_castle",
        version_uid="assetver:test_castle@1.0.0",
        kind="model",
        title="Test Castle",
        status="approved",
        version="1.0.0",
        content_path=str(payload),
        preview_path=str(preview),
        description="Reusable castle blockout.",
        license_spdx="CC-BY-4.0",
        tags=["castle"],
        provenance={"project_id": "proj:test", "action_card_id": "act:test"},
    )

    generated_preview = store.generate_preview_placeholder(asset["version_uid"])
    validation = store.validate_asset_version(asset["version_uid"])
    manifest = store.publish_package(asset["version_uid"], tmp_path / "packages")
    package_path = tmp_path / "packages" / "missing.zip"
    if manifest.get("package_path"):
        package_path = tmp_path / "packages" / manifest["package_path"].split("\\")[-1].split("/")[-1]
    if not package_path.exists():
        package_path = next((tmp_path / "packages").glob("*.zip"))
    imported = store.import_package(package_path)

    assert generated_preview["preview_path"]
    assert (tmp_path / "authority" / "previews").exists()
    assert validation["validation_state"] in {"incomplete", "passed"}
    assert package_path.exists()
    with zipfile.ZipFile(package_path, "r") as zf:
        assert "ai_assets_manifest.json" in zf.namelist()
        assert "blender_assets.cats.txt" in zf.namelist()
    assert imported["asset"]["status"] == "imported"
    assert imported["asset"]["version_uid"] == asset["version_uid"]
