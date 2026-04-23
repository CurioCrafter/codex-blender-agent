from __future__ import annotations

from typing import Any, Iterable


DEFAULT_MODEL_ID = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "xhigh"

_PENALIZED_MODEL_MARKERS = ("mini", "spark", "nano")


def _normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _model_field(model: Any, field: str) -> str:
    if isinstance(model, dict):
        return str(model.get(field, "") or "")
    return str(getattr(model, field, "") or "")


def _model_score(model: Any, preferred_model: str = DEFAULT_MODEL_ID) -> tuple[int, str]:
    preferred = _normalize(preferred_model)
    model_id = _model_field(model, "model_id") or _model_field(model, "id")
    label = _model_field(model, "label") or _model_field(model, "displayName")
    description = _model_field(model, "description")
    normalized_fields = tuple(_normalize(field) for field in (model_id, label, description))
    normalized_blob = " ".join(normalized_fields)
    is_penalized_variant = any(marker in normalized_blob for marker in _PENALIZED_MODEL_MARKERS)

    if any(field == preferred for field in normalized_fields if field):
        return (1000 if not is_penalized_variant else 700, model_id)
    if any(field.startswith(preferred) for field in normalized_fields if field):
        return (900 if not is_penalized_variant else 650, model_id)
    if preferred in normalized_blob:
        return (850 if not is_penalized_variant else 600, model_id)
    if "gpt54" in normalized_blob:
        return (800 if not is_penalized_variant else 550, model_id)
    if bool(_model_field(model, "is_default")):
        return (100, model_id)
    return (0, model_id)


def preferred_model_id(models: Iterable[Any], preferred_model: str = DEFAULT_MODEL_ID) -> str:
    """Return the best default model id, preferring GPT-5.4 when available."""

    candidates = [model for model in models if (_model_field(model, "model_id") or _model_field(model, "id"))]
    if not candidates:
        return ""
    scored = sorted((_model_score(model, preferred_model), index, model) for index, model in enumerate(candidates))
    best_score, _, best_model = scored[-1]
    if best_score[0] > 0:
        return _model_field(best_model, "model_id") or _model_field(best_model, "id")
    return _model_field(candidates[0], "model_id") or _model_field(candidates[0], "id")


def valid_reasoning_effort(effort: str) -> str:
    value = (effort or "").strip().lower()
    if value in {"low", "medium", "high", "xhigh"}:
        return value
    return DEFAULT_REASONING_EFFORT
