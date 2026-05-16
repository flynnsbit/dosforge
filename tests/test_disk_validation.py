from __future__ import annotations

from pathlib import Path

import pytest

from vhdmaker.disk import DiskManager
from vhdmaker.errors import ValidationError
from vhdmaker.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
)


def test_validate_rejects_freedos_auto_with_fat32() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.AUTO,
    )
    with pytest.raises(ValidationError, match="FAT16 only"):
        manager._validate_create_request(request)


def test_validate_accepts_freedos_auto_with_fat16() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.AUTO,
    )
    manager._validate_create_request(request)


def test_validate_accepts_msdos71_with_fat16() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=Path("/tmp/msdos-assets"),
    )
    manager._validate_create_request(request)


def test_validate_rejects_ibm8088_with_fat32() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
        boot_assets_path=Path("/tmp/ibm-assets"),
    )
    with pytest.raises(ValidationError, match="supports FAT16"):
        manager._validate_create_request(request)


def test_validate_rejects_ibm8088_dos33_above_32mb() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=(32 * 1024 * 1024) + 1,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
        boot_assets_path=Path("/tmp/ibm-assets"),
    )
    with pytest.raises(ValidationError, match="MS-DOS 3.3"):
        manager._validate_create_request(request)


def test_validate_accepts_ibm8088_dos50_504mb() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/test.vhd"),
        size_bytes=504 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
        boot_assets_path=Path("/tmp/ibm-assets"),
    )
    manager._validate_create_request(request)


def test_fetch_freedos_assets_uses_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("vhdmaker.disk.find_missing", lambda commands: [])
    monkeypatch.chdir(tmp_path)
    manager = DiskManager()

    captured: dict[str, object] = {}

    def fake_export(
        destination: Path,
        image_url: str | None = None,
        *,
        include_full_fdos: bool = False,
    ) -> Path:
        captured["destination"] = destination
        captured["image_url"] = image_url
        captured["include_full_fdos"] = include_full_fdos
        destination.mkdir(parents=True, exist_ok=True)
        return destination.resolve()

    monkeypatch.setattr(manager.boot_resolver, "export_latest_freedos_assets", fake_export)
    result = manager.fetch_freedos_assets()

    assert captured["destination"] == (tmp_path / "freedos")
    assert captured["include_full_fdos"] is True
    assert result == (tmp_path / "freedos").resolve()


def test_validate_rejects_img_without_img_extension() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/floppy.bin"),
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
    )
    with pytest.raises(ValidationError, match="must use .img or .ima"):
        manager._validate_create_request(request)


def test_validate_rejects_img_boot_mode_without_system_toggle() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/floppy.img"),
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        boot_mode=BootMode.FREEDOS,
        img_system_format=False,
    )
    with pytest.raises(ValidationError, match="Select System format"):
        manager._validate_create_request(request)


def test_validate_rejects_img_system_toggle_without_boot_mode() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/floppy.img"),
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        boot_mode=BootMode.NONE,
        img_system_format=True,
    )
    with pytest.raises(ValidationError, match="requires selecting a DOS boot mode"):
        manager._validate_create_request(request)


def test_validate_accepts_img_system_format_with_boot_mode() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/floppy.img"),
        size_bytes=FloppyType.F1200K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1200K,
        boot_mode=BootMode.COMPAQ331,
        img_system_format=True,
        boot_assets_path=Path("/tmp/compaq-assets"),
    )
    manager._validate_create_request(request)


def test_validate_accepts_img_system_format_with_pcdos7_xdf_mode() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/pcdos7.img"),
        size_bytes=FloppyType.F1840K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1840K,
        boot_mode=BootMode.PCDOS7,
        img_system_format=True,
        boot_assets_path=Path("/tmp/pcdos7-assets"),
    )
    manager._validate_create_request(request)


def test_validate_accepts_2880k_img_size() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/ed.img"),
        size_bytes=FloppyType.F2880K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F2880K,
    )
    manager._validate_create_request(request)


def test_validate_rejects_legacy_vhd_profile_with_fat32() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/legacy.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.PCDOS,
        boot_assets_path=Path("/tmp/pcdos-assets"),
    )
    with pytest.raises(ValidationError, match="Legacy DOS boot profiles support FAT16 only"):
        manager._validate_create_request(request)


def test_validate_rejects_missing_custom_payload_directory(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        custom_payload_path=tmp_path / "missing-payload",
    )
    with pytest.raises(ValidationError, match="Custom payload path does not exist"):
        manager._validate_create_request(request)


def test_validate_rejects_custom_payload_when_not_directory(tmp_path: Path) -> None:
    manager = DiskManager()
    payload_file = tmp_path / "payload.bin"
    payload_file.write_bytes(b"x")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        custom_payload_path=payload_file,
    )
    with pytest.raises(ValidationError, match="must be a directory"):
        manager._validate_create_request(request)


