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
    FAT12 = "fat12"
    FAT16 = "fat16"
    FAT32 = "fat32"

    @property
    def mkfs_bits(self) -> str:
        if self is DiskFormat.FAT12:
            return "12"
        if self is DiskFormat.FAT16:
            return "16"
        return "32"

    @property
    def parted_fs_label(self) -> str:
        # parted has no explicit "fat12" label; FAT12 partitions are created
        # with the fat16 label and then re-tagged via _set_mbr_partition_type
        # so DOS sees partition type 0x01 (FAT12 <32 MiB) instead of 0x04.
        return "fat32" if self is DiskFormat.FAT32 else "fat16"

    @property
    def boot_code_offset(self) -> int:
        # FAT12 and FAT16 share the same DOS-3-style BPB layout, so the
        # boot code begins at the same offset (62). FAT32 reserves more
        # BPB space and starts boot code at offset 90.
        return 90 if self is DiskFormat.FAT32 else 62


class BootMode(str, Enum):
    NONE = "none"
    FREEDOS = "freedos"
    # MS-DOS 7.10 — the FAT32-capable DOS kernel from Microsoft.  The
    # 7.10 kernel was never sold as a standalone product; it shipped
    # *only* inside Windows 95 OSR2 / OSR2.1 / OSR2.5 / OSR3 (build
    # 4.00.1111+) and Windows 98 / 98 SE.  dosforge sources its install
    # files from a Win95 OSR2 (4.00.1111) floppy set staged in
    # ``dosassets/w95/`` (see that folder's readme.txt for layout).
    # Produces a "DOS-only" boot — no Win95 GUI Setup, just the
    # IO.SYS / MSDOS.SYS / COMMAND.COM trio + a CONFIG.SYS that
    # bypasses WIN.COM so the system lands at a plain C:\> prompt.
    # Supports FAT16 (up to 2 GiB) and FAT32 (above) on IDE/AT-class.
    MSDOS71 = "msdos71"
    IBM8088 = "ibm8088"
    MSDOS33 = "msdos33"
    MSDOS331 = "msdos331"
    MSDOS5 = "msdos5"
    # Microsoft MS-DOS 6.0 (March 1993).  Released between MS-DOS 5.0
    # and 6.22.  Identical install pipeline to MS-DOS 5.0 / 6.22:
    # FORMAT C: /S inside QEMU from Disk1.img.  Files dated
    # 1993-03-10.  FAT16 only; works on IDE controllers.  OEM VBR
    # string is still ``MSDOS5.0`` (Microsoft only bumped the OEM
    # stamp to ``MSDOS6.22`` in 6.22).
    MSDOS6 = "msdos6"
    MSDOS622 = "msdos622"
    PCDOS = "pcdos"
    PCDOS7 = "pcdos7"
    # IBM PC-DOS 2000 = IBM PC-DOS 7.00 rebranded for the Y2K push.
    # Same VBR + IBMBIO/IBMDOS dates as PCDOS7, but distributed as a
    # raw 6-floppy WinWorldPC set (disk01.img..disk06.img) rather than
    # the LOADDSKF-compressed ``144US1.DSK`` PCDOS7 ships with.  We
    # keep them as separate boot modes so the user picks their own
    # asset source explicitly; the install pipeline is the same
    # FORMAT C: /S that PCDOS7 uses.
    PCDOS2000 = "pcdos2000"
    PCDOS71 = "pcdos71"
    COMPAQ331 = "compaq331"
    # Compaq OEM DOS 2.x (specifically Microsoft MS-DOS 2.11 with
    # Compaq's OEM build, 1984-05-30) — the earliest hard-disk-aware
    # DOS that dosforge supports.  FAT12 ONLY, max ~16 MiB partition
    # (DOS 2.x predates FAT16).  Bootable from the single 360 KB
    # 5.25" DSDD install floppy (disk01.img) inside the WinWorldPC
    # ``Microsoft MS-DOS 2.11 [Compaq OEM] (5.25-360k).7z`` archive
    # — the descriptor auto-extracts the .7z if no raw IMG is found
    # in dosassets/compaq2/.
    COMPAQ2 = "compaq2"
    # IBM PC-DOS 3.00 (1984-08-14) — IBM's first hard-disk-aware DOS.
    # FAT12 only (FAT16 was added in PC-DOS 3.10), max ~16 MiB partition.
    # Has BPB.hidden_sectors field so HDD boot works on any standard
    # MFM/IDE BIOS (unlike compaq2 which depends on Compaq 1984 BIOS
    # extensions).  Sources install media from
    # ``dosassets/pcdos3/IBM PC-DOS 3.00 (5.25).7z`` (auto-extracted via
    # py7zr) or pre-extracted ``Disk01.img`` (360 KB DSDD).  Boots on
    # both IDE and MFM controllers; defaults to MFM since that's the
    # 1984-authentic hardware target.
    PCDOS3 = "pcdos3"
    # Microsoft MS-DOS 3.00 [Compaq OEM] (1985-04-22) — Compaq-branded
    # MS-DOS 3.0 sibling of PCDOS3.  Same DOS-3.0 BPB (has
    # hidden_sectors) so HDD boot works on any standard MFM/IDE BIOS.
    # FAT12 only, max ~16 MiB partition.  Sources from
    # ``dosassets/compaq3/Microsoft MS-DOS 3.00 [Compaq OEM] (5.25-360k).7z``
    # (auto-extracted via py7zr) or pre-extracted ``DISK01.IMG`` (360 KB
    # DSDD).  Uses IBMBIO.COM / IBMDOS.COM naming (Compaq adopted IBM's
    # system-file names for the 3.0 release).  Defaults to MFM
    # controller for 1985-authentic hardware.
    COMPAQ3 = "compaq3"
    # Digital Research DR DOS 6.0 (October 1991) — DR-DOS competitor
    # to MS-DOS 5.0.  IBMBIO.COM + IBMDOS.COM + COMMAND.COM naming
    # (same convention as PC-DOS, but different binary bytes).  Has
    # DOS 3.3-class BPB (OEM stamp "IBM  3.3"), works on both IDE
    # and MFM controllers.  Sources from
    # ``dosassets/drdos6/Digital Research DR DOS 6.0 (10-16-1991)
    # (3.5-720k) (alt).7z`` -- 4 x 720 KB DSDD floppies, disk01
    # already bootable with the SYS-installable DR-DOS kernel.
    # FAT12 and FAT16 supported, max 32 MiB FAT16 partition.
    DRDOS6 = "drdos6"
    # Caldera DR-DOS 7.03 (January 1999) — final retail DR-DOS
    # release (later versions were Caldera/OpenDOS/free-DRDOS forks).
    # IBMBIO.COM + IBMDOS.COM + COMMAND.COM naming.  BPB OEM stamp
    # is "DRDOS  7".  Supports FAT16B (BIGDOS, >32 MiB FAT16
    # partitions up to 2 GiB) -- dosforge currently wires the FAT16
    # path with a 2 GiB cap; FAT32 LBA support could land in a
    # follow-up.  Sources from
    # ``dosassets/drdos7/Caldera DR-DOS 7.03 (01-07-1999)
    # (3.5-1.44mb).7z`` -- 5 x 1.44 MB floppies (Installation +
    # Utilities 1-5).  Disk1 ships at root with IBMBIO.COM +
    # IBMDOS.COM (hidden+system, DR-DOS 7 kernel) + the full DR-DOS
    # toolchain (COMMAND, SYS, FORMAT, FDISK) plus INSTALL.EXE /
    # SETUP2.EX_ (interactive installer, bypassed by dosforge).
    DRDOS7 = "drdos7"
    # 4DOS shell overlay (planned, requires --host-dos).  When set,
    # dosforge raises a clear "not yet implemented" message until
    # full 4DOS install media is provided.
    FOURDOS = "4dos"


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


