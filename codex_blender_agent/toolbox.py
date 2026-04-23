from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .ai_assets_store import AIAssetsError, AIAssetsStore, normalize_tags


TOOLBOX_CATEGORIES = ["mesh", "material", "rig", "animation", "workflow", "script", "note", "system"]
RUNNABLE_SCENE_TOOLS = {
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
    "export_fbx",
    "call_blender_operator",
    "undo",
    "save_checkpoint_copy",
}


class ToolboxError(RuntimeError):
    pass


class ToolboxStore:
    """Compatibility facade over the v0.8 SQLite AI Assets toolbox table."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "toolbox.json"
        self.authority = AIAssetsStore(self.root / "ai_assets", legacy_root=self.root)
        self.authority.initialize()
        self.authority.migrate_legacy()

    def list_entries(self, category: str | None = None) -> list[dict[str, Any]]:
        entries = self.authority.list_toolbox_entries(category)
        return [_legacy_toolbox_item(entry) for entry in entries]

    def save_entry(
        self,
        name: str,
        category: str,
        description: str,
        content: Any,
        tags: list[str] | str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ToolboxError("Toolbox item name is required.")
        category = (category or "system").strip().lower()
        if category not in TOOLBOX_CATEGORIES and category not in {"generate", "modify", "materials", "animate", "organize", "optimize", "export", "debug"}:
            raise ToolboxError(f"Unsupported toolbox category: {category}")
        item = self.authority.upsert_toolbox_entry(
            item_id=entry_id,
            name=name,
            category=category,
            description=description,
            content=content,
            tags=normalize_tags(tags),
        )
        return _legacy_toolbox_item(item)

    def get_entry(self, item_id_or_name: str) -> dict[str, Any]:
        item = self.authority.get_toolbox_entry(item_id_or_name)
        if not item:
            raise ToolboxError(f"Toolbox item not found: {item_id_or_name}")
        return _legacy_toolbox_item(item)

    def delete_entry(self, item_id_or_name: str) -> dict[str, Any]:
        try:
            return _legacy_toolbox_item(self.authority.delete_toolbox_entry(item_id_or_name))
        except AIAssetsError as exc:
            raise ToolboxError(str(exc)) from exc

    def run_recipe(self, item_id_or_name: str, executor: Callable[[str, dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
        entry = self.get_entry(item_id_or_name)
        steps = parse_recipe_steps(entry.get("content"))
        results: list[dict[str, Any]] = []
        for index, step in enumerate(steps, start=1):
            tool_name = step.get("tool")
            arguments = step.get("arguments", {})
            if tool_name not in RUNNABLE_SCENE_TOOLS:
                raise ToolboxError(f"Step {index} uses unsupported scene tool: {tool_name}")
            if not isinstance(arguments, dict):
                raise ToolboxError(f"Step {index} arguments must be an object.")
            payload = executor(tool_name, arguments)
            results.append({"step": index, "tool": tool_name, "success": payload.get("success", False), "payload": payload})
            if not payload.get("success", False):
                break
        return results


def parse_recipe_steps(content: Any) -> list[dict[str, Any]]:
    recipe = content
    if isinstance(content, str):
        try:
            recipe = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ToolboxError("Runnable toolbox systems must contain JSON recipe content.") from exc
    steps = recipe.get("steps") if isinstance(recipe, dict) else recipe
    if not isinstance(steps, list) or not steps:
        raise ToolboxError("Runnable toolbox systems must define a non-empty steps list.")
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str):
            raise ToolboxError("Each toolbox recipe step must be an object with a tool name.")
    return steps


def summarize_entries(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No toolbox items stored yet."
    lines = []
    for entry in entries:
        tags = ", ".join(entry.get("tags", []))
        tag_suffix = f" tags=[{tags}]" if tags else ""
        lines.append(f"- {entry.get('id')}: {entry.get('name')} ({entry.get('category')}) - {entry.get('description', '')}{tag_suffix}")
    return "\n".join(lines)


def _legacy_toolbox_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("item_id") or item.get("id", ""),
        "item_id": item.get("item_id") or item.get("id", ""),
        "name": item.get("name", ""),
        "category": item.get("category", "system"),
        "description": item.get("description", ""),
        "content": item.get("content", {}),
        "tags": item.get("tags", []),
        "runnable": bool(item.get("runnable", False)),
        "required_context": item.get("required_context", []),
        "output_type": item.get("output_type", ""),
        "approval_required": bool(item.get("approval_required", True)),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }
