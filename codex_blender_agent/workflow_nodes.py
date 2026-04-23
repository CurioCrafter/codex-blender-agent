from __future__ import annotations

import json
from typing import Any, Callable

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - imported outside Blender for tests
    bpy = None

if bpy is not None:  # pragma: no cover - Blender runtime path
    BoolProperty = bpy.props.BoolProperty
else:  # pragma: no cover - tests import without Blender
    def BoolProperty(**_kwargs):
        return False


NODETREE_IDNAME = "CODEX_AiWorkflowNodeTree"
NODETREE_LABEL = "Codex AI Workflow"

WORKFLOW_NODE_CATEGORY_ORDER = (
    "Interface",
    "Context",
    "AI",
    "Assets",
    "Actions",
    "Control",
    "Recipes",
    "Layout",
)

WORKFLOW_NODE_CATEGORY_LABELS = {
    "Interface": "Interface",
    "Context": "Context",
    "AI": "AI",
    "Assets": "Assets",
    "Actions": "Actions",
    "Control": "Control",
    "Recipes": "Recipes",
    "Layout": "Layout",
}

WORKFLOW_SOCKET_COLORS = {
    "flow": (0.75, 0.45, 0.12, 1.0),
    "context": (0.24, 0.52, 0.82, 1.0),
    "snapshot": (0.18, 0.66, 0.64, 1.0),
    "targets": (0.23, 0.68, 0.38, 1.0),
    "memory": (0.56, 0.35, 0.78, 1.0),
    "prompt": (0.82, 0.33, 0.58, 1.0),
    "asset_set": (0.86, 0.66, 0.25, 1.0),
    "artifact": (0.55, 0.55, 0.55, 1.0),
    "decision": (0.76, 0.22, 0.24, 1.0),
    "scalar": (0.80, 0.80, 0.82, 1.0),
    "any": (0.70, 0.70, 0.72, 1.0),
}


WORKFLOW_SOCKET_LABELS = {
    "flow": "Flow",
    "context": "Context",
    "snapshot": "Snapshot",
    "targets": "Targets",
    "memory": "Memory",
    "prompt": "Prompt",
    "asset_set": "Asset Set",
    "artifact": "Artifact",
    "decision": "Decision",
    "scalar": "Scalar",
    "any": "Any",
}


def _socket_class_name(kind: str) -> str:
    return f"CODEXBLENDERAGENT_{kind.title().replace('_', '')}Socket"


def _create_socket_class(kind: str):
    label = WORKFLOW_SOCKET_LABELS.get(kind, kind.title())
    class_name = _socket_class_name(kind)
    base = bpy.types.NodeSocket if bpy is not None else object

    attrs: dict[str, Any] = {
        "__module__": __name__,
        "bl_idname": class_name,
        "bl_label": label,
        "workflow_socket_kind": kind,
    }
    if bpy is not None:
        def draw_color_simple(cls):
            return WORKFLOW_SOCKET_COLORS.get(kind, WORKFLOW_SOCKET_COLORS["any"])

        attrs["draw"] = lambda self, context, layout, node, text: layout.label(text=text or self.name)
        attrs["draw_color"] = lambda self, context, node: WORKFLOW_SOCKET_COLORS.get(kind, WORKFLOW_SOCKET_COLORS["any"])
        attrs["draw_color_simple"] = classmethod(draw_color_simple)

    return type(class_name, (base,), attrs)


WORKFLOW_SOCKET_CLASSES: dict[str, Any] = {kind: _create_socket_class(kind) for kind in WORKFLOW_SOCKET_LABELS}


def _socket_spec(kind: str, name: str, *, multi_input: bool = False) -> dict[str, Any]:
    return {"kind": kind, "name": name, "multi_input": multi_input}


