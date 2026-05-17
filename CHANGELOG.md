# Changelog

All notable changes to `dosforge` are documented in this file.

The format is loosely based on [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/).

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
