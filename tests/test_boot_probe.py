"""Tests for the DOSBox-X boot-probe harness.

These tests verify the harness's machinery (marker injection,
conf-file generation, serial-log parsing, time-limit enforcement)
without requiring a real DOSBox-X run -- a stub binary is used
instead so the tests run in milliseconds on any platform.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dosforge._boot_probe import (
    BootProbeResult,
    _MARKER_TOKEN,
    _AUTOEXEC_MARKER_LINES,
    _read_img_info,
    _write_probe_conf,
    inject_boot_marker,
    run_boot_probe,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingRunner:
    """Captures mtools commands without invoking them.

    Returns canned stdout for ``mtype`` so tests can simulate "existing
    AUTOEXEC.BAT" without touching a real image.  For ``mcopy`` calls,
    reads the source file BEFORE returning so the test can inspect what
    would have been written -- the harness deletes the scratch file
    immediately after the (faked-OK) mcopy returns.
    """

    def __init__(self, mtype_stdout_for: dict[tuple[str, ...], str] | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.mcopy_payloads: list[bytes] = []
        self._mtype_stdout = mtype_stdout_for or {}

    def run(self, command: list[str], **kwargs: Any) -> Any:
        self.calls.append((tuple(command), kwargs))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if command and command[0] == "mtype":
            key = tuple(command[1:])
            if key in self._mtype_stdout:
                r = _Result()
                r.stdout = self._mtype_stdout[key]
                return r
            r = _Result()
            r.returncode = 1
            return r

        if command and command[0] == "mcopy":
            # mcopy ... <scratch> ::DEST -- snapshot the scratch before
            # the harness deletes it
            for arg in command:
                p = Path(arg)
                if p.is_file():
                    self.mcopy_payloads.append(p.read_bytes())
                    break

        return _Result()


# ---------------------------------------------------------------------------
# Marker injection
# ---------------------------------------------------------------------------


def test_inject_marker_when_no_existing_autoexec(tmp_path: Path) -> None:
    """No existing AUTOEXEC.BAT on disk -> create one with just the marker."""
    runner = _RecordingRunner()
    inject_boot_marker(
        runner=runner,
        disk_path=tmp_path / "x.vhd",
        media="vhd",
        partition_offset_bytes=1048576,
    )
    mtype_calls = [c for c in runner.calls if c[0][0] == "mtype"]
    assert len(mtype_calls) == 1
    mcopy_calls = [c for c in runner.calls if c[0][0] == "mcopy"]
    assert len(mcopy_calls) == 1
    assert runner.mcopy_payloads
    assert runner.mcopy_payloads[0] == _AUTOEXEC_MARKER_LINES


def test_inject_marker_preserves_existing_autoexec(tmp_path: Path) -> None:
    """Existing AUTOEXEC.BAT content survives, marker lines appended."""
    existing = "@ECHO OFF\r\nPATH C:\\;C:\\4DOS\r\nPROMPT $P$G\r\n"
    partition_target = f"{tmp_path / 'x.vhd'}@@1048576"
    runner = _RecordingRunner(
        mtype_stdout_for={
            ("-i", partition_target, "::AUTOEXEC.BAT"): existing,
        }
    )
    inject_boot_marker(
        runner=runner,
        disk_path=tmp_path / "x.vhd",
        media="vhd",
        partition_offset_bytes=1048576,
    )
    mcopy_calls = [c for c in runner.calls if c[0][0] == "mcopy"]
    assert len(mcopy_calls) == 1
    assert runner.mcopy_payloads, "RecordingRunner must capture mcopy payload"
    contents = runner.mcopy_payloads[0]
    assert b"PATH C:\\;C:\\4DOS" in contents
    assert b"PROMPT $P$G" in contents
    assert _AUTOEXEC_MARKER_LINES in contents
    assert contents.index(b"PROMPT $P$G") < contents.index(_AUTOEXEC_MARKER_LINES)


def test_inject_marker_for_img_uses_image_path_directly(tmp_path: Path) -> None:
    """For floppy IMGs, the partition target is the IMG path itself."""
    runner = _RecordingRunner()
    inject_boot_marker(
        runner=runner,
        disk_path=tmp_path / "floppy.img",
        media="img",
        partition_offset_bytes=0,
    )
    # The mtype/mcopy commands must use the IMG path, not an offset string
    for cmd, _ in runner.calls:
        if cmd[0] in ("mtype", "mcopy"):
            assert "@@" not in cmd[2], f"floppy IMG path must not have @@offset: {cmd!r}"


def test_marker_lines_format() -> None:
    """The marker payload must contain both COM1 echo and disk echo."""
    text = _AUTOEXEC_MARKER_LINES.decode("ascii")
    assert "ECHO BOOTOK > COM1" in text
    assert "ECHO BOOTOK > C:\\BOOTOK.TXT" in text
    # CRLF line endings (real DOS expects them)
    assert text.endswith("\r\n")


# ---------------------------------------------------------------------------
# Conf-file generation
# ---------------------------------------------------------------------------


def test_write_probe_conf_vhd_has_imgmount_with_chs(tmp_path: Path) -> None:
    from dosforge._boot_probe import _DiskInfo

    conf_path = tmp_path / "probe.conf"
    serial_log = tmp_path / "serial.log"
    info = _DiskInfo(
        media="vhd",
        cylinders=131,
        heads=16,
        sectors_per_track=63,
        partition_offset_bytes=1048576,
    )
    _write_probe_conf(
        conf_path=conf_path,
        disk_path=tmp_path / "msdos71-test.vhd",
        info=info,
        serial_log_path=serial_log,
    )
    text = conf_path.read_text(encoding="ascii")
    # Conf must imgmount the VHD with exact CHS so DOSBox-X matches the
    # footer geometry (not its own auto-detect)
    assert "imgmount 2" in text
    assert "-size 512,63,16,131" in text
    assert "-fs none" in text
    assert "boot -l c" in text
    # COM1 serial routed to the host log file
    assert f"serial1=file file:{serial_log.as_posix()}" in text
    assert "[autoexec]" in text


def test_write_probe_conf_img_uses_floppy_imgmount(tmp_path: Path) -> None:
    from dosforge._boot_probe import _DiskInfo

    conf_path = tmp_path / "probe.conf"
    info = _DiskInfo(
        media="img",
        cylinders=80,
        heads=2,
        sectors_per_track=18,
        partition_offset_bytes=0,
    )
    _write_probe_conf(
        conf_path=conf_path,
        disk_path=tmp_path / "floppy.img",
        info=info,
        serial_log_path=tmp_path / "serial.log",
    )
    text = conf_path.read_text(encoding="ascii")
    assert "imgmount A" in text
    assert "boot -l a" in text


# ---------------------------------------------------------------------------
# IMG BPB geometry parsing
# ---------------------------------------------------------------------------


def test_read_img_info_parses_standard_1440k_bpb(tmp_path: Path) -> None:
    """1.44 MiB floppy: spt=18, heads=2, total=2880 -> cyl=80."""
    img = tmp_path / "f.img"
    sector = bytearray(512)
    sector[0:3] = b"\xEB\x3C\x90"
    sector[3:11] = b"MSDOS5.0"
    struct.pack_into("<H", sector, 11, 512)  # BPS
    sector[13] = 1                            # spc
    struct.pack_into("<H", sector, 14, 1)    # reserved
    sector[16] = 2                            # FATs
    struct.pack_into("<H", sector, 17, 224)  # root entries
    struct.pack_into("<H", sector, 19, 2880) # total_sec_16
    sector[21] = 0xF0                         # media
    struct.pack_into("<H", sector, 22, 9)    # FAT size
    struct.pack_into("<H", sector, 24, 18)   # spt
    struct.pack_into("<H", sector, 26, 2)    # heads
    sector[510:512] = b"\x55\xAA"
    img.write_bytes(bytes(sector))
    # Pad to 1.44 MiB
    with img.open("ab") as h:
        h.write(b"\x00" * (1474560 - 512))

    info = _read_img_info(img)
    assert info.media == "img"
    assert info.sectors_per_track == 18
    assert info.heads == 2
    assert info.cylinders == 80


def test_read_img_info_falls_back_when_bpb_zero(tmp_path: Path) -> None:
    """If BPB spt=0 or heads=0, use 18/2 fallback to avoid divide-by-zero."""
    img = tmp_path / "f.img"
    img.write_bytes(b"\x00" * 1474560)
    info = _read_img_info(img)
    # Doesn't crash; produces sensible defaults
    assert info.sectors_per_track >= 1
    assert info.heads >= 1
    assert info.cylinders >= 1


# ---------------------------------------------------------------------------
# Full run_boot_probe (with stub DOSBox-X binary)
# ---------------------------------------------------------------------------


def _make_stub_backend(stub_exe: Path) -> Any:
    """Tiny shim that mimics the backend's tool_path.

    Returns the exact path passed in -- on Windows we'll point at a
    .cmd that wraps a Python script (since DOSBox-X is normally a .exe
    we have to substitute something Windows knows how to execute).
    """

    class _StubBackend:
        def tool_path(self, name: str) -> str:
            if name == "dosbox-x":
                return str(stub_exe)
            return name

    return _StubBackend()


def _write_python_stub(
    stub_path: Path,
    *,
    serial_marker: bool,
    disk_marker_via_mcopy: bool,
    exit_code: int = 0,
    sleep_seconds: float = 0.0,
) -> Path:
    """Write a script that imitates DOSBox-X's behaviour.

    Returns the path that should be invoked by the harness (a .cmd on
    Windows, the script itself elsewhere).
    """
    py_script = stub_path.with_suffix(".py")
    body = f"""\
