from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from vhdmaker.disk import DiskManager
from vhdmaker.e2e_emulator import qemu_boot_probe
from vhdmaker.errors import ValidationError
from vhdmaker.models import BootMode, CreateRequest, DiskFormat, FreeDOSSource, MediaType


def _native_boot_test_ready() -> tuple[bool, str]:
    required_commands = (
        "sudo",
        "qemu-img",
        "qemu-nbd",
        "parted",
        "partprobe",
        "mkfs.fat",
        "mount",
        "umount",
        "mcopy",
        "mattrib",
        "dd",
        "qemu-system-i386",
    )
    missing = [command for command in required_commands if shutil.which(command) is None]
    if missing:
        return (False, f"Missing required native boot test commands: {', '.join(missing)}")

    sudo_probe = subprocess.run(
        ["sudo", "-n", "true"],
        check=False,
        capture_output=True,
        text=True,
    )
    if sudo_probe.returncode != 0:
        detail = sudo_probe.stderr.strip() or sudo_probe.stdout.strip() or f"exit code {sudo_probe.returncode}"
        return (False, f"Native boot tests require non-interactive sudo: {detail}")

    assets_root = _freedos_assets_root()
    required_files = ("KERNEL.SYS", "COMMAND.COM", "BOOTSECT_FAT32.BIN")
    missing_files = [name for name in required_files if not (assets_root / name).is_file()]
    if missing_files:
        return (
            False,
            "Missing FreeDOS boot assets for native boot test "
            f"under {assets_root}: {', '.join(missing_files)}",
        )

    return (True, "")


def _freedos_assets_root() -> Path:
    configured = os.environ.get("VHDMAKER_NATIVE_FREEDOS_ASSETS")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "freedos").resolve()


class _VhdBootCase(NamedTuple):
    boot_mode: BootMode
    disk_format: DiskFormat
    assets_dir_name: str
    size_mb: int = 300


_VHD_BOOT_CASES: tuple[_VhdBootCase, ...] = (
    _VhdBootCase(BootMode.FREEDOS, DiskFormat.FAT16, "freedos"),
    _VhdBootCase(BootMode.FREEDOS, DiskFormat.FAT32, "freedos"),
    _VhdBootCase(BootMode.MSDOS71, DiskFormat.FAT16, "msdos7"),
    _VhdBootCase(BootMode.MSDOS71, DiskFormat.FAT32, "msdos7"),
    _VhdBootCase(BootMode.MSDOS331, DiskFormat.FAT16, "msdos331"),
    _VhdBootCase(BootMode.MSDOS5, DiskFormat.FAT16, "msdos5"),
    _VhdBootCase(BootMode.MSDOS622, DiskFormat.FAT16, "msdos622"),
    _VhdBootCase(BootMode.PCDOS, DiskFormat.FAT16, "pcdos7"),
    _VhdBootCase(BootMode.PCDOS7, DiskFormat.FAT16, "pcdos7"),
    _VhdBootCase(BootMode.COMPAQ331, DiskFormat.FAT16, "compaq331"),
)


def _resolve_assets_dir(name: str) -> Path:
    root = (Path.cwd() / name).resolve()
    if not root.exists():
        pytest.skip(f"Assets directory not found: {root}")
    return root


_NATIVE_BOOT_READY, _NATIVE_BOOT_REASON = _native_boot_test_ready()

pytestmark = [
    pytest.mark.native_linux,
    pytest.mark.native_boot,
    pytest.mark.skipif(not _NATIVE_BOOT_READY, reason=_NATIVE_BOOT_REASON),
]


def test_native_vhd_freedos_fat32_custom_payload_boots(tmp_path: Path) -> None:
    manager = DiskManager()
    assets_root = _freedos_assets_root()
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "AUTOEXEC.BAT").write_text("@ECHO OFF\r\n", encoding="ascii")
    (payload_dir / "README.TXT").write_text("native boot test payload", encoding="ascii")

    vhd_path = tmp_path / "freedos-fat32-custom.vhd"
    request = CreateRequest(
        path=vhd_path,
        size_bytes=300 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        media_type=MediaType.VHD,
        boot_mode=BootMode.FREEDOS,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=assets_root,
        custom_payload_path=payload_dir,
        overwrite=True,
    )

    manager.create_and_prepare(request)

    boot_ok, detail = qemu_boot_probe(
        image_path=vhd_path,
        image_format="vpc",
        timeout_seconds=90,
        expect_shell_prompt=False,
        diagnostics_dir=tmp_path / "diagnostics",
        case_id="freedos-fat32-custom",
    )
    assert boot_ok, detail


def test_native_vhd_msdos71_fat32_custom_payload_boots(tmp_path: Path) -> None:
    manager = DiskManager()
    payload_dir = tmp_path / "payload-msdos71"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "AUTOEXEC.BAT").write_text("@ECHO OFF\r\n", encoding="ascii")
    (payload_dir / "README.TXT").write_text("native msdos71 payload", encoding="ascii")

    assets_root = (Path.cwd() / "msdos7").resolve()
    if not assets_root.exists():
        pytest.skip(f"MS-DOS 7.1 assets directory not found: {assets_root}")

    vhd_path = tmp_path / "msdos71-fat32-custom.vhd"
    request = CreateRequest(
        path=vhd_path,
        size_bytes=300 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_root,
        custom_payload_path=payload_dir,
        overwrite=True,
    )

    manager.create_and_prepare(request)
    boot_ok, detail = qemu_boot_probe(
        image_path=vhd_path,
        image_format="vpc",
        timeout_seconds=90,
        expect_shell_prompt=False,
        diagnostics_dir=tmp_path / "diagnostics",
        case_id="msdos71-fat32-custom",
    )
    assert boot_ok, detail


@pytest.mark.parametrize("case", _VHD_BOOT_CASES, ids=lambda case: f"{case.boot_mode.value}-{case.disk_format.value}")
def test_native_vhd_boot_matrix_minimal_profile(tmp_path: Path, case: _VhdBootCase) -> None:
    manager = DiskManager()
    assets_root = _resolve_assets_dir(case.assets_dir_name)
    payload_dir = tmp_path / f"payload-{case.boot_mode.value}"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "AUTOEXEC.BAT").write_text("@ECHO OFF\r\n", encoding="ascii")
    (payload_dir / "PAYLOAD.TXT").write_text(case.boot_mode.value, encoding="ascii")

    request = CreateRequest(
        path=tmp_path / f"{case.boot_mode.value}-{case.disk_format.value}.vhd",
        size_bytes=case.size_mb * 1024 * 1024,
        disk_format=case.disk_format,
        media_type=MediaType.VHD,
        boot_mode=case.boot_mode,
        boot_assets_path=assets_root,
        custom_payload_path=payload_dir,
        overwrite=True,
    )
    if case.boot_mode is BootMode.FREEDOS:
        request.freedos_source = FreeDOSSource.LOCAL
    try:
        manager.create_and_prepare(request)
    except ValidationError as exc:
        if "floppy FAT12 boot sector" in str(exc):
            pytest.skip(str(exc))
        raise
    boot_ok, detail = qemu_boot_probe(
        image_path=request.path,
        image_format="vpc",
        timeout_seconds=45,
        expect_shell_prompt=False,
        diagnostics_dir=tmp_path / "diagnostics",
        case_id=f"{case.boot_mode.value}-{case.disk_format.value}",
    )
    assert boot_ok, detail
