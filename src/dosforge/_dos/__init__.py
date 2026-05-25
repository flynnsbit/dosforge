"""Per-DOS-version metadata for boot-mode-specific authenticity.

See ``plan.md`` Phase 14 for the authenticity rule this enforces.
"""

from __future__ import annotations

from .base import DosProfile, SystemFile, install_dir_for_media
from . import (
    compaq331,
    fourdos,
    freedos,
    ibm8088,
    msdos33,
    msdos331,
    msdos5,
    msdos622,
    msdos71,
    pcdos,
    pcdos7,
    pcdos71,
)

# Map BootMode.value -> per-mode profile.  Lookup-by-string is
# intentional: keeps this module free of cyclic imports with ``models``.
_PROFILES: dict[str, DosProfile] = {
    "freedos": freedos.PROFILE,
    "msdos33": msdos33.PROFILE,
    "msdos331": msdos331.PROFILE,
    "msdos5": msdos5.PROFILE,
    "msdos622": msdos622.PROFILE,
    "msdos71": msdos71.PROFILE,
    "pcdos": pcdos.PROFILE,
    "pcdos7": pcdos7.PROFILE,
    "pcdos71": pcdos71.PROFILE,
    "ibm8088": ibm8088.PROFILE,
    "compaq331": compaq331.PROFILE,
    "4dos": fourdos.PROFILE,
}


def get_profile(boot_mode_value: str) -> DosProfile:
    """Look up the per-mode profile by ``BootMode.value`` string.

    Raises ``KeyError`` for unknown boot modes.
    """
    return _PROFILES[boot_mode_value]


def has_profile(boot_mode_value: str) -> bool:
    return boot_mode_value in _PROFILES


__all__ = [
    "DosProfile",
    "SystemFile",
    "get_profile",
    "has_profile",
    "install_dir_for_media",
]

