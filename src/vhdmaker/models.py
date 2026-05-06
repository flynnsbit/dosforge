"""Core data models used by the app and backend services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FloppySpec:
    size_bytes: int
    tracks: int
    heads: int
    sectors_per_track: int
    media_descriptor: int
    root_entries: int
    sectors_per_cluster: int
    sectors_per_fat: int

    @property
    def total_sectors(self) -> int:
        return self.size_bytes // 512

    @property
    def mkfs_geometry(self) -> str:
        return f"{self.heads}/{self.sectors_per_track}"

    @property
    def media_descriptor_hex(self) -> str:
        return f"0x{self.media_descriptor:02x}"


class DiskFormat(str, Enum):
    FAT16 = "fat16"
    FAT32 = "fat32"

    @property
    def mkfs_bits(self) -> str:
        return "16" if self is DiskFormat.FAT16 else "32"

    @property
    def parted_fs_label(self) -> str:
        return "fat16" if self is DiskFormat.FAT16 else "fat32"

    @property
    def boot_code_offset(self) -> int:
        return 62 if self is DiskFormat.FAT16 else 90


class BootMode(str, Enum):
    NONE = "none"
    FREEDOS = "freedos"
    MSDOS71 = "msdos71"
    IBM8088 = "ibm8088"
    MSDOS33 = "msdos33"
    MSDOS331 = "msdos331"
    MSDOS5 = "msdos5"
    MSDOS622 = "msdos622"
    PCDOS = "pcdos"
    PCDOS7 = "pcdos7"
    COMPAQ331 = "compaq331"


class MediaType(str, Enum):
    VHD = "vhd"
    IMG = "img"


class FreeDOSSource(str, Enum):
    LOCAL = "local"
    AUTO = "auto"


class MSDOSInstallProfile(str, Enum):
    MINIMAL = "minimal"
    FULL = "full"


class IBMDOSVersion(str, Enum):
    DOS33 = "dos33"
    DOS50 = "dos50"


class FloppyType(str, Enum):
    F160K = "160k"
    F180K = "180k"
    F360K = "360k"
    F720K = "720k"
    F1840K = "1840k"
    F1200K = "1200k"
    F1440K = "1440k"
    F2880K = "2880k"

    @property
    def size_bytes(self) -> int:
        return self.spec.size_bytes

    @property
    def mkfs_size_kib(self) -> int:
        return self.size_bytes // 1024

    @property
    def spec(self) -> FloppySpec:
        return _FLOPPY_SPECS[self]


_FLOPPY_SPECS: dict[FloppyType, FloppySpec] = {
    FloppyType.F160K: FloppySpec(
        size_bytes=160 * 1024,
        tracks=40,
        heads=1,
        sectors_per_track=8,
        media_descriptor=0xFE,
        root_entries=64,
        sectors_per_cluster=4,
        sectors_per_fat=1,
    ),
    FloppyType.F180K: FloppySpec(
        size_bytes=180 * 1024,
        tracks=40,
        heads=1,
        sectors_per_track=9,
        media_descriptor=0xFC,
        root_entries=64,
        sectors_per_cluster=4,
        sectors_per_fat=1,
    ),
    FloppyType.F360K: FloppySpec(
        size_bytes=360 * 1024,
        tracks=40,
        heads=2,
        sectors_per_track=9,
        media_descriptor=0xFD,
        root_entries=112,
        sectors_per_cluster=2,
        sectors_per_fat=2,
    ),
    FloppyType.F720K: FloppySpec(
        size_bytes=720 * 1024,
        tracks=80,
        heads=2,
        sectors_per_track=9,
        media_descriptor=0xF9,
        root_entries=112,
        sectors_per_cluster=2,
        sectors_per_fat=3,
    ),
    FloppyType.F1840K: FloppySpec(
        size_bytes=1840 * 1024,
        tracks=80,
        heads=2,
        sectors_per_track=23,
        media_descriptor=0xF0,
        root_entries=224,
        sectors_per_cluster=1,
        sectors_per_fat=11,
    ),
    FloppyType.F1200K: FloppySpec(
        size_bytes=1200 * 1024,
        tracks=80,
        heads=2,
        sectors_per_track=15,
        media_descriptor=0xF9,
        root_entries=224,
        sectors_per_cluster=1,
        sectors_per_fat=7,
    ),
    FloppyType.F1440K: FloppySpec(
        size_bytes=1440 * 1024,
        tracks=80,
        heads=2,
        sectors_per_track=18,
        media_descriptor=0xF0,
        root_entries=224,
        sectors_per_cluster=1,
        sectors_per_fat=9,
    ),
    FloppyType.F2880K: FloppySpec(
        size_bytes=2880 * 1024,
        tracks=80,
        heads=2,
        sectors_per_track=36,
        media_descriptor=0xF0,
        root_entries=240,
        sectors_per_cluster=2,
        sectors_per_fat=9,
    ),
}


@dataclass(slots=True)
class CreateRequest:
    path: Path
    size_bytes: int
    disk_format: DiskFormat
    media_type: MediaType = MediaType.VHD
    floppy_type: FloppyType = FloppyType.F1440K
    img_system_format: bool = False
    label: str | None = None
    overwrite: bool = False
    boot_mode: BootMode = BootMode.NONE
    freedos_source: FreeDOSSource = FreeDOSSource.LOCAL
    boot_assets_path: Path | None = None
    freedos_download_url: str | None = None
    msdos_install_profile: MSDOSInstallProfile = MSDOSInstallProfile.MINIMAL
    ibm_dos_version: IBMDOSVersion = IBMDOSVersion.DOS33


@dataclass(slots=True)
class MountRecord:
    vhd_path: Path
    nbd_device: str
    partition_device: str
    mount_point: Path
    mounted_at: datetime

    @classmethod
    def create(
        cls,
        *,
        vhd_path: Path,
        nbd_device: str,
        partition_device: str,
        mount_point: Path,
    ) -> "MountRecord":
        return cls(
            vhd_path=vhd_path,
            nbd_device=nbd_device,
            partition_device=partition_device,
            mount_point=mount_point,
            mounted_at=datetime.now(timezone.utc),
        )

    def to_json(self) -> dict[str, str]:
        return {
            "vhd_path": str(self.vhd_path),
            "nbd_device": self.nbd_device,
            "partition_device": self.partition_device,
            "mount_point": str(self.mount_point),
            "mounted_at": self.mounted_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, str]) -> "MountRecord":
        return cls(
            vhd_path=Path(payload["vhd_path"]),
            nbd_device=payload["nbd_device"],
            partition_device=payload["partition_device"],
            mount_point=Path(payload["mount_point"]),
            mounted_at=datetime.fromisoformat(payload["mounted_at"]),
        )
