from __future__ import annotations

import dataclasses

import pytest

from dosforge import formlogic as f
from dosforge.errors import DosForgeError
from dosforge.models import (
    BIOSVendor,
    BootMode,
    DiskController,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    GeometrySource,
    IBMDOSVersion,
    MediaType,
    iter_bios_drive_types,
)


def _state(**overrides) -> f.FormState:
    base = dataclasses.replace(f.default_state(), output_path="~/disk.vhd")
    return dataclasses.replace(base, **overrides)


def test_default_vhd_visibility():
    vis = f.visible_fields(_state())
    assert f.FIELD_SIZE in vis
    assert f.FIELD_FORMAT in vis
    assert f.FIELD_DISK_CONTROLLER in vis
    assert f.FIELD_GEOMETRY_SOURCE in vis
    # v0.8.0 hierarchy: BIOS preset + custom CHS inputs only show
    # when the geometry-source picker selects them.  Default state
    # has geometry_source=SIZE so the static-size Input is visible
    # and the other two stay hidden.
    assert f.FIELD_BIOS_DRIVE not in vis
    assert f.FIELD_CUSTOM_CHS not in vis
    assert f.FIELD_BOOT_MODE in vis
    assert f.FIELD_CUSTOM_PAYLOAD in vis
    assert f.FIELD_FLOPPY not in vis


def test_img_visibility_hides_vhd_only_controls():
    vis = f.visible_fields(_state(media_type=MediaType.IMG.value))
    assert f.FIELD_FLOPPY in vis
    assert f.FIELD_IMG_SYSTEM_FORMAT in vis
    assert f.FIELD_SIZE not in vis
    assert f.FIELD_DISK_CONTROLLER not in vis
    assert f.FIELD_BIOS_DRIVE not in vis
    assert f.FIELD_GEOMETRY_SOURCE not in vis
    assert f.FIELD_BOOT_MODE not in vis


def test_freedos_local_shows_assets_not_url():
    state = _state(boot_mode=BootMode.FREEDOS.value, freedos_source=FreeDOSSource.LOCAL.value)
    vis = f.visible_fields(state)
    assert f.FIELD_FREEDOS_SOURCE in vis
    assert f.FIELD_FETCH_FREEDOS in vis
    assert f.FIELD_BOOT_ASSETS in vis
    assert f.FIELD_FREEDOS_URL not in vis


def test_pcdos71_shows_sgtk_fetch_button():
    vis = f.visible_fields(_state(boot_mode=BootMode.PCDOS71.value))
    assert f.FIELD_DOS_PROFILE in vis
    assert f.FIELD_BOOT_ASSETS in vis
    assert f.FIELD_FETCH_PCDOS71 in vis


def test_ibm8088_shows_version_toggle():
    assert f.FIELD_IBM_DOS_VERSION in f.visible_fields(_state(boot_mode=BootMode.IBM8088.value))


def _first_bios_slug() -> str:
    spec = next(iter(iter_bios_drive_types(BIOSVendor.PHOENIX)))
    return spec.slug


def test_geometry_source_preset_shows_bios_drive_hides_size_and_chs():
    """v0.8.0: picking 'BIOS preset' surfaces only the bios_drive
    Input.  Size + custom CHS inputs are hidden so the user sees a
    single source-of-truth."""
    state = _state(
        geometry_source=GeometrySource.PRESET.value,
        bios_drive_type=_first_bios_slug(),
    )
    vis = f.visible_fields(state)
    assert f.FIELD_BIOS_DRIVE in vis
    assert f.FIELD_SIZE not in vis
    assert f.FIELD_CUSTOM_CHS not in vis
    # effective_size_text still returns the preset's size in MB.
    assert f.effective_size_text(state).endswith("M")


def test_geometry_source_custom_chs_shows_chs_hides_others():
    """Picking 'Custom CHS' surfaces only the custom_chs Input."""
    state = _state(
        geometry_source=GeometrySource.CUSTOM_CHS.value,
        custom_chs="306,4,17",
    )
    vis = f.visible_fields(state)
    assert f.FIELD_CUSTOM_CHS in vis
    assert f.FIELD_SIZE not in vis
    assert f.FIELD_BIOS_DRIVE not in vis
    assert f.effective_size_text(state) == "10M"


