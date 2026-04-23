from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_ZIP = Path("codex_blender_agent.zip")
DEFAULT_PACKAGE = Path("codex_blender_agent")

REQUIRED_ZIP_ENTRIES = (
    "codex_blender_agent/__init__.py",
    "codex_blender_agent/blender_manifest.toml",
    "codex_blender_agent/asset_library.py",
    "codex_blender_agent/asset_store.py",
    "codex_blender_agent/runtime.py",
    "codex_blender_agent/tool_specs.py",
    "codex_blender_agent/workflow_nodes.py",
    "codex_blender_agent/workflow_examples.py",
    "codex_blender_agent/workspace.py",
    "codex_blender_agent/workspace_templates.blend",
)

BAD_ZIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".zip",
    ".blend1",
    ".tmp",
)


@dataclass
class GateReport:
    zip_path: str
    source_root: str
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    blender_extension_validate: dict[str, object] | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and not (
            self.blender_extension_validate
            and self.blender_extension_validate.get("returncode") not in (0, None)
        )

    def add_check(self, name: str) -> None:
        self.checks.append(name)

    def add_failure(self, message: str) -> None:
        self.failures.append(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "zip_path": self.zip_path,
            "source_root": self.source_root,
            "checks": self.checks,
            "failures": self.failures,
            "blender_extension_validate": self.blender_extension_validate,
        }


def parse_manifest_version(text: str) -> str:
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise ValueError("blender_manifest.toml does not declare version.")
    return match.group(1)


def parse_bl_info_version(init_text: str) -> str:
    tree = ast.parse(init_text)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    value = ast.literal_eval(node.value)
                    version = value.get("version")
                    if not isinstance(version, tuple):
                        raise ValueError("bl_info['version'] is not a tuple.")
                    return ".".join(str(part) for part in version)
    raise ValueError("__init__.py does not declare bl_info.")


def _zip_entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path, "r") as archive:
        return archive.namelist()


def _read_zip_text(zip_path: Path, entry: str) -> str:
    with zipfile.ZipFile(zip_path, "r") as archive:
        return archive.read(entry).decode("utf-8")


def validate_zip_source_only(zip_path: Path, source_root: Path = Path(".")) -> GateReport:
    zip_path = Path(zip_path)
    source_root = Path(source_root)
    report = GateReport(str(zip_path), str(source_root))

    if not zip_path.exists():
        report.add_failure(f"ZIP does not exist: {zip_path}")
        return report

    try:
        entries = _zip_entries(zip_path)
    except zipfile.BadZipFile as exc:
        report.add_failure(f"Invalid ZIP file: {exc}")
        return report

    report.add_check("zip_readable")
    entry_set = set(entries)
    for required in REQUIRED_ZIP_ENTRIES:
        if required not in entry_set:
            report.add_failure(f"Missing required ZIP entry: {required}")
    report.add_check("required_entries_present")

    for entry in entries:
        normalized = entry.replace("\\", "/")
        if entry != normalized:
            report.add_failure(f"ZIP entry uses backslashes: {entry}")
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            report.add_failure(f"ZIP entry escapes package root: {entry}")
        lower = normalized.lower()
        if "__pycache__/" in lower:
            report.add_failure(f"ZIP contains __pycache__: {entry}")
        if lower.endswith(BAD_ZIP_SUFFIXES):
            report.add_failure(f"ZIP contains forbidden build artifact: {entry}")
        if not normalized.startswith("codex_blender_agent/"):
            report.add_failure(f"ZIP entry is outside extension package root: {entry}")
    report.add_check("source_only_entries")

    if "codex_blender_agent/blender_manifest.toml" in entry_set and "codex_blender_agent/__init__.py" in entry_set:
        try:
            manifest_version = parse_manifest_version(_read_zip_text(zip_path, "codex_blender_agent/blender_manifest.toml"))
            bl_info_version = parse_bl_info_version(_read_zip_text(zip_path, "codex_blender_agent/__init__.py"))
            if manifest_version != bl_info_version:
                report.add_failure(f"Version mismatch: manifest={manifest_version}, bl_info={bl_info_version}")
        except Exception as exc:
            report.add_failure(f"Version validation failed: {exc}")
    report.add_check("version_consistency")

    manifest_path = source_root / DEFAULT_PACKAGE / "blender_manifest.toml"
    if manifest_path.exists():
        manifest_text = manifest_path.read_text(encoding="utf-8")
        for expected in ('"__pycache__/"', '"*.zip"'):
            if expected not in manifest_text:
                report.add_failure(f"Manifest build exclusions missing {expected}.")
        report.add_check("manifest_excludes_build_artifacts")

    return report


def run_blender_extension_validate(blender_exe: Path, zip_path: Path) -> dict[str, object]:
    command = [
        str(blender_exe),
        "--factory-startup",
        "-c",
        "extension",
        "validate",
        str(zip_path),
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "output": completed.stdout[-12000:],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the Codex Blender Agent extension package.")
    parser.add_argument("--zip", dest="zip_path", default=str(DEFAULT_ZIP), help="Path to codex_blender_agent.zip.")
    parser.add_argument("--source-root", default=".", help="Repository/source root.")
    parser.add_argument("--blender-exe", default="", help="Optional Blender executable used for extension validate.")
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = validate_zip_source_only(Path(args.zip_path), Path(args.source_root))
    if args.blender_exe:
        report.blender_extension_validate = run_blender_extension_validate(Path(args.blender_exe), Path(args.zip_path))

    payload = report.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        print(f"Package gate: {'PASS' if report.ok else 'FAIL'}")
        for check in report.checks:
            print(f"  check: {check}")
        for failure in report.failures:
            print(f"  failure: {failure}")
        if report.blender_extension_validate is not None:
            print(f"  blender extension validate returncode: {report.blender_extension_validate['returncode']}")
            output = str(report.blender_extension_validate.get("output", "")).strip()
            if output:
                print(output)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
