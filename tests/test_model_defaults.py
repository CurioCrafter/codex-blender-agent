from __future__ import annotations

from types import SimpleNamespace

from codex_blender_agent.model_defaults import DEFAULT_REASONING_EFFORT, preferred_model_id, valid_reasoning_effort


def test_preferred_model_defaults_to_gpt_54_when_available():
    models = [
        SimpleNamespace(model_id="gpt-5.2", label="GPT-5.2", description="", is_default=True),
        SimpleNamespace(model_id="gpt-5.4-mini", label="GPT-5.4 Mini", description="", is_default=False),
        SimpleNamespace(model_id="gpt-5.4", label="GPT-5.4", description="", is_default=False),
    ]

    assert preferred_model_id(models) == "gpt-5.4"


def test_preferred_model_falls_back_to_service_default():
    models = [
        SimpleNamespace(model_id="gpt-5.2", label="GPT-5.2", description="", is_default=False),
        SimpleNamespace(model_id="gpt-5.3", label="GPT-5.3", description="", is_default=True),
    ]

    assert preferred_model_id(models) == "gpt-5.3"


def test_reasoning_effort_defaults_to_extra_high():
    assert DEFAULT_REASONING_EFFORT == "xhigh"
    assert valid_reasoning_effort("") == "xhigh"
    assert valid_reasoning_effort("medium") == "medium"
