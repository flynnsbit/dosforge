# dosforge v0.5.1 — Linux release (XDG-aware dosassets discovery)

Patch release on top of v0.5.0 that makes dosforge much friendlier for
pip-only Linux installs.

## What's new

- **XDG-compliant dosassets discovery.** dosforge now looks for install
  media in (resolution order, highest priority first):
  1. `$DOSFORGE_DOSASSETS_DIR` env var
  2. `$PWD/dosassets/` (bundle-extract case)
  3. `$XDG_DATA_HOME/dosforge/dosassets/`
     (defaults to `~/.local/share/dosforge/dosassets/`)
  4. `~/.dosforge/dosassets/`
  5. `/usr/local/share/dosforge/dosassets/`
  6. `/usr/share/dosforge/dosassets/`

  Previously only the cwd-relative fallback worked, which meant
  pip-installed users had to either always `cd` to a specific
  directory or set `DOSFORGE_DOSASSETS_DIR` manually.

- **New `dosforge where-assets` subcommand** prints the resolution
  order for the current host with `[FOUND]` / `[ missing ]` markers
  on each candidate path, plus a one-liner showing how to populate
  the recommended XDG location.

- **`INSTALL.md` rewritten** to explain the precedence and recommend
  `~/.local/share/dosforge/dosassets/` for users who installed only
  the wheel (no bundle extract).

## Same as v0.5.0

Everything from v0.5.0 — per-DOS authentic MBR via `FDISK /MBR`, ECHS
geometry handling, PC-DOS 7.1 FAT32 booting, GUI/TUI/CLI front ends —
ships unchanged.

## Quick install

```bash
# 1. Install the Python package
python3 -m venv .venv
. .venv/bin/activate
pip install ./dosforge-0.5.1-py3-none-any.whl

# 2. Install system tools (Debian/Ubuntu)
sudo apt install qemu-system-x86 qemu-utils nbd-client \
    mtools p7zip-full innoextract python3-tk

# 3. Bootstrap the asset directory in a stable location
mkdir -p ~/.local/share/dosforge
cp -r dosassets ~/.local/share/dosforge/

# 4. Verify
dosforge where-assets
dosforge --help
```

After step 3 you can run dosforge from any directory and it will find
your install media at `~/.local/share/dosforge/dosassets/<mode>/`.

Full per-distro instructions are in `INSTALL.md` inside the
`-linux.tar.gz` bundle.
