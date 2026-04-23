from __future__ import annotations

import pytest

from codex_blender_agent.workflow_recipes import (
    GraphPatchValidationResult,
    RecipeMetadataValidation,
    VersionPinResolution,
    bump_semver,
    compare_semver,
    hash_recipe_manifest,
    is_version_compatible,
    parse_semver,
    resolve_version_pin,
    summarize_graph_patch_diff,
    summarize_recipe_manifest_diff,
    validate_graph_patch_proposal,
    validate_recipe_metadata,
)


def _recipe_metadata() -> dict[str, object]:
    return {
        "recipe_id": "recipe.castle.blockout",
        "display_name": "Castle Blockout",
        "version": "v1.2.3",
        "graph_hash": "a" * 64,
        "input_schema": {"type": "object", "properties": {"selection": {"type": "array"}}},
        "output_schema": {"type": "object", "properties": {"outputs": {"type": "array"}}},
        "required_tools": ["create_primitive", "assign_material"],
        "risk_profile": "write",
        "author": "Example Author",
        "changelog": "Initial release.",
        "preview_image": "previews/castle.png",
        "tests": [{"name": "smoke", "inputs": {"selection": ["Cube"]}}],
        "tags": ["castle", "blockout"],
        "catalog_path": "recipes/modeling/blockout",
        "compatibility_range": {"addon_min": "0.9.0", "addon_max": "0.10.0"},
    }


def test_validate_recipe_metadata_normalizes_and_hashes():
    result = validate_recipe_metadata(_recipe_metadata())

    assert isinstance(result, RecipeMetadataValidation)
    assert result.ok
    assert result.normalized["version"] == "1.2.3"
    assert result.normalized["required_tools"] == ["create_primitive", "assign_material"]
    assert len(result.manifest_hash) == 64
    assert result.manifest_hash == hash_recipe_manifest(result.normalized)


def test_validate_recipe_metadata_reports_missing_or_invalid_fields():
    recipe = _recipe_metadata()
    recipe.pop("version")
    recipe["graph_hash"] = "not-a-sha"
    recipe["risk_profile"] = "mystery"

    result = validate_recipe_metadata(recipe)

    assert not result.ok
    assert any("version" in issue for issue in result.issues)
    assert any("graph_hash" in issue for issue in result.issues)
    assert any("risk_profile" in issue for issue in result.issues)


def test_semver_helpers_and_pin_resolution():
    assert str(parse_semver("v1.2.3")) == "SemVer(major=1, minor=2, patch=3, prerelease=(), build=())"
    assert compare_semver("1.2.3", "1.2.4") < 0
    assert compare_semver("1.2.3", "1.2.3") == 0
    assert bump_semver("1.2.3", "patch") == "1.2.4"
    assert bump_semver("1.2.3", "minor") == "1.3.0"
    assert bump_semver("1.2.3", "major") == "2.0.0"
    assert is_version_compatible("1.2.3", "1.4.0")
    assert not is_version_compatible("1.2.3", "2.0.0")

    exact = resolve_version_pin(["1.0.0", "1.2.3", "1.2.4"], "1.2.3", "exact")
    compatible = resolve_version_pin(["1.0.0", "1.2.3", "1.2.4"], "1.2.3", "compatible")
    latest = resolve_version_pin(["1.0.0", "1.2.3", "1.9.0"], "1.2.3", "latest_within_major")

    assert isinstance(exact, VersionPinResolution)
    assert exact.resolved_version == "1.2.3"
    assert compatible.resolved_version == "1.2.4"
    assert latest.resolved_version == "1.9.0"


def test_version_pin_resolution_rejects_missing_and_incompatible_versions():
    with pytest.raises(ValueError):
        resolve_version_pin(["1.0.0"], "2.0.0", "compatible")
    with pytest.raises(ValueError):
        resolve_version_pin(["1.0.0"], "1.0.1", "exact")
    with pytest.raises(ValueError):
        resolve_version_pin([], "1.0.0", "compatible")


def test_hash_recipe_manifest_is_deterministic_across_key_order():
    a = {"b": {"y": 2, "x": 1}, "a": [1, 2, {"z": True}]}
    b = {"a": [1, 2, {"z": True}], "b": {"x": 1, "y": 2}}
    c = {"a": [1, 2, {"z": False}], "b": {"x": 1, "y": 2}}

    assert hash_recipe_manifest(a) == hash_recipe_manifest(b)
    assert hash_recipe_manifest(a) != hash_recipe_manifest(c)


