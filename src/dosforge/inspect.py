"""Read-only structural inspection of an existing VHD.

Provides :class:`VhdInfo`, a JSON-friendly snapshot of a VHD's MBR
+ first partition + BPB + root-level system files.  Shared between
``dosforge grow`` (which validates target sizes against the current
cluster band) and ``dosforge inspect`` (which surfaces the same
information for tooling).

Pure-Python implementation -- no mtools dependency for the
structural reads.  Root file listing uses ``mdir`` and is optional
(swallowed when mtools isn't available).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .commands import CommandRunner, subprocess_no_window_kwargs
from .errors import DependencyError, ValidationError
from .models import BootMode, DiskFormat


# OEM string → likely boot mode lookup. Matches the BPB OEM stamp
# written by each DOS's FORMAT.COM at install time.  Used for the
# best-effort boot-mode inference in :func:`inspect_vhd`.  Lookups
# are case-insensitive with trailing space tolerance.
_OEM_TO_BOOT_MODE: dict[str, BootMode] = {
    "MSWIN4.1": BootMode.MSDOS71,
    "MSDOS5.0": BootMode.MSDOS622,    # MS-DOS 5.0+ family; 6.22 stamps the same
    "MSDOS6.22": BootMode.MSDOS622,
    "IBM  3.3": BootMode.COMPAQ331,   # Compaq DOS 3.31 + DR-DOS 6
    "IBM  7.0": BootMode.PCDOS7,
    "IBM  7.1": BootMode.PCDOS71,
    "FRDOS5.1": BootMode.FREEDOS,
    "FRDOS4.1": BootMode.FREEDOS,
    "FreeDOS": BootMode.FREEDOS,
    "DRDOS  7": BootMode.DRDOS7,
}


_DOS_SYSTEM_FILES: tuple[str, ...] = (
    "IO.SYS",
    "MSDOS.SYS",
    "IBMBIO.COM",
    "IBMDOS.COM",
    "KERNEL.SYS",
    "COMMAND.COM",
    "CONFIG.SYS",
    "AUTOEXEC.BAT",
    "FDCONFIG.SYS",
    "FDAUTO.BAT",
)


@dataclass(frozen=True, slots=True)
class VhdInfo:
    """JSON-friendly inspection result for a VHD."""

    path: Path
    file_size_bytes: int
    is_fixed_vhd: bool
    footer_chs: tuple[int, int, int] | None

    mbr_partition_type: int
    partition_lba_start: int
    partition_sector_count: int
    partition_offset_bytes: int

    bpb_oem: str
    bytes_per_sector: int
    sectors_per_cluster: int
    cluster_size_bytes: int
    reserved_sectors: int
    num_fats: int
    root_dir_entries: int
    total_sectors: int
    sectors_per_fat: int
    fat_format: DiskFormat
    cluster_count: int
    volume_label: str | None
    volume_serial_hex: str | None

    inferred_boot_mode: BootMode | None
    root_system_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (enums → their .value, Path → str)."""

        payload: dict[str, Any] = {}
        for field_name, value in asdict(self).items():
            if isinstance(value, Path):
                payload[field_name] = str(value)
            elif isinstance(value, DiskFormat):
                payload[field_name] = value.value
            elif isinstance(value, BootMode):
                payload[field_name] = value.value
            else:
                payload[field_name] = value
        # Re-cast fat_format / inferred_boot_mode (asdict misses
        # enums inside frozen+slots dataclasses on some Python
        # versions).
        payload["fat_format"] = self.fat_format.value
        payload["inferred_boot_mode"] = (
            self.inferred_boot_mode.value if self.inferred_boot_mode else None
        )
        payload["footer_chs"] = (
            list(self.footer_chs) if self.footer_chs else None
        )
        payload["root_system_files"] = list(self.root_system_files)
        return payload

    def to_json(self, *, indent: int = 2) -> str:
        """Stable JSON serialization (sorted keys for diff-ability)."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def inspect_vhd(path: Path, *, runner: CommandRunner | None = None) -> VhdInfo:
    """Read MBR + BPB + root file list from ``path``.

    Pure-Python for the structural reads; uses ``mdir`` (when
    available) for root file enumeration.  Raises
    :class:`ValidationError` for malformed VHDs (missing 55 AA
    signature, no first partition, truncated VBR, etc.).
    """

    path = path.expanduser().resolve()
    if not path.exists():
        raise ValidationError(f"VHD does not exist: {path}")
    if not path.is_file():
        raise ValidationError(f"VHD is not a regular file: {path}")
    file_size = path.stat().st_size
    if file_size < 1024:
        raise ValidationError(f"VHD {path} is too small to be valid.")

    with path.open("rb") as fh:
        # MBR
        mbr = fh.read(512)
        if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
            raise ValidationError(f"VHD {path} has no valid MBR signature.")
        entry = mbr[446:462]
        part_type = entry[4]
        lba_start = int.from_bytes(entry[8:12], "little")
        sec_count = int.from_bytes(entry[12:16], "little")
        if lba_start == 0 or sec_count == 0:
            raise ValidationError(
                f"VHD {path} has no first MBR partition entry."
            )

        # VHD fixed-disk footer (last 512 bytes, "conectix" magic).
        fh.seek(file_size - 512)
        footer = fh.read(512)
        is_fixed_vhd = footer[0:8] == b"conectix"
        footer_chs: tuple[int, int, int] | None = None
        if is_fixed_vhd:
            cyl = (footer[56] << 8) | footer[57]
            heads = footer[58]
            spt = footer[59]
            footer_chs = (cyl, heads, spt)

        # Partition VBR + BPB
        partition_offset = lba_start * 512
        fh.seek(partition_offset)
        vbr = fh.read(512)
        if len(vbr) < 64:
            raise ValidationError(
                f"VHD {path} partition VBR is truncated; cannot read BPB."
            )
        bpb_oem = vbr[3:11].decode("ascii", errors="replace")
        bytes_per_sector = int.from_bytes(vbr[11:13], "little")
        sectors_per_cluster = vbr[13]
        if bytes_per_sector != 512 or sectors_per_cluster == 0:
            raise ValidationError(
                f"VHD {path} BPB looks malformed "
                f"(bytes/sec={bytes_per_sector}, "
                f"sec/clust={sectors_per_cluster})."
            )
        reserved = int.from_bytes(vbr[14:16], "little")
        num_fats = vbr[16]
        root_entries = int.from_bytes(vbr[17:19], "little")
        total_sec_16 = int.from_bytes(vbr[19:21], "little")
        total_sec_32 = int.from_bytes(vbr[32:36], "little")
        total_sectors = total_sec_32 if total_sec_32 else total_sec_16
        # Microsoft canonical FAT-detection: read sec_per_fat_16
        # first; only fall through to sec_per_fat_32 when zero.
        # Reading offset 36-40 unconditionally would mis-interpret
        # FAT16's volume-serial bytes as a uint32.
        sec_per_fat_16 = int.from_bytes(vbr[22:24], "little")
        if sec_per_fat_16 != 0:
            sec_per_fat = sec_per_fat_16
        else:
            sec_per_fat = (
                int.from_bytes(vbr[36:40], "little") if len(vbr) >= 40 else 0
            )
        root_dir_sectors = (
            (root_entries * 32) + bytes_per_sector - 1
        ) // bytes_per_sector
        data_sec = total_sectors - (
            reserved + num_fats * sec_per_fat + root_dir_sectors
        )
        cluster_count = data_sec // sectors_per_cluster if sectors_per_cluster else 0
        if cluster_count < 4085:
            fat_format = DiskFormat.FAT12
        elif cluster_count < 65525:
            fat_format = DiskFormat.FAT16
        else:
            fat_format = DiskFormat.FAT32

        # Volume label + serial number.  FAT12/16 stores them at
        # offset 39-43 (serial) and 43-54 (label).  FAT32 puts them
        # later (67/71).  Detection by fat_format.
        if fat_format is DiskFormat.FAT32 and len(vbr) >= 82:
            serial_bytes = vbr[67:71]
            label_bytes = vbr[71:82]
        else:
            serial_bytes = vbr[39:43]
            label_bytes = vbr[43:54]
        volume_serial_hex = serial_bytes[::-1].hex().upper()
        volume_label_raw = label_bytes.decode("ascii", errors="replace").rstrip()
        volume_label = volume_label_raw if volume_label_raw and volume_label_raw != "NO NAME" else None

    root_files = _list_root_system_files(path, partition_offset, runner=runner)
    inferred = _infer_boot_mode(
        bpb_oem=bpb_oem,
        fat_format=fat_format,
        partition_type=part_type,
        root_system_files=root_files,
    )

    return VhdInfo(
        path=path,
        file_size_bytes=file_size,
        is_fixed_vhd=is_fixed_vhd,
        footer_chs=footer_chs,
        mbr_partition_type=part_type,
        partition_lba_start=lba_start,
        partition_sector_count=sec_count,
        partition_offset_bytes=partition_offset,
        bpb_oem=bpb_oem,
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        cluster_size_bytes=bytes_per_sector * sectors_per_cluster,
        reserved_sectors=reserved,
        num_fats=num_fats,
        root_dir_entries=root_entries,
        total_sectors=total_sectors,
        sectors_per_fat=sec_per_fat,
        fat_format=fat_format,
        cluster_count=cluster_count,
        volume_label=volume_label,
        volume_serial_hex=volume_serial_hex,
        inferred_boot_mode=inferred,
        root_system_files=root_files,
    )


def _infer_boot_mode(
    *,
    bpb_oem: str,
    fat_format: DiskFormat,
    partition_type: int,
    root_system_files: tuple[str, ...],
) -> BootMode | None:
    """Best-effort BootMode inference.

    Two-stage fallback:

    1. Match BPB OEM stamp against known dosforge-supported modes
       (most precise -- each DOS's authentic FORMAT.COM writes a
       specific stamp).
    2. When the OEM is generic (e.g. ``mkfs.fat`` / ``MTOOLxxxx``
       from a third-party reformat), fall back to root-system-file
       presence heuristics:

       * ``KERNEL.SYS`` -> FreeDOS (FreeDOS's only kernel naming).
       * ``IO.SYS`` + ``MSDOS.SYS`` on a FAT32 LBA partition (type
         0x0C/0x0B) -> MSDOS71 (only OSR2 ships FAT32 boot).
       * ``IO.SYS`` + ``MSDOS.SYS`` on FAT16 -> MSDOS622 family
         (no way to distinguish 5.0 / 6.0 / 6.22 from the file set
         alone; pick the most common / latest).
       * ``IBMBIO.COM`` + ``IBMDOS.COM`` -> COMPAQ331 (catches
         Compaq DOS 3.31, DR-DOS 6, PC-DOS 3.x ambiguously; pick
         the most common dosforge-supported answer).
    """

    stripped = bpb_oem.strip()
    for needle, mode in _OEM_TO_BOOT_MODE.items():
        if stripped == needle.strip() or bpb_oem.startswith(needle):
            return mode

    upper_files = {name.upper() for name in root_system_files}
    if "KERNEL.SYS" in upper_files:
        return BootMode.FREEDOS
    if "IO.SYS" in upper_files and "MSDOS.SYS" in upper_files:
        if fat_format is DiskFormat.FAT32 or partition_type in (0x0B, 0x0C):
            return BootMode.MSDOS71
        return BootMode.MSDOS622
    if "IBMBIO.COM" in upper_files and "IBMDOS.COM" in upper_files:
        return BootMode.COMPAQ331
    return None


def _list_root_system_files(
    path: Path,
    partition_offset: int,
    *,
    runner: CommandRunner | None = None,
) -> tuple[str, ...]:
    """Return the subset of :data:`_DOS_SYSTEM_FILES` present at C:\\.

    Uses ``mdir -i <image>@@<offset> -a ::<name>`` for each well-
    known system filename.  Swallows DependencyError (no mtools on
    PATH) and returns the empty tuple in that case so inspect
    still works in mtools-free environments.
    """

    if runner is None:
        runner = CommandRunner()
    found: list[str] = []
    partition_image = f"{path}@@{partition_offset}"
    for name in _DOS_SYSTEM_FILES:
        try:
            result = runner.run(
                ["mdir", "-i", partition_image, "-a", f"::{name}"],
                check=False,
            )
        except DependencyError:
            return ()
        if result.returncode == 0:
            found.append(name)
    return tuple(found)


__all__ = [
    "VhdInfo",
    "inspect_vhd",
]
