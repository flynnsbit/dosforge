# dosforge windows-v0.6.17 — Compaq DOS 2.11 as a first-class boot mode

Adds `--boot-mode compaq2` (and the corresponding GUI/TUI option
"Compaq DOS 2.11 bootable (5.25-360k)") as a new bottom-of-the-line
DOS target. Sources its install media from a tiny ~158 KB WinWorldPC
.7z archive that the pipeline auto-extracts on first use — drop the
archive in `dosassets/compaq2/` and you're done. Also introduces a
reusable `_legacy_dos_archive` extractor that will be the foundation
for future legacy DOS modes (DR-DOS, older MS-DOS / PC-DOS, etc.)
distributed as one-file archives.

## What's new

### New boot mode

```powershell
.\dosforge create --media-type vhd --boot-mode compaq2 ^
    --format fat12 --size 16M ^
    --path C:\my-vhds\compaq2.vhd
```

Builds a bootable Compaq DOS 2.11 VHD in well under a minute (DOS 2.x
FORMAT C: /S is far faster than DOS 5+'s sector-verify pass). Produces
an authentic 1984-05-30 install with `IBMBIO.COM` + `IBMDOS.COM` +
`COMMAND.COM` at the root, a Compaq-style volume label, and
`ver` reporting something like *Compaq Personal Computer DOS Version 2.11*.

### Asset layout

Drop the WinWorldPC archive directly into the asset dir:

```
dosforge\dosassets\compaq2\Microsoft MS-DOS 2.11 [Compaq OEM] (5.25-360k).7z
```

The install pipeline auto-extracts to `<app_cache>/legacy-dos-archive/`,
caches by content hash, and finds the bootable `disk01.img` inside.
Pre-extracted layouts (drop just `disk01.img` straight into the asset
dir) also work and short-circuit the py7zr step.

### DOS 2.x quirks honored

* **FAT12 only** — DOS 2.x predates FAT16 entirely. The form gates
  disk format to FAT12; trying FAT16 / FAT32 raises a clear error
  pointing at compaq331 / msdos5 / msdos622.
* **16 MiB partition cap** — DOS 2.x maxes out near 16 MiB; the
  validator rejects larger requests with a clear pointer at
  compaq331 / msdos5 / msdos622. The FAT12-on-VHD restriction
  (previously MartyPC Xebec only) has been relaxed to allow
  `boot-mode=compaq2`.
* **Right-sized geometry** — the size-aligner now uses the FAT12
  floor (360 KiB) for FAT12-on-VHD instead of the FAT32 64 MiB
  floor, so a `--size 16M` request produces a ~15.7 MiB VHD instead
  of getting bumped up to 64 MiB.
* **MBR partition type 0x01** — set automatically (msdos33-style
  layout, FAT12 variant).
* **No `FDISK /MBR`** — DOS 2.x's FDISK predates that option by ~7
  years. dosforge writes its own era-appropriate generic MBR (same
  IPL used for MS-DOS 3.3 / IBM PC-DOS 3.x / Compaq DOS 3.31).
* **FORMAT prompts TWICE** — Compaq's OEM FORMAT.COM (1984-05-30)
  prompts both ``Press any key to begin formatting drive C:`` and
  ``Warning! ... Do you want to continue (Y/N)? [N]``; the install
  profile feeds the right input shape so both prompts get an
  affirmative answer.

### Known cosmetic caveat

`mtools mdir -a` may report substantially less "free" space than
the partition actually contains for DOS 2.11 partitions (e.g.
~4.3 MiB on a 15.7 MiB partition) — mtools' free-cluster walk
appears to disagree with Compaq's FAT layout. The underlying BPB
+ FAT are correct and DOS 2.11 itself sees the full partition;
this is a display issue only.

### Compatible MartyPC targets

`compaq2` joins the XT-class boot-mode allow-list for MartyPC Xebec
targets — it's the only DOS 2.x option in that group, and Type-1
Xebec drives (FAT12) snap to it naturally alongside MSDOS33 / IBM8088.

### Reusable archive extractor

The new `src/dosforge/_legacy_dos_archive.py` module is generic —
it'll cover most future legacy DOS modes that ship as a single .7z
or .zip on WinWorldPC (DR-DOS 5/6/7, older MS-DOS, etc.). Each new
mode just needs a `BootMode` enum value, a profile builder, a
descriptor entry, and a one-line dispatch in
`_install_legacy_dos_via_qemu`.

## Asset readme + UI updates

- `dosassets/compaq2/readme.txt` rewritten — documents the .7z
  direct-download workflow, DOS 2.x quirks, and the partition
  type byte.
- `_skeleton/compaq2/readme.txt` mirrored via `scripts/sync-asset-skeleton.py`.
- TUI: new "Compaq DOS 2.11 bootable (5.25-360k)" option in the
  boot-mode dropdown; same visibility rules as the existing
  Compaq DOS 3.31 entry.
- GUI: identical option in the boot-mode combo box.
- formlogic: new `_BootMediaRule` for FAT12-only, 16 MiB cap;
  added to `_DOS_PROFILE_BOOT_MODES` so the DOS install profile
  dropdown surfaces for compaq2 too.

## Tests

- 76/76 focused tests pass:
  `test_disk_windows_vhd.py`, `test_formlogic.py`,
  `test_asset_skeleton.py`, `test_strict_authenticity.py`,
  `test_cli.py`.
- New `test_windows_vhd_pipeline_accepts_compaq2` verifies the
  Windows VHD gate lets COMPAQ2 through.

## Notes

- No effect on existing boot modes — purely additive.
- Linux v0.6.17 is a parity-only bump; the same wiring works on
  both platforms via `py7zr`.
- Authenticity rule preserved: no cross-DOS file borrowing.
  Compaq DOS 2.11 installs only files from its own 360 KB floppy.
