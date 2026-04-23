from __future__ import annotations

from codex_blender_agent.validation_manifest import infer_asset_intent_manifest, parse_asset_intent_manifest


def test_manifest_roundtrip_normalizes_contacts_and_dimensions():
    raw = {
        "schema_version": "1.0.0",
        "asset_name": "wooden_chair",
        "unit": "meters",
        "prompt": "chair",
        "objects": [
            {
                "name": "Seat",
                "role": "support_surface",
                "expected_dimensions": [0.45, 0.45, 0.06],
                "must_touch": ["FrontLeftLeg", "FrontRightLeg"],
                "must_not_intersect": ["Backrest"],
                "centered_on": ["Base"],
                "flush_with": ["Apron"],
                "clearance": {"minimum": 0.01, "maximum": 0.03},
                "support": ["FrontLeftLeg", "FrontRightLeg"],
                "symmetry_group": "legs",
                "origin_pivot": "seat_origin",
                "anchors": {"top": "seat_top_plane"},
                "metadata": {"tag": "primary"},
            }
        ],
        "required_contacts": [{"object": "Seat", "targets": ["FrontLeftLeg", "FrontRightLeg"], "tolerance": 0.005}],
        "clearance_targets": [{"clearance_id": "seat_backrest", "object": "Seat", "target": "Backrest", "min_gap": 0.01, "max_gap": 0.03}],
        "allowed_intersections": [["Seat", "FrontLeftLeg"]],
        "forbidden_intersections": "all_other_pairs",
        "repair_policy": {
            "allow_safe_transforms": True,
            "allow_local_cleanup": True,
            "allow_destructive_mesh_ops": False,
            "destructive_requires_approval": True,
        },
    }

    manifest = parse_asset_intent_manifest(raw)
    normalized = manifest.to_dict()
    roundtrip = parse_asset_intent_manifest(normalized).to_dict()

    assert normalized["asset_name"] == "wooden_chair"
    assert normalized["unit"] == "meters"
    assert normalized["objects"][0]["expected_dimensions"] == [0.45, 0.45, 0.06]
    assert normalized["objects"][0]["must_touch"] == ["FrontLeftLeg", "FrontRightLeg"]
    assert normalized["required_contacts"][0]["object"] == "Seat"
    assert normalized["required_contacts"][0]["targets"] == ["FrontLeftLeg", "FrontRightLeg"]
    assert normalized["repair_policy"]["allow_destructive_mesh_ops"] is False
    assert normalized["repair_policy"]["destructive_requires_approval"] is True
    assert roundtrip == normalized


def test_inferred_manifest_prefers_record_names_and_roles():
    records = [
        {"name": "Seat", "location": [0.0, 0.0, 1.0], "dimensions": [4.0, 4.0, 0.5], "material_names": ["Wood"]},
        {"name": "FrontLeftLeg", "location": [0.0, 0.0, 0.0], "dimensions": [0.6, 0.6, 1.0], "collections": ["Furniture"]},
    ]

    manifest = infer_asset_intent_manifest(records, prompt="chair")
    data = manifest.to_dict()

    assert data["asset_name"] == "chair"
    assert data["inferred"] is True
    assert [item["name"] for item in data["objects"]] == ["Seat", "FrontLeftLeg"]
    assert data["objects"][0]["role"] == "support"
    assert data["objects"][1]["role"] == "support"
