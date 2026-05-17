FreeDOS bootable assets (slim bundle)
======================================

These files are FreeDOS — the open-source DOS-compatible operating
system — extracted from the FreeDOS 1.4 LiveCD and pre-organized for
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
Curated DOS userspace binaries shipped with FreeDOS. **Only the
`FDOS/BIN/` subdirectory is included in this slim bundle.** It
contains every executable a typical DOS session needs:

  - 36 EXE + 31 COM + 10 SYS binaries.
  - The full FreeDOS shell (`FREECOM/`) including the swap helper.
  - Core tools: EDIT, EDLIN, ATTRIB, CHOICE, COMP, DEBUG, DEVLOAD,
    DISPLAY, FC, FORMAT, LABEL, MEM, MODE, NANSI, SHARE, SORT, SYS,
    TREE, XCOPY, plus the FreeDOS XMS manager (FDXMS).
  - Optional / nice-to-have: CURL, LESS, GREP, SED, TOUCH, WCD, PING.

dosforge copies the entire `FDOS/` directory into C:\FDOS\ when the
user picks the `freedos` boot mode.

What was dropped from the bundle?
---------------------------------
Older versions of this bundle shipped the full 34 MB FreeDOS 1.4
LiveCD payload. The slim bundle drops these subdirectories to keep
the repo + release downloads under 10 MB:

  FDOS/APPS       Dos Navigator 2 (file manager)
  FDOS/APPINFO    FreeDOS package metadata for FDIMPLES
  FDOS/DEVEL      BWBasic interpreter
  FDOS/DOC        Per-tool documentation (txt/PDF)
  FDOS/HELP       Online help database used by `help <command>`
  FDOS/LINKS      Empty / symlink directory
  FDOS/NET        Networking stack (curl, links, ping, gopherus,
                  terminal — most require a DOS packet driver)
  FDOS/NLS        National language strings (i18n CPI files)
  FDOS/SOUND      Sound utilities (dosmid, opencp, sbpmixer, etc.)

How to get a richer FreeDOS install
-----------------------------------
If you want the full FreeDOS userland:

  1. Use `--freedos-source auto` — dosforge downloads the FreeDOS
     1.4 packages on demand from www.ibiblio.org. You can choose
     which package groups to include via the boot mode options.

  2. Drop your own FreeDOS LiveCD extraction at any path and pass
     `--boot-assets-path /path/to/freedos-1.4/` — dosforge will use
     that tree wholesale instead of this bundle.

Source: https://www.freedos.org/
License: GPL v2 / BSD (per file — see each component's LICENSE).
