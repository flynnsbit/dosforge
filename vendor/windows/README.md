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

```powershell
# On Windows (or any host with Python 3.11+):
python scripts/fetch-windows-vendor.py
```

The script will refuse to run until the `REPLACE_WITH_*` placeholders
in `manifest.json` have been filled in with real values. The
recommended values for dosforge v0.3.0 are:

- **qemu**: weilnetz qemu-w64-setup-`<latest-stable-datestamp>`.exe
  (fetch the latest stable from <https://qemu.weilnetz.de/w64/>).
- **mtools**: mingw64 `mingw-w64-x86_64-mtools` package
  (latest from <https://packages.msys2.org/package/mingw-w64-x86_64-mtools>).

After fetching, run `python -m dosforge --version` from the repo root
on Windows to verify the bundle is functional.
