from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


SMOKE_STEPS = (
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blender smoke test for the v0.9 multi-workspace studio redesign.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--module", default="codex_blender_agent")
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
    module = importlib.import_module(module_name)
    module.register()
    return module


def _layout_signature():
    import bpy  # type: ignore

    workspace = bpy.data.workspaces.get("Layout")
    if workspace is None or not workspace.screens:
        return ()
    return tuple(f"{area.type}:{area.width}x{area.height}" for area in workspace.screens[0].areas)


def _area_types(workspace_name: str) -> list[str]:
    import bpy  # type: ignore

    workspace = bpy.data.workspaces.get(workspace_name)
    if workspace is None or not workspace.screens:
        return []
    return [area.type for area in workspace.screens[0].areas]


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    import bpy  # type: ignore

    repo_root = Path(args.repo_root).resolve()
    module = _enable_addon(args.module, repo_root)
    runtime = module.runtime.get_runtime()

    initial_names = [workspace.name for workspace in bpy.data.workspaces]
    layout_before = _layout_signature()
    _assert("AI Studio" not in initial_names, "AI Studio should not be auto-created on enable.")
    _assert("Workflow" not in initial_names, "Workflow should not be auto-created on enable.")
    _assert("Assets" not in initial_names, "Assets should not be auto-created on enable.")

    result = bpy.ops.codex_blender_agent.create_ai_workspaces()
    _assert("FINISHED" in result, f"Create AI Workspaces failed: {result}")
    final_names = [workspace.name for workspace in bpy.data.workspaces]
    for name in ("AI Studio", "Workflow", "Assets"):
        _assert(name in final_names, f"{name} workspace missing after create.")

    layout_after = _layout_signature()
    _assert(layout_before == layout_after, "Layout workspace signature changed during AI workspace creation.")

    expected_editors = {
        "AI Studio": {"VIEW_3D", "OUTLINER", "INFO"},
        "Workflow": {"NODE_EDITOR", "VIEW_3D", "SPREADSHEET"},
        "Assets": {"FILE_BROWSER", "VIEW_3D", "PROPERTIES"},
    }
    areas = {name: _area_types(name) for name in expected_editors}
    for name, expected in expected_editors.items():
        _assert(expected.issubset(set(areas[name])), f"{name} missing editors: {sorted(expected - set(areas[name]))}")

    bpy.ops.codex_blender_agent.open_dashboard_workspace()
    active_after_alias = bpy.context.window.workspace.name if bpy.context.window and bpy.context.window.workspace else ""
    requested_after_alias = getattr(importlib.import_module(f"{module.__name__}.workspace"), "LAST_REQUESTED_WORKSPACE", "")
    _assert(
        active_after_alias == "AI Studio" or requested_after_alias == "AI Studio",
        f"Legacy dashboard alias opened/requested active={active_after_alias!r} requested={requested_after_alias!r}, expected AI Studio.",
    )

    verify = runtime.verify_workspace_suite(bpy.context)
    _assert(verify.get("ok"), f"Workspace suite verify failed: {verify}")

    visual_tokens = importlib.import_module(f"{module.__name__}.visual_tokens")
    _assert(visual_tokens.state_meta("awaiting_approval").label == "Review required", "v0.11 review state label missing.")
    _assert(visual_tokens.state_meta("completed").alert is False, "Completed state must not use alert styling.")
    _assert(visual_tokens.primary_action_for_card({"status": "running"}).label == "Stop", "Running card primary action should be Stop.")
    _assert(visual_tokens.primary_action_for_card({"status": "failed"}).label == "Recover action", "Failed card primary action should recover.")
    _assert(visual_tokens.empty_state_payload("assets").next_action == "Refresh assets", "Assets empty state should offer refresh.")

    for operator_name in (
        "inspect_ai_context",
        "view_action_changes",
        "undo_last_ai_change",
        "reset_ai_context",
        "open_action_details",
    ):
        _assert(hasattr(bpy.ops.codex_blender_agent, operator_name), f"Missing v0.11 operator: {operator_name}")

    return {
        "ok": True,
        "steps": list(SMOKE_STEPS),
        "initial_workspaces": initial_names,
        "final_workspaces": final_names,
        "areas": areas,
        "verify": verify,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_arg_parser().parse_args(_after_blender_separator(sys.argv) if argv is None else argv)
        report = run_smoke(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
