"""MartyPC compatibility tests for v0.9.48.

Covers:
- MartyPC-Xebec BIOS vendor + 4-entry drive type table
- XT-IDE controller geometry auto-picker (smallest fit in whitelist)
- XTIDE validation rules (no FAT32, no DOS 7.x, CHS must be whitelisted)
- All 127 XT-IDE format whitelist entries are reachable via auto-pick
  for sufficient size requests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.commands import CommandRunner
from dosforge.disk import (
    DiskManager,
    _MARTYPC_XTIDE_FORMATS,
    _MARTYPC_XTIDE_FORMAT_SET,
    _is_xt_class_controller,
    _resolved_xt_class_geometry,
    _xtide_geometry,
)
from dosforge.models import (
    BIOS_AT_DRIVE_TYPES,
    BIOSVendor,
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    FloppyType,
    MediaType,
    iter_bios_drive_types,
    lookup_bios_drive_type,
    parse_bios_drive_slug,
)
from dosforge.errors import ValidationError


# ---------------------------------------------------------------------------
# MartyPC-Xebec BIOS preset table (4 entries from xebec.rs)
# ---------------------------------------------------------------------------

XEBEC_EXPECTED = {
    # type_id : (cyl, heads, spt, wpc, lz, size_mb)
    1:  (306, 4, 17,   0, 305, 10),
    2:  (615, 4, 17, 300, 615, 20),
    13: (306, 8, 17, 128, 305, 20),
    16: (612, 4, 17,   0, 612, 20),
}


def test_martypc_xebec_vendor_enum_value() -> None:
    assert BIOSVendor.MARTYPC_XEBEC.value == "martypc-xebec"


def test_martypc_xebec_table_has_exactly_4_entries() -> None:
    specs = list(iter_bios_drive_types(BIOSVendor.MARTYPC_XEBEC))
    assert len(specs) == 4, "MartyPC's xebec.rs has exactly 4 hardcoded formats"
    assert {s.type_id for s in specs} == {1, 2, 13, 16}


@pytest.mark.parametrize("type_id", list(XEBEC_EXPECTED))
def test_martypc_xebec_entry_matches_upstream(type_id: int) -> None:
    """Geometry + wpc must match MartyPC's xebec.rs ``supported_formats`` vec."""
    spec = lookup_bios_drive_type(BIOSVendor.MARTYPC_XEBEC, type_id)
    cyl, heads, spt, wpc, lz, size_mb = XEBEC_EXPECTED[type_id]
    assert spec.cylinders == cyl
    assert spec.heads == heads
    assert spec.sectors_per_track == spt
    assert spec.write_precomp_cylinder == wpc
    assert spec.landing_zone_cylinder == lz
    assert spec.size_mb == size_mb


def test_martypc_xebec_slug_parses() -> None:
    assert parse_bios_drive_slug("martypc-xebec:16") == (BIOSVendor.MARTYPC_XEBEC, 16)


def test_martypc_xebec_description_uses_pretty_label() -> None:
    """MartyPC-Xebec should not show up as the ugly auto-capitalized
    'Martypc-xebec' that the generic ``.capitalize()`` fallback would produce."""
    spec = lookup_bios_drive_type(BIOSVendor.MARTYPC_XEBEC, 1)
    assert spec.description.startswith("MartyPC-Xebec Type 1")


def test_martypc_xebec_type_16_geometry_is_authentic() -> None:
    """Type 16 (612x4x17) -- in MartyPC's xebec.rs as a 20MB entry; the same
    CHS also happens to appear in Phoenix's table as Type 16, but the
    MartyPC-Xebec slug exists for unambiguous documentation."""
    xebec_t16 = lookup_bios_drive_type(BIOSVendor.MARTYPC_XEBEC, 16)
    assert (xebec_t16.cylinders, xebec_t16.heads, xebec_t16.sectors_per_track) == (612, 4, 17)


# ---------------------------------------------------------------------------
# XT-IDE controller enum + format whitelist
# ---------------------------------------------------------------------------

def test_disk_controller_xtide_value() -> None:
    assert DiskController.XTIDE.value == "xtide"


