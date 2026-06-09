from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dosforge.boot import BootAssets, BootInstaller
from dosforge.commands import CommandRunner
from dosforge.disk import DiskManager
from dosforge.models import BootMode, FloppyType


def _native_test_ready() -> tuple[bool, str]:
    if os.environ.get("DOSFORGE_RUN_NATIVE_IMG_TESTS") != "1":
        return (False, "Set DOSFORGE_RUN_NATIVE_IMG_TESTS=1 to run native Linux mount integration tests.")

    required_commands = ("sudo", "mkfs.fat", "fsck.fat", "mount", "umount", "mcopy", "mattrib", "dd")
    missing = [command for command in required_commands if shutil.which(command) is None]
    if missing:
        return (False, f"Missing required native test commands: {', '.join(missing)}")

    sudo_probe = subprocess.run(
        ["sudo", "-n", "true"],
        check=False,
        capture_output=True,
        text=True,
    )
    if sudo_probe.returncode != 0:
        detail = sudo_probe.stderr.strip() or sudo_probe.stdout.strip() or f"exit code {sudo_probe.returncode}"
        return (False, f"Native mount tests require non-interactive sudo: {detail}")

    return (True, "")


_NATIVE_READY, _NATIVE_REASON = _native_test_ready()

pytestmark = [
    pytest.mark.native_linux,
    pytest.mark.skipif(not _NATIVE_READY, reason=_NATIVE_REASON),
]


def _run_privileged(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", *command],
        check=False,
        capture_output=True,
        text=True,
    )


def _mount_ro_loop(image_path: Path, mountpoint: Path) -> None:
    mount_result = _run_privileged(["mount", "-t", "vfat", "-o", "loop,ro", str(image_path), str(mountpoint)])
    assert mount_result.returncode == 0, (
        f"mount failed for {image_path}: "
        f"{mount_result.stderr.strip() or mount_result.stdout.strip() or mount_result.returncode}"
    )


def _umount(mountpoint: Path) -> None:
    umount_result = _run_privileged(["umount", str(mountpoint)])
    assert umount_result.returncode == 0, (
        f"umount failed for {mountpoint}: "
        f"{umount_result.stderr.strip() or umount_result.stdout.strip() or umount_result.returncode}"
    )


@pytest.mark.parametrize("floppy_type", list(FloppyType))
def test_native_linux_mount_and_fsck_match_floppy_geometry(tmp_path: Path, floppy_type: FloppyType) -> None:
    manager = DiskManager()
    image_path = tmp_path / f"{floppy_type.value}.img"
    manager._create_fixed_img(image_path, floppy_type)
    manager._format_floppy_img(image_path, floppy_type=floppy_type, label=None)

    fsck = subprocess.run(
        ["fsck.fat", "-vn", str(image_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert fsck.returncode == 0, fsck.stderr or fsck.stdout
    report = f"{fsck.stdout}\n{fsck.stderr}"
    spec = floppy_type.spec
    assert "12 bit entries" in report
    assert f"Media byte 0x{spec.media_descriptor:02x}" in report
    assert f"{spec.root_entries} root directory entries" in report
    assert f"{spec.sectors_per_track} sectors/track, {spec.heads} heads" in report
    assert f"{spec.total_sectors} sectors total" in report

    mountpoint = tmp_path / f"mnt-{floppy_type.value}"
    mountpoint.mkdir()
    _mount_ro_loop(image_path, mountpoint)
    try:
        assert list(mountpoint.iterdir()) == []
    finally:
        _umount(mountpoint)


def test_native_linux_mount_shows_boot_system_files_at_root(tmp_path: Path) -> None:
    floppy_type = FloppyType.F720K
    manager = DiskManager()
    image_path = tmp_path / "legacy-boot.img"
    manager._create_fixed_img(image_path, floppy_type)
    manager._format_floppy_img(image_path, floppy_type=floppy_type, label=None)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(image_path.read_bytes()[:512])
    io_sys = tmp_path / "IO.SYS"
    msdos_sys = tmp_path / "MSDOS.SYS"
    command_com = tmp_path / "COMMAND.COM"
    io_sys.write_bytes(b"io-system")
    msdos_sys.write_bytes(b"msdos-system")
    command_com.write_bytes(b"command")

    assets = BootAssets(
        system_files={
            "IO.SYS": io_sys,
            "MSDOS.SYS": msdos_sys,
            "COMMAND.COM": command_com,
        },
        boot_sector_template=boot_template,
        fdos_payload_dir=None,
    )
    installer = BootInstaller(CommandRunner())
    installer.make_floppy_bootable(
        image_path=image_path,
        assets=assets,
        boot_mode=BootMode.PCDOS7,
        floppy_type=floppy_type,
        verify_legacy_layout=True,
    )

    mountpoint = tmp_path / "mnt-legacy"
    mountpoint.mkdir()
    _mount_ro_loop(image_path, mountpoint)
    try:
        names = {entry.name.upper() for entry in mountpoint.iterdir()}
        assert {"IO.SYS", "MSDOS.SYS", "COMMAND.COM"}.issubset(names)
    finally:
        _umount(mountpoint)
