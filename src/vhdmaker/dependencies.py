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

# Boot modes that drive an emulated DOS install to produce an authentic
# boot sector via the DOS's own SYS.COM. Currently compaq331 + msdos33
# (their boot-sector templates are stored inside FORMAT.COM/SYS.COM as a
# floppy layout that gets patched at runtime; offline extraction is
# unreliable).
LEGACY_DOS_QEMU_COMMANDS: tuple[str, ...] = (
    "qemu-system-i386",
    "mformat",
    "mcopy",
    "mattrib",
    "mtype",
    "mdir",
    "mdel",
)

# Boot modes that use the LEGACY_DOS_QEMU_COMMANDS install path. Update
# this set when adding a new legacy DOS boot mode that uses the same
# QEMU-driven SYS approach.
_LEGACY_DOS_QEMU_BOOT_MODES = frozenset({BootMode.COMPAQ331, BootMode.MSDOS33})


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
    if boot_mode in _LEGACY_DOS_QEMU_BOOT_MODES and media_type is MediaType.VHD:
        missing.extend(find_missing(LEGACY_DOS_QEMU_COMMANDS))
    missing = sorted(set(missing))
    if missing:
        formatted = ", ".join(missing)
        raise DependencyError(f"Missing required tools: {formatted}")
