# dosforge for Windows v0.9.6 — smoke matrix triage + FreeDOS IMG fix

Mirror of the Linux v0.9.6 release notes.  All shared backend
fixes (FreeDOS IMG payload clamp, DR-DOS / PCDOS2000 FAT32 reject,
e2e matrix trim) apply identically on Windows.

The smoke matrix script lives at `scripts/build-smoke-matrix.py`
in the repo but is Linux-only (relies on `sudo -n` for VHD
qemu-nbd attach); Windows users run smoke verification through
the GUI flow instead.

See `releases/linux-v0.9.6-release-notes.md` for the full
changelog.

## Verified Windows pipelines (unchanged)

- All msdos71/pcdos71 FAT32 and FAT16 install paths
- FreeDOS FAT16 + FAT32 (v0.9.4 CHS boot32 sector)
- PC-DOS 7.x + PC-DOS 2000 + Compaq DOS 3.31 + MS-DOS 5.0/6.22

Windows installer continues to ship the bundled `dosassets/`
tree under `<install>/dosassets/` (not `_internal/`).
