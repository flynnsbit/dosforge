"""CI guard: every dosassets/<mode>/ folder must ship a readme.txt.

Run as part of the release workflow before PyInstaller. Exits non-zero
listing any folders that lack a readme so the lite bundle never ships
an empty directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

DOSASSETS = Path(__file__).resolve().parent.parent / "dosassets"


def main() -> int:
    if not DOSASSETS.is_dir():
        print(f"FAIL: dosassets/ not found at {DOSASSETS}", file=sys.stderr)
        return 2
    missing: list[str] = []
    for entry in sorted(DOSASSETS.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "readme.txt").is_file():
            missing.append(entry.name)
    if missing:
        print(
            "FAIL: the following dosassets/<mode>/ folders have no readme.txt:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - dosassets/{name}/", file=sys.stderr)
        print(
            "\nRun scripts/write-dosassets-readmes.py to generate stubs, "
            "or add a hand-written readme.txt for each folder.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: all {sum(1 for p in DOSASSETS.iterdir() if p.is_dir())} dosassets/ folders have a readme.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
