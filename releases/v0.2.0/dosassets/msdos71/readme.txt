MS-DOS 7.1 install assets
=========================

Drop the MS-DOS 7.1 install diskette images here.

Expected files: disk01.img + disk02.img (or disk1.img + disk2.img).
.ima accepted. Inside these floppies, dosforge extracts DOS71_1S.PAK
(+ DOS71_2S.PAK for the FULL profile) and unpacks IO.SYS,
MSDOS.SYS, COMMAND.COM, HIMEM.SYS, IFSHLP.SYS, and the rest of the
DOS utility set.

Used by: boot-mode=msdos71.

Typical source: WinWorldPC.com — "Microsoft DOS 7.1 (3.5)". Extract
the .7z so the disk01.img / disk02.img files sit next to this
readme.txt.

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.
