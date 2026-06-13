# MartyPC compatibility reference

MartyPC (https://github.com/dbalsom/martypc) is an 8088-only cycle-accurate
IBM PC / XT emulator.  It ships two hard-disk controllers (one or the
other, picked in the machine config — never both at once):

1. **Xebec Fixed Disk Adapter** — the original 1983 IBM/Xebec MFM
   controller used by the IBM 5160 (XT) and clones.  Source:
   `crates/marty_core/src/devices/hdc/xebec.rs` in MartyPC's tree.
2. **XT-IDE** — the modern open-source 8-bit ISA AT register-set bridge.
   MartyPC's default machine config since v0.4.0.  Source:
   `crates/marty_core/src/devices/hdc/at_formats.rs`.

Both controllers do **strict CHS whitelist matching** when MartyPC
mounts a VHD: if the VHD's footer CHS (cylinders × heads ×
sectors-per-track) doesn't exactly match a whitelisted geometry, the
controller silently fails to mount the disk and the guest BIOS reports
"no fixed disk".  Wrong-geometry VHDs that boot fine in 86Box, PCem,
or DOSBox-X will not boot in MartyPC.

dosforge supports both controllers via the `--disk-controller` CLI
flag (or the **Disk controller** dropdown in the TUI / GUI).

## Xebec (`--disk-controller mfm --bios-drive-type martypc-xebec:N`)

Exactly **4 geometries** are accepted.  Pick by `--bios-drive-type`
slug:

| Slug                  | CHS         | WPC | Size  | Historical drive |
|-----------------------|-------------|-----|-------|------------------|
| `martypc-xebec:1`     | 306×4×17    | 0   | 10 MB | ST-225 / IBM 5160 stock |
| `martypc-xebec:2`     | 615×4×17    | 300 | 20 MB | ST-251 |
| `martypc-xebec:13`    | 306×8×17    | 128 | 20 MB | dual-platter ST-225 variant |
| `martypc-xebec:16`    | 612×4×17    | 0   | 20 MB | Generic 20 MB ST-class |

For backwards compatibility, `phoenix:1`, `phoenix:2`, `phoenix:13`,
and `phoenix:16` land on the same CHS tuples as the corresponding
`martypc-xebec:N` slugs (VHD footers carry CHS only — the wpc field
is metadata for the BIOS setup screen).  The dedicated
`martypc-xebec:N` slugs exist so it's obvious from the command line
which BIOS you're targeting.

**Build command** for a 10 MB Compaq DOS 2.11 Xebec VHD:

```bash
dosforge create \
    --media-type vhd --boot-mode compaq2 \
    --format fat12 \
    --disk-controller mfm \
    --bios-drive-type martypc-xebec:1 \
    --path ~/vhd/compaq2-martypc.vhd
```

## XT-IDE (`--disk-controller xtide`)

dosforge's XT-IDE auto-picker selects the smallest entry in MartyPC's
`AtFormats::vec` whitelist that is large enough to hold the requested
`--size`.  No `--bios-drive-type` needed for the common cases.

The full whitelist is in `_MARTYPC_XTIDE_FORMATS` in
`src/dosforge/disk.py` (127 entries, sourced verbatim from MartyPC's
`at_formats.rs`).  Common sizes:

| `--size`   | Auto-picked CHS  | Actual size |
|------------|------------------|-------------|
| `10M`      | 306×4×17         | 10 MiB |
| `20M`      | 306×8×17         | 20 MiB |
| `32M`      | 1024×4×17        | 34 MiB |
| `64M`      | 1024×5×26        | 65 MiB |
| `100M`     | 776×8×33         | 100 MiB |
| `200M`     | 684×16×38        | 203 MiB |
| `500M`     | 1024×16×63       | 504 MiB |

**Constraints:**
- FAT32 is rejected — XT-class DOS doesn't understand FAT32.
- msdos71 / pcdos71 are rejected — their FDISK only recognizes
  AT-class geometries.
- Largest possible disk is `1054×16×63` ≈ 520 MiB.

**Build command** for a 32 MiB MS-DOS 5.0 XT-IDE VHD:

```bash
dosforge create \
    --media-type vhd --boot-mode msdos5 \
    --format fat16 --size 32M \
    --disk-controller xtide \
    --path ~/vhd/msdos5-martypc.vhd
```

## "It mounted but won't boot"

If MartyPC sees the disk but the guest hangs at the BIOS or fails
INT 19h, the most common cause is a pre-DOS-5 boot mode (msdos33,
pcdos3, compaq2, compaq3) with an MBR that uses LBA reads.  dosforge
already auto-rewrites the MBR to CHS-only form for these modes on
either XT-class controller — but double-check that you're using the
matching `--boot-mode` for the DOS version on the install media.

## Why dosforge can't auto-detect MartyPC

VHD footers carry CHS but no controller-class flag.  An XT-IDE-formatted
disk loaded into 86Box AT-class IDE will appear to mount (the CHS is
valid AT-class geometry) but DOS will read garbage because of cylinder
sector translation differences.  Always rebuild the VHD with the right
`--disk-controller` for the target emulator.
