"""Core VHD/IMG creation, formatting, mount and unmount workflows."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .boot import BootAssetResolver, BootInstaller
from .commands import CommandRunner
from .legacy_dos_install import (
    Compaq331InstallSources,
    LegacyDosInstallProfile,
    LegacyDosQemuInstaller,
    compaq331_profile,
    msdos33_profile,
)
from .dependencies import BOOT_COMMANDS, REQUIRED_COMMANDS, assert_dependencies, find_missing
from .errors import ValidationError
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
    profile_builder: Callable[[Path], LegacyDosInstallProfile]


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

    Currently four flows go through ``_install_legacy_dos_via_qemu``:

    - ``BootMode.COMPAQ331`` — Compaq DOS 3.31 (FAT16B + SYS C:).
    - ``BootMode.MSDOS331`` — MS-DOS 3.31 reuses the Compaq pipeline
      (same Compaq OEM install media; the static-template path can't
      produce a working DOS-3.31 boot sector on an mkfs.fat BPB).
    - ``BootMode.MSDOS33`` — MS-DOS 3.30 (FORMAT C: /S from scratch).
    - ``BootMode.IBM8088`` with ``ibm_dos_version == DOS33`` — same
      MS-DOS 3.30 install media + the same FORMAT-from-scratch flow.
      The static-template install path produced an unbootable VHD
      (DOS 3.30 boot sectors are floppy-flavoured and reject a generic
      hard-disk BPB), so we redirect through the proven QEMU path.

    Other ``IBM8088`` versions (DOS 5.0) still use the regular
    ``make_partition_bootable`` flow because their static template is
    known to boot.
    """
    if request.boot_mode in (
        BootMode.COMPAQ331,
        BootMode.MSDOS331,
        BootMode.MSDOS33,
    ):
        return True
    if (
        request.boot_mode is BootMode.IBM8088
        and request.ibm_dos_version is IBMDOSVersion.DOS33
    ):
        return True
    return False


def _legacy_dos_install_descriptor(request: CreateRequest) -> _LegacyDosInstallDescriptor | None:
    """Pick the QEMU install descriptor for ``request``.

    IBM8088 + DOS33 reuses the MSDOS33 descriptor (same install media,
    same FORMAT C: /S flow).
    """
    if (
        request.boot_mode is BootMode.IBM8088
        and request.ibm_dos_version is IBMDOSVersion.DOS33
    ):
        return _LEGACY_DOS_INSTALL_DESCRIPTORS[BootMode.MSDOS33]
    return _LEGACY_DOS_INSTALL_DESCRIPTORS.get(request.boot_mode)


