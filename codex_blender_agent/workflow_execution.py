from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from .studio_state import normalize_action_status
from .tool_policy import classify_tool, strip_action_metadata


WORKFLOW_SOCKET_TYPES = (
    "Flow",
    "Context",
    "Snapshot",
    "Targets",
    "Memory",
    "Prompt",
    "AssetSet",
    "Artifact",
    "Decision",
    "Scalar",
    "Any",
)

WORKFLOW_NODE_STATES = (
    "draft",
    "ready",
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "bypassed",
    "stale",
)

WORKFLOW_NODE_CATEGORIES = (
    "Interface",
    "Context",
    "AI",
    "Assets",
    "Actions",
    "Control",
    "Recipes",
    "Layout",
)

WORKFLOW_RUN_STATES = (
    "draft",
    "ready",
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "stale",
)

RECIPE_PIN_MODES = ("exact", "compatible", "latest_within_major")

NODE_TYPE_ALIASES = {"toolbox_recipe": "recipe_call"}


@dataclass(frozen=True)
class SocketSpec:
    name: str
    socket_type: str
    direction: str
    required: bool = False
    multi_input: bool = False
    description: str = ""


@dataclass(frozen=True)
class NodeSpec:
    node_type: str
    label: str
    category: str
    pure: bool
    inputs: tuple[SocketSpec, ...]
    outputs: tuple[SocketSpec, ...]
    legacy_aliases: tuple[str, ...] = ()
    preview_mode: str = "static"
    requires_flow: bool = False
    action_kind: str = "inspect"
    description: str = ""


@dataclass(frozen=True)
class WorkflowIssue:
    severity: str
    code: str
    message: str
    node: str = ""
    socket: str = ""


@dataclass(frozen=True)
class WorkflowPlanStep:
    node_name: str
    node_type: str
    label: str
    category: str
    pure: bool
    preview_mode: str
    requires_action_card: bool
    blocked: bool
    block_reason: str
    state: str
    tool_name: str = ""
    tool_policy: dict[str, Any] = field(default_factory=dict)
    last_result_summary: str = ""
    last_error_summary: str = ""
    warning_count: int = 0
    socket_summary: dict[str, list[str]] = field(default_factory=dict)


class WorkflowExecutionError(RuntimeError):
    pass


def _socket(name: str, socket_type: str, direction: str, *, required: bool = False, multi_input: bool = False, description: str = "") -> SocketSpec:
    return SocketSpec(
        name=name,
        socket_type=socket_type,
        direction=direction,
        required=required,
        multi_input=multi_input,
        description=description,
    )


