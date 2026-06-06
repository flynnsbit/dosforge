"""Populate the user's PC-DOS 7.1 dosassets directory from the IBM SGTK.

Thin wrapper around :func:`dosforge.pcdos71_fetch.fetch_pcdos71_assets`.
Use this script when you don't want to invoke the dosforge CLI
(e.g. in CI or from a one-off cron job). End users should prefer:

    dosforge fetch-pcdos71-assets

which calls the same library function and prints the same output.

Usage::

    python scripts/fetch-pcdos71-assets.py [--keep-extract] [--force] [--target DIR]

Requirements: 7-Zip installed at one of the standard Windows paths
(or set ``DOSFORGE_SEVENZIP_EXE``); ``requests`` is not required.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this script directly from a checkout without `pip install -e`.
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dosforge.errors import DependencyError, ValidationError  # noqa: E402
from dosforge.pcdos71_fetch import (  # noqa: E402
    EXPECTED_SHA256,
    default_cache_dir,
    default_target_dir,
    fetch_pcdos71_assets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if the archive cache looks fresh.",
    )
    parser.add_argument(
        "--keep-extract",
        action="store_true",
        help="Leave the SGTK extraction in the cache directory "
        "(default: delete after staging).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help=(
            "Override the staging directory. Defaults to the user-scope "
            "dosassets/pcdos71 location (see 'dosforge where-assets')."
        ),
    )
    args = parser.parse_args(argv)

    target = args.target if args.target is not None else default_target_dir()
    print(f"Target: {target}")
    print(f"Cache:  {default_cache_dir()}")

    try:
        result = fetch_pcdos71_assets(
            target_dir=args.target,
            force=args.force,
            keep_extract=args.keep_extract,
            progress=lambda line: print(line),
        )
    except DependencyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\n== Summary ==")
    print(f"  DOS files staged:    {result.staged_count}/{result.total_count}")
    if result.missing:
        print("  MISSING (not in SGTK extract):")
        for name in result.missing:
            print(f"    - {name}")
    if result.vfd_filename is None:
        print(
            "  NO pre-built bootable VFD found in the SGTK. The toolkit's\n"
            "  manual notes 'bootable disks are created using the included\n"
            "  tool scripts.' You have two options:\n"
            "    (a) Run the SGTK's MAKEDISK script under DOSBox-X to\n"
            "        produce a bootable PC-DOS 7.1 floppy. See dosforge's\n"
            "        _pcdos7_loaddskf.py for the analogous DOSBox-X-driven\n"
            "        approach used for PC-DOS 7.0.\n"
            "    (b) Apply the github.com/Kreeblah/pcdos71-patch batch file\n"
            "        to dosassets/pcdos2000/disk01.img (after mounting it\n"
            "        in DOSBox-X) and copy the resulting patched disk\n"
            "        here as install.img.\n"
            "  pcdos71_profile won't accept the target dir until a\n"
            "  bootable VFD is in place."
        )
    else:
        print(f"  Install floppy:      {result.vfd_filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
