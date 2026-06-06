# dosforge windows-v0.6.4 — dosassets stays at the bundle root

Small but important Windows-bundle layout fix. **`dosassets/` now always
lives at the bundle root** (`dosforge\dosassets\`) — never under
`_internal\dosassets\`. The Python runtime stays in `_internal\`, but
anything users need to touch (install media drop-folders, per-mode
`readme.txt`) sits next to the EXEs where it's instantly discoverable
from File Explorer.

## What changed

- **`windows/dosforge_entry.py`** — Launcher no longer falls back to
  `<bundle>\_internal\dosassets\`. It probes only `<bundle>\dosassets\`
  (creating it if missing) and points `DOSFORGE_DOSASSETS_DIR` there.
- **`windows/dosforge.spec` + `windows/dosforge-cli.spec`** — Post-build
  hook that moves PyInstaller-staged datas out of `_internal\dosassets\`
  to the bundle root now **fails the build loudly** if PyInstaller
  didn't stage them, instead of silently shipping a bundle with no
  user-facing assets folder.
- **`scripts/cli-smoke.ps1`** — Smoke fallback updated to look at
  `<bundle>\dosassets\freedos\` instead of the legacy `_internal` path.

## Why this matters — PC-DOS 2000 hydration

In v0.6.2/v0.6.3 the PC-DOS 7.1 SGTK flow gained PC-DOS 2000 utility
hydration: drop the WinWorldPC IBM PC-DOS 2000 7z archive (or its
extracted floppy images) into `dosassets\pcdos2000\` and the
EMM386/POWER/DOSSHELL/DEFRAG/BACKUP/RESTORE/etc. utilities get merged
into `C:\DOS\` on FULL profile builds (SGTK wins on conflict).

On some Windows installs the launcher's old fallback would resolve
`DOSFORGE_DOSASSETS_DIR` to `<bundle>\_internal\dosassets\` instead of
the visible `<bundle>\dosassets\`, so users dropping their archive into
the obvious top-level folder saw the hydration step silently skip. The
new launcher only ever looks at the visible folder, and a misbuilt
bundle now hard-fails at build time instead of misbehaving at runtime.

## Carries forward

Everything from windows-v0.6.0 (every boot-mode × FAT combo validated
in 86Box) plus the post-v0.6.0 GUI/CLI improvements:

- PC-DOS 7.1 SGTK Fetch button in the desktop GUI (parity with the TUI).
- PC-DOS 2000 utility hydration for `pcdos71` FULL profile.
- Animated spinner on the Create+format button so users know the
  build is in flight.

## Build / run

```powershell
# Extract dosforge-0.6.4-windows-x64.zip somewhere convenient
cd dosforge

# Drop install media into dosassets\<mode>\ (now alongside the EXEs)
copy "C:\Downloads\IBM PC-DOS 2000 (3.5-1.44mb).7z" dosassets\pcdos2000\

.\dosforge-gui.exe       # desktop GUI
.\dosforge.exe tui       # textual TUI
.\dosforge.exe --help    # CLI reference
```

The `-cli` zip variant ships the same `dosforge.exe` and bundled
QEMU/mtools but drops the TUI + GUI dependencies.
