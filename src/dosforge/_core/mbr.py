"""Pure-Python single-partition MS-DOS MBR writer.

Replaces ``parted --script mklabel msdos / mkpart primary ...`` on
hosts where parted is unavailable (Windows). The output is a 512-byte
sector 0 containing:

- 446 bytes of zeroed boot code (the boot installer overwrites this
  later with the DOS MBR boot loader);
- a 4-byte disk signature at offset 440;
- a single primary partition entry at offset 446;
- the AA55 boot signature at offsets 510–511.

The partition entry is laid out byte-identically to the MS-DOS spec
that DOS 3.3 / 5.0 / 6.x / MS-DOS 7.x / FreeDOS all expect.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

SECTOR_SIZE = 512
MBR_BOOTSIG = b"\x55\xaa"


@dataclass(frozen=True, slots=True)
class PartitionEntry:
    """A single MBR primary partition entry."""

    bootable: bool
    partition_type: int
    first_lba: int
    sector_count: int
    chs_heads: int
    chs_spt: int

    def encode(self) -> bytes:
        """Encode as a 16-byte MBR partition entry."""

        first_chs = _lba_to_chs(self.first_lba, heads=self.chs_heads, spt=self.chs_spt)
        last_lba = self.first_lba + self.sector_count - 1
        last_chs = _lba_to_chs(last_lba, heads=self.chs_heads, spt=self.chs_spt)
        return (
            bytes([0x80 if self.bootable else 0x00])
            + first_chs
            + bytes([self.partition_type & 0xFF])
            + last_chs
            + struct.pack("<I", self.first_lba)
            + struct.pack("<I", self.sector_count)
        )


def _lba_to_chs(lba: int, *, heads: int, spt: int) -> bytes:
    """Convert ``lba`` to a 3-byte packed CHS triplet.

    Returns ``00 ff ff`` if the LBA cannot be represented in the
    24-bit CHS encoding (cylinder > 1023) — DOS treats that as
    "use LBA reads instead" via INT 13h AH=42.
    """

    if heads <= 0 or spt <= 0:
        return b"\x00\x00\x00"
    cylinder, remainder = divmod(lba, heads * spt)
    head, sector_zero = divmod(remainder, spt)
    sector = sector_zero + 1
    if cylinder > 1023:
        return b"\xfe\xff\xff"
    cyl_low = cylinder & 0xFF
    cyl_high = (cylinder >> 8) & 0x03
    return bytes([head & 0xFF, ((cyl_high << 6) | (sector & 0x3F)), cyl_low])


def write_single_partition_mbr(
    path: Path,
    *,
    partition: PartitionEntry,
    disk_signature: int = 0,
    boot_code: bytes | None = None,
) -> None:
    """Write a single-partition MBR to sector 0 of ``path``.

    ``path`` must already be at least ``(first_lba + sector_count) ×
    512`` bytes long — the partition region itself is not zeroed by
    this function. ``boot_code`` (max 440 bytes) replaces the
    boot-code region; if ``None``, the region is zeroed.
    """

    if boot_code is not None and len(boot_code) > 440:
        raise ValueError(f"boot_code may be at most 440 bytes (got {len(boot_code)})")
    sector = bytearray(SECTOR_SIZE)
    if boot_code:
        sector[: len(boot_code)] = boot_code
    sector[440:444] = struct.pack("<I", disk_signature & 0xFFFFFFFF)
    sector[444:446] = b"\x00\x00"
    sector[446:462] = partition.encode()
    sector[510:512] = MBR_BOOTSIG
    with path.open("r+b") as handle:
        handle.seek(0, os.SEEK_SET)
        handle.write(bytes(sector))


def read_partition_entry(path: Path, *, slot: int = 0) -> PartitionEntry | None:
    """Decode a primary partition entry from sector 0 of ``path``.

    Returns ``None`` if the slot is empty (all zeros). ``slot`` must
    be 0..3. The CHS heads/spt fields are best-effort from the entry
    itself; callers that need a specific geometry should validate
    elsewhere.
    """

    if not 0 <= slot < 4:
        raise ValueError(f"slot must be 0..3 (got {slot})")
    with path.open("rb") as handle:
        sector = handle.read(SECTOR_SIZE)
    if len(sector) < SECTOR_SIZE or sector[510:512] != MBR_BOOTSIG:
        return None
    offset = 446 + 16 * slot
    entry = sector[offset : offset + 16]
    if entry == bytes(16):
        return None
    bootable = entry[0] == 0x80
    head = entry[1]
    sector_cyl = entry[2]
    cyl_low = entry[3]
    partition_type = entry[4]
    first_lba = struct.unpack("<I", entry[8:12])[0]
    count = struct.unpack("<I", entry[12:16])[0]
    cylinder = ((sector_cyl & 0xC0) << 2) | cyl_low
    sector_one_based = sector_cyl & 0x3F
    # Best-effort heads/spt: rely on caller-provided geometry usually,
    # but reconstruct what we can from the encoded CHS.
    spt = max(sector_one_based, 1)
    heads = max(head + 1, 1)
    _ = cylinder  # decoded for symmetry; not surfaced via the entry
    return PartitionEntry(
        bootable=bootable,
        partition_type=partition_type,
        first_lba=first_lba,
        sector_count=count,
        chs_heads=heads,
        chs_spt=spt,
    )
