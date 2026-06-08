Microsoft MS-DOS 3.00 (Compaq OEM) install assets
=================================================

Staging area for the Compaq-branded MS-DOS 3.00 (April 1985) — the
1985 sibling of IBM PC-DOS 3.00.  Shipped with Compaq DeskPro,
Compaq Portable Plus, and other mid-1980s Compaq PCs.

Boot mode: ``--boot-mode compaq3``

Expected layout: 2 × 5.25" DSDD diskettes (360 KiB each), shipped
inside ``Microsoft MS-DOS 3.00 [Compaq OEM] (5.25-360k).7z`` from
WinWorldPC.  dosforge auto-extracts the .7z if present and uses
``DISK01.IMG`` as the install floppy.

Disk1 ships at root:
  - IBMBIO.COM, IBMDOS.COM (hidden + system, 1985-04-22)
  - COMMAND.COM
  - FORMAT.COM, FDISK.COM, SYS.COM
  - VDISK.SYS, CLOCK.SYS

Constraints:
  - FAT12 only (FAT16 added in DOS 3.10)
  - Max ~16 MiB partition
  - Defaults to MFM controller for 1985-authentic Compaq hardware
    (works on IDE too via override)

Compaq DOS 3.31 (FAT16B, >32 MiB partition support) has its own
folder (dosassets/compaq331/) and boot mode (``--boot-mode compaq331``).

Source (WinWorldPC): "Microsoft MS-DOS 3.00 [Compaq OEM] (5.25-360k)".

This folder tracks readme.txt + the .7z install archive; raw
extracted images are gitignored.

