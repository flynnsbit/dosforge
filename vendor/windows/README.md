# Windows bundled binaries

`vendor/windows/bin/` is **not** version-controlled. It is populated
at build time by `scripts/fetch-windows-vendor.py`, which reads
`vendor/windows/manifest.json`, downloads each upstream archive,
verifies its SHA-256, and extracts the required binaries.

## Layout after fetch

```
vendor/windows/
├── bin/                          # auto-populated, .gitignore'd
│   ├── qemu-img.exe              # from qemu-w64
│   ├── qemu-system-i386.exe      # from qemu-w64
│   ├── *.dll                     # qemu runtime DLLs
│   ├── mformat.exe               # from MSYS2 mtools
│   ├── mcopy.exe                 # from MSYS2 mtools
│   ├── mattrib.exe               # from MSYS2 mtools
│   ├── mdir.exe                  # from MSYS2 mtools
│   ├── mtype.exe                 # from MSYS2 mtools
│   └── mdel.exe                  # from MSYS2 mtools
├── licenses/                     # GPL / LGPL license texts (auto-populated)
│   ├── qemu-LICENSE
│   └── mtools-COPYING
├── manifest.json                 # version pins + URLs + SHA-256s
├── NOTICES.txt                   # third-party attribution
└── README.md                     # this file
```

## Provenance and license

| Binary                  | Upstream            | License           |
|-------------------------|---------------------|-------------------|
| `qemu-img.exe`          | qemu-w64 (S. Weil)  | GPL-2.0-only      |
| `qemu-system-i386.exe`  | qemu-w64 (S. Weil)  | GPL-2.0-only      |
| qemu runtime DLLs       | qemu-w64 (S. Weil)  | GPL-2.0 / LGPL    |
| `mformat.exe` etc.      | MSYS2 mtools        | GPL-3.0-or-later  |

The dosforge MIT license **does not** override these upstream
licenses. Redistributing the dosforge installer with these binaries
included is GPL-compliant because the dosforge installer is itself
distributed under the same GPL licenses (we ship a clear NOTICES.txt
and the original license texts under `licenses/`).

Users who prefer to avoid bundling GPL binaries can use the
`--no-vendor` build mode (TODO Phase 6) which requires them to
install the dependencies separately.

## Populating

### Host prerequisites

Before running the fetch script, install the host tools used to
download and unpack the upstream archives:

```powershell
# One-line install via winget (Python 3.12 + 7-Zip + innoextract):
.\scripts\install-windows-prereqs.ps1
```

What the script installs (and why):

| Tool | winget id | Why |
|---|---|---|
| Python 3.12 | `Python.Python.3.12` | dosforge requires `>= 3.11`; tested on 3.12. |
| 7-Zip 23+ | `7zip.7zip` | The current upstream QEMU installer for Windows is now **NSIS-format** (qemu-w64-setup-YYYYMMDD.exe). Modern 7-Zip can extract NSIS payloads natively; older 7-Zip 19.x cannot. |
| innoextract | `dscharrer.innoextract` | Fallback for legacy Inno-Setup QEMU installers. The fetch script auto-picks between 7-Zip (NSIS) and innoextract (Inno Setup) based on the manifest's `archive_format` field, so having both installed is the most flexible setup. |

The script is idempotent — it skips packages already present and only
re-checks the install paths. It does not require admin (winget installs
to the user profile by default).

### Fetching the vendor binaries

```powershell
# On Windows (or any host with Python 3.11+):
python scripts/fetch-windows-vendor.py
```

The script will refuse to run until the `REPLACE_WITH_*` placeholders
in `manifest.json` have been filled in with real values. The
recommended values for dosforge v0.3.0 are:

- **qemu**: weilnetz `qemu-w64-setup-<latest-stable-datestamp>.exe`
  (fetch the latest stable from <https://qemu.weilnetz.de/w64/>).
  `archive_format` is `"nsis"` for the modern installer (May 2026+);
  older releases used `"innosetup"`.
- **mtools**: mingw64 `mingw-w64-x86_64-mtools` package
  (latest from <https://packages.msys2.org/package/mingw-w64-x86_64-mtools>).
  Use `https://repo.msys2.org/mingw/mingw64/...` for the download URL
  — the `mirror.msys2.org` host hits a Cloudflare challenge that
  blocks scripted downloads.

After fetching, run `python -m dosforge --version` from the repo root
on Windows to verify the bundle is functional.

### End-to-end bootstrap (from a fresh clone)

```powershell
git clone git@github.com:flynnsbit/dosforge.git
cd dosforge

# 1. Install host prereqs (idempotent — safe to re-run)
.\scripts\install-windows-prereqs.ps1

# 2. Open a NEW shell so the freshly-installed Python is on PATH
#    (or refresh PATH from registry in this shell)

# 3. Project venv + Python deps
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pip install zstandard            # needed by the fetcher for *.pkg.tar.zst

# 4. Fill in vendor/windows/manifest.json with current upstream
#    versions + SHA-256s (see above)

# 5. Fetch + extract the bundled binaries (~250 MB of downloads,
#    ~170 MB extracted into vendor/windows/bin/)
python scripts/fetch-windows-vendor.py

# 6. Smoke-test
pytest tests/test_platform_windows.py tests/test_core_modules.py -v
```
