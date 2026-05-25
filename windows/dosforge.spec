# PyInstaller spec for the dosforge Windows portable bundle.
#
# Builds a onedir bundle under ``dist/dosforge/`` that ships:
#   - ``dosforge.exe`` — the launcher (entry: ``dosforge.cli:main``)
#   - ``_internal/`` — Python runtime + dependencies (textual, etc.)
#   - ``vendor/windows/bin/`` — bundled QEMU + mtools binaries
#   - ``dosassets/`` — FreeDOS userspace + per-mode readme stubs
#   - ``assets/icons/`` — application icons
#
# Build from the repo root inside the project venv:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge.spec --noconfirm

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
from spec_helpers import EXCLUDE_MODULES, strip_bloat, strip_hidden_imports  # noqa: E402

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

dosassets = REPO_ROOT / "dosassets"
for entry in dosassets.rglob("*"):
    if entry.is_file():
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

# Filter out verified-stale datas (Cryptodome.SelfTest, pip dist-info
# directories, setuptools leftovers, etc.).  See windows/spec_helpers.py
# for the full list and rationale.
datas = strip_bloat(datas)
binaries = strip_bloat(binaries)
hiddenimports = strip_hidden_imports(hiddenimports)

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
    excludes=["tkinter", "pytest", "pyinstaller", "zstandard", *EXCLUDE_MODULES],
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

# Post-build cleanup: remove .dist-info dirs + Cryptodome top-level
# subpackages that PyInstaller emits despite our excludes/strip_bloat
# filters (these come from PyInstaller's own metadata-handling and
# transitive import-graph walking after COLLECT).
from spec_helpers import post_build_cleanup  # noqa: E402
post_build_cleanup(Path(DISTPATH) / "dosforge")