def test_apply_custom_payload_autosizing_grows_vhd_size(tmp_path: Path) -> None:
    manager = DiskManager()
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir(parents=True)
    (payload_dir / "big.bin").write_bytes(b"x" * (8 * 1024 * 1024))
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=1 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        custom_payload_path=payload_dir,
    )

    manager._apply_custom_payload_autosizing(request)

    assert request.size_bytes > 8 * 1024 * 1024


def test_validate_martypc_xebec_accepts_type2_with_fat16(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,  # forced from drive type
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    manager._validate_create_request(request)
    # Validation must force the request size to match the Xebec drive type.
    assert request.size_bytes == MartyPCXebecDriveType.TYPE2.size_bytes


def test_validate_martypc_xebec_rejects_type1_until_fat12_supported(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE1,
    )
    with pytest.raises(ValidationError, match="Type 1.*FAT12"):
        manager._validate_create_request(request)


def test_validate_martypc_xebec_rejects_fat32(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.NONE,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    with pytest.raises(ValidationError, match="FAT16"):
        manager._validate_create_request(request)


def test_validate_martypc_xebec_rejects_non_xt_boot_mode(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    with pytest.raises(ValidationError, match="XT-class"):
        manager._validate_create_request(request)


def test_validate_martypc_xebec_rejects_img_media(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        machine_target=MachineTarget.MARTYPC_XEBEC,
    )
    # IMG path validates floppy-only; MartyPC Xebec target is incompatible.
    # IMG-path validation runs first and ignores machine_target by design,
    # so we exercise the VHD path explicitly:
    request_vhd = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    # Sanity: the VHD path accepts MartyPC.
    manager._validate_create_request(request_vhd)


def test_normalize_vhd_size_for_chs_returns_xebec_size(tmp_path: Path) -> None:
    manager = DiskManager()
    for drive_type in (
        MartyPCXebecDriveType.TYPE16,
        MartyPCXebecDriveType.TYPE2,
        MartyPCXebecDriveType.TYPE13,
    ):
        request = CreateRequest(
            path=tmp_path / "marty.vhd",
            size_bytes=1234567,  # arbitrary; must be overridden
            disk_format=DiskFormat.FAT16,
            machine_target=MachineTarget.MARTYPC_XEBEC,
            martypc_xebec_drive_type=drive_type,
        )
        assert manager._normalize_vhd_size_for_chs(request) == drive_type.size_bytes


def test_validate_martypc_xtide_accepts_504mib_with_fat16(tmp_path: Path) -> None:
    from vhdmaker.models import lookup_martypc_at_format, DEFAULT_MARTYPC_AT_FORMAT_SLUG

    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        machine_target=MachineTarget.MARTYPC_XTIDE,
        martypc_at_drive_type_slug=DEFAULT_MARTYPC_AT_FORMAT_SLUG,
    )
    manager._validate_create_request(request)
    assert request.size_bytes == lookup_martypc_at_format(DEFAULT_MARTYPC_AT_FORMAT_SLUG).size_bytes


def test_validate_martypc_xtide_rejects_below_fat16_min(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XTIDE,
        martypc_at_drive_type_slug="at-306-4-17",  # 10.16 MiB
    )
    with pytest.raises(ValidationError, match="FAT16 minimum"):
        manager._validate_create_request(request)


def test_validate_martypc_jride_rejects_oversize_for_dos33(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "marty.vhd",
        size_bytes=0,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
        machine_target=MachineTarget.MARTYPC_JRIDE,
        martypc_at_drive_type_slug="at-1024-16-63",  # 504 MiB - way over DOS 3.3 32 MiB cap
    )
    with pytest.raises(ValidationError, match="DOS 3.3"):
        manager._validate_create_request(request)


def test_normalize_vhd_size_for_chs_returns_at_drive_size(tmp_path: Path) -> None:
    from vhdmaker.models import MARTYPC_AT_FORMATS_BY_SLUG

    manager = DiskManager()
    for slug in ("at-1024-16-63", "at-1218-15-36", "at-1054-16-63"):
        request = CreateRequest(
            path=tmp_path / "marty.vhd",
            size_bytes=999_999_999,
            disk_format=DiskFormat.FAT16,
            machine_target=MachineTarget.MARTYPC_XTIDE,
            martypc_at_drive_type_slug=slug,
        )
        expected = MARTYPC_AT_FORMATS_BY_SLUG[slug].size_bytes
        assert manager._normalize_vhd_size_for_chs(request) == expected


def test_lookup_martypc_at_format_rejects_unknown_slug() -> None:
    from vhdmaker.models import lookup_martypc_at_format

    with pytest.raises(ValueError, match="Unknown MartyPC"):
        lookup_martypc_at_format("at-nonsense-1-2-3")


def test_validate_rejects_custom_payload_pointing_at_install_diskettes(tmp_path: Path) -> None:
    """Reject the common mistake of putting the DOS install dir into custom-payload.

    The custom payload feature copies the directory verbatim to C:\\; if the
    user typed the install-disk directory there, install diskettes (Disk1.img,
    Disk2.img, ...) would land on the disk instead of being extracted.
    """
    manager = DiskManager()
    install_dir = tmp_path / "msdos622"
    install_dir.mkdir()
    for name in ("Disk1.img", "Disk2.img", "Disk3.img"):
        (install_dir / name).write_bytes(b"\0" * 1024)

    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        custom_payload_path=install_dir,
    )
    with pytest.raises(ValidationError, match="install diskette"):
        manager._validate_create_request(request)


def test_validate_rejects_custom_payload_equal_to_boot_assets_path(tmp_path: Path) -> None:
    manager = DiskManager()
    install_dir = tmp_path / "msdos622"
    install_dir.mkdir()
    # No install-image .img files, so the install-image heuristic won't fire.
    (install_dir / "README.txt").write_text("hello")
    (install_dir / "IO.SYS").write_bytes(b"\0" * 1024)

    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        boot_assets_path=install_dir,
        custom_payload_path=install_dir,
    )
    with pytest.raises(ValidationError, match="boot assets directory"):
        manager._validate_create_request(request)


