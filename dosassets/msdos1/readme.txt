MS-DOS 1.x install assets (pre-1.25)
====================================

Staging area for the earliest MS-DOS 1.x releases (1.10 / 1.11 /
1.12 / 1.14). MS-DOS 1.25 has its own folder (dosassets/msdos125/)
because it shipped with extended ATA partition support and was
later open-sourced by Microsoft.

Expected files: 5.25" SS/DD floppy images (160 KiB or 180 KiB).

Status: vhdmaker does not yet ship a boot-mode for MS-DOS 1.x.
Drop install media here so it's ready when support lands. Until
then the tool will report "no install images found" if anyone
points it at this folder.

Source (WinWorldPC): "Microsoft MS-DOS 1.x" archives. Drop the
.img / .ima files directly into this folder.

This folder tracks readme.txt only; the install media itself is
gitignored.
