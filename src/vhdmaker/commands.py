"""Command execution helpers with explicit error propagation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .errors import CommandError, DependencyError


@dataclass(slots=True)
class RunResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, sudo_binary: str = "sudo") -> None:
        self.sudo_binary = sudo_binary

    def run(
        self,
        command: Sequence[str],
        *,
        sudo: bool = False,
        check: bool = True,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RunResult:
        full_command = (
            [self.sudo_binary, "-n", "--preserve-env=HOME,PATH", *command] if sudo else list(command)
        )
        try:
            completed = subprocess.run(
                full_command,
                check=False,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=dict(env) if env is not None else None,
            )
        except FileNotFoundError as exc:
            missing = full_command[0] if full_command else "<unknown>"
            raise DependencyError(f"Missing external command: {missing}") from exc

        if sudo and completed.returncode != 0 and self._sudo_disallows_preserve_env(completed.stderr):
            fallback_command = [self.sudo_binary, "-n", *command]
            try:
                completed = subprocess.run(
                    fallback_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    env=dict(env) if env is not None else None,
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
        try:
            subprocess.Popen(
                list(command),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            missing = command[0] if command else "<unknown>"
            raise DependencyError(f"Missing external command: {missing}") from exc
