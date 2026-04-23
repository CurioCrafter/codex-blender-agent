from __future__ import annotations

from types import SimpleNamespace

from codex_blender_agent.core.service import CodexService


def test_service_start_skips_account_model_refresh_when_already_running_fast_path() -> None:
    service = CodexService(dynamic_tools=[], tool_handler=lambda _name, _args: {})
    service._client = SimpleNamespace(is_running=True)  # type: ignore[attr-defined]
    calls: list[str] = []

    service.refresh_account = lambda: calls.append("account")  # type: ignore[method-assign]
    service.refresh_models = lambda: calls.append("models")  # type: ignore[method-assign]

    service.start("codex", "", "C:/workspace", refresh_state=False)
    assert calls == []

    service.start("codex", "", "C:/workspace", refresh_state=True)
    assert calls == ["account", "models"]
