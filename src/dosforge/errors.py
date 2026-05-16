"""Domain-specific exceptions for dosforge."""

from __future__ import annotations

from dataclasses import dataclass
from shlex import join as shell_join
from typing import Sequence


class DosForgeError(Exception):
    """Base error for all dosforge failures."""


class ValidationError(DosForgeError):
    """Raised when user input or request shape is invalid."""


class DependencyError(DosForgeError):
    """Raised when required external tools are not available."""


@dataclass(slots=True)
class CommandError(DosForgeError):
    """Raised when an external command fails."""

    command: Sequence[str]
    returncode: int
    stdout: str
    stderr: str

    def __str__(self) -> str:
        command_text = shell_join(list(self.command))
        return (
            f"Command failed ({self.returncode}): {command_text}\n"
            f"stdout:\n{self.stdout}\n"
            f"stderr:\n{self.stderr}"
        )