def test_disabled_fields_returns_empty_in_v080():
    """disabled_fields() is a no-op in v0.8.0 -- the geometry-source
    picker eliminates the need for the SIZE-disabled state by only
    showing one input at a time.  Kept as no-op for backward compat."""
    state = _state(bios_drive_type=_first_bios_slug())
    assert f.disabled_fields(state) == set()
    state = _state(custom_chs="306,4,17")
    assert f.disabled_fields(state) == set()


def test_infer_geometry_source_custom_chs_wins_over_preset():
    """infer_geometry_source migrates pre-v0.8.0 / external states:
    custom CHS wins over BIOS preset wins over static size."""
    # custom_chs wins
    state = _state(custom_chs="306,4,17", bios_drive_type=_first_bios_slug())
    assert f.infer_geometry_source(state) is GeometrySource.CUSTOM_CHS
    # bios preset wins over plain size
    state = _state(bios_drive_type=_first_bios_slug())
    assert f.infer_geometry_source(state) is GeometrySource.PRESET
    # bare state falls back to size
    assert f.infer_geometry_source(_state()) is GeometrySource.SIZE


def test_coerce_geometry_source_size_clears_preset_and_chs():
    """Switching back to 'Static size' clears the inactive inputs
    so the state matches what's visible."""
    state = _state(
        geometry_source=GeometrySource.SIZE.value,
        bios_drive_type=_first_bios_slug(),
        custom_chs="306,4,17",
    )
    snapped = f.coerce_on_geometry_source_change(state)
    assert snapped.bios_drive_type == ""
    assert snapped.custom_chs == ""


def test_coerce_geometry_source_preset_clears_custom_chs():
    state = _state(
        geometry_source=GeometrySource.PRESET.value,
        custom_chs="306,4,17",
    )
    snapped = f.coerce_on_geometry_source_change(state)
    assert snapped.custom_chs == ""


def test_coerce_geometry_source_custom_chs_clears_preset():
    state = _state(
        geometry_source=GeometrySource.CUSTOM_CHS.value,
        bios_drive_type=_first_bios_slug(),
    )
    snapped = f.coerce_on_geometry_source_change(state)
    assert snapped.bios_drive_type == ""


def test_coerce_boot_change_compaq2_snaps_geometry_source_to_preset():
    """COMPAQ2 / PCDOS3 / COMPAQ3 snap a Phoenix Type 1 preset, so
    geometry_source must also flip to PRESET so the right input is
    visible in Step 2."""
    for mode in (BootMode.COMPAQ2, BootMode.PCDOS3, BootMode.COMPAQ3):
        snapped = f.coerce_on_boot_change(_state(boot_mode=mode.value))
        assert snapped.geometry_source == GeometrySource.PRESET.value
        assert snapped.bios_drive_type == "phoenix:1"
        assert snapped.custom_chs == ""


def test_coerce_boot_change_default_snaps_geometry_source_to_size():
    """All non-preset boot modes snap geometry_source=SIZE and clear
    any stale BIOS preset / custom CHS so the state matches the
    visible static-size input."""
    snapped = f.coerce_on_boot_change(
        _state(
            boot_mode=BootMode.MSDOS622.value,
            bios_drive_type=_first_bios_slug(),
            custom_chs="306,4,17",
        )
    )
    assert snapped.geometry_source == GeometrySource.SIZE.value
    assert snapped.bios_drive_type == ""
    assert snapped.custom_chs == ""


def test_geometry_preview_text_for_size():
    state = _state(size_text="128M")
    text = f.geometry_preview_text(state)
    assert "128 MB" in text
    assert "auto-derived" in text


def test_geometry_preview_text_for_preset():
    state = _state(
        geometry_source=GeometrySource.PRESET.value,
        bios_drive_type="phoenix:1",
    )
    text = f.geometry_preview_text(state)
    assert "10 MB" in text
    assert "306" in text
    assert "spt" in text


def test_geometry_preview_text_for_custom_chs():
    state = _state(
        geometry_source=GeometrySource.CUSTOM_CHS.value,
        custom_chs="306,4,17",
    )
    text = f.geometry_preview_text(state)
    assert "10 MB" in text
    assert "306" in text


def test_geometry_preview_text_empty_for_img():
    """IMG mode has no VHD geometry, so the preview is empty."""
    state = _state(media_type=MediaType.IMG.value)
    assert f.geometry_preview_text(state) == ""


