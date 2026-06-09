# dosforge v0.9.6 — smoke matrix triage + FreeDOS IMG fix

Cuts the 51-case Tier 1 smoke matrix down to its supported subset,
adds pre-flight asset detection so missing install media surfaces as
**SKIP** (not FAIL), and fixes a real bug where FreeDOS floppy IMG
builds crashed with ENOSPC mid-payload-copy.

## What changed

### Bug fix: FreeDOS IMG floppy over-staging

`dosforge create --media-type img --boot-mode freedos --freedos-source
auto` used to crash with `OSError: [Errno 28] No space left on device`
while copying the FreeDOS `BIN/` tree (~66 utilities, easily >5 MiB)
onto a 1.44 MiB FAT12 floppy.

`_resolve_freedos` now strips the `fdos_payload_dir` from the
resolved `BootAssets` when the target is an IMG floppy, so only
the system files (`KERNEL.SYS`, `COMMAND.COM`, etc.) and minimal
startup files land.  The full FreeDOS shell tools remain available
on hard-disk (VHD) targets where they fit.

### Matrix correctness: FAT12-only modes excluded from VHD generation

`dosforge.e2e_matrix.valid_e2e_cases()` previously emitted FAT16
and FAT32 VHD cases for `compaq2`, `compaq3`, and `pcdos3` even
though those modes only support FAT12.  The CLI rightly rejected
them, but the matrix shouldn't have surfaced them in the first
place.  New `_FAT12_ONLY_NO_VHD` set excludes them from VHD
generation entirely.

### Matrix correctness: DR-DOS / PCDOS2000 are FAT16-only

`DRDOS6`, `DRDOS7`, and `PCDOS2000` are now in `_LEGACY_FAT16_ONLY`
in `e2e_matrix.py` AND in `_validate_create_request`'s
`legacy_fat16_modes` set.  Previously, FAT32 cases for these modes
would run the QEMU install loop for the full 5-minute timeout
before failing — now they reject up front with a clear message.

### Tooling: `scripts/build-smoke-matrix.py` overhaul

- Drops the `--disk-controller mfm` override block that was
  silently snapping IBM8088 / Compaq* VHDs to 10 MiB (XT Type 1),
  failing the FAT16 ≥16 MiB minimum.  IBM8088 + FAT16 now passes
  `--ibm-dos-version dos50 --bios-drive-type ami:45` for a 68 MiB
  AT-class build that exercises the dos50 install path.
- New `_FORCE_BIOS_DRIVE_TYPE` table for IBM8088 / MSDOS33 / PCDOS
  to override the MFM auto-detect.
- Per-mode `_DEFAULT_SIZE` fixes: MSDOS331 capped at 32 MiB
  (was 128 MiB), PCDOS71+FAT32 floored at 1 GiB (FORMAT32 minimum),
  DR-DOS family sized to its FAT16 cap.
- COMPAQ3 default floppy now `360k` (was `1440k` — Compaq 3.00 didn't
  ship 3.5" disks).
- New `_IMG_UNSUPPORTED_MODES` set and `_REQUIRED_ASSET_GLOBS` map.
  Pre-flight skip detection emits `SKIP-asset` for cases where the
  user must drop install media into `dosassets/<mode>/`, and
  `SKIP-not-implemented` for IMG combos with no resolver code path.
  Pre-skipped cases land in a dedicated MANIFEST.md section so users
  see at a glance what action to take.
- 4DOS cases auto-get `--host-boot-mode msdos71` (4DOS is a shell
  overlay, not a standalone DOS).
- Manifest + summary print pass/skip/fail counts separately;
  exit code = 0 unless an unexplained build fails.

### Expected outcome on the Tier 1 smoke run

Previous (v0.9.5): **20/51 PASS, 31 FAIL** (most "failures" were
script-side defaults or matrix over-generation).

Expected (v0.9.6): **~30 PASS, ~12 SKIP-asset / SKIP-not-implemented,
0–2 actual FAIL** — and any FAIL is a real regression worth
investigating, not a misconfigured size.

## Verification

Re-run `scripts/build-smoke-matrix.py` after upgrading.  All
`SKIP-asset` rows tell you exactly which dosassets directory to
populate (typically a `.7z` WinWorldPC archive).  PASS rows go
into 86Box per `MANIFEST.md`.

## Files changed

- `src/dosforge/boot.py` — FreeDOS IMG payload clamp in `_resolve_freedos`
- `src/dosforge/disk.py` — DR-DOS / PCDOS2000 FAT32 upfront reject
- `src/dosforge/e2e_matrix.py` — FAT12-only and DR-DOS exclusions
- `scripts/build-smoke-matrix.py` — pre-flight skip detection, size
  defaults, BIOS-drive-type overrides, manifest sections
- `tests/test_e2e_matrix.py` — accept new `_FAT12_ONLY_NO_VHD` set
- `pyproject.toml` + `src/dosforge/__init__.py` — version bump
