# Changelog

All notable changes to `dosforge` are documented in this file.

The format is loosely based on [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-05-19

**Windows port complete — feature parity with Linux.**

### Added — Windows platform

- **Single-file installer & launcher.** New `dosforge.bat` and
  `dosforge.ps1` at the repo root forward every argument to the
  PyInstaller bundle at `dist\dosforge\dosforge.exe`. Just run
  `.\dosforge` from the project root.
- **Native VHD mount on Windows** via `Mount-DiskImage` (Storage
  module, built into Windows 8+; requires admin elevation). Mounts
  to a real drive letter, tracked in dosforge's state store. Without
  admin: clear elevation hint + no-admin alternatives (the mtools
  verbs below).
- **mtools-based image content verbs** that work cross-platform
  WITHOUT mounting. Drop-in replacement for `mount` on Windows when
  you don't want to elevate, and useful on Linux too:
  - `dosforge ls <image> [path]`
  - `dosforge cat <image> <path>`
  - `dosforge get <image> <dos-path> [local]`
  - `dosforge put <image> <local> [dos-path]`
  - `dosforge rm <image> <path>`
  - `dosforge mkdir <image> <path>`
  Auto-detects partition offsets on VHDs; works on flat
  `.img`/`.ima`/`.vfd`/`.dsk`/`.xdf` too.
- **PC-DOS 7.1 boot mode (FAT32)** — the only PC-DOS variant with
  FAT32+LBA support, sourced from the IBM ServerGuide Scripting
  Toolkit per [vogons.org/viewtopic.php?t=93030](https://www.vogons.org/viewtopic.php?t=93030).
  Driven by an in-QEMU `FORMAT32 /Q /S` install that writes the
  correct `IBM  7.1` boot sector and stages
  IBMBIO.COM+IBMDOS.COM+COMMAND.COM in the cluster order PC-DOS 7.1's
  boot loader requires (plus the +R+S+H attribute fix). Tested
  end-to-end with the full SGTK utility tree under `C:\DOS\`.
- **MS-DOS 5.0, 6.22, PC-DOS, PC-DOS 7.0 boot modes on Windows.**
  Previously Linux-only. Now driven by the static-template
  resolver path against the Windows bundle.
- **`.7z` and `.zip` archive auto-extraction.** Drop a WinWorldPC
  archive into `dosassets/<mode>/` and dosforge transparently
  unpacks it on the next resolver run, materializing the
  `.img`/`.xdf`/`.ima`/`.dsk`/`.vfd` install media and DOS system
  files into the asset directory alongside the archive. User files
  never overwritten.
- **`open_in_files` works on Windows** via `os.startfile`. The TUI's
  "Open in file manager" buttons now open Explorer.
- **Cross-platform file picker.** TUI's Browse buttons use native
  Win32 dialogs (`tkinter.filedialog`) on Windows; zenity on Linux.
- **VHDs are now fully allocated on Windows** (de-sparsed after
  `qemu-img` creation). Without this, `Mount-DiskImage`, Windows
  Disk Management's "Attach VHD", 7-Zip's VHD reader, and several
  other tools all reject the file. Adds a one-time 5–15s per 100 MiB
  cost at creation.
- **`Fetch latest FreeDOS` button** now works on Windows. Falls back
  to `mformat` when `mkfs.fat` (Linux-only) isn't present.

### Added — boot-mode coverage

- **MartyPC Xebec Type 1 (10 MiB FAT12) + MS-DOS 3.3** boot path
  verified on Windows end-to-end.
- **`testimages/` build harness** (`scripts/build-testimages.ps1`)
  produces a bootable image for every supported `(media, boot mode,
  machine target)` combination. **29 images built clean on Windows**
  including FreeDOS, MS-DOS 3.30/3.31/5.0/6.22/7.1, PC-DOS 7.0/7.1,
  Compaq DOS 3.31, IBM 8088 DOS 3.3, plus the FULL DOS install
  profile (C:\DOS\ tools tree) variants of each.

### Changed

- TUI: `mount`/`unmount` buttons and the privilege-diagnostics
  button are now backend-gated. Sudo re-auth wrapper short-circuits
  on backends that don't require sudo.
- Error messages for missing install media now dump the relevant
  `dosassets/<mode>/readme.txt` so you know exactly which files to
  drop in and where to source them (typically WinWorldPC).
- Matrix test (`test_windows_cli_matrix.py`): 34 PASS + 1 SKIP.
  12 platform-neutral unit-test files re-enabled on Windows
  (was 27 PASS + 1 SKIP; now **295 PASS + 79 SKIP** total).

### Fixed

- PC-DOS 7.1 boot — three sequential fixes:
  1. Apply +R +S +H to IBMBIO.COM/IBMDOS.COM after FORMAT32 /S
     (PC-DOS boot loader scans for entries with System+Hidden set).
  2. Write the MBR boot code explicitly (FORMAT32 writes the VBR
     but not the MBR; bytes 0–439 were all zero before this).
  3. Ship a PC-DOS-dialect CONFIG.SYS (`LASTDRIVE=Z` not `LASTDRIVE=26`,
     no `DOS=HIGH,UMB,AUTO`).
- mtools out-of-image destination paths on Windows. mtools parses
  any positional arg starting with `<letter>:` as a DOS drive
  (`Drive 'C:' not supported`); fixed by passing `cwd=output_dir`
  + bare filename for every `mcopy` extraction call.
- FreeDOS auto-fetch on Windows (was: `Missing required tools for
  FreeDOS extraction: mkfs.fat`). Now uses `mformat` as a fallback.

### Notes

- Linux behavior is unchanged — every Linux-only code path
  (`qemu-nbd`, kernel `mount`, sudo, syslinux MBR) still runs as
  before. The Windows port is additive.
- `dosforge mount`/`unmount` are now available on Windows but
  require admin elevation (Mount-DiskImage loads the storage
  virtualization driver). For unprivileged image access, use the
  new `dosforge ls/cat/get/put/rm/mkdir` verbs instead.
- Floppy IMG (raw `.img`/`.ima`) cannot be mounted natively on
  Windows — `Mount-DiskImage` only supports `.vhd`/`.vhdx`/`.iso`.
  Use the mtools verbs for floppy IMGs.

## [0.2.2] — 2026-05-17

### Changed

- **Slimmed the bundled FreeDOS payload from 34 MB / 1,399 files
  down to 7 MB / 95 files.** Drops the FreeDOS userspace
  subdirectories that very few users actually need on a DOS-box
  build:

  - `FDOS/APPS` (Dos Navigator 2)
  - `FDOS/APPINFO` (FDIMPLES package metadata)
  - `FDOS/DEVEL` (BWBasic interpreter)
  - `FDOS/DOC` (per-tool documentation)
  - `FDOS/HELP` (`help <command>` database)
  - `FDOS/NET` (curl / links / ping / gopherus / terminal — most
    need a DOS packet driver which emulators rarely have set up)
  - `FDOS/NLS` (national-language CPI files)
  - `FDOS/SOUND` (DOSMID, OpenCP, etc.)
  - `FDOS/LINKS` (empty)

  Kept: all root boot files + the entire `FDOS/BIN/` directory
  (84 files — 36 EXE + 31 COM + 10 SYS + a small support set,
  including FREECOM, EDIT, EDLIN, ATTRIB, MEM, MODE, SYS, FORMAT,
  XCOPY, FDXMS, …). No source code is bundled.

  Users who want the full FreeDOS userland can pass
  `--freedos-source auto` (downloads from www.ibiblio.org on
  demand) or `--boot-assets-path /path/to/freedos-1.4/` to point
  at an external tree.

### Removed (git history)

- The same nine `FDOS/<subdir>` paths were also purged from every
  reachable commit via `git filter-repo`. This includes the
  duplicate copies under `releases/v0.1.0/` through
  `releases/v0.2.1/dosassets/freedos/`. The repo's pack file is
  ~4 MB smaller and clones download fewer redundant blobs.
- **Force-push notice:** anyone with an existing local clone
  needs to either:
  - re-clone the repo, or
  - run `git fetch --all && git reset --hard origin/main`
    (this will discard any local commits on `main`).
  The v0.2.0 and v0.2.1 tags were re-tagged after the rewrite
  and now point at the post-rewrite commits. GitHub Release
  assets are keyed by release-ID (not tag-SHA), so all v0.2.0 /
  v0.2.1 downloads remain intact and unchanged.

## [0.2.1] — 2026-05-17

### Fixed

- TUI header now displays "DosForge" instead of the leftover
  "VHD Maker" string (and the zenity sudo-prompt title is also
  "DosForge sudo authentication"). The original rename pass
  grepped for the lowercase token `vhdmaker` and missed the
  spaced/CamelCased variants.

## [0.2.0] — 2026-05-17

### Added

- **Classic AT BIOS HDD type presets (Phoenix + AMI Types 1–45).**
  When a Phoenix/AMI Type N entry is picked, dosforge locks the VHD
  footer CHS to that type's exact geometry so 86Box's BIOS
  auto-detect screen shows "Type N — Cyl×Hd×Spt" instead of
  "User-defined / 86B_HD00". Includes both vendor tables (identical
  for Types 1–32, divergent for some 33–45 entries).
- New CLI flag `--bios-drive-type <vendor>:<N>` (e.g. `phoenix:1`,
  `ami:45`, `auto:N` aliasing `phoenix:N`).
- New CLI subcommand `dosforge list-bios-drive-types` prints the
  full Phoenix + AMI tables with Cyl / Hd / Pre / LZ / Spt / Size.
- New TUI selector "Disk type" — defaults to "Custom — use size
  field"; picking a Phoenix/AMI type auto-fills the size input
  (read-only) with the preset's MB value. Hidden when a MartyPC
  machine target is selected (those have their own preset tables).
- `BIOSVendor` enum, `BIOSDriveSpec` dataclass, `BIOS_AT_DRIVE_TYPES`
  registry, `lookup_bios_drive_type()`, `iter_bios_drive_types()`,
  `parse_bios_drive_slug()` in `dosforge.models`.

### Changed

- `CreateRequest.bios_drive_type: tuple[BIOSVendor, int] | None`
  field (default `None` = current behavior).
- `_normalize_vhd_size_for_chs` now respects `bios_drive_type` and
  returns the preset's `cyl × heads × spt × 512` size.
- `_create_fixed_vhd` writes the preset's CHS verbatim into the VHD
  footer (skips the 16h/63s canonical normalization) when a BIOS
  preset is selected — same mechanism MartyPC presets use.
- Mutually exclusive with MartyPC machine targets; validation
  rejects combining them with a clear error.
- Boot-mode size caps still apply: e.g. Phoenix Type 4 (62 MB) +
  `boot-mode=msdos33` raises a "MS-DOS 3.30 32 MiB cap" error.

## [0.1.2] — 2026-05-17

### Fixed

- **`msdos331` install media detection broadened**. The 0.1.1
  release only accepted Compaq-style `STARTUP.IMG`/`STARTUP.IMA`
  filenames and used `IBMBIO.COM` as the system-file marker, so
  the more common "Microsoft DOS 3.31" archives (which ship as
  `Disk1.img` with `IO.SYS`/`MSDOS.SYS`) failed with
  "MS-DOS 3.31 boot mode requires a bootable install diskette".
  The descriptor now accepts `DISK1.IMG`, `DISK01.IMG`,
  `STARTUP.IMG`, and their `.IMA` variants, and uses `IO.SYS`
  as the heuristic-fallback marker.
- **`compaq331_profile` post-install verification accepts either
  system-file flavor**. `required_system_files` entries can now
  be a tuple of alternatives (e.g. `("IBMBIO.COM", "IO.SYS")`),
  so an install from a Microsoft-flavored Disk1.img isn't
  rejected for "missing IBMBIO.COM" when its SYS-equivalent
  `IO.SYS` is present.

## [0.1.1] — 2026-05-17

### Fixed

- **`msdos331` boot hang at "Verifying DMI pool data"**: the
  static-boot-template install path produced an unbootable VHD
  because the DOS 3.31 boot loader couldn't navigate the
  `mkfs.fat` BPB (reserved_sectors=4 / 8). Routed `msdos331`
  through the same QEMU-driven `SYS C:` install pipeline as
  `compaq331` so the boot sector is authentic.

### Changed

- **`msdos331` is now capped at 32 MiB** (FAT16 short, MBR
  partition type `0x04`) to match what Microsoft's MS-DOS 3.31
  kernel actually addresses. Only the Compaq OEM kernel
  (`compaq331`) supports FAT16B up to ~504 MiB. Both modes share
  the same Compaq DOS 3.31 install media in
  `dosassets/msdos331/` or `dosassets/compaq331/`.
- **`compaq331` is now explicitly capped at 504 MiB** with a
  clear validation error when exceeded (was previously silently
  allowed up to FAT16's 2 GiB limit, which doesn't actually
  boot).
- New constants `MSDOS331_MAX_BYTES` and `COMPAQ331_MAX_BYTES`
  in `dosforge.size`.

## [0.1.0] — 2026-05-16

First public release. The tool was previously developed under the name
`vhdmaker`; the rename to `dosforge` happened immediately prior to this
release. The legacy CLI command and migration shims have been removed —
`dosforge` is the only supported entry point.

### Added

- **Image creation**
  - Fixed-size VHD output (FAT12 / FAT16 / FAT32) targeting 86Box,
    MartyPC, QEMU, and other PC emulators.
  - Floppy IMG output for 160 KB / 180 KB / 320 KB / 360 KB / 720 KB /
    1.2 MB / 1.44 MB / 2.88 MB diskette geometries.
- **Boot modes** (i.e. `--boot-mode` options) with working install
  pipelines:
  - `freedos` (local or auto-downloaded LiveCD)
  - `msdos71` (with FAT32 boot template fix-ups)
  - `ibm8088` (DOS 3.3 + DOS 5.0 routes; DOS 3.3 reuses the msdos33
    QEMU FORMAT pipeline)
  - `msdos33` (`FORMAT C: /S` driven inside QEMU)
  - `msdos331` / `compaq331` (FAT16B, `SYS C:` driven inside QEMU)
  - `msdos5` / `msdos622` / `pcdos` / `pcdos7`
- **Machine targets** (`--machine-target`) with byte-exact footer CHS,
  partition layout, and BPB geometry:
  - `martypc-xebec` (4 MFM Xebec drive types, including FAT12 for Type 1)
  - `martypc-xtide` / `martypc-jride` (127-entry AT format table)
  - `generic` (default 16h/63spt layout for 86Box AUTO IDE)
- **Install profiles**: `minimal` (boot files only) vs `full` (DOS
  utilities staged under `C:\DOS\` plus normalized CONFIG.SYS /
  AUTOEXEC.BAT). For pre-DOS-5 boot modes the CONFIG.SYS template
  uses DOS-3.3-compatible directives (no `DOS=HIGH`, no two-arg
  `BUFFERS`, no `LASTDRIVE=<number>`).
- **MartyPC Xebec MBR** rewrite: writes a CHS-only DOS-3.3 MBR boot
  loader with a track-aligned partition entry (LBA=spt, real start /
  end CHS values) — byte-identical to a real DOS-3.3 FDISK install.
- **Asset layout**: all DOS-version install media lives under
  `dosassets/<bootmode>/`. Resolver auto-finds `dosassets/<name>/`
  when the user passes a bare boot-mode name.
- **Custom payload fit-check** for fixed-size MartyPC drives (rejects
  oversized payloads with a clear error instead of failing mid-build).
- **Textual TUI** with media-type / boot-mode / machine-target gating
  and dynamic visibility logic; CLI mirrors every flag.
- **Desktop integration**: pixel-bright hammer-strikes-anvil icon
  (SVG + pre-rendered PNGs at 16/24/32/48/64/128/256 px), a
  `dosforge-launcher` wrapper that picks a sensible working
  directory and opens the TUI in the user's preferred terminal,
  and a `dosforge.desktop` entry — so walker (Omarchy) or any
  XDG-aware app menu lists DOSforge with the custom icon. Bundled
  under `desktop/` in each release; installed automatically by
  `install.sh` unless `--no-desktop` is passed.
- **Release tooling**: `scripts/build-release.sh` assembles a
  self-contained `releases/v<version>/` bundle (wheel + sdist +
  `dosassets/` + `desktop/` + distro-aware installer + SHA-256
  manifest).

### Removed (vs. the previous `vhdmaker` project name)

- The `vhdmaker` CLI command. Run `dosforge` instead.
- The `VHDMAKER_*` env-var fallbacks. Use `DOSFORGE_*` instead.
- The `~/.local/state/vhdmaker/` state-dir auto-migration (the new
  path is `~/.local/state/dosforge/`).
