from __future__ import annotations

import struct
from pathlib import Path

import pytest

from vhdmaker.boot import (
    BootAssetResolver,
    normalize_freedos_autoexec_bat,
    normalize_freedos_config_sys,
)
from vhdmaker.commands import CommandRunner
from vhdmaker.errors import ValidationError
from vhdmaker.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
)


def _touch(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _make_freedos_fat32_vhd(path: Path) -> None:
    size = 512 * 600
    payload = bytearray(size)
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xaa"
    start_lba = 63
    p1 = bytearray(16)
    p1[0] = 0x80
    p1[4] = 0x0B
    p1[8:12] = struct.pack("<I", start_lba)
    p1[12:16] = struct.pack("<I", 500)
    mbr[446:462] = p1
    payload[:512] = mbr

    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x58\x90"
    pbs[3:11] = b"FRDOS5.1"
    pbs[510:512] = b"\x55\xaa"
    pbs[80:91] = b"KERNEL  SYS"
    payload[start_lba * 512 : (start_lba + 1) * 512] = pbs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _make_freedos_fat16_vhd(path: Path) -> None:
    size = 512 * 600
    payload = bytearray(size)
    mbr = bytearray(512)
    mbr[:440] = bytes(((index % 251) + 1 for index in range(440)))
    mbr[510:512] = b"\x55\xaa"
    start_lba = 63
    p1 = bytearray(16)
    p1[0] = 0x80
    p1[4] = 0x0E
    p1[8:12] = struct.pack("<I", start_lba)
    p1[12:16] = struct.pack("<I", 500)
    mbr[446:462] = p1
    payload[:512] = mbr

    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x3c\x90"
    pbs[3:11] = b"FRDOS5.1"
    pbs[54:62] = b"FAT16   "
    pbs[80:91] = b"KERNEL  SYS"
    pbs[510:512] = b"\x55\xaa"
    payload[start_lba * 512 : (start_lba + 1) * 512] = pbs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _freedos_fat16_boot_sector_bytes() -> bytes:
    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x3c\x90"
    pbs[3:11] = b"FRDOS5.1"
    pbs[54:62] = b"FAT16   "
    pbs[80:91] = b"KERNEL  SYS"
    pbs[510:512] = b"\x55\xaa"
    return bytes(pbs)


def _msdos_fat32_boot_sector_bytes() -> bytes:
    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x58\x90"
    pbs[3:11] = b"MSWIN4.1"
    pbs[11:13] = struct.pack("<H", 512)
    pbs[13] = 8
    pbs[14:16] = struct.pack("<H", 32)
    pbs[16] = 2
    pbs[21] = 0xF8
    pbs[24:26] = struct.pack("<H", 63)
    pbs[26:28] = struct.pack("<H", 255)
    pbs[32:36] = struct.pack("<I", 4096)
    pbs[36:40] = struct.pack("<I", 128)
    pbs[44:48] = struct.pack("<I", 2)
    pbs[64] = 0x80
    pbs[71:82] = b"NO NAME    "
    pbs[82:90] = b"FAT32   "
    pbs[120:131] = b"IO      SYS"
    pbs[510:512] = b"\x55\xaa"
    return bytes(pbs)


def _msdos_fat16_boot_sector_bytes() -> bytes:
    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x3c\x90"
    pbs[3:11] = b"MSWIN4.1"
    pbs[11:13] = struct.pack("<H", 512)
    pbs[13] = 4
    pbs[14:16] = struct.pack("<H", 1)
    pbs[16] = 2
    pbs[17:19] = struct.pack("<H", 512)
    pbs[21] = 0xF8
    pbs[22:24] = struct.pack("<H", 64)
    pbs[24:26] = struct.pack("<H", 63)
    pbs[26:28] = struct.pack("<H", 255)
    pbs[32:36] = struct.pack("<I", 32768)
    pbs[36] = 0x80
    pbs[38] = 0x29
    pbs[43:54] = b"NO NAME    "
    pbs[54:62] = b"FAT16   "
    pbs[90:101] = b"IO      SYS"
    pbs[510:512] = b"\x55\xaa"
    return bytes(pbs)


def _msdos33_boot_sector_bytes() -> bytes:
    pbs = bytearray(512)
    pbs[:3] = b"\xeb\x3c\x90"
    pbs[3:11] = b"MSDOS3.3"
    pbs[11:13] = struct.pack("<H", 512)
    pbs[13] = 2
    pbs[14:16] = struct.pack("<H", 1)
    pbs[16] = 2
    pbs[17:19] = struct.pack("<H", 112)
    pbs[19:21] = struct.pack("<H", 720)
    pbs[21] = 0xFD
    pbs[22:24] = struct.pack("<H", 2)
    pbs[24:26] = struct.pack("<H", 9)
    pbs[26:28] = struct.pack("<H", 2)
    # DOS 3.3 boot sectors typically do not include the FAT12/FAT16 text label at offset 54.
    pbs[54:62] = b"\xFA\x33\xC0\x8E\xD0\xBC\x00\x7C"
    pbs[80:91] = b"IO      SYS"
    pbs[510:512] = b"\x55\xaa"
    return bytes(pbs)


def test_resolve_freedos_local_directory(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _freedos_fat16_boot_sector_bytes())
    _touch(assets_dir / "FDOS" / "BIN" / "XCOPY.EXE")

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert sorted(assets.system_files) == ["COMMAND.COM", "KERNEL.SYS"]
    assert assets.boot_sector_template.name == "BOOTSECT_FAT16.BIN"
    assert assets.fdos_payload_dir == assets_dir / "FDOS"


def test_resolve_freedos_local_adds_fd_startup_aliases(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "CONFIG.SYS", b"SHELL=C:\\COMMAND.COM /P\r\n")
    _touch(assets_dir / "AUTOEXEC.BAT", b"PROMPT $P$G\r\n")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.system_files["CONFIG.SYS"] == assets_dir / "CONFIG.SYS"
    assert assets.system_files["FDCONFIG.SYS"] == assets_dir / "CONFIG.SYS"
    assert assets.system_files["AUTOEXEC.BAT"] == assets_dir / "AUTOEXEC.BAT"
    assert assets.system_files["FDAUTO.BAT"] == assets_dir / "AUTOEXEC.BAT"


def test_resolve_freedos_local_prefers_fdos_bin_core_binaries(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"legacy-kernel")
    _touch(assets_dir / "COMMAND.COM", b"legacy-command")
    _touch(assets_dir / "FDOS" / "BIN" / "KERNL386.SYS", b"core-kernel")
    _touch(assets_dir / "FDOS" / "BIN" / "COMMAND.COM", b"core-command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.system_files["COMMAND.COM"] == assets_dir / "FDOS" / "BIN" / "COMMAND.COM"
    assert assets.system_files["KERNEL.SYS"] == assets_dir / "FDOS" / "BIN" / "KERNL386.SYS"


def test_resolve_freedos_local_uses_explicit_mbr_template(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)
    _touch(assets_dir / "MBR_FAT16.BIN", b"\x01" * 440)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.mbr_boot_code_template == assets_dir / "MBR_FAT16.BIN"


def test_resolve_freedos_local_prefers_reference_vhd_boot_records(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"k")
    _touch(assets_dir / "COMMAND.COM", b"c")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)
    reference_vhd = tmp_path / "manual-good.vhd"
    _make_freedos_fat16_vhd(reference_vhd)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.boot_sector_template != assets_dir / "BOOTSECT_FAT16.BIN"
    assert b"FRDOS5.1" in assets.boot_sector_template.read_bytes()[:512]
    assert assets.mbr_boot_code_template is not None
    assert assets.mbr_boot_code_template.read_bytes()[:440] == reference_vhd.read_bytes()[:440]


def test_resolve_freedos_local_uses_cached_reference_boot_records(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"k")
    _touch(assets_dir / "COMMAND.COM", b"c")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    cached_boot = bytearray(512)
    cached_boot[3:11] = b"FRDOS5.1"
    cached_boot[80:91] = b"KERNEL  SYS"
    cached_boot[510:512] = b"\x55\xaa"
    resolver._save_cached_fat16_boot_records(mbr_code=b"\x44" * 440, boot_sector=bytes(cached_boot))

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    assets = resolver.resolve(request)

    assert assets.boot_sector_template == resolver.cache_root / "fat16-native-bootsect.bin"
    assert assets.mbr_boot_code_template == resolver.cache_root / "fat16-native-mbr.bin"


def test_resolve_freedos_local_uses_builtin_boot_records_when_no_reference(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"k")
    _touch(assets_dir / "COMMAND.COM", b"c")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", b"\0" * 512)

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    assets = resolver.resolve(request)

    assert assets.boot_sector_template == resolver.cache_root / "fat16-native-bootsect.bin"
    assert assets.mbr_boot_code_template == resolver.cache_root / "fat16-native-mbr.bin"
    assert b"FRDOS5.1" in assets.boot_sector_template.read_bytes()[:512]
    assert assets.mbr_boot_code_template.stat().st_size >= 440


def test_resolve_freedos_local_missing_template_fails(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")

    with pytest.raises(ValidationError):
        resolver.resolve(request)


def test_resolve_ibm8088_direct_directory(tmp_path: Path) -> None:
    assets_dir = tmp_path / "ibm"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())
    _touch(assets_dir / "CONFIG.SYS", b"FILES=20\r\n")

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_dir,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert sorted(assets.system_files) == ["COMMAND.COM", "CONFIG.SYS", "IO.SYS", "MSDOS.SYS"]
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


def test_resolve_ibm8088_uses_version_subdir(tmp_path: Path) -> None:
    assets_root = tmp_path / "ibm-assets"
    dos50 = assets_root / "dos50"
    _touch(dos50 / "IO.SYS", b"io")
    _touch(dos50 / "MSDOS.SYS", b"msdos")
    _touch(dos50 / "COMMAND.COM", b"command")
    _touch(dos50 / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_root,
        ibm_dos_version=IBMDOSVersion.DOS50,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    assert assets.boot_sector_template == dos50 / "BOOTSECT_FAT16.BIN"


def test_resolve_ibm8088_from_install_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "ibm"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk1.write_bytes(b"disk")

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_dir,
        ibm_dos_version=IBMDOSVersion.DOS50,
    )

    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    boot_sector = _msdos_fat16_boot_sector_bytes()

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1]
        payload_map = {
            "IO.SYS": b"io",
            "MSDOS.SYS": b"msdos",
            "COMMAND.COM": b"command",
            "SYS.COM": b"\x90" * 32 + boot_sector + b"\x90" * 32,
        }
        payload = payload_map.get(dos_name.upper())
        if payload is None:
            if required:
                raise ValidationError(f"missing {dos_name}")
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)

    assets = resolver.resolve(request)
    assert assets.system_files["IO.SYS"].read_bytes() == b"io"
    assert assets.system_files["MSDOS.SYS"].read_bytes() == b"msdos"
    assert assets.system_files["COMMAND.COM"].read_bytes() == b"command"
    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template[54:62] in (b"FAT16   ", b"FAT12   ")
    assert b"IO      SYS" in template


