# vhdmaker

`vhdmaker` is a DOS-focused image utility for Linux (Omarchy-friendly) with both a Textual TUI and CLI.

It can create, mount, browse, and unmount:

- fixed-size **VHD** images (FAT16/FAT32)
- floppy **IMG/IMA** images (FAT12)

with optional boot/system file staging for FreeDOS and legacy MS-DOS families.

## Highlights

- Dynamic TUI create flow with top-level **Media type** selector (**VHD** default, **IMG** optional)
- Progressive disclosure UI (only relevant options are shown)
- Bootable/system-format support for:
  - FreeDOS
  - MS-DOS 7.1
  - IBM DOS 3.3 / 5.0
  - PC-DOS
  - Compaq DOS 3.31
- Automatic DOS boot-template extraction from install images when possible
- Mount + open in file manager from TUI and CLI (`.vhd`, `.img`, `.ima`)

## Supported image modes

| Media | Format | Size model | Boot support |
|---|---|---|---|
| VHD | FAT16 / FAT32 | Fixed bytes (for example `512M`) | FreeDOS, MS-DOS 7.1, IBM DOS, PC-DOS, Compaq DOS |
| IMG/IMA | FAT12 | Fixed floppy presets | FreeDOS, MS-DOS 7.1, IBM DOS, PC-DOS, Compaq DOS (system-format toggle) |

Floppy presets: `160K`, `180K`, `320K`, `360K`, `720K`, `1.2M`, `1.44M`.

## Requirements

Base runtime:

- `mkfs.fat`
- `mount`, `umount`
- `sudo`
- `xdg-open`

VHD runtime:

- `qemu-img`
- `qemu-nbd`
- `parted`
- `partprobe`
- `modprobe` (kmod)

Boot prep:

- `dd`
- `mcopy`
- `mattrib`
- syslinux MBR binary (`/usr/lib/syslinux/bios/mbr.bin` or distro equivalent; VHD hard-disk boot mode)

## Install

```bash
python -m pip install -e .
```

## Run

```bash
vhdmaker
```

`vhdmaker` performs startup sudo auth for TUI (`sudo -v`) so credential prompts happen up front.

## TUI usage

1. Launch `vhdmaker`
2. In **Create disk image**:
   - choose **Media type** (`VHD` or `IMG`)
   - set path / size or floppy preset
   - optionally enable boot/system mode and provide DOS assets
3. Click **Create + format ...**
4. Select image in browser and click **Mount selected image**
5. Image opens in GUI file manager automatically

The file browser accepts `.vhd`, `.img`, `.ima`.

## CLI quick start

```bash
# Check dependencies (all VHD paths by default)
vhdmaker check-deps

# Check IMG-only dependencies
vhdmaker check-deps --media-type img

# Sudo/privilege diagnostics
vhdmaker sudo-check

# Create fixed-size FAT16 VHD
vhdmaker create --path ~/vhd/demo.vhd --size 512M --format fat16

# Create IBM DOS 5.0 VHD (8088/V20 profile)
vhdmaker create \
  --path ~/vhd/xt-dos5.vhd \
  --size 32M \
  --format fat16 \
  --boot-mode ibm8088 \
  --ibm-dos-version dos50 \
  --boot-assets-path ./dos5

# Create non-bootable 1.44M floppy IMG
vhdmaker create --path ~/floppy/tools.img --media-type img --floppy-type 1440k

# Create bootable 720K PC-DOS floppy IMG
vhdmaker create \
  --path ~/floppy/pcdos-boot.img \
  --media-type img \
  --floppy-type 720k \
  --img-system-format \
  --boot-mode pcdos \
  --boot-assets-path ./pcdos

# Mount + open
vhdmaker mount --path ~/vhd/demo.vhd --open
vhdmaker mount --path ~/floppy/tools.img --open

# Unmount
vhdmaker unmount --mount-point ~/.local/state/vhdmaker/mounts/demo-xxxxxxxx
```

## Boot assets (local media)

### FreeDOS

- Local dir or image with `KERNEL.SYS`, `COMMAND.COM`, boot template (`BOOTSECT_FAT16.BIN` / `BOOTSECT_FAT32.BIN`)
- Or auto-download path for FreeDOS image (`--freedos-source auto`)

### MS-DOS 7.1

Either:

1. direct files (`IO.SYS`, `MSDOS.SYS`, `COMMAND.COM`, `HIMEM.SYS`, `IFSHLP.SYS`, boot template), or
2. install disk images (`*.img` / `*.ima`) containing `DOS71_1S.PAK` (+ optional `DOS71_2S.PAK` for fuller payload)

Supports `minimal` and `full` install profiles.

### IBM DOS 3.3 / 5.0

- FAT16-only legacy profile
- `dos33` max 32 MiB
- `dos50` max ~504 MiB
- Assets can be direct files or floppy images

### PC-DOS / Compaq DOS 3.31

Resolver accepts either:

- `IO.SYS` + `MSDOS.SYS` + `COMMAND.COM`, or
- `IBMBIO.COM` + `IBMDOS.COM` + `COMMAND.COM`

plus `BOOTSECT_FAT16.BIN` (or `BOOTSECT.BIN`), or install images (`*.img` / `*.ima`).

Subfolder auto-detect:

- `pcdos/`
- `compaq331/`

## Compatibility guardrails

- FAT16 VHD: **16 MiB .. 2 GiB**
- FAT32 VHD: **64 MiB minimum** (up to 2 TiB)
- IMG mode uses fixed floppy capacities and FAT12 geometry
- Legacy DOS profiles enforce FAT16-compatible boot workflows

## State paths

- `~/.local/state/vhdmaker/state.json`
- Mount points under `~/.local/state/vhdmaker/mounts/`

List active mounts:

```bash
vhdmaker list-mounts
```

## Development

Run tests:

```bash
pytest -q
```

### Optional pre-push trailer cleanup hook

If you want a local pre-push hook that strips the Copilot co-author trailer from **HEAD** before push:

```bash
./scripts/install-githooks.sh
```

Manual dry-run check:

```bash
./scripts/strip-copilot-coauthor.sh --range HEAD --dry-run
```
