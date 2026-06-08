MS-DOS 6.00 install assets
==========================

Staging area for MS-DOS 6.00 (March 1993) — the first DoubleSpace
release in the MS-DOS 6.x line.  Predecessor of 6.20 / 6.21 / 6.22.

Boot mode: ``--boot-mode msdos6``

Expected layout: 3 × 3.5" 1.44 MiB install diskettes
(``DISK1.IMG`` + ``DISK2.IMG`` + ``DISK3.IMG``).  Disk1 ships
IO.SYS + MSDOS.SYS + COMMAND.COM + FORMAT.COM + FDISK.COM +
SYS.COM at its root.  dosforge auto-extracts the .7z below if
present and runs FORMAT C: /S inside QEMU (same pipeline as
``--boot-mode msdos5`` / ``--boot-mode msdos622``).

Source (WinWorldPC):
  "Microsoft MS-DOS 6.0 Plus Enhanced Tools (3.5).7z"
  3-disk set, ~3.85 MB compressed.

MS-DOS 6.22 (DriveSpace, post-Stac lawsuit) has its own folder
(dosassets/msdos622/) with its own boot mode (``--boot-mode msdos622``).

This folder tracks readme.txt + the .7z install archive; raw
extracted images are gitignored.

