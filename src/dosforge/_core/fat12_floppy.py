"""Pure-Python FAT12 floppy IMG writer.

Produces a FAT12 floppy image that is byte-for-byte compatible with
the BPB invariants asserted by
``dosforge.disk.DiskManager._validate_floppy_img_bpb`` — i.e. the
same shape ``mkfs.fat -F12 -g <h>/<spt> -M <media> -r <root_entries>
-s <spc>`` produces.

The result is suitable for DOS booting after the boot installer
overwrites the boot sector / boot code area.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from ..models import FloppySpec, FloppyType

SECTOR_SIZE = 512
FAT12_FS_TAG = b"FAT12   "
OEM_NAME = b"MSWIN4.1"
JUMP_BOOT = b"\xeb\x3c\x90"
BOOT_SIGNATURE = b"\x55\xaa"


def write_fat12_floppy(
    path: Path,
    *,
    floppy_type: FloppyType,
    volume_label: str | None = None,
    volume_serial: int = 0,
    overwrite: bool = True,
) -> None:
    """Create a FAT12 floppy IMG at ``path``.

    The file is created (or truncated when ``overwrite=True``),
    filled to ``floppy_type.size_bytes`` with 0xF6 (the standard
    "freshly formatted" pad byte that DOS FORMAT writes), the boot
    sector + BPB is laid down, and the FAT[0] / FAT[1] media-
    descriptor entries are initialised. The root directory area is
    zeroed.
    """

    spec = floppy_type.spec
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    payload = _build_image(spec, volume_label=volume_label, volume_serial=volume_serial)
    path.write_bytes(payload)


def _build_image(spec: FloppySpec, *, volume_label: str | None, volume_serial: int) -> bytes:
    total_sectors = spec.total_sectors
    image = bytearray(b"\xf6" * (total_sectors * SECTOR_SIZE))

    boot_sector = _build_boot_sector(spec, volume_label=volume_label, volume_serial=volume_serial)
    image[0:SECTOR_SIZE] = boot_sector

    fat_bytes = _build_fat_table(spec)
    fat_size_bytes = spec.sectors_per_fat * SECTOR_SIZE
    if len(fat_bytes) < fat_size_bytes:
        fat_bytes = fat_bytes + bytes(fat_size_bytes - len(fat_bytes))

    fat1_offset = SECTOR_SIZE  # reserved sectors = 1
    fat2_offset = fat1_offset + fat_size_bytes
    image[fat1_offset : fat1_offset + fat_size_bytes] = fat_bytes
    image[fat2_offset : fat2_offset + fat_size_bytes] = fat_bytes

    root_dir_offset = fat2_offset + fat_size_bytes
    root_dir_bytes = spec.root_entries * 32
    image[root_dir_offset : root_dir_offset + root_dir_bytes] = bytes(root_dir_bytes)

    data_region_offset = root_dir_offset + root_dir_bytes
    # data region is left as 0xF6 fill — DOS FORMAT default pad byte
    _ = data_region_offset

    return bytes(image)


def _build_boot_sector(
    spec: FloppySpec,
    *,
    volume_label: str | None,
    volume_serial: int,
) -> bytes:
    sector = bytearray(SECTOR_SIZE)
    sector[0:3] = JUMP_BOOT
    sector[3:11] = OEM_NAME
    struct.pack_into("<H", sector, 11, SECTOR_SIZE)              # bytes/sector
    sector[13] = spec.sectors_per_cluster
    struct.pack_into("<H", sector, 14, 1)                        # reserved sectors
    sector[16] = 2                                               # FATs
    struct.pack_into("<H", sector, 17, spec.root_entries)
    struct.pack_into("<H", sector, 19, spec.total_sectors)
    sector[21] = spec.media_descriptor
    struct.pack_into("<H", sector, 22, spec.sectors_per_fat)
    struct.pack_into("<H", sector, 24, spec.sectors_per_track)
    struct.pack_into("<H", sector, 26, spec.heads)
    struct.pack_into("<I", sector, 28, 0)                        # hidden sectors
    struct.pack_into("<I", sector, 32, 0)                        # total sectors (32-bit)
    sector[36] = 0x00                                            # drive number (floppy = 0)
    sector[37] = 0x00                                            # reserved
    sector[38] = 0x29                                            # extended boot signature
    struct.pack_into("<I", sector, 39, volume_serial & 0xFFFFFFFF)
    label_bytes = (volume_label or "NO NAME").upper().encode("ascii", "replace")[:11]
    label_padded = label_bytes + b" " * (11 - len(label_bytes))
    sector[43:54] = label_padded
    sector[54:62] = FAT12_FS_TAG
    sector[510:512] = BOOT_SIGNATURE
    return bytes(sector)


def _build_fat_table(spec: FloppySpec) -> bytes:
    """Return the FAT[0] + FAT[1] reserved entries plus padding to
    the end of the first FAT sector. The remaining cluster entries
    are zeroed (free).
    """

    fat = bytearray()
    # FAT12 reserved entries occupy the first 3 bytes (clusters 0
    # and 1, each 12 bits). Cluster 0 = media-descriptor; cluster 1
    # = 0xFFF (end-of-chain marker).
    fat.append(spec.media_descriptor)
    fat.append(0xFF)
    fat.append(0xFF)
    return bytes(fat)


def validate_floppy_bpb(path: Path, floppy_type: FloppyType) -> list[str]:
    """Return a list of BPB mismatches in ``path`` vs ``floppy_type``.

    Mirrors :meth:`DiskManager._validate_floppy_img_bpb` so the
    pure-Python writer can be smoke-tested without instantiating the
    full disk manager.
    """

    spec = floppy_type.spec
    data = path.read_bytes()[:SECTOR_SIZE]
    if len(data) < SECTOR_SIZE:
        return [f"image too small ({len(data)} bytes)"]
    issues: list[str] = []
    if data[510:512] != BOOT_SIGNATURE:
        issues.append("missing 0x55AA boot signature")
    bytes_per_sector = struct.unpack("<H", data[11:13])[0]
    sectors_per_cluster = data[13]
    reserved_sectors = struct.unpack("<H", data[14:16])[0]
    fats = data[16]
    root_entries = struct.unpack("<H", data[17:19])[0]
    total_sectors_16 = struct.unpack("<H", data[19:21])[0]
    media_descriptor = data[21]
    sectors_per_fat = struct.unpack("<H", data[22:24])[0]
    sectors_per_track = struct.unpack("<H", data[24:26])[0]
    heads = struct.unpack("<H", data[26:28])[0]
    hidden_sectors = struct.unpack("<I", data[28:32])[0]
    file_system_tag = data[54:62]
    pairs = (
        ("bytes/sector", SECTOR_SIZE, bytes_per_sector),
        ("sectors/cluster", spec.sectors_per_cluster, sectors_per_cluster),
        ("reserved sectors", 1, reserved_sectors),
        ("FAT count", 2, fats),
        ("root entries", spec.root_entries, root_entries),
        ("total sectors", spec.total_sectors, total_sectors_16),
        ("media descriptor", spec.media_descriptor, media_descriptor),
        ("sectors/FAT", spec.sectors_per_fat, sectors_per_fat),
        ("sectors/track", spec.sectors_per_track, sectors_per_track),
        ("heads", spec.heads, heads),
        ("hidden sectors", 0, hidden_sectors),
    )
    for field, expected, actual in pairs:
        if actual != expected:
            issues.append(f"{field}: expected {expected} got {actual}")
    if file_system_tag != FAT12_FS_TAG:
        issues.append(f"FS tag: expected {FAT12_FS_TAG!r} got {file_system_tag!r}")
    return issues
