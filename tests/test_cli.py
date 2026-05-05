from __future__ import annotations

import pytest

import vhdmaker.cli as cli
from vhdmaker.commands import RunResult
from vhdmaker.errors import ValidationError


def test_main_tui_primes_sudo_before_running_app(monkeypatch) -> None:
    calls = {"auth": 0, "run": 0}

    def fake_auth() -> None:
        calls["auth"] += 1

    class FakeApp:
        def run(self) -> None:
            calls["run"] += 1

    monkeypatch.setattr(cli, "ensure_startup_sudo_auth", fake_auth)
    monkeypatch.setattr(cli, "VhdMakerApp", FakeApp)

    assert cli.main(["tui"]) == 0
    assert calls == {"auth": 1, "run": 1}


def test_main_tui_returns_error_when_sudo_auth_fails(monkeypatch, capsys) -> None:
    def fail_auth() -> None:
        raise ValidationError("sudo auth failed")

    monkeypatch.setattr(cli, "ensure_startup_sudo_auth", fail_auth)

    assert cli.main(["tui"]) == 1
    captured = capsys.readouterr()
    assert "sudo auth failed" in captured.err


def test_sudo_check_exit_code_and_output(monkeypatch, capsys) -> None:
    class FakeManager:
        def privilege_diagnostics_summary(self) -> tuple[bool, str]:
            return (False, "Privilege diagnostics found blocking issues.")

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    assert cli.main(["sudo-check"]) == 1
    captured = capsys.readouterr()
    assert "blocking issues" in captured.out


def test_ensure_startup_sudo_auth_rejects_missing_noninteractive_session(monkeypatch) -> None:
    class Result:
        returncode = 0

    class FakeRunner:
        def run(self, command, *, sudo=False, check=True, cwd=None, env=None):
            del command, sudo, check, cwd, env
            return RunResult(command=("true",), returncode=1, stdout="", stderr="sudo: a password is required")

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(ValidationError, match="non-interactive sudo is not available"):
        cli.ensure_startup_sudo_auth(runner=FakeRunner())
