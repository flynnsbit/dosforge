# dosforge windows-v0.6.15 — minimal-authentic FreeDOS payload filter

User-raised authenticity correction: the FreeDOS path was xcopy-ing
the entire WinWorldPC FullCD bundle (1388 files, 29 MB including 258
NLS locale files for 20+ languages, 361 sound-card drivers, 232
APPINFO package-metadata files, 213 DOC files, 173 HELP files,
etc.) onto every FreeDOS VHD. A real FreeDOS Setup install never
copies all of those by default — it stages KERNEL.SYS + COMMAND.COM
at the root plus the active PATH= target (C:\\FDOS\\BIN\\\\*) plus any
files explicitly referenced from CONFIG.SYS / AUTOEXEC.BAT.

dosforge now matches that behavior. FreeDOS builds went from 5+
minutes (1388-file stage) to ~47 seconds (~85-file stage) on
Windows, and the resulting VHD is authentic to what FreeDOS Setup
would produce.

## Root cause

`BootAssetResolver._resolve_freedos_from_directory` set
`assets.fdos_payload_dir = directory / "FDOS"` and let
`_copy_payload_via_mtools` walk the entire tree, one mcopy
subprocess per file. The WinWorldPC FullCD source ships every
optional package — none of which Setup copies for a default install.
Other DOS modes already stage only their authentic system files
(IO.SYS / MSDOS.SYS / COMMAND.COM, ~3-5 files); FreeDOS was the
sole outlier.

## Fix

New `BootAssetResolver._select_minimal_freedos_payload(source,
partition_root)` builds a cached, filtered staging tree containing
only:

- Everything under `BIN/` (the active PATH=C:\\FDOS\\BIN target —
  ~84 files on FreeDOS 1.3 including ASSIGN, ATTRIB, CHOICE,
  DEBUG, EDIT, FDISK, FORMAT, KEYB, MEM, MODE, MOUSE, NANSI,
  SHARE, SORT, TREE, XCOPY plus the FREECOM/ subtree).
- Any file referenced by an uncommented `DEVICE=` / `DEVICEHIGH=` /
  `INSTALL=` / `SHELL=` line in the partition root's CONFIG.SYS /
  FDCONFIG.SYS.
- Any file referenced by an explicit `\\FDOS\\...` or
  `C:\\FDOS\\...` path in the partition root's AUTOEXEC.BAT /
  FDAUTO.BAT (covers `LH C:\\FDOS\\MOUSE.COM` and similar
  patterns).

Commented-out lines (starting with `;`, `;?`, or `REM`) are
deliberately skipped — they don't pull files in.

### What gets dropped (matching Setup defaults)

- `FDOS/APPINFO/` (232 files of package-manager metadata)
- `FDOS/APPS/` (48 optional GUI/editor packages)
- `FDOS/DEVEL/` (Pascal/C compilers — opt-in)
- `FDOS/DOC/` (213 documentation files)
- `FDOS/HELP/` (173 help-system files)
- `FDOS/LINKS/` (FreeDOS distro provenance)
- `FDOS/NET/` (curl/links/ping/etc. — opt-in)
- `FDOS/NLS/` (258 non-English locale files; a real install picks 1-2)
- `FDOS/SOUND/` (361 sound-card drivers — opt-in)

A user who needs any of these can either uncomment the relevant
reference in CONFIG.SYS / AUTOEXEC.BAT (will be auto-staged), or
drop a curated `dosassets/freedos/FDOS/` tree without the bloat
subdirs (filter detects this and is a no-op).

### Caching

Filtered output goes to
`<app_cache>/boot-assets/freedos-min-<hash>/` keyed on
`(source_payload_dir, partition_root, max-mtime of source)`. Repeat
builds reuse the staging dir without re-walking the source. Marker
file lives ALONGSIDE the staging dir (not inside it) so it doesn't
leak onto the user's VHD.

### Defensive: no-op when there's no bloat to filter

