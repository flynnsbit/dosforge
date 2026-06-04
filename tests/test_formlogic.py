"""Golden/parity tests for :mod:`dosforge.formlogic`.

These pin the create-form behavior the GUI relies on, mirroring the dynamic
visibility and request-building rules the Textual TUI implements inline. They
are fully headless (no Tk / Textual needed).
"""

from __future__ import annotations

import dataclasses

import pytest

from dosforge import formlogic as f
from dosforge.errors import DosForgeError
from dosforge.models import (
    BootMode,
    DiskFormat,
    FloppyType,
    IBMDOSVersion,
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
    FreeDOSSource,
    BIOSVendor,
    iter_bios_drive_types,
    lookup_martypc_at_format,
    DEFAULT_MARTYPC_AT_FORMAT_SLUG,
)


def _state(**overrides) -> f.FormState:
    base = dataclasses.replace(f.default_state(), output_path="~/disk.vhd")
    return dataclasses.replace(base, **overrides)


# ── Visibility ─────────────────────────────────────────────────────────────


def test_default_vhd_visibility():
    vis = f.visible_fields(_state())
    assert f.FIELD_SIZE in vis
    assert f.FIELD_FORMAT in vis
    assert f.FIELD_MACHINE_TARGET in vis
    assert f.FIELD_BIOS_DRIVE in vis
    assert f.FIELD_BOOT_MODE in vis
    assert f.FIELD_CUSTOM_PAYLOAD in vis
    # Floppy + system-format are IMG-only.
    assert f.FIELD_FLOPPY not in vis
    assert f.FIELD_IMG_SYSTEM_FORMAT not in vis


def test_img_visibility_hides_vhd_only_controls():
    vis = f.visible_fields(_state(media_type=MediaType.IMG.value))
    assert f.FIELD_FLOPPY in vis
    assert f.FIELD_IMG_SYSTEM_FORMAT in vis
    assert f.FIELD_SIZE not in vis
    assert f.FIELD_FORMAT not in vis
    assert f.FIELD_MACHINE_TARGET not in vis
    assert f.FIELD_BIOS_DRIVE not in vis
    # Boot controls are inactive for a non-system-format IMG.
    assert f.FIELD_BOOT_MODE not in vis


def test_img_system_format_activates_boot_controls():
    vis = f.visible_fields(
        _state(media_type=MediaType.IMG.value, img_system_format=True)
    )
    assert f.FIELD_BOOT_MODE in vis


def test_freedos_local_shows_assets_not_url():
    state = _state(boot_mode=BootMode.FREEDOS.value, freedos_source=FreeDOSSource.LOCAL.value)
    vis = f.visible_fields(state)
    assert f.FIELD_FREEDOS_SOURCE in vis
    assert f.FIELD_FETCH_FREEDOS in vis
    assert f.FIELD_BOOT_ASSETS in vis
    assert f.FIELD_FREEDOS_URL not in vis


def test_freedos_auto_shows_url_not_assets():
    state = _state(boot_mode=BootMode.FREEDOS.value, freedos_source=FreeDOSSource.AUTO.value)
    vis = f.visible_fields(state)
    assert f.FIELD_FREEDOS_URL in vis
    assert f.FIELD_BOOT_ASSETS not in vis


def test_dos_boot_mode_shows_profile_and_assets():
    state = _state(boot_mode=BootMode.MSDOS5.value)
    vis = f.visible_fields(state)
    assert f.FIELD_DOS_PROFILE in vis
    assert f.FIELD_BOOT_ASSETS in vis


def test_ibm8088_shows_version_toggle_except_on_xebec():
    state = _state(boot_mode=BootMode.IBM8088.value)
    assert f.FIELD_IBM_DOS_VERSION in f.visible_fields(state)

    xebec = _state(
        boot_mode=BootMode.IBM8088.value,
        machine_target=MachineTarget.MARTYPC_XEBEC.value,
    )
    assert f.FIELD_IBM_DOS_VERSION not in f.visible_fields(xebec)


def test_martypc_xebec_hides_size_format_bios():
    state = _state(machine_target=MachineTarget.MARTYPC_XEBEC.value)
    vis = f.visible_fields(state)
    assert f.FIELD_MARTYPC_XEBEC in vis
    assert f.FIELD_SIZE not in vis
    assert f.FIELD_FORMAT not in vis
    assert f.FIELD_BIOS_DRIVE not in vis
    assert f.FIELD_CUSTOM_PAYLOAD not in vis


def test_martypc_at_shows_at_dropdown_and_format():
    state = _state(machine_target=MachineTarget.MARTYPC_XTIDE.value)
    vis = f.visible_fields(state)
    assert f.FIELD_MARTYPC_AT in vis
    assert f.FIELD_FORMAT in vis  # AT keeps the format dropdown
    assert f.FIELD_SIZE not in vis  # but size is fixed by geometry
    assert f.FIELD_BIOS_DRIVE not in vis


# ── BIOS preset disable / effective size ───────────────────────────────────


def _first_bios_slug() -> str:
    spec = next(iter(iter_bios_drive_types(BIOSVendor.PHOENIX)))
    return spec.slug


def test_bios_preset_disables_and_fills_size():
    slug = _first_bios_slug()
    state = _state(bios_drive_type=slug)
    assert f.FIELD_SIZE in f.disabled_fields(state)
    # Effective size reflects the preset, not the raw 512M field.
    assert f.effective_size_text(state).endswith("M")


def test_custom_bios_leaves_size_enabled():
    state = _state(bios_drive_type="")
    assert f.FIELD_SIZE not in f.disabled_fields(state)
    assert f.effective_size_text(state) == "512M"


