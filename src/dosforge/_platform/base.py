"""Abstract :class:`PlatformBackend` interface.

Concrete subclasses live in :mod:`dosforge._platform.linux` and
:mod:`dosforge._platform.windows`. The base class intentionally has
sensible Linux-flavored defaults — Windows overrides what differs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from ..models import BootMode, FreeDOSSource, MediaType


class PlatformBackend(ABC):
    """Per-platform behavior contract for dosforge."""

    name: str = "abstract"

    # -- Filesystem locations ------------------------------------------------

    @abstractmethod
    def state_dir(self) -> Path:
        """Persistent app state (``state.json``, etc.)."""

    def cache_dir(self) -> Path:
        return self.state_dir() / "cache"

    def mount_root(self) -> Path:
        return self.state_dir() / "mounts"

    def state_file(self) -> Path:
        return self.state_dir() / "state.json"

    # -- Binary resolution ---------------------------------------------------

    def tool_path(self, name: str) -> str:
        """Resolve an external command to an absolute path or bare name.

        Linux returns the bare name and relies on ``PATH``. Windows
        overrides this to return a bundled ``vendor/windows/bin/`` path
        so the build is self-contained.
        """

        return name

    # -- Capability flags ----------------------------------------------------

    @property
    def supports_kernel_mount(self) -> bool:
        """True when ``mount(2)`` / ``losetup`` are available for FAT volumes."""

        return False

    @property
    def supports_nbd(self) -> bool:
        """True when ``qemu-nbd`` + Linux NBD kernel module work for VHDs."""

        return False

    @property
    def requires_sudo_for_disk_ops(self) -> bool:
        """True when partition-table / format / mount steps need root."""

        return False

    @property
    def supports_external_file_manager(self) -> bool:
        """True when xdg-open / explorer.exe can browse a mounted volume."""

        return False

    # -- Legacy DOS emulator ------------------------------------------------

    def legacy_dos_emulator(self) -> str:
        """Which emulator drives the SYS-install for the 3 legacy DOS modes.

        Returns ``"qemu"`` (default — drive ``qemu-system-i386``) or
        ``"dosbox-x"`` (drive DOSBox-X via ``dosbox-x.exe``).  The
        DOSBox-X path is smaller (~24 MB single EXE vs ~135 MB QEMU +
        DLL stack on Windows) and is the default on builds where the
        DOSBox-X vendor binary is available.
        """

        return "qemu"

    # -- Dependency lists ----------------------------------------------------

    @abstractmethod
    def required_commands(
        self,
        *,
        media_type: MediaType,
        boot_mode: BootMode,
        freedos_source: FreeDOSSource,
    ) -> tuple[str, ...]:
        """External commands the backend needs for the given request."""

    # -- Privilege helpers ---------------------------------------------------

    def sudo_prelaunch_command(self) -> list[str] | None:
        """Return the command to refresh sudo creds before TUI launch, if any."""

        return None

    # -- Misc ----------------------------------------------------------------

    @staticmethod
    def _unique_preserving_order(items: Iterable[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return tuple(ordered)
