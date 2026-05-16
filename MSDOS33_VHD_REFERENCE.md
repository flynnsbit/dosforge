# MS-DOS 3.30 VHD Boot Reference

Companion notes for `compaq331`-style legacy DOS boot modes in `vhdmaker`.
Focused on **MS-DOS 3.30** (`msdos33` boot mode).

## TL;DR

`vhdmaker --boot-mode msdos33` produces a bootable FAT16 VHD by:

1. Creating a fixed VPC VHD with normalized 16h/63spt footer geometry.
2. Partitioning with `parted` (legacy LBA 63 start, single primary).
3. Patching the MBR partition entry type byte from `0x06` to **`0x04`**
   (DOS 3.30 predates FAT16B / `0x06`).
4. Zeroing the first 2 MiB of the partition so DOS FORMAT.COM sees an
   uninitialized disk.
5. Writing the standard syslinux MBR boot code.
6. Detaching NBD, then booting MS-DOS 3.30 in `qemu-system-i386` with the
   VHD attached as IDE and a modified `DISK01.IMG` as floppy A:.
7. The injected `AUTOEXEC.BAT` runs `FORMAT C: /S < A:\YES.TXT` followed
   by `COPY A:\COMMAND.COM C:\`, then writes `C:\VHDMK.OK` as a
   completion marker.
8. The host polls for `C:\VHDMK.OK` via `mtools`; once present, QEMU is
   terminated and the disk is verified.

Result: an authentic MS-DOS 3.30 hard-disk boot sector with IO.SYS,
MSDOS.SYS, and COMMAND.COM at the root.

## Constraints (do not relax these)

- **Max partition size: 32 MiB.** DOS 3.30 reads `BPB.total_sectors_16`
  (uint16, max 65,535 sectors ≈ 31.99 MiB). FAT16B with `total_sectors_32`
  was introduced in **DOS 3.31** (Compaq OEM). Enforced in
  `_normalize_vhd_size_for_chs` and explicitly in `_validate_create_request`.
- **Partition type must be `0x04`** (FAT16, < 32 MiB) — *not* `0x06`
  (FAT16B). DOS 3.30 doesn't recognize `0x06` and reports
  "Invalid drive specification" when you try to access C:.
- **FAT16 only.** No FAT32 (DOS 3.30 predates it).
- **Install media must be a bootable MS-DOS 3.30 floppy** containing
  IO.SYS, MSDOS.SYS, COMMAND.COM, FORMAT.COM, SYS.COM. The MS-DOS 3.30
  distribution's `DISK01.IMG` (360K) fits the bill.

## Why MS-DOS 3.30 is fussier than Compaq DOS 3.31

| Concern | DOS 3.30 (`msdos33`) | Compaq DOS 3.31 (`compaq331`) |
|---|---|---|
| FAT16B / >32 MiB partitions | ✗ pre-FAT16B | ✓ supported |
| `mkfs.fat` BPB layout (`reserved=8`) | rejected by SYS | rejected by SYS |
| mformat's default BPB (`reserved=1`) | accepted by SYS but boot fails (see below) | accepted, **disk boots** |
| Partition type | `0x04` only | `0x06` (FAT16B) |
| Recommended install path | `FORMAT C: /S` (DOS lays out FS from scratch) | `mformat` + `SYS C:` |

## Root causes investigated

### "No room for system on destination disk"

DOS 3.x SYS.COM requires that **IBMBIO.COM/IO.SYS occupy specific
positions on disk**:

1. First entry in the root directory.
2. Contiguous clusters starting at the first data cluster.

mkfs.fat 4.x writes `BPB.reserved_sec_count = 8` (the OS/2 compatibility
hint). DOS 3.x SYS reads this and decides there's no room. mformat
writes `reserved = 1` (real-DOS default), which SYS accepts.

### "Non-System disk or disk error" after a successful `SYS C:`

mformat sizes the partition's `BPB.total_sectors_16` from the file image
(`file_size_after_offset / 512`), which can differ from the MBR-declared
partition sector count when the disk file has padding/tail (qemu-img
without `force_size=on` rounds up to its own CHS computation).

DOS 3.30's VBR boot code derives FAT layout from `BPB` values. If
`BPB.total_sectors_16` doesn't match the MBR's partition size, the boot
loader reads at offsets that don't correspond to the data layout the
files were written to → "Non-System disk".

Letting DOS 3.30's own `FORMAT C: /S` lay out the filesystem from scratch
sidesteps this entirely: DOS reads partition size from the MBR's
partition table and computes a self-consistent BPB.

### Disk reports "21 MB, LRG" in 86Box AUTO mode

For our normalized 42×16×63 footer, 86Box's AUTO detection labels the
mode "LRG" (LARGE), but with `cyl=42 ≤ 1024` the LARGE translation is
identity (no head doubling / cyl halving). BIOS reports geometry
straight through to DOS. This is fine and expected; the "LRG" label is
cosmetic.

## Install media expectations

`vhdmaker` looks for the bootable DOS 3.30 floppy under
`request.boot_assets_path` (or auto-detects `./msdos33/` from the
current working directory). Within that directory, it picks the first
match of these preferred filenames:

```
DISK01.IMG, DISK01.IMA, DISK1.IMG, DISK1.IMA
```

If none match, it scans every `*.img` / `*.ima` for one that contains
**both** `SYS.COM` and `IO.SYS` (heuristic fallback).

The chosen image is copied to a scratch location under
`~/.local/state/vhdmaker/cache/legacy-dos-install/`, then a custom
`AUTOEXEC.BAT`, `CONFIG.SYS`, and `YES.TXT` are injected via
`mcopy -i ... -o`. The injected files do not modify the original.

## QEMU command line

`vhdmaker` invokes:

```
qemu-system-i386 \
  -machine pc \
  -cpu 486 \
  -m 16 \
  -display none \
  -serial file:<cache-root>/legacydos-qemu-<id>.log \
  -no-reboot \
  -drive file=<scratch-floppy>,if=floppy,format=raw,index=0 \
  -drive file=<vhd>,if=ide,format=vpc,index=0,media=disk \
  -boot a
