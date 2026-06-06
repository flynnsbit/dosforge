"""Tests for ``pcdos2000_extract`` — focuses on the pure-Python parts.

The DOSBox-X / mtools extraction path is exercised end-to-end in
manual smoke testing only — it depends on a real PC-DOS 2000 7z
archive (gitignored, not in CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.pcdos2000_extract import (
    PCDOS2000_ARCHIVE_NAMES,
    PCDOS2000_BLACKLIST_PATTERNS,
    _is_blacklisted,
    _is_pcdos2000_disk_image,
    find_pcdos2000_archive,
    find_pcdos2000_disk_dir,
    find_pcdos2000_source,
    merge_pcdos2000_into_pcdos71_dos,
)


def test_blacklist_filters_pendos_and_av(tmp_path: Path) -> None:
    assert _is_blacklisted("PENDOS.CFG")
    assert _is_blacklisted("PEN.EXE")
    assert _is_blacklisted("PMOUSE.EXE")
    assert _is_blacklisted("PINK.EXE")
    assert _is_blacklisted("IBMAVD.EXE")
    assert _is_blacklisted("VIRSIG.LST")
    assert _is_blacklisted("DBLSPACE.COM")
    assert _is_blacklisted("AVBKUD.GRP")
    assert _is_blacklisted("WBACKUP1.GRP")
    assert _is_blacklisted("README.TXT")
    assert _is_blacklisted("FILES.TXT")
    assert _is_blacklisted("DISK.NUM")


def test_blacklist_keeps_canonical_dos_utilities() -> None:
    for name in (
        "EMM386.EXE", "POWER.EXE", "PRINT.COM", "RESTORE.COM",
        "BACKUP.COM", "DEFRAG.EXE", "DELTREE.EXE", "DISKCOMP.COM",
        "DOSSHELL.EXE", "DOSSHELL.HLP", "HELP.COM", "INTERLNK.EXE",
        "INTERSVR.EXE", "POWER.EXE", "SETVER.EXE", "SHARE.EXE",
        "UNDELETE.EXE", "REPLACE.EXE", "ASSIGN.COM", "ANSI.SYS",
        "EGA.SYS", "DRIVER.SYS", "JOIN.EXE", "MORE.COM", "EGA.CPI",
    ):
        assert not _is_blacklisted(name), f"{name} should NOT be blacklisted"


def test_blacklist_is_case_insensitive() -> None:
    assert _is_blacklisted("pendos.cfg")
    assert _is_blacklisted("Pen.Exe")
    assert _is_blacklisted("ibmavd.exe")


def test_find_pcdos2000_archive_exact_match(tmp_path: Path) -> None:
    (tmp_path / "IBM PC-DOS 2000 (3.5-1.44mb).7z").write_bytes(b"")
    (tmp_path / "readme.txt").write_text("notes")
    found = find_pcdos2000_archive(tmp_path)
    assert found is not None
    assert found.name == "IBM PC-DOS 2000 (3.5-1.44mb).7z"


def test_find_pcdos2000_archive_substring_match(tmp_path: Path) -> None:
    (tmp_path / "IBM-PC-DOS-2000-floppies.7z").write_bytes(b"")
    found = find_pcdos2000_archive(tmp_path)
    assert found is not None
    assert "2000" in found.name


def test_find_pcdos2000_archive_missing(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("only notes")
    assert find_pcdos2000_archive(tmp_path) is None


def test_find_pcdos2000_archive_dir_missing(tmp_path: Path) -> None:
    assert find_pcdos2000_archive(tmp_path / "does-not-exist") is None


def test_is_pcdos2000_disk_image_recognizes_winworld_layout() -> None:
    for name in ("disk01.img", "disk02.img", "DISK06.IMG", "disk6.img", "01.img", "6.IMG", "disk03.dsk"):
        assert _is_pcdos2000_disk_image(name), f"{name} should be recognized"
    for name in ("disk00.img", "disk09.img", "disk10.img", "command.com", "ibmbio.com", "readme.txt"):
        assert not _is_pcdos2000_disk_image(name), f"{name} should NOT be recognized"


def test_find_pcdos2000_disk_dir_with_six_imgs(tmp_path: Path) -> None:
    for i in range(1, 7):
        (tmp_path / f"disk0{i}.img").write_bytes(b"\x00" * 1024)
    found = find_pcdos2000_disk_dir(tmp_path)
    assert found == tmp_path


def test_find_pcdos2000_disk_dir_with_only_three_imgs(tmp_path: Path) -> None:
    # Threshold is >=5; three is not enough.
    for i in range(1, 4):
        (tmp_path / f"disk0{i}.img").write_bytes(b"")
    assert find_pcdos2000_disk_dir(tmp_path) is None


def test_find_pcdos2000_source_prefers_archive_over_imgs(tmp_path: Path) -> None:
    (tmp_path / "IBM PC-DOS 2000 (3.5-1.44mb).7z").write_bytes(b"")
    for i in range(1, 7):
        (tmp_path / f"disk0{i}.img").write_bytes(b"")
    found = find_pcdos2000_source(tmp_path)
    assert found is not None and found.is_file()
    assert found.name == "IBM PC-DOS 2000 (3.5-1.44mb).7z"


def test_find_pcdos2000_source_falls_through_to_imgs(tmp_path: Path) -> None:
    # No archive, but full set of floppies.
    for i in range(1, 7):
        (tmp_path / f"disk0{i}.img").write_bytes(b"\x00" * 1024)
    found = find_pcdos2000_source(tmp_path)
    assert found == tmp_path


def test_find_pcdos2000_source_returns_none_when_empty(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("notes")
    assert find_pcdos2000_source(tmp_path) is None


def test_merge_sgtk_wins_on_conflict(tmp_path: Path) -> None:
    pcdos71_dos = tmp_path / "pcdos71" / "DOS"
    pcdos71_dos.mkdir(parents=True)
    # SGTK already has these files with specific bytes
    (pcdos71_dos / "COMMAND.COM").write_bytes(b"SGTK COMMAND.COM bytes")
    (pcdos71_dos / "HIMEM.SYS").write_bytes(b"SGTK HIMEM.SYS bytes")
    (pcdos71_dos / "FORMAT.COM").write_bytes(b"SGTK FORMAT.COM bytes")

    pcdos2000_dos = tmp_path / "pcdos2000-extracted" / "DOS"
    pcdos2000_dos.mkdir(parents=True)
    # Same names — these should NOT overwrite SGTK
    (pcdos2000_dos / "COMMAND.COM").write_bytes(b"PCDOS2000 COMMAND")
    (pcdos2000_dos / "HIMEM.SYS").write_bytes(b"PCDOS2000 HIMEM")
    # Net-new — these SHOULD be copied
    (pcdos2000_dos / "EMM386.EXE").write_bytes(b"PCDOS2000 EMM386")
    (pcdos2000_dos / "POWER.EXE").write_bytes(b"PCDOS2000 POWER")
    (pcdos2000_dos / "DOSSHELL.EXE").write_bytes(b"PCDOS2000 DOSSHELL")

    added, skipped = merge_pcdos2000_into_pcdos71_dos(pcdos2000_dos, pcdos71_dos)

    assert added == 3
    assert skipped == 2
    # SGTK bytes preserved
    assert (pcdos71_dos / "COMMAND.COM").read_bytes() == b"SGTK COMMAND.COM bytes"
    assert (pcdos71_dos / "HIMEM.SYS").read_bytes() == b"SGTK HIMEM.SYS bytes"
    assert (pcdos71_dos / "FORMAT.COM").read_bytes() == b"SGTK FORMAT.COM bytes"
    # Net-new files staged
    assert (pcdos71_dos / "EMM386.EXE").read_bytes() == b"PCDOS2000 EMM386"
    assert (pcdos71_dos / "POWER.EXE").read_bytes() == b"PCDOS2000 POWER"
    assert (pcdos71_dos / "DOSSHELL.EXE").read_bytes() == b"PCDOS2000 DOSSHELL"


def test_merge_case_insensitive_conflict(tmp_path: Path) -> None:
    pcdos71_dos = tmp_path / "DOS"
    pcdos71_dos.mkdir()
    (pcdos71_dos / "command.com").write_bytes(b"SGTK lowercase")

    pcdos2000_dos = tmp_path / "src"
    pcdos2000_dos.mkdir()
    (pcdos2000_dos / "COMMAND.COM").write_bytes(b"PCDOS2000 uppercase")

    added, skipped = merge_pcdos2000_into_pcdos71_dos(pcdos2000_dos, pcdos71_dos)

    assert added == 0
    assert skipped == 1
    # Original (lowercase) file untouched; uppercase NOT created
    assert (pcdos71_dos / "command.com").read_bytes() == b"SGTK lowercase"


def test_merge_creates_target_dir_if_missing(tmp_path: Path) -> None:
    pcdos71_dos = tmp_path / "DOS"
    # Does NOT exist yet
    pcdos2000_dos = tmp_path / "src"
    pcdos2000_dos.mkdir()
    (pcdos2000_dos / "EMM386.EXE").write_bytes(b"x")

    added, skipped = merge_pcdos2000_into_pcdos71_dos(pcdos2000_dos, pcdos71_dos)

    assert added == 1
    assert skipped == 0
    assert (pcdos71_dos / "EMM386.EXE").is_file()


def test_archive_names_includes_winworldpc_default() -> None:
    assert "IBM PC-DOS 2000 (3.5-1.44mb).7z" in PCDOS2000_ARCHIVE_NAMES


def test_blacklist_patterns_nonempty() -> None:
    assert len(PCDOS2000_BLACKLIST_PATTERNS) > 10
