from __future__ import annotations

from codex_blender_agent.core.launch import build_codex_app_server_command


def test_launch_command_windows_cmd(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    command = build_codex_app_server_command(r"C:\Users\ExampleUser\AppData\Roaming\npm\codex.cmd")
    assert command[:2] == ["cmd.exe", "/c"]
    assert command[-3:] == ["app-server", "--listen", "stdio://"]


def test_launch_command_windows_exe(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    command = build_codex_app_server_command(r"C:\Tools\codex.exe")
    assert command == [r"C:\Tools\codex.exe", "app-server", "--listen", "stdio://"]


def test_launch_command_unix(monkeypatch):
    monkeypatch.setattr("os.name", "posix")
    command = build_codex_app_server_command("codex")
    assert command == ["codex", "app-server", "--listen", "stdio://"]
