Caldera DR-DOS 7.03 install assets
==================================

Staging area for Caldera DR-DOS 7.03 (January 1999) — the final
retail DR-DOS release.  Includes FAT16B / BIGDOS support (>32 MiB
FAT16 partitions up to 2 GiB) and the DR-DOS multitasker (TASKMGR).

Boot mode: ``--boot-mode drdos7``

Expected layout: 5 × 3.5" HD diskettes (1.44 MB each), shipped
inside ``Caldera DR-DOS 7.03 (01-07-1999) (3.5-1.44mb).7z`` from
WinWorldPC.  dosforge auto-extracts the .7z if present and uses
``Installation & Utilities 1.img`` as the install floppy.

Disk1 ships at root (dated 1999-01-07):
  - IBMBIO.COM, IBMDOS.COM (hidden + system, DR-DOS 7 kernel)
  - COMMAND.COM, SYS.COM, FORMAT.COM, FDISK.COM
  - HIMEM.SYS, ANSI.SYS, DRMOUSE.COM
  - INSTALL.EXE + SETUP2.EX_ + LOADER.COM + PNUNPACK.EXE
    (interactive Setup wizard -- dosforge bypasses it via scripted
    AUTOEXEC.BAT that runs FORMAT C: /S directly inside QEMU)
  - SETVER.EXE, UNFORMAT.COM, DOSBOOK.EX_ (extensive utilities)

Constraints:
  - FAT12 (floppy) or FAT16 / FAT16B up to 2 GiB
  - BPB OEM stamp is "DRDOS  7" -- DR-DOS 7 BPB carries
    hidden_sectors, boots on any standard IDE/MFM BIOS
  - FAT32 LBA support not yet wired (DR-DOS 7.03 supports it,
    but dosforge currently exposes FAT16 only; FAT32 would need
    a separate ``drdos7_fat32_profile`` mirror of pcdos71)

Source (WinWorldPC):
  "Caldera DR-DOS 7.03 (01-07-1999) (3.5-1.44mb).7z"

This folder tracks readme.txt + the .7z install archive; raw
extracted images are gitignored.

