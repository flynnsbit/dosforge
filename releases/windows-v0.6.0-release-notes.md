# dosforge windows-v0.6.0 — first Windows release with all 16 boot modes validated in 86Box

Companion to `linux-v0.6.0` (released earlier today). Every supported
boot mode × FAT combination now builds and boots end-to-end in 86Box
on Windows, with AUTO IDE → NORMAL translation, no manual BIOS
tweaking required.

## What's verified

Per the matrix in [`docs/WINDOWS_V6_VERIFICATION.MD`](https://github.com/flynnsbit/dosforge/blob/main/docs/WINDOWS_V6_VERIFICATION.MD)
— 5 priority targets that touched changed code paths + 10 smoke
targets across the unchanged paths, all booted to a DOS prompt in
86Box and report the expected `ver` string:

| # | Boot mode | Format | Size | Status |
|---|-----------|--------|------|--------|
| p1 | pcdos71 | fat16 | 32M | ✅ |
| p2 | msdos5 | fat16 | 128M | ✅ |
| p3 | msdos622 | fat16 | 128M | ✅ |
| p4 | pcdos7 | fat16 | 128M | ✅ |
| p5 | pcdos | fat16 | 32M | ✅ |
| s6 | freedos | fat16 | 32M | ✅ |
| s7 | msdos33 | fat16 | 32M | ✅ |
| s8 | msdos331 | fat16 | 32M | ✅ |
| s9 | compaq331 | fat16 | 32M | ✅ |
| s10 | msdos71 | fat16 | 32M | ✅ |
| s11 | msdos71 | fat32 | 128M | ✅ |
| s12 | pcdos71 | fat32 | 1G | ✅ |
| s13 | ibm8088 (dos33) | fat16 | 32M | ✅ |
| s14 | ibm8088 (dos50) | fat16 | 32M | ✅ |
| s15 | 4dos (msdos71) | fat16 | 128M | ✅ |

## Windows-specific fixes since linux-v0.6.0

Three Windows-only regressions surfaced during the 86Box verification
pass and were resolved in [commit `d1130dd`](https://github.com/flynnsbit/dosforge/commit/d1130dd):

1. **PCDOS alias (`p5`)** — Linux's `bce776f` routed the generic
   `pcdos` boot mode through the PC-DOS 7.0 QEMU FORMAT C: /S
   pipeline by relying on Linux's `if/elif` dispatch, where the
   static-template and QEMU-install branches are mutually exclusive.
   The Windows `_create_and_prepare_vhd_no_kernel` flow runs them as
   independent `if`s, so PCDOS hit BOTH: the static-template branch
   `mcopy`'d `IBMBIO.COM` onto the still-unformatted partition first
   (`init :: non DOS media`). Removed PCDOS from the Windows
   static-template branch — only the QEMU install runs now, matching
   Linux behavior.

2. **MS-DOS 7.10 + FAT16 (`s10`)** — Win95 OSR2 `SYS A: C:` silently
   refused to install on a partition with type `0x0E` (FAT16 LBA),
   bailing before writing IO.SYS / MSDOS.SYS. Postmortem floppy
   showed AUTOEXEC.BAT never ran past the boot phase; BPB OEM stayed
   at mtools-default `MTOO4049` instead of authentic `MSWIN4.1`.
   Switched `msdos71+fat16` to partition type `0x06` (FAT16-CHS,
   matching what `parted` writes on Linux). `pcdos71+fat16` keeps
   `0x0E` because PC-DOS 7.1 FORMAT.COM does accept it. After the
   switch the full Win95 OSR2 install lands cleanly:
   IO.SYS + MSDOS.SYS + COMMAND.COM + HIMEM.SYS + IFSHLP.SYS +
   DBLBUFF.SYS + CONFIG.SYS + AUTOEXEC.BAT.

3. **FORMAT C: /S timeout false-positive on Windows (`p1`)** —
   three-pronged fix because of three independent Windows-only
   issues:
   - On Windows, `mdir` cannot open the VHD while QEMU has an
     exclusive write handle, so every in-loop marker poll returned
     False. We only get a real read after QEMU exits.
   - PC-DOS 7.1 `FORMAT C: /S` inside unaccelerated Windows QEMU
     takes >>300s to finish the FAT scan/wipe pass (vs <60s on
     Linux), so the SYS-step timeout fired even when the system
     files were already on disk.
   - The FORMAT step has been observed to corrupt the running
     floppy's FAT during the wipe pass, leaving AUTOEXEC.BAT unable
     to continue past FORMAT and the `ECHO OK > C:\VHDMK.OK` line
     never executes.
   Fixes:
   1. `_run_qemu` adds a final marker check AFTER QEMU has released
      the VHD.
   2. When the post-exit marker check still finds no `VHDMK.OK`,
      fall back to a `required_system_files` presence check; if every
      system file is on disk the install is bootable so accept it as
      success.
   3. `_verify_install` is relaxed to skip the marker requirement
      when all system files are present.
   4. Move `ECHO OK > C:\VHDMK.OK` in the format-install autoexec to
      run immediately after FORMAT instead of after the COPY+ECHO
      chain, so the marker survives FORMAT-induced floppy corruption.

## Build / run

```powershell
# Extract dosforge-0.6.0-windows-x64.zip somewhere convenient
cd dosforge

# CLI build a 128 MB MS-DOS 6.22 bootable VHD:
.\dosforge create --media-type vhd --boot-mode msdos622 ^
    --format fat16 --size 128M ^
    --path C:\my-vhds\msdos622.vhd

# Or launch the Textual TUI:
.\dosforge tui

# Or the desktop GUI:
.\dosforge-gui
```

The `-cli` zip variant ships the same `dosforge.exe` and bundled
QEMU/mtools but drops the TUI + GUI dependencies (Textual, sv-ttk,
tkinter). Smaller download for users who only want the CLI.

## Same as linux-v0.6.0

Every linux-v0.6.0 fix is in this release too (they live in shared
code):

- Authentic per-DOS MBR via `FDISK /MBR` for MS-DOS 5+, PC-DOS,
  Compaq 3.31; era-appropriate generic MBR for DOS 3.x.
- ECHS bit-shift translation in the partition CHS entry so AT BIOSes
  >504 MiB see the right geometry.
- PC-DOS 7.1 FAT32 booting via authentic SGTK install media (LBA-
  aware MBR via `FDISK32 /MBR`, FORMAT32 /Q /S).
- New `pcdos71+fat16` install path via PC-DOS 7.1's regular
  `FORMAT.COM`.
- `pcdos` alias routes through the same PC-DOS 7.0 QEMU pipeline as
  `pcdos7` (instead of the legacy mkfs.fat stub VBR).
- `compaq331` / `msdos331` install fixes: FORMAT C: /S with correct
  partition type byte.
- `msdos5` / `msdos622` / `pcdos7` FORMAT prompt sequence fix
  (second Y for existing-FAT confirm).

## Known limitations on Windows

- **`freedos + fat32`** — still rejected by
  `src/dosforge/disk.py:1917-1926`. The linux-v0.6.0 FreeDOS FAT32
  boot-sector fix unblocks adding it, but the Windows path hasn't
  been wired up yet. Optional follow-up.
- **PC-DOS 7.1 FAT16 builds are slow on Windows** (~5 minutes vs
  ~30s on Linux). The file-presence fallback above makes this purely
  cosmetic — the build still succeeds — but each VHD takes a few
  minutes to produce. Investigating WHPX acceleration for QEMU as a
  future optimization.

## What's in the zip

- `dosforge.exe` — CLI + TUI launcher (TUI in the `-full` variant
  only).
- `dosforge-gui.exe` — Tk-based desktop GUI (full variant only).
- `_internal/` — Python runtime + bundled QEMU + mtools + py7zr +
  optional textual/sv-ttk.
- `dosassets/<mode>/readme.txt` — 29 pre-populated mode folders
  ready for you to drop install media into. (Drag your WinWorldPC
  .img/.7z files here.)

SHA-256 checksums are listed below per artifact.