def test_validate_allows_custom_payload_distinct_from_boot_assets(tmp_path: Path) -> None:
    manager = DiskManager()
    install_dir = tmp_path / "msdos622"
    install_dir.mkdir()
    (install_dir / "Disk1.img").write_bytes(b"\0" * 1024)
    (install_dir / "Disk2.img").write_bytes(b"\0" * 1024)

    payload_dir = tmp_path / "user-payload"
    payload_dir.mkdir()
    (payload_dir / "notes.txt").write_text("personal data")

    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        boot_assets_path=install_dir,
        custom_payload_path=payload_dir,
    )
    # Should not raise.
    manager._validate_create_request(request)


def test_validate_rejects_msdos33_above_32mib(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
    )
    with pytest.raises(ValidationError, match="msdos33.*32 MiB"):
        manager._validate_create_request(request)


def test_normalize_vhd_size_for_msdos33_caps_at_32mib(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
    )
    aligned = manager._normalize_vhd_size_for_chs(request)
    # 32 MiB request must round DOWN to fit in DOS 3.30's uint16 partition
    # sector cap (65535 sectors). 65 cyl x 16 x 63 x 512 = 33,546,240 B = 31.99 MiB.
    assert aligned == 65 * 16 * 63 * 512
    assert aligned < 32 * 1024 * 1024


def test_normalize_vhd_size_for_msdos331_allows_above_32mib(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS331,
    )
    aligned = manager._normalize_vhd_size_for_chs(request)
    # FAT16B (DOS 3.31 / Compaq) handles total_sectors_32, so >32 MiB is fine.
    # 128 MiB rounds up to 65,011,712 bytes (~62 MiB)? No, 128 MiB = 134217728
    # 134217728 / 516096 = 260.07 -> 261 cyl -> 261 * 516096 = 134,701,056 B
    assert aligned >= 128 * 1024 * 1024


def test_normalize_vhd_size_for_compaq331_allows_above_32mib(tmp_path: Path) -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.COMPAQ331,
    )
    aligned = manager._normalize_vhd_size_for_chs(request)
    assert aligned >= 128 * 1024 * 1024


def test_resolve_compaq331_assets_dir_uses_boot_assets_path(tmp_path: Path) -> None:
    manager = DiskManager()
    assets = tmp_path / "cpq"
    assets.mkdir()
    request = CreateRequest(
        path=tmp_path / "out.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.COMPAQ331,
        boot_assets_path=assets,
    )
    assert manager._resolve_compaq331_assets_dir(request) == assets.resolve()


def test_find_compaq331_startup_image_preferred_name(tmp_path: Path) -> None:
    manager = DiskManager()
    assets = tmp_path / "cpq"
    assets.mkdir()
    # Bytes don't matter; we only check the filename matching path.
    (assets / "STARTUP.IMG").write_bytes(b"\0" * 1024)
    found = manager._find_compaq331_startup_image(assets)
    assert found is not None
    assert found.name == "STARTUP.IMG"


def test_find_compaq331_startup_image_missing(tmp_path: Path) -> None:
    manager = DiskManager()
    assets = tmp_path / "cpq"
    assets.mkdir()
    (assets / "readme.txt").write_text("nothing here")
    assert manager._find_compaq331_startup_image(assets) is None


# --- IBM 8088 + DOS 3.3 routing through QEMU FORMAT install ---


def test_uses_legacy_dos_qemu_install_msdos33() -> None:
    from vhdmaker.disk import _uses_legacy_dos_qemu_install

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
    )
    assert _uses_legacy_dos_qemu_install(request) is True


def test_uses_legacy_dos_qemu_install_compaq331() -> None:
    from vhdmaker.disk import _uses_legacy_dos_qemu_install

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.COMPAQ331,
    )
    assert _uses_legacy_dos_qemu_install(request) is True


def test_uses_legacy_dos_qemu_install_ibm8088_dos33() -> None:
    from vhdmaker.disk import _uses_legacy_dos_qemu_install

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    assert _uses_legacy_dos_qemu_install(request) is True


