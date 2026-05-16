from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Callable, Sequence

import pytest

from dosforge.boot import BootAssetResolver, BootAssets, BootInstaller
from dosforge.commands import RunResult
from dosforge.disk import DiskManager
from dosforge.errors import ValidationError
from dosforge.models import BootMode, CreateRequest, DiskFormat, FloppyType, IBMDOSVersion, MediaType
from dosforge.state import StateStore


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

    monkeypatch.setattr("dosforge.disk.assert_dependencies", lambda **_: None)
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


def test_partition_and_format_uses_legacy_fat32_layout_for_boot_modes(tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager._wait_for_partition = lambda nbd_device, timeout_seconds=15.0: "/dev/nbd0p1"  # type: ignore[assignment]

    manager._partition_and_format(
        nbd_device="/dev/nbd0",
        disk_format=DiskFormat.FAT32,
        label=None,
        boot_mode=BootMode.MSDOS71,
    )

    assert any(
        command
        == (
            "parted",
            "--script",
            "/dev/nbd0",
            "mkpart",
            "primary",
            "fat32",
            "63s",
            "100%",
        )
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("parted", "--script", "/dev/nbd0", "set", "1", "lba", "off") and sudo
        for command, sudo in runner.calls
    )


def test_partition_and_format_uses_legacy_layout_for_bootable_fat16(tmp_path: Path) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    manager._wait_for_partition = lambda nbd_device, timeout_seconds=15.0: "/dev/nbd0p1"  # type: ignore[assignment]

    manager._partition_and_format(
        nbd_device="/dev/nbd0",
        disk_format=DiskFormat.FAT16,
        label=None,
        boot_mode=BootMode.MSDOS622,
    )

    assert any(
        command
        == (
            "parted",
            "--script",
            "/dev/nbd0",
            "mkpart",
            "primary",
            "fat16",
            "63s",
            "100%",
        )
        and sudo
        for command, sudo in runner.calls
    )
    assert any(
        command == ("parted", "--script", "/dev/nbd0", "set", "1", "lba", "off") and sudo
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

    monkeypatch.setattr("dosforge.disk.find_missing", lambda commands: [])
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

    monkeypatch.setattr("dosforge.disk.find_missing", lambda commands: [])
    manager = _manager(tmp_path, FakeRunner())

    ok, summary = manager.privilege_diagnostics_summary()
    assert ok is True
    assert "[WARN] NBD device availability" in summary


def test_read_vpc_bios_chs_geometry_reads_normalized_footer(tmp_path: Path) -> None:
    # _normalize_vhd_footer_geometry rewrites the VHD footer with standard ATA
    # geometry (16 heads x 63 spt). _read_vpc_bios_chs_geometry returns those
    # values so the BPB patcher writes a matching BIOS-canonical BPB.
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    image_path = tmp_path / "disk.vhd"
    image_path.write_bytes(b"\0" * 4096)
    with image_path.open("r+b") as handle:
        handle.seek(-512, 2)
        footer = bytearray(512)
        footer[:8] = b"conectix"
        # Simulate a freshly created VHD with qemu-img's legacy CHS, then
        # normalize it. The normalizer must rewrite to 16h/63spt.
        struct.pack_into(">Q", footer, 48, 100 * 1024 * 1024)  # current_size_bytes
        footer[56:58] = struct.pack(">H", 1007)
        footer[58] = 12
        footer[59] = 17
        # Checksum
        footer[64:68] = b"\x00\x00\x00\x00"
        cksum = (~sum(footer)) & 0xFFFFFFFF
        footer[64:68] = struct.pack(">I", cksum)
        handle.write(footer)

    manager = _manager(tmp_path, FakeRunner())
    manager._normalize_vhd_footer_geometry(image_path)
    assert manager._read_vpc_bios_chs_geometry(image_path) == (63, 16)

    # And the footer on disk must still be a valid VHD footer.
    with image_path.open("rb") as handle:
        handle.seek(-512, 2)
        footer_after = handle.read(512)
    assert footer_after[:8] == b"conectix"
    assert footer_after[58] == 16
    assert footer_after[59] == 63
    fb = bytearray(footer_after)
    stored_cksum = struct.unpack(">I", fb[64:68])[0]
    fb[64:68] = b"\x00\x00\x00\x00"
    assert stored_cksum == ((~sum(fb)) & 0xFFFFFFFF)


def test_create_passes_bios_canonical_geometry_to_boot_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def fake_create(path: Path, size_bytes: int, *, request=None) -> None:
        del size_bytes, request
        path.write_bytes(b"\0" * 4096)
        with path.open("r+b") as handle:
            handle.seek(-512, 2)
            footer = bytearray(512)
            footer[:8] = b"conectix"
            struct.pack_into(">Q", footer, 48, 100 * 1024 * 1024)
            footer[56:58] = struct.pack(">H", 1007)
            footer[58] = 12
            footer[59] = 17
            footer[64:68] = b"\x00\x00\x00\x00"
            cksum = (~sum(footer)) & 0xFFFFFFFF
            footer[64:68] = struct.pack(">I", cksum)
            handle.write(footer)
        # Mirror real _create_fixed_vhd's footer normalization so the BPB
        # patcher path receives the canonical 16h/63spt geometry.
        manager._normalize_vhd_footer_geometry(path)

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
    assert installer.calls[0]["bios_chs"] == (63, 16)


def test_create_img_system_format_invokes_floppy_boot_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template
            self.calls = 0

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            self.calls += 1
            return BootAssets(system_files={}, boot_sector_template=self.template, fdos_payload_dir=None)

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_floppy_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    resolver = StubResolver(boot_template)
    installer = StubInstaller()
    runner = FakeRunner()
    manager = DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=resolver,  # type: ignore[arg-type]
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "dos.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        img_system_format=True,
        boot_mode=BootMode.FREEDOS,
    )
    manager.create_and_prepare(request)

    assert request.path.exists()
    assert request.path.stat().st_size == FloppyType.F1440K.size_bytes
    assert any(command[:3] == ("mkfs.fat", "-F", "12") and sudo for command, sudo in runner.calls)
    assert resolver.calls == 1
    assert installer.calls
    assert installer.calls[0]["image_path"] == request.path


def test_create_img_custom_payload_copies_after_boot_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(system_files={}, boot_sector_template=self.template, fdos_payload_dir=None)

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_floppy_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir(parents=True)
    (payload_dir / "AUTOEXEC.BAT").write_bytes(b"echo hi\r\n")

    resolver = StubResolver(boot_template)
    installer = StubInstaller()
    runner = FakeRunner()
    manager = DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=resolver,  # type: ignore[arg-type]
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)
    call_order: list[str] = []

    def fake_make_floppy_bootable(**kwargs: object) -> None:
        del kwargs
        call_order.append("boot")

    def fake_copy_payload(*, partition_device: str, source_dir: Path, boot_mode: BootMode = BootMode.NONE) -> None:
        assert partition_device.endswith(".img")
        assert source_dir == payload_dir.resolve()
        assert boot_mode is BootMode.FREEDOS
        call_order.append("payload")

    installer.make_floppy_bootable = fake_make_floppy_bootable  # type: ignore[assignment]
    monkeypatch.setattr(manager, "_copy_custom_payload_to_filesystem", fake_copy_payload)

    request = CreateRequest(
        path=tmp_path / "dos.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        img_system_format=True,
        boot_mode=BootMode.FREEDOS,
        custom_payload_path=payload_dir,
    )
    manager.create_and_prepare(request)

    assert call_order == ["boot", "payload"]


