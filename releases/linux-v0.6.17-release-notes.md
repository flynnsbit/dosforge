# dosforge linux-v0.6.17 — Compaq DOS 2.11 as a first-class boot mode

Parity bump for the Compaq DOS 2.11 work shipped in windows-v0.6.17.
The new boot mode lives in shared `src/dosforge/` modules so Linux
gets the same support: drop the WinWorldPC .7z archive into
`dosassets/compaq2/`, build with `--boot-mode compaq2 --format fat12`,
get a bootable 16 MiB Compaq DOS 2.11 VHD with authentic 1984-05-30
files.

See the windows-v0.6.17 release notes for the full feature breakdown
(DOS 2.x quirks honored, reusable `_legacy_dos_archive` extractor,
new tests, asset readme updates).

## Linux-specific notes

- Uses the same `py7zr` extraction path — no `7z` / `7za` binary
  required.
- The standard Linux VHD pipeline (qemu-nbd + parted + mkfs.fat +
  QEMU SYS install) handles compaq2 via the existing msdos33-layout
  branch with a FAT12 partition-type byte (0x01).
- No new system dependencies beyond what dosforge already requires.

## Tests

76/76 focused tests pass:
`test_disk_windows_vhd.py`, `test_formlogic.py`,
`test_asset_skeleton.py`, `test_strict_authenticity.py`,
`test_cli.py`.
