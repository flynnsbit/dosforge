"""Unit tests for the dosforge.grow internal implementation.

Covers the surface-level helpers (snapshot, cluster-band check,
crash-safe replace, boot-mode auto-detect, mtools failure paths)
without spinning up a real VHD build.  End-to-end grow runs are
exercised manually via the CLI smoke-test in the dev workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock

import pytest

from dosforge._grow_impl import (
    _VhdSnapshot,
    _atomic_replace_vhd,
    _detect_boot_mode_from_root,
    _expected_cluster_size_for_new_size,
    _mtools_extract_partition_root,
    _mtools_inject_extracted_tree,
    _mtools_stage_directory,
    _snapshot_vhd,
    _validate_extracted_payload_fits,
)
from dosforge.commands import RunResult
from dosforge.errors import ValidationError
from dosforge.models import BootMode, DiskFormat


def _write_fake_vhd_with_partition(
    path: Path,
    *,
    partition_lba: int = 63,
    partition_sectors: int = 65473,
    partition_type: int = 0x06,
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 4,
    reserved_sectors: int = 1,
    num_fats: int = 2,
    root_entries: int = 512,
    sectors_per_fat_16: int = 256,
    sectors_per_fat_32: int = 0,
    total_sectors_16: int = 65473,
    total_sectors_32: int = 0,
) -> None:
    """Synthesize a minimal fixed VHD with one FAT16 partition."""
    # Compute total file size: data area + 512-byte footer.
    data_size = max((partition_lba + partition_sectors) * 512, 32 * 1024 * 1024)
    buf = bytearray(data_size + 512)

    # MBR signature + partition entry
    mbr = bytearray(512)
    mbr[446 + 4] = partition_type
    mbr[446 + 8:446 + 12] = partition_lba.to_bytes(4, "little")
    mbr[446 + 12:446 + 16] = partition_sectors.to_bytes(4, "little")
    mbr[510] = 0x55
    mbr[511] = 0xAA
    buf[0:512] = mbr

    # BPB at partition start
    bpb_offset = partition_lba * 512
    bpb = bytearray(512)
    bpb[0:3] = b"\xeb\x3c\x90"
    bpb[3:11] = b"MSDOS5.0"
    bpb[11:13] = bytes_per_sector.to_bytes(2, "little")
    bpb[13] = sectors_per_cluster
    bpb[14:16] = reserved_sectors.to_bytes(2, "little")
    bpb[16] = num_fats
    bpb[17:19] = root_entries.to_bytes(2, "little")
    bpb[19:21] = total_sectors_16.to_bytes(2, "little")
    bpb[22:24] = sectors_per_fat_16.to_bytes(2, "little")
    bpb[32:36] = total_sectors_32.to_bytes(4, "little")
    bpb[36:40] = sectors_per_fat_32.to_bytes(4, "little")
    bpb[510] = 0x55
    bpb[511] = 0xAA
    buf[bpb_offset:bpb_offset + 512] = bpb

    # VHD footer: 'conectix' magic at offset 0 of the last 512 bytes
    footer = bytearray(512)
    footer[0:8] = b"conectix"
    buf[-512:] = footer

    path.write_bytes(bytes(buf))


class TestSnapshotVhd:
    def test_reads_fat16_geometry(self, tmp_path: Path) -> None:
        vhd = tmp_path / "exo.vhd"
        _write_fake_vhd_with_partition(vhd)
        snap = _snapshot_vhd(vhd)
        assert snap.partition_lba_start == 63
        assert snap.partition_offset_bytes == 63 * 512
        assert snap.partition_type == 0x06
        assert snap.bytes_per_sector == 512
        assert snap.sectors_per_cluster == 4
        assert snap.cluster_size_bytes == 2048
        assert snap.fat_format is DiskFormat.FAT16

    def test_classifies_fat32_by_cluster_count(self, tmp_path: Path) -> None:
        vhd = tmp_path / "big.vhd"
        _write_fake_vhd_with_partition(
            vhd,
            partition_lba=2048,
            partition_sectors=2 * 1024 * 1024,  # 1 GiB
            partition_type=0x0C,
            sectors_per_cluster=8,
            reserved_sectors=32,
            num_fats=2,
            root_entries=0,             # FAT32: root in data area
            sectors_per_fat_16=0,
            sectors_per_fat_32=4096,
            total_sectors_16=0,
            total_sectors_32=2 * 1024 * 1024,
        )
        snap = _snapshot_vhd(vhd)
        assert snap.fat_format is DiskFormat.FAT32
        assert snap.cluster_size_bytes == 4096

    def test_missing_partition_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "empty.vhd"
        _write_fake_vhd_with_partition(vhd, partition_lba=0, partition_sectors=0)
        with pytest.raises(ValidationError, match="no first MBR partition"):
            _snapshot_vhd(vhd)

    def test_missing_mbr_signature_rejected(self, tmp_path: Path) -> None:
        vhd = tmp_path / "junk.vhd"
        vhd.write_bytes(b"\x00" * 4096)
        with pytest.raises(ValidationError, match="no valid MBR signature"):
            _snapshot_vhd(vhd)


class TestExpectedClusterSize:
    @pytest.mark.parametrize(
        "size, fmt, cluster",
        [
            (16 * 1024**2, DiskFormat.FAT16, 2048),
            (128 * 1024**2, DiskFormat.FAT16, 2048),
            (200 * 1024**2, DiskFormat.FAT16, 4096),
            (1 * 1024**3, DiskFormat.FAT16, 16384),
            (2 * 1024**3, DiskFormat.FAT16, 32768),
            (1 * 1024**3, DiskFormat.FAT32, 4096),
            (16 * 1024**3, DiskFormat.FAT32, 8192),
        ],
    )
    def test_mformat_band_table(self, size: int, fmt: DiskFormat, cluster: int) -> None:
        assert _expected_cluster_size_for_new_size(size, fmt) == cluster


class TestValidateExtractedPayloadFits:
    def _make_extract(self, root: Path, files: dict[str, int]) -> None:
        for rel, size in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x00" * size)

    def test_small_payload_fits_in_large_target(self, tmp_path: Path) -> None:
        extract = tmp_path / "x"
        self._make_extract(extract, {
            "KERNEL.SYS": 50_000,
            "COMMAND.COM": 90_000,
            "FDOS/BIN/EDIT.EXE": 60_000,
        })
        # 200 KB of files into a 128 MiB target -- trivially fits.
        _validate_extracted_payload_fits(extract, 128 * 1024 * 1024, DiskFormat.FAT16)

    def test_oversized_payload_rejected(self, tmp_path: Path) -> None:
        extract = tmp_path / "x"
        self._make_extract(extract, {
            "BIG.DAT": 40 * 1024 * 1024,  # 40 MiB
        })
        # 40 MiB into a 32 MiB target -- won't fit.
        with pytest.raises(ValidationError, match="won't fit"):
            _validate_extracted_payload_fits(extract, 32 * 1024 * 1024, DiskFormat.FAT16)

    def test_many_tiny_files_account_for_cluster_slack(self, tmp_path: Path) -> None:
        extract = tmp_path / "x"
        # 5000 tiny 100-byte files -- bytes total = 500 KB, but with
        # 8 KiB cluster slack per file = 40 MiB estimated, which
        # exceeds a 32 MiB target.
        files = {f"f{i:04d}.txt": 100 for i in range(5000)}
        self._make_extract(extract, files)
        with pytest.raises(ValidationError, match="won't fit"):
            _validate_extracted_payload_fits(extract, 32 * 1024 * 1024, DiskFormat.FAT16)


def _fake_snapshot() -> _VhdSnapshot:
    return _VhdSnapshot(
        file_size=32 * 1024 * 1024 + 512,
        partition_lba_start=63,
        partition_sector_count=65473,
        partition_type=0x06,
        partition_offset_bytes=63 * 512,
        bytes_per_sector=512,
        sectors_per_cluster=4,
        cluster_size_bytes=2048,
        fat_format=DiskFormat.FAT16,
    )


def _run_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> RunResult:
    return RunResult(
        command=("mcopy",),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class _ScriptedRunner:
    """Minimal CommandRunner stand-in with a scripted ``run`` sequence."""

    def __init__(self, results: Sequence[RunResult] | None = None) -> None:
        self._results = list(results or [])
        self.calls: list[list[str]] = []

    def run(self, command, *, check: bool = True, **_kwargs) -> RunResult:
        self.calls.append(list(command))
        if self._results:
            return self._results.pop(0)
        return _run_result(0)


class TestAtomicReplaceVhd:
    def test_keep_backup_moves_original_aside(self, tmp_path: Path) -> None:
        target = tmp_path / "disk.vhd"
        new_vhd = tmp_path / "new.vhd"
        target.write_bytes(b"ORIGINAL")
        new_vhd.write_bytes(b"GROWN-IMAGE")
        _atomic_replace_vhd(new_vhd, target, keep_backup=True)
        assert target.read_bytes() == b"GROWN-IMAGE"
        assert (tmp_path / "disk.vhd.bak").read_bytes() == b"ORIGINAL"
        assert not (tmp_path / "disk.vhd.new").exists()

    def test_no_backup_preserves_original_if_copy_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "disk.vhd"
        new_vhd = tmp_path / "new.vhd"
        target.write_bytes(b"ORIGINAL")
        new_vhd.write_bytes(b"GROWN-IMAGE")

        def boom(src, dst, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("dosforge._grow_impl.shutil.copy2", boom)
        with pytest.raises(ValidationError, match="Failed to install grown VHD"):
            _atomic_replace_vhd(new_vhd, target, keep_backup=False)
        assert target.read_bytes() == b"ORIGINAL"
        assert not (tmp_path / "disk.vhd.new").exists()

    def test_no_backup_replaces_in_place(self, tmp_path: Path) -> None:
        target = tmp_path / "disk.vhd"
        new_vhd = tmp_path / "new.vhd"
        target.write_bytes(b"ORIGINAL")
        new_vhd.write_bytes(b"GROWN-IMAGE")
        _atomic_replace_vhd(new_vhd, target, keep_backup=False)
        assert target.read_bytes() == b"GROWN-IMAGE"
        assert not (tmp_path / "disk.vhd.bak").exists()
        assert not (tmp_path / "disk.vhd.new").exists()

    def test_keep_backup_restores_original_if_final_rename_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "disk.vhd"
        new_vhd = tmp_path / "new.vhd"
        target.write_bytes(b"ORIGINAL")
        new_vhd.write_bytes(b"GROWN-IMAGE")

        real_replace = __import__("os").replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            # First replace is dest_tmp -> target after backup rename.
            if calls["n"] == 1:
                raise OSError("rename failed")
            return real_replace(src, dst)

        monkeypatch.setattr("dosforge._grow_impl.os.replace", flaky_replace)
        with pytest.raises(ValidationError, match="Failed to install grown VHD"):
            _atomic_replace_vhd(new_vhd, target, keep_backup=True)
        # Original must be restored to the live path.
        assert target.read_bytes() == b"ORIGINAL"


class TestDetectBootModeFromRoot:
    def test_kernel_sys_is_freedos(self, tmp_path: Path) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")
        runner = _ScriptedRunner([
            _run_result(0, stdout="KERNEL SYS     12345\n"),
        ])
        assert _detect_boot_mode_from_root(vhd, _fake_snapshot(), runner) is BootMode.FREEDOS

    def test_ibmbio_refuses_ambiguous_guess(self, tmp_path: Path) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")
        runner = _ScriptedRunner([
            _run_result(0, stdout="IBMBIO  COM    33430\nIBMDOS  COM    37394\n"),
        ])
        with pytest.raises(ValidationError, match="IBMBIO.COM/IBMDOS.COM"):
            _detect_boot_mode_from_root(vhd, _fake_snapshot(), runner)

    def test_msdos_sys_paths_is_msdos71(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")
        # mdir then mcopy of MSDOS.SYS — the mcopy path is a host scratch
        # file; patch read via writing when mcopy "runs".
        scratch_payload = b"[Paths]\r\nWinDir=C:\\WINDOWS"

        def run(command, *, check: bool = True, **_kwargs):
            if command[0] == "mdir":
                return _run_result(0, stdout="IO      SYS    222670\nMSDOS   SYS      1234\n")
            # mcopy to scratch: write the payload so detect can read it.
            dest = Path(command[-1])
            dest.write_bytes(scratch_payload)
            return _run_result(0)

        runner = MagicMock()
        runner.run.side_effect = run
        assert _detect_boot_mode_from_root(vhd, _fake_snapshot(), runner) is BootMode.MSDOS71

    def test_msdos_sys_binary_is_msdos622(
        self, tmp_path: Path
    ) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")

        def run(command, *, check: bool = True, **_kwargs):
            if command[0] == "mdir":
                return _run_result(0, stdout="IO      SYS    40470\nMSDOS   SYS    38138\n")
            dest = Path(command[-1])
            dest.write_bytes(b"\xeb\x3c\x90MSDOS5.0")
            return _run_result(0)

        runner = MagicMock()
        runner.run.side_effect = run
        assert _detect_boot_mode_from_root(vhd, _fake_snapshot(), runner) is BootMode.MSDOS622


class TestMtoolsExtractFailsHard:
    def test_empty_extract_after_failed_mcopy_raises(self, tmp_path: Path) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")
        extract = tmp_path / "extract"
        runner = _ScriptedRunner([
            _run_result(1, stderr="mcopy: Cannot initialize '::'"),
            _run_result(1, stderr="mcopy: Cannot initialize '::/'"),
        ])
        with pytest.raises(ValidationError, match="Failed to extract"):
            _mtools_extract_partition_root(vhd, _fake_snapshot(), extract, runner)

    def test_nonzero_mcopy_ok_when_files_landed(self, tmp_path: Path) -> None:
        vhd = tmp_path / "d.vhd"
        vhd.write_bytes(b"\x00")
        extract = tmp_path / "extract"

        def run(command, *, check: bool = True, **_kwargs):
            # Simulate mtools writing a file then returning nonzero (volume label).
            extract.mkdir(parents=True, exist_ok=True)
            (extract / "AUTOEXEC.BAT").write_text("@ECHO OFF\r\n", encoding="ascii")
            return _run_result(1, stderr="Volume label")

        runner = MagicMock()
        runner.run.side_effect = run
        _mtools_extract_partition_root(vhd, _fake_snapshot(), extract, runner)
        assert (extract / "AUTOEXEC.BAT").is_file()


class TestMtoolsInjectFailsHard:
    def test_root_file_mcopy_failure_raises(self, tmp_path: Path) -> None:
        extract = tmp_path / "extract"
        extract.mkdir()
        (extract / "README.TXT").write_text("hi", encoding="ascii")
        new_vhd = tmp_path / "new.vhd"
        new_vhd.write_bytes(b"\x00")
        runner = _ScriptedRunner([_run_result(1, stderr="mcopy: No space")])
        with pytest.raises(ValidationError, match="Failed to re-inject root"):
            _mtools_inject_extracted_tree(
                new_vhd, _fake_snapshot(), extract, runner
            )

    def test_subdir_mcopy_failure_raises(self, tmp_path: Path) -> None:
        extract = tmp_path / "extract"
        games = extract / "GAMES"
        games.mkdir(parents=True)
        (games / "DOOM.EXE").write_bytes(b"MZ")
        new_vhd = tmp_path / "new.vhd"
        new_vhd.write_bytes(b"\x00")
        runner = _ScriptedRunner([_run_result(1, stderr="mcopy: failed")])
        with pytest.raises(ValidationError, match=r"subdirectory \\GAMES\\"):
            _mtools_inject_extracted_tree(
                new_vhd, _fake_snapshot(), extract, runner
            )


class TestMtoolsStageFailsHard:
    def test_file_mcopy_failure_raises(self, tmp_path: Path) -> None:
        src = tmp_path / "stage"
        src.mkdir()
        (src / "GAME.EXE").write_bytes(b"MZ")
        new_vhd = tmp_path / "new.vhd"
        new_vhd.write_bytes(b"\x00")
        # mmd (ok-ish) then mcopy fails
        runner = _ScriptedRunner([
            _run_result(0),
            _run_result(1, stderr="mcopy: Disk full"),
        ])
        with pytest.raises(ValidationError, match="Failed to stage"):
            _mtools_stage_directory(
                new_vhd, _fake_snapshot(), src, "C:\\GAMES", runner
            )