import re, subprocess, sys, time
from pathlib import Path

argv = sys.argv[1:]
conf_path = None
for i, a in enumerate(argv):
    if a == '-conf':
        conf_path = Path(argv[i + 1])
        break

serial_path = None
disk_path = None
if conf_path and conf_path.exists():
    text = conf_path.read_text(encoding='ascii')
    m = re.search(r'serial1=file file:(.+)', text)
    if m:
        serial_path = Path(m.group(1).strip())
    m = re.search(r'imgmount 2 "([^"]+)"', text)
    if m:
        disk_path = Path(m.group(1))

if {repr(serial_marker)} and serial_path is not None:
    serial_path.write_text('{_MARKER_TOKEN}\\r\\n', encoding='ascii')

if {repr(disk_marker_via_mcopy)} and disk_path is not None:
    import os, struct, tempfile
    with disk_path.open('rb') as f:
        mbr = f.read(512)
    start = struct.unpack_from('<I', mbr, 0x1BE + 8)[0]
    part = f'{{disk_path}}@@{{start * 512}}'
    scratch = Path(tempfile.gettempdir()) / 'stub-bootok.txt'
    scratch.write_bytes(b'{_MARKER_TOKEN}\\r\\n')
    subprocess.run(['mcopy', '-o', '-i', part, str(scratch), '::BOOTOK.TXT'], check=False)
    scratch.unlink(missing_ok=True)