class DiskController(str, Enum):
    """Hard-disk controller class targeted by a VHD build.

    ``IDE`` (the default) targets AT-class IDE/ATA controllers found in
    any 86Box / DOSBox-X / PCem / MartyPC AT machine from 1988 onward.
    Geometry is canonical 16h/63s unless overridden via
    ``bios_drive_type`` or ``custom_chs``.

    ``MFM`` targets pre-IDE ST-506/ST-412 controllers (Western Digital
    WD1002A-WX1, Adaptec 4070, IBM/Xebec, etc.) from XT-class machines
    (1984-1990).  Produces a track-aligned partition (start LBA = spt)
    with an XT-class CHS-only MBR loader -- the layout DOS 2.x's 1984
    boot code requires.  Geometry must come from ``bios_drive_type``
    (Phoenix/AMI Types 1-15 cover all standard MFM drives) or
    ``custom_chs`` (free-form for unusual MFM emulator presets).
    """

    IDE = "ide"
    MFM = "mfm"


# =====================================================================
# Classic AT BIOS hard-drive type presets (Phoenix / AMI Standard Setup)
# =====================================================================
#
# 1985-1992 Phoenix, AMI, and Award BIOSes shipped with a 45-entry
# hard-drive type table. Picking Type N in BIOS Setup made the BIOS
# expose that exact CHS to DOS via INT 13h AH=08. dosforge can lock a
# VHD to one of these presets so 86Box's BIOS auto-detect shows
# "Type N — Cyl×Hd×Spt" instead of "User-defined / 86B_HD00".
#
# The two vendors agree on Types 1..32; Types 33..45 differ slightly
# between Phoenix and AMI (different drives were added by each vendor
# over the years). Both tables are stored here so the user can pick
# the one their target BIOS matches.

