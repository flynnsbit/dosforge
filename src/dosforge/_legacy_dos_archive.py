"""Auto-extract a WinWorldPC-style DOS install archive to a cached IMG.

Many of the WinWorldPC mirrors of legacy DOS (Compaq DOS 2.x/3.x,
the older MS-DOS / PC-DOS releases) ship a single .7z or .zip archive
containing one or more raw .img / .ima floppies. dosforge's
descriptor-based install flow expects a usable raw image at descriptor
resolution time; this module bridges that gap by extracting the
archive on-demand and caching the result under the app cache dir.

Used by legacy DOS boot modes whose ``dosassets/<mode>/`` only holds
the .7z (the user did a "direct download" of the WinWorldPC archive
without unpacking). When the user has already extracted the IMG
files themselves, ``find_extracted_install_image`` short-circuits to
those without invoking py7zr.

Public surface:

* :func:`extract_legacy_dos_install_archive` — locate the .7z / .zip
  in an asset dir, extract it to ``<cache>/legacy-dos-archive/<hash>/``,
  return the path to the resulting bootable install IMG.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from .errors import DependencyError, ValidationError
from .paths import app_cache_dir

__all__ = [
    "DEFAULT_INSTALL_IMAGE_NAMES",
    "extract_legacy_dos_install_archive",
    "find_extracted_install_image",
]

# Names dosforge will accept as the "bootable install floppy" inside
# either the asset dir directly or an extracted archive subdir.
# Ordered most-preferred-first; the first match wins.
DEFAULT_INSTALL_IMAGE_NAMES: tuple[str, ...] = (
    "disk01.img",
    "DISK01.IMG",
    "disk01.ima",
    "DISK01.IMA",
    "disk1.img",
    "DISK1.IMG",
    "144US1.IMG",
    "install.img",
    "INSTALL.IMG",
)


def _walk_find_case_insensitive(root: Path, names: Iterable[str]) -> Path | None:
    """Find the first file under ``root`` matching any of ``names``.

    Comparison is case-insensitive and walks recursively (handles
    archives whose extracted contents nest under a top-level dir).
    Order of ``names`` matters — the first match wins.
    """
    if not root.is_dir():
        return None
    target_set = {name.upper() for name in names}
    # First try the immediate root for the common "user extracted .7z
    # straight into dosassets/<mode>/" case.
    for entry in root.iterdir():
        if entry.is_file() and entry.name.upper() in target_set:
            return entry
    # Fall back to recursive walk for archives that include a
    # top-level subdir (e.g. WinWorldPC's
    # ``<archive-name>/disk01.img`` layout).
    for entry in sorted(root.rglob("*")):
        if entry.is_file() and entry.name.upper() in target_set:
            return entry
    return None


def find_extracted_install_image(
    assets_dir: Path,
    candidate_names: Iterable[str] = DEFAULT_INSTALL_IMAGE_NAMES,
) -> Path | None:
    """Return the user-extracted install IMG inside ``assets_dir``, or None.

    Short-circuits ``extract_legacy_dos_install_archive`` when the
    user has already unpacked the archive themselves (the common case
    once they realize disk01.img is what matters).
    """
    return _walk_find_case_insensitive(assets_dir, candidate_names)


def _find_archive(assets_dir: Path) -> Path | None:
    """Pick the first .7z / .zip in ``assets_dir`` (non-recursive)."""
    if not assets_dir.is_dir():
        return None
    archives: list[Path] = []
    for entry in sorted(assets_dir.iterdir()):
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix in (".7z", ".zip"):
            archives.append(entry)
    return archives[0] if archives else None


def _extract_7z(archive: Path, dest: Path) -> None:
    """Extract ``archive`` (.7z) into ``dest`` using py7zr."""
    try:
        import py7zr
    except ImportError as exc:
        raise DependencyError(
            "py7zr is required to auto-extract .7z DOS install archives. "
            "Install with: pip install py7zr"
        ) from exc
    try:
        with py7zr.SevenZipFile(archive, mode="r") as sz:
            sz.extractall(path=dest)
    except Exception as exc:  # py7zr raises a few different exception types
        raise ValidationError(
            f"Failed to extract {archive.name} via py7zr: {exc}"
        ) from exc


def _extract_zip(archive: Path, dest: Path) -> None:
    """Extract ``archive`` (.zip) into ``dest``."""
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(path=dest)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValidationError(
            f"Failed to extract {archive.name} ({exc.__class__.__name__}): {exc}"
        ) from exc


def extract_legacy_dos_install_archive(
    assets_dir: Path,
    *,
    cache_root: Path | None = None,
    candidate_names: Iterable[str] = DEFAULT_INSTALL_IMAGE_NAMES,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Return a raw bootable install IMG for the legacy DOS in ``assets_dir``.

    Resolution order:

    1. If a raw IMG matching ``candidate_names`` is already present
       in ``assets_dir`` (user unpacked the archive themselves), use
       it verbatim.  No cache hit, no extraction.
    2. Otherwise, find the first .7z / .zip in ``assets_dir`` and
       extract it to ``<cache_root>/legacy-dos-archive/<archive-hash>/``
       (created on demand).  Cache hits when both the destination
       exists AND the archive's bytes haven't changed (SHA-256-keyed).
    3. After extraction, scan the result for the first match in
       ``candidate_names`` and return that path.

    Raises:

    * ``ValidationError`` when no archive or extracted IMG is found,
      or when the extracted tree doesn't contain a recognizable
      install image.
    * ``DependencyError`` when a .7z archive is found but py7zr is
      not importable.

    Cache marker layout (alongside the extraction dir):
    ``<cache>/legacy-dos-archive/<hash>.marker`` contains the
    archive's path + SHA-256, used to detect when the source archive
    has been updated.
    """

    def _log(msg: str) -> None:
        if progress is not None:
            progress(msg)

    direct = find_extracted_install_image(assets_dir, candidate_names)
    if direct is not None:
        _log(f"  using pre-extracted install image: {direct.name}")
        return direct

    archive = _find_archive(assets_dir)
    if archive is None:
        raise ValidationError(
            f"No install IMG or .7z/.zip archive found in {assets_dir}. "
            f"Drop one of {sorted({n.upper() for n in candidate_names})!r} "
            "OR a WinWorldPC archive into this directory."
        )

    cache = (cache_root or app_cache_dir()) / "legacy-dos-archive"
    cache.mkdir(parents=True, exist_ok=True)

    archive_bytes = archive.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()[:16]
    extracted = cache / f"{archive.stem[:32]}-{digest}"
    marker = cache / f"{archive.stem[:32]}-{digest}.marker"
    expected_marker = f"{archive.resolve()}\n{digest}\n"

    if extracted.is_dir() and marker.exists():
        try:
            if marker.read_text(encoding="ascii") == expected_marker:
                cached_img = find_extracted_install_image(extracted, candidate_names)
                if cached_img is not None:
                    _log(f"  using cached extraction: {extracted.name}")
                    return cached_img
        except OSError:
            pass

    if extracted.exists():
        shutil.rmtree(extracted)
    if marker.exists():
        try:
            marker.unlink()
        except OSError:
            pass
    extracted.mkdir(parents=True)

    suffix = archive.suffix.lower()
    _log(f"  extracting {archive.name} -> {extracted}")
    if suffix == ".7z":
        _extract_7z(archive, extracted)
    elif suffix == ".zip":
        _extract_zip(archive, extracted)
    else:  # defensive — _find_archive only returns .7z/.zip
        raise ValidationError(f"Unsupported archive format: {archive.suffix}")

    install_image = find_extracted_install_image(extracted, candidate_names)
    if install_image is None:
        raise ValidationError(
            f"{archive.name} extracted to {extracted} but no recognizable "
            f"install IMG (looked for: {sorted({n.upper() for n in candidate_names})!r}) "
            "was found in the result.  Inspect the extracted tree to confirm "
            "the archive layout."
        )

    marker.write_text(expected_marker, encoding="ascii")
    _log(f"  found install image: {install_image.relative_to(extracted)}")
    return install_image
