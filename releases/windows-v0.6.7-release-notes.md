# dosforge v0.6.7 — Windows

**Root-cause fix for PC-DOS 7.1 FULL profile hydration on Windows.**

## What changed

The Windows bundles in v0.6.5 and v0.6.6 shipped `dosbox-x.exe` alone,
without the support files DOSBox-X needs to start (`dosbox-x.reference.conf`,
`languages/`, `glshaders/`, `drivez/`, `inpoutx64.dll`, `FREECG98.BMP`,
font files). The EXE silently exited on startup, so PC-DOS 2000 utility
hydration never ran — `C:\DOS\` ended up with only the 42 SGTK system
files instead of the ~138 you get with PC-DOS 2000 mixed in.

v0.6.7 ships the **full DOSBox-X mingw portable tree** (47 MB) under
`vendor/windows/bin/dosbox-x/` so the EXE finds its resources at startup.

## Verifying the fix

1. Download `dosforge-0.6.7-windows-x64.zip` from this release.
2. Unzip and drop your raw PC-DOS 2000 install floppies
   (`disk01.img`..`disk06.img`) into `dosforge\dosassets\pcdos2000\`.
3. Launch `dosforge-gui.exe`, select boot mode **PC-DOS 7.1 (SGTK)**
   with the **FULL** profile and at least 1 GiB.
4. Click **Fetch PC-DOS 7.1 (SGTK) assets** — the log should now show
   `unpacking DOS1, DOS2, …, SHELL2 via DOSBox-X` followed by
   `merged PC-DOS 2000 utilities: NN added, MM skipped (SGTK wins)`.
5. Create the VHD — `C:\DOS\` should contain ~138 files including
   `EMM386.EXE`, `POWER.EXE`, `DOSSHELL.EXE`, `DEFRAG.EXE`,
   `BACKUP.EXE`, `RESTORE.EXE`, and the other PC-DOS 2000 tools.

## Authenticity rule reminder

The PC-DOS 2000 hydration is the **one** approved exception to the
no-cross-DOS-borrowing rule: PC-DOS 2000 utilities are layered over
the SGTK PC-DOS 7.1 base, with SGTK winning every conflict. No other
boot mode borrows files across DOS variants.

## Internal changes

- `scripts/fetch-windows-vendor.py` — new `from_in_archive_tree` extract
  mode that preserves nested subdirectories when staging.
- `vendor/windows/manifest.json` — dosbox-x extracts the whole
  `mingw-build/mingw/` subtree into `vendor/windows/bin/dosbox-x/`.
- `src/dosforge/_platform/windows.py` — `tool_path("dosbox-x")` returns
  the new subdir path `vendor/windows/bin/dosbox-x/dosbox-x.exe`.
- `.github/workflows/release.yml` — smoke check now verifies the support
  files (`dosbox-x.reference.conf`, `languages/`) are present in the
  FULL bundle.

## Variants

- `dosforge-0.6.7-windows-x64.zip` (FULL, ~150 MB) — TUI + GUI + DOSBox-X
- `dosforge-0.6.7-windows-x64-cli.zip` (CLI-only, ~25 MB) — no DOSBox-X