def test_create_vhd_custom_payload_copies_to_partition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(system_files={}, boot_sector_template=self.template, fdos_payload_dir=None)

    class StubInstaller:
        def make_partition_bootable(self, **kwargs: object) -> None:
            del kwargs

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir(parents=True)
    (payload_dir / "FILE.TXT").write_text("payload", encoding="utf-8")

    manager = DiskManager(
        runner=FakeRunner(),
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=StubResolver(boot_template),  # type: ignore[arg-type]
        boot_installer=StubInstaller(),  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None: None)
    monkeypatch.setattr(manager, "_create_fixed_vhd", lambda path, size_bytes, *, request=None: path.write_bytes(b"\0" * 4096))
    monkeypatch.setattr(manager, "_partition_and_format", lambda **kwargs: "/dev/nbd0p1")
    monkeypatch.setattr(manager, "_with_connected_nbd", lambda vhd_path, callback, image_format=None: callback("/dev/nbd0"))
    monkeypatch.setattr(manager, "_validate_create_request", lambda request: None)
    copied: dict[str, object] = {}

    def fake_copy_payload(*, partition_device: str, source_dir: Path, boot_mode: BootMode = BootMode.NONE) -> None:
        copied["partition_device"] = partition_device
        copied["source_dir"] = source_dir
        copied["boot_mode"] = boot_mode

    monkeypatch.setattr(manager, "_copy_custom_payload_to_filesystem", fake_copy_payload)

    request = CreateRequest(
        path=tmp_path / "disk.vhd",
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        boot_mode=BootMode.FREEDOS,
        custom_payload_path=payload_dir,
    )
    manager.create_and_prepare(request)

    assert copied["partition_device"] == "/dev/nbd0p1"
    assert copied["source_dir"] == payload_dir.resolve()
    assert copied["boot_mode"] is BootMode.FREEDOS


