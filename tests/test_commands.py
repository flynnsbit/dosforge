from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from vhdmaker.commands import CommandRunner


def test_command_runner_uses_non_interactive_sudo(monkeypatch: Any) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        cwd: Path | None,
        env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, cwd, env
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = CommandRunner()
    runner.run(["true"], sudo=True)

    assert captured["command"][:3] == ["sudo", "-n", "--preserve-env=HOME,PATH"]


def test_command_runner_retries_without_preserve_env_when_disallowed(monkeypatch: Any) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        cwd: Path | None,
        env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, cwd, env
        calls.append(command)
        if command[:3] == ["sudo", "-n", "--preserve-env=HOME,PATH"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="sudo: sorry, you are not allowed to set the following environment variables: HOME, PATH",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = CommandRunner()
    runner.run(["true"], sudo=True)

    assert calls[0][:3] == ["sudo", "-n", "--preserve-env=HOME,PATH"]
    assert calls[1][:2] == ["sudo", "-n"]
    assert "--preserve-env=HOME,PATH" not in calls[1]
