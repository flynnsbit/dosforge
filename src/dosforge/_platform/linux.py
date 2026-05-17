"""Linux backend — current dosforge behavior.

This backend preserves the v0.2.x semantics 1:1 so the Linux build
is regression-safe. The Windows backend overrides what differs.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import BootMode, FreeDOSSource, MediaType
from .base import PlatformBackend


APP_NAME = "dosforge"


# These constants mirror what ``dependencies.py`` used to expose
# before the platform-abstraction refactor.
_REQUIRED_COMMANDS_BASE: tuple[str, ...] = (
    "mkfs.fat",
    "mount",
    "umount",
    "sudo",
    "xdg-open",
)

_REQUIRED_COMMANDS_VHD: tuple[str, ...] = (
    "qemu-img",
    "qemu-nbd",
    "parted",
    "partprobe",
)

_BOOT_COMMANDS: tuple[str, ...] = (
    "dd",
    "mcopy",
    "mattrib",
)

_LEGACY_DOS_QEMU_COMMANDS: tuple[str, ...] = (
    "qemu-system-i386",
    "mformat",
    "mcopy",
    "mattrib",
    "mtype",
    "mdir",
    "mdel",
)

# Boot modes that use the QEMU-driven SYS install pipeline. Mirrors
# ``dependencies._LEGACY_DOS_QEMU_BOOT_MODES``.
_LEGACY_DOS_QEMU_BOOT_MODES = frozenset(
    {BootMode.COMPAQ331, BootMode.MSDOS33, BootMode.MSDOS331}
)


class LinuxBackend(PlatformBackend):
    """XDG-conformant Linux backend with full kernel-mount + NBD support."""

    name = "linux"

    # -- Filesystem locations ------------------------------------------------

    def state_dir(self) -> Path:
        env_value = os.environ.get("XDG_STATE_HOME")
        base = Path(env_value).expanduser() if env_value else Path.home() / ".local" / "state"
        return base / APP_NAME

    # -- Capability flags ----------------------------------------------------

    @property
    def supports_kernel_mount(self) -> bool:
        return True

    @property
    def supports_nbd(self) -> bool:
        return True

    @property
    def requires_sudo_for_disk_ops(self) -> bool:
        return True

    @property
    def supports_external_file_manager(self) -> bool:
        return True

    # -- Dependency lists ----------------------------------------------------

    def required_commands(
        self,
        *,
        media_type: MediaType,
        boot_mode: BootMode,
        freedos_source: FreeDOSSource,
    ) -> tuple[str, ...]:
        commands: list[str] = list(_REQUIRED_COMMANDS_BASE)
        if media_type is MediaType.VHD:
            commands.extend(_REQUIRED_COMMANDS_VHD)
        if boot_mode is not BootMode.NONE:
            commands.extend(_BOOT_COMMANDS)
        if boot_mode is BootMode.FREEDOS and freedos_source is FreeDOSSource.AUTO:
            commands.append("mcopy")
        if boot_mode in _LEGACY_DOS_QEMU_BOOT_MODES and media_type is MediaType.VHD:
            commands.extend(_LEGACY_DOS_QEMU_COMMANDS)
        return self._unique_preserving_order(commands)

    # -- Privilege helpers ---------------------------------------------------

    def sudo_prelaunch_command(self) -> list[str] | None:
        # The TUI startup uses ``sudo -v --preserve-env=HOME,PATH`` to
        # warm the sudo timestamp before launch. The CLI keeps that
        # logic for backward compatibility.
        return ["sudo", "--preserve-env=HOME,PATH", "-v"]
