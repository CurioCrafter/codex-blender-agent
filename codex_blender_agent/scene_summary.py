from __future__ import annotations

import math

import bpy


def _format_triplet(values) -> str:
    return f"({values[0]:.2f}, {values[1]:.2f}, {values[2]:.2f})"


def _object_line(obj: bpy.types.Object) -> str:
    location = _format_triplet(obj.location)
    scale = _format_triplet(obj.scale)
    if hasattr(obj, "rotation_euler"):
        rotation = _format_triplet(tuple(math.degrees(value) for value in obj.rotation_euler))
    else:
        rotation = "(n/a)"
    modifiers = ", ".join(mod.type for mod in obj.modifiers[:4])
    modifier_suffix = f", modifiers={modifiers}" if modifiers else ""
    return f"- {obj.name} [{obj.type}] loc={location}, rot_deg={rotation}, scale={scale}{modifier_suffix}"


def build_selection_digest(context: bpy.types.Context) -> str:
    selected = list(context.selected_objects)
    if not selected:
        return "No objects are currently selected."

    lines = [f"Selected objects ({len(selected)}):"]
    for obj in selected:
        lines.append(_object_line(obj))
    return "\n".join(lines)


def build_scene_digest(context: bpy.types.Context, max_objects: int = 18) -> str:
    scene = context.scene
    objects = list(scene.objects)
    selected = list(context.selected_objects)
    active = context.active_object
    filepath = bpy.data.filepath or "Unsaved blend file"

    type_counts: dict[str, int] = {}
    for obj in objects:
        type_counts[obj.type] = type_counts.get(obj.type, 0) + 1

    lines = [
        f"File: {filepath}",
        f"Scene: {scene.name}",
        f"Frame: {scene.frame_current}",
        f"Object count: {len(objects)}",
        f"Object types: {', '.join(f'{key}={value}' for key, value in sorted(type_counts.items())) or 'none'}",
        f"Selected objects: {', '.join(obj.name for obj in selected) or 'none'}",
        f"Active object: {active.name if active else 'none'}",
    ]

    materials = sorted(mat.name for mat in bpy.data.materials)[:10]
    if materials:
        lines.append(f"Materials: {', '.join(materials)}")

    lines.append("Objects:")
    for obj in sorted(objects, key=lambda item: item.name)[:max_objects]:
        lines.append(_object_line(obj))

    remaining = len(objects) - min(len(objects), max_objects)
    if remaining > 0:
        lines.append(f"- ... {remaining} more objects")

    return "\n".join(lines)
