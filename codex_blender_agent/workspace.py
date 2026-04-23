from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - imported outside Blender for tests
    bpy = None

from .chat_surfaces import ensure_chat_text_blocks


STUDIO_WORKSPACE_NAME = "AI Studio"
WORKSPACE_NAME = STUDIO_WORKSPACE_NAME
WORKFLOW_WORKSPACE_NAME = "Workflow"
ASSETS_WORKSPACE_NAME = "Assets"
LEGACY_WORKSPACE_NAMES = {
    "AI Dashboard": STUDIO_WORKSPACE_NAME,
    "AI Workflow": WORKFLOW_WORKSPACE_NAME,
    "AI Assets": ASSETS_WORKSPACE_NAME,
}
CODEX_WORKSPACE_NAMES = (STUDIO_WORKSPACE_NAME, WORKFLOW_WORKSPACE_NAME, ASSETS_WORKSPACE_NAME)
CODEX_WORKSPACE_KINDS = {
    STUDIO_WORKSPACE_NAME: "studio",
    WORKFLOW_WORKSPACE_NAME: "workflow",
    ASSETS_WORKSPACE_NAME: "assets",
    "AI Dashboard": "studio",
    "AI Workflow": "workflow",
    "AI Assets": "assets",
}
CODEX_KIND_WORKSPACE_NAMES = {
    "studio": STUDIO_WORKSPACE_NAME,
    "dashboard": STUDIO_WORKSPACE_NAME,
    "workflow": WORKFLOW_WORKSPACE_NAME,
    "assets": ASSETS_WORKSPACE_NAME,
}
LAST_WORKSPACE_RESULT: dict[str, Any] = {}
LAST_WORKSPACE_ERROR = ""
LAST_LAYOUT_SIGNATURE_BEFORE: tuple[str, ...] | None = None
LAST_LAYOUT_SIGNATURE_AFTER: tuple[str, ...] | None = None
LAST_REQUESTED_WORKSPACE = ""


class WorkspaceActivationError(RuntimeError):
    pass


def canonical_workspace_name(workspace_name: str) -> str:
    value = (workspace_name or STUDIO_WORKSPACE_NAME).strip()
    if value in LEGACY_WORKSPACE_NAMES:
        return LEGACY_WORKSPACE_NAMES[value]
    if value in CODEX_KIND_WORKSPACE_NAMES:
        return CODEX_KIND_WORKSPACE_NAMES[value]
    return value


def ensure_dashboard_workspace(context: bpy.types.Context, mode: str = "open") -> bpy.types.WorkSpace:
    return ensure_codex_workspace(context, STUDIO_WORKSPACE_NAME, mode=mode)


def ensure_studio_workspace(context: bpy.types.Context, mode: str = "open") -> bpy.types.WorkSpace:
    return ensure_codex_workspace(context, STUDIO_WORKSPACE_NAME, mode=mode)


def ensure_workflow_workspace(context: bpy.types.Context, mode: str = "open") -> bpy.types.WorkSpace:
    return ensure_codex_workspace(context, WORKFLOW_WORKSPACE_NAME, mode=mode)


def ensure_assets_workspace(context: bpy.types.Context, mode: str = "open") -> bpy.types.WorkSpace:
    return ensure_codex_workspace(context, ASSETS_WORKSPACE_NAME, mode=mode)


def ensure_codex_suite_workspaces(context: bpy.types.Context, mode: str = "setup") -> list[bpy.types.WorkSpace]:
    workspaces = [ensure_codex_workspace(context, workspace_name, mode=mode) for workspace_name in CODEX_WORKSPACE_NAMES]
    _order_codex_suite_after_builtin(context)
    return workspaces


def migrate_legacy_ai_workspaces(context: bpy.types.Context) -> dict[str, Any]:
    if bpy is None:
        return {}
    renamed = []
    blocked = []
    for legacy, canonical in LEGACY_WORKSPACE_NAMES.items():
        legacy_workspace = bpy.data.workspaces.get(legacy)
        canonical_workspace = bpy.data.workspaces.get(canonical)
        if legacy_workspace is None:
            continue
        _tag_workspace(legacy_workspace, canonical)
        _unpin_scene(legacy_workspace)
        if canonical_workspace is None:
            _rename_workspace_exact(legacy_workspace, canonical)
            renamed.append({"legacy": legacy, "canonical": canonical})
        elif canonical_workspace != legacy_workspace:
            blocked.append({"legacy": legacy, "canonical": canonical, "reason": "canonical workspace already exists"})
    return {
        "renamed": renamed,
        "blocked": blocked,
        "diagnostics": diagnose_dashboard_workspace(context),
    }