WORKFLOW_NODE_CONTRACTS: dict[str, dict[str, Any]] = {
    "workflow_input": {
        "idname": "CODEXBLENDERAGENT_WorkflowInputNode",
        "label": "Workflow Input",
        "category": "Interface",
        "purity": "pure",
        "uses_flow": True,
        "required_context": "Run metadata",
        "output_type": "Run inputs",
        "description": "Declares workflow run inputs and visible context.",
        "auto_create": True,
        "inputs": [],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("snapshot", "Snapshot"),
            _socket_spec("targets", "Targets"),
            _socket_spec("memory", "Memory"),
            _socket_spec("prompt", "Prompt"),
            _socket_spec("asset_set", "Asset Set"),
            _socket_spec("artifact", "Artifact"),
            _socket_spec("decision", "Decision"),
            _socket_spec("scalar", "Scalar"),
        ],
    },
    "workflow_output": {
        "idname": "CODEXBLENDERAGENT_WorkflowOutputNode",
        "label": "Workflow Output",
        "category": "Interface",
        "purity": "pure",
        "uses_flow": True,
        "required_context": "Run result",
        "output_type": "Workflow summary",
        "description": "Declares workflow success criteria and visible outputs.",
        "auto_create": True,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("snapshot", "Snapshot"),
            _socket_spec("targets", "Targets"),
            _socket_spec("memory", "Memory"),
            _socket_spec("prompt", "Prompt"),
            _socket_spec("asset_set", "Asset Set"),
            _socket_spec("artifact", "Artifact"),
            _socket_spec("decision", "Decision"),
            _socket_spec("scalar", "Scalar"),
        ],
        "outputs": [],
    },
    "value": {
        "idname": "CODEXBLENDERAGENT_ValueNode",
        "label": "Value",
        "category": "Interface",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Literal value",
        "output_type": "Scalar value",
        "description": "Provides a typed literal for graph configuration.",
        "auto_create": False,
        "inputs": [],
        "outputs": [_socket_spec("scalar", "Scalar")],
    },
    "scene_snapshot": {
        "idname": "CODEXBLENDERAGENT_SceneSnapshotNode",
        "label": "Scene Snapshot",
        "category": "Context",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Scene",
        "output_type": "Scene summary",
        "description": "Reads a compact scene snapshot for preview and replay.",
        "auto_create": False,
        "inputs": [_socket_spec("targets", "Targets")],
        "outputs": [_socket_spec("snapshot", "Snapshot"), _socket_spec("context", "Context")],
    },
    "selection": {
        "idname": "CODEXBLENDERAGENT_SelectionNode",
        "label": "Selection",
        "category": "Context",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Selection",
        "output_type": "Selected objects",
        "description": "Resolves the current selection into a stable target set.",
        "auto_create": False,
        "inputs": [_socket_spec("snapshot", "Snapshot"), _socket_spec("context", "Context")],
        "outputs": [_socket_spec("targets", "Targets")],
    },
    "context_merge": {
        "idname": "CODEXBLENDERAGENT_ContextMergeNode",
        "label": "Context Merge",
        "category": "Context",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Context bundle",
        "output_type": "Merged context",
        "description": "Combines context bundles with explicit precedence.",
        "auto_create": False,
        "inputs": [_socket_spec("context", "Context", multi_input=True)],
        "outputs": [_socket_spec("context", "Context")],
    },
    "thread_memory": {
        "idname": "CODEXBLENDERAGENT_ThreadMemoryNode",
        "label": "Thread Memory",
        "category": "Context",
        "purity": "hybrid",
        "uses_flow": True,
        "required_context": "Thread",
        "output_type": "Thread memory",
        "description": "Reads, appends, or summarizes thread-scoped memory.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
        ],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("memory", "Memory"),
            _socket_spec("context", "Context"),
        ],
    },
    "assistant_prompt": {
        "idname": "CODEXBLENDERAGENT_AssistantPromptNode",
        "label": "Assistant Prompt",
        "category": "AI",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Prompt draft",
        "output_type": "Prompt text",
        "description": "Resolves a prompt template into structured assistant input.",
        "auto_create": False,
        "inputs": [
            _socket_spec("snapshot", "Snapshot"),
            _socket_spec("targets", "Targets"),
            _socket_spec("context", "Context"),
            _socket_spec("memory", "Memory"),
            _socket_spec("scalar", "Scalar"),
        ],
        "outputs": [_socket_spec("prompt", "Prompt")],
    },
    "assistant_call": {
        "idname": "CODEXBLENDERAGENT_AssistantCallNode",
        "label": "Assistant Call",
        "category": "AI",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Assistant request",
        "output_type": "Assistant result",
        "description": "Executes a structured assistant request against the resolved prompt.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("prompt", "Prompt"),
            _socket_spec("context", "Context"),
            _socket_spec("memory", "Memory"),
            _socket_spec("asset_set", "Asset Set"),
        ],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
            _socket_spec("decision", "Decision"),
        ],
    },
    "asset_search": {
        "idname": "CODEXBLENDERAGENT_AssetSearchNode",
        "label": "Asset Search",
        "category": "Assets",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Asset query",
        "output_type": "Asset matches",
        "description": "Searches the local asset store.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("snapshot", "Snapshot"),
            _socket_spec("targets", "Targets"),
            _socket_spec("context", "Context"),
            _socket_spec("scalar", "Scalar"),
        ],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("asset_set", "Asset Set"),
            _socket_spec("context", "Context"),
        ],
    },
    "tool_call": {
        "idname": "CODEXBLENDERAGENT_ToolCallNode",
        "label": "Tool Call",
        "category": "Actions",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Tool arguments",
        "output_type": "Tool result",
        "description": "Runs one structured Blender tool.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("targets", "Targets"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
        ],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
        ],
    },
    "recipe_call": {
        "idname": "CODEXBLENDERAGENT_RecipeCallNode",
        "label": "Recipe Call",
        "category": "Recipes",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Recipe reference",
        "output_type": "Recipe result",
        "description": "Runs a reusable workflow recipe by version reference.",
        "auto_create": False,
        "legacy_aliases": ("toolbox_recipe",),
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("snapshot", "Snapshot"),
            _socket_spec("targets", "Targets"),
        ],
        "outputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
            _socket_spec("decision", "Decision"),
        ],
    },
    "approval_gate": {
        "idname": "CODEXBLENDERAGENT_ApprovalGateNode",
        "label": "Approval Gate",
        "category": "Actions",
        "purity": "action",
        "uses_flow": True,
        "required_context": "User approval",
        "output_type": "Continue/block",
        "description": "Blocks risky execution until approved.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
            _socket_spec("asset_set", "Asset Set"),
        ],
        "outputs": [_socket_spec("flow", "Flow"), _socket_spec("decision", "Decision")],
    },
    "route": {
        "idname": "CODEXBLENDERAGENT_RouteNode",
        "label": "Route",
        "category": "Control",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Branch decision",
        "output_type": "Flow branch",
        "description": "Branches execution by bool, enum, or node state.",
        "auto_create": False,
        "inputs": [_socket_spec("flow", "Flow"), _socket_spec("decision", "Decision"), _socket_spec("scalar", "Scalar")],
        "outputs": [
            _socket_spec("flow", "Approved"),
            _socket_spec("flow", "Rejected"),
            _socket_spec("flow", "Default"),
        ],
    },
    "for_each": {
        "idname": "CODEXBLENDERAGENT_ForEachNode",
        "label": "For Each",
        "category": "Control",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Collection or target set",
        "output_type": "Batch results",
        "description": "Executes a recipe once per item or target.",
        "auto_create": False,
        "inputs": [_socket_spec("flow", "Flow"), _socket_spec("targets", "Targets"), _socket_spec("context", "Context")],
        "outputs": [_socket_spec("flow", "Flow"), _socket_spec("context", "Context"), _socket_spec("artifact", "Artifact")],
    },
    "join": {
        "idname": "CODEXBLENDERAGENT_JoinNode",
        "label": "Join",
        "category": "Control",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Branch results",
        "output_type": "Joined result",
        "description": "Waits for and merges branch results.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow", multi_input=True),
            _socket_spec("context", "Context", multi_input=True),
            _socket_spec("artifact", "Artifact", multi_input=True),
        ],
        "outputs": [_socket_spec("flow", "Flow"), _socket_spec("context", "Context"), _socket_spec("artifact", "Artifact")],
    },
    "preview_tap": {
        "idname": "CODEXBLENDERAGENT_PreviewTapNode",
        "label": "Preview Tap",
        "category": "Layout",
        "purity": "pure",
        "uses_flow": False,
        "required_context": "Inspectable payload",
        "output_type": "Preview copy",
        "description": "Pins an intermediate result for inspection without mutating flow.",
        "auto_create": False,
        "inputs": [_socket_spec("any", "Input")],
        "outputs": [_socket_spec("any", "Output")],
    },
    "publish_asset": {
        "idname": "CODEXBLENDERAGENT_PublishAssetNode",
        "label": "Publish Asset",
        "category": "Assets",
        "purity": "action",
        "uses_flow": True,
        "required_context": "Selection",
        "output_type": "Saved asset",
        "description": "Publishes selected objects into the asset library.",
        "auto_create": False,
        "inputs": [
            _socket_spec("flow", "Flow"),
            _socket_spec("targets", "Targets"),
            _socket_spec("context", "Context"),
            _socket_spec("artifact", "Artifact"),
        ],
        "outputs": [_socket_spec("flow", "Flow"), _socket_spec("artifact", "Artifact"), _socket_spec("decision", "Decision")],
    },
}

