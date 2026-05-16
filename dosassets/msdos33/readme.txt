MS-DOS 3.30 install assets
==========================

Drop the MS-DOS 3.30 install diskette images into this folder
(not a sub-folder).

Expected files (any one of these naming conventions):
  - DISK01.IMG + DISK02.IMG   (preferred)
  - DISK1.IMG + DISK2.IMG
  - .ima extensions also accepted

Used by:
  - boot-mode=msdos33          (FAT16 <32 MiB, MS-DOS 3.30 install)
  - boot-mode=ibm8088 +dos33   (same install media, IBM-PC variant)

vhdmaker boots Disk 1 inside QEMU and runs `FORMAT C: /S` on the
target — this is the only way to get a working DOS 3.30 boot sector
+ correctly attributed IO.SYS / MSDOS.SYS, since SYS.COM rewrites
those at runtime.

Typical source: WinWorldPC.com — "Microsoft MS-DOS 3.30". Extract
the .7z so the DISK01.IMG / DISK02.IMG files sit next to this
readme.txt.

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
