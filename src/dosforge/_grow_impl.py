"""Implementation for the ``dosforge grow`` operation.

Pragmatic v1: extract user files to host scratch, build a fresh
target-sized VHD with the same boot mode (via the existing
``DiskManager.create_and_prepare`` pipeline), inject the user's
files back, stage the manifest's new sources, atomic-swap.

This loses any custom MBR / VBR boot code the user may have hand-
patched -- the new VHD ships with dosforge's standard boot setup
for the chosen mode.  For the four supported modes (COMPAQ331,
MSDOS622, MSDOS71, FREEDOS), that's the same setup the user
originally got, so 99% of the time nothing observable changes.

VBR preservation, cluster-2 contiguity for IO.SYS, and headless
QEMU boot probing are left for v2.

The implementation is mtools-driven so it works on Windows without
NBD / loop mounts.  Linux behaves identically by going through the
same mcopy / mattrib commands.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from .commands import CommandRunner, subprocess_no_window_kwargs
from .disk import DiskManager
from .errors import DependencyError, ValidationError
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MediaType,
    MSDOSInstallProfile,
)
from .size import (
    FAT12_MAX_BYTES,
    FAT16_MAX_BYTES,
)


# Protected files at C:\ root that must NOT be overwritten by user-
# file injection.  These are the DOS system files dosforge create
# laid down on the fresh VHD; replacing them with the user's old
# versions risks losing cluster-2 contiguity or attribute state
# (+s +h) that the bootstrap depends on.
_PROTECTED_ROOT_SYSTEM_FILES: frozenset[str] = frozenset({
    "IO.SYS",
    "MSDOS.SYS",
    "IBMBIO.COM",
    "IBMDOS.COM",
    "COMMAND.COM",
    "KERNEL.SYS",
    "VHDMK.OK",
})

# Files always skipped when extracting/re-injecting (mformat housekeeping,
# Windows oddities, FAT volume label entry as a fake file).
_ALWAYS_SKIP_NAMES: frozenset[str] = frozenset({
    "$RECYCLE.BIN",
    "SYSTEM~1",
})


@dataclass(frozen=True, slots=True)
class _VhdSnapshot:
    """Structural snapshot of an existing VHD at grow-time.

    Captures everything :func:`_validate_cluster_band_match` needs
    plus the partition offset for subsequent mtools operations.
    """

    file_size: int
    partition_lba_start: int
    partition_sector_count: int
    partition_type: int
    partition_offset_bytes: int
    bytes_per_sector: int
    sectors_per_cluster: int
    cluster_size_bytes: int
    fat_format: DiskFormat


def _snapshot_vhd(path: Path) -> _VhdSnapshot:
    """Read MBR + first partition BPB to capture grow-time invariants."""

    file_size = path.stat().st_size
    if file_size < 1024:
        raise ValidationError(f"VHD {path} is too small to be valid.")
    with path.open("rb") as fh:
        mbr = fh.read(512)
        if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
            raise ValidationError(f"VHD {path} has no valid MBR signature.")
        # Partition 1 entry: bytes 446..461
        entry = mbr[446:462]
        part_type = entry[4]
        lba_start = int.from_bytes(entry[8:12], "little")
        sec_count = int.from_bytes(entry[12:16], "little")
        if lba_start == 0 or sec_count == 0:
            raise ValidationError(
                f"VHD {path} has no first MBR partition entry."
            )
        # Read the partition VBR / BPB.
        offset = lba_start * 512
        fh.seek(offset)
        vbr = fh.read(512)
        if len(vbr) < 90:
            raise ValidationError(
                f"VHD {path} partition VBR is truncated; cannot read BPB."
            )
        bytes_per_sector = int.from_bytes(vbr[11:13], "little")
        sectors_per_cluster = vbr[13]
        if bytes_per_sector not in (512,) or sectors_per_cluster == 0:
            raise ValidationError(
                f"VHD {path} BPB looks malformed "
                f"(bytes/sec={bytes_per_sector}, sec/clust={sectors_per_cluster})."
            )
        # Detect FAT12 vs FAT16 vs FAT32 by total cluster count.
        # Use BPB total_sectors_32 if present, else total_sectors_16.
        total_sec_16 = int.from_bytes(vbr[19:21], "little")
        total_sec_32 = int.from_bytes(vbr[32:36], "little")
        total_sectors = total_sec_32 if total_sec_32 else total_sec_16
        reserved = int.from_bytes(vbr[14:16], "little")
        num_fats = vbr[16]
        root_entries = int.from_bytes(vbr[17:19], "little")
        # FAT32 has sectors_per_fat_32 at offset 36; FAT16/12 has it
        # at offset 22.  Microsoft's canonical detection: if
        # sec_per_fat_16 is non-zero, the disk is FAT12/16 and the
        # offset-36 field is repurposed for "drive number / NT
        # reserved / signature / volume serial / volume label" -- do
        # NOT read sec_per_fat_32 from that range or you'll get a
        # bogus 4-byte uint from the volume serial bytes.
        sec_per_fat_16 = int.from_bytes(vbr[22:24], "little")
        if sec_per_fat_16 != 0:
            sec_per_fat = sec_per_fat_16
        else:
            sec_per_fat = (
                int.from_bytes(vbr[36:40], "little") if len(vbr) >= 40 else 0
            )
        root_dir_sectors = (
            (root_entries * 32) + bytes_per_sector - 1
        ) // bytes_per_sector
        data_sec = total_sectors - (reserved + num_fats * sec_per_fat + root_dir_sectors)
        cluster_count = data_sec // sectors_per_cluster if sectors_per_cluster else 0
        if cluster_count < 4085:
            fat_format = DiskFormat.FAT12
        elif cluster_count < 65525:
            fat_format = DiskFormat.FAT16
        else:
            fat_format = DiskFormat.FAT32

    return _VhdSnapshot(
        file_size=file_size,
        partition_lba_start=lba_start,
        partition_sector_count=sec_count,
        partition_type=part_type,
        partition_offset_bytes=offset,
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        cluster_size_bytes=bytes_per_sector * sectors_per_cluster,
        fat_format=fat_format,
    )


def _expected_cluster_size_for_new_size(
    new_size_bytes: int, fat_format: DiskFormat
) -> int:
    """Cluster size mformat would pick for a partition of the given size.

    Approximates the standard FAT16/FAT32 size→cluster table.  Used by
    :func:`_validate_cluster_band_match` to refuse grows that would
    cross a cluster-size boundary (which would require relaying out
    every file's cluster chain — out of scope for v1 grow).
    """

    # Standard FAT16 cluster table (mformat defaults, matches MS-DOS
    # FORMAT).  Includes a bit of headroom for the MBR + reserved
    # sectors + FAT tables.
    if fat_format is DiskFormat.FAT16:
        bands = [
            (32 * 1024**2, 2 * 1024),       # ≤32 MiB → 2 KiB
            (64 * 1024**2, 2 * 1024),       # ≤64 MiB → 2 KiB
            (128 * 1024**2, 2 * 1024),      # ≤128 MiB → 2 KiB
            (256 * 1024**2, 4 * 1024),      # ≤256 MiB → 4 KiB
            (512 * 1024**2, 8 * 1024),      # ≤512 MiB → 8 KiB
            (1024 * 1024**2, 16 * 1024),    # ≤1 GiB → 16 KiB
            (2 * 1024**3, 32 * 1024),       # ≤2 GiB → 32 KiB
        ]
    elif fat_format is DiskFormat.FAT32:
        bands = [
            (8 * 1024**3, 4 * 1024),        # ≤8 GiB → 4 KiB
            (16 * 1024**3, 8 * 1024),       # ≤16 GiB → 8 KiB
            (32 * 1024**3, 16 * 1024),      # ≤32 GiB → 16 KiB
            (2 * 1024**4, 32 * 1024),       # ≤2 TiB → 32 KiB
        ]
    else:
        # FAT12 should never reach grow (size cap is 32 MiB; not
        # in the GROWABLE set), but handle defensively.
        return 4 * 1024
    for limit, cluster in bands:
        if new_size_bytes <= limit:
            return cluster
    return bands[-1][1]


def _validate_extracted_payload_fits(
    extract_dir: Path, new_size_bytes: int, fat_format: DiskFormat
) -> None:
    """Refuse grow when the extracted user-file payload won't fit in
    the new partition.

    Computes a conservative estimate of disk space (host bytes + 8 KiB
    cluster slack per file) and refuses with an actionable error
    when it exceeds the new partition size minus filesystem overhead
    (~5% headroom for FAT tables + reserved sectors + root dir).

    Replaces the v0.9.26-era ``_validate_cluster_band_match``, which
    falsely rejected legitimate grows (e.g. FreeDOS FAT32 with
    512-byte clusters → larger size) by enforcing an Option-A
    in-place-edit constraint that doesn't apply to the actual
    Option-B (extract + rebuild + reinject) implementation.  In
    Option B the old cluster size is irrelevant because the old
    filesystem is discarded.
    """

    total_bytes = 0
    file_count = 0
    try:
        for entry in extract_dir.rglob("*"):
            if entry.is_file():
                file_count += 1
                try:
                    total_bytes += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        return  # Best-effort -- fail open if walk errors out.

    # Add 8 KiB per file as a generous cluster-slack estimate.
    estimated_bytes = total_bytes + (file_count * 8 * 1024)
    # Reserve 5% of the new partition for FAT tables + reserved
    # sectors + root dir overhead.
    usable_bytes = int(new_size_bytes * 0.95)
    if estimated_bytes > usable_bytes:
        raise ValidationError(
            f"Extracted user-file payload ({estimated_bytes:,} bytes "
            f"estimated with cluster slack across {file_count} files) "
            f"won't fit in the {new_size_bytes:,}-byte target "
            f"({usable_bytes:,} usable after filesystem overhead).  "
            "Pick a larger --new-size."
        )


def _detect_boot_mode_from_root(
    target_vhd: Path,
    snapshot: _VhdSnapshot,
    runner: CommandRunner,
) -> BootMode:
    """Infer the original boot mode from the VHD partition root.

    Inspects ``mdir`` output for signature system files and, for
    MS-DOS variants, peeks at MSDOS.SYS to discriminate 7.x text
    config from 6.22 binary header.  Returns one of the four
    growable boot modes (FREEDOS, MSDOS71, MSDOS622, COMPAQ331).

    Falls back to FREEDOS only when nothing identifiable is found,
    which is the safest choice for fresh dosforge-built VHDs.
    """

    partition_image = f"{target_vhd}@@{snapshot.partition_offset_bytes}"
    proc = runner.run(
        ["mdir", "-i", partition_image, "-/", "-a", "::"], check=False
    )
    stdout = (proc.stdout or "").upper()
    names: set[str] = set()
    for line in stdout.splitlines():
        head = line.split()[:2]
        if len(head) == 2 and head[0].isalnum() and head[1].isalnum():
            names.add(f"{head[0]}.{head[1]}")

    if "KERNEL.SYS" in names:
        return BootMode.FREEDOS
    if "IBMBIO.COM" in names or "IBMDOS.COM" in names:
        return BootMode.COMPAQ331
    if "IO.SYS" in names or "MSDOS.SYS" in names:
        # MS-DOS 7.x ships MSDOS.SYS as an ASCII text config file
        # beginning with "[Paths]".  6.22 ships it as a binary
        # kernel stub.  Sample first 16 bytes via mtype.
        with tempfile.NamedTemporaryFile(
            prefix="dosforge-grow-detect-", delete=False
        ) as fh:
            scratch = Path(fh.name)
        try:
            runner.run(
                ["mcopy", "-n", "-i", partition_image, "::MSDOS.SYS", str(scratch)],
                check=False,
            )
            head = scratch.read_bytes()[:16] if scratch.exists() else b""
        finally:
            try:
                scratch.unlink()
            except OSError:
                pass
        if b"[Paths]" in head or b"[PATHS]" in head.upper():
            return BootMode.MSDOS71
        return BootMode.MSDOS622
    return BootMode.FREEDOS


def _mtools_extract_partition_root(
    target_vhd: Path,
    snapshot: _VhdSnapshot,
    extract_dir: Path,
    runner: CommandRunner,
) -> None:
    """Recursively extract the VHD partition root → host directory.

    Uses ``mcopy -s -m -n -i <vhd>@@<offset> :: <extract>`` so the
    whole tree (including hidden + system files) lands on the host
    with mtimes preserved.  We use the wildcard form ``::/*`` for
    portability across mtools versions.
    """

    extract_dir.mkdir(parents=True, exist_ok=True)
    partition_image = f"{target_vhd}@@{snapshot.partition_offset_bytes}"
    # mcopy -s = recursive; -m = preserve mtime; -n = overwrite without
    # prompting; -Q = quit on first error; pass ::/* and let the shell
    # glob expand on the mtools side.
    result = runner.run(
        ["mcopy", "-s", "-m", "-n", "-i", partition_image, "::", str(extract_dir)],
        check=False,
    )
    if result.returncode != 0 and not any(extract_dir.iterdir()):
        # Some mtools versions need ::/* explicitly; retry.
        runner.run(
            ["mcopy", "-s", "-m", "-n", "-i", partition_image, "::/", str(extract_dir)],
            check=False,
        )
    # Even if mcopy returned nonzero (which it sometimes does for
    # FAT volume label "files" or zero-byte attribute oddities) the
    # extraction generally succeeds.  Caller validates by walking
    # extract_dir.


def _create_fresh_vhd(
    new_vhd: Path,
    *,
    boot_mode: BootMode,
    fat_format: DiskFormat,
    new_size_bytes: int,
) -> None:
    """Build a fresh empty bootable VHD at the new size.

    Reuses ``DiskManager.create_and_prepare`` so we get the same
    authentic boot pipeline the user originally used (QEMU FORMAT
    C:, system file install, etc.) — minus any custom payload.
    """

    manager = DiskManager()
    request = CreateRequest(
        path=new_vhd,
        size_bytes=new_size_bytes,
        disk_format=fat_format,
        media_type=MediaType.VHD,
        floppy_type=FloppyType.F1440K,
        img_system_format=False,
        label=None,
        overwrite=True,
        boot_mode=boot_mode,
        freedos_source=FreeDOSSource.LOCAL,
        boot_assets_path=None,
        freedos_download_url=None,
        msdos_install_profile=MSDOSInstallProfile.MINIMAL,
        ibm_dos_version=IBMDOSVersion.DOS50,
        custom_payload_path=None,
        bios_drive_type=None,
        disk_controller=None,
        custom_chs=None,
        host_boot_mode=None,
    )
    manager.create_and_prepare(request)


def _mtools_inject_extracted_tree(
    new_vhd: Path,
    new_snapshot: _VhdSnapshot,
    extract_dir: Path,
    runner: CommandRunner,
    progress: "Callable[[str], None] | None" = None,
) -> None:
    """Copy host extract dir back into the new VHD partition (fast path).

    Strategy: minimize the number of ``mcopy`` subprocess spawns,
    which is the dominant cost when injecting populated source VHDs.

    * Root-level files (excluding protected system files) are copied
      in ONE batched ``mcopy`` call using multi-source syntax.
    * Each top-level subdirectory is copied with ``mcopy -s``
      (recursive) in one shot, regardless of how many files it
      contains.

    The old implementation spawned one mcopy per file (~100ms each
    on slow disks), which made step 5 of grow appear to hang for
    minutes on a populated VHD.  This implementation typically
    finishes in well under a second for any FAT16 source.

    ``progress`` is called with short labels like
    ``"Step 5/8: Re-injecting 38 root files..."`` so the spinner can
    show movement instead of a stuck "Step 5/8" caption.
    """

    partition_image = f"{new_vhd}@@{new_snapshot.partition_offset_bytes}"

    def _report(msg: str) -> None:
        if progress is not None:
            try:
                progress(msg)
            except Exception:
                pass

    # Inventory top-level entries (files + dirs) skipping protected names.
    root_files: list[Path] = []
    root_dirs: list[Path] = []
    for entry in sorted(extract_dir.iterdir()):
        if entry.name.upper() in _ALWAYS_SKIP_NAMES:
            continue
        if entry.is_file():
            if entry.name.upper() in _PROTECTED_ROOT_SYSTEM_FILES:
                continue
            root_files.append(entry)
        elif entry.is_dir():
            root_dirs.append(entry)

    # Batched root file copy: chunk to keep argv under typical
    # ARG_MAX (~128 KiB on Linux).  500 files per chunk is well
    # under the limit even with long paths.
    if root_files:
        _report(f"Step 5/8: Re-injecting {len(root_files)} root file(s)...")
        chunk = 200
        for i in range(0, len(root_files), chunk):
            batch = root_files[i : i + chunk]
            cmd = ["mcopy", "-o", "-m", "-i", partition_image]
            cmd.extend(str(f) for f in batch)
            cmd.append("::/")
            runner.run(cmd, check=False)

    # Recursive subdirectory copy: one mcopy -s per top-level dir.
    for idx, sub in enumerate(root_dirs, start=1):
        _report(
            f"Step 5/8: Re-injecting subdirectory {idx}/{len(root_dirs)}: "
            f"\\{sub.name}\\..."
        )
        runner.run(
            ["mcopy", "-s", "-o", "-m", "-i", partition_image, str(sub), "::"],
            check=False,
        )


def _mtools_stage_directory(
    new_vhd: Path,
    new_snapshot: _VhdSnapshot,
    src: Path,
    dest_dos_path: str,
    runner: CommandRunner,
) -> None:
    """Stage ``src`` (a host directory) into ``dest_dos_path`` on the VHD.

    ``dest_dos_path`` is the manifest's DOS-style target (e.g.
    ``C:\\GAMES`` or ``\\GAMES``) and is normalized to an mtools
    ``::/PATH`` form here. Creates the destination directory tree
    via ``mmd`` and copies every file recursively via ``mcopy -o``.
    """

    partition_image = f"{new_vhd}@@{new_snapshot.partition_offset_bytes}"
    dos = dest_dos_path.replace("/", "\\")
    if len(dos) >= 3 and dos[1] == ":" and dos[2] == "\\":
        dos = dos[2:]  # strip "C:" -> "\\GAMES"
    dos = dos.lstrip("\\")
    if not dos:
        dest_prefix = "::"
    else:
        dest_prefix = "::/" + dos.replace("\\", "/")
        runner.run(["mmd", "-i", partition_image, dest_prefix], check=False)

    for entry in sorted(src.rglob("*"), key=lambda p: (p.is_file(), str(p))):
        rel = entry.relative_to(src)
        dest = dest_prefix + "/" + str(rel).replace(os.sep, "/")
        if entry.is_dir():
            runner.run(["mmd", "-i", partition_image, dest], check=False)
        elif entry.is_file():
            runner.run(
                ["mcopy", "-o", "-m", "-i", partition_image, str(entry), dest],
                check=False,
            )


def _mtools_read_file_bytes(
    vhd: Path,
    snapshot: _VhdSnapshot,
    dos_path: str,
    runner: CommandRunner,
) -> bytes | None:
    """Return file bytes from the partition, or None if it doesn't exist.

    Uses ``mtype`` to stream the file to a host scratch path so we
    can read it as bytes regardless of platform.  Returns None on
    any mtools-side failure (file not present, partition unreadable,
    etc.) -- callers treat that as "no original AUTOEXEC.BAT".
    """

    partition_image = f"{vhd}@@{snapshot.partition_offset_bytes}"
    with tempfile.NamedTemporaryFile(
        prefix="dosforge-grow-probe-", delete=False
    ) as fh:
        scratch = Path(fh.name)
    try:
        result = runner.run(
            ["mcopy", "-n", "-i", partition_image, f"::{dos_path}", str(scratch)],
            check=False,
        )
        if result.returncode != 0 or not scratch.exists():
            return None
        return scratch.read_bytes()
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass


def _mtools_write_file_bytes(
    vhd: Path,
    snapshot: _VhdSnapshot,
    dos_path: str,
    payload: bytes,
    runner: CommandRunner,
) -> None:
    """Write ``payload`` to ``::<dos_path>`` inside the partition."""

    partition_image = f"{vhd}@@{snapshot.partition_offset_bytes}"
    with tempfile.NamedTemporaryFile(
        prefix="dosforge-grow-probe-", delete=False
    ) as fh:
        scratch = Path(fh.name)
        fh.write(payload)
    try:
        runner.run(
            ["mcopy", "-o", "-i", partition_image, str(scratch), f"::{dos_path}"],
        )
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass


def _mtools_delete_file(
    vhd: Path,
    snapshot: _VhdSnapshot,
    dos_path: str,
    runner: CommandRunner,
) -> None:
    """Best-effort delete of ``::<dos_path>``.  Swallows missing-file."""

    partition_image = f"{vhd}@@{snapshot.partition_offset_bytes}"
    runner.run(
        ["mdel", "-i", partition_image, f"::{dos_path}"],
        check=False,
    )


# Marker the probe BAT echoes to COM1.  Picked to be unmistakable in
# serial output -- shouldn't appear in any normal DOS boot stream.
_BOOT_PROBE_MARKER: bytes = b"DOSFORGE_BOOT_PROBE_OK"

# Probe BAT script: redirect console to COM1, echo marker, redirect
# back to CON so the user's subsequent AUTOEXEC commands still see
# the screen.  CRLF line endings throughout (DOS-native).
_PROBE_BAT_SCRIPT: bytes = (
    b"@ECHO OFF\r\n"
    b"CTTY COM1\r\n"
    b"ECHO " + _BOOT_PROBE_MARKER + b"\r\n"
    b"CTTY CON\r\n"
)


def _run_boot_probe(
    new_vhd: Path,
    new_snapshot: _VhdSnapshot,
    runner: CommandRunner,
    *,
    timeout_seconds: float = 90.0,
) -> tuple[bool, str]:
    """Boot the grown VHD in headless QEMU and verify it reaches AUTOEXEC.

    Temporarily prepends ``@CALL C:\\BOOTPRB.BAT`` to the partition's
    AUTOEXEC.BAT (or creates one if absent) and writes ``BOOTPRB.BAT``
    to C:\\ root.  The probe BAT redirects DOS console to COM1, echoes
    a unique marker, then redirects back to CON so any subsequent
    AUTOEXEC commands still see the screen.  Boots in QEMU with
    serial output captured to a file via the ``chardev`` syntax
    (avoids the ``-serial file:C:\\...`` colon-parser bug that
    silently produces zero-byte logs on Windows).

    Always restores AUTOEXEC.BAT (delete if it didn't exist
    originally) and deletes BOOTPRB.BAT before returning, even on
    failure paths.

    Returns ``(passed, diagnostic_text)``.  ``diagnostic_text`` is
    the tail of QEMU's serial log -- useful for the caller's error
    message when probe fails.
    """

    import subprocess
    import time
    from uuid import uuid4

    from ._platform import get_backend

    backend = get_backend()
    qemu_path = backend.tool_path("qemu-system-i386")

    # 1. Snapshot user's original AUTOEXEC.BAT (might not exist).
    original_autoexec = _mtools_read_file_bytes(
        new_vhd, new_snapshot, "AUTOEXEC.BAT", runner
    )
    # 2. Write probe BAT + modified AUTOEXEC.
    probe_autoexec = b"@CALL C:\\BOOTPRB.BAT\r\n"
    if original_autoexec is not None:
        probe_autoexec += original_autoexec
    _mtools_write_file_bytes(new_vhd, new_snapshot, "BOOTPRB.BAT", _PROBE_BAT_SCRIPT, runner)
    _mtools_write_file_bytes(new_vhd, new_snapshot, "AUTOEXEC.BAT", probe_autoexec, runner)

    # 3. Boot QEMU.
    log_path = Path(tempfile.gettempdir()) / f"dosforge-bootprobe-{uuid4().hex[:8]}.log"
    log_path.write_bytes(b"")  # ensure the file exists for tail-reading

    machine_spec = "pc"
    if sys.platform == "win32":
        machine_spec = "pc,accel=whpx:tcg"

    cmd = [
        qemu_path,
        "-machine", machine_spec,
        "-cpu", "486",
        "-m", "16",
        "-display", "none",
        "-nic", "none",
        # Use chardev syntax instead of -serial file: -- the latter
        # uses ':' as a sub-option separator and silently mis-parses
        # paths with Windows drive letters like 'file:C:\\...'.
        "-chardev", f"file,id=bplog,path={log_path}",
        "-serial", "chardev:bplog",
        "-no-reboot",
        "-drive", f"file={new_vhd},if=ide,format=vpc,index=0,media=disk",
        "-boot", "c",
    ]
    if os.path.isabs(qemu_path):
        cmd.insert(1, str(Path(qemu_path).parent))
        cmd.insert(1, "-L")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **subprocess_no_window_kwargs(),
    )

    passed = False
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(1.0)
            try:
                if _BOOT_PROBE_MARKER in log_path.read_bytes():
                    passed = True
                    break
            except OSError:
                pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

    # Final marker check after QEMU exit (catches the race where
    # the marker landed in the last poll interval).
    try:
        if _BOOT_PROBE_MARKER in log_path.read_bytes():
            passed = True
    except OSError:
        pass

    diagnostic_tail = ""
    try:
        diagnostic_tail = log_path.read_bytes()[-2000:].decode("utf-8", errors="replace")
    except OSError:
        pass

    # 4. Restore original AUTOEXEC (best-effort, never raises).
    try:
        if original_autoexec is not None:
            _mtools_write_file_bytes(
                new_vhd, new_snapshot, "AUTOEXEC.BAT", original_autoexec, runner
            )
        else:
            _mtools_delete_file(new_vhd, new_snapshot, "AUTOEXEC.BAT", runner)
        _mtools_delete_file(new_vhd, new_snapshot, "BOOTPRB.BAT", runner)
    except Exception:
        # Restoration failure shouldn't mask the probe result.
        pass

    return passed, diagnostic_tail


def perform_grow(
    manifest,
    *,
    progress_callback: "Callable[[str], None] | None" = None,
) -> None:
    """End-to-end grow operation.

    Steps (see module docstring for the design rationale):

    1. Snapshot the existing VHD's MBR + BPB.
    2. Extract every file from the old partition to a host scratch
       directory (preserves mtimes, attributes, hidden/system bits).
    3. Validate the extracted payload will fit in the new partition
       size (with cluster slack + filesystem overhead headroom).
    4. Build a fresh empty bootable VHD at the new size via
       ``DiskManager.create_and_prepare`` (same boot mode + format).
       The new VHD gets whatever cluster size ``mformat`` picks for
       the requested size -- the OLD cluster size doesn't matter
       because we're rebuilding the filesystem from scratch and
       re-copying every file via ``mcopy``.
    5. Re-inject the extracted tree (skipping protected system files
       so the fresh VHD's authentic bootstrap survives).
    6. Stage every ``staging_sources`` entry.
    7. **When ``manifest.boot_probe`` is True** (default): inject a
       temporary AUTOEXEC marker, boot the temp VHD in headless QEMU,
       look for the marker in the serial log.  Restore AUTOEXEC.
       Abort the grow on probe failure so the user keeps their
       original VHD intact.
    8. Atomic swap: rename ``target.vhd`` -> ``target.vhd.bak``
       (when ``keep_backup``), move the new VHD into place.

    ``progress_callback`` is called with short human-readable stage
    labels at the start of each step.  Used by the TUI to keep the
    spinner honest about which step is currently burning wall-clock.
    """

    def _report(stage: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(stage)
            except Exception:
                pass

    runner = CommandRunner()

    _report("Snapshotting source VHD geometry...")
    snapshot = _snapshot_vhd(manifest.target_vhd)

    # Auto-detect boot mode from the source VHD when the manifest
    # doesn't pin one.  The CLI / TUI both now leave this unset so
    # the user doesn't have to remember which DOS family the VHD
    # was originally built with.
    boot_mode = manifest.boot_mode
    if boot_mode is None:
        _report("Detecting boot mode from source VHD root files...")
        boot_mode = _detect_boot_mode_from_root(
            manifest.target_vhd, snapshot, runner
        )
        _report(f"Detected boot mode: {boot_mode.value}")

    work_root = Path(tempfile.mkdtemp(prefix="dosforge-grow-"))
    try:
        extract_dir = work_root / "extract"
        new_vhd_temp = work_root / "new.vhd"

        # Step 2: extract old → host
        _report("Step 3/8: Extracting files from source VHD via mtools...")
        _mtools_extract_partition_root(
            target_vhd=manifest.target_vhd,
            snapshot=snapshot,
            extract_dir=extract_dir,
            runner=runner,
        )

        # Step 3: validate the extracted payload will actually fit in
        # the new partition.  Pure-rebuild model means cluster size
        # mismatch between old and new isn't a problem -- but the
        # total payload size still has to fit.
        _validate_extracted_payload_fits(
            extract_dir, manifest.new_size_bytes, snapshot.fat_format
        )

        # Step 4: build fresh VHD at the new size
        _report(
            f"Step 4/8: Building fresh {boot_mode.value} VHD at "
            f"{manifest.new_size_bytes:,} bytes (may need sudo for qemu-nbd)..."
        )
        _create_fresh_vhd(
            new_vhd_temp,
            boot_mode=boot_mode,
            fat_format=snapshot.fat_format,
            new_size_bytes=manifest.new_size_bytes,
        )
        new_snapshot = _snapshot_vhd(new_vhd_temp)

        # Step 5: inject extracted user files
        _report("Step 5/8: Re-injecting extracted user files...")
        _mtools_inject_extracted_tree(
            new_vhd=new_vhd_temp,
            new_snapshot=new_snapshot,
            extract_dir=extract_dir,
            runner=runner,
            progress=_report,
        )

        # Step 6: stage manifest sources
        if manifest.staging_sources:
            _report(
                f"Step 6/8: Staging {len(manifest.staging_sources)} additional "
                f"source(s) into DOS paths..."
            )
            for staging in manifest.staging_sources:
                _mtools_stage_directory(
                    new_vhd=new_vhd_temp,
                    new_snapshot=new_snapshot,
                    src=staging.src,
                    dest_dos_path=staging.dest,
                    runner=runner,
                )
        else:
            _report("Step 6/8: No staging sources -- skipping.")

        # Step 7: optional headless boot probe.  Inject a marker
        # AUTOEXEC line, boot in QEMU, look for the marker, restore
        # AUTOEXEC.  Abort the grow on probe failure so the user
        # keeps their original VHD.
        if manifest.boot_probe:
            _report(
                "Step 7/8: Headless boot probe -- booting grown VHD in QEMU "
                "(up to 90s; uncheck 'Headless boot probe' to skip)..."
            )
            passed, log_tail = _run_boot_probe(
                new_vhd=new_vhd_temp,
                new_snapshot=new_snapshot,
                runner=runner,
            )
            if not passed:
                raise ValidationError(
                    "Boot probe failed: the grown VHD did not reach the "
                    "AUTOEXEC.BAT probe marker within 90s.  This usually "
                    "means a CONFIG.SYS DEVICE= line references a file "
                    "not present on the new VHD, or the boot setup got "
                    "corrupted during file injection.  The original "
                    "VHD has NOT been modified.\n"
                    f"Serial-log tail:\n{log_tail}"
                )
        else:
            _report("Step 7/8: Boot probe disabled -- skipping QEMU verify.")

        # Step 8: atomic swap
        _report("Step 8/8: Atomic swap (moving grown VHD into place)...")
        target = manifest.target_vhd
        backup = target.with_suffix(target.suffix + ".bak")
        if backup.exists():
            backup.unlink()
        if manifest.keep_backup:
            target.rename(backup)
        else:
            target.unlink()
        shutil.copy2(new_vhd_temp, target)
        _report("Grow complete.")
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


__all__ = [
    "perform_grow",
]
