from __future__ import annotations

import os
import shlex


def build_codex_app_server_command(codex_command: str) -> list[str]:
    command_text = (codex_command or "").strip()
    if not command_text:
        raise ValueError("Codex command is empty.")

    parts = shlex.split(command_text, posix=os.name != "nt")
    if not parts:
        raise ValueError("Codex command is empty.")

    if os.name == "nt":
        first = parts[0].lower()
        if first.endswith(".ps1"):
            return [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                *parts,
                "app-server",
                "--listen",
                "stdio://",
            ]

        if first.endswith(".exe"):
            return [*parts, "app-server", "--listen", "stdio://"]

        return ["cmd.exe", "/c", *parts, "app-server", "--listen", "stdio://"]

    return [*parts, "app-server", "--listen", "stdio://"]
