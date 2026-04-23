from __future__ import annotations

from codex_blender_agent.validation_constraints import build_constraint_graph, infer_constraint_graph, summarize_constraint_graph


def _record(name, location, dimensions, **extra):
    return {"name": name, "type": "MESH", "location": location, "dimensions": dimensions, **extra}


def test_inferred_constraint_graph_detects_support_and_zone_exclusion():
    records = [
        _record("Seat", [0.0, 0.0, 1.0], [4.0, 4.0, 0.5], material_names=["Wood"]),
        _record("FrontLeftLeg", [0.0, 0.0, 0.0], [0.6, 0.6, 1.0], collections=["Furniture"]),
        _record("MoatRing", [0.0, 0.0, 0.0], [8.0, 8.0, 1.0]),
        _record("PineTree", [0.3, 0.2, 0.5], [0.4, 0.4, 2.0]),
    ]

    graph = infer_constraint_graph(records)
    edge_types = {edge["type"] for edge in graph["edges"]}

    assert graph["summary"]["node_count"] == 4
    assert "support_contact" in edge_types
    assert "zone_exclusion" in edge_types

    supported_edge = next(edge for edge in graph["edges"] if edge["type"] == "support_contact")
    assert supported_edge["source"] == "Seat"
    assert supported_edge["target"] == "FrontLeftLeg"
    assert supported_edge["source_kind"] == "inferred"

    zone_edge = next(edge for edge in graph["edges"] if edge["type"] == "zone_exclusion")
    assert zone_edge["source"] == "PineTree"
    assert zone_edge["target"] == "MoatRing"
    assert summarize_constraint_graph(graph)["relation_types"]["support_contact"] >= 1


def test_manifest_driven_graph_preserves_required_contacts_and_symmetry():
    records = [
        _record("WheelLeft", [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _record("Axle", [0.0, 0.0, 0.0], [2.0, 0.4, 0.4]),
    ]
    manifest = {
        "objects": [
            {
                "name": "WheelLeft",
                "role": "mechanical",
                "must_touch": ["Axle"],
                "centered_on": ["Axle"],
                "symmetry_group": "wheels",
            },
            {
                "name": "Axle",
                "role": "mechanical",
            },
        ],
        "symmetry_groups": {"wheels": ["WheelLeft", "WheelRight"]},
        "required_contacts": [{"object": "WheelLeft", "targets": ["Axle"], "tolerance": 0.005}],
    }

    graph = build_constraint_graph(records, manifest=manifest)
    edge_types = {edge["type"] for edge in graph["edges"]}

    assert "must_touch" in edge_types
    assert "centered_on" in edge_types
    assert "symmetry_peer" in edge_types
    assert "required_contact" in edge_types
