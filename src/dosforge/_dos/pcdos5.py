"""IBM PC-DOS 5.x profile (boot_mode='pcdos5').

IBM's branded counterpart to MS-DOS 5.0 (1991/1992).  Ships
``IBMBIO.COM`` + ``IBMDOS.COM`` instead of MS-DOS 5's
``IO.SYS`` + ``MSDOS.SYS``, but is otherwise the same era and
shares the FAT16-with-HMA/UMB feature set and the FORMAT C: /S
install pipeline.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="pcdos5",
    display_name="IBM PC-DOS 5.x",
    oem_string=b"IBM  5.0",
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
