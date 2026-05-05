from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from vhdmaker.boot import BootAssets, BootInstaller
from vhdmaker.commands import RunResult
from vhdmaker.errors import ValidationError
from vhdmaker.models import DiskFormat


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], bool]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        sudo: bool = False,
        check: bool = True,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        del check, cwd, env
        command_tuple = tuple(command)
        self.calls.append((command_tuple, sudo))
        return RunResult(command=command_tuple, returncode=0, stdout="", stderr="")


def _touch(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_boot_installer_writes_mbr_boot_code_before_partition_boot_code(tmp_path: Path) -> None:
    runner = FakeRunner()
    mbr = tmp_path / "mbr.bin"
    _touch(mbr, b"\0" * 440)
    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    _touch(boot_template, b"\0" * 512)
    kernel = tmp_path / "KERNEL.SYS"
    _touch(kernel, b"k")

    payload_root = tmp_path / "FDOS"
    _touch(payload_root / "BIN" / "EDIT.COM", b"e")

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(mbr,),
    )
    assets = BootAssets(
        system_files={"KERNEL.SYS": kernel},
        boot_sector_template=boot_template,
        fdos_payload_dir=payload_root,
    )

    installer.make_partition_bootable(
        disk_device="/dev/nbd0",
        partition_device="/dev/nbd0p1",
        disk_format=DiskFormat.FAT16,
        assets=assets,
    )

    assert runner.calls[0][0][:2] == ("dd", f"if={mbr}")
    assert runner.calls[0][0][2] == "of=/dev/nbd0"
    assert any(
        command == ("mcopy", "-o", "-i", "/dev/nbd0p1", str(kernel), "::KERNEL.SYS") and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("mattrib", "-i", "/dev/nbd0p1", "+s", "+h", "::KERNEL.SYS") and sudo
        for command, sudo in runner.calls
    )


def test_boot_installer_patches_fat16_bpb_geometry_from_vhd_footer(tmp_path: Path) -> None:
    runner = FakeRunner()
    mbr = tmp_path / "mbr.bin"
    _touch(mbr, b"\0" * 440)
    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    _touch(boot_template, b"\0" * 512)

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(mbr,),
    )
    assets = BootAssets(system_files={}, boot_sector_template=boot_template, fdos_payload_dir=None)

    installer.make_partition_bootable(
        disk_device="/dev/nbd0",
        partition_device="/dev/nbd0p1",
        disk_format=DiskFormat.FAT16,
        assets=assets,
        bios_chs=(17, 12),
    )

    assert any(
        command[0] == "dd" and "seek=24" in command and "count=4" in command and sudo
        for command, sudo in runner.calls
    )


def test_boot_installer_uses_asset_mbr_template_when_provided(tmp_path: Path) -> None:
    runner = FakeRunner()
    custom_mbr = tmp_path / "custom-mbr.bin"
    _touch(custom_mbr, b"\x7f" * 440)
    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    _touch(boot_template, b"\0" * 512)
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    assets = BootAssets(
        system_files={},
        boot_sector_template=boot_template,
        fdos_payload_dir=None,
        mbr_boot_code_template=custom_mbr,
    )

    installer.make_partition_bootable(
        disk_device="/dev/nbd0",
        partition_device="/dev/nbd0p1",
        disk_format=DiskFormat.FAT16,
        assets=assets,
    )

    assert runner.calls[0][0][:2] == ("dd", f"if={custom_mbr}")
    assert runner.calls[0][0][2] == "of=/dev/nbd0"


def test_boot_installer_uses_payload_target_dir_for_staged_copy(tmp_path: Path) -> None:
    runner = FakeRunner()
    mbr = tmp_path / "mbr.bin"
    _touch(mbr, b"\0" * 440)
    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    _touch(boot_template, b"\0" * 512)
    payload_root = tmp_path / "DOS"
    _touch(payload_root / "EDIT.COM", b"e")

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(mbr,),
    )
    captured: dict[str, object] = {}

    def fake_copy_payload_via_mount(*, partition_device: str, payload_dir: Path, payload_target_dir: str) -> None:
        captured["partition_device"] = partition_device
        captured["payload_dir"] = payload_dir
        captured["payload_target_dir"] = payload_target_dir

    installer._copy_payload_via_mount = fake_copy_payload_via_mount  # type: ignore[method-assign]
    assets = BootAssets(
        system_files={},
        boot_sector_template=boot_template,
        fdos_payload_dir=payload_root,
        payload_target_dir="DOS",
    )

    installer.make_partition_bootable(
        disk_device="/dev/nbd0",
        partition_device="/dev/nbd0p1",
        disk_format=DiskFormat.FAT16,
        assets=assets,
    )

    assert captured["partition_device"] == "/dev/nbd0p1"
    assert captured["payload_dir"] == payload_root
    assert captured["payload_target_dir"] == "DOS"


def test_boot_installer_reports_missing_mbr_boot_code(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    with pytest.raises(ValidationError, match="Unable to locate syslinux MBR boot code file"):
        installer._find_mbr_boot_code()


def test_prepare_source_file_normalizes_config_sys(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    config = tmp_path / "CONFIG.SYS"
    _touch(config, b"SHELL=A:\\COMMAND.COM /E:512 /MSG /P\r\n")
    temp_files: list[Path] = []

    prepared = installer._prepare_source_file(
        destination_name="CONFIG.SYS",
        source_path=config,
        temp_files=temp_files,
    )

    assert prepared != config
    assert "SHELL=C:\\COMMAND.COM" in prepared.read_text(encoding="latin-1")
    assert b"\r\n" in prepared.read_bytes()
    assert len(temp_files) == 1


def test_prepare_source_file_converts_lf_config_to_crlf(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    config = tmp_path / "CONFIG.SYS"
    _touch(config, b"SHELL=C:\\COMMAND.COM /E:512 /MSG /P\nFILES=20\n")
    temp_files: list[Path] = []

    prepared = installer._prepare_source_file(
        destination_name="CONFIG.SYS",
        source_path=config,
        temp_files=temp_files,
    )

    assert prepared != config
    raw = prepared.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert len(temp_files) == 1


def test_prepare_source_file_normalizes_minimal_autoexec(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    autoexec = tmp_path / "AUTOEXEC.BAT"
    _touch(autoexec, b"ECHO OFF\r\n\r\ncls\r\n")
    temp_files: list[Path] = []

    prepared = installer._prepare_source_file(
        destination_name="AUTOEXEC.BAT",
        source_path=autoexec,
        temp_files=temp_files,
    )

    assert prepared != autoexec
    content = prepared.read_text(encoding="latin-1")
    assert "SET DOSDIR=C:\\FDOS" in content
    assert "PROMPT $P$G" in content
    assert b"\r\n" in prepared.read_bytes()
    assert len(temp_files) == 1


def test_prepare_source_file_normalizes_fdauto_alias(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    fdauto = tmp_path / "FDAUTO.BAT"
    _touch(fdauto, b"ECHO OFF\r\n\r\ncls\r\n")
    temp_files: list[Path] = []

    prepared = installer._prepare_source_file(
        destination_name="FDAUTO.BAT",
        source_path=fdauto,
        temp_files=temp_files,
    )

    assert prepared != fdauto
    content = prepared.read_text(encoding="latin-1")
    assert "SET DOSDIR=C:\\FDOS" in content
    assert "PROMPT $P$G" in content
    assert b"\r\n" in prepared.read_bytes()
    assert len(temp_files) == 1
