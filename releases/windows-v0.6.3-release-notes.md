# dosforge windows-v0.6.3 — three releases of Linux work, now on Windows

Companion to `linux-v0.6.1`, `v0.6.2`, and `v0.6.3`. This is the
first Windows bundle since `windows-v0.6.0` (shipped 2026-06-05),
folding in every Linux fix + feature from the three intervening
releases. The Linux v0.6.x sequence was explicitly designed to
share its TUI / GUI / sudo / PC-DOS 7.1 work with Windows; this
release picks all of that up.

## What's new since `windows-v0.6.0`

### From linux-v0.6.1 — sudo + TUI polish

- **Sudo "prompt once" + background keep-alive.** Headless `dosforge
  create` / `mount` / `unmount` now do the same startup `sudo -v`
  prompt the TUI/GUI have always used, so a single password entry
  primes the whole command. A daemon refreshes the kernel sudo
  timestamp cache every 60 seconds while a long build is in flight
  (PC-DOS 7.1 FAT32 install, Win95 OSR2 SYS) so the default 5-minute
  `timestamp_timeout` no longer kills mid-flight operations. (Linux
  only; Windows didn't have this problem.)
- **TUI dropdowns open on the first click.** Replaced the wizard's
  `Select` widgets with a `SingleClickSelect` subclass that opens
  the overlay on `MouseDown` and suppresses the parent `Select`'s
  default toggle handler to prevent the race-close on the
  synthesized click that follows mouse-up.
- **TUI focused buttons no longer flash inverted text.** Dropped
  `reverse` from `Button.btn-primary:focus` and set
  `ALLOW_SELECT = False` on `DosForgeApp`, so focused primary
  buttons stay bold instead of swapping foreground/background, and
  click-drag no longer paints a text-selection marquee.

### From linux-v0.6.2 — PC-DOS 7.1 utility hydration + spinner

- **PC-DOS 7.1 FULL profile auto-hydrates from PC-DOS 2000.** The
  SGTK ships an intentionally slim DOS (40 binaries — no EMM386,
  DOSSHELL, DEFRAG, BACKUP, RESTORE, SETVER, UNDELETE, HELP, PRINT,
  REPLACE, SHARE, INTERLNK / INTERSVR, ANSI.SYS, EGA.SYS, …). When
  you drop the WinWorldPC `IBM PC-DOS 2000 (3.5-1.44mb).7z` into
  `dosassets/pcdos2000/`, the PC-DOS 7.1 pre-fetcher now extracts
  the 6 floppies, runs `dosbox-x` + IBM's `UNPACK2.EXE` to expand
  the FTCOMP pack files, and merges the result into
  `dosassets/pcdos71/DOS/` with **SGTK winning every filename
  conflict**. The final `C:\DOS\` on every PC-DOS 7.1 VHD goes
  from 40 files to **138 files**, all authentic IBM binaries.
  Failure modes are graceful — missing archive → SGTK install
  still succeeds.
- **Create-button spinner + elapsed timer.** The TUI's *Create +
  format VHD* button used to block silently for the entire
  pipeline. Now it disables the button, prints `Creating +
  formatting <VHD\|IMG> <name>…`, animates a Braille spinner
  (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) with an `[elapsed Xs]` suffix at ~10 Hz, and
  prints `✓ Created and prepared in Xs:` on success.

### From linux-v0.6.3 — GUI parity for the PC-DOS 7.1 fetcher

- **`dosforge-gui.exe` gains the *Fetch PC-DOS 7.1 (SGTK) assets*
  button.** Shown only when boot-mode = PC-DOS 7.1, on the New
  Disk view's *Boot* card. Runs the exact same
  `fetch_pcdos71_assets()` pipeline the TUI uses (which is the
  same library I wired up in `13a8b54` and which became the
  `dosforge fetch-pcdos71-assets` CLI subcommand). On success
  auto-fills the *Boot assets* field with the staged target
  directory. Hydration progress streams into the GUI log panel
  via stdout capture; success message reports the SGTK file count
  plus, when PC-DOS 2000 hydration ran, `… plus N extra utilities
  from <archive> (M kept SGTK)`.

### Other improvements landed in this window

- Wizard layout: Boot/Media step swap so OS constraints flow into
  Media; nav buttons widened so *Next: Payload >* no longer wraps;
  size auto-snap to PC-DOS 7.1 FAT32's 1 GiB minimum.
- Wizard validation: *Next* blocks from the Media step on per-OS
  size/format violations instead of failing later in the pipeline.
- `gitignore` cleanup for an accidentally-tracked copilot CLI
  session marker.

## Same as `windows-v0.6.0`

All Windows-specific fixes from the `windows-v0.6.0` 86Box
verification pass (commit `d1130dd`) remain in place:

1. PCDOS alias hits only the QEMU install pipeline, not the
   static-template branch (fixed "non DOS media" error).
2. `msdos71 + FAT16` uses partition type `0x06` instead of `0x0E`
   so Win95 OSR2 `SYS A: C:` accepts the install.
3. PC-DOS 7.1 FAT16 false-positive timeout — final marker re-check
   after QEMU exit, `required_system_files` presence fallback, and
   `VHDMK.OK` write moved earlier in the install autoexec.

15-target 86Box matrix from `docs/WINDOWS_V6_VERIFICATION.MD` still
passes: every supported boot mode × FAT combination boots to a DOS
prompt with AUTO IDE → NORMAL translation.

## Build / run

```powershell
# Extract dosforge-0.6.3-windows-x64.zip somewhere convenient
cd dosforge

# CLI: build a 1 GiB PC-DOS 7.1 FAT32 bootable VHD with the new
# 138-file C:\DOS\ (requires WinWorldPC PC-DOS 2000 archive in
# dosassets\pcdos2000\):
.\dosforge fetch-pcdos71-assets       # one-time SGTK + PC-DOS 2000 fetch
.\dosforge create --media-type vhd --boot-mode pcdos71 ^
    --format fat32 --size 1G ^
    --path C:\my-vhds\pcdos71-1g.vhd

# Or launch the Textual TUI:
.\dosforge tui

# Or the desktop GUI (now has the SGTK fetcher button):
.\dosforge-gui
```

The `-cli` zip variant ships the same `dosforge.exe` and bundled
QEMU/mtools but drops the TUI + GUI dependencies (Textual, sv-ttk,
tkinter). Smaller download for users who only want the CLI.

## Known limitations on Windows

Unchanged since `windows-v0.6.0`:

- **`freedos + fat32`** is still rejected by
  `src/dosforge/disk.py:1917-1926`. The Linux v0.6.0 FreeDOS FAT32
  boot-sector fix unblocks adding it but the Windows path hasn't
  been wired up yet.
- **PC-DOS 7.1 FAT16 builds are slow on Windows** (~5 minutes vs
  ~30 s on Linux) because Windows QEMU runs without HW
  acceleration. The file-presence fallback added in `windows-v0.6.0`
  makes this purely cosmetic — the build still succeeds — but each
  VHD takes a few minutes to produce.

## What's in the zip

- `dosforge.exe` — CLI + TUI launcher (TUI in the `-full` variant only).
- `dosforge-gui.exe` — Tk-based desktop GUI (full variant only) **with
  the new Fetch PC-DOS 7.1 (SGTK) assets button**.
- `_internal/` — Python runtime + bundled QEMU + mtools + py7zr +
  optional textual/sv-ttk.
- `dosassets/<mode>/readme.txt` — 29 pre-populated mode folders ready
  for you to drop install media into. Drag your WinWorldPC .img/.7z
  files (and the IBM PC-DOS 2000 archive into `pcdos2000/`) here.

SHA-256 checksums listed below per artifact.
