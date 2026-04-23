from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any


@dataclass(frozen=True)
class QuickPrompt:
    id: str
    label: str
    category: str
    prompt_template: str
    scope_hint: str
    execution_mode: str
    risk_lane: str
    icon: str
    color_token: str


CATEGORY_ORDER = ("start", "create_asset", "materials", "level_art", "workflow", "fix", "export", "tutor")

CATEGORY_LABELS = {
    "start": "Start",
    "create_asset": "Create asset",
    "materials": "Materials",
    "level_art": "Level art",
    "workflow": "Workflow",
    "fix": "Fix",
    "export": "Export",
    "tutor": "Tutor",
}


QUICK_PROMPTS: tuple[QuickPrompt, ...] = (
    QuickPrompt(
        "what_can_i_make",
        "What can I make?",
        "start",
        "Look at the current Blender context and suggest 3 useful game-creation actions I can do next. Keep it practical and explain what you see first.",
        "scene",
        "chat",
        "informational",
        "QUESTION",
        "learn",
    ),
    QuickPrompt(
        "explain_context",
        "Explain what AI sees",
        "start",
        "Explain what you can see in this Blender file right now, what is selected, what is excluded, and what I can ask you to do next.",
        "scene",
        "chat",
        "informational",
        "VIEWZOOM",
        "learn",
    ),
    QuickPrompt(
        "improve_with_screenshots",
        "Improve with screenshots",
        "start",
        "Create or improve this scene for the requested game-art goal, then review it from multiple viewpoints and keep improving until it is good.",
        "scene",
        "visual_review",
        "additive",
        "CAMERA_DATA",
        "create",
    ),
    QuickPrompt(
        "setup_asset_workflow",
        "Set up asset workflow",
        "start",
        "Set up a simple AI workflow for creating and checking game-ready assets in this scene. Make the graph easy to understand and explain each step.",
        "scene",
        "workflow",
        "additive",
        "NODETREE",
        "workflow",
    ),
    QuickPrompt(
        "game_ready_prop",
        "Game-ready prop",
        "create_asset",
        "Turn the selected object into a game-ready prop. Check scale, origin, transforms, naming, material slots, and reusable asset readiness. Make safe reversible changes where possible and summarize what changed.",
        "selection",
        "asset",
        "additive",
        "ASSET_MANAGER",
        "asset",
    ),
    QuickPrompt(
        "modular_kit",
        "Modular kit",
        "create_asset",
        "Create a modular game-art kit plan from the selected object or scene. Suggest reusable pieces, naming, pivots, snapping rules, and the first concrete Blender steps.",
        "selection",
        "chat",
        "additive",
        "LIGHT",
        "create",
    ),
    QuickPrompt(
        "make_variants",
        "Make variants",
        "create_asset",
        "Create 5 game-ready visual variants from the selected asset. Prefer additive or duplicated changes, keep the original intact, and summarize each variant.",
        "selection",
        "asset",
        "additive",
        "FILE_REFRESH",
        "create",
    ),
    QuickPrompt(
        "stylized_material",
        "Stylized material",
        "materials",
        "Create a stylized game material for the selected object. Use the current style hint if available: ${style_hint}. Keep it realtime-friendly.",
        "selection",
        "asset",
        "additive",
        "LIGHT",
        "material",
    ),
    QuickPrompt(
        "material_variants",
        "Material variants",
        "materials",
        "Make several color and surface variants for the selected object's material. Keep changes organized and easy to revert.",
        "selection",
        "asset",
        "additive",
        "FILE_REFRESH",
        "material",
    ),
    QuickPrompt(
        "optimize_materials",
        "Optimize materials",
        "materials",
        "Inspect the selected objects' materials for realtime game use. Identify expensive or messy setup and suggest safe cleanup steps.",
        "selection",
        "chat",
        "informational",
        "CHECKMARK",
        "optimize",
    ),
    QuickPrompt(
        "blockout_environment",
        "Block out level",
        "level_art",
        "Help block out a small game environment using the current selection and scene. Start with a concrete plan, then make reversible additive geometry if appropriate.",
        "scene",
        "chat",
        "additive",
        "WORKSPACE",
        "level",
    ),
    QuickPrompt(
        "dress_scene",
        "Dress scene",
        "level_art",
        "Dress this scene with reusable props and composition suggestions. Use existing assets when possible and ask only if the target style is unclear.",
        "scene",
        "chat",
        "broad",
        "ASSET_MANAGER",
        "level",
    ),
    QuickPrompt(
        "dungeon_room_kit",
        "Dungeon room kit",
        "level_art",
        "Create a practical plan for a modular dungeon room kit from this scene. Include wall, floor, trim, prop, material, and export-readiness steps.",
        "scene",
        "workflow",
        "additive",
        "NODETREE",
        "level",
    ),
    QuickPrompt(
        "workflow_low_poly_props",
        "Low-poly prop workflow",
        "workflow",
        "Build an AI workflow that creates low-poly environment prop variants from the selected object. Keep graph nodes unconnected until the plan is clear.",
        "selection",
        "workflow",
        "additive",
        "NODETREE",
        "workflow",
    ),
    QuickPrompt(
        "explain_workflow",
        "Explain workflow",
        "workflow",
        "Explain the current AI Workflow graph in plain language. Tell me what it does, where it may change the scene, and how to simplify it.",
        "workflow",
        "chat",
        "informational",
        "QUESTION",
        "workflow",
    ),
    QuickPrompt(
        "simplify_workflow",
        "Simplify workflow",
        "workflow",
        "Simplify the current AI Workflow graph for one-click game-asset creation. Propose changes first and keep risky nodes out of the default path.",
        "workflow",
        "workflow",
        "additive",
        "NODETREE",
        "workflow",
    ),
    QuickPrompt(
        "clean_game_export",
        "Clean for export",
        "fix",
        "Clean the selected assets for game export. Check names, origins, transforms, scale, material slots, hidden objects, and obvious engine import issues.",
        "selection",
        "asset",
        "additive",
        "CHECKMARK",
        "fix",
    ),
    QuickPrompt(
        "find_asset_problems",
        "Find problems",
        "fix",
        "Find obvious game-asset problems in the selected objects. Do not change anything yet; give a prioritized checklist and one-click next steps.",
        "selection",
        "chat",
        "informational",
        "VIEWZOOM",
        "fix",
    ),
    QuickPrompt(
        "fix_material_slots",
        "Fix material slots",
        "fix",
        "Inspect and fix missing or confusing material slots on the selected objects. Keep changes local and explain what changed.",
        "selection",
        "asset",
        "additive",
        "CHECKMARK",
        "fix",
    ),
    QuickPrompt(
        "export_unity_gltf",
        "Unity glTF prep",
        "export",
        "Prepare the selected assets for Unity glTF export. Check scale, transforms, material compatibility, texture paths, and write an export checklist.",
        "selection",
        "chat",
        "external",
        "ASSET_MANAGER",
        "export",
    ),
    QuickPrompt(
        "export_unreal_fbx",
        "Unreal FBX prep",
        "export",
        "Prepare the selected assets for Unreal FBX export. Check scale, pivots, naming, collision hints, materials, and write an export checklist.",
        "selection",
        "chat",
        "external",
        "ASSET_MANAGER",
        "export",
    ),
    QuickPrompt(
        "export_checklist",
        "Export checklist",
        "export",
        "Create a concise game-engine export checklist for the current selection and target engine: ${target_engine}.",
        "selection",
        "chat",
        "informational",
        "TEXT",
        "export",
    ),
    QuickPrompt(
        "teach_first_asset",
        "Teach first asset",
        "tutor",
        "Teach me how to create my first reusable AI game asset in this add-on. Use the current scene and give one step at a time.",
        "scene",
        "chat",
        "informational",
        "INFO",
        "learn",
    ),
    QuickPrompt(
        "walk_game_prop",
        "Walk me through prop",
        "tutor",
        "Walk me through making a game prop from the selected object. Explain why each step matters for game creation.",
        "selection",
        "chat",
        "informational",
        "INFO",
        "learn",
    ),
    QuickPrompt(
        "explain_addon",
        "Explain the add-on",
        "tutor",
        "Explain this add-on like I am trying to make game assets fast. Tell me the shortest path to chat, create, workflow, assets, and export.",
        "scene",
        "chat",
        "informational",
        "QUESTION",
        "learn",
    ),
)