time.sleep({sleep_seconds})
sys.exit({exit_code})
"""
    py_script.write_text(body, encoding="ascii")

    if sys.platform == "win32":
        cmd = stub_path.with_suffix(".cmd")
        cmd.write_text(
            f'@echo off\r\n"{sys.executable}" "{py_script}" %*\r\n',
            encoding="ascii",
        )
        return cmd
    stub_path.write_text(
        f"#!{sys.executable}\n" + body,
        encoding="ascii",
    )
    os.chmod(stub_path, 0o755)
    return stub_path


def _make_minimal_vhd(tmp_path: Path) -> Path:
    """Build a real (mtools-readable) 1 MiB VHD with a FAT12 partition.

    Uses dosforge's existing pipeline so the probe sees a realistic
    layout (MBR + partition + BPB).
    """
    from dosforge.disk import DiskManager
    from dosforge.models import (
        BootMode,
        CreateRequest,
        DiskFormat,
        MediaType,
    )

    mgr = DiskManager()
    out = tmp_path / "tiny.vhd"
    req = CreateRequest(
        path=out,
        size_bytes=20 * 1024 * 1024,  # 20 MiB (FAT16 min is 16 MiB)
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        boot_mode=BootMode.NONE,
        overwrite=True,
    )
    mgr.create_and_prepare(req)
    return out


@pytest.mark.skipif(
    shutil.which("qemu-img") is None and not Path(r"C:\Projects\dosforge\vendor\windows\bin\qemu-img.exe").exists(),
    reason="qemu-img not available -- can't build a real test VHD",
)
def test_run_boot_probe_with_stub_dosbox_serial_marker(tmp_path: Path) -> None:
    """A stub DOSBox-X that writes the serial marker -> success via serial."""
    pytest.importorskip("dosforge.commands")
    from dosforge.commands import CommandRunner

    vhd = _make_minimal_vhd(tmp_path)
    stub_base = tmp_path / "dosbox-x" / "dosbox-x"
    stub_base.parent.mkdir(parents=True, exist_ok=True)
    invoke_path = _write_python_stub(stub_base, serial_marker=True, disk_marker_via_mcopy=False)
    backend = _make_stub_backend(invoke_path)

    result = run_boot_probe(
        runner=CommandRunner(),
        disk_path=vhd,
        media="vhd",
        work_dir=tmp_path / "probe-work",
        time_limit_seconds=5,
        backend=backend,
    )
    assert result.success
    assert result.marker_via_serial
    assert not result.marker_via_disk
    assert "boot OK" in result.short_reason()


@pytest.mark.skipif(
    shutil.which("qemu-img") is None and not Path(r"C:\Projects\dosforge\vendor\windows\bin\qemu-img.exe").exists(),
    reason="qemu-img not available -- can't build a real test VHD",
)
def test_run_boot_probe_with_stub_dosbox_no_marker_means_fail(tmp_path: Path) -> None:
    """A stub DOSBox-X that writes nothing -> success=False, reason explains."""
    from dosforge.commands import CommandRunner

    vhd = _make_minimal_vhd(tmp_path)
    stub_base = tmp_path / "dosbox-x" / "dosbox-x"
    stub_base.parent.mkdir(parents=True, exist_ok=True)
    invoke_path = _write_python_stub(stub_base, serial_marker=False, disk_marker_via_mcopy=False)
    backend = _make_stub_backend(invoke_path)

    result = run_boot_probe(
        runner=CommandRunner(),
        disk_path=vhd,
        media="vhd",
        work_dir=tmp_path / "probe-work",
        time_limit_seconds=5,
        backend=backend,
    )
    assert not result.success
    assert not result.marker_via_serial
    assert not result.marker_via_disk
    assert "FAIL" in result.short_reason()


def test_boot_probe_result_dataclass_short_reason_handles_partial_success() -> None:
    r = BootProbeResult(
        success=True,
        marker_via_serial=True,
        marker_via_disk=False,
        elapsed_seconds=1.0,
        dosbox_exit_code=0,
    )
    assert r.short_reason() == "boot OK (serial)"

    r = BootProbeResult(
        success=True,
        marker_via_serial=False,
        marker_via_disk=True,
        elapsed_seconds=1.0,
        dosbox_exit_code=0,
    )
    assert r.short_reason() == "boot OK (disk)"

    r = BootProbeResult(
        success=False,
        marker_via_serial=False,
        marker_via_disk=False,
        elapsed_seconds=30.0,
        dosbox_exit_code=0,
    )
    assert "FAIL" in r.short_reason()
