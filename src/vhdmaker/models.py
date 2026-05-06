"""Core data models used by the app and backend services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


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
    PCDOS = "pcdos"
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
    F320K = "320k"
    F360K = "360k"
    F720K = "720k"
    F1200K = "1200k"
    F1440K = "1440k"

    @property
    def size_bytes(self) -> int:
        return {
            FloppyType.F160K: 160 * 1024,
            FloppyType.F180K: 180 * 1024,
            FloppyType.F320K: 320 * 1024,
            FloppyType.F360K: 360 * 1024,
            FloppyType.F720K: 720 * 1024,
            FloppyType.F1200K: 1200 * 1024,
            FloppyType.F1440K: 1440 * 1024,
        }[self]

    @property
    def mkfs_size_kib(self) -> int:
        return self.size_bytes // 1024


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
