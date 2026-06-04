"""Command execution helpers with explicit error propagation."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .errors import CommandError, DependencyError


# On Windows, when the parent process is windowed (e.g. dosforge-gui.exe with
# console=False), every subprocess spawned for a CLI tool like qemu-img.exe
# or mformat.exe gets its own brand-new console window that flashes on screen.
# Passing CREATE_NO_WINDOW (0x08000000) tells the OS not to create a console
# for the child. stdout/stderr are still captured via pipes because every
# call site uses ``capture_output=True``. On non-Windows this constant doesn't
# exist and the kwargs dict is empty.
def subprocess_no_window_kwargs() -> dict:
    """Return kwargs to add to ``subprocess.run`` / ``Popen`` calls so the
    child process does NOT pop a console window on Windows.

    Importable from any module that calls subprocess directly.
    """
    if sys.platform != "win32":
        return {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": flag}


_NO_WINDOW_KWARGS = subprocess_no_window_kwargs()


@dataclass(slots=True)
class RunResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(
        self,
        sudo_binary: str = "sudo",
        *,
        tool_resolver: Callable[[str], str] | None = None,
        sudo_required: bool = True,
    ) -> None:
        """Create a runner.

        ``tool_resolver`` (optional) substitutes the first argument of
        every command — used on Windows to swap bare names like
        ``qemu-img`` for absolute paths into ``vendor/windows/bin/``.

        ``sudo_required`` (default True) controls whether ``sudo=True``
        actually prepends a sudo invocation. On Windows backends this
        is set to False and the ``sudo=True`` flag becomes a no-op so
        existing call sites work unchanged.
        """

        self.sudo_binary = sudo_binary
        self._tool_resolver = tool_resolver
        self._sudo_required = sudo_required

    def _resolve_argv(self, command: Sequence[str]) -> list[str]:
        argv = list(command)
        if not argv:
            return argv
        if self._tool_resolver is not None:
            argv[0] = self._tool_resolver(argv[0])
        return argv

    def run(
        self,
        command: Sequence[str],
        *,
        sudo: bool = False,
        check: bool = True,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RunResult:
        resolved = self._resolve_argv(command)
        use_sudo = sudo and self._sudo_required
        full_command = (
            [self.sudo_binary, "-n", "--preserve-env=HOME,PATH", *resolved] if use_sudo else resolved
        )
        try:
            completed = subprocess.run(
                full_command,
                check=False,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                **_NO_WINDOW_KWARGS,
            )
        except FileNotFoundError as exc:
            missing = full_command[0] if full_command else "<unknown>"
            raise DependencyError(f"Missing external command: {missing}") from exc

        if use_sudo and completed.returncode != 0 and self._sudo_disallows_preserve_env(completed.stderr):
            fallback_command = [self.sudo_binary, "-n", *resolved]
            try:
                completed = subprocess.run(
                    fallback_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    env=dict(env) if env is not None else None,
                    **_NO_WINDOW_KWARGS,
                )
                full_command = fallback_command
            except FileNotFoundError as exc:
                missing = fallback_command[0] if fallback_command else "<unknown>"
                raise DependencyError(f"Missing external command: {missing}") from exc

        result = RunResult(
            command=tuple(full_command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and completed.returncode != 0:
            raise CommandError(
                command=result.command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def _sudo_disallows_preserve_env(self, stderr: str) -> bool:
        message = stderr.lower()
        return "not allowed to set the following environment variables" in message and (
            "home" in message or "path" in message
        )

    def run_detached(self, command: Sequence[str]) -> None:
        resolved = self._resolve_argv(command)
        try:
            subprocess.Popen(
                resolved,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                **_NO_WINDOW_KWARGS,
            )
        except FileNotFoundError as exc:
            missing = resolved[0] if resolved else "<unknown>"
            raise DependencyError(f"Missing external command: {missing}") from exc


def runner_for_backend(backend) -> CommandRunner:
    """Build a :class:`CommandRunner` configured for ``backend``.

    On Linux this is the historical behavior (sudo enforced). On
    Windows the runner is wired with the backend's ``tool_path`` and
    sudo is disabled entirely so existing ``sudo=True`` call sites
    continue to compile but become no-ops.
    """

    return CommandRunner(
        tool_resolver=backend.tool_path,
        sudo_required=backend.requires_sudo_for_disk_ops,
    )
