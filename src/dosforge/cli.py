"""CLI entrypoint for dosforge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

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


_CLI_HELP_EPILOG = """\
examples:
  Build a bootable 512 MB MS-DOS 6.22 VHD (FAT16, 86Box/QEMU/generic target):
    dosforge create --media-type vhd --path C:\\images\\dos622.vhd ^
        --size 512M --format fat16 --boot-mode msdos622 --label DOS622

  Build a bootable 32 MB IBM PC 8088 (DOS 3.3) VHD with custom payload:
    dosforge create --media-type vhd --path C:\\images\\ibm88.vhd ^
        --size 32M --format fat16 --boot-mode ibm8088 ^
        --ibm-dos-version dos33 --custom-payload-path C:\\extras\\dos

  Build a bootable 1.44 MB MS-DOS 3.3 floppy:
    dosforge create --media-type img --path C:\\images\\boot33.img ^
        --floppy-type 1440k --img-system-format --boot-mode msdos33 ^
        --label BOOT33

  Build a 720K data floppy (no boot, no DOS files):
    dosforge create --media-type img --path C:\\images\\data.img ^
        --floppy-type 720k --label DATA

  Build a 1 GB FAT32 MS-DOS 7.1 (Win95 OSR2) VHD:
    dosforge create --media-type vhd --path C:\\images\\dos71.vhd ^
        --size 1G --format fat32 --boot-mode msdos71

  Check dependencies before creating an image:
    dosforge check-deps --media-type vhd --boot-mode msdos622

Run any subcommand with --help for its full option list.
"""


def build_parser(*, include_tui_gui: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dosforge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_CLI_HELP_EPILOG,
    )
    subcommands = parser.add_subparsers(dest="command")

    if include_tui_gui:
        subcommands.add_parser("tui", help="Launch the interactive TUI.")
        subcommands.add_parser(
            "gui", help="Launch the desktop GUI (default on Windows)."
        )

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
        "--host-boot-mode",
        choices=[mode.value for mode in BootMode if mode not in (BootMode.NONE, BootMode.FOURDOS)],
        default=None,
        help=(
            "Underlying DOS for --boot-mode=4dos.  4DOS is a shell overlay; it "
            "needs an actual DOS to provide the VBR/IO.SYS/COMMAND.COM.  "
            "Currently only msdos71 is supported as a host."
        ),
    )
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

    # ----------------------------------------------------------------
    # Image-content verbs (mtools-based, no mount required). These
    # work cross-platform against .vhd / .img / .ima / .vfd / .dsk /
    # .xdf files. For partitioned VHDs the first non-empty primary
    # partition entry is auto-selected (override with --partition).
    # ----------------------------------------------------------------
    ls_cmd = subcommands.add_parser(
        "ls",
        help="List DOS directory contents inside a disk image (no mount).",
    )
    ls_cmd.add_argument("image", help="Path to .vhd / .img / .ima / .vfd file.")
    ls_cmd.add_argument("path", nargs="?", default="/", help="DOS directory path (default: /).")
    ls_cmd.add_argument("--partition", type=int, default=None, help="1-indexed partition (VHD only).")
    ls_cmd.add_argument("--all", action="store_true", dest="show_hidden", help="Show hidden + system files.")

    cat_cmd = subcommands.add_parser(
        "cat",
        help="Print the contents of a file inside a disk image to stdout.",
    )
    cat_cmd.add_argument("image", help="Path to .vhd / .img / .ima / .vfd file.")
    cat_cmd.add_argument("path", help="DOS file path (e.g. /CONFIG.SYS).")
    cat_cmd.add_argument("--partition", type=int, default=None)
    cat_cmd.add_argument(
        "--binary",
        action="store_true",
        help="Write raw bytes to stdout (default: decode CP437 with line-end normalization).",
    )

    get_cmd = subcommands.add_parser(
        "get",
        help="Copy a file out of a disk image to the local filesystem.",
    )
    get_cmd.add_argument("image", help="Path to .vhd / .img / .ima / .vfd file.")
    get_cmd.add_argument("dos_path", help="Source DOS path inside the image.")
    get_cmd.add_argument(
        "local_path",
        nargs="?",
        default=".",
        help="Local destination file or directory (default: current dir).",
    )
    get_cmd.add_argument("--partition", type=int, default=None)

    put_cmd = subcommands.add_parser(
        "put",
        help="Copy a local file into a disk image.",
    )
    put_cmd.add_argument("image", help="Path to .vhd / .img / .ima / .vfd file.")
    put_cmd.add_argument("local_path", help="Local source file.")
    put_cmd.add_argument(
        "dos_path",
        nargs="?",
        default=None,
        help="Destination DOS path inside the image (default: /<basename>).",
    )
    put_cmd.add_argument("--partition", type=int, default=None)
    put_cmd.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if the destination file already exists.",
    )

    rm_cmd = subcommands.add_parser(
        "rm",
        help="Delete a file inside a disk image.",
    )
    rm_cmd.add_argument("image")
    rm_cmd.add_argument("dos_path")
    rm_cmd.add_argument("--partition", type=int, default=None)

    mkdir_cmd = subcommands.add_parser(
        "mkdir",
        help="Create a directory inside a disk image.",
    )
    mkdir_cmd.add_argument("image")
    mkdir_cmd.add_argument("dos_path")
    mkdir_cmd.add_argument("--partition", type=int, default=None)

    return parser


def ensure_startup_sudo_auth(runner: CommandRunner | None = None) -> None:
    # Platforms without kernel-mount / NBD / sudo (Windows) never need to
    # cache sudo credentials at startup. The active backend's
    # ``requires_sudo_for_disk_ops`` flag is the canonical signal.
    from ._platform import get_backend

    if not get_backend().requires_sudo_for_disk_ops:
        return

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


def _maximize_console_window() -> None:
    """Best-effort: maximize the host console window on Windows before
    launching the Textual TUI. No-op on non-Windows or when no console
    is attached (e.g. running via a non-console launcher). Safe to fail
    silently — the TUI still launches at the default size.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        SW_MAXIMIZE = 3
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    except Exception:
        # Maximizing is a UX nicety, never a hard requirement. Swallow
        # any ctypes/import/permission error and continue.
        return


