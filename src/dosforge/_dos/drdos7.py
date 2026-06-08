"""Caldera DR-DOS 7.03 profile (boot_mode='drdos7').

The January 1999 final retail DR-DOS release.  Distinct
``DRDOS  7`` BPB OEM stamp.  Supports FAT16B / BIGDOS up to 2 GiB
plus FAT12 for floppies.  FAT32 LBA is structurally supported by
the kernel but dosforge currently exposes only the FAT16 path.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="drdos7",
    display_name="Caldera DR-DOS 7.03",
    oem_string=b"DRDOS  7",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS"),
        SystemFile(name="IBMDOS.COM", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=False,
    pre_dos5=False,
)
