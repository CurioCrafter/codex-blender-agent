from __future__ import annotations

from functools import lru_cache
from typing import Any

import bpy


COMMON_SURFACES = [
    "VIEW_3D",
    "TEXT_EDITOR",
    "PROPERTIES",
    "OUTLINER",
    "NODE_EDITOR",
    "DOPESHEET_EDITOR",
    "GRAPH_EDITOR",
    "NLA_EDITOR",
    "IMAGE_EDITOR",
    "SEQUENCE_EDITOR",
    "SPREADSHEET",
    "FILE_BROWSER",
    "CONSOLE",
    "INFO",
    "PREFERENCES",
]


def list_blender_surfaces(context: bpy.types.Context) -> dict[str, Any]:
    screen = context.window.screen if context.window else None
    open_areas = []
    if screen is not None:
        for area in screen.areas:
            open_areas.append(
                {
                    "type": area.type,
                    "width": area.width,
                    "height": area.height,
                    "regions": [region.type for region in area.regions],
                    "active_space": area.spaces.active.type if area.spaces.active else "",
                }
            )
    active = context.view_layer.objects.active
    return {
        "workspace": context.window.workspace.name if context.window and context.window.workspace else "",
        "open_areas": open_areas,
        "common_surfaces": COMMON_SURFACES,
        "active_object": active.name if active else "",
        "active_mode": active.mode if active else "OBJECT",
        "selected_objects": [obj.name for obj in context.selected_objects],
    }


def list_cached_operator_namespaces(limit_per_namespace: int = 80) -> dict[str, Any]:
    namespaces = {}
    for namespace in _operator_namespaces():
        operator_namespace = getattr(bpy.ops, namespace, None)
        if operator_namespace is None:
            continue
        names = [name for name in dir(operator_namespace) if not name.startswith("_")]
        namespaces[namespace] = names[:limit_per_namespace]
    return {"namespaces": namespaces, "namespace_count": len(namespaces)}


@lru_cache(maxsize=1)
def _operator_namespaces() -> tuple[str, ...]:
    return tuple(name for name in dir(bpy.ops) if not name.startswith("_"))
