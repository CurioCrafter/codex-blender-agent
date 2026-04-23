from __future__ import annotations

import json

from codex_blender_agent.asset_store import AssetStore, summarize_assets


def test_asset_store_copies_and_lists_file(tmp_path):
    source = tmp_path / "cube.obj"
    source.write_text("o Cube\n", encoding="utf-8")
    store = AssetStore(tmp_path / "store")

    item = store.save_file(source, name="Cube OBJ", category="model", tags=["blockout"])
    entries = store.list_entries()

    assert entries[0]["id"] == item["id"]
    assert entries[0]["kind"] == "model_file"
    assert entries[0]["tags"] == ["blockout"]
    assert "Cube OBJ" in summarize_assets(entries)


def test_asset_store_can_reference_without_copy(tmp_path):
    source = tmp_path / "ref.png"
    source.write_text("fake", encoding="utf-8")
    store = AssetStore(tmp_path / "store")

    item = store.save_file(source, name="Reference", category="image", copy_file=False)

    assert item["stored_path"] == str(source)
    assert item["is_library_copy"] is False


def test_asset_store_deletes_generated_asset_bundle(tmp_path):
    store = AssetStore(tmp_path / "store")
    item_id, bundle_path = store.reserve_asset_path("Generated Cube", ".blend")
    bundle_path.write_text("fake blend bundle", encoding="utf-8")

    item = store.save_generated_asset(
        filepath=bundle_path,
        item_id=item_id,
        name="Generated Cube",
        category="model",
        kind="blend_bundle",
    )

    assert item["is_generated"] is True
    assert bundle_path.exists()

    store.delete_entry(item_id)

    assert not bundle_path.exists()


def test_asset_store_filters_entries_and_searches_by_name(tmp_path):
    store = AssetStore(tmp_path / "store")

    model_source = tmp_path / "hero.glb"
    model_source.write_text("fake glb", encoding="utf-8")
    material_source = tmp_path / "clay.png"
    material_source.write_text("fake png", encoding="utf-8")

    hero = store.save_file(model_source, name="Hero Asset", category="model", tags=["publish"])
    clay = store.save_file(material_source, name="Clay Swatch", category="material", copy_file=False)

    assert [entry["id"] for entry in store.list_entries(category="model")] == [hero["id"]]
    assert [entry["id"] for entry in store.list_entries(kind="image_file")] == [clay["id"]]
    assert store.get_entry("hero asset")["id"] == hero["id"]


def test_asset_store_migrates_legacy_json_shape_when_saving(tmp_path):
    legacy_path = tmp_path / "store" / "asset_library.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "legacy-cube",
                        "name": "Legacy Cube",
                        "category": "model",
                        "kind": "blend_bundle",
                        "stored_path": "legacy.blend",
                    }
                ]
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    store = AssetStore(tmp_path / "store")
    source = tmp_path / "cube.blend"
    source.write_text("fake blend bundle", encoding="utf-8")

    item = store.save_file(source, name="Modern Cube", category="model", kind="blend_bundle")

    raw = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert "items" in raw
    assert any(entry["id"] == item["id"] for entry in raw["items"])
    assert store.get_entry("modern cube")["id"] == item["id"]
