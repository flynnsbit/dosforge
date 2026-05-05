"""External command dependency checks."""

from __future__ import annotations

import shutil
from collections.abc import Iterable

from .errors import DependencyError
from .models import BootMode, FreeDOSSource

REQUIRED_COMMANDS: tuple[str, ...] = (
    "qemu-img",
    "qemu-nbd",
    "parted",
    "partprobe",
    "mkfs.fat",
    "mount",
    "umount",
    "sudo",
    "xdg-open",
)

BOOT_COMMANDS: tuple[str, ...] = (
    "dd",
    "mcopy",
    "mattrib",
)


def find_missing(commands: Iterable[str]) -> list[str]:
    return sorted([command for command in commands if shutil.which(command) is None])


def assert_dependencies(
    *,
    boot_mode: BootMode = BootMode.NONE,
    freedos_source: FreeDOSSource = FreeDOSSource.LOCAL,
) -> None:
    missing = find_missing(REQUIRED_COMMANDS)
    if boot_mode is not BootMode.NONE:
        missing.extend(find_missing(BOOT_COMMANDS))
    if boot_mode is BootMode.FREEDOS and freedos_source is FreeDOSSource.AUTO:
        missing.extend(find_missing(("mcopy",)))
    missing = sorted(set(missing))
    if missing:
        formatted = ", ".join(missing)
        raise DependencyError(f"Missing required tools: {formatted}")
