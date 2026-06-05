# dosforge v0.6.0 — Linux release (all boot modes validated in 86Box)

The first Linux release with **every supported boot mode × FAT combination
booting to a DOS prompt in 86Box**. 16 VHDs total, each byte-equivalent to a
real install from that DOS's own install media.

Folds in the never-tagged 0.5.2 `init-assets` work plus the 0.5.1 → 0.6.0
boot-test fix sweep.

## Validated in 86Box

Every entry boots to the DOS prompt and reports the correct `ver` string.

| Boot mode    | FAT16 (32 MiB)        | FAT32 (128 MiB+)        |
|--------------|-----------------------|-------------------------|
| `freedos`    | ✅                    | ✅                      |
| `msdos33`    | ✅                    | n/a                     |
| `msdos331`   | ✅                    | n/a                     |
| `compaq331`  | ✅                    | n/a                     |
| `msdos5`     | ✅                    | n/a                     |
| `msdos622`   | ✅                    | n/a                     |
| `msdos71`    | ✅                    | ✅                      |
| `pcdos`      | ✅                    | n/a                     |
| `pcdos7`     | ✅                    | n/a                     |
| `pcdos71`    | ✅ (NEW)              | ✅ (1 GiB+)             |
| `ibm8088`    | ✅ (DOS33 + DOS50)    | n/a                     |
| `4dos`       | ✅ (overlay on host)  | ✅ (overlay on host)    |

## New in 0.6.0

### PC-DOS 7.1 FAT16 install path

`--boot-mode=pcdos71` now accepts `--format=fat16`. dosforge stages
`DOS/FORMAT.COM` from the SGTK `tk_raid.vfd` install media onto the install
floppy and runs `FORMAT C: /S` to lay down an authentic IBM 7.1 VBR.

```bash
dosforge create --boot-mode pcdos71 --format fat16 --size 32M --output pcdos71-32m.vhd
```

The FAT16 profile deliberately **skips** `FDISK /MBR` (a quirk specific to
PC-DOS 7.1's FORMAT + the install floppy's FAT layout — running it corrupts
the floppy mid-AUTOEXEC). dosforge's LBA-aware MBR with ptype `0x0E` boots
PC-DOS 7.1 without the refresh.

### `dosforge init-assets` subcommand (carried over from staged 0.5.2)

```bash
dosforge init-assets               # default: ~/.local/share/dosforge/dosassets/
dosforge init-assets --target /opt/dosforge/dosassets
dosforge init-assets --force       # refresh existing readmes
```

29 per-mode readmes ship inside the wheel — no release tarball required.
Existing readmes are skipped by default; user-supplied install media sitting
next to a readme is never touched.

### `docs/flow.md` build-flow reference

New documentation file under `docs/` covers every boot mode end-to-end: the
common VHD prelude (`qemu-img -o force_size=on …`), per-mode pipeline steps
(NBD attach → parted → mkfs.fat → MBR/VBR write → QEMU SYS/FORMAT install),
tools used (qemu-img, qemu-nbd, mkfs.fat, mformat, mcopy, mattrib,
qemu-system-i386, DOSBox-X, LOADDSKF), MBR partition type, VBR OEM string,
and the per-profile knobs (`format_yes_input`, `supports_fdisk_mbr`,
`pre_install_copies`).

## Boot-test fixes since linux-v0.5.1

All applied on the Linux NBD pipeline; Windows path inherits the same
geometry/format logic.

- **FreeDOS FAT32** — replaced the broken hand-rolled `BOOTSECT_FAT32.BIN`
  with the real `boot32lb` extracted from a reference FreeDOS install.
  Fixes the "blinking cursor after Verifying DMI Pool Data" hang in 86Box.
- **BPB heads/spt patch** — now applied for FAT32 partitions, not just
  FAT16. The FAT32 VBR's INT 13h reads now land on the right cluster.
- **MBR partition CHS rewrite** — `_rewrite_mbr_partition_entry_for_footer()`
  re-encodes the partition CHS using the VHD footer's geometry after
  `parted` runs, so 86Box AUTO IDE picks NORMAL translation.
- **Compaq DOS 3.31** — writes MBR partition type `0x06` (BIGDOS) instead
  of `0x04`; Compaq's `FORMAT.COM` refused to format type-`0x04` partitions
  and failed silently before the partition prompt.
- **MS-DOS 3.31** — keeps `0x04` (FAT16 short — what real MS-DOS 3.31 writes).
- **MS-DOS 5.0 / 6.22 / PC-DOS 7.0 FORMAT C: /S** — now feeds `Y\r\nY\r\n\r\n`
  to FORMAT (was `Y\r\n\r\n`). DOS 5+ FORMAT asks "Proceed with Format?"
  twice when the partition already has a FAT (the one `mkfs.fat` laid
  down differs from FORMAT's spec). Without the second Y, FORMAT bailed
  without transferring system files → "Missing operating system" at boot.
- **`pcdos` alias** routes through the PC-DOS 7.0 QEMU install pipeline
  (LOADDSKF-decompressed `144US1.DSK`) instead of FreeDOS-style staging.
- **PC-DOS 7.1 FAT32** — validation now correctly directs users to the
  FAT32 path when their VHD is ≥1 GiB (FORMAT32 rejects smaller drives).

## sudoers note for `mformat`

Some PC-DOS 7.1 / MS-DOS 7.10 install paths use `sudo mformat` to stage
pre-install files on the install floppy. The Linux release's `install.sh`
already sets up a NOPASSWD entry for the dosforge user covering qemu-nbd,
mount, parted, etc. If you installed via `pip` only (without
`install.sh`), add a `mformat` NOPASSWD line yourself:

```bash
sudo bash -c 'echo "%wheel ALL=(root) NOPASSWD: /usr/bin/mformat" \
  > /etc/sudoers.d/dosforge-mformat && chmod 0440 /etc/sudoers.d/dosforge-mformat \
  && visudo -c -f /etc/sudoers.d/dosforge-mformat'
```

(Replace `%wheel` with your local sudo group if your distro uses `sudo`
instead.)

## Upgrading from v0.5.x

```bash
# From the bundle:
cd dosforge-0.6.0-linux
. .venv/bin/activate
pip install --upgrade ./dosforge-0.6.0-py3-none-any.whl
dosforge init-assets       # safe to run; skips existing readmes

# Or upgrade directly from the wheel URL:
pip install --upgrade \
  https://github.com/flynnsbit/dosforge/releases/download/linux-v0.6.0/dosforge-0.6.0-py3-none-any.whl
```

## Quick install (fresh)

```bash
# 1. Install the Python package
python3 -m venv .venv
. .venv/bin/activate
pip install ./dosforge-0.6.0-py3-none-any.whl

# 2. Install system tools (Debian / Ubuntu)
sudo apt install qemu-system-x86 qemu-utils nbd-client \
    mtools p7zip-full innoextract python3-tk

# 3. Bootstrap the asset directory
dosforge init-assets

# 4. Verify
dosforge where-assets
dosforge --help
```

After step 3 you can run dosforge from any directory and it will find
your install media at `~/.local/share/dosforge/dosassets/<mode>/`.

Full per-distro instructions are in `INSTALL.md` inside the
`-linux.tar.gz` bundle. Build-flow reference is at
[`docs/flow.md`](https://github.com/flynnsbit/dosforge/blob/linux-v0.6.0/docs/flow.md).
