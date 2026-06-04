"""PyInstaller entry-point wrapper for the dosforge Windows bundle.

A single entry script powers BOTH bundled launchers — ``dosforge.exe``
(CLI-only) and ``dosforge-gui.exe`` (windowed GUI). The choice is made
at runtime from the EXE's filename so the two launchers can share one
``_internal/`` Python runtime without duplicating dependency DLLs.

* ``dosforge.exe``      -> :func:`dosforge.cli.cli_only_main`
* ``dosforge-gui.exe``  -> :func:`dosforge.cli.gui_only_main`

A symlink/rename of either EXE will still dispatch correctly based on
the new name. Anything that doesn't end in ``-gui`` is treated as CLI.
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

    # Vendor binaries (QEMU, mtools). The structured-lite layout puts
    # vendor/ adjacent to the EXE; the full onedir layout keeps it inside
    # _internal/.
    for candidate in (
        base / "_internal" / "vendor" / "windows" / "bin",
        base / "vendor" / "windows" / "bin",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_VENDOR_DIR", str(candidate))
            break

    # DOS assets.
    for candidate in (
        base / "dosassets",
        base / "_internal" / "dosassets",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_DOSASSETS_DIR", str(candidate))
            break


def main() -> int:
    _set_bundle_dirs()
    exe_name = Path(sys.executable).stem.lower()
    if exe_name.endswith("-gui"):
        from dosforge.cli import gui_only_main
        return gui_only_main()
    from dosforge.cli import cli_only_main
    return cli_only_main()


if __name__ == "__main__":
    raise SystemExit(main())
