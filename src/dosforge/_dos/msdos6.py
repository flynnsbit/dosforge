"""MS-DOS 6.0 profile (boot_mode='msdos6').

First DoubleSpace MS-DOS release (March 1993).  SYS.COM still
writes the 'MSDOS5.0' OEM string -- Microsoft didn't bump the OEM
stamp to 'MSDOS6.22' until 6.22.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos6",
    display_name="MS-DOS 6.0",
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
