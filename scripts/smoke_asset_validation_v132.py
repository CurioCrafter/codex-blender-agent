from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    import bpy
except ImportError:  # pragma: no cover - imported by normal Python static tests
    bpy = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SMOKE_STEPS = (
    "load_addon",
    "empty_scene_asset_validation",
    "detect_overlap_floater_zfight_topology",
    "capture_attaches_validation_report",
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


def _cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return obj


def _plane(name: str, location: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def _degenerate_mesh(name: str, location: tuple[float, float, float]) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def _payload(result: dict) -> dict:
    return json.loads(result["contentItems"][0]["text"])


def main() -> None:
    _ensure_registered()
    from codex_blender_agent.runtime import get_runtime

    runtime = get_runtime()

    _clear_scene()
    empty = _payload(runtime._execute_dynamic_tool(bpy.context, "validate_gpt_asset", {"selected_only": False}))
    if empty.get("status") != "no_target_geometry":
        raise AssertionError("Empty validation should return no_target_geometry.")

    _cube("Overlap_A", (0, 0, 0), (1, 1, 1))
    _cube("Overlap_B", (0.25, 0, 0), (1, 1, 1))
    _cube("Floating_Shard", (0, 0, 4), (0.2, 0.2, 0.2))
    _plane("Duplicate_Panel_A", (3, 0, 0))
    _plane("Duplicate_Panel_B", (3, 0, 0.0001))
    _degenerate_mesh("Degenerate_Triangle", (5, 0, 0))
    bpy.context.view_layer.update()

    report = _payload(runtime._execute_dynamic_tool(bpy.context, "validate_gpt_asset", {"selected_only": False}))
    issue_types = {issue.get("type") for issue in report.get("issues", [])}
    expected = {"interpenetration", "floating_part", "z_fighting_risk", "degenerate_geometry"}
    if not expected.intersection(issue_types) >= {"interpenetration", "floating_part", "degenerate_geometry"}:
        raise AssertionError(f"Missing core validation issues: {sorted(issue_types)}")
    if "z_fighting_risk" not in issue_types and "duplicate_surface_risk" not in issue_types:
        raise AssertionError(f"Missing duplicate/coplanar surface risk: {sorted(issue_types)}")
    if not report.get("report_id"):
        raise AssertionError("Validation report should have a report_id.")

    original_camera = bpy.context.scene.camera
    original_resolution = (
        bpy.context.scene.render.resolution_x,
        bpy.context.scene.render.resolution_y,
        bpy.context.scene.render.resolution_percentage,
    )
    original_filepath = bpy.context.scene.render.filepath
    output_dir = Path(tempfile.mkdtemp(prefix="codex_asset_validation_smoke_"))
    capture = _payload(
        runtime._execute_dynamic_tool(
            bpy.context,
            "capture_scene_viewpoints",
            {
                "output_dir": str(output_dir),
                "resolution": 192,
                "max_viewpoints": 6,
                "selected_only": False,
                "use_geometry_planner": True,
                "geometry_settings": {"candidate_view_count": 24, "selected_capture_count": 6, "audit_view_count": 2},
            },
        )
    )
    if not capture.get("asset_validation_report") or not capture.get("validation_report_id"):
        raise AssertionError("Capture should attach an asset validation report.")
    if not capture.get("validation_issues"):
        raise AssertionError("Capture should attach validation issues.")
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

    print(json.dumps({"ok": True, "steps": SMOKE_STEPS, "issues": sorted(issue_types), "report_id": report["report_id"]}, indent=2))


if __name__ == "__main__":
    main()
