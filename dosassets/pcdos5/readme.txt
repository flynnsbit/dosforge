IBM PC-DOS 5.00 / 5.02 install assets
=====================================

Staging area for IBM PC-DOS 5.x (IBM's branded counterpart to
MS-DOS 5.0; introduced HMA/UMB support and the DOSSHELL).

Status: supported as ``--boot-mode pcdos5`` since dosforge v0.9.47.
Also selectable as the "PC-DOS 5.x" option under the IBM 8088 boot
mode's "DOS version" picker in the TUI / GUI.

Expected files: 3.5" 1.44 MiB install diskettes from the WinWorldPC
"IBM PC-DOS 5.00 (1991) (3.5)" or "IBM PC-DOS 5.02 (1992) (3.5)"
archives. You can drop the .7z archive directly into this folder --
the install pipeline auto-extracts it on demand via py7zr -- or
pre-extract the .img files yourself.

Either layout works (per dosassets/<mode>/ convention):

    dosassets/pcdos5/IBM_PC-DOS_5.00_(1991)_(3.5).7z
        or
    dosassets/pcdos5/Disk01.img
    dosassets/pcdos5/Disk02.img
    ...

Install pipeline (mirrors PCDOS7 / MSDOS5):
  1. Auto-extract .7z if present (skipped when .img files already
     staged).
  2. Build a sanitized DOS 5 boot floppy from Disk01.img and run it
     under QEMU.
  3. AUTOEXEC.BAT runs ``FDISK /MBR``, then ``FORMAT C: /S`` (feeds
     Y/Y/ENTER to the prompt sequence), then copies the rest of the
     setup-floppy DOS tools to C:\\DOS\\.
  4. Sets system+hidden attributes on IBMBIO.COM / IBMDOS.COM via
     mattrib.

PC-DOS 5 system files differ from MS-DOS 5: it ships ``IBMBIO.COM``
+ ``IBMDOS.COM`` instead of ``IO.SYS`` + ``MSDOS.SYS``. The verifier
accepts either set.

Note: ``dosassets/msdos5/`` is the SEPARATE folder for Microsoft
MS-DOS 5.0 install media -- do not mix.

This folder tracks readme.txt only; the install media itself is
gitignored.
