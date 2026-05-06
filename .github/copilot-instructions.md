# Copilot instructions for `vhdmaker`

## Build, test, and lint commands

```bash
# Install in editable mode (includes test deps)
python -m pip install -e .[dev]

# Run the app (default command launches the TUI)
vhdmaker

# Full test suite
pytest -q

# Run a single test
pytest tests/test_disk_validation.py::test_validate_accepts_img_system_format_with_boot_mode -q

# Optional: install local pre-push hook for trailer cleanup
./scripts/install-githooks.sh
```

Linting: there is currently no dedicated lint command/tool configured in this repository.

## High-level architecture

- **Entry points (`src/vhdmaker/cli.py`)**
  - `vhdmaker` CLI builds a `CreateRequest` and delegates all disk operations to `DiskManager`.
  - Running `vhdmaker` (or `vhdmaker tui`) performs startup sudo auth (`sudo -v`) before launching Textual UI.

- **UI layer (`src/vhdmaker/app.py`)**
  - `VhdMakerApp` owns the interactive workflow and dynamic form behavior.
  - The create form is driven by `media-type` + `boot-mode`; `_sync_create_form_visibility()` is the central visibility gate.
  - Directory tree selection is dual-purpose: image selection and boot-assets directory selection.

- **Orchestration layer (`src/vhdmaker/disk.py`)**
  - `DiskManager.create_and_prepare()` is the main workflow split:
    - **VHD**: fixed VPC image creation -> NBD attach -> partition/format -> optional boot install.
    - **IMG**: fixed floppy size + FAT12 format -> optional system-format install.
  - FAT16 VHD boot path patches BPB geometry from VHD footer CHS.
  - Mount path split:
    - VHD via `qemu-nbd` + partition mount.
    - IMG via loop-mounted file.
  - Active mounts are persisted through `StateStore`.

- **Boot subsystem (`src/vhdmaker/boot.py`)**
  - `BootAssetResolver` resolves boot assets per boot mode (FreeDOS/MS-DOS 7.1/IBM DOS/PC-DOS/Compaq) from either directories or install images.
  - Resolved/extracted assets are cached under `~/.local/state/vhdmaker/cache/boot-assets`.
  - `BootInstaller` writes MBR/VBR boot code with `dd`, stages DOS system files via `mcopy`, and sets system/hidden attributes with `mattrib`.
  - DOS 3.3 IMG system-format from install media uses `DISK01.IMG` as base media when possible (preserves original geometry/layout).

- **State and paths (`src/vhdmaker/state.py`, `src/vhdmaker/paths.py`)**
  - Persistent state file: `~/.local/state/vhdmaker/state.json`
  - Mount root: `~/.local/state/vhdmaker/mounts`

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