def ensure_codex_workspace(context: bpy.types.Context, workspace_name: str, mode: str = "open") -> bpy.types.WorkSpace:
    if bpy is None:
        raise RuntimeError("Blender is required to create Codex workspaces.")
    if context.window is None:
        raise RuntimeError("A Blender window is required to create Codex workspaces.")
    workspace_name = canonical_workspace_name(workspace_name)
    mode = mode if mode in {"open", "setup"} else "open"

    global LAST_LAYOUT_SIGNATURE_BEFORE, LAST_LAYOUT_SIGNATURE_AFTER, LAST_WORKSPACE_ERROR
    LAST_WORKSPACE_ERROR = ""
    previous_workspace = context.window.workspace
    LAST_LAYOUT_SIGNATURE_BEFORE = workspace_area_signature(context, "Layout")

    workspace = _find_codex_workspace(workspace_name)
    created_workspace = False
    if workspace is None:
        workspace = _create_workspace(context, workspace_name)
        created_workspace = True
    if workspace is None:
        raise RuntimeError(f"Blender did not create the {workspace_name} workspace.")

    if mode == "open" or created_workspace:
        _request_workspace_activation(context, workspace)
    _rename_workspace_exact(workspace, workspace_name)
    _tag_workspace(workspace, workspace_name)
    _unpin_scene(workspace)
    if created_workspace:
        _reorder_workspace_to_back(context, workspace)
    ensure_chat_text_blocks()
    configure_codex_workspace(context, workspace_name, workspace=workspace)

    LAST_LAYOUT_SIGNATURE_AFTER = workspace_area_signature(context, "Layout")
    if LAST_LAYOUT_SIGNATURE_BEFORE and LAST_LAYOUT_SIGNATURE_AFTER and LAST_LAYOUT_SIGNATURE_BEFORE != LAST_LAYOUT_SIGNATURE_AFTER:
        LAST_WORKSPACE_ERROR = "Layout workspace screen signature changed during AI workspace setup."
        raise WorkspaceActivationError(LAST_WORKSPACE_ERROR)

    if mode == "open":
        _request_workspace_activation(context, workspace)
    elif previous_workspace is not None and bpy.data.workspaces.get(previous_workspace.name) is not None:
        context.window.workspace = previous_workspace
    return workspace


def configure_dashboard_workspace(context: bpy.types.Context) -> None:
    configure_codex_workspace(context, STUDIO_WORKSPACE_NAME)


def configure_codex_workspace(context: bpy.types.Context, workspace_name: str, workspace: bpy.types.WorkSpace | None = None) -> None:
    if bpy is None or context.window is None:
        return
    workspace_name = canonical_workspace_name(workspace_name)
    workspace = workspace or bpy.data.workspaces.get(workspace_name)
    if workspace is None:
        raise WorkspaceActivationError(f"Workspace not found: {workspace_name}.")
    if not workspace.get("codex_blender_agent", False) and workspace.name not in CODEX_WORKSPACE_NAMES:
        raise WorkspaceActivationError(f"Refusing to configure non-AI workspace: {workspace.name}.")
    screen = workspace.screens[0] if getattr(workspace, "screens", None) and len(workspace.screens) else None
    if screen is None:
        raise WorkspaceActivationError(f"{workspace_name} has no screen to configure.")
    areas = list(screen.areas)
    if not areas:
        raise WorkspaceActivationError(f"{workspace_name} has no screen areas to configure.")

    if len(areas) == 1:
        if context.window.workspace.name != workspace_name:
            raise WorkspaceActivationError(f"{workspace_name} has too few areas and is not active for safe splitting.")
        _split_area(context, areas[0], "VERTICAL", 0.26)
        areas = list(screen.areas)
    if len(areas) == 2:
        if context.window.workspace.name != workspace_name:
            raise WorkspaceActivationError(f"{workspace_name} has too few areas and is not active for safe splitting.")
        largest = max(areas, key=lambda area: area.width * area.height)
        _split_area(context, largest, "HORIZONTAL", 0.72)
        areas = list(screen.areas)
    kind = _workspace_kind(workspace_name)
    if len(areas) == 3 and kind in {"workflow", "assets"}:
        if context.window.workspace.name != workspace_name:
            raise WorkspaceActivationError(f"{workspace_name} has too few areas and is not active for safe splitting.")
        largest = max(areas, key=lambda area: area.width * area.height)
        _split_area(context, largest, "VERTICAL", 0.78)
        areas = list(screen.areas)
    if len(areas) == 4 and _workspace_kind(workspace_name) in {"workflow", "assets"}:
        # Four real editors are enough for the studio layouts; templates may provide more.
        pass

    sorted_areas = sorted(areas, key=lambda area: area.width * area.height, reverse=True)
    if kind == "workflow":
        _configure_workflow_areas(context, workspace_name, sorted_areas)
    elif kind == "assets":
        _configure_assets_areas(context, workspace_name, sorted_areas)
    else:
        _configure_dashboard_areas(context, workspace_name, sorted_areas)


