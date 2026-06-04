# PyInstaller spec for the dosforge Windows portable bundle (full).
#
# Builds a onedir bundle under ``dist/dosforge/`` containing TWO
# launchers that share one ``_internal/`` Python runtime:
#
#   - ``dosforge.exe``      — console launcher. Run with no arguments
#                             to see the help + examples. Subcommands
#                             include ``tui`` (launch the Textual TUI),
#                             ``gui`` (launch the desktop GUI),
#                             ``create``, ``mount``, ``ls``, etc.
#   - ``dosforge-gui.exe``  — windowed (``console=False``) GUI launcher
#                             (tkinter + sv_ttk; no TUI fallback).
#
# Both EXEs run the same entry script (windows/dosforge_entry.py),
# which dispatches based on the EXE filename and on whether the
# textual TUI is bundled. ONE Analysis covers both entry points so
# dependencies aren't duplicated.
#
# Bundles vendor binaries (QEMU, mtools, DOSBox-X), the dosassets
# folder skeleton (per-mode readmes + committed FreeDOS userspace),
# icons, AND the full textual/rich TUI stack so ``dosforge tui`` works.
# A separate ``windows/dosforge-cli.spec`` produces a slim CLI-only
# bundle that excludes both the TUI and GUI runtimes for users who
# only need the command-line verbs.
#
# Build from the repo root inside the project venv:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

datas = []
binaries = []

vendor_bin = REPO_ROOT / "vendor" / "windows" / "bin"
if vendor_bin.is_dir():
    for entry in vendor_bin.rglob("*"):
        if entry.is_file():
            datas.append((str(entry), "vendor/windows/bin"))
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

# Collect entire package trees (source, submodules, AND data files) for
# runtime deps that ship their own non-Python assets.
#
# * py7zr + compression backends: extract DOS install media archives.
# * sv_ttk: Sun Valley ttk theme (image sprites + Tcl scripts).
# * textual + rich + markdown_it + pygments: power the TUI launched
#   via ``dosforge tui``. Without these the TUI subcommand can't import.
hiddenimports = []
for _pkg in (
    "py7zr",
    "Cryptodome",
    "pyppmd",
    "pyzstd",
    "pybcj",
    "inflate64",
    "brotli",
    "multivolumefile",
    "texttable",
    "sv_ttk",
    "textual",
    "rich",
    "markdown_it",
    "mdit_py_plugins",
    "linkify_it",
    "uc_micro_py",
    "psutil",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(_pkg)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

# Pygments lexer used by Textual's syntax highlighting.
hiddenimports.append("pygments.lexers.python")

# tkinter is imported lazily by the GUI launcher and by the legacy
# native file picker; make PyInstaller bundle it explicitly.
hiddenimports.extend([
    "tkinter",
    "tkinter.filedialog",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.font",
])

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
    excludes=["pytest", "pyinstaller", "zstandard"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Console launcher (CLI + TUI + GUI all accessible).
exe_cli = EXE(
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

# Windowed GUI launcher (no console flash, no TUI fallback).
exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dosforge-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe_cli,
    exe_gui,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="dosforge",
)

# Post-build: move dosassets/ out of _internal/ so the per-mode folders
# (and their readme.txt instructions) sit alongside the EXEs. Users can
# then drop their install media into dosassets/<mode>/ without having
# to dig into the Python runtime folder.
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
    print(f"[dosforge] moved dosassets/ out of _internal/ -> {_dst}")
