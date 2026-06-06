# dosforge v0.6.9 — Windows

**Third follow-up to v0.6.7 — fixes the PC-DOS 2000 archive extraction
step that was silently failing on Windows because we shelled out to a
non-existent `7z.exe`.**

## What the user saw

After installing v0.6.8 and clicking **Fetch PC-DOS 7.1 (SGTK) assets**
with `IBM PC-DOS 2000 (3.5-1.44mb).7z` already in `dosassets\pcdos2000\`,
the log read:

```
[pcdos71] Hydrating C:\DOS\ with PC-DOS 2000 utilities…
[pcdos71]   found PC-DOS 2000 source: IBM PC-DOS 2000 (3.5-1.44mb).7z
[pcdos71]   extracting IBM PC-DOS 2000 (3.5-1.44mb).7z…
[pcdos71]   PC-DOS 2000 hydration FAILED (unexpected):
              FileNotFoundError(2, 'The system cannot find the file specified', None, 2, None)
```

`FileNotFoundError(2)` from `CreateProcess` = the EXE we tried to run
doesn't exist. We were calling `subprocess.run(["7z", "x", …])` and
Windows doesn't ship 7-Zip, so the bundle had no way to extract the
WinWorldPC `.7z` archive.

## v0.6.9 fix

`src/dosforge/pcdos2000_extract.py`: replaced the external 7-Zip
subprocess call with in-process extraction via `py7zr` (already a
runtime dependency, used elsewhere in `boot.py`) for `.7z` and
`zipfile` for `.zip`. No external 7-Zip required on Windows or Linux.

## Verification

Same flow as v0.6.7 — drop your `IBM PC-DOS 2000 (3.5-1.44mb).7z`
(OR raw `disk01.img`..`disk06.img` floppies) into
`dosforge\dosassets\pcdos2000\`, click **Fetch PC-DOS 7.1 (SGTK) assets**,
and the log should now progress past extraction:

```
[pcdos71]   extracting IBM PC-DOS 2000 (3.5-1.44mb).7z…
[pcdos71]   found 6 install floppies in archive
[pcdos71]   harvested NN files from floppies
[pcdos71]   unpacking DOS1, DOS2, DOS3, DOS4, SHELL1, SHELL2 via DOSBox-X…
[pcdos71]   merged PC-DOS 2000 utilities: NN added, MM skipped (SGTK wins)
[pcdos71] Done.
```

The resulting VHD should have ~138 files in `C:\DOS\` (vs the 42-file
SGTK-only set) including `EMM386.EXE`, `POWER.EXE`, `DOSSHELL.EXE`,
`DEFRAG.EXE`, `BACKUP.EXE`, `RESTORE.EXE`, and the other PC-DOS 2000
utilities.

## Recap of the v0.6.7-v0.6.9 fix chain

Three stacked bugs hid PC-DOS 2000 hydration on Windows:

1. **v0.6.7**: manifest only extracted `dosbox-x.exe`, not the support
   files DOSBox-X needs to start.
   → Fixed: ship the whole `mingw/` portable tree.
2. **v0.6.8**: PyInstaller spec flattened nested vendor files to
   `vendor/windows/bin/`, dropping `dosbox-x.exe` from the bundle.
   → Fixed: preserve relative subdir structure in `datas`.
3. **v0.6.9 (this release)**: archive extraction shelled out to `7z.exe`
   which doesn't exist on Windows.
   → Fixed: in-process extraction via `py7zr`/`zipfile`.
