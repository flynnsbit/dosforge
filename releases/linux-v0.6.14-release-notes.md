# dosforge linux-v0.6.14 — surface FreeDOS slow-build warning across GUI/TUI/CLI

User-facing quality-of-life improvement. FreeDOS' ~1388-file FDOS
userspace tree takes noticeably longer to stage than other DOS modes
(both platforms, but more pronounced on Windows). All three front-ends
now warn up-front so the user knows the spinner is going to be on-
screen for "a minute or two on Linux, 3-5 minutes on Windows"
instead of guessing whether the build is stuck.

## What's new

### Warning surfaces in all three front-ends

- **GUI** (`dosforge gui` / `dosforge-gui.exe`): picking FreeDOS in
  the boot-mode select immediately updates the status bar with the
  full hint; right-side summary card gains a *Build time: slow*
  row; Create button's busy message gets the compact "(FreeDOS:
  slow on Windows, expect 3-5 minutes)" suffix.
- **TUI** (`dosforge tui`): Create + format VHD spinner shows
  `(FreeDOS: ~3-5 minutes on Windows, see status log)`.
- **CLI** (`dosforge create --boot-mode freedos ...`): full hint
  prints to stdout before the build starts.

### Architecture

All three surfaces share one helper:

```python
# src/dosforge/formlogic.py
build_time_hint(state: FormState) -> str | None
build_time_hint_for_boot_mode(boot_mode: BootMode) -> str | None
```

Extensible — adding more "slow build" modes is a one-line edit to
`build_time_hint_for_boot_mode`.

## Why FreeDOS is slow

FreeDOS stages the entire userspace tree (~1388 files, 29 MB
including 258 NLS locale files) into the VHD via mtools.

- **Linux** uses `cp -r` against a mounted partition: ~1 minute.
- **Windows** uses one `mcopy.exe` subprocess per file (~50-200 ms
  spawn overhead each): typically 3-5 minutes.

All other DOS modes stage 3-5 system files and complete in
30-90 seconds.

## Tests

7 new cases in `tests/test_formlogic.py` covering the helper's
behavior across all boot modes + the summary-row integration. All
70 existing formlogic + CLI + Windows VHD + PC-DOS 7.1 fetch tests
still pass.

## Same code as `linux-v0.6.13`

No backend / boot-mode changes. Pure UX layer.

## Upgrade

```bash
cd releases/v0.6.14
chmod +x install.sh
./install.sh
```

Or in-place:

```bash
python -m pip install --user --upgrade releases/v0.6.14/dosforge-0.6.14-py3-none-any.whl
```
