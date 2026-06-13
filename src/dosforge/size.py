"""Size parsing and DOS-oriented FAT compatibility validation."""

from __future__ import annotations

import re
from typing import Final

from .errors import ValidationError
from .models import DiskFormat, FloppyType, IBMDOSVersion

_SIZE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(\d+)\s*([kmgt]?i?b?)?\s*$", re.IGNORECASE)
_SIZE_FACTORS: Final[dict[str, int]] = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}

FAT12_MIN_BYTES: Final[int] = 360 * 1024  # smallest standard floppy size
FAT12_MAX_BYTES: Final[int] = 32 * 1024**2  # FAT12 hard cap (4084 clusters * max clu sz)
FAT16_MIN_BYTES: Final[int] = 16 * 1024**2
FAT16_MAX_BYTES: Final[int] = 2 * 1024**3
FAT32_MIN_BYTES: Final[int] = 64 * 1024**2
FAT32_MAX_BYTES: Final[int] = 2 * 1024**4
IBM_DOS33_MAX_BYTES: Final[int] = 32 * 1024**2
IBM_DOS50_MAX_BYTES: Final[int] = 504 * 1024**2
# Microsoft-branded MS-DOS 3.31 is capped at 32 MiB (FAT16 short,
# partition type 0x04). The Compaq OEM version of DOS 3.31 lifts the
# cap to ~504 MiB with FAT16B (partition type 0x06) — see
# COMPAQ331_MAX_BYTES.
MSDOS331_MAX_BYTES: Final[int] = 32 * 1024**2
COMPAQ331_MAX_BYTES: Final[int] = 504 * 1024**2
FLOPPY_IMG_SIZES_BYTES: Final[set[int]] = {floppy_type.size_bytes for floppy_type in FloppyType}

# A "cylinder" in the BIOS-friendly canonical ATA geometry dosforge writes
# into VHD footers (16 heads × 63 sectors-per-track × 512 bytes per sector).
# Used to align disk sizes so footer CHS exactly maps to total_sectors.
NORMAL_CHS_CYLINDER_BYTES: Final[int] = 16 * 63 * 512  # 516096


def align_size_for_normal_chs(
    size_bytes: int,
    *,
    min_bytes: int | None = None,
    max_bytes: int | None = None,
) -> int:
    """Align ``size_bytes`` to a multiple of ``NORMAL_CHS_CYLINDER_BYTES``.

    Prefers rounding up; falls back to rounding down when the ceiling would
    exceed ``max_bytes`` (so DOS-3.3 / FAT16 / FAT32 caps remain honored).
    Ensures the result is at least ``min_bytes`` when supplied.
    """
    step = NORMAL_CHS_CYLINDER_BYTES
    if size_bytes <= 0:
        return step
    ceil_size = ((size_bytes + step - 1) // step) * step
    if max_bytes is not None and ceil_size > max_bytes:
        floor_size = (max_bytes // step) * step
        if floor_size > 0:
            ceil_size = floor_size
    if min_bytes is not None and ceil_size < min_bytes:
        ceil_size = ((min_bytes + step - 1) // step) * step
    return ceil_size


def parse_size(value: str) -> int:
    match = _SIZE_PATTERN.match(value)
    if not match:
        raise ValidationError(
            "Invalid size format. Use values such as 512M, 1G, or 2147483648."
        )

    amount_text, suffix_text = match.groups()
    suffix = (suffix_text or "").lower()
    if suffix not in _SIZE_FACTORS:
        raise ValidationError(f"Unsupported size suffix: {suffix_text!r}")

    amount = int(amount_text)
    if amount <= 0:
        raise ValidationError("Size must be greater than zero.")
    return amount * _SIZE_FACTORS[suffix]


def normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = label.strip().upper()
    if not cleaned:
        return None
    if len(cleaned) > 11:
        raise ValidationError("FAT volume labels must be at most 11 characters.")
    if not re.fullmatch(r"[A-Z0-9 _-]+", cleaned):
        raise ValidationError("Volume label can only contain A-Z, 0-9, space, underscore, and dash.")
    return cleaned


def validate_size_for_format(size_bytes: int, disk_format: DiskFormat) -> None:
    if disk_format is DiskFormat.FAT12:
        if size_bytes < FAT12_MIN_BYTES:
            raise ValidationError("FAT12 images must be at least 360 KiB.")
        if size_bytes > FAT12_MAX_BYTES:
            raise ValidationError(
                "FAT12 partitions are capped at 32 MiB. Use FAT16 for larger drives."
            )
        return

    if disk_format is DiskFormat.FAT16:
        if size_bytes < FAT16_MIN_BYTES:
            raise ValidationError("FAT16 images must be at least 16 MiB.")
        if size_bytes > FAT16_MAX_BYTES:
            raise ValidationError("FAT16 DOS-compatible images must not exceed 2 GiB.")
        return

    if size_bytes < FAT32_MIN_BYTES:
        raise ValidationError("FAT32 images should be at least 64 MiB for DOS compatibility.")
    if size_bytes > FAT32_MAX_BYTES:
        raise ValidationError("FAT32 images larger than 2 TiB are not supported.")


def validate_size_for_ibm_dos(size_bytes: int, dos_version: IBMDOSVersion) -> None:
    """4-way IBM 8088 profile size validation.

    PCDOS3 -> 16 MiB (FAT12-only, 1984 DOS 3.0 partition cap).
    MSDOS33 -> 32 MiB (DOS 3.3 FAT16 uint16 sector cap).
    MSDOS5 / PCDOS5 -> 504 MiB (FAT16 max under the IBM 8088 profile).
    """
    max_size = dos_version.max_size_bytes
    if size_bytes <= max_size:
        return
    label_map = {
        IBMDOSVersion.MSDOS33: "MS-DOS 3.3",
        IBMDOSVersion.PCDOS3: "IBM PC-DOS 3.x",
        IBMDOSVersion.MSDOS5: "MS-DOS 5.0",
        IBMDOSVersion.PCDOS5: "IBM PC-DOS 5.x",
    }
    label = label_map.get(dos_version, "MS-DOS 3.3")
    limit_mb = max_size // (1024 * 1024)
    raise ValidationError(
        f"{label} IBM 8088/V20 profile images must not exceed {limit_mb} MiB."
    )


def validate_size_for_floppy(size_bytes: int, floppy_type: FloppyType) -> None:
    if size_bytes not in FLOPPY_IMG_SIZES_BYTES:
        raise ValidationError("Unsupported floppy IMG size.")
    if size_bytes != floppy_type.size_bytes:
        raise ValidationError(
            f"Floppy type {floppy_type.value} requires size {floppy_type.mkfs_size_kib} KiB."
        )
