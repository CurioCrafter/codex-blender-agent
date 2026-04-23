from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .studio_state import classify_prompt_intent, compact_text


_CASTLE_TERMS = {
    "castle",
    "keep",
    "tower",
    "battlement",
    "battlements",
    "crenel",
    "crenels",
    "crown",
    "wall",
    "gate",
    "gatehouse",
    "moat",
    "bridge",
    "fortress",
    "fortification",
}

_FIX_TERMS = {
    "fix",
    "repair",
    "correct",
    "clean up",
    "cleanup",
    "align",
    "resolve",
    "adjust",
    "refine",
    "improve",
}

_CREATE_TERMS = {
    "make",
    "create",
    "build",
    "generate",
    "model",
    "construct",
    "block out",
    "blockout",
}


def expand_prompt(original_prompt: str, scene_context: Any | None = None) -> str:
    prompt = _normalize_prompt(original_prompt)
    if not prompt:
        prompt = "Create a game-ready Blender asset."

    intent = classify_prompt_intent(prompt)
    subject = _infer_subject(prompt)
    context_lines = _scene_context_lines(scene_context)
    castle_mode = _mentions_any(prompt, _CASTLE_TERMS) or _mentions_any(" ".join(context_lines), _CASTLE_TERMS)
    fix_mode = _mentions_any(prompt, _FIX_TERMS) or intent == "recover"

    sections: list[str] = []
    sections.append(f"User request: {prompt}")
    sections.append("")
    sections.append("Expanded brief:")
    sections.append(
        _expand_goal_line(
            intent=intent,
            subject=subject,
            castle_mode=castle_mode,
            fix_mode=fix_mode,
            prompt=prompt,
        )
    )
    sections.extend(_expand_core_guidance(intent=intent, castle_mode=castle_mode, fix_mode=fix_mode))
    if context_lines:
        sections.append("")
        sections.append("Scene context hints:")
        sections.extend(f"- {line}" for line in context_lines)
    sections.extend(_expand_qa_guidance(castle_mode=castle_mode, fix_mode=fix_mode))
    sections.extend(_expand_safety_guidance())
    sections.append("")
    sections.append("Output expectations:")
    sections.append("- Make the result clear for a game-asset workflow.")
    sections.append("- Summarize any scene edits, validation findings, and unresolved blockers.")
    return "\n".join(sections).rstrip() + "\n"


def _normalize_prompt(value: str) -> str:
    return " ".join((value or "").split())


def _infer_subject(prompt: str) -> str:
    lower = prompt.lower()
    for term in sorted(_CASTLE_TERMS, key=len, reverse=True):
        if term in lower:
            return "castle"
    for term in sorted(_FIX_TERMS, key=len, reverse=True):
        if term in lower:
            return "the asset"
    for term in sorted(_CREATE_TERMS, key=len, reverse=True):
        if term in lower:
            remainder = _trim_leading_phrase(prompt, term)
            return remainder or "the asset"
    return prompt.split(" ", 1)[1].strip() if prompt.count(" ") >= 1 and len(prompt) <= 40 else "the asset"


def _trim_leading_phrase(prompt: str, phrase: str) -> str:
    lower = prompt.lower()
    idx = lower.find(phrase)
    if idx == -1:
        return ""
    tail = prompt[idx + len(phrase):].strip(" ,.:;-")
    if tail.lower().startswith(("a ", "an ", "the ")):
        tail = tail.split(" ", 1)[1] if " " in tail else tail
    return tail.strip() or ""


def _scene_context_lines(scene_context: Any | None) -> list[str]:
    if scene_context is None:
        return []
    if isinstance(scene_context, str):
        text = compact_text(_normalize_prompt(scene_context), 220)
        return [text] if text else []
    if isinstance(scene_context, dict):
        lines: list[str] = []
        scene_name = _first_text(scene_context, ("scene_name", "scene", "name"))
        if scene_name:
            lines.append(f"Scene: {scene_name}")
        active_object = _first_text(scene_context, ("active_object", "active_object_name", "active"))
        if active_object:
            lines.append(f"Active object: {active_object}")
        selected = _string_list(scene_context.get("selected_objects") or scene_context.get("selection") or scene_context.get("objects"))
        if selected:
            lines.append("Selected objects: " + ", ".join(selected[:8]))
        visible_count = _first_text(scene_context, ("visible_object_count", "object_count", "selected_count"))
        if visible_count:
            lines.append(f"Counts: {visible_count}")
        materials = _string_list(scene_context.get("materials") or scene_context.get("material_names"))
        if materials:
            lines.append("Materials: " + ", ".join(materials[:6]))
        validation = _first_text(scene_context, ("validation_summary", "top_issue", "top_issues"))
        if validation:
            lines.append(f"Validation note: {compact_text(str(validation), 180)}")
        style_hint = _first_text(scene_context, ("style_hint", "style"))
        if style_hint:
            lines.append(f"Style hint: {style_hint}")
        return [line for line in lines if line]
    if isinstance(scene_context, Iterable):
        return [compact_text(str(item), 160) for item in scene_context if str(item).strip()]
    return [compact_text(str(scene_context), 160)]