def _launch_tui() -> int:
    """Launch the Textual TUI. Returns a process exit code."""
    ensure_startup_sudo_auth()
    try:
        from .app import DosForgeApp
    except ImportError as exc:
        print(
            "The dosforge TUI requires the 'textual' package, which is not "
            "available in this build. Run a CLI subcommand instead, e.g.:\n"
            "  dosforge create --help\n"
            "  dosforge check-deps\n"
            f"Underlying import error: {exc}",
            file=sys.stderr,
        )
        return 2
    _maximize_console_window()
    DosForgeApp().run()
    return 0


def _launch_gui(*, allow_tui_fallback: bool) -> int:
    """Launch the desktop GUI. Optionally fall back to the TUI on failure."""
    ensure_startup_sudo_auth()
    try:
        from ._gui import GuiUnavailable, run_gui
    except ImportError as exc:
        if allow_tui_fallback:
            return _launch_tui()
        print(
            "The dosforge GUI is not available in this build "
            f"(import error: {exc}). Try 'dosforge tui' instead.",
            file=sys.stderr,
        )
        return 2
    try:
        return run_gui()
    except GuiUnavailable as exc:
        if allow_tui_fallback:
            return _launch_tui()
        print(
            f"The dosforge GUI could not start: {exc}\n"
            "Try 'dosforge tui' instead.",
            file=sys.stderr,
        )
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Full CLI entry point used by ``pip install dosforge``.

    Includes ``tui`` and ``gui`` subcommands and the default-to-GUI-on-Windows
    behaviour. Bundled Windows ``dosforge.exe`` / ``dosforge-gui.exe`` use the
    slimmer :func:`cli_only_main` / :func:`gui_only_main` instead so they can
    drop the TUI dependencies entirely.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command is None:
            # Default: GUI on Windows (fall back to TUI), TUI elsewhere.
            if sys.platform == "win32":
                return _launch_gui(allow_tui_fallback=True)
            return _launch_tui()

        if args.command == "tui":
            return _launch_tui()

        if args.command == "gui":
            return _launch_gui(allow_tui_fallback=False)

        return _dispatch_cli_subcommand(args, parser)
    except (DependencyError, ValidationError, DosForgeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cli_only_main(argv: Sequence[str] | None = None) -> int:
    """CLI-only entry point used by the bundled ``dosforge.exe``.

    No ``tui`` / ``gui`` subcommands, no GUI/TUI imports — running this
    function does not pull in tkinter, sv_ttk, or textual. When invoked
    without arguments, prints the full help including example commands.
    """
    parser = build_parser(include_tui_gui=False)
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)

    try:
        if args.command is None:
            parser.print_help()
            return 0
        return _dispatch_cli_subcommand(args, parser)
    except (DependencyError, ValidationError, DosForgeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def gui_only_main(argv: Sequence[str] | None = None) -> int:
    """GUI-only entry point used by the bundled ``dosforge-gui.exe``.

    Launches the GUI directly with no TUI fallback and no subcommand
    parsing. Any extra argv is ignored.
    """
    return _launch_gui(allow_tui_fallback=False)


def _dispatch_cli_subcommand(args, parser) -> int:
    """Run the chosen CLI subcommand. Extracted so the CLI-only and full
    ``main()`` entry points can share the dispatch table without duplicating
    the giant ``create`` argument-marshalling block.
    """
    if args.command == "check-deps":
        assert_dependencies(
            media_type=MediaType(args.media_type),
            boot_mode=BootMode(args.boot_mode),
            freedos_source=FreeDOSSource(args.freedos_source),
        )
        print("All required dependencies are available.")
        return 0

    return _run_manager_subcommand(args, parser)


def _run_manager_subcommand(args, parser) -> int:
    try:

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
                host_boot_mode=BootMode(args.host_boot_mode) if args.host_boot_mode else None,
            )
            manager.create_and_prepare(request)
            print(f"Created and prepared {request.path.expanduser().resolve()}")
            return 0

        if args.command == "mount":
            from ._platform import get_backend

            backend = get_backend()
            # On Linux, kernel mount is always available. On Windows we
            # have native Mount-DiskImage for VHDs (admin required) and
            # nothing for IMG floppies (Mount-DiskImage rejects raw images).
            if not backend.supports_kernel_mount and sys.platform != "win32":
                print(
                    "`dosforge mount` requires kernel mount support.\n"
                    "On this platform use the mtools wrapper subcommands instead:\n"
                    "  dosforge ls <image> [path]      # list directory\n"
                    "  dosforge cat <image> <path>     # print file contents\n"
                    "  dosforge get <image> <path> [local]   # copy file out\n"
                    "  dosforge put <image> <local> [path]   # copy file in\n"
                    "  dosforge rm <image> <path>      # delete file\n"
                    "  dosforge mkdir <image> <path>   # create directory",
                    file=sys.stderr,
                )
                return 1
            try:
                record = manager.mount_vhd(Path(args.path))
            except DosForgeError as exc:
                msg = str(exc)
                # IMG on Windows lands here because _mount_vhd_native_windows
                # is VHD-only. Redirect to mtools verbs cleanly.
                if sys.platform == "win32" and Path(args.path).suffix.lower() in (".img", ".ima", ".vfd"):
                    print(
                        f"`dosforge mount` does not support floppy IMGs on Windows "
                        f"(Mount-DiskImage only handles .vhd/.vhdx/.iso).\n"
                        f"Use the mtools verbs instead: `dosforge ls/get/put/rm/mkdir <image>`.\n"
                        f"Original error: {msg}",
                        file=sys.stderr,
                    )
                    return 1
                raise
            print(f"Mounted {record.vhd_path} to {record.mount_point} via {record.nbd_device}")
            if args.open:
                manager.open_in_files(record.mount_point)
                print(f"Opened in file manager: {record.mount_point}")
            return 0

        if args.command == "unmount":
            from ._platform import get_backend

            # Both Linux (kernel mount) and Windows (Mount-DiskImage) record
            # mounts in the same state store; unmount() dispatches by record.
            record = manager.unmount(Path(args.mount_point))
            if record.nbd_device == "win-diskimage":
                print(f"Dismounted {record.vhd_path} (was {record.mount_point})")
            else:
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

        # --------------------------------------------------------------
        # Image-content verbs (cross-platform, no mount).
        # --------------------------------------------------------------
        if args.command in ("ls", "cat", "get", "put", "rm", "mkdir"):
            from . import image_ops

            if args.command == "ls":
                output = image_ops.ls(
                    Path(args.image),
                    args.path,
                    partition=args.partition,
                    all_files=args.show_hidden,
                )
                if output:
                    print(output)
                return 0

            if args.command == "cat":
                data = image_ops.cat(
                    Path(args.image),
                    args.path,
                    partition=args.partition,
                )
                if args.binary:
                    sys.stdout.buffer.write(data)
                else:
                    # Decode CP437 (DOS) and normalize CRLF to the host
                    # line ending. Falls back to lossy decoding for any
                    # bytes outside CP437.
                    text = data.decode("cp437", errors="replace").replace("\r\n", "\n")
                    sys.stdout.write(text)
                return 0

            if args.command == "get":
                written = image_ops.get(
                    Path(args.image),
                    args.dos_path,
                    Path(args.local_path),
                    partition=args.partition,
                )
                print(f"Copied {args.dos_path} -> {written}")
                return 0

            if args.command == "put":
                landed = image_ops.put(
                    Path(args.image),
                    Path(args.local_path),
                    args.dos_path,
                    partition=args.partition,
                    overwrite=not args.no_overwrite,
                )
                print(f"Copied {args.local_path} -> {args.image}:{landed}")
                return 0

            if args.command == "rm":
                image_ops.rm(Path(args.image), args.dos_path, partition=args.partition)
                print(f"Deleted {args.dos_path} from {args.image}")
                return 0

            if args.command == "mkdir":
                image_ops.mkdir(Path(args.image), args.dos_path, partition=args.partition)
                print(f"Created directory {args.dos_path} in {args.image}")
                return 0
    except DosForgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help(sys.stderr)
    return 2