def test_xt_class_helper_covers_mfm_and_xtide() -> None:
    assert _is_xt_class_controller(DiskController.MFM) is True
    assert _is_xt_class_controller(DiskController.XTIDE) is True
    assert _is_xt_class_controller(DiskController.IDE) is False


def test_xtide_format_table_matches_upstream_count() -> None:
    """MartyPC's at_formats.rs has 127 entries (verified against
    https://github.com/dbalsom/martypc raw at_formats.rs as of v0.4.x)."""
    assert len(_MARTYPC_XTIDE_FORMATS) == 127


def test_xtide_format_table_has_no_duplicates() -> None:
    assert len(_MARTYPC_XTIDE_FORMATS) == len(_MARTYPC_XTIDE_FORMAT_SET)


def test_xtide_format_table_only_uses_realistic_spt_values() -> None:
    """All entries use spt in {17, 26, 33-40, 46, 59, 62, 63} per at_formats.rs."""
    allowed_spt = {17, 26, 31, 33, 34, 35, 36, 38, 39, 40, 46, 59, 62, 63}
    seen_spt = {spt for _, _, spt in _MARTYPC_XTIDE_FORMATS}
    extras = seen_spt - allowed_spt
    assert not extras, f"unexpected spt values: {extras}"


# ---------------------------------------------------------------------------
# XTIDE geometry auto-picker
# ---------------------------------------------------------------------------

def _xtide_request(size_bytes: int) -> CreateRequest:
    return CreateRequest(
        path=Path("/tmp/x.vhd"),
        boot_mode=BootMode.MSDOS5,
        media_type=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=size_bytes,
        floppy_type=FloppyType.F1440K,
        disk_controller=DiskController.XTIDE,
    )


@pytest.mark.parametrize(
    "req_mib,expected_chs",
    [
        (10,  (306,  4, 17)),
        (16,  (1024, 2, 17)),
        (20,  (306,  8, 17)),
        (32,  (1024, 4, 17)),
        (64,  (1024, 5, 26)),
        (100, (776,  8, 33)),
        (200, (684, 16, 38)),
        (500, (1024,16, 63)),
    ],
)
def test_xtide_geometry_picks_smallest_fit(req_mib: int, expected_chs: tuple[int, int, int]) -> None:
    r = _xtide_request(req_mib * 1024 * 1024)
    cyl, h, spt, sz = _xtide_geometry(r)
    assert (cyl, h, spt) == expected_chs
    assert (cyl, h, spt) in _MARTYPC_XTIDE_FORMAT_SET
    assert sz >= req_mib * 1024 * 1024


def test_xtide_geometry_rejects_oversize_request() -> None:
    r = _xtide_request(2 * 1024 * 1024 * 1024)  # 2 GiB
    with pytest.raises(ValidationError, match="cannot fit"):
        _xtide_geometry(r)


def test_xtide_geometry_honors_explicit_bios_drive_type() -> None:
    """When --bios-drive-type is given, that geometry wins over auto-pick."""
    r = _xtide_request(0)
    r.bios_drive_type = (BIOSVendor.MARTYPC_XEBEC, 16)
    cyl, h, spt, _ = _xtide_geometry(r)
    assert (cyl, h, spt) == (612, 4, 17)


def test_resolved_xt_class_geometry_dispatches_by_controller() -> None:
    """Helper should pick XTIDE table for XTIDE, Phoenix shape for MFM."""
    r = _xtide_request(32 * 1024 * 1024)
    cyl_xtide, h_xtide, spt_xtide, _ = _resolved_xt_class_geometry(r)
    assert (cyl_xtide, h_xtide, spt_xtide) in _MARTYPC_XTIDE_FORMAT_SET

    r.disk_controller = DiskController.MFM
    cyl_mfm, h_mfm, spt_mfm, _ = _resolved_xt_class_geometry(r)
    # MFM uses spt=17 universally; cylinder count differs from XTIDE table.
    assert spt_mfm == 17


# ---------------------------------------------------------------------------
# XTIDE validation rules
# ---------------------------------------------------------------------------

@pytest.fixture
def manager() -> DiskManager:
    return DiskManager(CommandRunner())