If `dosassets/freedos/FDOS/` doesn't contain any of the known FullCD
subdirs (APPINFO/APPS/DEVEL/DOC/HELP/LINKS/NET/NLS/SOUND), the
filter is skipped entirely and the raw payload_dir is used.
Protects users who have already curated their FreeDOS payload from
unintended side-effects.

## Before / after on Windows

| Stage | v0.6.14 (1388 files) | v0.6.15 (85 files) |
|---|---|---|
| VHD allocation (256 MB) | ~5s | ~5s |
| mformat FAT32 | ~10s | ~10s |
| FreeDOS payload mcopy | **5+ minutes** | **~30s** |
| BPB patches | <1s | <1s |
| **Total build time** | **5-7 min** | **~47s** |

Output VHD has 7 root files (KERNEL.SYS, COMMAND.COM, CONFIG.SYS,
FDCONFIG.SYS, AUTOEXEC.BAT, FDAUTO.BAT, FDOS/) + 84 files under
`C:\\FDOS\\BIN\\` (matching real FreeDOS Setup "Standard" install).

## Knock-on cleanup: v0.6.14 slow-build warning removed

The v0.6.14 GUI/TUI/CLI "FreeDOS stages ~1388 files, expect 3-5
minutes on Windows" warning is removed. With the new ~47s build time
it no longer earns a warning. The warning infrastructure
(`formlogic.build_time_hint`, `build_time_hint_for_boot_mode`,
the summary card slot, the GUI status-bar wiring) is preserved so a
future boot mode can be flagged with a one-line edit if needed.

## Tests

6 new cases in `tests/test_boot_assets.py`:

- `test_freedos_filter_drops_bloat_subdirs`
- `test_freedos_filter_keeps_bin_recursively`
- `test_freedos_filter_picks_up_uncommented_config_refs`
- `test_freedos_filter_ignores_commented_directives`
- `test_freedos_filter_is_noop_for_curated_bin_only_bundle`
- `test_freedos_filter_cache_hits_on_unchanged_source`

`tests/test_formlogic.py` updated to assert the slow-build hint
now returns None for every mode (was: returned a warning for
FreeDOS).

All 130 focused tests (test_boot_assets + test_formlogic +
test_disk_windows_vhd + test_cli) pass.

## Live-verified on Windows

```
$ dosforge create --media-type vhd --boot-mode freedos --format fat32 \
      --size 256M --path C:\test\fdos.vhd --overwrite
Created and prepared C:\test\fdos.vhd  (47 seconds)

$ dosforge ls --all C:\test\fdos.vhd /
KERNEL  SYS  46256  ...
COMMAND COM  87772  ...
CONFIG  SYS    209  ...
AUTOEXEC BAT   535  ...
FDCONFIG SYS   209  ...
FDAUTO  BAT    535  ...
FDOS         <DIR>  ...
```

## Authenticity note

This brings FreeDOS in line with the existing authenticity rule
("byte-equivalent to a real install from THAT DOS's authentic
media"). The FullCD-dumping behavior was a leftover from when
FreeDOS staging predated the per-DOS authenticity profile registry.
PC-DOS 7.1 FULL profile remains the ONLY documented cross-DOS-
borrowing exception (it merges PC-DOS 2000 utilities — also
authentic IBM binaries).

## Same as `windows-v0.6.14`

Every fix from the v0.6.7→v0.6.14 chain is preserved:

- FreeDOS + FAT32 on Windows (v0.6.13)
- DOSBox-X standard MinGW64 build (v0.6.12)
- Windows mtools quirks all handled (v0.6.10, v0.6.11)
- PC-DOS 7.1 + PC-DOS 2000 hydration produces 138 files in `C:\\DOS\\`

## Companion Linux release

`linux-v0.6.15` parity bump. The filter benefits Linux too (smaller
on-disk file count, faster cp-based staging) but the wall-clock
improvement is less dramatic (Linux already used `cp -r` against a
mounted partition; 1388-file builds took ~1 minute vs. 5+ on
Windows).

SHA-256 checksums listed below per artifact.
