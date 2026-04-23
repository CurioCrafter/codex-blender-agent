from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_GATE_PATH = ROOT / "scripts" / "package_gate.py"


def _load_package_gate():
    spec = importlib.util.spec_from_file_location("package_gate", PACKAGE_GATE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_zip_is_source_only_and_version_consistent():
    package_gate = _load_package_gate()

    report = package_gate.validate_zip_source_only(ROOT / "codex_blender_agent.zip", ROOT)

    assert report.ok, report.as_dict()
    assert "source_only_entries" in report.checks
    assert "version_consistency" in report.checks


def test_package_gate_rejects_compiled_or_out_of_root_entries(tmp_path):
    package_gate = _load_package_gate()
    zip_path = tmp_path / "bad.zip"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("codex_blender_agent/__init__.py", "bl_info = {'version': (0, 0, 1)}")
        archive.writestr("codex_blender_agent/blender_manifest.toml", 'version = "0.0.1"')
        archive.writestr("codex_blender_agent/__pycache__/bad.pyc", "compiled")
        archive.writestr("outside.txt", "bad")

    report = package_gate.validate_zip_source_only(zip_path, tmp_path)

    assert not report.ok
    assert any("__pycache__" in failure for failure in report.failures)
    assert any("outside extension package root" in failure for failure in report.failures)


def test_manifest_and_bl_info_version_parsers():
    package_gate = _load_package_gate()

    assert package_gate.parse_manifest_version('id = "x"\nversion = "1.2.3"\n') == "1.2.3"
    assert package_gate.parse_bl_info_version("bl_info = {'name': 'x', 'version': (1, 2, 3)}\n") == "1.2.3"
