# PyInstaller spec for the dosforge Windows portable bundle (full).
#
# Builds a onedir bundle under ``dist/dosforge/`` containing TWO launchers
# that share one ``_internal/`` Python runtime:
#
#   - ``dosforge.exe``      — CLI-only launcher (no TUI, no GUI imports).
#                             Run with no arguments to see help + examples.
#   - ``dosforge-gui.exe``  — windowed (``console=False``) GUI launcher
#                             (tkinter + sv_ttk; no TUI fallback).
#
# Both EXEs run the same entry script (windows/dosforge_entry.py) which
# dispatches based on the EXE's filename. ONE Analysis covers both
# entry points, so dependencies aren't duplicated (the dual-Analysis
# approach attempted in v0.5.0-gui-pre3 bloated the bundle to 480 MB
# because PE-import scanning runs per-Analysis).
#
# Bundles vendor binaries (QEMU, mtools), the full DOS install media in
# dosassets/, and icons. Excludes the textual/rich/pygments TUI stack —
# neither launcher needs it.
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
# the runtime deps that need them:
#   - py7zr (and its compression backends): used to extract DOS install
#     media archives shipped in dosassets/.
#   - sv_ttk: Sun Valley ttk theme used by the GUI launcher.
hiddenimports = []
for _pkg in ("py7zr", "Cryptodome", "pyppmd", "pyzstd", "pybcj", "inflate64",
             "brotli", "multivolumefile", "texttable", "sv_ttk"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(_pkg)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

# tkinter is imported lazily by the GUI launcher (and by the legacy
# native file picker); make PyInstaller bundle it explicitly.
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
    # No launcher needs the TUI: ``dosforge.exe`` is CLI-only and
    # ``dosforge-gui.exe`` has no TUI fallback. Drop the whole textual
    # stack so we don't ship ~15-20 MB of unused Python source.
    excludes=[
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
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Console CLI launcher.
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

# Windowed GUI launcher (no console flash).
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
