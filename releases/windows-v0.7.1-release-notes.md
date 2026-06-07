# dosforge windows-v0.7.1 — Documentation refresh

Docs-only bump from v0.7.0.  No code changes, no behavior changes.

The v0.7.0 release tarball shipped with a stale README that still
documented the removed v0.6.x `--machine-target` / `--martypc-*`
surface.  v0.7.1 ships a fresh tarball with the rewritten README
matching the actual v0.7.0+ CLI.

## What's new

### README.md fully rewritten (commits 33b1998, 94ae948)

- **Removed** all references to v0.7.0-deleted flags
  (`--machine-target`, `--martypc-xebec-drive-type`,
  `--martypc-at-drive-type`, `dosforge list-martypc-formats`).
- **Removed** the long "Machine targets" section (~130 lines of
  MartyPC-specific drive-type tables).
- **Added** a new "Disk controllers" section explaining
  `--disk-controller {ide,mfm}`, auto-detect rules,
  `--bios-drive-type`, `--custom-chs`, with a curated
  common-geometry table (Phoenix Type 1-9 + ATA NORMAL cap).
- **Updated** "Supported boot modes" table to all **14 wired modes**
  (was missing `compaq2` + `pcdos2000` in the old README), with
  columns: FAT support / compatible controllers / min media.
- **Added** "Queued" boot modes section (pcdos3, msdos6, compaq3,
  drdos6, drdos7 — user has staged .7z media) and "Intentionally
  not implemented" (w95 retail; use msdos71 for FAT32 + DOS).
- **MSDOS71 label** updated to "MS-DOS 7.10 / Win95 OSR2
  (4.00.1111)" — making the provenance explicit (the kernel was
  never sold standalone).
- **Windows install Option A** added (release-bundle workflow —
  previously only build-from-source was documented).
- **Intro paragraph** updated to mention the Windows 11-styled
  tkinter GUI with wizard-like flow alongside the CLI.
- Bumped install command examples from v0.5.2 → v0.7.x.

## Code changes

None.  Version bump only (pyproject.toml + `__init__.py`).

## Compatibility

100% compatible with v0.7.0.  Same CLI, same VHD/IMG output,
same tests.
