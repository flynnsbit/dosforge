# dosforge windows-v0.6.5 — PC-DOS 2000 hydration parity with Linux

Fixes the Windows bundle's silent PC-DOS 2000 hydration skip. The
`dosforge-gui.exe` "Fetch PC-DOS 7.1 (SGTK) assets" button now mixes
in the IBM PC-DOS 2000 utilities (EMM386, POWER, DOSSHELL, DEFRAG,
BACKUP, RESTORE, UNDELETE, HELP, INTERLNK/INTERSVR, etc.) on the
Windows side too, matching the Linux flow.

## Two missing pieces, both fixed

### 1. The bundle had no `dosbox-x.exe`

PC-DOS 2000 ships its DOS utilities packed inside IBM FTCOMP archives
(`DOS1`..`DOS4`, `SHELL1`, `SHELL2`) that only `UNPACK2.EXE` can
expand, and the only sane way to run `UNPACK2.EXE` from a Python
script is inside a DOSBox-X sandbox. The Windows vendor manifest
shipped `qemu` + `mtools` but **not** `dosbox-x`, so the hydration
step silently failed with `ValidationError: requires DOSBox-X on PATH`.

Added DOSBox-X v2026.06.02 (mingw64 portable) to
`vendor/windows/manifest.json`. CI's `scripts/fetch-windows-vendor.py`
now stages `dosbox-x.exe` under `vendor\windows\bin\`. The Windows
backend already had `dosbox-x` in `_KNOWN_BUNDLED_TOOLS` — once the
exe is present, `tool_path("dosbox-x")` resolves to it automatically.

### 2. The hydration code required a `.7z` archive

The previous extraction code only accepted the WinWorldPC
`IBM PC-DOS 2000 (3.5-1.44mb).7z` archive — it 7z-extracted that to
get `disk01.img`..`disk06.img`, then mcopied utilities off each
floppy. Users who'd already extracted their copy and dropped the
loose `.img` files into `dosassets\pcdos2000\` got a silent skip
because `find_pcdos2000_archive()` only matched `.7z` / `.zip`.

`pcdos2000_extract.py` now accepts **either** the archive OR a
directory containing the six raw install floppies:

- New `find_pcdos2000_source()` returns the archive when present,
  falls through to the loose-IMG directory when the dir holds at
  least 5 of `disk01.img`..`disk06.img`.
- `extract_pcdos2000_utilities()` skips the 7z step when handed a
  directory — straight to the mcopy → UNPACK2 → blacklist pipeline.
- Cache stamp for the directory case is a stable
  SHA-256-of-(name, size, first-64KB) hash of every disk so re-runs
  with the same six floppies are a cache hit.
- 7-Zip is no longer required when the user has pre-extracted IMGs.

## Carries forward

Everything from windows-v0.6.4 (dosassets at bundle root, no
`_internal/dosassets/` fallback) plus all prior windows-v0.6.x fixes.

## Drop locations on Windows

```
dosforge\
├── dosforge.exe
├── dosforge-gui.exe
├── dosassets\
│   ├── pcdos71\       ← SGTK PC-DOS 7.10 sources (auto-fetched)
│   ├── pcdos2000\     ← drop EITHER the WinWorldPC .7z OR
│   │   │                disk01.img..disk06.img directly here
│   │   ├── disk01.img
│   │   ├── disk02.img
│   │   └── …
│   └── …
└── _internal\         ← Python runtime + vendor binaries
    └── vendor\windows\bin\
        ├── dosbox-x.exe   (NEW)
        ├── qemu-img.exe
        ├── mformat.exe
        └── …
```

## What hydration produces

PC-DOS 7.1 FULL profile builds go from ~40 SGTK files in `C:\DOS\` to
~138 files after hydration. SGTK always wins on filename conflict
(IBMBIO.COM, IBMDOS.COM, COMMAND.COM, HIMEM.SYS, FORMAT.COM etc.
keep their PC-DOS 7.10 versions); only PC-DOS 2000 utilities that
the SGTK omits get pulled in.

Blacklist (never copied, even from PC-DOS 2000): PenDOS handwriting
(`PEN*.EXE`, `PINK.EXE`, `PMOUSE.EXE`, `PSYS.EXE`, `PENDOS.*`),
Stacker disk compression (`DBLSPACE.*`, `STACKER.*`), and IBM
Antivirus 1998 signature databases.
