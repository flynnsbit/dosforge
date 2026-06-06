MS-DOS 7.1 install assets — DEPRECATED for VHD builds
=====================================================

NOTE (2026-05-25): dosforge no longer uses these "Microsoft DOS 7.1"
disk01.img / disk02.img files to build MS-DOS 7.10 VHDs.  The Chinese
re-release stored in DOS71_1S.PAK ships ``IO.SYS`` as an MZ-wrapped
SETUP stub that the original installer normally unpacks; extracting it
raw yields an unbootable disk ("Invalid system disk" from the MS-DOS
7.10 VBR).

For VHD builds, use authentic Win95 OSR2 (4.00.1111) floppies under
``dosassets/w95/`` instead — that path drives a QEMU-based SYS A: C:
install that produces a byte-equivalent disk.  See
``dosassets/w95/readme.txt`` for the expected layout.

The original PAK-based files in this directory are still recognised by
some older dosforge floppy IMG code paths (``--media-type img
--boot-mode msdos71``), but VHD builds will error if pointed here.

Used by: boot-mode=msdos71 (legacy floppy IMG path only).

This folder is intentionally kept under version control via this
readme.txt; the install media itself is gitignored.