```

While QEMU runs, the host polls for `C:\VHDMK.OK` on the VHD partition
every 1.5 s via `mdir -i <vhd>@@<partition-offset>`. The default timeout
for the FORMAT-based install is **300 s** (`profile.timeout_seconds`),
because DOS 3.30's `FORMAT.COM` does a sector-by-sector verify pass.

On QEMU's default IDE backend (max-speed), the 20 MiB format completes
in well under 30 seconds. The verify pass is only "slow" relative to
modern formatting; the actual marker file write happens immediately
after FORMAT returns control to AUTOEXEC.BAT.

## The injected AUTOEXEC.BAT

```bat
@ECHO OFF
PROMPT $p$g
ECHO step=before-format > A:\STEP.TXT
FORMAT C: /S < A:\YES.TXT > A:\FMT_OUT.TXT
ECHO step=after-format > A:\STEP.TXT
COPY A:\COMMAND.COM C:\ > A:\CP_OUT.TXT
ECHO step=after-copy > A:\STEP.TXT
ECHO OK> C:\VHDMK.OK
ECHO step=done > A:\STEP.TXT
:HALT
GOTO HALT
```

`YES.TXT` is `Y\r\n\r\n` — `Y` for the "Proceed with format?" confirmation
prompt and an empty `Enter` for the "Volume label?" prompt.

`STEP.TXT` is written to the floppy on every transition so that
post-mortem inspection (after QEMU is killed) can pinpoint where the
flow halted. Useful for debugging install-media incompatibilities.

## Result BPB (informational)

After `FORMAT C: /S` completes on a 20 MiB partition:

```
OEM:         'MSDOS3.3'
bps:         512
spc:         4         (2 KiB clusters)
reserved:    1
nfats:       2
root:        512
total16:     42273     (matches MBR-declared partition size)
media:       0xF8
fat_size16:  42
spt:         2         (left at "DPT" default; not used by HDD boot)
heads:       3         (left at "DPT" default; not used by HDD boot)
hidden:      63
ext_sig:     0x00      (no DOS-4 extended boot record)
```

**Note:** `spt=2, heads=3` look like nonsense compared to the VHD's
actual `42×16×63` geometry, but DOS 3.30's hard-disk boot loader does
**not** use these fields for INT 13h CHS computation — it goes through
the BIOS's own geometry knowledge. The values are leftover Diskette
Parameter Table defaults that DOS 3.30 FORMAT doesn't overwrite on
hard disks. The disk boots correctly anyway.

## Code locations

- `src/vhdmaker/disk.py`
  - `create_and_prepare` — dispatches MSDOS33 to the legacy DOS path
    (skips `make_partition_bootable`).
  - `_partition_and_format` — for MSDOS33: patches partition type to
    `0x04`, zeros first 2 MiB of partition, skips mformat (FORMAT will
    lay out the FS).
  - `_set_mbr_partition_type` — writes one byte at MBR offset `0x1c2`
    to flip the partition type.
  - `_zero_partition_head` — `dd if=/dev/zero of=<partition> bs=1M count=N`.
  - `_install_legacy_dos_via_qemu` — dispatches to
    `LegacyDosQemuInstaller`.
  - `_resolve_legacy_dos_assets_dir`, `_find_legacy_dos_install_image` —
    asset discovery.

- `src/vhdmaker/legacy_dos_install.py`
  - `LegacyDosInstallProfile` — descriptor with `install_method`
    (`"sys"` or `"format"`) and `timeout_seconds`.
  - `msdos33_profile()` — returns
    `install_method="format", timeout_seconds=300.0`.
  - `LegacyDosQemuInstaller._prepare_install_floppy` — builds the
    AUTOEXEC.BAT for either install method.
  - `LegacyDosQemuInstaller._run_qemu` — launches QEMU, polls for marker.

- `src/vhdmaker/dependencies.py`
  - `LEGACY_DOS_QEMU_COMMANDS` — extra deps required for `msdos33` and
    `compaq331` VHD targets: `qemu-system-i386`, `mformat`, `mcopy`,
    `mattrib`, `mtype`, `mdir`, `mdel`.

## Gotchas to remember

1. **Quit and re-launch the TUI after vhdmaker code changes.** Python
   caches imports in long-running processes. A vhdmaker TUI that was
   already running when you `git pull` or edit source will keep using
   the old code in-memory. The behaviour can range from "missing fix"
   to "silently raises and shows stale status text". Always restart the
   TUI after pulling/editing.
2. **vhdmaker always writes `qemu` as the VHD creator string** (because
   `_create_fixed_vhd` calls `qemu-img`). If a VHD in your dir has
   `creator='mVHD'` (Microsoft VHD signature) or anything other than
   `'qemu'`, it was NOT produced by vhdmaker — it's a stale file from
   86Box's "Create new VHD…" or some other tool. Delete it before
   testing.
3. **`VHDMK.OK` must not exist when polling starts.** vhdmaker zeroes the
   first 2 MiB of the partition before launching QEMU. If you change
   the install method later, make sure any prior marker file is wiped
   so the host doesn't return success from a previous run.
4. **`DISK01.IMG` from MS-DOS 3.30 (5.25-inch 360 KiB)** is what works
   here. Other media (3.5-inch 1.44 MiB MS-DOS 3.30 disks, IBM PC DOS
   3.30 disks with IBMBIO.COM/IBMDOS.COM instead of IO.SYS/MSDOS.SYS)
   need different profiles — `compaq331` for the IBM-style ones.
5. **Don't confuse `msdos33` with `msdos331`.** MS-DOS 3.30 (`msdos33`)
   is FAT16-only ≤ 32 MiB, no FAT16B. MS-DOS 3.31 (`msdos331`) and
   Compaq DOS 3.31 (`compaq331`) introduced FAT16B and accept larger
   partitions. They use a different SYS.COM and different boot code.

## Test commands

```bash
# Build a fresh msdos33-20M.vhd via the CLI (TUI equivalent):
vhdmaker create \
  --path ./msdos33-20M.vhd \
  --size 20M \
  --format fat16 \
  --boot-mode msdos33 \
  --boot-assets-path ./msdos33 \
  --overwrite