class BIOSVendor(str, Enum):
    PHOENIX = "phoenix"
    AMI     = "ami"


class GeometrySource(str, Enum):
    """Which input governs the VHD's effective on-disk geometry.

    The TUI / GUI surface a single picker rather than three
    competing always-visible inputs: custom CHS wins over BIOS
    preset wins over static size.  Only the chosen source's input
    is visible underneath.
    """

    SIZE = "size"             # static-size text Input
    PRESET = "preset"         # BIOS preset dropdown
    CUSTOM_CHS = "custom_chs"  # custom CYL/HEAD/SPT


@dataclass(frozen=True, slots=True)
class BIOSDriveSpec:
    vendor: BIOSVendor
    type_id: int
    cylinders: int
    heads: int
    write_precomp_cylinder: int  # -1 == auto / not specified
    landing_zone_cylinder: int
    sectors_per_track: int

    @property
    def size_bytes(self) -> int:
        return self.cylinders * self.heads * self.sectors_per_track * 512

    @property
    def size_mb(self) -> int:
        return self.size_bytes // 1024 // 1024

    @property
    def slug(self) -> str:
        return f"{self.vendor.value}:{self.type_id}"

    @property
    def description(self) -> str:
        vendor_label = self.vendor.value.capitalize()
        pre = "auto" if self.write_precomp_cylinder < 0 else str(self.write_precomp_cylinder)
        lz = self.landing_zone_cylinder
        return (
            f"{vendor_label} Type {self.type_id} — "
            f"{self.cylinders}×{self.heads}×{self.sectors_per_track} — "
            f"Pre={pre} LZ={lz} — {self.size_mb} MB"
        )


