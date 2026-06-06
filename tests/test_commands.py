from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from dosforge.commands import (
    CommandRunner,
    SudoKeepAlive,
    sudo_keepalive_for_backend,
)


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


def _fake_completed(argv: list[str], *, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout="", stderr=stderr)


def test_sudo_keepalive_is_noop_when_not_required() -> None:
    """Windows-style backends should never spawn the keep-alive thread."""

    calls: list[list[str]] = []

    def fake_runner(argv):
        calls.append(list(argv))
        return _fake_completed(list(argv))

    keep = SudoKeepAlive(required=False, interval_seconds=0.05, runner=fake_runner)
    keep.start()
    time.sleep(0.15)
    keep.stop(timeout=0.5)

    assert calls == []
    assert keep._thread is None  # type: ignore[attr-defined]


def test_sudo_keepalive_refreshes_periodically_with_preserve_env() -> None:
    calls: list[list[str]] = []
    saw_two = threading.Event()

    def fake_runner(argv):
        calls.append(list(argv))
        if len(calls) >= 2:
            saw_two.set()
        return _fake_completed(list(argv))

    # SudoKeepAlive clamps interval to >=0.05s; wait long enough to
    # observe two firings at this fast test cadence.
    keep = SudoKeepAlive(required=True, interval_seconds=0.05, runner=fake_runner)
    with keep:
        assert saw_two.wait(timeout=2.0)

    assert len(calls) >= 2
    for argv in calls:
        assert argv[:4] == ["sudo", "-n", "-v", "--preserve-env=HOME,PATH"]


def test_sudo_keepalive_falls_back_when_preserve_env_disallowed() -> None:
    calls: list[list[str]] = []
    saw_fallback = threading.Event()

    def fake_runner(argv):
        calls.append(list(argv))
        if argv[:4] == ["sudo", "-n", "-v", "--preserve-env=HOME,PATH"]:
            return _fake_completed(
                list(argv),
                returncode=1,
                stderr=(
                    "sudo: sorry, you are not allowed to set the following "
                    "environment variables: HOME, PATH"
                ),
            )
        saw_fallback.set()
        return _fake_completed(list(argv))

    keep = SudoKeepAlive(required=True, interval_seconds=0.05, runner=fake_runner)
    with keep:
        assert saw_fallback.wait(timeout=2.0)

    # First call: --preserve-env attempt that gets refused.
    assert calls[0][:4] == ["sudo", "-n", "-v", "--preserve-env=HOME,PATH"]
    # Second call: bare fallback without --preserve-env.
    assert any(c[:3] == ["sudo", "-n", "-v"] and "--preserve-env=HOME,PATH" not in c for c in calls)


def test_sudo_keepalive_invokes_on_failure_once_per_stale_state() -> None:
    failures: list[subprocess.CompletedProcess[str]] = []
    failed_event = threading.Event()

    def fake_runner(argv):
        return _fake_completed(list(argv), returncode=1, stderr="sudo: a password is required")

    def on_failure(result):
        failures.append(result)
        failed_event.set()

    keep = SudoKeepAlive(
        required=True,
        interval_seconds=0.05,
        runner=fake_runner,
        on_failure=on_failure,
    )
    with keep:
        assert failed_event.wait(timeout=2.0)
        # Give the loop more opportunities to fire.
        time.sleep(0.3)

    # The callback must fire exactly once until the next *successful*
    # refresh resets the stale flag.
    assert len(failures) == 1
    assert failures[0].returncode == 1


def test_sudo_keepalive_factory_respects_backend_flag() -> None:
    class WindowsLikeBackend:
        requires_sudo_for_disk_ops = False

    class LinuxLikeBackend:
        requires_sudo_for_disk_ops = True

    win_keep = sudo_keepalive_for_backend(WindowsLikeBackend())
    lin_keep = sudo_keepalive_for_backend(LinuxLikeBackend())

    assert isinstance(win_keep, SudoKeepAlive)
    assert win_keep._required is False  # type: ignore[attr-defined]
    assert lin_keep._required is True  # type: ignore[attr-defined]
