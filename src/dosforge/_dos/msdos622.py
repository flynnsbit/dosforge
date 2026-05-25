"""MS-DOS 6.22 profile (boot_mode='msdos622').

The final retail MS-DOS release before the MS-DOS 7 Win9x merge.
SYS.COM writes the same OEM string as MS-DOS 5.0 ('MSDOS5.0').
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos622",
    display_name="MS-DOS 6.22",
    oem_string=b"MSDOS5.0",
    system_files=(
        SystemFile(name="IO.SYS", attributes="RHS"),
        SystemFile(name="MSDOS.SYS", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=False,
    pre_dos5=False,
)
