Compaq DOS 2.x install assets
=============================

Staging area for Compaq OEM DOS 2.x releases (1983-1984 era,
shipped with the Compaq Portable and DeskPro). Compaq DOS 3.31
(the FAT16B Compaq OEM that introduced >32 MiB partition support)
has its own folder (dosassets/compaq331/).

Expected files: 5.25" DS/DD floppy images (320 KiB).

Status: vhdmaker does not yet ship a boot-mode=compaq2. Drop install
media here so it's ready when support lands. Until then the tool
will report "no install images found" if anyone points it at this
folder.

Source (WinWorldPC): "Compaq MS-DOS 2.x" archives.

This folder tracks readme.txt only; the install media itself is
gitignored.
