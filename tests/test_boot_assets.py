from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest

from dosforge.boot import (
    _BUILTIN_FAT16_BOOT_SECTOR_B64,
    _BUILTIN_FAT32_BOOT_SECTOR_B64,
    _BUILTIN_MSDOS_MBR_BOOT_CODE_B64,
    DEFAULT_MBR_BOOT_CODE_CANDIDATES,
    BootAssetResolver,
    normalize_freedos_autoexec_bat,
    normalize_freedos_config_sys,
)
from dosforge.commands import CommandRunner
from dosforge.errors import ValidationError
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)


@pytest.fixture(autouse=True)
def _allow_legacy_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the legacy CONFIG.SYS/AUTOEXEC.BAT synthesis path.

    These tests pre-date the Phase 14B authenticity rule -- they test
    the synthesizer behavior directly with minimal asset fixtures.
    The opt-out env var keeps the synthesizer enabled so the tests
    continue to exercise the legacy code path.  Phase 14G adds
    separate strict-mode authenticity tests.
    """
    monkeypatch.setenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", "1")


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


def test_resolve_freedos_local_fat32_falls_back_to_fat16_template_when_fat32_is_non_bootable(tmp_path: Path) -> None:
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _freedos_fat16_boot_sector_bytes())
    bad_fat32 = bytearray(512)
    bad_fat32[82:90] = b"FAT32   "
    bad_fat32[90:90 + len(b"This is not a bootable disk")] = b"This is not a bootable disk"
    bad_fat32[510:512] = b"\x55\xaa"
    _touch(assets_dir / "BOOTSECT_FAT32.BIN", bytes(bad_fat32))

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


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
    # Even with CONFIG.SYS available in the asset dir, MINIMAL profile
    # (the default) must NOT stage CONFIG.SYS / AUTOEXEC.BAT — they
    # would add A:\DOS-flavoured defaults on a boot-files-only build.
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

    assert sorted(assets.system_files) == ["COMMAND.COM", "IO.SYS", "MSDOS.SYS"]
    assert "CONFIG.SYS" not in assets.system_files
    assert "AUTOEXEC.BAT" not in assets.system_files
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT16.BIN"


def test_resolve_ibm8088_direct_directory_normalizes_startup_files(tmp_path: Path) -> None:
    assets_dir = tmp_path / "ibm"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())
    (assets_dir / "DOS").mkdir(parents=True, exist_ok=True)
    _touch(assets_dir / "CONFIG.SYS", b"FILES=20\r\nPATH=C:\\DOS\r\n")
    _touch(assets_dir / "AUTOEXEC.BAT", b"@ECHO OFF\r\nPROMPT $P$G\r\nKEYB US\r\n")

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        boot_assets_path=assets_dir,
        ibm_dos_version=IBMDOSVersion.DOS33,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    config_text = assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1")
    autoexec_text = assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1")
    assert "PATH=" not in config_text.upper()
    # VHD target → C:\DOS (was A:\DOS for floppy-only legacy behavior).
    assert autoexec_text.splitlines() == ["@ECHO OFF", "PATH=C:\\DOS"]


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


def test_mtools_image_path_extracts_savedskf_wrapper(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    raw_payload = _msdos_fat16_boot_sector_bytes() + (b"\0" * (FloppyType.F1440K.size_bytes - 512))
    offset = 0x29
    header = bytearray(offset)
    header[:2] = b"\xAA\x59"
    header[0x22:0x24] = struct.pack("<H", len(raw_payload) // 512)
    header[0x26:0x28] = struct.pack("<H", offset)

    savedskf = tmp_path / "install.dsk"
    savedskf.write_bytes(bytes(header) + raw_payload)

    normalized = resolver._mtools_image_path(savedskf)
    assert normalized != savedskf
    assert normalized.exists()
    assert normalized.stat().st_size == len(raw_payload)
    assert normalized.read_bytes()[:512] == raw_payload[:512]


def test_select_source_image_size_prefers_xdf(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    img = tmp_path / "disk01.img"
    xdf = tmp_path / "disk02.xdf"
    img.write_bytes(b"\0" * FloppyType.F1440K.size_bytes)
    xdf.write_bytes(b"\0" * FloppyType.F1840K.size_bytes)

    selected_size = resolver._select_source_image_size_bytes([img, xdf])
    assert selected_size == FloppyType.F1840K.size_bytes


def test_resolve_pcdos7_from_install_images_prefers_xdf_source_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "pcdos7"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.img"
    disk2 = assets_dir / "disk02.xdf"
    disk1.write_bytes(_msdos_fat16_boot_sector_bytes() + (b"\0" * (FloppyType.F1440K.size_bytes - 512)))
    disk2.write_bytes(_msdos33_boot_sector_bytes() + (b"\0" * (FloppyType.F1840K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS7,
        boot_assets_path=assets_dir,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1, disk2])

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1, disk2]
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

    assert assets.source_image_size_bytes == FloppyType.F1840K.size_bytes
    assert assets.system_files["IBMBIO.COM"].read_bytes() == b"bios"
    assert assets.system_files["IBMDOS.COM"].read_bytes() == b"dos"
    assert len(assets.boot_sector_template.read_bytes()) == 512


def test_resolve_pcdos7_prefers_live_install_media_when_images_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "pcdos7"
    assets_dir.mkdir(parents=True)
    _touch(assets_dir / "IBMBIO.COM", b"direct-bios")
    _touch(assets_dir / "IBMDOS.COM", b"direct-dos")
    _touch(assets_dir / "COMMAND.COM", b"direct-command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    disk1 = assets_dir / "disk01.xdf"
    disk1.write_bytes(_msdos33_boot_sector_bytes() + (b"\0" * (FloppyType.F1840K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS7,
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
            "IBMBIO.COM": b"live-bios",
            "IBMDOS.COM": b"live-dos",
            "COMMAND.COM": b"live-command",
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

    assert assets.system_files["IBMBIO.COM"].read_bytes() == b"live-bios"
    assert assets.system_files["IBMDOS.COM"].read_bytes() == b"live-dos"
    assert assets.system_files["COMMAND.COM"].read_bytes() == b"live-command"
    assert assets.system_files["IBMBIO.COM"].resolve() != (assets_dir / "IBMBIO.COM").resolve()
    assert assets.boot_sector_template != assets_dir / "BOOTSECT_FAT16.BIN"
    assert assets.boot_sector_template.read_bytes() == _msdos33_boot_sector_bytes()


def test_resolve_pcdos7_install_media_does_not_stage_installer_startup_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "pcdos7"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.xdf"
    disk1.write_bytes(_msdos33_boot_sector_bytes() + (b"\0" * (FloppyType.F1840K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS7,
        boot_assets_path=assets_dir,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])

    requested_names: list[str] = []

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [disk1]
        requested_names.append(dos_name.upper())
        payload_map = {
            "IBMBIO.COM": b"bios",
            "IBMDOS.COM": b"dos",
            "COMMAND.COM": b"command",
            "CONFIG.SYS": b"country=001\r\n",
            "AUTOEXEC.BAT": b"setup\r\n",
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

    assert "CONFIG.SYS" not in assets.system_files
    assert "AUTOEXEC.BAT" not in assets.system_files
    assert "CONFIG.SYS" not in requested_names
    assert "AUTOEXEC.BAT" not in requested_names


def test_resolve_pcdos7_full_profile_extracts_payload_and_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "pcdos7"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk01.xdf"
    disk1.write_bytes(_msdos33_boot_sector_bytes() + (b"\0" * (FloppyType.F1840K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.PCDOS7,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
        media_type=MediaType.IMG,
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

    captured: dict[str, object] = {}

    def fake_full_payload(
        *,
        install_images: list[Path],
        destination: Path,
        payload_budget_bytes: int | None = None,
        startup_files: dict[str, Path] | None = None,
    ) -> None:
        captured["install_images"] = install_images
        captured["destination"] = destination
        captured["payload_budget_bytes"] = payload_budget_bytes
        captured["startup_files"] = startup_files
        _touch(destination / "EDIT.COM", b"edit")

    monkeypatch.setattr(resolver, "_extract_legacy_full_payload_from_images", fake_full_payload)
    assets = resolver.resolve(request)

    assert assets.payload_target_dir == "DOS"
    assert assets.fdos_payload_dir is not None
    assert assets.fdos_payload_dir.name == "DOS"
    assert captured["install_images"] == [disk1]
    assert captured["destination"] == assets.fdos_payload_dir
    assert captured["payload_budget_bytes"] == 512 * 1024
    assert isinstance(captured["startup_files"], dict)
    assert (assets.fdos_payload_dir / "EDIT.COM").read_bytes() == b"edit"
    assert "CONFIG.SYS" in assets.system_files
    assert "AUTOEXEC.BAT" in assets.system_files
    assert "PATH=" not in assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1").upper()
    assert assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1").splitlines()[:2] == [
        "@ECHO OFF",
        "PATH=A:\\DOS",
    ]


def test_extract_legacy_full_payload_from_images_uses_core_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image = tmp_path / "disk1.img"
    image.write_bytes(b"disk")
    destination = tmp_path / "DOS"
    requested_names: list[str] = []

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert required is False
        assert image_paths == [image]
        requested_names.append(dos_name.upper())
        payloads = {
            "EDIT.COM": b"edit",
            "QBASIC.EXE": b"qbasic",
            "CHKDSK.COM": b"check",
            "SUBST.EXE": b"subst",
        }
        payload = payloads.get(dos_name.upper())
        if payload is None:
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    resolver._extract_legacy_full_payload_from_images(
        install_images=[image],
        destination=destination,
        payload_budget_bytes=64 * 1024,
    )

    assert sorted(path.name for path in destination.iterdir()) == [
        "CHKDSK.COM",
        "EDIT.COM",
        "QBASIC.EXE",
        "SUBST.EXE",
    ]
    assert "CHKDSK.EXE" in requested_names
    assert "CHKDSK.COM" in requested_names


def test_extract_core_payload_from_images_respects_budget_with_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image = tmp_path / "disk1.img"
    image.write_bytes(b"disk")
    destination = tmp_path / "DOS"

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert required is False
        assert image_paths == [image]
        payloads = {
            "EDIT.COM": b"edit",  # 4
            "CHKDSK.EXE": b"x" * 20,  # too large for remaining budget
            "CHKDSK.COM": b"check",  # fallback candidate
            "SUBST.EXE": b"subst",  # exceeds remaining budget
        }
        payload = payloads.get(dos_name.upper())
        if payload is None:
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    resolver._extract_legacy_full_payload_from_images(
        install_images=[image],
        destination=destination,
        payload_budget_bytes=10,
    )

    assert sorted(path.name for path in destination.iterdir()) == ["CHKDSK.COM", "EDIT.COM"]
    assert not (destination / "CHKDSK.EXE").exists()
    assert not (destination / "SUBST.EXE").exists()


def test_extract_core_payload_prioritizes_existing_core_before_qbasic_when_budget_is_tight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image = tmp_path / "disk1.img"
    image.write_bytes(b"disk")
    destination = tmp_path / "DOS"

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert required is False
        assert image_paths == [image]
        payloads = {
            "EDIT.COM": b"edit",  # 4
            "E.EXE": b"eeee",  # 4
            "CHKDSK.COM": b"check",  # 5
            "QBASIC.EXE": b"q" * 20,  # too large after core selection
        }
        payload = payloads.get(dos_name.upper())
        if payload is None:
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    resolver._extract_legacy_full_payload_from_images(
        install_images=[image],
        destination=destination,
        payload_budget_bytes=13,
    )

    assert sorted(path.name for path in destination.iterdir()) == ["CHKDSK.COM", "E.EXE", "EDIT.COM"]
    assert not (destination / "QBASIC.EXE").exists()


def test_extract_file_from_images_with_compression_fallback_expands_country_sys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image = tmp_path / "disk1.img"
    image.write_bytes(b"disk")
    output_dir = tmp_path / "extract"
    source = b"COUNTRY"
    compressed_stream = b"\x7f" + source
    compressed_payload = b"SZDD\x88\xf0'3" + bytes([0x41, 0x00]) + len(source).to_bytes(4, "little") + compressed_stream

    def fake_extract_from_images(
        image_paths: list[Path],
        destination: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert image_paths == [image]
        assert required is False
        if dos_name.upper() == "COUNTRY.SY_":
            path = destination / dos_name
            _touch(path, compressed_payload)
            return path
        return None

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    expanded = resolver._extract_file_from_images_with_compression_fallback(
        [image],
        output_dir,
        "COUNTRY.SYS",
        required=True,
    )

    assert expanded is not None
    assert expanded.name == "COUNTRY.SYS"
    assert expanded.read_bytes() == source


def test_extract_legacy_full_payload_from_images_includes_startup_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    image = tmp_path / "disk1.img"
    image.write_bytes(b"disk")
    destination = tmp_path / "DOS"
    config = tmp_path / "CONFIG.SYS"
    autoexec = tmp_path / "AUTOEXEC.BAT"
    _touch(config, b"DEVICE=HIMEM.SYS\r\n")
    # NLSFUNC and SETUP are referenced in AUTOEXEC.BAT but must NOT
    # be staged: they're on the curated-payload exclusion list
    # (international code-page support stack + installer wizard).
    # KEYB and HIMEM are legitimate startup references and stay.
    _touch(autoexec, b"@ECHO OFF\r\nNLSFUNC\r\nKEYB US\r\nSETUP\r\n")

    def fake_extract_from_images(
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        assert required is False
        assert image_paths == [image]
        payloads = {
            "EDIT.COM": b"edit",
            "HIMEM.SYS": b"himem",
            "NLSFUNC.EXE": b"nls",
            "KEYB.COM": b"keyb",
            "SETUP.EXE": b"setup",
        }
        payload = payloads.get(dos_name.upper())
        if payload is None:
            return None
        path = output_dir / dos_name
        _touch(path, payload)
        return path

    monkeypatch.setattr(resolver, "_extract_file_from_images", fake_extract_from_images)
    resolver._extract_legacy_full_payload_from_images(
        install_images=[image],
        destination=destination,
        payload_budget_bytes=256 * 1024,
        startup_files={"CONFIG.SYS": config, "AUTOEXEC.BAT": autoexec},
    )

    assert (destination / "HIMEM.SYS").read_bytes() == b"himem"
    assert (destination / "KEYB.COM").read_bytes() == b"keyb"
    assert (destination / "EDIT.COM").read_bytes() == b"edit"
    # Excluded -- never staged regardless of AUTOEXEC reference.
    assert not (destination / "NLSFUNC.EXE").exists()
    assert not (destination / "SETUP.EXE").exists()


def test_resolve_legacy_full_profile_adds_country_sys_to_root_when_config_requires_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "msdos622"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk1.img"
    disk1.write_bytes(_msdos33_boot_sector_bytes() + (b"\0" * (FloppyType.F1440K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=256 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
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
            "CONFIG.SYS": b"country=001\r\n",
            "AUTOEXEC.BAT": b"@ECHO OFF\r\nNLSFUNC\r\n",
            "COUNTRY.SYS": b"country",
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
    monkeypatch.setattr(
        resolver,
        "_extract_legacy_full_payload_from_images",
        lambda *, install_images, destination, payload_budget_bytes=None, startup_files=None: _touch(
            destination / "EDIT.COM",
            b"edit",
        ),
    )

    assets = resolver.resolve(request)
    assert assets.system_files["COUNTRY.SYS"].read_bytes() == b"country"
    assert "COUNTRY.SYS" in assets.system_files


def test_resolve_msdos622_vhd_accepts_install_image_bootsector_when_floppy_fat12(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets_dir = tmp_path / "msdos622"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk1.img"
    floppy_sector = bytearray(512)
    floppy_sector[:3] = b"\xeb\x3c\x90"
    floppy_sector[3:11] = b"MSDOS5.0"
    floppy_sector[11:13] = struct.pack("<H", 512)
    floppy_sector[13] = 1
    floppy_sector[14:16] = struct.pack("<H", 1)
    floppy_sector[16] = 2
    floppy_sector[17:19] = struct.pack("<H", 224)
    floppy_sector[19:21] = struct.pack("<H", 2880)
    floppy_sector[21] = 0xF0
    floppy_sector[22:24] = struct.pack("<H", 9)
    floppy_sector[24:26] = struct.pack("<H", 18)
    floppy_sector[26:28] = struct.pack("<H", 2)
    floppy_sector[54:62] = b"FAT12   "
    floppy_sector[0x180:0x180 + 11] = b"IO      SYS"
    floppy_sector[0x190:0x190 + 11] = b"MSDOS   SYS"
    floppy_sector[510:512] = b"\x55\xaa"
    disk1.write_bytes(bytes(floppy_sector) + (b"\0" * (FloppyType.F1440K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=100 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS622,
        boot_assets_path=assets_dir,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])
    monkeypatch.setattr(resolver, "_extract_msdos_fat16_boot_sector_from_images", lambda image_paths: bytes(floppy_sector))

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
    assert assets.boot_sector_template.read_bytes()[:512] == bytes(floppy_sector)


def test_resolve_msdos622_vhd_normalizes_kernel_loader_bootsector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets_dir = tmp_path / "msdos622"
    assets_dir.mkdir(parents=True)
    disk1 = assets_dir / "disk1.img"
    floppy_sector = bytearray(512)
    floppy_sector[:3] = b"\xeb\x3c\x90"
    floppy_sector[3:11] = b"FRDOS5.1"
    floppy_sector[11:13] = struct.pack("<H", 512)
    floppy_sector[13] = 1
    floppy_sector[14:16] = struct.pack("<H", 1)
    floppy_sector[16] = 2
    floppy_sector[17:19] = struct.pack("<H", 224)
    floppy_sector[19:21] = struct.pack("<H", 2880)
    floppy_sector[21] = 0xF0
    floppy_sector[22:24] = struct.pack("<H", 9)
    floppy_sector[24:26] = struct.pack("<H", 18)
    floppy_sector[26:28] = struct.pack("<H", 2)
    floppy_sector[54:62] = b"FAT12   "
    floppy_sector[0x1F0 : 0x1F0 + 11] = b"KERNEL  SYS"
    floppy_sector[510:512] = b"\x55\xaa"
    disk1.write_bytes(bytes(floppy_sector) + (b"\0" * (FloppyType.F1440K.size_bytes - 512)))

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=100 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS622,
        boot_assets_path=assets_dir,
    )
    monkeypatch.setattr(resolver, "_collect_msdos71_install_images", lambda directory: [disk1])
    monkeypatch.setattr(
        resolver,
        "_extract_msdos_fat16_boot_sector_from_images",
        lambda image_paths: bytes(floppy_sector),
    )

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
    assert assets.boot_sector_template.read_bytes()[:512] == base64.b64decode(_BUILTIN_FAT16_BOOT_SECTOR_B64)


def test_trim_payload_to_core_files_prioritizes_startup_references(tmp_path: Path) -> None:
    # HIMEM.SYS is a legitimate startup reference (CONFIG.SYS DEVICE=);
    # NLSFUNC would normally be filtered by the exclusion list, so we
    # use HIMEM here to keep this test focused on the "startup ref
    # beats budget pressure" invariant.
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    payload_dir = tmp_path / "payload"
    _touch(payload_dir / "HIMEM.SYS", b"himem")
    _touch(payload_dir / "EDIT.COM", b"edit")
    config = tmp_path / "CONFIG.SYS"
    _touch(config, b"DEVICE=HIMEM.SYS\r\n")

    resolver._trim_payload_to_core_files(
        payload_dir=payload_dir,
        payload_budget_bytes=5,
        startup_files={"CONFIG.SYS": config},
    )

    assert sorted(entry.name for entry in payload_dir.iterdir()) == ["HIMEM.SYS"]


def test_trim_payload_to_core_files_prioritizes_core_utilities(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    payload_dir = tmp_path / "payload"
    _touch(payload_dir / "EDIT.COM", b"e" * 20)
    _touch(payload_dir / "E.EXE", b"e" * 25)
    _touch(payload_dir / "E.EX", b"x" * 10)
    _touch(payload_dir / "CHKDSK.COM", b"c" * 20)
    _touch(payload_dir / "SUBST.EXE", b"s" * 20)
    _touch(payload_dir / "README.TXT", b"r" * 200)

    resolver._trim_payload_to_core_files(payload_dir=payload_dir, payload_budget_bytes=100)

    assert sorted(entry.name for entry in payload_dir.iterdir()) == [
        "CHKDSK.COM",
        "E.EX",
        "E.EXE",
        "EDIT.COM",
        "SUBST.EXE",
    ]


def test_record_startup_payload_request_filters_excluded_basenames() -> None:
    """Names on _DOS_CORE_PAYLOAD_EXCLUDED_BASENAMES must never be
    recorded as startup-payload requests, even when CONFIG.SYS /
    AUTOEXEC.BAT references them (e.g. the DR-DOS install media's
    AUTOEXEC auto-runs INSTALL.EXE + LOGIN.EXE, but neither belongs
    on the user's hard disk after install).
    """

    from collections import OrderedDict

    resolver = BootAssetResolver(CommandRunner())
    requests: OrderedDict[tuple[str, ...], None] = OrderedDict()

    for excluded in ("INSTALL", "LOGIN", "DEVSWAP", "SSTORDRV", "SETUP", "NLSFUNC", "VSAFE"):
        resolver._record_startup_payload_request(requests, excluded, ("EXE", "COM"))
    assert requests == OrderedDict()

    # Legitimate references still get recorded (with compressed variant).
    resolver._record_startup_payload_request(requests, "HIMEM", ("SYS",))
    assert any("HIMEM.SYS" in entry for entry in requests)


def test_dos_core_payload_budget_uses_floppy_bounds(tmp_path: Path) -> None:
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")

    img_request = CreateRequest(
        path=tmp_path / "disk.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
    )
    tiny_img_request = CreateRequest(
        path=tmp_path / "tiny.img",
        size_bytes=FloppyType.F160K.size_bytes,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
    )
    vhd_request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS622,
    )

    assert resolver._dos_core_payload_budget(img_request) == 512 * 1024
    assert resolver._dos_core_payload_budget(tiny_img_request) == 80 * 1024
    assert resolver._dos_core_payload_budget(vhd_request) is None


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

    # MINIMAL profile must not stage CONFIG.SYS / AUTOEXEC.BAT.
    assert sorted(assets.system_files) == [
        "COMMAND.COM",
        "HIMEM.SYS",
        "IFSHLP.SYS",
        "IO.SYS",
        "MSDOS.SYS",
    ]
    assert "CONFIG.SYS" not in assets.system_files
    assert "AUTOEXEC.BAT" not in assets.system_files
    assert assets.boot_sector_template == assets_dir / "BOOTSECT_FAT32.BIN"


def test_resolve_msdos71_direct_directory_full_targets_c_drive(tmp_path: Path) -> None:
    """FULL profile on VHD must stage CONFIG.SYS/AUTOEXEC.BAT pointing at C:\\DOS."""
    assets_dir = tmp_path / "msdos"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "HIMEM.SYS", b"himem")
    _touch(assets_dir / "IFSHLP.SYS", b"ifshlp")
    _touch(assets_dir / "BOOTSECT_FAT32.BIN", _msdos_fat32_boot_sector_bytes())
    (assets_dir / "DOS").mkdir(parents=True, exist_ok=True)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=512 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    assert "CONFIG.SYS" in assets.system_files
    assert "AUTOEXEC.BAT" in assets.system_files
    autoexec_text = assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1")
    assert autoexec_text.splitlines() == ["@ECHO OFF", "PATH=C:\\DOS"]


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

    # MINIMAL: only boot/system files, no startup files.
    assert sorted(assets.system_files) == [
        "COMMAND.COM",
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
    (assets_dir / "DOS").mkdir(parents=True, exist_ok=True)

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

    config_text = assets.system_files["CONFIG.SYS"].read_text(encoding="latin-1")
    autoexec_text = assets.system_files["AUTOEXEC.BAT"].read_text(encoding="latin-1")
    # VHD target → C:\DOS paths.
    assert "DEVICE=C:\\DOS\\HIMEM.SYS" in config_text
    assert "DEVICEHIGH=C:\\DOS\\SETVER.EXE" in config_text
    assert "PATH=" not in config_text.upper()
    assert autoexec_text.splitlines() == ["@ECHO OFF", "PATH=C:\\DOS"]


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
    assert assets.source_image_size_bytes == disk1.stat().st_size
    # MINIMAL profile (default) must not stage CONFIG.SYS or AUTOEXEC.BAT.
    assert "CONFIG.SYS" not in assets.system_files
    assert "AUTOEXEC.BAT" not in assets.system_files
    template = assets.boot_sector_template.read_bytes()
    assert len(template) == 512
    assert template[82:90] == b"FAT32   "
    assert b"IO      SYS" in template
    assert assets.source_image_size_bytes == disk1.stat().st_size


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

    def fake_full_payload(
        *,
        install_images: list[Path],
        extraction_root: Path,
        destination: Path,
        payload_budget_bytes: int | None = None,
        startup_files: dict[str, Path] | None = None,
    ) -> None:
        assert install_images == [disk1]
        assert extraction_root.name.startswith("msdos71-")
        assert payload_budget_bytes is None
        assert isinstance(startup_files, dict)
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
    assert assets.source_image_size_bytes == disk1.stat().st_size


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
    assert assets.source_image_size_bytes == disk1.stat().st_size
    # MINIMAL: startup files are NOT staged.
    assert "CONFIG.SYS" not in assets.system_files
    assert "AUTOEXEC.BAT" not in assets.system_files
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


# ── FreeDOS minimal-payload filter ─────────────────────────────────────────


def _make_freedos_bundle_with_bloat(root: Path) -> None:
    """Stage a fake WinWorldPC-style FreeDOS bundle with FullCD bloat dirs."""
    _touch(root / "KERNEL.SYS")
    _touch(root / "COMMAND.COM")
    _touch(root / "BOOTSECT_FAT16.BIN", _freedos_fat16_boot_sector_bytes())
    # CONFIG.SYS with one uncommented DEVICE= line + one commented out.
    config_sys = (
        b"SWITCHES=/N\r\n"
        b"DOS=HIGH\r\n"
        b";DEVICE=\\FDOS\\HIMEM.EXE /VERBOSE\r\n"     # commented: skip
        b"DEVICE=\\FDOS\\BIN\\HIMEM.EXE /VERBOSE\r\n"  # uncommented: stage
        b"INSTALL=\\FDOS\\SHARE.EXE\r\n"               # uncommented: stage
        b"FILES=20\r\n"
        b"SHELL=C:\\COMMAND.COM /P\r\n"
    )
    _touch(root / "CONFIG.SYS", config_sys)
    _touch(root / "AUTOEXEC.BAT", b"LH C:\\FDOS\\MOUSE.COM\r\nPATH=C:\\FDOS\\BIN\r\n")

    fdos = root / "FDOS"
    # The 84-file BIN/ subtree we WANT to keep.
    _touch(fdos / "BIN" / "XCOPY.EXE")
    _touch(fdos / "BIN" / "ATTRIB.COM")
    _touch(fdos / "BIN" / "FREECOM" / "subhelper.exe")  # nested in BIN/
    # Files referenced by uncommented DEVICE= / INSTALL= / AUTOEXEC.
    _touch(fdos / "BIN" / "HIMEM.EXE")
    _touch(fdos / "SHARE.EXE")
    _touch(fdos / "MOUSE.COM")
    # Files referenced by COMMENTED-OUT directives (NOT staged).
    _touch(fdos / "HIMEM.EXE")  # mentioned in commented DEVICE= line
    # Bloat dirs Setup would never copy.
    _touch(fdos / "APPINFO" / "BACKUP.LSM")
    _touch(fdos / "DOC" / "README.TXT")
    _touch(fdos / "HELP" / "EDIT.HLP")
    _touch(fdos / "NLS" / "FC.PL")
    _touch(fdos / "NLS" / "FC.RU")
    _touch(fdos / "SOUND" / "ADPLAY" / "ADPLAY.EXE")
    _touch(fdos / "NET" / "CURL.EXE")
    _touch(fdos / "APPS" / "DN2.EXE")


def test_freedos_filter_drops_bloat_subdirs(tmp_path: Path) -> None:
    """APPINFO/DOC/HELP/NLS/SOUND/NET/APPS don't survive the filter."""
    assets_dir = tmp_path / "freedos"
    _make_freedos_bundle_with_bloat(assets_dir)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    staged = assets.fdos_payload_dir
    assert staged is not None, "resolver returned no FDOS payload dir"
    # Filter must have produced a cached subtree under cache_root,
    # not pointed straight at the raw FDOS/ dir.
    assert staged.parent == (tmp_path / "cache").resolve(), (
        f"expected filtered staging under cache/, got {staged}"
    )
    for bloat in ("APPINFO", "APPS", "DOC", "HELP", "NLS", "NET", "SOUND"):
        assert not (staged / bloat).exists(), f"{bloat}/ leaked into the filtered payload"


def test_freedos_filter_keeps_bin_recursively(tmp_path: Path) -> None:
    """BIN/* (including nested FREECOM/ etc.) survives in full."""
    assets_dir = tmp_path / "freedos"
    _make_freedos_bundle_with_bloat(assets_dir)
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    staged = assets.fdos_payload_dir
    assert staged is not None
    assert (staged / "BIN" / "XCOPY.EXE").is_file()
    assert (staged / "BIN" / "ATTRIB.COM").is_file()
    assert (staged / "BIN" / "FREECOM" / "subhelper.exe").is_file()
    assert (staged / "BIN" / "HIMEM.EXE").is_file()  # also a CONFIG.SYS ref


def test_freedos_filter_picks_up_uncommented_config_refs(tmp_path: Path) -> None:
    """INSTALL=\\FDOS\\SHARE.EXE stages SHARE.EXE at the FDOS root."""
    assets_dir = tmp_path / "freedos"
    _make_freedos_bundle_with_bloat(assets_dir)
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    staged = assets.fdos_payload_dir
    assert staged is not None
    assert (staged / "SHARE.EXE").is_file(), "INSTALL=\\FDOS\\SHARE.EXE not honored"
    # MOUSE.COM is referenced from AUTOEXEC.BAT (`LH C:\FDOS\MOUSE.COM`).
    assert (staged / "MOUSE.COM").is_file(), "AUTOEXEC \\FDOS\\MOUSE.COM not honored"


def test_freedos_filter_ignores_commented_directives(tmp_path: Path) -> None:
    """A `;DEVICE=\\FDOS\\HIMEM.EXE` line does NOT stage HIMEM.EXE at the FDOS root."""
    assets_dir = tmp_path / "freedos"
    _make_freedos_bundle_with_bloat(assets_dir)
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    staged = assets.fdos_payload_dir
    assert staged is not None
    # The commented DEVICE= line references \FDOS\HIMEM.EXE (at the
    # FDOS root, not BIN/). The uncommented one references
    # \FDOS\BIN\HIMEM.EXE.  Only the latter should be staged.
    assert not (staged / "HIMEM.EXE").is_file(), (
        "commented-out FDOS reference leaked into the filtered payload"
    )
    assert (staged / "BIN" / "HIMEM.EXE").is_file()


def test_freedos_filter_is_noop_for_curated_bin_only_bundle(tmp_path: Path) -> None:
    """A user who already curated dosassets/freedos/FDOS/ down to BIN/ only

    gets EXACTLY their tree (no filter side effect)."""
    assets_dir = tmp_path / "freedos"
    _touch(assets_dir / "KERNEL.SYS")
    _touch(assets_dir / "COMMAND.COM")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _freedos_fat16_boot_sector_bytes())
    _touch(assets_dir / "FDOS" / "BIN" / "XCOPY.EXE")
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    # No bloat dirs -> filter is a no-op; payload_dir points straight at
    # the user's FDOS/ folder.
    assert assets.fdos_payload_dir == assets_dir / "FDOS"


