MS-DOS 5.0 install assets
=========================

Drop the MS-DOS 5.0 install diskette images here.

Expected files: Disk01.img + Disk02.img + Disk03.img (case
insensitive; .ima also accepted).

Used by:
  - boot-mode=msdos5            (MS-DOS 5.0 boot)
  - boot-mode=ibm8088 +dos50    (same media, IBM-PC variant)

MS-DOS 5.0 introduced the modern CONFIG.SYS dialect (DOS=HIGH,
LASTDRIVE=letter, BUFFERS=N,M) so dosforge writes a full
CONFIG.SYS template here.

Typical source: WinWorldPC.com — "Microsoft MS-DOS 5.00 (3.5-720k)"
archive. Extract the .7z so the .img files sit next to this readme.txt.

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