def test_format_cap_clamps_freedos_fat16_to_2gib():
    """v0.8.2: FreeDOS doesn't pin its own max_mb in the per-boot-mode
    rule, but the FAT16 backend cap (2 GiB) now feeds into the snap
    so the UI clamps live instead of waiting for Create to fail."""
    state = _state(
        boot_mode=BootMode.FREEDOS.value,
        disk_format=DiskFormat.FAT16.value,
        size_text="5G",
    )
    snapped = f.coerce_on_format_change(state)
    # 2G = 2048 MiB
    assert snapped.size_text == "2G"


def test_format_cap_clamps_msdos622_fat16_to_2gib():
    state = _state(
        boot_mode=BootMode.MSDOS622.value,
        disk_format=DiskFormat.FAT16.value,
        size_text="4G",
    )
    snapped = f.coerce_on_format_change(state)
    assert snapped.size_text == "2G"


def test_format_cap_does_not_loosen_tighter_per_mode_cap():
    """IBM8088 has per-mode max_mb=32; the FAT16 backend cap (2048)
    must NOT loosen this -- the tighter cap wins."""
    state = _state(
        boot_mode=BootMode.IBM8088.value,
        disk_format=DiskFormat.FAT16.value,
        size_text="500M",
    )
    snapped = f.coerce_on_format_change(state)
    assert snapped.size_text == "32M"


def test_format_cap_clamps_freedos_fat32_to_2tib():
    state = _state(
        boot_mode=BootMode.FREEDOS.value,
        disk_format=DiskFormat.FAT32.value,
        size_text="5T",
    )
    snapped = f.coerce_on_format_change(state)
    # 2 TiB = 2048 GiB rendered as "2048G"
    assert snapped.size_text == "2048G"


def test_validate_media_step_rejects_oversized_fat16_freedos():
    """Step 2 -> Step 3 'Next' click surfaces the FAT16 cap error
    before the user wastes time on Step 3 + Create."""
    state = _state(
        boot_mode=BootMode.FREEDOS.value,
        disk_format=DiskFormat.FAT16.value,
        size_text="3G",
    )
    err = f.validate_media_step(state)
    assert err is not None
    assert "fat16" in err.lower()
    assert "2g" in err.lower() or "2048" in err.lower()


def test_geometry_preview_includes_max_cap_for_size_mode():
    """Preview line shows the effective cap so the user sees the
    ceiling at a glance: '-> 512 MB (...) (max 2G for fat16)'."""
    state = _state(
        boot_mode=BootMode.MSDOS622.value,
        disk_format=DiskFormat.FAT16.value,
        size_text="512M",
    )
    text = f.geometry_preview_text(state)
    assert "max" in text.lower()
    assert "fat16" in text.lower()


def test_request_requires_path():
    with pytest.raises(DosForgeError):
        f.build_create_request(dataclasses.replace(f.default_state(), output_path=""))


def test_vhd_request_basic():
    req = f.build_create_request(_state(size_text="256M"))
    assert req.media_type is MediaType.VHD
    assert req.size_bytes == 256 * 1024 * 1024
    assert req.disk_format is DiskFormat.FAT16
    assert req.disk_controller is None


def test_disk_controller_and_custom_chs_request():
    req = f.build_create_request(_state(disk_controller="mfm", custom_chs="306,4,17"))
    assert req.disk_controller is DiskController.MFM
    assert req.custom_chs == (306, 4, 17)
    assert req.size_bytes == 306 * 4 * 17 * 512


def test_bios_preset_sets_request_tuple():
    req = f.build_create_request(_state(bios_drive_type=_first_bios_slug()))
    assert req.bios_drive_type is not None
    assert req.bios_drive_type[0] in (BIOSVendor.PHOENIX, BIOSVendor.AMI)


def test_img_request_uses_floppy_size_and_suppresses_boot():
    req = f.build_create_request(
        _state(media_type=MediaType.IMG.value, floppy_type=FloppyType.F1440K.value, boot_mode=BootMode.MSDOS5.value)
    )
    assert req.size_bytes == FloppyType.F1440K.size_bytes
    assert req.boot_mode is BootMode.NONE


def test_img_system_format_honors_boot_mode():
    req = f.build_create_request(_state(media_type=MediaType.IMG.value, img_system_format=True, boot_mode=BootMode.MSDOS33.value))
    assert req.boot_mode is BootMode.MSDOS33


def test_custom_payload_allows_omitted_size():
    req = f.build_create_request(_state(size_text="", custom_payload="~/payload"))
    assert req.size_bytes == 1


