"""External command dependency checks.

The list of required commands is computed by the active platform
backend (see :mod:`dosforge._platform`). The module-level
``REQUIRED_COMMANDS*`` / ``BOOT_COMMANDS`` / ``LEGACY_DOS_QEMU_COMMANDS``
tuples are kept as Linux-only constants for backward compatibility
with existing tests; new code should call
:func:`assert_dependencies` (which dispatches through the backend).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from ._platform import get_backend
from ._platform.linux import (
    _BOOT_COMMANDS as _LINUX_BOOT_COMMANDS,
    _LEGACY_DOS_QEMU_COMMANDS as _LINUX_LEGACY_DOS_QEMU_COMMANDS,
    _REQUIRED_COMMANDS_BASE as _LINUX_REQUIRED_COMMANDS_BASE,
    _REQUIRED_COMMANDS_VHD as _LINUX_REQUIRED_COMMANDS_VHD,
)
from .errors import DependencyError
from .models import BootMode, FreeDOSSource, MediaType

# Legacy module-level constants. These mirror what the v0.2.x build
# exposed; tests and CLI ``dependency-check`` callers still use them.
# The backend produces a platform-appropriate effective list.
REQUIRED_COMMANDS_BASE: tuple[str, ...] = _LINUX_REQUIRED_COMMANDS_BASE
REQUIRED_COMMANDS_VHD: tuple[str, ...] = _LINUX_REQUIRED_COMMANDS_VHD
REQUIRED_COMMANDS: tuple[str, ...] = (*REQUIRED_COMMANDS_BASE, *REQUIRED_COMMANDS_VHD)
BOOT_COMMANDS: tuple[str, ...] = _LINUX_BOOT_COMMANDS
LEGACY_DOS_QEMU_COMMANDS: tuple[str, ...] = _LINUX_LEGACY_DOS_QEMU_COMMANDS


def find_missing(commands: Iterable[str], *, backend=None) -> list[str]:
    """Return the subset of ``commands`` that cannot be located.

    On Linux this is a thin wrapper over :func:`shutil.which`. On
    Windows (where dosforge ships its own ``vendor/windows/bin/``
    binaries that are not on system PATH), the active platform backend
    is consulted first: if ``backend.tool_path(command)`` returns an
    absolute path that exists on disk, the command is considered
    available. Falls back to ``shutil.which`` otherwise.
    """

    if backend is None:
        backend = get_backend()
    missing: list[str] = []
    for command in commands:
        resolved = backend.tool_path(command)
        # ``tool_path`` returns the bare name when the bundled tool
        # could not be located; in that case use the regular PATH
        # lookup to handle both Linux (where commands live on PATH)
        # and any user-installed-on-PATH overrides on Windows.
        if resolved and resolved != command and Path(resolved).exists():
            continue
        if shutil.which(command) is not None:
            continue
        missing.append(command)
    return sorted(missing)


def assert_dependencies(
    *,
    media_type: MediaType = MediaType.VHD,
    boot_mode: BootMode = BootMode.NONE,
    freedos_source: FreeDOSSource = FreeDOSSource.LOCAL,
) -> None:
    backend = get_backend()
    required = backend.required_commands(
        media_type=media_type,
        boot_mode=boot_mode,
        freedos_source=freedos_source,
    )
    missing = find_missing(required, backend=backend)
    if missing:
        formatted = ", ".join(missing)
        raise DependencyError(f"Missing required tools: {formatted}")
