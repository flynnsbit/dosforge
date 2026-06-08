"""IBM PC-DOS 2000 profile (boot_mode='pcdos2000').

PC-DOS 2000 = PC-DOS 7.00 rebranded for the Y2K cycle.  Same VBR +
IBMBIO / IBMDOS dates as PCDOS7, but distributed as a 6-floppy
WinWorldPC set (disk01.img..disk06.img) rather than the
LOADDSKF-compressed 144US1.DSK PCDOS7 ships with.  Install
pipeline matches PCDOS7's FORMAT C: /S.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="pcdos2000",
    display_name="IBM PC-DOS 2000",
    oem_string=b"IBM  7.0",
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
