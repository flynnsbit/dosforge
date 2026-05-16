Compaq DOS 3.31 install assets
==============================

Drop the Compaq DOS 3.31 install diskette images into THIS folder
(not a sub-folder).

Expected files:
  - STARTUP.IMG   (required — dosforge boots this floppy in QEMU
                   and runs `SYS C:` on the target VHD)
  - OPER.IMG      (optional — operations diskette)
  - FASTART.IMG   (optional — fast-startup diskette)

dosforge also accepts .ima extensions and is case-insensitive on
filenames. The first floppy whose name matches STARTUP.IMG /
STARTUP.IMA wins; if none match, dosforge scans for any floppy
that contains SYS.COM + IBMBIO.COM and uses that as the boot
template.

Typical source: WinWorldPC.com archive of "Microsoft MS-DOS 3.31
[Compaq OEM Rev G]". Extract the .7z into this folder so the .img
files sit next to this readme.txt.

This folder is intentionally kept under version control via this
readme.txt, but the .img / .7z / etc. payload files are gitignored.
