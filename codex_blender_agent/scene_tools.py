from __future__ import annotations

import contextlib
import io
import json
import math
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy
import mathutils

from .addon_settings import get_addon_preferences
from .asset_validation import validate_scene_asset
from .scene_summary import build_scene_digest, build_selection_digest
from .visual_review import plan_viewpoints
from .visual_view_planner import plan_geometry_review_viewpoints


class BlenderToolError(RuntimeError):
    pass


_DATA_COLLECTION_ALIASES = {
    "object": "objects",
    "objects": "objects",
    "mesh": "meshes",
    "meshes": "meshes",
    "material": "materials",
    "materials": "materials",
    "armature": "armatures",
    "armatures": "armatures",
    "camera": "cameras",
    "cameras": "cameras",
    "light": "lights",
    "lights": "lights",
    "collection": "collections",
    "collections": "collections",
    "image": "images",
    "images": "images",
    "action": "actions",
    "actions": "actions",
    "curve": "curves",
    "curves": "curves",
    "grease_pencil": "grease_pencils",
    "grease_pencils": "grease_pencils",
    "lattice": "lattices",
    "lattices": "lattices",
    "node_group": "node_groups",
    "node_groups": "node_groups",
    "node_tree": "node_groups",
    "palette": "palettes",
    "palettes": "palettes",
    "particle": "particles",
    "particles": "particles",
    "scene": "scenes",
    "scenes": "scenes",
    "screen": "screens",
    "screens": "screens",
    "sound": "sounds",
    "sounds": "sounds",
    "speaker": "speakers",
    "speakers": "speakers",
    "text": "texts",
    "texts": "texts",
    "texture": "textures",
    "textures": "textures",
    "volume": "volumes",
    "volumes": "volumes",
    "world": "worlds",
    "worlds": "worlds",
    "workspace": "workspaces",
    "workspaces": "workspaces",
    "brush": "brushes",
    "brushes": "brushes",
}

_MUTATING_TOOL_NAMES = {
    "create_primitive",
    "create_mesh_object",
    "create_empty",
    "rename_object",
    "duplicate_object",
    "set_transform",
    "set_custom_property",
    "set_blender_property",
    "set_object_visibility",
    "set_parent",
    "create_vertex_group",
    "assign_vertex_group",
    "delete_object",
    "create_collection",
    "move_object_to_collection",
    "create_material",
    "assign_material",
    "add_modifier",
    "remove_modifier",
    "apply_modifier",
    "create_light",
    "create_camera",
    "insert_keyframe",
    "set_frame_range",
    "add_armature_bone",
    "set_bone_deform",
    "delete_armature_bones",
    "set_pose_bone_transform",
    "import_file",
    "call_blender_operator",
    "execute_blender_python",
}


def execute_tool(context: bpy.types.Context, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise BlenderToolError(f"Unknown Blender tool: {tool_name}")
    if tool_name in _MUTATING_TOOL_NAMES:
        _push_undo_step(f"Codex {tool_name}")
    return handler(context, arguments or {})


def _success(text: str) -> dict[str, Any]:
    return {
        "success": True,
        "contentItems": [{"type": "inputText", "text": text}],
    }


def _failure(text: str) -> dict[str, Any]:
    return {
        "success": False,
        "contentItems": [{"type": "inputText", "text": text}],
    }


def _push_undo_step(message: str) -> None:
    try:
        bpy.ops.ed.undo_push(message=message)
    except Exception:
        pass


def _vector3(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BlenderToolError(f"{name} must be a list of 3 numbers.")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise BlenderToolError(f"{name} must contain only numbers.") from exc


def _vector4(value: Any, name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise BlenderToolError(f"{name} must be a list of 4 numbers.")
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except (TypeError, ValueError) as exc:
        raise BlenderToolError(f"{name} must contain only numbers.") from exc


def _find_object(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise BlenderToolError(f"Object '{name}' was not found.")
    return obj


def _find_armature(name: str) -> bpy.types.Object:
    obj = _find_object(name)
    if obj.type != "ARMATURE":
        raise BlenderToolError(f"Object '{name}' is not an armature.")
    return obj


def _set_active_object(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _enter_mode(obj: bpy.types.Object, mode: str) -> None:
    _set_active_object(obj)
    with _override_context():
        bpy.ops.object.mode_set(mode=mode)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)


def _expert_tools_enabled(context: bpy.types.Context) -> bool:
    preferences = get_addon_preferences(context, fallback=True)
    return bool(getattr(preferences, "enable_expert_tools", False))


def _operator_bridge_enabled(context: bpy.types.Context) -> bool:
    preferences = get_addon_preferences(context, fallback=True)
    return bool(getattr(preferences, "enable_operator_bridge", True) or getattr(preferences, "enable_expert_tools", False))


def _python_execution_enabled(context: bpy.types.Context) -> bool:
    preferences = get_addon_preferences(context, fallback=True)
    return bool(getattr(preferences, "enable_python_execution", False) or getattr(preferences, "enable_expert_tools", False))


def _area_override(area_type: str = "VIEW_3D", region_type: str = "WINDOW") -> dict[str, Any]:
    area_type = (area_type or "VIEW_3D").upper()
    region_type = (region_type or "WINDOW").upper()
    window_manager = bpy.context.window_manager
    for window in window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != area_type:
                continue
            for region in area.regions:
                if region.type == region_type:
                    return {
                        "window": window,
                        "screen": screen,
                        "area": area,
                        "region": region,
                    }
    return {}


def _view3d_override() -> dict[str, Any]:
    return _area_override("VIEW_3D", "WINDOW")


@contextlib.contextmanager
def _override_context(area_type: str | None = None, region_type: str | None = None, switch_area_if_missing: bool = False):
    override = _area_override(area_type or "VIEW_3D", region_type or "WINDOW")
    if override:
        with bpy.context.temp_override(**override):
            yield
        return

    requested_area = (area_type or "").strip().upper()
    if switch_area_if_missing and requested_area and getattr(bpy.context, "area", None) is not None:
        area = bpy.context.area
        previous_type = area.type
        try:
            area.type = requested_area
            switched_override = _area_override(requested_area, region_type or "WINDOW")
            if switched_override:
                with bpy.context.temp_override(**switched_override):
                    yield
            else:
                yield
        finally:
            try:
                area.type = previous_type
            except Exception:
                pass
        return

    yield


def _ensure_object_mode() -> None:
    obj = bpy.context.active_object
    if obj is None or obj.mode == "OBJECT":
        return
    with _override_context():
        bpy.ops.object.mode_set(mode="OBJECT")


def _describe_object(obj: bpy.types.Object) -> str:
    location = tuple(float(value) for value in obj.location)
    scale = tuple(float(value) for value in obj.scale)
    return f"{obj.name} [{obj.type}] loc={location} scale={scale}"


def _object_details(obj: bpy.types.Object) -> dict[str, Any]:
    return {
        "name": obj.name,
        "type": obj.type,
        "data": obj.data.name if getattr(obj, "data", None) else None,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler) if hasattr(obj, "rotation_euler") else None,
        "scale": list(obj.scale),
        "parent": obj.parent.name if obj.parent else None,
        "children": [child.name for child in obj.children],
        "collections": [collection.name for collection in obj.users_collection],
        "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
        "modifiers": [{"name": mod.name, "type": mod.type, "show_viewport": mod.show_viewport} for mod in obj.modifiers],
        "custom_properties": {key: obj[key] for key in obj.keys()},
        "animation_data": bool(obj.animation_data),
    }


def _armature_summary(obj: bpy.types.Object) -> dict[str, Any]:
    return {
        "object": obj.name,
        "data": obj.data.name,
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "use_deform": bone.use_deform,
                "head_local": list(bone.head_local),
                "tail_local": list(bone.tail_local),
                "children": [child.name for child in bone.children],
            }
            for bone in obj.data.bones
        ],
        "pose_bones": [
            {
                "name": pose_bone.name,
                "location": list(pose_bone.location),
                "rotation_euler": list(pose_bone.rotation_euler),
                "scale": list(pose_bone.scale),
            }
            for pose_bone in obj.pose.bones
        ],
    }


def _jsonable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (mathutils.Vector, mathutils.Euler, mathutils.Quaternion)):
        return list(value)
    if isinstance(value, mathutils.Matrix):
        return [list(row) for row in value]
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(item) for item in value]
    if hasattr(value, "name"):
        return {
            "name": getattr(value, "name", ""),
            "type": type(value).__name__,
        }
    return repr(value)


