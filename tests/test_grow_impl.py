"""Unit tests for the dosforge.grow internal implementation.

Covers the surface-level helpers (snapshot, cluster-band check)
without spinning up a real VHD build.  End-to-end grow runs are
exercised manually via the CLI smoke-test in the dev workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge._grow_impl import (
    _expected_cluster_size_for_new_size,
    _snapshot_vhd,
    _validate_cluster_band_match,
)
from dosforge.errors import ValidationError
from dosforge.models import DiskFormat


def _write_fake_vhd_with_partition(
    path: Path,
    *,
    partition_lba: int = 63,
    partition_sectors: int = 65473,
    partition_type: int = 0x06,
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 4,
    reserved_sectors: int = 1,
    num_fats: int = 2,
    root_entries: int = 512,
    sectors_per_fat_16: int = 256,
    sectors_per_fat_32: int = 0,
    total_sectors_16: int = 65473,
    total_sectors_32: int = 0,
) -> None:
    """Synthesize a minimal fixed VHD with one FAT16 partition."""
    # Compute total file size: data area + 512-byte footer.
    data_size = max((partition_lba + partition_sectors) * 512, 32 * 1024 * 1024)
    buf = bytearray(data_size + 512)

    # MBR signature + partition entry
    mbr = bytearray(512)
    mbr[446 + 4] = partition_type
    mbr[446 + 8:446 + 12] = partition_lba.to_bytes(4, "little")
    mbr[446 + 12:446 + 16] = partition_sectors.to_bytes(4, "little")
    mbr[510] = 0x55
    mbr[511] = 0xAA
    buf[0:512] = mbr

    # BPB at partition start
    bpb_offset = partition_lba * 512
    bpb = bytearray(512)
    bpb[0:3] = b"\xeb\x3c\x90"
    bpb[3:11] = b"MSDOS5.0"
    bpb[11:13] = bytes_per_sector.to_bytes(2, "little")
    bpb[13] = sectors_per_cluster
    bpb[14:16] = reserved_sectors.to_bytes(2, "little")
    bpb[16] = num_fats
    bpb[17:19] = root_entries.to_bytes(2, "little")
    bpb[19:21] = total_sectors_16.to_bytes(2, "little")
    bpb[22:24] = sectors_per_fat_16.to_bytes(2, "little")
    bpb[32:36] = total_sectors_32.to_bytes(4, "little")
    bpb[36:40] = sectors_per_fat_32.to_bytes(4, "little")
    bpb[510] = 0x55
    bpb[511] = 0xAA
    buf[bpb_offset:bpb_offset + 512] = bpb

    # VHD footer: 'conectix' magic at offset 0 of the last 512 bytes
    footer = bytearray(512)
    footer[0:8] = b"conectix"
    buf[-512:] = footer

    path.write_bytes(bytes(buf))


class TestSnapshotVhd:
    def test_reads_fat16_geometry(self, tmp_path: Path) -> None:
        vhd = tmp_path / "exo.vhd"
        _write_fake_vhd_with_partition(vhd)
        snap = _snapshot_vhd(vhd)
        assert snap.partition_lba_start == 63
        assert snap.partition_offset_bytes == 63 * 512
        assert snap.partition_type == 0x06
        assert snap.bytes_per_sector == 512
        assert snap.sectors_per_cluster == 4
        assert snap.cluster_size_bytes == 2048
        assert snap.fat_format is DiskFormat.FAT16

    def test_classifies_fat32_by_cluster_count(self, tmp_path: Path) -> None:
        vhd = tmp_path / "big.vhd"
        _write_fake_vhd_with_partition(
            vhd,
            partition_lba=2048,
            partition_sectors=2 * 1024 * 1024,  # 1 GiB
            partition_type=0x0C,
            sectors_per_cluster=8,
            reserved_sectors=32,
            num_fats=2,
            root_entries=0,             # FAT32: root in data area
            sectors_per_fat_16=0,
            sectors_per_fat_32=4096,
            total_sectors_16=0,
            total_sectors_32=2 * 1024 * 1024,
        )
        snap = _snapshot_vhd(vhd)
        assert snap.fat_format is DiskFormat.FAT32
        assert snap.cluster_size_bytes == 4096

    def test_missing_partition_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "empty.vhd"
        _write_fake_vhd_with_partition(vhd, partition_lba=0, partition_sectors=0)
        with pytest.raises(ValidationError, match="no first MBR partition"):
            _snapshot_vhd(vhd)

    def test_missing_mbr_signature_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "junk.vhd"
        vhd.write_bytes(b"\x00" * 4096)
        with pytest.raises(ValidationError, match="no valid MBR signature"):
            _snapshot_vhd(vhd)


class TestExpectedClusterSize:
    @pytest.mark.parametrize(
        "size, fmt, cluster",
        [
            (16 * 1024**2, DiskFormat.FAT16, 2048),
            (128 * 1024**2, DiskFormat.FAT16, 2048),
            (200 * 1024**2, DiskFormat.FAT16, 4096),
            (1 * 1024**3, DiskFormat.FAT16, 16384),
            (2 * 1024**3, DiskFormat.FAT16, 32768),
            (1 * 1024**3, DiskFormat.FAT32, 4096),
            (16 * 1024**3, DiskFormat.FAT32, 8192),
        ],
    )
    def test_mformat_band_table(self, size: int, fmt: DiskFormat, cluster: int) -> None:
        assert _expected_cluster_size_for_new_size(size, fmt) == cluster


class TestValidateClusterBand:
    def test_same_band_passes(self, tmp_path: Path) -> None:
        vhd = tmp_path / "exo.vhd"
        _write_fake_vhd_with_partition(vhd)  # 2048-byte clusters
        snap = _snapshot_vhd(vhd)
        # Old: 32 MiB, 2 KiB clusters. New: 128 MiB still in same band.
        _validate_cluster_band_match(snap, 128 * 1024 * 1024)

    def test_different_band_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "exo.vhd"
        _write_fake_vhd_with_partition(vhd)
        snap = _snapshot_vhd(vhd)
        # Grow from 32 MiB to 256 MiB crosses the 2KiB→4KiB band.
        with pytest.raises(ValidationError, match="cluster size"):
            _validate_cluster_band_match(snap, 256 * 1024 * 1024)
