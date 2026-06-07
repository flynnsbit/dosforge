"""Tests for FAT12 boot-template resolution.

The resolver used to fall through to ``BOOTSECT_FAT32.BIN`` for any
non-FAT16 ``DiskFormat``; combined with the CLI defaulting IMG floppies
to ``DiskFormat.FAT16``, FAT12 floppies got the FAT16 boot loader whose
loader code walks FAT entries as 16-bit, silently failing to locate
KERNEL.SYS on a 12-bit FAT. These tests pin the corrected behavior:

  1. For ``MediaType.IMG`` the resolver always treats the filesystem as
     FAT12 regardless of ``request.disk_format``.
  2. For an explicit FAT12 disk format the resolver prefers
     ``BOOTSECT_FAT12.BIN`` from the assets dir, then falls back to the
     built-in FreeDOS FAT12 boot sector materialized in the cache.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from dosforge.boot import (
    _BUILTIN_FAT12_BOOT_SECTOR_B64,
    BootAssetResolver,
)
from dosforge.commands import CommandRunner
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    MediaType,
)


_BUILTIN_FAT12_BOOT_SECTOR = base64.b64decode(_BUILTIN_FAT12_BOOT_SECTOR_B64)


def _make_resolver(tmp_path: Path) -> BootAssetResolver:
    return BootAssetResolver(
        runner=CommandRunner(sudo_required=False),
        cache_root=tmp_path / "cache",
    )


def _make_floppy_request(target_path: Path) -> CreateRequest:
    return CreateRequest(
        path=target_path,
        size_bytes=1474560,
        media_type=MediaType.IMG,
        # CLI hard-codes FAT16 for IMG, even though the on-disk FS is FAT12.
        disk_format=DiskFormat.FAT16,
        floppy_type=FloppyType.F1440K,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
    )


def test_effective_filesystem_format_returns_fat12_for_img(tmp_path: Path):
    resolver = _make_resolver(tmp_path)
    request = _make_floppy_request(tmp_path / "floppy.img")
    assert resolver._effective_filesystem_format(request) is DiskFormat.FAT12


def test_effective_filesystem_format_passes_through_for_vhd(tmp_path: Path):
    resolver = _make_resolver(tmp_path)
    request = _make_floppy_request(tmp_path / "disk.vhd")
    # Patch the request to be a VHD.
    request = CreateRequest(
        path=request.path,
        size_bytes=64 * 1024 * 1024,
        media_type=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        floppy_type=request.floppy_type,
        boot_mode=request.boot_mode,
        freedos_source=request.freedos_source,
    )
    assert resolver._effective_filesystem_format(request) is DiskFormat.FAT16


def test_resolve_boot_template_uses_builtin_fat12_when_local_missing(tmp_path: Path):
    resolver = _make_resolver(tmp_path)
    assets_dir = tmp_path / "freedos"
    assets_dir.mkdir()
    # No BOOTSECT_FAT12.BIN in the assets directory; resolver should fall
    # back to the built-in FreeDOS FAT12 boot sector materialized to cache.
    template = resolver._resolve_boot_template(assets_dir, DiskFormat.FAT12)
    assert template.exists()
    assert template.read_bytes()[:512] == _BUILTIN_FAT12_BOOT_SECTOR


def test_resolve_boot_template_prefers_local_fat12_when_present(tmp_path: Path):
    resolver = _make_resolver(tmp_path)
    assets_dir = tmp_path / "freedos"
    assets_dir.mkdir()
    # A user-provided FAT12 template must win over the built-in fallback.
    sentinel = b"\xeb\x3c\x90" + b"\xaa" * 507 + b"\x55\xaa"
    assert len(sentinel) == 512
    user_template = assets_dir / "BOOTSECT_FAT12.BIN"
    user_template.write_bytes(sentinel)

    template = resolver._resolve_boot_template(assets_dir, DiskFormat.FAT12)
    assert template == user_template
    assert template.read_bytes() == sentinel


def test_builtin_fat12_boot_sector_is_well_formed():
    assert len(_BUILTIN_FAT12_BOOT_SECTOR) == 512
    # Real FAT12 boot sectors start with a short JMP + NOP and end with
    # the AA55 boot signature. The OEM ID at offset 3..10 should be
    # "FreeDOS " for the bundled FreeDOS upstream sector.
    assert _BUILTIN_FAT12_BOOT_SECTOR[0] == 0xEB
    assert _BUILTIN_FAT12_BOOT_SECTOR[2] == 0x90
    assert _BUILTIN_FAT12_BOOT_SECTOR[510:512] == b"\x55\xaa"
    assert _BUILTIN_FAT12_BOOT_SECTOR[3:11] == b"FreeDOS "
    # The FAT-type field at offset 54..61 must say "FAT12   ".
    assert _BUILTIN_FAT12_BOOT_SECTOR[54:62] == b"FAT12   "
