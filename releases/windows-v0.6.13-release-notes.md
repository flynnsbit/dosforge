# dosforge windows-v0.6.13 — enable FreeDOS FAT32 VHDs on Windows

Closes the last known Windows-only limitation called out in the
`windows-v0.6.0` and `windows-v0.6.12` release notes. `freedos +
fat32` VHDs now build through the Windows pipeline.

## What changed

Before this release the Windows path
(`_create_and_prepare_vhd_no_kernel` in `src/dosforge/disk.py`)
hard-blocked `freedos + fat32` with:

> FreeDOS VHDs on Windows are currently restricted to FAT16. FAT32
> support requires an FAT32 MBR boot code template that the FreeDOS
> asset resolver does not yet produce — fix is tracked in the next
> port phase.

That note was a stale placeholder. The FreeDOS FAT32 boot sector
template (`BOOTSECT_FAT32.BIN`, real `boot32lb` from FDOS/kernel) has
shipped in `dosassets/freedos/` since linux-v0.6.0 (commit `3af7909`),
and `BootAssetResolver` + `BootInstaller.make_partition_bootable` have
always known how to use it. The Windows-side guard was never updated
after the boot sector landed.

This release:

- **Removes the `freedos + fat32` `ValidationError`** in
  `_create_and_prepare_vhd_no_kernel`.
- **Extends `fat_bios_chs` to cover `DiskFormat.FAT32`** (was
  FAT12/FAT16 only) so the FreeDOS FAT32 VBR's heads/sectors-per-
  track get patched to match the VHD footer geometry. Without this,
  AT BIOSes >504 MiB apply ECHS bit-shift translation while the VBR
  still uses raw footer CHS, causing `INT 13h` reads to land on the
  wrong sectors (silent boot failure, blinking cursor).
- **Drops the `(FAT16)` qualifier** from the unsupported-mode error
  message so `freedos` is documented as accepting both FAT16 and
  FAT32.

## Authenticity

No change. FreeDOS continues to use its own boot sector + IO.SYS +
COMMAND.COM. The FAT32 boot sector is `boot32lb` from FDOS/kernel,
the same authentic source used on Linux.

## Verification

To exercise the new path:

```powershell
cd dosforge

# Build a 256 MiB FreeDOS FAT32 VHD (FAT32 minimum is 64 MiB; 256 MiB
# is a comfortable starting size). The build runs the FreeDOS asset
# resolver + writes the BOOTSECT_FAT32.BIN VBR + patches BPB
# heads/spt to footer geometry.
.\dosforge create --media-type vhd --boot-mode freedos ^
    --format fat32 --size 256M ^
    --path C:\my-vhds\freedos-fat32.vhd

# Verify the on-disk layout
.\_internal\vendor\windows\bin\mdir.exe -i C:\my-vhds\freedos-fat32.vhd@@1048576 ::
```

Expected: FAT32 partition with KERNEL.SYS + COMMAND.COM + CONFIG.SYS
+ AUTOEXEC.BAT + FDCONFIG.SYS + FDAUTO.BAT + FDOS/ directory at the
root. Then boot in 86Box (AUTO IDE → NORMAL translation) — should
reach the FreeDOS prompt without "Non-System disk" / blinking
cursor.

## Same as `windows-v0.6.12`

Every fix from the v0.6.7→v0.6.12 PC-DOS 7.1 FULL profile hydration
chain is preserved:

- PC-DOS 7.1 + PC-DOS 2000 utility hydration produces 138 files in
  `C:\DOS\` (40 SGTK + 98 from PC-DOS 2000) when the WinWorldPC
  archive is in `dosassets\pcdos2000\`.
- DOSBox-X standard MinGW64 build with built-in MS-DOS emulation.
- Windows mtools quirks (path quoting, trailing-slash) all handled.
- PyInstaller subdir staging works correctly.

## Companion Linux release

`linux-v0.6.13` parity bump. Linux was never affected by the
freedos+fat32 gate — the Linux path
(`_create_and_prepare_vhd_with_nbd`) goes through `parted` + `mkfs.fat
-F 32` + the same shared `BootInstaller.make_partition_bootable`
helper, which has always handled FAT32 correctly. No code changes
on the Linux side.

SHA-256 checksums listed below per artifact.
