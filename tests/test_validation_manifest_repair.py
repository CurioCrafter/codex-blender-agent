from __future__ import annotations

from codex_blender_agent.validation_core import classify_aabb_pair, classify_triangle_pair, effective_tolerances
from codex_blender_agent.validation_manifest import build_constraint_graph, normalize_asset_intent_manifest
from codex_blender_agent.validation_repair import build_asset_repair_plan, safe_repair_delta_prompt
from codex_blender_agent.visual_geometry import AABB


def _record(name: str, location: list[float], dimensions: list[float], *, material_names: list[str] | None = None) -> dict:
    return {"name": name, "location": location, "dimensions": dimensions, "material_names": material_names or [], "collections": []}


def test_asset_intent_manifest_roundtrip_and_inferred_constraint_graph():
    records = [
        _record("Seat", [0, 0, 1], [2, 2, 0.2]),
        _record("Leg", [0.8, 0.8, 0.45], [0.2, 0.2, 0.9]),
        _record("CastleMoat", [0, 0, -0.05], [5, 5, 0.1], material_names=["Water"]),
    ]
    manifest = normalize_asset_intent_manifest(
        {
            "asset_name": "chair fixture",
            "objects": [{"name": "Seat", "role": "support"}, {"name": "Leg", "role": "support_leg"}],
            "required_contacts": [{"object": "Leg", "targets": ["Seat"], "tolerance": 0.02}],
            "allowed_intersections": [["Leg", "Seat"]],
            "expected_dimensions": {"Seat": [2, 2, 0.2]},
        },
        records=records,
        prompt="make a chair",
    )

    assert manifest["schema_version"] == "0.15.0"
    assert manifest["source"] == "gpt_intent"
    assert manifest["required_contacts"][0]["object"] == "Leg"
    assert manifest["constraint_graph"]["node_count"] == 3
    assert any(edge["relation"] == "required_contact" for edge in manifest["constraint_graph"]["edges"])

    inferred = normalize_asset_intent_manifest(None, records=records, prompt="make a castle with moat")
    assert inferred["inferred"] is True
    assert any(node["role"] == "water_zone" for node in inferred["constraint_graph"]["nodes"])


def test_constraint_graph_can_be_built_from_report_records_and_manifest():
    records = [_record("Wheel", [0, 0, 1], [1, 1, 1]), _record("Axle", [0, 0, 1], [2, 0.2, 0.2])]
    manifest = normalize_asset_intent_manifest(
        {"constraints": [{"type": "centered_on", "objects": ["Wheel"], "target": "Axle"}]},
        records=records,
    )
    graph = build_constraint_graph(records, manifest)

    assert {node["id"] for node in graph["nodes"]} == {"Wheel", "Axle"}
    assert any(edge["relation"] == "centered_on" for edge in graph["edges"])


def test_repair_plan_separates_safe_and_gated_actions():
    report = {
        "report_id": "report-1",
        "issues": [
            {"issue_id": "float", "type": "floating_part", "severity": "high", "target": "Leg", "objects": ["Leg"], "acceptance_tests": ["touches support"]},
            {"issue_id": "bvh", "type": "interpenetration", "severity": "critical", "target": "Crown", "objects": ["Crown", "Wall"], "acceptance_tests": ["no overlap"]},
        ],
    }
    plan = build_asset_repair_plan(report, manifest={"repair_policy": {"allow_safe_transforms": True}})

    assert plan["counts"]["safe"] == 1
    assert plan["counts"]["gated"] == 1
    assert plan["safe_actions"][0]["operation"] == "snap_to_support"
    assert plan["gated_actions"][0]["operation"] == "separate_or_boolean_union"

    delta = safe_repair_delta_prompt(plan)
    assert delta["mode"] == "patch"
    assert delta["targets"] == ["float"]
    assert delta["max_edits"] == 1


def test_validation_core_classifies_pairs_and_triangle_candidates():
    tolerances = effective_tolerances(10.0)
    left = AABB((0, 0, 0), (2, 2, 2))
    right = AABB((1, 0, 0), (3, 2, 2))
    classified = classify_aabb_pair(left, right, tolerances=tolerances)

    assert classified["classification"] == "interpenetration"
    assert classified["overlap_ratio_of_smaller"] == 0.5

    tri = classify_triangle_pair(((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0.2, 0.2, 0), (0.8, 0.2, 0), (0.2, 0.8, 0)))
    assert tri["classification"] == "coplanar_overlap"
