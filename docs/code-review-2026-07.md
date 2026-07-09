# DosForge codebase review (understanding + issues)

**Date:** 2026-07-09  
**Scope:** Full-package read-only review of `dosforge` v0.9.57 (not a local-diff review).  
**Goal:** Understand what the code does end-to-end, and surface correctness / reliability / product-consistency issues.

### Status since this review

| Item | Status |
|------|--------|
| **H1** Grow non-atomic swap | **Fixed** (`_atomic_replace_vhd`; commit `a854093` / rebased) |
| **H2** Soft mtools on extract/reinject/stage | **Fixed** (hard-fail when empty or mcopy errors) |
| **H3** IBMBIO → COMPAQ331 auto-detect | **Fixed** (refuses; requires explicit `--boot-mode`) |
| **M3** grow PREVIEW / NotImplemented docs | **Fixed** (module + CLI wording) |
| TUI IBM 8088 DOS-version field snap | **Fixed** (commit `2fc566d`) |
| msdos33 → msdos331 sibling asset alias | **Fixed** (commit `2fc566d`) |
| **H4–H5**, remaining **M\*** / **R\*** | **Open** (see backlog below) |

Original review body follows (issue descriptions left as written at review time).

---

## Context

**dosforge** builds authentically bootable DOS disk images for emulators (86Box, MartyPC, QEMU, etc.):

- Fixed **VHD** (FAT12/16/32, IDE or MFM geometry)
- Floppy **IMG/IMA/VFD** (FAT12 presets)
- **17+ boot modes** (FreeDOS, MS-DOS 3.x–7.1, PC-DOS, Compaq OEM, DR-DOS, IBM 8088 profile, planned 4DOS overlay)
- Surfaces: **CLI**, **Textual TUI** (Linux default), **tkinter GUI** (Windows default)
- Linux: kernel NBD + `parted`/`mkfs` + sudo  
- Windows: pure-Python MBR + mtools `@@offset` + bundled vendor tools (no admin for create)

Authenticity goal (see `docs/flow.md`): boot code and install media match the chosen DOS; no cross-pollinated boot sectors between versions.

---

## Architecture (what everything does)

### Layers

```
CLI (cli.py)  ──┐
TUI (app.py)  ──┼──► formlogic → CreateRequest / GrowManifest
GUI (_gui/*)  ──┘         │
                          ▼
              DiskManager (disk.py) / grow / image_ops / inspect
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
   boot.py          legacy_dos_install   _core/*
   BootAssetResolver  + QEMU FORMAT/SYS  mbr, vhd_footer, fat12
   BootInstaller
         │
         ▼
   _platform (linux | windows) → CommandRunner → host/vendor tools
         │
         ▼
   state.py (mounts JSON) · paths.py (dosassets resolution)
```

| Module | Role | Size (approx) |
|--------|------|---------------|
| `disk.py` | Orchestration: create VHD/IMG, mount/unmount, geometry, QEMU install dispatch | ~4.7k LOC |
| `boot.py` | Asset resolve/extract, FreeDOS download, MBR/VBR install, system-file staging | ~4.9k LOC |
| `app.py` | Textual TUI | ~2.9k LOC |
| `legacy_dos_install.py` | QEMU-driven FORMAT/SYS profiles + installer | ~1.8k LOC |
| `cli.py` | argparse + subcommands | ~1.3k LOC |
| `formlogic.py` | Pure form state → validation → `CreateRequest` (shared TUI/GUI) | ~900 LOC |
| `models.py` | Enums, `CreateRequest`, BIOS drive tables | ~800 LOC |
| `_grow_impl.py` | Grow: extract → rebuild → reinject → swap | ~900 LOC |
| `_gui/*` | Windows-oriented desktop shell | ~2k total |
| `_dos/*` | Authenticity metadata registry | small; **tests-only at runtime** |
| `_core/*` | Pure-Python MBR / VHD footer / FAT12 floppy | small |
| `_platform/*` | Paths, tools, dep lists, mount/NBD capabilities | small |

### Create pipeline (VHD)

1. `preflight` + size/CHS validation (`DiskManager`)
2. `qemu-img create -f vpc` fixed VHD
3. **Linux:** NBD attach → `parted` → `mkfs.fat` / mformat → boot install  
   **Windows:** pure MBR + mformat `@@offset` → boot install
