from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from dosforge.e2e_emulator import qemu_boot_probe


def test_qemu_boot_probe_reports_boot_failure_marker(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(
            args=[],
            returncode=124,
            stdout="Booting from Hard Disk...\nThis is not a bootable disk.\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = qemu_boot_probe(image_path=tmp_path / "disk.vhd")
    assert ok is False
    assert "boot failure marker" in detail


def test_qemu_boot_probe_reports_error_loading_operating_system(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(
            args=[],
            returncode=124,
            stdout="Booting from Hard Disk...\nError loading operating system\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = qemu_boot_probe(image_path=tmp_path / "disk.vhd")
    assert ok is False
    assert "boot failure marker" in detail


def test_qemu_boot_probe_requires_shell_marker_when_requested(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(args=[], returncode=124, stdout="Booting from Hard Disk...\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = qemu_boot_probe(image_path=tmp_path / "disk.vhd", expect_shell_prompt=True)
    assert ok is False
    assert "no DOS shell prompt signature" in detail


def test_qemu_boot_probe_accepts_shell_marker(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(args=[], returncode=124, stdout="Booting from Hard Disk...\nC:\\>\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = qemu_boot_probe(image_path=tmp_path / "disk.vhd", expect_shell_prompt=True)
    assert ok is True
    assert detail == ""


def test_qemu_boot_probe_requires_floppy_boot_stage(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(args=[], returncode=124, stdout="Booting from Hard Disk...\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = qemu_boot_probe(image_path=tmp_path / "disk.img", image_format="raw", boot_media="floppy")
    assert ok is False
    assert "did not reach floppy boot stage" in detail


def test_qemu_boot_probe_writes_diagnostics(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        del command, check, capture_output, text
        return subprocess.CompletedProcess(args=[], returncode=124, stdout="Booting from Hard Disk...\nC:\\>\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    diagnostics_dir = tmp_path / "diag"
    ok, detail = qemu_boot_probe(
        image_path=tmp_path / "disk.vhd",
        expect_shell_prompt=True,
        diagnostics_dir=diagnostics_dir,
        case_id="demo-case",
    )
    assert ok is True
    assert detail == ""
    assert (diagnostics_dir / "demo-case.command.txt").is_file()
    assert (diagnostics_dir / "demo-case.returncode.txt").read_text(encoding="ascii").strip() == "124"
    assert "Booting from Hard Disk" in (diagnostics_dir / "demo-case.output.log").read_text(encoding="utf-8")