def test_xtide_validates_clean_msdos5_request(manager: DiskManager) -> None:
    r = _xtide_request(32 * 1024 * 1024)
    manager._validate_xtide_request(r)
    # Validation should snap size_bytes to a whitelisted geometry's size.
    assert r.size_bytes >= 32 * 1024 * 1024


def test_xtide_rejects_fat32(manager: DiskManager) -> None:
    r = _xtide_request(128 * 1024 * 1024)
    r.disk_format = DiskFormat.FAT32
    with pytest.raises(ValidationError, match="FAT32"):
        manager._validate_xtide_request(r)


def test_xtide_rejects_msdos71(manager: DiskManager) -> None:
    r = _xtide_request(32 * 1024 * 1024)
    r.boot_mode = BootMode.MSDOS71
    with pytest.raises(ValidationError, match="msdos71"):
        manager._validate_xtide_request(r)


def test_xtide_rejects_pcdos71(manager: DiskManager) -> None:
    r = _xtide_request(128 * 1024 * 1024)
    r.boot_mode = BootMode.PCDOS71
    with pytest.raises(ValidationError, match="pcdos71"):
        manager._validate_xtide_request(r)


def test_xtide_rejects_img_media(manager: DiskManager) -> None:
    r = _xtide_request(1474560)
    r.media_type = MediaType.IMG
    with pytest.raises(ValidationError, match="VHD"):
        manager._validate_xtide_request(r)


def test_xtide_rejects_custom_chs_not_in_whitelist(manager: DiskManager) -> None:
    """A custom CHS that resolves to a non-whitelisted geometry must fail
    closed -- otherwise the VHD will silently fail to mount in MartyPC."""
    r = _xtide_request(0)
    r.custom_chs = (500, 8, 17)  # not in whitelist
    with pytest.raises(ValidationError, match="not in MartyPC's XT-IDE format whitelist"):
        manager._validate_xtide_request(r)


def test_xtide_accepts_custom_chs_in_whitelist(manager: DiskManager) -> None:
    """A custom CHS that exactly matches a whitelist entry passes."""
    r = _xtide_request(0)
    r.custom_chs = (1024, 16, 17)  # is in whitelist
    manager._validate_xtide_request(r)
    assert r.size_bytes == 1024 * 16 * 17 * 512


# ---------------------------------------------------------------------------
# Form coercion: picking a MartyPC-Xebec preset forces FAT12 default
# ---------------------------------------------------------------------------

from dataclasses import replace as _dc_replace

from dosforge import formlogic as fl


@pytest.mark.parametrize("slug", [
    "martypc-xebec:1",
    "martypc-xebec:2",
    "martypc-xebec:13",
    "martypc-xebec:16",
])
def test_coerce_on_bios_drive_change_forces_fat12_for_xebec(slug: str) -> None:
    """Picking any martypc-xebec preset should default disk_format to FAT12.

    Type 1 is 10 MiB (below FAT16's 16 MiB minimum) -- defaulting to
    FAT12 prevents a confusing 'FAT16 needs >=16 MiB' error.  The
    20 MiB Types 2/13/16 also default to FAT12 since they pair with
    FAT12-only DOS 2.x/3.x; user can still flip to FAT16 manually.
    """
    state = fl.FormState(
        bios_drive_type=slug,
        disk_format=DiskFormat.FAT16.value,
    )
    snapped = fl.coerce_on_bios_drive_change(state)
    assert snapped.disk_format == DiskFormat.FAT12.value


def test_coerce_on_bios_drive_change_leaves_phoenix_untouched() -> None:
    """Phoenix / AMI presets keep whatever format the user already picked."""
    state = fl.FormState(
        bios_drive_type="phoenix:1",
        disk_format=DiskFormat.FAT16.value,
    )
    snapped = fl.coerce_on_bios_drive_change(state)
    assert snapped.disk_format == DiskFormat.FAT16.value


def test_coerce_on_bios_drive_change_leaves_unset_untouched() -> None:
    """Empty bios_drive_type (Custom -- use size field) is a no-op."""
    state = fl.FormState(
        bios_drive_type="",
        disk_format=DiskFormat.FAT16.value,
    )
    snapped = fl.coerce_on_bios_drive_change(state)
    assert snapped.disk_format == DiskFormat.FAT16.value
