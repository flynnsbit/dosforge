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


def find_missing(commands: Iterable[str]) -> list[str]:
    return sorted([command for command in commands if shutil.which(command) is None])


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
    missing = find_missing(required)
    if missing:
        formatted = ", ".join(missing)
        raise DependencyError(f"Missing required tools: {formatted}")
