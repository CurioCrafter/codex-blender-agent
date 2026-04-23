from __future__ import annotations

from pathlib import Path


def _configure() -> None:
    import bpy  # type: ignore

    legacy = {"AI Dashboard": "AI Studio", "AI Workflow": "Workflow", "AI Assets": "Assets"}
    for old, new in legacy.items():
        workspace = bpy.data.workspaces.get(old)
        if workspace and not bpy.data.workspaces.get(new):
            workspace.name = new
        elif workspace and bpy.data.workspaces.get(new):
            try:
                if bpy.context.window:
                    bpy.context.window.workspace = workspace
                bpy.ops.workspace.delete()
            except Exception:
                workspace.name = f"Legacy {old}"

    def tag(name: str, kind: str) -> None:
        workspace = bpy.data.workspaces.get(name)
        if not workspace:
            return
        workspace["codex_blender_agent"] = True
        workspace["codex_workspace_kind"] = kind
        workspace["codex_workspace_version"] = 9
        workspace["codex_dashboard_version"] = 9
        for attr in ("use_pin_scene", "pin_scene"):
            if hasattr(workspace, attr):
                try:
                    setattr(workspace, attr, False)
                except Exception:
                    pass

    def assign_roles(name: str, roles: tuple[str, ...]) -> None:
        workspace = bpy.data.workspaces.get(name)
        if not workspace or not workspace.screens:
            return
        if bpy.context.window:
            try:
                bpy.context.window.workspace = workspace
            except Exception:
                pass
        areas = sorted(list(workspace.screens[0].areas), key=lambda area: area.width * area.height, reverse=True)
        used: set[int] = set()
        for role in roles:
            area = next((item for item in areas if id(item) not in used and item.type == role), None)
            if area is None:
                candidates = [item for item in areas if id(item) not in used]
                if not candidates:
                    break
                area = candidates[0]
                try:
                    area.type = role
                except Exception as exc:
                    print("AREA_ROLE_FAILED", name, role, exc)
            used.add(id(area))
            if role == "FILE_BROWSER":
                for space in area.spaces:
                    if space.type == "FILE_BROWSER":
                        try:
                            space.browse_mode = "ASSETS"
                        except Exception:
                            pass

    assign_roles("AI Studio", ("VIEW_3D", "OUTLINER", "INFO"))
    assign_roles("Workflow", ("NODE_EDITOR", "VIEW_3D", "SPREADSHEET", "INFO"))
    assign_roles("Assets", ("FILE_BROWSER", "VIEW_3D", "PROPERTIES", "INFO"))
    tag("AI Studio", "studio")
    tag("Workflow", "workflow")
    tag("Assets", "assets")
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(__file__).resolve().parents[1] / "codex_blender_agent" / "workspace_templates.blend"))


def _timer_main():
    import bpy  # type: ignore

    try:
        _configure()
        print("WORKSPACE_TEMPLATE_REGENERATED", [workspace.name for workspace in bpy.data.workspaces])
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    import bpy  # type: ignore

    bpy.app.timers.register(_timer_main, first_interval=0.5)
