Compaq DOS 2.x install media
============================

dosassets/compaq2/

dosforge's --boot-mode=compaq2 builds bootable VHDs/IMGs from a
Microsoft MS-DOS 2.11 [Compaq OEM] release — the version that
shipped with the original 1983-1984 Compaq Portable and DeskPro
(8088 / 4.77 MHz).  Compaq DOS 3.31 (the FAT16B Compaq OEM that
introduced >32 MiB partition support) has its own folder at
``dosassets/compaq331/``.

Expected file:

  disk01.img       The bootable install floppy.  Raw 5.25" DSDD
                   image (360 KiB = 368,640 bytes) with
                   IBMBIO.COM + IBMDOS.COM (hidden+system) at
                   the root, plus COMMAND.COM, FORMAT.COM,
                   SYS.COM, and FDISK.COM.  Marker file
                   ``IBMBIO.COM`` identifies it.

OR — the equivalent direct-download archive from WinWorldPC:

  Microsoft MS-DOS 2.11 [Compaq OEM] (5.25-360k).7z
                   ~158 KB compressed.  The install pipeline
                   auto-extracts this on first use (cached
                   under ``<app_cache>/legacy-dos-archive/``)
                   and finds ``disk01.img`` inside.  Drop
                   the .7z directly into this folder — no
                   pre-extraction needed.

Either layout works; the pre-extracted ``disk01.img`` wins if
both are present.

DOS 2.x quirks
--------------

* FAT12 only — DOS 2.x predates FAT16 entirely.
* Maximum partition size: ~16 MiB (default formlogic cap).
* Partition type byte: 0x01 (FAT12, <= 16 MiB).
* No FDISK /MBR option — dosforge writes an era-appropriate
  IPL into sector 0 itself.
* ``FORMAT C:`` on Compaq's OEM build (1984-05-30) prompts TWICE:
  ``Press any key to begin formatting drive C:`` then
  ``Warning! ... Do you want to continue (Y/N)? [N]``.  The install
  pipeline feeds both prompts with explicit Ys.

Source provenance
-----------------

WinWorldPC's "Microsoft MS-DOS 2.11 [Compaq OEM]" archive
(360 KB 5.25" floppy set).  The disk contains a single
volume labelled ``COMPAQ DOS`` with files dated
1984-05-30.  ``ver`` on the resulting VHD reports something
like ``Compaq Personal Computer DOS Version 2.11``.

The files here are NOT shipped with dosforge; please supply
your own legally-obtained media.

This folder tracks readme.txt only; the install media itself
is gitignored.