def dashboard_context(context: bpy.types.Context) -> dict[str, Any]:
    if bpy is None:
        return {}
    workspace = context.window.workspace if context.window else None
    screen = context.window.screen if context.window else None
    return {
        "workspace": workspace.name if workspace else "",
        "is_ai_studio": bool(workspace and workspace.get("codex_blender_agent", False)),
        "is_ai_dashboard": bool(workspace and workspace.get("codex_blender_agent", False)),
        "workspace_kind": workspace.get("codex_workspace_kind", "") if workspace else "",
        "areas": _area_payload(screen),
    }


def diagnose_dashboard_workspace(context: bpy.types.Context) -> dict[str, Any]:
    if bpy is None:
        return {}
    return workspace_diagnostic_payload(
        workspace_names=[workspace.name for workspace in bpy.data.workspaces],
        active_name=context.window.workspace.name if context.window and context.window.workspace else "",
        dashboard_name=STUDIO_WORKSPACE_NAME,
        tagged=bool((bpy.data.workspaces.get(STUDIO_WORKSPACE_NAME) or {}).get("codex_blender_agent", False)) if bpy.data.workspaces.get(STUDIO_WORKSPACE_NAME) else False,
        last_result=LAST_WORKSPACE_RESULT,
        expected_workspace=LAST_REQUESTED_WORKSPACE,
        last_exception=LAST_WORKSPACE_ERROR,
        layout_before=LAST_LAYOUT_SIGNATURE_BEFORE,
        layout_after=LAST_LAYOUT_SIGNATURE_AFTER,
        codex_workspaces=_codex_workspace_diagnostics(context),
    )


def verify_workspace_suite(context: bpy.types.Context) -> dict[str, Any]:
    if bpy is None:
        return {}
    previous = context.window.workspace if context.window else None
    results = []
    try:
        for workspace_name in CODEX_WORKSPACE_NAMES:
            workspace = bpy.data.workspaces.get(workspace_name)
            if workspace is None:
                results.append({"name": workspace_name, "exists": False, "active_verified": False, "areas": []})
                continue
            areas = _area_payload(workspace.screens[0] if len(workspace.screens) else None)
            area_types = [item["type"] for item in areas]
            results.append(
                {
                    "name": workspace_name,
                    "exists": True,
                    "active_verified": context.window.workspace.name == workspace_name if context.window else False,
                    "activation_requested": LAST_REQUESTED_WORKSPACE == workspace_name,
                    "kind": workspace.get("codex_workspace_kind", ""),
                    "pin_scene": _workspace_pin_scene(workspace),
                    "areas": areas,
                    "expected_area_types": _expected_area_types(workspace_name),
                    "preferred_area_types": _preferred_area_types(workspace_name),
                    "area_types_ok": _has_expected_area_types(area_types, _expected_area_types(workspace_name)),
                    "space_types_ok": _has_expected_spaces(areas, _expected_area_types(workspace_name)),
                    "missing_preferred_area_types": [
                        area_type for area_type in _preferred_area_types(workspace_name) if area_type not in area_types
                    ],
                }
            )
    finally:
        if previous is not None and context.window is not None and bpy.data.workspaces.get(previous.name) is not None:
            context.window.workspace = previous
    missing = [item["name"] for item in results if not item.get("exists")]
    bad_areas = [
        item["name"]
        for item in results
        if item.get("exists") and (not item.get("area_types_ok") or not item.get("space_types_ok"))
    ]
    layout_signature = workspace_area_signature(context, "Layout")
    missing_node_menu_entries = _missing_node_menu_entries()
    workspace_names = [workspace.name for workspace in bpy.data.workspaces]
    order_state = _workspace_order_state(workspace_names)
    pin_scene_bad = [item["name"] for item in results if item.get("exists") and item.get("pin_scene") is True]
    return {
        "ok": not missing
        and not bad_areas
        and not pin_scene_bad
        and not missing_node_menu_entries
        and "Layout" in workspace_names,
        "active_workspace": context.window.workspace.name if context.window and context.window.workspace else "",
        "workspace_order": workspace_names,
        "workspace_order_ok": order_state["ok"],
        "workspace_order_state": order_state,
        "legacy_aliases": _legacy_alias_diagnostics(),
        "layout_exists": bpy.data.workspaces.get("Layout") is not None,
        "layout_signature": layout_signature,
        "layout_preserved": LAST_LAYOUT_SIGNATURE_BEFORE in {None, layout_signature},
        "missing_workspaces": missing,
        "inactive_workspaces": [item["name"] for item in results if item.get("exists") and not item.get("active_verified")],
        "bad_area_workspaces": bad_areas,
        "pin_scene_workspaces": pin_scene_bad,
        "template_available": Path(__file__).with_name("workspace_templates.blend").exists(),
        "codex_workspaces": results,
        "last_operator_result": LAST_WORKSPACE_RESULT,
        "last_exception": LAST_WORKSPACE_ERROR,
        "repair_recommendations": _workspace_repair_recommendations(missing, bad_areas, pin_scene_bad, order_state),
        "missing_panels": [],
        "missing_node_menu_entries": missing_node_menu_entries,
    }


