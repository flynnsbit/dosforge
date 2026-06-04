"""Sync the wheel-bundled readme skeleton with the in-tree dosassets/.

The dosforge wheel ships a copy of each ``dosassets/<mode>/readme.txt``
inside ``src/dosforge/_skeleton/`` so ``dosforge init-assets`` can lay
down the same folder structure on a fresh Linux install. This script
keeps the mirror in lock-step with the source-of-truth ``dosassets/``
directory.

Run it whenever you add, remove, or edit a per-mode readme.txt. CI
should run it with ``--check`` to fail the build if the mirror drifts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "dosassets"
MIRROR = REPO_ROOT / "src" / "dosforge" / "_skeleton"
INIT_PY = MIRROR / "__init__.py"
INIT_PY_BODY = (
    '"""Skeleton readmes bundled into the wheel for ``dosforge init-assets``."""\n'
)


def _collect_source_readmes() -> dict[str, bytes]:
    """Return {mode: readme.txt bytes} for every mode dir with a readme."""
    if not SOURCE.is_dir():
        raise SystemExit(f"dosassets/ not found at {SOURCE}")
    readmes: dict[str, bytes] = {}
    for entry in sorted(SOURCE.iterdir()):
        if not entry.is_dir():
            continue
        readme = entry / "readme.txt"
        if readme.is_file():
            readmes[entry.name] = readme.read_bytes()
    return readmes


def _collect_mirror_readmes() -> dict[str, bytes]:
    if not MIRROR.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for entry in sorted(MIRROR.iterdir()):
        if not entry.is_dir():
            continue
        readme = entry / "readme.txt"
        if readme.is_file():
            out[entry.name] = readme.read_bytes()
    return out


def _diff(
    src: dict[str, bytes], dst: dict[str, bytes]
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, removed, modified) mode lists."""
    src_keys = set(src)
    dst_keys = set(dst)
    added = sorted(src_keys - dst_keys)
    removed = sorted(dst_keys - src_keys)
    modified = sorted(m for m in src_keys & dst_keys if src[m] != dst[m])
    return added, removed, modified


def _apply(src: dict[str, bytes]) -> None:
    MIRROR.mkdir(parents=True, exist_ok=True)
    INIT_PY.write_text(INIT_PY_BODY, encoding="utf-8")
    # Remove any stale mode dirs not in source.
    for entry in MIRROR.iterdir():
        if entry.name == "__init__.py":
            continue
        if entry.is_dir() and entry.name not in src:
            for child in entry.iterdir():
                child.unlink()
            entry.rmdir()
    for mode, data in src.items():
        mode_dir = MIRROR / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "readme.txt").write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the mirror is out of sync (no writes).",
    )
    args = ap.parse_args(argv)

    src = _collect_source_readmes()
    dst = _collect_mirror_readmes()
    added, removed, modified = _diff(src, dst)

    if not (added or removed or modified):
        print(f"Skeleton mirror is in sync ({len(src)} modes).")
        return 0

    print("Skeleton mirror is OUT OF SYNC:")
    for m in added:
        print(f"  + {m}")
    for m in removed:
        print(f"  - {m}")
    for m in modified:
        print(f"  ~ {m}")

    if args.check:
        print(
            "\nRun: python scripts/sync-asset-skeleton.py  (without --check)"
        )
        return 1

    _apply(src)
    print(
        f"\nMirror updated: +{len(added)} -{len(removed)} ~{len(modified)} "
        f"({len(src)} total modes)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