def test_validate_graph_patch_proposal_accepts_staged_recipe_graph():
    graph_state = {
        "nodes": [
            {"node_id": "input", "label": "Input"},
            {"node_id": "tool", "label": "Tool"},
        ],
        "links": [
            {"from_node": "input", "from_socket": "Output", "to_node": "tool", "to_socket": "Input"},
        ],
    }
    proposal = {
        "graph_id": "workflow.castle",
        "operations": [
            {"op": "add_node", "node_id": "preview", "node_type": "preview_tap", "label": "Preview"},
            {"op": "set_property", "node_id": "tool", "property": "tool_name", "value": "create_primitive"},
            {"op": "move_node", "node_id": "preview", "location": [320, -160]},
            {"op": "add_link", "from_node": "input", "from_socket": "Output", "to_node": "preview", "to_socket": "Input"},
            {
                "op": "wrap_as_recipe",
                "node_ids": ["input", "preview"],
                "recipe": _recipe_metadata(),
            },
        ],
    }

    result = validate_graph_patch_proposal(proposal, graph_state=graph_state)

    assert isinstance(result, GraphPatchValidationResult)
    assert result.ok
    assert "wrap as recipe Castle Blockout" in result.summary
    assert result.normalized["operations"][0]["op"] == "add_node"
    assert result.normalized["operations"][-1]["recipe"]["version"] == "1.2.3"


def test_validate_graph_patch_proposal_reports_invalid_refs_and_bad_recipe():
    proposal = {
        "operations": [
            {"op": "add_link", "from_node": "missing", "from_socket": "Output", "to_node": "tool", "to_socket": "Input"},
            {"op": "move_node", "node_id": "missing", "location": [10, 20]},
            {
                "op": "wrap_as_recipe",
                "node_ids": ["missing"],
                "recipe": {
                    "recipe_id": "recipe.bad",
                    "display_name": "",
                    "version": "1.0.0",
                    "graph_hash": "bad",
                    "input_schema": {},
                    "output_schema": {},
                    "required_tools": [],
                    "risk_profile": "write",
                    "author": "Example Author",
                    "changelog": "",
                    "preview_image": "",
                    "tests": [],
                    "tags": [],
                    "catalog_path": "",
                    "compatibility_range": "",
                },
            },
            {"op": "unknown"},
        ],
    }

    result = validate_graph_patch_proposal(proposal)

    assert not result.ok
    assert any("unknown" in issue for issue in result.issues)
    assert any("missing" in issue for issue in result.issues)
    assert any("recipe" in issue for issue in result.issues)


def test_graph_and_manifest_diff_summaries_are_human_readable():
    before_graph = {
        "nodes": [
            {"node_id": "input", "label": "Input"},
            {"node_id": "tool", "label": "Tool"},
        ],
        "links": [
            {"from_node": "input", "from_socket": "Output", "to_node": "tool", "to_socket": "Input"},
        ],
    }
    after_graph = {
        "nodes": [
            {"node_id": "input", "label": "Input"},
            {"node_id": "tool", "label": "Tool v2"},
            {"node_id": "preview", "label": "Preview"},
        ],
        "links": [
            {"from_node": "input", "from_socket": "Output", "to_node": "preview", "to_socket": "Input"},
            {"from_node": "preview", "from_socket": "Output", "to_node": "tool", "to_socket": "Input"},
        ],
    }
    before_manifest = {"version": "1.0.0", "tags": ["castle"], "input_schema": {"required": ["selection"]}}
    after_manifest = {"version": "1.1.0", "tags": ["castle", "stone"], "input_schema": {"required": ["selection", "style"]}}

    graph_summary = summarize_graph_patch_diff(before_graph, after_graph)
    manifest_summary = summarize_recipe_manifest_diff(before_manifest, after_manifest)

    assert "Added nodes: preview" in graph_summary
    assert "Changed nodes: tool" in graph_summary
    assert "Added links:" in graph_summary
    assert "version" in manifest_summary
    assert "tags" in manifest_summary
    assert "input_schema" in manifest_summary