LEGACY_NODE_TYPE_ALIASES = {
    "toolbox_recipe": "recipe_call",
    "toolbox recipe": "recipe_call",
    "recipe": "recipe_call",
}

LEGACY_NODE_IDNAME_ALIASES = {
    "CODEXBLENDERAGENT_ToolboxRecipeNode": "recipe_call",
}

NODE_TYPES = {
    node_type: {
        "idname": spec["idname"],
        "label": spec["label"],
        "category": spec["category"],
        "purity": spec["purity"],
        "uses_flow": spec["uses_flow"],
        "required_context": spec.get("required_context", ""),
        "output_type": spec.get("output_type", ""),
        "description": spec.get("description", ""),
        "auto_create": spec.get("auto_create", False),
        "inputs": tuple(spec.get("inputs", ())),
        "outputs": tuple(spec.get("outputs", ())),
        "legacy_aliases": tuple(spec.get("legacy_aliases", ())),
    }
    for node_type, spec in WORKFLOW_NODE_CONTRACTS.items()
}


def canonical_node_type(node_type: str) -> str:
    value = (node_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    value = LEGACY_NODE_TYPE_ALIASES.get(value, value)
    return value


def node_contract(node_type: str) -> dict[str, Any]:
    canonical = canonical_node_type(node_type)
    if canonical not in NODE_TYPES:
        valid = ", ".join(sorted(NODE_TYPES))
        raise ValueError(f"Unsupported workflow node type: {node_type}. Valid types: {valid}")
    return dict(NODE_TYPES[canonical], node_type=canonical)


def workflow_node_category(node_type: str) -> str:
    return str(node_contract(node_type)["category"])


def workflow_node_purity(node_type: str) -> str:
    return str(node_contract(node_type)["purity"])


def workflow_node_has_flow(node_type: str) -> bool:
    return bool(node_contract(node_type)["uses_flow"])


def workflow_node_contract_summary(node_type: str) -> dict[str, Any]:
    contract = node_contract(node_type)
    return {
        "node_type": contract["node_type"],
        "label": contract["label"],
        "category": contract["category"],
        "purity": contract["purity"],
        "uses_flow": bool(contract["uses_flow"]),
        "required_context": contract.get("required_context", ""),
        "output_type": contract.get("output_type", ""),
        "description": contract.get("description", ""),
        "legacy_aliases": tuple(contract.get("legacy_aliases", ())),
    }


def workflow_node_categories(include_legacy: bool = False) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    for category in WORKFLOW_NODE_CATEGORY_ORDER:
        node_types = [
            node_type
            for node_type, spec in NODE_TYPES.items()
            if spec["category"] == category and (include_legacy or not spec.get("legacy_alias_of"))
        ]
        categories.append(
            {
                "category": category,
                "label": WORKFLOW_NODE_CATEGORY_LABELS.get(category, category),
                "node_types": node_types,
            }
        )
    return categories


def workflow_node_is_pure(node_type: str) -> bool:
    return node_contract(node_type)["purity"] == "pure"


def workflow_node_is_action(node_type: str) -> bool:
    return node_contract(node_type)["purity"] in {"action", "hybrid"}


def workflow_node_uses_flow(node_type: str) -> bool:
    return bool(node_contract(node_type)["uses_flow"])


def workflow_node_socket_specs(node_type: str) -> dict[str, tuple[dict[str, Any], ...]]:
    contract = node_contract(node_type)
    return {
        "inputs": tuple(dict(spec) for spec in contract["inputs"]),
        "outputs": tuple(dict(spec) for spec in contract["outputs"]),
    }


WORKFLOW_NODE_ROOT_TYPES = ("workflow_input", "workflow_output")


def workflow_root_blueprint() -> list[dict[str, Any]]:
    return [
        {"node_type": "workflow_input", "label": "Workflow Input", "location": (-980.0, 120.0)},
        {"node_type": "workflow_output", "label": "Workflow Output", "location": (700.0, 120.0)},
    ]


def workflow_graph_blueprint(with_default_nodes: bool = True) -> list[dict[str, Any]]:
    if not with_default_nodes:
        return []
    return [
        {"node_type": "workflow_input", "label": "Workflow Input", "location": (-980.0, 120.0)},
        {"node_type": "scene_snapshot", "label": "Scene Snapshot", "location": (-660.0, 180.0)},
        {"node_type": "selection", "label": "Selection", "location": (-660.0, -20.0)},
        {"node_type": "assistant_prompt", "label": "Assistant Prompt", "location": (-320.0, 120.0)},
        {"node_type": "assistant_call", "label": "Assistant Call", "location": (20.0, 120.0)},
        {"node_type": "approval_gate", "label": "Approval Gate", "location": (360.0, 120.0)},
        {"node_type": "workflow_output", "label": "Workflow Output", "location": (700.0, 120.0)},
    ]


def ensure_workflow_root_nodes(tree) -> list[str]:
    if bpy is None:
        return []
    existing = {_tree_node_type(node) for node in tree.nodes}
    created: list[str] = []
    if not tree.nodes:
        for blueprint in workflow_graph_blueprint(True):
            node = add_workflow_node(tree.name, blueprint["node_type"], label=blueprint["label"], location=tuple(blueprint["location"]))
            created.append(node.name)
        return created
    positions = [float(node.location.x) for node in tree.nodes] or [0.0]
    left = min(positions) - 340.0
    right = max(positions) + 340.0
    if "workflow_input" not in existing:
        node = add_workflow_node(tree.name, "workflow_input", label="Workflow Input", location=(left, 120.0))
        created.append(node.name)
    if "workflow_output" not in existing:
        node = add_workflow_node(tree.name, "workflow_output", label="Workflow Output", location=(right, 120.0))
        created.append(node.name)
    return created


def migrate_legacy_node_config(config: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(config or {})
    if "idname" in migrated and migrated["idname"] in LEGACY_NODE_IDNAME_ALIASES:
        migrated["node_type"] = LEGACY_NODE_IDNAME_ALIASES[str(migrated["idname"])]
    if "node_type" in migrated:
        migrated["node_type"] = canonical_node_type(str(migrated["node_type"]))
    if "toolbox_recipe" in migrated and "node_type" not in migrated:
        migrated["node_type"] = "recipe_call"
    if migrated.get("node_type") == "recipe_call":
        migrated.setdefault("recipe_ref", migrated.get("memory_query", ""))
    return migrated


def migrate_legacy_workflow_graph_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    data = dict(manifest or {})
    nodes = [migrate_legacy_node_config(node) for node in data.get("nodes", []) if isinstance(node, dict)]
    links = [dict(link) for link in data.get("links", []) if isinstance(link, dict)]
    node_types = [str(node.get("node_type", "")) for node in nodes]
    existing = {canonical_node_type(node_type) for node_type in node_types}
    for root_node in ("workflow_input", "workflow_output"):
        if root_node not in existing:
            blueprint = next(item for item in workflow_graph_blueprint(True) if item["node_type"] == root_node)
            nodes.append(dict(blueprint))
    data["nodes"] = nodes
    data["links"] = links
    data["legacy_migrated"] = True
    return data


def workflow_node_menu_sections(include_legacy: bool = False) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for category in WORKFLOW_NODE_CATEGORY_ORDER:
        entries = [
            {
                "node_type": node_type,
                "idname": spec["idname"],
                "label": spec["label"],
                "description": spec.get("description", ""),
                "category": spec["category"],
                "purity": spec["purity"],
                "uses_flow": bool(spec["uses_flow"]),
            }
            for node_type, spec in NODE_TYPES.items()
            if spec["category"] == category and (include_legacy or not spec.get("legacy_alias_of"))
        ]
        if entries:
            sections.append({"category": category, "label": WORKFLOW_NODE_CATEGORY_LABELS.get(category, category), "entries": entries})
    return sections


def validate_workflow_graph_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    migrated = migrate_legacy_workflow_graph_manifest(manifest)
    nodes = migrated.get("nodes", [])
    links = migrated.get("links", [])
    issues: list[str] = []
    node_map = {str(node.get("name", node.get("label", ""))): node for node in nodes if isinstance(node, dict)}
    node_types = [canonical_node_type(str(node.get("node_type", ""))) for node in nodes if isinstance(node, dict)]
    for required in ("workflow_input", "workflow_output"):
        if required not in node_types:
            issues.append(f"Missing required root node: {required}")
    for node in nodes:
        node_type = canonical_node_type(str(node.get("node_type", "")))
        if node_type not in NODE_TYPES:
            issues.append(f"Unknown node type: {node.get('node_type', '')}")
            continue
        if "inputs" not in node or "outputs" not in node:
            contract = workflow_node_socket_specs(node_type)
            if not node.get("inputs"):
                node["inputs"] = contract["inputs"]
            if not node.get("outputs"):
                node["outputs"] = contract["outputs"]
        if workflow_node_has_flow(node_type) and not node.get("inputs"):
            issues.append(f"Action node missing flow inputs: {node.get('node_type', '')}")
    for link in links:
        source = node_map.get(str(link.get("from_node", "")))
        target = node_map.get(str(link.get("to_node", "")))
        if source is None or target is None:
            issues.append(f"Unresolved link: {link}")
            continue
        source_socket = str(link.get("from_socket", ""))
        target_socket = str(link.get("to_socket", ""))
        source_contract = _socket_contract_from_node_payload(source, source_socket, "outputs")
        target_contract = _socket_contract_from_node_payload(target, target_socket, "inputs")
        if source_contract and target_contract:
            source_kind = source_contract["kind"]
            target_kind = target_contract["kind"]
            if source_kind != "any" and target_kind != "any" and source_kind != target_kind:
                issues.append(
                    f"Socket kind mismatch on link {source.get('name', '')}:{source_socket} -> {target.get('name', '')}:{target_socket}"
                )
                continue
        elif source_contract is None or target_contract is None:
            issues.append(
                f"Unresolved socket contract on link {source.get('name', '')}:{source_socket} -> {target.get('name', '')}:{target_socket}"
            )
    return {
        "ok": not issues,
        "issues": issues,
        "manifest": migrated,
    }


def compile_workflow_graph_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    validation = validate_workflow_graph_manifest(manifest)
    migrated = validation["manifest"]
    order = compute_execution_order(
        [
            {
                "name": str(node.get("name", node.get("label", ""))),
                "location": list(node.get("location", [0.0, 0.0])),
            }
            for node in migrated.get("nodes", [])
        ],
        migrated.get("links", []),
    )
    return {
        "ok": validation["ok"],
        "issues": validation["issues"],
        "manifest": migrated,
        "execution_order": order,
    }


def _socket_contract_from_node_payload(node: dict[str, Any], socket_name: str, direction: str) -> dict[str, Any] | None:
    node_type = canonical_node_type(str(node.get("node_type", "")))
    contract = NODE_TYPES.get(node_type)
    if contract is None:
        return None
    specs = contract[direction]
    for spec in specs:
        if spec["name"] == socket_name:
            return dict(spec)
    return None


def normalize_node_type(node_type: str) -> str:
    value = (node_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value not in NODE_TYPES:
        valid = ", ".join(sorted(NODE_TYPES))
        raise ValueError(f"Unsupported workflow node type: {node_type}. Valid types: {valid}")
    return value


def parse_arguments_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arguments_json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("arguments_json must decode to an object.")
    return parsed


def validate_node_config(config: dict[str, Any]) -> dict[str, Any]:
    validated = dict(config or {})
    if "arguments" in validated and "arguments_json" in validated:
        raise ValueError("Use either arguments or arguments_json, not both.")
    if "arguments" in validated:
        arguments = parse_arguments_json(validated["arguments"])
        validated["arguments_json"] = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    if "arguments_json" in validated:
        arguments = parse_arguments_json(validated["arguments_json"])
        validated["arguments_json"] = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    if "node_type" in validated:
        validated["node_type"] = normalize_node_type(str(validated["node_type"]))
        contract = node_contract(validated["node_type"])
        validated.setdefault("node_label", contract["label"])
        validated.setdefault("node_category", contract["category"])
        validated.setdefault("node_purity", contract["purity"])
        validated.setdefault("node_uses_flow", bool(contract["uses_flow"]))
        validated.setdefault("node_required_context", contract.get("required_context", ""))
        validated.setdefault("node_output_type", contract.get("output_type", ""))
        validated.setdefault("node_description", contract.get("description", ""))
        validated.setdefault("approval_required", workflow_node_is_action(validated["node_type"]))
        validated.setdefault("socket_inputs", workflow_node_socket_specs(validated["node_type"])["inputs"])
        validated.setdefault("socket_outputs", workflow_node_socket_specs(validated["node_type"])["outputs"])
    return validated


def workflow_node_menu_entries(include_legacy: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, str]] = []
    for section in workflow_node_menu_sections(include_legacy=include_legacy):
        entries.extend(section["entries"])
    return entries


def compute_execution_order(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[str]:
    node_names = [str(node.get("name", "")) for node in nodes if str(node.get("name", ""))]
    node_set = set(node_names)
    incoming: dict[str, int] = {name: 0 for name in node_names}
    outgoing: dict[str, list[str]] = {name: [] for name in node_names}
    for link in links:
        source = str(link.get("from_node", ""))
        target = str(link.get("to_node", ""))
        if source not in node_set or target not in node_set or source == target:
            continue
        outgoing[source].append(target)
        incoming[target] += 1

    position = {str(node.get("name", "")): _payload_position(node) for node in nodes}
    ready = sorted((name for name, count in incoming.items() if count == 0), key=lambda name: position.get(name, (0.0, 0.0, name)))
    ordered: list[str] = []
    while ready:
        name = ready.pop(0)
        ordered.append(name)
        for target in sorted(outgoing.get(name, []), key=lambda item: position.get(item, (0.0, 0.0, item))):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
        ready.sort(key=lambda item: position.get(item, (0.0, 0.0, item)))

    if len(ordered) < len(node_names):
        remaining = [name for name in node_names if name not in set(ordered)]
        ordered.extend(sorted(remaining, key=lambda name: position.get(name, (0.0, 0.0, name))))
    return ordered


def list_workflow_graphs() -> list[dict[str, Any]]:
    if bpy is None:
        return []
    graphs = []
    for tree in bpy.data.node_groups:
        if getattr(tree, "bl_idname", "") == NODETREE_IDNAME:
            graphs.append(inspect_workflow_graph(tree.name, include_results=False))
    return graphs


def create_workflow_graph(name: str = NODETREE_LABEL, with_default_nodes: bool = False):
    if bpy is None:
        raise RuntimeError("Blender is required to create workflow graphs.")
    name = (name or NODETREE_LABEL).strip() or NODETREE_LABEL
    tree = bpy.data.node_groups.get(name)
    if tree is None or getattr(tree, "bl_idname", "") != NODETREE_IDNAME:
        tree = bpy.data.node_groups.new(name, NODETREE_IDNAME)
    if with_default_nodes:
        if not tree.nodes:
            for blueprint in workflow_graph_blueprint(True):
                add_workflow_node(tree.name, blueprint["node_type"], label=blueprint["label"], location=tuple(blueprint["location"]))
        else:
            ensure_workflow_root_nodes(tree)
    return tree


def add_workflow_node(graph_name: str, node_type: str, label: str = "", location: tuple[float, float] | None = None):
    if bpy is None:
        raise RuntimeError("Blender is required to add workflow nodes.")
    tree = _find_graph(graph_name)
    normalized = normalize_node_type(node_type)
    node = tree.nodes.new(NODE_TYPES[normalized]["idname"])
    node.name = _unique_node_name(tree, label or NODE_TYPES[normalized]["label"])
    node.label = label or NODE_TYPES[normalized]["label"]
    node["node_type"] = normalized
    node["node_label"] = NODE_TYPES[normalized]["label"]
    node["node_category"] = NODE_TYPES[normalized]["category"]
    node["node_purity"] = NODE_TYPES[normalized]["purity"]
    node["node_uses_flow"] = bool(NODE_TYPES[normalized]["uses_flow"])
    node["node_description"] = NODE_TYPES[normalized].get("description", "")
    node["tool_name"] = ""
    node["arguments_json"] = "{}"
    node["memory_query"] = ""
    node["approval_required"] = workflow_node_is_action(normalized)
    node["status"] = "idle"
    node["last_result"] = ""
    node["last_error"] = ""
    if location is not None:
        node.location = location
    return node


def connect_workflow_nodes(graph_name: str, from_node: str, from_socket: str, to_node: str, to_socket: str) -> dict[str, Any]:
    if bpy is None:
        raise RuntimeError("Blender is required to connect workflow nodes.")
    tree = _find_graph(graph_name)
    source = _find_node(tree, from_node)
    target = _find_node(tree, to_node)
    out_socket = source.outputs.get(from_socket) or (source.outputs[0] if source.outputs else None)
    in_socket = target.inputs.get(to_socket) or (target.inputs[0] if target.inputs else None)
    if out_socket is None or in_socket is None:
        raise RuntimeError("Could not resolve workflow node sockets.")
    source_type = _socket_kind_for_socket(source, out_socket, "outputs")
    target_type = _socket_kind_for_socket(target, in_socket, "inputs")
    if source_type != "any" and target_type != "any" and source_type != target_type:
        raise RuntimeError(
            f"Cannot connect {source.name}:{out_socket.name} ({source_type}) to {target.name}:{in_socket.name} ({target_type})."
        )
    tree.links.new(out_socket, in_socket)
    return {"graph": tree.name, "from": source.name, "to": target.name}


def set_workflow_node_config(graph_name: str, node_name: str, config: dict[str, Any]) -> dict[str, Any]:
    if bpy is None:
        raise RuntimeError("Blender is required to configure workflow nodes.")
    tree = _find_graph(graph_name)
    node = _find_node(tree, node_name)
    previous_type = _tree_node_type(node)
    config = validate_node_config(config)
    if "node_type" in config:
        node["node_type"] = config["node_type"]
        if config["node_type"] != previous_type:
            _refresh_node_sockets(node)
            node["node_label"] = NODE_TYPES[config["node_type"]]["label"]
            node["node_category"] = NODE_TYPES[config["node_type"]]["category"]
            node["node_purity"] = NODE_TYPES[config["node_type"]]["purity"]
            node["node_uses_flow"] = bool(NODE_TYPES[config["node_type"]]["uses_flow"])
            node["node_description"] = NODE_TYPES[config["node_type"]].get("description", "")
    for key in ("tool_name", "arguments_json", "memory_query", "status", "last_result", "last_error"):
        if key in config:
            node[key] = str(config[key])
    if "approval_required" in config:
        node["approval_required"] = bool(config["approval_required"])
    return _node_payload(node, include_results=True)


def inspect_workflow_graph(graph_name: str, include_results: bool = True) -> dict[str, Any]:
    if bpy is None:
        return {}
    tree = _find_graph(graph_name)
    return {
        "name": tree.name,
        "node_tree": NODETREE_IDNAME,
        "nodes": [_node_payload(node, include_results=include_results) for node in tree.nodes],
        "links": [
            {
                "from_node": link.from_node.name,
                "from_socket": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket": link.to_socket.name,
            }
            for link in tree.links
        ],
    }


def run_workflow_graph(
    graph_name: str,
    *,
    preview_only: bool,
    tool_runner: Callable[[str, dict[str, Any]], dict[str, Any]],
    memory_reader: Callable[[str], dict[str, Any]],
    toolbox_runner: Callable[[str], dict[str, Any]],
    asset_searcher: Callable[[dict[str, Any]], dict[str, Any]],
    prompt_reader: Callable[[], str],
) -> dict[str, Any]:
    if bpy is None:
        raise RuntimeError("Blender is required to run workflow graphs.")
    tree = _find_graph(graph_name)
    results = []
    for node in _execution_order(tree):
        node_type = _tree_node_type(node)
        node["status"] = "preview" if preview_only else "running"
        try:
            result = _run_node(
                node,
                node_type,
                preview_only=preview_only,
                tool_runner=tool_runner,
                memory_reader=memory_reader,
                toolbox_runner=toolbox_runner,
                asset_searcher=asset_searcher,
                prompt_reader=prompt_reader,
            )
        except Exception as exc:
            node["status"] = "failed"
            node["last_error"] = str(exc)
            results.append({"node": node.name, "type": node_type, "success": False, "error": str(exc)})
            break
        node["status"] = "previewed" if preview_only else "completed"
        node["last_result"] = json.dumps(result, ensure_ascii=True, default=str)[:6000]
        node["last_error"] = ""
        results.append({"node": node.name, "type": node_type, "success": True, "result": result})
        if node_type == "approval_gate" and result.get("blocked"):
            break
    return {"graph": tree.name, "preview_only": preview_only, "results": results}


class CODEXBLENDERAGENT_NodeBase:
    bl_width_default = 220
    node_type = ""

    @classmethod
    def poll(cls, ntree):
        return getattr(ntree, "bl_idname", "") == NODETREE_IDNAME

    def init(self, _context):
        _apply_node_contract_metadata(self)
        _refresh_node_sockets(self)

    def draw_label(self) -> str:
        return self.bl_label

    def draw_buttons(self, _context, layout):
        spec = workflow_node_contract_summary(str(self.get("node_type", self.node_type)))
        layout.label(text=f"Type: {spec.get('label', self.get('node_type', self.node_type))}")
        layout.label(text=f"Category: {spec.get('category', '')}")
        layout.label(text=f"Purity: {spec.get('purity', '')}")
        layout.label(text=f"Flow: {'yes' if spec.get('uses_flow') else 'no'}")
        if spec.get("description"):
            layout.label(text=str(spec["description"]))
        if spec.get("required_context"):
            layout.label(text=f"Requires: {spec['required_context']}")
        if spec.get("output_type"):
            layout.label(text=f"Output: {spec['output_type']}")
        _draw_node_idprop(layout, self, "tool_name", "Tool")
        _draw_node_idprop(layout, self, "arguments_json", "Args JSON")
        _draw_node_idprop(layout, self, "memory_query", "Memory/Asset")
        _draw_node_idprop(layout, self, "approval_required", "Approval")
        layout.label(text=f"Status: {self.get('status', 'idle')}")
        result = self.get("last_result", "")
        if result:
            layout.label(text=f"Result: {str(result)[:80]}")
        error = self.get("last_error", "")
        if error:
            layout.label(text=f"Error: {str(error)[:80]}")


def _apply_node_contract_metadata(node) -> None:
    contract = node_contract(str(getattr(node, "node_type", getattr(node, "get", lambda *_: "")("node_type", ""))))
    node["node_type"] = contract["node_type"]
    node["node_label"] = contract["label"]
    node["node_category"] = contract["category"]
    node["node_purity"] = contract["purity"]
    node["node_uses_flow"] = bool(contract["uses_flow"])
    node["node_description"] = contract.get("description", "")
    node["tool_name"] = ""
    node["arguments_json"] = "{}"
    node["memory_query"] = ""
    node["approval_required"] = workflow_node_is_action(contract["node_type"])
    node["status"] = "idle"
    node["last_result"] = ""
    node["last_error"] = ""


def _refresh_node_sockets(node) -> None:
    if bpy is None:
        return
    contract = node_contract(str(node.get("node_type", getattr(node, "node_type", ""))))
    try:
        while node.inputs:
            node.inputs.remove(node.inputs[0])
    except Exception:
        pass
    try:
        while node.outputs:
            node.outputs.remove(node.outputs[0])
    except Exception:
        pass
    for spec in contract["inputs"]:
        socket = node.inputs.new(WORKFLOW_SOCKET_CLASSES[spec["kind"]].bl_idname, spec["name"])
        if spec.get("multi_input") and hasattr(socket, "link_limit"):
            socket.link_limit = 4096
        try:
            socket["workflow_socket_kind"] = spec["kind"]
        except Exception:
            pass
    for spec in contract["outputs"]:
        socket = node.outputs.new(WORKFLOW_SOCKET_CLASSES[spec["kind"]].bl_idname, spec["name"])
        try:
            socket["workflow_socket_kind"] = spec["kind"]
        except Exception:
            pass


class CODEXBLENDERAGENT_NodeTree(bpy.types.NodeTree if bpy is not None else object):  # type: ignore[misc]
    bl_idname = NODETREE_IDNAME
    bl_label = NODETREE_LABEL
    bl_icon = "NODETREE"

    @classmethod
    def poll(cls, _context):
        return True

    @classmethod
    def valid_socket_type(cls, socket_type):
        return socket_type in {socket_cls.bl_idname for socket_cls in WORKFLOW_SOCKET_CLASSES.values()} or socket_type == "NodeSocketString"


def _node_class(name: str, node_type: str, label: str, *, idname_override: str | None = None):
    contract = node_contract(node_type)
    return type(
        name,
        (CODEXBLENDERAGENT_NodeBase, bpy.types.Node if bpy is not None else object),
        {"__module__": __name__, "bl_idname": idname_override or contract["idname"], "bl_label": label, "node_type": node_type},
    )


CODEXBLENDERAGENT_WorkflowInputNode = _node_class("CODEXBLENDERAGENT_WorkflowInputNode", "workflow_input", "Workflow Input")
CODEXBLENDERAGENT_WorkflowOutputNode = _node_class("CODEXBLENDERAGENT_WorkflowOutputNode", "workflow_output", "Workflow Output")
CODEXBLENDERAGENT_ValueNode = _node_class("CODEXBLENDERAGENT_ValueNode", "value", "Value")
CODEXBLENDERAGENT_ContextMergeNode = _node_class("CODEXBLENDERAGENT_ContextMergeNode", "context_merge", "Context Merge")
CODEXBLENDERAGENT_AssistantCallNode = _node_class("CODEXBLENDERAGENT_AssistantCallNode", "assistant_call", "Assistant Call")
CODEXBLENDERAGENT_RouteNode = _node_class("CODEXBLENDERAGENT_RouteNode", "route", "Route")
CODEXBLENDERAGENT_ForEachNode = _node_class("CODEXBLENDERAGENT_ForEachNode", "for_each", "For Each")
CODEXBLENDERAGENT_JoinNode = _node_class("CODEXBLENDERAGENT_JoinNode", "join", "Join")
CODEXBLENDERAGENT_PreviewTapNode = _node_class("CODEXBLENDERAGENT_PreviewTapNode", "preview_tap", "Preview Tap")
CODEXBLENDERAGENT_RecipeCallNode = _node_class("CODEXBLENDERAGENT_RecipeCallNode", "recipe_call", "Recipe Call")
CODEXBLENDERAGENT_SceneSnapshotNode = _node_class("CODEXBLENDERAGENT_SceneSnapshotNode", "scene_snapshot", "Scene Snapshot")
CODEXBLENDERAGENT_SelectionNode = _node_class("CODEXBLENDERAGENT_SelectionNode", "selection", "Selection")
CODEXBLENDERAGENT_ThreadMemoryNode = _node_class("CODEXBLENDERAGENT_ThreadMemoryNode", "thread_memory", "Thread Memory")
CODEXBLENDERAGENT_ToolCallNode = _node_class("CODEXBLENDERAGENT_ToolCallNode", "tool_call", "Tool Call")
CODEXBLENDERAGENT_AssetSearchNode = _node_class("CODEXBLENDERAGENT_AssetSearchNode", "asset_search", "Asset Search")
CODEXBLENDERAGENT_ApprovalGateNode = _node_class("CODEXBLENDERAGENT_ApprovalGateNode", "approval_gate", "Approval Gate")
CODEXBLENDERAGENT_AssistantPromptNode = _node_class("CODEXBLENDERAGENT_AssistantPromptNode", "assistant_prompt", "Assistant Prompt")
CODEXBLENDERAGENT_PublishAssetNode = _node_class("CODEXBLENDERAGENT_PublishAssetNode", "publish_asset", "Publish Asset")
CODEXBLENDERAGENT_ToolboxRecipeNode = _node_class(
    "CODEXBLENDERAGENT_ToolboxRecipeNode",
    "toolbox_recipe",
    "Toolbox Recipe",
    idname_override="CODEXBLENDERAGENT_ToolboxRecipeNode",
)


class CODEXBLENDERAGENT_OT_create_workflow_tree(bpy.types.Operator if bpy is not None else object):  # type: ignore[misc]
    bl_idname = "codex_blender_agent.create_workflow_tree"
    bl_label = "Create AI Workflow Graph"
    bl_description = "Create or open a blank Codex AI Workflow node graph. Starter templates are explicit."

    with_default_nodes: BoolProperty(  # type: ignore[var-annotated]
        name="Create starter nodes",
        description="Compatibility option for explicit starter graphs.",
        default=False,
    )

    def execute(self, context):
        tree = create_workflow_graph(NODETREE_LABEL, with_default_nodes=self.with_default_nodes)
        _show_graph_in_area(context, tree)
        return {"FINISHED"}


class NODE_MT_codex_ai_workflow_add(bpy.types.Menu if bpy is not None else object):  # type: ignore[misc]
    bl_idname = "NODE_MT_codex_ai_workflow_add"
    bl_label = "Codex AI Workflow"

    @classmethod
    def poll(cls, context):
        return is_codex_workflow_context(context)

    def draw(self, context):
        layout = self.layout
        for section in workflow_node_menu_sections():
            layout.label(text=section["label"])
            for entry in section["entries"]:
                op = layout.operator("codex_blender_agent.add_workflow_node", text=entry["label"], icon="NODE")
                op.node_type = entry["node_type"]
            layout.separator()


def is_codex_workflow_context(context) -> bool:
    space = getattr(context, "space_data", None)
    if space is None or getattr(space, "type", "") != "NODE_EDITOR":
        return False
    node_tree = getattr(space, "node_tree", None)
    return getattr(space, "tree_type", "") == NODETREE_IDNAME or getattr(node_tree, "bl_idname", "") == NODETREE_IDNAME


def _draw_codex_node_add_menu(self, context) -> None:
    if is_codex_workflow_context(context):
        self.layout.separator()
        self.layout.menu(NODE_MT_codex_ai_workflow_add.bl_idname, icon="NODETREE")


def _find_graph(name: str):
    graph_name = (name or NODETREE_LABEL).strip() or NODETREE_LABEL
    tree = bpy.data.node_groups.get(graph_name)
    if tree is None or getattr(tree, "bl_idname", "") != NODETREE_IDNAME:
        raise RuntimeError(f"Workflow graph not found: {graph_name}")
    return tree


def _find_node(tree, node_name: str):
    node = tree.nodes.get(node_name)
    if node is None:
        raise RuntimeError(f"Workflow node not found: {node_name}")
    return node


def _tree_node_type(node) -> str:
    return canonical_node_type(str(getattr(node, "get", lambda *_: "")("node_type", _node_type_from_idname(node.bl_idname))))


def _socket_kind_for_socket(node, socket, direction: str) -> str:
    kind = ""
    try:
        kind = str(socket.get("workflow_socket_kind", ""))
    except Exception:
        kind = ""
    if kind:
        return kind
    node_type = _tree_node_type(node)
    specs = workflow_node_socket_specs(node_type)[direction]
    for spec in specs:
        if spec["name"] == socket.name:
            return str(spec["kind"])
    return "any"


def _unique_node_name(tree, base_name: str) -> str:
    if tree.nodes.get(base_name) is None:
        return base_name
    index = 2
    while tree.nodes.get(f"{base_name} {index}") is not None:
        index += 1
    return f"{base_name} {index}"


def _node_payload(node, include_results: bool) -> dict[str, Any]:
    contract = workflow_node_contract_summary(_tree_node_type(node))
    payload = {
        "name": node.name,
        "label": node.label or node.name,
        "node_type": contract["node_type"],
        "node_label": contract["label"],
        "node_category": contract["category"],
        "node_purity": contract["purity"],
        "node_uses_flow": bool(contract["uses_flow"]),
        "required_context": contract.get("required_context", ""),
        "output_type": contract.get("output_type", ""),
        "description": contract.get("description", ""),
        "tool_name": node.get("tool_name", ""),
        "arguments_json": node.get("arguments_json", "{}"),
        "memory_query": node.get("memory_query", ""),
        "approval_required": bool(node.get("approval_required", False)),
        "status": node.get("status", "idle"),
        "socket_inputs": workflow_node_socket_specs(contract["node_type"])["inputs"],
        "socket_outputs": workflow_node_socket_specs(contract["node_type"])["outputs"],
    }
    if include_results:
        payload["last_result"] = node.get("last_result", "")
        payload["last_error"] = node.get("last_error", "")
    return payload


def _execution_order(tree) -> list[Any]:
    nodes = [
        {
            "name": node.name,
            "location": [float(node.location.x), float(node.location.y)],
        }
        for node in tree.nodes
    ]
    links = [
        {
            "from_node": link.from_node.name,
            "to_node": link.to_node.name,
        }
        for link in tree.links
    ]
    order = compute_execution_order(nodes, links)
    by_name = {node.name: node for node in tree.nodes}
    return [by_name[name] for name in order if name in by_name]


def _run_node(
    node,
    node_type: str,
    *,
    preview_only: bool,
    tool_runner,
    memory_reader,
    toolbox_runner,
    asset_searcher,
    prompt_reader,
) -> dict[str, Any]:
    args = parse_arguments_json(node.get("arguments_json", "{}"))
    if node_type == "workflow_input":
        return {"preview": True, "node_type": node_type, "label": node.label, "contract": workflow_node_contract_summary(node_type)}
    if node_type == "workflow_output":
        return {"preview": True, "node_type": node_type, "label": node.label, "inputs": args, "contract": workflow_node_contract_summary(node_type)}
    if node_type == "value":
        value = args.get("value", node.get("memory_query", ""))
        return {"preview": True, "value": value, "value_type": args.get("value_type", "string")} if preview_only else {"value": value, "value_type": args.get("value_type", "string")}
    if node_type == "context_merge":
        return {"preview": True, "merged_context": args} if preview_only else {"merged_context": args}
    if node_type == "scene_snapshot":
        return {"preview": True, "tool": "get_scene_summary"} if preview_only else tool_runner("get_scene_summary", {})
    if node_type == "selection":
        return {"preview": True, "tool": "get_selection"} if preview_only else tool_runner("get_selection", {})
    if node_type == "thread_memory":
        return memory_reader(str(node.get("memory_query", "")))
    if node_type == "assistant_call":
        payload = {"prompt": node.get("memory_query", "") or args.get("prompt", ""), "arguments": args, "schema": node.get("node_output_schema", "")}
        return {"preview": True, **payload} if preview_only else {"assistant_call": payload, "result": "submitted"}
    if node_type == "tool_call":
        tool_name = str(node.get("tool_name", "")).strip()
        if not tool_name:
            raise RuntimeError("Tool Call node requires tool_name.")
        return {"preview": True, "tool": tool_name, "arguments": args} if preview_only else tool_runner(tool_name, args)
    if node_type in {"toolbox_recipe", "recipe_call"}:
        recipe = str(node.get("memory_query", "") or args.get("item_id_or_name", "")).strip()
        if not recipe:
            raise RuntimeError("Recipe Call node requires memory_query or item_id_or_name.")
        return {"preview": True, "recipe": recipe} if preview_only else toolbox_runner(recipe)
    if node_type == "asset_search":
        return asset_searcher(args)
    if node_type == "approval_gate":
        blocked = bool(node.get("approval_required", False)) and not preview_only
        return {"blocked": blocked, "message": "Approval required before continuing." if blocked else "Approval gate passed."}
    if node_type == "assistant_prompt":
        return {"prompt": prompt_reader()}
    if node_type == "route":
        branch = str(args.get("branch", node.get("memory_query", "") or "default"))
        return {"preview": True, "branch": branch, "branches": [str(value) for value in args.get("branches", [])]} if preview_only else {"branch": branch, "branches": [str(value) for value in args.get("branches", [])]}
    if node_type == "for_each":
        items = args.get("items", [])
        return {"preview": True, "items": items, "count": len(items)} if preview_only else {"items": items, "count": len(items)}
    if node_type == "join":
        return {"preview": True, "joined": args} if preview_only else {"joined": args}
    if node_type == "preview_tap":
        return {"preview": True, "tap": args} if preview_only else {"tap": args}
    if node_type == "publish_asset":
        publish_args = dict(args)
        publish_args.setdefault("name", node.get("memory_query", "") or "Workflow Asset")
        return {"preview": True, "tool": "save_selection_to_asset_library", "arguments": publish_args} if preview_only else tool_runner("save_selection_to_asset_library", publish_args)
    raise RuntimeError(f"Unsupported workflow node type: {node_type}")


def _node_type_from_idname(idname: str) -> str:
    if idname in LEGACY_NODE_IDNAME_ALIASES:
        return LEGACY_NODE_IDNAME_ALIASES[idname]
    for node_type, spec in NODE_TYPES.items():
        if spec["idname"] == idname:
            return node_type
    return "tool_call"


def _show_graph_in_area(context, tree) -> None:
    area = getattr(context, "area", None)
    if area is None:
        return
    try:
        area.type = "NODE_EDITOR"
        for space in area.spaces:
            if space.type == "NODE_EDITOR":
                space.tree_type = NODETREE_IDNAME
                space.node_tree = tree
                break
    except Exception:
        pass


def _payload_position(node: dict[str, Any]) -> tuple[float, float, str]:
    location = node.get("location", [0.0, 0.0])
    try:
        x = float(location[0])
        y = float(location[1])
    except Exception:
        x = 0.0
        y = 0.0
    return (x, -y, str(node.get("name", "")))


def _draw_node_idprop(layout, node, key: str, text: str) -> None:
    try:
        layout.prop(node, f'["{key}"]', text=text)
    except Exception:
        value = node.get(key, "")
        layout.label(text=f"{text}: {str(value)[:80]}")


CLASSES = (
    *WORKFLOW_SOCKET_CLASSES.values(),
    CODEXBLENDERAGENT_NodeTree,
    CODEXBLENDERAGENT_WorkflowInputNode,
    CODEXBLENDERAGENT_WorkflowOutputNode,
    CODEXBLENDERAGENT_ValueNode,
    CODEXBLENDERAGENT_ContextMergeNode,
    CODEXBLENDERAGENT_AssistantCallNode,
    CODEXBLENDERAGENT_RouteNode,
    CODEXBLENDERAGENT_ForEachNode,
    CODEXBLENDERAGENT_JoinNode,
    CODEXBLENDERAGENT_PreviewTapNode,
    CODEXBLENDERAGENT_RecipeCallNode,
    CODEXBLENDERAGENT_SceneSnapshotNode,
    CODEXBLENDERAGENT_SelectionNode,
    CODEXBLENDERAGENT_ThreadMemoryNode,
    CODEXBLENDERAGENT_ToolCallNode,
    CODEXBLENDERAGENT_ToolboxRecipeNode,
    CODEXBLENDERAGENT_AssetSearchNode,
    CODEXBLENDERAGENT_ApprovalGateNode,
    CODEXBLENDERAGENT_AssistantPromptNode,
    CODEXBLENDERAGENT_PublishAssetNode,
    CODEXBLENDERAGENT_OT_create_workflow_tree,
    NODE_MT_codex_ai_workflow_add,
)


def register() -> None:
    if bpy is None:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if hasattr(bpy.types, "NODE_MT_add"):
        bpy.types.NODE_MT_add.append(_draw_codex_node_add_menu)


def unregister() -> None:
    if bpy is None:
        return
    if hasattr(bpy.types, "NODE_MT_add"):
        try:
            bpy.types.NODE_MT_add.remove(_draw_codex_node_add_menu)
        except Exception:
            pass
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
