IBM PC-DOS 3.0 / 3.10 / 3.20 / 3.30 install assets
===================================================

Staging area for IBM PC-DOS 3.x releases:
  3.00 — IBM PC/AT launch DOS
  3.10 — bug-fix release
  3.20 — 720 KiB 3.5" floppy support
  3.30 — extended partition support, hard-disk improvements

Expected files: 5.25" DS/DD (360 KiB) or 3.5" DS/DD (720 KiB)
floppy images per the version.

Status: dosforge does not yet ship a boot-mode=pcdos3. The
existing generic boot-mode=pcdos can be pointed here, but the
default pcdos resolver is tuned for PC-DOS 4.01+ and may not
produce a working result without further work. Until dedicated
support lands the tool will report "no install images found".

Source (WinWorldPC): "IBM PC-DOS 3.00 / 3.10 / 3.20 / 3.30".

This folder tracks readme.txt only; the install media itself is
gitignored.
