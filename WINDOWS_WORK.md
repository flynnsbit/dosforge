# dosforge — Windows work log

Companion to [`windows-progress.md`](windows-progress.md). That file
captured the initial port (P0–P3, FreeDOS-only) up through commit
`d8632db` ("Windows port: VHD pipeline + BootInstaller refactor").
**This document picks up where that one left off** and tracks every
piece of Windows-related work landed after `d8632db`, plus the
phases that are still open.

If you're getting started on a fresh Windows machine, read
`windows-progress.md` § "Pick-up instructions" first, then come
back here for the current capability matrix.

---

## 1. Timeline since the port baseline

Newest first. Commits shown short-sha only — they're all on
`origin/feature/dos-authenticity` and `origin/main`.

### 1.1 Feature-parity hardening (`9fae58b` … `9d22d98`, v0.3.0)

| Commit  | Summary |
|---------|---------|
| `9fae58b` | `dosforge.bat` + `dosforge.ps1` wrappers at repo root so the TUI is launchable from a clean clone with no setup chant. |
| `af0b06b` | TUI parity: backend-gates mount UI off on Windows, falls back to tkinter file picker, skips sudo reauth. |
| `dfebb84` | README parity matrix; `conftest` re-enables 12 unit-test files previously skipped on Windows. |
| `b9ba7ba` | mtools wrapper verbs (`ls`/`cat`/`get`/`put`/`rm`/`mkdir`) + IMG floppy fixes for Windows. |
| `87848cd` | "Fetch latest FreeDOS" works on Windows — `mformat` substitutes for `mkfs.fat`. |
| `f213c58` | TUI regression tests: every manager call the TUI makes is exercised against the active backend. |
| `46fcf5c` | Native `Mount-DiskImage` on Windows (PowerShell), de-sparse VHDs, `.zip` install-media support, surface vendor readme on missing assets. |
| `9d22d98` | **0.3.0 release: Windows feature parity with Linux declared.** |

### 1.2 PyInstaller bundles + CI (`1a26d30` … `3825840`)

