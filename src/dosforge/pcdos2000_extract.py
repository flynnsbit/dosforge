"""PC-DOS 2000 utility extractor for PC-DOS 7.1 FULL profile hydration.

PC-DOS 7.10 (as shipped in the IBM ServerGuide Scripting Toolkit
1.3.07 — the only canonical distribution that exists) is a slimmed
build of PC-DOS for server deployment. The SGTK omits classic DOS
utilities like ``EMM386.EXE``, ``DOSSHELL.EXE``, ``DEFRAG.EXE``,
``BACKUP.COM``, ``RESTORE.COM``, ``POWER.EXE``, ``UNDELETE.EXE``,
``HELP.COM``, ``INTERLNK``/``INTERSVR``, etc. — confirmed by the
SGTK readme: *"The emm386.exe expanded memory device driver is not
supported by the ServerGuide Scripting Toolkit."*

PC-DOS 2000 (= PC-DOS 7.0, IBM's last commercial DOS release) ships
all of those utilities. Per a user-approved exception to the hard
authenticity rule, the ``pcdos71`` boot mode's FULL profile merges
PC-DOS 2000 utilities into the SGTK's ``C:\\DOS\\`` directory so
users get a familiar, full-featured DOS environment. The conflict
rule is **SGTK wins** — IBMBIO.COM / IBMDOS.COM / COMMAND.COM and
all 40 SGTK files keep their PC-DOS 7.10 versions; only files NOT
in the SGTK set get pulled from PC-DOS 2000.

The PC-DOS 2000 install media (six 1.44 MB floppies) packs most of
its utilities inside IBM FTCOMP-format archives named ``DOS1``,
``DOS2``, ``DOS3``, ``DOS4``, ``SHELL1``, ``SHELL2``. These can only
be expanded by ``UNPACK2.EXE`` (IBM's official tool, shipped on
disk01). We use DOSBox-X to run ``UNPACK2`` against each pack and
harvest the resulting files into a cache dir.

Authenticity rule observance
----------------------------

Every file we copy is an authentic IBM binary lifted byte-for-byte
from one of the six WinWorldPC-archived PC-DOS 2000 install floppies
(produced by IBM in 1998), expanded with IBM's own ``UNPACK2.EXE``
in a DOSBox-X sandbox. No synthesis, no third-party substitutes,
no cross-DOS borrowing from FreeDOS or MS-DOS.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .commands import subprocess_no_window_kwargs
from .errors import DosForgeError, ValidationError
from .paths import app_cache_dir


__all__ = [
    "PCDOS2000_ARCHIVE_NAMES",
    "PCDOS2000_PACK_FILES",
    "PCDOS2000_BLACKLIST_PATTERNS",
    "extract_pcdos2000_utilities",
    "merge_pcdos2000_into_pcdos71_dos",
    "default_cache_dir",
]


# Names the user's WinWorldPC download might appear under. ``pcdos71_fetch``
# probes ``dosassets/pcdos2000/`` for the first match.
PCDOS2000_ARCHIVE_NAMES: tuple[str, ...] = (
    "IBM PC-DOS 2000 (3.5-1.44mb).7z",
    "IBM PC-DOS 2000 (3.5-1.44mb).zip",
    "pcdos2000.7z",
)

# IBM FTCOMP-format pack files we hand to UNPACK2 inside DOSBox-X.
# Order is the order we issue UNPACK2 commands; if two packs both
# emit FOO.EXE the later one wins (consistent with how the real
# SETUP.COM installs them, since SETUP also processes them in order).
PCDOS2000_PACK_FILES: tuple[str, ...] = (
    "DOS1",
    "DOS2",
    "DOS3",
    "DOS4",
    "SHELL1",
    "SHELL2",
)

# Files we DON'T want hydrated into C:\DOS, even though they're in
# PC-DOS 2000. These are PenDOS handwriting input (no use under
# emulation), Windows-side wrappers (.GRP/.PIF/.ICO), Stacker disk
# compression (incompatible with FAT16/FAT32 host volumes), and
# IBM Antivirus 1998 signature databases (~3 MB of stale data).
# Match is case-insensitive against the bare filename.
PCDOS2000_BLACKLIST_PATTERNS: tuple[str, ...] = (
    # Stacker compression (incompatible with our FAT volumes)
    "DBLSPACE.*",
    "DBLBOOT.*",
    "STACKER.*",
    # PenDOS handwriting input
    "PENDOS.*",
    "PENDEV.*",
    "PEN.EXE",
    "PINK.EXE",
    "PMOUSE.EXE",
    "PSYS.EXE",
    "PWW.EXE",
    "PSETUP.EXE",
    "PKEYUS.EXE",
    "VLOAD.EXE",
    "LIMREC.*",
    # Windows-side wrappers (not DOS commands)
    "*.GRP",
    "*.PIF",
    "*.ICO",
    "WUNDEL.*",
    "WBACKUP*.*",
    "WINAV.*",
    "MWBACKUP.*",
    "MWUNDEL.*",
    "MWAV.*",
    "MWAVTSR.*",
    # IBM Antivirus 1998 signatures (stale, bulky)
    "IBMAV*.*",
    "VIRUS.LST",
    "VIRSIG.LST",
    "VIRINFO.LST",
    "VERV.VDB",
    "SHSIG.LST",
    "TUTORIAL.LST",
    "PRODINFO.LST",
    "PALETTE.AVD",
    "LOCAL.MSG",
    # 7z self-extractor scaffolding from the WinWorldPC archive
    "FILES.TXT",
    "DISK.NUM",
    "BLISTLAY.OUT",
    "SETUP.COM",
    "SETUP.INI",
    "SETUP.MSG",
    "SETUP1.OVL",
    "SETUP2.OVL",
    "SETUP2.TXT",
    "SETUP3.OVL",
    "AUTOEXEC.BAT",
    "CONFIG.SYS",
    "README.TXT",
    "WINA20.386",
)


_PCDOS2000_DOS_RELDIR = "DOS"
_CACHE_DIRNAME = "pcdos2000-install"
_TIME_LIMIT_SECONDS_DEFAULT = 240


def default_cache_dir() -> Path:
    """Cache root for extracted PC-DOS 2000 utilities."""
    return app_cache_dir() / _CACHE_DIRNAME


def _content_stamp(path: Path, length: int = 12) -> str:
    """First N hex chars of SHA-256 of the file content."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def _is_blacklisted(filename: str) -> bool:
    from fnmatch import fnmatchcase
    name = filename.upper()
    return any(fnmatchcase(name, pat.upper()) for pat in PCDOS2000_BLACKLIST_PATTERNS)


