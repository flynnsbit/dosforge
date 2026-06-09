# Windows VHD verification pickup

After `linux-v0.6.0` shipped with every supported boot mode × FAT
combination validated in 86Box on Linux, this document is the
handoff for running the equivalent verification pass on Windows.

Generated 2026-06-05. Cross-link: [`docs/flow.md`](flow.md),
[`docs/WINDOWS_WORK.md`](WINDOWS_WORK.md),
[`releases/linux-v0.6.0-release-notes.md`](../releases/linux-v0.6.0-release-notes.md).

---

## TL;DR

You should do a Windows 86Box pass, but a small one — most of the
`linux-v0.6.0` fixes inherit automatically because they live in
shared code.

**Priority:** 5 modes that exercise changed code paths.
**Smoke check:** 10 modes whose Windows code paths are unchanged.
**Known gap:** `freedos+fat32` is still rejected on Windows — optional
follow-up.

---

## How the Linux ↔ Windows pipelines diverge

`DiskManager.create_and_prepare()` dispatches on
`backend.supports_nbd`:

| Stage                       | Linux path                                | Windows path (`_create_and_prepare_vhd_no_kernel`) |
|-----------------------------|-------------------------------------------|----------------------------------------------------|
| Create fixed VHD            | `qemu-img create -f vpc -o force_size=on` | same                                               |
| Read footer CHS             | `_read_vpc_bios_chs_geometry()`           | same                                               |
| Attach for partition write  | `qemu-nbd /dev/nbdN`                      | none — direct file write                           |
| Partition table             | `parted --script mkpart`                  | `core_mbr.write_single_partition_mbr` (pure-Py)    |
| Filesystem                  | `mkfs.fat`                                | `mformat -i vhd@@offset -T -H`                     |
| MBR partition CHS encoding  | `_rewrite_mbr_partition_entry_for_footer` AFTER parted (parted clobbers it) | Inline ECHS translation in `core_mbr.PartitionEntry` BEFORE write |
| MBR boot code               | `BootInstaller.write_mbr_only` (shared)   | same                                               |
| QEMU-driven SYS/FORMAT      | `_install_legacy_dos_via_qemu` (shared)   | same                                               |
| BPB heads/spt patch (FAT16) | `patch_fat16_bpb_geometry` (shared)       | same                                               |
| BPB footer-geometry patch   | `_patch_partition_bpb_to_footer_geometry` (shared) | same                                       |
| BPB ECHS-translated patch   | `_patch_partition_bpb_to_translated_geometry` (shared, pcdos71+FAT32) | same                            |
| pcdos71 IBMBIO/IBMDOS mattrib | `mattrib +R +S +H` (shared)             | same                                               |
| FULL-profile DOS payload    | `_stage_legacy_dos_full_profile_payload` (shared) | same                                       |

---

## How each linux-v0.5.1 → linux-v0.6.0 fix maps to Windows

| Fix (commit)                                | Layer                                  | Windows applicability |
|---------------------------------------------|----------------------------------------|----------------------|
| FreeDOS FAT32 boot sector (`3af7909`)       | `dosassets/freedos/BOOTSECT_FAT32.BIN` + `boot.py` validator | **N/A** — Windows path rejects FreeDOS FAT32 (`disk.py:1917-1926`). Pre-existing Windows limitation. |
| BPB heads/spt FAT32 patch (`1655b61`)       | `boot.py` + `disk.py`                  | **Inherits** — pcdos71+FAT32 calls shared `_patch_partition_bpb_to_translated_geometry`; FreeDOS FAT32 not built on Windows. |
| MBR CHS rewrite after parted (`3951021`)    | Linux-only `_rewrite_mbr_partition_entry_for_footer` | **N/A** — Windows writes MBR via `core_mbr` with ECHS-translated CHS inline (`disk.py:1970-1978`), never had the parted-clobber bug. |
| compaq331 MBR ptype 0x06 (`1fecb40`)        | `_legacy_dos_install_descriptor`       | **Already correct on Windows** — inline ptype dispatch (`disk.py:1987-1996`) sends COMPAQ331 to the `else: 0x06` branch (the `msdos33_layout` helper excludes it). No-op for Windows. |
| msdos5/622/pcdos7 FORMAT double-Y (`e9c5694`) | `legacy_dos_install.py` profile `format_yes_input` | **Inherits** — Windows uses the same profile registry. Behavior change in the QEMU install run. |
| pcdos71 FAT16 install path (`adc7fa7`)      | `pcdos71_fat16_profile` + descriptor branch + `patch_fat16_bpb_geometry` eligibility | **Inherits the install profile**, AND Windows's inline ptype logic at `disk.py:1991` already gives PCDOS71+FAT16 → `0x0E` (FAT16 LBA). Path is wired but **never run on Windows**. |

---

## Bottom line