WORKFLOW_NODE_SPECS: dict[str, NodeSpec] = {
    "workflow_input": NodeSpec(
        node_type="workflow_input",
        label="Workflow Input",
        category="Interface",
        pure=True,
        inputs=(),
        outputs=(
            _socket("Flow", "Flow", "output", required=True),
            _socket("Context", "Context", "output"),
            _socket("Snapshot", "Snapshot", "output"),
            _socket("Targets", "Targets", "output"),
            _socket("Memory", "Memory", "output"),
            _socket("Prompt", "Prompt", "output"),
            _socket("AssetSet", "AssetSet", "output"),
            _socket("Artifact", "Artifact", "output"),
            _socket("Decision", "Decision", "output"),
            _socket("Scalar", "Scalar", "output"),
        ),
        description="Declares graph inputs and runtime metadata.",
    ),
    "workflow_output": NodeSpec(
        node_type="workflow_output",
        label="Workflow Output",
        category="Interface",
        pure=True,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Context", "Context", "input"),
            _socket("Artifact", "Artifact", "input"),
            _socket("Decision", "Decision", "input"),
        ),
        outputs=(),
        description="Declares graph outputs and success criteria.",
    ),
    "value": NodeSpec(
        node_type="value",
        label="Value",
        category="Interface",
        pure=True,
        inputs=(),
        outputs=(_socket("Scalar", "Scalar", "output", required=True),),
        description="Provides a literal scalar or JSON configuration value.",
    ),
    "context_merge": NodeSpec(
        node_type="context_merge",
        label="Context Merge",
        category="Context",
        pure=True,
        inputs=(_socket("Context", "Context", "input", required=True, multi_input=True),),
        outputs=(_socket("Context", "Context", "output", required=True),),
        description="Merges structured context bundles with explicit conflict policy.",
    ),
    "scene_snapshot": NodeSpec(
        node_type="scene_snapshot",
        label="Scene Snapshot",
        category="Context",
        pure=True,
        inputs=(_socket("Targets", "Targets", "input"),),
        outputs=(
            _socket("Snapshot", "Snapshot", "output", required=True),
            _socket("Context", "Context", "output"),
        ),
        description="Captures immutable scene context for preview and replay.",
    ),
    "selection": NodeSpec(
        node_type="selection",
        label="Selection",
        category="Context",
        pure=True,
        inputs=(
            _socket("Snapshot", "Snapshot", "input"),
            _socket("Context", "Context", "input"),
        ),
        outputs=(
            _socket("Targets", "Targets", "output", required=True),
            _socket("Context", "Context", "output"),
        ),
        description="Resolves a stable Blender target set from the active scene.",
    ),
    "thread_memory": NodeSpec(
        node_type="thread_memory",
        label="Thread Memory",
        category="Context",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input"),
            _socket("Context", "Context", "input"),
            _socket("Artifact", "Artifact", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Memory", "Memory", "output"),
            _socket("Context", "Context", "output"),
        ),
        preview_mode="plan_only",
        action_kind="recover",
        description="Reads or updates thread-scoped memory with explicit mode semantics.",
    ),
    "assistant_prompt": NodeSpec(
        node_type="assistant_prompt",
        label="Assistant Prompt",
        category="AI",
        pure=True,
        inputs=(
            _socket("Snapshot", "Snapshot", "input"),
            _socket("Targets", "Targets", "input"),
            _socket("Context", "Context", "input"),
            _socket("Memory", "Memory", "input"),
            _socket("Scalar", "Scalar", "input"),
        ),
        outputs=(_socket("Prompt", "Prompt", "output", required=True),),
        description="Resolves a prompt template into a previewable assistant request.",
    ),
    "assistant_call": NodeSpec(
        node_type="assistant_call",
        label="Assistant Call",
        category="AI",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input"),
            _socket("Prompt", "Prompt", "input", required=True),
            _socket("Context", "Context", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Context", "Context", "output"),
            _socket("Artifact", "Artifact", "output"),
        ),
        preview_mode="dry_run",
        description="Executes a structured assistant request and returns artifacts.",
    ),
    "asset_search": NodeSpec(
        node_type="asset_search",
        label="Asset Search",
        category="Assets",
        pure=True,
        inputs=(
            _socket("Flow", "Flow", "input"),
            _socket("Snapshot", "Snapshot", "input"),
            _socket("Targets", "Targets", "input"),
            _socket("Context", "Context", "input"),
            _socket("Scalar", "Scalar", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("AssetSet", "AssetSet", "output", required=True),
            _socket("Context", "Context", "output"),
        ),
        description="Searches asset libraries and returns ranked candidates.",
    ),
    "tool_call": NodeSpec(
        node_type="tool_call",
        label="Tool Call",
        category="Actions",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Targets", "Targets", "input"),
            _socket("Context", "Context", "input"),
            _socket("Artifact", "Artifact", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Context", "Context", "output"),
            _socket("Artifact", "Artifact", "output"),
        ),
        preview_mode="plan_only",
        action_kind="change",
        requires_flow=True,
        description="Executes one registered tool or Blender operator against structured inputs.",
    ),
    "approval_gate": NodeSpec(
        node_type="approval_gate",
        label="Approval Gate",
        category="Control",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Context", "Context", "input"),
            _socket("Artifact", "Artifact", "input"),
            _socket("Decision", "Decision", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Decision", "Decision", "output", required=True),
        ),
        description="Pauses the run until the proposed payload is approved or rejected.",
    ),
    "route": NodeSpec(
        node_type="route",
        label="Route",
        category="Control",
        pure=True,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Decision", "Decision", "input"),
            _socket("Scalar", "Scalar", "input"),
        ),
        outputs=(
            _socket("True", "Flow", "output"),
            _socket("False", "Flow", "output"),
            _socket("Default", "Flow", "output"),
        ),
        description="Branches execution by bool, enum, or state value.",
    ),
    "for_each": NodeSpec(
        node_type="for_each",
        label="For Each",
        category="Control",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Targets", "Targets", "input"),
            _socket("AssetSet", "AssetSet", "input"),
            _socket("Context", "Context", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Context", "Context", "output"),
            _socket("Artifact", "Artifact", "output"),
        ),
        preview_mode="plan_only",
        action_kind="automate",
        requires_flow=True,
        description="Executes a child workflow once per item with explicit batching rules.",
    ),
    "join": NodeSpec(
        node_type="join",
        label="Join",
        category="Control",
        pure=True,
        inputs=(
            _socket("Flow", "Flow", "input", required=True, multi_input=True),
            _socket("Context", "Context", "input", multi_input=True),
            _socket("Artifact", "Artifact", "input", multi_input=True),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Context", "Context", "output"),
            _socket("Artifact", "Artifact", "output"),
        ),
        description="Waits for branches and merges results with an explicit policy.",
    ),
    "preview_tap": NodeSpec(
        node_type="preview_tap",
        label="Preview Tap",
        category="Layout",
        pure=True,
        inputs=(_socket("Any", "Any", "input", required=True),),
        outputs=(_socket("Any", "Any", "output", required=True),),
        description="Pins an intermediate result for inspection without interrupting flow.",
    ),
    "recipe_call": NodeSpec(
        node_type="recipe_call",
        label="Recipe Call",
        category="Recipes",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Snapshot", "Snapshot", "input"),
            _socket("Targets", "Targets", "input"),
            _socket("Context", "Context", "input"),
            _socket("Memory", "Memory", "input"),
            _socket("Prompt", "Prompt", "input"),
            _socket("AssetSet", "AssetSet", "input"),
            _socket("Artifact", "Artifact", "input"),
            _socket("Decision", "Decision", "input"),
            _socket("Scalar", "Scalar", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Context", "Context", "output"),
            _socket("Artifact", "Artifact", "output"),
        ),
        legacy_aliases=("toolbox_recipe",),
        preview_mode="plan_only",
        action_kind="automate",
        requires_flow=True,
        description="Calls a version-pinned reusable recipe asset.",
    ),
    "publish_asset": NodeSpec(
        node_type="publish_asset",
        label="Publish Asset",
        category="Assets",
        pure=False,
        inputs=(
            _socket("Flow", "Flow", "input", required=True),
            _socket("Targets", "Targets", "input"),
            _socket("Context", "Context", "input"),
            _socket("Artifact", "Artifact", "input"),
        ),
        outputs=(
            _socket("Flow", "Flow", "output"),
            _socket("Artifact", "Artifact", "output"),
            _socket("Context", "Context", "output"),
        ),
        preview_mode="plan_only",
        action_kind="export",
        requires_flow=True,
        description="Publishes approved outputs into an asset library or file destination.",
    ),
}


def list_workflow_node_categories() -> tuple[str, ...]:
    return WORKFLOW_NODE_CATEGORIES


def list_workflow_node_types() -> tuple[str, ...]:
    return tuple(WORKFLOW_NODE_SPECS.keys())


