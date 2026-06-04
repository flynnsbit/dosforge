"""PyInstaller entry-point wrapper for the dosforge Windows bundles.

A single entry script powers the bundled launchers:

* ``dosforge-gui.exe``  -> :func:`dosforge.cli.gui_only_main`
* ``dosforge.exe``      -> :func:`dosforge.cli.full_console_main` if the
                           textual TUI is bundled (full bundle), or
                           :func:`dosforge.cli.cli_only_main` if it isn't
                           (slim CLI-only bundle).

The full bundle therefore exposes the TUI, the GUI and every CLI verb
from a single console launcher (``dosforge tui`` / ``dosforge gui`` /
``dosforge create ...``). The CLI-only bundle has no TUI/GUI imports at
all and shows the help-with-examples output when run with no arguments.

A symlink/rename of either EXE will still dispatch correctly based on
the new name. Anything that doesn't end in ``-gui`` is treated as the
console launcher.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_bundle_dirs() -> None:
    """Point dosforge at the QEMU/mtools binaries shipped alongside the EXE."""
    if not getattr(sys, "frozen", False):
        return
    base = Path(sys.executable).resolve().parent

    for candidate in (
        base / "_internal" / "vendor" / "windows" / "bin",
        base / "vendor" / "windows" / "bin",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_VENDOR_DIR", str(candidate))
            break

    for candidate in (
        base / "dosassets",
        base / "_internal" / "dosassets",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_DOSASSETS_DIR", str(candidate))
            break


def _tui_bundled() -> bool:
    """Return True if the textual TUI is importable in this bundle."""
    try:
        import textual  # noqa: F401
    except Exception:
        return False
    return True


def main() -> int:
    _set_bundle_dirs()
    exe_name = Path(sys.executable).stem.lower()
    if exe_name.endswith("-gui"):
        from dosforge.cli import gui_only_main
        return gui_only_main()
    if _tui_bundled():
        from dosforge.cli import full_console_main
        return full_console_main()
    from dosforge.cli import cli_only_main
    return cli_only_main()


if __name__ == "__main__":
    raise SystemExit(main())
