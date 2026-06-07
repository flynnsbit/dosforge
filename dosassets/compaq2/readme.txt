Compaq DOS 2.x install media
============================

dosassets/compaq2/

dosforge's --boot-mode=compaq2 produces a bootable Compaq DOS 2.11
disk in one of two layouts:

1. **Floppy IMG (default)** -- an authentic 1984 Compaq DOS 2.11
   360 KiB DSDD bootable floppy, verbatim copy of the original
   WinWorldPC ``disk01.img``.  Boots in any 86Box / DOSBox-X
   machine with a 5.25" 360k or 1.2M drive.

2. **MartyPC Xebec Type 1 VHD** -- a 10 MiB MFM/Xebec hard-disk
   image with an XT-class MBR + track-aligned FAT12 partition,
   matching how a real 1984 Compaq Plus or DeskPro presented its
   HDD.  Boots in **MartyPC** with the Xebec Type 1 (10 MiB)
   preset.  Other emulators (86Box AT-class IDE, DOSBox-X) cannot
   boot Compaq DOS 2.11 from HDD because they lack the
   Compaq-specific 1984 BIOS extensions.

   Build command:

     dosforge create \\
         --media-type vhd --boot-mode compaq2 \\
         --format fat12 \\
         --machine-target martypc-xebec \\
         --martypc-xebec-drive-type type1 \\
         --path C:\\my-vhds\\compaq2-xebec.vhd

Floppy IMG build command:

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
