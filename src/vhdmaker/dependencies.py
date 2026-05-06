"""External command dependency checks."""

from __future__ import annotations

import shutil
from collections.abc import Iterable

from .errors import DependencyError
from .models import BootMode, FreeDOSSource, MediaType

REQUIRED_COMMANDS_BASE: tuple[str, ...] = (
    "mkfs.fat",
    "mount",
    "umount",
    "sudo",
    "xdg-open",
)

REQUIRED_COMMANDS_VHD: tuple[str, ...] = (
    "qemu-img",
    "qemu-nbd",
    "parted",
    "partprobe",
)
REQUIRED_COMMANDS: tuple[str, ...] = (*REQUIRED_COMMANDS_BASE, *REQUIRED_COMMANDS_VHD)

BOOT_COMMANDS: tuple[str, ...] = (
    "dd",
    "mcopy",
    "mattrib",
)


def find_missing(commands: Iterable[str]) -> list[str]:
    return sorted([command for command in commands if shutil.which(command) is None])


def assert_dependencies(
    *,
    media_type: MediaType = MediaType.VHD,
    boot_mode: BootMode = BootMode.NONE,
    freedos_source: FreeDOSSource = FreeDOSSource.LOCAL,
) -> None:
    missing = find_missing(REQUIRED_COMMANDS_BASE)
    if media_type is MediaType.VHD:
        missing.extend(find_missing(REQUIRED_COMMANDS_VHD))
    if boot_mode is not BootMode.NONE:
        missing.extend(find_missing(BOOT_COMMANDS))
    if boot_mode is BootMode.FREEDOS and freedos_source is FreeDOSSource.AUTO:
        missing.extend(find_missing(("mcopy",)))
    missing = sorted(set(missing))
    if missing:
        formatted = ", ".join(missing)
        raise DependencyError(f"Missing required tools: {formatted}")