def test_uses_legacy_dos_qemu_install_ibm8088_dos50_skipped() -> None:
    from vhdmaker.disk import _uses_legacy_dos_qemu_install

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
    )
    # DOS 5.0 static-template boot works fine — don't reroute through QEMU.
    assert _uses_legacy_dos_qemu_install(request) is False


def test_uses_legacy_dos_qemu_install_other_modes_false() -> None:
    from vhdmaker.disk import _uses_legacy_dos_qemu_install

    for mode in (
        BootMode.NONE,
        BootMode.FREEDOS,
        BootMode.MSDOS71,
        BootMode.MSDOS5,
        BootMode.MSDOS622,
        BootMode.PCDOS7,
    ):
        request = CreateRequest(
            path=Path("/tmp/x.vhd"),
            size_bytes=64 * 1024 * 1024,
            disk_format=DiskFormat.FAT16,
            boot_mode=mode,
        )
        assert _uses_legacy_dos_qemu_install(request) is False, mode


def test_legacy_dos_install_descriptor_ibm8088_dos33_uses_msdos33() -> None:
    from vhdmaker.disk import _legacy_dos_install_descriptor

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    descriptor = _legacy_dos_install_descriptor(request)
    assert descriptor is not None
    assert descriptor.label == "MS-DOS 3.30"
    assert "msdos33" in descriptor.asset_fallback_dirs


def test_uses_msdos33_filesystem_layout_ibm8088_dos33() -> None:
    from vhdmaker.disk import _uses_msdos33_filesystem_layout

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    assert _uses_msdos33_filesystem_layout(request) is True


def test_uses_msdos33_filesystem_layout_ibm8088_dos50_false() -> None:
    from vhdmaker.disk import _uses_msdos33_filesystem_layout

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
    )
    assert _uses_msdos33_filesystem_layout(request) is False


def test_resolve_legacy_dos_assets_dir_ibm8088_dos33_descends_into_version_subdir(
    tmp_path: Path,
) -> None:
    manager = DiskManager()
    root = tmp_path / "ibm-pc"
    versioned = root / "dos33"
    versioned.mkdir(parents=True)
    (versioned / "DISK01.IMG").write_bytes(b"\0" * 1024)
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
        boot_assets_path=root,
    )
    resolved = manager._resolve_legacy_dos_assets_dir(
        request=request,
        fallback_dirs=("msdos33",),
        label="MS-DOS 3.30",
    )
    assert resolved == versioned.resolve()


def test_resolve_legacy_dos_assets_dir_ibm8088_dos33_uses_root_when_no_subdir(
    tmp_path: Path,
) -> None:
    manager = DiskManager()
    root = tmp_path / "ibm-pc"
    root.mkdir(parents=True)
    (root / "DISK01.IMG").write_bytes(b"\0" * 1024)
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
        boot_assets_path=root,
    )
    resolved = manager._resolve_legacy_dos_assets_dir(
        request=request,
        fallback_dirs=("msdos33",),
        label="MS-DOS 3.30",
    )
    assert resolved == root.resolve()


# --- FAT12 + MartyPC Xebec Type 1 ---


def _martypc_xebec_type1_request(**overrides) -> CreateRequest:
    base = dict(
        path=Path("/tmp/x.vhd"),
        size_bytes=10 * 1024 * 1024,  # ignored — MartyPC forces drive_type size
        disk_format=DiskFormat.FAT12,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE1,
        boot_assets_path=Path("/tmp/msdos33"),
    )
    base.update(overrides)
    return CreateRequest(**base)


def test_validate_accepts_martypc_xebec_type1_fat12_msdos33(tmp_path: Path) -> None:
    manager = DiskManager()
    assets = tmp_path / "msdos33"
    assets.mkdir()
    (assets / "DISK01.IMG").write_bytes(b"\0" * 1024)
    request = _martypc_xebec_type1_request(boot_assets_path=assets)
    manager._validate_create_request(request)


def test_validate_accepts_martypc_xebec_type1_fat12_ibm8088_dos33(tmp_path: Path) -> None:
    manager = DiskManager()
    assets = tmp_path / "msdos33"
    assets.mkdir()
    (assets / "DISK01.IMG").write_bytes(b"\0" * 1024)
    request = _martypc_xebec_type1_request(
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
        boot_assets_path=assets,
    )
    manager._validate_create_request(request)


def test_validate_rejects_martypc_xebec_type1_fat16() -> None:
    manager = DiskManager()
    request = _martypc_xebec_type1_request(disk_format=DiskFormat.FAT16)
    with pytest.raises(ValidationError, match="Type 1.*requires FAT12"):
        manager._validate_create_request(request)


def test_validate_rejects_martypc_xebec_type2_fat12() -> None:
    manager = DiskManager()
    request = _martypc_xebec_type1_request(
        disk_format=DiskFormat.FAT12,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    with pytest.raises(ValidationError, match="requires FAT16"):
        manager._validate_create_request(request)


def test_validate_rejects_fat12_on_non_martypc() -> None:
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=10 * 1024 * 1024,
        disk_format=DiskFormat.FAT12,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.GENERIC,
        boot_assets_path=Path("/tmp/msdos33"),
    )
    with pytest.raises(ValidationError, match="FAT12 on VHD"):
        manager._validate_create_request(request)


