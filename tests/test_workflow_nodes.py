from __future__ import annotations

import pytest
import inspect

from codex_blender_agent.workflow_examples import (
    get_workflow_example,
    workflow_example_ids,
    workflow_example_items,
)
from codex_blender_agent.workflow_nodes import (
    NODETREE_IDNAME,
    NODETREE_LABEL,
    NODE_TYPES,
    WORKFLOW_NODE_CATEGORY_ORDER,
    WORKFLOW_NODE_ROOT_TYPES,
    canonical_node_type,
    compute_execution_order,
    migrate_legacy_node_config,
    migrate_legacy_workflow_graph_manifest,
    normalize_node_type,
    node_contract,
    parse_arguments_json,
    validate_node_config,
    workflow_graph_blueprint,
    workflow_node_category,
    workflow_node_categories,
    workflow_node_contract_summary,
    workflow_node_has_flow,
    workflow_node_is_action,
    workflow_node_is_pure,
    workflow_node_menu_entries,
    workflow_node_menu_sections,
    workflow_node_purity,
    workflow_node_socket_specs,
    workflow_root_blueprint,
)


def test_workflow_node_taxonomy_and_contract_helpers():
    assert NODETREE_IDNAME == "CODEX_AiWorkflowNodeTree"
    assert NODETREE_LABEL == "Codex AI Workflow"
    assert normalize_node_type("Workflow Input") == "workflow_input"
    assert normalize_node_type("Workflow Output") == "workflow_output"
    assert normalize_node_type("Recipe Call") == "recipe_call"
    assert canonical_node_type("toolbox_recipe") == "recipe_call"
    assert workflow_node_category("Workflow Input") == "Interface"
    assert workflow_node_purity("Workflow Input") == "pure"
    assert workflow_node_has_flow("Workflow Input") is True
    assert workflow_node_is_pure("Workflow Input") is True
    assert workflow_node_is_action("Assistant Call") is True
    assert "workflow_input" in NODE_TYPES
    assert "workflow_output" in NODE_TYPES
    assert "assistant_call" in NODE_TYPES
    assert "recipe_call" in NODE_TYPES
    assert node_contract("toolbox_recipe")["label"] == "Recipe Call"
    assert workflow_node_contract_summary("Assistant Call")["uses_flow"] is True


def test_workflow_socket_and_menu_sections_are_grouped_by_category():
    sections = workflow_node_menu_sections()
    assert [section["category"] for section in sections] == list(WORKFLOW_NODE_CATEGORY_ORDER)
    assert sections[0]["label"] == "Interface"

    interface_types = [entry["node_type"] for entry in sections[0]["entries"]]
    assert interface_types[:3] == ["workflow_input", "workflow_output", "value"]

    recipes_section = next(section for section in sections if section["category"] == "Recipes")
    recipe_types = [entry["node_type"] for entry in recipes_section["entries"]]
    assert "recipe_call" in recipe_types

    flat_entries = workflow_node_menu_entries()
    assert flat_entries[0]["node_type"] == "workflow_input"
    assert flat_entries[-1]["node_type"] in {"publish_asset", "preview_tap", "toolbox_recipe"}

    outputs = workflow_node_socket_specs("workflow_input")["outputs"]
    assert [spec["name"] for spec in outputs][:4] == ["Flow", "Context", "Snapshot", "Targets"]


def test_workflow_root_blueprint_and_default_graph_blueprint():
    assert workflow_root_blueprint() == [
        {"node_type": "workflow_input", "label": "Workflow Input", "location": (-980.0, 120.0)},
        {"node_type": "workflow_output", "label": "Workflow Output", "location": (700.0, 120.0)},
    ]

    blueprint = workflow_graph_blueprint()
    assert blueprint[0]["node_type"] == "workflow_input"
    assert blueprint[-1]["node_type"] == "workflow_output"
    assert workflow_graph_blueprint(False) == []
    assert WORKFLOW_NODE_ROOT_TYPES == ("workflow_input", "workflow_output")
    from codex_blender_agent.workflow_nodes import create_workflow_graph

    assert inspect.signature(create_workflow_graph).parameters["with_default_nodes"].default is False


