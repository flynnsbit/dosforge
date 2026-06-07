# dosforge linux-v0.6.18 — Compaq DOS 2.11 restricted to IMG floppy

Parity bump for the Compaq DOS 2.11 IMG-only restriction shipped in
windows-v0.6.18.  The v0.6.17 VHD path produced a structurally
correct disk that nevertheless hangs at a blinking cursor on every
modern emulator (86Box, DOSBox-X, PCem) because Compaq DOS 2.11's
1984 boot code depends on Compaq-specific BIOS extensions no
modern emulator emulates -- even the Compaq Portable II machine
in 86Box.

See the windows-v0.6.18 release notes for the full diagnosis,
the byte-by-byte comparison vs. an authentic Compaq FDISK +
FORMAT C: /S install, and the migration path
(``--media-type img --floppy-type 360k --img-system-format``).

## Linux-specific notes

- COMPAQ2 IMG output uses the same py7zr extraction path as
  Windows -- the disk01.img verbatim-copy short-circuit lives
  in shared `src/dosforge/disk.py:_create_and_prepare_floppy_img`
  so behavior matches across platforms.
- No new dependencies.

## Tests

170/170 focused tests pass:
`test_disk_windows_vhd.py`, `test_formlogic.py`,
`test_asset_skeleton.py`, `test_strict_authenticity.py`,
`test_cli.py`, `test_disk_validation.py`.