def workspace_diagnostic_payload(
    *,
    workspace_names: list[str],
    active_name: str,
    dashboard_name: str = STUDIO_WORKSPACE_NAME,
    tagged: bool = False,
    last_result: dict[str, Any] | None = None,
    expected_workspace: str = "",
    last_exception: str = "",
    layout_before: tuple[str, ...] | None = None,
    layout_after: tuple[str, ...] | None = None,
    codex_workspaces: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "workspace_names": workspace_names,
        "active_workspace": active_name,
        "expected_workspace": expected_workspace,
        "studio_workspace": dashboard_name,
        "studio_exists": dashboard_name in workspace_names,
        "studio_index": workspace_names.index(dashboard_name) if dashboard_name in workspace_names else -1,
        "workspace_order_ok": _workspace_order_state(workspace_names)["ok"],
        "workspace_order_state": _workspace_order_state(workspace_names),
        "studio_tagged": tagged,
        "dashboard_workspace": dashboard_name,
        "dashboard_exists": dashboard_name in workspace_names,
        "dashboard_index": workspace_names.index(dashboard_name) if dashboard_name in workspace_names else -1,
        "dashboard_tagged": tagged,
        "legacy_aliases": [
            {"legacy": legacy, "canonical": canonical, "exists": legacy in workspace_names}
            for legacy, canonical in LEGACY_WORKSPACE_NAMES.items()
        ],
        "layout_exists": "Layout" in workspace_names,
        "layout_before": list(layout_before or []),
        "layout_after": list(layout_after or []),
        "layout_preserved": not layout_before or not layout_after or layout_before == layout_after,
        "last_operator_result": last_result or {},
        "last_exception": last_exception,
        "codex_workspaces": codex_workspaces or [],
        "missing_panels": [],
        "missing_node_menu_entries": [],
    }


def operator_finished(result: Any) -> bool:
    if isinstance(result, set):
        return "FINISHED" in result
    if isinstance(result, (list, tuple)):
        return "FINISHED" in result
    return result == {"FINISHED"} or result == "FINISHED"


def workspace_area_signature(context: bpy.types.Context, workspace_name: str) -> tuple[str, ...] | None:
    if bpy is None:
        return None
    workspace = bpy.data.workspaces.get(workspace_name)
    if workspace is None or not getattr(workspace, "screens", None) or not len(workspace.screens):
        return None
    screen = workspace.screens[0]
    return tuple(f"{area.type}:{area.width}x{area.height}" for area in screen.areas)


def _create_workspace(context: bpy.types.Context, workspace_name: str):
    template_workspace = _append_workspace_template(context, workspace_name)
    if template_workspace is not None:
        return template_workspace
    added = _add_workspace(context, workspace_name)
    if added is not None:
        return added
    return _duplicate_workspace(context, workspace_name)


def _append_workspace_template(context: bpy.types.Context, workspace_name: str):
    template_blend = Path(__file__).with_name("workspace_templates.blend")
    if not template_blend.exists():
        _record_workspace_result("append_activate", "SKIPPED", "workspace_templates.blend not bundled")
        return None
    idnames = [workspace_name] + [legacy for legacy, canonical in LEGACY_WORKSPACE_NAMES.items() if canonical == workspace_name]
    last_error = ""
    for idname in idnames:
        try:
            result = bpy.ops.workspace.append_activate(idname=idname, filepath=str(template_blend))
        except Exception as exc:
            last_error = str(exc)
            _record_workspace_result("append_activate", "ERROR", f"{idname}: {exc}")
            continue
        _record_workspace_result("append_activate", result, f"idname={idname}")
        if not operator_finished(result):
            continue
        workspace = bpy.data.workspaces.get(idname) or context.window.workspace
        _rename_workspace_exact(workspace, workspace_name)
        _tag_workspace(workspace, workspace_name)
        _unpin_scene(workspace)
        return workspace
    if last_error:
        _record_workspace_result("append_activate", "ERROR", last_error)
    return None


def _add_workspace(context: bpy.types.Context, workspace_name: str):
    try:
        result = bpy.ops.workspace.add()
    except Exception as exc:
        _record_workspace_result("add", "ERROR", str(exc))
        return None
    _record_workspace_result("add", result)
    if not operator_finished(result):
        return None
    workspace = context.window.workspace
    _rename_workspace_exact(workspace, workspace_name)
    _tag_workspace(workspace, workspace_name)
    _unpin_scene(workspace)
    return workspace


