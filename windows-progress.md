# dosforge Windows port — progress + pick-up notes

This file documents the Windows-port work in progress as of the
v0.2.1 tag plus four "Phase 0–3 scaffolding" commits on `main`. It
is the canonical reference for resuming the port on a Windows
machine.

---

## Shipped phases

| Phase | Commit  | Contents                                                                                                                                                                                                  |
|-------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| P0    | `488138f` | `src/dosforge/_platform/` abstraction: `LinuxBackend` + `WindowsBackend`, capability flags (sudo / NBD / mount / file-manager), state-dir helpers. Linux v0.2.1 behavior preserved 1:1.                  |
| P1    | `27b0df8` | `src/dosforge/_core/` pure-Python building blocks: `vhd_footer.py`, `mbr.py`, `fat12_floppy.py` — single-partition MBR + FAT12 floppy writer replace `parted` + `mkfs.fat` on Windows. 16 new tests.       |
| P2    | `02bb19b` | `vendor/windows/` layout, JSON manifest with `REPLACE_WITH_*` placeholders, cross-platform `scripts/fetch-windows-vendor.py` (zip / tar / zstd / Inno Setup), GPL `NOTICES.txt`, `.gitignore` for bin/licenses. |
| P3 (scaffolding) | `91ab7fb` | `WindowsBackend.tool_path()` resolves bundled binaries; `CommandRunner` gets `tool_resolver` + `sudo_required`; `runner_for_backend()` factory; `DiskManager` accepts a `backend`; `_format_floppy_img()` dispatches → pure-Python on Windows. 16 new tests. |

**Test state:** 305/305 pass on Linux; 9 native-only tests skipped as before. **Zero Linux regression.**

---

## What works on Windows today

(After running `scripts/fetch-windows-vendor.py` once.)

- **FAT12 floppy IMG creation** in all 5 standard sizes (360K, 720K,
  1.2M, 1.44M, 2.88M) via the pure-Python `_core.fat12_floppy` path.
  No admin needed.
- **State + cache dirs** under `%LOCALAPPDATA%\dosforge`.
- **Tool resolution** wired to `vendor/windows/bin/` (relative to the
  repo root) or the `$DOSFORGE_VENDOR_DIR` env var (used by the
  PyInstaller bundle later).
- **`CommandRunner.run(..., sudo=True)`** becomes a no-op on Windows
  so existing call sites compile and run without modification.

---

## Pick-up instructions on a Windows box

```powershell
# 1. Get the code
git clone git@github.com:flynnsbit/dosforge.git
cd dosforge

# 2. Install python deps (Python 3.11+)
python -m pip install -e .[dev]
python -m pip install zstandard   # required by the fetch script for .pkg.tar.zst

# 3. Populate vendor/windows/manifest.json
#    Replace every REPLACE_WITH_* value with real version pins,
#    download URLs, and SHA-256 checksums. See vendor/windows/README.md
#    for upstream sources:
#      - qemu:   https://qemu.weilnetz.de/w64/
#      - mtools: https://packages.msys2.org/package/mingw-w64-x86_64-mtools

# 4. (For Inno Setup archives only) install innoextract
scoop install innoextract     # OR: choco install innoextract

# 5. Fetch + extract bundled binaries
python scripts/fetch-windows-vendor.py
# → populates vendor/windows/bin/ (~250 MB)

# 6. Smoke-test the scaffolding
pytest tests/test_platform_windows.py tests/test_core_modules.py -v
python -c "from dosforge._platform import get_backend; b = get_backend(); print(b.name, b.tool_path('qemu-img'))"

# 7. Build a FAT12 floppy via the pure-Python path
dosforge create --media-type img --floppy-type 1440k --path test.img
# Should produce a valid 1.44 MB FAT12 floppy with no QEMU/mtools required.
```

---

## Remaining work for full v0.3.0

Tracked in `plan.md` (session workspace) and the SQL `todos` table.

### P3 cont'd — Windows VHD pipeline (BIGGEST GAP)

Refactor `DiskManager._create_and_prepare_vhd()` to branch on
`self.backend.supports_nbd`:

1. **Linux path** (unchanged): qemu-img create → qemu-nbd attach →
   parted → mkfs.fat → mount → copy → unmount → qemu-nbd detach.