4. **FreeDOS:** host-side KERNEL.SYS + boot sector (no QEMU)  
   **Legacy commercial DOS:** `LegacyDosQemuInstaller` boots install floppy in QEMU, runs FORMAT/SYS, verifies system files
5. Post: rewrite MBR CHS from VHD footer; patch BPB for emulator geometry; optional custom payload via mtools

### Other workflows

- **IMG:** allocate + format FAT12 (mkfs or pure-Python); optional system install or verbatim clone of install disk01
- **Inspect:** MBR slot 0 + first partition BPB + optional `mdir` heuristics
- **Grow:** mtools extract → fresh `create_and_prepare` → reinject (skip protected system files) → optional QEMU boot probe → backup + replace target
- **Image ops:** `ls/cat/get/put/rm/mkdir` via mtools `path@@offset` (CLI; GUI tools currently Windows-gated)
- **Mount:** Linux qemu-nbd + kernel mount (tracked in `state.py`); Windows Mount-DiskImage for VHD only

### Dual “profile” systems (important mental model)

1. **`_dos.DosProfile`** — OEM strings, system-file lists, FS support. Used by **tests/golden authenticity only**. Production never calls `get_profile`.
2. **`LegacyDosInstallProfile` + `_LegacyDosInstallDescriptor` in `disk.py`** — **actual** QEMU install behavior (prompts, method, timeouts, assets).

Drift between these two systems is already visible (e.g. `requires_emulator_for_sys_install` false for modes that use QEMU).

### Entry points

- `dosforge` / `python -m dosforge` → `cli.main` (no args: GUI on Windows, TUI elsewhere)
- `cli_only_main` / `gui_only_main` / `full_console_main` for PyInstaller bundles

---

## Issues found (verified against source)

### High — correctness / data loss / silent mis-install

| # | Issue | Where |
|---|--------|--------|
| **H1** | **Grow “atomic swap” is not atomic.** Target is renamed/unlinked *before* `shutil.copy2` completes. Crash or disk-full during copy leaves user without the live path (and without original if `keep_backup=False`). | `_grow_impl.py` ~889–899 |
| **H2** | **Grow mtools reinject/extract often uses `check=False`.** Failed `mcopy` can still yield a “successful” grow with missing trees. | `_grow_impl.py` ~343–351 and reinject/stage paths |
| **H3** | **Grow/inspect auto-detect maps any `IBMBIO.COM` → `COMPAQ331`.** Growing PC-DOS / DR-DOS / PC-DOS 7.x without explicit `--boot-mode` rebuilds with the wrong DOS family. | `_grow_impl.py` ~298–299; similar heuristic in `inspect.py` |
| **H4** | **Dependency gating for QEMU is stale.** Platform `required_commands` only adds `qemu-system-i386` for `compaq331`/`msdos33`/`msdos331`, but `_uses_legacy_dos_qemu_install` includes msdos5/6/622/71, pcdos*, compaq2/3, drdos*, ibm8088. `check-deps` / preflight can pass without qemu for modes that need it. | `_platform/linux.py` 54–56, 105–107; `_platform/windows.py` ~158; `disk.py` 429–468 |
| **H5** | **Archive extraction has no path sanitization.** `py7zr`/`zipfile.extractall` without rejecting `..` / absolute members — zip-slip style write outside cache when processing untrusted WinWorld archives. | `_legacy_dos_archive.py` 121–133; also `pcdos2000_extract.py` |

### Medium — product consistency / UX / docs

