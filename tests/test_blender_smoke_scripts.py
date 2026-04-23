from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_PATH = ROOT / "scripts" / "smoke_blender_assets.py"
WORKSPACE_SMOKE_PATH = ROOT / "scripts" / "smoke_workspace_v09.py"
WORKFLOW_SMOKE_PATH = ROOT / "scripts" / "smoke_workflow_v10.py"
VISUAL_GEOMETRY_SMOKE_PATH = ROOT / "scripts" / "smoke_visual_geometry_v131.py"
ASSET_VALIDATION_SMOKE_PATH = ROOT / "scripts" / "smoke_asset_validation_v132.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_blender_assets", SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_blender_assets_smoke_script_compiles():
    py_compile.compile(str(SMOKE_PATH), doraise=True)
    py_compile.compile(str(WORKSPACE_SMOKE_PATH), doraise=True)
    py_compile.compile(str(WORKFLOW_SMOKE_PATH), doraise=True)
    py_compile.compile(str(VISUAL_GEOMETRY_SMOKE_PATH), doraise=True)
    py_compile.compile(str(ASSET_VALIDATION_SMOKE_PATH), doraise=True)


def test_blender_assets_smoke_script_declares_required_steps():
    smoke = _load_smoke_module()

    assert smoke.SMOKE_STEPS == (
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


def test_blender_assets_smoke_script_argument_defaults():
    smoke = _load_smoke_module()

    args = smoke.build_arg_parser().parse_args([])

    assert args.module == "codex_blender_agent"
    assert args.keep_temp is False


def test_workspace_v09_smoke_script_declares_required_steps():
    spec = importlib.util.spec_from_file_location("smoke_workspace_v09", WORKSPACE_SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.SMOKE_STEPS == (
        "load_addon",
        "verify_no_auto_workspace_creation",
        "create_ai_workspaces",
        "verify_layout_preserved",
        "verify_workspace_names",
        "verify_workspace_editors",
        "verify_legacy_open_alias",
        "verify_v11_design_system_contract",
        "verify_v11_ui_operators",
    )


def test_workflow_v10_smoke_script_declares_required_steps():
    spec = importlib.util.spec_from_file_location("smoke_workflow_v10", WORKFLOW_SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.SMOKE_STEPS == (
        "load_addon",
        "validate_core_workflow_surface",
        "probe_v10_optional_apis",
        "create_or_refresh_workflow_graph",
        "preview_workflow_graph",
        "inspect_graph_summary",
    )
    assert module.CORE_OPERATOR_NAMES == (
        "create_workflow_tree",
        "add_workflow_node",
        "inspect_workflow_graph",
        "run_workflow_graph",
    )
    assert "assistant_call" in module.OPTIONAL_V10_NODE_TYPES


def test_workflow_v10_smoke_script_argument_defaults():
    spec = importlib.util.spec_from_file_location("smoke_workflow_v10", WORKFLOW_SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    args = module.build_arg_parser().parse_args([])

    assert args.module == "codex_blender_agent"
    assert args.require_v10_apis is False


def test_visual_geometry_v131_smoke_script_declares_required_steps():
    spec = importlib.util.spec_from_file_location("smoke_visual_geometry_v131", VISUAL_GEOMETRY_SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.SMOKE_STEPS == (
        "load_addon",
        "empty_scene_geometry_analysis",
        "plan_rotated_asset_views",
        "detect_generic_part_defects",
        "capture_geometry_planned_views",
        "verify_state_restoration",
    )


def test_asset_validation_v132_smoke_script_declares_required_steps():
    spec = importlib.util.spec_from_file_location("smoke_asset_validation_v132", ASSET_VALIDATION_SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.SMOKE_STEPS == (
        "load_addon",
        "empty_scene_asset_validation",
        "detect_overlap_floater_zfight_topology",
        "capture_attaches_validation_report",
        "verify_state_restoration",
    )