# ── Request building ───────────────────────────────────────────────────────


def test_request_requires_path():
    with pytest.raises(DosForgeError):
        f.build_create_request(dataclasses.replace(f.default_state(), output_path=""))


def test_vhd_request_basic():
    req = f.build_create_request(_state(size_text="256M"))
    assert req.media_type is MediaType.VHD
    assert req.size_bytes == 256 * 1024 * 1024
    assert req.disk_format is DiskFormat.FAT16


def test_ibm8088_coerces_512m_to_32m():
    req = f.build_create_request(
        _state(boot_mode=BootMode.IBM8088.value, size_text="512M")
    )
    assert req.size_bytes == 32 * 1024 * 1024


def test_ibm8088_keeps_explicit_size():
    req = f.build_create_request(
        _state(boot_mode=BootMode.IBM8088.value, size_text="128M")
    )
    assert req.size_bytes == 128 * 1024 * 1024


def test_img_request_uses_floppy_size_and_suppresses_boot():
    req = f.build_create_request(
        _state(
            media_type=MediaType.IMG.value,
            floppy_type=FloppyType.F1440K.value,
            boot_mode=BootMode.MSDOS5.value,  # ignored without system-format
            img_system_format=False,
        )
    )
    assert req.size_bytes == FloppyType.F1440K.size_bytes
    assert req.boot_mode is BootMode.NONE


def test_img_system_format_honors_boot_mode():
    req = f.build_create_request(
        _state(
            media_type=MediaType.IMG.value,
            img_system_format=True,
            boot_mode=BootMode.MSDOS33.value,
        )
    )
    assert req.boot_mode is BootMode.MSDOS33


def test_martypc_xebec_type1_is_fat12_with_fixed_size():
    req = f.build_create_request(
        _state(
            machine_target=MachineTarget.MARTYPC_XEBEC.value,
            martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE1.value,
        )
    )
    assert req.disk_format is DiskFormat.FAT12
    assert req.size_bytes == MartyPCXebecDriveType.TYPE1.size_bytes


def test_martypc_xebec_type2_is_fat16():
    req = f.build_create_request(
        _state(
            machine_target=MachineTarget.MARTYPC_XEBEC.value,
            martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2.value,
        )
    )
    assert req.disk_format is DiskFormat.FAT16
    assert req.size_bytes == MartyPCXebecDriveType.TYPE2.size_bytes


def test_martypc_at_uses_format_table_size():
    slug = DEFAULT_MARTYPC_AT_FORMAT_SLUG
    req = f.build_create_request(
        _state(machine_target=MachineTarget.MARTYPC_XTIDE.value, martypc_at_drive_type=slug)
    )
    assert req.size_bytes == lookup_martypc_at_format(slug).size_bytes


def test_custom_payload_allows_omitted_size():
    req = f.build_create_request(
        _state(size_text="", custom_payload="~/payload")
    )
    assert req.size_bytes == 1


def test_omitted_size_without_payload_raises():
    with pytest.raises(DosForgeError):
        f.build_create_request(_state(size_text=""))


def test_bios_preset_sets_request_tuple():
    slug = _first_bios_slug()
    req = f.build_create_request(_state(bios_drive_type=slug))
    assert req.bios_drive_type is not None
    assert req.bios_drive_type[0] in (BIOSVendor.PHOENIX, BIOSVendor.AMI)


# ── Coercions ──────────────────────────────────────────────────────────────


def test_coerce_media_to_img_resets_boot_and_machine():
    state = _state(
        media_type=MediaType.IMG.value,
        boot_mode=BootMode.MSDOS5.value,
        machine_target=MachineTarget.MARTYPC_XTIDE.value,
        img_system_format=True,
    )
    new = f.coerce_on_media_change(state)
    assert new.boot_mode == BootMode.NONE.value
    assert new.machine_target == MachineTarget.GENERIC.value
    assert new.img_system_format is False


def test_coerce_machine_to_xebec_type1_snaps_format_and_version():
    state = _state(
        machine_target=MachineTarget.MARTYPC_XEBEC.value,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE1.value,
        boot_mode=BootMode.MSDOS5.value,
    )
    new = f.coerce_on_machine_change(state)
    assert new.disk_format == DiskFormat.FAT12.value
    assert new.ibm_dos_version == IBMDOSVersion.DOS33.value
    assert new.boot_mode == BootMode.MSDOS33.value  # incompatible -> snapped


def test_coerce_xebec_drive_flip_to_type2_restores_fat16():
    state = _state(
        machine_target=MachineTarget.MARTYPC_XEBEC.value,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2.value,
        disk_format=DiskFormat.FAT12.value,
    )
    new = f.coerce_on_xebec_drive_change(state)
    assert new.disk_format == DiskFormat.FAT16.value


def test_coerce_boot_to_ibm8088_sets_default_size():
    new = f.coerce_on_boot_change(_state(boot_mode=BootMode.IBM8088.value, size_text="512M"))
    assert new.size_text == "32M"


def test_coerce_uncheck_system_format_clears_boot():
    state = _state(
        media_type=MediaType.IMG.value, img_system_format=False, boot_mode=BootMode.MSDOS5.value
    )
    new = f.coerce_on_img_system_format_change(state)
    assert new.boot_mode == BootMode.NONE.value


# ── Summary ────────────────────────────────────────────────────────────────


def test_summary_has_expected_rows():
    rows = dict(f.build_summary(_state(size_text="256M")))
    assert "VHD" in rows["Media"]
    assert rows["Overwrite"] == "no"
    assert rows["Output"].endswith("disk.vhd")
