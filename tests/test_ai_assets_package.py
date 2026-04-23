from __future__ import annotations

from pathlib import Path
import tomllib

from codex_blender_agent import bl_info
from codex_blender_agent.constants import ADDON_VERSION


def test_package_manifest_version_matches_python_metadata():
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "codex_blender_agent" / "blender_manifest.toml").read_text(encoding="utf-8"))

    assert manifest["id"] == "codex_blender_agent"
    assert manifest["version"] == ADDON_VERSION
    assert tuple(int(part) for part in ADDON_VERSION.split(".")) == bl_info["version"]
    assert "__pycache__/" in manifest["build"]["paths_exclude_pattern"]
    assert "*.zip" in manifest["build"]["paths_exclude_pattern"]
