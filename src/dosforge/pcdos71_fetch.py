"""Library helpers for downloading + staging IBM PC-DOS 7.1 assets.

PC-DOS 7.1 (the FAT32-capable IBM release) was only ever distributed
inside the IBM ServerGuide Scripting Toolkit (SGTK), DOS Edition,
v1.3.07. IBM's own support page no longer hosts the binary; this
module downloads the IBM-distributed installer from the Internet
Archive mirror, verifies it, and copies the files dosforge needs
(``tk_raid.vfd`` plus ``DOS/FORMAT32.COM`` and the PC-DOS 7.1 system
files) into the user's PC-DOS 7.1 dosassets directory in the layout
:func:`dosforge.legacy_dos_install.pcdos71_profile` expects.

Per-file SHA-256s come from the community patch repo
``github.com/Kreeblah/pcdos71-patch`` and are checked after
extraction. No binaries are bundled with dosforge; users always
fetch fresh from archive.org.

Both the standalone ``scripts/fetch-pcdos71-assets.py`` script and
the ``dosforge fetch-pcdos71-assets`` CLI subcommand consume this
module so the wheel ships a single implementation. The TUI's
"Fetch IBM PC-DOS 7.1 assets" wizard button calls the same library
function with a Textual-friendly progress callback.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import DependencyError, ValidationError
from .paths import app_cache_dir, dos_assets_root

__all__ = [
    "EXPECTED_SHA256",
    "FetchResult",
    "PROGRESS_STAGES",
    "SGTK_SHA1",
    "SGTK_SIZE",
    "SGTK_URL",
    "VFD_CANDIDATES",
    "default_cache_dir",
    "default_target_dir",
    "fetch_pcdos71_assets",
    "find_sevenzip",
]

# Public constants — re-exported for the script wrapper + tests.

SGTK_URL = (
    "https://archive.org/download/pcdos-71-sgtk-1-3-07/"
    "PCDOS71-sgtk_1_3_07.EXE"
)
# SHA-1 + size from archive.org's files.xml metadata
# (https://archive.org/download/pcdos-71-sgtk-1-3-07/pcdos-71-sgtk-1-3-07_files.xml)
SGTK_SHA1 = "e9a1c3a2c9312148671e53887c05603f03b2a102"
SGTK_SIZE = 15216373

# Per-file SHA-256 reference hashes for the PC-DOS 7.1 files in the
# SGTK's ``sgdeploy/sgtk/DOS/`` directory. Source:
# https://github.com/Kreeblah/pcdos71-patch (README; community-published).
# Any extracted file we copy MUST match the corresponding hash here.
EXPECTED_SHA256: dict[str, str] = {
    # Boot / install-critical (also used by FORMAT C: /S over QEMU).
    "ATTRIB.EXE": "91710325176330e403be85d935d6ad21d5bb6a77b589afb84ac4739636e466cd",
    "BLDLEVEL.COM": "d25a4e54cddc46070fd5ad7ca26ff566fe344c2ef9fac87d6b2d8956363d9133",
    "COMMAND.COM": "4bb46e6c3228969b06c423dd181df9c6765999094d4c687772efd9ee23881e7a",
    "DEBUG.COM": "8b0b0a27486c8ad67d60644ede2e57b5621291054baf5d3d376e216bfdb78957",
    "DYNALOAD.COM": "458201d78b36e5a1cc03afe7a16e8f765483034c7279b7cdc74f470ec1208e28",
    "FDISK32.COM": "e4ef889ad29b49d472cd4b30b14e47bf3e95cbcac7c60d4e9ee96cfadfbe5198",
    "FORMAT.COM": "8de7d48bf524159cb7340067590d02cf033aafb2c8d1f77f5f63da7ba35252ff",
    "FORMAT32.COM": "8281d9480359868740c45ab3c8f709417d83bb3461061fe5f796a2670c0041c1",
    "HIMEM.SYS": "f758d0fce53b5879747c38aa64662109fe7d2d504cae16dc410bf227873a2fb9",
    "IBMBIO.COM": "d1c9e34aafa2a65b8f74eeace701b273e16d6b7fae1368c1ba7a768b39eb4558",
    "IBMCDET.SYS": "4ce81df66fd3e6674485f0f70d1413bfca17163f95b02aec68fee28673cf0b2d",
    "IBMDOS.COM": "f426a13b1e2e5a05bc7e56a18d551608d3bdc4cb14045324468860a3725e2084",
    "IBMIDECD.SYS": "6623d237bdfb6bd416e5de3076cd18f12119562005af8cd005b634b94afb80c8",
    "IPSRASPI.SYS": "3b1398944b44b0f9245095bd1f72c1841f36e3967038574c02f86fbc8acc9639",
    "MSCDEX.EXE": "8fd939a93c1153c2a1b2c8e349d438237d3a67f268a78908420447d90c518199",
    "NOINT25.COM": "9ac9a255e9fb2248eef66b18479e19abeef04d82dd16c5aa16696db5dda1c94b",
    # PC-DOS 7.1 full toolkit shipped alongside the boot files in the
    # SGTK's ``sgdeploy/sgtk/DOS/`` directory. These get copied verbatim
    # into ``C:\DOS\`` on every FULL-profile pcdos71 build so the
    # finished VHD matches a real authentic PC-DOS 7.1 install.
    "CHKDSK.COM": "8bb3940afec38c879fde5c2f97c31064db0d6d353615f9c9466f22ec0dda5a2a",
    "COUNTRY.SYS": "f0635909c8cc38374433c5ede680b3c6192f2f02aa4b4c405974bb8d17e1ee1c",
    "DELTREE.EXE": "f9643b03a3ddd4c55cdefb76943ff135b412700478e296f133adafc8414f932e",
    "DISPLAY.SYS": "fc4d8e4f895efea472d2f040fd4d53668b58d7f48a71419675bbd652261fa4fc",
    "DOSKEY.COM": "6a322a1e6bdc2c82a5261f7deffb1745e194ea1f3383cba8fb148c77df6fb24b",
    # IBM "E" editor — E.EXE is the in-memory build, E.EX is the
    # swap-file build; ship both so power users can pick.
    "E.EX": "b8656a8fbd70976521f54bd79e7a534e3955cee4cd8d8cce0498ef3fd9743204",
    "E.EXE": "01c315f9f0ac9adf9ee0436eba64a4535a3f93d3836896dbcad64a2905d0bb68",
    "E.INI": "75eaadef0654c95f3052f97eeb3d02acac5b70ecbfbfb4f97357ba444efd2140",
    "FC.EXE": "4ab2c5b15cc5207bd78a78752fce9c85debd34e907da21e22a7ff2668d5c4271",
    "FIND.EXE": "6deb36a5f43e817f51dec16c84810cb1d1d8aeb8db8146b179d7048f1e283614",
    "KEYB.COM": "b8d8ae213a6577a69a26ce1081106e68d104eceb1a4d2b2a72ce488d98eaafce",
    "KEYBOARD.SYS": "6cf676269baecd0953a19e38d35bdc77bf97274a7f3a5a63ffe5f653f8353ce3",
    "LABEL.COM": "ca3192ea91b56cde0b246711366d9de32c33e0cd951b06a4ff5d0a527aa5fd89",
    "MEM.EXE": "09c9f88fef84d7ec6260d7d07feee116cd618299e3dd6898b5f4aa32b0b80dae",
    "MODE.COM": "129618d3175b6295bb8790b6fe76799ccb18708c6cf9af444defb6109d38506b",
    "MORE.COM": "4fd1cc81ab276f802124c8a165b86e5ce100396a610852f305aa2618f3fc02aa",
    "MOUSE.COM": "ebf49d2c025729d9716ed17925cc8db32df2913454410fcff3d85e244a50d4e0",
    "MOVE.EXE": "6957fb1e90498e134e297fd6f3d4b7852f795a0941635e6b1fe75ea4c2cb7843",
    "RAMDRIVE.SYS": "42eacd1032370e81ec4d5d606c375828e1fd3a5d31c576c030b2bca64f995184",
    "SMARTDRV.EXE": "a3a30b24ef1fd1f60446c168eae3e1b2fcba6a805c463e6546e00e88dc09568a",
    "SUBST.EXE": "e2bfc33c1fe327ef2c15eaf59e099ccbe0627c37a1daa4972217c3c13928215c",
    "SYS.COM": "79ccf82f01ad54da58c11400ff4def26a0eeb2921606acce3f922ea8d81dab46",
    "TREE.COM": "4f6a59af3be68477b3d5c8556d48a2327babca62f771bbd3ed22c02f4d4a0284",
    "XCOPY.EXE": "2a5fdf2bc9c6eb1296c19b213208abdef0b0633ddd887e0db1e6c0d7077ad2b0",
}

# Bootable install floppy candidates dosforge can use (preferred order).
# ``pcdos71_profile`` takes the first one that's actually present.
VFD_CANDIDATES = ("tk_raid.vfd", "tk_raid2.vfd", "install.vfd", "install.img")

# Stable progress-stage labels emitted via the ``progress`` callback.
# Kept as a public tuple so tests can assert they're all reached.
PROGRESS_STAGES = (
    "locating_sevenzip",
    "downloading_sgtk",
    "extracting_sgtk",
    "locating_dos_files",
    "staging_files",
    "hydrating_pcdos2000",
    "done",
)


@dataclass(frozen=True)
class FetchResult:
    """Outcome of :func:`fetch_pcdos71_assets`.

    * ``target_dir`` — where files were staged.
    * ``staged_count`` / ``total_count`` — how many of the expected
      ``EXPECTED_SHA256`` files made it onto disk (with verified
      SHA-256). Both counts are always meaningful; an asymmetry
      means the SGTK extract was incomplete (rare; report `missing`).
    * ``missing`` — files in ``EXPECTED_SHA256`` that the SGTK
      extract didn't contain.
    * ``vfd_filename`` — the bootable floppy that got staged (one of
      ``VFD_CANDIDATES``), or ``None`` if the SGTK didn't include any.
      ``pcdos71_profile`` won't accept the target dir without one.
    """

    target_dir: Path
    staged_count: int
    total_count: int
    missing: tuple[str, ...] = field(default_factory=tuple)
    vfd_filename: str | None = None
    pcdos2000_added: int = 0
    pcdos2000_skipped: int = 0
    pcdos2000_archive: str | None = None
    pcdos2000_error: str | None = None


def default_target_dir() -> Path:
    """Return the user-scope PC-DOS 7.1 dosassets directory.

    Resolved through :func:`dos_assets_root` so XDG / well-known
    overrides work the same way as for the rest of dosforge's
    asset lookup. Equivalent to ``<dosassets>/pcdos71``.
    """
    return dos_assets_root() / "pcdos71"


def default_cache_dir() -> Path:
    """Return the platform-appropriate scratch dir for the SGTK fetch.

    Lives under :func:`app_cache_dir` so it survives across runs
    (cache hits short-circuit the download) but doesn't pollute
    the repo. Replaces the old ``<repo>/build/pcdos71-cache``
    convention that only worked in dev checkouts.
    """
    return app_cache_dir() / "pcdos71-fetch"


def find_sevenzip() -> Path:
    """Locate a usable 7-Zip executable for SGTK extraction.

    Honors the ``DOSFORGE_SEVENZIP_EXE`` env var first, then looks
    up the standard POSIX binary names (``7z``/``7zz``/``7za``) on
    ``PATH``, and finally walks the well-known Windows install
    locations. Raises :class:`DependencyError` (clean CLI error,
    no traceback) when nothing matches.

    The 7-Zip CLI (``7z x -y -o<dir> <archive>``) is identical
    across the official Windows build, ``7zz`` (the upstream POSIX
    binary), and the ``p7zip`` fork ``7z`` / ``7za`` shipped on
    most Linux distros, so any match works for SGTK extraction.
    """
    env = os.environ.get("DOSFORGE_SEVENZIP_EXE")
    if env and Path(env).is_file():
        return Path(env)
    # POSIX (Linux/macOS): p7zip ships /usr/bin/7z and /usr/bin/7za;
    # upstream 7-Zip for POSIX ships /usr/local/bin/7zz.
    for name in ("7z", "7zz", "7za"):
        found = shutil.which(name)
        if found:
            return Path(found)
    # Windows fallback paths.
    for candidate in (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\7-Zip\7z.exe"),
    ):
        p = Path(candidate)
        if p.is_file():
            return p
    raise DependencyError(
        "7-Zip not found. Install it (Linux: 'p7zip-full' / 'p7zip'; "
        "macOS: 'brew install sevenzip'; Windows: https://www.7-zip.org/) "
        "or set DOSFORGE_SEVENZIP_EXE to the path of the executable."
    )


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(
    url: str,
    dest: Path,
    *,
    expected_size: int,
    expected_sha1: str,
    progress: Callable[[str], None] | None,
) -> None:
    if dest.is_file() and dest.stat().st_size == expected_size:
        sha1 = _sha1(dest)
        if sha1.lower() == expected_sha1.lower():
            if progress:
                progress(f"  cached: {dest.name} ({expected_size:,} bytes, SHA-1 verified)")
            return
        if progress:
            progress(f"  cache stale (SHA-1 mismatch), redownloading")
        dest.unlink()
    if progress:
        progress(f"  downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    actual_size = tmp.stat().st_size
    if actual_size != expected_size:
        # Leave the .part file alone for inspection / resume.
        raise ValidationError(
            f"PC-DOS 7.1 SGTK download size mismatch: got {actual_size:,}, "
            f"expected {expected_size:,}. The archive.org mirror may be down "
            "or the URL may have changed."
        )
    sha1 = _sha1(tmp)
    if sha1.lower() != expected_sha1.lower():
        raise ValidationError(
            f"PC-DOS 7.1 SGTK SHA-1 mismatch on download: got {sha1}, "
            f"expected {expected_sha1}. The archive.org mirror may have "
            "been tampered with — refusing to use this file."
        )
    tmp.replace(dest)
    if progress:
        progress(f"  saved: {dest} ({actual_size:,} bytes, SHA-1 verified)")


def _extract(
    seven_zip: Path,
    archive: Path,
    dest: Path,
    *,
    progress: Callable[[str], None] | None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    # `x` preserves directory structure (vs `e` which flattens).
    result = subprocess.run(
        [str(seven_zip), "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValidationError(
            f"7-Zip extraction failed (rc={result.returncode}):\n"
            f"  stdout: {result.stdout[-1500:]}\n"
            f"  stderr: {result.stderr[-1500:]}"
        )
    if progress:
        progress(f"  extracted to {dest}")


def _walk_find(root: Path, name: str) -> Path | None:
    """Case-insensitive recursive search for ``name`` under ``root``."""
    needle = name.lower()
    for entry in root.rglob("*"):
        if entry.is_file() and entry.name.lower() == needle:
            return entry
    return None


def _walk_find_dir(root: Path, name: str) -> Path | None:
    needle = name.lower()
    for entry in root.rglob("*"):
        if entry.is_dir() and entry.name.lower() == needle:
            return entry
    return None


def _copy_with_verification(
    src: Path,
    dst: Path,
    *,
    expected_sha256: str,
    progress: Callable[[str], None] | None,
) -> None:
    actual = _sha256(src)
    if actual.lower() != expected_sha256.lower():
        raise ValidationError(
            f"SHA-256 mismatch for {src.name}:\n"
            f"  expected: {expected_sha256}\n"
            f"  actual:   {actual}\n"
            "Refusing to copy a file whose contents differ from the "
            "Kreeblah-published PC-DOS 7.1 reference hashes."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if progress:
        progress(f"  staged: {dst.name}  ({src.stat().st_size:,} bytes)")


def fetch_pcdos71_assets(
    *,
    target_dir: Path | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
    keep_extract: bool = False,
    progress: Callable[[str], None] | None = None,
) -> FetchResult:
    """Download, verify, and stage IBM PC-DOS 7.1 assets from the SGTK.

    Pipeline:

    1. Resolve / create ``target_dir`` (default
       ``<dosassets>/pcdos71``) and ``cache_dir`` (default
       ``<app_cache>/pcdos71-fetch``).
    2. Locate a 7-Zip executable (raises :class:`DependencyError`
       with install guidance if missing).
    3. Download the SGTK self-extracting installer from
       :data:`SGTK_URL` to ``cache_dir`` if not already cached.
       Verifies size + SHA-1 before accepting either the cache hit
       or a fresh download.
    4. Extract with 7-Zip into ``cache_dir/extract`` (reused on
       subsequent runs unless ``force=True``).
    5. Walk the extract to find the ``DOS`` directory and one of
       :data:`VFD_CANDIDATES`.
    6. Copy each :data:`EXPECTED_SHA256` file into
       ``target_dir/DOS/`` (verifying SHA-256 before each write)
       and copy the install floppy into ``target_dir/``.

    Returns a :class:`FetchResult` summarizing what landed on disk.
    Callers should check ``vfd_filename`` for ``None`` and prompt
    the user to run the SGTK's MAKEDISK script (or apply the
    Kreeblah patch) if no bootable VFD was packaged in the
    installer they downloaded.

    ``progress`` is invoked with one of the labels from
    :data:`PROGRESS_STAGES` at each stage boundary, plus free-form
    lines for download / extraction progress. The TUI uses this to
    update its status bar; the CLI script wrapper prints to stdout.
    """
    target = (target_dir or default_target_dir()).expanduser()
    cache = (cache_dir or default_cache_dir()).expanduser()
    cache.mkdir(parents=True, exist_ok=True)

    if progress:
        progress("locating_sevenzip")
    seven_zip = find_sevenzip()
    if progress:
        progress(f"  7-Zip: {seven_zip}")

    archive = cache / "PCDOS71-sgtk_1_3_07.EXE"
    if progress:
        progress("downloading_sgtk")
    _download(
        SGTK_URL,
        archive,
        expected_size=SGTK_SIZE,
        expected_sha1=SGTK_SHA1,
        progress=progress,
    )

    extract_root = cache / "extract"
    if progress:
        progress("extracting_sgtk")
    if extract_root.exists() and force:
        shutil.rmtree(extract_root)
    needs_extract = not extract_root.exists() or not any(extract_root.iterdir())
    if needs_extract:
        _extract(seven_zip, archive, extract_root, progress=progress)
    else:
        if progress:
            progress(f"  reusing existing extract at {extract_root}")

    if progress:
        progress("locating_dos_files")
    dos_dir = _walk_find_dir(extract_root, "DOS")
    if dos_dir is None:
        raise ValidationError(
            f"Could not find a 'DOS' directory under {extract_root}. "
            "Inspect the extraction manually to confirm the SGTK layout."
        )
    if progress:
        progress(f"  found DOS files at: {dos_dir.relative_to(extract_root)}")

    vfd_src: Path | None = None
    for candidate in VFD_CANDIDATES:
        found = _walk_find(extract_root, candidate)
        if found is not None:
            vfd_src = found
            if progress:
                progress(f"  found install floppy: {found.relative_to(extract_root)}")
            break

    if progress:
        progress("staging_files")
    target.mkdir(parents=True, exist_ok=True)
    target_dos = target / "DOS"
    target_dos.mkdir(parents=True, exist_ok=True)

    staged = 0
    missing: list[str] = []
    for filename, expected in EXPECTED_SHA256.items():
        src = _walk_find(dos_dir, filename)
        if src is None:
            missing.append(filename)
            continue
        _copy_with_verification(
            src,
            target_dos / filename,
            expected_sha256=expected,
            progress=progress,
        )
        staged += 1

    vfd_name: str | None = None
    if vfd_src is not None:
        # Keep the original filename so dosforge's pcdos71 install-image
        # scan can pick it up via ``preferred_image_names``.
        dst = target / vfd_src.name
        shutil.copy2(vfd_src, dst)
        vfd_name = vfd_src.name
        if progress:
            progress(f"  staged: {dst.name}  ({vfd_src.stat().st_size:,} bytes)")

    if not keep_extract:
        # Leave the downloaded archive in place (cache hit on next run)
        # but reclaim the ~50 MB of extracted tree.
        try:
            shutil.rmtree(extract_root)
        except OSError:
            # Non-fatal: just means a future run will re-extract.
            pass

    # PC-DOS 2000 utility hydration (FULL profile extra). Looks for a
    # WinWorldPC ``IBM PC-DOS 2000 (3.5-1.44mb).7z`` next to the
    # pcdos71 dosassets dir — OR pre-extracted ``disk01.img``..
    # ``disk06.img`` install floppies in the same folder — and, when
    # present, merges its DOS utilities into ``target_dir/DOS/`` (SGTK
    # wins on conflict). Failures are informational only — the SGTK-only
    # set is always valid on its own.
    pcdos2000_added = 0
    pcdos2000_skipped = 0
    pcdos2000_archive_name: str | None = None
    pcdos2000_error: str | None = None
    if progress is not None:
        progress("hydrating_pcdos2000")
    try:
        from . import pcdos2000_extract as _p2k

        pcdos2000_dir = target.parent / "pcdos2000"
        source = _p2k.find_pcdos2000_source(pcdos2000_dir)
        if source is None:
            if progress is not None:
                progress(
                    f"  no PC-DOS 2000 source found in {pcdos2000_dir}; "
                    "skipping (download IBM PC-DOS 2000 from WinWorldPC and "
                    "place the .7z OR extracted disk01.img..disk06.img there "
                    "to enable EMM386, POWER, DEFRAG, BACKUP, DOSSHELL, etc.)"
                )
        else:
            label = source.name if source.is_file() else f"{source.name}/ (raw floppies)"
            if progress is not None:
                progress(f"  found PC-DOS 2000 source: {label}")
            pcdos2000_archive_name = label
            extracted_dos = _p2k.extract_pcdos2000_utilities(
                source,
                progress=progress,
            )
            pcdos2000_added, pcdos2000_skipped = _p2k.merge_pcdos2000_into_pcdos71_dos(
                extracted_dos,
                target / "DOS",
                progress=progress,
            )
    except ValidationError as exc:
        pcdos2000_error = str(exc)
        if progress is not None:
            progress(f"  PC-DOS 2000 hydration FAILED: {exc}")
    except Exception as exc:  # noqa: BLE001 - keep SGTK fetch healthy
        pcdos2000_error = f"unexpected: {exc!r}"
        if progress is not None:
            progress(f"  PC-DOS 2000 hydration FAILED (unexpected): {exc!r}")

    if progress:
        progress("done")

    return FetchResult(
        target_dir=target,
        staged_count=staged,
        total_count=len(EXPECTED_SHA256),
        missing=tuple(missing),
        vfd_filename=vfd_name,
        pcdos2000_added=pcdos2000_added,
        pcdos2000_skipped=pcdos2000_skipped,
        pcdos2000_archive=pcdos2000_archive_name,
        pcdos2000_error=pcdos2000_error,
    )