_PROMPTS_BY_ID = {prompt.id: prompt for prompt in QUICK_PROMPTS}


def quick_prompt_categories() -> tuple[str, ...]:
    return CATEGORY_ORDER


def quick_prompt_category_items() -> list[tuple[str, str, str]]:
    return [(category, CATEGORY_LABELS[category], "") for category in CATEGORY_ORDER]


def list_quick_prompts(category: str = "") -> list[QuickPrompt]:
    if category and category != "all":
        return [prompt for prompt in QUICK_PROMPTS if prompt.category == category]
    return list(QUICK_PROMPTS)


def get_quick_prompt(prompt_id: str) -> QuickPrompt:
    try:
        return _PROMPTS_BY_ID[prompt_id]
    except KeyError as exc:
        raise KeyError(f"Unknown quick prompt: {prompt_id}") from exc


def quick_prompt_payload(prompt: QuickPrompt) -> dict[str, str]:
    return {
        "id": prompt.id,
        "label": prompt.label,
        "category": prompt.category,
        "category_label": CATEGORY_LABELS.get(prompt.category, prompt.category.title()),
        "prompt_template": prompt.prompt_template,
        "scope_hint": prompt.scope_hint,
        "execution_mode": prompt.execution_mode,
        "risk_lane": prompt.risk_lane,
        "icon": prompt.icon,
        "color_token": prompt.color_token,
    }


def render_quick_prompt(prompt_id: str, context_payload: dict[str, Any] | None = None) -> str:
    prompt = get_quick_prompt(prompt_id)
    payload = dict(context_payload or {})
    safe_payload = {key: str(value) for key, value in payload.items()}
    return Template(prompt.prompt_template).safe_substitute(safe_payload)