# Phoenix Standard Setup HDD types 1..45.
# Source: Phoenix BIOS reference 1985-1992 era; matches the table shown
# in user-supplied Phoenix Setup Utility screenshots (Type 1 = 306×4×17
# Pre=128 LZ=305 → 10 MB; Type 45 = 1024×8×17 Pre=auto LZ=1024 → 68 MB).
_BIOS_PHOENIX_DRIVE_ROWS: tuple[tuple[int, int, int, int, int, int], ...] = (
    # (type, cyl, hd, pre, lz, spt)
    ( 1,  306,  4,  128,  305, 17),
    ( 2,  615,  4,  300,  615, 17),
    ( 3,  615,  6,  300,  615, 17),
    ( 4,  940,  8,  512,  940, 17),
    ( 5,  940,  6,  512,  940, 17),
    ( 6,  615,  4,   -1,  615, 17),
    ( 7,  462,  8,  256,  511, 17),
    ( 8,  733,  5,   -1,  733, 17),
    ( 9,  900, 15,   -1,  901, 17),
    (10,  820,  3,   -1,  820, 17),
    (11,  855,  5,   -1,  855, 17),
    (12,  855,  7,   -1,  855, 17),
    (13,  306,  8,  128,  319, 17),
    (14,  733,  7,   -1,  733, 17),
    # Type 15 reserved by IBM; clones omit it. We include it with the
    # same shape as Type 1 so the table indices stay contiguous; this
    # entry is intentionally not exposed in lookups (the dict skips it).
    (16,  612,  4,    0,  663, 17),
    (17,  977,  5,  300,  977, 17),
    (18,  977,  7,   -1,  977, 17),
    (19, 1024,  7,  512, 1023, 17),
    (20,  733,  5,  300,  732, 17),
    (21,  733,  7,  300,  732, 17),
    (22,  733,  5,  300,  733, 17),
    (23,  306,  4,    0,  336, 17),
    (24,  612,  4,  305,  663, 17),
    (25,  306,  4,   -1,  340, 17),
    (26,  612,  4,   -1,  670, 17),
    (27,  698,  7,  300,  732, 17),
    (28,  976,  5,  488,  977, 17),
    (29,  306,  4,    0,  340, 17),
    (30,  611,  4,  306,  663, 17),
    (31,  732,  7,  300,  732, 17),
    (32, 1023,  5,   -1, 1023, 17),
    # Phoenix 33..45 — values from Phoenix BIOS reference.
    (33,  614,  4,   -1,  663, 25),
    (34,  775,  2,  254,  775, 27),
    (35,  921,  2,    0,  921, 33),
    (36,  402,  4,    0,  402, 39),
    (37,  580,  6,    0,  580, 26),
    (38,  845,  2,    0,  845, 36),
    (39,  769,  3,  256,  769, 36),
    (40,  531,  4,    0,  532, 39),
    (41,  577,  2,    0,  577, 40),
    (42,  654,  2,    0,  654, 32),
    (43,  923,  5,    0,  923, 36),
    (44,  531,  8,   -1,  532, 39),
    (45, 1024,  8,   -1, 1024, 17),
)

