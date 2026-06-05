# Build flow reference — every boot mode

This document records exactly what `dosforge` does for each `--boot-mode` and
`--media-type` combination. It is the build-flow companion to
[`FREEDOS_VHD_REFERENCE.md`](FREEDOS_VHD_REFERENCE.md) and
[`MSDOS33_VHD_REFERENCE.md`](MSDOS33_VHD_REFERENCE.md).

The goal is authenticity: every VHD or IMG must be byte-equivalent to a real
install from **that DOS's own install media**. We never cross-pollinate boot
code between DOS versions (FreeDOS code only runs when `--boot-mode=freedos`,
PC-DOS 7.0 MBR boot code only goes onto PC-DOS 7.0 disks, etc.).

---

## Top-level dispatch

`DiskManager.create_and_prepare()` (`src/dosforge/disk.py`) picks one of three
pipelines based on the request:

| Request                                                | Pipeline                              | Section |
|--------------------------------------------------------|---------------------------------------|---------|
| `--boot-mode=4dos`                                     | `_create_and_prepare_fourdos()`       | [4DOS overlay](#4dos-shell-overlay-4dos)  |
| `--media-type=img`                                     | `_create_and_prepare_floppy_img()`    | [Floppy IMG](#floppy-img-media-type--img) |
| `--media-type=vhd` (everything else)                   | `_create_and_prepare_vhd()` (Linux NBD) / `_create_and_prepare_vhd_no_kernel()` (Windows) | [VHD per-mode](#vhd-per-mode-flows) |

Every VHD build then runs through the same six high-level stages; the boot mode
selects which substeps activate.

### Common VHD prelude (every boot mode, every host)

1. `preflight()` — verify required tools, then `_validate_create_request()`.
2. `_normalize_vhd_size_for_chs()` — round size up to a CHS-aligned boundary so
   86Box AUTO IDE picks NORMAL translation.
3. `_create_fixed_vhd()` — `qemu-img create -f vpc -o subformat=fixed,force_size=on …`
   to produce a fixed-size VPC-format VHD whose `current_size` equals
   `cyl × heads × spt × 512` exactly.
4. `_read_vpc_bios_chs_geometry()` — read footer CHS so later BPB patches use
   geometry the target BIOS will actually report.

### Common VHD post-install (Linux NBD path)

After the per-mode work below finishes, `create_and_prepare()` always does:

5. `_rewrite_mbr_partition_entry_for_footer()` — re-encode the MBR partition
   CHS using the VHD footer's geometry (overrides whatever `parted` wrote).
6. For legacy DOS modes only: `_patch_partition_bpb_to_footer_geometry()` so
   the VBR's INT 13h reads line up with what 86Box presents.
7. Optional `custom_payload` copy via `mtools` or the kernel mount.

### Common tools, by job

| Job                                              | Linux tool                              | Windows backend tool                |
|--------------------------------------------------|-----------------------------------------|-------------------------------------|
| Create fixed VHD                                 | `qemu-img create -f vpc`                | `qemu-img.exe` from bundle          |
| Attach VHD as block device                       | `qemu-nbd` + `/dev/nbdN`                | n/a (pure-Python + `@@offset`)      |
| Partition table                                  | `parted --script` + `_set_mbr_partition_type` | `core_mbr.write_single_partition_mbr` |
| Filesystem layout (FAT12/16/32)                  | `mkfs.fat` or `mformat`                 | `mformat`                           |
| Sector I/O (boot code, FAT patches)              | `dd` (sudo)                             | Python file I/O                     |
| FAT directory access (copy/list/attrib)          | `mcopy` / `mdir` / `mattrib` / `mdel`   | same `mtools` binaries              |
| QEMU-driven SYS/FORMAT install                   | `qemu-system-i386`                      | `qemu-system-i386.exe` from bundle  |
| PC-DOS 7.0 install-media extraction              | DOSBox-X + `LOADDSKF.EXE`               | same (DOSBox-X bundled)             |
| OSR2 Quantum CAB extraction                      | `7z` (optional, host-side)              | `7z.exe` (bundled)                  |

---

## VHD per-mode flows

Each subsection describes the substeps between the [common prelude](#common-vhd-prelude-every-boot-mode-every-host)
and [common post-install](#common-vhd-post-install-linux-nbd-path).

### Boot mode dispatch summary

| boot-mode    | FAT    | Install style                             | MBR ptype | VBR OEM    | Profile module                       |
|--------------|--------|-------------------------------------------|-----------|------------|--------------------------------------|
| `none`       | any    | mkfs.fat only (data disk)                 | 0x0C/0x06 | mkfs.fat   | —                                    |
| `freedos`    | 16/32  | Stage FreeDOS KERNEL.SYS + sys-fat patch  | 0x0C/0x06 | mkfs.fat\* | `boot.py` (`BootInstaller`)          |
| `msdos33`    | 16     | QEMU FORMAT C: /S (MS-DOS 3.30 floppy)    | 0x04      | MSDOS3.3   | `legacy_dos_install.msdos33_profile` |
| `msdos331`   | 16     | QEMU FORMAT C: /S (Compaq STARTUP.IMG)    | 0x04      | IBM  3.3   | `legacy_dos_install.compaq331_profile` |
| `msdos5`     | 16     | QEMU FORMAT C: /S (MS-DOS 5.0 Disk1)      | 0x06      | MSDOS5.0   | `legacy_dos_install.msdos5_profile`  |
| `msdos622`   | 16     | QEMU FORMAT C: /S (MS-DOS 6.22 Disk1)     | 0x06      | MSDOS5.0   | `legacy_dos_install.msdos622_profile` |
| `msdos71`    | 16/32  | QEMU SYS A: C: (Win95 OSR2 Boot.img)      | 0x0E/0x0C | MSWIN4.1   | `legacy_dos_install.msdos71_profile` |
| `pcdos`      | 16     | QEMU FORMAT C: /S (LOADDSKF→144US1.DSK)   | 0x06      | IBM  7.0   | `legacy_dos_install.pcdos7_profile`  |
| `pcdos7`     | 16     | QEMU FORMAT C: /S (LOADDSKF→144US1.DSK)   | 0x06      | IBM  7.0   | `legacy_dos_install.pcdos7_profile`  |
| `pcdos71`    | 16     | QEMU FORMAT C: /S (SGTK tk_raid.vfd)      | 0x0E      | IBM  7.1   | `legacy_dos_install.pcdos71_fat16_profile` |
| `pcdos71`    | 32     | QEMU FORMAT32 + FDISK32 /MBR (SGTK)       | 0x0C      | IBM  7.1   | `legacy_dos_install.pcdos71_profile` |
| `compaq331`  | 16     | QEMU FORMAT C: /S (Compaq STARTUP.IMG)    | 0x06      | IBM  3.3   | `legacy_dos_install.compaq331_profile` |
| `ibm8088`    | 16     | Reuses `msdos33` or `msdos5` per `--ibm-dos-version` | 0x04/0x06 | MSDOS3.3/5.0 | (reuse)                              |
| `4dos`       | any    | Build host DOS, then overlay 4DOS shell   | host's    | host's     | `_create_and_prepare_fourdos()`      |

\*FreeDOS deliberately preserves the `mkfs.fat` OEM string in the BPB; the
*actual* boot code is FreeDOS's KERNEL.SYS loader.

---

### FreeDOS (`--boot-mode=freedos`)

Fully host-side. No emulator is launched.

1. NBD attach → `parted mklabel msdos` + `mkpart` at 1 MiB + `set boot on` + `set lba on`.
2. `mkfs.fat -F 16` or `-F 32` on the partition.
3. `boot_resolver.resolve()` → loads FreeDOS assets from
   `~/.local/share/dosforge/dosassets/freedos/` (or installs them with
   `omarchy install freedos`). Returns `KERNEL.SYS`, `COMMAND.COM`,
   `CONFIG.SYS`, FAT12/16/32 boot-sector templates, and full `FDOS/` payload.
4. `BootInstaller.make_partition_bootable()`:
   * `_write_mbr_boot_code()` — `dd` an installer-style MBR (`MBR_FAT16.BIN`
     extracted from a reference FreeDOS VHD if available, otherwise syslinux
     `mbr.bin`).
   * `_write_boot_sector()` — `dd` the FAT16 or FAT32 VBR template. For FAT32
     the template prefers a VBR extracted from a known-good FreeDOS VHD over
     the generated `BOOTSECT_FAT32.BIN`.
   * `_copy_system_files()` — kernel mount the partition, `cp` KERNEL.SYS +
     COMMAND.COM, normalize `CONFIG.SYS` `SHELL=` line, then `chattr +iSh` the
     system files; on the no-NBD path use `mcopy` + `mattrib +s +h`.
5. Copy `FDOS/` tree into `C:\FDOS\` via the same mechanism.
6. For FAT16: `patch_fat16_bpb_geometry()` rewrites BPB `heads`/`secs/track` to
   match the VHD footer so the boot code's INT 13h CHS matches BIOS geometry.

See [`FREEDOS_VHD_REFERENCE.md`](FREEDOS_VHD_REFERENCE.md) for full detail.

---

### MS-DOS 3.30 (`--boot-mode=msdos33`)

Drives MS-DOS 3.30's own FORMAT inside QEMU. Skips `mkfs.fat` entirely.

1. NBD attach → `parted mklabel msdos` + `mkpart` at `63s` + `set boot on` +
   `set lba off`.
2. `_set_mbr_partition_type` → byte 0x04 (FAT16 short — DOS 3.30 predates
   FAT16B/0x06).
3. `_zero_partition_head(2 MiB)` so DOS's FORMAT lays out everything from
   scratch.
4. `BootInstaller.write_mbr_only()` — `dd` a generic DOS-3.3-compatible MBR
   (DOS 3.30 has no `FDISK /MBR`).
5. NBD detach.
6. `_install_legacy_dos_via_qemu(profile=msdos33_profile)`:
   * `_prepare_install_floppy()` — clone DISK01 from `dosassets/msdos33/`,
     inject a `CONFIG.SYS` (`FILES=8 BUFFERS=8`) and an `AUTOEXEC.BAT` whose
     body is:
     ```bat
     FORMAT C: /S < A:\YES.TXT > A:\FMT_OUT.TXT
     COPY A:\COMMAND.COM C:\
     ECHO OK> C:\VHDMK.OK
     :HALT
     GOTO HALT
     ```
   * `YES.TXT` is `Y\r\n\r\n` (DOS 3.x FORMAT prompts once).
   * `qemu-system-i386 -machine pc -cpu 486 -m 16 -display none -drive
     file=floppy,if=floppy -drive file=vhd,if=ide,format=vpc -boot a`.
   * Host poll loop checks for `C:\VHDMK.OK` via `mdir -i vhd@@offset`.
   * On success, verify `IO.SYS`/`MSDOS.SYS`/`COMMAND.COM` exist on C: and
     delete the marker.
7. `_stage_legacy_dos_full_profile_payload()` — copy `CONFIG.SYS` +
   `AUTOEXEC.BAT` + `DOS/` tools if the user picked the FULL install profile.
8. `_patch_partition_bpb_to_footer_geometry()`.

XT-class target (MartyPC Xebec): step 4 is replaced by `_rewrite_mbr_for_xt_class`
which writes a CHS-only DOS-3.3 MBR with a track-aligned partition entry.

---

### MS-DOS 3.31 / Compaq DOS 3.31 (`--boot-mode=msdos331`, `compaq331`)

Same FORMAT-from-scratch flow as `msdos33`, but:

* **Install media** comes from `dosassets/msdos331/Disk1.img` *or* the Compaq
  `STARTUP.IMG` from `dosassets/compaq331/`. Both descriptor entries point at
  `compaq331_profile()`.
* **Partition type** diverges:
  * `compaq331` → **0x06** (FAT16B / BIGDOS). Compaq DOS 3.31 introduced
    BIGDOS, and its `FORMAT.COM` refuses to format type-0x04 partitions
    (`Format failure` before the prompt).
  * `msdos331` → **0x04** (FAT16 short, what real MS-DOS 3.31 writes).
* `patch_fat16_bpb_geometry` runs after the MBR write (the FAT layout is what
  `parted`/`mformat` produced before QEMU starts; QEMU's FORMAT overwrites it).

---

### MS-DOS 5.0 / 6.22 (`--boot-mode=msdos5`, `msdos622`)

Same skeleton as msdos33 with three differences:

* Install media: `dosassets/msdos5/Disk01.img` or `dosassets/msdos622/Disk1.img`.
* Partition type **0x06** (FAT16B), set by `_set_mbr_partition_type` inline.
* AUTOEXEC.BAT runs `FDISK /MBR` first (`supports_fdisk_mbr=True`) — writes
  authentic MS-DOS 5/6.22 LBA-aware MBR boot code over the generic MBR.
* `YES.TXT` is `Y\r\nY\r\n\r\n` (the **`format_yes_input`** field): DOS 5+
  FORMAT asks "Proceed with Format?" *twice* when the partition already has a
  FAT (the one `mkfs.fat` laid down differs from FORMAT's spec). The second Y
  is critical — without it FORMAT bails out without transferring system files.

The full autoexec stanza:

```bat
@ECHO OFF
FDISK /MBR > A:\MBR_OUT.TXT
FORMAT C: /S < A:\YES.TXT > A:\FMT_OUT.TXT
COPY A:\COMMAND.COM C:\ > A:\CP_OUT.TXT
ECHO OK> C:\VHDMK.OK
:HALT
GOTO HALT
```

---

### MS-DOS 7.10 (`--boot-mode=msdos71`)

Uses Win95 OSR2's Emergency Boot Disk (`Boot.img` in `dosassets/w95/`) plus
host-side cab extraction. Supports both FAT16 and FAT32.

1. NBD attach → `parted` (1 MiB alignment, LBA on) → `mkfs.fat -F 16` or `-F 32`.
2. MBR ptype 0x0E (FAT16 LBA) or 0x0C (FAT32 LBA).
3. `BootInstaller.write_mbr_only()` (generic MBR; replaced inside QEMU by
   FDISK /MBR).
4. **Pre-install host-side staging** (`vhd_pre_install_copies`):
   * Locate `Disk13.img` + `Disk17.img` in the OSR2 floppy set.
   * Extract `WIN95_13.CAB` and `WIN95_17.CAB` host-side.
   * Use `7z` to extract `DBLBUFF.SYS` and `IFSHLP.SYS` from those Quantum-
     compressed CABs (the OSR2-vintage `EXTRACT.EXE` cannot handle Quantum).
   * Stage them onto C:\ via `mcopy` before QEMU launches.
5. `_install_legacy_dos_via_qemu(profile=msdos71_profile)`:
   * `_prepare_install_floppy()` rewrites `CONFIG.SYS` (himem + ramdrive only,
     no CD-ROM menu) and replaces `AUTOEXEC.BAT` with a script that:
     ```bat
     CALL SETRAMD.BAT
     EXTRACT /Y /E /L %RAMD%:\ A:\ebd.cab
     %RAMD%:\FDISK.EXE /MBR
     %RAMD%:\sys.com A: C:
     COPY A:\COMMAND.COM C:\
     %RAMD%:\ATTRIB.EXE +R +S +H C:\IFSHLP.SYS
     %RAMD%:\ATTRIB.EXE +R +S +H C:\DBLBUFF.SYS
     ECHO OK> C:\VHDMK.OK
     ```
   * QEMU runs; `SYS A: C:` writes the authentic MSWIN4.1 OEM VBR and copies
     IO.SYS/MSDOS.SYS/DRVSPACE.BIN/COMMAND.COM.
6. `_stage_legacy_dos_full_profile_payload()`.
7. **No** `_patch_partition_bpb_to_footer_geometry()` for FAT32 — the SeaBIOS
   geometry that SYS preserves works on 86Box. FAT16 still gets the patch.

---

### PC-DOS 7.0 / PC-DOS (`--boot-mode=pcdos7`, `pcdos`)

The install media is IBM's proprietary **LOADDSKF-compressed** `144US1.DSK`
(magic `AA 59 F0`). `mtools` and `qemu-system-i386 imgmount` cannot read it
directly.

1. **Host-side decompression** (cached under `~/.local/share/dosforge/cache/pcdos7-install/`):
   * `_pcdos7_loaddskf.extract_pcdos7_install_floppy()` launches **DOSBox-X**
     mounting `dosassets/pcdos7/` (which bundles IBM's `LOADDSKF.EXE`).
   * Inside DOSBox-X: `LOADDSKF 144US1.DSK ramdrive:` produces a raw 1.44 MB
     IMG that DOSBox-X writes back to the cache.
2. NBD attach → `parted` (63s start, lba off) → `mkfs.fat -F 16`.
3. MBR ptype 0x06.
4. `BootInstaller.write_mbr_only()`.
5. `patch_fat16_bpb_geometry()` (the partition still has the mkfs.fat layout
   for now; QEMU's FORMAT will replace it).
6. `_install_legacy_dos_via_qemu(profile=pcdos7_profile)` — same shape as
   msdos5/622 (FDISK /MBR → FORMAT C: /S → COPY COMMAND.COM → VHDMK.OK).
7. `_stage_legacy_dos_full_profile_payload()`.

The `pcdos` alias routes through this exact same pipeline, with
`asset_fallback_dirs=("pcdos", "pcdos7")` so users can drop their own install
media in `dosassets/pcdos/`.

---

### PC-DOS 7.1 FAT16 (`--boot-mode=pcdos71 --format=fat16`)

PC-DOS 7.1 ships **both** `FORMAT.COM` and `FORMAT32.COM` in the SGTK
`tk_raid.vfd` install media (under `DOS/`). The FAT16 path uses `FORMAT.COM`.

1. NBD attach → `parted` (1 MiB alignment) → `mkfs.fat -F 16`.
2. MBR ptype **0x0E** (FAT16 LBA — PC-DOS 7.1's VBR is LBA-aware).
3. `BootInstaller.write_mbr_only()` (LBA-aware generic MBR — works because
   `pcdos71_fat16_profile.supports_fdisk_mbr=False`; see below).
4. `patch_fat16_bpb_geometry()`.
5. `_install_legacy_dos_via_qemu(profile=pcdos71_fat16_profile)`:
   * Pre-install copy: stages `DOS/FORMAT.COM` from the boot-assets directory
     onto `tk_raid.vfd` (which ships IBMBIO/IBMDOS/COMMAND.COM at root but no
     FORMAT tool).
   * AUTOEXEC.BAT runs `FORMAT C: /S < A:\YES.TXT > A:\FMT_OUT.TXT` (no
     `FDISK /MBR` — see [the FDISK note](#why-pcdos71fat16-skips-fdisk-mbr)).
   * `YES.TXT` is `Y\r\nY\r\n\r\n` (DOS 5+ double-prompt pattern).
6. `mattrib +R +S +H` on `IBMBIO.COM` and `IBMDOS.COM` — PC-DOS 7.1's VBR
   loader scans for entries with +System+Hidden attributes; without those bits
   it prints "Non-System disk".
7. `_stage_legacy_dos_full_profile_payload()`.
8. `_patch_partition_bpb_to_footer_geometry()`.

#### Why pcdos71+fat16 skips FDISK /MBR

In the FAT16 path, `FDISK /MBR` (even silent with stdout redirected to
`A:\MBR_OUT.TXT`) interacts badly with the subsequent `FORMAT C: /S` step and
corrupts the install floppy's FAT, leaving AUTOEXEC unable to continue past
FORMAT. The FAT32 path does not exhibit this — it uses `FDISK32 /MBR` from a
different binary. Isolated in `pcdos71_fat16_profile` via
`supports_fdisk_mbr=False`. dosforge's own LBA-aware MBR (with ptype 0x0E)
boots PC-DOS 7.1 fine without the refresh.

---

### PC-DOS 7.1 FAT32 (`--boot-mode=pcdos71 --format=fat32`)

Requires ≥1 GiB (FORMAT32 rejects smaller partitions: *"The drive specified is
too small to use FAT32."*).

1. NBD attach → `parted` (1 MiB alignment, lba on) → `mkfs.fat -F 32`.
2. MBR ptype 0x0C.
3. `BootInstaller.write_mbr_only()`.
4. `_install_legacy_dos_via_qemu(profile=pcdos71_profile)`:
   * Pre-install copies: stages `DOS/FORMAT32.COM` and `DOS/FDISK32.COM` onto
     `tk_raid.vfd`.
   * AUTOEXEC.BAT runs:
     ```bat
     FDISK32 /MBR > A:\MBR_OUT.TXT
     FORMAT32 C: /Q /V:DOS71 < A:\YES.TXT > A:\FMT1_OUT.TXT
     FORMAT32 C: /Q /S /V:DOS71 < A:\YES.TXT > A:\FMT2_OUT.TXT
     ECHO OK> C:\VHDMK.OK
     ```
   * Two FORMAT32 passes: per vogons.org, `/S` only transfers system files on
     the second pass when the partition was just (re)formatted.
   * `FDISK32 /MBR` writes IBM's LBA-aware MBR boot code (INT 13h AH=42h
     extended LBA reads) — eliminates the whole class of CHS/ECHS/LBA
     translation mismatches.
5. `mattrib +R +S +H IBMBIO.COM IBMDOS.COM`.
6. `_stage_legacy_dos_full_profile_payload()`.
7. `_patch_partition_bpb_to_translated_geometry()` — patches the BPB with the
   AT-BIOS-translated heads/spt (e.g. 64×63 on a >504 MB drive) so the FAT32
   VBR's INT 13h reads line up.

---

### IBM 8088 (`--boot-mode=ibm8088`)

Not its own install pipeline; reuses `msdos33` or `msdos5` based on
`request.ibm_dos_version` (selected via `--ibm-dos-version=DOS33|DOS50` in
the TUI/CLI). The MBR/VBR is whatever the chosen sub-mode produces; the only
addition is the XT-class CHS-only MBR rewrite when paired with
`--machine-target=martypc-xebec` and DOS 3.30.

---

### 4DOS shell overlay (`--boot-mode=4dos`)

Two-phase build via `_create_and_prepare_fourdos()`:

1. Reconstruct an internal `CreateRequest` with `request.boot_mode =
   request.host_boot_mode` and run the entire pipeline above for the host DOS
   (typically `msdos71`). The host DOS owns the VBR / IO.SYS / MSDOS.SYS /
   COMMAND.COM.
2. Overlay 4DOS:
   * `resolve_fourdos_assets_dir()` locates `4DOS.COM` and helpers.
   * `mcopy` them into `C:\4DOS\`.
   * Patch `CONFIG.SYS` to `SHELL=C:\4DOS\4DOS.COM C:\4DOS /P`.

The 4DOS overlay never modifies the boot sector or the system files. It is
strictly a `SHELL=` redirection on top of an otherwise-pristine host DOS.

---

## Floppy IMG (`--media-type=img`)

`_create_and_prepare_floppy_img()` is much simpler than the VHD path:

1. `_create_fixed_img()` — write a zero-padded raw IMG sized for `--floppy-type`.
2. `_format_floppy_img()` — `mkfs.fat -F 12 -g <heads/spt> -M <media> -r <root>`
   on Linux, or pure-Python `format_existing()` on Windows.
3. If `--img-system-format` and a boot mode were given:
   * `boot_resolver.resolve()` loads boot assets for the chosen DOS.
   * For legacy DOS boot modes, `_align_floppy_type_from_source_media()` snaps
     `--floppy-type` to whatever the source install diskette uses (e.g. force
     1.2 MB when MS-DOS 3.30 ships on 1.2 MB media).
   * `BootInstaller.make_floppy_bootable()`:
     * `_write_floppy_boot_sector()` — overlays the DOS boot sector template
       onto sector 0 *while preserving the BPB fields*.
     * `_validate_floppy_bpb_fields_preserved()` — sanity-check.
     * `_copy_system_files()` — `mcopy` IO.SYS/IBMBIO.COM / MSDOS.SYS/IBMDOS.COM
       / COMMAND.COM in the correct cluster order; `mattrib +s +h` on the
       hidden system files.
     * `_validate_legacy_floppy_system_layout()` — confirm IBMBIO/IO.SYS
       landed at cluster 2 (DOS 3.x boot sector requirement).
4. Optional custom payload copy via `_copy_custom_payload_to_filesystem` (Linux
   kernel mount) or `_copy_custom_payload_to_img_via_mtools` (Windows).

Floppy IMG never uses QEMU — the boot assets all ship pre-extracted, so the
host-side `mcopy` + `mattrib` pipeline is sufficient.

---

## QEMU-driven install (shared by all legacy DOS modes)

Implemented in `src/dosforge/legacy_dos_install.py:LegacyDosQemuInstaller`.

### Per-profile knobs (`LegacyDosInstallProfile`)

| Field                       | Purpose                                                                 |
|-----------------------------|-------------------------------------------------------------------------|
| `install_image`             | Path to the bootable install floppy (e.g. `Disk01.img`, `tk_raid.vfd`). |
| `required_system_files`     | Tuple checked after install to confirm SYS files landed on C:.          |
| `install_method`            | `"format"`, `"format32"`, `"sys_w95"` — selects the AUTOEXEC template.  |
| `pre_install_copies`        | `(host_path, "FAT_NAME")` pairs `mcopy`'d onto the floppy before boot.  |
| `pre_install_deletes`       | Names of files/dirs scrubbed from the floppy (`mdel` / `mdeltree`).     |
| `vhd_pre_install_copies`    | Files staged onto **C:** via mtools *before* QEMU launches.             |
| `supports_fdisk_mbr`        | When True, AUTOEXEC runs `FDISK /MBR` before FORMAT.                    |
| `format_yes_input`          | Bytes piped into `FORMAT C: /S` (Y/ENTER variants).                     |
| `timeout_seconds`           | Host-side polling deadline waiting for `C:\VHDMK.OK`.                   |

### QEMU command line

```
qemu-system-i386 -machine pc -cpu 486 -m 16 -display none -nic none \
  -no-reboot \
  -serial file:<cache>/legacydos-qemu-<id>.log \
  -drive file=<work-floppy>.img,if=floppy,format=raw,index=0 \
  -drive file=<target>.vhd,if=ide,format=vpc,index=0,media=disk \
  -boot a
```

The host polls every 1.5s for `C:\VHDMK.OK` on the VHD's partition via
`mdir -i vhd@@offset -a ::VHDMK.OK`. When the marker appears, QEMU is
terminated with SIGTERM. On timeout, the install floppy is copied to
`~/.local/state/dosforge/cache/legacy-dos-install/FAILED-*.img` for
postmortem.

### Postmortem files written by every AUTOEXEC template

| File           | Contents                                                    |
|----------------|-------------------------------------------------------------|
| `A:\STEP.TXT`  | Updated at each phase (`before-format`, `after-format`, …). |
| `A:\MBR_OUT.TXT` | Captured stdout of `FDISK /MBR` (empty when silent).       |
| `A:\FMT_OUT.TXT` (and `FMT1`/`FMT2_OUT.TXT` for FORMAT32) | FORMAT progress + prompts. |
| `A:\CP_OUT.TXT` | Captured stdout of `COPY A:\COMMAND.COM C:\`.              |
| `A:\SYS_OUT.TXT` | (sys_w95 only) Captured stdout of `SYS A: C:`.             |
| `C:\VHDMK.OK`  | The success sentinel polled by the host.                    |

---

## Strict authenticity rule

A useful one-glance check: open the built VHD and verify both:

1. **MBR partition type byte** at offset `0x1be + 4` matches the table above
   for the chosen boot mode + FAT.
2. **VBR OEM string** at `(partition_start_LBA × 512) + 3` for 8 bytes
   matches the expected DOS-specific OEM (`IBM  3.3`, `MSDOS3.3`, `MSDOS5.0`,
   `MSWIN4.1`, `IBM  7.0`, `IBM  7.1`, etc.).

If either differs from the table, the disk is not authentic to the chosen DOS
and should be rebuilt.

```python
from pathlib import Path
data = Path("disk.vhd").read_bytes()
ptype = data[0x1be + 4]
lba = int.from_bytes(data[0x1be + 8 : 0x1be + 12], "little")
oem = data[lba * 512 + 3 : lba * 512 + 11]
print(f"ptype=0x{ptype:02x} oem={oem!r}")
```
