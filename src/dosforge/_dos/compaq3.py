"""Microsoft MS-DOS 3.00 [Compaq OEM] profile (boot_mode='compaq3').

The 1985 Compaq-branded MS-DOS 3.00 release.  DOS 3.0 BPB (with
hidden_sectors) so HDD boot works on standard MFM / IDE BIOS.
FAT12 only -- FAT16 wasn't added until DOS 3.10.  Caps at ~16 MiB.
Uses IBM-style system file naming (Compaq adopted IBMBIO / IBMDOS
for the 3.0 release).
"""

from __future__ import annotations

from .base import DosProfile, SystemFile

PROFILE = DosProfile(
    boot_mode="compaq3",
    display_name="Compaq MS-DOS 3.00",
    oem_string=b"IBM  3.3",
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
