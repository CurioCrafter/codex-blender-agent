from __future__ import annotations

from typing import Any

from .constants import ADDON_ID, default_codex_command, default_codex_home


class FallbackPreferences:
    def __init__(self) -> None:
        self.codex_command = default_codex_command()
        self.codex_home = default_codex_home()
        self.workspace_root = ""
        self.auto_setup_dashboard_workspace = False
        self.enable_operator_bridge = True
        self.enable_python_execution = False
        self.enable_expert_tools = False
        self.enable_experimental_asset_maintenance = False
        self.enable_append_reuse_data_policy = False
        self.ai_assets_storage_root = ""


def addon_module_candidates() -> tuple[str, ...]:
    package = __package__ or ADDON_ID
    return (
        ADDON_ID,
        package,
        f"bl_ext.user_default.{ADDON_ID}",
    )


def get_addon_preferences(context: Any, *, fallback: bool = True) -> Any:
    preferences = getattr(context, "preferences", None)
    addons = getattr(preferences, "addons", None)
    if addons is None:
        return FallbackPreferences() if fallback else None

    for key in addon_module_candidates():
        addon = addons.get(key)
        if addon is not None:
            return addon.preferences

    for key in getattr(addons, "keys", lambda: [])():
        text = str(key)
        if text == ADDON_ID or text.endswith(f".{ADDON_ID}"):
            addon = addons.get(key)
            if addon is not None:
                return addon.preferences

    return FallbackPreferences() if fallback else None
