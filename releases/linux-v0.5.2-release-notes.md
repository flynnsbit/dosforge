# dosforge v0.5.2 — Linux release (auto-hydrate dosassets/ skeleton)

Patch release on top of v0.5.1 that closes the last UX gap between pip-only
Linux installs and the Windows bundle: a single command now lays down the
per-mode `dosassets/` folder tree so you know exactly where to drop install
media.

## What's new

- **New `dosforge init-assets` subcommand.** Materializes the per-mode
  folder + `readme.txt` skeleton at `$XDG_DATA_HOME/dosforge/dosassets/`
  (defaults to `~/.local/share/dosforge/dosassets/`). 29 readmes ship
  inside the wheel itself, so it works from any working directory and
  doesn't require the release tarball.

  ```bash
  dosforge init-assets               # default: ~/.local/share/dosforge/dosassets/
  dosforge init-assets --target /opt/dosforge/dosassets
  dosforge init-assets --force       # refresh existing readmes
  ```

  Existing readmes are skipped by default; user-supplied install media
  sitting next to a readme is never touched.

- **CI smoke-tests `init-assets`** — the wheel build now installs into a
  scratch venv, runs `init-assets` into a tempdir, and verifies content
  + idempotency + `--force` semantics before publishing the release.

- **README + `INSTALL.md` updated** to recommend `dosforge init-assets`
  instead of the old `mkdir -p ~/.local/share/dosforge && cp -r dosassets …`
  two-step.

## Upgrading from v0.5.0 / v0.5.1

```bash
# From the bundle:
cd dosforge-0.5.2-linux
. .venv/bin/activate
pip install --upgrade ./dosforge-0.5.2-py3-none-any.whl
dosforge init-assets       # safe to run; skips existing readmes

# Or upgrade directly from the wheel URL:
pip install --upgrade \
  https://github.com/flynnsbit/dosforge/releases/download/linux-v0.5.2/dosforge-0.5.2-py3-none-any.whl
```

## Same as v0.5.0 / v0.5.1

Everything from the prior Linux releases ships unchanged: per-DOS
authentic MBR via `FDISK /MBR`, ECHS geometry handling, PC-DOS 7.1
FAT32 booting, GUI / TUI / CLI front ends, XDG-compliant dosassets
discovery.

## Quick install

```bash
# 1. Install the Python package
python3 -m venv .venv
. .venv/bin/activate
pip install ./dosforge-0.5.2-py3-none-any.whl

# 2. Install system tools (Debian / Ubuntu)
sudo apt install qemu-system-x86 qemu-utils nbd-client \
    mtools p7zip-full innoextract python3-tk

# 3. Bootstrap the asset directory — one command, no manual copy
dosforge init-assets

# 4. Verify
dosforge where-assets
dosforge --help
```

After step 3 you can run dosforge from any directory and it will find
your install media at `~/.local/share/dosforge/dosassets/<mode>/`.

Full per-distro instructions are in `INSTALL.md` inside the
`-linux.tar.gz` bundle.