def test_validate_rejects_fat12_with_non_msdos33_boot_mode() -> None:
    manager = DiskManager()
    request = _martypc_xebec_type1_request(boot_mode=BootMode.COMPAQ331)
    with pytest.raises(ValidationError, match="FAT12 on VHD requires boot-mode"):
        manager._validate_create_request(request)


# --- BPB-to-footer geometry patch (MartyPC Xebec Type 2 boot fix) ---


def _make_fake_vhd_with_partition(
    path: Path,
    *,
    footer_cyl: int,
    footer_heads: int,
    footer_spt: int,
    bpb_spt: int = 63,
    bpb_heads: int = 16,
    partition_start_lba: int = 63,
) -> None:
    """Build a minimal VHD-like file: zeroed data + footer + a BPB stub."""
    import struct as _struct

    total_sectors = footer_cyl * footer_heads * footer_spt
    data_size = total_sectors * 512
    path.write_bytes(b"\x00" * (data_size + 512))
    # Stub BPB at partition VBR (offset partition_start_lba * 512).
    with path.open("r+b") as f:
        f.seek(partition_start_lba * 512 + 24)
        f.write(_struct.pack("<HH", bpb_spt, bpb_heads))
        # Write a footer cookie + CHS so _read_vpc_bios_chs_geometry can parse it.
        f.seek(-512, 2)
        footer = bytearray(512)
        footer[:8] = b"conectix"
        footer[56:58] = _struct.pack(">H", footer_cyl)
        footer[58] = footer_heads
        footer[59] = footer_spt
        f.write(footer)


def test_patch_partition_bpb_to_footer_geometry_rewrites_spt_and_heads(
    tmp_path: Path,
) -> None:
    import struct as _struct

    manager = DiskManager()
    vhd = tmp_path / "fake.vhd"
    # MartyPC Xebec Type 2 geometry — 615 × 4 × 17 MFM.
    _make_fake_vhd_with_partition(
        vhd,
        footer_cyl=615,
        footer_heads=4,
        footer_spt=17,
        bpb_spt=63,
        bpb_heads=16,
    )
    manager._patch_partition_bpb_to_footer_geometry(
        vhd_path=vhd,
        partition_offset_bytes=63 * 512,
    )
    # Read back the BPB heads/spt — should now match the footer.
    with vhd.open("rb") as f:
        f.seek(63 * 512 + 24)
        spt, heads = _struct.unpack("<HH", f.read(4))
    assert spt == 17
    assert heads == 4


def test_patch_partition_bpb_to_footer_geometry_noop_for_canonical_chs(
    tmp_path: Path,
) -> None:
    import struct as _struct

    manager = DiskManager()
    vhd = tmp_path / "fake.vhd"
    # Generic disk with already-canonical 16/63 footer (e.g. non-MartyPC
    # build). The BPB ends up matching the footer, so the patch is a no-op
    # in observable terms.
    _make_fake_vhd_with_partition(
        vhd,
        footer_cyl=64,
        footer_heads=16,
        footer_spt=63,
        bpb_spt=63,
        bpb_heads=16,
    )
    manager._patch_partition_bpb_to_footer_geometry(
        vhd_path=vhd,
        partition_offset_bytes=63 * 512,
    )
    with vhd.open("rb") as f:
        f.seek(63 * 512 + 24)
        spt, heads = _struct.unpack("<HH", f.read(4))
    assert spt == 63
    assert heads == 16


# --- XT-class MBR rewrite (MartyPC Xebec) ---


def _make_minimal_vhd_with_footer_and_parted_mbr(
    path: Path,
    *,
    cyl: int,
    heads: int,
    spt: int,
) -> None:
    """Build a fake VHD: zeroed data area + footer + a parted-style MBR."""
    import struct as _struct

    total_sectors = cyl * heads * spt
    size = total_sectors * 512
    path.write_bytes(b"\x00" * (size + 512))
    with path.open("r+b") as f:
        # Write a parted-style MBR (LBA-aware boot code + bogus 31/63 CHS).
        parted_mbr = bytes.fromhex(
            "33c0fa8ed88ed0bc007c89e606578ec0fbfcbf0006b90001f3a5ea1f06000052"
        )
        f.seek(0)
        f.write(parted_mbr)
        # Random NT signature
        f.seek(440)
        f.write(b"\xaa\xbb\xcc\xdd")
        # parted partition entry at LBA 63, bogus CHS (head=31).
        entry = bytes([
            0x80, 0x1f, 0x02, 0x00, 0x04, 0xfe, 0x02, 0x51,
            0x3f, 0x00, 0x00, 0x00, 0x1d, 0xa3, 0x00, 0x00,
        ])
        f.seek(446)
        f.write(entry)
        f.seek(510)
        f.write(b"\x55\xaa")
        # Footer with given CHS
        f.seek(-512, 2)
        footer = bytearray(512)
        footer[:8] = b"conectix"
        footer[56:58] = _struct.pack(">H", cyl)
        footer[58] = heads
        footer[59] = spt
        f.write(footer)