def _duplicate_workspace(context: bpy.types.Context, workspace_name: str):
    before = {workspace.as_pointer() for workspace in bpy.data.workspaces}
    try:
        result = bpy.ops.workspace.duplicate()
    except Exception as exc:
        _record_workspace_result("duplicate", "ERROR", str(exc))
        return None
    _record_workspace_result("duplicate", result)
    if not operator_finished(result):
        return None
    created = [workspace for workspace in bpy.data.workspaces if workspace.as_pointer() not in before]
    workspace = created[-1] if created else context.window.workspace
    context.window.workspace = workspace
    _rename_workspace_exact(workspace, workspace_name)
    _tag_workspace(workspace, workspace_name)
    _unpin_scene(workspace)
    return workspace


def _activate_workspace(context: bpy.types.Context, workspace: bpy.types.WorkSpace) -> bool:
    try:
        context.window.workspace = workspace
    except Exception as exc:
        _record_workspace_result("activate", "ERROR", str(exc))
        return False
    active = context.window.workspace
    ok = active is not None and active.name == workspace.name
    if not ok:
        _record_workspace_result(
            "activate",
            "CANCELLED",
            f"active={active.name if active else '<none>'}; requested={workspace.name}",
        )
    return ok


def _request_workspace_activation(context: bpy.types.Context, workspace: bpy.types.WorkSpace) -> None:
    global LAST_REQUESTED_WORKSPACE
    LAST_REQUESTED_WORKSPACE = workspace.name
    _activate_workspace(context, workspace)


def _reorder_workspace_to_front(context: bpy.types.Context, workspace: bpy.types.WorkSpace) -> None:
    if context.window is None:
        _record_workspace_result("reorder_to_front", "SKIPPED", "No window context")
        return
    if context.window.workspace is None or context.window.workspace.name != workspace.name:
        _request_workspace_activation(context, workspace)
    if context.window.workspace is None or context.window.workspace.name != workspace.name:
        _record_workspace_result(
            "reorder_to_front",
            "SKIPPED",
            f"Active workspace is {context.window.workspace.name if context.window.workspace else '<none>'}; requested {workspace.name}",
        )
        return
    try:
        result = bpy.ops.workspace.reorder_to_front()
    except Exception as exc:
        _record_workspace_result("reorder_to_front", "ERROR", str(exc))
        return
    _record_workspace_result("reorder_to_front", result)


def _reorder_workspace_to_back(context: bpy.types.Context, workspace: bpy.types.WorkSpace) -> None:
    if context.window is None:
        _record_workspace_result("reorder_to_back", "SKIPPED", "No window context")
        return
    if context.window.workspace is None or context.window.workspace.name != workspace.name:
        _request_workspace_activation(context, workspace)
    if context.window.workspace is None or context.window.workspace.name != workspace.name:
        _record_workspace_result(
            "reorder_to_back",
            "SKIPPED",
            f"active={context.window.workspace.name if context.window.workspace else '<none>'}; requested={workspace.name}",
        )
        return
    try:
        result = bpy.ops.workspace.reorder_to_back()
    except Exception as exc:
        _record_workspace_result("reorder_to_back", "ERROR", str(exc))
        return
    _record_workspace_result("reorder_to_back", result)


def _order_codex_suite_after_builtin(context: bpy.types.Context) -> None:
    """Best-effort live UI ordering for the opt-in AI workspace block.

    Blender exposes workspace tab ordering only through UI operators. Those
    operators are no-ops from background smoke tests because scripts cannot make
    a different workspace active there, but they do work when the user invokes
    the setup operator from an interactive Blender window. Diagnostics report
    when the order still needs a live repair pass.
    """
    if bpy is None or context.window is None:
        return
    if any(bpy.data.workspaces.get(name) is None for name in CODEX_WORKSPACE_NAMES):
        return
    previous = context.window.workspace
    for name in CODEX_WORKSPACE_NAMES:
        workspace = bpy.data.workspaces.get(name)
        if workspace is not None:
            _reorder_workspace_to_back(context, workspace)
    if previous is not None and bpy.data.workspaces.get(previous.name) is not None:
        try:
            context.window.workspace = previous
        except Exception:
            pass


def _split_area(context: bpy.types.Context, area: bpy.types.Area, direction: str, factor: float) -> None:
    region = next((region for region in area.regions if region.type == "WINDOW"), None)
    if region is None:
        raise WorkspaceActivationError(f"Area {area.type} has no WINDOW region for splitting.")
    try:
        with context.temp_override(area=area, region=region):
            result = bpy.ops.screen.area_split(direction=direction, factor=factor)
    except Exception as exc:
        raise WorkspaceActivationError(f"Could not split area {area.type}: {exc}") from exc
    if not operator_finished(result):
        raise WorkspaceActivationError(f"Could not split area {area.type}; Blender returned {result}.")


