FreeDOS bootable assets
=======================

These files are FreeDOS — the open-source DOS-compatible operating
system — extracted from the FreeDOS LiveCD and pre-organized for
dosforge's `boot-mode=freedos` (local source) flow. The contents are
GPL/BSD-licensed and freely redistributable, so they live under
version control inside this repo (unlike the other dosassets/
subdirectories, which only carry a readme.txt placeholder).

Top-level files
---------------
  KERNEL.SYS              FreeDOS kernel
  COMMAND.COM             FreeDOS shell
  AUTOEXEC.BAT / CONFIG.SYS    plain-text startup
  FDAUTO.BAT / FDCONFIG.SYS    FreeDOS-specific aliases used by SYS
  BOOTSECT_FAT16.BIN      FAT16 boot sector template
  BOOTSECT_FAT32.BIN      FAT32 boot sector template
  MBR_FAT16.BIN           MBR boot loader template

FDOS/
-----
Curated DOS userspace shipped with FreeDOS (editor, tools, drivers,
help system, …). dosforge copies this into C:\FDOS\ when the user
picks the `freedos` boot mode.

dosforge can also fetch FreeDOS directly from the upstream LiveCD
image (`--freedos-source auto`). Use this local copy when you want
reproducible builds without an internet dependency.

Source: https://www.freedos.org/
License: GPL v2 / BSD (per file — see each component's LICENSE).
