"""DOSBox-X-driven boot verification for built DOS disks.

Phase 14H (informal): unit tests and the build-matrix script declare
"build OK" when ``dosforge create`` exits cleanly, but that doesn't
guarantee the disk actually boots into a DOS prompt -- the user has
observed many "OK" builds that fail to reach C:\\> when loaded into
86Box.  This module closes the gap: given a built VHD or floppy IMG,
it runs DOSBox-X headless against a *probe copy* and reports whether
DOS actually got far enough to execute AUTOEXEC.BAT.

Authenticity rule observance
----------------------------

The harness ONLY mutates a **copy** of the built disk -- the
user-facing artifact is never modified.  Marker injection only
touches AUTOEXEC.BAT (creates it if absent; appends if present);
CONFIG.SYS is never touched so the 4DOS overlay's ``SHELL=`` line
and similar install-set-up content survives.

DOSBox-X behaviour notes (verified against official wiki, 2026-05-25)
---------------------------------------------------------------------

- ``EXIT`` / ``QUIT`` are DOSBox-X's *internal shell* built-ins.
  After ``BOOT -L C`` the DOSBox-X shell is replaced by the booted
  DOS's COMMAND.COM, so those commands are gone.  We CANNOT use an
  in-DOS ``EXIT`` line to terminate the emulator.
- ``-time-limit N`` (documented as "Starts and terminates DOSBox-X
  after 'n' seconds") IS the supported hard-cap mechanism, and
  what this module uses.
- ``-silent`` runs without showing the window and auto-exits after
  the host [autoexec] section finishes.  ``-fastlaunch`` skips the
  welcome banner.

Boot success signal
-------------------

The probe injects this script into the disk's AUTOEXEC.BAT:

    ECHO BOOTOK > COM1
    ECHO BOOTOK > C:\\BOOTOK.TXT

The host runs:

    dosbox-x.exe -conf <probe.conf> -silent -fastlaunch -time-limit N -exit

Where ``probe.conf`` does ``imgmount 2 <disk> ...`` and ``boot -l c``,
and routes COM1 to a host-side log file.

After DOSBox-X terminates (either at the time-limit or when the
booted DOS's AUTOEXEC.BAT finishes), the host checks ``C:\\BOOTOK.TXT``
on the VHD via mtools AND reads the serial log file.  Either signal
== boot succeeded; neither == boot failed.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from ._core import mbr as core_mbr
from ._core import vhd_footer as core_vhd_footer
from .commands import CommandRunner
from .errors import ValidationError


_MARKER_TOKEN = "BOOTOK"
_AUTOEXEC_MARKER_LINES = (
    f"ECHO {_MARKER_TOKEN} > COM1\r\n"
    f"ECHO {_MARKER_TOKEN} > C:\\BOOTOK.TXT\r\n"
).encode("ascii")


@dataclass(slots=True)
class BootProbeResult:
    """Outcome of a single ``run_boot_probe`` invocation.

    ``success`` is True when EITHER the serial log contains the marker
    OR the on-disk marker file is present.  Both empty strings/None mean
    the disk didn't even reach AUTOEXEC.BAT -- a real boot failure.

    ``dosbox_exit_code`` is the emulator's exit code.  DOSBox-X
    ``-time-limit`` typically exits 0 on either normal exit or
    time-limit hit, so this is rarely the discriminator.

    ``serial_tail`` and ``dosbox_stderr_tail`` are kept short (last 2 KiB)
    so they are safe to embed in test assertion messages without
    flooding pytest output.
    """

    success: bool
    marker_via_serial: bool
    marker_via_disk: bool
    elapsed_seconds: float
    dosbox_exit_code: int | None
    serial_tail: str = ""
    dosbox_stderr_tail: str = ""
    probe_disk_path: Path | None = None
    conf_path: Path | None = None

    def short_reason(self) -> str:
        if self.success:
            sources = []
            if self.marker_via_serial:
                sources.append("serial")
            if self.marker_via_disk:
                sources.append("disk")
            return f"boot OK ({'+'.join(sources)})"
        if self.elapsed_seconds >= 0:
            return "boot FAIL (no marker reached AUTOEXEC.BAT)"
        return "boot FAIL"


@dataclass(slots=True)
class _DiskInfo:
    """Geometry/layout we need from a built disk to drive DOSBox-X."""

    media: str  # "vhd" or "img"
    cylinders: int
    heads: int
    sectors_per_track: int
    partition_offset_bytes: int


def _read_vhd_info(disk_path: Path) -> _DiskInfo:
    footer = core_vhd_footer.read_footer(disk_path)
    entry = core_mbr.read_partition_entry(disk_path, slot=0)
    if entry is None:
        raise ValidationError(
            f"Probe target has no MBR partition: {disk_path}.  Bootable "
            "VHDs must have a primary partition; non-bootable disks "
            "shouldn't be boot-probed."
        )
    return _DiskInfo(
        media="vhd",
        cylinders=footer.cylinders,
        heads=footer.heads,
        sectors_per_track=footer.sectors_per_track,
        partition_offset_bytes=entry.first_lba * 512,
    )


def _read_img_info(disk_path: Path) -> _DiskInfo:
    """Read floppy BPB to learn CHS for DOSBox-X imgmount.

    Floppies have no MBR -- the BPB at sector 0 carries the geometry.
    """
    with disk_path.open("rb") as handle:
        sector = handle.read(512)
    if len(sector) < 512:
        raise ValidationError(f"Floppy IMG too small: {disk_path}")
    sectors_per_track = struct.unpack_from("<H", sector, 24)[0] or 18
    heads = struct.unpack_from("<H", sector, 26)[0] or 2
    total_sectors_16 = struct.unpack_from("<H", sector, 19)[0]
    total_sectors_32 = struct.unpack_from("<I", sector, 32)[0]
    total_sectors = total_sectors_16 or total_sectors_32 or (disk_path.stat().st_size // 512)
    cylinders = max(1, total_sectors // max(1, sectors_per_track * heads))
    return _DiskInfo(
        media="img",
        cylinders=cylinders,
        heads=heads,
        sectors_per_track=sectors_per_track,
        partition_offset_bytes=0,
    )


def inject_boot_marker(
    *,
    runner: CommandRunner,
    disk_path: Path,
    media: str,
    partition_offset_bytes: int = 0,
) -> None:
    """Append the marker lines to AUTOEXEC.BAT on the probe disk.

    Creates AUTOEXEC.BAT if absent (legacy DOS modes typically don't
    write one).  Preserves any existing content -- we strip a trailing
    blank line then append the marker lines, so a pre-existing
    AUTOEXEC.BAT (e.g. the 4DOS overlay's PATH+PROMPT script) still
    runs first and the marker still gets written.

    NEVER touches CONFIG.SYS or any other file -- in particular the
    4DOS overlay's CONFIG.SYS ``SHELL=`` line stays intact.
    """
    if media == "vhd":
        partition_target = f"{disk_path}@@{partition_offset_bytes}"
    else:
        partition_target = str(disk_path)

    # Try to fetch existing AUTOEXEC.BAT.  mtools' mcopy with src=- and
    # dst=local-path-prefix-style isn't quite right; we use mtype
    # instead which captures content to stdout.
    existing: bytes = b""
    fetch = runner.run(
        ["mtype", "-i", partition_target, "::AUTOEXEC.BAT"],
        check=False,
    )
    if fetch.returncode == 0:
        existing = (fetch.stdout or "").encode("ascii", "replace")

    if existing and not existing.endswith((b"\r\n", b"\n")):
        existing += b"\r\n"

    new_content = existing + _AUTOEXEC_MARKER_LINES

    # Stage to a scratch file, then mcopy back.
    scratch = Path(os.environ.get("TEMP", os.environ.get("TMPDIR", "."))) / (
        f"dosforge-probe-autoexec-{uuid4().hex[:8]}.bat"
    )
    scratch.write_bytes(new_content)
    try:
        runner.run(
            ["mcopy", "-o", "-i", partition_target, str(scratch), "::AUTOEXEC.BAT"],
        )
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass


def _write_probe_conf(
    *,
    conf_path: Path,
    disk_path: Path,
    info: _DiskInfo,
    serial_log_path: Path,
) -> None:
    """Write a minimal dosbox-x.conf that imgmounts + boots the disk.

    The [autoexec] section runs three commands: imgmount the disk as
    IDE master (for VHDs) or floppy A (for IMGs), tell DOS the COM1
    serial output goes to the host log file, and BOOT off the disk.

    We deliberately use ``machine=svga_s3`` (DOSBox-X default) and a
    modest 16 MiB memsize -- enough for any DOS we ship to boot, and
    small enough to keep CI memory pressure low.
    """
    if info.media == "vhd":
        imgmount_line = (
            f'imgmount 2 "{disk_path.as_posix()}" -fs none '
            f"-size 512,{info.sectors_per_track},{info.heads},{info.cylinders}"
        )
        boot_line = "boot -l c"
    else:
        imgmount_line = f'imgmount A "{disk_path.as_posix()}" -t floppy'
        boot_line = "boot -l a"

    serial_line = f"serial1=file file:{serial_log_path.as_posix()}"

    conf = (
        "[dosbox]\n"
        "machine=svga_s3\n"
        "memsize=16\n"
        "\n"
        "[cpu]\n"
        "core=normal\n"
        "cputype=auto\n"
        "\n"
        "[render]\n"
        "frameskip=0\n"
        "\n"
        "[sdl]\n"
        "output=surface\n"
        "autolock=false\n"
        "\n"
        "[mixer]\n"
        "nosound=true\n"
        "\n"
        "[serial]\n"
        f"{serial_line}\n"
        "\n"
        "[autoexec]\n"
        f"{imgmount_line}\n"
        f"{boot_line}\n"
    )
    conf_path.write_text(conf, encoding="ascii")


def _read_disk_marker(
    *,
    runner: CommandRunner,
    disk_path: Path,
    media: str,
    partition_offset_bytes: int,
) -> bool:
    if media == "vhd":
        partition_target = f"{disk_path}@@{partition_offset_bytes}"
    else:
        partition_target = str(disk_path)
    result = runner.run(
        ["mtype", "-i", partition_target, "::BOOTOK.TXT"],
        check=False,
    )
    if result.returncode != 0:
        return False
    return _MARKER_TOKEN in (result.stdout or "")


def _read_serial_log(path: Path) -> tuple[bool, str]:
    try:
        data = path.read_bytes()
    except OSError:
        return (False, "")
    text = data.decode("ascii", "replace")
    return (_MARKER_TOKEN in text, text[-2048:])


def _resolve_dosbox_path(backend) -> str:
    """Find dosbox-x via the platform backend's bundled-tool resolver.

    Returns the absolute path when bundled; falls back to a bare
    ``dosbox-x`` name (PATH lookup) on Linux or when the vendor copy
    hasn't been fetched.
    """
    return backend.tool_path("dosbox-x")


def run_boot_probe(
    *,
    runner: CommandRunner,
    disk_path: Path,
    media: str,
    work_dir: Path,
    time_limit_seconds: int = 30,
    inject_marker: bool = True,
    backend=None,
    dosbox_argv_extra: Sequence[str] = (),
) -> BootProbeResult:
    """Boot ``disk_path`` in DOSBox-X and report whether DOS reached AUTOEXEC.

    ``work_dir`` collects the probe artifacts (the probe copy of the
    disk, the conf file, the serial log).  Caller is responsible for
    creating and cleaning up ``work_dir``; we don't delete it on
    failure so the caller can grep the serial log for diagnostics.

    ``inject_marker=False`` skips the AUTOEXEC.BAT mutation -- useful
    for tests of the harness itself that verify behaviour without
    needing a real disk.
    """
    if backend is None:
        from ._platform import get_backend

        backend = get_backend()

    work_dir.mkdir(parents=True, exist_ok=True)
    probe_disk = work_dir / f"probe-{disk_path.name}"
    shutil.copy2(disk_path, probe_disk)

    if media == "vhd":
        info = _read_vhd_info(probe_disk)
    elif media == "img":
        info = _read_img_info(probe_disk)
    else:
        raise ValidationError(f"Unknown media type: {media!r}")

    if inject_marker:
        inject_boot_marker(
            runner=runner,
            disk_path=probe_disk,
            media=media,
            partition_offset_bytes=info.partition_offset_bytes,
        )

    serial_log = work_dir / "serial.log"
    serial_log.write_bytes(b"")  # truncate / create
    conf_path = work_dir / "probe.conf"
    _write_probe_conf(
        conf_path=conf_path,
        disk_path=probe_disk,
        info=info,
        serial_log_path=serial_log,
    )

    dosbox_exe = _resolve_dosbox_path(backend)
    con_log = work_dir / "console.log"
    argv = [
        dosbox_exe,
        "-conf", str(conf_path),
        "-silent",
        "-fastlaunch",
        "-time-limit", str(time_limit_seconds),
        "-exit",
        "-log-con",  # routes booted-DOS CON output to a file
        *dosbox_argv_extra,
    ]

    t0 = time.monotonic()
    # Process timeout = time_limit + 10s grace (DOSBox-X may take a
    # second or two to actually tear down once -time-limit fires).
    proc_timeout = time_limit_seconds + 10
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=proc_timeout,
        )
        exit_code: int | None = proc.returncode
        stderr_tail = (proc.stderr or "")[-2048:]
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stderr_tail = (
            "DOSBox-X did not exit within "
            f"{proc_timeout}s (time-limit was {time_limit_seconds}s); host killed it.\n"
            f"stderr-so-far: {(exc.stderr or '')!r}"
        )
    elapsed = time.monotonic() - t0

    marker_serial, serial_text = _read_serial_log(serial_log)
    marker_disk = _read_disk_marker(
        runner=runner,
        disk_path=probe_disk,
        media=media,
        partition_offset_bytes=info.partition_offset_bytes,
    )

    success = marker_serial or marker_disk
    return BootProbeResult(
        success=success,
        marker_via_serial=marker_serial,
        marker_via_disk=marker_disk,
        elapsed_seconds=elapsed,
        dosbox_exit_code=exit_code,
        serial_tail=serial_text[-2048:],
        dosbox_stderr_tail=stderr_tail,
        probe_disk_path=probe_disk,
        conf_path=conf_path,
    )