def test_resolve_ibm8088_from_install_images_dos33_floppy_boot_sector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "ibm"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "DISK01.IMG"
    boot_sector = _msdos33_boot_sector_bytes()
    disk1.write_bytes(boot_sector + (b"\0" * (FloppyType.F360K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_dir,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )

    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1]
        payload_map = {
            "IO.SYS": b"io",
            "MSDOS.SYS": b"msdos",
            "COMMAND.COM": b"command",
        }
        payload = payload_map.get(dos_name.upper())
        if payload is None:
            if required:
                raise ValidationError(f"missing {dos_name}")
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)

    assets = resolver.resolve(request)
    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template == boot_sector
    assert b"IO      SYS" in template
    assert assets.source_image_size_bytes == FloppyType.F360K.size_bytes
    assert assets.source_image_path == disk1


def test_resolve_ibm8088_dos33_prefers_install_image_boot_sector_over_sys_com(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "ibm"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "DISK01.IMG"
    boot_sector_from_image = _msdos33_boot_sector_bytes()
    disk1.write_bytes(boot_sector_from_image + (b"\0" * 1024))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=1440 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_dir,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    fat16_sector_from_sys = _msdos_fat16_boot_sector_bytes()

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1]
        payload_map = {
            "IO.SYS": b"io",
            "MSDOS.SYS": b"msdos",
            "COMMAND.COM": b"command",
            "SYS.COM": b"\x90" * 32 + fat16_sector_from_sys + b"\x90" * 32,
        }
        payload = payload_map.get(dos_name.upper())
        if payload is None:
            if required:
                raise ValidationError(f"missing {dos_name}")
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    assets = resolver.resolve(request)

    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template == boot_sector_from_image


