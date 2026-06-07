# dosforge windows-v0.7.0 — Controller-first VHD organization (BREAKING CHANGE)

Restructures the VHD type model from **emulator-first** to
**controller-first**.  Users now pick a hard-disk controller class
(IDE or MFM) as the primary disk-type choice, then optionally a
geometry source (BIOS Type 1-45 preset or custom CHS).  MartyPC
is no longer the organizing principle — its previously dedicated
geometry presets are subsumed into the standard Phoenix/AMI BIOS
Type table, which works identically across MartyPC, 86Box, PCem,
DOSBox-X, and real 1984-1995 hardware.

## 🚨 Breaking changes

The following CLI flags are **REMOVED**:

| Removed flag | v0.7.0 replacement |
|---|---|
| `--machine-target generic` | (default — omit entirely) |
| `--machine-target martypc-xebec --martypc-xebec-drive-type type1` | `--disk-controller mfm --bios-drive-type phoenix:1` |
| `--machine-target martypc-xebec --martypc-xebec-drive-type type2` | `--disk-controller mfm --bios-drive-type phoenix:2` |
| `--machine-target martypc-xebec --martypc-xebec-drive-type type13` | `--disk-controller mfm --bios-drive-type phoenix:2` (geometrically identical) |
| `--machine-target martypc-xebec --martypc-xebec-drive-type type16` | `--disk-controller mfm --bios-drive-type phoenix:2` (geometrically identical) |
| `--machine-target martypc-xtide --martypc-at-drive-type at-1024-16-63` | `--custom-chs 1024,16,63` (or any matching BIOS Type) |
| `--machine-target martypc-jride --martypc-at-drive-type <slug>` | `--disk-controller ide` + `--bios-drive-type <vendor:N>` or `--custom-chs <c,h,s>` |

User scripts using these flags will fail loudly with
``unrecognized arguments`` — no silent compatibility shim.  Update
your scripts using the table above.

## What's new

### `--disk-controller {ide,mfm}` (the headline change)

```powershell
# IDE controller (default for most boot modes) — AT-class machines
.\dosforge create --media-type vhd --boot-mode msdos622 ^
    --format fat16 --size 64M ^
    --disk-controller ide ^
    --path C:\my-vhds\msdos622.vhd

# MFM controller — XT-class machines, ST-225 era
.\dosforge create --media-type vhd --boot-mode compaq2 ^
    --format fat12 ^
    --disk-controller mfm --bios-drive-type phoenix:1 ^
    --path C:\my-vhds\compaq2-mfm.vhd
```

When `--disk-controller` is omitted, it auto-detects from the
boot mode:
- **MFM**: `compaq2`, `msdos33`, `pcdos`, `ibm8088+dos33` (XT-era DOS)
- **IDE**: everything else

### `--custom-chs CYL,HEAD,SPT`

Free-form geometry source — overrides `--bios-drive-type` when set.
Useful for unusual emulator presets that don't map to standard
BIOS Type 1-45 entries.

```powershell
.\dosforge create --media-type vhd --boot-mode msdos33 ^
    --format fat16 --disk-controller mfm ^
    --custom-chs 615,4,17 ^
    --path C:\my-vhds\custom-st225.vhd
```

### Boot mode label updates

The MS-DOS 7.1 label in the TUI/GUI now explicitly identifies its
provenance:

- Old: `"MS-DOS 7.1 bootable"`
- New: `"MS-DOS 7.10 / Win95 OSR2 bootable (FAT16/FAT32, 4.00.1111)"`

Reflects the fact that MS-DOS 7.10 was never sold as a standalone
product — it shipped only inside Windows 95 OSR2 (4.00.1111+)
and Windows 98.  See ``dosassets/msdos71/readme.txt`` and the
new ``BootMode.MSDOS71`` docstring in models.py.

## Why this matters

