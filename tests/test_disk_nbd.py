from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Callable, Sequence

import pytest

from vhdmaker.boot import BootAssetResolver, BootAssets, BootInstaller
from vhdmaker.commands import RunResult
from vhdmaker.disk import DiskManager
from vhdmaker.errors import ValidationError
from vhdmaker.models import BootMode, CreateRequest, DiskFormat
from vhdmaker.state import StateStore


class FakeRunner:
    def __init__(
        self,
        on_run: Callable[[Sequence[str], bool], RunResult] | None = None,
    ) -> None:
        self.on_run = on_run
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
        if self.on_run is not None:
            return self.on_run(command_tuple, sudo)
        return RunResult(command=command_tuple, returncode=0, stdout="", stderr="")

    def run_detached(self, command: Sequence[str]) -> None:
        del command


def _manager(tmp_path: Path, runner: FakeRunner) -> DiskManager:
    return DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=BootAssetResolver(runner, cache_root=tmp_path / "cache"),
        boot_installer=BootInstaller(runner, mount_root=tmp_path / "boot"),
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )


def test_find_free_nbd_loads_module_when_devices_missing(tmp_path: Path) -> None:
    sys_block = tmp_path / "sys-class-block"
    dev_root = tmp_path / "dev"
    sys_block.mkdir(parents=True)
    dev_root.mkdir(parents=True)

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        if command[:2] == ("modprobe", "nbd"):
            (sys_block / "nbd0").mkdir(parents=True, exist_ok=True)
            (dev_root / "nbd0").write_text("", encoding="utf-8")
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    runner = FakeRunner(on_run=on_run)
    manager = _manager(tmp_path, runner)

    assert manager._find_free_nbd() == str(dev_root / "nbd0")
    assert any(command[:2] == ("modprobe", "nbd") and sudo for command, sudo in runner.calls)


