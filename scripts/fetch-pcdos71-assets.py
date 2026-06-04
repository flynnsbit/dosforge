"""Populate ``dosassets/pcdos71/`` from the IBM ServerGuide Scripting Toolkit.

PC-DOS 7.1 (the FAT32-capable IBM release) was only ever distributed
inside the IBM ServerGuide Scripting Toolkit (SGTK), DOS Edition,
v1.3.07. IBM's own support page no longer hosts the binary; this
script downloads the IBM-distributed installer from the Internet
Archive mirror, verifies it, and copies the files dosforge needs
(`tk_raid.vfd` plus `DOS/FORMAT32.COM` and the PC-DOS 7.1 system
files) into ``dosassets/pcdos71/`` in the layout
``pcdos71_profile`` expects.

Per-file SHA-256s come from the community patch repo
``github.com/Kreeblah/pcdos71-patch`` and are checked after
extraction. No binaries are committed to dosforge; the local
``dosassets/pcdos71/`` is gitignored.

Usage::

    python scripts/fetch-pcdos71-assets.py [--keep-extract] [--force]

Requirements: 7-Zip installed at one of the standard Windows paths
(or set ``DOSFORGE_SEVENZIP_EXE``); ``requests`` is not required —
this script uses ``urllib`` from the stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "dosassets" / "pcdos71"
CACHE_DIR = REPO_ROOT / "build" / "pcdos71-cache"

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
}

# Bootable install floppy candidates dosforge can use (preferred order).
# pcdos71_profile takes the first one that's actually present.
VFD_CANDIDATES = ("tk_raid.vfd", "tk_raid2.vfd", "install.vfd", "install.img")


def _find_sevenzip() -> Path:
    env = os.environ.get("DOSFORGE_SEVENZIP_EXE")
    if env and Path(env).is_file():
        return Path(env)
    for candidate in (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\7-Zip\7z.exe"),
    ):
        p = Path(candidate)
        if p.is_file():
            return p
    raise SystemExit(
        "7-Zip (7z.exe) not found. Install from https://www.7-zip.org/ "
        "or set DOSFORGE_SEVENZIP_EXE to the path."
    )


def _download(url: str, dest: Path, *, expected_size: int, expected_sha1: str) -> None:
    if dest.is_file() and dest.stat().st_size == expected_size:
        sha1 = _sha1(dest)
        if sha1.lower() == expected_sha1.lower():
            print(f"  cached: {dest.name} ({expected_size:,} bytes, SHA-1 verified)")
            return
        print(f"  cache stale (SHA-1 mismatch), redownloading")
        dest.unlink()
    print(f"  downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    actual_size = tmp.stat().st_size
    if actual_size != expected_size:
        raise SystemExit(
            f"download size mismatch: got {actual_size:,}, expected {expected_size:,}"
        )
    sha1 = _sha1(tmp)
    if sha1.lower() != expected_sha1.lower():
        raise SystemExit(
            f"SHA-1 mismatch on download: got {sha1}, expected {expected_sha1}"
        )
    tmp.replace(dest)
    print(f"  saved: {dest} ({actual_size:,} bytes, SHA-1 verified)")


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


def _extract(seven_zip: Path, archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    # `x` preserves directory structure (vs `e` which flattens).
    result = subprocess.run(
        [str(seven_zip), "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"7-Zip extraction failed (rc={result.returncode}):\n"
            f"  stdout: {result.stdout[-1500:]}\n"
            f"  stderr: {result.stderr[-1500:]}"
        )
    print(f"  extracted to {dest}")


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


def _copy_with_verification(src: Path, dst: Path, *, expected_sha256: str) -> None:
    actual = _sha256(src)
    if actual.lower() != expected_sha256.lower():
        raise SystemExit(
            f"SHA-256 mismatch for {src.name}:\n"
            f"  expected: {expected_sha256}\n"
            f"  actual:   {actual}\n"
            "Refusing to copy a file whose contents differ from the "
            "Kreeblah-published PC-DOS 7.1 reference hashes."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  staged: {dst.relative_to(REPO_ROOT)}  ({src.stat().st_size:,} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if the archive cache looks fresh.",
    )
    parser.add_argument(
        "--keep-extract",
        action="store_true",
        help="Leave the SGTK extraction under build/pcdos71-cache/ "
        "(default: delete after staging).",
    )
    args = parser.parse_args()

    print(f"Target: {TARGET_DIR}")
    print(f"Cache:  {CACHE_DIR}")
    seven_zip = _find_sevenzip()
    print(f"7-Zip:  {seven_zip}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive = CACHE_DIR / "PCDOS71-sgtk_1_3_07.EXE"
    print("\n== Stage 1: download SGTK self-extracting installer ==")
    _download(SGTK_URL, archive, expected_size=SGTK_SIZE, expected_sha1=SGTK_SHA1)

    extract_root = CACHE_DIR / "extract"
    if extract_root.exists() and args.force:
        shutil.rmtree(extract_root)
    needs_extract = not extract_root.exists() or not any(extract_root.iterdir())
    print("\n== Stage 2: extract with 7-Zip ==")
    if needs_extract:
        _extract(seven_zip, archive, extract_root)
    else:
        print(f"  reusing existing extract at {extract_root}")

    print("\n== Stage 3: locate SGTK DOS files ==")
    dos_dir = _walk_find_dir(extract_root, "DOS")
    if dos_dir is None:
        raise SystemExit(
            f"Could not find a 'DOS' directory under {extract_root}. "
            "Inspect the extraction manually to confirm the SGTK layout."
        )
    print(f"  found DOS files at: {dos_dir.relative_to(extract_root)}")

    vfd_src: Path | None = None
    for candidate in VFD_CANDIDATES:
        found = _walk_find(extract_root, candidate)
        if found is not None:
            vfd_src = found
            print(f"  found install floppy: {found.relative_to(extract_root)}")
            break

    print("\n== Stage 4: stage files into dosassets/pcdos71/ ==")
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    target_dos = TARGET_DIR / "DOS"
    target_dos.mkdir(parents=True, exist_ok=True)

    staged = 0
    missing: list[str] = []
    for filename, expected in EXPECTED_SHA256.items():
        src = _walk_find(dos_dir, filename)
        if src is None:
            missing.append(filename)
            continue
        _copy_with_verification(src, target_dos / filename, expected_sha256=expected)
        staged += 1

    if vfd_src is not None:
        # Keep the original filename so dosforge's pcdos71 install-image
        # scan can pick it up via preferred_image_names.
        dst = TARGET_DIR / vfd_src.name
        shutil.copy2(vfd_src, dst)
        print(f"  staged: {dst.relative_to(REPO_ROOT)}  ({vfd_src.stat().st_size:,} bytes)")

    print("\n== Summary ==")
    print(f"  DOS files staged:    {staged}/{len(EXPECTED_SHA256)}")
    if missing:
        print(f"  MISSING (not in SGTK extract):")
        for name in missing:
            print(f"    - {name}")
    if vfd_src is None:
        print(
            "  NO pre-built bootable VFD found in the SGTK. The toolkit's\n"
            "  manual notes 'bootable disks are created using the included\n"
            "  tool scripts.' You have two options:\n"
            "    (a) Run the SGTK's MAKEDISK script under DOSBox-X to\n"
            "        produce a bootable PC-DOS 7.1 floppy. See dosforge's\n"
            "        _pcdos7_loaddskf.py for the analogous DOSBox-X-driven\n"
            "        approach used for PC-DOS 7.0.\n"
            "    (b) Apply the github.com/Kreeblah/pcdos71-patch batch file\n"
            "        to dosassets/pcdos2000/disk01.img (after mounting it\n"
            "        in DOSBox-X) and copy the resulting patched disk\n"
            "        here as install.img.\n"
            "  pcdos71_profile won't accept dosassets/pcdos71/ until a\n"
            "  bootable VFD is in place."
        )

    if not args.keep_extract:
        shutil.rmtree(extract_root, ignore_errors=True)
        print(f"  cleaned up {extract_root}")

    print(f"\n  Result: dosassets/pcdos71/ now contains:")
    for entry in sorted(TARGET_DIR.rglob("*")):
        if entry.is_file():
            rel = entry.relative_to(TARGET_DIR)
            print(f"    {rel}  ({entry.stat().st_size:,} bytes)")

    if missing or vfd_src is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