def test_resolve_pcdos_direct_directory_with_ibmbio_set(tmp_path: Path) -> None:
    assets_dir = tmp_path / "pcdos"
    _touch(assets_dir / "IBMBIO.COM", b"bios")
    _touch(assets_dir / "IBMDOS.COM", b"dos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=1440 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert sorted(assets.system_files) == ["COMMAND.COM", "IBMBIO.COM", "IBMDOS.COM"]
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


def test_resolve_compaq331_uses_named_subdirectory(tmp_path: Path) -> None:
    assets_root = tmp_path / "dos-assets"
    compaq = assets_root / "compaq331"
    _touch(compaq / "IO.SYS", b"io")
    _touch(compaq / "MSDOS.SYS", b"msdos")
    _touch(compaq / "COMMAND.COM", b"command")
    _touch(compaq / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=1440 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.COMPAQ331,
        boot_assets_path=assets_root,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.boot_sector_template == compaq / "BOOTSECT_FAT16.BIN"
    assert "IO.SYS" in assets.system_files


def test_resolve_pcdos_from_install_images_uses_ibmbio_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "pcdos"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk1.write_bytes(_msdos_fat16_boot_sector_bytes() + (b"\0" * 1024))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=1440 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS,
        boot_assets_path=assets_dir,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1]
        payload_map = {
            "IBMBIO.COM": b"bios",
            "IBMDOS.COM": b"dos",
            "COMMAND.COM": b"command",
        }
        payload = payload_map.get(dos_name.upper())
        if payload is None:
            if required:
                raise ValidationError(f"missing {dos_name}")
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    assets = resolver.resolve(request)

    assert assets.system_files["IBMBIO.COM"].read_bytes() == b"bios"
    assert assets.system_files["IBMDOS.COM"].read_bytes() == b"dos"


def test_resolve_msdos71_direct_directory(tmp_path: Path) -> None:
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "HIMEM.SYS", b"himem")
    _touch(assets_dir / "IFSHLP.SYS", b"ifshlp")
    _touch(assets_dir / "BOOTSECT_FAT32.BIN", _msdos_fat32_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert sorted(assets.system_files) == [
        "AUTOEXEC.BAT",
        "COMMAND.COM",
        "CONFIG.SYS",
        "HIMEM.SYS",
        "IFSHLP.SYS",
        "IO.SYS",
        "MSDOS.SYS",
    ]
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT32.BIN"
    assert "SHELL=COMMAND.COM /P /E:640" in assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1")
    config_text = assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1")
    autoexec_text = assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1")
    assert "SET PATH=C:\\DOS;..;." in config_text
    assert "PROMPT $P$G" in autoexec_text
    assert autoexec_text.splitlines()[:2] == ["@ECHO OFF", "PATH=C:\\DOS;..;."]


def test_resolve_msdos71_direct_directory_fat16(tmp_path: Path) -> None:
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "HIMEM.SYS", b"himem")
    _touch(assets_dir / "IFSHLP.SYS", b"ifshlp")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert sorted(assets.system_files) == [
        "AUTOEXEC.BAT",
        "COMMAND.COM",
        "CONFIG.SYS",
        "HIMEM.SYS",
        "IFSHLP.SYS",
        "IO.SYS",
        "MSDOS.SYS",
    ]
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


