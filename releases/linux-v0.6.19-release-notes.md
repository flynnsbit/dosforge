# dosforge linux-v0.6.19 — Compaq DOS 2.11 bootable VHD via MartyPC Xebec Type 1

Parity bump for the COMPAQ2 + MartyPC Xebec Type 1 VHD path shipped
in windows-v0.6.19.  Reuses the existing MartyPC Xebec Type 1 code
path (already used for msdos33 and ibm8088+dos33) to build an
authentic 1984-style 10 MiB MFM hard-disk VHD with FAT12 + Compaq
boot code.

See the windows-v0.6.19 release notes for the full build command,
implementation notes (which existing helpers already handled most
of the layout), and the validation refinements.

## Linux-specific notes

- All COMPAQ2 paths use shared modules (`src/dosforge/disk.py`,
  `formlogic.py`, `legacy_dos_install.py`, `_legacy_dos_archive.py`).
  Linux behavior matches Windows.
- Linux build of the new path:
  ```
  dosforge create --media-type vhd --boot-mode compaq2 \\
      --format fat12 \\
      --machine-target martypc-xebec \\
      --martypc-xebec-drive-type type1 \\
      --path ~/compaq2-xebec.vhd
  ```

## Tests

170/170 focused tests pass:
`test_disk_windows_vhd.py`, `test_formlogic.py`,
`test_asset_skeleton.py`, `test_strict_authenticity.py`,
`test_cli.py`, `test_disk_validation.py`.