def test_freedos_filter_cache_hits_on_unchanged_source(tmp_path: Path) -> None:
    """Re-running the resolver with no source changes hits the cache (same path returned)."""
    assets_dir = tmp_path / "freedos"
    _make_freedos_bundle_with_bloat(assets_dir)
    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_dir,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    first = resolver.resolve(request).fdos_payload_dir
    second = resolver.resolve(request).fdos_payload_dir
    assert first == second
    # Cache hit means the staging dir is reused; marker lives
    # alongside the staging dir (NOT inside it, so it doesn't get
    # copied to the user's VHD) and pins source mtime.
    assert first is not None
    marker = first.parent / f"{first.name}.marker"
    assert marker.is_file(), f"missing cache marker: {marker}"


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


def test_write_fat32_boot_template_seeds_builtin_when_no_local_source(tmp_path: Path) -> None:
    """Regression for v0.9.3 FreeDOS FAT32 hang: without a local VHD
    source, dosforge previously fell back to the mkfs.fat stub, whose
    OEM string ``mkfs.fat`` failed the FreeDOS validator and triggered
    a silent FAT16-on-FAT32 boot sector swap (jmp ``EB 3C 90`` over a
    FAT32 BPB), producing a blinking cursor in 86Box.  The builtin
    boot32lb fallback must produce a real FreeDOS FAT32 sector."""
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    destination = tmp_path / "BOOTSECT_FAT32.BIN"
    resolver._write_fat32_boot_template(destination, search_roots=())

    data = destination.read_bytes()
    assert len(data) == 512
    assert data[0:3] == b"\xeb\x58\x90", (
        f"FAT32 jmp opcode must be EB 58 90, got {data[0:3].hex()}"
    )
    assert data[3:11] == b"FRDOS5.1", (
        f"FAT32 OEM must be FRDOS5.1, got {data[3:11]!r}"
    )
    assert data[510:512] == b"\x55\xaa"
    assert b"KERNEL  SYS" in data


