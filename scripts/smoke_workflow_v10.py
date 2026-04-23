from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


SMOKE_STEPS = (
    "load_addon",
    "validate_core_workflow_surface",
    "probe_v10_optional_apis",
    "create_or_refresh_workflow_graph",
    "preview_workflow_graph",
    "inspect_graph_summary",
)

CORE_OPERATOR_NAMES = (
    "create_workflow_tree",
    "add_workflow_node",
    "inspect_workflow_graph",
    "run_workflow_graph",
)

OPTIONAL_V10_OPERATOR_NAMES = (
    "validate_workflow_graph",
    "compile_workflow_graph",
    "preview_workflow_graph",
    "start_workflow_run",
    "resume_workflow_run",
    "stop_workflow_run",
    "publish_workflow_recipe",
    "propose_workflow_patch",
    "apply_workflow_patch",
)

OPTIONAL_V10_NODE_TYPES = (
    "workflow_input",
    "workflow_output",
    "value",
    "context_merge",
    "assistant_call",
    "route",
    "for_each",
    "join",
    "preview_tap",
    "recipe_call",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blender smoke test for the v0.10 workflow orchestration surface.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]), help="Repository root containing codex_blender_agent.")
    parser.add_argument("--module", default="codex_blender_agent", help="Addon module name. Use bl_ext.user_default.codex_blender_agent for installed extension mode.")
    parser.add_argument(
        "--require-v10-apis",
        action="store_true",
        help="Fail when optional v0.10 workflow APIs are missing instead of reporting them as gaps.",
    )
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


def _operator_exists(namespace, name: str) -> bool:
    return hasattr(namespace, name)


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    import bpy  # type: ignore

    repo_root = Path(args.repo_root).resolve()
    module = _enable_addon(args.module, repo_root)
    runtime = module.runtime.get_runtime()
    workflow_nodes = importlib.import_module(f"{module.__name__}.workflow_nodes")

    core_namespace = getattr(bpy.ops, "codex_blender_agent", None)
    _assert(core_namespace is not None, "Codex Blender Agent operator namespace is missing.")

    core_missing = [name for name in CORE_OPERATOR_NAMES if not _operator_exists(core_namespace, name)]
    _assert(not core_missing, f"Missing core workflow operators: {core_missing}")

    graph_name = "Codex AI Workflow Smoke"
    runtime.create_workflow_graph(graph_name, with_default_nodes=False)
    created_nodes = [
        workflow_nodes.add_workflow_node(graph_name, "workflow_input", label="Workflow Input", location=(-1020.0, 120.0)),
        workflow_nodes.add_workflow_node(graph_name, "scene_snapshot", label="Scene Snapshot", location=(-720.0, 140.0)),
        workflow_nodes.add_workflow_node(graph_name, "selection", label="Selection", location=(-720.0, -80.0)),
        workflow_nodes.add_workflow_node(graph_name, "assistant_prompt", label="Assistant Prompt", location=(-360.0, 120.0)),
        workflow_nodes.add_workflow_node(graph_name, "assistant_call", label="Assistant Call", location=(-40.0, 120.0)),
        workflow_nodes.add_workflow_node(graph_name, "approval_gate", label="Approval Gate", location=(280.0, 120.0)),
        workflow_nodes.add_workflow_node(graph_name, "workflow_output", label="Workflow Output", location=(620.0, 120.0)),
    ]
    by_label = {node.label or node.name: node for node in created_nodes}
    typed_links = [
        ("Workflow Input", "Flow", "Assistant Call", "Flow"),
        ("Workflow Input", "Snapshot", "Selection", "Snapshot"),
        ("Selection", "Targets", "Scene Snapshot", "Targets"),
        ("Selection", "Targets", "Assistant Prompt", "Targets"),
        ("Scene Snapshot", "Snapshot", "Assistant Prompt", "Snapshot"),
        ("Assistant Prompt", "Prompt", "Assistant Call", "Prompt"),
        ("Assistant Call", "Flow", "Approval Gate", "Flow"),
        ("Assistant Call", "Artifact", "Approval Gate", "Artifact"),
        ("Approval Gate", "Flow", "Workflow Output", "Flow"),
        ("Approval Gate", "Decision", "Workflow Output", "Decision"),
    ]
    for from_label, from_socket, to_label, to_socket in typed_links:
        workflow_nodes.connect_workflow_nodes(graph_name, by_label[from_label].name, from_socket, by_label[to_label].name, to_socket)
    graph = workflow_nodes.inspect_workflow_graph(graph_name)

    optional_operator_missing = [name for name in OPTIONAL_V10_OPERATOR_NAMES if not _operator_exists(core_namespace, name)]
    optional_node_missing = [name for name in OPTIONAL_V10_NODE_TYPES if name not in getattr(workflow_nodes, "NODE_TYPES", {})]

    if getattr(args, "require_v10_apis", False):
        _assert(not optional_operator_missing, f"Missing v0.10 workflow operators: {optional_operator_missing}")
        _assert(not optional_node_missing, f"Missing v0.10 workflow node types: {optional_node_missing}")

    preview_result = runtime.preview_workflow_graph(bpy.context, graph_name=graph_name) if not optional_operator_missing else runtime.run_workflow_graph(bpy.context, graph_name=graph_name, preview_only=True)

    return {
        "ok": True,
        "steps": list(SMOKE_STEPS),
        "module": module.__name__,
        "workflow_node_tree": getattr(workflow_nodes, "NODETREE_IDNAME", ""),
        "workflow_graph_name": graph.get("name", "") if isinstance(graph, dict) else "",
        "core_operators_present": CORE_OPERATOR_NAMES,
        "optional_operators_present": [name for name in OPTIONAL_V10_OPERATOR_NAMES if name not in optional_operator_missing],
        "missing_optional_operators": optional_operator_missing,
        "optional_node_types_present": [name for name in OPTIONAL_V10_NODE_TYPES if name not in optional_node_missing],
        "missing_optional_node_types": optional_node_missing,
        "graph_summary": graph,
        "preview_result": preview_result,
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
