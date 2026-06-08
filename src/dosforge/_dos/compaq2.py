"""Compaq OEM MS-DOS 2.11 profile (boot_mode='compaq2').

The 1984 Compaq OEM release of MS-DOS 2.11.  DOS 2.x predates
FAT16 entirely; FAT12 only, ~16 MiB max partition.  Uses the
IBM-style system file names (IBMBIO.COM / IBMDOS.COM) that Compaq
carried over from PC-DOS.  Boots only on Compaq-era MFM
controllers because DOS 2.11's loader expects Compaq 1984 BIOS
extensions modern emulators don't provide.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="compaq2",
    display_name="Compaq MS-DOS 2.11",
    oem_string=b"COMPAQ  ",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS"),
        SystemFile(name="IBMDOS.COM", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12",),
    expects_dos_dir=False,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=True,
)
