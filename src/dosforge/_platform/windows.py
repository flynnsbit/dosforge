"""Windows backend stub.

Phase 0 only — supplies state-dir paths and capability flags so the
rest of the codebase can ask the right questions on a Windows host.
Phases 2 and 3 will fill in :meth:`tool_path` to point at bundled
binaries under ``vendor/windows/bin/`` and replace the kernel-mount /
NBD code paths with pure-Python + mtools equivalents.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import BootMode, FreeDOSSource, MediaType
from .base import PlatformBackend


APP_NAME = "dosforge"


class WindowsBackend(PlatformBackend):
    """Windows 11 backend: no kernel mount, no NBD, no sudo.

    All disk operations run as the current user; partitioning + FAT
    formatting are pure-Python; system-file staging uses bundled
    mtools binaries; SYS-install paths drive a bundled QEMU.
    """

    name = "windows"

    # -- Filesystem locations ------------------------------------------------

    def state_dir(self) -> Path:
        env_value = os.environ.get("LOCALAPPDATA")
        if env_value:
            base = Path(env_value)
        else:
            # Fall back to %USERPROFILE%\AppData\Local — matches the
            # default Windows resolution if LOCALAPPDATA is somehow
            # unset (it almost always is set on a sane Win11 host).
            user_profile = os.environ.get("USERPROFILE")
            base = (
                Path(user_profile) / "AppData" / "Local"
                if user_profile
                else Path.home() / "AppData" / "Local"
            )
        return base / APP_NAME

    # -- Capability flags ----------------------------------------------------
    #
    # Windows has no NBD module and we deliberately avoid Mount-VHD /
    # diskpart attach-vdisk in v0.3.0 so that no admin elevation is
    # ever required. The in-app mtools file browser replaces both.

    @property
    def supports_kernel_mount(self) -> bool:
        return False

    @property
    def supports_nbd(self) -> bool:
        return False

    @property
    def requires_sudo_for_disk_ops(self) -> bool:
        return False

    @property
    def supports_external_file_manager(self) -> bool:
        # The Windows port intentionally skips Explorer integration for
        # mounted VHDs — the in-app TUI browser is the supported flow.
        return False

    # -- Dependency lists ----------------------------------------------------
    #
    # The Windows backend bundles all of these under
    # ``vendor/windows/bin/`` so this list is informational rather than
    # a precondition. ``tool_path`` will turn each name into an
    # absolute ``.exe`` path inside the install layout.

    def required_commands(
        self,
        *,
        media_type: MediaType,
        boot_mode: BootMode,
        freedos_source: FreeDOSSource,
    ) -> tuple[str, ...]:
        commands: list[str] = []
        if media_type is MediaType.VHD:
            commands.append("qemu-img")
        # FAT format + partition staging is done in pure Python on
        # Windows (Phase 1 + 3), but mtools is still required for
        # boot system-file staging.
        if boot_mode is not BootMode.NONE:
            commands.extend(("mcopy", "mattrib"))
        if boot_mode in {BootMode.COMPAQ331, BootMode.MSDOS33, BootMode.MSDOS331} and (
            media_type is MediaType.VHD
        ):
            commands.extend(("qemu-system-i386", "mformat", "mcopy", "mattrib", "mdir"))
        if boot_mode is BootMode.FREEDOS and freedos_source is FreeDOSSource.AUTO:
            commands.append("mcopy")
        return self._unique_preserving_order(commands)
