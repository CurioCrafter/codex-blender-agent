from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    import bpy
except ImportError:  # pragma: no cover - normal Python imports this module for static tests
    bpy = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SMOKE_STEPS = (
    "load_addon",
    "empty_scene_geometry_analysis",
    "plan_rotated_asset_views",
    "detect_generic_part_defects",
    "capture_geometry_planned_views",
    "verify_state_restoration",
)


def _ensure_registered() -> None:
    if bpy is None:
        raise RuntimeError("This smoke test must run inside Blender.")
    import codex_blender_agent

    try:
        codex_blender_agent.register()
    except Exception as exc:
        if "already registered" not in str(exc).lower():
            raise


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float], rotation_z: float = 0.0) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=(0.0, 0.0, rotation_z))
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return obj


def _payload(result: dict) -> dict:
    return json.loads(result["contentItems"][0]["text"])


def main() -> None:
    _ensure_registered()
    from codex_blender_agent.runtime import get_runtime

    runtime = get_runtime()

    _clear_scene()
    empty = _payload(runtime._execute_dynamic_tool(bpy.context, "analyze_visual_geometry", {"selected_only": False}))
    if empty.get("object_count") != 0:
        raise AssertionError("Empty scene analysis should not invent target geometry.")
    if empty.get("defects", [{}])[0].get("type") != "no_target_geometry":
        raise AssertionError("Empty scene should return no_target_geometry.")

    _cube("Rotated_Main_Asset", (0, 0, 0), (2.5, 0.5, 0.5), rotation_z=0.785398)
    _cube("Floating_Shard", (0, 0, 4), (0.2, 0.2, 0.2))
    _cube("Overlap_A", (2, 0, 0), (0.8, 0.8, 0.8))
    _cube("Overlap_B", (2, 0, 0), (0.8, 0.8, 0.8))
    _cube("Tiny_Detail", (-2, 0, 0.2), (0.02, 0.02, 0.02))
    bpy.context.view_layer.update()

    plan = _payload(
        runtime._execute_dynamic_tool(
            bpy.context,
            "plan_geometry_review_viewpoints",
            {"selected_only": False, "settings": {"candidate_view_count": 24, "selected_capture_count": 8, "audit_view_count": 3}},
        )
    )
    selected = plan.get("selected_viewpoints", [])
    if len(selected) != 8:
        raise AssertionError(f"Expected 8 geometry-planned views, got {len(selected)}")
    digest = plan.get("geometry_digest", {})
    defects = {item.get("type") for item in digest.get("defects", [])}
    if "floating_part" not in defects:
        raise AssertionError("Expected floating_part defect.")
    if "excessive_overlap" not in defects:
        raise AssertionError("Expected excessive_overlap defect.")
    if "tiny_detail_missed" not in defects:
        raise AssertionError("Expected tiny_detail_missed defect.")
    frame = digest.get("footprint_frame", {})
    if not frame.get("axis_x"):
        raise AssertionError("Expected PCA footprint frame.")

    original_camera = bpy.context.scene.camera
    original_resolution = (
        bpy.context.scene.render.resolution_x,
        bpy.context.scene.render.resolution_y,
        bpy.context.scene.render.resolution_percentage,
    )
    original_filepath = bpy.context.scene.render.filepath

    output_dir = Path(tempfile.mkdtemp(prefix="codex_visual_geometry_smoke_"))
    capture = _payload(
        runtime._execute_dynamic_tool(
            bpy.context,
            "capture_scene_viewpoints",
            {
                "output_dir": str(output_dir),
                "resolution": 192,
                "max_viewpoints": 8,
                "selected_only": False,
                "use_geometry_planner": True,
                "geometry_settings": {"candidate_view_count": 24, "selected_capture_count": 8, "audit_view_count": 3},
            },
        )
    )
    captures = capture.get("captures", [])
    if len(captures) < 5:
        raise AssertionError(f"Expected at least 5 captures, got {len(captures)}")
    missing = [item.get("path") for item in captures if not Path(str(item.get("path", ""))).exists()]
    if missing:
        raise AssertionError(f"Missing capture files: {missing}")
    if not capture.get("geometry_digest"):
        raise AssertionError("Capture payload should include geometry_digest.")
    if bpy.context.scene.camera != original_camera:
        raise AssertionError("Scene camera was not restored.")
    restored_resolution = (
        bpy.context.scene.render.resolution_x,
        bpy.context.scene.render.resolution_y,
        bpy.context.scene.render.resolution_percentage,
    )
    if restored_resolution != original_resolution:
        raise AssertionError(f"Render resolution was not restored: {restored_resolution} != {original_resolution}")
    if bpy.context.scene.render.filepath != original_filepath:
        raise AssertionError("Render filepath was not restored.")

    print(json.dumps({"ok": True, "steps": SMOKE_STEPS, "captures": len(captures), "defects": sorted(defects)}, indent=2))


if __name__ == "__main__":
    main()
