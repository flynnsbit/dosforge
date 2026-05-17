"""VPC / Microsoft "fixed" VHD footer helpers.

The VHD footer is the last 512 bytes of a fixed VHD file. It contains
the file's apparent geometry (CHS) and a checksum over the rest of
the footer. Patching the CHS triplet is how dosforge persuades 86Box
and other AT-class BIOSes to lock onto a specific BIOS disk type.

This module is pure-Python and platform-independent.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

VHD_FOOTER_SIZE = 512
VHD_COOKIE = b"conectix"


@dataclass(frozen=True, slots=True)
class VHDFooter:
    """A decoded VHD footer (fixed-format subset we care about)."""

    cylinders: int
    heads: int
    sectors_per_track: int
    current_size_bytes: int
    original_size_bytes: int

    @property
    def total_sectors(self) -> int:
        return self.current_size_bytes // 512


def read_footer(path: Path) -> VHDFooter:
    """Decode the VHD footer of ``path``.

    Raises :class:`ValueError` if the file is too short or lacks the
    ``conectix`` cookie.
    """

    with path.open("rb") as handle:
        handle.seek(-VHD_FOOTER_SIZE, os.SEEK_END)
        footer = handle.read(VHD_FOOTER_SIZE)
    return decode_footer(footer)


def decode_footer(footer: bytes) -> VHDFooter:
    if len(footer) != VHD_FOOTER_SIZE:
        raise ValueError(f"VHD footer must be {VHD_FOOTER_SIZE} bytes (got {len(footer)})")
    if footer[:8] != VHD_COOKIE:
        raise ValueError("Not a VHD footer (missing 'conectix' cookie)")
    original_size = struct.unpack(">Q", footer[40:48])[0]
    current_size = struct.unpack(">Q", footer[48:56])[0]
    cylinders = struct.unpack(">H", footer[56:58])[0]
    heads = footer[58]
    spt = footer[59]
    return VHDFooter(
        cylinders=cylinders,
        heads=heads,
        sectors_per_track=spt,
        current_size_bytes=current_size,
        original_size_bytes=original_size,
    )


def write_footer_chs(
    path: Path,
    *,
    cylinders: int,
    heads: int,
    sectors_per_track: int,
) -> None:
    """Overwrite the CHS triplet + checksum in the footer of ``path``.

    No-ops silently if the file does not have a valid VHD footer
    (matches the existing Linux behavior).
    """

    try:
        with path.open("r+b") as handle:
            handle.seek(-VHD_FOOTER_SIZE, os.SEEK_END)
            footer = bytearray(handle.read(VHD_FOOTER_SIZE))
            if len(footer) != VHD_FOOTER_SIZE or footer[:8] != VHD_COOKIE:
                return
            _write_footer_chs_in_place(
                handle, footer,
                cylinders=cylinders,
                heads=heads,
                sectors_per_track=sectors_per_track,
            )
    except OSError:
        return


def normalize_footer_to_ata(path: Path) -> None:
    """Rewrite ``path``'s footer CHS to 16h/63s canonical AT geometry.

    This is the "make 86Box auto-detect pick NORMAL not LARGE" code
    path; preserved for parity with the existing Linux behavior.
    """

    try:
        with path.open("r+b") as handle:
            handle.seek(-VHD_FOOTER_SIZE, os.SEEK_END)
            footer = bytearray(handle.read(VHD_FOOTER_SIZE))
            if len(footer) != VHD_FOOTER_SIZE or footer[:8] != VHD_COOKIE:
                return
            current_size_bytes = struct.unpack(">Q", footer[48:56])[0]
            total_sectors = current_size_bytes // 512
            if total_sectors <= 0:
                return
            heads = 16
            spt = 63
            cylinders = total_sectors // (heads * spt)
            if cylinders <= 0:
                return
            _write_footer_chs_in_place(
                handle, footer,
                cylinders=cylinders,
                heads=heads,
                sectors_per_track=spt,
            )
    except OSError:
        return


def _write_footer_chs_in_place(
    handle: BinaryIO,
    footer: bytearray,
    *,
    cylinders: int,
    heads: int,
    sectors_per_track: int,
) -> None:
    footer[56:58] = struct.pack(">H", min(max(cylinders, 1), 0xFFFF))
    footer[58] = heads & 0xFF
    footer[59] = sectors_per_track & 0xFF
    footer[64:68] = b"\x00\x00\x00\x00"
    checksum = (~sum(footer)) & 0xFFFFFFFF
    footer[64:68] = struct.pack(">I", checksum)
    handle.seek(-VHD_FOOTER_SIZE, os.SEEK_END)
    handle.write(bytes(footer))
