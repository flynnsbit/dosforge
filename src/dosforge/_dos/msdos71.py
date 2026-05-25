"""MS-DOS 7.1 profile (boot_mode='msdos71').

MS-DOS 7.10 is the FAT32-capable DOS kernel from Microsoft Windows 95
OSR2 (4.00.1111).  dosforge builds MSDOS71 VHDs by booting the OSR2
Emergency Boot Disk (``Boot.img``) inside QEMU and running ``SYS A: C:``
from a ramdrive-extracted copy of the OSR2 SYS.COM.  OSR2's SYS.COM
writes the authentic MS-DOS 7.10 FAT32 VBR with OEM string ``MSWIN4.1``
and copies the real Microsoft IO.SYS / MSDOS.SYS / DRVSPACE.BIN /
COMMAND.COM onto C:\\.

Earlier builds tried to use a "Microsoft DOS 7.1" PAK release.  That
distribution ships IO.SYS as an MZ-wrapped SETUP stub and is not a
viable install source — see ``dosassets/w95/readme.txt`` for context.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos71",
    display_name="MS-DOS 7.10 (Win95 OSR2)",
    oem_string=b"MSWIN4.1",
    system_files=(
        SystemFile(name="IO.SYS", attributes="RHS"),
        SystemFile(name="MSDOS.SYS", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
        SystemFile(name="DRVSPACE.BIN", attributes="RHS", required=False),
    ),
    supported_filesystems=("fat12", "fat16", "fat32"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=False,
)
