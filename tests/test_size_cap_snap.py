"""Tests for the cap-aware geometry snap (v0.9.54+).

Covers the contract that the form's advertised max size round-trips
through create without silently bumping past the per-boot-mode cap.

See ``plan.md`` in the session workspace for the full audit + design.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.disk import (
    _MARTYPC_XTIDE_FORMATS,
    _effective_size_cap_bytes,
    _xtide_geometry,
)
from dosforge.errors import ValidationError
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MediaType,
    MSDOSInstallProfile,
)


def _make_request(
    *,
    boot_mode: BootMode,
    disk_format: DiskFormat,
    size_bytes: int,
    ibm_dos_version: IBMDOSVersion = IBMDOSVersion.MSDOS33,
    disk_controller: DiskController | None = DiskController.XTIDE,
) -> CreateRequest:
    return CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=size_bytes,
        disk_format=disk_format,
        media_type=MediaType.VHD,
        floppy_type=FloppyType.F1440K,
        img_system_format=False,
        label=None,
        overwrite=True,
        boot_mode=boot_mode,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=None,
        freedos_download_url=None,
        msdos_install_profile=MSDOSInstallProfile.MINIMAL,
        ibm_dos_version=ibm_dos_version,
        custom_payload_path=None,
        bios_drive_type=None,
        disk_controller=disk_controller,
        custom_chs=None,
        host_boot_mode=None,
    )


class TestEffectiveSizeCapBytes:
    def test_pcdos3_caps_at_16_mib(self) -> None:
        req = _make_request(
            boot_mode=BootMode.PCDOS3,
            disk_format=DiskFormat.FAT12,
            size_bytes=16 * 1024 * 1024,
        )
        assert _effective_size_cap_bytes(req) == 16 * 1024 * 1024

    def test_compaq331_caps_at_504_mib(self) -> None:
        req = _make_request(
            boot_mode=BootMode.COMPAQ331,
            disk_format=DiskFormat.FAT16,
            size_bytes=504 * 1024 * 1024,
        )
        assert _effective_size_cap_bytes(req) == 504 * 1024 * 1024

    def test_ibm8088_dos33_caps_at_32_mib(self) -> None:
        req = _make_request(
            boot_mode=BootMode.IBM8088,
            disk_format=DiskFormat.FAT16,
            size_bytes=32 * 1024 * 1024,
            ibm_dos_version=IBMDOSVersion.MSDOS33,
        )
        assert _effective_size_cap_bytes(req) == 32 * 1024 * 1024

    def test_ibm8088_pcdos5_caps_at_504_mib(self) -> None:
        req = _make_request(
            boot_mode=BootMode.IBM8088,
            disk_format=DiskFormat.FAT16,
            size_bytes=504 * 1024 * 1024,
            ibm_dos_version=IBMDOSVersion.PCDOS5,
        )
        assert _effective_size_cap_bytes(req) == 504 * 1024 * 1024

    def test_freedos_no_mode_cap_falls_back_to_fat_format_cap(self) -> None:
        # FreeDOS has no per-boot-mode cap; the FAT format cap is the
        # only constraint.  FAT16 = 2 GiB.
        req = _make_request(
            boot_mode=BootMode.FREEDOS,
            disk_format=DiskFormat.FAT16,
            size_bytes=128 * 1024 * 1024,
            disk_controller=DiskController.IDE,
        )
        assert _effective_size_cap_bytes(req) == 2 * 1024 * 1024 * 1024


class TestXtideGeometryCapSnap:
    def test_pcdos3_16_mib_snaps_down_under_cap(self) -> None:
        """The user's reported bug: 16 MiB input + PCDOS3 16 MiB cap
        must snap DOWN to the largest whitelist entry <= 16 MiB,
        not UP to (1024, 2, 17) = ~17 MiB."""
        req = _make_request(
            boot_mode=BootMode.PCDOS3,
            disk_format=DiskFormat.FAT12,
            size_bytes=16 * 1024 * 1024,
        )
        cap = _effective_size_cap_bytes(req)
        cyl, h, spt, size = _xtide_geometry(req, max_size_bytes=cap)
        assert size <= cap
        # Largest whitelist entry that fits in 16 MiB is (306, 4, 26).
        assert (cyl, h, spt) == (306, 4, 26)

    def test_below_cap_input_still_snaps_up(self) -> None:
        """Sanity: smaller request still gets the smallest fits-above
        entry, unchanged from pre-v0.9.54 behavior."""
        req = _make_request(
            boot_mode=BootMode.PCDOS3,
            disk_format=DiskFormat.FAT12,
            size_bytes=8 * 1024 * 1024,
        )
        cap = _effective_size_cap_bytes(req)
        cyl, h, spt, size = _xtide_geometry(req, max_size_bytes=cap)
        # Snapped up to first entry >= 8 MiB and <= 16 MiB.
        assert size >= 8 * 1024 * 1024
        assert size <= cap

    def test_no_cap_picks_smallest_fits_above(self) -> None:
        """No cap (max_size_bytes=None) preserves the original
        smallest-fits-above behavior."""
        req = _make_request(
            boot_mode=BootMode.FREEDOS,
            disk_format=DiskFormat.FAT16,
            size_bytes=16 * 1024 * 1024,
        )
        cyl, h, spt, size = _xtide_geometry(req, max_size_bytes=None)
        # Without cap, the snap-up wins and picks (1024, 2, 17).
        assert (cyl, h, spt) == (1024, 2, 17)
        assert size == 1024 * 2 * 17 * 512

    def test_request_exceeds_largest_whitelist_entry_raises(self) -> None:
        """Existing behavior preserved: requesting >520 MiB raises."""
        req = _make_request(
            boot_mode=BootMode.FREEDOS,
            disk_format=DiskFormat.FAT16,
            size_bytes=1024 * 1024 * 1024,  # 1 GiB
        )
        with pytest.raises(ValidationError, match="tops out near"):
            _xtide_geometry(req)

    def test_cap_below_smallest_whitelist_entry_raises(self) -> None:
        """Edge case: cap below every whitelist entry's size -> clear
        error telling the user XT-IDE can't make a disk that small."""
        # Smallest whitelist entry is (306, 4, 17) = ~10.16 MiB.
        # Construct a cap below that (e.g. 5 MiB) by forging a request
        # with size = 1 MiB.  In production this can't happen because
        # the form caps at the boot-mode minimum, but the safety net
        # in _xtide_geometry should still raise cleanly.
        req = _make_request(
            boot_mode=BootMode.PCDOS3,
            disk_format=DiskFormat.FAT12,
            size_bytes=15 * 1024 * 1024,
        )
        # Synthetic 5 MiB cap (below smallest whitelist entry).
        with pytest.raises(ValidationError, match="cannot fit a disk under"):
            _xtide_geometry(req, max_size_bytes=5 * 1024 * 1024)


class TestXtideWhitelistInvariants:
    """Sanity checks on the whitelist data itself so future edits
    don't accidentally drop the entries the cap-snap relies on."""

    def test_has_entry_below_16_mib(self) -> None:
        """The snap-down for PCDOS3 16 MiB requires at least one entry
        <= 16 MiB.  (306, 4, 26) = 15.54 MiB qualifies."""
        below_16mib = [
            (c, h, s) for (c, h, s) in _MARTYPC_XTIDE_FORMATS
            if c * h * s * 512 <= 16 * 1024 * 1024
        ]
        assert len(below_16mib) >= 1

    def test_smallest_entry_is_under_11_mib(self) -> None:
        """Sanity bound: the smallest whitelist entry should be
        <= 11 MiB (rounded), matching MartyPC's at_formats[0]."""
        smallest = min(c * h * s * 512 for (c, h, s) in _MARTYPC_XTIDE_FORMATS)
        assert smallest <= 11 * 1024 * 1024