def _set_area_type(area: bpy.types.Area, area_type: str) -> None:
    try:
        area.type = area_type
    except Exception as exc:
        raise WorkspaceActivationError(f"Could not set area to {area_type}: {exc}") from exc


def _assign_text(area: bpy.types.Area, text_name: str) -> None:
    if area.type != "TEXT_EDITOR":
        return
    text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
    for space in area.spaces:
        if space.type == "TEXT_EDITOR":
            space.text = text
            space.show_word_wrap = True
            return


def _configure_dashboard_areas(context: bpy.types.Context, workspace_name: str, sorted_areas: list[bpy.types.Area]) -> None:
    assigned = _ensure_area_roles(context, workspace_name, sorted_areas, ("VIEW_3D", "OUTLINER", "INFO"))
    _show_sidebar(assigned.get("VIEW_3D"))


def _configure_workflow_areas(context: bpy.types.Context, workspace_name: str, sorted_areas: list[bpy.types.Area]) -> None:
    assigned = _ensure_area_roles(context, workspace_name, sorted_areas, ("NODE_EDITOR", "VIEW_3D", "SPREADSHEET"))
    node_area = assigned["NODE_EDITOR"]
    _assign_workflow_tree(node_area)
    _show_sidebar(node_area)


def _configure_assets_areas(context: bpy.types.Context, workspace_name: str, sorted_areas: list[bpy.types.Area]) -> None:
    assigned = _ensure_area_roles(context, workspace_name, sorted_areas, ("FILE_BROWSER", "VIEW_3D", "PROPERTIES"))
    _configure_asset_browser_area(assigned.get("FILE_BROWSER"))


def _areas_with_space(areas: list[bpy.types.Area], area_type: str) -> list[bpy.types.Area]:
    return [area for area in areas if area.type == area_type and any(space.type == area_type for space in area.spaces)]


def _ensure_area_roles(
    context: bpy.types.Context,
    workspace_name: str,
    areas: list[bpy.types.Area],
    area_types: tuple[str, ...],
) -> dict[str, bpy.types.Area]:
    assigned: dict[str, bpy.types.Area] = {}
    used: set[int] = set()
    for area_type in area_types:
        existing = next(
            (area for area in areas if id(area) not in used and area.type == area_type and any(space.type == area_type for space in area.spaces)),
            None,
        )
        if existing is None:
            if context.window is None or context.window.workspace is None or context.window.workspace.name != workspace_name:
                target_workspace = bpy.data.workspaces.get(workspace_name)
                if target_workspace is None or not target_workspace.get("codex_blender_agent", False):
                    raise WorkspaceActivationError(f"{workspace_name} is missing {area_type} and is not active for safe repair.")
                if not _activate_workspace(context, target_workspace):
                    detail = LAST_WORKSPACE_RESULT.get("detail", "") if LAST_WORKSPACE_RESULT else ""
                    raise WorkspaceActivationError(
                        f"{workspace_name} is missing {area_type} and could not be activated for safe repair. {detail}".strip()
                    )
            candidates = [area for area in areas if id(area) not in used]
            if not candidates:
                raise WorkspaceActivationError(f"{workspace_name} has no available area for {area_type}.")
            existing = max(candidates, key=lambda area: area.width * area.height)
            _set_area_type(existing, area_type)
            if not any(space.type == area_type for space in existing.spaces):
                raise WorkspaceActivationError(f"Could not configure {workspace_name} area as {area_type}.")
        assigned[area_type] = existing
        used.add(id(existing))
    return assigned


def _required_area(context: bpy.types.Context, workspace_name: str, areas: list[bpy.types.Area], area_type: str) -> bpy.types.Area:
    matching = _areas_with_space(areas, area_type)
    if matching:
        return matching[0]
    if context.window is not None and context.window.workspace is not None and context.window.workspace.name == workspace_name:
        candidate = max(areas, key=lambda area: area.width * area.height)
        _set_area_type(candidate, area_type)
        if any(space.type == area_type for space in candidate.spaces):
            return candidate
    raise WorkspaceActivationError(
        f"{workspace_name} template is missing a real {area_type} editor space. "
        "Reinstall the bundled workspace template or run Repair AI Workspace in an active Blender window."
    )


def _show_sidebar(area: bpy.types.Area | None) -> None:
    if area is None:
        return
    for space in area.spaces:
        try:
            space.show_region_ui = True
        except Exception:
            continue


def _configure_asset_browser_area(area: bpy.types.Area | None) -> None:
    if area is None or area.type != "FILE_BROWSER":
        return
    for space in area.spaces:
        if space.type != "FILE_BROWSER":
            continue
        for attr, value in (("browse_mode", "ASSETS"), ("display_type", "THUMBNAIL")):
            try:
                setattr(space, attr, value)
            except Exception:
                pass