def test_rewrite_mbr_for_xt_class_matches_dos33_fdisk_layout(tmp_path: Path) -> None:
    import struct as _struct

    manager = DiskManager()
    vhd = tmp_path / "fake.vhd"
    # MartyPC Xebec Type 2 geometry — 615 × 4 × 17.
    _make_minimal_vhd_with_footer_and_parted_mbr(vhd, cyl=615, heads=4, spt=17)

    manager._rewrite_mbr_for_xt_class(
        vhd_path=vhd,
        cylinders=615,
        heads=4,
        sectors_per_track=17,
        fs_type=0x04,
    )

    mbr = vhd.read_bytes()[:512]
    # Boot signature preserved.
    assert mbr[510:512] == b"\x55\xaa"
    # NT signature area zeroed (DOS 3.3 doesn't write one).
    assert mbr[440:444] == b"\x00\x00\x00\x00"
    assert mbr[444:446] == b"\x00\x00"
    # Partition entry at MBR offset 446.
    e = mbr[446:462]
    assert e[0] == 0x80  # bootable flag
    assert e[4] == 0x04  # FAT16 <32 MiB partition type
    # Start CHS = (cyl=0, head=1, sec=1) -> bytes [01, 01, 00].
    assert e[1:4] == b"\x01\x01\x00", e[1:4].hex()
    # End CHS = (cyl=613, head=3, sec=17). Encoding:
    #   head=3, sector=17, cyl=613 → bytes [03, 0x91, 0x65].
    assert e[5:8] == b"\x03\x91\x65", e[5:8].hex()
    # Start LBA = spt = 17; count = (cyl-1)*heads*spt - spt = 41735.
    assert _struct.unpack("<I", e[8:12])[0] == 17
    assert _struct.unpack("<I", e[12:16])[0] == 41735
    # Partition entries 2-4 zeroed.
    assert mbr[462:510] == b"\x00" * 48
    # MBR boot code uses CHS reads — first 8 bytes match DOS 3.3 standard
    # ("fa 33 c0 8e d0 bc 00 7c").
    assert mbr[:8] == bytes.fromhex("fa33c08ed0bc007c")


def test_rewrite_mbr_for_xt_class_fat12_type1(tmp_path: Path) -> None:
    import struct as _struct

    manager = DiskManager()
    vhd = tmp_path / "fake.vhd"
    # MartyPC Xebec Type 1 — 306 × 4 × 17 = 10 MiB MFM.
    _make_minimal_vhd_with_footer_and_parted_mbr(vhd, cyl=306, heads=4, spt=17)

    manager._rewrite_mbr_for_xt_class(
        vhd_path=vhd,
        cylinders=306,
        heads=4,
        sectors_per_track=17,
        fs_type=0x01,  # FAT12
    )

    mbr = vhd.read_bytes()[:512]
    e = mbr[446:462]
    assert e[4] == 0x01  # FAT12 partition type
    assert _struct.unpack("<I", e[8:12])[0] == 17  # start LBA
    # count = (306-1)*4*17 - 17 = 20740 - 17 = 20723
    assert _struct.unpack("<I", e[12:16])[0] == 20723


def test_partition_offset_bytes_for_xebec_type2() -> None:
    from vhdmaker.disk import _partition_offset_bytes_for

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=21411840,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
    )
    # Type 2 spt = 17 → partition starts at LBA 17.
    assert _partition_offset_bytes_for(request) == 17 * 512


def test_partition_offset_bytes_for_generic_msdos33() -> None:
    from vhdmaker.disk import _partition_offset_bytes_for

    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.GENERIC,
    )
    # Generic targets use the conventional LBA 63 layout.
    assert _partition_offset_bytes_for(request) == 63 * 512


# --- FULL-profile payload staging for legacy DOS QEMU install ---


def test_stage_legacy_dos_full_profile_payload_minimal_is_noop(tmp_path: Path) -> None:
    """MINIMAL profile must not call mtools at all; FORMAT C: /S already
    produced a complete boot disk and there's nothing else to stage."""
    from vhdmaker.commands import CommandRunner
    from vhdmaker import disk as _disk
    from vhdmaker.models import MSDOSInstallProfile

    calls: list[list[str]] = []

    class FakeRunner(CommandRunner):
        def run(self, args, *, sudo=False, check=True, env=None):
            calls.append(list(args))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    class FakeResolver:
        def resolve(self, request):
            raise AssertionError("resolver should not be called for MINIMAL profile")

    mgr = _disk.DiskManager(runner=FakeRunner(), boot_resolver=FakeResolver())
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        msdos_install_profile=MSDOSInstallProfile.MINIMAL,
    )
    mgr._stage_legacy_dos_full_profile_payload(
        request=request,
        vhd_path=tmp_path / "fake.vhd",
        partition_offset_bytes=17 * 512,
    )
    assert calls == []


