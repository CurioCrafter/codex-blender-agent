from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .workflow_nodes import NODE_TYPES, normalize_node_type


@dataclass(frozen=True)
class WorkflowExampleNodeSpec:
    node_type: str
    label: str
    tool_name: str = ""
    arguments_json: str = "{}"
    memory_query: str = ""
    approval_required: bool = False
    location: tuple[float, float] = (0.0, 0.0)
    description: str = ""
    output_type: str = ""
    required_context: str = ""


@dataclass(frozen=True)
class WorkflowExampleSpec:
    example_id: str
    title: str
    description: str
    node_specs: tuple[WorkflowExampleNodeSpec, ...]


def _node_spec(
    node_type: str,
    label: str,
    *,
    tool_name: str = "",
    arguments_json: str = "{}",
    memory_query: str = "",
    approval_required: bool = False,
    location: tuple[float, float] = (0.0, 0.0),
    description: str = "",
) -> WorkflowExampleNodeSpec:
    normalized = normalize_node_type(node_type)
    node_type_info = NODE_TYPES[normalized]
    return WorkflowExampleNodeSpec(
        node_type=normalized,
        label=label,
        tool_name=tool_name,
        arguments_json=arguments_json,
        memory_query=memory_query,
        approval_required=approval_required,
        location=location,
        description=description or node_type_info.get("description", ""),
        output_type=node_type_info.get("output_type", ""),
        required_context=node_type_info.get("required_context", ""),
    )


WORKFLOW_EXAMPLES: tuple[WorkflowExampleSpec, ...] = (
    WorkflowExampleSpec(
        example_id="scene_inspector",
        title="Scene Inspector",
        description="A read-only graph that inspects the scene, selection, and prompt draft before any mutation.",
        node_specs=(
            _node_spec("scene_snapshot", "Scene Snapshot", location=(-640.0, 160.0)),
            _node_spec("selection", "Selection", location=(-340.0, 160.0)),
            _node_spec("assistant_prompt", "Prompt Draft", location=(-40.0, 160.0)),
        ),
    ),
    WorkflowExampleSpec(
        example_id="safe_castle_blockout",
        title="Safe Castle Blockout",
        description="A review-first graph that turns a castle request into a structured primitive creation plan.",
        node_specs=(
            _node_spec("assistant_prompt", "Castle Prompt", location=(-720.0, 80.0)),
            _node_spec(
                "tool_call",
                "Create Castle Blockout",
                tool_name="create_primitive",
                arguments_json='{"name": "Castle Blockout", "primitive_type": "CUBE"}',
                approval_required=True,
                location=(-320.0, 80.0),
                description="Create a primitive blockout for a castle concept.",
            ),
            _node_spec(
                "approval_gate",
                "Approval Gate",
                memory_query="Review the blockout before committing scene changes.",
                approval_required=True,
                location=(120.0, 80.0),
            ),
        ),
    ),
    WorkflowExampleSpec(
        example_id="material_assignment",
        title="Material Assignment",
        description="A structured graph that creates a material and assigns it to the current selection.",
        node_specs=(
            _node_spec("selection", "Selection", location=(-760.0, 120.0)),
            _node_spec(
                "tool_call",
                "Create Material",
                tool_name="create_material",
                arguments_json='{"name": "Castle Material", "use_nodes": true}',
                approval_required=True,
                location=(-420.0, 120.0),
            ),
            _node_spec(
                "tool_call",
                "Assign Material",
                tool_name="assign_material",
                arguments_json='{"material_name": "Castle Material"}',
                approval_required=True,
                location=(-80.0, 120.0),
            ),
            _node_spec(
                "approval_gate",
                "Approval Gate",
                memory_query="Confirm material creation and assignment before execution.",
                approval_required=True,
                location=(280.0, 120.0),
            ),
        ),
    ),
    WorkflowExampleSpec(
        example_id="save_selection_asset",
        title="Save Selection Asset",
        description="A graph that saves selected objects into the local asset library and publishes the result.",
        node_specs=(
            _node_spec("selection", "Selection", location=(-560.0, 120.0)),
            _node_spec(
                "tool_call",
                "Save Selection",
                tool_name="save_selection_to_asset_library",
                arguments_json='{"name": "Reusable Asset", "category": "model", "mark_as_blender_assets": true}',
                approval_required=True,
                location=(-200.0, 120.0),
            ),
            _node_spec(
                "publish_asset",
                "Publish Asset",
                memory_query="Reuse this saved asset later from AI Assets.",
                approval_required=False,
                location=(180.0, 120.0),
            ),
        ),
    ),
    WorkflowExampleSpec(
        example_id="asset_reuse",
        title="Asset Reuse",
        description="A graph that finds a stored asset and appends it into the current scene with review.",
        node_specs=(
            _node_spec(
                "asset_search",
                "Search Assets",
                memory_query="castle blockout",
                location=(-560.0, 120.0),
            ),
            _node_spec(
                "tool_call",
                "Append Asset",
                tool_name="append_asset_from_library",
                arguments_json='{"item_id_or_name": "castle blockout", "link": false}',
                approval_required=True,
                location=(-160.0, 120.0),
            ),
            _node_spec(
                "approval_gate",
                "Approval Gate",
                memory_query="Approve importing the searched asset into the current scene.",
                approval_required=True,
                location=(240.0, 120.0),
            ),
        ),
    ),
)


def workflow_example_ids() -> tuple[str, ...]:
    return tuple(example.example_id for example in WORKFLOW_EXAMPLES)


def workflow_example_items() -> list[tuple[str, str, str]]:
    return [(example.example_id, example.title, example.description) for example in WORKFLOW_EXAMPLES]


def get_workflow_example(example_id: str) -> WorkflowExampleSpec:
    key = (example_id or "").strip()
    for example in WORKFLOW_EXAMPLES:
        if example.example_id == key:
            return example
    valid = ", ".join(workflow_example_ids())
    raise KeyError(f"Unknown workflow example: {example_id}. Valid examples: {valid}")

