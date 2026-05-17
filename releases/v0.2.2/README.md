# dosforge 0.2.2 — release bundle

This folder is a self-contained, **source-free** installable bundle of
`dosforge` version **0.2.2**. It contains everything you need to
install and run the tool on a fresh Linux system.

## What's in this folder

| File / dir                                  | Purpose                                                                 |
|---------------------------------------------|-------------------------------------------------------------------------|
| `dosforge-0.2.2-py3-none-any.whl`     | Pure-Python wheel (preferred install artifact)                          |
| `dosforge-0.2.2.tar.gz`               | Source distribution (for building from source)                          |
| `install.sh`                                | One-shot installer: system deps + wheel + `dosassets/` + desktop entry  |
| `dosassets/`                                | DOS boot-asset tree (FreeDOS payload + per-mode `readme.txt`)           |
| `desktop/`                                  | Launcher wrapper, icon set, `.desktop` template (walker / app menu)     |
| `SHA256SUMS`                                | Integrity manifest for every file above                                 |
| `README.md`                                 | This file                                                               |

## Quick install (Arch or Ubuntu)

```bash
chmod +x install.sh
./install.sh
```

The installer:

1. Detects whether you're on **Arch** (or a derivative like CachyOS,
   EndeavourOS, Manjaro, Garuda) or **Ubuntu/Debian** (Mint, Pop!\_OS,
   elementary, Kali, Zorin, Raspbian).
2. Installs the system command-line tools `dosforge` needs:
   `qemu-img`, `qemu-nbd`, `qemu-system-i386`, `mtools` (mcopy / mformat
   / mattrib / mtype / mdir / mdel), `dosfstools`, `parted`,
   `util-linux`, `xdg-utils`, `sudo`.
3. Installs the bundled wheel into your Python environment via
   **pipx** (preferred) — falling back to `pip install --user` if
   pipx isn't available.
4. Stages the bundled `dosassets/` into
   `~/.local/share/dosforge/dosassets/` so the tool's bare-name
   boot-asset lookups (e.g. `--boot-assets-path msdos33`) work even
   when you're not inside the release directory.
5. Installs the **dosforge launcher integration** — a small
   `dosforge-launcher` wrapper to `~/.local/bin/`, the SVG + PNG
   icon set to `~/.local/share/icons/hicolor/`, and a `.desktop`
   entry to `~/.local/share/applications/` — so dosforge shows up
   in walker (Omarchy) or any other XDG-aware app menu with the
   forge / hammer-strike icon.

Pass `--system` to install dosforge system-wide (`pipx --global` or
sudo + PIPX_HOME=/opt). Pass `--no-dosassets` to skip step 4 if you're
managing your own dosassets/ tree. Pass `--no-desktop` to skip step 5
if you don't want the launcher integration.

## Manual install

If your distribution isn't Arch- or Debian-family, install these
system commands yourself (any modern Linux distribution will have
packages for them):

```
python3 (>= 3.11)
qemu-img / qemu-nbd / qemu-system-i386
mtools (mcopy, mformat, mattrib, mtype, mdir, mdel)
dosfstools (mkfs.fat)
parted (parted, partprobe)
util-linux (mount, umount)
coreutils (dd)
xdg-utils (xdg-open)
sudo
pipx (optional but recommended)
```

Then install the wheel:

```bash
pipx install ./dosforge-0.2.2-py3-none-any.whl
# or
python3 -m pip install --user ./dosforge-0.2.2-py3-none-any.whl
```

And (optionally) copy `dosassets/` to a convenient location:

```bash
mkdir -p ~/.local/share/dosforge
cp -r dosassets ~/.local/share/dosforge/
```

## Verifying the integrity of this release

```bash
sha256sum -c SHA256SUMS
```

## Running

Launch the Textual TUI:

```bash
dosforge
```

Or use the CLI directly:

```bash
dosforge create \
    --path ~/vhd/demo.vhd \
    --size 32M \
    --format fat16 \
    --boot-mode msdos33 \
    --boot-assets-path msdos33    # resolves to ./dosassets/msdos33/
```

## Project links

- Repository: <https://github.com/flynnsbit/dosforge>
- Issue tracker: <https://github.com/flynnsbit/dosforge/issues>

## License

Dosforge itself is MIT-licensed. The `dosassets/` tree bundles:

- **FreeDOS** (GPL v2 / BSD per component — see the upstream FreeDOS
  release).
- Per-version `readme.txt` placeholders for WinWorldPC-derived install
  media (no install media is shipped — drop your own copies into the
  matching subdir).
- Staging folders for the Microsoft-open-sourced MS-DOS releases (MIT
  per <https://github.com/microsoft/ms-dos>).
