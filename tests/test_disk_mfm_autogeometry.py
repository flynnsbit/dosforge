"""Regression tests for the MFM auto-derived CHS geometry path
(``disk._xt_class_geometry`` when no BIOS preset and no custom CHS
are supplied).

Before v0.9.45, the function silently fell back to Phoenix Type 1
(10 MiB) whenever neither ``bios_drive_spec`` nor ``custom_chs`` was
set.  ``_validate_mfm_request`` then overwrote the user's typed
``size_bytes`` with that 10 MiB value, which immediately failed
``validate_size_for_format`` for FAT16 (>=16 MiB requirement) -- so a
user picking *Boot=IBM PC 8088*, *Filesystem=FAT16*, *Static size=32M*,
*Controller=MFM* hit:

    "FAT16 images must be at least 16 MiB."

The fix derives an MFM/XT-class CHS from ``request.size_bytes`` by
iterating heads in (4, 6, 8, 15) with spt=17, picking the smallest
heads where the cylinder count stays <= 1024 (the XT-class BIOS
limit).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.disk import _xt_class_geometry
from dosforge.errors import ValidationError
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    FloppyType,
    IBMDOSVersion,
    MediaType,
)


def _ibm8088_mfm_request(size_mib: int) -> CreateRequest:
    return CreateRequest(
        path=Path("/tmp/ibm8088.vhd"),
        size_bytes=size_mib * 1024 * 1024,
        media_type=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        floppy_type=FloppyType.F1440K,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
        disk_controller=DiskController.MFM,
    )


@pytest.mark.parametrize(
    "size_mib",
    [16, 20, 32, 50, 64, 100, 127],
)
def test_xt_class_auto_geometry_honors_user_size(size_mib: int) -> None:
    """Derived geometry must round UP to >= the user's requested size
    (never silently shrink) and must stay within the BIOS-compatible
    1024-cylinder cap on heads in {4,6,8,15} with 17 spt."""
    request = _ibm8088_mfm_request(size_mib)
    cylinders, heads, spt, size_bytes = _xt_class_geometry(request)

    assert cylinders <= 1024, "cylinders must fit the XT-class BIOS cap"
    assert heads in (4, 6, 8, 15), "heads must be an MFM-compatible value"
    assert spt == 17, "spt must be the universal MFM/RLL value"
    assert size_bytes >= request.size_bytes, (
        f"auto-derived size ({size_bytes}) must be >= requested "
        f"({request.size_bytes}); never silently shrink the user's input"
    )
    # FAT16 minimum -- the original bug: 10 MiB Type 1 fallback failed
    # this check.  Any size_mib >= 16 must clear it.
    assert size_bytes >= 16 * 1024 * 1024


def test_xt_class_auto_geometry_picks_smallest_heads() -> None:
    """For a 32 MiB request, 4-head geometry fits (964 x 4 x 17 x 512 =
    32.0 MiB), so we should NOT pick 6/8/15 heads."""
    request = _ibm8088_mfm_request(32)
    _, heads, _, _ = _xt_class_geometry(request)
    assert heads == 4


def test_xt_class_auto_geometry_steps_up_to_15_heads_for_large_size() -> None:
    """A 100 MiB request can't fit in 4-, 6-, or 8-head geometries
    (4*17*512*1024 = 33.4 MiB, 6*17*512*1024 = 51 MiB, 8*17*512*1024
    = 68 MiB -- all below 100 MiB) so we must step up to 15 heads."""
    request = _ibm8088_mfm_request(100)
    _, heads, _, _ = _xt_class_geometry(request)
    assert heads == 15


def test_xt_class_auto_geometry_rejects_oversize_request() -> None:
    """Requests above ~127 MiB exceed the MFM 1024 x 15 x 17 ceiling.
    The function must raise ValidationError rather than silently
    capping (would produce a wrong-size VHD)."""
    request = _ibm8088_mfm_request(200)
    with pytest.raises(ValidationError, match="MFM controller auto-geometry"):
        _xt_class_geometry(request)


def test_xt_class_auto_geometry_zero_size_uses_phoenix_type1() -> None:
    """Zero/negative size falls back to the legacy Phoenix Type 1
    default (preserves pre-v0.9.45 behavior for callers that genuinely
    have no size hint)."""
    request = _ibm8088_mfm_request(0)
    cylinders, heads, spt, size_bytes = _xt_class_geometry(request)
    assert (cylinders, heads, spt) == (306, 4, 17)
    assert size_bytes == 306 * 4 * 17 * 512