def test_resolve_msdos71_normalizes_startup_files_for_install_profile(tmp_path: Path) -> None:
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "HIMEM.SYS", b"himem")
    _touch(assets_dir / "IFSHLP.SYS", b"ifshlp")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())
    _touch(
        assets_dir / "CONFIG.SYS",
        b"DEVICE=HIMEM.SYS\r\nDEVICEHIGH=SETVER.EXE\r\nSHELL=COMMAND.COM /P /E:640\r\n",
    )
    _touch(
        assets_dir / "AUTOEXEC.BAT",
        b"@ECHO OFF\r\nPROMPT $P$G\r\nLH DOSLFN /Z:CP437UNI.TBL\r\n",
    )

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    config_text = assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1")
    autoexec_text = assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1")
    assert "DEVICE=C:\\DOS\\HIMEM.SYS" in config_text
    assert "DEVICEHIGH=C:\\DOS\\SETVER.EXE" in config_text
    assert "SET PATH=C:\\DOS;..;." in config_text
    assert autoexec_text.splitlines()[:2] == ["@ECHO OFF", "PATH=C:\\DOS;..;."]
    assert "LH DOSLFN /Z:C:\\DOS\\CP437UNI.TBL" in autoexec_text


def test_resolve_msdos71_direct_directory_full_uses_dos_payload(tmp_path: Path) -> None:
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "HIMEM.SYS", b"himem")
    _touch(assets_dir / "IFSHLP.SYS", b"ifshlp")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())
    _touch(assets_dir / "DOS" / "EDIT.COM", b"edit")

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.fdos_payload_dir == assets_dir / "DOS"
    assert assets.payload_target_dir == "DOS"


