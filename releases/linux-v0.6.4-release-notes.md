# dosforge linux-v0.6.4 — companion to windows-v0.6.4

No functional changes for Linux users. This Linux release is published
in lock-step with `windows-v0.6.4`, which fixes the Windows bundle's
`dosassets\` layout so users can drop install media (notably the IBM
PC-DOS 2000 archive used for PC-DOS 7.1 utility hydration) into the
obvious top-level `dosforge\dosassets\<mode>\` folder.

## What changed

Windows-only:

- `windows/dosforge_entry.py` — Launcher only probes `<bundle>\dosassets\`,
  never `<bundle>\_internal\dosassets\`.
- `windows/dosforge.spec`, `windows/dosforge-cli.spec` — Post-build hook
  fails loudly if PyInstaller didn't stage `_internal\dosassets\` for
  the move-to-root step.
- `scripts/cli-smoke.ps1` — Updated to probe the new root-level path.

The Linux shape (wheel, sdist, source tarball, `init-assets` flow,
`$DOSFORGE_DOSASSETS_DIR` env var) is unchanged from `linux-v0.6.1`.

## Highlights since linux-v0.6.1 (carried via v0.6.2 / v0.6.3)

- **PC-DOS 7.1 SGTK fetcher in the desktop GUI** — same button + flow
  as the TUI (`fetch-pcdos71-btn` visible when boot mode is PCDOS71).
- **PC-DOS 2000 utility hydration** — FULL profile pcdos71 builds now
  merge EMM386 / POWER / DOSSHELL / DEFRAG / BACKUP / RESTORE / etc.
  from the IBM PC-DOS 2000 install media into `C:\DOS\`. SGTK wins on
  filename conflicts.
- **Create+format spinner** — TUI/GUI show a live animated indicator
  and elapsed-time counter while a long-running build is in progress.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install dosforge-0.6.4-py3-none-any.whl

# Materialize the per-mode dosassets/ skeleton in your user data dir
dosforge init-assets

# Or extract the linux tarball and run dosforge from inside it (uses
# the bundled dosassets/ next to the wheel).
```

See `INSTALL.md` in the tarball for the full system-deps one-liners
(Debian / Fedora / Arch).
