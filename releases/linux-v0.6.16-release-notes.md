# dosforge linux-v0.6.16 — IBM PC-DOS 2000 as a first-class boot mode

Adds `--boot-mode pcdos2000` (and the corresponding GUI/TUI option
"IBM PC-DOS 2000 bootable (6-floppy set)") as a sibling of the
existing `pcdos7` mode. Same DOS internally, different distribution
channel — and now you can pick either one explicitly.

## What's new

```bash
dosforge create --media-type vhd --boot-mode pcdos2000 \
    --format fat16 --size 32M \
    --path ~/my-vhds/pcdos2000.vhd
```

Drop the WinWorldPC `IBM PC-DOS 2000 (3.5-1.44mb).7z` archive (or
its extracted 6-floppy contents) into
`~/.local/share/dosforge/dosassets/pcdos2000/`. The install
pipeline only needs `disk01.img` — the bootable install floppy
with IBMBIO/IBMDOS/COMMAND/SYS.COM/FORMAT.COM at its root.

## PC-DOS 2000 vs PC-DOS 7.0

IBM rebranded **PC-DOS 7.00** as **PC-DOS 2000** for the Y2K
marketing cycle. The two are byte-identical for the boot kernel
and core utilities — `ver` on a PC-DOS 2000 install reports
"IBM PC-DOS Version 7.00" because IBM kept the internal version
number unchanged. Only the boxart, manuals, SETUP.COM splash, and
DATE/TIME Y2K helpers differ.

What changed is the **distribution channel**:

| | --boot-mode=pcdos7 | --boot-mode=pcdos2000 |
|---|---|---|
| Source media | `dosassets/pcdos7/144US1.DSK` (IBM LOADDSKF) | `dosassets/pcdos2000/disk01.img` (raw IMG) |
| Extraction at build time | DOSBox-X + LOADDSKF.EXE | None |
| Build time | ~30-45s | **~5-10s** |
| WinWorldPC archive | "PC DOS 7 (3.5).7z" | "IBM PC-DOS 2000 (3.5-1.44mb).7z" |

Resulting VHDs are byte-equivalent modulo the IBMBIO/IBMDOS build
date (1994-11-17 for PC-DOS 7.0 vs 1998-04-30 for PC-DOS 2000).

## Implementation

- `BootMode.PCDOS2000` added to `src/dosforge/models.py`.
- `pcdos2000_profile()` in `legacy_dos_install.py` — reuses the
  PC-DOS 7.0 FORMAT C: /S pipeline.
- `_LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.PCDOS2000]` in
  `disk.py` with `asset_fallback_dirs=("pcdos2000",)` +
  `preferred_image_names=("disk01.img", "DISK01.IMG", ...)`.
- Added to every existing set that includes PCDOS7
  (`_uses_legacy_dos_qemu_install`, the various validation +
  pipeline + payload sets, the formlogic Minimal/Full toggle, the
  TUI/GUI boot-mode dropdowns).
- `dosassets/pcdos2000/readme.txt` rewritten (was "(reserved)").

## Tests

7 new test cases:
- `test_windows_vhd_pipeline_accepts_pcdos2000` — new
- `test_windows_vhd_pipeline_accepts_every_legacy_dos_mode` —
  updated to iterate PCDOS2000 too

All 230 focused tests pass.

## Verified live on Windows

Built a 32 MB FAT16 PC-DOS 2000 VHD in 5 seconds, booted in 86Box
(AUTO IDE / NORMAL translation), reached DOS prompt, `ver` reports
"IBM PC-DOS Version 7.00" (correct — see explanation above).

## Same code as `linux-v0.6.15`

No backend regressions. FreeDOS minimal-authentic filter, PC-DOS
7.1 SGTK hydration, all the rest of v0.6.x stays put.

## Upgrade

```bash
cd releases/v0.6.16
chmod +x install.sh
./install.sh
```

Or in-place:

```bash
python -m pip install --user --upgrade releases/v0.6.16/dosforge-0.6.16-py3-none-any.whl
```
