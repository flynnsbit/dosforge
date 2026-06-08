Digital Research DR DOS 6.0 install assets
==========================================

Staging area for Digital Research DR DOS 6.0 (October 1991) — the
DR-DOS release that competed head-on with MS-DOS 5.0, with full
EMM386 + DPMI support and the SuperStor disk compression driver
(SSTORDRV.SYS).

Boot mode: ``--boot-mode drdos6``

Expected layout: 4 × 3.5" DSDD diskettes (720 KiB each), shipped
inside ``Digital Research DR DOS 6.0 (10-16-1991) (3.5-720k)
(alt).7z`` from WinWorldPC.  dosforge auto-extracts the .7z if
present and uses ``disk01.img`` as the install floppy.

Disk1 ships at root (dated 1991-10-16):
  - IBMBIO.COM, IBMDOS.COM (hidden + system, DR-DOS kernel)
  - COMMAND.COM, SYS.COM, FORMAT.COM, FDISK.COM
  - INSTALL.EXE (interactive installer — bypassed by dosforge,
    which drives FORMAT C: /S directly via QEMU)
  - HIDOS.SYS, EMM386.SYS, SSTORDRV.SYS (DR-DOS drivers)
  - DRDOS.INI (DR-DOS configuration)

Constraints:
  - FAT12 (<=16 MiB) or FAT16 (<=32 MiB)
  - BPB OEM stamp is "IBM  3.3" -- DR-DOS 6 is BPB-compatible
    with DOS 3.3 (has hidden_sectors), boots on any standard
    MFM/IDE BIOS

Source (WinWorldPC):
  "Digital Research DR DOS 6.0 (10-16-1991) (3.5-720k) (alt).7z"

This folder tracks readme.txt + the .7z install archive; raw
extracted images are gitignored.

