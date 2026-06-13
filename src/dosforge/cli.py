"""CLI entrypoint for dosforge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .commands import CommandRunner
from .dependencies import assert_dependencies
from .disk import DiskManager
from .errors import DependencyError, ValidationError, DosForgeError
from .models import (
    BIOSVendor,
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
    iter_bios_drive_types,
    lookup_bios_drive_type,
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


def _parse_chs(value: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected CYL,HEAD,SPT (for example 306,4,17)")
    try:
        cylinders, heads, sectors_per_track = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CHS values must be integers") from exc
    if cylinders <= 0 or heads <= 0 or sectors_per_track <= 0:
        raise argparse.ArgumentTypeError("CHS values must be positive")
    return (cylinders, heads, sectors_per_track)


def build_parser(*, include_tui_gui: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dosforge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_CLI_HELP_EPILOG,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"dosforge {__version__}",
        help="Print version and exit.",
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
        choices=[
            IBMDOSVersion.MSDOS33.value,
            IBMDOSVersion.PCDOS3.value,
            IBMDOSVersion.MSDOS5.value,
            IBMDOSVersion.PCDOS5.value,
            # Legacy v0.9.46-and-earlier wire values, accepted via
            # IBMDOSVersion._missing_ for back-compat with scripted CLIs.
            "dos33",
            "dos50",
        ],
        default=IBMDOSVersion.MSDOS33.value,
        help=(
            "DOS version for IBM PC 8088/V20 boot mode: "
            "msdos33 (MS-DOS 3.3, max 32MB), pcdos3 (PC-DOS 3.x, max 16MB FAT12), "
            "msdos5 (MS-DOS 5.0, max ~504MB), pcdos5 (PC-DOS 5.x, max ~504MB). "
            "Legacy aliases 'dos33'/'dos50' accepted for back-compat."
        ),
    )
    create.add_argument(
        "--custom-payload-path",
        default=None,
        help="Directory whose contents are copied into the created filesystem root.",
    )
    create.add_argument(
        "--disk-controller",
        choices=[controller.value for controller in DiskController],
        default=None,
        help=(
            "Hard-disk controller class for VHD output (auto-detected from boot "
            "mode if unset). Use 'xtide' for MartyPC compatibility (XT-class, "
            "8088-only; geometry is auto-snapped to MartyPC's XT-IDE format "
            "whitelist). Use 'mfm' for 86Box / PCem ST-225-era Xebec builds. "
            "See docs/martypc-compatibility.md for the full reference."
        ),
    )
    create.add_argument(
        "--custom-chs",
        type=_parse_chs,
        default=None,
        help="Custom CHS geometry as CYL,HEAD,SPT (e.g. 306,4,17). Used when --bios-drive-type is unset.",
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
            "Run 'dosforge list-bios-drive-types' for the full table."
        ),
    )

    mount = subcommands.add_parser("mount", help="Mount a disk image and track it in app state.")
    mount.add_argument("--path", required=True, help="Path to .vhd/.img/.ima file to mount.")
    mount.add_argument("--open", action="store_true", help="Open mounted path in GUI file manager.")

    unmount = subcommands.add_parser("unmount", help="Unmount a previously tracked mount point.")
    unmount.add_argument("--mount-point", required=True, help="Mount path to unmount.")

    subcommands.add_parser("list-mounts", help="List tracked active mounts.")
    subcommands.add_parser(
        "list-bios-drive-types",
        help="Print the Phoenix and AMI classic AT BIOS HDD type tables and exit.",
    )
    subcommands.add_parser(
        "where-assets",
        help=(
            "Print the dosassets/ search path for this host (env var, cwd, "
            "XDG data home, and system locations, in resolution order). "
            "Useful when 'install media not found' errors are unexpected."
        ),
    )
    init_assets_cmd = subcommands.add_parser(
        "init-assets",
        help=(
            "Create the dosassets/ directory skeleton (one folder + readme.txt "
            "per supported DOS mode) so you know where to drop install media. "
            "Defaults to $XDG_DATA_HOME/dosforge/dosassets/ on Linux."
        ),
    )
    init_assets_cmd.add_argument(
        "--target",
        type=Path,
        default=None,
        help=(
            "Directory to populate (default: $XDG_DATA_HOME/dosforge/dosassets, "
            "i.e. ~/.local/share/dosforge/dosassets on most Linux hosts)."
        ),
    )
    init_assets_cmd.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing readme.txt files instead of skipping them.",
    )
    fetch_pcdos71_cmd = subcommands.add_parser(
        "fetch-pcdos71-assets",
        help=(
            "Download and stage IBM PC-DOS 7.1 system files from the IBM "
            "ServerGuide Scripting Toolkit on archive.org. PC-DOS 7.1 is "
            "the only FAT32 + LBA-capable IBM DOS and the SGTK is the "
            "only legitimate distribution channel; this command does the "
            "download + SHA verification + extraction so you don't have "
            "to run the standalone script. Required once before "
            "'--boot-mode pcdos71' works."
        ),
    )
    fetch_pcdos71_cmd.add_argument(
        "--target",
        type=Path,
        default=None,
        help=(
            "Override the staging directory. Defaults to the user-scope "
            "dosassets/pcdos71 location (see 'dosforge where-assets')."
        ),
    )
    fetch_pcdos71_cmd.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if the archive cache looks fresh.",
    )
    fetch_pcdos71_cmd.add_argument(
        "--keep-extract",
        action="store_true",
        help=(
            "Leave the extracted SGTK tree in the cache directory after "
            "staging (default: delete to reclaim ~50 MB)."
        ),
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

    inspect_cmd = subcommands.add_parser(
        "inspect",
        help=(
            "Read-only structural inspection of a VHD (MBR + first "
            "partition BPB + root system files).  Output is JSON when "
            "--json is given, human-friendly otherwise."
        ),
    )
    inspect_cmd.add_argument("vhd", help="Path to the VHD to inspect.")
    inspect_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON for downstream tooling (e.g. exodosconverter).",
    )

    grow_cmd = subcommands.add_parser(
        "grow",
        help=(
            "Grow an existing VHD (FAT16 BIGDOS / FAT32 LBA) and "
            "optionally append staging content."
        ),
    )
    grow_cmd.add_argument(
        "--manifest",
        help="Path to a JSON grow manifest (see dosforge.grow.GrowManifest).",
    )
    grow_cmd.add_argument(
        "--target",
        help="Path to the existing VHD to grow (ignored when --manifest is given).",
    )
    grow_cmd.add_argument(
        "--new-size",
        help=(
            "New disk size in human form (e.g. '2G', '512M'). Ignored "
            "when --manifest is given."
        ),
    )
    grow_cmd.add_argument(
        "--boot-mode",
        help=(
            "Boot mode of the existing VHD. Must be one of: compaq331, "
            "msdos622, msdos71, freedos. Ignored when --manifest is given."
        ),
    )
    grow_cmd.add_argument(
        "--add-from",
        action="append",
        default=[],
        metavar="SRC=DEST",
        help=(
            "Stage SRC (host directory) into DEST (DOS absolute path, "
            "e.g. 'C:\\\\GAMES'). Repeatable. Ignored when --manifest "
            "is given."
        ),
    )
    grow_cmd.add_argument(
        "--no-boot-probe",
        dest="boot_probe",
        action="store_false",
        default=True,
        help="Skip the headless QEMU boot probe of the grown VHD.",
    )
    grow_cmd.add_argument(
        "--no-keep-backup",
        dest="keep_backup",
        action="store_false",
        default=True,
        help="Do not retain the original VHD as <target>.bak after a successful grow.",
    )

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
        "This host may require a password for every sudo command. Run `sudo -v` from a terminal immediately "
        "before launching dosforge, or extend your sudo timestamp_timeout so the cached credentials survive the build.\n"
        f"Details: {detail}"
    )


def _where_assets_command() -> int:
    """Print the dosassets/ search order for the current host.

    Walks the same candidate list ``resolve_dos_asset_dir()`` uses for
    each known boot mode and shows which paths exist. Helps Linux users
    figure out where to drop install media for a pip install vs. a
    bundle extract.
    """
    import os
    from pathlib import Path

    from .paths import (
        DOS_ASSETS_SUBDIR,
        _bundle_dosassets_dir,
        _wellknown_asset_roots,
    )

    print("dosforge dosassets/ resolution order (highest priority first):")
    print()

    rows: list[tuple[str, Path | None, str]] = []

    env_value = os.environ.get("DOSFORGE_DOSASSETS_DIR")
    if env_value:
        env_path = Path(env_value)
        rows.append(("DOSFORGE_DOSASSETS_DIR (env)", env_path, "set"))
    else:
        rows.append(("DOSFORGE_DOSASSETS_DIR (env)", None, "unset"))

    bundled = _bundle_dosassets_dir()
    if bundled is not None:
        rows.append(("bundled (frozen launcher)", bundled, "resolved"))

    cwd_root = Path.cwd() / DOS_ASSETS_SUBDIR
    rows.append(("cwd/dosassets", cwd_root, "cwd"))

    for root in _wellknown_asset_roots():
        rows.append(("well-known", root, "system / xdg"))

    for label, path, kind in rows:
        exists = path is not None and path.is_dir()
        marker = "[FOUND]" if exists else "[ missing ]"
        path_str = str(path) if path is not None else "(not set)"
        print(f"  {marker}  {label:32s}  {path_str}")

    print()
    print("To set a fixed asset library for pip-installed dosforge:")
    print("  export DOSFORGE_DOSASSETS_DIR=/path/to/your/dosassets")
    print()
    print("Or populate one of the well-known paths (the recommended")
    print("user-scope location is the XDG one):")
    xdg = next(iter(_wellknown_asset_roots()))
    print(f"  mkdir -p {xdg}")
    print()
    print("Tip: run 'dosforge init-assets' to materialize the per-mode")
    print("readme.txt skeleton at the recommended XDG location.")
    print()
    return 0


def _init_assets_command(target: Path | None, *, force: bool) -> int:
    """Materialize the per-mode dosassets/ skeleton.

    Drops one ``<mode>/readme.txt`` per supported DOS mode under
    ``target`` (defaults to ``$XDG_DATA_HOME/dosforge/dosassets``).
    Existing readmes are left alone unless ``--force`` is passed; user
    install media that already lives alongside a readme is never
    touched.
    """
    import os as _os

    from .asset_skeleton import default_target, materialize

    resolved_target = target if target is not None else default_target()
    print(f"Materializing dosassets skeleton at: {resolved_target}")
    try:
        final, created, updated, skipped = materialize(target, force=force)
    except OSError as exc:
        print(
            f"Error: cannot write skeleton at {resolved_target}: {exc}\n"
            "Pick a writable --target path or run with appropriate "
            "permissions (e.g. sudo for /usr/share/dosforge/dosassets).",
            file=sys.stderr,
        )
        return 1
    print(
        f"  created: {created}   updated: {updated}   skipped: {skipped}"
    )
    if skipped and not force:
        print(
            "  (skipped readmes already exist; pass --force to refresh them)"
        )
    print()
    print("Drop your DOS install media under the matching mode folder, e.g.:")
    sample = final / "msdos622"
    sep = _os.sep
    print(
        f"  {sample}{sep}  <- MS-DOS 6.22 install floppies "
        "(DISK1.IMG, DISK2.IMG, ...)"
    )
    print()
    print("Run 'dosforge where-assets' to confirm the location is now discovered.")
    return 0


def _inspect_command(args) -> int:
    """Dispatch ``dosforge inspect``: read MBR + BPB + root system
    files from a VHD and print either human-readable summary or
    JSON (for tooling integration).
    """

    from .inspect import inspect_vhd

    info = inspect_vhd(Path(args.vhd))
    if args.as_json:
        print(info.to_json())
        return 0

    # Human-readable summary.
    def _fmt_bytes(n: int) -> str:
        if n >= 1024**3:
            return f"{n / 1024**3:.2f} GiB ({n:,} bytes)"
        if n >= 1024**2:
            return f"{n / 1024**2:.2f} MiB ({n:,} bytes)"
        if n >= 1024:
            return f"{n / 1024:.2f} KiB ({n:,} bytes)"
        return f"{n} bytes"

    print(f"VHD: {info.path}")
    print(f"  File size       : {_fmt_bytes(info.file_size_bytes)}")
    print(f"  Format          : {'Fixed VHD (conectix)' if info.is_fixed_vhd else 'Raw / unknown'}")
    if info.footer_chs:
        c, h, s = info.footer_chs
        print(f"  Footer CHS      : {c} cyl x {h} heads x {s} spt ({c*h*s:,} sectors)")
    print()
    print(f"  Partition       : type=0x{info.mbr_partition_type:02X}  "
          f"LBA={info.partition_lba_start}-{info.partition_lba_start + info.partition_sector_count - 1}  "
          f"({_fmt_bytes(info.partition_sector_count * 512)})")
    print()
    print(f"  BPB OEM         : {info.bpb_oem!r}")
    print(f"  FAT format      : {info.fat_format.value}")
    print(f"  Cluster size    : {info.cluster_size_bytes:,} bytes "
          f"({info.bytes_per_sector} bytes/sector x {info.sectors_per_cluster} sectors/cluster)")
    print(f"  Cluster count   : {info.cluster_count:,}")
    print(f"  Total sectors   : {info.total_sectors:,}")
    print(f"  Reserved        : {info.reserved_sectors}")
    print(f"  Num FATs        : {info.num_fats}")
    print(f"  Sectors/FAT     : {info.sectors_per_fat}")
    print(f"  Root dir entries: {info.root_dir_entries}")
    if info.volume_label:
        print(f"  Volume label    : {info.volume_label}")
    if info.volume_serial_hex:
        print(f"  Volume serial   : {info.volume_serial_hex[:4]}-{info.volume_serial_hex[4:]}")
    print()
    if info.inferred_boot_mode:
        print(f"  Inferred boot mode: {info.inferred_boot_mode.value}")
    else:
        print(f"  Inferred boot mode: (unknown -- BPB OEM not in dosforge's table)")
    print()
    if info.root_system_files:
        print(f"  Root system files: {', '.join(info.root_system_files)}")
    else:
        print(f"  Root system files: (mtools unavailable -- run with mdir on PATH for detection)")
    return 0


def _grow_command(args) -> int:
    """Dispatch ``dosforge grow``: build a :class:`GrowManifest`
    from either ``--manifest`` or the per-flag form and invoke the
    grow pipeline.

    PREVIEW: the in-place expansion implementation is not yet
    landed. This command validates inputs and surfaces the public
    contract so downstream tools (notably ``exodosconverter``) can
    integrate against a stable API. Manifests that pass validation
    raise :class:`NotImplementedError` from
    :func:`dosforge.grow.grow_vhd`.
    """

    from .grow import (
        GrowManifest,
        StagingSource,
        grow_vhd,
        load_manifest_from_json,
    )

    if args.manifest:
        manifest = load_manifest_from_json(Path(args.manifest))
    else:
        missing = [
            flag for flag, value in (
                ("--target", args.target),
                ("--new-size", args.new_size),
            ) if value is None
        ]
        if missing:
            raise ValidationError(
                f"dosforge grow requires either --manifest, or both of: "
                f"--target, --new-size. Missing: {', '.join(missing)}."
            )
        boot_mode: BootMode | None = None
        if args.boot_mode:
            try:
                boot_mode = BootMode(args.boot_mode)
            except ValueError as exc:
                raise ValidationError(
                    f"Unknown --boot-mode {args.boot_mode!r}."
                ) from exc

        from .size import parse_size as _parse_size

        sources: list[StagingSource] = []
        for raw in args.add_from:
            if "=" not in raw:
                raise ValidationError(
                    f"--add-from value {raw!r} must be in the form SRC=DEST."
                )
            src, dest = raw.split("=", 1)
            sources.append(StagingSource(src=Path(src), dest=dest))

        manifest = GrowManifest(
            target_vhd=Path(args.target),
            new_size_bytes=_parse_size(args.new_size),
            boot_mode=boot_mode,
            staging_sources=tuple(sources),
            boot_probe=args.boot_probe,
            keep_backup=args.keep_backup,
        )

    try:
        grow_vhd(manifest)
    except NotImplementedError as exc:
        # Convert the contract-frozen stub error into a friendly CLI
        # preview message so downstream automation (exodosconverter)
        # doesn't see a raw Python traceback. Exit non-zero so any
        # wrapper script still notices the operation didn't complete.
        print(f"dosforge grow (PREVIEW): {exc}", file=sys.stderr)
        return 2
    print(f"Grew {manifest.target_vhd} to {manifest.new_size_bytes} bytes.")
    return 0


def _fetch_pcdos71_assets_command(
    target: Path | None,
    *,
    force: bool,
    keep_extract: bool,
) -> int:
    """Download + verify + stage IBM PC-DOS 7.1 assets from the SGTK.

    Thin CLI wrapper around
    :func:`dosforge.pcdos71_fetch.fetch_pcdos71_assets`. Catches
    ``DependencyError`` (no 7-Zip), ``OSError`` (cache / target
    write failures), and ``ValidationError`` (download SHA-1
    mismatch, missing DOS dir, per-file SHA-256 mismatch) so the
    CLI exits 1 with a clean error message instead of a traceback.
    """
    from .errors import DependencyError, ValidationError as _ValidationError
    from .pcdos71_fetch import (
        default_cache_dir,
        default_target_dir,
        fetch_pcdos71_assets,
    )

    resolved_target = target if target is not None else default_target_dir()
    print(f"Target: {resolved_target}")
    print(f"Cache:  {default_cache_dir()}")

    try:
        result = fetch_pcdos71_assets(
            target_dir=target,
            force=force,
            keep_extract=keep_extract,
            progress=lambda line: print(line),
        )
    except DependencyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except _ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"Error: cannot stage PC-DOS 7.1 assets at {resolved_target}: {exc}\n"
            "Pick a writable --target path or fix the file-system permissions.",
            file=sys.stderr,
        )
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
            "  tool scripts.' Either run the SGTK's MAKEDISK script under\n"
            "  DOSBox-X, or apply the github.com/Kreeblah/pcdos71-patch\n"
            "  batch to dosassets/pcdos2000/disk01.img and copy the\n"
            "  resulting disk to the target as install.img.\n"
            "  pcdos71_profile won't accept the target until a bootable\n"
            "  VFD is in place."
        )
    else:
        print(f"  Install floppy:      {result.vfd_filename}")
    print()
    print("You can now build PC-DOS 7.1 VHDs, e.g.:")
    print("  dosforge create --media-type vhd --boot-mode pcdos71 \\")
    print("      --format fat32 --size 1G --path my-pcdos71.vhd")
    return 0


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


def full_console_main(argv: Sequence[str] | None = None) -> int:
    """Console entry for the bundled full ``dosforge.exe``.

    Supports every subcommand including ``tui`` and ``gui``, so the user
    can launch the TUI from the console or open the GUI without leaving
    the shell. Without arguments, prints the full help (including
    examples) instead of auto-launching anything — same gentle default
    as :func:`cli_only_main`.
    """
    parser = build_parser(include_tui_gui=True)
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
        if args.command == "tui":
            return _launch_tui()
        if args.command == "gui":
            return _launch_gui(allow_tui_fallback=False)
        return _dispatch_cli_subcommand(args, parser)
    except (DependencyError, ValidationError, DosForgeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


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


def _is_sudo_auth_error_message(message: str) -> bool:
    """Heuristically detect CLI errors caused by a stale sudo cache."""

    if not message:
        return False
    lowered = message.lower()
    markers = (
        "sudo authentication is required for disk operations",
        "sudo: a password is required",
        "non-interactive sudo is not available",
        "a terminal is required to read the password",
    )
    return any(marker in lowered for marker in markers)


def _print_sudo_failure_guidance(message: str) -> None:
    """Augment a sudo-related CLI error with actionable next steps."""

    if sys.stdin.isatty():
        hint = (
            "Sudo credentials are not available. Run `sudo -v` in this "
            "terminal to prime the cache, then re-run dosforge."
        )
    else:
        hint = (
            "Sudo credentials are not available and this session has no "
            "TTY for prompting. Run dosforge from an interactive terminal "
            "(or prime the cache with `sudo -v` in a script wrapper) "
            "before invoking privileged subcommands."
        )
    print(f"\n{hint}", file=sys.stderr)


def _run_manager_subcommand(args, parser) -> int:
    try:

        manager = DiskManager()

        # Subcommands that perform privileged disk operations should
        # prompt for sudo once upfront so the rest of the run uses
        # the cached credentials non-interactively. TUI/GUI launches
        # already do this; we mirror it here so headless CLI flows
        # don't fall into the lazy-failure trap.
        _SUDO_REQUIRING_COMMANDS = ("create", "mount", "unmount")
        if args.command in _SUDO_REQUIRING_COMMANDS:
            ensure_startup_sudo_auth()

        if args.command == "sudo-check":
            ok, summary = manager.privilege_diagnostics_summary()
            print(summary)
            return 0 if ok else 1

        if args.command == "create":
            media_type = MediaType(args.media_type)
            floppy_type = FloppyType(args.floppy_type)
            disk_format = DiskFormat(args.disk_format) if media_type is MediaType.VHD else DiskFormat.FAT16
            disk_controller = DiskController(args.disk_controller) if args.disk_controller else None
            bios_drive_type: tuple[BIOSVendor, int] | None = None
            if args.bios_drive_type is not None:
                try:
                    bios_drive_type = parse_bios_drive_slug(args.bios_drive_type)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
            if media_type is MediaType.VHD:
                if bios_drive_type is not None:
                    vendor, type_id = bios_drive_type
                    size_bytes = lookup_bios_drive_type(vendor, type_id).size_bytes
                elif args.custom_chs is not None:
                    cyl, heads, spt = args.custom_chs
                    size_bytes = cyl * heads * spt * 512
                elif args.size:
                    size_bytes = parse_size(args.size)
                elif args.custom_payload_path:
                    size_bytes = 1
                else:
                    raise ValidationError(
                        "--size is required when --media-type is vhd unless --custom-payload-path, "
                        "--bios-drive-type, or --custom-chs is provided."
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
                bios_drive_type=bios_drive_type,
                disk_controller=disk_controller,
                custom_chs=args.custom_chs,
                host_boot_mode=BootMode(args.host_boot_mode) if args.host_boot_mode else None,
            )
            # Surface a "this build is slow" hint up-front for boot
            # modes whose staging is dominated by file count (FreeDOS'
            # ~1388 NLS files etc.). Without this, the CLI offers no
            # signal that a multi-minute wait is expected vs. a hang.
            from .formlogic import build_time_hint_for_boot_mode
            slow_hint = build_time_hint_for_boot_mode(request.boot_mode)
            if slow_hint:
                print(f"  [build] {slow_hint}")
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

        if args.command == "where-assets":
            return _where_assets_command()

        if args.command == "init-assets":
            return _init_assets_command(args.target, force=args.force)

        if args.command == "fetch-pcdos71-assets":
            return _fetch_pcdos71_assets_command(
                args.target,
                force=args.force,
                keep_extract=args.keep_extract,
            )

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

        if args.command == "grow":
            return _grow_command(args)
        if args.command == "inspect":
            return _inspect_command(args)
    except DosForgeError as exc:
        message = str(exc)
        print(message, file=sys.stderr)
        if _is_sudo_auth_error_message(message):
            _print_sudo_failure_guidance(message)
        return 1

    parser.print_help(sys.stderr)
    return 2
