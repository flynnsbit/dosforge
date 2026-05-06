"""CLI entrypoint for vhdmaker."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .app import VhdMakerApp
from .commands import CommandRunner
from .dependencies import assert_dependencies
from .disk import DiskManager
from .errors import DependencyError, ValidationError, VhdMakerError
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)
from .size import parse_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vhdmaker")
    subcommands = parser.add_subparsers(dest="command")

    subcommands.add_parser("tui", help="Launch the interactive TUI (default).")

    check_deps = subcommands.add_parser("check-deps", help="Check external command dependencies.")
    check_deps.add_argument(
        "--media-type",
        choices=[media.value for media in MediaType],
        default=MediaType.VHD.value,
        help="Media type to check dependencies for.",
    )
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
    subcommands.add_parser("sudo-check", help="Run sudo/privilege readiness diagnostics.")

    create = subcommands.add_parser("create", help="Create and format a VHD or floppy IMG.")
    create.add_argument("--path", required=True, help="Output image file path.")
    create.add_argument("--media-type", choices=[media.value for media in MediaType], default=MediaType.VHD.value)
    create.add_argument("--size", help="Static size (for example 512M or 1G). Required for VHD mode.")
    create.add_argument(
        "--format",
        dest="disk_format",
        choices=[fmt.value for fmt in DiskFormat],
        default=DiskFormat.FAT16.value,
        help="Filesystem format for VHD mode.",
    )
    create.add_argument(
        "--floppy-type",
        choices=[floppy.value for floppy in FloppyType],
        default=FloppyType.F1440K.value,
        help="Floppy geometry preset for IMG mode.",
    )
    create.add_argument(
        "--img-system-format",
        action="store_true",
        help="Install boot/system files into IMG when a DOS boot mode is selected.",
    )
    create.add_argument("--label", default=None, help="Optional FAT volume label.")
    create.add_argument("--overwrite", action="store_true", help="Overwrite existing image at --path.")
    create.add_argument("--boot-mode", choices=[mode.value for mode in BootMode], default=BootMode.NONE.value)
    create.add_argument(
        "--freedos-source",
        choices=[source.value for source in FreeDOSSource],
        default=FreeDOSSource.LOCAL.value,
    )
    create.add_argument("--boot-assets-path", default=None, help="Path to local boot assets dir or image.")
    create.add_argument("--freedos-download-url", default=None, help="Override FreeDOS auto-download URL.")
    create.add_argument(
        "--msdos-install-profile",
        choices=[profile.value for profile in MSDOSInstallProfile],
        default=MSDOSInstallProfile.MINIMAL.value,
        help="MS-DOS 7.1 install profile: minimal boot files or full C:\\DOS payload.",
    )
    create.add_argument(
        "--ibm-dos-version",
        choices=[version.value for version in IBMDOSVersion],
        default=IBMDOSVersion.DOS33.value,
        help="IBM PC 8088/V20 DOS version: dos33 (max 32MB) or dos50 (max ~504MB).",
    )

    mount = subcommands.add_parser("mount", help="Mount a disk image and track it in app state.")
    mount.add_argument("--path", required=True, help="Path to .vhd/.img/.ima file to mount.")
    mount.add_argument("--open", action="store_true", help="Open mounted path in GUI file manager.")

    unmount = subcommands.add_parser("unmount", help="Unmount a previously tracked mount point.")
    unmount.add_argument("--mount-point", required=True, help="Mount path to unmount.")

    subcommands.add_parser("list-mounts", help="List tracked active mounts.")
    return parser


def ensure_startup_sudo_auth(runner: CommandRunner | None = None) -> None:
    try:
        result = subprocess.run(
            ["sudo", "--preserve-env=HOME,PATH", "-v"],
            check=False,
        )
    except FileNotFoundError as exc:
        raise DependencyError("Missing external command: sudo") from exc
    if result.returncode != 0:
        raise ValidationError(
            "Sudo authentication failed before launching the TUI. "
            "Verify your sudo password/PAM setup, then retry."
        )

    command_runner = runner or CommandRunner()
    probe = command_runner.run(["true"], sudo=True, check=False)
    if probe.returncode == 0:
        return

    detail = probe.stderr.strip() or probe.stdout.strip() or f"exit code {probe.returncode}"
    raise ValidationError(
        "Sudo credentials were accepted, but non-interactive sudo is not available for runtime disk operations. "
        "This host may require a password for every sudo command. Configure sudo credential caching or scoped "
        "NOPASSWD rules, then retry.\n"
        f"Details: {detail}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command in (None, "tui"):
            ensure_startup_sudo_auth()
            VhdMakerApp().run()
            return 0

        if args.command == "check-deps":
            assert_dependencies(
                media_type=MediaType(args.media_type),
                boot_mode=BootMode(args.boot_mode),
                freedos_source=FreeDOSSource(args.freedos_source),
            )
            print("All required dependencies are available.")
            return 0

        manager = DiskManager()

        if args.command == "sudo-check":
            ok, summary = manager.privilege_diagnostics_summary()
            print(summary)
            return 0 if ok else 1

        if args.command == "create":
            media_type = MediaType(args.media_type)
            floppy_type = FloppyType(args.floppy_type)
            disk_format = DiskFormat(args.disk_format) if media_type is MediaType.VHD else DiskFormat.FAT16
            if media_type is MediaType.VHD:
                if not args.size:
                    raise ValidationError("--size is required when --media-type is vhd.")
                size_bytes = parse_size(args.size)
            else:
                size_bytes = parse_size(args.size) if args.size else floppy_type.size_bytes
            request = CreateRequest(
                path=Path(args.path).expanduser(),
                size_bytes=size_bytes,
                disk_format=disk_format,
                media_type=media_type,
                floppy_type=floppy_type,
                img_system_format=bool(args.img_system_format),
                label=args.label,
                overwrite=bool(args.overwrite),
                boot_mode=BootMode(args.boot_mode),
                freedos_source=FreeDOSSource(args.freedos_source),
                boot_assets_path=Path(args.boot_assets_path).expanduser() if args.boot_assets_path else None,
                freedos_download_url=args.freedos_download_url,
                msdos_install_profile=MSDOSInstallProfile(args.msdos_install_profile),
                ibm_dos_version=IBMDOSVersion(args.ibm_dos_version),
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
