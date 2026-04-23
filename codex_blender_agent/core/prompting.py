from __future__ import annotations


def compose_turn_text(user_prompt: str, scene_digest: str, chat_mode: str = "scene_agent") -> str:
    prompt = (user_prompt or "").strip()
    digest = (scene_digest or "").strip()
    if not prompt:
        raise ValueError("Prompt is empty.")

    mode_guidance = {
        "scene_agent": "Mode: Game Creator. Inspect and edit the Blender scene when useful for game assets, materials, levels, workflows, and exports.",
        "chat_only": "Mode: Chat Only. Answer as a normal assistant; do not inspect or edit Blender unless the user explicitly asks.",
        "toolbox": "Mode: Toolbox. Focus on reusable systems, recipes, and stored workflows.",
        "assets": "Mode: Assets. Focus on asset storage, asset import/export, and reusable library items.",
    }
    parts = [mode_guidance.get(chat_mode, mode_guidance["scene_agent"]), f"User request:\n{prompt}"]
    if digest:
        parts.append(f"Blender scene summary at request time:\n{digest}")
    parts.append("Use the fewest targeted Blender tools needed. Prefer structured tools first; use the operator bridge only when the needed Blender surface is not covered by a structured tool. For local reversible game-creation work, act directly when allowed and summarize what changed.")
    return "\n\n".join(parts)