The v0.6.x model put MartyPC at the centre because that's where we
first proved the MFM HDD path worked.  But the actual layout dosforge
produces (XT-class CHS-only MBR + track-aligned FAT12 partition at
LBA=spt + ST-225 geometry) is a generic 1984-1990 MFM hard-disk
layout — it works on any emulator that supports an MFM controller
(86Box's WD1002A, PCem's MFM, MartyPC's Xebec) and on real
WD1002A-WX1 / WD1003 hardware.  Re-framing the choice as
*controller class* + *standard BIOS geometry* makes that
generality visible.

It also lets us collapse three enums (`MachineTarget`,
`MartyPCXebecDriveType`, `MartyPCATDriveType`) into one
controller flag plus the existing `BIOSDriveType` table.

## Validation matrix

| | IDE controller | MFM controller |
|---|---|---|
| FAT12 | ❌ (use IMG floppy) | ✅ (DOS 2.x/3.x XT-era) |
| FAT16 ≤32 MiB | ✅ msdos33-71/pcdos/ibm8088 | ✅ msdos33/compaq331 |
| FAT16 >32 MiB | ✅ compaq331/msdos5+ | ❌ (no FAT16B-capable MFM DOS in our table) |
| FAT32 | ✅ msdos71/pcdos71/freedos | ❌ (no FAT32-capable MFM-era DOS) |
| compaq2 | ❌ (Compaq 1984 BIOS only) | ✅ |
| msdos71/pcdos71 | ✅ | ❌ |

The disk pipeline detects illegal combinations early and raises
``ValidationError`` with an actionable message.

## Files changed (12 files)

- `src/dosforge/models.py`: + `DiskController` enum; + `disk_controller`, `custom_chs` fields on `CreateRequest`; + `effective_disk_controller` property with auto-detect; removed `MartyPCXebecDriveType` / `MartyPCAtFormat` data + helpers; `MachineTarget` kept as deprecated internal-only enum for one release (removed v0.8.0)
- `src/dosforge/disk.py`: refactored `_uses_msdos33_filesystem_layout`, `_needs_xt_class_mbr_rewrite`, `_partition_offset_bytes_for`, `_normalize_vhd_size_for_chs`, `_normalize_vhd_footer_geometry` to key on `effective_disk_controller`; added `_xt_class_geometry` / `_ide_geometry` resolver helpers
- `src/dosforge/cli.py`: removed `--machine-target`, `--martypc-xebec-drive-type`, `--martypc-at-drive-type`; added `--disk-controller`, `--custom-chs`
- `src/dosforge/formlogic.py`: removed `machine_target`, `martypc_xebec_drive_type`, `martypc_at_drive_type` from FormState; added `disk_controller`, `custom_chs`; removed xebec rule helpers
- `src/dosforge/app.py` (TUI): replaced machine-target select with disk-controller; MS-DOS 7.1 label updated to mention Win95 OSR2 4.00.1111
- `src/dosforge/_gui/options.py` + `create_view.py` (GUI): same controller select; same label
- `dosassets/compaq2/readme.txt` + `_skeleton/compaq2/readme.txt`: updated build command examples to v0.7.0 syntax
- `dosassets/msdos71/readme.txt` + `_skeleton/msdos71/readme.txt`: provenance section moved to top, expected asset path explicitly stated
- `tests/test_disk_windows_vhd.py`, `test_formlogic.py`, `test_cli.py`, `test_disk_validation.py`, `test_windows_cli_matrix.py`, `test_fat12_boot_template.py`: updated for new API

## Tests

208 focused tests pass:
- `test_cli.py`, `test_disk_validation.py`, `test_disk_windows_vhd.py`
- `test_formlogic.py`, `test_asset_skeleton.py`
- `test_strict_authenticity.py`, `test_windows_cli_matrix.py`
- `test_fat12_boot_template.py`

Byte-equivalence verified for previously-supported invocations:
v0.6.19 build commands produce identical MBR/VBR/BPB when run
with the v0.7.0 migrated flags.  One minor data-area diff at
file offset 17526 in the MartyPC Xebec Type 1 path (Phoenix Type 1
geometry now used instead of the MartyPC-specific table entry —
size_bytes is the same, but the IBMBIO write_precomp_cylinder
field differs slightly; harmless and DOS-invisible).

## Live verification

```
$ dosforge create --media-type vhd --boot-mode compaq2 \
      --format fat12 \
      --disk-controller mfm --bios-drive-type phoenix:1 \
      --path compaq2-mfm.vhd --overwrite
Created and prepared compaq2-mfm.vhd

VHD inspection:
- size: 10,654,208 bytes (10.2 MiB)
- footer: cyl=306 heads=4 spt=17 (ST-225 / Phoenix Type 1)
- partition: firstLBA=17 sectors=20723 type=0x01 active CHS 0/1/1
- VBR at LBA 17: OEM 'CCC  2.1' total_sectors_16=20723
- root: IBMBIO.COM/IBMDOS.COM/COMMAND.COM (1984-05-30)
```

User-tested in MartyPC 0.4.1 with Xebec Type 1 preset — boots
cleanly to "The COMPAQ Personal Computer MS-DOS Version 2.11"
identical to the v0.6.19 output.

## Roadmap

v0.7.1 (next): TUI redesign — replace the flat controller select
with a hierarchical "Disk type" pane (controller → geometry source
→ specific preset/custom CHS).  Geometry preview + tooltips.

v0.7.2 (after): same hierarchical pattern in the tkinter GUI.

v0.7.x boot-mode additions (queued, user-staged .7z media):
`pcdos3` (IBM PC-DOS 3.00), `msdos6` (MS-DOS 6.0), `compaq3`
(Compaq OEM MS-DOS 3.00), `drdos6` (DR DOS 6.0), `drdos7`
(Caldera DR-DOS 7.03).  `w95` retail intentionally dropped
(use `msdos71` for FAT32+DOS use case).
