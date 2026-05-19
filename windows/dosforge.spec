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

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

datas = []

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

hiddenimports = [
    "textual",
    "textual.app",
    "textual.widgets",
    "textual.widgets._directory_tree",
    "textual.css",
    "textual.css.parse",
    "rich",
    "rich.console",
    "rich.text",
    "linkify_it",
    "uc_micro_py",
    "mdit_py_plugins",
    "markdown_it",
    "pygments.lexers.python",
    # py7zr + its compression backends (pure-Python entry points; some
    # codecs live in C extensions PyInstaller's analysis won't follow).
    "py7zr",
    "py7zr.callbacks",
    "py7zr.compressor",
    "py7zr.cli",
    "pycryptodomex",
    "Cryptodome",
    "Cryptodome.Cipher",
    "Cryptodome.Cipher.AES",
    "Cryptodome.Hash",
    "Cryptodome.Hash.SHA256",
    "Cryptodome.Random",
    "Cryptodome.Util",
    "Cryptodome.Util.Padding",
    "multivolumefile",
    "texttable",
    "pyppmd",
    "pyzstd",
    "pybcj",
    "inflate64",
    "brotli",
    "psutil",
]

block_cipher = None

a = Analysis(
    [str(REPO_ROOT / "windows" / "dosforge_entry.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
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
