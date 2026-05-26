"""Tests for the 4DOS shell overlay installer (Phase 14F-full)."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import pytest

from dosforge.errors import ValidationError
from dosforge.fourdos_overlay import (
    FourDosOverlayContext,
    install_fourdos_overlay,
    list_fourdos_files,
    resolve_fourdos_assets_dir,
)
from dosforge.models import BootMode


class _CaptureRunner:
    """Stand-in for CommandRunner that records every ``run`` invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def run(self, cmd: list[str], **kwargs: Any) -> Any:
        self.calls.append((tuple(cmd), kwargs))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()


def _make_assets(tmp_path: Path, files: dict[str, bytes]) -> Path:
    target = tmp_path / "4dos"
    target.mkdir()
    for name, payload in files.items():
        (target / name).write_bytes(payload)
    return target


def test_list_fourdos_files_includes_4dos_com() -> None:
    names = [src for src, _, _ in list_fourdos_files()]
    assert "4DOS.COM" in names


def test_list_fourdos_files_marks_4dos_com_required() -> None:
    for src, _, required in list_fourdos_files():
        if src == "4DOS.COM":
            assert required is True
            return
    pytest.fail("4DOS.COM missing from curated file list")


def test_list_fourdos_files_excludes_windows_installer_payload() -> None:
    """The Wise-installer scaffolding (UNWISE32.EXE, FILE####.DAT) must
    not appear in the overlay -- it's Windows-only and irrelevant to
    DOS-native boot."""
    names = {src.upper() for src, _, _ in list_fourdos_files()}
    forbidden = {"UNWISE32.EXE", "FILE0001.DAT", "WISE0001.DLL", "PROGRESS.DLL"}
    assert forbidden.isdisjoint(names)


def test_resolve_fourdos_assets_dir_explicit_path(tmp_path: Path) -> None:
    assets = _make_assets(tmp_path, {"4DOS.COM": b"\xcd\x20" * 100})
    resolved = resolve_fourdos_assets_dir(assets)
    assert resolved == assets.resolve()


def test_resolve_fourdos_assets_dir_explicit_parent_with_subdir(tmp_path: Path) -> None:
    """If the user points at a parent containing /4dos/, find it."""
    parent = tmp_path / "all-dos-stuff"
    parent.mkdir()
    fourdos = parent / "4dos"
    fourdos.mkdir()
    (fourdos / "4DOS.COM").write_bytes(b"x" * 100)
    resolved = resolve_fourdos_assets_dir(parent)
    assert resolved == fourdos.resolve()


def test_resolve_fourdos_assets_dir_missing_required_file(tmp_path: Path, monkeypatch) -> None:
    """A directory without 4DOS.COM is not a valid 4DOS install dir.

    Run from an isolated cwd so the repo's real dosassets/4dos/ doesn't
    get picked up by the bare-name fallback resolution."""
    monkeypatch.chdir(tmp_path)
    assets = tmp_path / "fake-4dos"
    assets.mkdir()
    (assets / "README.TXT").write_bytes(b"this is not 4dos.com")
    with pytest.raises(ValidationError, match="4DOS install media not found"):
        resolve_fourdos_assets_dir(assets)