def test_copy_entry_does_not_overwrite_root_boot_files(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeRunner())
    source = tmp_path / "source-command.com"
    source.write_text("payload", encoding="utf-8")
    destination = tmp_path / "COMMAND.COM"
    destination.write_text("boot", encoding="utf-8")

    manager._copy_entry(
        source=source,
        destination=destination,
        protected_root_files={"COMMAND.COM"},
        is_root=True,
    )

    assert destination.read_text(encoding="utf-8") == "boot"


def test_copy_entry_allows_nested_boot_named_files(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeRunner())
    source_root = tmp_path / "payload"
    source_root.mkdir(parents=True)
    source_nested = source_root / "DOS" / "COMMAND.COM"
    source_nested.parent.mkdir(parents=True)
    source_nested.write_text("nested", encoding="utf-8")
    destination_root = tmp_path / "target"
    destination_root.mkdir(parents=True)

    manager._copy_directory_contents_to_root(
        source_dir=source_root,
        destination_root=destination_root,
        protected_root_files={"COMMAND.COM"},
    )

    assert (destination_root / "DOS" / "COMMAND.COM").read_text(encoding="utf-8") == "nested"


def test_create_img_system_format_aligns_ibm_dos33_with_install_image_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(
                system_files={},
                boot_sector_template=self.template,
                fdos_payload_dir=None,
                source_image_size_bytes=FloppyType.F360K.size_bytes,
            )

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_floppy_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    resolver = StubResolver(boot_template)
    installer = StubInstaller()
    runner = FakeRunner()
    manager = DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=resolver,  # type: ignore[arg-type]
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "dos33.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        img_system_format=True,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.DOS33,
    )
    manager.create_and_prepare(request)

    assert request.path.exists()
    assert request.path.stat().st_size == FloppyType.F360K.size_bytes
    assert request.floppy_type is FloppyType.F360K
    assert request.size_bytes == FloppyType.F360K.size_bytes
    assert any(command[:3] == ("mkfs.fat", "-F", "12") and sudo for command, sudo in runner.calls)
    assert installer.calls
    assert installer.calls[0]["image_path"] == request.path


def test_create_img_formats_with_explicit_floppy_geometry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "geo720.img",
        size_bytes=FloppyType.F720K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F720K,
        img_system_format=False,
        boot_mode=BootMode.NONE,
    )
    manager.create_and_prepare(request)

    mkfs_command = next(command for command, _ in runner.calls if command[:3] == ("mkfs.fat", "-F", "12"))
    assert "-S" in mkfs_command and "512" in mkfs_command
    assert "-g" in mkfs_command and "2/9" in mkfs_command
    assert "-M" in mkfs_command and "0xf9" in mkfs_command
    assert "-r" in mkfs_command and "112" in mkfs_command
    assert "-s" in mkfs_command and "2" in mkfs_command
    assert request.path.stat().st_size == FloppyType.F720K.size_bytes


