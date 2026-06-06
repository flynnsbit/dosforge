# dosforge v0.6.10 — Windows

**Fourth follow-up to v0.6.7: fix the mcopy destination-path syntax
that was silently making mtools refuse to write to the staging dir
on Windows.**

## What the user saw (v0.6.9 log)

```
[pcdos71]   found 6 install floppies in archive
[pcdos71]   harvested 0 files from floppies          ← BUG
[pcdos71]   unpacking DOS1, DOS2, … via DOSBox-X…
[pcdos71]   PC-DOS 2000 hydration FAILED:
            DOSBox-X UNPACK2 produced no output files
            (nothing was staged to harvest)
```

DOSBox-X actually started fine in v0.6.9 (the support files fix from
v0.6.7 worked) — but the floppy harvest step before it produced zero
files, so there was nothing for UNPACK2 to expand.

## Root cause

`pcdos2000_extract._harvest_floppy_contents` was passing the staging
directory as a positional argument to `mcopy`:

```
mcopy -s -n -m -i <img> :: C:\Users\…\staging/
```

mtools reserves the syntax `<letter>:` as a drive alias (looked up
via `MTOOLSRC`). When the destination starts with `C:\…`, mtools
parses `C:` as an MTOOLSRC drive alias, can't resolve it (we don't
ship a mtoolsrc), and silently treats the destination as invalid —
the recursive copy short-circuits with zero files copied and no
useful error.

## v0.6.10 fix

Pass the destination as a relative path with `cwd=` so it never
contains a colon:

```python
subprocess.run(
    [mcopy, "-s", "-n", "-m", "-i", str(img), "::", "./"],
    cwd=str(dest_dir),   # mtools writes here, no drive-alias confusion
    ...,
)
```

Also: capture mcopy's stderr per-floppy and surface it in the failure
message if zero files end up in the staging dir, so the next class of
mtools bug won't be invisible.

## Verification

Same procedure — drop `IBM PC-DOS 2000 (3.5-1.44mb).7z` (or raw
`disk0*.img`) into `dosforge\dosassets\pcdos2000\`, click **Fetch
PC-DOS 7.1 (SGTK) assets**. The log should now show:

```
[pcdos71]   found 6 install floppies in archive
[pcdos71]   harvested 76+ files from floppies   ← was 0
[pcdos71]   unpacking DOS1, DOS2, DOS3, DOS4, SHELL1, SHELL2 via DOSBox-X…
[pcdos71]   merged PC-DOS 2000 utilities: 96 added, 9 skipped (SGTK wins)
[pcdos71] Done.
```

And the final VHD should land with ~138 files in `C:\DOS\` (EMM386,
POWER, DOSSHELL, DEFRAG, BACKUP, RESTORE, etc.) instead of just 42.

## Cumulative fix chain for PC-DOS 2000 hydration on Windows

1. **v0.6.7**: ship the full DOSBox-X mingw portable tree (not just the EXE).
2. **v0.6.8**: PyInstaller spec must preserve nested vendor subdirs in `datas`.
3. **v0.6.9**: extract `.7z`/`.zip` in-process via `py7zr`/`zipfile` (don't shell out).
4. **v0.6.10** *(this release)*: mcopy destination via `cwd=` + `./` (avoid mtools drive-alias parse on `C:\…`).
