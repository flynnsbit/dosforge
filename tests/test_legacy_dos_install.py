"""Tests for legacy_dos_install profile flags + AUTOEXEC generation.

Focused on the DR-DOS 6/7 install-pipeline fix landed in v0.9.10:

* ``use_sys_after_format`` emits a two-step ``FORMAT C:`` +
  ``SYS C:`` AUTOEXEC instead of ``FORMAT C: /S``.
* ``supplementary_disk_images`` + ``supplementary_disk_extract_globs``
  pull FORMAT / SYS / FDISK from extra install diskettes.
* DR-DOS 6 profile auto-detects the 5.25" 6-disk archive layout
  (Disk02..Disk06 siblings of Disk01.img) and pre-fills the
  supplementary fields + pre-install scrubbing list.
* The install orchestration preserves the work floppy as
  ``FAILED-VERIFY-*`` when ``_verify_install`` raises, not just on
  QEMU failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import pytest

from dosforge.commands import RunResult
from dosforge.errors import ValidationError
from dosforge.legacy_dos_install import (
    LegacyDosInstallProfile,
    LegacyDosQemuInstaller,
    drdos6_profile,
    drdos7_profile,
)


class FakeRunner:
    """Captures every command tuple; defers behavior to ``on_run``."""

    def __init__(
        self,
        on_run: Callable[[tuple[str, ...]], RunResult] | None = None,
    ) -> None:
        self.on_run = on_run
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        sudo: bool = False,
        check: bool = True,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        del sudo, check, cwd, env
        cmd = tuple(command)
        self.calls.append(cmd)
        if self.on_run is not None:
            return self.on_run(cmd)
        return RunResult(command=cmd, returncode=0, stdout="", stderr="")

    def run_detached(self, command: Sequence[str]) -> None:
        del command


def _make_installer(tmp_path: Path, runner: FakeRunner) -> LegacyDosQemuInstaller:
    cache = tmp_path / "cache"
    cache.mkdir()
    return LegacyDosQemuInstaller(runner=runner, cache_root=cache)


def _empty_floppy(tmp_path: Path, name: str = "install.img", size: int = 1_474_560) -> Path:
    img = tmp_path / name
    img.write_bytes(b"\x00" * size)
    return img


def _autoexec_bytes(runner: FakeRunner, tmp_path: Path) -> bytes:
    """Recover the AUTOEXEC.BAT bytes from the FakeRunner mcopy calls.

    The installer mcopies a scratch file containing the AUTOEXEC.BAT
    bytes; the scratch file is unlinked on success, so we have to
    re-read the bytes the runner saw.
    """
    for cmd in runner.calls:
        if cmd[0] != "mcopy":
            continue
        # mcopy [-o] -i <image> <src> ::DEST  -- find AUTOEXEC entries
        if not any(c.endswith("::AUTOEXEC.BAT") for c in cmd):
            continue
        # Find the source file path (penultimate arg before the ::DEST).
        try:
            dest_idx = next(i for i, c in enumerate(cmd) if c.endswith("::AUTOEXEC.BAT"))
        except StopIteration:
            continue
        src = Path(cmd[dest_idx - 1])
        if src.exists():
            return src.read_bytes()
    pytest.fail("AUTOEXEC.BAT mcopy call not found in runner.calls")
    return b""


# ---------------------------------------------------------------------------
# use_sys_after_format
# ---------------------------------------------------------------------------


def test_format_only_emits_legacy_format_slash_s(tmp_path: Path) -> None:
    """Default ``use_sys_after_format=False`` keeps the legacy AUTOEXEC."""
    runner = FakeRunner()
    installer = _make_installer(tmp_path, runner)
    profile = LegacyDosInstallProfile(
        label="MS-DOS 5.0",
        install_image=_empty_floppy(tmp_path),
        required_system_files=("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
        install_method="format",
        format_yes_input=b"Y\r\nY\r\n\r\n",
    )

    captured: dict[str, bytes] = {}
    real_mcopy_text = installer._mcopy_text

    def capture_mcopy_text(image: Path, name: str, payload: bytes) -> None:
        captured[name] = payload
        real_mcopy_text(image, name, payload)

    installer._mcopy_text = capture_mcopy_text  # type: ignore[assignment]
    installer._prepare_install_floppy(profile)

    autoexec = captured["AUTOEXEC.BAT"]
    assert b"FORMAT C: /S < A:\\YES.TXT > A:\\FMT_OUT.TXT" in autoexec
    assert b"SYS C:" not in autoexec
    assert b"SYSIN.TXT" not in autoexec
    # Marker still emitted right after FORMAT.
    assert b"ECHO OK> C:\\VHDMK.OK" in autoexec


def test_use_sys_after_format_emits_two_step_autoexec(tmp_path: Path) -> None:
    """DR-DOS-style profiles emit ``FORMAT C:`` (no /S) + explicit ``SYS C:``."""
    runner = FakeRunner()
    installer = _make_installer(tmp_path, runner)
    profile = LegacyDosInstallProfile(
        label="DR-DOS 7.03",
        install_image=_empty_floppy(tmp_path),
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format",
        format_yes_input=b"\r\nY\r\n\r\n",
        use_sys_after_format=True,
    )

    captured: dict[str, bytes] = {}
    real_mcopy_text = installer._mcopy_text

    def capture_mcopy_text(image: Path, name: str, payload: bytes) -> None:
        captured[name] = payload
        real_mcopy_text(image, name, payload)

    installer._mcopy_text = capture_mcopy_text  # type: ignore[assignment]
    installer._prepare_install_floppy(profile)

    autoexec = captured["AUTOEXEC.BAT"]
    # No more FORMAT /S — just FORMAT C: with YES.TXT and then SYS C:.
    assert b"FORMAT C: /S" not in autoexec
    assert b"FORMAT C: < A:\\YES.TXT > A:\\FMT_OUT.TXT" in autoexec
    assert b"SYS C: < A:\\SYSIN.TXT > A:\\SYS_OUT.TXT" in autoexec
    # Marker still written after SYS so a slow QEMU exit doesn't kill it.
    assert b"ECHO OK> C:\\VHDMK.OK" in autoexec
    # Both stdin streams staged.
    assert captured["YES.TXT"] == b"\r\nY\r\n\r\n"
    assert captured["SYSIN.TXT"] == b"\r\n"


# ---------------------------------------------------------------------------
# supplementary disks
# ---------------------------------------------------------------------------


def test_supplementary_disks_extract_and_merge(tmp_path: Path) -> None:
    """Files matching extract globs are pulled out of supplementary disks."""
    install = _empty_floppy(tmp_path, "Disk01.img", size=368_640)
    disk06 = _empty_floppy(tmp_path, "Disk06.img", size=368_640)

    extracted: list[Path] = []

    def fake_run(cmd: tuple[str, ...]) -> RunResult:
        # First mcopy in the supplementary path: extract from disk → scratch.
        # Shape: ['mcopy', '-i', '<disk>', '::NAME', '<scratch>']
        # Make the extract appear to succeed for FORMAT.COM and SYS.COM,
        # and fail for FDISK.COM (not present on Disk06).
        if cmd[0] == "mcopy" and "-i" in cmd and len(cmd) == 5:
            name = cmd[3].removeprefix("::")
            scratch = Path(cmd[4])
            if name in ("FORMAT.COM", "SYS.COM"):
                scratch.write_bytes(b"\x4d\x5a" + bytes(50))  # fake MZ stub
                extracted.append(scratch)
                return RunResult(command=cmd, returncode=0, stdout="", stderr="")
            return RunResult(command=cmd, returncode=1, stdout="", stderr="not found")
        return RunResult(command=cmd, returncode=0, stdout="", stderr="")

    runner = FakeRunner(on_run=fake_run)
    installer = _make_installer(tmp_path, runner)
    profile = LegacyDosInstallProfile(
        label="DR-DOS 6.0 5.25",
        install_image=install,
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format",
        format_yes_input=b"\r\nY\r\n\r\n",
        use_sys_after_format=True,
        supplementary_disk_images=(disk06,),
        supplementary_disk_extract_globs=("FORMAT.COM", "SYS.COM", "FDISK.COM"),
    )

    installer._prepare_install_floppy(profile)

    # Three extract attempts (one per glob name).
    extract_calls = [
        c for c in runner.calls
        if c[0] == "mcopy" and "-i" in c and c[2] == str(disk06)
    ]
    extract_targets = sorted(c[3] for c in extract_calls)
    assert extract_targets == ["::FDISK.COM", "::FORMAT.COM", "::SYS.COM"]

    # Two successful merges (FORMAT.COM, SYS.COM) → mcopy back to work floppy.
    merge_calls = [
        c for c in runner.calls
        if c[0] == "mcopy" and "-o" in c and c[-1] in ("::FORMAT.COM", "::SYS.COM")
    ]
    assert len(merge_calls) == 2


def test_no_supplementary_disks_skips_merge(tmp_path: Path) -> None:
    """Empty supplementary fields → ``_merge_supplementary_disks`` is a no-op."""
    runner = FakeRunner()
    installer = _make_installer(tmp_path, runner)
    profile = LegacyDosInstallProfile(
        label="DR-DOS 7.03",
        install_image=_empty_floppy(tmp_path),
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format",
        format_yes_input=b"\r\nY\r\n\r\n",
        use_sys_after_format=True,
    )

    installer._prepare_install_floppy(profile)

    # No mcopy call should touch Disk0N siblings — verify no extract-pattern
    # call exists (extract pattern: ['mcopy', '-i', <disk>, '::NAME', <scratch>]).
    extract_pattern_calls = [
        c for c in runner.calls
        if c[0] == "mcopy" and "-i" in c and len(c) == 5
    ]
    assert extract_pattern_calls == []


# ---------------------------------------------------------------------------
# DR-DOS 6 profile auto-detection
# ---------------------------------------------------------------------------


def test_drdos6_profile_detects_525_archive(tmp_path: Path) -> None:
    """DR-DOS 6 profile picks up Disk02..Disk06 siblings + scrub list."""
    archive_dir = tmp_path / "Digital Research DR-DOS 6.0 (5.25)"
    archive_dir.mkdir()
    install = archive_dir / "Disk01.img"
    install.write_bytes(b"\x00" * 368_640)
    for n in range(2, 7):
        (archive_dir / f"Disk0{n}.img").write_bytes(b"\x00" * 368_640)

    profile = drdos6_profile(install)

    assert profile.use_sys_after_format is True
    sup_names = sorted(p.name for p in profile.supplementary_disk_images)
    assert sup_names == [
        "Disk02.img",
        "Disk03.img",
        "Disk04.img",
        "Disk05.img",
        "Disk06.img",
    ]
    assert "FORMAT.COM" in profile.supplementary_disk_extract_globs
    assert "SYS.COM" in profile.supplementary_disk_extract_globs
    assert "FDISK.COM" in profile.supplementary_disk_extract_globs
    # Pre-install scrub frees the 360 KB Disk01 budget for the new tools.
    assert "VIEWMAX" in profile.pre_install_deletes
    assert "EMM386.SYS" in profile.pre_install_deletes
    # System files we want to keep are NEVER scrubbed.
    assert "IBMBIO.COM" not in profile.pre_install_deletes
    assert "IBMDOS.COM" not in profile.pre_install_deletes
    assert "COMMAND.COM" not in profile.pre_install_deletes


def test_drdos6_profile_no_siblings_no_supplementary(tmp_path: Path) -> None:
    """Lone Disk01 (e.g. 3.5" 4-disk alt archive case) → no merge config."""
    install = tmp_path / "disk01.img"
    install.write_bytes(b"\x00" * 737_280)  # 720 KB

    profile = drdos6_profile(install)

    assert profile.use_sys_after_format is True
    assert profile.supplementary_disk_images == ()
    assert profile.pre_install_deletes == ()


def test_drdos7_profile_no_supplementary(tmp_path: Path) -> None:
    """DR-DOS 7 single 1.44 MB floppy archive → no merge needed."""
    install = tmp_path / "Installation & Utilities 1.img"
    install.write_bytes(b"\x00" * 1_474_560)

    profile = drdos7_profile(install)

    assert profile.use_sys_after_format is True
    assert profile.supplementary_disk_images == ()
    assert profile.supplementary_disk_extract_globs == ()


# ---------------------------------------------------------------------------
# Diagnostic preservation: FAILED-VERIFY-*
# ---------------------------------------------------------------------------


def test_verify_failure_preserves_install_floppy(tmp_path: Path) -> None:
    """If _verify_install raises, work floppy is preserved as FAILED-VERIFY-*."""
    runner = FakeRunner()
    installer = _make_installer(tmp_path, runner)

    install_img = _empty_floppy(tmp_path)
    profile = LegacyDosInstallProfile(
        label="DR-DOS 7.03",
        install_image=install_img,
        required_system_files=("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
        install_method="format",
        format_yes_input=b"\r\nY\r\n\r\n",
        use_sys_after_format=True,
    )

    # Bypass QEMU; force _verify_install to raise.
    installer._run_qemu = lambda **kw: None  # type: ignore[assignment]

    def fake_verify(**kwargs: object) -> None:
        raise ValidationError("system files missing on C:")

    installer._verify_install = fake_verify  # type: ignore[assignment]

    fake_vhd = tmp_path / "fake.vhd"
    fake_vhd.write_bytes(b"\x00" * 1024)

    with pytest.raises(ValidationError):
        installer.install_system(
            vhd_path=fake_vhd,
            partition_offset_bytes=63 * 512,
            profile=profile,
        )

    # FAILED-VERIFY-<name>.img should exist under cache_root.
    preserved = list(installer.cache_root.glob("FAILED-VERIFY-*.img"))
    assert preserved, "expected FAILED-VERIFY-*.img postmortem floppy"
    # And the original work floppy should be unlinked.
    work_originals = [
        p for p in installer.cache_root.glob("legacydos-sys-*.img")
        if not p.name.startswith("FAILED-")
    ]
    assert work_originals == []


def test_qemu_failure_preserves_install_floppy_with_qemu_prefix(tmp_path: Path) -> None:
    """If _run_qemu raises, work floppy is preserved as FAILED-QEMU-*."""
    runner = FakeRunner()
    installer = _make_installer(tmp_path, runner)

    install_img = _empty_floppy(tmp_path)
    profile = LegacyDosInstallProfile(
        label="DR-DOS 7.03",
        install_image=install_img,
        required_system_files=("IBMBIO.COM",),
        install_method="format",
        format_yes_input=b"\r\nY\r\n\r\n",
        use_sys_after_format=True,
    )

    def fail_run_qemu(**kwargs: object) -> None:
        raise ValidationError("qemu blew up")

    installer._run_qemu = fail_run_qemu  # type: ignore[assignment]

    fake_vhd = tmp_path / "fake.vhd"
    fake_vhd.write_bytes(b"\x00" * 1024)

    with pytest.raises(ValidationError):
        installer.install_system(
            vhd_path=fake_vhd,
            partition_offset_bytes=63 * 512,
            profile=profile,
        )

    preserved = list(installer.cache_root.glob("FAILED-QEMU-*.img"))
    assert preserved, "expected FAILED-QEMU-*.img postmortem floppy"