2. **Windows path** (new):
   - `qemu-img create -f vpc -o subformat=fixed,force_size=on …`
     (already correct; just needs to use `self.backend.tool_path('qemu-img')`).
   - `_core.vhd_footer.write_footer_chs(path, ...)` for MartyPC /
     BIOS Type presets (already pure-Python).
   - `_core.mbr.write_single_partition_mbr(path, …)` writes the
     MBR directly to byte 0 of the VHD.
   - `mformat -i <vhd_path>@@<partition_offset_bytes> ::` — mtools
     understands the `@@offset` syntax for raw images, no NBD needed.
   - For partition_offset_bytes: legacy DOS = 63 × 512 = 32256;
     modern = 2048 × 512 = 1 MiB. Use the existing
     `_partition_offset_bytes_for(request)` helper.

### P3 cont'd — `BootInstaller` Windows port

`src/dosforge/boot.py` is ~3000 lines with heavy `mount`/`umount`/`sudo`
coupling. The refactor pattern:

- Every `mcopy -i <partition_device>` / `mattrib -i <partition_device>`
  call already takes a partition reference — on Linux this is the NBD
  partition device (`/dev/nbd0p1`); on Windows it can be the
  `@@offset` form of the same image.
- Replace each `mount …; cp …; umount …` block with `mcopy -i
  <vhd>@@<offset> -o <src> ::DEST` (mtools handles the staging
  directly).
- The QEMU-driven SYS install path (`legacy_dos_install.py`) already
  uses qemu-system-i386 — should mostly work on Windows once the
  resolver points it at the bundled exe.

### P4 — In-app mtools file browser (cross-platform)

New Textual `BrowseScreen` that replaces the external mount + GUI
file-manager flow:

- Lists FAT contents via `mdir`.
- Copy in / copy out via `mcopy`.
- Rename / delete / set attributes via `mattrib` + `mdel`.
- Works on both Linux and Windows — no kernel mount needed.

### P5 — TUI polish on Windows

- Verify Textual rendering in Windows Terminal 11.
- Skip the zenity sudo path (Windows backend skips sudo entirely
  already — just guard the import / call sites).