def test_resolve_msdos71_from_install_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "dos71"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk1.write_bytes(b"disk")

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )

    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    def fake_copy(image_path: Path, dos_name: str, destination: Path) -> bool:
        assert image_path == disk1
        if dos_name.upper() != "DOS71_1S.PAK":
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"pak")
        return True

    monkeypatch.setattr(resolver, "_copy_file_from_image_case_insensitive", fake_copy)

    boot_sector = _msdos_fat32_boot_sector_bytes()

    def fake_extract(pak_path: Path, destination: Path) -> None:
        assert pak_path.name == "DOS71_1S.PAK"
        _touch(destination / "IO.SYS", b"io")
        _touch(destination / "MSDOS.SYS", b"msdos")
        _touch(destination / "COMMAND.COM", b"command")
        _touch(destination / "HIMEM.SYS", b"himem")
        _touch(destination / "IFSHLP.SYS", b"ifshlp")
        _touch(destination / "SYS.COM", b"\x90" * 64 + boot_sector + b"\x90" * 32)

    monkeypatch.setattr(resolver, "_extract_msdos71_pak_files", fake_extract)

    assets = resolver.resolve(request)

    assert assets.system_files["IO.SYS"].read_bytes() == b"io"
    assert assets.system_files["MSDOS.SYS"].read_bytes() == b"msdos"
    assert assets.system_files["COMMAND.COM"].read_bytes() == b"command"
    assert assets.system_files["HIMEM.SYS"].read_bytes() == b"himem"
    assert assets.system_files["IFSHLP.SYS"].read_bytes() == b"ifshlp"
    assert "CONFIG.SYS" in assets.system_files
    assert "AUTOEXEC.BAT" in assets.system_files
    assert assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1").splitlines()[:2] == [
        "@ECHO OFF",
        "PATH=C:\\DOS;..;.",
    ]
    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template[82:90] == b"FAT32   "
    assert b"IO      SYS" in template