def find_pcdos2000_archive(pcdos2000_dir: Path) -> Path | None:
    """Locate the WinWorldPC PC-DOS 2000 archive in ``pcdos2000_dir``.

    Honors :data:`PCDOS2000_ARCHIVE_NAMES` in order (exact match), then
    falls back to ``*.7z`` / ``*.zip`` glob with the substring
    ``pc-dos 2000`` (case-insensitive).
    """
    if not pcdos2000_dir.is_dir():
        return None
    listing = {entry.name: entry for entry in pcdos2000_dir.iterdir() if entry.is_file()}
    for name in PCDOS2000_ARCHIVE_NAMES:
        if name in listing:
            return listing[name]
    for entry in pcdos2000_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in (".7z", ".zip"):
            continue
        normalized = entry.stem.lower().replace("-", " ").replace("_", " ")
        if "pc dos 2000" in normalized or "pcdos2000" in normalized:
            return entry
    return None


def _harvest_floppy_contents(
    img_paths: list[Path],
    dest_dir: Path,
    *,
    mcopy_exe: str,
) -> None:
    """mcopy every file off each floppy IMG into ``dest_dir`` (flat)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for img in img_paths:
        subprocess.run(
            [mcopy_exe, "-s", "-n", "-m", "-i", str(img), "::", str(dest_dir) + "/"],
            check=False,
            capture_output=True,
            **subprocess_no_window_kwargs(),
        )


def _run_unpack2_in_dosbox(
    staging_dir: Path,
    out_root: Path,
    *,
    pack_files: tuple[str, ...],
    dosbox_exe: str,
    time_limit_seconds: int,
    extra_log_lines: list[str] | None = None,
) -> int:
    """Run ``UNPACK2 <pack> D:\\OUT`` for each pack in DOSBox-X.

    Returns DOSBox-X exit code (informational only — many UNPACK2
    runs are successful even when DOSBox-X returns non-zero on
    timeout exit). The caller validates via the output file count.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    out_subdir = out_root / "OUT"
    out_subdir.mkdir(parents=True, exist_ok=True)

    conf_path = out_root / "_unpack2.conf"
    autoexec_lines = [
        f'mount C "{staging_dir.as_posix()}"',
        f'mount D "{out_root.as_posix()}"',
        "C:",
    ]
    for pack in pack_files:
        if (staging_dir / pack).is_file():
            autoexec_lines.append(f"UNPACK2 C:\\{pack} D:\\OUT")
    conf_path.write_text(
        "[dosbox]\n"
        "machine=svga_s3\n"
        "memsize=32\n"
        "\n"
        "[sdl]\n"
        "output=surface\n"
        "autolock=false\n"
        "nomenu=true\n"
        "\n"
        "[mixer]\n"
        "nosound=true\n"
        "\n"
        "[autoexec]\n"
        + "\n".join(autoexec_lines)
        + "\n",
        encoding="ascii",
    )

    result = subprocess.run(
        [
            dosbox_exe,
            "-conf", str(conf_path),
            "-fastlaunch",
            "-time-limit", str(time_limit_seconds),
            "-exit",
            "-silent",
        ],
        capture_output=True,
        text=True,
        timeout=time_limit_seconds + 30,
        **subprocess_no_window_kwargs(),
    )
    if extra_log_lines is not None:
        extra_log_lines.append(
            f"dosbox-x exit={result.returncode} stderr_tail={(result.stderr or '')[-400:]!r}"
        )
    return result.returncode


