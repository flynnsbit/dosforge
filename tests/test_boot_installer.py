from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

import dosforge.boot as boot_module
from dosforge.boot import BootAssets, BootInstaller
from dosforge.commands import RunResult
from dosforge.errors import ValidationError
from dosforge.models import BootMode, DiskFormat


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
        command == ("mattrib", "-i", "/dev/nbd0p1", "+r", "+s", "+h", "-a", "::KERNEL.SYS") and sudo
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


def test_copy_payload_via_mount_expands_compressed_dos_payload_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    mount_root = tmp_path / "mount-root"
    payload_root = tmp_path / "DOS"
    _touch(payload_root / "SUBST.EX_", b"compressed")
    _touch(payload_root / "KEYB.COM", b"keyb")

    installer = BootInstaller(
        runner,
        mount_root=mount_root,
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    monkeypatch.setattr(boot_module, "expand_dos_compressed_payload", lambda payload: b"expanded")

    removed_paths: list[Path] = []

    def fake_rmtree(path: Path) -> None:
        removed_paths.append(Path(path))

    monkeypatch.setattr(boot_module.shutil, "rmtree", fake_rmtree)
    installer._copy_payload_via_mount(
        partition_device=str(tmp_path / "disk.img"),
        payload_dir=payload_root,
        payload_target_dir="DOS",
    )

    staging_dirs = [path for path in mount_root.glob("staging-*") if path.is_dir()]
    assert len(staging_dirs) == 1
    staged_root = staging_dirs[0] / "DOS"
    assert (staged_root / "SUBST.EXE").read_bytes() == b"expanded"
    assert not (staged_root / "SUBST.EX_").exists()
    assert (staged_root / "KEYB.COM").read_bytes() == b"keyb"
    assert removed_paths and removed_paths[0] == staging_dirs[0]


def test_copy_payload_via_mount_raises_when_compressed_payload_cannot_expand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner()
    payload_root = tmp_path / "DOS"
    _touch(payload_root / "SUBST.EX_", b"compressed")
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )

    def failing_expand(payload: bytes) -> bytes:
        del payload
        raise ValidationError("decode failed")

    monkeypatch.setattr(boot_module, "expand_dos_compressed_payload", failing_expand)
    with pytest.raises(ValidationError, match="Unable to expand compressed DOS payload file SUBST.EX_"):
        installer._copy_payload_via_mount(
            partition_device=str(tmp_path / "disk.img"),
            payload_dir=payload_root,
            payload_target_dir="DOS",
        )


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


def test_prepare_source_file_skips_freedos_normalization_for_msdos_modes(tmp_path: Path) -> None:
    runner = FakeRunner()
    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    config = tmp_path / "CONFIG.SYS"
    _touch(config, b"SHELL=A:\\COMMAND.COM /P\r\n")
    temp_files: list[Path] = []

    prepared = installer._prepare_source_file(
        destination_name="CONFIG.SYS",
        source_path=config,
        temp_files=temp_files,
        boot_mode=BootMode.IBM8088,
    )

    assert prepared == config
    assert temp_files == []


def test_make_floppy_bootable_writes_boot_sector_and_system_files(tmp_path: Path) -> None:
    runner = FakeRunner()
    boot_template = tmp_path / "BOOTSECT.BIN"
    _touch(boot_template, b"\0" * 512)
    ibmbio = tmp_path / "IBMBIO.COM"
    ibmdos = tmp_path / "IBMDOS.COM"
    command = tmp_path / "COMMAND.COM"
    _touch(ibmbio, b"bios")
    _touch(ibmdos, b"dos")
    _touch(command, b"command")

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    assets = BootAssets(
        system_files={
            "IBMBIO.COM": ibmbio,
            "IBMDOS.COM": ibmdos,
            "COMMAND.COM": command,
        },
        boot_sector_template=boot_template,
        fdos_payload_dir=None,
    )
    image_path = tmp_path / "disk.img"
    image_path.write_bytes(b"\0" * (1440 * 1024))

    installer.make_floppy_bootable(
        image_path=image_path,
        assets=assets,
        boot_mode=BootMode.PCDOS,
    )

    assert any(
        command[:3] == ("dd", f"if={boot_template}", f"of={str(image_path)}") and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("mcopy", "-o", "-i", str(image_path), str(ibmbio), "::IBMBIO.COM") and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("mattrib", "-i", str(image_path), "+r", "+s", "+h", "-a", "::IBMBIO.COM") and sudo
        for command, sudo in runner.calls
    )
    assert not any(
        command == ("mattrib", "-i", str(image_path), "+r", "+s", "+h", "-a", "::COMMAND.COM") and sudo
        for command, sudo in runner.calls
    )
    assert not any(
        command == ("mattrib", "-i", str(image_path), "-r", "-s", "-h", "::COMMAND.COM") and sudo
        for command, sudo in runner.calls
    )


