# PyInstaller spec for the dosforge Windows portable bundle (lite).
#
# Same two-launcher layout as ``dosforge.spec``: ``dosforge.exe`` is the
# console CLI launcher (no TUI, no GUI imports), ``dosforge-gui.exe`` is
# the windowed GUI launcher. Both share one ``_internal/`` because they
# dispatch from the same entry script based on EXE filename.
#
# Lite ships only the per-mode ``readme.txt`` stubs in ``dosassets/``;
# users drop their own DOS install media in there. ``dosassets/`` is
# moved out of ``_internal/`` at the end of the build so the user can
# manage it alongside the EXEs.
#
# Build:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge-lite.spec --noconfirm

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

hiddenimports = []
for _pkg in ("py7zr", "Cryptodome", "pyppmd", "pyzstd", "pybcj", "inflate64",
             "brotli", "multivolumefile", "texttable", "sv_ttk"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(_pkg)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

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

# Post-build: move dosassets/ out of _internal/ so users can manage
# their DOS install media alongside the EXEs.
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
