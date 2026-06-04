# dosforge v0.5.0 — Linux release

First official Linux release of the v0.5.0 series. Same code as the
Windows bundles (commit `c821bdc` on `main`), just packaged for Linux
the Linux way: a pip-installable wheel plus a self-contained tarball
with install instructions.

## What's in the release

| Artifact | What it is | Use when |
|----------|------------|----------|
| `dosforge-0.5.0-py3-none-any.whl` | Pure-Python wheel | `pip install` into a venv |
| `dosforge-0.5.0.tar.gz` | sdist (source dist) | `pip install dosforge.tar.gz` or for downstream packaging |
| `dosforge-0.5.0-linux.tar.gz` | Self-contained bundle: wheel + sdist + `dosassets/` skeleton + `scripts/` + `INSTALL.md` | One-stop download for new users |

## Quick install

```bash
# 1. Install the Python package
python3 -m venv .venv
. .venv/bin/activate
pip install ./dosforge-0.5.0-py3-none-any.whl

# 2. Install the system tools dosforge shells out to
#    (Debian/Ubuntu example)
sudo apt install qemu-system-x86 qemu-utils nbd-client \
    mtools p7zip-full innoextract python3-tk

# 3. Run
dosforge                # help + examples
dosforge tui            # interactive TUI
dosforge gui            # desktop GUI (X11 / Wayland)
dosforge create --media-type vhd --path test.vhd \
    --size 1G --format fat32 --boot-mode pcdos71
```

The full per-distro install instructions (Debian/Ubuntu, Fedora/RHEL,
Arch) are in `INSTALL.md` inside the `-linux.tar.gz` bundle.

## What's in v0.5.0

This release captures every commit in the `feature/dos-authenticity`
work merged into `main`:

### Boot authenticity
- **Per-DOS authentic MBR**: every DOS 5+ boot mode now writes its
  own OS's MBR boot code via `FDISK /MBR` during the in-QEMU install
  pass (msdos5, msdos622, pcdos7, msdos71, pcdos71 via `FDISK32 /MBR`).
  No more cross-DOS MBR borrowing.
- **ECHS bit-shift translation** applied to MBR partition table CHS
  entries and the FAT32 BPB heads/spt for drives >504 MB. Makes
  VBRs that do CHS reads land on the right sectors regardless of
  BIOS translation mode (CHS / ECHS / LBA).
- **IBM PC-DOS 7.1 (FAT32)** is now fully functional: a 1 GB FAT32
  bootable VHD boots cleanly in 86Box. Authentic IBM kernel, MBR,
  VBR — byte-equivalent to a real install from SGTK 1.3.07 media.
- `scripts/fetch-pcdos71-assets.py` downloads and verifies the
  official IBM ServerGuide Scripting Toolkit installer from the
  Internet Archive mirror (IBM no longer hosts it). Per-file
  SHA-256 verification against community-published reference hashes.

### dosassets folder skeleton
- Every supported DOS mode ships a `dosassets/<mode>/readme.txt`
  explaining what install media files to drop in. CI verifies the
  folder skeleton stays complete.

### TUI / GUI / CLI front ends
- New tkinter + Sun Valley GUI (`dosforge gui`) — also works on
  Linux with X11/Wayland + Tk installed.
- Refreshed Textual TUI (`dosforge tui`).
- CLI no-args prints help with worked examples for VHD + floppy
  builds across every common DOS mode.

### Subprocess + DOSBox-X polish
- Subprocess calls no longer pop console windows during a build.
- GUI status bar gained a live log panel that streams backend
  `print()` output line-by-line during operations.

## Linux-specific notes

- All install-pipeline work runs inside QEMU on Linux just as it
  does on Windows — same FDISK /MBR, same authentic BPB. The only
  difference is the host-side disk-prep phase uses qemu-nbd
  (Linux's kernel NBD) instead of mtools' `@@offset` syntax.
- The GUI requires `python3-tk` (Debian/Ubuntu) or equivalent.
- Native Linux integration tests (`native_linux`, `native_boot`,
  `native_86box` pytest markers) are opt-in and require real
  privileged mount + emulator setups — see `pyproject.toml`.

## Source

Built from commit
[`c821bdc`](https://github.com/flynnsbit/dosforge/commit/c821bdc)
on `main`.
