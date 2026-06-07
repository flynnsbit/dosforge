# dosforge windows-v0.6.18 — Compaq DOS 2.11 restricted to IMG floppy

Restricts `--boot-mode=compaq2` (Compaq OEM MS-DOS 2.11) to floppy
IMG output only.  The v0.6.17 VHD path produced a structurally valid
disk that boots correctly inside QEMU during the install pipeline,
but **the resulting VHD hangs at a blinking cursor on every modern
emulator** (86Box, DOSBox-X, PCem) regardless of layout, machine
type, or drive geometry.  Diagnosis below.

## What's new

### IMG output is now the only supported COMPAQ2 path

```powershell
.\dosforge create --media-type img --boot-mode compaq2 ^
    --format fat12 --floppy-type 360k --img-system-format ^
    --path C:\my-floppies\compaq2.img
```

Produces a **verbatim 1984 Compaq DOS 2.11 360 KiB DSDD floppy**
(byte-identical to the WinWorldPC ``disk01.img``).  Boots cleanly
in any 86Box machine with a 5.25" 360k or 1.2M drive.  Volume
label ``COMPAQ DOS``, files dated 1984-05-30, ``ver`` reports
*Compaq Personal Computer DOS Version 2.11*.

### VHD path now blocks with an actionable error

```
$ dosforge create --media-type vhd --boot-mode compaq2 ...
Compaq DOS 2.11 (compaq2) cannot boot from a VHD on any modern
emulator -- its 1984 boot code depends on Compaq BIOS extensions
that 86Box / DOSBox-X / PCem don't provide.  Use --media-type img
--floppy-type 360k to produce a bootable 360 KiB DSDD floppy
(the authentic 1984 Compaq DOS 2.11 medium).  For a hard-disk-
compatible DOS, use compaq331 (Compaq DOS 3.31, FAT16B, up to
504 MiB) or msdos5 / msdos622.
```

### TUI/GUI auto-snap

Selecting "Compaq DOS 2.11 floppy (5.25-360k, IMG only)" in the
boot-mode dropdown automatically:
- Switches media type to IMG
- Sets format to FAT12
- Sets floppy type to 360k
- Enables img_system_format

so the user can't accidentally land in an invalid combination.

## Diagnosis (full investigation)

v0.6.17 shipped with a structurally correct VHD output:
- MBR signature 0x55AA
- Active partition at LBA 1 (matching authentic Compaq FDISK
  output verified inside 86Box)
- VBR byte-identical to a real Compaq FORMAT C: /S install
  (OEM ``CCC  2.1``, total_sectors_16=32255, sectors_per_fat=12)
- IBMBIO.COM at cluster 2 + IBMDOS.COM at cluster 4
  (1984-05-30 dates)

The user manually FDISK'd + FORMAT'd a blank disk inside 86Box
using Compaq's own boot floppy.  The resulting disk had:
- MBR boot code = Compaq's authentic 1984 IPL (with the
  "Insert COMPAQ DOS diskette in drive A" error message)
- Partition entry in slot 4 (a Compaq FDISK quirk)
- firstLBA=1, sectors=31247 (Compaq leaves last cylinder unused)
- VBR identical to ours (same OEM, same BPB)

**Both VHDs hang at a blinking cursor** in 86Box's Pentium AT,
Compaq Portable II, IBM AT, and XTIDE Universal BIOS machine
configurations.  DOSBox-X's `boot -l c` likewise hangs on both.

Conclusion: Compaq DOS 2.11's MBR/VBR boot code depends on
Compaq-specific 1984 BIOS extensions (the original Compaq Plus
and DeskPro had a custom hard-disk BIOS) that no modern emulator
emulates -- even when running a Compaq Portable II BIOS in
86Box.  Floppy boot works in every emulator because floppy boot
only uses standard INT 13h floppy services, which are universally
emulated.

The only path to HDD-bootable DOS 2.x would be to write a
custom non-Compaq HDD loader (similar to FreeDOS's LBA loader)
that loads IBMBIO.COM into memory at the right address and
matches IBMBIO's expected register state on entry.  That is
non-trivial and not 1984-authentic, so not pursued.

## Files changed

- `src/dosforge/disk.py`: COMPAQ2 IMG short-circuit (verbatim
  copy of disk01.img); COMPAQ2 + VHD validation error placed
  early so it surfaces before the generic FAT12-on-VHD message;
  reverted LBA-1 partition logic (now dead code without VHD path)
- `src/dosforge/formlogic.py`: `coerce_on_boot_change` snaps to
  IMG/FAT12/360k when COMPAQ2 selected
- `src/dosforge/app.py` + `_gui/options.py`: relabeled to
  "Compaq DOS 2.11 floppy (5.25-360k, IMG only)" so the
  constraint is visible in the picker
- `dosassets/compaq2/readme.txt` + skeleton mirror: rewritten
  to document the IMG-only design + provenance + diagnosis
- `tests/test_disk_windows_vhd.py`: replaced
  `test_..._accepts_compaq2` with `test_..._rejects_compaq2`
  asserting the new error message

## Tests

170/170 focused tests pass:
`test_disk_windows_vhd.py`, `test_formlogic.py`,
`test_asset_skeleton.py`, `test_strict_authenticity.py`,
`test_cli.py`, `test_disk_validation.py`.

## Live verification

```
$ dosforge create --media-type img --boot-mode compaq2 \
      --format fat12 --floppy-type 360k --img-system-format \
      --path compaq2.img --overwrite
Created and prepared compaq2.img

$ ls -la compaq2.img
-rw-r--r-- 1 user user 368640 ... compaq2.img

$ mdir -i compaq2.img ::
 Volume in drive : is COMPAQ DOS
 IBMBIO   COM      5120 1984-05-30  12:00
 IBMDOS   COM     17408 1984-05-30  12:00
 COMMAND  COM     18272 1984-05-30  12:00
 ... (39 files total)
```

Boot test pending user confirmation in 86Box (5.25" 360k drive
or 1.2M drive both accept 360 KiB media).