- **Most fixes inherit automatically** because they live in shared
  modules (`legacy_dos_install.py`, `boot.py`, the
  `_install_legacy_dos_via_qemu` + `_patch_partition_bpb_to_…_geometry`
  helpers).
- **Two Linux-only fixes don't apply to Windows** because the Windows
  pipeline never had the underlying bugs (parted CHS clobber; the
  COMPAQ331 inline ptype was already 0x06).
- **One Linux fix doesn't apply** because the corresponding Windows
  scenario is still rejected (FreeDOS FAT32).
- **Three changes were never re-verified on Windows after landing:**
  msdos5 / msdos622 / pcdos7 FORMAT double-Y change
  rewrite, and the brand-new pcdos71+FAT16 install path.

---

## Verification pass

### Priority targets (touched changed code)

| # | Boot mode + format             | Size     | Why                                               |
|---|--------------------------------|----------|---------------------------------------------------|
| 1 | `pcdos71 + fat16`              | 32 MiB   | **Brand-new install path, no Windows runs yet**   |
| 2 | `msdos5 + fat16`               | 128 MiB  | FORMAT double-Y behavior change                   |
| 3 | `msdos622 + fat16`             | 128 MiB  | FORMAT double-Y behavior change                   |
| 4 | `pcdos7 + fat16`               | 128 MiB  | FORMAT double-Y + LOADDSKF via DOSBox-X           |

### Smoke check (unchanged code paths — should still boot)

| #  | Boot mode + format             | Size     |
|----|--------------------------------|----------|
| 6  | `freedos + fat16`              | 32 MiB   |
| 7  | `msdos33 + fat16`              | 32 MiB   |
| 8  | `msdos331 + fat16`             | 32 MiB   |
| 9  | `compaq331 + fat16`            | 32 MiB   |
| 10 | `msdos71 + fat16`              | 32 MiB   |
| 11 | `msdos71 + fat32`              | 128 MiB  |
| 12 | `pcdos71 + fat32`              | 1 GiB    |
| 13 | `ibm8088 + DOS33`              | 32 MiB   |
| 14 | `ibm8088 + DOS50`              | 32 MiB   |
| 15 | `4dos + msdos71`               | 128 MiB  |

### Known Windows-only gap (not in scope here)

`freedos + fat32` is rejected by the Windows path
(`src/dosforge/disk.py:1917-1926`). The FreeDOS FAT32 boot-sector
fix from `linux-v0.6.0` unblocks adding it — separate optional
follow-up if you want full parity.

---

## How to run on the Windows machine

```powershell
cd $repo
git fetch origin
git checkout linux-v0.6.0     # the tag we just published
.\scripts\install-windows-prereqs.ps1   # once, if not already done
python -m pip install -e .[dev]

# For each priority + smoke target, e.g.:
dosforge create --boot-mode pcdos71 --format fat16 --size 32M `
  --output $env:USERPROFILE\dosforge-win-v6\pcdos71-fat16-32m.vhd

dosforge create --boot-mode msdos5 --format fat16 --size 128M `
  --output $env:USERPROFILE\dosforge-win-v6\msdos5-fat16-128m.vhd

# … (repeat for each of the 15 modes above)
```

Then open each `.vhd` in 86Box (AUTO IDE detection should pick
NORMAL translation). Confirm:
1. Boots to a DOS prompt (no "Missing operating system",
   "Non-System disk", blinking cursor, or "Verifying DMI Pool Data"
   hang).
2. `ver` returns the expected DOS version string.

Report results back per-mode (✅ / failure message) the same way as
the Linux v6 matrix.

---

## If Windows verification surfaces issues

- The `linux-v0.6.0` release is independent — no need to re-cut it.
- Fixes go in shared code where possible (so they auto-apply to
  Linux too) and ride into a follow-up release like `windows-v0.6.0`
  or `v0.6.1`.
- Use the existing per-DOS profile registry in
  `src/dosforge/_dos/*.py` and `src/dosforge/legacy_dos_install.py`
  to scope behavior changes — do not branch on `sys.platform` in
  the boot pipeline.

---

## Quick reference — file locations to read first

- Windows VHD dispatcher: `src/dosforge/disk.py:1868` —
  `_create_and_prepare_vhd_no_kernel`
- Inline ptype + ECHS CHS logic: `src/dosforge/disk.py:1960-2008`
- Shared legacy DOS install: `src/dosforge/legacy_dos_install.py`
- Per-DOS authenticity profiles: `src/dosforge/_dos/*.py`
- Boot installer (mtools + dd-equivalent patches):
  `src/dosforge/boot.py`
- Build-flow reference (per boot mode): [`docs/flow.md`](flow.md)
- Windows port history + capability matrix:
  [`docs/WINDOWS_WORK.md`](WINDOWS_WORK.md),
  [`docs/windows-progress.md`](windows-progress.md)
