from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path


SMOKE_STEPS = (
    "load_addon",
    "patch_temp_storage_root",
    "asset_store_init",
    "asset_store_corrupt_json_recovery",
    "register_asset_library",
    "open_assets_workspace",
    "save_selection_package",
    "append_asset_package",
    "workflow_asset_examples",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blender smoke test for Codex Blender Agent AI Assets readiness.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]), help="Repository root containing codex_blender_agent.")
    parser.add_argument("--module", default="codex_blender_agent", help="Addon module name. Use bl_ext.user_default.codex_blender_agent for installed extension mode.")
    parser.add_argument("--zip", dest="zip_path", default="", help="Optional ZIP path to inspect for source-only package contents.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary smoke storage directory.")
    return parser


def _after_blender_separator(argv: list[str]) -> list[str]:
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _enable_addon(module_name: str, repo_root: Path):
    import bpy  # type: ignore

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        result = bpy.ops.preferences.addon_enable(module=module_name)
        if "FINISHED" in result:
            return importlib.import_module(module_name)
    except Exception:
        pass

    module = importlib.import_module(module_name)
    module.register()
    return module


def _inspect_zip(zip_path: Path) -> dict[str, object]:
    if not zip_path:
        return {"checked": False}
    if not zip_path.exists():
        raise AssertionError(f"ZIP does not exist: {zip_path}")
    import zipfile

    with zipfile.ZipFile(zip_path, "r") as archive:
        entries = archive.namelist()
    bad = [
        entry
        for entry in entries
        if "__pycache__/" in entry.lower()
        or entry.lower().endswith((".pyc", ".pyo", ".zip", ".blend1", ".tmp"))
        or not entry.replace("\\", "/").startswith("codex_blender_agent/")
    ]
    _assert(not bad, f"ZIP contains non-source or out-of-root entries: {bad}")
    _assert("codex_blender_agent/blender_manifest.toml" in entries, "ZIP is missing blender_manifest.toml.")
    _assert("codex_blender_agent/__init__.py" in entries, "ZIP is missing __init__.py.")
    return {"checked": True, "entries": len(entries)}


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    import bpy  # type: ignore

    repo_root = Path(args.repo_root).resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="codex_blender_assets_smoke_"))
    results: dict[str, object] = {"steps": list(SMOKE_STEPS), "temp_root": str(temp_root)}

    try:
        module = _enable_addon(args.module, repo_root)
        results["module"] = module.__name__
        results["bl_info_version"] = ".".join(str(part) for part in module.bl_info["version"])

        runtime_mod = importlib.import_module(f"{module.__name__}.runtime")
        asset_store_mod = importlib.import_module(f"{module.__name__}.asset_store")
        workflow_examples_mod = importlib.import_module(f"{module.__name__}.workflow_examples")

        runtime = runtime_mod.get_runtime()
        runtime._storage_root = lambda _context: temp_root

        store = asset_store_mod.AssetStore(temp_root)
        _assert(store.list_entries() == [], "Fresh asset store should be empty.")
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json", encoding="utf-8")
        _assert(store.list_entries() == [], "Corrupt asset store JSON should recover as an empty store.")
        if store.path.exists():
            store.path.unlink()

        registration_card = runtime.register_asset_library(bpy.context)
        results["asset_library_registration_card"] = registration_card
        _assert(registration_card.get("action_id"), "Asset library registration should create a review card before mutation.")
        runtime._current_action_id = registration_card["action_id"]
        try:
            registration = runtime.register_asset_library(bpy.context)
        finally:
            runtime._current_action_id = ""
        results["asset_library_registration"] = registration
        legacy = registration.get("legacy", {})
        _assert(Path(legacy["path"]) == temp_root / "blender_asset_library", "Asset library path should use smoke temp root.")
        _assert(legacy.get("registered") is True, f"Asset library did not register: {registration}")

        bpy.ops.codex_blender_agent.open_assets_workspace()
        workspace_names = [workspace.name for workspace in bpy.data.workspaces]
        _assert("Assets" in workspace_names, "Assets workspace was not created.")

        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete()
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        cube = bpy.context.object
        cube.name = "SmokeAssetCube"
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube

        save_card = runtime.save_selected_asset_from_ui(bpy.context, "Smoke Asset Cube")
        results["save_card"] = save_card
        _assert(save_card.get("action_id"), "Save selection should create a review card before writing files.")
        runtime._current_action_id = save_card["action_id"]
        try:
            save_result = runtime.save_selected_asset_from_ui(bpy.context, "Smoke Asset Cube")
        finally:
            runtime._current_action_id = ""
        results["save_result"] = save_result
        item = store.get_entry(save_result["id"])
        bundle_path = Path(item["stored_path"])
        _assert(bundle_path.exists(), f"Saved .blend asset bundle does not exist: {bundle_path}")
        _assert(item["kind"] == "blend_bundle", f"Expected blend_bundle kind, got {item['kind']}")
        _assert("SmokeAssetCube" in item.get("metadata", {}).get("object_names", []), "Saved asset metadata missing source object name.")
        runtime._sync_asset_items(bpy.context.window_manager)
        bpy.context.window_manager.codex_blender_asset_index = 0

        bpy.data.objects.remove(cube, do_unlink=True)
        import_card = runtime.import_selected_asset_from_ui(bpy.context, link=False)
        results["import_card"] = import_card
        _assert(import_card.get("action_id"), "Import should create a review card before scene mutation.")
        runtime._current_action_id = import_card["action_id"]
        try:
            import_result = runtime._import_asset_item(bpy.context, item["id"], link=False)
        finally:
            runtime._current_action_id = ""
        results["import_result"] = import_result
        _assert("SmokeAssetCube" in bpy.data.objects, "Appended asset object was not restored to bpy.data.objects.")

        example_ids = workflow_examples_mod.workflow_example_ids()
        _assert("save_selection_asset" in example_ids, "Workflow examples missing save_selection_asset.")
        _assert("asset_reuse" in example_ids, "Workflow examples missing asset_reuse.")
        results["workflow_examples"] = list(example_ids)

        if args.zip_path:
            results["zip"] = _inspect_zip(Path(args.zip_path))

        results["ok"] = True
        return results
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(_after_blender_separator(sys.argv) if argv is None else argv)
    try:
        report = run_smoke(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