def test_seed_builtin_fat16_boot_records_prefers_syslinux_mbr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for v0.9.3 FreeDOS FAT16 'Verifying DMI Pool Data'
    hang: the embedded 71-byte CHS-only MBR breaks on 86Box where BIOS
    geometry diverges from the partition table's CHS encoding.  The
    syslinux LBA-aware MBR must be preferred when available."""
    syslinux_mbr_payload = (b"\xfa\x31\xc0\x8e\xd0\xbc\xe0\x7b\xfb\xfc\x8e\xd8" + b"S" * 428)
    fake_syslinux = tmp_path / "syslinux-mbr.bin"
    fake_syslinux.write_bytes(syslinux_mbr_payload)
    monkeypatch.setattr(
        "dosforge.boot.DEFAULT_MBR_BOOT_CODE_CANDIDATES",
        (fake_syslinux,),
    )

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    resolver._seed_builtin_fat16_boot_records()
    cached_mbr = resolver._cached_fat16_mbr_boot_code_path().read_bytes()

    builtin_mbr = base64.b64decode(_BUILTIN_MSDOS_MBR_BOOT_CODE_B64)[:440]
    assert cached_mbr == syslinux_mbr_payload[:440]
    assert cached_mbr != builtin_mbr, (
        "Should not seed builtin 71-byte MBR when syslinux mbr.bin is available"
    )


def test_seed_builtin_fat16_boot_records_falls_back_to_builtin_without_syslinux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On hosts without syslinux installed (e.g. Windows), the builtin
    71-byte MBR must still be seeded as a last-resort fallback."""
    monkeypatch.setattr("dosforge.boot.DEFAULT_MBR_BOOT_CODE_CANDIDATES", ())

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    resolver._seed_builtin_fat16_boot_records()
    cached_mbr = resolver._cached_fat16_mbr_boot_code_path().read_bytes()

    builtin_mbr = base64.b64decode(_BUILTIN_MSDOS_MBR_BOOT_CODE_B64)[:440]
    assert cached_mbr == builtin_mbr


