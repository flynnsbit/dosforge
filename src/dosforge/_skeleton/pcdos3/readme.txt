IBM PC-DOS 3.00 install media
=============================

dosassets/pcdos3/

dosforge's --boot-mode=pcdos3 produces a bootable IBM PC-DOS 3.00
disk in two layouts:

1. **Floppy IMG (--media-type img --floppy-type 360k)** -- a verbatim
   copy of the authentic 1984-08-14 IBM PC-DOS 3.00 install floppy
   from the WinWorldPC archive.  Boots in any 86Box / DOSBox-X
   machine with a 5.25" 360k or 1.2M drive.

2. **MFM hard-disk VHD (--disk-controller mfm --bios-drive-type
   phoenix:1)** -- a 10 MiB MFM/ST-225 hard-disk image with FAT12 +
   1984 IBM-style MBR + BPB.  Unlike compaq2 (DOS 2.11), PC-DOS 3.00
   has the BPB.hidden_sectors field added in DOS 3.0, so HDD boot
   works on any standard MFM controller in 86Box / PCem / MartyPC --
   no Compaq-specific BIOS extensions required.

   v0.7.x build command:

     dosforge create --media-type vhd --boot-mode pcdos3 \\
         --format fat12 \\
         --disk-controller mfm --bios-drive-type phoenix:1 \\
         --path C:\\my-vhds\\pcdos3-mfm.vhd

Expected file (auto-extracted .7z or pre-extracted IMG):

  IBM PC-DOS 3.00 (5.25).7z   ~4.1 MB WinWorldPC archive.  The
                              build pipeline auto-extracts via py7zr
                              and finds ``Disk01.img`` inside.

  OR a pre-extracted layout:

  Disk01.img                  Raw 5.25" DSDD image (360 KiB) with
                              IBMBIO.COM + IBMDOS.COM (hidden+system)
                              + COMMAND.COM + FORMAT.COM + SYS.COM +
                              FDISK.COM + VDISK.SYS + standard
                              utilities at its root.  Marker file
                              ``IBMBIO.COM``.

Either layout works; the pre-extracted ``Disk01.img`` wins if both
are present.

DOS 3.0 constraints
-------------------

* FAT12 only -- FAT16 was added in PC-DOS 3.10.  Larger partitions
  need ``--boot-mode msdos33`` (FAT12/FAT16 up to 32 MiB) or
  ``--boot-mode msdos331`` / ``compaq331``.
* Max partition size: ~16 MiB (FAT12 sweet spot for DOS 3.0).
* Uses IBM-style system file naming (IBMBIO.COM / IBMDOS.COM)
  matching the compaq2 / compaq331 / pcdos7 family.
* PC-DOS 3.00 FORMAT.COM prompts twice for a fixed disk like
  Compaq DOS 2.11: once for "Press any key to begin formatting"
  and once for the destructive-confirm Y/N.  The install pipeline
  feeds the appropriate input shape.
* No FDISK /MBR option (that was added in DOS 5.0); dosforge
  writes its own era-appropriate generic MBR.

Source provenance
-----------------

WinWorldPC's "IBM PC-DOS 3.00 (5.25)" archive (2-floppy set).
The disks contain files dated 1984-08-14 -- the original IBM PC AT
release date.  ``ver`` on the resulting disk reports something like
*The IBM Personal Computer DOS Version 3.00*.

The files here are NOT shipped with dosforge; please supply your
own legally-obtained media.

This folder tracks readme.txt only; the install media itself is
gitignored.
