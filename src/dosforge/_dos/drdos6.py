"""Digital Research DR DOS 6.0 profile (boot_mode='drdos6').

The October 1991 DR-DOS release that competed head-on with MS-DOS
5.0.  Carries an IBM-3.3-class BPB stamp despite shipping
DR-DOS-flavored IBMBIO / IBMDOS kernel binaries.  Supports FAT12
and FAT16, max ~32 MiB partition.  Works on any standard
MFM / IDE BIOS.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="drdos6",
    display_name="DR DOS 6.0",
    oem_string=b"IBM  3.3",
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
