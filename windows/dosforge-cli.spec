# PyInstaller spec for the dosforge Windows *CLI-only* portable bundle.
#
# Produces the smallest possible Windows bundle WITHOUT the TUI.  Drops:
#
#   - All TUI Python packages (textual, rich, markdown_it stack, pygments)
#   - py7zr stack (Cryptodome, pyppmd, pyzstd, etc.) — .zip auto-extract
#     still works via stdlib zipfile; .7z archives are not supported
#   - qemu-system-i386.exe and its ~110 MB of GTK/SDL/codec DLLs
#   - 33 MB of orphan vendor files (Vulkan, swiftshader, etc.)
#
# Keeps:
#
#   - dosforge.exe launcher + Python runtime
#   - qemu-img.exe + mtools + their 28 transitively-required DLLs (~25 MB)
#   - DOSBox-X (~24 MB single self-contained EXE) — replaces
#     qemu-system-i386 for the 3 legacy DOS modes that need an emulator
#     to run SYS C: (compaq331, msdos33, msdos331)
#   - readme.txt stubs in dosassets/
#
# All 11 boot modes work in this bundle (DOSBox-X covers the legacy
# DOS modes that previously required ~135 MB of QEMU + DLL stack).
#
# Build:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge-cli.spec --noconfirm

from pathlib import Path
import sys

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

# Import the shared vendor allowlist (same as lite/full specs).
sys.path.insert(0, str(SPEC_DIR))
from vendor_allowlist import VENDOR_ALLOWLIST as VENDOR_CLI_ALLOWLIST  # noqa: E402
from spec_helpers import strip_bloat  # noqa: E402

datas = []
binaries = []

vendor_bin = REPO_ROOT / "vendor" / "windows" / "bin"
if vendor_bin.is_dir():
    matched = 0
    for entry in vendor_bin.iterdir():
        if entry.is_file() and entry.name.lower() in VENDOR_CLI_ALLOWLIST:
            datas.append((str(entry), "vendor/windows/bin"))
            matched += 1
    expected = len(VENDOR_CLI_ALLOWLIST)
    if matched < expected:
        missing = sorted(
            n for n in VENDOR_CLI_ALLOWLIST
            if not (vendor_bin / n).exists()
        )
        raise SystemExit(
            f"vendor/windows/bin/ is missing {expected - matched} expected "
            f"CLI-allowlist files: {missing}.  Run "
            "scripts\\fetch-windows-vendor.py first."
        )
else:
    raise SystemExit(
        f"vendor/windows/bin/ is empty or missing at {vendor_bin}. "
        "Run scripts\\fetch-windows-vendor.py first."
    )

# CLI bundle: only readme.txt stubs in dosassets/, no binary DOS payloads.
dosassets = REPO_ROOT / "dosassets"
for entry in dosassets.rglob("readme.txt"):
    rel = entry.relative_to(dosassets).parent
    target = "dosassets" if rel == Path(".") else f"dosassets/{rel.as_posix()}"
    datas.append((str(entry), target))

# No icons folder — TUI-only artwork.

# NO TUI packages here.  We intentionally do not collect_all() textual,
# rich, markdown_it, pygments, psutil, py7zr, Cryptodome, etc.  The CLI
# verbs do not import any of them.  ``dosforge tui`` will print the
# existing fallback message ("TUI requires textual, not available in
# this build").
hiddenimports: list[str] = []

# Filter out verified-stale datas (.dist-info dirs, setuptools, etc.).
# The CLI bundle excludes all the heavy TUI packages already so this is
# mostly a regression guard.
datas = strip_bloat(datas)
binaries = strip_bloat(binaries)

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
    # Aggressively exclude TUI/markup/p7zr packages so PyInstaller's
    # transitive analysis cannot drag them in even if some unused
    # import accidentally references them.
    excludes=[
        "tkinter",
        "pytest",
        "pyinstaller",
        "zstandard",
        "textual",
        "rich",
        "markdown_it",
        "mdit_py_plugins",
        "linkify_it",
        "uc_micro_py",
        "pygments",
        "psutil",
        "py7zr",
        "Cryptodome",
        "pycryptodomex",
        "pyppmd",
        "pyzstd",
        "pybcj",
        "inflate64",
        "brotli",
        "multivolumefile",
        "texttable",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    icon=None,
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

# Post-build cleanup (regression guard — CLI excludes Cryptodome so
# nothing should be removed here; this just ensures consistency).
from spec_helpers import post_build_cleanup  # noqa: E402
post_build_cleanup(Path(DISTPATH) / "dosforge")

# Post-build: move dosassets/ out of _internal/ so users can see the
# readmes (and drop their own DOS install media) without digging into
# the Python runtime folder.  Mirrors the lite spec's structured layout.
import shutil as _shutil

_bundle_root = Path(DISTPATH) / "dosforge"
_src = _bundle_root / "_internal" / "dosassets"
_dst = _bundle_root / "dosassets"

if _src.is_dir():
    if _dst.exists():
        raise SystemExit(
            f"Post-build error: destination {_dst} already exists. "
            "Run with --noconfirm or delete dist/dosforge/ first."
        )
    _shutil.move(str(_src), str(_dst))
    print(f"[dosforge-cli] moved dosassets/ out of _internal/ -> {_dst}")