- Path handling: ensure every `Path` use is correct for `\` separators
  and Windows reserved names. UNC + long-path sanity check.
- Optional `tkfiledialog` native fallback for "Open" / "Save" pickers.

### P6 — Packaging: portable zip + Inno Setup installer

- `windows/dosforge.spec` — PyInstaller onedir spec including
  Textual + deps, `vendor/windows/bin/`, `dosassets/`, `assets/icons/`.
- `windows/build-portable.ps1` produces `dosforge-VER-windows-x64-portable.zip`.
- `windows/dosforge.iss` (Inno Setup) produces
  `dosforge-VER-windows-x64-setup.exe` with:
  - Start Menu shortcut "DosForge".
  - Optional Desktop shortcut.
  - File associations: right-click `.vhd` / `.img` → "Inspect with DosForge".
  - Uninstaller.
- `windows/README.md` with install + Windows Defender SmartScreen
  ("More info → Run anyway") guidance for unsigned exes.

### P7 — GitHub Actions Windows CI

- `.github/workflows/windows-build.yml` on `windows-latest`:
  - Cache the fetched vendor archives.
  - Run `pytest -q -m "not native_linux and not native_boot and not native_86box"`.
  - Build portable zip + installer; upload as artifacts.
- New `native_windows` pytest marker gated by
  `DOSFORGE_RUN_NATIVE_WINDOWS_TESTS=1` for integration tests.

### P8 — Documentation

- README "Windows install" section.
- `releases/v0.3.0/README.md` covers both platforms.
- CHANGELOG entry for 0.3.0.

### P9 — Release v0.3.0

- Bump version to 0.3.0 in `pyproject.toml` + `src/dosforge/__init__.py`.
- Build Linux bundle (existing `scripts/build-release.sh`).
- Build Windows portable zip + installer (new pipeline).
- GitHub Release with all artifacts:
  - `dosforge-0.3.0-bundle.tar.gz`, `.zip` (Linux).
  - `dosforge-0.3.0-windows-x64-portable.zip`.
  - `dosforge-0.3.0-windows-x64-setup.exe`.
  - Wheel + sdist.
  - `SHA256SUMS`.

---

## Architecture invariants to preserve

Hard-won lessons from v0.2.x — do not regress these on Windows.

- **86Box BIOS auto-detect mode** is the canonical target. VHDs must
  have a footer CHS that matches one of: (a) MartyPC machine-specific
  presets, (b) Phoenix/AMI BIOS Type 1–45, or (c) canonical 16h/63s
  ATA geometry. The pure-Python `_core.vhd_footer` module handles all
  three paths.
- **mkfs.fat BPB is incompatible with DOS 3.x SYS** for `compaq331` /
  `msdos33` / `msdos331`. These boot modes use `mformat` + a QEMU-
  driven `SYS C:` install. On Windows this path stays the same — just
  resolves through bundled binaries.
- **FAT16 VHD BPB must be BIOS-canonical (16h/63s)**, not VHD-footer
  CHS, for AUTO IDE boot in 86Box. The `_normalize_vhd_size_for_chs` /
  footer-patch logic handles this; preserve when refactoring.
- **MS-DOS 3.30 needs MBR partition type 0x04**, not 0x06. Encoded in
  the existing partition-table writer; respect this when the Windows
  VHD pipeline lands.
- **DOS system files** (`IO.SYS`, `MSDOS.SYS`, `IBMBIO.COM`,
  `IBMDOS.COM`, `KERNEL.SYS`) get `+r +s +h -a`. `COMMAND.COM` does
  not get +s/+h. Preserve in any boot-install refactor.
- **DOS startup normalization** strips PATH from CONFIG.SYS and forces
  AUTOEXEC.BAT to only `@ECHO OFF` + `PATH=C:\DOS` (boot-mode-specific
  to FreeDOS; do not apply to MS-DOS/IBM DOS).

---

## Pull request strategy (suggestion)

When porting the remaining phases on Windows, land them as separate
PRs rather than a single big v0.3.0 PR. Suggested order:

1. **P3 cont'd VHD pipeline** — biggest gap, unblocks real Windows
   usage. Land first.
2. **P3 cont'd BootInstaller refactor** — depends on (1). Big refactor;
   split into "use mtools @@offset on Linux too" (regression-safe) then
   "remove kernel-mount paths on Windows".
3. **P4 in-app browser** — independent, can land in parallel.
4. **P5 + P6** — package after the runtime works.
5. **P7 CI** — only useful once P6 is reliable.
6. **P8 + P9** — release.

---

## Files added in this session

```
src/dosforge/_platform/
  __init__.py          # get_backend() factory
  base.py              # PlatformBackend ABC + capability flags
  linux.py             # LinuxBackend (v0.2.1 semantics)
  windows.py           # WindowsBackend (tool_path, no sudo/NBD/mount)

src/dosforge/_core/
  __init__.py
  vhd_footer.py        # decode_footer, write_footer_chs, normalize_to_ata
  mbr.py               # PartitionEntry, write_single_partition_mbr,
                       # read_partition_entry, _lba_to_chs
  fat12_floppy.py      # write_fat12_floppy, format_existing,
                       # validate_floppy_bpb

vendor/windows/
  manifest.json        # version pins + URLs + SHA-256 (placeholders)
  NOTICES.txt          # GPL attribution
  README.md            # provenance + populate instructions
  # bin/ + licenses/ are .gitignore'd; auto-populated by the fetch script

scripts/
  fetch-windows-vendor.py   # cross-platform vendor fetcher + extractor

tests/
  test_core_modules.py      # 16 tests covering vhd_footer/mbr/fat12_floppy
  test_platform_windows.py  # 16 tests covering WindowsBackend + runner wiring
```

## Files modified

```
src/dosforge/paths.py         # delegates state/cache/mount paths to backend
src/dosforge/dependencies.py  # backend-driven required-commands list
src/dosforge/commands.py      # CommandRunner gets tool_resolver + sudo_required
src/dosforge/disk.py          # DiskManager.backend, _format_floppy_img dispatch
.gitignore                    # excludes vendor/windows/bin, licenses, .vendor-cache
```

---

## Quick links

- **Repo:** <https://github.com/flynnsbit/dosforge>
- **Latest tagged release:** [v0.2.1](https://github.com/flynnsbit/dosforge/releases/tag/v0.2.1)
- **Plan in session workspace:** `~/.copilot/session-state/<session-id>/plan.md`
- **Todos:** SQL `todos` table (10 entries, 3 done, 1 in progress).