def test_make_floppy_bootable_normalizes_msdos_command_attributes(tmp_path: Path) -> None:
    runner = FakeRunner()
    boot_template = tmp_path / "BOOTSECT.BIN"
    _touch(boot_template, b"\0" * 512)
    io = tmp_path / "IO.SYS"
    msdos = tmp_path / "MSDOS.SYS"
    command = tmp_path / "COMMAND.COM"
    _touch(io, b"io")
    _touch(msdos, b"msdos")
    _touch(command, b"command")

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    assets = BootAssets(
        system_files={
            "IO.SYS": io,
            "MSDOS.SYS": msdos,
            "COMMAND.COM": command,
        },
        boot_sector_template=boot_template,
        fdos_payload_dir=None,
    )
    image_path = tmp_path / "disk-msdos.img"
    image_path.write_bytes(b"\0" * (1440 * 1024))

    installer.make_floppy_bootable(
        image_path=image_path,
        assets=assets,
        boot_mode=BootMode.MSDOS622,
    )

    assert any(
        command == ("mattrib", "-i", str(image_path), "+r", "+s", "+h", "-a", "::IO.SYS") and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("mattrib", "-i", str(image_path), "+r", "+s", "+h", "-a", "::MSDOS.SYS") and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("mattrib", "-i", str(image_path), "-r", "-s", "-h", "::COMMAND.COM") and sudo
        for command, sudo in runner.calls
    )
    assert not any(
        command == ("mattrib", "-i", str(image_path), "+r", "+s", "+h", "-a", "::COMMAND.COM") and sudo
        for command, sudo in runner.calls
    )


def test_make_floppy_bootable_uses_legacy_dos33_code_offset(tmp_path: Path) -> None:
    runner = FakeRunner()
    boot_template = tmp_path / "BOOTSECT.BIN"
    sector = bytearray(512)
    sector[:3] = b"\xeb\x3c\x90"
    sector[11:13] = (512).to_bytes(2, "little")
    sector[13] = 2
    sector[14:16] = (1).to_bytes(2, "little")
    sector[16] = 2
    sector[17:19] = (112).to_bytes(2, "little")
    sector[21] = 0xFD
    sector[22:24] = (2).to_bytes(2, "little")
    sector[24:26] = (9).to_bytes(2, "little")
    sector[26:28] = (2).to_bytes(2, "little")
    # Legacy DOS 3.x style templates don't include FAT12/FAT16 text at 54.
    sector[54:62] = b"\xFA\x33\xC0\x8E\xD0\xBC\x00\x7C"
    sector[510:512] = b"\x55\xaa"
    _touch(boot_template, bytes(sector))
    image_path = tmp_path / "disk.img"
    image_path.write_bytes(b"\0" * (1440 * 1024))

    installer = BootInstaller(
        runner,
        mount_root=tmp_path / "mount-root",
        mbr_boot_candidates=(tmp_path / "missing-mbr.bin",),
    )
    assets = BootAssets(system_files={}, boot_sector_template=boot_template, fdos_payload_dir=None)
    installer.make_floppy_bootable(
        image_path=image_path,
        assets=assets,
        boot_mode=BootMode.IBM8088,
    )

    assert any(
        command[0] == "dd"
        and "skip=54" in command
        and "seek=54" in command
        and "count=456" in command
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command[0] == "dd"
        and command[2] == f"of={str(image_path)}"
        and "skip=3" in command
        and "seek=3" in command
        and "count=8" in command
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command[0] == "dd"
        and command[2] == f"of={str(image_path)}"
        and "skip=38" in command
        and "seek=38" in command
        and "count=16" in command
        and sudo
        for command, sudo in runner.calls
    )


def test_make_partition_bootable_uses_legacy_dos33_code_offset(tmp_path: Path) -> None:
    runner = FakeRunner()
    mbr = tmp_path / "mbr.bin"
    _touch(mbr, b"\0" * 440)
    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    sector = bytearray(512)
    sector[:3] = b"\xeb\x3c\x90"
    sector[11:13] = (512).to_bytes(2, "little")
    sector[13] = 2
    sector[14:16] = (1).to_bytes(2, "little")
    sector[16] = 2
    sector[17:19] = (112).to_bytes(2, "little")
    sector[21] = 0xFD
    sector[22:24] = (2).to_bytes(2, "little")
    sector[24:26] = (9).to_bytes(2, "little")
    sector[26:28] = (2).to_bytes(2, "little")
    sector[54:62] = b"\xFA\x33\xC0\x8E\xD0\xBC\x00\x7C"
    sector[510:512] = b"\x55\xaa"
    _touch(boot_template, bytes(sector))

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
        boot_mode=BootMode.IBM8088,
    )

    assert any(
        command[0] == "dd"
        and command[2] == "of=/dev/nbd0p1"
        and "skip=54" in command
        and "seek=54" in command
        and "count=456" in command
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command[0] == "dd"
        and command[2] == "of=/dev/nbd0p1"
        and "skip=3" in command
        and "seek=3" in command
        and "count=8" in command
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command[0] == "dd"
        and command[2] == "of=/dev/nbd0p1"
        and "skip=38" in command
        and "seek=38" in command
        and "count=16" in command
        and sudo
        for command, sudo in runner.calls
    )
