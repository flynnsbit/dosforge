"""IBM PC-DOS 3.00 profile (boot_mode='pcdos3').

IBM's first hard-disk-aware DOS (August 1984), released alongside
the IBM PC AT.  FAT12 only (FAT16 was added in PC-DOS 3.10), ~16 MiB
max partition.  Has BPB.hidden_sectors field so HDD boot works on
any standard MFM / IDE BIOS without Compaq-specific extensions.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="pcdos3",
    display_name="IBM PC-DOS 3.00",
    oem_string=b"IBM  3.0",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS"),
        SystemFile(name="IBMDOS.COM", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12",),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=True,
)
