from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codex_blender_agent  # noqa: E402
from codex_blender_agent.runtime import get_runtime  # noqa: E402
from codex_blender_agent.visual_review import plan_viewpoints  # noqa: E402


def _ensure_registered() -> None:
    try:
        codex_blender_agent.register()
    except Exception as exc:
        if "already registered" not in str(exc).lower():
            raise


def _cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return obj


def main() -> None:
    _ensure_registered()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    _cube("Castle_Gate", (0, -3, 1), (2.0, 0.4, 1.0))
    _cube("Castle_Wall_Left", (-3, 0, 1), (0.4, 4.0, 1.0))
    _cube("Castle_Wall_Right", (3, 0, 1), (0.4, 4.0, 1.0))
    _cube("Castle_Keep", (0, 2, 2), (1.3, 1.3, 2.0))
    _cube("North_Tower", (-3, 3, 3), (0.7, 0.7, 3.0))
    _cube("South_Tower", (3, 3, 3), (0.7, 0.7, 3.0))

    original_camera = bpy.context.scene.camera
    original_resolution = (
        bpy.context.scene.render.resolution_x,
        bpy.context.scene.render.resolution_y,
        bpy.context.scene.render.resolution_percentage,
    )
    original_filepath = bpy.context.scene.render.filepath

    records = [
        {"name": obj.name, "location": list(obj.location), "dimensions": list(obj.dimensions)}
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
    ]
    viewpoints = plan_viewpoints(records)
    if len(viewpoints) < 6:
        raise AssertionError(f"Expected at least 6 viewpoints, got {len(viewpoints)}")
    if not any(view.get("kind") == "detail" for view in viewpoints):
        raise AssertionError("Expected semantic detail viewpoints for castle proxy scene.")

    output_dir = Path(tempfile.mkdtemp(prefix="codex_visual_review_smoke_"))
    result = get_runtime()._execute_dynamic_tool(
        bpy.context,
        "capture_scene_viewpoints",
        {
            "output_dir": str(output_dir),
            "resolution": 256,
            "max_viewpoints": 8,
            "selected_only": False,
        },
    )
    payload = json.loads(result["contentItems"][0]["text"])
    captures = payload.get("captures", [])
    if len(captures) < 5:
        raise AssertionError(f"Expected at least 5 captures, got {len(captures)}")
    missing = [item.get("path") for item in captures if not Path(str(item.get("path", ""))).exists()]
    if missing:
        raise AssertionError(f"Missing capture files: {missing}")
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

    print(
        json.dumps(
            {
                "ok": True,
                "captures": len(captures),
                "capture_failed": payload.get("capture_failed", False),
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
