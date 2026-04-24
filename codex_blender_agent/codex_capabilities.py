from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


IMAGE_PURPOSES = {
    "concept": "Concept art or visual direction",
    "texture": "Texture or material reference",
    "reference": "Reference image for Blender modeling",
    "ui": "Game UI, icon, or HUD artwork",
    "skybox": "Skybox, matte painting, or environment reference",
}


def list_codex_capabilities() -> list[dict[str, Any]]:
    """Return Codex-side capability bridges visible to the Blender assistant."""

    return [
        {
            "id": "image_generation",
            "label": "Generate images",
            "status": "handoff_ready",
            "tool_names": ["create_image_generation_brief", "register_generated_image_asset"],
            "description": (
                "Create a pinned image-generation brief that can be handed to Codex/ChatGPT image generation, "
                "then register the generated PNG/JPEG/WebP as an AI Asset."
            ),
            "best_for": ["concept art", "texture references", "icons", "skybox studies", "modeling references"],
            "recovery": "Generated files stay external until explicitly registered as image assets.",
        },
        {
            "id": "live_observability",
            "label": "Watch AI work live",
            "status": "active",
            "tool_names": ["list_live_ai_activity", "list_ui_explanation_context", "list_available_workflows", "get_visual_review_context", "list_action_cards"],
            "description": "Stream prompt, tool, validation, screenshot, and card activity into the Studio dashboard and web console.",
            "best_for": ["debugging stuck turns", "seeing current tool calls", "reviewing visual QA passes"],
            "recovery": "Open the web console or dashboard Live Activity panel when the transcript is too noisy.",
        },
        {
            "id": "model_control",
            "label": "Choose model before prompting",
            "status": "active",
            "tool_names": ["list_model_state", "refresh_model_state"],
            "description": "Start the service, load model choices, persist the selected model, and explain why model selection is unavailable.",
            "best_for": ["first run setup", "switching GPT models", "debugging missing model lists"],
            "recovery": "Use Start / Refresh Models, then Login / Re-login if the model list stays empty.",
        },
        {
            "id": "operator_bridge",
            "label": "Use Blender operators",
            "status": "available",
            "tool_names": ["list_blender_operators", "inspect_blender_operator", "check_blender_operator_poll", "call_blender_operator"],
            "description": "Discover and safely call bpy.ops across Blender editors when structured scene tools are not enough.",
            "best_for": ["specialized Blender commands", "modifier/UI operations", "import/export add-ons"],
            "recovery": "Context-sensitive or broad operator calls require action-card approval.",
        },
        {
            "id": "visual_review",
            "label": "Self-review with screenshots",
            "status": "active",
            "tool_names": ["plan_visual_review_viewpoints", "capture_scene_viewpoints", "validate_gpt_asset"],
            "description": "Use geometry checks, viewpoint planning, screenshots, and critic prompts to improve game assets automatically.",
            "best_for": ["castle blockouts", "props", "environment kits", "scene polish"],
            "recovery": "Stop the loop, apply only safe repairs, or inspect the run manifest.",
        },
        {
            "id": "asset_memory",
            "label": "Remember generated assets",
            "status": "available",
            "tool_names": ["save_asset_file", "save_selection_to_asset_library", "search_ai_assets", "pin_asset_version"],
            "description": "Store useful generated outputs, selected-object bundles, recipes, and references in searchable AI Assets memory.",
            "best_for": ["reusing work", "publishing packages", "keeping provenance"],
            "recovery": "Draft assets can be validated, pinned, archived, or republished as packages.",
        },
    ]