def _first_text(mapping: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = mapping.get(key, "")
        if isinstance(value, (list, tuple)):
            if value:
                return compact_text(str(value[0]), 160)
        text = compact_text(str(value), 160)
        if text:
            return text
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            text = compact_text(str(item), 96)
            if text:
                result.append(text)
        return result
    return []


def _mentions_any(text: str, terms: set[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def _expand_goal_line(*, intent: str, subject: str, castle_mode: bool, fix_mode: bool, prompt: str) -> str:
    if fix_mode:
        return f"Diagnose the evaluated scene first, then repair the smallest safe set of changes on {subject or 'the asset'}."
    if castle_mode:
        return f"Create or refine a game-ready castle asset with a coherent fortification silhouette, clean supports, and readable defensive shapes."
    if intent == "automate":
        return f"Turn the request into a repeatable Blender workflow for {subject or 'the asset'}."
    if intent == "inspect":
        return f"Inspect {subject or 'the asset'} and report concrete geometry, scale, and organization issues before making changes."
    return f"Create {subject or 'the asset'} as a game-ready Blender asset with clear shape, sensible scale, and reusable topology."


def _expand_core_guidance(*, intent: str, castle_mode: bool, fix_mode: bool) -> list[str]:
    lines = [
        "- Keep the original user goal intact and avoid scope creep.",
        "- Prefer reversible, local, and additive edits before destructive operations.",
        "- Preserve the main silhouette, ownership of parts, and any useful materials or naming.",
        "- Use evaluated Blender geometry as the source of truth.",
    ]
    if fix_mode:
        lines.append("- Repair the smallest set of problems that actually blocks the asset from being game-ready.")
        lines.append("- Avoid broad remesh or boolean-style cleanup unless it is clearly the safest option.")
    else:
        lines.append("- Build the asset so it can be reused, exported, and reviewed without extra manual cleanup.")
    if intent == "automate":
        lines.append("- Organize the request into clear repeatable steps that could be reused on similar assets.")
    if castle_mode:
        lines.append("- Keep the castle structure coherent: walls, towers, keep, gate, and crown elements should read as one fortification.")
    return lines


def _expand_qa_guidance(*, castle_mode: bool, fix_mode: bool) -> list[str]:
    lines = [
        "",
        "Geometry and QA expectations:",
        "- Validate scale, origin, transforms, and material assignments.",
        "- Check for floating parts, intersections, gaps, duplicated surfaces, and weak silhouettes.",
        "- Capture multiple screenshots after the edit and verify the result from more than one angle.",
        "- If a defect appears, fix the underlying geometry first and only then polish framing or presentation.",
    ]
    if fix_mode:
        lines.append("- Report which defects were found, what was changed, and which issues still remain.")
    if castle_mode:
        lines.extend(
            [
                "- Castle-specific checks: towers should sit cleanly on the walls, battlements should not interpenetrate support walls, and the crown/roof line should not clip into the keep.",
                "- Castle-specific checks: merge obvious blockout pieces when they are meant to read as a single wall mass, and keep moat, bridge, gate, and water/terrain clearances sensible.",
                "- Castle-specific checks: keep trees and props out of moat or water zones unless they are intentionally placed there.",
            ]
        )
    return lines


def _expand_safety_guidance() -> list[str]:
    return [
        "",
        "Safety and preservation rules:",
        "- Do not delete unrelated scene content.",
        "- Do not rewrite the whole scene when a focused fix is enough.",
        "- Keep changes non-destructive where possible and call out any higher-risk step explicitly.",
        "- After any scene change, run automatic validation and screenshot review before treating the result as complete.",
    ]
