"""PyInstaller entry-point wrapper for the dosforge Windows bundle.

PyInstaller wants an actual ``.py`` file as its Analysis target; this
wrapper imports the real CLI ``main`` and runs it. We also resolve
``DOSFORGE_VENDOR_DIR`` and ``DOSFORGE_DOSASSETS_DIR`` at startup so
the WindowsBackend and path helpers can find bundled binaries and DOS
assets regardless of the working directory the user invokes
``dosforge.exe`` from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_bundle_dirs() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(sys.executable).resolve().parent

    # Vendor binaries (QEMU, mtools).  The structured-lite layout puts
    # vendor/ adjacent to dosforge.exe; the full onedir layout keeps it
    # inside _internal/.  The entry-point's setdefault means a user-set
    # DOSFORGE_VENDOR_DIR is honoured over the auto-detected path.
    for candidate in (
        base / "_internal" / "vendor" / "windows" / "bin",
        base / "vendor" / "windows" / "bin",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_VENDOR_DIR", str(candidate))
            break

    # DOS assets.  The structured-lite layout moves dosassets/ out of
    # _internal/ so users can manage them alongside dosforge.exe.  The
    # full onedir layout keeps them inside _internal/.
    for candidate in (
        base / "dosassets",
        base / "_internal" / "dosassets",
    ):
        if candidate.is_dir():
            os.environ.setdefault("DOSFORGE_DOSASSETS_DIR", str(candidate))
            break


def main() -> int:
    _set_bundle_dirs()
    from dosforge.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
