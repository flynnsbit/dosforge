"""Unit tests for the DOSBox-X SYS install driver."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dosforge.legacy_dos_dosboxx_install import LegacyDosDosBoxXInstaller


@pytest.fixture
def installer(tmp_path: Path) -> LegacyDosDosBoxXInstaller:
    return LegacyDosDosBoxXInstaller(cache_root=tmp_path)


def test_build_conf_has_imgmount_for_floppy_and_vhd(installer):
    conf = installer._build_conf(
        floppy_path="C:/tmp/install.img",
        vhd_path="C:/tmp/target.vhd",
        log_path="C:/tmp/dosbox.log",
    )
    assert "IMGMOUNT 0 C:/tmp/install.img -t floppy" in conf
    assert "IMGMOUNT C C:/tmp/target.vhd -t hdd -fs none" in conf
    assert "BOOT A:" in conf


def test_build_conf_uses_pc_compatible_machine(installer):
    conf = installer._build_conf(
        floppy_path="X.img", vhd_path="X.vhd", log_path="X.log"
    )
    # 16 MB / 486 / svga_s3 matches the QEMU profile (pc + 486 + 16 MB).
    assert "memsize=16" in conf
    assert "cputype=486" in conf
    assert "machine=svga_s3" in conf


def test_build_conf_disables_sound_and_serial(installer):
    """Headless install: no audio / mpu401 / serial ports needed."""
    conf = installer._build_conf(
        floppy_path="X.img", vhd_path="X.vhd", log_path="X.log"
    )
    assert "nosound=true" in conf
    assert "mpu401=none" in conf
    assert "sbtype=none" in conf
    assert "serial1=disabled" in conf


def test_build_conf_routes_log_to_provided_path(installer):
    conf = installer._build_conf(
        floppy_path="X.img",
        vhd_path="X.vhd",
        log_path="C:/scratch/dosbox-run.log",
    )
    assert "logfile=C:/scratch/dosbox-run.log" in conf


def test_legacy_dos_emulator_default_is_qemu():
    """Linux backend keeps QEMU (no DOSBox-X in its vendor path)."""

    if sys.platform == "win32":
        pytest.skip("Linux backend tested only on non-win32")
    from dosforge._platform.linux import LinuxBackend

    assert LinuxBackend().legacy_dos_emulator() == "qemu"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows backend only")
def test_windows_backend_picks_dosbox_x_when_bundled(monkeypatch, tmp_path):
    """Windows backend selects dosbox-x when its EXE is bundled."""

    from dosforge._platform import windows as winmod

    # Point the search path at a tmp dir with a fake dosbox-x.exe
    fake_dir = tmp_path / "vendor"
    fake_dir.mkdir()
    (fake_dir / "dosbox-x.exe").write_bytes(b"MZ")
    monkeypatch.setattr(winmod, "_vendor_search_paths", lambda: [fake_dir])

    backend = winmod.WindowsBackend()
    assert backend.legacy_dos_emulator() == "dosbox-x"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows backend only")
def test_windows_backend_falls_back_to_qemu_when_no_dosbox_x(monkeypatch, tmp_path):
    """Without DOSBox-X in vendor, the Windows backend keeps QEMU."""

    from dosforge._platform import windows as winmod

    fake_dir = tmp_path / "vendor"
    fake_dir.mkdir()
    # Note: no dosbox-x.exe in this dir
    monkeypatch.setattr(winmod, "_vendor_search_paths", lambda: [fake_dir])

    backend = winmod.WindowsBackend()
    assert backend.legacy_dos_emulator() == "qemu"
