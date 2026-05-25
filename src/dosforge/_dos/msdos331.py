"""MS-DOS 3.31 profile (boot_mode='msdos331').

Microsoft's OEM-only build with partition >32 MB support and the
Compaq-derived BPB.  Robust SYS.COM that installs onto an mformat'd
partition, but we still drive it via emulator for VBR authenticity.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="msdos331",
    display_name="MS-DOS 3.31",
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
