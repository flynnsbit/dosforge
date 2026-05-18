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
| P3 (smoke fixes) | (uncommitted) | NSIS extraction in `fetch-windows-vendor.py` (modern QEMU upstream is NSIS-format, not Inno Setup); `DiskManager` now uses `runner_for_backend(self.backend)` so Windows commands resolve to bundled binaries; `_ensure_sudo_ready` is a no-op when `backend.requires_sudo_for_disk_ops` is False; `find_missing` consults the backend so bundled tools aren't reported as missing; `_make_fixed_vhd` test fixture is cross-platform. |
| P3 (cont'd: VHD)  | (uncommitted) | `DiskManager._create_and_prepare_vhd_no_kernel` — Windows VHD pipeline using `_core.mbr` + `_core.vhd_footer` + mtools `mformat -i <vhd>@@<offset>` with explicit `-T` and `-H`. Active for non-bootable VHDs (`boot_mode=NONE`); other modes raise `ValidationError`. `mmd` added to bundled mtools. 6 new tests. |
| P3 (cont'd: BootInstaller / FreeDOS) | (uncommitted) | `PartitionRef` dataclass + unified `_patch_at_offset` primitive replace every `dd` call (covers MBR boot code, VBR JMP/code/signature, legacy FAT12/16 header bytes, FAT16 BPB geometry patch, floppy boot sector). MBR write now bytes 0..439 only (preserves partition table). `_copy_payload_via_mtools` mirrors mount-path semantics (mmd + mcopy, DOS `*_` compressed-file expansion to temp files, destination collision tracking). `_copy_system_files` dispatches mount-vs-mtools on `backend.supports_kernel_mount`. `sync` gated on Linux. `BootInstaller` takes `backend`; `DiskManager` propagates. **Result:** bootable FreeDOS FAT16 VHDs on Windows verified end-to-end (booted in qemu-system-i386, VGA buffer shows `C:\>` prompt). |
| Prereqs script | (uncommitted) | `scripts/install-windows-prereqs.ps1` — idempotent winget install of Python 3.12, 7-Zip 23+ (NSIS extraction), innoextract (legacy fallback). `vendor/windows/README.md` updated with the install script + NSIS notes + end-to-end bootstrap sequence. Manifest also extracts QEMU's i386 BIOS firmware (`bios-256k.bin`, `vgabios.bin`, `kvmvapic.bin`, etc.) into `vendor/windows/bin/`. |

**Test state:** 305/305 pass on Linux; 9 native-only tests skipped as before. **Zero Linux regression.**

---

## What works on Windows today

After running `scripts/install-windows-prereqs.ps1` (one-time) and
`scripts/fetch-windows-vendor.py` (once `manifest.json` is populated):

- **FAT12 floppy IMG creation** in all 5 standard sizes (360K, 720K,
  1.2M, 1.44M, 2.88M) via the pure-Python `_core.fat12_floppy` path.
  No admin needed.
- **Non-bootable VHD creation** in FAT16 and FAT32 via the
  `_create_and_prepare_vhd_no_kernel` path: `_core.mbr` writes a
  single-partition MBR (FAT16=0x06, FAT32=0x0C, partition starts at
  LBA 2048 for 1 MiB alignment, active flag set for parity with
  parted) and bundled `mformat.exe` formats the partition using the
  `<vhd>@@<offset>` syntax with explicit `-T total_sectors` and
  `-H hidden_sectors` so the VHD footer is excluded from the FAT
  data area.
- **Bootable FreeDOS FAT16 VHD creation** via the BootInstaller
  refactor: pure-Python `_patch_at_offset` writes the MBR boot code
  (bytes 0..439 only, preserving the partition table) and the FAT16
  VBR (JMP + code + signature) directly into the VHD without any
  `dd` / `mount` / kernel-mount support. `_copy_payload_via_mtools`
  stages the FreeDOS `FDOS/BIN/` payload via `mmd` + `mcopy` with
  the same DOS `*_` compressed-file expansion behavior as the Linux
  mount path. Verified end-to-end on this Windows host by booting
  the resulting VHD in the bundled `qemu-system-i386.exe` and
  inspecting the VGA text buffer via QMP — produces a real
  `C:\>` FreeDOS prompt.
- **Custom payload directory copy** into a non-bootable VHD via
  bundled `mmd.exe` + `mcopy.exe` (no kernel mount required).
- **State + cache dirs** under `%LOCALAPPDATA%\dosforge`.
- **Tool resolution** wired to `vendor/windows/bin/` (relative to the
  repo root) or the `$DOSFORGE_VENDOR_DIR` env var (used by the
  PyInstaller bundle later).
- **`CommandRunner.run(..., sudo=True)`** becomes a no-op on Windows
  so existing call sites compile and run without modification.
- **Dependency checks** consult the backend before falling back to
  PATH, so bundled binaries aren't reported as "missing required tools".

Other boot modes (MS-DOS 3.x / 5.x / 6.22 / 7.1, IBM DOS, PC-DOS,
Compaq DOS, FreeDOS-FAT32) still raise `ValidationError` on Windows
VHD targets — those paths depend on the QEMU-driven SYS/FORMAT
install flow (compaq331, msdos33, msdos331, ibm8088+dos33) or on a
FreeDOS FAT32 MBR template that the asset resolver doesn't yet
produce, and are tracked as the next port phase.

---

## Pick-up instructions on a Windows box

```powershell
# 1. Get the code
git clone git@github.com:flynnsbit/dosforge.git
cd dosforge

# 2. Install host prerequisites (idempotent: Python 3.12, 7-Zip 23+, innoextract)
.\scripts\install-windows-prereqs.ps1
#    Open a NEW shell so the freshly-installed PATH entries are visible.

# 3. Project venv + Python deps
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pip install zstandard

# 4. Populate vendor/windows/manifest.json
#    Replace every REPLACE_WITH_* value with real version pins,
#    download URLs, and SHA-256 checksums. See vendor/windows/README.md
#    for upstream sources:
#      - qemu:   https://qemu.weilnetz.de/w64/   (NSIS format from ~May 2026)
#      - mtools: https://packages.msys2.org/package/mingw-w64-x86_64-mtools

# 5. Fetch + extract bundled binaries
python scripts/fetch-windows-vendor.py
# → populates vendor/windows/bin/ (~170 MB)

# 6. Smoke-test the scaffolding (32 tests)
pytest tests/test_platform_windows.py tests/test_core_modules.py -v
python -c "from dosforge._platform import get_backend; b = get_backend(); print(b.name, b.tool_path('qemu-img'))"

# 7. Build a FAT12 floppy via the pure-Python path
dosforge create --media-type img --floppy-type 1440k --path test.img
# Should produce a valid 1.44 MB FAT12 floppy with no QEMU/mtools required.

# 8. Build a non-bootable FAT16 VHD via the no-kernel pipeline
dosforge create --media-type vhd --format fat16 --size 32M --path test32.vhd
vendor\windows\bin\mdir.exe -i "test32.vhd@@1048576" ::
# Should report an empty FAT16 partition with ~32 MiB free.
```

---

## Remaining work for full v0.3.0

Tracked in `plan.md` (session workspace) and the SQL `todos` table.

### P3 cont'd — Windows VHD pipeline ✓ LANDED (non-bootable VHDs)

Implemented `DiskManager._create_and_prepare_vhd_no_kernel` and
dispatched on `self.backend.supports_nbd` in `create_and_prepare`.
The Linux NBD path is untouched. The Windows path:

- Uses the existing cross-platform `_create_fixed_vhd` (qemu-img
  create + footer-CHS normalize) to allocate the VHD.
- Reads the resulting footer to learn the canonical CHS triplet.
- Writes a single-partition MBR via `_core.mbr.write_single_partition_mbr`
  at LBA 2048 with the active flag, type byte 0x06 (FAT16) or 0x0C
  (FAT32) — byte-identical to what Linux parted produces for
  `boot_mode=NONE`.
- Formats the partition with bundled `mformat -i <vhd>@@<offset>
  -T <partition_sectors> -H 2048 [-v label] [-F]`. The explicit
  `-T` is critical: without it mtools auto-detects from EOF and would
  silently include the 512-byte VHD footer in the data area.
- Copies any custom payload via the existing `_copy_custom_payload_to_vhd_via_mtools`
  helper (uses bundled `mmd` + `mcopy`).

Bootable VHDs (`boot_mode != NONE`) raise `ValidationError` directing
the user to build them on the Linux side. The boot-installer refactor
remains the next phase.

### P3 cont'd — `BootInstaller` Windows port ✓ LANDED (FreeDOS FAT16)

Refactored every `dd` call into a unified `_patch_at_offset` primitive
that takes either a raw image path + absolute byte offset (Windows
path, Python file I/O) or a Linux block device + sudo (legacy `dd`
path). The MBR write was tightened to bytes 0..439 only so the
partition table laid down by `_core.mbr.write_single_partition_mbr`
survives the boot-code copy. Added `PartitionRef` to carry both
address forms cleanly. `_copy_payload_via_mtools` mirrors the mount-
path semantics (`mmd` + `mcopy`, compressed `*_` file expansion,
collision skip) for FreeDOS's `FDOS/BIN/` tree. `BootInstaller`
takes a `backend` and `DiskManager` propagates it. `sync` is gated
on Linux. Result: a FreeDOS FAT16 VHD built end-to-end on Windows
boots cleanly in QEMU to a `C:\>` prompt.

**Still gated on Linux NBD path:** other boot modes (MS-DOS family,
PC-DOS, IBM DOS, Compaq DOS) and FreeDOS-FAT32. Their gaps are
documented below.

### P3 cont'd — Additional boot modes ✓ PARTIALLY LANDED

- **MS-DOS 7.1 (msdos71)** is now accepted by the Windows VHD pipeline.
  Code path is fully wired (resolver runs, `make_partition_bootable`
  is called with a `PartitionRef.from_image(...)`). End-to-end boot
  cannot be smoke-tested with the install media currently present
  under `dosassets/msdos71/` (the disk01.img in this repo is missing
  `DOS71_1S.PAK`, so the resolver bails before extracting system
  files). The Windows wiring is correct — provide standard MS-DOS 7.1
  install diskettes and it should work the same way as FreeDOS does.

- **Bootable floppy IMG** path is unblocked on Windows: the new
  `_patch_at_offset` writes the floppy boot sector via Python file
  I/O, `_format_floppy_img` already dispatched to `_core.fat12_floppy`
  on Windows, `_copy_system_files` dispatches to `_copy_payload_via_mtools`,
  and `mattrib` correctly hides `KERNEL.SYS`. Discovered a **pre-existing
  dosforge bug** in `_resolve_boot_template` (`boot.py:2536-2541`):
  the resolver only handles `DiskFormat.FAT16` and falls through to
  `BOOTSECT_FAT32.BIN` for everything else, so FAT12 floppies have
  been getting the wrong boot sector regardless of platform. Not
  Windows-specific. Deferred fix.

### P3 cont'd — Remaining boot modes (NEXT, smaller now)

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
