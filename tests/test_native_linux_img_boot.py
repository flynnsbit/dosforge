from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from dosforge.disk import DiskManager
from dosforge.e2e_emulator import qemu_boot_probe
from dosforge.models import BootMode, CreateRequest, DiskFormat, FloppyType, FreeDOSSource, IBMDOSVersion, MediaType


def _native_boot_test_ready() -> tuple[bool, str]:
    required_commands = (
        "sudo",
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
        return (False, f"Missing required native IMG boot test commands: {', '.join(missing)}")

    sudo_probe = subprocess.run(
        ["sudo", "-n", "true"],
        check=False,
        capture_output=True,
        text=True,
    )
    if sudo_probe.returncode != 0:
        detail = sudo_probe.stderr.strip() or sudo_probe.stdout.strip() or f"exit code {sudo_probe.returncode}"
        return (False, f"Native IMG boot tests require non-interactive sudo: {detail}")

    return (True, "")


class _ImgBootCase(NamedTuple):
    boot_mode: BootMode
    assets_dir_name: str
    floppy_type: FloppyType
    ibm_version: IBMDOSVersion = IBMDOSVersion.DOS33


_IMG_BOOT_CASES: tuple[_ImgBootCase, ...] = (
    _ImgBootCase(BootMode.MSDOS71, "msdos7", FloppyType.F1440K),
    _ImgBootCase(BootMode.IBM8088, "msdos33", FloppyType.F360K, IBMDOSVersion.DOS33),
    _ImgBootCase(BootMode.MSDOS33, "msdos33", FloppyType.F360K),
    _ImgBootCase(BootMode.MSDOS331, "msdos331", FloppyType.F720K),
    _ImgBootCase(BootMode.MSDOS5, "msdos5", FloppyType.F1200K),
    _ImgBootCase(BootMode.MSDOS622, "msdos622", FloppyType.F1440K),
    _ImgBootCase(BootMode.PCDOS, "pcdos7", FloppyType.F1440K),
    _ImgBootCase(BootMode.PCDOS7, "pcdos7", FloppyType.F1440K),
    _ImgBootCase(BootMode.COMPAQ331, "compaq331", FloppyType.F720K),
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


@pytest.mark.parametrize("case", _IMG_BOOT_CASES, ids=lambda case: f"{case.boot_mode.value}-{case.floppy_type.value}")
def test_native_img_boot_matrix_system_format(tmp_path: Path, case: _ImgBootCase) -> None:
    manager = DiskManager()
    assets_root = _resolve_assets_dir(case.assets_dir_name)
    payload_dir = tmp_path / f"payload-{case.boot_mode.value}"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "AUTOEXEC.BAT").write_text("@ECHO OFF\r\n", encoding="ascii")
    (payload_dir / "PAYLOAD.TXT").write_text(case.boot_mode.value, encoding="ascii")

    request = CreateRequest(
        path=tmp_path / f"{case.boot_mode.value}-{case.floppy_type.value}.img",
        size_bytes=case.floppy_type.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=case.floppy_type,
        boot_mode=case.boot_mode,
        boot_assets_path=assets_root,
        img_system_format=True,
        custom_payload_path=payload_dir,
        overwrite=True,
    )
    if case.boot_mode is BootMode.FREEDOS:
        request.freedos_source = FreeDOSSource.LOCAL
    if case.boot_mode is BootMode.IBM8088:
        request.ibm_dos_version = case.ibm_version

    manager.create_and_prepare(request)
    boot_ok, detail = qemu_boot_probe(
        image_path=request.path,
        image_format="raw",
        timeout_seconds=45,
        expect_shell_prompt=False,
        boot_media="floppy",
        diagnostics_dir=tmp_path / "diagnostics",
        case_id=f"{case.boot_mode.value}-{case.floppy_type.value}",
    )
    assert boot_ok, detail
