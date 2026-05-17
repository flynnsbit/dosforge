"""Tests for the platform abstraction layer + Windows backend stub.

These tests can be run on Linux — they exercise the
:class:`WindowsBackend` purely via its methods and capability flags,
without ever spawning a Windows process or expecting Windows-only
binaries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge._core import fat12_floppy
from dosforge._platform import (
    LinuxBackend,
    PlatformBackend,
    WindowsBackend,
    get_backend,
)
from dosforge._platform.windows import _KNOWN_BUNDLED_TOOLS
from dosforge.commands import CommandRunner, runner_for_backend
from dosforge.models import BootMode, FreeDOSSource, MediaType


# -- WindowsBackend basics ------------------------------------------------


def test_windows_backend_reports_no_kernel_mount_no_nbd_no_sudo():
    backend = WindowsBackend()
    assert backend.supports_kernel_mount is False
    assert backend.supports_nbd is False
    assert backend.requires_sudo_for_disk_ops is False
    assert backend.supports_external_file_manager is False


def test_windows_backend_state_dir_uses_localappdata(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/Test/AppData/Local")
    backend = WindowsBackend()
    state = backend.state_dir()
    assert "dosforge" in state.parts[-1]
    assert "Local" in str(state)


def test_windows_backend_state_dir_falls_back_to_userprofile(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", "C:/Users/Test")
    backend = WindowsBackend()
    state = backend.state_dir()
    assert state.parts[-1] == "dosforge"


def test_known_bundled_tools_includes_expected_set():
    expected = {"qemu-img", "qemu-system-i386", "mformat", "mcopy", "mattrib", "mdir"}
    assert expected.issubset(_KNOWN_BUNDLED_TOOLS)


def test_tool_path_returns_bare_name_for_unknown_tools():
    backend = WindowsBackend()
    assert backend.tool_path("hypothetical-tool") == "hypothetical-tool"


def test_tool_path_falls_back_to_bare_name_when_bundle_missing():
    """When ``vendor/windows/bin/`` doesn't have the tool, return its
    bare name so the OS can search ``PATH`` (or fail with a clear
    ``Missing external command`` error)."""

    backend = WindowsBackend()
    resolved = backend.tool_path("qemu-img")
    # Either an absolute path (vendor populated) OR the bare name.
    assert resolved == "qemu-img" or resolved.endswith("qemu-img.exe")


def test_tool_path_uses_env_override(monkeypatch, tmp_path):
    bundle = tmp_path / "bin"
    bundle.mkdir()
    fake_qemu = bundle / "qemu-img.exe"
    fake_qemu.write_bytes(b"#!stub\n")
    monkeypatch.setenv("DOSFORGE_VENDOR_DIR", str(bundle))
    backend = WindowsBackend()
    assert backend.tool_path("qemu-img") == str(fake_qemu)


def test_windows_required_commands_excludes_sudo_mount():
    backend = WindowsBackend()
    cmds = backend.required_commands(
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS5,
        freedos_source=FreeDOSSource.LOCAL,
    )
    assert "sudo" not in cmds
    assert "mount" not in cmds
    assert "umount" not in cmds
    assert "parted" not in cmds
    assert "qemu-nbd" not in cmds
    # qemu-img + mformat + mcopy + mattrib should be required
    assert "qemu-img" in cmds
    assert "mformat" in cmds


def test_linux_required_commands_includes_sudo_mount():
    backend = LinuxBackend()
    cmds = backend.required_commands(
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS5,
        freedos_source=FreeDOSSource.LOCAL,
    )
    assert "sudo" in cmds
    assert "mount" in cmds
    assert "parted" in cmds


# -- Tool resolver wiring -------------------------------------------------


def test_runner_resolves_first_argument_via_resolver(monkeypatch, tmp_path):
    """A ``tool_resolver`` should rewrite ``argv[0]`` before execution."""

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("dosforge.commands.subprocess.run", fake_run)
    runner = CommandRunner(
        tool_resolver=lambda name: f"/opt/bundle/{name}.exe",
        sudo_required=False,
    )
    runner.run(["qemu-img", "create", "-f", "vpc", "x.vhd", "10M"])
    assert calls == [["/opt/bundle/qemu-img.exe", "create", "-f", "vpc", "x.vhd", "10M"]]


def test_runner_for_backend_is_sudo_aware():
    linux_runner = runner_for_backend(LinuxBackend())
    win_runner = runner_for_backend(WindowsBackend())
    # Internal state — verified via behavior in subsequent tests.
    assert linux_runner._sudo_required is True
    assert win_runner._sudo_required is False


def test_windows_runner_makes_sudo_true_a_noop(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(argv, **kwargs):
        captured.append(list(argv))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("dosforge.commands.subprocess.run", fake_run)
    runner = runner_for_backend(WindowsBackend())
    runner.run(["mformat", "-i", "x.vhd@@32256", "::"], sudo=True)
    # On Windows the ``sudo=True`` flag should NOT prepend a sudo call.
    assert captured[0][0] != "sudo"
    assert captured[0][0].endswith("mformat") or captured[0][0].endswith("mformat.exe")


# -- Pure-Python in-place floppy formatter --------------------------------


def test_format_existing_writes_bpb_in_place(tmp_path):
    """Used by the Windows IMG path: format an already-allocated file."""

    from dosforge.models import FloppyType

    path = tmp_path / "1.44m.img"
    # Allocate an empty file of the right size, mimicking what
    # ``_create_fixed_img`` does on Windows.
    with path.open("wb") as h:
        h.truncate(FloppyType.F1440K.size_bytes)
    fat12_floppy.format_existing(path, floppy_type=FloppyType.F1440K, volume_label="DOSWIN")
    issues = fat12_floppy.validate_floppy_bpb(path, FloppyType.F1440K)
    assert issues == []


def test_format_existing_rejects_undersized_file(tmp_path):
    from dosforge.models import FloppyType

    path = tmp_path / "tiny.img"
    path.write_bytes(b"\x00" * 1024)
    with pytest.raises(ValueError, match="smaller than expected"):
        fat12_floppy.format_existing(path, floppy_type=FloppyType.F1440K)


def test_format_existing_rejects_missing_file(tmp_path):
    from dosforge.models import FloppyType

    with pytest.raises(FileNotFoundError):
        fat12_floppy.format_existing(tmp_path / "nope.img", floppy_type=FloppyType.F1440K)


# -- Backend factory ------------------------------------------------------


def test_get_backend_returns_singleton_per_process():
    a = get_backend()
    b = get_backend()
    assert a is b
    assert isinstance(a, PlatformBackend)
