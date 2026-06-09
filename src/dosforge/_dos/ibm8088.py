"""IBM PC 8088/V20 vintage profile (boot_mode='ibm8088').

This boot mode targets 8088-era hardware (~1981-1986) and dispatches
based on ``--ibm-dos-version``:
  - dos33: behaves like MS-DOS 3.3 (max 32 MB partition)
  - dos50: behaves like ``msdos5`` (max ~504 MB partition)

The asset directory follows a per-version layout under
``dosassets/ibm8088/<version>/``.

For authenticity-rule purposes, this module just declares the umbrella;
actual VBR / MBR / system-file extraction is delegated to the per-version
profile at install time (selected via the IBMDOSVersion enum).
"""

from __future__ import annotations

from .base import DosProfile, SystemFile
from . import msdos33 as _msdos33, msdos5 as _msdos5

# Umbrella profile -- placeholder fields are overridden at install time
# based on --ibm-dos-version.  Kept here to keep the module list
# uniform across boot modes.
PROFILE = DosProfile(
    boot_mode="ibm8088",
    display_name="IBM PC 8088 (DOS 3.3 / DOS 5.0)",
    oem_string=b"IBM  3.3",
    system_files=(
        SystemFile(name="IBMBIO.COM", attributes="RHS", required=False),
        SystemFile(name="IBMDOS.COM", attributes="RHS", required=False),
        SystemFile(name="IO.SYS", attributes="RHS", required=False),
        SystemFile(name="MSDOS.SYS", attributes="RHS", required=False),
        SystemFile(name="COMMAND.COM", attributes="A"),
    ),
    supported_filesystems=("fat12", "fat16"),
    expects_dos_dir=True,
    install_dir_name="DOS",
    requires_emulator_for_sys_install=True,
    pre_dos5=True,
)


def resolve_inner_profile(version: str) -> DosProfile:
    """Pick the actual per-version profile based on --ibm-dos-version."""
    if version == "dos33":
        return _msdos33.PROFILE
    if version == "dos50":
        return _msdos5.PROFILE
    raise ValueError(f"Unknown ibm-dos-version: {version!r}")
