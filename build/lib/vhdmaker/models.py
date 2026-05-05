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


class FreeDOSSource(str, Enum):
    LOCAL = "local"
    AUTO = "auto"


@dataclass(slots=True)
class CreateRequest:
    path: Path
    size_bytes: int
    disk_format: DiskFormat
    label: str | None = None
    overwrite: bool = False
    boot_mode: BootMode = BootMode.NONE
    freedos_source: FreeDOSSource = FreeDOSSource.LOCAL
    boot_assets_path: Path | None = None
    freedos_download_url: str | None = None


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