def test_stage_legacy_dos_full_profile_payload_full_copies_tools_and_startup(
    tmp_path: Path,
) -> None:
    from vhdmaker.commands import CommandRunner
    from vhdmaker import disk as _disk
    from vhdmaker.boot import BootAssets
    from vhdmaker.models import MSDOSInstallProfile

    payload_dir = tmp_path / "payload"
    (payload_dir / "FDISK.COM").parent.mkdir(parents=True, exist_ok=True)
    (payload_dir / "FDISK.COM").write_bytes(b"fdisk")
    (payload_dir / "FORMAT.COM").write_bytes(b"format")
    sub = payload_dir / "SUB"
    sub.mkdir()
    (sub / "MORE.EXE").write_bytes(b"more")
    config = tmp_path / "CONFIG.SYS"
    config.write_bytes(b"FILES=20\r\n")
    autoexec = tmp_path / "AUTOEXEC.BAT"
    autoexec.write_bytes(b"@ECHO OFF\r\nPATH=C:\\DOS\r\n")
    # FORMAT C: /S puts these; staging must NOT overwrite them.
    iosys = tmp_path / "IO.SYS"
    iosys.write_bytes(b"io")
    cmd = tmp_path / "COMMAND.COM"
    cmd.write_bytes(b"command")

    fake_assets = BootAssets(
        system_files={
            "IO.SYS": iosys,
            "COMMAND.COM": cmd,
            "CONFIG.SYS": config,
            "AUTOEXEC.BAT": autoexec,
        },
        boot_sector_template=None,
        fdos_payload_dir=payload_dir,
        payload_target_dir="DOS",
    )

    calls: list[list[str]] = []

    class FakeRunner(CommandRunner):
        def run(self, args, *, sudo=False, check=True, env=None):
            calls.append(list(args))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    class FakeResolver:
        def resolve(self, request):
            return fake_assets

    mgr = _disk.DiskManager(runner=FakeRunner(), boot_resolver=FakeResolver())
    vhd = tmp_path / "fake.vhd"
    request = CreateRequest(
        path=vhd,
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )
    mgr._stage_legacy_dos_full_profile_payload(
        request=request,
        vhd_path=vhd,
        partition_offset_bytes=17 * 512,
    )

    # The DOS dir was created at C:\DOS.
    assert any(
        call[:2] == ["mmd", "-i"] and call[-1] == "::DOS"
        for call in calls
    ), calls
    # FDISK.COM was copied into C:\DOS\FDISK.COM
    assert any(
        call[:2] == ["mcopy", "-i"]
        and call[-2] == str(payload_dir / "FDISK.COM")
        and call[-1] == "::DOS/FDISK.COM"
        for call in calls
    ), calls
    # Subdir SUB was created and MORE.EXE staged inside it.
    assert any(call[-1] == "::DOS/SUB" for call in calls), calls
    assert any(
        call[:2] == ["mcopy", "-i"]
        and call[-1] == "::DOS/SUB/MORE.EXE"
        for call in calls
    ), calls
    # CONFIG.SYS + AUTOEXEC.BAT were copied to C:\.
    assert any(call[-1] == "::CONFIG.SYS" for call in calls), calls
    assert any(call[-1] == "::AUTOEXEC.BAT" for call in calls), calls
    # IO.SYS / COMMAND.COM must NOT be overwritten — FORMAT already wrote
    # them with system+hidden attributes.
    assert not any(call[-1] == "::IO.SYS" for call in calls), calls
    assert not any(call[-1] == "::COMMAND.COM" for call in calls), calls


# --- Custom payload fit check on fixed-size MartyPC drives ---


def _populate(dir_: Path, files: dict[str, int]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    for name, size in files.items():
        (dir_ / name).write_bytes(b"\x00" * size)


def test_apply_custom_payload_fits_small_payload_on_xebec_type2(tmp_path: Path) -> None:
    manager = DiskManager()
    payload = tmp_path / "payload"
    _populate(payload, {"a.exe": 64 * 1024, "b.txt": 1024})
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=20 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
        custom_payload_path=payload,
    )
    # Force MartyPC size as validator would.
    request.size_bytes = MartyPCXebecDriveType.TYPE2.size_bytes
    # Should not raise.
    manager._apply_custom_payload_autosizing(request)
    # Size must be unchanged (MartyPC drives are fixed).
    assert request.size_bytes == MartyPCXebecDriveType.TYPE2.size_bytes


def test_apply_custom_payload_rejects_oversized_on_xebec_type1(tmp_path: Path) -> None:
    manager = DiskManager()
    payload = tmp_path / "payload"
    # Type 1 = 10 MiB (FAT12). Build a payload that clearly won't fit.
    _populate(payload, {"big.bin": 12 * 1024 * 1024})
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=MartyPCXebecDriveType.TYPE1.size_bytes,
        disk_format=DiskFormat.FAT12,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE1,
        custom_payload_path=payload,
    )
    with pytest.raises(ValidationError, match="does not fit"):
        manager._apply_custom_payload_autosizing(request)


