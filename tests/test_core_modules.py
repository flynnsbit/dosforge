"""Tests for the pure-Python core building blocks."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess

import pytest

from dosforge._core import fat12_floppy, mbr, vhd_footer
from dosforge._platform import get_backend
from dosforge.models import FloppyType


# -- VHD footer -----------------------------------------------------------


def _resolve_qemu_img() -> str | None:
    """Locate ``qemu-img`` cross-platform.

    Prefers the platform backend's resolver (so on Windows the bundled
    ``vendor/windows/bin/qemu-img.exe`` is found), falls back to PATH.
    """

    candidate = get_backend().tool_path("qemu-img")
    if candidate and candidate != "qemu-img" and os.path.exists(candidate):
        return candidate
    return shutil.which("qemu-img")


def _make_fixed_vhd(tmp_path, *, size_bytes: int = 10 * 1024 * 1024):
    """Allocate a fixed VHD via qemu-img (skipped if not available)."""

    qemu_img = _resolve_qemu_img()
    if qemu_img is None:
        pytest.skip("qemu-img not available")
    path = tmp_path / "fixture.vhd"
    subprocess.run(
        [qemu_img, "create", "-f", "vpc", "-o", "subformat=fixed", str(path), str(size_bytes)],
        check=True,
        capture_output=True,
    )
    return path


def test_read_footer_returns_geometry(tmp_path):
    path = _make_fixed_vhd(tmp_path)
    footer = vhd_footer.read_footer(path)
    assert footer.cylinders > 0
    assert footer.heads in (4, 8, 16)
    assert footer.sectors_per_track in (17, 63)
    assert footer.current_size_bytes > 0


def test_write_footer_chs_updates_geometry_and_checksum(tmp_path):
    path = _make_fixed_vhd(tmp_path)
    vhd_footer.write_footer_chs(path, cylinders=306, heads=4, sectors_per_track=17)
    refreshed = vhd_footer.read_footer(path)
    assert refreshed.cylinders == 306
    assert refreshed.heads == 4
    assert refreshed.sectors_per_track == 17


def test_normalize_footer_to_ata_sets_16_heads_63_spt(tmp_path):
    path = _make_fixed_vhd(tmp_path, size_bytes=64 * 1024 * 1024)
    vhd_footer.normalize_footer_to_ata(path)
    refreshed = vhd_footer.read_footer(path)
    assert refreshed.heads == 16
    assert refreshed.sectors_per_track == 63


def test_decode_footer_rejects_missing_cookie():
    bad = b"\x00" * 512
    with pytest.raises(ValueError, match="conectix"):
        vhd_footer.decode_footer(bad)


# -- MBR ------------------------------------------------------------------


def test_partition_entry_encodes_to_16_bytes():
    entry = mbr.PartitionEntry(
        bootable=True,
        partition_type=0x06,
        first_lba=63,
        sector_count=20559,
        chs_heads=4,
        chs_spt=17,
    )
    encoded = entry.encode()
    assert len(encoded) == 16
    assert encoded[0] == 0x80
    assert encoded[4] == 0x06
    assert struct.unpack("<I", encoded[8:12])[0] == 63
    assert struct.unpack("<I", encoded[12:16])[0] == 20559


def test_write_single_partition_mbr_round_trip(tmp_path):
    path = tmp_path / "disk.img"
    path.write_bytes(b"\x00" * (10 * 1024 * 1024))
    entry = mbr.PartitionEntry(
        bootable=True,
        partition_type=0x04,
        first_lba=63,
        sector_count=20337,
        chs_heads=4,
        chs_spt=17,
    )
    mbr.write_single_partition_mbr(path, partition=entry, disk_signature=0xDEADBEEF)
    sector0 = path.read_bytes()[:512]
    assert sector0[510:512] == b"\x55\xaa"
    assert struct.unpack("<I", sector0[440:444])[0] == 0xDEADBEEF
    decoded = mbr.read_partition_entry(path, slot=0)
    assert decoded is not None
    assert decoded.bootable is True
    assert decoded.partition_type == 0x04
    assert decoded.first_lba == 63
    assert decoded.sector_count == 20337


def test_read_partition_entry_returns_none_for_empty_slot(tmp_path):
    path = tmp_path / "disk.img"
    path.write_bytes(b"\x00" * (10 * 1024 * 1024))
    entry = mbr.PartitionEntry(
        bootable=False, partition_type=0x06, first_lba=63, sector_count=100, chs_heads=4, chs_spt=17,
    )
    mbr.write_single_partition_mbr(path, partition=entry)
    assert mbr.read_partition_entry(path, slot=1) is None


def test_partition_entry_uses_high_chs_when_cylinder_overflows():
    # 16 heads × 63 spt × 1024 cylinders = 1,032,192 sectors; LBAs
    # past that get the 0xFE/FF/FF marker per the MBR spec.
    entry = mbr.PartitionEntry(
        bootable=False,
        partition_type=0x06,
        first_lba=2_000_000,
        sector_count=1024,
        chs_heads=16,
        chs_spt=63,
    )
    encoded = entry.encode()
    assert encoded[1:4] == b"\xfe\xff\xff"


def test_write_mbr_rejects_oversized_boot_code(tmp_path):
    path = tmp_path / "disk.img"
    path.write_bytes(b"\x00" * 4096)
    entry = mbr.PartitionEntry(
        bootable=False, partition_type=0x06, first_lba=1, sector_count=1, chs_heads=1, chs_spt=1,
    )
    with pytest.raises(ValueError, match="boot_code"):
        mbr.write_single_partition_mbr(
            path, partition=entry, boot_code=b"\x00" * 441,
        )


# -- FAT12 floppy ---------------------------------------------------------


@pytest.mark.parametrize(
    "floppy_type",
    [FloppyType.F360K, FloppyType.F720K, FloppyType.F1200K, FloppyType.F1440K, FloppyType.F2880K],
)
def test_write_fat12_floppy_passes_bpb_validation(tmp_path, floppy_type):
    path = tmp_path / f"{floppy_type.value}.img"
    fat12_floppy.write_fat12_floppy(path, floppy_type=floppy_type, volume_label="DOSFORGE")
    assert path.stat().st_size == floppy_type.size_bytes
    issues = fat12_floppy.validate_floppy_bpb(path, floppy_type)
    assert issues == [], f"BPB mismatches for {floppy_type.value}: {issues}"


def test_fat12_floppy_writes_media_descriptor_at_fat_offsets(tmp_path):
    floppy_type = FloppyType.F1440K
    path = tmp_path / "1.44m.img"
    fat12_floppy.write_fat12_floppy(path, floppy_type=floppy_type)
    data = path.read_bytes()
    spec = floppy_type.spec
    fat1_offset = 512
    fat2_offset = fat1_offset + spec.sectors_per_fat * 512
    assert data[fat1_offset] == spec.media_descriptor
    assert data[fat1_offset + 1 : fat1_offset + 3] == b"\xff\xff"
    assert data[fat2_offset] == spec.media_descriptor
    assert data[fat2_offset + 1 : fat2_offset + 3] == b"\xff\xff"


def test_fat12_floppy_data_region_padded_with_format_pad_byte(tmp_path):
    floppy_type = FloppyType.F1440K
    path = tmp_path / "1.44m.img"
    fat12_floppy.write_fat12_floppy(path, floppy_type=floppy_type)
    data = path.read_bytes()
    # The last 8 sectors of a 1.44 MB floppy are well inside the data
    # region — they should all be the DOS FORMAT 0xF6 pad byte.
    tail = data[-8 * 512 :]
    assert tail == b"\xf6" * len(tail)