def test_workflow_argument_json_validation():
    assert parse_arguments_json('{"tool": "get_scene_summary"}') == {"tool": "get_scene_summary"}
    assert parse_arguments_json({"name": "Cube"}) == {"name": "Cube"}
    with pytest.raises(ValueError):
        parse_arguments_json("[1, 2, 3]")
    with pytest.raises(ValueError):
        parse_arguments_json("{")


def test_workflow_config_validation_populates_contract_metadata():
    config = validate_node_config({"arguments": {"prompt": "Create a castle"}, "node_type": "Assistant Call"})

    assert config["node_type"] == "assistant_call"
    assert config["arguments_json"] == '{"prompt": "Create a castle"}'
    assert config["node_label"] == "Assistant Call"
    assert config["node_category"] == "AI"
    assert config["node_purity"] == "action"
    assert config["node_uses_flow"] is True
    assert config["approval_required"] is True
    assert [spec["name"] for spec in config["socket_inputs"]] == ["Flow", "Prompt", "Context", "Memory", "Asset Set"]

    with pytest.raises(ValueError):
        validate_node_config({"arguments": {}, "arguments_json": "{}"})


def test_workflow_legacy_node_migration_and_manifest_root_repair():
    migrated = migrate_legacy_node_config(
        {
            "idname": "CODEXBLENDERAGENT_ToolboxRecipeNode",
            "memory_query": "castle recipe",
        }
    )
    assert migrated["node_type"] == "recipe_call"
    assert migrated["recipe_ref"] == "castle recipe"

    manifest = migrate_legacy_workflow_graph_manifest(
        {
            "nodes": [
                {"name": "Recipe", "node_type": "toolbox_recipe", "location": [0.0, 0.0]},
            ],
            "links": [],
        }
    )
    node_types = [node["node_type"] for node in manifest["nodes"]]
    assert "workflow_input" in node_types
    assert "workflow_output" in node_types
    assert "recipe_call" in node_types
    assert manifest["legacy_migrated"] is True


def test_workflow_execution_order_prefers_links_over_position():
    nodes = [
        {"name": "Tool", "location": [0, 0]},
        {"name": "Snapshot", "location": [500, 0]},
        {"name": "Publish", "location": [-500, 0]},
    ]
    links = [
        {"from_node": "Snapshot", "to_node": "Tool"},
        {"from_node": "Tool", "to_node": "Publish"},
    ]

    assert compute_execution_order(nodes, links) == ["Snapshot", "Tool", "Publish"]


def test_workflow_node_categories_remain_stable_and_interface_first():
    categories = workflow_node_categories()
    assert [entry["category"] for entry in categories] == list(WORKFLOW_NODE_CATEGORY_ORDER)
    assert categories[0]["node_types"][0] == "workflow_input"


def test_workflow_example_ids_and_items_are_stable():
    assert workflow_example_ids() == (
        "scene_inspector",
        "safe_castle_blockout",
        "material_assignment",
        "save_selection_asset",
        "asset_reuse",
    )
    assert workflow_example_items()[0] == (
        "scene_inspector",
        "Scene Inspector",
        "A read-only graph that inspects the scene, selection, and prompt draft before any mutation.",
    )


def test_workflow_examples_include_configured_tool_nodes():
    castle = get_workflow_example("safe_castle_blockout")
    assert castle.title == "Safe Castle Blockout"
    assert [node.node_type for node in castle.node_specs] == [
        "assistant_prompt",
        "tool_call",
        "approval_gate",
    ]
    tool_node = castle.node_specs[1]
    assert tool_node.tool_name == "create_primitive"
    assert tool_node.approval_required is True
    assert parse_arguments_json(tool_node.arguments_json) == {
        "name": "Castle Blockout",
        "primitive_type": "CUBE",
    }

    material = get_workflow_example("material_assignment")
    tool_names = [node.tool_name for node in material.node_specs if node.tool_name]
    assert tool_names == ["create_material", "assign_material"]
    assert all(node.approval_required for node in material.node_specs if node.node_type == "tool_call")

    reuse = get_workflow_example("asset_reuse")
    assert reuse.node_specs[1].tool_name == "append_asset_from_library"
    assert reuse.node_specs[1].approval_required is True