def test_load_cached_fat16_boot_records_invalidates_stale_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for v0.9.3: existing users who already had the
    71-byte builtin cached must get their cache invalidated when
    syslinux becomes available, so the next build picks up the
    LBA-aware MBR instead of reusing the stale stub."""
    syslinux_mbr_payload = b"\xfa\x31\xc0\x8e\xd0" + b"X" * 435
    fake_syslinux = tmp_path / "syslinux-mbr.bin"
    fake_syslinux.write_bytes(syslinux_mbr_payload)
    monkeypatch.setattr(
        "dosforge.boot.DEFAULT_MBR_BOOT_CODE_CANDIDATES",
        (fake_syslinux,),
    )

    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    # Plant the stale 71-byte builtin in the cache by hand.
    resolver._save_cached_fat16_boot_records(
        mbr_code=base64.b64decode(_BUILTIN_MSDOS_MBR_BOOT_CODE_B64),
        boot_sector=base64.b64decode(_BUILTIN_FAT16_BOOT_SECTOR_B64),
    )
    loaded = resolver._load_cached_fat16_boot_record_paths()
    assert loaded is None, (
        "Stale 71-byte builtin MBR must be rejected so the cache is"
        " re-seeded from the syslinux source on the next build."
    )


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


# --- pre-DOS-5 CONFIG.SYS defaults ---


def test_default_msdos_config_sys_pre_dos5_minimal(tmp_path: Path) -> None:
    """MSDOS 3.x must get a CONFIG.SYS that DOS 3.3 actually understands.

    DOS=HIGH, BUFFERS=N,M, LASTDRIVE=<number>, and DEVICE=HIMEM.SYS all
    trip "Unrecognized command in CONFIG.SYS" lines on DOS 3.3.
    """
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    text = resolver._default_msdos_config_sys(has_himem=False, pre_dos5=True)
    assert "DOS=" not in text.upper()
    assert "LASTDRIVE" not in text.upper()
    assert "HIMEM.SYS" not in text.upper()
    # BUFFERS=20 (single arg) is fine; BUFFERS=20,0 (two-arg) is not.
    assert ",0" not in text
    lines = [line for line in text.replace("\r\n", "\n").splitlines() if line.strip()]
    assert lines == ["FILES=30", "BUFFERS=20"]


def test_default_msdos_config_sys_modern_keeps_dos_high(tmp_path: Path) -> None:
    """Modern DOS (5.0+) gets the full DOS=HIGH/UMB/AUTO stack."""
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    text = resolver._default_msdos_config_sys(has_himem=True, pre_dos5=False)
    assert "DEVICE=HIMEM.SYS" in text
    assert "DOS=HIGH,UMB,AUTO" in text
    assert "BUFFERS=20,0" in text
    assert "LASTDRIVE=26" in text


def test_use_pre_dos5_config_sys_legacy_dos_modes() -> None:
    from dosforge.boot import _use_pre_dos5_config_sys

    for mode in (BootMode.MSDOS33, BootMode.MSDOS331, BootMode.COMPAQ331):
        request = CreateRequest(
            path=Path("/tmp/x.vhd"),
            size_bytes=32 * 1024 * 1024,
            disk_format=DiskFormat.FAT16,
            boot_mode=mode,
        )
        assert _use_pre_dos5_config_sys(request) is True, mode


def test_use_pre_dos5_config_sys_ibm8088_dos33_vs_dos50() -> None:
    from dosforge.boot import _use_pre_dos5_config_sys

    dos33 = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    dos50 = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS50,
    )
    assert _use_pre_dos5_config_sys(dos33) is True
    assert _use_pre_dos5_config_sys(dos50) is False


def test_use_pre_dos5_config_sys_modern_dos_modes() -> None:
    from dosforge.boot import _use_pre_dos5_config_sys

    for mode in (
        BootMode.MSDOS5,
        BootMode.MSDOS622,
        BootMode.PCDOS7,
        BootMode.MSDOS71,
        BootMode.FREEDOS,
    ):
        request = CreateRequest(
            path=Path("/tmp/x.vhd"),
            size_bytes=128 * 1024 * 1024,
            disk_format=DiskFormat.FAT16,
            boot_mode=mode,
        )
        assert _use_pre_dos5_config_sys(request) is False, mode


def test_resolve_msdos33_full_profile_writes_pre_dos5_config_sys(
    tmp_path: Path,
) -> None:
    """End-to-end: msdos33 FULL profile must stage a DOS-3.3-compatible CONFIG.SYS."""
    assets_dir = tmp_path / "msdos33-assets"
    _touch(assets_dir / "IO.SYS", b"io")
    _touch(assets_dir / "MSDOS.SYS", b"msdos")
    _touch(assets_dir / "COMMAND.COM", b"command")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())
    # Provide a DOS dir so the resolver can pick the FULL payload path.
    (assets_dir / "DOS" / "FDISK.COM").parent.mkdir(parents=True, exist_ok=True)
    (assets_dir / "DOS" / "FDISK.COM").write_bytes(b"fdisk")

    request = CreateRequest(
        path=tmp_path / "x.vhd",
        size_bytes=20 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.MSDOS33,
        boot_assets_path=assets_dir,
        msdos_install_profile=MSDOSInstallProfile.FULL,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)

    config_path = assets.system_files["CONFIG.SYS"]
    config_text = config_path.read_text(encoding="latin-1")
    # No DOS 5+ directives.
    assert "DOS=" not in config_text.upper()
    assert "LASTDRIVE" not in config_text.upper()
    assert "HIMEM" not in config_text.upper()
    assert ",0" not in config_text  # rule out BUFFERS=20,0


def test_resolve_freedos_local_auto_picks_dosassets_freedos(tmp_path: Path, monkeypatch) -> None:
    """When no boot_assets_path is given, FreeDOS LOCAL mode should auto-pick
    ./dosassets/freedos/."""
    monkeypatch.chdir(tmp_path)
    assets_dir = tmp_path / "dosassets" / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"k")
    _touch(assets_dir / "COMMAND.COM", b"c")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "fd.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        # No boot_assets_path → resolver should fall back to dosassets/freedos.
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    assert "KERNEL.SYS" in assets.system_files
    assert assets.system_files["KERNEL.SYS"].read_bytes() == b"k"


def test_resolve_freedos_local_bare_name_resolves_under_dosassets(
    tmp_path: Path, monkeypatch
) -> None:
    """Bare boot_assets_path='freedos' must resolve to ./dosassets/freedos/."""
    monkeypatch.chdir(tmp_path)
    assets_dir = tmp_path / "dosassets" / "freedos"
    _touch(assets_dir / "KERNEL.SYS", b"k")
    _touch(assets_dir / "COMMAND.COM", b"c")
    _touch(assets_dir / "BOOTSECT_FAT16.BIN", _msdos_fat16_boot_sector_bytes())

    request = CreateRequest(
        path=tmp_path / "fd.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=Path("freedos"),
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    assets = resolver.resolve(request)
    assert "KERNEL.SYS" in assets.system_files


def test_resolve_freedos_local_error_mentions_dosassets(tmp_path: Path, monkeypatch) -> None:
    """When dosassets/freedos/ is missing, the error should point users there."""
    monkeypatch.chdir(tmp_path)
    request = CreateRequest(
        path=tmp_path / "fd.vhd",
        size_bytes=128 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
    )
    resolver = BootAssetResolver(CommandRunner(), cache_root=tmp_path / "cache")
    with pytest.raises(ValidationError, match=r"dosassets/freedos"):
        resolver.resolve(request)
