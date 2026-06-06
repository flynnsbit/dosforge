# dosforge windows-v0.6.14 — warn users about FreeDOS slow builds

Quality-of-life follow-up after the v0.6.13 freedos+fat32 unlock.
After observing a 5+ minute FreeDOS FAT32 build on Windows with no
visual feedback past the "Creating + formatting…" line, the GUI /
TUI / CLI now surface an up-front hint that FreeDOS builds take
significantly longer than other DOS modes.

## What's new

### Slow-build warning on the boot-mode select (GUI)

When the user picks **FreeDOS** in the GUI's New Disk → Boot card,
the status bar immediately shows:

> FreeDOS stages ~1388 userspace files (FDOS/ tree including NLS
> locales) one at a time via mtools — expect 3-5 minutes on
> Windows, ~1 minute on Linux. Other DOS modes finish in 30-90
> seconds.

The right-side summary card also gains a **Build time: slow — see
status bar** row so the warning persists while the user is
filling out the rest of the wizard.

### Compact reminder on the Create button (GUI)

When the user clicks **Create + format VHD** with FreeDOS selected,
the busy-msg spinner now reads:

> Creating C:\path\to\fdos.vhd (FreeDOS: slow on Windows, expect 3-5 minutes)...

instead of the previous generic message. The full multi-line hint
also prints once to the GUI log pane.

### Same hint on TUI + CLI

- **TUI** `Create + format VHD` spinner shows `(FreeDOS: ~3-5
  minutes on Windows, see status log)` and prints the full hint
  via the status pane.
- **CLI** `dosforge create --boot-mode freedos ...` prints the hint
  to stdout before `manager.create_and_prepare(request)` starts.

### Architecture

All three surfaces (GUI, TUI, CLI) go through one new helper in
`src/dosforge/formlogic.py`:

```python
build_time_hint(state: FormState) -> str | None
build_time_hint_for_boot_mode(boot_mode: BootMode) -> str | None
```

The lower-level boot-mode form is what the TUI/CLI use (they work
against a built `CreateRequest`); the FormState form is what the GUI
uses (and also short-circuits for non-bootable IMG floppies that
don't stage any DOS payload).

This is intentionally extensible — when we eventually want to flag
PC-DOS 7.1 FAT16 on Windows as a slow build too (FORMAT C: /S runs
for 5+ minutes), the change is a one-line addition to
`build_time_hint_for_boot_mode`.

## Why FreeDOS is slow on Windows specifically

Other DOS boot modes stage **3-5 system files** onto the VHD
(`IO.SYS` + `MSDOS.SYS` + `COMMAND.COM`, or `IBMBIO.COM` +
`IBMDOS.COM` + `COMMAND.COM`). FreeDOS stages the **entire
userspace tree** — **1388 files**, 29 MB, including 258 NLS locale
files.

The Windows path uses one `mcopy.exe` subprocess invocation per
file. Each subprocess spawn on Windows costs ~50-200 ms. 1388 × 100 ms
= ~140 seconds minimum, typically 3-5 minutes in practice with
mtools open-the-VHD-and-write-one-file overhead.

The Linux path uses `cp -r` against a mounted partition (one
operation, finishes in seconds).

A future optimization would be to switch the FreeDOS payload to
`mcopy -s` (recursive, single invocation) on both platforms, which
would cut Windows build time from minutes to seconds. Tracked as a
perf follow-up; out of scope for this release.

## Tests

7 new cases in `tests/test_formlogic.py`:

- `test_build_time_hint_freedos_vhd_warns_about_file_count`
- `test_build_time_hint_freedos_img_system_format_warns`
- `test_build_time_hint_freedos_img_no_system_format_is_silent`
- `test_build_time_hint_other_modes_silent`
- `test_build_time_hint_for_boot_mode_freedos`
- `test_build_summary_appends_slow_row_for_freedos`
- `test_build_summary_no_slow_row_for_non_freedos`

All 70 existing formlogic + CLI + Windows VHD + PC-DOS 7.1 fetch
tests still pass.

## Same as `windows-v0.6.13`

Every fix from the v0.6.4 → v0.6.13 chain is preserved:

- FreeDOS + FAT32 on Windows (v0.6.13)
- DOSBox-X standard MinGW64 build w/ built-in MS-DOS emulation (v0.6.12)
- Windows mtools quirks all handled (v0.6.10, v0.6.11)
- PC-DOS 7.1 + PC-DOS 2000 hydration produces 138 files in `C:\DOS\` (v0.6.4-v0.6.12)

## Companion Linux release

`linux-v0.6.14` parity bump. The hint also fires on Linux for
consistency (says "~1 minute on Linux" instead of "3-5 minutes" so
expectations are set right per platform).

SHA-256 checksums listed below per artifact.
