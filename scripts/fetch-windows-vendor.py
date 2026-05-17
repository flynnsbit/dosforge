"""Fetch + verify Windows vendor binaries into ``vendor/windows/bin/``.

Reads ``vendor/windows/manifest.json``, downloads each component's
upstream archive, verifies its SHA-256, and extracts the required
``.exe`` / ``.dll`` files into ``vendor/windows/bin/``.

Cross-platform: runs on Linux, macOS, or Windows. Designed to be
invoked from CI (GitHub Actions ``windows-latest``) and from a
developer machine.

Usage:

    python scripts/fetch-windows-vendor.py [--manifest PATH] [--force]

The script refuses to run until the ``REPLACE_WITH_*`` placeholders
in the manifest have been replaced with real values. See
``vendor/windows/README.md`` for the recommended values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "vendor" / "windows" / "manifest.json"
BIN_DIR = REPO_ROOT / "vendor" / "windows" / "bin"
LICENSES_DIR = REPO_ROOT / "vendor" / "windows" / "licenses"


class ManifestError(RuntimeError):
    pass


def _check_for_placeholders(manifest: dict[str, Any]) -> None:
    """Refuse to fetch if any REPLACE_WITH_* token remains in the manifest."""

    flat = json.dumps(manifest)
    if "REPLACE_WITH_" in flat:
        raise ManifestError(
            "vendor/windows/manifest.json still contains REPLACE_WITH_* "
            "placeholders. Populate version_pin, download_url, and "
            "expected_sha256 for every component first. See "
            "vendor/windows/README.md for guidance.",
        )


def _download(url: str, dest: Path) -> None:
    print(f"  downloading {url}")
    try:
        with urllib.request.urlopen(url) as response, dest.open("wb") as out:
            shutil.copyfileobj(response, out)
    except urllib.error.URLError as exc:  # pragma: no cover - network only
        raise ManifestError(f"download failed: {url}: {exc}") from exc


def _verify_sha256(path: Path, expected: str) -> None:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    actual = hasher.hexdigest()
    if actual.lower() != expected.lower():
        raise ManifestError(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}",
        )


def _extract_zip(archive: Path, extracts: list[dict[str, str]], staging: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(staging)


def _extract_tar(archive: Path, extracts: list[dict[str, str]], staging: Path, *, compression: str) -> None:
    mode = {"gz": "r:gz", "bz2": "r:bz2", "xz": "r:xz", "zst": "r|zst"}[compression]
    if compression == "zst":
        # Python's stdlib tarfile gained zstd support in 3.14; until
        # then, decode via zstandard. The dev/build host should have
        # the ``zstandard`` PyPI package installed.
        try:
            import zstandard  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - install-time
            raise ManifestError(
                "Decoding *.zst archives requires the 'zstandard' package. "
                "Install it with: pip install zstandard",
            ) from exc
        dctx = zstandard.ZstdDecompressor()
        with archive.open("rb") as compressed, tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as plain:
            dctx.copy_stream(compressed, plain)
            plain_path = Path(plain.name)
        try:
            with tarfile.open(plain_path, "r:") as tf:
                tf.extractall(staging)
        finally:
            plain_path.unlink(missing_ok=True)
        return
    with tarfile.open(archive, mode) as tf:
        tf.extractall(staging)


def _extract_innosetup(archive: Path, extracts: list[dict[str, str]], staging: Path) -> None:
    """Extract an Inno Setup installer (.exe) using innoextract.

    Requires ``innoextract`` on PATH (apt-get install innoextract /
    brew install innoextract / scoop install innoextract).
    """

    if not shutil.which("innoextract"):
        raise ManifestError(
            "Extracting Inno Setup installers requires the 'innoextract' tool. "
            "Install it with your package manager (apt-get install innoextract).",
        )
    import subprocess

    subprocess.run(
        ["innoextract", "--silent", "--output-dir", str(staging), str(archive)],
        check=True,
    )


def _stage_extracts(component: dict[str, Any], staging: Path) -> None:
    """Copy the requested files from ``staging`` into ``vendor/windows/bin/``."""

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for spec in component["extracts"]:
        if "from_in_archive_glob" in spec:
            pattern = spec["from_in_archive_glob"]
            target_dir = BIN_DIR / spec.get("to_in_bin_dir", ".")
            target_dir = target_dir.resolve()
            matches = list(staging.rglob(pattern))
            if not matches:
                raise ManifestError(
                    f"{component['name']}: no archive entries matched glob '{pattern}'",
                )
            for match in matches:
                dest = target_dir / match.name
                shutil.copy2(match, dest)
                print(f"    staged {dest.relative_to(REPO_ROOT)}")
        else:
            from_path = spec["from_in_archive"]
            to_name = spec["to_in_bin"]
            candidates = list(staging.rglob(Path(from_path).name))
            if not candidates:
                raise ManifestError(
                    f"{component['name']}: archive missing '{from_path}'",
                )
            # Prefer the candidate whose tail matches ``from_path``.
            best = next(
                (c for c in candidates if str(c).endswith(from_path.replace("/", "\\")) or str(c).endswith(from_path)),
                candidates[0],
            )
            dest = BIN_DIR / to_name
            shutil.copy2(best, dest)
            print(f"    staged {dest.relative_to(REPO_ROOT)}")


def _stage_license(component: dict[str, Any], staging: Path) -> None:
    """Copy any LICENSE / COPYING text discovered in the archive."""

    LICENSES_DIR.mkdir(parents=True, exist_ok=True)
    for license_name in ("LICENSE", "COPYING", "LICENSE.txt", "COPYING.txt"):
        for match in staging.rglob(license_name):
            dest = LICENSES_DIR / f"{component['name']}-{license_name}"
            shutil.copy2(match, dest)
            print(f"    staged {dest.relative_to(REPO_ROOT)}")
            return


def fetch_component(component: dict[str, Any], *, cache_dir: Path, force: bool) -> None:
    name = component["name"]
    url = component["download_url"]
    expected_sha = component["expected_sha256"]
    archive_format = component["archive_format"]

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / Path(url).name
    if archive_path.exists() and not force:
        print(f"[{name}] using cached {archive_path.name}")
    else:
        print(f"[{name}] fetching")
        _download(url, archive_path)

    print(f"[{name}] verifying SHA-256")
    _verify_sha256(archive_path, expected_sha)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        print(f"[{name}] extracting ({archive_format})")
        if archive_format == "zip":
            _extract_zip(archive_path, component["extracts"], staging)
        elif archive_format.startswith("tar_") or archive_format in {"zstandard_tar"}:
            compression = {
                "tar_gz": "gz",
                "tar_bz2": "bz2",
                "tar_xz": "xz",
                "zstandard_tar": "zst",
            }[archive_format]
            _extract_tar(archive_path, component["extracts"], staging, compression=compression)
        elif archive_format == "innosetup":
            _extract_innosetup(archive_path, component["extracts"], staging)
        else:
            raise ManifestError(f"unknown archive_format: {archive_format}")
        print(f"[{name}] staging artifacts")
        _stage_extracts(component, staging)
        _stage_license(component, staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=REPO_ROOT / ".vendor-cache")
    parser.add_argument("--force", action="store_true", help="redownload even if cached")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    manifest = json.loads(args.manifest.read_text())
    try:
        _check_for_placeholders(manifest)
        for component in manifest.get("components", []):
            fetch_component(component, cache_dir=args.cache_dir, force=args.force)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nAll components staged under vendor/windows/bin/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