def test_omitted_size_without_payload_raises():
    with pytest.raises(DosForgeError):
        f.build_create_request(_state(size_text=""))


def test_coerce_media_to_img_resets_boot_and_controller():
    state = _state(media_type=MediaType.IMG.value, boot_mode=BootMode.MSDOS5.value, disk_controller="mfm", img_system_format=True)
    new = f.coerce_on_media_change(state)
    assert new.boot_mode == BootMode.NONE.value
    assert new.disk_controller == ""
    assert new.img_system_format is False


def test_coerce_boot_to_compaq2_sets_mfm_fat12_type1():
    new = f.coerce_on_boot_change(_state(boot_mode=BootMode.COMPAQ2.value))
    assert new.disk_controller == DiskController.MFM.value
    assert new.disk_format == DiskFormat.FAT12.value
    assert new.bios_drive_type == "phoenix:1"
    assert new.size_text == "10M"


def test_coerce_boot_to_ibm8088_sets_default_size_and_mfm():
    new = f.coerce_on_boot_change(_state(boot_mode=BootMode.IBM8088.value, size_text="512M"))
    assert new.size_text == "32M"
    assert new.disk_controller == DiskController.MFM.value
    assert new.ibm_dos_version == IBMDOSVersion.DOS33.value


def test_coerce_uncheck_system_format_clears_boot():
    new = f.coerce_on_img_system_format_change(_state(media_type=MediaType.IMG.value, img_system_format=False, boot_mode=BootMode.MSDOS5.value))
    assert new.boot_mode == BootMode.NONE.value


@pytest.mark.parametrize(
    "boot_mode,expected",
    [
        (BootMode.NONE, ""),
        (BootMode.FREEDOS, "freedos"),
        (BootMode.MSDOS33, "msdos33"),
        (BootMode.MSDOS622, "msdos622"),
        (BootMode.PCDOS, "pcdos"),
        (BootMode.PCDOS3, "pcdos3"),
        (BootMode.PCDOS71, "pcdos71"),
        (BootMode.COMPAQ2, "compaq2"),
        (BootMode.COMPAQ3, "compaq3"),
        (BootMode.DRDOS6, "drdos6"),
        (BootMode.DRDOS7, "drdos7"),
        (BootMode.IBM8088, "ibm8088"),
        (BootMode.MSDOS71, "msdos71"),
    ],
)
def test_default_boot_assets_for_each_mode(boot_mode, expected):
    """default_boot_assets_for pre-populates the dosassets/<mode>/ subdir
    name for the Boot assets Input.  NONE → empty (no boot)."""
    assert f.default_boot_assets_for(boot_mode) == expected


def test_coerce_boot_change_snaps_boot_assets_to_mode_value():
    """coerce_on_boot_change overwrites boot_assets on every mode change,
    matching the snap pattern used for media_type/disk_format/etc."""
    # Start with custom path, pick MSDOS5 -> snaps to 'msdos5'.
    new = f.coerce_on_boot_change(
        _state(boot_mode=BootMode.MSDOS5.value, boot_assets="/tmp/my-custom-path")
    )
    assert new.boot_assets == "msdos5"

    # Pick PCDOS -> snaps to 'pcdos' (the generic catch-all dir).
    new = f.coerce_on_boot_change(
        _state(boot_mode=BootMode.PCDOS.value, boot_assets="msdos5")
    )
    assert new.boot_assets == "pcdos"

    # Pick NONE -> empty (no boot, no assets needed).
    new = f.coerce_on_boot_change(
        _state(boot_mode=BootMode.NONE.value, boot_assets="freedos")
    )
    assert new.boot_assets == ""


def test_coerce_boot_change_snaps_boot_assets_in_early_return_branches():
    """The early-return branches (COMPAQ2, PCDOS3, COMPAQ3) must also
    snap boot_assets, since they bypass the trailing snap chain."""
    for mode in (BootMode.COMPAQ2, BootMode.PCDOS3, BootMode.COMPAQ3):
        new = f.coerce_on_boot_change(
            _state(boot_mode=mode.value, boot_assets="/tmp/stale")
        )
        assert new.boot_assets == mode.value, (
            f"early-return branch for {mode.value} dropped the boot_assets snap"
        )


def test_summary_has_expected_rows():
    rows = dict(f.build_summary(_state(size_text="256M")))
    assert "VHD" in rows["Media"]
    assert rows["Controller"] == "auto"
    assert rows["Overwrite"] == "no"
