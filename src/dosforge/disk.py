"""Core VHD/IMG creation, formatting, mount and unmount workflows."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, replace as _dataclass_replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .boot import BootAssetResolver, BootInstaller, PartitionRef
from .commands import CommandRunner, SudoKeepAlive, runner_for_backend, sudo_keepalive_for_backend
from ._core import mbr as core_mbr
from ._core import vhd_footer as core_vhd_footer
from .fourdos_overlay import (
    FourDosOverlayContext,
    install_fourdos_overlay,
    resolve_fourdos_assets_dir,
)
from .legacy_dos_install import (
    Compaq331InstallSources,
    LegacyDosInstallProfile,
    LegacyDosQemuInstaller,
    compaq2_profile,
    compaq331_profile,
    msdos33_profile,
    msdos5_profile,
    msdos622_profile,
    msdos71_profile,
    pcdos2000_profile,
    pcdos7_profile,
    pcdos71_fat16_profile,
    pcdos71_profile,
)
from .dependencies import BOOT_COMMANDS, REQUIRED_COMMANDS, assert_dependencies, find_missing
from .errors import DependencyError, DosForgeError, ValidationError
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MachineTarget,
    MartyPCAtFormat,
    MartyPCXebecDriveType,
    MediaType,
    MountRecord,
    lookup_martypc_at_format,
)
from .paths import (
    DOS_ASSETS_SUBDIR,
    app_cache_dir,
    app_mount_root,
    describe_dos_asset_locations,
    resolve_dos_asset_dir,
)
from .size import (
    FAT16_MAX_BYTES,
    FAT16_MIN_BYTES,
    FAT32_MAX_BYTES,
    FAT32_MIN_BYTES,
    IBM_DOS33_MAX_BYTES,
    IBM_DOS50_MAX_BYTES,
    MSDOS331_MAX_BYTES,
    COMPAQ331_MAX_BYTES,
    align_size_for_normal_chs,
    normalize_label,
    validate_size_for_floppy,
    validate_size_for_format,
    validate_size_for_ibm_dos,
)
from .state import StateStore


def _is_windows_admin() -> bool:
    """Return True if the current process has Windows admin rights.

    No-op on non-Windows platforms (returns True so the elevation gate
    is a no-op there). Uses ctypes to call ``IsUserAnAdmin`` which
    works whether or not Hyper-V / Storage cmdlets are available.
    """

    if sys.platform != "win32":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class _LegacyDosInstallDescriptor:
    """Per-boot-mode metadata for the QEMU-driven SYS install flow.

    Used by :meth:`DiskManager._install_legacy_dos_via_qemu` to dispatch on
    ``request.boot_mode`` without sprinkling per-mode if-chains through the
    code.
    """

    label: str
    asset_fallback_dirs: tuple[str, ...]
    preferred_image_names: tuple[str, ...]
    system_file_marker: str
    profile_builder: Callable[[Path, Path], LegacyDosInstallProfile]
    """Build the profile from ``(install_image, boot_assets_dir)``. Most
    profiles ignore the assets dir; pcdos71 uses it to locate
    FORMAT32.COM for the install floppy."""


_LEGACY_DOS_INSTALL_DESCRIPTORS: dict[BootMode, _LegacyDosInstallDescriptor] = {
    BootMode.COMPAQ331: _LegacyDosInstallDescriptor(
        label="Compaq DOS 3.31",
        asset_fallback_dirs=("compaq331", "msdos331"),
        preferred_image_names=("STARTUP.IMG", "STARTUP.IMA"),
        system_file_marker="IBMBIO.COM",
        profile_builder=compaq331_profile,
    ),
    # MS-DOS 3.31 (msdos331) shares the QEMU-driven SYS C: install
    # pipeline with Compaq DOS 3.31, but the install media you'll find
    # in the wild is varied:
    #
    #   - "Microsoft DOS 3.31" WinWorldPC archives ship as a single
    #     bootable Disk1.img with MS-flavoured IO.SYS / MSDOS.SYS.
    #   - Compaq DOS 3.31 archives ship as STARTUP.IMG / OPER.IMG /
    #     FASTART.IMG with IBM-flavoured IBMBIO.COM / IBMDOS.COM.
    #
    # Accept both naming conventions in ``preferred_image_names`` and
    # use IO.SYS as the system-file marker (the install-image scanner
    # is case-insensitive and will also match IBMBIO.COM via the
    # heuristic-fallback path inside ``_find_legacy_dos_install_image``).
    BootMode.MSDOS331: _LegacyDosInstallDescriptor(
        label="MS-DOS 3.31",
        asset_fallback_dirs=("msdos331", "compaq331"),
        preferred_image_names=(
            "DISK1.IMG", "DISK1.IMA",
            "DISK01.IMG", "DISK01.IMA",
            "STARTUP.IMG", "STARTUP.IMA",
        ),
        system_file_marker="IO.SYS",
        profile_builder=compaq331_profile,
    ),
    BootMode.MSDOS33: _LegacyDosInstallDescriptor(
        label="MS-DOS 3.30",
        asset_fallback_dirs=("msdos33",),
        preferred_image_names=("DISK01.IMG", "DISK01.IMA", "DISK1.IMG", "DISK1.IMA"),
        system_file_marker="IO.SYS",
        profile_builder=msdos33_profile,
    ),
    BootMode.PCDOS71: _LegacyDosInstallDescriptor(
        label="PC-DOS 7.1",
        asset_fallback_dirs=("pcdos71",),
        # tk_raid.vfd / install.vfd is our preferred install image — a
        # pre-built bootable PC-DOS 7.1 floppy from the IBM ServerGuide
        # Scripting Toolkit. The installer rewrites its AUTOEXEC.BAT to
        # drive FORMAT32 against the target VHD.
        preferred_image_names=(
            "INSTALL.VFD", "INSTALL.IMG",
            "TK_RAID.VFD", "TK_RAID2.VFD",
        ),
        system_file_marker="IBMBIO.COM",
        profile_builder=pcdos71_profile,
    ),
    # MS-DOS 7.10 install media: Microsoft Win95 OSR2 (build 4.00.1111)
    # floppy set. We use the Emergency Boot Disk (Boot.img) as the install
    # source — it ships a bootable real-Microsoft IO.SYS plus an ebd.cab
    # archive containing SYS.COM. The installer rewrites the boot disk's
    # AUTOEXEC.BAT to extract ebd.cab to a ramdrive and run SYS A: C:.
    #
    # Earlier dosforge builds tried to use the Chinese DOS 7.1 release
    # (DOS71_1S.PAK from disk01.img/disk02.img). That release ships
    # IO.SYS as an MZ-wrapped SETUP stub that the real installer unpacks
    # at install time — extracting it raw produces an unbootable VHD
    # ("Invalid system disk" from the MS-DOS 7.10 VBR). The OSR2 path
    # produces a byte-equivalent install (genuine MSWIN4.1 OEM VBR,
    # genuine OSR2 IO.SYS / MSDOS.SYS / COMMAND.COM).
    BootMode.MSDOS71: _LegacyDosInstallDescriptor(
        label="MS-DOS 7.10 (Win95 OSR2)",
        asset_fallback_dirs=("w95", "msdos71"),
        preferred_image_names=("Boot.img", "BOOT.IMG", "BOOT.IMA"),
        system_file_marker="IO.SYS",
        profile_builder=msdos71_profile,
    ),
    BootMode.MSDOS5: _LegacyDosInstallDescriptor(
        label="MS-DOS 5.0",
        asset_fallback_dirs=("msdos5", "dos5", "dos50"),
        preferred_image_names=(
            "DISK01.IMG", "DISK01.IMA", "DISK1.IMG", "DISK1.IMA",
        ),
        system_file_marker="IO.SYS",
        profile_builder=msdos5_profile,
    ),
    BootMode.MSDOS622: _LegacyDosInstallDescriptor(
        label="MS-DOS 6.22",
        asset_fallback_dirs=("msdos622",),
        preferred_image_names=(
            "DISK1.IMG", "DISK1.IMA", "DISK01.IMG", "DISK01.IMA",
        ),
        system_file_marker="IO.SYS",
        profile_builder=msdos622_profile,
    ),
    BootMode.PCDOS7: _LegacyDosInstallDescriptor(
        label="IBM PC-DOS 7.0",
        asset_fallback_dirs=("pcdos7",),
        # The install_image is supplied dynamically via
        # ``extract_pcdos7_install_floppy`` (which decompresses
        # 144US1.DSK via LOADDSKF.EXE inside DOSBox-X) -- this name
        # list is unused for pcdos7 but kept non-empty for the
        # descriptor contract.
        preferred_image_names=("pcdos7-install.img",),
        system_file_marker="IBMBIO.COM",
        profile_builder=pcdos7_profile,
    ),
    # Generic "PC-DOS bootable" alias.  Uses the same PC-DOS 7.0 install
    # pipeline as PCDOS7 (LOADDSKF.EXE on 144US1.DSK, then FORMAT C: /S
    # in QEMU) so the resulting VHD has an authentic 'IBM  7.0' VBR
    # instead of the leftover mkfs.fat stub VBR (which previously caused
    # a 'Non-System disk or disk error' on boot).  Asset fallback tries
    # ``pcdos/`` first for users who explicitly drop their own install
    # media there, then ``pcdos7/`` for the standard LOADDSKF flow.
    BootMode.PCDOS: _LegacyDosInstallDescriptor(
        label="PC-DOS",
        asset_fallback_dirs=("pcdos", "pcdos7"),
        preferred_image_names=("pcdos7-install.img",),
        system_file_marker="IBMBIO.COM",
        profile_builder=pcdos7_profile,
    ),
    # IBM PC-DOS 2000 (= PC-DOS 7.00 rebrand for the Y2K cycle).
    # Distributed by IBM as a 6-floppy set on a Software Selections CD;
    # WinWorldPC archives this as ``IBM PC-DOS 2000 (3.5-1.44mb).7z``
    # containing six raw 1.44 MB IMGs (``disk01.img`` is the bootable
    # install floppy with IBMBIO/IBMDOS/COMMAND/SYS.COM/FORMAT.COM at
    # its root).  Unlike PCDOS7 (which ships LOADDSKF-compressed
    # ``144US1.DSK``), no DOSBox-X decompression step is needed —
    # ``disk01.img`` is directly usable as the install_image.  The
    # FORMAT C: /S pipeline is the same one PCDOS7 uses, so the
    # resulting VHD is byte-equivalent to a PCDOS7 VHD aside from
    # build-time diagnostics.
    BootMode.PCDOS2000: _LegacyDosInstallDescriptor(
        label="IBM PC-DOS 2000",
        asset_fallback_dirs=("pcdos2000",),
        preferred_image_names=(
            "disk01.img",
            "DISK01.IMG",
            "disk01.ima",
            "DISK01.IMA",
            "DISK1.IMG",
        ),
        system_file_marker="IBMBIO.COM",
        profile_builder=pcdos2000_profile,
    ),
    # Compaq OEM MS-DOS 2.11 (FAT12, 360 KB install floppy).  Sources
    # both ``disk01.img`` directly (if user pre-extracted) and the
    # WinWorldPC ``Microsoft MS-DOS 2.11 [Compaq OEM] (5.25-360k).7z``
    # archive (auto-extracted via py7zr in
    # ``_legacy_dos_archive.extract_legacy_dos_install_archive``).
    # Marker is IBMBIO.COM (Compaq used IBM-style system file names
    # even though it's a Microsoft OEM build).
    BootMode.COMPAQ2: _LegacyDosInstallDescriptor(
        label="Compaq DOS 2.11",
        asset_fallback_dirs=("compaq2",),
        preferred_image_names=(
            "disk01.img",
            "DISK01.IMG",
            "disk01.ima",
            "DISK01.IMA",
        ),
        system_file_marker="IBMBIO.COM",
        profile_builder=compaq2_profile,
    ),
}


# Standard PC-DOS / MS-DOS 3.3-compatible MBR boot loader (bytes 0..439,
# 440 bytes total). The NT-style disk signature area (offsets 440-443) and
# the 2-byte reserved area (444-445) are written separately as zeros. The
# 0x55AA boot signature lives at MBR offset 510-511 and is also written
# separately so this constant stays exactly 440 bytes.
#
# Extracted verbatim from a real MS-DOS 3.30 install performed inside 86Box
# on an MFM/RLL drive (the user's 86Box-MFM-20M-Option3.vhd reference). The
# boot loader uses CHS reads only (INT 13h AH=02), which is essential for
# pre-LBA XT-class BIOSes (the MartyPC Xebec controller and 86Box's MFM/RLL
# controller both fall in that category). Modern Linux MBRs that parted
# writes use INT 13h AH=42 LBA reads and silently fail on these BIOSes
# (POST OK, then the boot sector load returns CF=1 and the MBR error path
# either prints "Error loading operating system" if string offsets line up,
# or just leaves a blinking cursor if the boot code returned to BIOS).
_LEGACY_DOS_MBR_BOOT_CODE_PRE_SIG: bytes = bytes.fromhex(
    "fa33c08ed0bc007c8bf45007501ffbfcbf0006b90001f2a5ea1d060000bebe07"
    "b304803c80740e803c00751c83c610fecb75efcd188b148b4c028bee83c610fe"
    "cb741a803c0074f4be8b06ac3c00740b56bb0700b40ecd105eebf0ebfebf0500"
    "bb007cb8010257cd135f730c33c0cd134f75edbea306ebd3bec206bffe7d813d"
    "55aa75c78bf5ea007c0000496e76616c696420706172746974696f6e20746162"
    "6c65004572726f72206c6f6164696e67206f7065726174696e67207379737465"
    "6d004d697373696e67206f7065726174696e672073797374656d000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000"
)
assert len(_LEGACY_DOS_MBR_BOOT_CODE_PRE_SIG) == 440


def _chs_to_partition_table_bytes(*, cyl: int, head: int, sector: int) -> bytes:
    """Encode a CHS triple in MBR-partition-entry byte format.

    Layout: ``[head, ((sector & 0x3F) | ((cyl >> 2) & 0xC0)), cyl & 0xFF]``.
    Caller is responsible for keeping ``cyl <= 1023`` (XT-class drives
    never exceed this so no clamping is needed here).
    """
    cyl_low = cyl & 0xFF
    cyl_high = (cyl >> 8) & 0x3
    return bytes(
        [
            head & 0xFF,
            (sector & 0x3F) | (cyl_high << 6),
            cyl_low,
        ]
    )


def _uses_legacy_dos_qemu_install(request: CreateRequest) -> bool:
    """Return True for boot modes whose install step is driven by QEMU.

    Currently eight flows go through ``_install_legacy_dos_via_qemu``:

    - ``BootMode.COMPAQ331`` -- Compaq DOS 3.31 (FAT16B + SYS C:).
    - ``BootMode.MSDOS331`` -- MS-DOS 3.31 reuses the Compaq pipeline.
    - ``BootMode.MSDOS33`` -- MS-DOS 3.30 (FORMAT C: /S from scratch).
    - ``BootMode.MSDOS5`` -- MS-DOS 5.0 (FORMAT C: /S).
    - ``BootMode.MSDOS622`` -- MS-DOS 6.22 (FORMAT C: /S).
    - ``BootMode.MSDOS71`` -- MS-DOS 7.10 via Win95 OSR2 SYS A: C:.
    - ``BootMode.IBM8088`` (both DOS 3.3 and DOS 5.0) -- reuses the
      msdos33 or msdos5 install pipeline depending on
      ``ibm_dos_version``.  The DOS 5.0 case used to use the static
      template path but that grafted a FLOPPY boot sector onto an HDD
      partition and didn't boot; switched to msdos5_profile here.
    - ``BootMode.PCDOS71`` -- PC-DOS 7.1 via FORMAT32 inside QEMU.
    """
    if request.boot_mode in (
        BootMode.COMPAQ2,
        BootMode.COMPAQ331,
        BootMode.MSDOS331,
        BootMode.MSDOS33,
        BootMode.MSDOS5,
        BootMode.MSDOS622,
        BootMode.MSDOS71,
        BootMode.PCDOS,
        BootMode.PCDOS7,
        BootMode.PCDOS2000,
        BootMode.PCDOS71,
    ):
        return True
    if request.boot_mode is BootMode.IBM8088:
        return True
    return False


def _legacy_dos_install_descriptor(request: CreateRequest) -> _LegacyDosInstallDescriptor | None:
    """Pick the QEMU install descriptor for ``request``.

    IBM8088 reuses per-version DOS descriptors: DOS 3.3 -> MSDOS33,
    DOS 5.0 -> MSDOS5.  Same install media, same FORMAT C: /S flow.

    PCDOS71 swaps profile based on disk_format: FAT32 uses FORMAT32.COM
    (``pcdos71_profile``) and FAT16/FAT12 uses the regular FORMAT.COM
    (``pcdos71_fat16_profile``).  Both ship with the SGTK install media.
    """
    if request.boot_mode is BootMode.IBM8088:
        if request.ibm_dos_version is IBMDOSVersion.DOS33:
            return _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.MSDOS33]
        return _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.MSDOS5]
    if (
        request.boot_mode is BootMode.PCDOS71
        and request.disk_format is not DiskFormat.FAT32
    ):
        # Return a per-call descriptor with the FAT16 profile builder so
        # the FORMAT.COM path is selected at install time.
        base = _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.PCDOS71]
        return _LegacyDosInstallDescriptor(
            label=base.label,
            asset_fallback_dirs=base.asset_fallback_dirs,
            preferred_image_names=base.preferred_image_names,
            system_file_marker=base.system_file_marker,
            profile_builder=pcdos71_fat16_profile,
        )
    return _LEGACY_DOS_INSTALL_DESCRIPTORS.get(request.boot_mode)


def _uses_msdos33_filesystem_layout(request: CreateRequest) -> bool:
    """Return True when DOS 3.30's FORMAT lays out the FAT itself.

    Also covers older DOS 2.x with the same track-aligned, primitive
    BPB layout (Compaq DOS 2.11 — FAT12 only, gets partition type
    0x01 instead of 0x04).

    Partition-table prep for these requests must:
    - set MBR partition type 0x04 (FAT16 <32 MiB, pre-FAT16B) or
      0x01 (FAT12, DOS 2.x), and
    - skip mformat (FORMAT C: /S writes its own BPB from scratch).
    """
    if request.boot_mode in (BootMode.MSDOS33, BootMode.COMPAQ2):
        return True
    if (
        request.boot_mode is BootMode.IBM8088
        and request.ibm_dos_version is IBMDOSVersion.DOS33
    ):
        return True
    return False


def _needs_xt_class_mbr_rewrite(request: CreateRequest) -> bool:
    """Return True when the VHD must use a CHS-only DOS-3.3 MBR.

    parted's modern MBR boot loader uses INT 13h AH=42 LBA reads and
    invents a BIOS-canonical (head=31+) start CHS in the partition
    entry — both fatal on pre-LBA XT-class BIOSes like MartyPC's
    Xebec MFM controller. For these targets we overwrite parted's
    MBR with a standard DOS-3.3 MBR boot loader (CHS reads only) and
    a track-aligned partition entry (start_LBA = spt, real CHS
    values for start/end) AFTER NBD detaches.

    Other targets (86Box AUTO IDE, etc.) keep parted's MBR — it's
    fine when the BIOS exposes LBA-aware INT 13h extensions.
    """
    return (
        request.machine_target is MachineTarget.MARTYPC_XEBEC
        and _uses_msdos33_filesystem_layout(request)
    )


def _partition_offset_bytes_for(request: CreateRequest) -> int:
    """Return the byte offset of the FAT partition inside the VHD.

    parted's default layout puts the partition at LBA 63 for legacy
    boot mode. The XT-class MBR rewrite (see ``_needs_xt_class_mbr_rewrite``)
    moves the partition to LBA = spt (one full track from the disk start
    — track-aligned for MFM drives, matching what real DOS 3.3 FDISK
    produces).
    """
    if _needs_xt_class_mbr_rewrite(request):
        spec = request.martypc_xebec_drive_type.spec
        return spec.sectors_per_track * 512
    return 63 * 512


# Filenames/directories never copied from a custom payload to the
# target disk: source-control metadata and host-OS junk that would
# only confuse a DOS user (e.g. ".gitignore" surfacing as
# ``GITIGN~1`` on the FAT root).  Matched case-insensitively against
# each path component, so e.g. ``stage/.git/HEAD`` is fully excluded.
_PAYLOAD_EXCLUDED_BASENAMES: frozenset[str] = frozenset({
    # Git
    ".git",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".gitkeep",
    # Other VCS
    ".svn",
    ".hg",
    ".hgignore",
    ".hgtags",
    ".bzr",
    # macOS / Windows / Python droppings
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    "__macosx",
    "__pycache__",
})


def _payload_path_is_excluded(relative: Path) -> bool:
    """Return True if any component of ``relative`` is a junk basename."""
    for part in relative.parts:
        if part.lower() in _PAYLOAD_EXCLUDED_BASENAMES:
            return True
    return False


@dataclass(slots=True)
class PrivilegeCheck:
    name: str
    status: str
    detail: str


class DiskManager:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        state_store: StateStore | None = None,
        boot_resolver: BootAssetResolver | None = None,
        boot_installer: BootInstaller | None = None,
        mount_root: Path | None = None,
        nbd_sys_block_root: Path | None = None,
        nbd_dev_root: Path | None = None,
        nbd_discovery_timeout: float = 5.0,
        backend: "PlatformBackend | None" = None,
    ) -> None:
        from ._platform import get_backend
        from ._platform.base import PlatformBackend  # noqa: F401 — type only

        self.backend = backend or get_backend()
        self.runner = runner or runner_for_backend(self.backend)
        self.state_store = state_store or StateStore()
        self.mount_root = mount_root or app_mount_root()
        self.mount_root.mkdir(parents=True, exist_ok=True)
        self.boot_resolver = boot_resolver or BootAssetResolver(self.runner)
        self.boot_installer = boot_installer or BootInstaller(self.runner, backend=self.backend)
        self.nbd_sys_block_root = nbd_sys_block_root or Path("/sys/class/block")
        self.nbd_dev_root = nbd_dev_root or Path("/dev")
        self.nbd_discovery_timeout = nbd_discovery_timeout

    def preflight(
        self,
        request: CreateRequest | None = None,
        *,
        media_type: MediaType | None = None,
    ) -> None:
        if request is not None:
            assert_dependencies(
                media_type=request.media_type,
                boot_mode=request.boot_mode,
                freedos_source=request.freedos_source,
            )
        else:
            assert_dependencies(media_type=media_type or MediaType.VHD)
        self._ensure_sudo_ready()

    def _sudo_keepalive(self) -> SudoKeepAlive:
        """Build a keep-alive sized to this manager's backend.

        Returned object is a no-op context manager on Windows (or any
        backend without ``requires_sudo_for_disk_ops``) — call sites
        can wrap unconditionally.
        """

        return sudo_keepalive_for_backend(self.backend)

    def create_and_prepare(self, request: CreateRequest) -> None:
        with self._sudo_keepalive():
            self._create_and_prepare_impl(request)

    def _create_and_prepare_impl(self, request: CreateRequest) -> None:
        self.preflight(request)
        self._apply_custom_payload_autosizing(request)
        self._validate_create_request(request)

        if request.boot_mode is BootMode.FOURDOS:
            self._create_and_prepare_fourdos(request)
            return

        if request.media_type is MediaType.IMG:
            self._create_and_prepare_floppy_img(request)
            return

        target_path = request.path.expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            if request.overwrite:
                target_path.unlink()
            else:
                raise ValidationError(f"VHD already exists: {target_path}")

        size_bytes = self._normalize_vhd_size_for_chs(request)
        self._create_fixed_vhd(target_path, size_bytes, request=request)
        request.size_bytes = size_bytes
        request.path = target_path
        fat_bios_chs = (
            self._read_vpc_bios_chs_geometry(target_path)
            if request.disk_format in (DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32)
            else None
        )

        # On platforms without qemu-nbd (Windows), partition + format the
        # VHD directly with pure-Python primitives + mtools' ``@@offset``
        # syntax. Only non-bootable VHDs are supported by this path at the
        # moment; bootable modes still require the Linux NBD route.
        if not self.backend.supports_nbd:
            self._create_and_prepare_vhd_no_kernel(request)
            return

        def configure(nbd_device: str) -> None:
            partition_device = self._partition_and_format(
                nbd_device=nbd_device,
                disk_format=request.disk_format,
                label=normalize_label(request.label),
                boot_mode=request.boot_mode,
                use_msdos33_layout=_uses_msdos33_filesystem_layout(request),
            )
            # Legacy DOS modes (compaq331, msdos33, ibm8088+dos33)
            # produce an authentic boot sector by running the DOS's own
            # SYS.COM or FORMAT.COM inside QEMU AFTER NBD detaches (QEMU
            # needs exclusive file access). Here we only write the MBR
            # boot code AND (for mformat-based installs) patch the BPB
            # heads/spt to match the VHD's footer geometry so DOS's
            # INT 13h reads line up. msdos33 / ibm8088+dos33 use the
            # FORMAT-from-scratch install method and there's no BPB to
            # patch yet (FORMAT writes its own).
            if _uses_legacy_dos_qemu_install(request):
                self.boot_installer.write_mbr_only(disk_device=nbd_device)
                if (
                    request.boot_mode in (BootMode.COMPAQ331, BootMode.MSDOS331)
                    and fat_bios_chs is not None
                ):
                    self.boot_installer.patch_fat16_bpb_geometry(
                        partition_device=partition_device,
                        bios_chs=fat_bios_chs,
                    )
            elif request.boot_mode is not BootMode.NONE:
                assets = self.boot_resolver.resolve(request)
                self.boot_installer.make_partition_bootable(
                    disk_device=nbd_device,
                    partition_device=partition_device,
                    disk_format=request.disk_format,
                    assets=assets,
                    bios_chs=fat_bios_chs,
                    boot_mode=request.boot_mode,
                )
            custom_payload = self._resolve_custom_payload_path(request)
            if custom_payload is not None and not _uses_legacy_dos_qemu_install(request):
                self._copy_custom_payload_to_filesystem(
                    partition_device=partition_device,
                    source_dir=custom_payload,
                    boot_mode=request.boot_mode,
                )

        self._with_connected_nbd(target_path, configure, image_format="vpc")

        # Fix parted's partition-entry CHS so 86Box AUTO IDE doesn't fall
        # back to LRG translation (see ``_rewrite_mbr_partition_entry_for_footer``).
        # Skipped for XT-class targets; they get a full MBR rewrite below.
        if not _needs_xt_class_mbr_rewrite(request):
            self._rewrite_mbr_partition_entry_for_footer(
                vhd_path=target_path,
                request=request,
            )

        # XT-class machine targets (MartyPC Xebec on msdos33-layout) need
        # an MS-DOS 3.3-style MBR + a track-aligned partition entry.
        # parted's MBR uses LBA INT 13h reads and invents BIOS-canonical
        # start CHS, both of which silently fail on pre-LBA XT BIOSes.
        # Rewrite the MBR here, while QEMU isn't running and we have
        # exclusive file access. The new partition entry points the
        # subsequent FORMAT C: /S at LBA = spt, which is exactly the
        # layout real DOS 3.3 FDISK produces on MFM controllers.
        if _needs_xt_class_mbr_rewrite(request):
            spec = request.martypc_xebec_drive_type.spec
            fs_type = 0x01 if request.disk_format is DiskFormat.FAT12 else 0x04
            self._rewrite_mbr_for_xt_class(
                vhd_path=target_path,
                cylinders=spec.cylinders,
                heads=spec.heads,
                sectors_per_track=spec.sectors_per_track,
                fs_type=fs_type,
            )

        partition_offset_bytes = _partition_offset_bytes_for(request)

        # Legacy DOS modes: after NBD detaches, drive the DOS's own SYS step
        # inside QEMU. This writes an authentic boot sector and copies
        # IO.SYS/IBMBIO.COM, MSDOS.SYS/IBMDOS.COM, COMMAND.COM with correct
        # attributes — exactly the workflow used on real hardware.
        if _uses_legacy_dos_qemu_install(request):
            self._install_legacy_dos_via_qemu(
                request=request,
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            # QEMU FORMAT C: /S only stages IO.SYS / MSDOS.SYS /
            # COMMAND.COM. If the user picked the FULL install profile
            # ("Tools + Startup files"), the DOS tools payload and
            # CONFIG.SYS / AUTOEXEC.BAT live in BootAssets after
            # resolution — copy them onto C: via mtools so they survive
            # the FORMAT step.
            self._stage_legacy_dos_full_profile_payload(
                request=request,
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            # QEMU's SeaBIOS exposes BIOS-canonical translation (16h/63s)
            # to the guest, so when DOS's FORMAT.COM writes the partition
            # BPB it picks up 16/63 for heads/spt. For targets whose
            # actual on-hardware controller exposes a different geometry
            # (notably MartyPC's Xebec MFM controller, which uses native
            # CHS, e.g. 615×4×17), the BPB ends up mismatching real
            # INT 13h reads and the boot sector double-faults — two beeps
            # and a drop into ROM-BASIC. Patch the BPB heads/spt to
            # whatever the VHD footer advertises so it matches what the
            # emulator's hard-disk controller will report.
            self._patch_partition_bpb_to_footer_geometry(
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            # QEMU's FORMAT/FDISK may have rewritten sector 0 (boot code +
            # partition table) using SeaBIOS-canonical CHS, re-introducing
            # the parted-style CHS mismatch we just fixed above. Re-apply
            # the footer-aligned CHS so 86Box AUTO IDE keeps NORMAL
            # translation. Skipped for XT-class (handled by full MBR rewrite).
            if not _needs_xt_class_mbr_rewrite(request):
                self._rewrite_mbr_partition_entry_for_footer(
                    vhd_path=target_path,
                    request=request,
                )
            # Custom payload (for these modes) is copied via mtools after
            # the QEMU SYS step, since the NBD path is no longer active.
            custom_payload = self._resolve_custom_payload_path(request)
            if custom_payload is not None:
                self._copy_custom_payload_to_vhd_via_mtools(
                    vhd_path=target_path,
                    partition_offset_bytes=partition_offset_bytes,
                    source_dir=custom_payload,
                )

    def mount_vhd(self, path: Path) -> MountRecord:
        with self._sudo_keepalive():
            return self._mount_vhd_impl(path)

    def _mount_vhd_impl(self, path: Path) -> MountRecord:
        image_path = path.expanduser().resolve()
        if not image_path.exists():
            raise ValidationError(f"Disk image file does not exist: {image_path}")

        media_type = self._media_type_for_path(image_path)
        self.preflight(media_type=media_type)
        # Windows native mount path (Mount-DiskImage). VHD only; floppy
        # IMG isn't supported by Mount-DiskImage at all (it only handles
        # .vhd/.vhdx/.iso) so we don't try it.
        if sys.platform == "win32" and media_type is MediaType.VHD:
            return self._mount_vhd_native_windows(image_path)
        if media_type is MediaType.IMG:
            return self._mount_floppy_img(image_path)
        return self._mount_vhd(image_path)

    def unmount(self, mount_point: Path) -> MountRecord:
        with self._sudo_keepalive():
            return self._unmount_impl(mount_point)

    def _unmount_impl(self, mount_point: Path) -> MountRecord:
        record = self.state_store.find_mount(mount_point.expanduser().resolve())
        if record is None:
            raise ValidationError(f"Mount point is not tracked by dosforge: {mount_point}")

        # Windows native unmount: nbd_device == "win-diskimage" sentinel.
        if record.nbd_device == "win-diskimage":
            self._unmount_vhd_native_windows(record)
            self.state_store.remove_mount(record.mount_point)
            return record

        self.preflight(media_type=MediaType.VHD if self._is_nbd_record(record) else MediaType.IMG)
        self.runner.run(["umount", str(record.mount_point)], sudo=True)
        if self._is_nbd_record(record):
            self._disconnect_nbd(record.nbd_device, check=True)
        self.state_store.remove_mount(record.mount_point)
        if record.mount_point.exists():
            record.mount_point.rmdir()
        return record

    def _mount_vhd_native_windows(self, vhd_path: Path) -> MountRecord:
        """Mount a VHD as a real Windows drive letter via Mount-DiskImage.

        Built-in to Windows 8+ (Storage module); does NOT need Hyper-V.
        Does require admin elevation — Mount-DiskImage for VHDs loads
        the storage virtualization driver. ISOs mount unprivileged but
        VHDs always need admin. We surface that as a clear error with
        the elevation hint when the call fails for that reason.

        The resulting mount uses Windows's native FAT driver, so it's
        readable/writable by Explorer, PowerShell, and every other
        Windows tool — much friendlier than the mtools wrappers when
        the user has admin and wants full file-manager access.
        """

        if not _is_windows_admin():
            raise ValidationError(
                "Native VHD mount on Windows requires admin elevation "
                "(Mount-DiskImage loads the storage virtualization driver). "
                "Either:\n"
                "  - Restart dosforge from an elevated PowerShell:\n"
                "      Start-Process powershell -Verb RunAs\n"
                "      cd C:\\Projects\\dosforge ; .\\dosforge\n"
                "  - Or use the no-admin alternatives:\n"
                "      dosforge ls    <image> [path]   (browse)\n"
                "      dosforge get   <image> <dos-path> [local]  (extract)\n"
                "      dosforge put   <image> <local> [dos-path]  (inject)"
            )

        ps_script = (
            f"$ErrorActionPreference='Stop';"
            f"$img = Mount-DiskImage -ImagePath '{vhd_path}' -PassThru;"
            f"$vol = $img | Get-Disk | Get-Partition | Get-Volume | Where-Object DriveLetter;"
            f"if (-not $vol) {{ throw 'Mounted but no drive letter assigned' }};"
            f"$vol.DriveLetter"
        )
        result = self.runner.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "required privilege is not held" in stderr.lower():
                raise ValidationError(
                    "Native VHD mount failed: admin elevation required. "
                    "Restart dosforge from an elevated PowerShell.\n"
                    f"Details: {stderr}"
                )
            raise ValidationError(
                f"Native VHD mount failed: {stderr or 'unknown error'}"
            )
        drive_letter = (result.stdout or "").strip()
        if not drive_letter:
            raise ValidationError(
                "Mount-DiskImage succeeded but no drive letter was assigned. "
                "The VHD may be partitionless or use an unsupported filesystem."
            )

        mount_point = Path(f"{drive_letter}:\\")
        record = MountRecord.create(
            vhd_path=vhd_path,
            nbd_device="win-diskimage",
            partition_device=f"{drive_letter}:",
            mount_point=mount_point,
        )
        self.state_store.add_mount(record)
        return record

    def _unmount_vhd_native_windows(self, record: MountRecord) -> None:
        """Dismount a VHD previously mounted via _mount_vhd_native_windows."""

        ps_script = (
            f"$ErrorActionPreference='Stop';"
            f"Dismount-DiskImage -ImagePath '{record.vhd_path}' | Out-Null"
        )
        result = self.runner.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "required privilege is not held" in stderr.lower():
                raise ValidationError(
                    "Dismount-DiskImage failed: admin elevation required. "
                    "Restart dosforge from an elevated PowerShell.\n"
                    f"Details: {stderr}"
                )
            raise ValidationError(
                f"Native VHD dismount failed: {stderr or 'unknown error'}"
            )

    def list_mounts(self) -> list[MountRecord]:
        return self.state_store.list_mounts()

    def _mount_vhd(self, vhd_path: Path) -> MountRecord:
        nbd_device = self._connect_nbd(vhd_path)
        mountpoint = self._next_mountpoint(vhd_path)
        mountpoint.mkdir(parents=True, exist_ok=True)
        mounted = False
        try:
            partition_device = self._wait_for_partition(nbd_device)
            mount_options = "uid={uid},gid={gid},umask=022,shortname=mixed".format(
                uid=os.getuid(),
                gid=os.getgid(),
            )
            self.runner.run(
                ["mount", "-t", "vfat", "-o", mount_options, partition_device, str(mountpoint)],
                sudo=True,
            )
            mounted = True
            record = MountRecord.create(
                vhd_path=vhd_path,
                nbd_device=nbd_device,
                partition_device=partition_device,
                mount_point=mountpoint,
            )
            self.state_store.add_mount(record)
            return record
        except Exception:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            self._disconnect_nbd(nbd_device, check=False)
            mountpoint.rmdir()
            raise

    def _mount_floppy_img(self, image_path: Path) -> MountRecord:
        mountpoint = self._next_mountpoint(image_path)
        mountpoint.mkdir(parents=True, exist_ok=True)
        mount_options = "loop,uid={uid},gid={gid},umask=022,shortname=mixed".format(
            uid=os.getuid(),
            gid=os.getgid(),
        )
        mounted = False
        try:
            self.runner.run(
                ["mount", "-t", "vfat", "-o", mount_options, str(image_path), str(mountpoint)],
                sudo=True,
            )
            mounted = True
            record = MountRecord.create(
                vhd_path=image_path,
                nbd_device="img-loop",
                partition_device=str(image_path),
                mount_point=mountpoint,
            )
            self.state_store.add_mount(record)
            return record
        except Exception:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            if mountpoint.exists():
                mountpoint.rmdir()
            raise

    def privilege_diagnostics(self) -> list[PrivilegeCheck]:
        checks: list[PrivilegeCheck] = []

        if not self.backend.requires_sudo_for_disk_ops:
            checks.append(
                PrivilegeCheck(
                    name="Privilege model",
                    status="ok",
                    detail=(
                        f"{self.backend.name} backend does not require sudo or kernel "
                        "mounts; all disk operations run as the current user via bundled "
                        "binaries."
                    ),
                )
            )
            try:
                assert_dependencies(media_type=MediaType.VHD)
                checks.append(
                    PrivilegeCheck(
                        name="Required commands",
                        status="ok",
                        detail="All bundled tools resolved successfully.",
                    )
                )
            except DosForgeError as exc:
                checks.append(
                    PrivilegeCheck(
                        name="Required commands",
                        status="fail",
                        detail=str(exc),
                    )
                )
            return checks

        missing_required = find_missing(REQUIRED_COMMANDS)
        if missing_required:
            checks.append(
                PrivilegeCheck(
                    name="Required commands",
                    status="fail",
                    detail=f"Missing: {', '.join(missing_required)}",
                )
            )
        else:
            checks.append(
                PrivilegeCheck(
                    name="Required commands",
                    status="ok",
                    detail="All base runtime commands are available.",
                )
            )

        missing_boot = find_missing(BOOT_COMMANDS)
        if missing_boot:
            checks.append(
                PrivilegeCheck(
                    name="Boot workflow tools",
                    status="warn",
                    detail=(
                        "Missing boot-only commands: "
                        f"{', '.join(missing_boot)} (needed only for bootable image preparation)"
                    ),
                )
            )
        else:
            checks.append(
                PrivilegeCheck(
                    name="Boot workflow tools",
                    status="ok",
                    detail="Boot preparation commands are available.",
                )
            )

        if "sudo" in missing_required:
            checks.append(
                PrivilegeCheck(
                    name="Non-interactive sudo readiness",
                    status="fail",
                    detail="sudo is not installed. Install sudo and configure sudoers first.",
                )
            )
        else:
            result = self.runner.run(["true"], sudo=True, check=False)
            if result.returncode == 0:
                checks.append(
                    PrivilegeCheck(
                        name="Non-interactive sudo readiness",
                        status="ok",
                        detail="sudo -n calls are currently authorized.",
                    )
                )
            else:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                checks.append(
                    PrivilegeCheck(
                        name="Non-interactive sudo readiness",
                        status="fail",
                        detail=(
                            f"{detail}. Run `sudo -v` in this terminal before launching dosforge so the "
                            "credential cache is primed for the session."
                        ),
                    )
                )

        candidates = self._list_nbd_candidates()
        if not candidates:
            checks.append(
                PrivilegeCheck(
                    name="NBD device availability",
                    status="warn",
                    detail=(
                        "No nbd devices are currently visible in sysfs; app will try "
                        "`sudo modprobe nbd max_part=16` when needed."
                    ),
                )
            )
        else:
            missing_nodes = [
                candidate.name for candidate in candidates if not (self.nbd_dev_root / candidate.name).exists()
            ]
            if missing_nodes:
                checks.append(
                    PrivilegeCheck(
                        name="NBD device availability",
                        status="warn",
                        detail=(
                            "NBD devices exist in sysfs but some /dev nodes are missing: "
                            f"{', '.join(missing_nodes)}"
                        ),
                    )
                )
            else:
                checks.append(
                    PrivilegeCheck(
                        name="NBD device availability",
                        status="ok",
                        detail=f"{len(candidates)} nbd device(s) detected and mapped in /dev.",
                    )
                )

        return checks

    def privilege_diagnostics_summary(self) -> tuple[bool, str]:
        checks = self.privilege_diagnostics()
        has_failures = any(check.status == "fail" for check in checks)
        marker = {"ok": "[OK]", "warn": "[WARN]", "fail": "[FAIL]"}
        lines = [
            f"{marker.get(check.status, '[INFO]')} {check.name}: {check.detail}"
            for check in checks
        ]
        headline = (
            "Privilege diagnostics found blocking issues."
            if has_failures
            else "Privilege diagnostics completed."
        )
        return (not has_failures, "\n".join([headline, *lines]))

    def open_in_files(self, path: Path) -> None:
        target = path.expanduser().resolve()
        if not target.exists():
            raise ValidationError(f"Cannot open missing path: {target}")
        # Windows: use the shell's "open" verb via os.startfile (opens
        # Explorer for directories, default handler for files). Linux:
        # delegate to xdg-open through the existing run_detached helper.
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return
        self.runner.run_detached(["xdg-open", str(target)])

    def fetch_freedos_assets(self, destination: Path | None = None, download_url: str | None = None) -> Path:
        # The hard requirement is mcopy (used to extract files from the
        # downloaded FreeDOS install image). The BOOTSECT_FAT32.BIN that
        # `_write_fat32_boot_template` produces requires either mkfs.fat
        # (Linux) or mformat (Windows / no-kernel-mount backends); only
        # one of them needs to be present.
        required = ["mcopy"]
        fat32_formatter = "mkfs.fat" if self.backend.supports_kernel_mount else "mformat"
        required.append(fat32_formatter)
        missing = find_missing(tuple(required), backend=self.backend)
        if missing:
            raise ValidationError(
                f"Missing required tools for FreeDOS extraction: {', '.join(missing)}"
            )
        target = (
            destination
            if destination is not None
            else (Path.cwd() / DOS_ASSETS_SUBDIR / "freedos")
        )
        return self.boot_resolver.export_latest_freedos_assets(
            target,
            image_url=download_url,
            include_full_fdos=True,
        )

    def _validate_create_request(self, request: CreateRequest) -> None:
        normalize_label(request.label)
        # 4DOS is a shell overlay -- it must be paired with a host DOS
        # boot mode that owns the actual VBR/IO.SYS/etc.  Validate the
        # pairing here so the rest of the pipeline can assume
        # ``host_boot_mode`` is set and sane.
        if request.boot_mode is BootMode.FOURDOS:
            if request.host_boot_mode is None:
                raise ValidationError(
                    "--boot-mode 4dos is a shell overlay; it requires "
                    "--host-boot-mode naming the underlying DOS (e.g. "
                    "msdos71).  4DOS layers on top of an already-bootable "
                    "DOS install; it cannot boot a disk by itself."
                )
            if request.host_boot_mode in (BootMode.NONE, BootMode.FOURDOS):
                raise ValidationError(
                    f"--host-boot-mode={request.host_boot_mode.value} is not "
                    "valid for the 4DOS overlay.  Choose a real DOS boot "
                    "mode (msdos71, msdos622, pcdos7, etc.)."
                )
            # Initial Phase 14F-full scope: only MSDOS71 is validated as a
            # working host.  Other host modes are likely to work but
            # haven't been smoke-tested yet; reject them explicitly so
            # users get a clear error instead of a half-broken VHD.
            _SUPPORTED_4DOS_HOSTS = {BootMode.MSDOS71}
            if request.host_boot_mode not in _SUPPORTED_4DOS_HOSTS:
                supported = ", ".join(sorted(m.value for m in _SUPPORTED_4DOS_HOSTS))
                raise ValidationError(
                    f"4DOS overlay on top of host '{request.host_boot_mode.value}' "
                    f"isn't supported yet.  Currently supported hosts: {supported}.  "
                    "More host modes can be added in subsequent iterations."
                )
        elif request.host_boot_mode is not None:
            raise ValidationError(
                f"--host-boot-mode={request.host_boot_mode.value} is only "
                "valid with --boot-mode=4dos; omit it for other modes."
            )
        self._resolve_custom_payload_path(request)
        if request.media_type is MediaType.IMG:
            validate_size_for_floppy(request.size_bytes, request.floppy_type)
            if request.path.suffix.lower() not in {".img", ".ima"}:
                raise ValidationError("Floppy images must use .img or .ima extension.")
            if request.img_system_format and request.boot_mode is BootMode.NONE:
                raise ValidationError("System-formatted IMG requires selecting a DOS boot mode.")
            if not request.img_system_format and request.boot_mode is not BootMode.NONE:
                raise ValidationError("Select System format to install DOS boot files into IMG.")
            return

        if request.machine_target is MachineTarget.MARTYPC_XEBEC:
            self._validate_martypc_xebec_request(request)
        elif request.machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            self._validate_martypc_at_request(request)

        # BIOS drive-type preset: lock size + footer CHS to the
        # selected Phoenix/AMI Type N row. Mutually exclusive with the
        # MartyPC machine targets (which already lock geometry through
        # their own preset tables).
        if request.bios_drive_type is not None:
            self._validate_bios_drive_type_request(request)

        validate_size_for_format(request.size_bytes, request.disk_format)
        if request.disk_format is DiskFormat.FAT12:
            # FAT12 on VHD is a narrow capability:
            #   * MartyPC Xebec Type 1 (10 MiB MFM) preset with MS-DOS 3.30
            #     (msdos33) or IBM 8088 + DOS33 install, OR
            #   * Compaq DOS 2.11 (compaq2) — DOS 2.x predates FAT16
            #     entirely so FAT12 is its only option (capped at 16 MiB
            #     elsewhere in this validator).
            # Anywhere else we'd need a hard-disk-aware FAT12 boot
            # sector / SYS workflow we don't currently produce.
            if request.boot_mode is not BootMode.COMPAQ2:
                if request.machine_target is not MachineTarget.MARTYPC_XEBEC:
                    raise ValidationError(
                        "FAT12 on VHD is only supported with the MartyPC Xebec Type 1 (10 MiB) preset "
                        "or boot-mode=compaq2 (Compaq DOS 2.11)."
                    )
                if request.martypc_xebec_drive_type is not MartyPCXebecDriveType.TYPE1:
                    raise ValidationError(
                        "FAT12 on VHD is only supported with MartyPC Xebec Type 1 (10 MiB) "
                        "or boot-mode=compaq2. Pick FAT16 for Xebec Type 2 / 13 / 16."
                    )
                if not _uses_msdos33_filesystem_layout(request):
                    raise ValidationError(
                        "FAT12 on VHD requires boot-mode=msdos33, ibm8088 + --ibm-dos-version dos33, "
                        "or boot-mode=compaq2 (DOS's own FORMAT C: /S writes the FAT12 BPB)."
                    )
        if request.boot_mode is BootMode.IBM8088:
            if request.disk_format not in (DiskFormat.FAT16, DiskFormat.FAT12):
                raise ValidationError(
                    "IBM PC 8088/V20 mode supports FAT16 (and FAT12 for the MartyPC Xebec Type 1 preset)."
                )
            validate_size_for_ibm_dos(request.size_bytes, request.ibm_dos_version)
        # MS-DOS 3.30 (msdos33) predates FAT16B and only reads
        # BPB.total_sectors_16 (uint16, max 65535 sectors ~= 31.99 MiB). The
        # post-CHS-alignment size effectively caps at IBM_DOS33_MAX_BYTES, but
        # raise here too so the user sees a clear "requested too big" error
        # instead of a silent shrink. compaq331 uses Compaq's FAT16B-capable
        # kernel and stretches the cap to ~504 MiB.
        if (
            request.boot_mode is BootMode.MSDOS33
            and request.size_bytes > IBM_DOS33_MAX_BYTES
        ):
            raise ValidationError(
                "MS-DOS 3.30 (msdos33) only supports FAT16 partitions up to 32 MiB "
                "because its boot loader and kernel read total_sectors_16 (uint16). "
                "Use compaq331 (Compaq DOS 3.31 / FAT16B) or msdos622 for larger partitions."
            )
        # Microsoft MS-DOS 3.31 (msdos331) has the same 32 MiB cap as
        # DOS 3.30 — Microsoft never shipped a true FAT16B kernel, only
        # Compaq did. The install media in dosassets/msdos331/ is the
        # Compaq OEM release, so we still drive it through the same
        # SYS C: pipeline, but the size is artificially capped at
        # 32 MiB to mirror what the Microsoft kernel can actually
        # address.
        if (
            request.boot_mode is BootMode.MSDOS331
            and request.size_bytes > MSDOS331_MAX_BYTES
        ):
            raise ValidationError(
                "MS-DOS 3.31 (msdos331) is capped at 32 MiB (FAT16 short). "
                "Use compaq331 for Compaq DOS 3.31's FAT16B kernel which "
                f"goes up to ~{COMPAQ331_MAX_BYTES // 1024 // 1024} MiB."
            )
        if (
            request.boot_mode is BootMode.COMPAQ331
            and request.size_bytes > COMPAQ331_MAX_BYTES
        ):
            raise ValidationError(
                f"Compaq DOS 3.31 (compaq331) only supports FAT16B partitions up to "
                f"{COMPAQ331_MAX_BYTES // 1024 // 1024} MiB. Use msdos5 / msdos622 "
                "for larger partitions."
            )
        # Compaq DOS 2.11 (and DOS 2.x in general) predate FAT16 entirely
        # and address at most ~16 MiB via FAT12. Cap accordingly.
        if (
            request.boot_mode is BootMode.COMPAQ2
            and request.size_bytes > 16 * 1024 * 1024
        ):
            raise ValidationError(
                "Compaq DOS 2.11 (compaq2) only supports FAT12 partitions up to "
                "16 MiB. Use compaq331 (FAT16B) or msdos5 / msdos622 for larger "
                "partitions."
            )
        if (
            request.boot_mode is BootMode.COMPAQ2
            and request.disk_format is not DiskFormat.FAT12
        ):
            raise ValidationError(
                "Compaq DOS 2.11 (compaq2) requires FAT12 (DOS 2.x predates FAT16)."
            )
        legacy_fat16_modes = {
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.PCDOS2000,
            BootMode.COMPAQ331,
        }
        if request.boot_mode in legacy_fat16_modes and request.disk_format is not DiskFormat.FAT16:
            raise ValidationError("Legacy DOS boot profiles support FAT16 only.")
        # PC-DOS 7.1 supports both FAT32 (via FORMAT32.COM) and FAT16
        # (via the regular FORMAT.COM) -- _legacy_dos_install_descriptor
        # picks the right profile based on request.disk_format.
        # PC-DOS FORMAT32 refuses to format partitions below ~1 GiB
        # ("The drive specified is too small to use FAT32."). The
        # threshold matches Win9x's FAT32 minimum cluster-count math
        # for the default 4 KiB cluster size (65525 clusters * 4 KiB
        # ~ 256 MiB) but PC-DOS uses a larger default, so set the
        # bar at 1 GiB to give FORMAT32 enough room.
        if (
            request.boot_mode is BootMode.PCDOS71
            and request.disk_format is DiskFormat.FAT32
            and request.size_bytes < 1024 * 1024 * 1024
        ):
            raise ValidationError(
                "PC-DOS 7.1 FAT32 partitions must be at least 1 GiB. "
                "PC-DOS FORMAT32 rejects smaller partitions with "
                "'The drive specified is too small to use FAT32.' "
                "Use --size 1G (or larger), or pick --format fat16 for "
                "smaller drives."
            )
        # MSDOS33 accepts FAT16 (default) and FAT12 (only for MartyPC Xebec
        # Type 1, validated above).
        if (
            request.boot_mode is BootMode.MSDOS33
            and request.disk_format not in (DiskFormat.FAT16, DiskFormat.FAT12)
        ):
            raise ValidationError(
                "MS-DOS 3.30 boot mode supports FAT16 (and FAT12 for the MartyPC Xebec Type 1 preset)."
            )
        if (
            request.boot_mode is BootMode.FREEDOS
            and request.freedos_source is FreeDOSSource.AUTO
            and request.disk_format is DiskFormat.FAT32
        ):
            raise ValidationError(
                "FreeDOS auto-download boot mode currently supports FAT16 only. "
                "For FAT32, use local FreeDOS assets with BOOTSECT_FAT32.BIN."
            )

    def _resolve_custom_payload_path(self, request: CreateRequest) -> Path | None:
        payload_path = request.custom_payload_path
        if payload_path is None:
            return None
        resolved = payload_path.expanduser().resolve()
        if not resolved.exists():
            raise ValidationError(f"Custom payload path does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValidationError(f"Custom payload path must be a directory: {resolved}")
        request.custom_payload_path = resolved
        self._validate_custom_payload_is_not_boot_assets(request, resolved)
        return resolved

    def _validate_custom_payload_is_not_boot_assets(
        self,
        request: CreateRequest,
        custom_payload: Path,
    ) -> None:
        # Reject the most common mistake: putting the DOS install-asset
        # directory into the custom payload field. The custom payload feature
        # copies the directory's full contents (Disk1.img, Disk2.img, etc.,
        # .7z archives, JPEGs, txt files) verbatim to C:\, which is virtually
        # never what the user wants.
        boot_dos_modes = {
            BootMode.FREEDOS,
            BootMode.MSDOS71,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.PCDOS2000,
            BootMode.PCDOS71,
            BootMode.COMPAQ2,
            BootMode.COMPAQ331,
        }
        if request.boot_mode not in boot_dos_modes:
            return

        if request.boot_assets_path is not None:
            resolved_boot_assets = (
                resolve_dos_asset_dir(request.boot_assets_path)
                or request.boot_assets_path.expanduser().resolve()
            )
            if (
                resolved_boot_assets == custom_payload
                or resolved_boot_assets.is_dir() and custom_payload == resolved_boot_assets
            ):
                raise ValidationError(
                    "Custom payload directory is the same as the boot assets directory: "
                    f"{custom_payload}. The custom payload feature copies the directory's "
                    "contents verbatim to C:\\, so DOS install diskettes (*.img/*.ima/*.dsk) "
                    "would land on the disk instead of being extracted. Use --custom-payload-path "
                    "for extra files (e.g. user data, apps), not for the DOS install media."
                )

        # Also detect "I put the install-disk directory into custom payload by
        # mistake" when boot_assets_path is empty but custom_payload looks like
        # an install-disk directory.
        install_image_suffixes = {".img", ".ima", ".dsk", ".xdf"}
        try:
            top_level_install_images = [
                child
                for child in custom_payload.iterdir()
                if child.is_file() and child.suffix.lower() in install_image_suffixes
            ]
        except OSError:
            return
        if len(top_level_install_images) >= 2:
            sample = ", ".join(sorted(p.name for p in top_level_install_images)[:4])
            raise ValidationError(
                f"Custom payload directory {custom_payload} appears to contain DOS install "
                f"diskette images ({sample}). The custom payload feature copies the directory's "
                "contents verbatim to C:\\, which would put install media files on the disk. "
                "Did you mean to fill the 'Boot assets path' field instead? If you really want "
                "to copy these files, move them into a sub-directory away from the install set."
            )

    def _validate_martypc_xebec_request(self, request: CreateRequest) -> None:
        if request.media_type is not MediaType.VHD:
            raise ValidationError(
                "MartyPC Xebec target requires VHD media; IMG floppies are not supported."
            )
        drive_type = request.martypc_xebec_drive_type
        if drive_type is MartyPCXebecDriveType.TYPE1:
            # 10 MiB MFM drive — must use FAT12 (only 20800 sectors,
            # well under FAT16's 16 MiB minimum).
            if request.disk_format is not DiskFormat.FAT12:
                raise ValidationError(
                    "MartyPC Xebec Type 1 (10 MiB, 306x4x17) requires FAT12. "
                    "Pick disk-format=fat12 (and boot-mode=msdos33 or ibm8088+dos33)."
                )
        else:
            if request.disk_format is not DiskFormat.FAT16:
                raise ValidationError(
                    "MartyPC Xebec target requires FAT16 (FAT32 is not supported by the XT-class Xebec HDC). "
                    "Type 1 uses FAT12 instead."
                )
        xt_class_modes = {
            BootMode.NONE,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.PCDOS,
            BootMode.COMPAQ2,
            BootMode.COMPAQ331,
        }
        if request.boot_mode not in xt_class_modes:
            raise ValidationError(
                "MartyPC Xebec target only supports XT-class DOS boot modes "
                "(none, ibm8088, msdos33, msdos331, pcdos, compaq2, compaq331)."
            )
        if request.boot_mode is BootMode.IBM8088 and request.ibm_dos_version is not IBMDOSVersion.DOS33:
            raise ValidationError(
                "MartyPC Xebec target with ibm8088 boot mode requires --ibm-dos-version dos33 "
                "(the 20 MiB Xebec drives are well under the DOS 5.0 504 MiB profile cap)."
            )
        # Force the requested size to match the drive type so users don't get a
        # confusing "size was X, became Y" surprise. Validation always runs
        # before the size is consumed downstream.
        request.size_bytes = drive_type.size_bytes

    def _validate_martypc_at_request(self, request: CreateRequest) -> None:
        controller_label = (
            "XT-IDE"
            if request.machine_target is MachineTarget.MARTYPC_XTIDE
            else "JR-IDE"
        )
        if request.media_type is not MediaType.VHD:
            raise ValidationError(
                f"MartyPC {controller_label} target requires VHD media; IMG floppies are not supported."
            )
        fmt = request.martypc_at_drive_type
        size_bytes = fmt.size_bytes
        if size_bytes < FAT16_MIN_BYTES and request.disk_format is DiskFormat.FAT16:
            raise ValidationError(
                f"MartyPC {controller_label} drive type {fmt.slug} "
                f"({fmt.description}) is below the 16 MiB FAT16 minimum and requires FAT12, "
                "which dosforge does not yet produce for VHD targets. "
                "Pick an AT drive type that is at least 16 MiB."
            )
        if request.disk_format is DiskFormat.FAT32 and size_bytes < FAT32_MIN_BYTES:
            raise ValidationError(
                f"MartyPC {controller_label} drive type {fmt.slug} "
                f"({fmt.description}) is below the 64 MiB FAT32 minimum. "
                "Pick a larger drive type, or use FAT16."
            )
        if request.boot_mode is BootMode.IBM8088:
            ibm_max = (
                IBM_DOS33_MAX_BYTES
                if request.ibm_dos_version is IBMDOSVersion.DOS33
                else IBM_DOS50_MAX_BYTES
            )
            if size_bytes > ibm_max:
                version_label = (
                    "DOS 3.3 (32 MiB)"
                    if request.ibm_dos_version is IBMDOSVersion.DOS33
                    else "DOS 5.0 (504 MiB)"
                )
                raise ValidationError(
                    f"MartyPC {controller_label} drive type {fmt.slug} "
                    f"({fmt.description}, {size_bytes // 1024 // 1024} MiB) exceeds the "
                    f"IBM 8088/V20 {version_label} limit. Pick a smaller AT drive type or "
                    "switch to a non-IBM8088 boot mode."
                )
        request.size_bytes = size_bytes

    def _validate_bios_drive_type_request(self, request: CreateRequest) -> None:
        """Validate a Phoenix/AMI BIOS drive-type preset and lock the size.

        The classic AT-BIOS HDD types lock both the total size and the
        footer CHS, so 86Box's BIOS auto-detect locks onto "Type N"
        instead of "User-defined". Mutually exclusive with the MartyPC
        machine targets — they're a different geometry source and
        combining them would produce ambiguous footers.

        Also enforces the regular boot-mode size caps (msdos33 and
        msdos331 at 32 MiB, IBM8088+DOS33 at 32 MiB, etc.) since some
        BIOS Types exceed those caps (Type 4 = 62 MB, Type 9 = 112 MB).
        """
        if request.media_type is not MediaType.VHD:
            raise ValidationError(
                "BIOS drive-type presets are only valid for VHD media."
            )
        if request.machine_target is not MachineTarget.GENERIC:
            raise ValidationError(
                "BIOS drive-type presets are mutually exclusive with MartyPC "
                "machine targets. Use machine-target=generic to pick a Phoenix/AMI "
                "Type N, or switch off the BIOS drive-type to use MartyPC's "
                "drive-type table."
            )
        spec = request.bios_drive_spec  # raises if invalid (vendor, type_id)
        assert spec is not None  # _validate_create_request only calls us when set

        # Lock the request's size to the spec; downstream callers
        # (qemu-img create, partition table) expect size_bytes to match
        # the eventual footer CHS exactly.
        request.size_bytes = spec.size_bytes

        # Re-apply boot-mode size caps now that the BIOS preset has
        # potentially raised the size above the requested value.
        if request.boot_mode is BootMode.IBM8088:
            ibm_max = (
                IBM_DOS33_MAX_BYTES
                if request.ibm_dos_version is IBMDOSVersion.DOS33
                else IBM_DOS50_MAX_BYTES
            )
            if spec.size_bytes > ibm_max:
                version_label = "DOS 3.3" if request.ibm_dos_version is IBMDOSVersion.DOS33 else "DOS 5.0"
                raise ValidationError(
                    f"BIOS drive-type preset {spec.slug} ({spec.description}) "
                    f"exceeds the IBM 8088/V20 {version_label} {ibm_max // 1024 // 1024} MiB "
                    "limit. Pick a smaller BIOS type or switch off IBM 8088 mode."
                )
        if request.boot_mode is BootMode.MSDOS33 and spec.size_bytes > IBM_DOS33_MAX_BYTES:
            raise ValidationError(
                f"BIOS drive-type preset {spec.slug} ({spec.description}) "
                f"exceeds the MS-DOS 3.30 32 MiB cap. Pick a smaller BIOS type or "
                "switch to compaq331 / msdos5 / msdos622 for larger partitions."
            )
        if request.boot_mode is BootMode.MSDOS331 and spec.size_bytes > MSDOS331_MAX_BYTES:
            raise ValidationError(
                f"BIOS drive-type preset {spec.slug} ({spec.description}) "
                f"exceeds the MS-DOS 3.31 32 MiB cap. Pick a smaller BIOS type or "
                "switch to compaq331 / msdos5 / msdos622 for larger partitions."
            )
        if request.boot_mode is BootMode.COMPAQ331 and spec.size_bytes > COMPAQ331_MAX_BYTES:
            raise ValidationError(
                f"BIOS drive-type preset {spec.slug} ({spec.description}) "
                f"exceeds the Compaq DOS 3.31 {COMPAQ331_MAX_BYTES // 1024 // 1024} MiB cap. "
                "Pick a smaller BIOS type or switch to msdos5 / msdos622."
            )

    def _apply_custom_payload_autosizing(self, request: CreateRequest) -> None:
        custom_payload = self._resolve_custom_payload_path(request)
        if custom_payload is None:
            return
        if request.media_type is not MediaType.VHD:
            return
        if request.machine_target in (
            MachineTarget.MARTYPC_XEBEC,
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            # MartyPC targets have fixed geometry/size; we cannot grow them
            # to fit payload. Validation in _validate_martypc_*_request
            # enforces the chosen drive type's size verbatim, so the most
            # helpful thing we can do is fail fast when the requested
            # payload won't fit.
            self._validate_custom_payload_fits_fixed_drive(
                request=request,
                custom_payload=custom_payload,
            )
            return
        if request.bios_drive_type is not None:
            # BIOS-typed disks are locked to the preset's exact size,
            # same as MartyPC drives. Fail fast if the payload won't fit.
            self._validate_custom_payload_fits_fixed_drive(
                request=request,
                custom_payload=custom_payload,
            )
            return

        estimated_payload = self._estimate_payload_bytes_on_fat(
            source_dir=custom_payload,
            cluster_bytes=4096,
        )
        safety_buffer = max(16 * 1024 * 1024, estimated_payload // 5)
        required_size = self._round_up_to_alignment(estimated_payload + safety_buffer, 1024 * 1024)
        if required_size > request.size_bytes:
            request.size_bytes = required_size

    def _validate_custom_payload_fits_fixed_drive(
        self,
        *,
        request: CreateRequest,
        custom_payload: Path,
    ) -> None:
        """Reject a custom payload that won't fit in a fixed-size MartyPC VHD.

        Mirrors the behavior of generic VHDs (which auto-grow) and the
        floppy IMG / mounted-FS payload copy (which uses statvfs to
        verify free space). MartyPC drives have a fixed geometry from
        the chosen drive type, so we estimate payload bytes here and
        raise a clear ValidationError if it exceeds the data area.

        The estimate uses an MS-DOS-3.3-style cluster size based on the
        disk format (FAT12 → 1 sector/cluster; FAT16 <32 MiB → 4
        sectors/cluster) and reserves a conservative overhead for the
        FAT, root directory, system files (IO.SYS, MSDOS.SYS,
        COMMAND.COM), and CONFIG.SYS / AUTOEXEC.BAT.
        """
        cluster_bytes = 512 if request.disk_format is DiskFormat.FAT12 else 2048
        estimated_payload = self._estimate_payload_bytes_on_fat(
            source_dir=custom_payload,
            cluster_bytes=cluster_bytes,
        )
        # ~1 MiB covers FAT tables (~80 KiB on a 20 MiB FAT16 disk),
        # root directory (16 KiB for 512 entries), the DOS system files
        # (~80 KiB), CONFIG.SYS / AUTOEXEC.BAT, and a small slack. For
        # the smallest preset (Xebec Type 1 = 10 MiB), this is still
        # roughly 10% reserved — appropriate for a vintage DOS install.
        overhead_bytes = 1 * 1024 * 1024
        # FULL profile also stages DOS utilities (FDISK, FORMAT, EDIT,
        # …). Conservatively reserve another 800 KiB on top so a
        # custom payload doesn't elbow the tools off the disk.
        if request.msdos_install_profile is MSDOSInstallProfile.FULL:
            overhead_bytes += 800 * 1024
        available_bytes = request.size_bytes - overhead_bytes
        if estimated_payload > available_bytes:
            drive_label = self._describe_machine_drive(request)
            raise ValidationError(
                f"Custom payload (~{estimated_payload // 1024} KiB on FAT) does not fit on the "
                f"{drive_label} ({request.size_bytes // 1024} KiB total, "
                f"~{available_bytes // 1024} KiB usable after DOS files / FAT overhead). "
                "Pick a larger MartyPC drive type, or shrink the custom payload."
            )

    @staticmethod
    def _describe_machine_drive(request: CreateRequest) -> str:
        if request.machine_target is MachineTarget.MARTYPC_XEBEC:
            spec = request.martypc_xebec_drive_type.spec
            return (
                f"MartyPC Xebec {request.martypc_xebec_drive_type.value} "
                f"({spec.description})"
            )
        if request.machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            fmt = request.martypc_at_drive_type
            label = "XT-IDE" if request.machine_target is MachineTarget.MARTYPC_XTIDE else "JR-IDE"
            return f"MartyPC {label} {fmt.slug} ({fmt.description})"
        bios_spec = request.bios_drive_spec
        if bios_spec is not None:
            return f"BIOS preset {bios_spec.slug} ({bios_spec.description})"
        return "selected fixed-size drive"

    @staticmethod
    def _martypc_locked_geometry(
        request: CreateRequest,
    ) -> tuple[int, int, int] | None:
        """Return (cyl, heads, spt) when the request targets a MartyPC HDC.

        Returns ``None`` for generic targets so callers can fall through to
        the standard 16h/63spt footer normalization.
        """
        if request.machine_target is MachineTarget.MARTYPC_XEBEC:
            spec = request.martypc_xebec_drive_type.spec
            return (spec.cylinders, spec.heads, spec.sectors_per_track)
        if request.machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            fmt = request.martypc_at_drive_type
            return (fmt.cylinders, fmt.heads, fmt.sectors_per_track)
        return None

    @staticmethod
    def _request_locked_geometry(
        request: CreateRequest,
    ) -> tuple[int, int, int] | None:
        """Return locked (cyl, heads, spt) from MartyPC OR BIOS-type presets.

        The MartyPC machine targets and the classic AT-BIOS HDD-type
        presets both lock the footer CHS to an exact value (instead of
        the 16h/63s canonical normalization). They are mutually
        exclusive — validated in ``_validate_create_request``. This
        helper returns whichever geometry source is active, or ``None``
        for a fully generic build.
        """
        martypc = DiskManager._martypc_locked_geometry(request)
        if martypc is not None:
            return martypc
        spec = request.bios_drive_spec
        if spec is not None:
            return (spec.cylinders, spec.heads, spec.sectors_per_track)
        return None

    def _create_fixed_vhd(
        self,
        path: Path,
        size_bytes: int,
        *,
        request: CreateRequest | None = None,
    ) -> None:
        # For machine-specific targets, use force_size=on so qemu-img uses the
        # requested size verbatim instead of rounding up to its internal CHS
        # algorithm. We then rewrite the footer CHS to the emulator's
        # expected geometry; current_size will exactly equal cyl*heads*spt*512.
        locked = (
            self._request_locked_geometry(request) if request is not None else None
        )
        if locked is not None:
            self.runner.run(
                [
                    "qemu-img",
                    "create",
                    "-f",
                    "vpc",
                    "-o",
                    "subformat=fixed,force_size=on",
                    str(path),
                    str(size_bytes),
                ]
            )
            cyl, heads, spt = locked
            self._write_vhd_footer_geometry(
                path,
                cylinders=cyl,
                heads=heads,
                sectors_per_track=spt,
            )
            self._densify_file_for_windows(path)
            return

        self.runner.run(
            [
                "qemu-img",
                "create",
                "-f",
                "vpc",
                "-o",
                "subformat=fixed,force_size=on",
                str(path),
                str(size_bytes),
            ]
        )
        # qemu-img writes Microsoft's legacy VHD CHS algorithm into the footer
        # (e.g. 1007x12x17 for ~100 MiB). 86Box's IDE AUTO detection treats
        # non-power-of-2 head counts as LARGE-translated geometry and reports
        # a doubled-heads/halved-cyl CHS to DOS via INT 13h AH=08. The BPB we
        # write reflects the *footer* geometry, so once BIOS reports a
        # different translated geometry, MS-DOS IO.SYS computes wrong CHS at
        # boot and reads the wrong sectors -> "Non-System disk" error.
        #
        # ``force_size=on`` makes qemu-img use ``size_bytes`` verbatim for
        # ``current_size`` instead of rounding up to its internal CHS
        # algorithm. ``_normalize_vhd_size_for_chs`` has already aligned
        # ``size_bytes`` to a multiple of 16x63x512, so after the footer-CHS
        # rewrite below ``current_size == cyl*heads*spt*512`` exactly --
        # 86Box AUTO IDE then picks NORMAL mode because total LBA == CHS
        # capacity. Without force_size, qemu would inflate the file by
        # a few sectors and AUTO would see "more LBA than CHS reach" and
        # pick LARGE instead, breaking boot for users on AUTO settings.
        #
        # Rewriting the footer to standard ATA geometry (16 heads, 63 spt)
        # makes 86Box AUTO pick NORMAL mode and report the footer values
        # directly. mkfs.fat then writes a matching BPB through qemu-nbd, and
        # IO.SYS's LBA->CHS arithmetic at boot lines up with what BIOS reports.
        self._normalize_vhd_footer_geometry(path)
        self._densify_file_for_windows(path)

    def _densify_file_for_windows(self, path: Path) -> None:
        """Clear the NTFS sparse attribute and materialize every byte.

        qemu-img produces fixed VHDs as NTFS-sparse files on Windows (only
        the small written regions — header, footer, allocated clusters —
        consume real disk space; the rest is a logical hole that returns
        zeros on read). Several Windows tools refuse sparse VHDs:

        - ``Mount-DiskImage`` errors with "Virtual hard disk files must be
          uncompressed and unencrypted and must not be sparse" before we
          can wire up native VHD mounting on Windows.
        - Windows Disk Management → "Attach VHD" rejects the file
          silently with the same constraint.
        - Some third-party tools (7-Zip, Disk2vhd, etc.) refuse to read
          or convert sparse VHDs.

        Two steps to fully densify the file:

        1. Clear the FILE_ATTRIBUTE_SPARSE_FILE flag via ``fsutil sparse
           setflag``. New writes after this point won't be sparse.
        2. Read every chunk and write it back to the same offset. Reads
           through sparse holes return zeros; writing those zeros back
           materializes the disk extent. Done in 4 MiB chunks; ~5-15s
           per 100 MiB on SSD, scales linearly. The footer + any
           previously-written content is preserved verbatim.

        No-op on non-Windows platforms (Linux supports sparse VHDs via
        qemu-nbd and has no need to densify).
        """

        if sys.platform != "win32":
            return
        try:
            self.runner.run(
                ["fsutil", "sparse", "setflag", str(path), "0"],
                check=False,
            )
        except Exception:
            # fsutil may not be in PATH in unusual environments; the
            # densify loop below still does the materialization.
            pass

        chunk_size = 4 * 1024 * 1024
        with path.open("r+b") as handle:
            handle.seek(0, os.SEEK_END)
            total = handle.tell()
            handle.seek(0)
            while True:
                offset = handle.tell()
                if offset >= total:
                    break
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                handle.seek(offset)
                handle.write(chunk)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass

    def _normalize_vhd_size_for_chs(self, request: CreateRequest) -> int:
        """Determine the byte-exact size to pass to ``qemu-img create``.

        - ``MachineTarget.MARTYPC_XEBEC``: returns the exact size of the
          selected Xebec drive type (cyl x heads x spt x 512). MartyPC's
          Xebec HDC validates the footer against this exact CHS at mount
          time, so any deviation will be rejected.
        - ``MachineTarget.MARTYPC_XTIDE`` / ``MARTYPC_JRIDE``: returns the
          exact size of the selected AT/XT-IDE drive type from MartyPC's
          127-entry AtFormats table.
        - ``CreateRequest.bios_drive_type`` set: returns the exact size
          of the selected classic AT BIOS Type N preset (mirrors the
          MartyPC behavior — the BIOS table also requires footer CHS to
          match the table's geometry exactly so 86Box's BIOS auto-detect
          locks onto Type N at boot).
        - ``MachineTarget.GENERIC``: rounds ``request.size_bytes`` to a
          cylinder of 16-head x 63-spt geometry so the post-create footer
          rewrite maps ``cyl x 16 x 63`` exactly to ``total_sectors``. Caps
          respect the requested DOS / FAT format (DOS-3.3 partition uint16
          cap, FAT16 2 GiB, FAT32 2 TiB).
        """
        if request.machine_target is MachineTarget.MARTYPC_XEBEC:
            return request.martypc_xebec_drive_type.size_bytes
        if request.machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            return request.martypc_at_drive_type.size_bytes
        bios_spec = request.bios_drive_spec
        if bios_spec is not None:
            return bios_spec.size_bytes

        min_bytes: int | None
        max_bytes: int | None
        if request.disk_format is DiskFormat.FAT12:
            # Compaq DOS 2.11 and other FAT12-on-VHD users want a
            # *small* hard disk (DOS 2.x maxes out at ~16 MiB).  Fall
            # back to the floppy minimum so 10-16 MiB requests don't
            # get bumped up to 64 MiB by the FAT32 default floor.
            from .size import FAT12_MIN_BYTES, FAT12_MAX_BYTES

            min_bytes = FAT12_MIN_BYTES
            max_bytes = FAT12_MAX_BYTES
            if request.boot_mode is BootMode.COMPAQ2:
                max_bytes = min(max_bytes, 16 * 1024 * 1024)
        elif request.disk_format is DiskFormat.FAT16:
            min_bytes = FAT16_MIN_BYTES
            max_bytes = FAT16_MAX_BYTES
            if request.boot_mode is BootMode.IBM8088:
                ibm_max = (
                    IBM_DOS33_MAX_BYTES
                    if request.ibm_dos_version is IBMDOSVersion.DOS33
                    else IBM_DOS50_MAX_BYTES
                )
                max_bytes = min(max_bytes, ibm_max)
            # MS-DOS 3.30 (msdos33) predates FAT16B and only reads
            # BPB.total_sectors_16 (uint16, max 65535 sectors ~= 31.99 MiB).
            # Anything larger trips the same boot failure (BPB.total16
            # wraps to 0, kernel can't locate the FAT). Microsoft MS-DOS
            # 3.31 (msdos331) has the same 32 MiB cap — only the
            # Compaq OEM kernel (compaq331) handles FAT16B up to ~504 MiB.
            if request.boot_mode is BootMode.MSDOS33:
                max_bytes = min(max_bytes, IBM_DOS33_MAX_BYTES)
            if request.boot_mode is BootMode.MSDOS331:
                max_bytes = min(max_bytes, MSDOS331_MAX_BYTES)
            if request.boot_mode is BootMode.COMPAQ331:
                max_bytes = min(max_bytes, COMPAQ331_MAX_BYTES)
        else:
            min_bytes = FAT32_MIN_BYTES
            max_bytes = FAT32_MAX_BYTES
        return align_size_for_normal_chs(
            request.size_bytes, min_bytes=min_bytes, max_bytes=max_bytes
        )

    def _normalize_vhd_footer_geometry(self, path: Path) -> None:
        try:
            with path.open("r+b") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = bytearray(handle.read(512))
                if len(footer) != 512 or footer[:8] != b"conectix":
                    return
                current_size_bytes = struct.unpack(">Q", footer[48:56])[0]
                total_sectors = current_size_bytes // 512
                if total_sectors <= 0:
                    return
                heads = 16
                spt = 63
                cylinders = total_sectors // (heads * spt)
                if cylinders <= 0:
                    return
                self._write_footer_chs_in_place(
                    handle, footer, cylinders=cylinders, heads=heads, sectors_per_track=spt
                )
        except OSError:
            return

    def _write_vhd_footer_geometry(
        self,
        path: Path,
        *,
        cylinders: int,
        heads: int,
        sectors_per_track: int,
    ) -> None:
        try:
            with path.open("r+b") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = bytearray(handle.read(512))
                if len(footer) != 512 or footer[:8] != b"conectix":
                    return
                self._write_footer_chs_in_place(
                    handle,
                    footer,
                    cylinders=cylinders,
                    heads=heads,
                    sectors_per_track=sectors_per_track,
                )
        except OSError:
            return

    @staticmethod
    def _write_footer_chs_in_place(
        handle,
        footer: bytearray,
        *,
        cylinders: int,
        heads: int,
        sectors_per_track: int,
    ) -> None:
        footer[56:58] = struct.pack(">H", min(max(cylinders, 1), 0xFFFF))
        footer[58] = heads & 0xFF
        footer[59] = sectors_per_track & 0xFF
        footer[64:68] = b"\x00\x00\x00\x00"
        checksum = (~sum(footer)) & 0xFFFFFFFF
        footer[64:68] = struct.pack(">I", checksum)
        handle.seek(-512, os.SEEK_END)
        handle.write(bytes(footer))

    def _create_and_prepare_vhd_no_kernel(self, request: CreateRequest) -> None:
        """No-kernel-mount VHD pipeline for Windows hosts.

        Replaces the Linux qemu-nbd + parted + mkfs.fat flow. The VHD
        file has already been allocated by ``_create_fixed_vhd`` (which
        also wrote the correct footer CHS for the chosen machine target).
        From here we:

        1. Read the VHD footer to discover the canonical CHS triplet
           (heads / sectors-per-track) that the partition entry must
           encode for legacy BIOS INT 13h reads to line up with what
           the emulator's hard disk controller reports.
        2. Write a single-partition MBR at sector 0 using the pure-Python
           writer in ``_core.mbr``. Layout matches what Linux parted
           produces for ``boot_mode=NONE``: partition starts at LBA 2048
           (1 MiB alignment), bootable flag set, partition type 0x06
           (FAT16-CHS) or 0x0C (FAT32-LBA).
        3. Format the partition in-place via ``mformat -i <vhd>@@<offset>``
           passing the partition size via ``-T`` and the partition start
           via ``-H``. Without those, mtools auto-detects from EOF which
           would silently include the VHD footer in the data area.
        4. Copy any custom payload via the existing mtools-based helper.

        Bootable VHDs are explicitly out of scope at this layer (the
        BootInstaller still depends on kernel mounts / NBD partition
        devices). Callers that pass any non-``BootMode.NONE`` request
        hit a ``ValidationError`` directing them to the Linux path.
        """

        if request.boot_mode not in (
            BootMode.NONE,
            BootMode.FREEDOS,
            BootMode.MSDOS71,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.COMPAQ2,
            BootMode.COMPAQ331,
            BootMode.IBM8088,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.PCDOS2000,
            BootMode.PCDOS71,
        ):
            raise ValidationError(
                "This boot mode is not yet supported on this platform. "
                "On Windows, supported VHD boot modes are: none, freedos, "
                "msdos71, msdos33, msdos331, compaq2, compaq331, "
                "ibm8088 (dos33), msdos5, msdos622, pcdos, pcdos7, "
                "pcdos2000, pcdos71."
            )

        target_path = request.path
        footer = core_vhd_footer.read_footer(target_path)
        total_sectors = footer.total_sectors
        # FAT32 also needs footer-CHS for the VBR geometry patch so AT
        # BIOSes with >504 MiB drives apply ECHS bit-shift translation
        # consistently — the FreeDOS FAT32 boot sector
        # (BOOTSECT_FAT32.BIN, real boot32lb) is already shipped in
        # dosassets/freedos/ and validated by the BootAssetResolver, so
        # extending fat_bios_chs to cover FAT32 is the only step that
        # was missing to unblock freedos+fat32 on Windows.
        fat_bios_chs = (
            self._read_vpc_bios_chs_geometry(target_path)
            if request.disk_format in (DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32)
            else None
        )

        legacy_qemu_install = _uses_legacy_dos_qemu_install(request)
        msdos33_layout = _uses_msdos33_filesystem_layout(request)
        pcdos71_layout = request.boot_mode is BootMode.PCDOS71
        msdos71_layout = request.boot_mode is BootMode.MSDOS71

        # Partition start: legacy DOS-3.x modes get a track-aligned
        # partition at LBA = spt (or 63 by default) to mirror the layout
        # that real DOS FDISK / MS-DOS 3.x install produces. PC-DOS 7.1
        # and MS-DOS 7.10 are LBA-aware so they get the same modern
        # 1 MiB alignment used by FreeDOS / non-bootable. Everything
        # else legacy gets the spt-aligned offset.
        if legacy_qemu_install and not (pcdos71_layout or msdos71_layout):
            start_lba = _partition_offset_bytes_for(request) // 512
        else:
            start_lba = 2048

        partition_sectors = total_sectors - start_lba
        if partition_sectors <= 0:
            raise ValidationError(
                f"VHD too small ({total_sectors} sectors) to host a partition "
                f"starting at LBA {start_lba}."
            )

        # MBR partition CHS encoding: AT BIOSes apply ECHS bit-shift
        # translation when the drive's physical cylinder count exceeds
        # 1024 (every drive >~504 MB at 16h/63s). The BIOS doubles heads
        # and halves cylinders until cyl <= 1024, presenting a virtual
        # geometry like 64h/63s instead of the footer's 16h/63s. The MBR
        # boot code uses INT 13h AH=02 with the partition entry's CHS,
        # which the BIOS resolves through THAT translated geometry —
        # so the partition table CHS must be encoded with the translated
        # heads/spt or the MBR loads the wrong sector and the boot
        # silently fails (blinking cursor on 86Box).
        partition_chs_heads = footer.heads
        partition_chs_spt = footer.sectors_per_track
        if footer.heads > 0 and footer.cylinders > 1024:
            heads = footer.heads
            cyls = footer.cylinders
            while cyls > 1024 and heads < 256:
                heads *= 2
                cyls = (cyls + 1) // 2
            partition_chs_heads = min(heads, 255)

        # Partition type byte: legacy DOS gets 0x04 (FAT16 <32 MiB,
        # pre-FAT16B) or 0x01 (FAT12); pcdos71 / msdos71 get 0x0C
        # (FAT32 LBA) or 0x0E (FAT16 LBA); modern gets 0x0C / 0x06.
        # MSDOS331 caps at 32 MiB and uses 0x04 (FAT16 short, matching
        # what MS-DOS 3.31's FORMAT writes).  COMPAQ331 uses 0x06
        # (FAT16B / BIGDOS) because Compaq DOS 3.31 *introduced* BIGDOS
        # and its FORMAT.COM refuses to format type-0x04 partitions.
        if msdos33_layout or request.boot_mode is BootMode.MSDOS331:
            partition_type = 0x01 if request.disk_format is DiskFormat.FAT12 else 0x04
        elif (pcdos71_layout or msdos71_layout) and request.disk_format is DiskFormat.FAT32:
            partition_type = 0x0C
        elif pcdos71_layout:
            partition_type = 0x0E  # FAT16 LBA (PC-DOS 7.1 FORMAT.COM accepts it)
        elif msdos71_layout:
            # Win95 OSR2 SYS A: C: refuses to install on partition type 0x0E
            # (FAT16 LBA) — the boot floppy's autoexec runs but SYS bails
            # before writing IO.SYS / MSDOS.SYS, leaving only the
            # pre-staged DBLBUFF.SYS + IFSHLP.SYS on disk. Use 0x06
            # (FAT16-CHS) to match what parted writes on the Linux path.
            partition_type = 0x06
        elif request.disk_format is DiskFormat.FAT32:
            partition_type = 0x0C
        else:
            partition_type = 0x06

        core_mbr.write_single_partition_mbr(
            target_path,
            partition=core_mbr.PartitionEntry(
                bootable=True,
                partition_type=partition_type,
                first_lba=start_lba,
                sector_count=partition_sectors,
                chs_heads=partition_chs_heads,
                chs_spt=partition_chs_spt,
            ),
        )

        partition_offset_bytes = start_lba * 512
        partition_image = f"{target_path}@@{partition_offset_bytes}"

        # Filesystem layout step:
        # - msdos33_layout: skip mformat. DOS 3.30 FORMAT C: /S writes
        #   the FAT/BPB from scratch inside QEMU. Zero the first 2 MiB
        #   so FORMAT doesn't see a stale BPB and try to preserve it.
        # - msdos5 / msdos622: same FORMAT-from-scratch approach.  Plain
        #   ``SYS C:`` on DOS 5/6 didn't transfer system files on
        #   mformat-prepared >=16 MiB partitions (DOS's SYS is
        #   conservative about re-laying-out an existing BPB).  FORMAT
        #   /S writes everything from scratch and produces an
        #   authentic VBR + system-file layout.
        # - pcdos71_layout: same idea -- FORMAT32 inside QEMU writes the
        #   FAT32 BPB and boot sector. Zero a wider region (the FAT32
        #   reserved-sectors area is larger; FSInfo + backup BPB live at
        #   sector 6 by default).
        # - msdos71: mformat the FAT32 partition. Win95 OSR2 SYS A: C:
        #   preserves the existing BPB and rewrites only the boot code
        #   (and the OEM string to 'MSWIN4.1'), so an mformat'd partition
        #   is the right starting state.
        # - compaq331 / msdos331: use mformat for a DOS-3-compatible
        #   layout (reserved_sec_count=1) that SYS C: will accept.
        # - everything else: standard mformat with -T/-H.
        format_from_scratch_modes = (
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.PCDOS2000,
        )
        msdos5_layout = (
            request.boot_mode in format_from_scratch_modes
            or (
                request.boot_mode is BootMode.IBM8088
                and request.ibm_dos_version is IBMDOSVersion.DOS50
            )
        )
        if msdos33_layout or msdos5_layout:
            self._zero_image_region(target_path, partition_offset_bytes, 2 * 1024 * 1024)
        elif pcdos71_layout:
            self._zero_image_region(target_path, partition_offset_bytes, 4 * 1024 * 1024)
        else:
            format_cmd: list[str] = [
                "mformat",
                "-i",
                partition_image,
                "-T",
                str(partition_sectors),
                "-H",
                str(start_lba),
            ]
            label = normalize_label(request.label)
            if label:
                format_cmd += ["-v", label]
            if request.disk_format is DiskFormat.FAT32:
                format_cmd.append("-F")
            format_cmd.append("::")
            self.runner.run(format_cmd)

        # XT-class machine targets (MartyPC Xebec on msdos33-layout) need
        # an MS-DOS 3.3-style MBR + track-aligned partition entry that
        # MartyPC's pre-LBA Xebec controller will accept. Rewrite the
        # MBR here, while QEMU isn't running and we have exclusive file
        # access. The new partition entry points subsequent FORMAT C: /S
        # at LBA = spt, which is what real DOS 3.3 FDISK produces on MFM
        # controllers.
        if _needs_xt_class_mbr_rewrite(request):
            spec = request.martypc_xebec_drive_type.spec
            fs_type = 0x01 if request.disk_format is DiskFormat.FAT12 else 0x04
            self._rewrite_mbr_for_xt_class(
                vhd_path=target_path,
                cylinders=spec.cylinders,
                heads=spec.heads,
                sectors_per_track=spec.sectors_per_track,
                fs_type=fs_type,
            )

        # Static-template boot installer path: FreeDOS only.  PCDOS
        # used to live here too, but commit bce776f (Linux) routed it
        # through the same QEMU FORMAT C: /S pipeline as PCDOS7.  The
        # Windows path missed that change and was running BOTH the
        # static-template install *and* the QEMU install for PCDOS,
        # which failed because the partition is unformatted at this
        # point (the format-from-scratch modes intentionally skip
        # mformat — DOS's own FORMAT writes the FAT in the next step).
        # Removing PCDOS from this branch leaves the QEMU install path
        # below as the sole installer, matching Linux behavior.
        #
        # Everything else legacy -- MSDOS5, MSDOS622, MSDOS71, PCDOS7,
        # IBM8088, PCDOS71, COMPAQ331, MSDOS331, MSDOS33 -- has moved
        # to the QEMU SYS/FORMAT install path because their static
        # templates were extracted from FLOPPY boot sectors that don't
        # work on an HDD partition.
        if request.boot_mode is BootMode.FREEDOS:
            assets = self.boot_resolver.resolve(request)
            partition_ref = PartitionRef.from_image(
                image_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            self.boot_installer.make_partition_bootable(
                disk_device=str(target_path),
                partition_device=partition_image,
                disk_format=request.disk_format,
                assets=assets,
                bios_chs=fat_bios_chs,
                boot_mode=request.boot_mode,
                partition_ref=partition_ref,
            )

        # Legacy DOS modes that use the QEMU SYS install: MS-DOS 3.30,
        # MS-DOS 3.31, Compaq DOS 3.31, MS-DOS 7.10, IBM DOS 3.3 (via
        # ibm8088), PC-DOS 7.1.
        if legacy_qemu_install:
            # compaq331 / msdos331 / msdos71 / pcdos71 need an MBR IPL
            # written now — the QEMU SYS / FORMAT32 step writes the
            # partition VBR but not the MBR's boot code, so bytes 0-439
            # of the disk are zeroes and the BIOS hangs immediately on
            # the invalid instruction stream when it jumps to the MBR.
            #
            # msdos33 / ibm8088+dos33 also need an MBR IPL: DOS 3.30
            # FORMAT C: /S writes the *partition VBR* but it does NOT
            # write sector 0 of the disk (that was always FDISK's job
            # in real DOS).  Without an MBR IPL the BIOS jumps to a
            # zero-filled sector 0 on boot and the machine either
            # silently exits (modern emulators) or hangs at a blinking
            # cursor (real hardware).  An earlier comment here claimed
            # FORMAT wrote both MBR and VBR -- that was incorrect.
            if request.boot_mode in (
                BootMode.COMPAQ2,
                BootMode.COMPAQ331,
                BootMode.MSDOS331,
                BootMode.MSDOS33,
                BootMode.MSDOS5,
                BootMode.MSDOS622,
                BootMode.MSDOS71,
                BootMode.PCDOS,
                BootMode.PCDOS7,
                BootMode.PCDOS2000,
                BootMode.PCDOS71,
                BootMode.IBM8088,
            ):
                self.boot_installer.write_mbr_only(
                    disk_device=str(target_path),
                    image_path=target_path,
                )
                # FAT16 BPB heads/spt patch only applies to FAT16 legacy
                # modes -- PC-DOS 7.1 and MS-DOS 7.10 boot FAT32 with a
                # different BPB extension layout, and SYS C: / FORMAT32
                # already wrote correct geometry matching the VHD footer.
                if (
                    (
                        request.boot_mode in (
                            BootMode.COMPAQ331,
                            BootMode.MSDOS331,
                            BootMode.MSDOS5,
                            BootMode.MSDOS622,
                            BootMode.PCDOS7,
                            BootMode.PCDOS2000,
                        )
                        or (
                            request.boot_mode is BootMode.PCDOS71
                            and request.disk_format is not DiskFormat.FAT32
                        )
                    )
                    and fat_bios_chs is not None
                ):
                    self.boot_installer.patch_fat16_bpb_geometry(
                        partition_device=partition_image,
                        bios_chs=fat_bios_chs,
                        image_path=target_path,
                        partition_offset_bytes=partition_offset_bytes,
                    )

            self._install_legacy_dos_via_qemu(
                request=request,
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            # PC-DOS 7.1's FORMAT32 /S writes the system files with
            # only the Archive bit set. PC-DOS 7.1's boot sector locates
            # IBMBIO.COM by scanning for an entry with +System+Hidden
            # attributes in the root directory — without those bits the
            # loader prints "Non-System disk" or silently fails to
            # transfer control. Per the vogons.org PC-DOS 7.1 guide
            # (step 8) we apply +R +S +H ourselves.
            if request.boot_mode is BootMode.PCDOS71:
                for sysfile in ("IBMBIO.COM", "IBMDOS.COM"):
                    self.runner.run(
                        [
                            "mattrib",
                            "-i",
                            partition_image,
                            "+r",
                            "+s",
                            "+h",
                            f"::{sysfile}",
                        ],
                        check=False,
                    )
            self._stage_legacy_dos_full_profile_payload(
                request=request,
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
            )
            # Patch the partition's FAT BPB heads/spt so the VBR's
            # internal CHS calculations match what the target BIOS will
            # present at boot time.
            if request.boot_mode is BootMode.PCDOS71 and request.disk_format is DiskFormat.FAT32:
                # FAT32 on a >504 MB drive: AT BIOSes apply ECHS bit-
                # shift translation (e.g. 64h/63s for a 1 GB drive). The
                # BPB must use the translated heads/spt so the VBR's
                # INT 13h CHS reads land on the right sectors. Without
                # this, 86Box shows a blinking cursor after the MBR
                # loads (silent VBR failure).
                self._patch_partition_bpb_to_translated_geometry(
                    vhd_path=target_path,
                    partition_offset_bytes=partition_offset_bytes,
                )
            elif request.boot_mode is not BootMode.MSDOS71:
                # FAT16 modes: QEMU SYS install leaves QEMU's SeaBIOS
                # geometry in the BPB. Patch to the VHD footer CHS that
                # the target controller will actually present (16h/63s
                # on generic targets; MartyPC Xebec drive geometry on
                # Xebec targets — that's what avoids the "two beeps +
                # ROM-BASIC" boot failure on Xebec).
                #
                # MSDOS71 (Win95 OSR2 SYS A: C:) is intentionally left
                # alone — the existing mformat-laid BPB has worked on
                # 86Box historically. If 86Box ever shows a blinking
                # cursor on msdos71, the fix is the same as pcdos71:
                # patch BPB to translated geometry.
                self._patch_partition_bpb_to_footer_geometry(
                    vhd_path=target_path,
                    partition_offset_bytes=partition_offset_bytes,
                )

        custom_payload = self._resolve_custom_payload_path(request)
        if custom_payload is not None:
            self._copy_custom_payload_to_vhd_via_mtools(
                vhd_path=target_path,
                partition_offset_bytes=partition_offset_bytes,
                source_dir=custom_payload,
            )

    def _create_and_prepare_fourdos(self, request: CreateRequest) -> None:
        """Build a host DOS VHD/IMG and overlay the 4DOS shell on top.

        Phase 14F-full: 4DOS is a shell overlay; the host DOS owns the
        VBR / IO.SYS / MSDOS.SYS / COMMAND.COM.  After the host build
        completes we copy 4DOS.COM (and helpers) to C:\\4DOS\\ and write
        a CONFIG.SYS that points SHELL= at the 4DOS interpreter.

        ``request.host_boot_mode`` selects the underlying DOS.  We
        validate the host choice in :meth:`_validate_create_request`;
        by the time we get here it is guaranteed non-None and
        non-FOURDOS.
        """
        if request.host_boot_mode is None or request.host_boot_mode is BootMode.FOURDOS:
            raise ValidationError(
                "4DOS overlay reached the install step without a valid host "
                "boot mode -- this indicates a validation gap."
            )

        # 1. Run the host build with the user's custom payload deferred
        #    until after the overlay (so 4DOS-overlay-written CONFIG.SYS
        #    isn't clobbered by a user-supplied one with the same name).
        host_request = _dataclass_replace(
            request,
            boot_mode=request.host_boot_mode,
            host_boot_mode=None,
            custom_payload_path=None,
        )
        self.create_and_prepare(host_request)

        # 2. Resolve 4DOS install media.  Errors here are loud --
        #    we just built a bootable host disk that the user will
        #    notice is missing 4DOS.
        assets_dir = resolve_fourdos_assets_dir(request.boot_assets_path)

        # 3. Locate the host partition so mtools can write to it.
        target_path = request.path.expanduser().resolve()
        if request.media_type is MediaType.IMG:
            partition_target = str(target_path)
        else:
            entry = core_mbr.read_partition_entry(target_path, slot=0)
            if entry is None:
                raise ValidationError(
                    f"4DOS overlay: no MBR partition found in {target_path}.  "
                    "Host DOS build did not produce a partitioned VHD."
                )
            partition_offset_bytes = entry.first_lba * 512
            partition_target = f"{target_path}@@{partition_offset_bytes}"

        # 4. Overlay 4DOS + write CONFIG.SYS / AUTOEXEC.BAT.
        install_fourdos_overlay(
            runner=self.runner,
            context=FourDosOverlayContext(
                assets_dir=assets_dir,
                partition_target=partition_target,
            ),
        )

        # 5. Now apply the user's custom payload (deferred from step 1).
        custom_payload = self._resolve_custom_payload_path(request)
        if custom_payload is not None:
            if request.media_type is MediaType.IMG:
                if self.backend.supports_kernel_mount:
                    self._copy_custom_payload_to_filesystem(
                        partition_device=str(target_path),
                        source_dir=custom_payload,
                        boot_mode=request.boot_mode,
                    )
                else:
                    self._copy_custom_payload_to_img_via_mtools(
                        image_path=target_path,
                        source_dir=custom_payload,
                        boot_mode=request.boot_mode,
                    )
            else:
                entry = core_mbr.read_partition_entry(target_path, slot=0)
                if entry is not None:
                    self._copy_custom_payload_to_vhd_via_mtools(
                        vhd_path=target_path,
                        partition_offset_bytes=entry.first_lba * 512,
                        source_dir=custom_payload,
                    )

    def _create_and_prepare_floppy_img(self, request: CreateRequest) -> None:
        target_path = request.path.expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            if request.overwrite:
                target_path.unlink()
            else:
                raise ValidationError(f"IMG already exists: {target_path}")

        request.path = target_path
        assets = None
        if request.img_system_format and request.boot_mode is not BootMode.NONE:
            assets = self.boot_resolver.resolve(request)
            self._align_floppy_type_from_source_media(request, assets.source_image_size_bytes)

        self._create_fixed_img(target_path, request.floppy_type)
        self._format_floppy_img(target_path, floppy_type=request.floppy_type, label=normalize_label(request.label))
        if assets is not None:
            verify_legacy_layout = request.boot_mode in {
                BootMode.MSDOS71,
                BootMode.IBM8088,
                BootMode.MSDOS33,
                BootMode.MSDOS331,
                BootMode.MSDOS5,
                BootMode.MSDOS622,
                BootMode.PCDOS,
                BootMode.PCDOS7,
                BootMode.PCDOS2000,
                BootMode.COMPAQ331,
            }
            self.boot_installer.make_floppy_bootable(
                image_path=target_path,
                assets=assets,
                boot_mode=request.boot_mode,
                floppy_type=request.floppy_type,
                verify_legacy_layout=verify_legacy_layout,
            )
        custom_payload = self._resolve_custom_payload_path(request)
        if custom_payload is not None:
            if self.backend.supports_kernel_mount:
                self._copy_custom_payload_to_filesystem(
                    partition_device=str(target_path),
                    source_dir=custom_payload,
                    boot_mode=request.boot_mode,
                )
            else:
                # No kernel mount available (Windows): use mtools to write
                # directly into the FAT12 floppy. Matches Linux behavior of
                # skipping protected DOS system files so img_system_format's
                # IO.SYS / IBMBIO.COM etc. aren't clobbered.
                self._copy_custom_payload_to_img_via_mtools(
                    image_path=target_path,
                    source_dir=custom_payload,
                    boot_mode=request.boot_mode,
                )

    def _create_fixed_img(self, path: Path, floppy_type: FloppyType) -> None:
        with path.open("wb") as handle:
            handle.truncate(floppy_type.size_bytes)

    def _install_legacy_dos_via_qemu(
        self,
        *,
        request: CreateRequest,
        vhd_path: Path,
        partition_offset_bytes: int | None = None,
    ) -> None:
        """Boot the appropriate legacy DOS in QEMU and run SYS C: on the VHD.

        Dispatches on ``request.boot_mode`` to pick the correct install
        image + profile (Compaq DOS 3.31 vs MS-DOS 3.30). Produces an
        authentic DOS boot sector and copies system files exactly the way
        installing on real hardware would.

        ``partition_offset_bytes`` defaults to ``_partition_offset_bytes_for(request)``
        when not provided so callers don't have to thread it through.
        """
        descriptor = _legacy_dos_install_descriptor(request)
        if descriptor is None:
            raise ValidationError(
                f"No QEMU SYS install descriptor for boot mode {request.boot_mode.value}."
            )

        boot_assets_dir = self._resolve_legacy_dos_assets_dir(
            request=request,
            fallback_dirs=descriptor.asset_fallback_dirs,
            label=descriptor.label,
        )
        # PCDOS7 (and the generic PCDOS alias) ship their install floppy
        # in IBM's LOADDSKF compressed format that mtools can't read.
        # Extract it on-demand via LOADDSKF.EXE inside DOSBox-X (cached
        # after first run) and use the resulting raw 1.44 MB IMG as the
        # install_image.
        if request.boot_mode in (BootMode.PCDOS, BootMode.PCDOS7):
            from ._pcdos7_loaddskf import extract_pcdos7_install_floppy

            # For PCDOS the user may have dropped their own pcdos install
            # media in dosassets/pcdos/ -- prefer that if a usable image
            # is already present, otherwise fall back to pcdos7 LOADDSKF.
            install_image = None
            if request.boot_mode is BootMode.PCDOS:
                install_image = self._find_legacy_dos_install_image(
                    directory=boot_assets_dir,
                    preferred_names=descriptor.preferred_image_names,
                    system_file_marker=descriptor.system_file_marker,
                )
            if install_image is None:
                install_image = extract_pcdos7_install_floppy(boot_assets_dir)
        elif request.boot_mode is BootMode.COMPAQ2:
            # COMPAQ2 ships as a single .7z archive containing a 360 KB
            # disk01.img (the user did a "direct download" of the
            # WinWorldPC archive rather than pre-extracting).  Auto-
            # extract via py7zr, cache the result, and use the
            # bundled disk01.img as the install_image.  Short-circuits
            # to a raw IMG if the user has already extracted.
            from ._legacy_dos_archive import extract_legacy_dos_install_archive

            install_image = extract_legacy_dos_install_archive(boot_assets_dir)
        else:
            install_image = self._find_legacy_dos_install_image(
                directory=boot_assets_dir,
                preferred_names=descriptor.preferred_image_names,
                system_file_marker=descriptor.system_file_marker,
            )
        if install_image is None:
            base_msg = (
                f"{descriptor.label} boot mode requires a bootable install diskette "
                f"(with SYS.COM and {descriptor.system_file_marker}) in the boot "
                f"assets directory. Preferred names: "
                f"{', '.join(descriptor.preferred_image_names)}. "
                f"Checked: {boot_assets_dir}"
            )
            readme = self.boot_resolver._read_asset_readme(boot_assets_dir)
            if readme:
                base_msg = (
                    f"{base_msg}\n\n"
                    f"Per the local readme for this mode:\n"
                    f"------------------------------------------------------------\n"
                    f"{readme}\n"
                    f"------------------------------------------------------------\n"
                )
            raise ValidationError(base_msg)

        cache_root = app_cache_dir() / "legacy-dos-install"
        cache_root.mkdir(parents=True, exist_ok=True)
        installer = LegacyDosQemuInstaller(
            runner=self.runner,
            cache_root=cache_root,
        )
        profile = descriptor.profile_builder(install_image, boot_assets_dir)
        # MBR partition usually starts at LBA 63 (parted's legacy DOS
        # layout). XT-class targets (MartyPC Xebec on msdos33) get a
        # track-aligned partition at LBA = spt instead — see
        # ``_partition_offset_bytes_for``.
        if partition_offset_bytes is None:
            partition_offset_bytes = _partition_offset_bytes_for(request)
        installer.install_system(
            vhd_path=vhd_path,
            profile=profile,
            partition_offset_bytes=partition_offset_bytes,
        )
        # The Win95 OSR2 Emergency Boot Disk (Boot.img) ships a 6-byte
        # stub MSDOS.SYS containing only ``;SYS\r\n``.  ``SYS A: C:``
        # copies it verbatim to C:.  OSR2 IO.SYS then reads MSDOS.SYS on
        # boot, fails to find the required ``[Paths]`` / ``[Options]``
        # sections, and bombs with an "I/O error" before reaching the
        # DOS prompt.  Replace the stub with a canonical hard-disk
        # MSDOS.SYS configured for DOS-only boot (no WIN.COM autostart).
        if profile.install_method == "sys_w95":
            self._write_osr2_msdos_sys(
                vhd_path=vhd_path,
                partition_offset_bytes=partition_offset_bytes,
            )

    def _write_osr2_msdos_sys(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
    ) -> None:
        """Write a canonical Win95-OSR2 hard-disk ``MSDOS.SYS`` to C:\\.

        Required because the OSR2 Emergency Boot Disk's own MSDOS.SYS
        is a 6-byte stub (``;SYS\\r\\n``) that ``SYS A: C:`` propagates
        to the freshly-installed VHD.  IO.SYS reads MSDOS.SYS during
        boot to locate WIN.COM and read boot-time flags; an
        empty/stub file causes an I/O error before any DOS code runs.

        The file written here mirrors what an authentic Windows 95
        OSR2 SETUP run would leave on a DOS-only install: BootGUI=0
        keeps boot at the ``C:\\>`` prompt, ``BootMulti=0`` skips the
        dual-boot menu, and the padding block keeps the file >1024
        bytes (MS Tools have historically rejected MSDOS.SYS files
        smaller than that).
        """
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"
        payload = self._build_osr2_msdos_sys_content()
        scratch_root = Path(
            os.environ.get("TEMP", os.environ.get("TMPDIR", "."))
        )
        scratch_root.mkdir(parents=True, exist_ok=True)
        scratch = scratch_root / f"dosforge-msdos-sys-{uuid4().hex[:8]}"
        scratch.write_bytes(payload)
        try:
            self.runner.run(
                [
                    "mattrib",
                    "-i",
                    partition_image,
                    "-r",
                    "-h",
                    "-s",
                    "::MSDOS.SYS",
                ],
                check=False,
            )
            self.runner.run(
                [
                    "mcopy",
                    "-o",
                    "-i",
                    partition_image,
                    str(scratch),
                    "::MSDOS.SYS",
                ],
            )
            self.runner.run(
                [
                    "mattrib",
                    "-i",
                    partition_image,
                    "+r",
                    "+h",
                    "+s",
                    "::MSDOS.SYS",
                ],
            )
        finally:
            try:
                scratch.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _build_osr2_msdos_sys_content() -> bytes:
        """Canonical Win95 OSR2 ``MSDOS.SYS`` for a DOS-only hard-disk boot.

        Matches the layout produced by a real OSR2 SETUP into a DOS-only
        partition: ``BootGUI=0`` keeps boot in real-mode DOS, the rest
        are the canonical defaults that OSR2 expects.  ``Network`` and
        ``DoubleBuffer`` keys are intentionally omitted so IO.SYS loads
        the genuine ``IFSHLP.SYS`` + ``DBLBUFF.SYS`` we stage on C:\\
        (see ``_stage_msdos71_osr2_dos_payload``).
        """
        lines = [
            b"[Paths]",
            b"WinDir=C:\\",
            b"WinBootDir=C:\\",
            b"HostWinBootDrv=C",
            b"",
            b"[Options]",
            b"BootMulti=0",
            b"BootGUI=0",
            b"BootDelay=0",
            b"Logo=0",
            b"AutoScan=1",
            b"",
            b";",
            b";The following lines are required for compatibility with other programs.",
            b";Do not remove them (MSDOS.SYS needs to be >1024 bytes).",
            b";",
        ]
        body = b"\r\n".join(lines) + b"\r\n"
        pad_line = b";" + b"x" * 76 + b"\r\n"
        while len(body) < 1100:
            body += pad_line
        return body

    # Loose 1996-08-24-dated MS-DOS-mode utilities at the root of the
    # OSR2 Emergency Boot Disk.  These get copied verbatim into C:\DOS\.
    _OSR2_BOOT_IMG_LOOSE_DOS_TOOLS: tuple[str, ...] = (
        "FDISK.EXE",
        "EXTRACT.EXE",
        "HIMEM.SYS",
    )

    def _stage_msdos71_osr2_boot_essentials(
        self,
        *,
        request: CreateRequest,
        partition_image: str,
    ) -> bool:
        """Stage OSR2 boot-time essentials at C:\\ root regardless of profile.

        OSR2's IO.SYS implicitly loads ``HIMEM.SYS`` from C:\\ during
        the ``Starting Windows 95...`` boot phase (per the ``WinDir=C:\\``
        line we write to MSDOS.SYS).  If it's not present at the root,
        the boot prints "The following file is missing or corrupted:
        C:\\HIMEM.SYS" before reaching the DOS prompt.

        This is a **boot requirement**, not a "tool" — it must happen
        for every install profile (MINIMAL too), independent of whether
        the user opted into the C:\\DOS\\ utilities payload.

        Returns ``True`` if HIMEM.SYS was successfully copied to C:\\,
        ``False`` if the OSR2 install media cannot be located (in which
        case the boot warning will appear but the disk still boots).
        """
        descriptor = _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.MSDOS71]
        boot_assets_dir = self._resolve_legacy_dos_assets_dir(
            request=request,
            fallback_dirs=descriptor.asset_fallback_dirs,
            label=descriptor.label,
        )
        install_image = self._find_legacy_dos_install_image(
            directory=boot_assets_dir,
            preferred_names=descriptor.preferred_image_names,
            system_file_marker=descriptor.system_file_marker,
        )
        if install_image is None:
            return False
        staging_dir = Path(tempfile.mkdtemp(prefix="dosforge-msdos71-boot-"))
        try:
            himem_scratch = staging_dir / "HIMEM.SYS"
            self.runner.run(
                [
                    "mcopy",
                    "-i",
                    str(install_image),
                    "-n",
                    "::/HIMEM.SYS",
                    "HIMEM.SYS",
                ],
                cwd=staging_dir,
                check=False,
            )
            if not himem_scratch.is_file() or himem_scratch.stat().st_size == 0:
                return False
            self.runner.run(
                [
                    "mcopy",
                    "-i",
                    partition_image,
                    "-n",
                    str(himem_scratch),
                    "::/HIMEM.SYS",
                ],
                cwd=staging_dir,
                check=False,
            )
            return True
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _stage_msdos71_osr2_dos_payload(
        self,
        *,
        request: CreateRequest,
        partition_image: str,
    ) -> bool:
        """Stage authentic OSR2 DOS utilities into C:\\DOS\\.

        Sourced exclusively from the user's OSR2 install media
        (typically ``dosassets/w95/Boot.img``).  Two streams are
        merged into a scratch directory and then bulk-copied to the
        VHD with :meth:`BootInstaller._copy_payload_via_mtools`:

        1. Loose 1996-08-24-dated binaries from the floppy root —
           ``FDISK.EXE``, ``EXTRACT.EXE``, ``HIMEM.SYS``.
        2. The contents of the embedded ``ebd.cab`` Microsoft uses
           to ship MS-DOS-mode utilities (``ATTRIB.EXE``,
           ``FORMAT.COM``, ``EDIT.COM``, ``SYS.COM``,
           ``SCANDISK.EXE``, …) — the bulk of the cab is OSR2-vintage
           too.

        Returns ``True`` on success, ``False`` if no install image
        can be located (in which case the caller should leave
        C:\\DOS\\ untouched rather than write a half-curated set).
        """
        descriptor = _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.MSDOS71]
        boot_assets_dir = self._resolve_legacy_dos_assets_dir(
            request=request,
            fallback_dirs=descriptor.asset_fallback_dirs,
            label=descriptor.label,
        )
        install_image = self._find_legacy_dos_install_image(
            directory=boot_assets_dir,
            preferred_names=descriptor.preferred_image_names,
            system_file_marker=descriptor.system_file_marker,
        )
        if install_image is None:
            return False

        staging_dir = Path(tempfile.mkdtemp(prefix="dosforge-msdos71-tools-"))
        try:
            for name in self._OSR2_BOOT_IMG_LOOSE_DOS_TOOLS:
                self.runner.run(
                    [
                        "mcopy",
                        "-i",
                        str(install_image),
                        "-n",
                        f"::/{name}",
                        name,
                    ],
                    cwd=staging_dir,
                    check=False,
                )

            cab_scratch = staging_dir / "ebd.cab"
            cab_result = self.runner.run(
                [
                    "mcopy",
                    "-i",
                    str(install_image),
                    "-n",
                    "::/ebd.cab",
                    "ebd.cab",
                ],
                cwd=staging_dir,
                check=False,
            )
            if (
                cab_result.returncode == 0
                and cab_scratch.is_file()
                and cab_scratch.stat().st_size > 0
            ):
                self._expand_msdos_cab(cab_scratch, staging_dir)
            try:
                cab_scratch.unlink()
            except FileNotFoundError:
                pass

            for child in list(staging_dir.iterdir()):
                if child.is_file() and child.stat().st_size == 0:
                    child.unlink()

            if not any(staging_dir.iterdir()):
                return False

            self.boot_installer._copy_payload_via_mtools(
                partition_device=partition_image,
                payload_dir=staging_dir,
                payload_target_dir="DOS",
            )
            return True
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _expand_msdos_cab(self, cab_path: Path, destination: Path) -> None:
        """Expand a Microsoft CAB archive into ``destination``.

        Uses Windows' built-in ``expand.exe`` (always on PATH via
        ``%SystemRoot%\\System32``) on Windows, and ``cabextract`` on
        other platforms (a common package on Linux/macOS).
        """
        destination.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            argv = ["expand.exe", str(cab_path), "-F:*", str(destination)]
        else:
            argv = ["cabextract", "-d", str(destination), str(cab_path)]
        try:
            self.runner.run(argv)
        except DependencyError as exc:
            tool = argv[0]
            raise DependencyError(
                f"Missing external command '{tool}' required to expand "
                f"MS-CAB archives.  Install it (Windows ships expand.exe "
                f"with the OS at %SystemRoot%\\System32; on Linux/macOS "
                f"install the 'cabextract' package)."
            ) from exc

    def _resolve_legacy_dos_assets_dir(
        self,
        *,
        request: CreateRequest,
        fallback_dirs: tuple[str, ...],
        label: str,
    ) -> Path:
        # IBM8088 mode keeps version-specific assets under a versioned
        # subdir (e.g. <root>/dos33/DISK01.IMG, mirroring the directory
        # layout used by the BootAssetResolver). Try that first so users
        # who organize their boot assets that way don't get a confusing
        # "no install diskette found" error.
        version_subdir = (
            "dos33"
            if (
                request.boot_mode is BootMode.IBM8088
                and request.ibm_dos_version is IBMDOSVersion.DOS33
            )
            else None
        )
        if request.boot_assets_path is not None:
            # Bare names (e.g. "msdos33") map to ./dosassets/msdos33/.
            resolved = resolve_dos_asset_dir(request.boot_assets_path)
            root = resolved if resolved is not None else request.boot_assets_path.expanduser().resolve()
            if version_subdir is not None:
                versioned = (root / version_subdir).resolve()
                if versioned.is_dir():
                    return versioned
            return root
        for fallback in fallback_dirs:
            candidate = resolve_dos_asset_dir(fallback)
            if candidate is None:
                continue
            if version_subdir is not None:
                versioned = (candidate / version_subdir).resolve()
                if versioned.is_dir():
                    return versioned
            return candidate
        searched = ", ".join(
            describe_dos_asset_locations(name) for name in fallback_dirs
        )
        raise ValidationError(
            f"{label} boot mode requires a local boot assets directory. "
            f"Searched: {searched or '(no defaults configured)'}. "
            f"Drop the install media into ./{DOS_ASSETS_SUBDIR}/<name>/ "
            "(see ./dosassets/readme.txt for the expected layout) or pass "
            "--boot-assets-path /full/path/to/dir."
        )

    def _find_legacy_dos_install_image(
        self,
        *,
        directory: Path,
        preferred_names: tuple[str, ...],
        system_file_marker: str,
    ) -> Path | None:
        if not directory.is_dir():
            return None
        # Preferred filename match first.
        upper_preferred = {name.upper() for name in preferred_names}
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.name.upper() in upper_preferred:
                return entry
        # Heuristic fallback: any *.img/*.ima that contains SYS.COM and the
        # DOS-specific system file marker (IBMBIO.COM, IO.SYS, etc.).
        for entry in sorted(directory.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in (".img", ".ima"):
                continue
            sys_check = self.runner.run(
                ["mdir", "-i", str(entry), "-a", "::SYS.COM"],
                check=False,
            )
            if sys_check.returncode != 0:
                continue
            marker_check = self.runner.run(
                ["mdir", "-i", str(entry), "-a", f"::{system_file_marker}"],
                check=False,
            )
            if marker_check.returncode == 0:
                return entry
        return None

    # Backwards-compatible thin shims for tests / external callers.
    def _install_compaq331_via_qemu(
        self,
        *,
        request: CreateRequest,
        vhd_path: Path,
    ) -> None:
        self._install_legacy_dos_via_qemu(request=request, vhd_path=vhd_path)

    def _resolve_compaq331_assets_dir(self, request: CreateRequest) -> Path:
        return self._resolve_legacy_dos_assets_dir(
            request=request,
            fallback_dirs=("compaq331", "msdos331"),
            label="Compaq DOS 3.31",
        )

    def _find_compaq331_startup_image(self, directory: Path) -> Path | None:
        return self._find_legacy_dos_install_image(
            directory=directory,
            preferred_names=("STARTUP.IMG", "STARTUP.IMA"),
            system_file_marker="IBMBIO.COM",
        )

    def _stage_legacy_dos_full_profile_payload(
        self,
        *,
        request: CreateRequest,
        vhd_path: Path,
        partition_offset_bytes: int,
    ) -> None:
        """Stage the FULL profile's DOS tools + startup files onto C: via mtools.

        Called after :meth:`_install_legacy_dos_via_qemu` for the legacy
        DOS QEMU install path. The QEMU FORMAT C: /S step only writes
        IO.SYS / MSDOS.SYS (or IBMBIO.COM / IBMDOS.COM) + COMMAND.COM.
        When the user picks the ``FULL`` install profile ("Tools +
        Startup files") the BootAssetResolver also exposes:

        - ``assets.fdos_payload_dir``: a directory of DOS utilities
          (FDISK.COM, FORMAT.COM, EDIT.COM, etc.) to copy into
          ``C:\\<payload_target_dir>\\`` (typically C:\\DOS).
        - ``assets.system_files``: CONFIG.SYS and AUTOEXEC.BAT (already
          normalized to point at the correct install_dir per
          media_type — C:\\DOS for VHD).

        Skip everything when the resolved profile is MINIMAL; FORMAT C:
        /S has already produced a bootable disk in that case.

        Exception: MS-DOS 7.10 (Win95 OSR2) always stages C:\\HIMEM.SYS
        and a minimal CONFIG.SYS + AUTOEXEC.BAT, even for MINIMAL,
        because OSR2's IO.SYS implicitly loads C:\\HIMEM.SYS during
        ``Starting Windows 95...`` and missing it prints a boot warning.
        """
        # MS-DOS 7.10 via the Win95 OSR2 install path has no Chinese-
        # release crossover allowed (DOS71_1S.PAK is from a different
        # 7.1 lineage and would violate the per-DOS authenticity rule).
        # Instead, source DOS-mode utilities directly from the OSR2
        # install media the user supplied (dosassets/w95/Boot.img):
        # loose 1996-08-24-dated binaries at the floppy root plus the
        # ``ebd.cab`` archive Microsoft uses to ship FORMAT.COM,
        # SCANDISK.EXE, EDIT.COM, etc.  Everything that lands in
        # C:\\DOS\\ originates from the same Boot.img the SYS install
        # ran from.
        if request.boot_mode is BootMode.MSDOS71:
            partition_image = f"{vhd_path}@@{partition_offset_bytes}"
            # ALWAYS stage HIMEM.SYS at C:\ — required by OSR2 IO.SYS
            # regardless of install profile.  IFSHLP.SYS + DBLBUFF.SYS
            # are staged unconditionally as well, by the QEMU SYS
            # install flow itself (vhd_pre_install_copies in
            # ``msdos71_profile``), because they live inside Quantum-
            # compressed cabinets only host-side 7-Zip can decompress.
            essentials_staged = self._stage_msdos71_osr2_boot_essentials(
                request=request,
                partition_image=partition_image,
            )
            install_dir = ""
            if request.msdos_install_profile is MSDOSInstallProfile.FULL:
                tools_staged = self._stage_msdos71_osr2_dos_payload(
                    request=request,
                    partition_image=partition_image,
                )
                if tools_staged:
                    install_dir = "DOS"
            if essentials_staged:
                self._write_sane_msdos_startup_files(
                    partition_image=partition_image,
                    install_dir=install_dir,
                )
            return
        if request.msdos_install_profile is not MSDOSInstallProfile.FULL:
            return
        assets = self.boot_resolver.resolve(request)
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"

        # 1. Stage the DOS tools payload under C:\<payload_target_dir>\.
        # Delegate to BootInstaller._copy_payload_via_mtools so that
        # MS-DOS SETUP-style compressed payload files (e.g. ATTRIB.EX_,
        # DISKCOPY.CO_, HIMEM.SY_ -- SZDD or KWAJ format) are expanded
        # to their canonical names (ATTRIB.EXE, DISKCOPY.COM, HIMEM.SYS)
        # exactly like a real SETUP.EXE run would.  Skipping the
        # expansion leaves C:\DOS\ littered with unbootable underscore-
        # suffixed archives -- DIR shows them but the user can't run
        # them.
        if assets.fdos_payload_dir is not None and assets.fdos_payload_dir.is_dir():
            target_dir = (assets.payload_target_dir or "DOS").strip("/\\").upper()
            self.boot_installer._copy_payload_via_mtools(
                partition_device=partition_image,
                payload_dir=assets.fdos_payload_dir,
                payload_target_dir=target_dir,
            )

        # 2. Stage CONFIG.SYS / AUTOEXEC.BAT to C:\. Skip the DOS system
        # files (IO.SYS, MSDOS.SYS, IBMBIO.COM, IBMDOS.COM, COMMAND.COM)
        # — they were written by SYS C: / FORMAT C: /S with the correct
        # +s +h attributes already, and overwriting them strips those
        # attributes.
        protected_system_files = {
            "IO.SYS",
            "MSDOS.SYS",
            "IBMBIO.COM",
            "IBMDOS.COM",
            "KERNEL.SYS",
            "COMMAND.COM",
        }
        for name, src in (assets.system_files or {}).items():
            if name.upper() in protected_system_files:
                continue
            # AUTOEXEC.BAT and CONFIG.SYS on install diskettes are
            # SETUP-launcher scripts (they run ``setup`` / ``install``
            # to invite the user to install DOS onto a hard disk) --
            # NOT the right content for a hard-disk-installed system.
            # Skip them here; ``_write_sane_msdos_startup_files`` below
            # writes appropriate hard-disk versions for QEMU-install
            # modes after the rest of the staging completes.
            if name.upper() in {"AUTOEXEC.BAT", "CONFIG.SYS"}:
                continue
            if not src.is_file():
                continue
            self.runner.run(
                ["mcopy", "-i", partition_image, "-o", str(src), f"::{name}"],
            )

        # Write canonical hard-disk CONFIG.SYS + AUTOEXEC.BAT.  Without
        # this, FORMAT-install-floppy AUTOEXEC.BAT (``setup``) would
        # silently launch the DOS install wizard at every boot and hang
        # waiting for keypresses.
        self._write_sane_msdos_startup_files(
            partition_image=partition_image,
            install_dir=(assets.payload_target_dir or "DOS").strip("/\\").upper(),
        )

    def _write_sane_msdos_startup_files(
        self,
        *,
        partition_image: str,
        install_dir: str,
    ) -> None:
        """Write a clean hard-disk CONFIG.SYS + AUTOEXEC.BAT to C:\\.

        Replaces whatever shipped on the install floppy (typically a
        SETUP-launcher script that hangs in batch mode) with the
        minimum boot scaffolding a real user would write after
        installing DOS:

          CONFIG.SYS
            FILES=30
            BUFFERS=20

          AUTOEXEC.BAT
            @ECHO OFF
            PATH C:\\;C:\\<install_dir>
            PROMPT $P$G

        Files are staged through a scratch path because mtools doesn't
        accept stdin as a source for ``mcopy``.
        """
        config_sys = (
            b"FILES=30\r\n"
            b"BUFFERS=20\r\n"
        )
        if install_dir:
            path_line = b"PATH C:\\;C:\\" + install_dir.encode("ascii") + b"\r\n"
        else:
            path_line = b"PATH C:\\\r\n"
        autoexec_bat = (
            b"@ECHO OFF\r\n"
            + path_line
            + b"PROMPT $P$G\r\n"
        )
        scratch_root = Path(os.environ.get("TEMP", os.environ.get("TMPDIR", ".")))
        scratch_root.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("CONFIG.SYS", config_sys),
            ("AUTOEXEC.BAT", autoexec_bat),
        ):
            scratch = scratch_root / f"dosforge-startup-{uuid4().hex[:8]}-{name}"
            scratch.write_bytes(payload)
            try:
                self.runner.run(
                    ["mcopy", "-o", "-i", partition_image, str(scratch), f"::{name}"],
                )
            finally:
                try:
                    scratch.unlink()
                except FileNotFoundError:
                    pass

    def _copy_custom_payload_to_vhd_via_mtools(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
        source_dir: Path,
    ) -> None:
        """Copy a directory's contents to C:\\ via mtools (no NBD/mount needed).

        Used by boot modes where the standard mount-based payload copy
        cannot run (because the partition format was finalized by an
        out-of-process step like the Compaq DOS 3.31 QEMU SYS install).
        Subdirectories are recreated with ``mmd`` and files copied with
        ``mcopy``. The partition's FAT16 BPB must already be valid.
        """
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"
        for entry in sorted(source_dir.rglob("*")):
            relative = entry.relative_to(source_dir)
            if _payload_path_is_excluded(relative):
                continue
            dest = "::" + str(relative).replace(os.sep, "/")
            if entry.is_dir():
                self.runner.run(
                    ["mmd", "-i", partition_image, dest],
                    check=False,
                )
            elif entry.is_file():
                self.runner.run(
                    ["mcopy", "-i", partition_image, "-o", str(entry), dest],
                )

    def _copy_custom_payload_to_img_via_mtools(
        self,
        *,
        image_path: Path,
        source_dir: Path,
        boot_mode: BootMode = BootMode.NONE,
    ) -> None:
        """Copy a directory's contents to A:\\ via mtools (no loop mount).

        Floppy-IMG counterpart of ``_copy_custom_payload_to_vhd_via_mtools``.
        Used on backends where ``supports_kernel_mount`` is False
        (Windows). Mirrors the Linux ``_copy_custom_payload_to_filesystem``
        protected-file filter so ``img_system_format``-staged DOS system
        files (IO.SYS, IBMBIO.COM, COMMAND.COM, …) aren't clobbered by
        same-named entries in the user's payload directory.
        """
        protected = self._protected_boot_filenames(boot_mode)
        for entry in sorted(source_dir.rglob("*")):
            relative = entry.relative_to(source_dir)
            if _payload_path_is_excluded(relative):
                continue
            dest = "::" + str(relative).replace(os.sep, "/")
            if entry.is_dir():
                self.runner.run(
                    ["mmd", "-i", str(image_path), dest],
                    check=False,
                )
            elif entry.is_file():
                # Skip protected DOS system files at the root only.
                # Same-named files in subdirectories are passthrough.
                if relative.parent == Path(".") and entry.name.upper() in protected:
                    continue
                self.runner.run(
                    ["mcopy", "-i", str(image_path), "-o", str(entry), dest],
                )

    def _copy_custom_payload_to_filesystem(
        self,
        *,
        partition_device: str,
        source_dir: Path,
        boot_mode: BootMode = BootMode.NONE,
    ) -> None:
        mountpoint = self.mount_root / f"custom-payload-{os.getpid()}-{uuid4().hex[:6]}"
        mountpoint.mkdir(parents=True, exist_ok=True)
        mount_options = f"uid={os.getuid()},gid={os.getgid()},umask=022,shortname=mixed"
        if not partition_device.startswith("/dev/"):
            mount_options = f"loop,{mount_options}"
        mounted = False
        try:
            self.runner.run(
                [
                    "mount",
                    "-t",
                    "vfat",
                    "-o",
                    mount_options,
                    partition_device,
                    str(mountpoint),
                ],
                sudo=True,
            )
            mounted = True
            stat = os.statvfs(mountpoint)
            free_bytes = stat.f_bavail * stat.f_frsize
            cluster_bytes = max(512, stat.f_frsize)
            required_bytes = self._estimate_payload_bytes_on_fat(
                source_dir=source_dir,
                cluster_bytes=cluster_bytes,
            )
            if required_bytes > free_bytes:
                raise ValidationError(
                    "Custom payload does not fit in target filesystem. "
                    f"Required approximately {required_bytes} bytes but only {free_bytes} bytes are available."
                )
            protected_root_files = self._protected_boot_filenames(boot_mode)
            self._copy_directory_contents_to_root(
                source_dir=source_dir,
                destination_root=mountpoint,
                protected_root_files=protected_root_files,
            )
            self.runner.run(["sync"], check=False)
        finally:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            if mountpoint.exists():
                shutil.rmtree(mountpoint)

    def _copy_directory_contents_to_root(
        self,
        *,
        source_dir: Path,
        destination_root: Path,
        protected_root_files: set[str] | None = None,
    ) -> None:
        protected = protected_root_files or set()
        for entry in sorted(source_dir.iterdir(), key=lambda item: item.name.upper()):
            if entry.name.lower() in _PAYLOAD_EXCLUDED_BASENAMES:
                continue
            destination = destination_root / entry.name
            self._copy_entry(
                source=entry,
                destination=destination,
                protected_root_files=protected,
                is_root=True,
            )

    def _copy_entry(
        self,
        *,
        source: Path,
        destination: Path,
        protected_root_files: set[str],
        is_root: bool,
    ) -> None:
        if source.is_symlink():
            raise ValidationError(f"Custom payload does not support symlinks: {source}")
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            for child in sorted(source.iterdir(), key=lambda item: item.name.upper()):
                if child.name.lower() in _PAYLOAD_EXCLUDED_BASENAMES:
                    continue
                self._copy_entry(
                    source=child,
                    destination=destination / child.name,
                    protected_root_files=protected_root_files,
                    is_root=False,
                )
            return
        if source.is_file():
            if is_root and destination.name.upper() in protected_root_files and destination.exists():
                return
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return
        raise ValidationError(f"Custom payload includes unsupported filesystem entry: {source}")

    def _protected_boot_filenames(self, boot_mode: BootMode) -> set[str]:
        if boot_mode is BootMode.NONE:
            return set()
        return {
            "IO.SYS",
            "MSDOS.SYS",
            "IBMBIO.COM",
            "IBMDOS.COM",
            "KERNEL.SYS",
            "COMMAND.COM",
        }

    def _estimate_payload_bytes_on_fat(self, *, source_dir: Path, cluster_bytes: int) -> int:
        rounded = 0
        directory_clusters = 0
        source_root = source_dir.resolve()
        for directory, dir_names, file_names in os.walk(source_root):
            current_dir = Path(directory)
            # Prune excluded directories from the walk (modifies in place).
            dir_names[:] = [
                name for name in dir_names
                if name.lower() not in _PAYLOAD_EXCLUDED_BASENAMES
            ]
            if current_dir != source_root:
                directory_clusters += cluster_bytes
            for file_name in file_names:
                if file_name.lower() in _PAYLOAD_EXCLUDED_BASENAMES:
                    continue
                path = current_dir / file_name
                if path.is_symlink():
                    raise ValidationError(f"Custom payload does not support symlinks: {path}")
                if not path.is_file():
                    raise ValidationError(f"Custom payload includes unsupported filesystem entry: {path}")
                rounded += self._round_up_to_alignment(path.stat().st_size, cluster_bytes)
            for dir_name in dir_names:
                path = current_dir / dir_name
                if path.is_symlink():
                    raise ValidationError(f"Custom payload does not support symlinks: {path}")
        metadata_overhead = max(cluster_bytes * 2, 4096)
        return rounded + directory_clusters + metadata_overhead

    def _round_up_to_alignment(self, value: int, alignment: int) -> int:
        if alignment <= 0:
            return value
        remainder = value % alignment
        if remainder == 0:
            return value
        return value + (alignment - remainder)

    def _format_floppy_img(self, image_path: Path, *, floppy_type: FloppyType, label: str | None) -> None:
        if not self.backend.supports_kernel_mount:
            # Windows / no-kernel-mount path: format in place with the
            # pure-Python writer. Produces a BPB byte-identical (in the
            # fields we care about) to ``mkfs.fat -F12 -g h/spt -M
            # <media> -r <root> -s <spc>``.
            from ._core.fat12_floppy import format_existing

            format_existing(
                image_path,
                floppy_type=floppy_type,
                volume_label=label,
            )
            if isinstance(self.runner, CommandRunner):
                self._validate_floppy_img_bpb(image_path=image_path, floppy_type=floppy_type)
            return

        spec = floppy_type.spec
        command = [
            "mkfs.fat",
            "-F",
            "12",
            "-S",
            "512",
            "-g",
            spec.mkfs_geometry,
            "-M",
            spec.media_descriptor_hex,
            "-r",
            str(spec.root_entries),
            "-s",
            str(spec.sectors_per_cluster),
        ]
        if label:
            command += ["-n", label]
        command.append(str(image_path))
        self.runner.run(command, sudo=True)
        if isinstance(self.runner, CommandRunner):
            self._validate_floppy_img_bpb(image_path=image_path, floppy_type=floppy_type)

    def _align_floppy_type_from_source_media(self, request: CreateRequest, source_size_bytes: int | None) -> None:
        if source_size_bytes is None:
            return
        if request.boot_mode not in {
            BootMode.MSDOS71,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.COMPAQ331,
        }:
            return
        source_floppy = self._floppy_type_for_size(source_size_bytes)
        if source_floppy is None:
            return
        request.floppy_type = source_floppy
        request.size_bytes = source_floppy.size_bytes

    def _floppy_type_for_size(self, size_bytes: int) -> FloppyType | None:
        for floppy_type in FloppyType:
            if floppy_type.size_bytes == size_bytes:
                return floppy_type
        return None

    def _validate_floppy_img_bpb(self, *, image_path: Path, floppy_type: FloppyType) -> None:
        data = image_path.read_bytes()[:512]
        if len(data) < 512:
            raise ValidationError(f"Formatted IMG is too small to contain a valid boot sector: {image_path}")
        if data[510:512] != b"\x55\xaa":
            raise ValidationError(f"Formatted IMG is missing boot sector signature 0x55AA: {image_path}")

        bytes_per_sector = struct.unpack("<H", data[11:13])[0]
        sectors_per_cluster = data[13]
        reserved_sectors = struct.unpack("<H", data[14:16])[0]
        fats = data[16]
        root_entries = struct.unpack("<H", data[17:19])[0]
        total_sectors_16 = struct.unpack("<H", data[19:21])[0]
        media_descriptor = data[21]
        sectors_per_fat = struct.unpack("<H", data[22:24])[0]
        sectors_per_track = struct.unpack("<H", data[24:26])[0]
        heads = struct.unpack("<H", data[26:28])[0]
        hidden_sectors = struct.unpack("<I", data[28:32])[0]
        total_sectors_32 = struct.unpack("<I", data[32:36])[0]
        total_sectors = total_sectors_16 or total_sectors_32
        file_system_tag = data[54:62]
        spec = floppy_type.spec

        mismatches: list[str] = []
        expected_pairs = (
            ("bytes/sector", 512, bytes_per_sector),
            ("sectors/cluster", spec.sectors_per_cluster, sectors_per_cluster),
            ("reserved sectors", 1, reserved_sectors),
            ("FAT count", 2, fats),
            ("root entries", spec.root_entries, root_entries),
            ("total sectors", spec.total_sectors, total_sectors),
            ("media descriptor", spec.media_descriptor, media_descriptor),
            ("sectors/FAT", spec.sectors_per_fat, sectors_per_fat),
            ("sectors/track", spec.sectors_per_track, sectors_per_track),
            ("heads", spec.heads, heads),
            ("hidden sectors", 0, hidden_sectors),
        )
        for field, expected, actual in expected_pairs:
            if actual != expected:
                if field == "media descriptor":
                    mismatches.append(f"{field} expected 0x{expected:02x} got 0x{actual:02x}")
                else:
                    mismatches.append(f"{field} expected {expected} got {actual}")

        if file_system_tag != b"FAT12   ":
            mismatches.append(f"filesystem tag expected FAT12 got {file_system_tag.decode('latin-1', 'replace').strip()!r}")

        if mismatches:
            detail = "; ".join(mismatches)
            raise ValidationError(
                f"Formatted IMG BPB does not match {floppy_type.value} floppy geometry for {image_path}: {detail}"
            )

    def _partition_and_format(
        self,
        *,
        nbd_device: str,
        disk_format: DiskFormat,
        label: str | None,
        boot_mode: BootMode = BootMode.NONE,
        use_msdos33_layout: bool = False,
    ) -> str:
        legacy_boot_layout = boot_mode is not BootMode.NONE
        partition_start = "63s" if legacy_boot_layout else "1MiB"
        self.runner.run(["parted", "--script", nbd_device, "mklabel", "msdos"], sudo=True)
        self.runner.run(
            [
                "parted",
                "--script",
                nbd_device,
                "mkpart",
                "primary",
                disk_format.parted_fs_label,
                partition_start,
                "100%",
            ],
            sudo=True,
        )
        self.runner.run(
            ["parted", "--script", nbd_device, "set", "1", "boot", "on"],
            sudo=True,
            check=False,
        )
        if legacy_boot_layout:
            lba_state = "off"
            self.runner.run(["parted", "--script", nbd_device, "set", "1", "lba", lba_state], sudo=True, check=False)
        elif disk_format is DiskFormat.FAT32:
            self.runner.run(["parted", "--script", nbd_device, "set", "1", "lba", "on"], sudo=True, check=False)

        self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
        partition_device = self._wait_for_partition(nbd_device)

        # Legacy DOS modes have special handling. Their install path is
        # driven by an emulated DOS SYS or FORMAT later (see
        # ``_install_legacy_dos_via_qemu``). Some need mformat to lay out
        # the FAT16 BPB with DOS-3-compatible defaults (compaq331); others
        # let DOS's own FORMAT.COM lay out everything from scratch
        # (msdos33, ibm8088+dos33 — same install media). The MS-DOS 3.30
        # layout also requires partition type 0x01 (FAT12 <32 MiB) or
        # 0x04 (FAT16 <32 MiB) because DOS 3.30 predates FAT16B /
        # partition type 0x06.
        if use_msdos33_layout:
            fs_type = 0x01 if disk_format is DiskFormat.FAT12 else 0x04
            self._set_mbr_partition_type(nbd_device, partition_index=1, fs_type=fs_type)
            # No mformat: FORMAT C: /S inside DOS will write the FS from
            # scratch with DOS 3.30's exact expected layout. Zero the
            # first 2 MB to clear any residual data so FORMAT doesn't
            # see a stale BPB and skip the format.
            self._zero_partition_head(partition_device, bytes_to_zero=2 * 1024 * 1024)
            return partition_device

        if boot_mode in (BootMode.COMPAQ331, BootMode.MSDOS331):
            # Compaq DOS 3.31 / MS-DOS 3.31 install path: FORMAT C: /S
            # inside QEMU lays out an authentic DOS-3.31 BPB and transfers
            # IBMBIO.COM / IBMDOS.COM (or IO.SYS / MSDOS.SYS) in one pass.
            # Same approach as msdos33 -- skip mformat (DOS 3.x SYS rejects
            # any non-DOS-FORMAT BPB with "No room for system" because its
            # bootstrap-cluster cap is too small for IO.SYS to fit), and
            # zero the first 2 MiB so FORMAT doesn't see a stale BPB.
            #
            # Partition type: Compaq DOS 3.31 introduced FAT16B (BIGDOS,
            # type 0x06) and its FORMAT.COM refuses to format type-0x04
            # partitions even on <=32 MiB drives (reports "Format failure"
            # before even prompting for confirmation).  MS-DOS 3.31's
            # FORMAT happily accepts either; we use 0x06 for COMPAQ331 and
            # 0x04 for MSDOS331 so each matches what its own FORMAT writes.
            fs_type = 0x06 if boot_mode is BootMode.COMPAQ331 else 0x04
            self._set_mbr_partition_type(nbd_device, partition_index=1, fs_type=fs_type)
            self._zero_partition_head(partition_device, bytes_to_zero=2 * 1024 * 1024)
            return partition_device

        command = ["mkfs.fat", "-F", disk_format.mkfs_bits]
        if label:
            command += ["-n", label]
        command.append(partition_device)
        self.runner.run(command, sudo=True)
        return partition_device

    def _set_mbr_partition_type(
        self,
        nbd_device: str,
        *,
        partition_index: int,
        fs_type: int,
    ) -> None:
        """Patch the MBR partition entry's filesystem-type byte in-place.

        parted writes partition type 0x06 for FAT16 by default, but DOS 3.30
        only supports 0x04 (and 0x01). The kernel-visible /dev/nbdXp1 view
        doesn't include the MBR, so we go through /dev/nbdX (the whole
        disk) and patch the byte at offset 0x1be + 0x04 (first entry).
        """
        if partition_index != 1:
            raise NotImplementedError("only first partition supported here")
        offset = 0x1BE + 0x04
        scratch = self.mount_root / f"_parttype-{uuid4().hex[:8]}.bin"
        scratch.write_bytes(bytes([fs_type]))
        try:
            self.runner.run(
                [
                    "dd",
                    f"if={scratch}",
                    f"of={nbd_device}",
                    "bs=1",
                    f"seek={offset}",
                    "count=1",
                    "conv=notrunc",
                ],
                sudo=True,
            )
        finally:
            if scratch.exists():
                scratch.unlink()

    def _zero_partition_head(self, partition_device: str, *, bytes_to_zero: int) -> None:
        """Zero the first ``bytes_to_zero`` bytes of a partition.

        Used when the partition's filesystem will be created from scratch
        by an out-of-band tool (e.g. DOS FORMAT.COM in QEMU); without
        zeroing, leftover content from prior operations can confuse the
        formatter into thinking a valid filesystem already exists.
        """
        # Use /dev/zero through dd; bs=1M ensures it streams efficiently.
        count_mib = max(1, bytes_to_zero // (1024 * 1024))
        self.runner.run(
            [
                "dd",
                "if=/dev/zero",
                f"of={partition_device}",
                "bs=1M",
                f"count={count_mib}",
                "conv=notrunc",
            ],
            sudo=True,
        )

    def _zero_image_region(
        self,
        image_path: Path,
        byte_offset: int,
        bytes_to_zero: int,
    ) -> None:
        """Zero ``bytes_to_zero`` bytes starting at ``byte_offset`` in ``image_path``.

        Cross-platform Python file I/O equivalent to ``dd if=/dev/zero
        of=... seek=... bs=1M``. Used by the Windows VHD pipeline before
        a DOS-3.30 FORMAT C: /S step inside QEMU, so leftover bytes do
        not look like a valid filesystem to FORMAT.
        """
        chunk = b"\x00" * (1024 * 1024)
        remaining = bytes_to_zero
        with image_path.open("r+b") as fh:
            fh.seek(byte_offset)
            while remaining > 0:
                write_len = min(remaining, len(chunk))
                fh.write(chunk[:write_len])
                remaining -= write_len

    def _with_connected_nbd(
        self,
        vhd_path: Path,
        callback: Callable[[str], None],
        *,
        image_format: str | None = None,
    ) -> None:
        nbd_device = self._connect_nbd(vhd_path, image_format=image_format)
        try:
            callback(nbd_device)
        finally:
            self._disconnect_nbd(nbd_device, check=False)

    def _connect_nbd(self, path: Path, *, image_format: str | None = None) -> str:
        nbd_device = self._find_free_nbd()
        effective_format = image_format or self._detect_image_format(path)
        self.runner.run(
            ["qemu-nbd", "--format", effective_format, "--connect", nbd_device, str(path)],
            sudo=True,
        )
        self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
        return nbd_device

    def _disconnect_nbd(self, nbd_device: str, *, check: bool) -> None:
        self.runner.run(["qemu-nbd", "--disconnect", nbd_device], sudo=True, check=check)

    def _wait_for_partition(self, nbd_device: str, timeout_seconds: float = 15.0) -> str:
        partition_path = Path(f"{nbd_device}p1")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if partition_path.exists():
                return str(partition_path)
            self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
            time.sleep(0.25)
        raise ValidationError(f"Partition device did not appear for {nbd_device} within {timeout_seconds:.0f}s.")

    def _find_free_nbd(self) -> str:
        candidates = self._list_nbd_candidates()
        if not candidates:
            result = self.runner.run(["modprobe", "nbd", "max_part=16"], sudo=True, check=False)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise ValidationError(
                    "No /dev/nbd* devices are available on this host, and loading the NBD module failed. "
                    f"Tried `sudo modprobe nbd max_part=16`: {detail}"
                )

            deadline = time.monotonic() + self.nbd_discovery_timeout
            while time.monotonic() < deadline:
                candidates = self._list_nbd_candidates()
                if candidates:
                    break
                time.sleep(0.2)
            if not candidates:
                raise ValidationError(
                    "No /dev/nbd* devices appeared after loading the NBD module. "
                    "Verify kernel support and run `sudo modprobe nbd nbds_max=16 max_part=16`."
                )

        missing_dev_nodes = 0
        for candidate in candidates:
            dev_path = self.nbd_dev_root / candidate.name
            if not dev_path.exists():
                missing_dev_nodes += 1
                continue

            pid_path = candidate / "pid"
            if not pid_path.exists():
                return str(dev_path)
            try:
                pid_text = pid_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not pid_text:
                return str(dev_path)

        if missing_dev_nodes == len(candidates):
            raise ValidationError(
                "NBD devices were detected in sysfs, but device nodes are missing under /dev. "
                "Ensure udev is running and retry."
            )
        raise ValidationError("All nbd devices are in use. Unmount/disconnect a device and try again.")

    def _next_mountpoint(self, vhd_path: Path) -> Path:
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", vhd_path.stem).strip("-") or "vhd"
        return self.mount_root / f"{safe_stem}-{uuid4().hex[:8]}"

    def _media_type_for_path(self, path: Path) -> MediaType:
        return MediaType.IMG if path.suffix.lower() in {".img", ".ima"} else MediaType.VHD

    def _is_nbd_record(self, record: MountRecord) -> bool:
        return record.nbd_device.startswith("/dev/nbd")

    def _list_nbd_candidates(self) -> list[Path]:
        return sorted(
            [path for path in self.nbd_sys_block_root.glob("nbd*") if path.name[3:].isdigit()],
            key=lambda entry: int(entry.name[3:]),
        )

    def _detect_image_format(self, path: Path) -> str:
        result = self.runner.run(["qemu-img", "info", "--output=json", str(path)])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Unable to parse qemu-img info output for {path}") from exc
        image_format = payload.get("format")
        if not isinstance(image_format, str) or not image_format:
            raise ValidationError(f"Unable to determine disk format for {path}")
        if image_format == "raw" and self._has_vpc_footer(path):
            return "vpc"
        return image_format

    def _has_vpc_footer(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = handle.read(512)
        except OSError:
            return False
        return len(footer) == 512 and footer[:8] == b"conectix"

    def _read_vpc_bios_chs_geometry(self, path: Path) -> tuple[int, int] | None:
        try:
            with path.open("rb") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = handle.read(512)
        except OSError:
            return None
        if len(footer) != 512 or footer[:8] != b"conectix":
            return None

        heads = footer[58]
        sectors_per_track = footer[59]
        if heads <= 0 or sectors_per_track <= 0:
            return None
        return (sectors_per_track, heads)

    def _patch_partition_bpb_to_footer_geometry(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
    ) -> None:
        """Patch the FAT BPB's heads/spt to match the VHD footer CHS.

        After QEMU runs FORMAT C: /S inside DOS, the BPB heads/spt
        reflect QEMU's SeaBIOS view of the disk (BIOS-canonical
        16h/63s), not the geometry the real target controller will
        expose. For non-MartyPC targets (86Box AUTO IDE / LARGE
        translation) the footer is also 16/63, so this is a no-op.
        For MartyPC Xebec targets the footer carries the controller's
        native MFM CHS (e.g. 615×4×17 for Type 2), and patching the
        BPB here is what stops the "two beeps + corrupt characters +
        ROM-BASIC" boot failure.
        """
        bios_chs = self._read_vpc_bios_chs_geometry(vhd_path)
        if bios_chs is None:
            return
        sectors_per_track, heads = bios_chs
        if sectors_per_track <= 0 or heads <= 0:
            return
        with vhd_path.open("r+b") as handle:
            handle.seek(partition_offset_bytes + 24)
            handle.write(struct.pack("<HH", sectors_per_track, heads))

    def _patch_partition_bpb_to_translated_geometry(
        self,
        *,
        vhd_path: Path,
        partition_offset_bytes: int,
    ) -> None:
        """Patch the BPB to ECHS-translated heads/spt for >504 MB drives.

        AT BIOSes apply bit-shift translation to drives whose physical
        cylinder count exceeds 1024 (every >504 MB drive at 16h/63s),
        doubling heads and halving cylinders until cyl ≤ 1024. The
        resulting virtual geometry (e.g. 64h/63s for a 1 GB drive) is
        what 86Box and modern QEMU IDE controllers present to DOS,
        and what the VBR's INT 13h CHS reads must match.

        For drives ≤504 MB this is a no-op (no translation needed,
        falls back to the footer's geometry).
        """
        footer = core_vhd_footer.read_footer(vhd_path)
        if footer.heads <= 0 or footer.sectors_per_track <= 0:
            return
        heads = footer.heads
        cyls = footer.cylinders
        while cyls > 1024 and heads < 256:
            heads *= 2
            cyls = (cyls + 1) // 2
        translated_heads = min(heads, 255)
        with vhd_path.open("r+b") as handle:
            handle.seek(partition_offset_bytes + 24)
            handle.write(struct.pack("<HH", footer.sectors_per_track, translated_heads))

    def _rewrite_mbr_for_xt_class(
        self,
        *,
        vhd_path: Path,
        cylinders: int,
        heads: int,
        sectors_per_track: int,
        fs_type: int,
    ) -> None:
        """Overwrite the VHD's MBR with a DOS-3.3-style boot loader and
        a track-aligned partition entry.

        Used for MartyPC Xebec targets whose XT-class BIOS only supports
        INT 13h AH=02 (CHS) reads. The partition is placed at LBA = spt
        (one track in, exactly what real DOS 3.3 FDISK produces on an
        MFM drive) with start CHS = (cyl=0, head=1, sec=1) and end CHS
        = (cyl=cylinders-2, head=heads-1, sec=spt), leaving the last
        cylinder unused (the same allocation DOS 3.3 FDISK makes).

        Args:
            vhd_path: VHD file to rewrite (must be a fixed VHD with a
                512-byte conectix footer).
            cylinders / heads / sectors_per_track: drive CHS that the
                target's BIOS will report via INT 13h AH=08.
            fs_type: MBR partition type byte (0x04 for FAT16 <32 MiB,
                0x01 for FAT12 <32 MiB).
        """
        if cylinders < 3 or heads < 1 or sectors_per_track < 1:
            raise ValidationError(
                f"XT-class MBR rewrite needs cyl>=3, heads>=1, spt>=1; "
                f"got {cylinders}x{heads}x{sectors_per_track}."
            )

        # Reserve the entire first track for the MBR (LBA 0 .. spt-1),
        # and skip the final cylinder. This matches what DOS 3.3 FDISK
        # produces on MFM controllers — verified byte-identical with the
        # user's 86Box-MFM-20M-Option3.vhd reference.
        start_lba = sectors_per_track
        usable_cyls = cylinders - 1  # leave last cylinder unused
        partition_sectors = usable_cyls * heads * sectors_per_track - start_lba

        start_chs = _chs_to_partition_table_bytes(cyl=0, head=1, sector=1)
        end_chs = _chs_to_partition_table_bytes(
            cyl=usable_cyls - 1,
            head=heads - 1,
            sector=sectors_per_track,
        )
        entry = (
            bytes([0x80])  # bootable flag
            + start_chs
            + bytes([fs_type & 0xFF])
            + end_chs
            + struct.pack("<II", start_lba, partition_sectors)
        )
        assert len(entry) == 16, len(entry)

        with vhd_path.open("r+b") as handle:
            # Boot code (0..439).
            handle.seek(0)
            handle.write(_LEGACY_DOS_MBR_BOOT_CODE_PRE_SIG)
            # NT disk signature area (440..443) — DOS 3.3 keeps this 0.
            handle.write(b"\x00\x00\x00\x00")
            # Reserved (444..445).
            handle.write(b"\x00\x00")
            # Partition table entries (446..509) — entry 1 active, 2-4 zeroed.
            handle.write(entry)
            handle.write(b"\x00" * 16 * 3)
            # Boot signature.
            handle.write(b"\x55\xaa")

    def _rewrite_mbr_partition_entry_for_footer(
        self,
        *,
        vhd_path: Path,
        request: CreateRequest,
    ) -> None:
        """Re-encode MBR partition entry 1's CHS + type to match the VHD footer.

        Called after ``parted --script mkpart`` (and, for legacy DOS modes,
        after the QEMU FORMAT/FDISK step) on the Linux NBD flow to fix a
        long-standing bug: parted writes the partition entry's CHS bytes
        using its own BIOS-canonical geometry (head=31 / spt=63 style),
        which mismatches the VHD footer's actual geometry (typically
        16h/63s) and causes 86Box AUTO IDE to fall back to LRG translation
        — INT 13h reads then land on the wrong sectors and the disk fails
        to boot with "Missing operating system".

        This rewrite preserves parted's boot code (bytes 0..439), disk
        signature (440..443), and boot signature (510..511); only bytes
        446..461 (partition entry 1) are touched. Entries 2..4 (462..509)
        are also preserved since parted may have used them too.

        The CHS recomputation uses ``footer.heads`` / ``footer.spt`` (no
        ECHS translation — the VHDs we currently generate are <504 MB
        effective so BIOS reports the footer geometry directly). The
        partition-type byte mirrors the Windows path computation at
        ``create_and_prepare_vhd_no_kernel`` (FAT32→0x0C, FAT32+msdos71/
        pcdos71→0x0C, FAT16 LBA→0x0E for msdos71/pcdos71, FAT16→0x06,
        FAT16<32M for msdos33/msdos331→0x04, FAT12→0x01).
        """
        if _needs_xt_class_mbr_rewrite(request):
            # XT-class targets are handled by _rewrite_mbr_for_xt_class which
            # rewrites the entire MBR with a DOS-3.3-style layout.
            return

        try:
            footer = core_vhd_footer.read_footer(vhd_path)
        except (ValueError, OSError):
            # Stub VHDs used in unit tests (and any path that doesn't have
            # a real conectix footer) — nothing to align against.
            return
        if footer.heads <= 0 or footer.sectors_per_track <= 0:
            return

        with vhd_path.open("rb") as handle:
            sector = handle.read(512)
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            # Sector 0 isn't a valid MBR; nothing we can safely patch.
            return

        entry = sector[0x1BE:0x1CE]
        first_lba = struct.unpack("<I", entry[8:12])[0]
        sector_count = struct.unpack("<I", entry[12:16])[0]
        if first_lba == 0 or sector_count == 0:
            return

        # Determine partition-type byte (mirrors the Windows path logic).
        msdos33_layout = _uses_msdos33_filesystem_layout(request)
        pcdos71_layout = request.boot_mode is BootMode.PCDOS71
        msdos71_layout = request.boot_mode is BootMode.MSDOS71
        if msdos33_layout or request.boot_mode is BootMode.MSDOS331:
            partition_type = 0x01 if request.disk_format is DiskFormat.FAT12 else 0x04
        elif (pcdos71_layout or msdos71_layout) and request.disk_format is DiskFormat.FAT32:
            partition_type = 0x0C
        elif pcdos71_layout or msdos71_layout:
            partition_type = 0x0E
        elif request.disk_format is DiskFormat.FAT32:
            partition_type = 0x0C
        elif request.disk_format is DiskFormat.FAT12:
            partition_type = 0x01
        else:
            partition_type = 0x06

        new_entry = core_mbr.PartitionEntry(
            bootable=entry[0] == 0x80,
            partition_type=partition_type,
            first_lba=first_lba,
            sector_count=sector_count,
            chs_heads=footer.heads,
            chs_spt=footer.sectors_per_track,
        ).encode()
        assert len(new_entry) == 16, len(new_entry)

        if new_entry == entry:
            return

        with vhd_path.open("r+b") as handle:
            handle.seek(0x1BE)
            handle.write(new_entry)

    def _ensure_sudo_ready(self) -> None:
        if not self.backend.requires_sudo_for_disk_ops:
            return
        result = self.runner.run(["true"], sudo=True, check=False)
        if result.returncode == 0:
            return
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValidationError(
            "Sudo authentication is required for disk operations. "
            "Run `sudo -v` in a terminal, then retry. "
            "If this still fails after authentication, run `dosforge sudo-check` to detect sudo policy issues.\n"
            f"Details: {detail}"
        )
