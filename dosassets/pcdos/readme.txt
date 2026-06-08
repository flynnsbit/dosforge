IBM PC-DOS (generic, CLI-only) install assets
==============================================

This is the generic IBM PC-DOS catch-all boot mode.  Used via
the CLI only:

  dosforge create --boot-mode pcdos --boot-assets-path dosassets/pcdos/ \
      --media-type vhd --format fat16 --size 32M --path pcdos.vhd

The GUI / TUI dropdowns do NOT list this mode.  They surface the
four version-specific PC-DOS options instead, which carry the
correct per-version size caps and asset layout:

  --boot-mode pcdos3    IBM PC-DOS 3.00 (1984, .7z 360k DSDD)
  --boot-mode pcdos7    IBM PC-DOS 7.0 (LOADDSKF 144US1.DSK)
  --boot-mode pcdos2000 IBM PC-DOS 2000 (6-floppy .7z)
  --boot-mode pcdos71   IBM PC-DOS 7.1 (SGTK download)

What this generic mode does
---------------------------

The resolver searches dosassets/pcdos/ first for a raw IMG with
IBMBIO.COM at root (typical "disk01.img" or similar), then falls
back to dosassets/pcdos7/144US1.DSK via IBM LOADDSKF decompression.
If a usable IMG is found in dosassets/pcdos/, it's fed into
PC-DOS 7.0's FORMAT C: /S pipeline inside QEMU.

This is "loose, hopeful" -- the same QEMU install pipeline runs
for whichever PC-DOS version you drop in.  No version-aware:
  - size cap (PC-DOS 3.x = 32 MiB, 5.x = 504 MiB, 6.x = 2 GiB)
  - BPB OEM string check
  - CONFIG.SYS / AUTOEXEC.BAT expectation

What can succeed
----------------

PC-DOS 3.10 / 3.20 / 3.30 / 4.00 / 5.00 / 5.02 / 6.10 / 6.30
disk1 in raw IMG form, with IBMBIO.COM + IBMDOS.COM + COMMAND.COM
at root.  Drop as:

  dosassets/pcdos/disk01.img

(or DISK01.IMG, Disk01.img -- case-insensitive search).

What will NOT work
------------------

  - MS-DOS install media (uses IO.SYS, not IBMBIO.COM)
  - PC-DOS 1.x / 2.x (no hard-disk install in those releases)
  - Compaq DOS (use --boot-mode compaq2 / compaq3 / compaq331)
  - DR-DOS (use --boot-mode drdos6 / drdos7)
  - PC-DOS 7.x in LOADDSKF format (use --boot-mode pcdos7 instead;
    the fallback to dosassets/pcdos7/ pulls 144US1.DSK if you drop
    nothing here, but you may as well pick pcdos7 directly)

For most use cases pick a version-specific mode instead.

This folder tracks readme.txt only; install media is gitignored.