def extract_pcdos2000_utilities(
    pcdos2000_archive: Path,
    *,
    backend=None,
    cache_root: Path | None = None,
    time_limit_seconds: int = _TIME_LIMIT_SECONDS_DEFAULT,
    progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> Path:
    """Extract PC-DOS 2000 DOS utilities into a cached ``DOS/`` directory.

    Returns the path to the cached ``DOS/`` directory; on a cache hit
    no DOSBox-X / mtools work is performed.

    Args:
        pcdos2000_archive: Path to the WinWorldPC ``IBM PC-DOS 2000
            (3.5-1.44mb).7z`` (or compatible) file.
        backend: Platform backend (auto-detected when None).
        cache_root: Override for the cache dir (default
            :func:`default_cache_dir`).
        time_limit_seconds: Per-DOSBox-X run cap. 240s is comfortable
            for all six packs on a modern host.
        progress: Optional callback for human-readable progress lines.
        force: If True, ignore an existing cache and re-extract.

    Raises:
        ValidationError if the archive is missing, unreadable, or the
        DOSBox-X invocation fails to produce any output files.
    """
    if not pcdos2000_archive.is_file():
        raise ValidationError(
            f"PC-DOS 2000 archive not found: {pcdos2000_archive}. "
            "Download IBM PC-DOS 2000 from WinWorldPC and place the "
            "7z file at dosassets/pcdos2000/ to enable PC-DOS 7.1 "
            "FULL profile hydration."
        )

    if cache_root is None:
        cache_root = default_cache_dir()
    cache_root.mkdir(parents=True, exist_ok=True)

    stamp = _content_stamp(pcdos2000_archive)
    cached_dos = cache_root / f"pcdos2000-{stamp}" / _PCDOS2000_DOS_RELDIR
    if not force and cached_dos.is_dir() and any(cached_dos.iterdir()):
        if progress is not None:
            progress(f"  cached: {cached_dos} ({sum(1 for _ in cached_dos.iterdir())} files)")
        return cached_dos

    if backend is None:
        from ._platform import get_backend
        backend = get_backend()

    # Locate the tools we need up front so we fail loudly before any
    # disk work if something's missing on PATH.
    try:
        seven_zip_exe = backend.tool_path("7z")
    except DosForgeError:
        seven_zip_exe = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
        if seven_zip_exe is None:
            raise ValidationError(
                "PC-DOS 2000 extraction requires 7-Zip on PATH "
                "(7z / 7zz / 7za). Install p7zip-full and retry."
            )
    try:
        dosbox_exe = backend.tool_path("dosbox-x")
    except DosForgeError:
        dosbox_exe = shutil.which("dosbox-x")
        if dosbox_exe is None:
            raise ValidationError(
                "PC-DOS 2000 extraction requires DOSBox-X on PATH. "
                "Install dosbox-x and retry."
            )
    try:
        mcopy_exe = backend.tool_path("mcopy")
    except DosForgeError:
        mcopy_exe = shutil.which("mcopy")
        if mcopy_exe is None:
            raise ValidationError(
                "PC-DOS 2000 extraction requires mtools (mcopy) on PATH."
            )

    work = cache_root / f"_extract-{uuid4().hex[:8]}"
    work.mkdir()
    keep_work_for_postmortem = False
    try:
        # 1. Extract the WinWorldPC 7z into a flat scratch.
        if progress is not None:
            progress(f"  extracting {pcdos2000_archive.name}…")
        archive_extract = work / "archive"
        archive_extract.mkdir()
        subprocess.run(
            [str(seven_zip_exe), "x", "-y", f"-o{archive_extract}", str(pcdos2000_archive)],
            check=True,
            capture_output=True,
            **subprocess_no_window_kwargs(),
        )

        # 2. Locate disk01.img..disk06.img anywhere under the extract.
        disks: list[Path] = sorted(
            p for p in archive_extract.rglob("disk0[1-6].img")
        )
        if not disks:
            keep_work_for_postmortem = True
            raise ValidationError(
                f"PC-DOS 2000 archive {pcdos2000_archive.name} doesn't "
                f"contain disk01.img..disk06.img. Expected the WinWorldPC "
                f"\"IBM PC-DOS 2000 (3.5-1.44mb)\" layout."
            )
        if progress is not None:
            progress(f"  found {len(disks)} install floppies")

        # 3. Harvest every file from every floppy into a flat staging dir
        #    (so UNPACK2 sees all the FTCOMP pack files under C:).
        staging = work / "staging"
        _harvest_floppy_contents(disks, staging, mcopy_exe=str(mcopy_exe))
        if progress is not None:
            progress(f"  harvested {sum(1 for _ in staging.iterdir())} files from floppies")

        # 4. Use DOSBox-X to run UNPACK2 against each pack file.
        if progress is not None:
            progress(f"  unpacking {', '.join(PCDOS2000_PACK_FILES)} via DOSBox-X…")
        unpack_root = work / "unpack"
        log_lines: list[str] = []
        _run_unpack2_in_dosbox(
            staging,
            unpack_root,
            pack_files=PCDOS2000_PACK_FILES,
            dosbox_exe=str(dosbox_exe),
            time_limit_seconds=time_limit_seconds,
            extra_log_lines=log_lines,
        )
        unpack_out = unpack_root / "OUT"
        if not unpack_out.is_dir() or not any(unpack_out.iterdir()):
            keep_work_for_postmortem = True
            raise ValidationError(
                f"DOSBox-X UNPACK2 produced no output files at {unpack_out}. "
                f"Log: {'; '.join(log_lines)}"
            )

        # 5. Build the final DOS/ tree: every file from staging (the
        #    plaintext disk01 files like ATTRIB.EXE) + every UNPACK2'd
        #    file, minus the blacklist. ``staging`` files come first so
        #    UNPACK2'd duplicates win (matches IBM's SETUP.COM order).
        scratch_dos = work / "DOS"
        scratch_dos.mkdir()

        def stage(src: Path) -> None:
            if src.is_dir():
                return
            if _is_blacklisted(src.name):
                return
            # Pack files themselves shouldn't appear in C:\DOS.
            if src.name.upper() in {p.upper() for p in PCDOS2000_PACK_FILES}:
                return
            # IBM Antivirus + Stacker pack file remnants
            if src.name.upper() in {
                "AV1", "AV2", "BACKUP1", "BACKUP2", "PCM1", "PCM2",
                "PEN1", "PEN2", "PS1", "REXX", "STAC1", "STAC2", "STAC3",
                "WBACKUP1", "WBACKUP2", "WBACKUP3", "WGRP", "WINAV", "WUNDEL",
            }:
                return
            dst = scratch_dos / src.name.upper()
            shutil.copy2(src, dst)

        for entry in sorted(staging.iterdir()):
            stage(entry)
        for entry in sorted(unpack_out.iterdir()):
            stage(entry)
        if not any(scratch_dos.iterdir()):
            keep_work_for_postmortem = True
            raise ValidationError(
                "PC-DOS 2000 extraction produced no usable utility files "
                "after blacklist filter."
            )

        # 6. Atomic move into the cache key.
        cache_parent = cached_dos.parent
        cache_parent.mkdir(parents=True, exist_ok=True)
        if cached_dos.exists():
            shutil.rmtree(cached_dos, ignore_errors=True)
        shutil.move(str(scratch_dos), str(cached_dos))
        if progress is not None:
            progress(
                f"  staged {sum(1 for _ in cached_dos.iterdir())} PC-DOS 2000 utilities"
                f" to {cached_dos}"
            )
        return cached_dos
    finally:
        if not keep_work_for_postmortem:
            try:
                shutil.rmtree(work, ignore_errors=True)
            except OSError:
                pass


def merge_pcdos2000_into_pcdos71_dos(
    pcdos2000_dos: Path,
    pcdos71_dos: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """Copy PC-DOS 2000 utilities into ``pcdos71_dos`` (SGTK wins).

    Files already present in ``pcdos71_dos`` (any case) are NOT
    overwritten — the SGTK / PC-DOS 7.10 version always wins per the
    user-approved exception to the authenticity rule.

    Returns ``(added, skipped)`` for the caller's progress report.
    """
    if not pcdos2000_dos.is_dir():
        raise ValidationError(
            f"PC-DOS 2000 source dir doesn't exist: {pcdos2000_dos}"
        )
    pcdos71_dos.mkdir(parents=True, exist_ok=True)
    existing = {p.name.upper() for p in pcdos71_dos.iterdir() if p.is_file()}
    added = 0
    skipped = 0
    for src in sorted(pcdos2000_dos.iterdir()):
        if not src.is_file():
            continue
        if src.name.upper() in existing:
            skipped += 1
            continue
        shutil.copy2(src, pcdos71_dos / src.name.upper())
        added += 1
    if progress is not None:
        progress(
            f"  merged PC-DOS 2000 utilities: {added} added, "
            f"{skipped} skipped (SGTK wins)"
        )
    return (added, skipped)