# Quick QEMU boot check (no display):
qemu-system-i386 \
  -machine pc -cpu 486 -m 16 -nographic -no-reboot \
  -drive file=msdos33-20M.vhd,if=ide,format=vpc,index=0,media=disk \
  -boot c

# Inspect the produced footer + BPB:
python3 -c '
import os, struct
path = "msdos33-20M.vhd"
with open(path,"rb") as f:
    f.seek(-512, 2); footer = f.read(512)
cur = struct.unpack(">Q", footer[48:56])[0]
print(f"FOOTER: current_size={cur} ({cur//512} sec) "
      f"CHS={struct.unpack(\">H\", footer[56:58])[0]}x{footer[58]}x{footer[59]} "
      f"creator={footer[28:32]!r}")
with open(path,"rb") as f:
    mbr = f.read(512)
e = mbr[0x1be:0x1be+16]
print(f"MBR p1: type=0x{e[4]:02x} lba_start={struct.unpack(\"<I\", e[8:12])[0]} "
      f"sectors={struct.unpack(\"<I\", e[12:16])[0]}")
with open(path,"rb") as f:
    f.seek(63*512); vbr = f.read(512)
print(f"VBR OEM={vbr[3:11]!r} spc={vbr[13]} "
      f"hidden={struct.unpack(\"<I\", vbr[28:32])[0]} "
      f"total16={struct.unpack(\"<H\", vbr[19:21])[0]}")
'
```

## Stored memories (subject: "dos boot")

- "msdos33 boot mode uses FORMAT C: /S inside DOS (not SYS C:); DOS 3.30
  needs MBR partition type 0x04 (not 0x06) and rejects mformat-laid-out
  partitions whose total_sectors_16 differs from the MBR-declared
  partition size."
- "For compaq331 use mformat (mtools) not mkfs.fat — DOS 3.x SYS rejects
  mkfs.fat BPB layout (reserved=8) with 'No room for system'."
- "compaq331 boot mode uses qemu-system-i386 to boot Compaq DOS 3.31
  STARTUP.IMG and run SYS C: on the VHD (offline boot-sector extraction
  is unreliable)."
