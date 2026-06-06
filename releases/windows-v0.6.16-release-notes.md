# dosforge windows-v0.6.16 — IBM PC-DOS 2000 as a first-class boot mode

Adds `--boot-mode pcdos2000` (and the corresponding GUI/TUI option
"IBM PC-DOS 2000 bootable (6-floppy set)") as a sibling of the
existing `pcdos7` mode. Same DOS internally, different distribution
channel — and now you can pick either one explicitly.

## What's new

### New boot mode

```powershell
.\dosforge create --media-type vhd --boot-mode pcdos2000 ^
    --format fat16 --size 32M ^
    --path C:\my-vhds\pcdos2000.vhd
```

Builds a bootable IBM PC-DOS 2000 VHD in ~5-10 seconds (just FORMAT
C: /S inside QEMU — no LOADDSKF decompression step needed).
Produces an authentic ``IBM  7.0`` OEM-stamped VBR with
`IBMBIO.COM` + `IBMDOS.COM` + `COMMAND.COM` carrying the genuine
1998-04-30 PC-DOS 2000 build dates.

### Asset layout

Drop the WinWorldPC `IBM PC-DOS 2000 (3.5-1.44mb).7z` (or its
extracted 6-floppy contents) into
`dosforge\dosassets\pcdos2000\`. The install pipeline only needs
`disk01.img` (the bootable install floppy with
IBMBIO/IBMDOS/COMMAND/SYS.COM/FORMAT.COM at its root); the other
five disks ship the rest of the DOS toolset but aren't currently
consumed.

### Why a separate boot mode from PCDOS7

IBM rebranded **PC-DOS 7.00** as **PC-DOS 2000** for the Y2K
marketing cycle. The two are byte-identical for the boot kernel
and core utilities — `ver` on a PC-DOS 2000 install reports
"IBM PC-DOS Version 7.00" because IBM kept the internal version
number unchanged. Only the boxart, manuals, SETUP.COM splash, and
DATE/TIME Y2K helpers differ.

What changed is the **distribution channel**:

| | --boot-mode=pcdos7 | --boot-mode=pcdos2000 |
|---|---|---|
| Source media | `dosassets/pcdos7/144US1.DSK` | `dosassets/pcdos2000/disk01.img` |
| Format | LOADDSKF compressed (IBM-proprietary) | Raw 1.44 MB IMG |
| Extraction at build time | DOSBox-X + LOADDSKF.EXE | None (use disk01 directly) |
| Build time | ~30-45s (LOADDSKF extract on first run) | **~5-10s** (no extract) |
| WinWorldPC archive | "PC DOS 7 (3.5).7z" | "IBM PC-DOS 2000 (3.5-1.44mb).7z" |

Resulting VHDs are byte-equivalent (modulo the IBMBIO/IBMDOS
build-date difference — 1994-11-17 for PC-DOS 7.0 vs 1998-04-30
for PC-DOS 2000).

## Implementation

- `src/dosforge/models.py` — new `BootMode.PCDOS2000` enum value.
- `src/dosforge/legacy_dos_install.py` — new `pcdos2000_profile()`
  function. Same FORMAT C: /S pipeline as `pcdos7_profile`, just
  with a different `label` string for build diagnostics.
- `src/dosforge/disk.py` — new entry in
  `_LEGACY_DOS_INSTALL_DESCRIPTORS` keyed on `BootMode.PCDOS2000`
  with `asset_fallback_dirs=("pcdos2000",)` and
  `preferred_image_names=("disk01.img", "DISK01.IMG", ...)`. Added
  to every existing set/tuple that includes `BootMode.PCDOS7`:
  - `_uses_legacy_dos_qemu_install`
  - `legacy_fat16_modes` validation
  - Windows VHD pipeline supported boot modes
  - `format_from_scratch_modes`
  - `write_mbr_only` boot_dos_modes
  - `patch_fat16_bpb_geometry` trigger
  - `_validate_legacy_floppy_system_layout`
- `src/dosforge/formlogic.py` — added to `_DOS_PROFILE_BOOT_MODES`
  (Minimal/Full toggle) and `_BOOT_MODE_MEDIA_RULES`
  (FAT12/FAT16 allowed).
- `src/dosforge/app.py` (TUI) — added to boot-mode Select options
  + `dos_boot_modes` visibility set.
- `src/dosforge/_gui/options.py` — added "IBM PC-DOS 2000 bootable
  (6-floppy set)" label.
- `dosassets/pcdos2000/readme.txt` (and the wheel-bundled
  `_skeleton` mirror) rewritten — was "(reserved)", now documents
  the live boot mode with asset layout + provenance + relation to
  PCDOS7.

## Verification

Live-built on Windows:

```
$ dosforge create --media-type vhd --boot-mode pcdos2000 --format fat16 \
      --size 32M --path C:\dosforge-win-v6\pcdos2000-test.vhd --overwrite
Created and prepared C:\dosforge-win-v6\pcdos2000-test.vhd  (5 seconds)

VHD verification:
  MBR signature: 0x55 0xAA       VALID
  MBR partition: type=0x06 (FAT16-CHS), bootable=0x80, start_lba=63
  VBR OEM: 'IBM  7.0'            (authentic — PCDOS 2000 IS PCDOS 7.0)
  VBR signature: 0x55 0xAA       VALID

C:\ root files (all hidden+system+ro for IBMBIO/IBMDOS):
  IBMBIO.COM   40,726  1998-04-30 13:00   (authentic PC-DOS 2000 build date)
  IBMDOS.COM   37,066  1998-04-30 13:00
  COMMAND.COM  52,965  1998-04-30 13:00
```

86Box boot test: **PASS**. VHD boots to a DOS prompt; `ver` reports
"IBM PC-DOS Version 7.00" (correct — IBM never bumped the internal
version when they rebranded for Y2K).

## Tests

New: `tests/test_disk_windows_vhd.py::test_windows_vhd_pipeline_accepts_pcdos2000`.
Updated: `test_windows_vhd_pipeline_accepts_every_legacy_dos_mode` now includes
PCDOS2000 in its iterated mode list. All 230 focused tests
(test_boot_assets + test_formlogic + test_disk_validation +
test_disk_windows_vhd + test_strict_authenticity + test_cli) pass.

## Same as `windows-v0.6.15`

Every fix from the v0.6.7→v0.6.15 chain is preserved:

- FreeDOS minimal-authentic payload filter (v0.6.15)
- FreeDOS + FAT32 on Windows (v0.6.13)
- DOSBox-X standard MinGW64 build (v0.6.12)
- Windows mtools quirks all handled (v0.6.10, v0.6.11)
- PC-DOS 7.1 + PC-DOS 2000 hydration produces 138 files in
  `C:\\DOS\\` for FULL profile

## Companion Linux release

`linux-v0.6.16` parity bump — same code, same boot mode, same
asset layout. PC-DOS 2000 is a 6-floppy install media set so its
behavior is identical on Linux.

SHA-256 checksums listed below per artifact.
