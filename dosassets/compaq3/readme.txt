Compaq DOS 3.0 / 3.10 install assets (pre-3.31)
================================================

Staging area for the early Compaq OEM DOS 3.x releases (Compaq
DOS 3.00 and 3.10) shipped with mid-80s Compaq PCs. The later
Compaq DOS 3.31 — which introduced FAT16B (>32 MiB partition
support) — has its own folder (dosassets/compaq331/).

Expected files: 5.25" DS/DD floppy images (360 KiB) or 3.5" DS/DD
(720 KiB) per the version.

Status: dosforge does not yet ship a boot-mode=compaq3. Drop install
media here so it's ready when support lands. Until then the tool
will report "no install images found" if anyone points it at this
folder.

Source (WinWorldPC): "Compaq MS-DOS 3.00 / 3.10" archives.

This folder tracks readme.txt only; the install media itself is
gitignored.
