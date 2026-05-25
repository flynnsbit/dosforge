"""IBM PC-DOS baseline profile (boot_mode='pcdos').

Generic IBM PC-DOS 2.x/3.x family.  Pre-DOS-5 layout: IBMBIO.COM +
IBMDOS.COM + COMMAND.COM, no HIMEM, no DOS=HIGH support.  Each
sub-variant (2.0, 3.0, 3.3) ships its own SYS.COM that writes a
slightly different VBR; dosforge extracts the VBR from whichever
SYS.COM is in the install media.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="pcdos",
    display_name="IBM PC-DOS (2.x/3.x)",
    oem_string=b"IBM  3.3",  # most common; sub-variants override
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
