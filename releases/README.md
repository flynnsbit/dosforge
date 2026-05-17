# dosforge releases

Each subdirectory under this folder (`v<MAJOR>.<MINOR>.<PATCH>/`) is a
self-contained, source-free installable bundle of the named release.

## Versioning scheme

`dosforge` follows [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR** (`X.0.0`): breaking changes to the CLI surface,
  `BootMode` enums, or asset layout that require a user-side migration.
- **MINOR** (`0.Y.0`): new boot modes, machine targets, install
  profiles, or large feature additions that are backwards compatible.
- **PATCH** (`0.0.Z`): bug fixes and small enhancements that don't
  change documented behavior.

Pre-1.0 (the current line) is treated as "everything may still change,
but each release is a working snapshot". Once the first stable v1.0.0
ships, the contract above becomes binding.

## How to make a release

1. Bump `version` in `pyproject.toml`.
2. Add an entry to `CHANGELOG.md`.
3. Run `./scripts/build-release.sh` from the repo root — this builds
   the wheel + sdist and assembles the new bundle under
   `releases/v<version>/`.
4. Commit the bumped pyproject, changelog entry, and new
   `releases/v<version>/` folder in one commit.
5. Tag the commit as `v<version>` and push.

## Releases

| Version | Date       | Notes                                                                                                       |
|---------|------------|-------------------------------------------------------------------------------------------------------------|
| 0.2.1   | 2026-05-17 | Fixes leftover "VHD Maker" / "VHDMaker" strings in the TUI header and zenity sudo prompt (now "DosForge").  |
| 0.2.0   | 2026-05-17 | Adds Phoenix + AMI classic AT BIOS HDD type presets (Types 1–45) with new `--bios-drive-type` flag and TUI selector. |
| 0.1.2   | 2026-05-17 | Accepts `Disk1.img` (Microsoft DOS 3.31 archive) for `msdos331`; system-file verification accepts either flavor. |
| 0.1.1   | 2026-05-17 | Fixes `msdos331` boot hang (routes through QEMU SYS install); `msdos331` capped at 32 MiB, `compaq331` at 504 MiB. |
| 0.1.0   | 2026-05-16 | First public release. VHD + IMG creation, FreeDOS / MS-DOS 3.30 – 7.1 / Compaq / PC-DOS, MartyPC presets.   |