# AMI BIOS HDD types 1..45. Identical to Phoenix for 1..32; AMI's
# 33..45 entries come from their late-80s/early-90s clone BIOS tables
# and differ in geometry from Phoenix for a few sizes (commonly noted
# in motherboard manuals of the era).
_BIOS_AMI_DRIVE_ROWS: tuple[tuple[int, int, int, int, int, int], ...] = (
    # 1..32 — same as Phoenix.
    ( 1,  306,  4,  128,  305, 17),
    ( 2,  615,  4,  300,  615, 17),
    ( 3,  615,  6,  300,  615, 17),
    ( 4,  940,  8,  512,  940, 17),
    ( 5,  940,  6,  512,  940, 17),
    ( 6,  615,  4,   -1,  615, 17),
    ( 7,  462,  8,  256,  511, 17),
    ( 8,  733,  5,   -1,  733, 17),
    ( 9,  900, 15,   -1,  901, 17),
    (10,  820,  3,   -1,  820, 17),
    (11,  855,  5,   -1,  855, 17),
    (12,  855,  7,   -1,  855, 17),
    (13,  306,  8,  128,  319, 17),
    (14,  733,  7,   -1,  733, 17),
    (16,  612,  4,    0,  663, 17),
    (17,  977,  5,  300,  977, 17),
    (18,  977,  7,   -1,  977, 17),
    (19, 1024,  7,  512, 1023, 17),
    (20,  733,  5,  300,  732, 17),
    (21,  733,  7,  300,  732, 17),
    (22,  733,  5,  300,  733, 17),
    (23,  306,  4,    0,  336, 17),
    (24,  612,  4,  305,  663, 17),
    (25,  306,  4,   -1,  340, 17),
    (26,  612,  4,   -1,  670, 17),
    (27,  698,  7,  300,  732, 17),
    (28,  976,  5,  488,  977, 17),
    (29,  306,  4,    0,  340, 17),
    (30,  611,  4,  306,  663, 17),
    (31,  732,  7,  300,  732, 17),
    (32, 1023,  5,   -1, 1023, 17),
    # AMI 33..45 — divergent from Phoenix.
    (33,  830,  7,    0,  830, 17),
    (34,  830, 10,    0,  830, 17),
    (35, 1024, 10,    0, 1024, 17),
    (36, 1024,  8,    0, 1024, 17),
    (37,  615,  8,  128,  615, 17),
    (38,  830,  4,    0,  830, 26),
    (39,  697, 13,   -1,  697, 25),
    (40,  723,  9,    0,  723, 36),
    (41,  723, 13,   -1,  723, 36),
    (42,  855, 15,   -1,  855, 17),
    (43, 1024,  9,    0, 1024, 17),
    (44,  977,  3,   -1,  977, 17),
    (45, 1024,  8,   -1, 1024, 17),
)


def _build_bios_drive_table(
    vendor: BIOSVendor,
    rows: tuple[tuple[int, int, int, int, int, int], ...],
) -> dict[tuple[BIOSVendor, int], BIOSDriveSpec]:
    out: dict[tuple[BIOSVendor, int], BIOSDriveSpec] = {}
    for type_id, cyl, hd, pre, lz, spt in rows:
        out[(vendor, type_id)] = BIOSDriveSpec(
            vendor=vendor,
            type_id=type_id,
            cylinders=cyl,
            heads=hd,
            write_precomp_cylinder=pre,
            landing_zone_cylinder=lz,
            sectors_per_track=spt,
        )
    return out


BIOS_AT_DRIVE_TYPES: dict[tuple[BIOSVendor, int], BIOSDriveSpec] = {
    **_build_bios_drive_table(BIOSVendor.PHOENIX, _BIOS_PHOENIX_DRIVE_ROWS),
    **_build_bios_drive_table(BIOSVendor.AMI, _BIOS_AMI_DRIVE_ROWS),
}


def parse_bios_drive_slug(slug: str) -> tuple[BIOSVendor, int]:
    """Parse a ``<vendor>:<type_id>`` slug used on the CLI / TUI.

    Vendor aliases: ``auto`` → Phoenix (they agree on Types 1..32 and
    Phoenix is the more widely-supported preset table).
    """
    raw = slug.strip().lower()
    if ":" not in raw:
        raise ValueError(
            f"Invalid BIOS drive-type slug {slug!r}; expected '<vendor>:<id>' (e.g. 'phoenix:1')."
        )
    vendor_part, _, id_part = raw.partition(":")
    if vendor_part == "auto":
        vendor = BIOSVendor.PHOENIX
    else:
        try:
            vendor = BIOSVendor(vendor_part)
        except ValueError as exc:
            valid = ", ".join(v.value for v in BIOSVendor)
            raise ValueError(
                f"Unknown BIOS vendor {vendor_part!r}; valid: {valid} (or 'auto')."
            ) from exc
    try:
        type_id = int(id_part)
    except ValueError as exc:
        raise ValueError(
            f"Invalid BIOS drive type id {id_part!r}; must be an integer 1..45."
        ) from exc
    return (vendor, type_id)