def test_find_free_nbd_reports_modprobe_failure(tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        if command[:2] == ("modprobe", "nbd"):
            return RunResult(
                command=tuple(command),
                returncode=1,
                stdout="",
                stderr="modprobe: FATAL: Module nbd not found",
            )
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    manager = _manager(tmp_path, FakeRunner(on_run=on_run))
    with pytest.raises(ValidationError, match="modprobe nbd max_part=16"):
        manager._find_free_nbd()


def test_find_free_nbd_reports_missing_device_nodes(tmp_path: Path) -> None:
    sys_block = tmp_path / "sys-class-block"
    sys_block.mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    (sys_block / "nbd0").mkdir(parents=True)

    manager = _manager(tmp_path, FakeRunner())
    with pytest.raises(ValidationError, match="device nodes are missing"):
        manager._find_free_nbd()


def test_preflight_requires_sudo_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        if command == ("true",) and sudo:
            return RunResult(
                command=tuple(command),
                returncode=1,
                stdout="",
                stderr="sudo: a password is required",
            )
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vhdmaker.disk.assert_dependencies", lambda **_: None)
    manager = _manager(tmp_path, FakeRunner(on_run=on_run))
    with pytest.raises(ValidationError, match="sudo -v"):
        manager.preflight()


def test_partition_and_format_sets_partition_boot_flag(tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager._wait_for_partition = lambda nbd_device, timeout_seconds=15.0: "/dev/nbd0p1"  # type: ignore[assignment]

    manager._partition_and_format(nbd_device="/dev/nbd0", disk_format=DiskFormat.FAT16, label=None)

    assert any(
        command == ("parted", "--script", "/dev/nbd0", "set", "1", "boot", "on") and sudo
        for command, sudo in runner.calls
    )


def test_connect_nbd_uses_detected_image_format(tmp_path: Path) -> None:
    sys_block = tmp_path / "sys-class-block"
    dev_root = tmp_path / "dev"
    sys_block.mkdir(parents=True)
    dev_root.mkdir(parents=True)
    (sys_block / "nbd0").mkdir(parents=True)
    (dev_root / "nbd0").write_text("", encoding="utf-8")
    image_path = tmp_path / "sample.vhd"
    image_path.write_bytes(b"")

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        if command[:3] == ("qemu-img", "info", "--output=json"):
            return RunResult(
                command=tuple(command),
                returncode=0,
                stdout=json.dumps({"format": "raw"}),
                stderr="",
            )
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    runner = FakeRunner(on_run=on_run)
    manager = _manager(tmp_path, runner)
    selected = manager._connect_nbd(image_path)

    assert selected == str(dev_root / "nbd0")
    assert any(
        command[:4] == ("qemu-nbd", "--format", "raw", "--connect") and sudo
        for command, sudo in runner.calls
    )


def test_connect_nbd_prefers_explicit_image_format(tmp_path: Path) -> None:
    sys_block = tmp_path / "sys-class-block"
    dev_root = tmp_path / "dev"
    sys_block.mkdir(parents=True)
    dev_root.mkdir(parents=True)
    (sys_block / "nbd0").mkdir(parents=True)
    (dev_root / "nbd0").write_text("", encoding="utf-8")
    image_path = tmp_path / "sample.vhd"
    image_path.write_bytes(b"")

    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    selected = manager._connect_nbd(image_path, image_format="vpc")

    assert selected == str(dev_root / "nbd0")
    assert any(
        command[:4] == ("qemu-nbd", "--format", "vpc", "--connect") and sudo
        for command, sudo in runner.calls
    )


def test_detect_image_format_uses_vpc_footer_hint(tmp_path: Path) -> None:
    image_path = tmp_path / "disk.vhd"
    image_path.write_bytes(b"\0" * 1024)
    with image_path.open("r+b") as handle:
        handle.seek(-512, 2)
        footer = bytearray(512)
        footer[:8] = b"conectix"
        handle.write(footer)

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        del sudo
        if command[:3] == ("qemu-img", "info", "--output=json"):
            return RunResult(command=tuple(command), returncode=0, stdout=json.dumps({"format": "raw"}), stderr="")
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    manager = _manager(tmp_path, FakeRunner(on_run=on_run))
    assert manager._detect_image_format(image_path) == "vpc"


def test_privilege_diagnostics_fail_when_noninteractive_sudo_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)

    def on_run(command: Sequence[str], sudo: bool) -> RunResult:
        if command == ("true",) and sudo:
            return RunResult(
                command=tuple(command),
                returncode=1,
                stdout="",
                stderr="sudo: a password is required",
            )
        return RunResult(command=tuple(command), returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vhdmaker.disk.find_missing", lambda commands: [])
    manager = _manager(tmp_path, FakeRunner(on_run=on_run))

    ok, summary = manager.privilege_diagnostics_summary()
    assert ok is False
    assert "[FAIL] Non-interactive sudo readiness" in summary
    assert "sudo -v" in summary


def test_privilege_diagnostics_warn_when_nbd_not_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)

    monkeypatch.setattr("vhdmaker.disk.find_missing", lambda commands: [])
    manager = _manager(tmp_path, FakeRunner())

    ok, summary = manager.privilege_diagnostics_summary()
    assert ok is True
    assert "[WARN] NBD device availability" in summary


def test_read_vpc_bios_chs_geometry_from_footer(tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    image_path = tmp_path / "disk.vhd"
    image_path.write_bytes(b"\0" * 4096)
    with image_path.open("r+b") as handle:
        handle.seek(-512, 2)
        footer = bytearray(512)
        footer[:8] = b"conectix"
        footer[56:58] = struct.pack(">H", 1007)
        footer[58] = 12
        footer[59] = 17
        handle.write(footer)

    manager = _manager(tmp_path, FakeRunner())
    assert manager._read_vpc_bios_chs_geometry(image_path) == (17, 12)


def test_create_passes_vpc_footer_geometry_to_boot_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(system_files={}, boot_sector_template=self.template, fdos_payload_dir=None)

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_partition_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    installer = StubInstaller()
    manager = DiskManager(
        runner=FakeRunner(),
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=StubResolver(boot_template),
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )

    def fake_create(path: Path, size_bytes: int) -> None:
        del size_bytes
        path.write_bytes(b"\0" * 4096)
        with path.open("r+b") as handle:
            handle.seek(-512, 2)
            footer = bytearray(512)
            footer[:8] = b"conectix"
            footer[56:58] = struct.pack(">H", 1007)
            footer[58] = 12
            footer[59] = 17
            handle.write(footer)

    monkeypatch.setattr(manager, "preflight", lambda request=None: None)
    monkeypatch.setattr(manager, "_validate_create_request", lambda request: None)
    monkeypatch.setattr(manager, "_create_fixed_vhd", fake_create)
    monkeypatch.setattr(manager, "_partition_and_format", lambda **kwargs: "/dev/nbd0p1")
    monkeypatch.setattr(
        manager,
        "_with_connected_nbd",
        lambda vhd_path, callback, image_format=None: callback("/dev/nbd0"),
    )

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
    )
    manager.create_and_prepare(request)

    assert installer.calls
    assert installer.calls[0]["bios_chs"] == (17, 12)
