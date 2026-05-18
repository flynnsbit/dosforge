# Copilot instructions for `dosforge`

## Build and run commands

```bash
# Install in editable mode (includes test deps)
python -m pip install -e .[dev]

# Run the app (default command launches the TUI)
dosforge

# Optional: install local pre-push hook for trailer cleanup
./scripts/install-githooks.sh
```

Linting: there is currently no dedicated lint command/tool configured in this repository.

> **Note on tests:** A `pytest -q` suite exists under `tests/` (including
> `native_linux`, `native_boot`, `native_86box` markers configured in
> `pyproject.toml`), but **do not run it as part of routine work** — it is
> slow, partly hangs in this environment, and not informative for the current
> debugging cycle. Validate changes by inspecting code and built artifacts
> directly (e.g. footer/BPB hex dumps, 86Box boot probes) rather than via the
> test suite, unless the user explicitly asks for a test run.

## Push workflow (REQUIRED)

**Always run `~/Projects/shared-scripts/strip-copilot-coauthor.sh` before pushing to GitHub.**
This repository must never publish the `Co-authored-by: Copilot ...`
trailer on `origin`. The script lives in the shared
`~/Projects/shared-scripts/` folder (override with the `SHARED_SCRIPTS`
env var). The expected order before any `git push` is:

```bash
# Verify no trailer survives on the commits about to be pushed
~/Projects/shared-scripts/strip-copilot-coauthor.sh --range origin/main..HEAD --dry-run

# If the dry-run reports any trailers, strip them in place
~/Projects/shared-scripts/strip-copilot-coauthor.sh --range origin/main..HEAD --apply

# Then push
git push origin main
```

The local pre-push hook (`./scripts/install-githooks.sh`) runs the strip
script automatically, but the rule applies whether or not the hook is
installed: **never push without the strip step.**

## High-level architecture

- **Entry points (`src/dosforge/cli.py`)**
  - `dosforge` CLI builds a `CreateRequest` and delegates all disk operations to `DiskManager`.
  - Running `dosforge` (or `dosforge tui`) performs startup sudo auth (`sudo -v`) before launching Textual UI.

- **UI layer (`src/dosforge/app.py`)**
  - `DosForgeApp` owns the interactive workflow and dynamic form behavior.
  - The create form is driven by `media-type` + `boot-mode`; `_sync_create_form_visibility()` is the central visibility gate.
  - Directory tree selection is dual-purpose: image selection and boot-assets directory selection.

- **Orchestration layer (`src/dosforge/disk.py`)**
  - `DiskManager.create_and_prepare()` is the main workflow split:
    - **VHD**: fixed VPC image creation -> NBD attach -> partition/format -> optional boot install.
    - **IMG**: fixed floppy size + FAT12 format -> optional system-format install.
  - FAT16 VHD boot path patches BPB geometry from VHD footer CHS.
  - Mount path split:
    - VHD via `qemu-nbd` + partition mount.
    - IMG via loop-mounted file.
  - Active mounts are persisted through `StateStore`.

- **Boot subsystem (`src/dosforge/boot.py`)**
  - `BootAssetResolver` resolves boot assets per boot mode (FreeDOS/MS-DOS 7.1/IBM DOS/PC-DOS/Compaq) from either directories or install images.
  - Resolved/extracted assets are cached under `~/.local/state/dosforge/cache/boot-assets`.
  - `BootInstaller` writes MBR/VBR boot code with `dd`, stages DOS system files via `mcopy`, and sets system/hidden attributes with `mattrib`.
  - DOS 3.3 IMG system-format uses installer-derived boot assets and stages only core system files; floppy geometry is aligned to source install media size.

- **State and paths (`src/dosforge/state.py`, `src/dosforge/paths.py`)**
  - Persistent state file: `~/.local/state/dosforge/state.json`
  - Mount root: `~/.local/state/dosforge/mounts`

## Key repository conventions

- Use `CreateRequest` + enums from `models.py` as the contract between CLI, TUI, and backend logic. Avoid introducing raw string switches in new code paths.
- Privileged commands should go through `CommandRunner.run(..., sudo=True)`, which uses non-interactive sudo (`sudo -n --preserve-env=HOME,PATH`). Keep interactive sudo prompts in startup auth only (`ensure_startup_sudo_auth`).
- Keep validation in `DiskManager._validate_create_request()` and size checks in `size.py`; errors should raise `ValidationError` with actionable messages.
- Legacy DOS asset discovery is case-insensitive and supports both system-file sets:
  - `IO.SYS` + `MSDOS.SYS` + `COMMAND.COM`
  - `IBMBIO.COM` + `IBMDOS.COM` + `COMMAND.COM`
- FreeDOS startup normalization is intentionally boot-mode-specific (applied for FreeDOS in `BootInstaller._prepare_source_file`); do not apply those rewrites to MS-DOS/IBM DOS flows.
- Tests rely heavily on `FakeRunner`/monkeypatching rather than real disk operations; follow this pattern for new tests around disk/boot logic.
- If you use local git hooks, this repo’s optional hook setup is `scripts/install-githooks.sh` (it wires `.githooks/pre-push` and trailer cleanup script).
