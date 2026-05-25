"""Windows backend.

Implements the platform contract for Windows 11 hosts. All disk
operations run as the current user (no sudo / no admin):

- VHD allocation uses the bundled ``qemu-img.exe``.
- Partitioning uses :mod:`dosforge._core.mbr` (pure Python).
- FAT format uses the bundled ``mformat.exe`` (mtools) for VHDs and
  :mod:`dosforge._core.fat12_floppy` for floppy IMGs.
- System-file staging uses bundled ``mcopy.exe`` / ``mattrib.exe``
  with the ``-i <vhd_path>@@<partition_offset_bytes>`` syntax — no
  kernel mount required.
- QEMU-driven SYS install (compaq331 / msdos33 / msdos331) uses the
  bundled ``qemu-system-i386.exe``.

Tool binaries are resolved relative to the dosforge install root.
Two search strategies are tried, in order:

1. ``vendor/windows/bin/`` relative to the package source tree (dev
   checkouts populated by ``scripts/fetch-windows-vendor.py``).
2. ``DOSFORGE_VENDOR_DIR`` environment variable, set by the
   PyInstaller bundle launcher.

If neither yields the requested ``.exe``, the bare name is returned
and the OS will fall back to ``PATH``.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import BootMode, FreeDOSSource, MediaType
from .base import PlatformBackend


APP_NAME = "dosforge"

# Binaries we expect to find under ``vendor/windows/bin/``.
_KNOWN_BUNDLED_TOOLS: frozenset[str] = frozenset(
    {
        "qemu-img",
        "qemu-system-i386",
        "mformat",
        "mcopy",
        "mattrib",
        "mdir",
        "mtype",
        "mdel",
        "mmd",
        "dosbox-x",
    }
)


def _vendor_search_paths() -> list[Path]:
    """Return candidate ``vendor/windows/bin/`` directories.

    Order: env-var override (used by PyInstaller bundle) first, then
    relative-to-the-package source-tree layout (used by editable
    installs).
    """

    candidates: list[Path] = []
    env_override = os.environ.get("DOSFORGE_VENDOR_DIR")
    if env_override:
        candidates.append(Path(env_override))
    # ``Path(__file__).parents[2]`` is the package's repository root
    # in an editable install: <repo>/src/dosforge/_platform/windows.py
    # → repo = parents[2].
    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "vendor" / "windows" / "bin")
    except IndexError:  # pragma: no cover - unusual layout
        pass
    return candidates


class WindowsBackend(PlatformBackend):
    """Windows 11 backend: no kernel mount, no NBD, no sudo."""

    name = "windows"

    # -- Filesystem locations ------------------------------------------------

    def state_dir(self) -> Path:
        env_value = os.environ.get("LOCALAPPDATA")
        if env_value:
            base = Path(env_value)
        else:
            user_profile = os.environ.get("USERPROFILE")
            base = (
                Path(user_profile) / "AppData" / "Local"
                if user_profile
                else Path.home() / "AppData" / "Local"
            )
        return base / APP_NAME

    # -- Binary resolution ---------------------------------------------------

    def tool_path(self, name: str) -> str:
        """Resolve to ``vendor/windows/bin/<name>.exe`` if bundled."""

        if name not in _KNOWN_BUNDLED_TOOLS:
            return name
        for directory in _vendor_search_paths():
            candidate = directory / f"{name}.exe"
            if candidate.exists():
                return str(candidate)
        return name  # PATH fallback — fetch script likely hasn't run

    # -- Capability flags ----------------------------------------------------

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
        return True

    # -- Legacy DOS emulator selection --------------------------------------

    def legacy_dos_emulator(self) -> str:
        """Prefer the bundled DOSBox-X executable when present.

        DOSBox-X is a single self-contained ~24 MB EXE.  When the
        vendor fetch script has staged it under
        ``vendor/windows/bin/dosbox-x.exe``, the legacy-DOS install
        flow uses it instead of qemu-system-i386 + its ~110 MB of
        GTK / SDL / codec / virgl / etc. DLL ecosystem.

        Falls back to QEMU when DOSBox-X is not bundled (e.g., a build
        that pre-dates the DOSBox-X swap or a custom build that
        explicitly chose qemu-system).
        """

        for directory in _vendor_search_paths():
            if (directory / "dosbox-x.exe").exists():
                return "dosbox-x"
        return "qemu"

    # -- Dependency lists ----------------------------------------------------

    def required_commands(
        self,
        *,
        media_type: MediaType,
        boot_mode: BootMode,
        freedos_source: FreeDOSSource,
    ) -> tuple[str, ...]:
        commands: list[str] = []
        if media_type is MediaType.VHD:
            # mcopy + mmd are needed when a custom payload is being copied
            # into a non-bootable VHD (the existing mtools @@offset path).
            # Bundling them unconditionally keeps `check-deps` honest.
            commands.extend(("qemu-img", "mformat", "mcopy", "mmd"))
        if boot_mode is not BootMode.NONE:
            commands.extend(("mcopy", "mattrib"))
        if boot_mode in {BootMode.COMPAQ331, BootMode.MSDOS33, BootMode.MSDOS331} and (
            media_type is MediaType.VHD
        ):
            # Either DOSBox-X (preferred, ~24 MB single EXE) or
            # qemu-system-i386 (~135 MB with DLL stack) drives the
            # SYS install for these legacy DOS modes.  Whichever is
            # bundled wins.
            emulator = self.legacy_dos_emulator()
            if emulator == "dosbox-x":
                commands.extend(("dosbox-x", "mformat", "mcopy", "mattrib", "mdir"))
            else:
                commands.extend(("qemu-system-i386", "mformat", "mcopy", "mattrib", "mdir"))
        if boot_mode is BootMode.FREEDOS and freedos_source is FreeDOSSource.AUTO:
            commands.append("mcopy")
        return self._unique_preserving_order(commands)
