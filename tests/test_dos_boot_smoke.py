"""Boot-smoke tests for every supported DOS boot mode.

Builds a representative disk for each (boot_mode, media, format) combo
that dosforge claims to support, then runs ``_boot_probe.run_boot_probe``
against it.  Asserts the disk actually boots into AUTOEXEC.BAT in
DOSBox-X -- catching cases where the build succeeds but the resulting
disk doesn't reach a DOS prompt.

Gated by ``DOSFORGE_RUN_DOS_BOOT_SMOKE=1`` because:
  1. Each test takes 15-60 seconds (build + DOSBox-X probe)
  2. Requires the bundled DOSBox-X binary at
     ``vendor/windows/bin/dosbox-x.exe``
  3. Generates real disk artifacts in ``tmp_path``

Run locally with:

    DOSFORGE_RUN_DOS_BOOT_SMOKE=1 pytest tests/test_dos_boot_smoke.py -v
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from dosforge._boot_probe import run_boot_probe
from dosforge.commands import CommandRunner
from dosforge.disk import DiskManager
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)


_OPT_IN_ENV = "DOSFORGE_RUN_DOS_BOOT_SMOKE"


def _opted_in() -> bool:
    return os.environ.get(_OPT_IN_ENV, "").strip() in ("1", "true", "TRUE", "yes", "on")


pytestmark = pytest.mark.skipif(
    not _opted_in(),
    reason=f"Set {_OPT_IN_ENV}=1 to run boot-smoke tests (slow + needs DOSBox-X).",
)


@dataclass(frozen=True)
class _BootCase:
    """One row of the boot-smoke matrix."""

    test_id: str
    boot_mode: BootMode
    media: MediaType
    disk_format: DiskFormat
    size_bytes: int
    floppy_type: FloppyType = FloppyType.F1440K
    ibm_dos_version: IBMDOSVersion = IBMDOSVersion.DOS33
    boot_assets_path: "Path | None" = None
    img_system_format: bool = False
    time_limit_seconds: int = 30
    expected_to_boot: bool = True  # Set False for documented known-failures


_W95 = Path(r"C:\Projects\dosforge\dosassets\w95")


# Matrix kept in sync with files/build-matrix.py.  Mirrors the same
# success/failure expectations the user has verified manually.
_CASES: tuple[_BootCase, ...] = (
    _BootCase(
        test_id="freedos-vhd-fat16-32m",
        boot_mode=BootMode.FREEDOS,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
    ),
    _BootCase(
        test_id="msdos33-vhd-fat16-32m",
        boot_mode=BootMode.MSDOS33,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
    ),
    _BootCase(
        test_id="msdos33-img-fat12-360k",
        boot_mode=BootMode.MSDOS33,
        media=MediaType.IMG,
        disk_format=DiskFormat.FAT12,
        size_bytes=360 * 1024,
        floppy_type=FloppyType.F360K,
        img_system_format=True,
    ),
    _BootCase(
        test_id="msdos71-vhd-fat16-32m",
        boot_mode=BootMode.MSDOS71,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
        boot_assets_path=_W95,
    ),
    _BootCase(
        test_id="ibm8088-dos33-vhd-fat16-32m",
        boot_mode=BootMode.IBM8088,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
        ibm_dos_version=IBMDOSVersion.DOS33,
    ),
    # Known-failing per the matrix run on this branch -- static-template
    # boot install produces a VBR that doesn't load IO.SYS correctly.
    # These cases are tracked here so the suite reflects ground truth;
    # set ``expected_to_boot=False`` so the assertion is XFAIL-style
    # documentation rather than a noisy failure.
    _BootCase(
        test_id="msdos5-vhd-fat16-32m",
        boot_mode=BootMode.MSDOS5,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
        expected_to_boot=False,
    ),
    _BootCase(
        test_id="msdos622-vhd-fat16-32m",
        boot_mode=BootMode.MSDOS622,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
        expected_to_boot=False,
    ),
    _BootCase(
        test_id="pcdos7-vhd-fat16-32m",
        boot_mode=BootMode.PCDOS7,
        media=MediaType.VHD,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
        expected_to_boot=False,
    ),
)


def _build_disk(case: _BootCase, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".vhd" if case.media is MediaType.VHD else ".img"
    out_path = out_dir / f"{case.test_id}{suffix}"
    request = CreateRequest(
        path=out_path,
        size_bytes=case.size_bytes,
        disk_format=case.disk_format,
        media_type=case.media,
        floppy_type=case.floppy_type,
        img_system_format=case.img_system_format,
        boot_mode=case.boot_mode,
        ibm_dos_version=case.ibm_dos_version,
        boot_assets_path=case.boot_assets_path,
        overwrite=True,
    )
    mgr = DiskManager()
    mgr.create_and_prepare(request)
    return out_path


@pytest.mark.parametrize("case", _CASES, ids=[c.test_id for c in _CASES])
def test_boot_smoke(case: _BootCase, tmp_path: Path) -> None:
    """Build the disk, probe it with DOSBox-X, assert boot reaches AUTOEXEC."""
    disk = _build_disk(case, tmp_path / "disks")
    media = "vhd" if case.media is MediaType.VHD else "img"
    work = tmp_path / "probe"
    result = run_boot_probe(
        runner=CommandRunner(),
        disk_path=disk,
        media=media,
        work_dir=work,
        time_limit_seconds=case.time_limit_seconds,
    )
    if case.expected_to_boot:
        assert result.success, (
            f"{case.test_id} did not boot to AUTOEXEC.BAT in "
            f"{result.elapsed_seconds:.1f}s.\n"
            f"reason: {result.short_reason()}\n"
            f"serial tail: {result.serial_tail!r}\n"
            f"dosbox stderr tail: {result.dosbox_stderr_tail[-800:]!r}"
        )
    else:
        # Documented known-failure: assert it still DOESN'T boot.
        # When someone fixes the underlying issue, this assertion
        # flips and forces them to update ``expected_to_boot=True``.
        assert not result.success, (
            f"{case.test_id} now boots successfully -- update "
            "expected_to_boot=True in the test case definition."
        )
