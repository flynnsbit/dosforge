"""FreeDOS profile (boot_mode='freedos')."""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="freedos",
    display_name="FreeDOS",
    oem_string=b"FRDOS5.1",
    system_files=(
        SystemFile(name="KERNEL.SYS", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16", "fat32"),
    expects_dos_dir=False,
    install_dir_name="FDOS",
    pre_dos5=False,
    is_freedos=True,
)