def _resolve_rna_target(context: bpy.types.Context, target_type: str, target_name: str | None) -> Any:
    target_type = (target_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    target_name = (target_name or "").strip()

    if target_type in {"active_object", "selected_object"}:
        target = context.view_layer.objects.active if target_type == "active_object" else (context.selected_objects[0] if context.selected_objects else None)
        if target is None:
            raise BlenderToolError(f"No {target_type} is available.")
        return target

    if target_type in {"object_data", "active_object_data", "data"}:
        obj = _find_object(target_name) if target_name else context.view_layer.objects.active
        if obj is None or obj.data is None:
            raise BlenderToolError("No object data target is available.")
        return obj.data

    if target_type == "active_material":
        obj = _find_object(target_name) if target_name else context.view_layer.objects.active
        material = obj.active_material if obj is not None else None
        if material is None:
            raise BlenderToolError("No active material is available.")
        return material

    if target_type == "scene":
        return bpy.data.scenes.get(target_name) if target_name else context.scene

    if target_type == "world":
        target = bpy.data.worlds.get(target_name) if target_name else context.scene.world
        if target is None:
            raise BlenderToolError("World target was not found.")
        return target

    if target_type == "view_layer":
        if target_name:
            for view_layer in context.scene.view_layers:
                if view_layer.name == target_name:
                    return view_layer
            raise BlenderToolError(f"View layer '{target_name}' was not found.")
        return context.view_layer

    if target_type == "modifier":
        object_name, modifier_name = _split_compound_target(target_name, "modifier")
        modifier = _find_object(object_name).modifiers.get(modifier_name)
        if modifier is None:
            raise BlenderToolError(f"Modifier '{modifier_name}' was not found on {object_name}.")
        return modifier

    if target_type in {"pose_bone", "bone"}:
        armature_name, bone_name = _split_compound_target(target_name, target_type)
        armature = _find_armature(armature_name)
        if target_type == "pose_bone":
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is None:
                raise BlenderToolError(f"Pose bone '{bone_name}' was not found on {armature_name}.")
            return pose_bone
        bone = armature.data.bones.get(bone_name)
        if bone is None:
            raise BlenderToolError(f"Bone '{bone_name}' was not found on {armature_name}.")
        return bone

    collection_name = _DATA_COLLECTION_ALIASES.get(target_type) or target_type
    if not hasattr(bpy.data, collection_name) and not collection_name.endswith("s"):
        collection_name = f"{collection_name}s"
    collection = getattr(bpy.data, collection_name, None)
    if collection is None:
        known = ", ".join(sorted(_DATA_COLLECTION_ALIASES.keys()))
        raise BlenderToolError(f"Unsupported RNA target type '{target_type}'. Try active_object, object_data, active_material, scene, world, view_layer, modifier, pose_bone, or one of: {known}.")
    if not target_name:
        raise BlenderToolError(f"target_name is required for target_type={target_type}.")
    target = collection.get(target_name)
    if target is None:
        raise BlenderToolError(f"Blender {target_type} target was not found: {target_name}")
    return target


def _split_compound_target(target_name: str, target_type: str) -> tuple[str, str]:
    for delimiter in ("::", "/", "|", ":"):
        if delimiter in target_name:
            left, right = target_name.split(delimiter, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    raise BlenderToolError(f"{target_type} target_name must be formatted as 'ObjectName/ItemName'.")


def _set_rna_path_value(target: Any, data_path: str, value: Any) -> None:
    data_path = (data_path or "").strip()
    if not data_path:
        raise BlenderToolError("data_path is required.")
    if "." in data_path:
        owner_path, attr = data_path.rsplit(".", 1)
        owner = target.path_resolve(owner_path)
    else:
        owner = target
        attr = data_path
    if not hasattr(owner, attr):
        raise BlenderToolError(f"Property '{attr}' was not found on resolved RNA target.")
    try:
        setattr(owner, attr, value)
    except TypeError:
        if isinstance(value, list):
            setattr(owner, attr, tuple(value))
        else:
            raise


def _int_sequence(value: Any, name: str, min_items: int = 0) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) < min_items:
        raise BlenderToolError(f"{name} must be a list with at least {min_items} items.")
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise BlenderToolError(f"{name} must contain only integers.") from exc


def _resolve_operator(operator_id: str) -> Any:
    operator_id = (operator_id or "").strip()
    if "." not in operator_id:
        raise BlenderToolError("operator must look like 'object.shade_smooth', 'mesh.extrude_region_move', or 'wm.save_as_mainfile'.")
    namespace, op_name = operator_id.split(".", 1)
    operator_namespace = getattr(bpy.ops, namespace, None)
    if operator_namespace is None:
        raise BlenderToolError(f"Unknown bpy.ops namespace: {namespace}")
    operator = getattr(operator_namespace, op_name, None)
    if operator is None:
        raise BlenderToolError(f"Unknown bpy.ops operator: {operator_id}")
    return operator


def _normalize_mode(mode: Any) -> str:
    text = str(mode or "").strip().upper()
    aliases = {
        "EDIT_MESH": "EDIT",
        "EDIT_ARMATURE": "EDIT",
        "EDIT_CURVE": "EDIT",
        "OBJECT_MODE": "OBJECT",
        "POSE_MODE": "POSE",
        "SCULPT_MODE": "SCULPT",
    }
    return aliases.get(text, text)


def _apply_operator_context(arguments: dict[str, Any]) -> None:
    active_name = str(arguments.get("active_object", "") or "").strip()
    selected_names = [str(name) for name in arguments.get("selected_objects", []) if str(name).strip()]
    mode = _normalize_mode(arguments.get("mode"))
    switch_area = bool(arguments.get("switch_area_if_missing", True))

    if active_name or selected_names:
        _ensure_object_mode()
        with _override_context(arguments.get("area_type"), arguments.get("region_type"), switch_area):
            bpy.ops.object.select_all(action="DESELECT")
        selected_objects = [_find_object(name) for name in selected_names]
        active_object = _find_object(active_name) if active_name else (selected_objects[0] if selected_objects else None)
        for obj in selected_objects:
            obj.select_set(True)
        if active_object is not None:
            active_object.select_set(True)
            bpy.context.view_layer.objects.active = active_object

    if mode:
        active_object = bpy.context.view_layer.objects.active
        if active_object is None:
            raise BlenderToolError("mode was provided, but no active object is available.")
        with _override_context(arguments.get("area_type"), arguments.get("region_type"), switch_area):
            result = bpy.ops.object.mode_set(mode=mode)
        if "FINISHED" not in result:
            raise BlenderToolError(f"Could not switch active object to mode {mode}.")


@contextlib.contextmanager
def _temporary_operator_context(arguments: dict[str, Any]):
    previous_active = bpy.context.view_layer.objects.active
    previous_selected = list(bpy.context.selected_objects)
    previous_mode_object = previous_active
    previous_mode = previous_mode_object.mode if previous_mode_object is not None else "OBJECT"
    try:
        _apply_operator_context(arguments)
        switch_area = bool(arguments.get("switch_area_if_missing", True))
        with _override_context(arguments.get("area_type"), arguments.get("region_type"), switch_area):
            yield
    finally:
        try:
            current_active = bpy.context.view_layer.objects.active
            if current_active is not None and current_active.mode != "OBJECT":
                with _override_context(arguments.get("area_type"), arguments.get("region_type"), bool(arguments.get("switch_area_if_missing", True))):
                    bpy.ops.object.mode_set(mode="OBJECT")
            with _override_context(arguments.get("area_type"), arguments.get("region_type"), bool(arguments.get("switch_area_if_missing", True))):
                bpy.ops.object.select_all(action="DESELECT")
            for obj in previous_selected:
                if bpy.data.objects.get(obj.name) is not None:
                    obj.select_set(True)
            if previous_active is not None and bpy.data.objects.get(previous_active.name) is not None:
                bpy.context.view_layer.objects.active = previous_active
                if previous_mode != "OBJECT":
                    with _override_context(arguments.get("area_type"), arguments.get("region_type"), bool(arguments.get("switch_area_if_missing", True))):
                        bpy.ops.object.mode_set(mode=previous_mode)
        except Exception:
            pass


def _operator_poll(operator: Any) -> bool:
    poll = getattr(operator, "poll", None)
    if poll is None:
        return True
    try:
        return bool(poll())
    except Exception:
        return False


def _operator_status_finished(result: Any) -> bool:
    if isinstance(result, set):
        return "FINISHED" in result
    if isinstance(result, (list, tuple)):
        return "FINISHED" in result
    return result == {"FINISHED"} or result == "FINISHED"


def _operator_rna(operator: Any) -> Any:
    get_rna_type = getattr(operator, "get_rna_type", None)
    if get_rna_type is None:
        return None
    try:
        return get_rna_type()
    except Exception:
        return None


def _operator_metadata(operator_id: str, operator: Any, include_properties: bool = False) -> dict[str, Any]:
    rna = _operator_rna(operator)
    data: dict[str, Any] = {
        "operator": operator_id,
        "name": getattr(rna, "name", "") if rna else "",
        "description": getattr(rna, "description", "") if rna else "",
    }
    if include_properties:
        data["properties"] = _operator_properties(rna)
    return data


def _operator_properties(rna: Any) -> list[dict[str, Any]]:
    if rna is None:
        return []
    properties = []
    for prop in getattr(rna, "properties", []):
        identifier = getattr(prop, "identifier", "")
        if identifier == "rna_type":
            continue
        item: dict[str, Any] = {
            "identifier": identifier,
            "name": getattr(prop, "name", ""),
            "description": getattr(prop, "description", ""),
            "type": getattr(prop, "type", ""),
            "subtype": getattr(prop, "subtype", ""),
            "is_required": bool(getattr(prop, "is_required", False)),
            "is_readonly": bool(getattr(prop, "is_readonly", False)),
        }
        if hasattr(prop, "default"):
            try:
                item["default"] = _jsonable_value(prop.default)
            except Exception:
                pass
        if hasattr(prop, "default_array"):
            try:
                item["default"] = _jsonable_value(list(prop.default_array))
            except Exception:
                pass
        if getattr(prop, "type", "") == "ENUM":
            enum_items = []
            try:
                for enum_item in prop.enum_items:
                    enum_items.append(
                        {
                            "identifier": enum_item.identifier,
                            "name": enum_item.name,
                            "description": enum_item.description,
                        }
                    )
            except Exception:
                pass
            item["enum_items"] = enum_items
        properties.append(item)
    return properties


def _tool_get_scene_summary(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    return _success(build_scene_digest(context))


def _tool_get_selection(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    return _success(build_selection_digest(context))


def _tool_list_data_blocks(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    data_type = arguments.get("data_type")
    limit = int(arguments.get("limit", 100))
    collection_name = _DATA_COLLECTION_ALIASES.get(str(data_type or "").lower(), str(data_type or ""))
    collection = getattr(bpy.data, collection_name, None)
    if collection is None:
        raise BlenderToolError(f"Unsupported data type: {data_type}")
    items = []
    for item in list(collection)[:limit]:
        items.append(
            {
                "name": item.name,
                "users": getattr(item, "users", None),
                "library": item.library.filepath if getattr(item, "library", None) else None,
            }
        )
    return _success(_json_text({"data_type": data_type, "count": len(collection), "items": items}))


def _tool_get_object_details(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    details = _object_details(obj)
    if obj.type == "MESH" and obj.data:
        details["mesh"] = {
            "vertices": len(obj.data.vertices),
            "edges": len(obj.data.edges),
            "polygons": len(obj.data.polygons),
            "shape_keys": [key.name for key in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [],
        }
    if obj.type == "ARMATURE":
        details["armature"] = _armature_summary(obj)
    return _success(_json_text(details))


def _tool_get_blender_property(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_rna_target(context, str(arguments.get("target_type", "")), arguments.get("target_name"))
    data_path = str(arguments.get("data_path", "")).strip()
    if not data_path:
        raise BlenderToolError("data_path is required.")
    value = target.path_resolve(data_path)
    return _success(_json_text({"data_path": data_path, "value": _jsonable_value(value)}))


def _tool_set_blender_property(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_rna_target(context, str(arguments.get("target_type", "")), arguments.get("target_name"))
    data_path = str(arguments.get("data_path", "")).strip()
    _set_rna_path_value(target, data_path, arguments.get("value"))
    context.view_layer.update()
    target_name = getattr(target, "name", str(arguments.get("target_type", "")))
    return _success(f"Set {target_name}.{data_path}.")


def _tool_create_primitive(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    primitive = arguments.get("primitive")
    if not isinstance(primitive, str):
        raise BlenderToolError("primitive is required.")

    location = _vector3(arguments.get("location", [0.0, 0.0, 0.0]), "location")
    rotation = _vector3(arguments.get("rotation_euler", [0.0, 0.0, 0.0]), "rotation_euler")
    scale = _vector3(arguments.get("scale", [1.0, 1.0, 1.0]), "scale")
    name = arguments.get("name")

    primitive_ops = {
        "cube": bpy.ops.mesh.primitive_cube_add,
        "plane": bpy.ops.mesh.primitive_plane_add,
        "uv_sphere": bpy.ops.mesh.primitive_uv_sphere_add,
        "ico_sphere": bpy.ops.mesh.primitive_ico_sphere_add,
        "cylinder": bpy.ops.mesh.primitive_cylinder_add,
        "cone": bpy.ops.mesh.primitive_cone_add,
        "torus": bpy.ops.mesh.primitive_torus_add,
        "monkey": bpy.ops.mesh.primitive_monkey_add,
    }
    operator = primitive_ops.get(primitive)
    if operator is None:
        raise BlenderToolError(f"Unsupported primitive type: {primitive}")

    _ensure_object_mode()
    with _override_context():
        result = operator(location=location, rotation=rotation)
    if "FINISHED" not in result:
        return _failure(f"Blender could not create a {primitive}.")

    obj = bpy.context.active_object
    if obj is None:
        return _failure(f"Blender created a {primitive}, but the new object could not be resolved.")

    obj.scale = scale
    if isinstance(name, str) and name.strip():
        obj.name = name.strip()

    return _success(f"Created {_describe_object(obj)}.")


def _tool_create_mesh_object(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    vertices = [_vector3(vertex, "vertices item") for vertex in arguments.get("vertices", [])]
    if not vertices:
        raise BlenderToolError("vertices must contain at least one vertex.")
    edges = [_int_sequence(edge, "edge", min_items=2)[:2] for edge in arguments.get("edges", [])]
    faces = [_int_sequence(face, "face", min_items=3) for face in arguments.get("faces", [])]

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, edges, faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)

    collection_name = str(arguments.get("collection_name", "")).strip()
    collection = bpy.data.collections.get(collection_name) if collection_name else context.collection
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        context.scene.collection.children.link(collection)
    collection.objects.link(obj)

    obj.location = _vector3(arguments.get("location", [0.0, 0.0, 0.0]), "location")
    obj.rotation_euler = _vector3(arguments.get("rotation_euler", [0.0, 0.0, 0.0]), "rotation_euler")
    obj.scale = _vector3(arguments.get("scale", [1.0, 1.0, 1.0]), "scale")

    material_name = str(arguments.get("material_name", "")).strip()
    if material_name:
        material = bpy.data.materials.get(material_name)
        if material is None:
            raise BlenderToolError(f"Material '{material_name}' was not found.")
        obj.data.materials.append(material)

    context.view_layer.update()
    return _success(f"Created mesh {obj.name} with {len(vertices)} vertices, {len(edges)} edges, and {len(faces)} faces.")


def _tool_create_empty(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = str(arguments.get("empty_display_type", "PLAIN_AXES")).upper()
    context.collection.objects.link(obj)
    obj.location = _vector3(arguments.get("location", [0.0, 0.0, 0.0]), "location")
    obj.rotation_euler = _vector3(arguments.get("rotation_euler", [0.0, 0.0, 0.0]), "rotation_euler")
    obj.scale = _vector3(arguments.get("scale", [1.0, 1.0, 1.0]), "scale")
    return _success(f"Created empty {_describe_object(obj)}.")


def _tool_rename_object(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    new_name = str(arguments.get("new_name", "")).strip()
    if not new_name:
        raise BlenderToolError("new_name is required.")
    old_name = obj.name
    obj.name = new_name
    return _success(f"Renamed {old_name} to {obj.name}.")


def _tool_duplicate_object(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    source = _find_object(str(arguments.get("object_name", "")))
    duplicate = source.copy()
    if not arguments.get("linked_data", False) and source.data is not None:
        duplicate.data = source.data.copy()
    if arguments.get("new_name"):
        duplicate.name = str(arguments["new_name"])
    context.collection.objects.link(duplicate)
    if "location" in arguments:
        duplicate.location = _vector3(arguments["location"], "location")
    if "rotation_euler" in arguments:
        duplicate.rotation_euler = _vector3(arguments["rotation_euler"], "rotation_euler")
    if "scale" in arguments:
        duplicate.scale = _vector3(arguments["scale"], "scale")
    return _success(f"Duplicated {source.name} as {_describe_object(duplicate)}.")


def _tool_set_transform(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    object_name = arguments.get("object_name")
    if not isinstance(object_name, str) or not object_name.strip():
        raise BlenderToolError("object_name is required.")

    obj = _find_object(object_name)
    if "location" in arguments:
        obj.location = _vector3(arguments["location"], "location")
    if "rotation_euler" in arguments:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = _vector3(arguments["rotation_euler"], "rotation_euler")
    if "scale" in arguments:
        obj.scale = _vector3(arguments["scale"], "scale")

    context.view_layer.update()
    return _success(f"Updated {_describe_object(obj)}.")


def _tool_set_custom_property(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    property_name = str(arguments.get("property_name", "")).strip()
    if not property_name:
        raise BlenderToolError("property_name is required.")
    obj[property_name] = arguments.get("value")
    return _success(f"Set custom property {property_name} on {obj.name}.")


def _tool_set_object_visibility(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    if "hide_viewport" in arguments:
        obj.hide_viewport = bool(arguments["hide_viewport"])
    if "hide_render" in arguments:
        obj.hide_render = bool(arguments["hide_render"])
    if "display_type" in arguments:
        obj.display_type = str(arguments["display_type"]).upper()
    return _success(
        f"Updated visibility for {obj.name}: hide_viewport={obj.hide_viewport}, hide_render={obj.hide_render}, display_type={obj.display_type}."
    )


def _tool_set_parent(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    child = _find_object(str(arguments.get("child_name", "")))
    parent_name = str(arguments.get("parent_name", "")).strip()
    keep_transform = bool(arguments.get("keep_transform", True))
    original_matrix = child.matrix_world.copy() if keep_transform else None

    if not parent_name:
        child.parent = None
        child.parent_type = "OBJECT"
        child.parent_bone = ""
        if original_matrix is not None:
            child.matrix_world = original_matrix
        return _success(f"Cleared parent for {child.name}.")

    parent = _find_object(parent_name)
    parent_type = str(arguments.get("parent_type", "OBJECT")).upper()
    if parent_type == "BONE":
        bone_name = str(arguments.get("parent_bone", "")).strip()
        if parent.type != "ARMATURE":
            raise BlenderToolError("Bone parenting requires an armature parent.")
        if not bone_name or parent.data.bones.get(bone_name) is None:
            raise BlenderToolError(f"Parent bone '{bone_name}' was not found on {parent.name}.")
        child.parent = parent
        child.parent_type = "BONE"
        child.parent_bone = bone_name
    else:
        child.parent = parent
        child.parent_type = "ARMATURE" if parent_type == "ARMATURE" else "OBJECT"
        child.parent_bone = ""

    if original_matrix is not None:
        child.matrix_world = original_matrix
    context.view_layer.update()
    suffix = f" bone {child.parent_bone}" if child.parent_type == "BONE" else ""
    return _success(f"Parented {child.name} to {parent.name}{suffix}.")


def _tool_create_vertex_group(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    if obj.type != "MESH":
        raise BlenderToolError(f"{obj.name} is not a mesh object.")
    group_name = str(arguments.get("group_name", "")).strip()
    if not group_name:
        raise BlenderToolError("group_name is required.")
    existing = obj.vertex_groups.get(group_name)
    if existing is not None and arguments.get("replace_existing", False):
        obj.vertex_groups.remove(existing)
        existing = None
    group = existing or obj.vertex_groups.new(name=group_name)
    return _success(f"Vertex group {group.name} is available on {obj.name} at index {group.index}.")


def _tool_assign_vertex_group(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    if obj.type != "MESH":
        raise BlenderToolError(f"{obj.name} is not a mesh object.")
    group_name = str(arguments.get("group_name", "")).strip()
    group = obj.vertex_groups.get(group_name) or obj.vertex_groups.new(name=group_name)
    if arguments.get("all_vertices", False):
        indices = [vertex.index for vertex in obj.data.vertices]
    else:
        indices = _int_sequence(arguments.get("vertex_indices", []), "vertex_indices")
    if not indices:
        raise BlenderToolError("No vertex indices were provided.")
    weight = float(arguments.get("weight", 1.0))
    mode = str(arguments.get("mode", "REPLACE")).upper()
    group.add(indices, weight, mode)
    return _success(f"Assigned {len(indices)} vertices to {group.name} on {obj.name} with weight {weight}.")


def _tool_delete_object(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    object_names = arguments.get("object_names")
    if not isinstance(object_names, list) or not object_names:
        raise BlenderToolError("object_names must be a non-empty list.")

    objects = [_find_object(str(name)) for name in object_names]
    names = [obj.name for obj in objects]
    _ensure_object_mode()

    with _override_context():
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        result = bpy.ops.object.delete(use_global=False)
    if "FINISHED" not in result:
        return _failure(f"Blender could not delete: {', '.join(names)}")

    return _success(f"Deleted objects: {', '.join(names)}.")


def _tool_create_collection(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    collection = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    parent_name = arguments.get("parent_collection")
    if parent_name:
        parent = bpy.data.collections.get(str(parent_name))
        if parent is None:
            raise BlenderToolError(f"Parent collection '{parent_name}' was not found.")
        if parent.children.get(collection.name) is None:
            parent.children.link(collection)
    elif context.scene.collection.children.get(collection.name) is None:
        context.scene.collection.children.link(collection)
    return _success(f"Created collection {collection.name}.")


def _tool_move_object_to_collection(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    collection_name = str(arguments.get("collection_name", "")).strip()
    if not collection_name:
        raise BlenderToolError("collection_name is required.")
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        context.scene.collection.children.link(collection)
    if collection.objects.get(obj.name) is None:
        collection.objects.link(obj)
    if arguments.get("unlink_from_other_collections", False):
        for existing in list(obj.users_collection):
            if existing != collection:
                existing.objects.unlink(obj)
    return _success(f"Moved {obj.name} to collection {collection.name}.")


def _tool_create_material(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    base_color = arguments.get("base_color")
    if base_color is not None:
        material.diffuse_color = _vector4(base_color, "base_color")
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if principled is not None:
        if base_color is not None and "Base Color" in principled.inputs:
            principled.inputs["Base Color"].default_value = _vector4(base_color, "base_color")
        if "metallic" in arguments and "Metallic" in principled.inputs:
            principled.inputs["Metallic"].default_value = float(arguments["metallic"])
        if "roughness" in arguments and "Roughness" in principled.inputs:
            principled.inputs["Roughness"].default_value = float(arguments["roughness"])
    return _success(f"Created/updated material {material.name}.")


def _tool_assign_material(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    material = bpy.data.materials.get(str(arguments.get("material_name", "")))
    if material is None:
        raise BlenderToolError(f"Material '{arguments.get('material_name')}' was not found.")
    slot_index = int(arguments.get("slot_index", 0))
    names = []
    object_names = arguments.get("object_names", [])
    if not isinstance(object_names, list) or not object_names:
        raise BlenderToolError("object_names must be a non-empty list.")
    for object_name in object_names:
        obj = _find_object(str(object_name))
        if obj.data is None or not hasattr(obj.data, "materials"):
            raise BlenderToolError(f"{obj.name} does not support material slots.")
        while len(obj.data.materials) <= slot_index:
            obj.data.materials.append(None)
        obj.data.materials[slot_index] = material
        names.append(obj.name)
    return _success(f"Assigned {material.name} to {', '.join(names)}.")


def _tool_add_modifier(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    modifier_type = str(arguments.get("modifier_type", "")).upper()
    if not modifier_type:
        raise BlenderToolError("modifier_type is required.")
    name = str(arguments.get("name") or modifier_type.title())
    modifier = obj.modifiers.new(name=name, type=modifier_type)
    for key, value in (arguments.get("properties") or {}).items():
        if hasattr(modifier, key):
            setattr(modifier, key, value)
    return _success(f"Added {modifier.type} modifier {modifier.name} to {obj.name}.")


def _tool_remove_modifier(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    modifier = obj.modifiers.get(str(arguments.get("modifier_name", "")))
    if modifier is None:
        raise BlenderToolError(f"Modifier '{arguments.get('modifier_name')}' was not found on {obj.name}.")
    obj.modifiers.remove(modifier)
    return _success(f"Removed modifier {arguments.get('modifier_name')} from {obj.name}.")


def _tool_apply_modifier(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    modifier_name = str(arguments.get("modifier_name", ""))
    _ensure_object_mode()
    _set_active_object(obj)
    with _override_context():
        result = bpy.ops.object.modifier_apply(modifier=modifier_name)
    if "FINISHED" not in result:
        return _failure(f"Could not apply modifier {modifier_name} on {obj.name}.")
    return _success(f"Applied modifier {modifier_name} on {obj.name}.")


def _tool_create_light(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    light_type = str(arguments.get("light_type", "POINT")).upper()
    data = bpy.data.lights.new(name=name, type=light_type)
    obj = bpy.data.objects.new(name, data)
    context.collection.objects.link(obj)
    obj.location = _vector3(arguments.get("location", [0.0, 0.0, 0.0]), "location")
    if "energy" in arguments:
        data.energy = float(arguments["energy"])
    if "color" in arguments:
        data.color = _vector3(arguments["color"], "color")
    return _success(f"Created light {_describe_object(obj)}.")


def _tool_create_camera(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise BlenderToolError("name is required.")
    data = bpy.data.cameras.new(name=name)
    obj = bpy.data.objects.new(name, data)
    context.collection.objects.link(obj)
    obj.location = _vector3(arguments.get("location", [0.0, 0.0, 0.0]), "location")
    obj.rotation_euler = _vector3(arguments.get("rotation_euler", [0.0, 0.0, 0.0]), "rotation_euler")
    if "focal_length" in arguments:
        data.lens = float(arguments["focal_length"])
    if arguments.get("make_active", False):
        context.scene.camera = obj
    return _success(f"Created camera {_describe_object(obj)}.")


def _tool_capture_scene_viewpoints(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(arguments.get("output_dir") or Path(tempfile.gettempdir()) / "codex_visual_review")).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    resolution = max(128, min(int(arguments.get("resolution", 1024)), 4096))
    max_viewpoints = max(1, min(int(arguments.get("max_viewpoints", 10)), 16))
    selected_only = bool(arguments.get("selected_only", False))
    records = _capture_object_records(context, selected_only=selected_only)
    planner_payload: dict[str, Any] = {}
    planner_settings: dict[str, Any] = {}
    supplied_viewpoints = arguments.get("viewpoints")
    if supplied_viewpoints:
        viewpoints = supplied_viewpoints
    elif bool(arguments.get("use_geometry_planner", True)):
        planner_settings = dict(arguments.get("geometry_settings") or {}) if isinstance(arguments.get("geometry_settings"), dict) else {}
        planner_settings.setdefault("selected_capture_count", max_viewpoints)
        planner_payload = plan_geometry_review_viewpoints(records, settings=planner_settings)
        viewpoints = planner_payload.get("selected_viewpoints") or planner_payload.get("viewpoints") or []
    else:
        viewpoints = plan_viewpoints(records)
    if not isinstance(viewpoints, list):
        raise BlenderToolError("viewpoints must be a list when provided.")
    viewpoints = viewpoints[:max_viewpoints]
    if not viewpoints and records:
        viewpoints = plan_viewpoints([])

    scene = context.scene
    original_camera = scene.camera
    original_filepath = scene.render.filepath
    original_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage)
    created_cameras: list[bpy.types.Object] = []
    captures: list[dict[str, Any]] = []
    diagnostics: list[str] = []

    try:
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        for index, viewpoint in enumerate(viewpoints, start=1):
            view_id = _safe_filename(str(viewpoint.get("id") or f"view_{index:02d}"))
            path = output_dir / f"{index:02d}_{view_id}.png"
            camera = _create_review_camera(context, viewpoint, index)
            created_cameras.append(camera)
            scene.camera = camera
            scene.render.filepath = str(path)
            method = "opengl"
            ok = False
            error = ""
            try:
                with _override_context("VIEW_3D", "WINDOW", switch_area_if_missing=True):
                    result = bpy.ops.render.opengl(write_still=True, view_context=False)
                ok = "FINISHED" in result and path.exists()
            except Exception as exc:
                error = str(exc)
                diagnostics.append(f"{view_id}: OpenGL capture failed: {error}")
            if not ok:
                method = "placeholder"
                _write_placeholder_png(path)
            captures.append(
                {
                    "id": view_id,
                    "label": str(viewpoint.get("label") or view_id),
                    "kind": str(viewpoint.get("kind") or "coverage"),
                    "path": str(path),
                    "method": method,
                    "camera": {
                        "name": camera.name,
                        "location": [float(value) for value in camera.location],
                        "rotation_euler": [float(value) for value in camera.rotation_euler],
                        "lens": float(camera.data.lens),
                    },
                    "viewpoint": viewpoint,
                    "error": error,
                }
            )
    finally:
        scene.camera = original_camera
        scene.render.filepath = original_filepath
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = original_resolution
        for camera in created_cameras:
            data = camera.data
            try:
                bpy.data.objects.remove(camera, do_unlink=True)
            except Exception:
                pass
            try:
                if data and data.users == 0:
                    bpy.data.cameras.remove(data)
            except Exception:
                pass

    payload = {
        "captures": captures,
        "viewpoints": viewpoints,
        "object_count": len(records),
        "objects": records,
        "output_dir": str(output_dir),
        "resolution": resolution,
        "scene_digest": build_scene_digest(context),
        "diagnostics": diagnostics,
        "capture_failed": not captures or all(item.get("method") == "placeholder" for item in captures),
    }
    if planner_payload:
        payload.update(
            {
                "geometry_digest": planner_payload.get("geometry_digest", {}),
                "view_scores": planner_payload.get("view_scores", []),
                "coverage_by_part": planner_payload.get("coverage_by_part", {}),
                "defects": planner_payload.get("defects", []),
                "metric_vector": planner_payload.get("metric_vector", {}),
                "hard_gates": planner_payload.get("hard_gates", {}),
                "planner_diagnostics": planner_payload.get("diagnostics", []),
                "optimization_viewpoints": planner_payload.get("optimization_viewpoints", []),
                "audit_viewpoints": planner_payload.get("audit_viewpoints", []),
            }
        )
    validation_report = validate_scene_asset(
        context,
        selected_only=selected_only,
        settings=planner_settings or (dict(arguments.get("geometry_settings") or {}) if isinstance(arguments.get("geometry_settings"), dict) else {}),
        coverage_by_part=dict(planner_payload.get("coverage_by_part", {}) or {}),
        intent_manifest=(planner_settings or {}).get("intent_manifest") if isinstance(planner_settings, dict) else None,
    )
    payload["asset_validation_report"] = validation_report
    payload["validation_report_id"] = str(validation_report.get("report_id", ""))
    payload["validation_metrics"] = dict(validation_report.get("metric_vector", {}) or {})
    payload["validation_issues"] = list(validation_report.get("issues", []) or [])
    if validation_report.get("issues"):
        payload["defects"] = list(validation_report.get("issues", []) or [])
    if validation_report.get("metric_vector"):
        payload["metric_vector"] = dict(validation_report.get("metric_vector", {}) or {})
    if validation_report.get("hard_gates"):
        payload["hard_gates"] = dict(validation_report.get("hard_gates", {}) or {})
    diagnostics.append(str(validation_report.get("validation_summary", "VERIFYING completed.")))
    return _success(_json_text(payload))


def _capture_object_records(context: bpy.types.Context, *, selected_only: bool = False) -> list[dict[str, Any]]:
    source = list(context.selected_objects or []) if selected_only and context.selected_objects else []
    if not source:
        source = [obj for obj in context.scene.objects if not obj.hide_get() and obj.type not in {"CAMERA", "LIGHT"}]
    records = []
    for obj in source:
        world_bounds = []
        try:
            world_bounds = [list(obj.matrix_world @ mathutils.Vector(corner)) for corner in obj.bound_box]
        except Exception:
            world_bounds = []
        material_names = []
        material_slot_count = 0
        try:
            material_slot_count = len(getattr(obj, "material_slots", []) or [])
            material_names = [
                slot.material.name
                for slot in getattr(obj, "material_slots", []) or []
                if getattr(slot, "material", None) is not None
            ]
        except Exception:
            material_names = []
        collections = []
        try:
            collections = [collection.name for collection in getattr(obj, "users_collection", []) or []]
        except Exception:
            collections = []
        vertex_count = 0
        face_count = 0
        try:
            data = getattr(obj, "data", None)
            vertex_count = len(getattr(data, "vertices", []) or [])
            face_count = len(getattr(data, "polygons", []) or [])
        except Exception:
            vertex_count = 0
            face_count = 0
        records.append(
            {
                "name": obj.name,
                "type": obj.type,
                "location": [float(value) for value in obj.location],
                "dimensions": [float(value) for value in getattr(obj, "dimensions", (1.0, 1.0, 1.0))],
                "bounds": world_bounds,
                "material_names": material_names,
                "material_slot_count": material_slot_count,
                "collections": collections,
                "vertex_count": vertex_count,
                "face_count": face_count,
            }
        )
    return records


def _create_review_camera(context: bpy.types.Context, viewpoint: dict[str, Any], index: int) -> bpy.types.Object:
    camera_data = bpy.data.cameras.new(name=f"CodexReviewCamera_{index:02d}")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    context.collection.objects.link(camera)
    location = _vector3(viewpoint.get("camera_location", [0.0, -5.0, 3.0]), "camera_location")
    target = mathutils.Vector(_vector3(viewpoint.get("target", [0.0, 0.0, 0.0]), "target"))
    camera.location = location
    direction = target - camera.location
    if direction.length < 0.001:
        direction = mathutils.Vector((0.0, 0.0, -1.0))
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = float(viewpoint.get("focal_length", 38.0))
    camera.data.angle = math.radians(50.0)
    clip_range = viewpoint.get("clip_range", {})
    if isinstance(clip_range, dict):
        try:
            camera.data.clip_start = max(0.001, float(clip_range.get("near", camera.data.clip_start)))
            camera.data.clip_end = max(camera.data.clip_start + 0.1, float(clip_range.get("far", camera.data.clip_end)))
        except (TypeError, ValueError):
            pass
    return camera


def _safe_filename(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "view"


def _write_placeholder_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000002000100ffff03000006000557bfab00000000"
            "49454e44ae426082"
        )
    )


def _tool_insert_keyframe(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    obj = _find_object(str(arguments.get("object_name", "")))
    data_path = str(arguments.get("data_path", ""))
    frame = float(arguments.get("frame"))
    obj.keyframe_insert(data_path=data_path, frame=frame)
    return _success(f"Inserted keyframe for {obj.name}.{data_path} at frame {frame}.")


def _tool_set_frame_range(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    if "frame_start" in arguments:
        context.scene.frame_start = int(arguments["frame_start"])
    if "frame_end" in arguments:
        context.scene.frame_end = int(arguments["frame_end"])
    if "frame_current" in arguments:
        context.scene.frame_set(int(arguments["frame_current"]))
    return _success(f"Frame range is {context.scene.frame_start}-{context.scene.frame_end}, current {context.scene.frame_current}.")


def _tool_get_armature_summary(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    armature = _find_armature(str(arguments.get("armature_name", "")))
    return _success(_json_text(_armature_summary(armature)))


def _tool_add_armature_bone(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    armature = _find_armature(str(arguments.get("armature_name", "")))
    bone_name = str(arguments.get("bone_name", "")).strip()
    if not bone_name:
        raise BlenderToolError("bone_name is required.")

    previous_mode = armature.mode
    _enter_mode(armature, "EDIT")
    try:
        edit_bone = armature.data.edit_bones.new(bone_name)
        edit_bone.head = mathutils.Vector(_vector3(arguments.get("head"), "head"))
        edit_bone.tail = mathutils.Vector(_vector3(arguments.get("tail"), "tail"))
        parent_name = arguments.get("parent")
        if parent_name:
            parent = armature.data.edit_bones.get(str(parent_name))
            if parent is None:
                raise BlenderToolError(f"Parent bone '{parent_name}' was not found.")
            edit_bone.parent = parent
        use_deform = bool(arguments.get("use_deform", True))
        with _override_context():
            bpy.ops.object.mode_set(mode="OBJECT")
        armature.data.bones[bone_name].use_deform = use_deform
    finally:
        if previous_mode != "OBJECT":
            with _override_context():
                bpy.ops.object.mode_set(mode=previous_mode)
    return _success(f"Added bone {bone_name} to {armature.name}.")


def _tool_set_bone_deform(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    armature = _find_armature(str(arguments.get("armature_name", "")))
    use_deform = bool(arguments.get("use_deform"))
    updated = []
    for bone_name in arguments.get("bone_names", []):
        bone = armature.data.bones.get(str(bone_name))
        if bone is None:
            raise BlenderToolError(f"Bone '{bone_name}' was not found on {armature.name}.")
        bone.use_deform = use_deform
        updated.append(bone.name)
    return _success(f"Set use_deform={use_deform} on bones: {', '.join(updated)}.")


def _tool_delete_armature_bones(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    armature = _find_armature(str(arguments.get("armature_name", "")))
    bone_names = [str(name) for name in arguments.get("bone_names", [])]
    if not bone_names:
        raise BlenderToolError("bone_names must be a non-empty list.")
    previous_mode = armature.mode
    _enter_mode(armature, "EDIT")
    try:
        for bone_name in bone_names:
            edit_bone = armature.data.edit_bones.get(bone_name)
            if edit_bone is None:
                raise BlenderToolError(f"Edit bone '{bone_name}' was not found on {armature.name}.")
            armature.data.edit_bones.remove(edit_bone)
    finally:
        with _override_context():
            bpy.ops.object.mode_set(mode="OBJECT")
        if previous_mode != "OBJECT":
            with _override_context():
                bpy.ops.object.mode_set(mode=previous_mode)
    return _success(f"Deleted bones from {armature.name}: {', '.join(bone_names)}.")


def _tool_set_pose_bone_transform(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    armature = _find_armature(str(arguments.get("armature_name", "")))
    pose_bone = armature.pose.bones.get(str(arguments.get("bone_name", "")))
    if pose_bone is None:
        raise BlenderToolError(f"Pose bone '{arguments.get('bone_name')}' was not found on {armature.name}.")
    pose_bone.rotation_mode = "XYZ"
    if "location" in arguments:
        pose_bone.location = _vector3(arguments["location"], "location")
    if "rotation_euler" in arguments:
        pose_bone.rotation_euler = _vector3(arguments["rotation_euler"], "rotation_euler")
    if "scale" in arguments:
        pose_bone.scale = _vector3(arguments["scale"], "scale")
    if arguments.get("insert_keyframe", False):
        frame = float(arguments.get("frame", context.scene.frame_current))
        pose_bone.keyframe_insert(data_path="location", frame=frame)
        pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
    context.view_layer.update()
    return _success(f"Updated pose bone {pose_bone.name} on {armature.name}.")


def _tool_import_file(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(arguments.get("filepath", ""))).expanduser()
    if not path.exists():
        raise BlenderToolError(f"Import file does not exist: {path}")
    file_type = str(arguments.get("file_type", "auto")).lower()
    if file_type == "auto":
        file_type = path.suffix.lower().lstrip(".")
    with _override_context():
        if file_type == "fbx":
            result = bpy.ops.import_scene.fbx(filepath=str(path))
        elif file_type == "obj":
            if hasattr(bpy.ops.wm, "obj_import"):
                result = bpy.ops.wm.obj_import(filepath=str(path))
            else:
                result = bpy.ops.import_scene.obj(filepath=str(path))
        elif file_type in {"gltf", "glb"}:
            result = bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            raise BlenderToolError(f"Unsupported import file type: {file_type}")
    if "FINISHED" not in result:
        return _failure(f"Blender could not import {path}.")
    return _success(f"Imported {path}.")


def _tool_export_fbx(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    filepath = str(arguments.get("filepath", "")).strip()
    if not filepath:
        raise BlenderToolError("filepath is required.")
    path = Path(filepath).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    object_names = arguments.get("object_names") or []
    use_selection = bool(arguments.get("use_selection", bool(object_names)))
    if object_names:
        bpy.ops.object.select_all(action="DESELECT")
        selected = []
        for object_name in object_names:
            obj = _find_object(str(object_name))
            obj.select_set(True)
            selected.append(obj.name)
        if selected:
            bpy.context.view_layer.objects.active = bpy.data.objects[selected[0]]
    object_types = set(arguments.get("object_types") or ["ARMATURE", "MESH"])
    kwargs = {
        "filepath": str(path),
        "use_selection": use_selection,
        "object_types": object_types,
        "add_leaf_bones": bool(arguments.get("add_leaf_bones", False)),
        "use_armature_deform_only": bool(arguments.get("use_armature_deform_only", True)),
        "bake_anim": bool(arguments.get("bake_anim", True)),
        "axis_forward": str(arguments.get("axis_forward", "-Z")),
        "axis_up": str(arguments.get("axis_up", "Y")),
    }
    with _override_context():
        result = bpy.ops.export_scene.fbx(**kwargs)
    if "FINISHED" not in result:
        return _failure(f"Blender could not export FBX to {path}.")
    return _success(f"Exported FBX to {path}. Settings: {_json_text(kwargs)}")


def _tool_list_blender_operators(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    namespace_filter = str(arguments.get("namespace", "") or "").strip().lower()
    search = str(arguments.get("search", "") or "").strip().lower()
    limit = int(arguments.get("limit", 200))
    include_poll = bool(arguments.get("include_poll", False))
    results: list[dict[str, Any]] = []

    namespaces = []
    if namespace_filter:
        namespaces = [namespace_filter]
    else:
        namespaces = [name for name in dir(bpy.ops) if not name.startswith("_")]

    with _temporary_operator_context(arguments):
        for namespace in namespaces:
            operator_namespace = getattr(bpy.ops, namespace, None)
            if operator_namespace is None:
                continue
            for op_name in dir(operator_namespace):
                if op_name.startswith("_"):
                    continue
                operator_id = f"{namespace}.{op_name}"
                operator = getattr(operator_namespace, op_name, None)
                if operator is None:
                    continue
                metadata = _operator_metadata(operator_id, operator, include_properties=False)
                haystack = f"{operator_id} {metadata.get('name', '')} {metadata.get('description', '')}".lower()
                if search and search not in haystack:
                    continue
                if include_poll:
                    metadata["poll"] = _operator_poll(operator)
                results.append(metadata)
                if len(results) >= limit:
                    return _success(_json_text({"count": len(results), "truncated": True, "operators": results}))

    return _success(_json_text({"count": len(results), "truncated": False, "operators": results}))


def _tool_inspect_blender_operator(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    operator_id = str(arguments.get("operator", ""))
    operator = _resolve_operator(operator_id)
    with _temporary_operator_context(arguments):
        metadata = _operator_metadata(operator_id, operator, include_properties=True)
        metadata["poll"] = _operator_poll(operator)
    return _success(_json_text(metadata))


def _tool_check_blender_operator_poll(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    operator_id = str(arguments.get("operator", ""))
    operator = _resolve_operator(operator_id)
    with _temporary_operator_context(arguments):
        poll_result = _operator_poll(operator)
    return _success(_json_text({"operator": operator_id, "poll": poll_result}))


def _tool_call_blender_operator(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    if not _operator_bridge_enabled(context):
        return _failure("The full Blender operator bridge is disabled in add-on preferences.")
    operator_id = str(arguments.get("operator", ""))
    operator = _resolve_operator(operator_id)

    _apply_operator_context(arguments)
    properties = arguments.get("properties") or {}
    if not isinstance(properties, dict):
        raise BlenderToolError("properties must be an object.")

    execution_context = str(arguments.get("execution_context", "") or "").strip().upper()
    with _override_context(arguments.get("area_type"), arguments.get("region_type"), bool(arguments.get("switch_area_if_missing", True))):
        if arguments.get("poll_first", True) and not _operator_poll(operator):
            return _failure(f"bpy.ops.{operator_id}.poll() returned False for the requested context.")
        if execution_context:
            result = operator(execution_context, **properties)
        else:
            result = operator(**properties)
    if not _operator_status_finished(result):
        return _failure(f"bpy.ops.{operator_id} returned {result}; Blender did not report FINISHED.")
    return _success(f"Called bpy.ops.{operator_id}, result={result}.")


def _tool_execute_blender_python(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    if not _python_execution_enabled(context):
        return _failure("Python execution is disabled in add-on preferences.")
    code = str(arguments.get("code", ""))
    if not code.strip():
        raise BlenderToolError("code is required.")
    stdout = io.StringIO()
    globals_dict = {
        "__name__": "__codex_blender_agent_exec__",
        "bpy": bpy,
        "mathutils": mathutils,
        "context": context,
    }
    with contextlib.redirect_stdout(stdout):
        exec(compile(code, "<codex_blender_agent>", "exec"), globals_dict, globals_dict)
    output = stdout.getvalue().strip()
    if len(output) > 6000:
        output = output[:6000] + "\n[Output truncated.]"
    return _success(output or "Executed Blender Python.")


def _tool_undo(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    steps = int(arguments.get("steps", 1))
    if steps < 1 or steps > 10:
        raise BlenderToolError("steps must be between 1 and 10.")

    _ensure_object_mode()
    with _override_context():
        for _ in range(steps):
            result = bpy.ops.ed.undo()
            if "FINISHED" not in result:
                return _failure("Blender could not undo the requested step.")
    return _success(f"Undid {steps} step(s).")


def _tool_save_checkpoint_copy(context: bpy.types.Context, arguments: dict[str, Any]) -> dict[str, Any]:
    filepath_arg = arguments.get("filepath")
    if filepath_arg:
        target = Path(str(filepath_arg))
    else:
        current = Path(bpy.data.filepath) if bpy.data.filepath else None
        if current is not None:
            directory = current.parent
            stem = current.stem
        else:
            directory = Path(tempfile.gettempdir())
            stem = "untitled"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"{stem}.codex-checkpoint-{timestamp}.blend"

    target.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True, check_existing=False)
    if "FINISHED" not in result:
        return _failure(f"Blender could not save a checkpoint copy to {target}.")
    return _success(f"Saved checkpoint copy to {target}.")


_TOOL_HANDLERS = {
    "get_scene_summary": _tool_get_scene_summary,
    "get_selection": _tool_get_selection,
    "list_data_blocks": _tool_list_data_blocks,
    "get_object_details": _tool_get_object_details,
    "get_blender_property": _tool_get_blender_property,
    "set_blender_property": _tool_set_blender_property,
    "create_primitive": _tool_create_primitive,
    "create_mesh_object": _tool_create_mesh_object,
    "create_empty": _tool_create_empty,
    "rename_object": _tool_rename_object,
    "duplicate_object": _tool_duplicate_object,
    "set_transform": _tool_set_transform,
    "set_custom_property": _tool_set_custom_property,
    "set_object_visibility": _tool_set_object_visibility,
    "set_parent": _tool_set_parent,
    "create_vertex_group": _tool_create_vertex_group,
    "assign_vertex_group": _tool_assign_vertex_group,
    "delete_object": _tool_delete_object,
    "create_collection": _tool_create_collection,
    "move_object_to_collection": _tool_move_object_to_collection,
    "create_material": _tool_create_material,
    "assign_material": _tool_assign_material,
    "add_modifier": _tool_add_modifier,
    "remove_modifier": _tool_remove_modifier,
    "apply_modifier": _tool_apply_modifier,
    "create_light": _tool_create_light,
    "create_camera": _tool_create_camera,
    "capture_scene_viewpoints": _tool_capture_scene_viewpoints,
    "insert_keyframe": _tool_insert_keyframe,
    "set_frame_range": _tool_set_frame_range,
    "get_armature_summary": _tool_get_armature_summary,
    "add_armature_bone": _tool_add_armature_bone,
    "set_bone_deform": _tool_set_bone_deform,
    "delete_armature_bones": _tool_delete_armature_bones,
    "set_pose_bone_transform": _tool_set_pose_bone_transform,
    "import_file": _tool_import_file,
    "export_fbx": _tool_export_fbx,
    "list_blender_operators": _tool_list_blender_operators,
    "inspect_blender_operator": _tool_inspect_blender_operator,
    "check_blender_operator_poll": _tool_check_blender_operator_poll,
    "call_blender_operator": _tool_call_blender_operator,
    "execute_blender_python": _tool_execute_blender_python,
    "undo": _tool_undo,
    "save_checkpoint_copy": _tool_save_checkpoint_copy,
}
