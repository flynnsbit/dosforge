"""IBM PC-DOS 7.1 profile (boot_mode='pcdos71').

Final IBM PC-DOS release with FAT32 support via FORMAT32.COM.
Uses the emulator-driven install path because FORMAT32 must run
under a host DOS to lay down the FAT32 partition correctly.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="pcdos71",
    display_name="IBM PC-DOS 7.1",
    oem_string=b"IBM  7.1",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS"),
        SystemFile(name="IBMDOS.COM", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16", "fat32"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=False,
)
