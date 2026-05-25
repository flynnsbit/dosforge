# PyInstaller spec for the dosforge Windows *lite* portable bundle.
#
# Produces a structured onedir bundle under ``dist/dosforge/`` that ships:
#   - ``dosforge.exe``        — the launcher
#   - ``_internal/``          — Python runtime + vendor binaries (QEMU, mtools)
#   - ``dosassets/``          — per-mode readme stubs ONLY (no DOS binaries)
#
# The ``dosassets/`` directory is moved out of ``_internal/`` during the
# build so users can see and manage their own DOS install media alongside
# the launcher without digging into the internal Python runtime folder.
#
# DOS binary payloads (pcdos7, msdos622, compaq331, etc.) are NOT bundled.
# Users drop their own install media into ``dosassets/<mode>/`` and
# dosforge will find it via ``DOSFORGE_DOSASSETS_DIR`` (set at startup by
# the launcher).  FreeDOS auto-download still works out-of-the-box.
#
# Build from the repo root inside the project venv:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge-lite.spec --noconfirm
#
# Or use the helper script:
#
#   .\scripts\build-lite-bundle.ps1

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

# Import the shared vendor allowlist.  Same set of binaries goes into
# all three Windows variants (full / lite / cli) — DOSBox-X replaced
# qemu-system-i386's 135 MB stack with a 24 MB self-contained EXE.
sys.path.insert(0, str(SPEC_DIR))
from vendor_allowlist import VENDOR_ALLOWLIST  # noqa: E402

datas = []
binaries = []

vendor_bin = REPO_ROOT / "vendor" / "windows" / "bin"
if vendor_bin.is_dir():
    matched = 0
    for entry in vendor_bin.iterdir():
        if entry.is_file() and entry.name.lower() in VENDOR_ALLOWLIST:
            datas.append((str(entry), "vendor/windows/bin"))
            matched += 1
    expected = len(VENDOR_ALLOWLIST)
    if matched < expected:
        missing = sorted(
            n for n in VENDOR_ALLOWLIST
            if not (vendor_bin / n).exists()
        )
        raise SystemExit(
            f"vendor/windows/bin/ is missing {expected - matched} allowlist "
            f"files: {missing}.  Run scripts\\fetch-windows-vendor.py first."
        )
else:
    raise SystemExit(
        f"vendor/windows/bin/ is empty or missing at {vendor_bin}. "
        "Run scripts\\fetch-windows-vendor.py first."
    )

# Lite: only readme.txt stubs, no binary DOS payloads.
dosassets = REPO_ROOT / "dosassets"
for entry in dosassets.rglob("readme.txt"):
    rel = entry.relative_to(dosassets).parent
    target = "dosassets" if rel == Path(".") else f"dosassets/{rel.as_posix()}"
    datas.append((str(entry), target))

icons = REPO_ROOT / "assets" / "icons"
if icons.is_dir():
    for entry in icons.iterdir():
        if entry.is_file():
            datas.append((str(entry), "assets/icons"))

# Collect entire package trees (source, submodules, AND data files).
# textual ships ``.tcss`` stylesheets; rich ships theme data; py7zr ships
# headers; etc.  Plain ``hiddenimports`` only grabs the top-level
# module's ``__init__.py``, which is why earlier builds shipped only the
# ``dist-info`` directories and broke at first import.
hiddenimports = []
for _pkg in (
    "textual",
    "rich",
    "markdown_it",
    "mdit_py_plugins",
    "linkify_it",
    "uc_micro_py",
    "py7zr",
    "Cryptodome",
    "pyppmd",
    "pyzstd",
    "pybcj",
    "inflate64",
    "brotli",
    "multivolumefile",
    "texttable",
    "psutil",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(_pkg)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

# Pygments lexer used by Textual's syntax highlighting.
hiddenimports.append("pygments.lexers.python")

block_cipher = None

a = Analysis(
    [str(REPO_ROOT / "windows" / "dosforge_entry.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pyinstaller", "zstandard"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_path = icons / "dosforge.ico" if (icons / "dosforge.ico").is_file() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dosforge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="dosforge",
)

# Post-build: move dosassets/ out of _internal/ so it sits alongside
# dosforge.exe.  Users can then manage their DOS install media by
# browsing to the dosassets/ folder without digging into the Python
# runtime internals.
#
# This runs AFTER COLLECT has fully assembled the onedir bundle, so it
# is safe to move directories at this point — PyInstaller will not
# re-process the moved files.
import shutil as _shutil

_bundle_root = Path(DISTPATH) / "dosforge"
_src = _bundle_root / "_internal" / "dosassets"
_dst = _bundle_root / "dosassets"

if _src.is_dir():
    if _dst.exists():
        raise SystemExit(
            f"Post-build error: destination {_dst} already exists. "
            "Run with --noconfirm or delete the existing dist/dosforge/ first."
        )
    _shutil.move(str(_src), str(_dst))
    print(f"[dosforge-lite] moved dosassets/ out of _internal/ -> {_dst}")