def build_image_generation_brief(
    *,
    prompt: str,
    purpose: str = "concept",
    style: str = "",
    target_engine: str = "",
    asset_name: str = "",
    size: str = "",
    negative_prompt: str = "",
    reference_paths: list[str] | None = None,
    scene_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = " ".join(str(prompt or "").split())
    if not text:
        raise ValueError("Image generation prompt is required.")
    normalized_purpose = purpose if purpose in IMAGE_PURPOSES else "concept"
    references = [str(path) for path in reference_paths or [] if str(path).strip()]
    context = dict(scene_context or {})
    title = asset_name.strip() if asset_name.strip() else _title_from_prompt(text, normalized_purpose)
    style_line = style.strip() or str(context.get("game_style", "") or "").strip() or "cohesive game-art direction"
    engine_line = target_engine.strip() or str(context.get("target_engine", "") or "").strip() or "generic realtime game asset pipeline"
    size_line = size.strip() or _default_size(normalized_purpose)
    handoff_prompt = _compose_handoff_prompt(
        text,
        purpose=normalized_purpose,
        style=style_line,
        target_engine=engine_line,
        size=size_line,
        negative_prompt=negative_prompt,
        reference_paths=references,
        scene_context=context,
    )
    request_id = f"img-{_safe_slug(title)}-{uuid.uuid4().hex[:8]}"
    return {
        "request_id": request_id,
        "title": title,
        "purpose": normalized_purpose,
        "purpose_label": IMAGE_PURPOSES[normalized_purpose],
        "prompt": text,
        "style": style_line,
        "target_engine": engine_line,
        "size": size_line,
        "negative_prompt": negative_prompt.strip(),
        "reference_paths": references,
        "scene_context": context,
        "handoff_prompt": handoff_prompt,
        "summary": f"{IMAGE_PURPOSES[normalized_purpose]} brief for {title}.",
        "next_steps": [
            "Use the handoff prompt in a Codex/ChatGPT image-generation tool.",
            "Save the generated image as PNG, JPEG, or WebP.",
            "Register the generated file with register_generated_image_asset or save_asset_file.",
            "Attach or import the registered image as reference, texture, UI art, or concept memory.",
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def render_image_generation_brief(brief: dict[str, Any]) -> str:
    lines = [
        f"# {brief.get('title', 'Image Generation Brief')}",
        "",
        f"- Request: {brief.get('request_id', '')}",
        f"- Purpose: {brief.get('purpose_label', brief.get('purpose', 'concept'))}",
        f"- Size: {brief.get('size', '')}",
        f"- Target engine: {brief.get('target_engine', '')}",
        f"- Style: {brief.get('style', '')}",
        "",
        "## Handoff Prompt",
        brief.get("handoff_prompt", ""),
        "",
        "## Negative Prompt",
        brief.get("negative_prompt", "") or "None.",
        "",
        "## References",
    ]
    references = list(brief.get("reference_paths", []) or [])
    if references:
        lines.extend(f"- {path}" for path in references)
    else:
        lines.append("- None.")
    lines.extend(["", "## Next Steps"])
    lines.extend(f"- {step}" for step in list(brief.get("next_steps", []) or []))
    return "\n".join(lines).strip() + "\n"


def _compose_handoff_prompt(
    prompt: str,
    *,
    purpose: str,
    style: str,
    target_engine: str,
    size: str,
    negative_prompt: str,
    reference_paths: list[str],
    scene_context: dict[str, Any],
) -> str:
    selected = ", ".join(str(item) for item in scene_context.get("selected_objects", []) or [] if str(item).strip())
    active = str(scene_context.get("active_object", "") or "").strip()
    context_bits = []
    if active:
        context_bits.append(f"active object: {active}")
    if selected:
        context_bits.append(f"selection: {selected}")
    if scene_context.get("scope"):
        context_bits.append(f"scope: {scene_context.get('scope')}")
    context_line = "; ".join(context_bits) if context_bits else "no required Blender scene dependency"
    reference_line = "; ".join(reference_paths) if reference_paths else "no external references"
    negative = negative_prompt.strip() or "avoid text artifacts, watermarks, muddy details, unusable perspective, and inconsistent scale"
    return (
        f"Create {IMAGE_PURPOSES[purpose].lower()} for a Blender game-creation workflow. "
        f"Main request: {prompt}. "
        f"Visual style: {style}. "
        f"Target pipeline: {target_engine}. "
        f"Canvas/output: {size}. "
        f"Blender context to respect: {context_line}. "
        f"Reference paths: {reference_line}. "
        f"Negative guidance: {negative}. "
        "Favor clear silhouettes, readable forms, production-friendly materials, and details that can be modeled or textured in Blender."
    )


def _default_size(purpose: str) -> str:
    if purpose == "ui":
        return "1024x1024 transparent-background friendly"
    if purpose == "skybox":
        return "1792x1024 wide environment study"
    return "1024x1024"


def _title_from_prompt(prompt: str, purpose: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)[:7]
    core = " ".join(words) if words else "Image Brief"
    return f"{core} {purpose.title()}".strip()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "image-brief"