def _uses_msdos33_filesystem_layout(request: CreateRequest) -> bool:
    """Return True when DOS 3.30's FORMAT lays out the FAT itself.

    Partition-table prep for these requests must:
    - set MBR partition type 0x04 (FAT16 <32 MiB, pre-FAT16B), and
    - skip mformat (FORMAT C: /S writes its own BPB from scratch).
    """
    if request.boot_mode is BootMode.MSDOS33:
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
        self.runner = runner or CommandRunner()
        self.state_store = state_store or StateStore()
        self.mount_root = mount_root or app_mount_root()
        self.mount_root.mkdir(parents=True, exist_ok=True)
        self.boot_resolver = boot_resolver or BootAssetResolver(self.runner)
        self.boot_installer = boot_installer or BootInstaller(self.runner)
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

    def create_and_prepare(self, request: CreateRequest) -> None:
        self.preflight(request)
        self._apply_custom_payload_autosizing(request)
        self._validate_create_request(request)

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
            if request.disk_format in (DiskFormat.FAT12, DiskFormat.FAT16)
            else None
        )

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
        image_path = path.expanduser().resolve()
        if not image_path.exists():
            raise ValidationError(f"Disk image file does not exist: {image_path}")

        media_type = self._media_type_for_path(image_path)
        self.preflight(media_type=media_type)
        if media_type is MediaType.IMG:
            return self._mount_floppy_img(image_path)
        return self._mount_vhd(image_path)

    def unmount(self, mount_point: Path) -> MountRecord:
        record = self.state_store.find_mount(mount_point.expanduser().resolve())
        if record is None:
            raise ValidationError(f"Mount point is not tracked by dosforge: {mount_point}")

        self.preflight(media_type=MediaType.VHD if self._is_nbd_record(record) else MediaType.IMG)
        self.runner.run(["umount", str(record.mount_point)], sudo=True)
        if self._is_nbd_record(record):
            self._disconnect_nbd(record.nbd_device, check=True)
        self.state_store.remove_mount(record.mount_point)
        if record.mount_point.exists():
            record.mount_point.rmdir()
        return record

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
                            f"{detail}. Run `sudo -v` before launch or configure scoped NOPASSWD sudoers rules."
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
        self.runner.run_detached(["xdg-open", str(target)])

    def fetch_freedos_assets(self, destination: Path | None = None, download_url: str | None = None) -> Path:
        missing = find_missing(("mcopy", "mkfs.fat"))
        if missing:
            raise ValidationError(f"Missing required tools for FreeDOS extraction: {', '.join(missing)}")
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
            # FAT12 on VHD is a narrow capability: only the MartyPC
            # Xebec Type 1 (10 MiB MFM) preset is supported today, with
            # an MS-DOS 3.30 (msdos33) or IBM 8088 + DOS33 install.
            # Anywhere else we'd need a hard-disk-aware FAT12 boot
            # sector / SYS workflow we don't currently produce.
            if request.machine_target is not MachineTarget.MARTYPC_XEBEC:
                raise ValidationError(
                    "FAT12 on VHD is only supported with the MartyPC Xebec Type 1 (10 MiB) preset."
                )
            if request.martypc_xebec_drive_type is not MartyPCXebecDriveType.TYPE1:
                raise ValidationError(
                    "FAT12 on VHD is only supported with MartyPC Xebec Type 1 (10 MiB). "
                    "Pick FAT16 for Xebec Type 2 / 13 / 16."
                )
            if not _uses_msdos33_filesystem_layout(request):
                raise ValidationError(
                    "FAT12 on VHD requires boot-mode=msdos33 or ibm8088 + --ibm-dos-version dos33 "
                    "(DOS's own FORMAT C: /S writes the FAT12 BPB)."
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
        legacy_fat16_modes = {
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.COMPAQ331,
        }
        if request.boot_mode in legacy_fat16_modes and request.disk_format is not DiskFormat.FAT16:
            raise ValidationError("Legacy DOS boot profiles support FAT16 only.")
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
            BootMode.COMPAQ331,
        }
        if request.boot_mode not in xt_class_modes:
            raise ValidationError(
                "MartyPC Xebec target only supports XT-class DOS boot modes "
                "(none, ibm8088, msdos33, msdos331, pcdos, compaq331)."
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
            return

        self.runner.run(
            ["qemu-img", "create", "-f", "vpc", "-o", "subformat=fixed", str(path), str(size_bytes)]
        )
        # qemu-img writes Microsoft's legacy VHD CHS algorithm into the footer
        # (e.g. 1007x12x17 for ~100 MiB). 86Box's IDE AUTO detection treats
        # non-power-of-2 head counts as LARGE-translated geometry and reports
        # a doubled-heads/halved-cyl CHS to DOS via INT 13h AH=08. The BPB we
        # write reflects the *footer* geometry, so once BIOS reports a
        # different translated geometry, MS-DOS IO.SYS computes wrong CHS at
        # boot and reads the wrong sectors -> "Non-System disk" error.
        #
        # Rewriting the footer to standard ATA geometry (16 heads, 63 spt)
        # makes 86Box AUTO pick NORMAL mode and report the footer values
        # directly. mkfs.fat then writes a matching BPB through qemu-nbd, and
        # IO.SYS's LBA->CHS arithmetic at boot lines up with what BIOS reports.
        self._normalize_vhd_footer_geometry(path)

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
        if request.disk_format is DiskFormat.FAT16:
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
            self._copy_custom_payload_to_filesystem(
                partition_device=str(target_path),
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
        install_image = self._find_legacy_dos_install_image(
            directory=boot_assets_dir,
            preferred_names=descriptor.preferred_image_names,
            system_file_marker=descriptor.system_file_marker,
        )
        if install_image is None:
            raise ValidationError(
                f"{descriptor.label} boot mode requires a bootable install diskette "
                f"(with SYS.COM and {descriptor.system_file_marker}) in the boot assets "
                f"directory. Preferred names: {', '.join(descriptor.preferred_image_names)}. "
                f"Checked: {boot_assets_dir}"
            )

        cache_root = app_cache_dir() / "legacy-dos-install"
        cache_root.mkdir(parents=True, exist_ok=True)
        installer = LegacyDosQemuInstaller(
            runner=self.runner,
            cache_root=cache_root,
        )
        profile = descriptor.profile_builder(install_image)
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
        """
        if request.msdos_install_profile is not MSDOSInstallProfile.FULL:
            return
        assets = self.boot_resolver.resolve(request)
        partition_image = f"{vhd_path}@@{partition_offset_bytes}"

        # 1. Stage the DOS tools payload under C:\<payload_target_dir>\.
        if assets.fdos_payload_dir is not None and assets.fdos_payload_dir.is_dir():
            target_dir = (assets.payload_target_dir or "DOS").strip("/\\").upper()
            # Create the top-level dir on C:\ first. mmd errors out if
            # it already exists, so let it through (check=False).
            self.runner.run(
                ["mmd", "-i", partition_image, f"::{target_dir}"],
                check=False,
            )
            for entry in sorted(assets.fdos_payload_dir.rglob("*")):
                relative = entry.relative_to(assets.fdos_payload_dir)
                dos_rel = str(relative).replace(os.sep, "/")
                dest = f"::{target_dir}/{dos_rel}"
                if entry.is_dir():
                    self.runner.run(
                        ["mmd", "-i", partition_image, dest],
                        check=False,
                    )
                elif entry.is_file():
                    self.runner.run(
                        ["mcopy", "-i", partition_image, "-o", str(entry), dest],
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
            if not src.is_file():
                continue
            self.runner.run(
                ["mcopy", "-i", partition_image, "-o", str(src), f"::{name}"],
            )

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
            if current_dir != source_root:
                directory_clusters += cluster_bytes
            for file_name in file_names:
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
            # Compaq / MS-DOS 3.31 SYS.COM rejects mkfs.fat's BPB layout
            # (reserved_sec_count=8 in particular) with "No room for system
            # on destination disk", and the resulting hard-disk boot
            # sector hangs at "Verifying DMI pool data" because the
            # DOS-3.31 loader can't navigate the unfamiliar BPB. mformat
            # defaults to a DOS-3-compatible layout (reserved=1) that
            # SYS accepts and that DOS-3.31's boot loader understands.
            #
            # Microsoft MS-DOS 3.31 (msdos331) is capped at 32 MiB so it
            # gets the FAT16-short partition type (0x04). Compaq DOS 3.31
            # (compaq331) supports FAT16B up to ~504 MiB and keeps the
            # parted-assigned 0x06 partition type.
            if boot_mode is BootMode.MSDOS331:
                self._set_mbr_partition_type(nbd_device, partition_index=1, fs_type=0x04)
            mformat_cmd = ["mformat", "-i", partition_device]
            if label:
                mformat_cmd += ["-v", label]
            mformat_cmd.append("::")
            self.runner.run(mformat_cmd, sudo=True)
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

    def _ensure_sudo_ready(self) -> None:
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
