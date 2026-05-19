"""Windows CLI matrix test.

This test exercises the full ``dosforge`` CLI surface as a subprocess
on Windows, covering every supported combination of media type, FAT
format, machine target, and boot mode. For each case it asserts the
exit code, looks for specific substrings in stdout/stderr, and where
applicable validates the produced artifact (file size, MBR/VBR
signatures, mtools-visible contents).

Why subprocess and not in-process? The CLI's argparse + error
formatting is part of what we're testing — a clean error path is
defined by what reaches stderr with a non-zero exit, not by which
exception happened to bubble up.

Conventions in this file:
* ``run_cli(args)`` returns a small ``CliResult`` namedtuple.
* Every test uses its own ``tmp_path`` and never touches files
  outside it (besides reading the bundled FreeDOS asset tree).
* Tests are organized into eight groups, in priority order:
    1. Plumbing verbs (check-deps, list-mounts, etc.)
    2. Non-bootable IMG floppies (all 8 sizes)
    3. Non-bootable VHDs (FAT16/FAT32 across sizes)
    4. VHD custom-payload copy
    5. Machine-target VHDs (MartyPC Xebec / XT-IDE)
    6. Bootable FreeDOS FAT16 VHD (CLI artifacts + optional QEMU
       boot probe)
    7. Bootable FreeDOS FAT12 floppy (CLI artifacts only — full
       boot blocked by a separate pre-existing CONFIG.SYS gap)
    8. Negative cases (unsupported boot-modes raise clean
       ValidationError).
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows CLI matrix test runs only on Windows.",
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FREEDOS_ASSETS = REPO_ROOT / "dosassets" / "freedos"
VENDOR_BIN = REPO_ROOT / "vendor" / "windows" / "bin"


# --------------------------------------------------------------------------
# Subprocess helpers
# --------------------------------------------------------------------------


@dataclass
class CliResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return (
            f"CliResult(args={self.args!r}, returncode={self.returncode}, "
            f"stdout={self.stdout!r}, stderr={self.stderr!r})"
        )


def run_cli(*args: str, cwd: Path | None = None, timeout: float = 180.0) -> CliResult:
    """Run ``python -m dosforge <args>`` and capture stdout/stderr/exit."""

    cmd = [sys.executable, "-m", "dosforge", *args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return CliResult(
        args=tuple(args),
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def assert_success(result: CliResult) -> None:
    if result.returncode != 0:
        pytest.fail(
            f"CLI exited with {result.returncode} for args={result.args}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def assert_clean_error(result: CliResult, *, contains: str) -> None:
    """Assert non-zero exit + ``contains`` appears in stderr without a Python traceback."""

    if result.returncode == 0:
        pytest.fail(
            f"Expected non-zero exit for args={result.args}, got 0\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    if "Traceback (most recent call last)" in result.stderr:
        pytest.fail(
            f"Python traceback leaked through stderr for args={result.args}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    if contains.lower() not in (result.stdout + result.stderr).lower():
        pytest.fail(
            f"Expected error containing {contains!r} for args={result.args}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


# --------------------------------------------------------------------------
# Disk-image inspection helpers (pure-Python, no mtools needed)
# --------------------------------------------------------------------------


def read_mbr(path: Path) -> bytes:
    with path.open("rb") as fh:
        return fh.read(512)


def read_partition_sector(path: Path, partition_offset_bytes: int) -> bytes:
    with path.open("rb") as fh:
        fh.seek(partition_offset_bytes)
        return fh.read(512)


def read_vhd_footer(path: Path) -> bytes:
    """Return the trailing 512-byte VHD footer."""

    with path.open("rb") as fh:
        fh.seek(-512, os.SEEK_END)
        return fh.read(512)


def parse_partition_entry(mbr: bytes, slot: int = 0) -> dict:
    """Return a dict describing partition entry ``slot`` from an MBR sector."""

    offset = 446 + 16 * slot
    entry = mbr[offset : offset + 16]
    return {
        "bootable": entry[0],
        "partition_type": entry[4],
        "first_lba": struct.unpack("<I", entry[8:12])[0],
        "sector_count": struct.unpack("<I", entry[12:16])[0],
    }


def parse_fat_bpb(sector: bytes) -> dict:
    return {
        "oem_id": sector[3:11].decode("ascii", errors="replace"),
        "bytes_per_sector": struct.unpack("<H", sector[11:13])[0],
        "sectors_per_cluster": sector[13],
        "reserved_sectors": struct.unpack("<H", sector[14:16])[0],
        "fat_count": sector[16],
        "root_entries": struct.unpack("<H", sector[17:19])[0],
        "total_sectors_16": struct.unpack("<H", sector[19:21])[0],
        "media_descriptor": sector[21],
        "sectors_per_fat": struct.unpack("<H", sector[22:24])[0],
        "sectors_per_track": struct.unpack("<H", sector[24:26])[0],
        "heads": struct.unpack("<H", sector[26:28])[0],
        "fs_type": sector[54:62].decode("ascii", errors="replace"),
        "boot_signature": sector[510:512].hex(),
    }


# --------------------------------------------------------------------------
# 1. Plumbing verbs
# --------------------------------------------------------------------------


class TestPlumbingVerbs:
    def test_check_deps_default(self):
        result = run_cli("check-deps")
        assert_success(result)
        assert "All required dependencies are available." in result.stdout

    def test_check_deps_img(self):
        result = run_cli("check-deps", "--media-type", "img")
        assert_success(result)
        assert "All required dependencies are available." in result.stdout

    def test_list_mounts(self):
        result = run_cli("list-mounts")
        assert_success(result)

    def test_list_martypc_formats(self):
        result = run_cli("list-martypc-formats")
        assert_success(result)
        # The table should advertise the standard 504 MiB cap entry.
        assert "at-1024-16-63" in result.stdout
        # We expect 127 entries; count slug-shaped lines.
        slug_lines = re.findall(r"^\s*at-\d+-\d+-\d+", result.stdout, flags=re.MULTILINE)
        assert len(slug_lines) == 127, f"Expected 127 AT slugs, got {len(slug_lines)}"

    def test_list_bios_drive_types(self):
        result = run_cli("list-bios-drive-types")
        assert_success(result)
        # Both vendor sections should appear.
        lowered = result.stdout.lower()
        assert "phoenix" in lowered
        assert "ami" in lowered

    def test_sudo_check_clean_on_windows(self):
        """sudo-check should report cleanly on Windows (no-op backend)."""

        result = run_cli("sudo-check")
        # We don't assert the exact summary text since it's free-form,
        # but it must not raise a traceback and must exit 0 (since
        # Windows is the no-sudo path).
        assert result.returncode == 0, (
            f"sudo-check expected exit 0 on Windows, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "Traceback" not in result.stderr


# --------------------------------------------------------------------------
# 2. Non-bootable IMG floppies (every supported size)
# --------------------------------------------------------------------------


FLOPPY_SIZES = [
    # (cli_floppy_type, expected_size_bytes, expected_media, expected_spt, expected_heads)
    ("160k", 163_840, 0xFE, 8, 1),
    ("180k", 184_320, 0xFC, 9, 1),
    ("360k", 368_640, 0xFD, 9, 2),
    ("720k", 737_280, 0xF9, 9, 2),
    ("1200k", 1_228_800, 0xF9, 15, 2),
    ("1440k", 1_474_560, 0xF0, 18, 2),
    ("1840k", 1_884_160, 0xF0, 23, 2),
    ("2880k", 2_949_120, 0xF0, 36, 2),
]


class TestNonBootableFloppyImg:
    @pytest.mark.parametrize(
        "floppy_type,expected_size,expected_media,expected_spt,expected_heads",
        FLOPPY_SIZES,
        ids=[s[0] for s in FLOPPY_SIZES],
    )
    def test_create_non_bootable_img(
        self,
        tmp_path: Path,
        floppy_type: str,
        expected_size: int,
        expected_media: int,
        expected_spt: int,
        expected_heads: int,
    ):
        img = tmp_path / f"blank-{floppy_type}.img"
        result = run_cli(
            "create",
            "--media-type", "img",
            "--floppy-type", floppy_type,
            "--path", str(img),
        )
        assert_success(result)
        assert img.exists(), "IMG file was not produced"
        assert img.stat().st_size == expected_size, (
            f"Expected {expected_size} bytes for {floppy_type}, got {img.stat().st_size}"
        )
        bpb = parse_fat_bpb(read_mbr(img))
        assert bpb["boot_signature"] == "55aa", (
            f"Boot signature missing for {floppy_type}: {bpb!r}"
        )
        assert bpb["fs_type"].startswith("FAT12"), (
            f"FS type should be FAT12 for {floppy_type}, got {bpb['fs_type']!r}"
        )
        assert bpb["media_descriptor"] == expected_media, (
            f"Media byte mismatch for {floppy_type}: "
            f"expected 0x{expected_media:02x}, got 0x{bpb['media_descriptor']:02x}"
        )
        assert bpb["sectors_per_track"] == expected_spt
        assert bpb["heads"] == expected_heads
        assert bpb["bytes_per_sector"] == 512


# --------------------------------------------------------------------------
# 3. Non-bootable VHDs (FAT16 + FAT32, various sizes)
# --------------------------------------------------------------------------


class TestNonBootableVhd:
    @pytest.mark.parametrize(
        "size_arg,disk_format,expected_partition_type",
        [
            ("16M", "fat16", 0x06),
            ("32M", "fat16", 0x06),
            ("64M", "fat16", 0x06),
            ("128M", "fat32", 0x0C),
            ("256M", "fat32", 0x0C),
        ],
    )
    def test_create_non_bootable_vhd(
        self,
        tmp_path: Path,
        size_arg: str,
        disk_format: str,
        expected_partition_type: int,
    ):
        vhd = tmp_path / f"blank-{disk_format}-{size_arg}.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", disk_format,
            "--size", size_arg,
            "--path", str(vhd),
        )
        assert_success(result)
        assert vhd.exists(), "VHD file was not produced"

        mbr = read_mbr(vhd)
        assert mbr[510:512] == b"\x55\xaa", "MBR boot signature missing"

        entry = parse_partition_entry(mbr, slot=0)
        assert entry["bootable"] == 0x80, "Partition should have active flag set"
        assert entry["partition_type"] == expected_partition_type, (
            f"Partition type mismatch: expected 0x{expected_partition_type:02x}, "
            f"got 0x{entry['partition_type']:02x}"
        )
        assert entry["first_lba"] == 2048, "Partition should start at LBA 2048"
        # sector_count should match (file_size - footer - 2048*512) / 512.
        expected_sectors = (vhd.stat().st_size - 512) // 512 - 2048
        assert entry["sector_count"] == expected_sectors, (
            f"Partition sector count mismatch: expected {expected_sectors}, "
            f"got {entry['sector_count']}"
        )

        footer = read_vhd_footer(vhd)
        assert footer[:8] == b"conectix", "VHD footer cookie missing"


# --------------------------------------------------------------------------
# 4. VHD with custom payload
# --------------------------------------------------------------------------


class TestVhdCustomPayload:
    def test_custom_payload_files_appear_on_disk(self, tmp_path: Path):
        payload = tmp_path / "payload"
        (payload / "TOOLS").mkdir(parents=True)
        (payload / "README.TXT").write_text("hello dosforge\n", encoding="ascii")
        (payload / "TOOLS" / "HELLO.BAT").write_text("@ECHO OFF\n", encoding="ascii")

        vhd = tmp_path / "payload.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--size", "32M",
            "--path", str(vhd),
            "--custom-payload-path", str(payload),
        )
        assert_success(result)

        # mdir against partition @@offset=1048576 should list the
        # payload files. We use the bundled mtools.exe.
        mdir = VENDOR_BIN / "mdir.exe"
        if not mdir.is_file():
            pytest.skip("vendor/windows/bin/mdir.exe missing — run fetch script first")

        proc = subprocess.run(
            [str(mdir), "-i", f"{vhd}@@1048576", "::"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            f"mdir failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        # mdir uses "8.3" column formatting: "README   TXT", "TOOLS        <DIR>".
        normalized = proc.stdout.upper().replace(" ", "").replace("\r", "")
        assert "READMETXT" in normalized, f"Expected README.TXT in root, got:\n{proc.stdout}"
        assert "TOOLS" in proc.stdout.upper(), f"Expected TOOLS dir in root, got:\n{proc.stdout}"


# --------------------------------------------------------------------------
# 5. Machine-target VHDs
# --------------------------------------------------------------------------


class TestMachineTargets:
    @pytest.mark.parametrize(
        "drive_type,expected_cyl,expected_heads,expected_spt",
        [
            ("type16", 612, 4, 17),
            ("type2", 615, 4, 17),
            ("type13", 306, 8, 17),
        ],
    )
    def test_martypc_xebec_geometry_locks_footer(
        self,
        tmp_path: Path,
        drive_type: str,
        expected_cyl: int,
        expected_heads: int,
        expected_spt: int,
    ):
        vhd = tmp_path / f"xebec-{drive_type}.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--machine-target", "martypc-xebec",
            "--martypc-xebec-drive-type", drive_type,
            "--path", str(vhd),
        )
        assert_success(result)
        footer = read_vhd_footer(vhd)
        cyl = struct.unpack(">H", footer[56:58])[0]
        heads = footer[58]
        spt = footer[59]
        assert (cyl, heads, spt) == (expected_cyl, expected_heads, expected_spt), (
            f"Footer CHS mismatch for {drive_type}: "
            f"expected {(expected_cyl, expected_heads, expected_spt)}, got {(cyl, heads, spt)}"
        )

    def test_martypc_xtide_504mib_standard(self, tmp_path: Path):
        vhd = tmp_path / "xtide-504m.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--machine-target", "martypc-xtide",
            "--martypc-at-drive-type", "at-1024-16-63",
            "--path", str(vhd),
        )
        assert_success(result)
        footer = read_vhd_footer(vhd)
        cyl = struct.unpack(">H", footer[56:58])[0]
        heads = footer[58]
        spt = footer[59]
        assert (cyl, heads, spt) == (1024, 16, 63), (
            f"504MiB XT-IDE footer CHS expected (1024,16,63), got {(cyl, heads, spt)}"
        )
        # Total data area should be exactly cyl*heads*spt*512.
        expected_total = 1024 * 16 * 63 * 512
        actual_data = vhd.stat().st_size - 512  # minus footer
        assert actual_data == expected_total, (
            f"Data area size mismatch: expected {expected_total}, got {actual_data}"
        )


# --------------------------------------------------------------------------
# 6. Bootable FreeDOS FAT16 VHD
# --------------------------------------------------------------------------


class TestBootableFreedosVhd:
    def test_create_bootable_freedos_fat16_vhd(self, tmp_path: Path):
        if not FREEDOS_ASSETS.is_dir():
            pytest.skip("dosassets/freedos not present in this checkout")

        vhd = tmp_path / "freedos.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--size", "64M",
            "--path", str(vhd),
            "--boot-mode", "freedos",
            "--freedos-source", "local",
            "--boot-assets-path", str(FREEDOS_ASSETS),
        )
        assert_success(result)

        mbr = read_mbr(vhd)
        assert mbr[510:512] == b"\x55\xaa"

        # MBR boot code (bytes 0..439) should be substantial.
        non_zero = sum(1 for b in mbr[:440] if b != 0)
        assert non_zero >= 200, (
            f"MBR boot code looks empty: {non_zero} non-zero bytes in 0..439"
        )

        # VBR (partition sector at LBA 2048) should have FreeDOS markers.
        vbr = read_partition_sector(vhd, 1048576)
        assert vbr[510:512] == b"\x55\xaa", "VBR boot signature missing"
        assert b"FAT16" in vbr[54:62], "VBR FAT16 label missing"
        vbr_code_non_zero = sum(1 for b in vbr[62:510] if b != 0)
        assert vbr_code_non_zero >= 200, (
            f"VBR boot code looks empty: {vbr_code_non_zero} non-zero bytes"
        )

        # Verify staged files via mdir.
        mdir = VENDOR_BIN / "mdir.exe"
        if not mdir.is_file():
            pytest.skip("vendor/windows/bin/mdir.exe missing")
        proc = subprocess.run(
            [str(mdir), "-i", f"{vhd}@@1048576", "-a", "::"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"mdir failed: {proc.stderr}"
        normalized = proc.stdout.upper().replace(" ", "")
        assert "KERNELSYS" in normalized, "KERNEL.SYS not staged on FreeDOS VHD"
        assert "COMMANDCOM" in normalized, "COMMAND.COM not staged on FreeDOS VHD"
        assert "FDOS" in proc.stdout.upper(), "FDOS dir not staged on FreeDOS VHD"

    @pytest.mark.skipif(
        not (VENDOR_BIN / "qemu-system-i386.exe").is_file()
        or not (VENDOR_BIN / "bios-256k.bin").is_file(),
        reason="QEMU + BIOS firmware not present in vendor/windows/bin",
    )
    def test_freedos_fat16_vhd_actually_boots(self, tmp_path: Path):
        """Boot the FreeDOS VHD in QEMU and assert C:\\> reaches VGA."""

        if not FREEDOS_ASSETS.is_dir():
            pytest.skip("dosassets/freedos not present")
        vhd = tmp_path / "freedos-boot.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--size", "64M",
            "--path", str(vhd),
            "--boot-mode", "freedos",
            "--freedos-source", "local",
            "--boot-assets-path", str(FREEDOS_ASSETS),
        )
        assert_success(result)

        ppm_path = tmp_path / "screen.ppm"
        b8_path = tmp_path / "b8.bin"
        qemu = VENDOR_BIN / "qemu-system-i386.exe"
        port = 4500 + (os.getpid() % 100)
        proc = subprocess.Popen(
            [
                str(qemu),
                "-L", str(VENDOR_BIN),
                "-drive", f"file={vhd},format=vpc,if=ide",
                "-m", "64M",
                "-nic", "none",
                "-display", "none",
                "-qmp", f"tcp:127.0.0.1:{port},server=on,wait=off",
                "-no-reboot",
                "-boot", "c",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Give the BIOS + MBR + VBR + KERNEL.SYS + COMMAND.COM enough
            # time to reach the C:\> prompt.
            time.sleep(6)
            _qmp_screendump_text(port, b8_path)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        if not b8_path.is_file():
            pytest.fail("Failed to capture VGA text buffer from QEMU via QMP")
        text = _decode_vga_text(b8_path.read_bytes())
        assert "C:\\>" in text, (
            f"Expected FreeDOS prompt 'C:\\>' in VGA text buffer, got:\n{text}"
        )


def _qmp_screendump_text(port: int, b8_path: Path) -> None:
    import json
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect(("127.0.0.1", port))
    file_obj = sock.makefile("rwb", buffering=0)
    # Read greeting line.
    file_obj.readline()

    def cmd(payload: dict) -> None:
        file_obj.write((json.dumps(payload) + "\n").encode())
        file_obj.readline()

    cmd({"execute": "qmp_capabilities"})
    cmd(
        {
            "execute": "human-monitor-command",
            "arguments": {
                "command-line": f"memsave 0xb8000 4000 {b8_path.as_posix()}",
            },
        }
    )
    cmd({"execute": "quit"})
    sock.close()


def _decode_vga_text(buf: bytes) -> str:
    """Decode an 80x25 VGA text-mode memory dump into ASCII."""

    lines = []
    for row in range(25):
        chars = []
        for col in range(80):
            idx = (row * 80 + col) * 2
            if idx >= len(buf):
                break
            byte = buf[idx]
            if 0x20 <= byte < 0x7F:
                chars.append(chr(byte))
            else:
                chars.append(" ")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 7. Bootable FreeDOS FAT12 floppy
# --------------------------------------------------------------------------


class TestBootableFreedosFloppy:
    def test_create_bootable_freedos_floppy(self, tmp_path: Path):
        """Confirm boot sector + KERNEL.SYS staging; full boot is blocked
        by a separate pre-existing CONFIG.SYS gap (C: drive reference on
        a floppy boot) so we don't probe to a prompt here."""

        if not FREEDOS_ASSETS.is_dir():
            pytest.skip("dosassets/freedos not present")

        # FreeDOS FDOS/BIN/ tree is bigger than 1.44M (CURL.EXE alone is
        # 1.27 MB). Build a stripped-down assets dir without FDOS/ to
        # exercise the boot-sector + system-files staging without the
        # FAT-full overflow.
        stripped = tmp_path / "freedos-no-fdos"
        for entry in FREEDOS_ASSETS.iterdir():
            if entry.name.upper() == "FDOS":
                continue
            target = stripped / entry.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.is_file():
                shutil.copy2(entry, target)
            else:
                shutil.copytree(entry, target)

        img = tmp_path / "freedos.img"
        result = run_cli(
            "create",
            "--media-type", "img",
            "--floppy-type", "1440k",
            "--path", str(img),
            "--img-system-format",
            "--boot-mode", "freedos",
            "--freedos-source", "local",
            "--boot-assets-path", str(stripped),
        )
        assert_success(result)

        # VBR check.
        vbr = read_mbr(img)
        assert vbr[510:512] == b"\x55\xaa", "Floppy boot signature missing"
        assert vbr[54:62] == b"FAT12   ", (
            f"BPB FS type should be FAT12, got {vbr[54:62]!r}"
        )
        # Boot code at offset 62+ should be the built-in FreeDOS FAT12
        # sector — verify a substantial code region was written.
        boot_code_non_zero = sum(1 for b in vbr[62:510] if b != 0)
        assert boot_code_non_zero >= 200, (
            f"VBR boot code looks empty: {boot_code_non_zero} non-zero bytes in 62..509"
        )

        # mdir with -a shows hidden files; KERNEL.SYS should appear.
        mdir = VENDOR_BIN / "mdir.exe"
        if not mdir.is_file():
            pytest.skip("vendor/windows/bin/mdir.exe missing")
        proc = subprocess.run(
            [str(mdir), "-i", str(img), "-a", "::"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"mdir failed: {proc.stderr}"
        normalized = proc.stdout.upper().replace(" ", "")
        assert "KERNELSYS" in normalized, "KERNEL.SYS not staged"
        assert "COMMANDCOM" in normalized, "COMMAND.COM not staged"


# --------------------------------------------------------------------------
# 8. Negative cases
# --------------------------------------------------------------------------


UNSUPPORTED_VHD_BOOT_MODES: list[tuple[str, list[str]]] = [
    # All previously-unsupported VHD boot modes (msdos5, msdos622, pcdos,
    # pcdos7) now run on Windows via the static-template asset resolver
    # path. The negative-case list is intentionally empty.
]


class TestNegativeCases:
    @pytest.mark.parametrize(
        "boot_mode,extra",
        UNSUPPORTED_VHD_BOOT_MODES,
        ids=[m[0] for m in UNSUPPORTED_VHD_BOOT_MODES],
    )
    def test_unsupported_vhd_boot_mode_reports_clean_error(
        self,
        tmp_path: Path,
        boot_mode: str,
        extra: list[str],
    ):
        vhd = tmp_path / f"{boot_mode}.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat16",
            "--size", "32M",
            "--path", str(vhd),
            "--boot-mode", boot_mode,
            *extra,
        )
        assert_clean_error(result, contains="not yet supported")

    def test_freedos_fat32_reports_clean_error(self, tmp_path: Path):
        vhd = tmp_path / "freedos-fat32.vhd"
        result = run_cli(
            "create",
            "--media-type", "vhd",
            "--format", "fat32",
            "--size", "128M",
            "--path", str(vhd),
            "--boot-mode", "freedos",
            "--freedos-source", "local",
            "--boot-assets-path", str(FREEDOS_ASSETS),
        )
        assert_clean_error(result, contains="FAT16")