| # | Issue | Where |
|---|--------|--------|
| **M1** | **IBM8088 form silently maps size `512M` → `32M` for all IBM versions**, including DOS 5 (cap ~504 MiB). | `formlogic.py` 844–845 |
| **M2** | **`build_time_hint_for_boot_mode` always returns `None`.** FreeDOS multi-minute builds get no slow-build hint in CLI/TUI/GUI despite call sites. | `formlogic.py` 763–764 |
| **M3** | **`grow.py` module docstring still claims PREVIEW / `NotImplementedError`**, but `grow_vhd` is implemented via `_grow_impl`. | `grow.py` 1–19 |
| **M4** | **Windows allowlist error message omits modes that are actually allowed** (pcdos5, msdos6, drdos*, compaq3) and still says `ibm8088 (dos33)`. | `disk.py` 2397–2423 |
| **M5** | **`pcdos5` is CLI-only** — missing from TUI boot list and GUI `_gui/options.py`. | `app.py`, `_gui/options.py` |
| **M6** | **Image Tools (mtools) UI hidden on Linux** (`supports_mtools = is_windows`) though CLI mtools works on both platforms. | `capabilities.py` 41 |
| **M7** | **VHD auto-extract of `.7z` only for a subset of modes**; docs claim broader “drop .7z anywhere.” PCDOS5/MSDOS family often require pre-extracted IMG. | `disk.py` install path ~3114–3131 |
| **M8** | **`_dos` registry dead for production** — dual source of truth with install profiles; will keep drifting. | `_dos/*` vs `legacy_dos_install.py` |
| **M9** | **4DOS** partially implemented (`fourdos_overlay.py`) but form/TUI/GUI lack host mode; docs/module comments still say “planned.” | models, formlogic, README |
| **M10** | **`list-bios-drive-types` omits MartyPC-Xebec** though models/GUI support it. | `cli.py` ~1175–1196 |
| **M11** | Theme toggle doesn’t refresh nav/status chrome; Linux scroll wheel likely broken (`MouseWheel` only, no Button-4/5). | `_gui/__init__.py`, `_gui/widgets.py` |
| **M12** | Grow target not refreshed from Browse selection while already on Grow view. | `_gui/__init__.py` `set_selected_image` |

### Medium / low — reliability

| # | Issue | Where |
|---|--------|--------|
| **R1** | VHD footer write swallows all `OSError` — geometry updates can fail silently. | `_core/vhd_footer.py` |
| **R2** | State store mount JSON has no lock (TOCTOU under concurrent processes). | `state.py` |
| **R3** | FreeDOS auto-download has no content hash (unlike pcdos71_fetch SHA checks). | `boot.py` FreeDOS fetch |
| **R4** | `mscompress` lacks max output size (decompression bomb risk). | `mscompress.py` |
| **R5** | Inspect only reads MBR partition slot 0. | `inspect.py` |
| **R6** | Tests: Windows allowlist includes phantom `test_dosbox_x_install.py`; many platform-neutral tests skipped on Windows; almost no GUI coverage. | `tests/conftest.py` |

### Strengths (balance)

- Clear **formlogic** separation shared by TUI and GUI
- Serious investment in **CHS authenticity** (footer + MBR + BPB alignment for 86Box NORMAL)
- Platform split (NBD vs pure-Python) is coherent
- Broad, documented DOS matrix; PC-DOS 7.1 fetch has real integrity checks
- Large unit test suite for form validation, disk validation, boot assets, CLI

---

## Optional remediation backlog

Prioritized, independent PR-sized chunks:

1. **Grow safety** — `copy2` then `os.replace`; never unlink target first; fail grow on reinject mtools errors; refuse or narrow IBMBIO auto-detect. **(Done — see status table.)**
2. **QEMU dep set** — expand `_LEGACY_DOS_QEMU_BOOT_MODES` (Linux + Windows) to match `_uses_legacy_dos_qemu_install`.
3. **Safe archive extract** — reject `..`/absolute members; stream-hash instead of full `read_bytes` where practical.
4. **Form/UX fixes** — IBM8088 size clamp only for DOS3-class; restore FreeDOS time hint; refresh grow docs; Windows error message list; pcdos5 in TUI/GUI; MartyPC in list-bios; mtools tools on Linux GUI.
5. **Docs/registry** — either wire `_dos` into validation or mark test-only; align 4DOS status.

**Critical files for remaining fixes:**  
`_platform/linux.py`, `_platform/windows.py`, `_legacy_dos_archive.py`, `formlogic.py`, `disk.py`, `capabilities.py`, `_gui/options.py`, `app.py`, `cli.py`.

**Verification:**

```bash
pytest -q
# After dep fix: dosforge check-deps --boot-mode msdos622 --media-type vhd  # must list qemu-system-i386
# After extract fix: unit test with zip member ../../evil.txt must raise
```

---

## Summary judgment

dosforge is a **mature, domain-heavy** disk-image tool with a solid layered design and unusually deep DOS authenticity work. The main risks are not “it doesn’t know what it’s doing,” but:

1. **Grow’s replace path and soft mtools failures** (user data / incomplete grow) — *addressed after this review*
2. **Stale dependency allowlists** vs the real QEMU install matrix
3. **Untrusted archive extraction** without path confinement
4. **UI/docs/registry drift** (pcdos5, FreeDOS hints, dual profile systems, grow PREVIEW text)

This document is the durable copy of the 2026-07-09 full-package review plan.
