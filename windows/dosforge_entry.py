"""PyInstaller entry-point wrapper for the dosforge Windows bundle.

PyInstaller wants an actual ``.py`` file as its Analysis target; this
wrapper imports the real CLI ``main`` and runs it. We also resolve
``DOSFORGE_VENDOR_DIR`` at startup so the WindowsBackend can find
bundled binaries regardless of the working directory the user invokes
``dosforge.exe`` from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_vendor_dir() -> None:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        # PyInstaller onedir places datafiles under ``_internal/`` next
        # to the exe; older releases used the exe's directory directly.
        for candidate in (
            base / "_internal" / "vendor" / "windows" / "bin",
            base / "vendor" / "windows" / "bin",
        ):
            if candidate.is_dir():
                os.environ.setdefault("DOSFORGE_VENDOR_DIR", str(candidate))
                return


def main() -> int:
    _set_vendor_dir()
    from dosforge.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
