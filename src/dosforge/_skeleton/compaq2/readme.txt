Compaq DOS 2.x install media
============================

dosassets/compaq2/

dosforge's --boot-mode=compaq2 produces an **authentic 1984 Compaq
DOS 2.11 360 KiB DSDD bootable floppy IMG** — a verbatim copy of
the original WinWorldPC ``disk01.img`` from the Microsoft MS-DOS
2.11 [Compaq OEM] release.

**IMG only — VHD output is intentionally unsupported.**  Compaq
DOS 2.11's 1984 MBR / VBR boot path depends on Compaq-specific
BIOS extensions that no modern emulator (86Box, DOSBox-X, PCem)
provides.  Even an authentic Compaq FDISK + FORMAT C: /S install
performed inside 86Box hangs at a blinking cursor after sector-0
chainload.  This was verified against real Compaq DOS 2.11 FDISK
output (slot-4 partition entry, firstLBA=1, OEM='CCC  2.1' VBR).
For a hard-disk-compatible DOS, use ``--boot-mode=compaq331``
(Compaq DOS 3.31, FAT16B, up to 504 MiB) or ``msdos5`` / ``msdos622``.

Example build command:

  dosforge create \\
      --media-type img --boot-mode compaq2 \\
      --format fat12 --floppy-type 360k --img-system-format \\
      --path C:\\my-floppies\\compaq2.img

Expected file in this folder:

  Microsoft MS-DOS 2.11 [Compaq OEM] (5.25-360k).7z
                   ~158 KB compressed.  The build pipeline
                   auto-extracts this on first use (cached
                   under ``<app_cache>/legacy-dos-archive/``)
                   and finds ``disk01.img`` inside.  Drop
                   the .7z directly into this folder.

OR — pre-extracted layout (skips the py7zr extract step):

  disk01.img       Raw 5.25" DSDD image (360 KiB = 368,640
                   bytes) with IBMBIO.COM + IBMDOS.COM
                   (hidden+system) at the root, plus
                   COMMAND.COM, FORMAT.COM, SYS.COM, and
                   FDISK.COM.  Marker file ``IBMBIO.COM``.

Either layout works; the pre-extracted ``disk01.img`` wins if
both are present.

Source provenance
-----------------

WinWorldPC's "Microsoft MS-DOS 2.11 [Compaq OEM]" archive
(360 KB 5.25" floppy set).  The disk contains a single volume
labelled ``COMPAQ DOS`` with files dated 1984-05-30.  ``ver``
on the resulting floppy boot reports something like *Compaq
Personal Computer DOS Version 2.11*.

The files here are NOT shipped with dosforge; please supply
your own legally-obtained media.

This folder tracks readme.txt only; the install media itself
is gitignored.
