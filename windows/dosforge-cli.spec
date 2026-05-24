# PyInstaller spec for the dosforge Windows *CLI-only* portable bundle.
#
# Produces the absolute minimum Windows bundle that retains 8 of the 11
# boot modes without the TUI.  Drops:
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
#   - readme.txt stubs in dosassets/
#
# Lost boot modes (these need qemu-system-i386 to run an install
# diskette and call SYS C:): compaq331, msdos33, msdos331.
#
# Build:
#
#   .\.venv\Scripts\python -m PyInstaller windows\dosforge-cli.spec --noconfirm

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

# Allowlist of vendor files that qemu-img.exe + mtools need.
# Empirically verified via PE-import transitive closure (see
# C:\Temp\trace_dll_closure.py and plan.md Phase 11).
VENDOR_CLI_ALLOWLIST = frozenset(
    name.lower()
    for name in (
        # EXEs
        "qemu-img.exe",
        "mformat.exe",
        "mcopy.exe",
        "mattrib.exe",
        "mdir.exe",
        "mtype.exe",
        "mdel.exe",
        "mmd.exe",
        # Direct + transitive DLL dependencies (28 files, ~19.5 MB)
        "libbrotlicommon.dll",
        "libbrotlidec.dll",
        "libbrotlienc.dll",
        "libbz2-1.dll",
        "libcrypto-3-x64.dll",
        "libcurl-4.dll",
        "libffi-8.dll",
        "libgcc_s_seh-1.dll",
        "libglib-2.0-0.dll",
        "libgmp-10.dll",
        "libgnutls-30.dll",
        "libhogweed-6.dll",
        "libiconv-2.dll",
        "libidn2-0.dll",
        "libintl-8.dll",
        "libnettle-8.dll",
        "libnfs-14.dll",
        "libp11-kit-0.dll",
        "libpcre2-8-0.dll",
        "libpsl-5.dll",
        "libssh.dll",
        "libssh2-1.dll",
        "libssp-0.dll",
        "libtasn1-6.dll",
        "libunistring-5.dll",
        "libwinpthread-1.dll",
        "libzstd.dll",
        "zlib1.dll",
    )
)

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
