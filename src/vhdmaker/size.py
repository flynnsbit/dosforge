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

FAT16_MIN_BYTES: Final[int] = 16 * 1024**2
FAT16_MAX_BYTES: Final[int] = 2 * 1024**3
FAT32_MIN_BYTES: Final[int] = 64 * 1024**2
FAT32_MAX_BYTES: Final[int] = 2 * 1024**4
IBM_DOS33_MAX_BYTES: Final[int] = 32 * 1024**2
IBM_DOS50_MAX_BYTES: Final[int] = 504 * 1024**2
FLOPPY_IMG_SIZES_BYTES: Final[set[int]] = {floppy_type.size_bytes for floppy_type in FloppyType}


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
    max_size = IBM_DOS33_MAX_BYTES if dos_version is IBMDOSVersion.DOS33 else IBM_DOS50_MAX_BYTES
    if size_bytes > max_size:
        limit_mb = 32 if dos_version is IBMDOSVersion.DOS33 else 504
        label = "MS-DOS 3.3" if dos_version is IBMDOSVersion.DOS33 else "MS-DOS 5.0"
        raise ValidationError(f"{label} IBM 8088/V20 profile images must not exceed {limit_mb} MiB.")


def validate_size_for_floppy(size_bytes: int, floppy_type: FloppyType) -> None:
    if size_bytes not in FLOPPY_IMG_SIZES_BYTES:
        raise ValidationError("Unsupported floppy IMG size.")
    if size_bytes != floppy_type.size_bytes:
        raise ValidationError(
            f"Floppy type {floppy_type.value} requires size {floppy_type.mkfs_size_kib} KiB."
        )
