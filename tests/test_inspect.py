"""Tests for the dosforge.inspect VHD inspector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dosforge.errors import ValidationError
from dosforge.inspect import VhdInfo, inspect_vhd
from dosforge.models import BootMode, DiskFormat


def _write_fat16_vhd(
    path: Path,
    *,
    partition_lba: int = 63,
    partition_sectors: int = 65473,
    partition_type: int = 0x06,
    sectors_per_cluster: int = 4,
    reserved_sectors: int = 1,
    num_fats: int = 2,
    root_entries: int = 512,
    sectors_per_fat_16: int = 256,
    total_sectors: int = 65473,
    oem: bytes = b"MSDOS5.0",
    volume_label: bytes = b"DOSFORGE   ",
    volume_serial: int = 0xDEADBEEF,
) -> None:
    """Synthesize a fixed VHD with one FAT16 partition."""
    data_size = max((partition_lba + partition_sectors) * 512, 32 * 1024 * 1024)
    buf = bytearray(data_size + 512)

    mbr = bytearray(512)
    mbr[446 + 4] = partition_type
    mbr[446 + 8:446 + 12] = partition_lba.to_bytes(4, "little")
    mbr[446 + 12:446 + 16] = partition_sectors.to_bytes(4, "little")
    mbr[510] = 0x55
    mbr[511] = 0xAA
    buf[0:512] = mbr

    bpb_offset = partition_lba * 512
    bpb = bytearray(512)
    bpb[0:3] = b"\xeb\x3c\x90"
    bpb[3:11] = oem
    bpb[11:13] = (512).to_bytes(2, "little")
    bpb[13] = sectors_per_cluster
    bpb[14:16] = reserved_sectors.to_bytes(2, "little")
    bpb[16] = num_fats
    bpb[17:19] = root_entries.to_bytes(2, "little")
    bpb[19:21] = (total_sectors if total_sectors < 65536 else 0).to_bytes(2, "little")
    bpb[22:24] = sectors_per_fat_16.to_bytes(2, "little")
    bpb[32:36] = (total_sectors if total_sectors >= 65536 else 0).to_bytes(4, "little")
    # Volume serial at offset 39 (FAT16 extended BPB)
    bpb[39:43] = volume_serial.to_bytes(4, "little")
    bpb[43:54] = volume_label.ljust(11, b" ")[:11]
    bpb[510] = 0x55
    bpb[511] = 0xAA
    buf[bpb_offset:bpb_offset + 512] = bpb

    footer = bytearray(512)
    footer[0:8] = b"conectix"
    footer[56] = 0x01  # cyl high
    footer[57] = 0x00  # cyl low (256 cyl)
    footer[58] = 16
    footer[59] = 63
    buf[-512:] = footer
    path.write_bytes(bytes(buf))


class TestInspectVhd:
    def test_basic_fat16_msdos5(self, tmp_path: Path) -> None:
        vhd = tmp_path / "msdos.vhd"
        _write_fat16_vhd(vhd)
        info = inspect_vhd(vhd)
        assert info.file_size_bytes == vhd.stat().st_size
        assert info.is_fixed_vhd is True
        assert info.footer_chs == (256, 16, 63)
        assert info.mbr_partition_type == 0x06
        assert info.partition_lba_start == 63
        assert info.partition_offset_bytes == 63 * 512
        assert info.bpb_oem == "MSDOS5.0"
        assert info.cluster_size_bytes == 2048
        assert info.fat_format is DiskFormat.FAT16
        assert info.volume_label == "DOSFORGE"
        assert info.volume_serial_hex == "DEADBEEF"
        assert info.inferred_boot_mode is BootMode.MSDOS622

    def test_inferred_boot_mode_unknown_for_mkfs_oem(self, tmp_path: Path) -> None:
        vhd = tmp_path / "mkfs.vhd"
        _write_fat16_vhd(vhd, oem=b"mkfs.fat")
        info = inspect_vhd(vhd)
        assert info.inferred_boot_mode is None

    @pytest.mark.parametrize(
        "oem, expected_mode",
        [
            (b"IBM  3.3", BootMode.COMPAQ331),
            (b"IBM  7.0", BootMode.PCDOS7),
            (b"FRDOS5.1", BootMode.FREEDOS),
            (b"DRDOS  7", BootMode.DRDOS7),
            (b"MSWIN4.1", BootMode.MSDOS71),
        ],
    )
    def test_oem_table(self, tmp_path: Path, oem: bytes, expected_mode: BootMode) -> None:
        vhd = tmp_path / f"{oem.decode().strip()}.vhd"
        _write_fat16_vhd(vhd, oem=oem)
        info = inspect_vhd(vhd)
        assert info.inferred_boot_mode is expected_mode

    def test_root_file_inference_kernel_sys_means_freedos(self) -> None:
        """When BPB OEM is generic (mformat MTOOLxxxx stamp), fall
        back to root-system-file presence: KERNEL.SYS at root is the
        unique FreeDOS signal."""
        from dosforge.inspect import _infer_boot_mode

        inferred = _infer_boot_mode(
            bpb_oem="MTOO4049",
            fat_format=DiskFormat.FAT32,
            partition_type=0x0C,
            root_system_files=("KERNEL.SYS", "COMMAND.COM"),
        )
        assert inferred is BootMode.FREEDOS

    def test_root_file_inference_io_sys_fat32_means_msdos71(self) -> None:
        """IO.SYS + MSDOS.SYS on FAT32 LBA partition -> MSDOS71
        (OSR2 is the only DOS that boots from FAT32)."""
        from dosforge.inspect import _infer_boot_mode

        inferred = _infer_boot_mode(
            bpb_oem="mkfs.fat",
            fat_format=DiskFormat.FAT32,
            partition_type=0x0C,
            root_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        )
        assert inferred is BootMode.MSDOS71

    def test_root_file_inference_ibmbio_means_compaq331(self) -> None:
        """IBMBIO.COM + IBMDOS.COM at root -> COMPAQ331 family
        (covers Compaq 3.31, DR-DOS 6, PC-DOS 3.x ambiguously)."""
        from dosforge.inspect import _infer_boot_mode

        inferred = _infer_boot_mode(
            bpb_oem="mkfs.fat",
            fat_format=DiskFormat.FAT16,
            partition_type=0x06,
            root_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        )
        assert inferred is BootMode.COMPAQ331

    def test_oem_match_takes_precedence_over_file_fallback(self) -> None:
        """Authentic BPB OEM stamp always wins; file-based fallback
        only runs when OEM doesn't match any known stamp."""
        from dosforge.inspect import _infer_boot_mode

        # IBM 3.3 stamp wins even though IO.SYS is in the root list.
        inferred = _infer_boot_mode(
            bpb_oem="IBM  3.3",
            fat_format=DiskFormat.FAT16,
            partition_type=0x06,
            root_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        )
        assert inferred is BootMode.COMPAQ331

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="does not exist"):
            inspect_vhd(tmp_path / "nope.vhd")

    def test_no_mbr_signature_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "junk.vhd"
        vhd.write_bytes(b"\x00" * 4096)
        with pytest.raises(ValidationError, match="no valid MBR signature"):
            inspect_vhd(vhd)

    def test_to_json_round_trip(self, tmp_path: Path) -> None:
        vhd = tmp_path / "rt.vhd"
        _write_fat16_vhd(vhd)
        info = inspect_vhd(vhd)
        text = info.to_json()
        decoded = json.loads(text)
        assert decoded["bpb_oem"] == "MSDOS5.0"
        assert decoded["fat_format"] == "fat16"
        assert decoded["inferred_boot_mode"] == "msdos622"
        assert decoded["footer_chs"] == [256, 16, 63]
        assert decoded["partition_lba_start"] == 63
        # JSON output is stable (sorted keys) for diff-ability.
        text2 = info.to_json()
        assert text == text2