def test_resolve_msdos71_from_install_images_full_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "dos71"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk1.write_bytes(b"disk")

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )

    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    def fake_copy(image_path: Path, dos_name: str, destination: Path) -> bool:
        assert image_path == disk1
        if dos_name.upper() not in ("DOS71_1S.PAK", "DOS71_2S.PAK"):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"pak")
        return True

    monkeypatch.setattr(resolver, "_copy_file_from_image_case_insensitive", fake_copy)

    boot_sector = _msdos_fat32_boot_sector_bytes()

    def fake_extract(pak_path: Path, destination: Path) -> None:
        assert pak_path.name == "DOS71_1S.PAK"
        _touch(destination / "IO.SYS", b"io")
        _touch(destination / "MSDOS.SYS", b"msdos")
        _touch(destination / "COMMAND.COM", b"command")
        _touch(destination / "HIMEM.SYS", b"himem")
        _touch(destination / "IFSHLP.SYS", b"ifshlp")
        _touch(destination / "SYS.COM", b"\x90" * 64 + boot_sector + b"\x90" * 32)

    monkeypatch.setattr(resolver, "_extract_msdos71_pak_files", fake_extract)

    def fake_full_payload(*, install_images: list[Path], extraction_root: Path, destination: Path) -> None:
        assert install_images == [disk1]
        assert extraction_root.name.startswith("msdos71-")
        _touch(destination / "DOSGUI" / "EDIT.COM", b"edit")

    monkeypatch.setattr(resolver, "_extract_msdos71_full_payload", fake_full_payload)

    assets = resolver.resolve(request)

    assert assets.payload_target_dir == "DOS"
    assert assets.fdos_payload_dir is not None
    assert assets.fdos_payload_dir.name == "DOS"
    assert (assets.fdos_payload_dir / "DOSGUI" / "EDIT.COM").read_bytes() == b"edit"
    assert assets.system_files["HIMEM.SYS"].read_bytes() == b"himem"
    assert assets.system_files["IFSHLP.SYS"].read_bytes() == b"ifshlp"
    assert "CONFIG.SYS" in assets.system_files
    assert "AUTOEXEC.BAT" in assets.system_files


def test_resolve_msdos71_from_install_images_fat16(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "dos71"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk1.write_bytes(b"disk")

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )

    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    def fake_copy(image_path: Path, dos_name: str, destination: Path) -> bool:
        assert image_path == disk1
        if dos_name.upper() != "DOS71_1S.PAK":
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"pak")
        return True

    monkeypatch.setattr(resolver, "_copy_file_from_image_case_insensitive", fake_copy)

    boot_sector = _msdos_fat16_boot_sector_bytes()

    def fake_extract(pak_path: Path, destination: Path) -> None:
        assert pak_path.name == "DOS71_1S.PAK"
        _touch(destination / "IO.SYS", b"io")
        _touch(destination / "MSDOS.SYS", b"msdos")
        _touch(destination / "COMMAND.COM", b"command")
        _touch(destination / "HIMEM.SYS", b"himem")
        _touch(destination / "IFSHLP.SYS", b"ifshlp")
        _touch(destination / "SYS.COM", b"\x90" * 32 + boot_sector + b"\x90" * 64)

    monkeypatch.setattr(resolver, "_extract_msdos71_pak_files", fake_extract)

    assets = resolver.resolve(request)

    assert assets.system_files["IO.SYS"].read_bytes() == b"io"
    assert assets.system_files["MSDOS.SYS"].read_bytes() == b"msdos"
    assert assets.system_files["COMMAND.COM"].read_bytes() == b"command"
    assert assets.system_files["HIMEM.SYS"].read_bytes() == b"himem"
    assert assets.system_files["IFSHLP.SYS"].read_bytes() == b"ifshlp"
    assert "CONFIG.SYS" in assets.system_files
    assert "AUTOEXEC.BAT" in assets.system_files
    assert assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1").splitlines()[:2] == [
        "@ECHO OFF",
        "PATH=C:\\DOS;..;.",
    ]
    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template[54:62] in (b"FAT16   ", b"FAT12   ")
    assert b"IO      SYS" in template