def test_create_img_system_format_aligns_msdos71_with_install_image_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(
                system_files={},
                boot_sector_template=self.template,
                fdos_payload_dir=None,
                source_image_size_bytes=FloppyType.F1200K.size_bytes,
            )

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_floppy_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    resolver = StubResolver(boot_template)
    installer = StubInstaller()
    runner = FakeRunner()
    manager = DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=resolver,  # type: ignore[arg-type]
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "dos71.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        img_system_format=True,
        boot_mode=BootMode.MSDOS71,
    )
    manager.create_and_prepare(request)

    assert request.path.stat().st_size == FloppyType.F1200K.size_bytes
    assert request.floppy_type is FloppyType.F1200K
    assert request.size_bytes == FloppyType.F1200K.size_bytes
    mkfs_command = next(command for command, _ in runner.calls if command[:3] == ("mkfs.fat", "-F", "12"))
    assert "-g" in mkfs_command and "2/15" in mkfs_command
    assert installer.calls
    assert installer.calls[0]["floppy_type"] is FloppyType.F1200K
    assert installer.calls[0]["verify_legacy_layout"] is True


def test_create_img_system_format_preserves_selected_floppy_for_pcdos7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubResolver:
        def __init__(self, template: Path) -> None:
            self.template = template

        def resolve(self, request: CreateRequest) -> BootAssets:
            del request
            return BootAssets(
                system_files={},
                boot_sector_template=self.template,
                fdos_payload_dir=None,
                source_image_size_bytes=FloppyType.F1840K.size_bytes,
            )

    class StubInstaller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def make_floppy_bootable(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    boot_template = tmp_path / "BOOTSECT_FAT16.BIN"
    boot_template.write_bytes(b"\0" * 512)
    resolver = StubResolver(boot_template)
    installer = StubInstaller()
    runner = FakeRunner()
    manager = DiskManager(
        runner=runner,
        state_store=StateStore(tmp_path / "state.json"),
        boot_resolver=resolver,  # type: ignore[arg-type]
        boot_installer=installer,  # type: ignore[arg-type]
        mount_root=tmp_path / "mounts",
        nbd_sys_block_root=tmp_path / "sys-class-block",
        nbd_dev_root=tmp_path / "dev",
        nbd_discovery_timeout=0.2,
    )
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "pcdos7.img",
        size_bytes=FloppyType.F1440K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F1440K,
        img_system_format=True,
        boot_mode=BootMode.PCDOS7,
    )
    manager.create_and_prepare(request)

    assert request.path.stat().st_size == FloppyType.F1440K.size_bytes
    assert request.floppy_type is FloppyType.F1440K
    assert request.size_bytes == FloppyType.F1440K.size_bytes
    mkfs_command = next(command for command, _ in runner.calls if command[:3] == ("mkfs.fat", "-F", "12"))
    assert "-g" in mkfs_command and "2/18" in mkfs_command
    assert installer.calls
    assert installer.calls[0]["floppy_type"] is FloppyType.F1440K
    assert installer.calls[0]["verify_legacy_layout"] is True


def test_create_img_supports_2880k_geometry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    request = CreateRequest(
        path=tmp_path / "ed2880.img",
        size_bytes=FloppyType.F2880K.size_bytes,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.IMG,
        floppy_type=FloppyType.F2880K,
    )
    manager.create_and_prepare(request)

    assert request.path.stat().st_size == FloppyType.F2880K.size_bytes
    mkfs_command = next(command for command, _ in runner.calls if command[:3] == ("mkfs.fat", "-F", "12"))
    assert "-g" in mkfs_command and "2/36" in mkfs_command
    assert "-M" in mkfs_command and "0xf0" in mkfs_command
    assert "-r" in mkfs_command and "240" in mkfs_command


def test_mount_img_uses_loop_mount_and_skips_nbd_disconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "sys-class-block").mkdir(parents=True)
    (tmp_path / "dev").mkdir(parents=True)
    runner = FakeRunner()
    manager = _manager(tmp_path, runner)
    monkeypatch.setattr(manager, "preflight", lambda request=None, media_type=None: None)

    image = tmp_path / "disk.img"
    image.write_bytes(b"\0" * FloppyType.F1440K.size_bytes)

    record = manager.mount_vhd(image)
    assert record.nbd_device == "img-loop"
    assert record.partition_device == str(image.resolve())
    assert any(
        command[:4] == ("mount", "-t", "vfat", "-o") and "loop," in command[4] and sudo
        for command, sudo in runner.calls
    )

    manager.unmount(record.mount_point)
    assert not any(command[:2] == ("qemu-nbd", "--disconnect") for command, _ in runner.calls)
