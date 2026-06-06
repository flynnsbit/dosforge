MS-DOS 6.00 / 6.20 / 6.21 install assets (pre-6.22)
====================================================

Staging area for the pre-6.22 MS-DOS 6.x line:
  6.00 — initial release, includes DoubleSpace
  6.20 — DoubleSpace bug fixes
  6.21 — DoubleSpace removed (Stac Electronics lawsuit)

MS-DOS 6.22 (with DriveSpace replacing DoubleSpace) has its own
folder (dosassets/msdos622/).

Expected files: 3.5" 1.44 MiB install diskettes (Disk1.img +
Disk2.img + Disk3.img typical layout).

Status: dosforge does not yet ship a boot-mode for pre-6.22 MS-DOS.
Drop install media here so it's ready when support lands. Until
then the tool will report "no install images found" if anyone
points it at this folder.

Source (WinWorldPC): "Microsoft MS-DOS 6.00 / 6.20 / 6.21".

This folder tracks readme.txt only; the install media itself is
gitignored.