def test_msdos71_accepts_fat16(tmp_path: Path) -> None:
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS")
    _touch(assets_dir / "MSDOS.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "HIMEM.SYS")
    _touch(assets_dir / "IFSHLP.SYS")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


def test_export_latest_freedos_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_root = tmp_path / "cache"
    resolver = BootAssetResolver(CommandRunner(), cache_root=cache_root)

    image_path = cache_root / "fd.img"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\0" * 1024)

    extraction = cache_root / "extract"
    _touch(extraction / "KERNEL.SYS", b"k")
    _touch(extraction / "COMMAND.COM", b"c")
    _touch(extraction / "BOOTSECT_FAT16.BIN", b"\0" * 512)
    _touch(extraction / "CONFIG.SYS", b"SHELL=A:\\COMMAND.COM /E:512 /MSG /P\r\n")
    _touch(extraction / "AUTOEXEC.BAT", b"ECHO OFF\r\n\r\ncls\r\n")

    monkeypatch.setattr(resolver, "_download_freedos_image", lambda url: image_path)

    def fake_resolve_from_image(path: Path, disk_format: DiskFormat):
        assert path == image_path
        assert disk_format is DiskFormat.FAT16
        return resolver._resolve_freedos_from_directory(extraction, DiskFormat.FAT16)

    monkeypatch.setattr(resolver, "_resolve_freedos_from_image", fake_resolve_from_image)
    monkeypatch.setattr(
        resolver,
        "_write_fat32_boot_template",
        lambda destination, **kwargs: destination.write_bytes(b"\0" * 512),
    )

    output = tmp_path / "freedos"
    destination = resolver.export_latest_freedos_assets(output, image_url="https://example.invalid/fd.img")
    assert destination == output.resolve()
    assert (destination / "KERNEL.SYS").exists()
    assert (destination / "COMMAND.COM").exists()
    assert (destination / "BOOTSECT_FAT16.BIN").exists()
    assert (destination / "BOOTSECT_FAT32.BIN").exists()
    assert (destination / "README.txt").exists()
    assert "SHELL=C:\\COMMAND.COM" in (destination / "CONFIG.SYS").read_text(encoding="latin-1")
    assert (destination / "FDCONFIG.SYS").exists()
    assert (destination / "FDAUTO.BAT").exists()
    autoexec_text = (destination / "AUTOEXEC.BAT").read_text(encoding="latin-1")
    assert "PROMPT $P$G" in autoexec_text
    assert "SET DOSDIR=C:\\FDOS" in autoexec_text
    assert b"\r\n" in (destination / "CONFIG.SYS").read_bytes()
    assert b"\r\n" in (destination / "AUTOEXEC.BAT").read_bytes()


def test_export_latest_freedos_assets_can_include_fdos_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_root = tmp_path / "cache"
    resolver = BootAssetResolver(CommandRunner(), cache_root=cache_root)

    image_path = cache_root / "fd.img"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\0" * 1024)

    extraction = cache_root / "extract"
    _touch(extraction / "KERNEL.SYS", b"k")
    _touch(extraction / "COMMAND.COM", b"c")
    _touch(extraction / "BOOTSECT_FAT16.BIN", b"\0" * 512)

    monkeypatch.setattr(resolver, "_download_freedos_image", lambda url: image_path)
    monkeypatch.setattr(
        resolver,
        "_resolve_freedos_from_image",
        lambda path, disk_format: resolver._resolve_freedos_from_directory(extraction, DiskFormat.FAT16),
    )
    monkeypatch.setattr(
        resolver,
        "_write_fat32_boot_template",
        lambda destination, **kwargs: destination.write_bytes(b"\0" * 512),
    )

    marker: dict[str, Path] = {}

    def fake_extract(destination: Path) -> None:
        marker["destination"] = destination
        _touch(destination / "BIN" / "EDIT.COM", b"e")

    monkeypatch.setattr(resolver, "_download_and_extract_freedos_userspace", fake_extract)

    output = tmp_path / "freedos"
    resolver.export_latest_freedos_assets(output, include_full_fdos=True)
    assert marker["destination"] == output.resolve() / "FDOS"
    assert (output / "FDOS" / "BIN" / "EDIT.COM").exists()


def test_write_fat32_boot_template_prefers_local_freedos_vhd(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    source_vhd = tmp_path / "refs" / "shareware.vhd"
    _make_freedos_fat32_vhd(source_vhd)

    destination = tmp_path / "BOOTSECT_FAT32.BIN"
    resolver._write_fat32_boot_template(destination, search_roots=(source_vhd.parent,))

    data = destination.read_bytes()
    assert len(data) == 512
    assert b"FRDOS5.1" in data
    assert b"KERNEL  SYS" in data
    assert b"This is not a bootable disk" not in data


def test_resolve_freedos_from_image_prefers_core_binaries_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image_path = tmp_path / "fd.img"
    image_path.write_bytes(b"\0" * 1024)

    def fake_extract_file(
        image: Path,
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        del image
        if required:
            payload = b"k" if dos_name == "KERNEL.SYS" else b"c"
            path = output_dir / dos_name
            _touch(path, payload)
            return path
        return None

    def fake_ensure_core(payload_dir: Path) -> None:
        _touch(payload_dir / "BIN" / "COMMAND.COM", b"core-command")
        _touch(payload_dir / "BIN" / "KERNL386.SYS", b"core-kernel")

    monkeypatch.setattr(resolver, "_extract_file_from_image", fake_extract_file)
    monkeypatch.setattr(resolver, "_ensure_freedos_core_payload", fake_ensure_core)

    assets = resolver._resolve_freedos_from_image(image_path, DiskFormat.FAT16)
    assert assets.system_files["COMMAND.COM"].read_bytes() == b"core-command"
    assert assets.system_files["KERNEL.SYS"].name == "KERNL386.SYS"
    assert assets.system_files["KERNEL.SYS"].read_bytes() == b"core-kernel"
    assert assets.fdos_payload_dir == resolver.cache_root / f"freedos-{resolver._hash_value(str(image_path.resolve()))}" / "FDOS"


def test_extract_msdos71_fat32_boot_sector_from_binary(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    boot_sector = _msdos_fat32_boot_sector_bytes()
    binary = tmp_path / "sys.com"
    _touch(binary, b"\x00" * 123 + boot_sector + b"\xff" * 33)

    extracted = resolver._extract_msdos71_fat32_boot_sector_from_binary(binary)
    assert extracted == boot_sector


def test_extract_msdos71_fat16_boot_sector_from_binary(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    boot_sector = _msdos_fat16_boot_sector_bytes()
    binary = tmp_path / "sys.com"
    _touch(binary, b"\x00" * 77 + boot_sector + b"\xff" * 9)

    extracted = resolver._extract_msdos71_fat16_boot_sector_from_binary(binary)
    assert extracted == boot_sector


def test_normalize_freedos_config_sys_rewrites_floppy_shell_path() -> None:
    src = "DOS=HIGH\r\nSHELL=A:\\COMMAND.COM /E:512 /MSG /P\r\nFILES=20\r\n"
    out = normalize_freedos_config_sys(src)
    assert "SHELL=C:\\COMMAND.COM /E:512 /MSG /P" in out
    assert "/D" not in out
    assert "/K" not in out


def test_normalize_freedos_config_sys_removes_forced_startup_switches() -> None:
    src = "SHELL=C:\\COMMAND.COM /E:512 /MSG /P /D /K C:\\FDAUTO.BAT\r\n"
    out = normalize_freedos_config_sys(src)
    assert "/D" not in out
    assert "/K" not in out
    assert out.count("/P") == 1


def test_normalize_freedos_autoexec_adds_hdd_fallbacks_for_minimal_script() -> None:
    src = "ECHO OFF\r\n\r\ncls\r\n"
    out = normalize_freedos_autoexec_bat(src)
    assert "SET DOSDIR=C:\\FDOS" in out
    assert "IF EXIST C:\\FDOS\\BIN\\*.* SET PATH=C:\\FDOS\\BIN;C:\\" in out
    assert "PROMPT $P$G" in out


def test_normalize_freedos_autoexec_rewrites_floppy_drive_references() -> None:
    src = "ECHO OFF\r\nSET PATH=A:\\FDOS\\BIN;A:\\\r\n"
    out = normalize_freedos_autoexec_bat(src)
    assert "SET PATH=C:\\FDOS\\BIN;C:\\" in out


def test_normalize_freedos_autoexec_converts_lf_to_crlf() -> None:
    src = "ECHO OFF\n\ncls\n"
    out = normalize_freedos_autoexec_bat(src)
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")