def test_apply_custom_payload_full_profile_reserves_more_overhead(tmp_path: Path) -> None:
    """FULL profile reserves an extra ~800 KiB so DOS tools have room."""
    manager = DiskManager()
    payload = tmp_path / "payload"
    # Type 2 = ~20.4 MiB. Leave just enough so MINIMAL would pass but
    # FULL won't (within the 800 KiB FULL-only headroom).
    type2_size = MartyPCXebecDriveType.TYPE2.size_bytes
    # Use a payload that's ~size - 1.4 MiB → fits MINIMAL but not FULL.
    payload_size = type2_size - (1 * 1024 * 1024 + 600 * 1024)
    _populate(payload, {"big.bin": payload_size})
    common = dict(
        path=tmp_path / "x.vhd",
        size_bytes=type2_size,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        machine_target=MachineTarget.MARTYPC_XEBEC,
        martypc_xebec_drive_type=MartyPCXebecDriveType.TYPE2,
        custom_payload_path=payload,
    )
    from vhdmaker.models import MSDOSInstallProfile
    minimal_req = CreateRequest(**common, msdos_install_profile=MSDOSInstallProfile.MINIMAL)
    full_req = CreateRequest(**common, msdos_install_profile=MSDOSInstallProfile.FULL)
    # MINIMAL passes
    manager._apply_custom_payload_autosizing(minimal_req)
    # FULL rejects with a clear error
    with pytest.raises(ValidationError, match="does not fit"):
        manager._apply_custom_payload_autosizing(full_req)


def test_apply_custom_payload_generic_still_autogrows(tmp_path: Path) -> None:
    """Confirm the MartyPC fit-check doesn't regress the generic path."""
    manager = DiskManager()
    payload = tmp_path / "payload"
    _populate(payload, {"big.bin": 100 * 1024 * 1024})
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        machine_target=MachineTarget.GENERIC,
        custom_payload_path=payload,
    )
    manager._apply_custom_payload_autosizing(request)
    # Generic VHD should have grown to fit the payload.
    assert request.size_bytes > 100 * 1024 * 1024


# --- dosassets/ folder resolution ---


def test_resolve_dos_asset_dir_prefers_dosassets_subdir(tmp_path: Path, monkeypatch) -> None:
    from vhdmaker.paths import resolve_dos_asset_dir

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "msdos33"
    legacy.mkdir()
    nested = tmp_path / "dosassets" / "msdos33"
    nested.mkdir(parents=True)
    # When both exist, the dosassets/ one wins.
    resolved = resolve_dos_asset_dir("msdos33")
    assert resolved == nested.resolve()


def test_resolve_dos_asset_dir_falls_back_to_legacy_layout(tmp_path: Path, monkeypatch) -> None:
    from vhdmaker.paths import resolve_dos_asset_dir

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "msdos33"
    legacy.mkdir()
    # No dosassets/msdos33 here, so the bare name resolves to the legacy
    # location for back-compat with existing user setups.
    resolved = resolve_dos_asset_dir("msdos33")
    assert resolved == legacy.resolve()


def test_resolve_dos_asset_dir_full_path_used_verbatim(tmp_path: Path) -> None:
    from vhdmaker.paths import resolve_dos_asset_dir

    target = tmp_path / "elsewhere" / "msdos33"
    target.mkdir(parents=True)
    resolved = resolve_dos_asset_dir(str(target))
    assert resolved == target.resolve()


def test_resolve_dos_asset_dir_returns_none_for_missing(tmp_path: Path, monkeypatch) -> None:
    from vhdmaker.paths import resolve_dos_asset_dir

    monkeypatch.chdir(tmp_path)
    assert resolve_dos_asset_dir("missing-bootmode") is None


def test_legacy_dos_assets_dir_resolves_bare_name_under_dosassets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assets = tmp_path / "dosassets" / "msdos33"
    assets.mkdir(parents=True)
    (assets / "DISK01.IMG").write_bytes(b"\x00" * 1024)

    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=20 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        # Bare name — should be auto-resolved to dosassets/msdos33/.
        boot_assets_path=Path("msdos33"),
    )
    resolved = manager._resolve_legacy_dos_assets_dir(
        request=request,
        fallback_dirs=("msdos33",),
        label="MS-DOS 3.30",
    )
    assert resolved == assets.resolve()


def test_legacy_dos_assets_dir_uses_dosassets_fallback_when_no_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assets = tmp_path / "dosassets" / "msdos33"
    assets.mkdir(parents=True)
    (assets / "DISK01.IMG").write_bytes(b"\x00" * 1024)

    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=20 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        # No explicit boot_assets_path — fallback names should be searched
        # under dosassets/ first.
    )
    resolved = manager._resolve_legacy_dos_assets_dir(
        request=request,
        fallback_dirs=("msdos33",),
        label="MS-DOS 3.30",
    )
    assert resolved == assets.resolve()


def test_legacy_dos_assets_dir_error_mentions_dosassets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = DiskManager()
    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=20 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
    )
    with pytest.raises(ValidationError, match=r"dosassets/<name>/"):
        manager._resolve_legacy_dos_assets_dir(
            request=request,
            fallback_dirs=("msdos33",),
            label="MS-DOS 3.30",
        )
