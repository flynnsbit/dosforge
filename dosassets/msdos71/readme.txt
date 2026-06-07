MS-DOS 7.10 install assets — DEPRECATED for VHD builds
=======================================================

dosassets/msdos71/

**Provenance:** MS-DOS 7.10 is the FAT32-capable DOS kernel that
shipped *only* as part of Windows 95 OSR2 / OSR2.1 / OSR2.5 / OSR3
(build 4.00.1111+) and Windows 98.  It was never sold as a
standalone product.  --boot-mode=msdos71 produces a DOS-only boot
(no Win95 GUI Setup) from authentic Win95 OSR2 floppy media.

**Required asset path (NOT this folder):**

  dosassets/w95/Boot.img + Disk01..Disk04.img
                    Authentic Windows 95 OSR2 (4.00.1111) floppy
                    set.  dosforge's QEMU-based SYS A: C: install
                    extracts IO.SYS + MSDOS.SYS + DBLBUFF.SYS +
                    IFSHLP.SYS + COMMAND.COM from these and writes
                    them to a freshly-prepared FAT16/FAT32 partition.

**Why NOT this folder anymore:** the older "Microsoft DOS 7.1"
disk01.img / disk02.img files that used to live here (DOS71_1S.PAK
Chinese re-release) ship ``IO.SYS`` as an MZ-wrapped SETUP stub.
The original Chinese installer normally unpacks it at install time;
extracting it raw yields an unbootable disk ("Invalid system disk"
from the MS-DOS 7.10 VBR).

For VHD builds, see ``dosassets/w95/readme.txt`` for the expected
Win95 OSR2 layout.

The original PAK-based files in this directory are still recognised
by some older dosforge floppy IMG code paths
(``--media-type img --boot-mode msdos71``), but VHD builds will
error if pointed here.

Used by: boot-mode=msdos71 (legacy floppy IMG path only — VHD path
sources from ``dosassets/w95/``).

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