def normalize_workflow_node_type(node_type: str) -> str:
    value = (node_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    value = NODE_TYPE_ALIASES.get(value, value)
    if value not in WORKFLOW_NODE_SPECS:
        valid = ", ".join(sorted(WORKFLOW_NODE_SPECS))
        raise ValueError(f"Unsupported workflow node type: {node_type}. Valid types: {valid}")
    return value


def normalize_recipe_pin_mode(pin_mode: str) -> str:
    value = (pin_mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in RECIPE_PIN_MODES else "compatible"


def get_workflow_node_spec(node_type: str, node: dict[str, Any] | None = None) -> NodeSpec:
    normalized = normalize_workflow_node_type(node_type)
    spec = WORKFLOW_NODE_SPECS[normalized]
    if normalized == "thread_memory" and node is not None:
        mode = str(node.get("mode", "read")).strip().lower().replace("-", "_")
        if mode in {"append", "summarize"}:
            return NodeSpec(
                node_type=spec.node_type,
                label=spec.label,
                category=spec.category,
                pure=False,
                inputs=(
                    _socket("Flow", "Flow", "input", required=True),
                    _socket("Context", "Context", "input"),
                    _socket("Artifact", "Artifact", "input"),
                ),
                outputs=spec.outputs,
                legacy_aliases=spec.legacy_aliases,
                preview_mode="plan_only",
                action_kind="recover",
                requires_flow=True,
                description=spec.description,
            )
    return spec


def socket_types_compatible(source_type: str, target_type: str) -> bool:
    source = (source_type or "").strip()
    target = (target_type or "").strip()
    if not source or not target:
        return False
    if source == target:
        return True
    if "Any" in {source, target}:
        return True
    return False


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return strip_action_metadata(arguments)
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        if isinstance(parsed, dict):
            return strip_action_metadata(parsed)
        return {"value": parsed}
    return {"value": arguments}


def _socket_signature(socket: SocketSpec) -> dict[str, Any]:
    return {
        "name": socket.name,
        "socket_type": socket.socket_type,
        "direction": socket.direction,
        "required": socket.required,
        "multi_input": socket.multi_input,
        "description": socket.description,
    }


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    value = dict(node or {})
    value["name"] = str(value.get("name", "")).strip()
    value["label"] = str(value.get("label", value["name"])).strip() or value["name"]
    value["node_type"] = normalize_workflow_node_type(str(value.get("node_type", "tool_call")))
    value["state"] = str(value.get("state", "draft")).strip().lower().replace("-", "_").replace(" ", "_") or "draft"
    value["freshness"] = str(value.get("freshness", "clean")).strip() or "clean"
    value["risk_level"] = str(value.get("risk_level", "none")).strip() or "none"
    value["warning_count"] = int(value.get("warning_count", 0) or 0)
    value["last_run_id"] = str(value.get("last_run_id", "")).strip()
    value["last_updated_at"] = str(value.get("last_updated_at", "")).strip()
    value["last_duration_ms"] = int(value.get("last_duration_ms", 0) or 0)
    value["last_cost"] = value.get("last_cost", 0)
    value["last_result_summary"] = str(value.get("last_result_summary", "")).strip()
    value["last_error_summary"] = str(value.get("last_error_summary", "")).strip()
    value["action_card_ref"] = str(value.get("action_card_ref", "")).strip()
    value["tool_name"] = str(value.get("tool_name", "")).strip()
    value["arguments"] = _normalize_arguments(value.get("arguments", value.get("arguments_json", {})))
    value["approval_policy"] = str(value.get("approval_policy", "")).strip()
    value["enabled"] = bool(value.get("enabled", True))
    value["bypass"] = bool(value.get("bypass", False))
    value["cache_policy"] = str(value.get("cache_policy", "default")).strip() or "default"
    value["timeout_s"] = int(value.get("timeout_s", 0) or 0)
    value["retry_limit"] = int(value.get("retry_limit", 0) or 0)
    value["dry_run_supported"] = bool(value.get("dry_run_supported", True))
    value["snapshot_hash"] = str(value.get("snapshot_hash", "")).strip()
    value["graph_hash"] = str(value.get("graph_hash", "")).strip()
    value["version"] = str(value.get("version", "")).strip()
    value["node_revision"] = int(value.get("node_revision", 0) or 0)
    return value


def _normalize_link(link: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_node": str(link.get("from_node", "")).strip(),
        "from_socket": str(link.get("from_socket", "")).strip() or "Flow",
        "to_node": str(link.get("to_node", "")).strip(),
        "to_socket": str(link.get("to_socket", "")).strip() or "Flow",
    }


def normalize_workflow_graph(graph: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(graph or {})
    value["name"] = str(value.get("name", "")).strip() or "Codex AI Workflow"
    value["metadata"] = dict(value.get("metadata", {}) or {})
    value["nodes"] = [_normalize_node(node) for node in value.get("nodes", []) or []]
    value["links"] = [_normalize_link(link) for link in value.get("links", []) or []]
    return value


def ensure_workflow_root_nodes(graph: dict[str, Any]) -> dict[str, Any]:
    value = normalize_workflow_graph(graph)
    node_types = {node["node_type"] for node in value["nodes"]}
    if "workflow_input" not in node_types:
        value["nodes"].insert(0, _normalize_node({"name": "Workflow Input", "label": "Workflow Input", "node_type": "workflow_input"}))
    if "workflow_output" not in node_types:
        value["nodes"].append(_normalize_node({"name": "Workflow Output", "label": "Workflow Output", "node_type": "workflow_output"}))
    return value


def workflow_graph_manifest(graph: dict[str, Any]) -> dict[str, Any]:
    normalized = ensure_workflow_root_nodes(graph)
    nodes = []
    for node in sorted(normalized["nodes"], key=lambda item: item["name"]):
        spec = get_workflow_node_spec(node["node_type"], node)
        nodes.append(
            {
                "name": node["name"],
                "label": node["label"],
                "node_type": spec.node_type,
                "category": spec.category,
                "pure": spec.pure,
                "preview_mode": spec.preview_mode,
                "inputs": [_socket_signature(socket) for socket in spec.inputs],
                "outputs": [_socket_signature(socket) for socket in spec.outputs],
                "tool_name": node.get("tool_name", ""),
                "arguments": _normalize_arguments(node.get("arguments")),
                "approval_policy": node.get("approval_policy", ""),
                "risk_level": node.get("risk_level", ""),
                "cache_policy": node.get("cache_policy", "default"),
                "timeout_s": int(node.get("timeout_s", 0) or 0),
                "retry_limit": int(node.get("retry_limit", 0) or 0),
                "enabled": bool(node.get("enabled", True)),
                "bypass": bool(node.get("bypass", False)),
                "dry_run_supported": bool(node.get("dry_run_supported", True)),
                "version": node.get("version", ""),
                "node_revision": int(node.get("node_revision", 0) or 0),
            }
        )
    links = sorted((_normalize_link(link) for link in normalized["links"]), key=lambda item: (item["from_node"], item["from_socket"], item["to_node"], item["to_socket"]))
    return {"name": normalized["name"], "metadata": normalized["metadata"], "nodes": nodes, "links": links}


def workflow_graph_hash(graph: dict[str, Any]) -> str:
    payload = json.dumps(workflow_graph_manifest(graph), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workflow_add_menu_entries() -> list[dict[str, str]]:
    entries = []
    for node_type, spec in WORKFLOW_NODE_SPECS.items():
        entries.append({"category": spec.category, "node_type": node_type, "label": spec.label, "description": spec.description})
    return entries


def _graph_node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in graph.get("nodes", []) or [] if node.get("name")}


def _graph_link_map(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for link in graph.get("links", []) or []:
        normalized = _normalize_link(link)
        by_target.setdefault(normalized["to_node"], []).append(normalized)
    return by_target


def _socket_map(sockets: tuple[SocketSpec, ...]) -> dict[str, SocketSpec]:
    return {socket.name: socket for socket in sockets}


def _resolve_socket(spec: NodeSpec, socket_name: str, direction: str) -> SocketSpec | None:
    sockets = spec.inputs if direction == "input" else spec.outputs
    if not sockets:
        return None
    by_name = _socket_map(sockets)
    if socket_name in by_name:
        return by_name[socket_name]
    if socket_name and socket_name in {socket.socket_type for socket in sockets}:
        return next(socket for socket in sockets if socket.socket_type == socket_name)
    return sockets[0]


def _topological_order(graph: dict[str, Any]) -> tuple[list[str], list[str]]:
    nodes = _graph_node_map(graph)
    links = [_normalize_link(link) for link in graph.get("links", []) or []]
    incoming: dict[str, int] = {name: 0 for name in nodes}
    outgoing: dict[str, list[str]] = {name: [] for name in nodes}
    for link in links:
        if link["from_node"] not in nodes or link["to_node"] not in nodes:
            continue
        if link["from_node"] == link["to_node"]:
            continue
        outgoing[link["from_node"]].append(link["to_node"])
        incoming[link["to_node"]] += 1
    ready = sorted(name for name, count in incoming.items() if count == 0)
    ordered: list[str] = []
    while ready:
        node_name = ready.pop(0)
        ordered.append(node_name)
        for target in sorted(outgoing.get(node_name, [])):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
        ready.sort()
    remaining = [name for name in nodes if name not in ordered]
    if remaining:
        ordered.extend(sorted(remaining))
    cycles = [name for name, count in incoming.items() if count > 0]
    return ordered, cycles


def _reachable_nodes(graph: dict[str, Any]) -> set[str]:
    nodes = _graph_node_map(graph)
    adjacency: dict[str, set[str]] = {name: set() for name in nodes}
    for link in graph.get("links", []) or []:
        normalized = _normalize_link(link)
        if normalized["from_node"] in nodes and normalized["to_node"] in nodes:
            adjacency[normalized["from_node"]].add(normalized["to_node"])
    roots = [name for name, node in nodes.items() if node.get("node_type") == "workflow_input"]
    if not roots:
        roots = [next(iter(nodes), "")] if nodes else []
    seen: set[str] = set()
    stack = [root for root in roots if root]
    while stack:
        node_name = stack.pop()
        if node_name in seen:
            continue
        seen.add(node_name)
        stack.extend(sorted(adjacency.get(node_name, ())))
    return seen


def _source_socket_spec(graph: dict[str, Any], node_name: str, socket_name: str) -> SocketSpec | None:
    node = _graph_node_map(graph).get(node_name)
    if node is None:
        return None
    spec = get_workflow_node_spec(node["node_type"], node)
    return _resolve_socket(spec, socket_name, "output")


def _target_socket_spec(graph: dict[str, Any], node_name: str, socket_name: str) -> SocketSpec | None:
    node = _graph_node_map(graph).get(node_name)
    if node is None:
        return None
    spec = get_workflow_node_spec(node["node_type"], node)
    return _resolve_socket(spec, socket_name, "input")


def _resolve_approved_card(node: dict[str, Any], approved_cards: Iterable[dict[str, Any] | str]) -> dict[str, Any]:
    card_ref = str(node.get("action_card_ref", "")).strip()
    cards: list[dict[str, Any]] = []
    for item in approved_cards:
        if isinstance(item, str):
            cards.append({"action_id": item})
        elif isinstance(item, dict):
            cards.append(dict(item))
    if card_ref:
        for card in cards:
            if str(card.get("action_id", "")).strip() == card_ref:
                return card
        return {}
    for card in cards:
        if str(card.get("action_id", "")).strip():
            return card
    return {}


def node_requires_action_card(node: dict[str, Any], approved_cards: Iterable[dict[str, Any] | str] | None = None) -> bool:
    spec = get_workflow_node_spec(node.get("node_type", ""), node)
    if node.get("approval_required") is True:
        return True
    if spec.node_type in {"workflow_input", "workflow_output", "value", "context_merge", "preview_tap", "route", "join", "scene_snapshot", "selection", "asset_search", "assistant_prompt"}:
        return False
    tool_name = str(node.get("tool_name", "")).strip()
    if spec.node_type == "assistant_call":
        return False
    if spec.node_type == "recipe_call" and node.get("approval_policy"):
        return True
    if tool_name:
        policy = classify_tool(tool_name)
        return policy.requires_action or policy.requires_expert
    return False


def requires_action_card_for_tool(tool_name: str) -> bool:
    return classify_tool(tool_name).requires_action


def node_can_preview(node: dict[str, Any]) -> bool:
    spec = get_workflow_node_spec(node.get("node_type", ""), node)
    if spec.pure:
        return True
    if spec.preview_mode in {"static", "dry_run"}:
        return True
    tool_name = str(node.get("tool_name", "")).strip()
    if tool_name:
        policy = classify_tool(tool_name)
        return policy.category in {"read_only", "preview_safe", "action_store"}
    return False


def node_preview_mode(node: dict[str, Any]) -> str:
    spec = get_workflow_node_spec(node.get("node_type", ""), node)
    if spec.pure:
        return "static"
    if spec.preview_mode == "dry_run" and not node.get("dry_run_supported", True):
        return "plan_only"
    return spec.preview_mode


def node_execution_policy(node: dict[str, Any], approved_cards: Iterable[dict[str, Any] | str] | None = None) -> dict[str, Any]:
    normalized = _normalize_node(node)
    card_required = node_requires_action_card(normalized, approved_cards=approved_cards)
    tool_name = str(normalized.get("tool_name", "")).strip()
    policy = classify_tool(tool_name) if tool_name else None
    approved_card = _resolve_approved_card(normalized, approved_cards or [])
    card_status = normalize_action_status(str(approved_card.get("status", ""))) if approved_card else ""
    card_stale = is_action_card_stale(
        approved_card or normalized,
        current_snapshot_hash=str(normalized.get("snapshot_hash", "")),
        current_graph_hash=str(normalized.get("graph_hash", "")),
    ) if (approved_card or normalized.get("action_card_ref")) else False
    allowed = True
    reasons = []
    if card_required:
        if not approved_card:
            allowed = False
            reasons.append("Action card required.")
        elif card_status not in {"approved", "running"}:
            allowed = False
            reasons.append(f"Action card must be approved or running, not {card_status or 'missing'}.")
    if card_stale:
        allowed = False
        reasons.append("Action card is stale.")
    if policy and policy.requires_expert:
        allowed = False
        reasons.append("Expert mode required.")
    return {
        "node_name": normalized["name"],
        "node_type": normalized["node_type"],
        "requires_action_card": card_required,
        "approved_card": approved_card or {},
        "approved_card_status": card_status,
        "allowed": allowed,
        "reasons": reasons,
        "tool_policy": {
            "name": policy.name,
            "category": policy.category,
            "risk": policy.risk,
            "requires_action": policy.requires_action,
            "requires_expert": policy.requires_expert,
        }
        if policy
        else {},
        "preview_mode": node_preview_mode(normalized),
    }


def _preview_summary_for_step(step: dict[str, Any]) -> str:
    if step["pure"]:
        return f"Preview {step['label']} safely."
    if step["preview_mode"] == "dry_run":
        return f"Dry-run {step['label']} without committing side effects."
    return f"Plan-only preview for {step['label']}."


def validate_workflow_graph(
    graph: dict[str, Any],
    *,
    auto_create_roots: bool = False,
    approved_cards: Iterable[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    normalized = ensure_workflow_root_nodes(graph) if auto_create_roots else normalize_workflow_graph(graph)
    issues: list[WorkflowIssue] = []
    nodes = _graph_node_map(normalized)
    if not normalized["name"]:
        issues.append(WorkflowIssue("error", "graph_name_missing", "Workflow graph needs a name."))
    if not nodes:
        issues.append(WorkflowIssue("error", "graph_nodes_missing", "Workflow graph has no nodes."))

    if "workflow_input" not in {node["node_type"] for node in normalized["nodes"]}:
        issues.append(WorkflowIssue("warning", "workflow_input_missing", "Workflow Input is missing."))
    if "workflow_output" not in {node["node_type"] for node in normalized["nodes"]}:
        issues.append(WorkflowIssue("warning", "workflow_output_missing", "Workflow Output is missing."))

    seen_names: set[str] = set()
    for node in normalized["nodes"]:
        if not node["name"]:
            issues.append(WorkflowIssue("error", "node_name_missing", "Every workflow node needs a name."))
            continue
        if node["name"] in seen_names:
            issues.append(WorkflowIssue("error", "node_name_duplicate", f"Duplicate node name: {node['name']}", node=node["name"]))
        seen_names.add(node["name"])
        if node.get("state") not in WORKFLOW_NODE_STATES:
            issues.append(WorkflowIssue("warning", "node_state_unknown", f"Unknown node state for {node['name']}: {node.get('state')}", node=node["name"]))

    for link in normalized["links"]:
        if link["from_node"] not in nodes:
            issues.append(WorkflowIssue("error", "link_source_missing", f"Link source node not found: {link['from_node']}", node=link["from_node"]))
            continue
        if link["to_node"] not in nodes:
            issues.append(WorkflowIssue("error", "link_target_missing", f"Link target node not found: {link['to_node']}", node=link["to_node"]))
            continue
        source_spec = _source_socket_spec(normalized, link["from_node"], link["from_socket"])
        target_spec = _target_socket_spec(normalized, link["to_node"], link["to_socket"])
        if source_spec is None:
            issues.append(WorkflowIssue("error", "link_source_socket_missing", f"Source socket not found: {link['from_node']}.{link['from_socket']}", node=link["from_node"], socket=link["from_socket"]))
            continue
        if target_spec is None:
            issues.append(WorkflowIssue("error", "link_target_socket_missing", f"Target socket not found: {link['to_node']}.{link['to_socket']}", node=link["to_node"], socket=link["to_socket"]))
            continue
        if not socket_types_compatible(source_spec.socket_type, target_spec.socket_type):
            issues.append(WorkflowIssue("error", "socket_type_mismatch", f"Incompatible sockets: {source_spec.socket_type} -> {target_spec.socket_type} for {link['from_node']} -> {link['to_node']}.", node=link["to_node"], socket=link["to_socket"]))

    incoming_counts: dict[tuple[str, str], int] = {}
    for link in normalized["links"]:
        key = (link["to_node"], link["to_socket"])
        incoming_counts[key] = incoming_counts.get(key, 0) + 1
    for node in normalized["nodes"]:
        spec = get_workflow_node_spec(node["node_type"], node)
        for socket in spec.inputs:
            count = incoming_counts.get((node["name"], socket.name), 0)
            if count > 1 and not socket.multi_input:
                issues.append(WorkflowIssue("error", "multiple_links_not_allowed", f"Socket {node['name']}.{socket.name} accepts only one incoming link.", node=node["name"], socket=socket.name))
            if socket.required and count == 0 and node["node_type"] != "workflow_input":
                if socket.socket_type != "Flow" or node["node_type"] != "workflow_output":
                    issues.append(WorkflowIssue("warning", "required_input_missing", f"Node {node['name']} is missing required input socket {socket.name}.", node=node["name"], socket=socket.name))
        if node_requires_action_card(node, approved_cards=approved_cards) and not _resolve_approved_card(node, approved_cards or []):
            issues.append(WorkflowIssue("error", "action_card_required", f"Node {node['name']} requires an approved action card before execution.", node=node["name"]))

    ordered, cycles = _topological_order(normalized)
    if cycles:
        for node_name in cycles:
            issues.append(WorkflowIssue("error", "cycle_detected", f"Cycle detected at node {node_name}.", node=node_name))

    reachable = _reachable_nodes(normalized)
    unreachable = sorted(name for name in nodes if name not in reachable)
    for node_name in unreachable:
        issues.append(WorkflowIssue("warning", "node_unreachable", f"Node {node_name} is not reachable from Workflow Input.", node=node_name))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return {
        "ok": not errors,
        "graph_name": normalized["name"],
        "graph_hash": workflow_graph_hash(normalized),
        "node_count": len(nodes),
        "link_count": len(normalized["links"]),
        "node_order": ordered,
        "reachable_nodes": sorted(reachable),
        "unreachable_nodes": unreachable,
        "issues": [issue.__dict__ for issue in issues],
        "errors": [issue.__dict__ for issue in errors],
        "warnings": [issue.__dict__ for issue in warnings],
        "manifest": workflow_graph_manifest(normalized),
    }


def compile_workflow_graph(
    graph: dict[str, Any],
    *,
    auto_create_roots: bool = True,
    approved_cards: Iterable[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    normalized = ensure_workflow_root_nodes(graph) if auto_create_roots else normalize_workflow_graph(graph)
    validation = validate_workflow_graph(normalized, auto_create_roots=False, approved_cards=approved_cards)
    nodes = _graph_node_map(normalized)
    ordered = validation["node_order"]
    steps: list[dict[str, Any]] = []
    contains_action_nodes = False
    blocked = False
    for node_name in ordered:
        node = nodes[node_name]
        spec = get_workflow_node_spec(node["node_type"], node)
        policy = node_execution_policy(node, approved_cards=approved_cards)
        node_blocked = not policy["allowed"]
        blocked = blocked or node_blocked
        contains_action_nodes = contains_action_nodes or node_requires_action_card(node, approved_cards=approved_cards)
        block_reason = "; ".join(policy["reasons"]) if policy["reasons"] else ("Dry-run or approval path available." if not spec.pure else "")
        steps.append(
            WorkflowPlanStep(
                node_name=node["name"],
                node_type=spec.node_type,
                label=node["label"],
                category=spec.category,
                pure=spec.pure,
                preview_mode=policy["preview_mode"],
                requires_action_card=policy["requires_action_card"],
                blocked=node_blocked,
                block_reason=block_reason,
                state=str(node.get("state", "draft")),
                tool_name=str(node.get("tool_name", "")),
                tool_policy=policy.get("tool_policy", {}),
                last_result_summary=str(node.get("last_result_summary", "")),
                last_error_summary=str(node.get("last_error_summary", "")),
                warning_count=int(node.get("warning_count", 0) or 0),
                socket_summary={"inputs": [socket.name for socket in spec.inputs], "outputs": [socket.name for socket in spec.outputs]},
            ).__dict__
        )
    root_created = "workflow_input" in {node["node_type"] for node in normalized["nodes"]} and "workflow_output" in {node["node_type"] for node in normalized["nodes"]}
    return {
        "ok": validation["ok"] and not blocked,
        "graph_name": normalized["name"],
        "graph_hash": validation["graph_hash"],
        "validation": validation,
        "steps": steps,
        "node_order": ordered,
        "contains_action_nodes": contains_action_nodes,
        "requires_approval": any(step["requires_action_card"] for step in steps),
        "blocked": blocked,
        "root_nodes_present": root_created,
        "manifest": validation["manifest"],
    }


def preview_workflow_graph(
    graph: dict[str, Any],
    *,
    auto_create_roots: bool = True,
    approved_cards: Iterable[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    compiled = compile_workflow_graph(graph, auto_create_roots=auto_create_roots, approved_cards=approved_cards)
    preview_steps = []
    for step in compiled["steps"]:
        preview_steps.append(
            {
                **step,
                "preview_summary": _preview_summary_for_step(step),
                "execution_allowed": not step["blocked"] and not step["requires_action_card"],
                "preview_only": True,
            }
        )
    return {**compiled, "preview_only": True, "preview_steps": preview_steps}


def start_workflow_run(
    graph: dict[str, Any],
    *,
    current_snapshot_hash: str = "",
    approved_cards: Iterable[dict[str, Any] | str] | None = None,
    previous_run: dict[str, Any] | None = None,
    auto_create_roots: bool = True,
) -> dict[str, Any]:
    compiled = compile_workflow_graph(graph, auto_create_roots=auto_create_roots, approved_cards=approved_cards)
    run_id = f"run-{uuid.uuid4().hex[:16]}"
    state = "waiting_approval" if compiled["blocked"] else "queued"
    if previous_run and previous_run.get("state") in {"paused", "stale"} and not compiled["blocked"]:
        state = "queued"
    run = {
        "run_id": run_id,
        "graph_name": compiled["graph_name"],
        "graph_hash": compiled["graph_hash"],
        "snapshot_hash": current_snapshot_hash,
        "state": state,
        "compiled": compiled,
        "current_step_index": 0,
        "checkpoints": [],
        "last_good_result": previous_run.get("last_good_result", {}) if previous_run else {},
        "last_result": {},
        "history": [],
    }
    if compiled["blocked"]:
        run["state"] = "waiting_approval"
        run["blocked_nodes"] = [step["node_name"] for step in compiled["steps"] if step["blocked"]]
    return run


def resume_workflow_run(run: dict[str, Any], *, current_snapshot_hash: str = "") -> dict[str, Any]:
    value = deepcopy(run or {})
    if is_snapshot_stale(value.get("snapshot_hash", ""), current_snapshot_hash):
        value["state"] = "stale"
        value["stale_reason"] = "Snapshot hash changed before resume."
        return value
    if value.get("state") in {"paused", "waiting_approval", "queued"}:
        value["state"] = "running"
    return value


def stop_workflow_run(run: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    value = deepcopy(run or {})
    current_state = str(value.get("state", "draft"))
    value["state"] = "paused" if current_state in {"running", "queued", "waiting_approval"} else current_state
    value["stop_reason"] = reason or value.get("stop_reason", "")
    return value


def transition_workflow_node_state(previous: str, next_state: str) -> str:
    current = (previous or "draft").strip().lower().replace("-", "_").replace(" ", "_")
    target = (next_state or "draft").strip().lower().replace("-", "_").replace(" ", "_")
    if current == target:
        return target if target in WORKFLOW_NODE_STATES else "draft"
    allowed = {
        "draft": {"ready", "queued", "running", "waiting_approval", "failed", "cancelled", "bypassed", "stale"},
        "ready": {"queued", "running", "waiting_approval", "failed", "cancelled", "bypassed", "stale"},
        "queued": {"running", "waiting_approval", "paused", "failed", "cancelled", "bypassed", "stale"},
        "running": {"waiting_approval", "completed", "failed", "cancelled", "paused", "bypassed", "stale"},
        "waiting_approval": {"running", "paused", "cancelled", "failed", "stale"},
        "paused": {"queued", "running", "cancelled", "stale", "bypassed"},
        "completed": {"bypassed", "stale"},
        "failed": {"stale", "bypassed"},
        "cancelled": {"stale", "bypassed"},
        "bypassed": {"stale"},
        "stale": {"draft", "ready", "queued", "running", "waiting_approval", "cancelled"},
    }
    if target not in WORKFLOW_NODE_STATES:
        raise WorkflowExecutionError(f"Unknown workflow node state: {next_state}")
    if target not in allowed.get(current, set()):
        raise WorkflowExecutionError(f"Illegal workflow node transition: {current} -> {target}")
    return target


def transition_workflow_run_state(previous: str, next_state: str) -> str:
    current = (previous or "draft").strip().lower().replace("-", "_").replace(" ", "_")
    target = (next_state or "draft").strip().lower().replace("-", "_").replace(" ", "_")
    if target not in WORKFLOW_RUN_STATES:
        raise WorkflowExecutionError(f"Unknown workflow run state: {next_state}")
    if current == target:
        return target
    allowed = {
        "draft": {"ready", "queued", "waiting_approval", "failed", "cancelled", "stale"},
        "ready": {"queued", "waiting_approval", "running", "failed", "cancelled", "stale"},
        "queued": {"running", "waiting_approval", "paused", "failed", "cancelled", "stale"},
        "running": {"waiting_approval", "paused", "completed", "completed_with_warnings", "failed", "cancelled", "stale"},
        "waiting_approval": {"running", "paused", "cancelled", "failed", "stale"},
        "paused": {"queued", "running", "completed", "completed_with_warnings", "failed", "cancelled", "stale"},
        "completed": {"stale", "cancelled"},
        "completed_with_warnings": {"stale", "cancelled"},
        "failed": {"stale", "cancelled"},
        "cancelled": {"stale"},
        "stale": {"draft", "ready", "queued"},
    }
    if target not in allowed.get(current, set()):
        raise WorkflowExecutionError(f"Illegal workflow run transition: {current} -> {target}")
    return target


def is_snapshot_stale(previous_hash: str, current_hash: str) -> bool:
    previous = str(previous_hash or "").strip()
    current = str(current_hash or "").strip()
    return bool(previous and current and previous != current)


def is_action_card_stale(card: dict[str, Any] | None, *, current_snapshot_hash: str = "", current_graph_hash: str = "") -> bool:
    if not card:
        return False
    snapshot_hash = str(card.get("snapshot_hash", card.get("detail", {}).get("snapshot_hash", ""))).strip()
    graph_hash = str(card.get("graph_hash", card.get("detail", {}).get("graph_hash", ""))).strip()
    state = normalize_action_status(str(card.get("status", "")))
    if state in {"completed", "completed_with_warnings", "failed", "recovered", "archived", "cancelled"}:
        return False
    if snapshot_hash and is_snapshot_stale(snapshot_hash, current_snapshot_hash):
        return True
    if graph_hash and str(current_graph_hash or "").strip() and graph_hash != str(current_graph_hash or "").strip():
        return True
    return False


def retain_last_good_result(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    previous_value = deepcopy(previous or {})
    current_value = deepcopy(current or {})
    if not previous_value:
        return current_value
    if not current_value:
        return previous_value
    previous_status = normalize_action_status(str(previous_value.get("state", previous_value.get("status", ""))))
    current_status = normalize_action_status(str(current_value.get("state", current_value.get("status", ""))))
    if current_status in {"completed", "completed_with_warnings"}:
        current_value["last_good_result"] = deepcopy(current_value)
        return current_value
    if previous_status in {"completed", "completed_with_warnings"}:
        merged = deepcopy(current_value)
        merged["last_good_result"] = previous_value
        if not merged.get("last_result_summary"):
            merged["last_result_summary"] = previous_value.get("last_result_summary", previous_value.get("summary", ""))
        return merged
    return current_value


def result_is_success(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    state = str(result.get("state", result.get("status", ""))).strip().lower()
    return state in {"completed", "completed_with_warnings"}


def build_workflow_plan_summary(plan: dict[str, Any]) -> str:
    if not plan:
        return "No workflow plan available."
    errors = len(plan.get("validation", {}).get("errors", []))
    warnings = len(plan.get("validation", {}).get("warnings", []))
    step_count = len(plan.get("steps", []))
    parts = [f"{step_count} step(s)"]
    if errors:
        parts.append(f"{errors} error(s)")
    if warnings:
        parts.append(f"{warnings} warning(s)")
    if plan.get("blocked"):
        parts.append("approval blocked")
    elif plan.get("requires_approval"):
        parts.append("approval required")
    return ", ".join(parts)


def _semver_tuple(version: str) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", str(version))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def _semver_key(version: str) -> tuple[int, int, int]:
    return _semver_tuple(version)


def select_recipe_version(
    versions: Iterable[str],
    *,
    requested_version: str = "",
    pin_mode: str = "compatible",
) -> dict[str, Any]:
    candidates = sorted({str(version).strip() for version in versions if str(version).strip()}, key=_semver_key)
    mode = normalize_recipe_pin_mode(pin_mode)
    if not candidates:
        return {"selected": "", "candidates": [], "pin_mode": mode, "reason": "No candidate recipe versions available."}
    if not requested_version:
        selected = candidates[-1]
        return {"selected": selected, "candidates": candidates, "pin_mode": mode, "reason": "No requested version; selected latest available."}
    requested = str(requested_version).strip()
    if mode == "exact":
        if requested not in candidates:
            return {"selected": "", "candidates": candidates, "pin_mode": mode, "reason": f"Exact recipe version {requested} not found."}
        return {"selected": requested, "candidates": candidates, "pin_mode": mode, "reason": "Exact version matched."}
    requested_major = _semver_tuple(requested)[0]
    compatible = [candidate for candidate in candidates if _semver_tuple(candidate)[0] == requested_major]
    if not compatible:
        return {"selected": candidates[-1], "candidates": candidates, "pin_mode": mode, "reason": "No compatible major version found; selected latest overall."}
    if mode == "latest_within_major":
        return {"selected": compatible[-1], "candidates": candidates, "pin_mode": mode, "reason": "Selected latest within requested major version."}
    newer_or_equal = [candidate for candidate in compatible if _semver_key(candidate) >= _semver_key(requested)]
    if newer_or_equal:
        return {"selected": newer_or_equal[-1], "candidates": candidates, "pin_mode": mode, "reason": "Selected newest compatible version at or above requested version."}
    return {"selected": compatible[-1], "candidates": candidates, "pin_mode": mode, "reason": "No newer compatible version found; selected latest within major."}


def workflow_graph_diff(base_graph: dict[str, Any], updated_graph: dict[str, Any]) -> dict[str, Any]:
    base = normalize_workflow_graph(base_graph)
    updated = normalize_workflow_graph(updated_graph)
    base_nodes = _graph_node_map(base)
    updated_nodes = _graph_node_map(updated)
    node_names = sorted(set(base_nodes) | set(updated_nodes))

    added_nodes = [name for name in node_names if name not in base_nodes]
    removed_nodes = [name for name in node_names if name not in updated_nodes]
    changed_nodes: list[dict[str, Any]] = []
    for name in node_names:
        if name not in base_nodes or name not in updated_nodes:
            continue
        before = base_nodes[name]
        after = updated_nodes[name]
        changes = {
            key: {"before": before.get(key), "after": after.get(key)}
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        }
        if changes:
            changed_nodes.append({"name": name, "changes": changes})

    base_links = {(
        _normalize_link(link)["from_node"],
        _normalize_link(link)["from_socket"],
        _normalize_link(link)["to_node"],
        _normalize_link(link)["to_socket"],
    ) for link in base.get("links", []) or []}
    updated_links = {(
        _normalize_link(link)["from_node"],
        _normalize_link(link)["from_socket"],
        _normalize_link(link)["to_node"],
        _normalize_link(link)["to_socket"],
    ) for link in updated.get("links", []) or []}
    added_links = [
        {"from_node": from_node, "from_socket": from_socket, "to_node": to_node, "to_socket": to_socket}
        for from_node, from_socket, to_node, to_socket in sorted(updated_links - base_links)
    ]
    removed_links = [
        {"from_node": from_node, "from_socket": from_socket, "to_node": to_node, "to_socket": to_socket}
        for from_node, from_socket, to_node, to_socket in sorted(base_links - updated_links)
    ]
    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_links": added_links,
        "removed_links": removed_links,
    }


def _apply_patch_operation(graph: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(graph or {})
    op = str(operation.get("op", "")).strip().lower().replace("-", "_").replace(" ", "_")
    nodes = value.setdefault("nodes", [])
    links = value.setdefault("links", [])
    if op == "add_node":
        node = _normalize_node(operation.get("node", operation))
        nodes.append(node)
        return value
    if op == "remove_node":
        node_name = str(operation.get("name", operation.get("node_name", ""))).strip()
        value["nodes"] = [node for node in nodes if node.get("name") != node_name]
        value["links"] = [link for link in links if _normalize_link(link)["from_node"] != node_name and _normalize_link(link)["to_node"] != node_name]
        return value
    if op == "set_property":
        node_name = str(operation.get("name", operation.get("node_name", ""))).strip()
        key = str(operation.get("property", "")).strip()
        if not node_name or not key:
            raise WorkflowExecutionError("set_property requires node_name and property.")
        for node in nodes:
            if node.get("name") == node_name:
                node[key] = deepcopy(operation.get("value"))
                return value
        raise WorkflowExecutionError(f"Node not found for set_property: {node_name}")
    if op == "add_link":
        links.append(_normalize_link(operation.get("link", operation)))
        return value
    if op == "remove_link":
        target = _normalize_link(operation.get("link", operation))
        value["links"] = [
            link
            for link in links
            if _normalize_link(link) != target
        ]
        return value
    if op == "move_node":
        node_name = str(operation.get("name", operation.get("node_name", ""))).strip()
        position = operation.get("position", {})
        for node in nodes:
            if node.get("name") == node_name:
                if isinstance(position, dict):
                    if "x" in position:
                        node["location_x"] = position["x"]
                    if "y" in position:
                        node["location_y"] = position["y"]
                return value
        raise WorkflowExecutionError(f"Node not found for move_node: {node_name}")
    if op == "wrap_as_recipe":
        metadata = value.setdefault("metadata", {})
        metadata["wrapped_as_recipe"] = True
        metadata["recipe_name"] = str(operation.get("recipe_name", metadata.get("recipe_name", ""))).strip()
        metadata["recipe_version"] = str(operation.get("recipe_version", metadata.get("recipe_version", ""))).strip()
        return value
    raise WorkflowExecutionError(f"Unsupported workflow patch operation: {op}")


def validate_workflow_patch(base_graph: dict[str, Any], operations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_workflow_graph(base_graph)
    issues: list[WorkflowIssue] = []
    staging = deepcopy(normalized)
    for index, operation in enumerate(operations):
        try:
            staging = _apply_patch_operation(staging, operation)
        except WorkflowExecutionError as exc:
            issues.append(WorkflowIssue("error", "patch_operation_failed", str(exc), node=str(operation.get("name", ""))))
            continue
        validation = validate_workflow_graph(staging, auto_create_roots=False)
        if not validation["ok"]:
            issues.append(WorkflowIssue("error", "patch_validation_failed", f"Patch step {index + 1} makes the graph invalid.", node=str(operation.get("name", ""))))
    errors = [issue for issue in issues if issue.severity == "error"]
    return {
        "ok": not errors,
        "issues": [issue.__dict__ for issue in issues],
        "errors": [issue.__dict__ for issue in errors],
        "patched_graph": staging,
        "diff": workflow_graph_diff(normalized, staging),
    }


def propose_workflow_patch(base_graph: dict[str, Any], operations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_workflow_graph(base_graph)
    operations = [dict(operation) for operation in operations]
    validation = validate_workflow_patch(normalized, operations)
    return {
        "ok": validation["ok"],
        "graph_hash": workflow_graph_hash(normalized),
        "operation_count": len(operations),
        "operations": operations,
        "validation": validation,
        "diff": validation["diff"],
        "proposal_id": f"patch-{uuid.uuid4().hex[:16]}",
    }


def preview_workflow_patch(base_graph: dict[str, Any], operations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    proposal = propose_workflow_patch(base_graph, operations)
    return {
        **proposal,
        "preview_only": True,
        "preview_summary": build_workflow_plan_summary({
            "steps": [{"node_name": op.get("name", ""), "label": op.get("op", ""), "pure": True, "preview_mode": "static"} for op in proposal["operations"]],
            "validation": proposal["validation"],
            "blocked": not proposal["validation"]["ok"],
            "requires_approval": False,
        }),
    }


def apply_workflow_patch(base_graph: dict[str, Any], operations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    proposal = propose_workflow_patch(base_graph, operations)
    if not proposal["ok"]:
        raise WorkflowExecutionError("Cannot apply invalid workflow patch.")
    patched = proposal["validation"]["patched_graph"]
    return {
        "graph": patched,
        "graph_hash": workflow_graph_hash(patched),
        "diff": proposal["diff"],
        "proposal_id": proposal["proposal_id"],
    }


__all__ = [
    "NODE_TYPE_ALIASES",
    "RECIPE_PIN_MODES",
    "SocketSpec",
    "NodeSpec",
    "WorkflowExecutionError",
    "WorkflowIssue",
    "WorkflowPlanStep",
    "WORKFLOW_NODE_CATEGORIES",
    "WORKFLOW_NODE_SPECS",
    "WORKFLOW_NODE_STATES",
    "WORKFLOW_RUN_STATES",
    "WORKFLOW_SOCKET_TYPES",
    "apply_workflow_patch",
    "build_workflow_plan_summary",
    "compile_workflow_graph",
    "ensure_workflow_root_nodes",
    "get_workflow_node_spec",
    "is_action_card_stale",
    "is_snapshot_stale",
    "list_workflow_node_categories",
    "list_workflow_node_types",
    "normalize_recipe_pin_mode",
    "normalize_workflow_graph",
    "normalize_workflow_node_type",
    "node_can_preview",
    "node_execution_policy",
    "node_preview_mode",
    "node_requires_action_card",
    "preview_workflow_graph",
    "preview_workflow_patch",
    "propose_workflow_patch",
    "ਰੇ" if False else "result_is_success",
    "retain_last_good_result",
    "resume_workflow_run",
    "select_recipe_version",
    "socket_types_compatible",
    "start_workflow_run",
    "stop_workflow_run",
    "transition_workflow_node_state",
    "transition_workflow_run_state",
    "validate_workflow_graph",
    "validate_workflow_patch",
    "workflow_add_menu_entries",
    "workflow_graph_diff",
    "workflow_graph_hash",
    "workflow_graph_manifest",
    "result_is_success",
]


__all__ = [
    "NODE_TYPE_ALIASES",
    "RECIPE_PIN_MODES",
    "SocketSpec",
    "NodeSpec",
    "WorkflowExecutionError",
    "WorkflowIssue",
    "WorkflowPlanStep",
    "WORKFLOW_NODE_CATEGORIES",
    "WORKFLOW_NODE_SPECS",
    "WORKFLOW_NODE_STATES",
    "WORKFLOW_RUN_STATES",
    "WORKFLOW_SOCKET_TYPES",
    "apply_workflow_patch",
    "build_workflow_plan_summary",
    "compile_workflow_graph",
    "ensure_workflow_root_nodes",
    "get_workflow_node_spec",
    "is_action_card_stale",
    "is_snapshot_stale",
    "list_workflow_node_categories",
    "list_workflow_node_types",
    "normalize_recipe_pin_mode",
    "normalize_workflow_graph",
    "normalize_workflow_node_type",
    "node_can_preview",
    "node_execution_policy",
    "node_preview_mode",
    "node_requires_action_card",
    "preview_workflow_graph",
    "preview_workflow_patch",
    "propose_workflow_patch",
    "result_is_success",
    "retain_last_good_result",
    "resume_workflow_run",
    "select_recipe_version",
    "socket_types_compatible",
    "start_workflow_run",
    "stop_workflow_run",
    "transition_workflow_node_state",
    "transition_workflow_run_state",
    "validate_workflow_graph",
    "validate_workflow_patch",
    "workflow_add_menu_entries",
    "workflow_graph_diff",
    "workflow_graph_hash",
    "workflow_graph_manifest",
]
