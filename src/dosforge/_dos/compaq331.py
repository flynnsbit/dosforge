"""Compaq DOS 3.31 profile (boot_mode='compaq331').

Compaq's licensed MS-DOS 3.31 build for their hardware -- adds >32 MB
partition support via the Compaq-specific BPB.  Robust SYS.COM that
tolerates mformat'd partitions.  Driven via QEMU/DOSBox-X to ensure
the VBR is authentic.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="compaq331",
    display_name="Compaq DOS 3.31",
    oem_string=b"IBM  3.3",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS"),
        SystemFile(name="IBMDOS.COM", attributes="RHS"),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=True,
)
