# dosforge v0.6.11 — Windows

**Fifth and (hopefully) final fix for PC-DOS 2000 hydration on Windows.**

## What v0.6.10's diagnostics caught

```
mcopy disk01.img exit=1 stderr_tail=
  'Failure to make directory .//: No such file or directory\n'
```

The new error capture from v0.6.10 paid off immediately — on Windows
the mingw mtools 4.0.49 build appends its own trailing `/` to a
destination dir argument, so passing `./` became `.//` and `mkdir`
failed with ENOENT. Linux mtools doesn't double-slash, which is why
the bug only manifested on Windows.

## v0.6.11 fix

Pass `.` (no trailing slash) as the destination. mtools still
recognizes it as the cwd and writes files into it without trying to
mkdir a literal `.//` path. Verified that Linux mcopy also accepts
`.` (no behavioral change there).

```python
subprocess.run(
    [mcopy, "-s", "-n", "-m", "-i", str(img), "::", "."],   # was "./"
    cwd=str(dest_dir),
    ...,
)
```

## Verification

Drop `IBM PC-DOS 2000 (3.5-1.44mb).7z` (or raw `disk0*.img`) into
`dosforge\dosassets\pcdos2000\`, click **Fetch PC-DOS 7.1 (SGTK)
assets**. You should now see:

```
[pcdos71]   found 6 install floppies in archive
[pcdos71]   harvested 76+ files from floppies          ← was 0
[pcdos71]   unpacking DOS1, DOS2, DOS3, DOS4, SHELL1, SHELL2 via DOSBox-X…
[pcdos71]   merged PC-DOS 2000 utilities: 96 added, 9 skipped (SGTK wins)
[pcdos71] Done.
```

Final VHD `C:\DOS\` should land with ~138 files (EMM386, POWER,
DOSSHELL, DEFRAG, BACKUP, RESTORE, and the other PC-DOS 2000 tools
merged over the SGTK base).

## Full fix chain (v0.6.7 → v0.6.11)

| Release  | Bug                                                                                  |
|----------|--------------------------------------------------------------------------------------|
| v0.6.7   | Manifest only extracted `dosbox-x.exe`, not its support files                        |
| v0.6.8   | PyInstaller spec flattened nested vendor subdirs, dropping `dosbox-x.exe`            |
| v0.6.9   | `7z.exe` shell-out failed (Windows ships no 7-Zip); switched to `py7zr`/`zipfile`    |
| v0.6.10  | mtools parsed `C:\…` dest as drive alias; switched to `cwd=` + relative path         |
| **v0.6.11** | **Windows mtools appends `/`, so `./` becomes `.//`; pass `.` instead**            |