def _assign_workflow_tree(area: bpy.types.Area) -> None:
    if area.type != "NODE_EDITOR":
        return
    from .workflow_nodes import NODETREE_IDNAME, NODETREE_LABEL, create_workflow_graph

    tree = create_workflow_graph(NODETREE_LABEL, with_default_nodes=True)
    for space in area.spaces:
        if space.type == "NODE_EDITOR":
            space.tree_type = NODETREE_IDNAME
            space.node_tree = tree
            return


def _workspace_kind(workspace_name: str) -> str:
    value = canonical_workspace_name(workspace_name)
    return CODEX_WORKSPACE_KINDS.get(value, CODEX_WORKSPACE_KINDS.get(workspace_name, "studio"))


def _tag_workspace(workspace: bpy.types.WorkSpace, workspace_name: str) -> None:
    workspace["codex_blender_agent"] = True
    workspace["codex_workspace_kind"] = _workspace_kind(workspace_name)
    workspace["codex_workspace_version"] = 9
    workspace["codex_dashboard_version"] = 9


def _workspace_pin_scene(workspace: bpy.types.WorkSpace) -> bool | None:
    for attr in ("use_pin_scene", "pin_scene"):
        if hasattr(workspace, attr):
            try:
                return bool(getattr(workspace, attr))
            except Exception:
                return None
    return None


def _unpin_scene(workspace: bpy.types.WorkSpace) -> None:
    for attr in ("use_pin_scene", "pin_scene"):
        if hasattr(workspace, attr):
            try:
                setattr(workspace, attr, False)
            except Exception:
                pass


def _record_workspace_result(operator: str, result: Any, detail: str = "") -> None:
    LAST_WORKSPACE_RESULT.clear()
    LAST_WORKSPACE_RESULT.update(
        {
            "operator": operator,
            "result": sorted(result) if isinstance(result, set) else str(result),
            "detail": detail,
            "finished": operator_finished(result),
        }
    )


def _find_codex_workspace(workspace_name: str):
    workspace_name = canonical_workspace_name(workspace_name)
    exact = bpy.data.workspaces.get(workspace_name)
    if exact is not None:
        return exact
    kind = _workspace_kind(workspace_name)
    for workspace in bpy.data.workspaces:
        workspace_kind = workspace.get("codex_workspace_kind", "")
        if workspace_kind == "dashboard":
            workspace_kind = "studio"
        if workspace.get("codex_blender_agent", False) and workspace_kind == kind:
            return workspace
    for legacy, canonical in LEGACY_WORKSPACE_NAMES.items():
        if canonical == workspace_name:
            legacy_workspace = bpy.data.workspaces.get(legacy)
            if legacy_workspace is not None:
                return legacy_workspace
    for workspace in bpy.data.workspaces:
        if workspace.name == workspace_name or workspace.name.startswith(f"{workspace_name}."):
            return workspace
    return None


def _rename_workspace_exact(workspace: bpy.types.WorkSpace, workspace_name: str) -> None:
    if workspace.name == workspace_name:
        return
    existing = bpy.data.workspaces.get(workspace_name)
    if existing is not None and existing != workspace:
        raise WorkspaceActivationError(f"Cannot rename {workspace.name} to {workspace_name}; target name already exists.")
    workspace.name = workspace_name


def _area_payload(screen) -> list[dict[str, Any]]:
    if screen is None:
        return []
    areas = []
    for area in screen.areas:
        areas.append(
            {
                "type": area.type,
                "width": area.width,
                "height": area.height,
                "regions": [region.type for region in area.regions],
                "spaces": [space.type for space in area.spaces],
                "asset_browser": _area_has_asset_browser_mode(area),
            }
        )
    return areas


def _area_has_asset_browser_mode(area: bpy.types.Area) -> bool:
    if area.type != "FILE_BROWSER":
        return False
    for space in area.spaces:
        if space.type == "FILE_BROWSER" and str(getattr(space, "browse_mode", "")).upper() == "ASSETS":
            return True
    return False


def _codex_workspace_diagnostics(context: bpy.types.Context) -> list[dict[str, Any]]:
    names = [workspace.name for workspace in bpy.data.workspaces]
    diagnostics = []
    for workspace_name in CODEX_WORKSPACE_NAMES:
        workspace = bpy.data.workspaces.get(workspace_name)
        diagnostics.append(
            {
                "name": workspace_name,
                "exists": workspace_name in names,
                "index": names.index(workspace_name) if workspace_name in names else -1,
                "tagged": bool(workspace and workspace.get("codex_blender_agent", False)),
                "kind": workspace.get("codex_workspace_kind", "") if workspace else "",
                "pin_scene": _workspace_pin_scene(workspace) if workspace else None,
                "area_signature": list(workspace_area_signature(context, workspace_name) or []),
            }
        )
    return diagnostics


