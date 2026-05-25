"""MS-DOS 3.30 profile (boot_mode='msdos33').

MS-DOS 3.30 has a strict BPB layout (mformat's defaults don't match
what SYS.COM expects), so dosforge runs the install in QEMU or
DOSBox-X driving DOS's own FORMAT C: /S.  The system files land via
the install media's SYS step, not via dosforge.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos33",
    display_name="MS-DOS 3.30",
    oem_string=b"MSDOS3.3",
    system_files=(
        SystemFile(name="IO.SYS", attributes="RHS"),
        SystemFile(name="MSDOS.SYS", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=True,
)
