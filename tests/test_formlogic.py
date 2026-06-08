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
    assert f.FIELD_BIOS_DRIVE in vis
    assert f.FIELD_CUSTOM_CHS in vis
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


def test_bios_preset_disables_and_fills_size():
    state = _state(bios_drive_type=_first_bios_slug())
    assert f.FIELD_SIZE in f.disabled_fields(state)
    assert f.effective_size_text(state).endswith("M")


def test_custom_chs_disables_and_fills_size():
    state = _state(custom_chs="306,4,17")
    assert f.FIELD_SIZE in f.disabled_fields(state)
    assert f.effective_size_text(state) == "10M"


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