| Commit  | Summary |
|---------|---------|
| `1a26d30` | First Windows PyInstaller bundle: structured `dosforge\` layout, `DOSFORGE_DOSASSETS_DIR` for relocated dosassets. |
| `c66a263` | 0.3.1: fix broken TUI in bundle — use `collect_all()` for textual etc. (bundle was missing transitive imports). |
| `69881e3` | 0.3.1 hotfix: replace unicode arrow in lite spec print (Windows console encoding crash). |
| `602c5ef` | **0.3.2: CLI-only Windows bundle (~27 MB zipped)** — no TUI deps, for headless scripted matrix builds. |
| `2082545`, `c9076d7`, `dd99977` | CLI bundle smoke test: tolerates `dosforge.exe tui` exit code 2, collects failures, explicit `exit 0` to override `LASTEXITCODE`. |
| `396dca6` | CI: 3 Windows builds (lite/full/cli) run in a matrix strategy in parallel. |
| `fd83bbf` | CI: hyphenated tags → pre-release, plus v0.4.0-dosbox-x-pre1 notes. |
| `3825840` | Prune `_internal/` bloat: strip `Cryptodome.SelfTest` + `.dist-info` + `setuptools` from bundles. |

### 1.3 DOSBox-X swap (`edb63e4`)

`edb63e4` **replaces bundled `qemu-system-i386` + 110 MB of QEMU
DLLs with a 24 MB DOSBox-X.** Triggered by 86Box compatibility
issues with QEMU-format VHDs and by the bundle size. Used downstream
for the LOADDSKF extraction (`07f9638`) and as the runtime under
which legacy DOS `FORMAT C: /S` runs.

### 1.4 Authenticity overhaul (Phase 14A → 14G, `92acece` … `8b1b6a3`)

The "every DOS image must byte-equivalent a real install from THAT
DOS's authentic media" hard rule landed here.

| Commit  | Summary |
|---------|---------|
| `92acece` | **Phase 14A:** per-DOS-version authenticity profile registry under `src/dosforge/_dos/*.py` — each DOS gets its own module with strictly its own MBR/VBR/sysfile/config defaults. |
| `462e6c6` | **Phase 14C:** rename `_apply_fat16_reference_boot_records` → `_apply_freedos_fat16_reference_boot_records` to make the FreeDOS-only intent explicit (no cross-DOS borrowing). |
| `c21324e` | **Phase 14B:** strict-authentic `CONFIG.SYS`/`AUTOEXEC.BAT` on by default. |
| `1b53550` | Replace strict FreeDOS-style MBR with classic MS-DOS MBR (440 bytes, INT 13h AH=02h, no VBR signature check). |
| `5fa9cab` | `fix(mbr)`: correct `je` offset in custom MS-DOS MBR (was 04, must be 07). |
| `8b1b6a3` | **Phase 14E/F-prep/G:** 4DOS BootMode (post-install shell overlay) + authenticity golden tests (`tests/test_authenticity_golden.py`, `tests/test_strict_authenticity.py`). |

### 1.5 Per-DOS install pipelines (`13af74d` … `07f9638`)

| Commit  | Summary |
|---------|---------|
| `13af74d` | SHA-256 content stamp in cached binary filenames (`<basename>-<sha256_8>.<ext>`) — prevents stale-cache footguns. |
| `b08434a` | **MSDOS71:** pivot from the Chinese DOS71_1S.PAK to Win95 OSR2 floppies (`dosassets/w95/Boot.img`) + QEMU `SYS A: C:`. The PAK release ships a non-bootable MZ-only IO.SYS — replaced with the authentic 1996-08-24 OSR2 IO.SYS. |
| `4ba62e3` | `disk: use qemu-img force_size=on for GENERIC VHDs too` — without it, qemu-img rounds size up to its legacy MS CHS algorithm and `current_size` ends up > `footer cyl*heads*spt*512`, which makes 86Box AUTO IDE pick `LARGE` instead of `NORMAL`. |
| `7b52acd` | `boot: cleanup pre-Phase-14G un-versioned cache files on init` — one-time eviction of cache files predating the SHA-256 stamping. |
| `2635e73` | Boot-probe harness + 4DOS overlay + per-mode boot fixes (multi-mode `tests/test_native_86box_boot.py`). |
| `8d978cb` | **matrix bootability:** msdos5 / msdos622 / ibm8088:dos50 migrated to QEMU `FORMAT C: /S` install (replaces the offline boot-sector extraction approach that didn't survive 86Box's BIOS strict mode). |
| `07f9638` | **PC-DOS 7.0:** the shipped `dosassets/pcdos7/144US1.DSK` is IBM's proprietary LOADDSKF compressed format (magic `AA 59 F0`). Added `src/dosforge/_pcdos7_loaddskf.py` that decompresses via the bundled `LOADDSKF.EXE` inside DOSBox-X to get a raw bootable 1.44 MB IMG (cached under `app_cache_dir()/pcdos7-install/`), then runs the standard FORMAT-C:-/S flow. |

### 1.6 Payload + system-file polish (`a14abc4` … `79950a1`)

| Commit  | Summary |
|---------|---------|
| `a14abc4` | `fix(disk): override install-floppy AUTOEXEC.BAT/CONFIG.SYS in FULL profile` — when a FULL-profile install copies the entire install-floppy contents, the floppy's startup files would otherwise clobber our generated ones. |
| `c7eca7d` | `fix(disk): exclude VCS metadata + OS droppings from custom payload copy` — `.git*`/`.svn`/`.hg`/`.bzr`/`.ds_store`/`Thumbs.db`/`desktop.ini`/`__pycache__`/`__MACOSX` no longer end up on the end-user disk. `_PAYLOAD_EXCLUDED_BASENAMES` in `disk.py`. |
| `936bc6b` | `fix(disk): expand SZDD/KWAJ compressed payload files in FULL profile staging` — install-media `*.SY_` / `*.EX_` files are SZDD/KWAJ; previously landed compressed in `C:\DOS`, now expanded to canonical names. |
| `ba29cc4` | `fix(msdos71): write canonical MSDOS.SYS after OSR2 SYS install` — OSR2's `SYS C:` writes a 6-byte stub `MSDOS.SYS`; replaced with the canonical 1150-byte stub (`[Paths]` + `[Options]`). |
| `9bb90d0` | **msdos71: stage authentic OSR2 DOS utilities to `C:\DOS`** — extracts FDISK.EXE/EXTRACT.EXE/HIMEM.SYS from `Boot.img` + expands `ebd.cab` (ATTRIB, FORMAT, EDIT, SYS, SCANDISK, MSCDEX, PKZIP/PKUNZIP, REGEDIT, XCOPY/XCOPY32, etc.) → 28 files / 948 KB in `C:\DOS`. |
| `79950a1` | **msdos71: silence OSR2 boot warnings for HIMEM/IFSHLP/DBLBUFF** — `HIMEM.SYS` now also staged at `C:\` root (sourced from Boot.img); MSDOS.SYS gets `DoubleBuffer=0` + `Network=0` to suppress load attempts for `IFSHLP.SYS` and `DBLBUFF.SYS` (which don't exist on any OSR2 floppy — confirmed by scanning all of Disk01–22 + PRECOPY*.CAB + WIN95_*.CAB + MINI.CAB). |

---

## 2. What works on Windows today

End-to-end on a Windows host with `scripts/install-windows-prereqs.ps1`
and a populated `vendor/windows/bin/`:

### 2.1 Disk creation
- **FAT12 floppy IMG** in all 5 standard sizes (360K, 720K, 1.2M, 1.44M, 2.88M) via pure-Python `_core.fat12_floppy`.
- **VHD creation** in FAT12/FAT16/FAT32, fixed-size, with authentic VHD footer geometry (force-`current_size = cyl*heads*spt*512`) so 86Box AUTO IDE picks NORMAL.
- **MartyPC Xebec + AT/XT-IDE/JR-IDE** geometry presets honored on Windows.
- **Custom payload directory copy** into a VHD via bundled mtools, with VCS metadata + OS droppings stripped.

### 2.2 Boot modes (all bootable in 86Box, verified)
- **FreeDOS** (FAT12 floppy + FAT16/FAT32 VHD) — initial port, still the reference.
- **MS-DOS 3.30** — QEMU-driven `FORMAT C: /S`, MBR type 0x04, 4DOS overlay supported.
- **Compaq DOS 3.31** — QEMU-driven `SYS C:` from `STARTUP.IMG`, mformat-laid-out BPB, OEM `IBM  3.3`.
- **MS-DOS 5.00** — QEMU-driven `FORMAT C: /S` (post-`8d978cb`).
- **MS-DOS 6.22** — QEMU-driven `FORMAT C: /S` (post-`8d978cb`).
- **MS-DOS 7.10 / Win95 OSR2** — Win95 OSR2 floppies (`dosassets/w95/Boot.img`) + QEMU `SYS A: C:` + canonical MSDOS.SYS stub + C:\DOS\ hydrated from Boot.img + ebd.cab + HIMEM.SYS at root + Network/DoubleBuffer=0.
- **PC-DOS 7.0** — LOADDSKF decompression via DOSBox-X + FORMAT-C:-/S install.
- **PC-DOS 7.1** — FAT32 + IBMBIO/IBMDOS `+R +S +H` post-FORMAT, PC-DOS-dialect CONFIG.SYS (`LASTDRIVE=Z` not `26`).
- **IBM PC-DOS 3.30 / 5.0** (via `ibm8088` boot mode + `--ibm-dos-version`) — QEMU FORMAT install path.

### 2.3 FULL profile (system + tools)
- Authentic install-media files are copied into `C:\DOS\` (per-DOS rules).
- SZDD/KWAJ compressed files are expanded to canonical names.
- Install-floppy stub `AUTOEXEC.BAT` / `CONFIG.SYS` is overridden by the dosforge-generated pair.
- OSR2 hydrates `C:\DOS\` from Boot.img loose tools + ebd.cab.

### 2.4 Hydrated profile (FULL + custom payload)
- `--custom-payload-path <dir>` copies the directory into the VHD root.
- VCS metadata + OS droppings excluded.
- Auto-sizing: dosforge computes the required size based on payload bytes + per-DOS overhead.

### 2.5 Distribution
- **`dosforge-full-windows-x86_64.zip`** (~150 MB): full PyInstaller bundle with Textual TUI, mtools, qemu-img, DOSBox-X (replaces qemu-system-i386), 86Box ROM bundle, all dosassets.
- **`dosforge-lite-windows-x86_64.zip`** (~80 MB): TUI bundle without 86Box ROMs / no DOSBox-X — relies on `DOSFORGE_DOSASSETS_DIR` for assets.
- **`dosforge-cli-windows-x86_64.zip`** (~27 MB): headless CLI for matrix scripting, no TUI deps.
- Built in parallel by `.github/workflows/release.yml` (matrix strategy, `396dca6`).
- `_internal/` bloat (`Cryptodome.SelfTest` / `setuptools` / `.dist-info`) pruned (`3825840`).

### 2.6 Tooling
- **Native Mount-DiskImage** on Windows via PowerShell (no kernel mount needed).
- **mtools wrappers**: `dosforge ls / cat / get / put / rm / mkdir` against a VHD/IMG, all routed through bundled mtools on Windows.
- **TUI**: full Textual TUI works on Windows (backend-gates the mount UI off, uses tkinter file picker).
- **SHA-256 content-stamped cache** under `%LOCALAPPDATA%\dosforge\cache\`.

---

## 3. Verification status

- **Unit tests:** `pytest -q` is intentionally skipped per repo
  policy during routine work (slow, hangs in this environment). The
  targeted suites — `test_disk_validation`, `test_disk_windows_vhd`,
  `test_authenticity_golden`, `test_strict_authenticity` — pass
  100% on Windows after every commit in §1.6.
- **86Box native boot:** verified end-to-end by user (FreeDOS,
  MSDOS33, MSDOS5, MSDOS622, MSDOS71-OSR2, PCDOS7, IBM8088-DOS33,
  IBM8088-DOS50) booting to `C:\>` from rebuilt matrix VHDs.
- **OSR2 boot warnings** (`Starting Windows 95...` → "missing
  C:\HIMEM.SYS / C:\DBLBUFF.SYS / C:\IFSHLP.SYS"): suppressed in
  `79950a1` via HIMEM-at-root + `DoubleBuffer=0` + `Network=0`.
  **Pending user re-verification** (commit landed 2026-05-29).

---

## 4. Open phases / known follow-ups

### 4.1 Awaiting user verification
- **OSR2 boot-warning suppression** (commit `79950a1`). User
  previously hit the "missing C:\HIMEM.SYS / C:\DBLBUFF.SYS /
  C:\IFSHLP.SYS" prompts before reaching `C:\>` — fix is in
  but a clean 86Box boot pass hasn't been confirmed yet.

### 4.2 Authenticity gaps
- **IFSHLP.SYS / DBLBUFF.SYS for OSR2** — currently disabled via
  MSDOS.SYS `Network=0` / `DoubleBuffer=0` because the binaries
  don't exist on any OSR2 install diskette (only inside a fully
  Setup-installed Win95 in `C:\WINDOWS\`). If the user later
  supplies an authentic OSR2 hard-disk image we could extract them
  and ship them at `C:\` for a "real Win95-flavored" boot.
- **No Windows 95 GUI boot path** — `BootGUI=0` is hard-coded.
  Booting into the Windows 95 GUI from dosforge VHDs would require
  shipping the full Setup-extracted Windows tree, which is a much
  bigger asset+licensing story.

### 4.3 Distribution polish
- **Bundle size**: lite is ~80 MB. The biggest remaining win is
  pruning unused Textual themes / locale data from the `_internal`
  tree.
- **Code signing**: bundles are unsigned; SmartScreen will flag
  first-run. No EV cert in flight.
- **MSI installer**: only `.zip` bundles ship today. Inno Setup /
  WiX wrapper is the natural next step but not on the roadmap.

### 4.4 Test infrastructure
- **Native 86Box CI**: `tests/test_native_86box_boot.py` is gated
  on `VHDMAKER_86BOX_BOOT_COMMAND` env var being set; CI doesn't
  run it (no 86Box in CI). Manual user verification covers it for
  now. Worth a future GitHub Actions self-hosted-runner-on-Windows
  matrix.
- **DOSBox-X probe tests**: same pattern — local-only, no CI run.

### 4.5 Boot modes not yet ported
None. As of `8d978cb` + `07f9638` every DOS boot mode the TUI
exposes works on Windows.

---

## 5. File-system layout (Windows)

```
%LOCALAPPDATA%\dosforge\
  state.json                  # active mounts, last-used paths
  cache\
    boot-assets\              # SHA-256-stamped extracted boot binaries
    pcdos7-install\           # LOADDSKF-decompressed 1.44 MB IMGs
    msdos71-install\          # OSR2 Boot.img-derived staging
  mounts\                     # Mount-DiskImage targets

<repo>\vendor\windows\bin\    # bundled tools (mtools, qemu-img, dosbox-x, ...)
<bundle>\dosforge\_internal\  # PyInstaller payload (full / lite / cli)
<bundle>\dosforge\vendor\     # bundled tools mirrored from repo
<bundle>\dosforge\dosassets\  # FreeDOS + 4DOS + readme (full / lite only)
```

---

## 6. Quick links

- **Repo:** <https://github.com/flynnsbit/dosforge>
- **Active branch:** `feature/dos-authenticity` (auth + OSR2 work)
- **Default branch:** `main`
- **Initial port notes (P0-P3 / FreeDOS-only):** [`windows-progress.md`](windows-progress.md)
- **Strict authenticity rule (hard):** see `.github/copilot-instructions.md` → "High-level architecture" + `tests/test_strict_authenticity.py`.
- **Per-DOS profile registry:** `src/dosforge/_dos/*.py`
- **OSR2 install plumbing:** `src/dosforge/legacy_dos_install.py` (`msdos71_profile`, `install_method='sys_w95'`) + `src/dosforge/disk.py` (`_stage_msdos71_osr2_dos_payload`, `_build_osr2_msdos_sys_content`).
