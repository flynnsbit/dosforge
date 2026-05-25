"""Shared dataclasses for per-DOS-version metadata."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import MediaType


@dataclass(frozen=True, slots=True)
class SystemFile:
    """One file that must land at the partition root after install."""

    name: str
    attributes: str  # FAT attr flags like "RHS" for IO.SYS, "A" for COMMAND.COM
    required: bool = True


@dataclass(frozen=True, slots=True)
class DosProfile:
    """Authenticity metadata for one DOS variant."""

    boot_mode: str
    display_name: str
    oem_string: bytes
    system_files: tuple[SystemFile, ...]
    supported_filesystems: tuple[str, ...]
    expects_dos_dir: bool = True
    install_dir_name: str = "DOS"
    requires_emulator_for_sys_install: bool = False
    pre_dos5: bool = False
    is_freedos: bool = False


def install_dir_for_media(profile: DosProfile, media_type: MediaType) -> str:
    drive = "C:" if media_type is MediaType.VHD else "A:"
    return f"{drive}\\{profile.install_dir_name}"
