"""CLI entrypoint for dosforge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .app import DosForgeApp
from .commands import CommandRunner
from .dependencies import assert_dependencies
from .disk import DiskManager
from .errors import DependencyError, ValidationError, DosForgeError
from .models import (
    BIOSVendor,
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
    DEFAULT_MARTYPC_AT_FORMAT_SLUG,
    MARTYPC_AT_FORMATS,
    iter_bios_drive_types,
    lookup_martypc_at_format,
    parse_bios_drive_slug,
)
from .size import parse_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dosforge")
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
    create.add_argument(
        "--size",
        help="Static size (for example 512M or 1G). Optional for VHD when --custom-payload-path is provided.",
    )
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
    create.add_argument(
        "--boot-assets-path",
        default=None,
        help=(
            "Path to local boot assets dir, or a bare name like 'msdos33' "
            "(resolved as ./dosassets/msdos33/; see ./dosassets/readme.txt)."
        ),
    )
    create.add_argument("--freedos-download-url", default=None, help="Override FreeDOS auto-download URL.")
    create.add_argument(
        "--dos-install-profile",
        "--msdos-install-profile",
        dest="msdos_install_profile",
        choices=[profile.value for profile in MSDOSInstallProfile],
        default=MSDOSInstallProfile.MINIMAL.value,
        help="DOS install profile for bootable DOS modes: minimal boot files or full C:\\DOS-style payload.",
    )
    create.add_argument(
        "--ibm-dos-version",
        choices=[version.value for version in IBMDOSVersion],
        default=IBMDOSVersion.DOS33.value,
        help="IBM PC 8088/V20 DOS version: dos33 (max 32MB) or dos50 (max ~504MB).",
    )
    create.add_argument(
        "--custom-payload-path",
        default=None,
        help="Directory whose contents are copied into the created filesystem root.",
    )
    create.add_argument(
        "--machine-target",
        choices=[target.value for target in MachineTarget],
        default=MachineTarget.GENERIC.value,
        help=(
            "Emulator/machine profile constraining VHD geometry. "
            "'generic' uses canonical ATA 16h/63spt; "
            "'martypc-xebec' uses one of the 4 fixed Xebec MFM drive geometries."
        ),
    )
    create.add_argument(
        "--martypc-xebec-drive-type",
        choices=[dt.value for dt in MartyPCXebecDriveType],
        default=MartyPCXebecDriveType.TYPE2.value,
        help=(
            "MartyPC Xebec drive type when --machine-target=martypc-xebec: "
            "type1 (10 MiB 306x4x17, requires FAT12 — not yet supported), "
            "type16 (20 MiB 612x4x17), "
            "type2 (20 MiB 615x4x17), "
            "type13 (20 MiB 306x8x17)."
        ),
    )
    create.add_argument(
        "--martypc-at-drive-type",
        default=DEFAULT_MARTYPC_AT_FORMAT_SLUG,
        metavar="SLUG",
        help=(
            "MartyPC AT/XT-IDE drive type when --machine-target=martypc-xtide "
            "or martypc-jride. Slug format is 'at-<cyl>-<heads>-<spt>' (for "
            "example 'at-1024-16-63' for the 504 MiB entry). Run "
            "'dosforge list-martypc-formats' for the full set of 127 entries."
        ),
    )
    create.add_argument(
        "--bios-drive-type",
        default=None,
        metavar="VENDOR:N",
        help=(
            "Lock the VHD to a classic AT BIOS Type N preset so 86Box's BIOS "
            "auto-detect shows 'Type N' instead of 'User-defined'. Format is "
            "'<vendor>:<type_id>', e.g. 'phoenix:1' (10 MB 306x4x17), "
            "'ami:45' (68 MB 1024x8x17), or 'auto:N' (alias for phoenix). "
            "Run 'dosforge list-bios-drive-types' for the full table. "
            "Mutually exclusive with the MartyPC machine targets."
        ),
    )

    mount = subcommands.add_parser("mount", help="Mount a disk image and track it in app state.")
    mount.add_argument("--path", required=True, help="Path to .vhd/.img/.ima file to mount.")
    mount.add_argument("--open", action="store_true", help="Open mounted path in GUI file manager.")

    unmount = subcommands.add_parser("unmount", help="Unmount a previously tracked mount point.")
    unmount.add_argument("--mount-point", required=True, help="Mount path to unmount.")

    subcommands.add_parser("list-mounts", help="List tracked active mounts.")
    subcommands.add_parser(
        "list-martypc-formats",
        help="Print all 127 MartyPC AT/XT-IDE drive type slugs and exit.",
    )
    subcommands.add_parser(
        "list-bios-drive-types",
        help="Print the Phoenix and AMI classic AT BIOS HDD type tables and exit.",
    )
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
            DosForgeApp().run()
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
            machine_target_value = MachineTarget(args.machine_target)
            martypc_at_slug = args.martypc_at_drive_type
            if machine_target_value in (
                MachineTarget.MARTYPC_XTIDE,
                MachineTarget.MARTYPC_JRIDE,
            ):
                # Validate slug eagerly so CLI errors are clear.
                lookup_martypc_at_format(martypc_at_slug)
            bios_drive_type: tuple[BIOSVendor, int] | None = None
            if args.bios_drive_type is not None:
                try:
                    bios_drive_type = parse_bios_drive_slug(args.bios_drive_type)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
            if media_type is MediaType.VHD:
                if args.size:
                    size_bytes = parse_size(args.size)
                elif args.custom_payload_path:
                    size_bytes = 1
                elif machine_target_value is MachineTarget.MARTYPC_XEBEC:
                    size_bytes = MartyPCXebecDriveType(args.martypc_xebec_drive_type).size_bytes
                elif machine_target_value in (
                    MachineTarget.MARTYPC_XTIDE,
                    MachineTarget.MARTYPC_JRIDE,
                ):
                    size_bytes = lookup_martypc_at_format(martypc_at_slug).size_bytes
                elif bios_drive_type is not None:
                    # BIOS-typed drives lock size to the preset; placeholder
                    # value is overwritten by ``_validate_bios_drive_type_request``.
                    from .models import lookup_bios_drive_type as _lookup_bios
                    vendor, type_id = bios_drive_type
                    size_bytes = _lookup_bios(vendor, type_id).size_bytes
                else:
                    raise ValidationError(
                        "--size is required when --media-type is vhd unless --custom-payload-path is provided, "
                        "--bios-drive-type is set, or --machine-target selects a fixed-geometry profile."
                    )
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
                custom_payload_path=Path(args.custom_payload_path).expanduser() if args.custom_payload_path else None,
                machine_target=MachineTarget(args.machine_target),
                martypc_xebec_drive_type=MartyPCXebecDriveType(args.martypc_xebec_drive_type),
                martypc_at_drive_type_slug=martypc_at_slug,
                bios_drive_type=bios_drive_type,
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

        if args.command == "list-martypc-formats":
            print(
                f"{'slug':18s}  {'CHS':>13}  {'bytes':>11}  {'MiB':>7}  description"
            )
            for fmt in MARTYPC_AT_FORMATS:
                chs = f"{fmt.cylinders}x{fmt.heads}x{fmt.sectors_per_track}"
                print(
                    f"{fmt.slug:18s}  {chs:>13}  {fmt.size_bytes:>11}  "
                    f"{fmt.size_bytes/1024/1024:>7.2f}  {fmt.description}"
                )
            return 0

        if args.command == "list-bios-drive-types":
            for vendor in (BIOSVendor.PHOENIX, BIOSVendor.AMI):
                vendor_label = vendor.value.capitalize()
                print(f"\n{vendor_label} BIOS Standard Setup HDD types:")
                print(
                    f"  {'Type':>4}  {'Cyl':>5}  {'Hd':>3}  {'Pre':>5}  "
                    f"{'LZ':>5}  {'Spt':>3}  {'Size':>7}  slug"
                )
                for spec in iter_bios_drive_types(vendor):
                    pre = "---" if spec.write_precomp_cylinder < 0 else str(spec.write_precomp_cylinder)
                    print(
                        f"  {spec.type_id:>4}  "
                        f"{spec.cylinders:>5}  {spec.heads:>3}  {pre:>5}  "
                        f"{spec.landing_zone_cylinder:>5}  {spec.sectors_per_track:>3}  "
                        f"{spec.size_mb:>4} MB  {spec.slug}"
                    )
            print(
                "\nUse with: dosforge create --bios-drive-type <vendor>:<type_id> ...\n"
                "  e.g. --bios-drive-type phoenix:1  (10 MB, 306x4x17)\n"
                "       --bios-drive-type ami:45     (68 MB, 1024x8x17)\n"
                "       --bios-drive-type auto:2     (alias for phoenix:2)"
            )
            return 0
    except DosForgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help(sys.stderr)
    return 2
