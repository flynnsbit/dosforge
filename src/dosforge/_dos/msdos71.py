"""MS-DOS 7.1 profile (boot_mode='msdos71').

MS-DOS 7.10 is the standalone DOS kernel from Windows 98 SE,
distributed as Microsoft 'DOS 7.1' install diskettes.  FAT32-aware.
SYS.COM writes 'IBM  7.1' as the OEM string (no idea why MS picked
the IBM marker; that's what their tool writes).
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos71",
    display_name="MS-DOS 7.1",
    oem_string=b"IBM  7.1",
    system_files=(
        SystemFile(name="IO.SYS", attributes="RHS"),
        SystemFile(name="MSDOS.SYS", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
        SystemFile(name="HIMEM.SYS", attributes="A", required=False),
        SystemFile(name="IFSHLP.SYS", attributes="A", required=False),
    ),
    supported_filesystems=("fat12", "fat16", "fat32"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=False,
    pre_dos5=False,
)