def test_resolve_fourdos_assets_dir_no_path_errors_clearly(tmp_path: Path, monkeypatch) -> None:
    """No boot_assets_path AND no dosassets/4dos/ -> clear error."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError, match="4DOS install media not found"):
        resolve_fourdos_assets_dir(None)


def test_install_overlay_writes_4dos_dir_and_config_files(tmp_path: Path) -> None:
    assets = _make_assets(
        tmp_path,
        {
            "4DOS.COM": b"a" * 1000,
            "4DOS.HLP": b"b" * 1000,
            "OPTION.EXE": b"c" * 1000,
            "BATCOMP.EXE": b"d" * 1000,
        },
    )
    runner = _CaptureRunner()
    context = FourDosOverlayContext(
        assets_dir=assets,
        partition_target="DUMMY@@0",
    )
    install_fourdos_overlay(runner=runner, context=context)

    # mmd 4DOS
    mmd_calls = [c for c in runner.calls if c[0][0] == "mmd"]
    assert any("::4DOS" in cmd for cmd, _ in mmd_calls)

    # mcopy each present 4DOS file
    mcopy_calls = [c for c in runner.calls if c[0][0] == "mcopy"]
    copied_dests = [cmd[-1] for cmd, _ in mcopy_calls]
    assert "::4DOS/4DOS.COM" in copied_dests
    assert "::4DOS/4DOS.HLP" in copied_dests
    assert "::4DOS/OPTION.EXE" in copied_dests
    assert "::4DOS/BATCOMP.EXE" in copied_dests
    # 4HELP.EXE wasn't supplied -- must NOT appear
    assert "::4DOS/4HELP.EXE" not in copied_dests

    # mcopy CONFIG.SYS + AUTOEXEC.BAT to root
    root_dests = [cmd[-1] for cmd, _ in mcopy_calls]
    assert "::CONFIG.SYS" in root_dests
    assert "::AUTOEXEC.BAT" in root_dests


def test_install_overlay_default_config_sys_has_4dos_shell_line(tmp_path: Path) -> None:
    """The default CONFIG.SYS must point SHELL= at C:\\4DOS\\4DOS.COM --
    otherwise the host DOS still uses COMMAND.COM and 4DOS never loads."""
    assets = _make_assets(tmp_path, {"4DOS.COM": b"x" * 100})
    captured_payloads: list[bytes] = []
    parent_run = _CaptureRunner().run

    class _ScratchSniffingRunner:
        calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

        def run(self, cmd: list[str], **kwargs: Any) -> Any:
            self.calls.append((tuple(cmd), kwargs))
            if cmd[0] == "mcopy" and cmd[-1] == "::CONFIG.SYS":
                # The scratch path is in args[-2]
                scratch_path = Path(cmd[-2])
                captured_payloads.append(scratch_path.read_bytes())

            class _R:
                returncode = 0
                stdout = ""
                stderr = ""

            return _R()

    runner = _ScratchSniffingRunner()
    context = FourDosOverlayContext(assets_dir=assets, partition_target="DUMMY")
    install_fourdos_overlay(runner=runner, context=context)
    assert captured_payloads, "CONFIG.SYS was never written"
    config_text = captured_payloads[0].decode("ascii")
    assert "SHELL=C:\\4DOS\\4DOS.COM" in config_text
    assert "C:\\4DOS" in config_text
    assert config_text.endswith("\n") or config_text.endswith("\r\n")


def test_install_overlay_missing_required_file_raises(tmp_path: Path) -> None:
    """If 4DOS.COM mysteriously disappears between resolve and install,
    raise loudly rather than write a broken overlay."""
    assets = tmp_path / "4dos"
    assets.mkdir()
    # Don't write 4DOS.COM
    (assets / "OPTION.EXE").write_bytes(b"x" * 100)
    runner = _CaptureRunner()
    context = FourDosOverlayContext(assets_dir=assets, partition_target="DUMMY")
    with pytest.raises(ValidationError, match="4DOS required file 4DOS.COM"):
        install_fourdos_overlay(runner=runner, context=context)


def test_install_overlay_rejects_install_dir_with_separators(tmp_path: Path) -> None:
    assets = _make_assets(tmp_path, {"4DOS.COM": b"x" * 100})
    runner = _CaptureRunner()
    for bad_dir in ("SUB\\4DOS", "SUB/4DOS", "", "   "):
        context = FourDosOverlayContext(
            assets_dir=assets, partition_target="DUMMY", install_dir=bad_dir
        )
        with pytest.raises(ValidationError, match="install_dir"):
            install_fourdos_overlay(runner=runner, context=context)


def test_install_overlay_case_insensitive_source_filenames(tmp_path: Path) -> None:
    """4DOS distributions sometimes ship lowercase ``4dos.com``."""
    assets = tmp_path / "4dos"
    assets.mkdir()
    (assets / "4dos.com").write_bytes(b"x" * 100)  # lowercase
    (assets / "option.exe").write_bytes(b"y" * 100)  # lowercase
    runner = _CaptureRunner()
    context = FourDosOverlayContext(assets_dir=assets, partition_target="DUMMY")
    install_fourdos_overlay(runner=runner, context=context)
    mcopy_dests = [
        c[0][-1] for c in runner.calls if c[0][0] == "mcopy" and c[0][-1].startswith("::4DOS/")
    ]
    assert "::4DOS/4DOS.COM" in mcopy_dests
    assert "::4DOS/OPTION.EXE" in mcopy_dests


# --- DiskManager validation -------------------------------------------------


def test_disk_manager_rejects_4dos_without_host(tmp_path: Path) -> None:
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.FOURDOS,
    )
    with pytest.raises(ValidationError, match="--host-boot-mode"):
        mgr._validate_create_request(req)


def test_disk_manager_rejects_4dos_with_none_host(tmp_path: Path) -> None:
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.FOURDOS,
        host_boot_mode=BootMode.NONE,
    )
    with pytest.raises(ValidationError, match="not.*valid"):
        mgr._validate_create_request(req)


def test_disk_manager_rejects_4dos_nested_in_host(tmp_path: Path) -> None:
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.FOURDOS,
        host_boot_mode=BootMode.FOURDOS,
    )
    with pytest.raises(ValidationError, match="not.*valid"):
        mgr._validate_create_request(req)


def test_disk_manager_rejects_unsupported_host_for_now(tmp_path: Path) -> None:
    """Phase 14F-full only supports msdos71 as a host -- other modes
    error with a clear 'not supported yet' message."""
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.FOURDOS,
        host_boot_mode=BootMode.MSDOS622,
    )
    with pytest.raises(ValidationError, match="isn't supported yet"):
        mgr._validate_create_request(req)


def test_disk_manager_accepts_4dos_with_msdos71_host(tmp_path: Path) -> None:
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.FOURDOS,
        host_boot_mode=BootMode.MSDOS71,
    )
    # Should not raise
    mgr._validate_create_request(req)


def test_disk_manager_rejects_host_boot_mode_without_4dos(tmp_path: Path) -> None:
    """--host-boot-mode is only meaningful with --boot-mode=4dos."""
    from dosforge.disk import DiskManager
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    mgr = DiskManager()
    req = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        path=tmp_path / "x.vhd",
        boot_mode=BootMode.MSDOS71,
        host_boot_mode=BootMode.MSDOS622,
    )
    with pytest.raises(ValidationError, match="only.*valid.*4dos"):
        mgr._validate_create_request(req)