def _expected_area_types(workspace_name: str) -> tuple[str, ...]:
    kind = _workspace_kind(workspace_name)
    if kind == "workflow":
        return ("NODE_EDITOR", "VIEW_3D", "SPREADSHEET")
    if kind == "assets":
        return ("PROPERTIES", "VIEW_3D", "FILE_BROWSER")
    return ("VIEW_3D", "OUTLINER", "INFO")


def _preferred_area_types(workspace_name: str) -> tuple[str, ...]:
    kind = _workspace_kind(workspace_name)
    if kind in {"workflow", "assets"}:
        return (*_expected_area_types(workspace_name), "INFO")
    return _expected_area_types(workspace_name)


def _has_expected_area_types(area_types: list[str], expected: tuple[str, ...]) -> bool:
    return all(area_type in area_types for area_type in expected)


def _has_expected_spaces(areas: list[dict[str, Any]], expected: tuple[str, ...]) -> bool:
    for area_type in expected:
        if not any(item.get("type") == area_type and area_type in item.get("spaces", []) for item in areas):
            return False
    return True


def _legacy_alias_diagnostics() -> list[dict[str, Any]]:
    if bpy is None:
        return []
    names = {workspace.name for workspace in bpy.data.workspaces}
    return [
        {"legacy": legacy, "canonical": canonical, "exists": legacy in names, "canonical_exists": canonical in names}
        for legacy, canonical in LEGACY_WORKSPACE_NAMES.items()
    ]


def _workspace_order_state(workspace_names: list[str] | None = None) -> dict[str, Any]:
    if bpy is None and workspace_names is None:
        workspace_names = []
    names = workspace_names or [workspace.name for workspace in bpy.data.workspaces]
    indexes = {name: names.index(name) for name in CODEX_WORKSPACE_NAMES if name in names}
    block = [name for name in names if name in CODEX_WORKSPACE_NAMES]
    all_present = len(indexes) == len(CODEX_WORKSPACE_NAMES)
    expected_order = block == list(CODEX_WORKSPACE_NAMES)
    contiguous = False
    after_non_ai = False
    if all_present:
        block_indexes = [indexes[name] for name in CODEX_WORKSPACE_NAMES]
        contiguous = max(block_indexes) - min(block_indexes) + 1 == len(CODEX_WORKSPACE_NAMES)
        non_ai_indexes = [index for index, name in enumerate(names) if name not in CODEX_WORKSPACE_NAMES]
        after_non_ai = not non_ai_indexes or min(block_indexes) > max(non_ai_indexes)
    return {
        "ok": bool(all_present and expected_order and contiguous and after_non_ai),
        "expected_block": list(CODEX_WORKSPACE_NAMES),
        "actual_block": block,
        "indexes": indexes,
        "all_present": all_present,
        "expected_order": expected_order,
        "contiguous": contiguous,
        "after_non_ai_workspaces": after_non_ai,
    }


def _workspace_repair_recommendations(
    missing: list[str],
    bad_areas: list[str],
    pin_scene_bad: list[str],
    order_state: dict[str, Any] | None = None,
) -> list[str]:
    recommendations = []
    for name in missing:
        recommendations.append(f"Create {name} from the AI workspace suite.")
    for name in bad_areas:
        recommendations.append(f"Open {name}, then run Repair AI Workspace so Blender can safely split/configure its editors.")
    for name in pin_scene_bad:
        recommendations.append(f"Disable Pin Scene on {name} so the AI workspace follows the current scene.")
    if order_state and not order_state.get("ok") and order_state.get("all_present"):
        recommendations.append(
            "Run Create AI Workspaces from an interactive Blender window to move AI Studio, Workflow, and Assets into a contiguous block after the built-in tabs."
        )
    if not recommendations:
        recommendations.append("Workspace suite looks structurally healthy.")
    return recommendations


def _missing_node_menu_entries() -> list[str]:
    if bpy is None:
        return []
    try:
        from . import workflow_nodes
        from .workflow_nodes import workflow_node_menu_entries
    except Exception:
        return ["NODE_MT_codex_ai_workflow_add"]
    missing = []
    if not hasattr(bpy.types, "NODE_MT_codex_ai_workflow_add"):
        missing.append("NODE_MT_codex_ai_workflow_add")
    for entry in workflow_node_menu_entries():
        cls = getattr(workflow_nodes, entry["idname"], None)
        is_registered = False
        if cls is not None:
            try:
                is_registered = bool(cls.is_registered_node_type())
            except Exception:
                is_registered = True
        if not is_registered:
            missing.append(entry["idname"])
    return missing
