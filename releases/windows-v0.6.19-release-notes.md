# dosforge windows-v0.6.19 — Compaq DOS 2.11 bootable VHD via MartyPC Xebec Type 1

Extends ``--boot-mode=compaq2`` to support a second bootable target:
**MartyPC Xebec Type 1** (10 MiB MFM hard disk).  This is the only
modern-emulator setup whose BIOS + controller combination matches
what Compaq's 1984 DOS 2.11 expects -- a Western-Digital-style
8-bit MFM controller with ST-225-class CHS geometry (306×4×17) and
a track-aligned partition starting at LBA = sectors_per_track (17).

## What's new

### New: bootable Compaq DOS 2.11 hard-disk VHD

```powershell
.\dosforge create --media-type vhd --boot-mode compaq2 ^
    --format fat12 ^
    --machine-target martypc-xebec --martypc-xebec-drive-type type1 ^
    --path C:\my-vhds\compaq2-xebec.vhd
```

Produces a **10.2 MiB VHD** with:
- Footer geometry: 306 cyl × 4 head × 17 spt (ST-225-class)
- MBR: XT-class boot loader (CHS reads only, no INT 13h AH=42 LBA),
  active partition entry pointing at LBA 17 with start CHS 0/1/1
- Partition: FAT12, type 0x01, track-aligned at LBA 17
- VBR: authentic Compaq OEM 'CCC  2.1' with valid 1984 boot code
- Root: IBMBIO.COM + IBMDOS.COM + COMMAND.COM with 1984-05-30 dates

Boot it in MartyPC by selecting the Xebec Type 1 (10 MiB) drive
preset.  Other emulators cannot boot this VHD because they don't
emulate the WD1002A-style 8-bit MFM controller path that
DOS 2.11 expects.

### Floppy IMG output unchanged (v0.6.18 behavior preserved)

```powershell
.\dosforge create --media-type img --boot-mode compaq2 ^
    --format fat12 --floppy-type 360k --img-system-format ^
    --path C:\my-floppies\compaq2.img
```

Still produces the authentic 360 KiB DSDD floppy IMG.  Default
for any 86Box / DOSBox-X / PCem use case.

### Improved validation error

VHD attempts with anything other than MartyPC Xebec Type 1 now
get a single, actionable error:

```
Compaq DOS 2.11 (compaq2) on VHD requires --machine-target
martypc-xebec --martypc-xebec-drive-type type1 (10 MiB MFM, the
1984-authentic Compaq HDD target).  For IDE/AT-class machines,
DOS 2.11's boot code depends on Compaq BIOS extensions no modern
emulator provides -- use --media-type img --floppy-type 360k
instead, or pick compaq331 / msdos5 / msdos622 for a
hard-disk-compatible DOS.
```

The check is placed before ``validate_size_for_format`` so users
picking MartyPC AT/xtide targets see the compaq2-specific message
instead of a confusing FAT12 size-cap error.

## TUI / GUI

- Boot-mode option relabeled to "Compaq DOS 2.11 (360k floppy or
  MartyPC Xebec Type 1 MFM)" so both supported paths are visible
  in the picker.
- ``coerce_on_boot_change`` now: if MartyPC Xebec target is already
  selected when COMPAQ2 is picked, snap to VHD / FAT12 / Xebec
  Type 1 (instead of forcing IMG floppy).  Otherwise default to
  IMG floppy 360k as before.

## Implementation

Reuses the existing **MartyPC Xebec Type 1 code path** already used
for ``msdos33`` and ``ibm8088+dos33``:
- ``_uses_msdos33_filesystem_layout(request)`` already includes
  COMPAQ2 (added in v0.6.17).
- ``_needs_xt_class_mbr_rewrite(request)`` returns True for
  MartyPC Xebec + msdos33-layout, so COMPAQ2 + Xebec gets the
  authentic 1984-style MBR rewrite for free.
- ``_partition_offset_bytes_for(request)`` returns
  ``spec.sectors_per_track * 512`` = 17 * 512 = 8704 for Xebec
  Type 1, producing the track-aligned LBA-17 partition.
- ``_install_legacy_dos_via_qemu`` reuses ``compaq2_profile`` from
  legacy_dos_install.py for the QEMU FORMAT C: /S install step.

No new install profile or boot-asset resolver needed -- it's a
pure validation + form-snapping change on top of v0.6.18.

## Files changed

- `src/dosforge/disk.py`: relaxed COMPAQ2 + VHD ValidationError to
  allow MartyPC Xebec Type 1; reordered check to run before
  validate_size_for_format
- `src/dosforge/formlogic.py`: `coerce_on_boot_change` snaps to
  VHD+Xebec when MartyPC Xebec is already selected, else IMG
- `src/dosforge/_gui/options.py` + `app.py`: relabeled to surface
  both paths
- `dosassets/compaq2/readme.txt` + skeleton mirror: documents both
  IMG and Xebec paths with build commands
- `tests/test_disk_windows_vhd.py`:
  `test_..._rejects_compaq2_on_at_class` -- asserts the new error
  message mentions martypc-xebec + type1

## Tests

170/170 focused tests pass:
`test_disk_windows_vhd.py`, `test_formlogic.py`,
`test_asset_skeleton.py`, `test_strict_authenticity.py`,
`test_cli.py`, `test_disk_validation.py`.

## Live verification

```
$ dosforge create --media-type vhd --boot-mode compaq2 \
      --format fat12 \
      --machine-target martypc-xebec \
      --martypc-xebec-drive-type type1 \
      --path compaq2-xebec.vhd --overwrite
Created and prepared compaq2-xebec.vhd

VHD inspection:
- size: 10,654,208 bytes (10.2 MiB)
- footer: cyl=306 heads=4 spt=17 (ST-225 class)
- partition: firstLBA=17 sectors=20723 type=0x01 active CHS 0/1/1
- VBR at LBA 17: OEM 'CCC  2.1' total_sectors_16=20723
- root: IBMBIO.COM/IBMDOS.COM/COMMAND.COM (1984-05-30)
```

Boot test pending user confirmation in MartyPC with Xebec Type 1
preset.
