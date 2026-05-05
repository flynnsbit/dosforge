"""CLI entrypoint for vhdmaker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .app import VhdMakerApp
from .dependencies import assert_dependencies
from .disk import DiskManager
from .errors import VhdMakerError
from .models import BootMode, CreateRequest, DiskFormat, FreeDOSSource
from .size import parse_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vhdmaker")
    subcommands = parser.add_subparsers(dest="command")

    subcommands.add_parser("tui", help="Launch the interactive TUI (default).")

    check_deps = subcommands.add_parser("check-deps", help="Check external command dependencies.")
    check_deps.add_argument(
        "--boot-mode",
        choices=[mode.value for mode in BootMode],
        default=BootMode.NONE.value,
        help="Check dependencies for the given boot mode.",
    )
    check_deps.add_argument(
        "--freedos-source",
        choices=[source.value for source in FreeDOSSource],
        default=FreeDOSSource.LOCAL.value,
        help="FreeDOS source mode (only relevant for freedos boot mode).",
    )

    create = subcommands.add_parser("create", help="Create and format a fixed-size VHD.")
    create.add_argument("--path", required=True, help="Output VHD file path.")
    create.add_argument("--size", required=True, help="Static size (for example 512M or 1G).")
    create.add_argument("--format", dest="disk_format", choices=[fmt.value for fmt in DiskFormat], required=True)
    create.add_argument("--label", default=None, help="Optional FAT volume label.")
    create.add_argument("--overwrite", action="store_true", help="Overwrite existing VHD at --path.")
    create.add_argument("--boot-mode", choices=[mode.value for mode in BootMode], default=BootMode.NONE.value)
    create.add_argument(
        "--freedos-source",
        choices=[source.value for source in FreeDOSSource],
        default=FreeDOSSource.LOCAL.value,
    )
    create.add_argument("--boot-assets-path", default=None, help="Path to local boot assets dir or image.")
    create.add_argument("--freedos-download-url", default=None, help="Override FreeDOS auto-download URL.")

    mount = subcommands.add_parser("mount", help="Mount a VHD and track it in app state.")
    mount.add_argument("--path", required=True, help="Path to .vhd file to mount.")
    mount.add_argument("--open", action="store_true", help="Open mounted path in GUI file manager.")

    unmount = subcommands.add_parser("unmount", help="Unmount a previously tracked mount point.")
    unmount.add_argument("--mount-point", required=True, help="Mount path to unmount.")

    subcommands.add_parser("list-mounts", help="List tracked active mounts.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "tui"):
        VhdMakerApp().run()
        return 0

    if args.command == "check-deps":
        assert_dependencies(
            boot_mode=BootMode(args.boot_mode),
            freedos_source=FreeDOSSource(args.freedos_source),
        )
        print("All required dependencies are available.")
        return 0

    manager = DiskManager()

    try:
        if args.command == "create":
            request = CreateRequest(
                path=Path(args.path).expanduser(),
                size_bytes=parse_size(args.size),
                disk_format=DiskFormat(args.disk_format),
                label=args.label,
                overwrite=bool(args.overwrite),
                boot_mode=BootMode(args.boot_mode),
                freedos_source=FreeDOSSource(args.freedos_source),
                boot_assets_path=Path(args.boot_assets_path).expanduser() if args.boot_assets_path else None,
                freedos_download_url=args.freedos_download_url,
            )
            manager.create_and_prepare(request)
            print(f"Created and prepared {request.path.expanduser().resolve()}")
            return 0

        if args.command == "mount":
            record = manager.mount_vhd(Path(args.path))
            print(f"Mounted {record.vhd_path} to {record.mount_point} via {record.nbd_device}")
            if args.open:
                manager.open_in_files(record.mount_point)
                print(f"Opened in file manager: {record.mount_point}")
            return 0

        if args.command == "unmount":
            record = manager.unmount(Path(args.mount_point))
            print(f"Unmounted {record.mount_point} and disconnected {record.nbd_device}")
            return 0

        if args.command == "list-mounts":
            mounts = manager.list_mounts()
            if not mounts:
                print("No active mounts tracked.")
                return 0
            for mount in mounts:
                print(f"{mount.mount_point}\t{mount.vhd_path}\t{mount.nbd_device}")
            return 0
    except VhdMakerError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help(sys.stderr)
    return 2