def lookup_bios_drive_type(vendor: BIOSVendor, type_id: int) -> BIOSDriveSpec:
    """Return the spec for ``(vendor, type_id)`` or raise ``KeyError``.

    Type 15 is intentionally absent (IBM reserved it; clones omit it).
    """
    key = (vendor, type_id)
    if key not in BIOS_AT_DRIVE_TYPES:
        raise KeyError(
            f"No BIOS drive type {vendor.value}:{type_id} (valid range 1..45 minus 15)."
        )
    return BIOS_AT_DRIVE_TYPES[key]


def iter_bios_drive_types(vendor: BIOSVendor | None = None) -> list[BIOSDriveSpec]:
    """List BIOS drive specs in vendor-then-type-id order."""
    entries = list(BIOS_AT_DRIVE_TYPES.values())
    if vendor is not None:
        entries = [spec for spec in entries if spec.vendor is vendor]
    return sorted(entries, key=lambda s: (s.vendor.value, s.type_id))


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
    custom_payload_path: Path | None = None
    # Optional classic-AT-BIOS hard-drive preset. When set as a
    # ``(vendor, type_id)`` tuple, the VHD's footer CHS + total size
    # are locked to the BIOS-table spec so 86Box BIOS auto-detect
    # shows "Type N" instead of "User-defined / 86B_HD00". Custom is
    # represented by ``None`` (the default) — in that case ``size_bytes``
    # is used as today and the footer gets the 16h/63s canonical CHS.
    bios_drive_type: tuple[BIOSVendor, int] | None = None
    # ``disk_controller`` is the primary way to choose VHD type.
    # When left at None, ``effective_disk_controller`` auto-detects
    # from the boot mode (MFM for compaq2 / msdos33 / ibm8088+dos33 /
    # pcdos, IDE otherwise).  ``custom_chs`` provides a free-form
    # cyl/head/spt geometry source.
    disk_controller: DiskController | None = None
    custom_chs: tuple[int, int, int] | None = None
    # When ``boot_mode == BootMode.FOURDOS``, dosforge first runs the
    # ``host_boot_mode`` build flow to lay down a fully-bootable DOS, then
    # overlays the 4DOS shell on top (copies 4DOS.COM + helpers to
    # ``C:\\4DOS\\`` and rewrites CONFIG.SYS's SHELL= line).  Must be set
    # to a non-FOURDOS, non-NONE boot mode whenever ``boot_mode`` is
    # FOURDOS; ignored for every other boot mode.
    host_boot_mode: BootMode | None = None

    @property
    def bios_drive_spec(self) -> BIOSDriveSpec | None:
        """Resolve ``bios_drive_type`` to a full ``BIOSDriveSpec``."""
        if self.bios_drive_type is None:
            return None
        vendor, type_id = self.bios_drive_type
        return lookup_bios_drive_type(vendor, type_id)

    @property
    def effective_disk_controller(self) -> DiskController:
        """Return the disk controller, auto-detected from boot mode if unset.

        v0.7.0 selection rules:
        - ``disk_controller`` explicitly set: use as-is
        - Otherwise auto-detect from ``boot_mode``:
          * COMPAQ2, MSDOS33, PCDOS, IBM8088+DOS33: MFM (XT-class era)
          * Everything else: IDE
        """
        if self.disk_controller is not None:
            return self.disk_controller
        # Auto-detect path. Keep these branches narrow -- a boot mode
        # only counts as MFM-default when its authentic 1980s hardware
        # used an MFM controller.
        if self.boot_mode is BootMode.COMPAQ2:
            return DiskController.MFM
        if self.boot_mode is BootMode.MSDOS33:
            return DiskController.MFM
        if self.boot_mode is BootMode.PCDOS:
            return DiskController.MFM
        if self.boot_mode is BootMode.PCDOS3:
            return DiskController.MFM
        if self.boot_mode is BootMode.COMPAQ3:
            return DiskController.MFM
        if (
            self.boot_mode is BootMode.IBM8088
            and self.ibm_dos_version is IBMDOSVersion.DOS33
        ):
            return DiskController.MFM
        return DiskController.IDE


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
