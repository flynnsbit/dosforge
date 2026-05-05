from __future__ import annotations

from pathlib import Path

import pytest

from vhdmaker.disk import DiskManager
from vhdmaker.errors import ValidationError
from vhdmaker.models import BootMode, CreateRequest, DiskFormat, FreeDOSSource


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
