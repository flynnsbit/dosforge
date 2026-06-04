"""PC-DOS 7.0 install-floppy extractor via LOADDSKF in DOSBox-X.

PC-DOS 7.0 ships its bootable install floppy (1.44 MB) as an IBM
``LOADDSKF``-format compressed file (``144US1.DSK``).  This format is
not readable by mtools, and DOSBox-X's ``imgmount`` rejects it with
"Illegal BPB value".  The official IBM tool to decompress it --
``LOADDSKF.EXE`` -- ships in the same dosassets directory.  This
module wraps a DOSBox-X invocation that runs LOADDSKF.EXE inside
DOSBox-X against an empty ``imgmount A:`` to produce a raw,
mtools-readable 1.44 MB IMG containing the genuine PC-DOS 7.0
install floppy (IBMBIO.COM, IBMDOS.COM, COMMAND.COM, SYS.COM,
FORMAT.COM, FDISK.COM, ...).

The extraction is cached under ``app_cache_dir()/pcdos7-install/``
keyed by the source DSK's SHA-256 prefix so subsequent dosforge
runs don't repeat the work.

Authenticity rule observance
----------------------------

LOADDSKF.EXE is the official IBM tool shipped with PC-DOS 7.0
install media.  The extraction it performs is byte-equivalent to
what a user running LOADDSKF on real hardware would produce.  The
resulting floppy contains genuine PC-DOS 7.0 system files written
by IBM in 1994.  No third-party code, no synthesis, no falsified
boot sectors.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .commands import subprocess_no_window_kwargs
from .errors import ValidationError
from .paths import app_cache_dir


_PCDOS7_DSK_NAMES = ("144US1.DSK", "144us1.dsk")
_LOADDSKF_EXE_NAMES = ("LOADDSKF.EXE", "loaddskf.exe")


def _find_case_insensitive(directory: Path, candidates: tuple[str, ...]) -> Path | None:
    try:
        listing = list(directory.iterdir())
    except OSError:
        return None
    lookup = {entry.name.upper(): entry for entry in listing if entry.is_file()}
    for name in candidates:
        located = lookup.get(name.upper())
        if located is not None:
            return located
    return None


def _content_stamp(path: Path, length: int = 12) -> str:
    """First N hex chars of SHA-256 of the file content.

    Used to key the extraction cache so an updated source DSK
    (different bytes) automatically gets re-extracted.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def extract_pcdos7_install_floppy(
    pcdos7_assets_dir: Path,
    *,
    backend=None,
    cache_root: Path | None = None,
    time_limit_seconds: int = 90,
) -> Path:
    """Decompress 144US1.DSK to a raw 1.44 MB floppy IMG.

    Returns the path to the cached raw IMG (created on first call;
    re-used on subsequent calls).

    Raises ValidationError if the source DSK or LOADDSKF.EXE is missing,
    or if the DOSBox-X invocation fails to write a recognisable
    1.44 MB floppy.
    """
    dsk = _find_case_insensitive(pcdos7_assets_dir, _PCDOS7_DSK_NAMES)
    if dsk is None:
        raise ValidationError(
            f"PC-DOS 7.0 install media not found at {pcdos7_assets_dir}: "
            "missing 144US1.DSK.  Place the IBM PC-DOS 7.0 install "
            "diskette images in this folder."
        )
    loaddskf = _find_case_insensitive(pcdos7_assets_dir, _LOADDSKF_EXE_NAMES)
    if loaddskf is None:
        raise ValidationError(
            f"PC-DOS 7.0 LOADDSKF.EXE not found at {pcdos7_assets_dir}.  "
            "This tool ships alongside the install diskettes and is "
            "required to decompress IBM's LOADDSKF-format .DSK files."
        )

    if cache_root is None:
        cache_root = app_cache_dir() / "pcdos7-install"
    cache_root.mkdir(parents=True, exist_ok=True)
    stamp = _content_stamp(dsk)
    cache_path = cache_root / f"pcdos7-install-{stamp}.img"
    if cache_path.is_file() and cache_path.stat().st_size == 1474560:
        return cache_path

    if backend is None:
        from ._platform import get_backend

        backend = get_backend()

    dosbox_exe = backend.tool_path("dosbox-x")
    mformat_exe = backend.tool_path("mformat")

    work = cache_root / f"_extract-{uuid4().hex[:8]}"
    work.mkdir()
    keep_work_for_postmortem = False
    try:
        host = work / "host"
        host.mkdir()
        shutil.copy2(loaddskf, host / "LOADDSKF.EXE")
        shutil.copy2(dsk, host / "PCDOS7.DSK")

        scratch_img = work / "extracted.img"
        scratch_img.write_bytes(b"\x00" * 1474560)
        subprocess.run(
            [mformat_exe, "-i", str(scratch_img), "-f", "1440", "::"],
            check=True,
            capture_output=True,
            **subprocess_no_window_kwargs(),
        )

        conf = work / "extract.conf"
        conf.write_text(
            "[dosbox]\n"
            "machine=svga_s3\n"
            "memsize=16\n"
            "\n"
            "[sdl]\n"
            "output=surface\n"
            "autolock=false\n"
            "\n"
            "[mixer]\n"
            "nosound=true\n"
            "\n"
            "[autoexec]\n"
            f'mount C "{host.as_posix()}"\n'
            f'imgmount A "{scratch_img.as_posix()}" -t floppy\n'
            "C:\n"
            "LOADDSKF PCDOS7.DSK A: /Y\n",
            encoding="ascii",
        )

        result = subprocess.run(
            [
                dosbox_exe,
                "-conf", str(conf),
                "-fastlaunch",
                "-time-limit", str(time_limit_seconds),
                "-exit",
                "-log-con",
            ],
            capture_output=True,
            text=True,
            timeout=time_limit_seconds + 15,
            **subprocess_no_window_kwargs(),
        )

        if not scratch_img.is_file() or scratch_img.stat().st_size != 1474560:
            keep_work_for_postmortem = True
            raise ValidationError(
                f"DOSBox-X LOADDSKF extraction did not produce a valid "
                f"1.44 MB floppy at {scratch_img}.  "
                f"DOSBox-X exit code: {result.returncode}.  "
                f"Stderr tail: {result.stderr[-1500:]!r}"
            )

        # Validate the extracted IMG actually contains PC-DOS 7.0
        # system files.  ``-a`` is critical: IBMBIO.COM and IBMDOS.COM
        # are written by LOADDSKF with the System+Hidden+ReadOnly
        # attributes (matching a real PC-DOS 7.0 boot floppy), and
        # plain ``mdir`` without -a skips files with those attrs.
        mdir_exe = backend.tool_path("mdir")
        check = subprocess.run(
            [mdir_exe, "-i", str(scratch_img), "-a", "::"],
            capture_output=True, text=True,
            **subprocess_no_window_kwargs(),
        )
        if "IBMBIO" not in (check.stdout or "").upper():
            keep_work_for_postmortem = True
            raise ValidationError(
                f"DOSBox-X LOADDSKF extraction completed but the resulting "
                f"floppy at {scratch_img} doesn't contain IBMBIO.COM.  "
                f"Source DSK may be corrupted or in an unrecognised format.  "
                f"mdir stdout: {(check.stdout or '')[:800]!r}\n"
                f"DOSBox-X stderr tail: {(result.stderr or '')[-1500:]!r}"
            )

        # Move into cache atomically (rename within same volume).
        shutil.move(str(scratch_img), str(cache_path))
        return cache_path
    finally:
        if not keep_work_for_postmortem:
            try:
                shutil.rmtree(work, ignore_errors=True)
            except OSError:
                pass
