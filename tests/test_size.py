from __future__ import annotations

import pytest

from vhdmaker.errors import ValidationError
from vhdmaker.models import DiskFormat, FloppyType, IBMDOSVersion
from vhdmaker.size import (
    FAT16_MAX_BYTES,
    FAT16_MIN_BYTES,
    FAT32_MIN_BYTES,
    IBM_DOS33_MAX_BYTES,
    IBM_DOS50_MAX_BYTES,
    normalize_label,
    parse_size,
    validate_size_for_floppy,
    validate_size_for_ibm_dos,
    validate_size_for_format,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("512M", 512 * 1024 * 1024),
        ("1G", 1024 * 1024 * 1024),
        ("4096", 4096),
        ("2GiB", 2 * 1024 * 1024 * 1024),
        ("64mb", 64 * 1024 * 1024),
    ],
)
def test_parse_size_valid(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "10PB", "-1G", "0"])
def test_parse_size_invalid(text: str) -> None:
    with pytest.raises(ValidationError):
        parse_size(text)


def test_validate_size_for_fat16_limits() -> None:
    validate_size_for_format(FAT16_MIN_BYTES, DiskFormat.FAT16)
    validate_size_for_format(FAT16_MAX_BYTES, DiskFormat.FAT16)
    with pytest.raises(ValidationError):
        validate_size_for_format(FAT16_MIN_BYTES - 1, DiskFormat.FAT16)
    with pytest.raises(ValidationError):
        validate_size_for_format(FAT16_MAX_BYTES + 1, DiskFormat.FAT16)


def test_validate_size_for_fat32_lower_limit() -> None:
    validate_size_for_format(FAT32_MIN_BYTES, DiskFormat.FAT32)
    with pytest.raises(ValidationError):
        validate_size_for_format(FAT32_MIN_BYTES - 1, DiskFormat.FAT32)


def test_validate_size_for_ibm_dos_limits() -> None:
    validate_size_for_ibm_dos(IBM_DOS33_MAX_BYTES, IBMDOSVersion.DOS33)
    validate_size_for_ibm_dos(IBM_DOS50_MAX_BYTES, IBMDOSVersion.DOS50)
    with pytest.raises(ValidationError, match="MS-DOS 3.3"):
        validate_size_for_ibm_dos(IBM_DOS33_MAX_BYTES + 1, IBMDOSVersion.DOS33)
    with pytest.raises(ValidationError, match="MS-DOS 5.0"):
        validate_size_for_ibm_dos(IBM_DOS50_MAX_BYTES + 1, IBMDOSVersion.DOS50)


def test_validate_size_for_floppy_type() -> None:
    validate_size_for_floppy(FloppyType.F1440K.size_bytes, FloppyType.F1440K)
    validate_size_for_floppy(FloppyType.F2880K.size_bytes, FloppyType.F2880K)
    with pytest.raises(ValidationError, match="requires size"):
        validate_size_for_floppy(FloppyType.F1200K.size_bytes, FloppyType.F1440K)
    with pytest.raises(ValidationError, match="Unsupported floppy IMG size"):
        validate_size_for_floppy(12345, FloppyType.F1440K)


def test_normalize_label() -> None:
    assert normalize_label("disk_one") == "DISK_ONE"
    assert normalize_label("  ") is None
    with pytest.raises(ValidationError):
        normalize_label("this-label-is-way-too-long")
    with pytest.raises(ValidationError):
        normalize_label("bad*chars")
