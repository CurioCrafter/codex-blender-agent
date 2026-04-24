from __future__ import annotations

bl_info = {
    "name": "Codex Blender Agent",
    "author": "OpenAI Codex",
    "version": (0, 16, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > AI",
    "description": "Use Codex as a chat-first Blender game-creation assistant with optional Workflow and Assets workspaces.",
    "category": "3D View",
}

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - imported outside Blender for tests
    bpy = None


if bpy is not None:
    from . import operators, preferences, properties, runtime, ui, workflow_nodes

    def register() -> None:
        preferences.register()
        properties.register()
        operators.register()
        ui.register()
        workflow_nodes.register()
        runtime.register_timer()

    def unregister() -> None:
        runtime.unregister_timer()
        workflow_nodes.unregister()
        ui.unregister()
        operators.unregister()
        properties.unregister()
        preferences.unregister()

else:  # pragma: no cover - imported outside Blender for tests
    def register() -> None:
        raise RuntimeError("This add-on can only be registered inside Blender.")

    def unregister() -> None:
        return None
