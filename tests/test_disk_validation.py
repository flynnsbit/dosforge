from __future__ import annotations

from pathlib import Path

import pytest

from vhdmaker.disk import DiskManager
from vhdmaker.errors import ValidationError
from vhdmaker.models import BootMode, CreateRequest, DiskFormat, FloppyType, FreeDOSSource, IBMDOSVersion, MediaType


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
    with pytest.raises(ValidationError, match="FAT16 only"):
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
