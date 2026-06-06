# dosforge linux-v0.6.15 — minimal-authentic FreeDOS payload filter

User-raised authenticity correction: the FreeDOS path was xcopy-ing
the entire WinWorldPC FullCD bundle (1388 files, 29 MB) onto every
FreeDOS VHD. A real FreeDOS Setup install never copies all of those
by default — it stages KERNEL.SYS + COMMAND.COM at the root plus the
active PATH= target (C:\\FDOS\\BIN\\\\*) plus any files explicitly
referenced from CONFIG.SYS / AUTOEXEC.BAT. dosforge now matches that
behavior.

## What changed

`BootAssetResolver._select_minimal_freedos_payload(source,
partition_root)` builds a cached, filtered staging tree containing
only:

- Everything under `BIN/` (~84 files: the active PATH= target).
- Files referenced by uncommented `DEVICE=` / `DEVICEHIGH=` /
  `INSTALL=` / `SHELL=` lines in CONFIG.SYS / FDCONFIG.SYS.
- Files referenced by explicit `\\FDOS\\...` paths in AUTOEXEC.BAT
  / FDAUTO.BAT.

Dropped from staging (Setup never copies these by default):
`FDOS/APPINFO/`, `FDOS/APPS/`, `FDOS/DEVEL/`, `FDOS/DOC/`,
`FDOS/HELP/`, `FDOS/LINKS/`, `FDOS/NET/`, `FDOS/NLS/`,
`FDOS/SOUND/`. Users who want any of these can either reference them
from CONFIG.SYS / AUTOEXEC.BAT (auto-stages) or curate their
`dosassets/freedos/FDOS/` to drop the bloat dirs (filter is a no-op
in that case).

## Linux impact

Wall-clock improvement is less dramatic than on Windows (the Linux
NBD-mount path already used `cp -r` against a mounted partition, so
1388-file builds completed in ~1 minute). The **on-disk file count
improvement** is the same: ~85 files vs 1388, matching authentic
FreeDOS Setup output.

| Stage | v0.6.14 (1388 files) | v0.6.15 (85 files) |
|---|---|---|
| FreeDOS payload copy | ~30s | ~5s |
| **Total build time** | ~1 min | ~15-25s |

## v0.6.14 slow-build warning removed

Since FreeDOS builds are no longer slow, the v0.6.14
GUI/TUI/CLI "FreeDOS stages ~1388 files" warning is removed.
The warning infrastructure is preserved for future slow-build modes.

## Tests

6 new cases in `tests/test_boot_assets.py` covering the filter
behavior. `tests/test_formlogic.py` updated to assert no boot mode
currently earns a slow-build warning.

## Upgrade

```bash
cd releases/v0.6.15
chmod +x install.sh
./install.sh
```

Or in-place:

```bash
python -m pip install --user --upgrade releases/v0.6.15/dosforge-0.6.15-py3-none-any.whl
```

## See also

- `releases/windows-v0.6.15-release-notes.md` — full context + the
  user-flagged authenticity issue this resolves.
