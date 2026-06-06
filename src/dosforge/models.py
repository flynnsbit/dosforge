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
    MSDOS71 = "msdos71"
    IBM8088 = "ibm8088"
    MSDOS33 = "msdos33"
    MSDOS331 = "msdos331"
    MSDOS5 = "msdos5"
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
    # 4DOS shell overlay (planned, requires --host-dos).  Phase 14F
    # implementation is pending until 4DOS install media is provided.
    # When set, dosforge raises a clear "not yet implemented" message
    # rather than producing a partial build.
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


class MachineTarget(str, Enum):
    """Optional emulator/machine profile constraining VHD geometry.

    GENERIC uses canonical ATA 16h/63spt geometry with cap-aware size
    alignment (the default behavior). Machine-specific targets force the
    output VHD to use one of a small fixed set of legacy CHS geometries
    that the emulator's hard disk controller will accept.
    """

    GENERIC = "generic"
    # MartyPC's IBM/Xebec MFM controller validates VHDs against exactly 4
    # hardcoded geometries; see MartyPCXebecDriveType below.
    MARTYPC_XEBEC = "martypc-xebec"
    # MartyPC's XT-IDE (Rev 2, PIO) controller validates VHDs against the
    # 127-entry AtFormats table; see MARTYPC_AT_FORMATS below.
    MARTYPC_XTIDE = "martypc-xtide"
    # MartyPC's JR-IDE (PCjr IDE sidecar) controller — shares the same
    # 127-entry AtFormats table as XT-IDE.
    MARTYPC_JRIDE = "martypc-jride"


@dataclass(frozen=True, slots=True)
class MartyPCAtFormat:
    """One entry from MartyPC's AT/XT-IDE geometry table.

    Source: ``crates/marty_core/src/devices/hdc/at_formats.rs``
    (``AtFormats::vec()`` in dbalsom/martypc). All entries use ``s_off=1``
    (ATA convention, 1-indexed sectors) and 512 byte sectors. ``wpc`` is
    ``None`` for every AT entry.
    """

    slug: str
    cylinders: int
    heads: int
    sectors_per_track: int
    description: str

    @property
    def total_sectors(self) -> int:
        return self.cylinders * self.heads * self.sectors_per_track

    @property
    def size_bytes(self) -> int:
        return self.total_sectors * 512


def _at(c: int, h: int, s: int, desc: str) -> MartyPCAtFormat:
    return MartyPCAtFormat(
        slug=f"at-{c}-{h}-{s}",
        cylinders=c,
        heads=h,
        sectors_per_track=s,
        description=desc,
    )


# All 127 entries of MartyPC's AtFormats::vec(), in the order MartyPC defines
# them. Used by both XT-IDE and JR-IDE controllers; the emulator validates the
# VHD footer's exact CHS triple against this table.
MARTYPC_AT_FORMATS: tuple[MartyPCAtFormat, ...] = (
    _at(306, 4, 17, "10MB (306/4/17)"),
    _at(615, 2, 17, "10MB (615/2/17)"),
    _at(306, 4, 26, "15MB (306/4/26)"),
    _at(1024, 2, 17, "17MB (1024/2/17)"),
    _at(697, 3, 17, "17MB (697/3/17)"),
    _at(306, 8, 17, "20MB (306/8/17)"),
    _at(614, 4, 17, "20MB (614/4/17)"),
    _at(615, 4, 17, "20MB (615/4/17)"),
    _at(670, 4, 17, "22MB (670/4/17)"),
    _at(697, 4, 17, "23MB (697/4/17)"),
    _at(987, 3, 17, "24MB (987/3/17)"),
    _at(820, 4, 17, "27MB (820/4/17)"),
    _at(670, 5, 17, "27MB (670/5/17)"),
    _at(697, 5, 17, "28MB (697/5/17)"),
    _at(733, 5, 17, "30MB (733/5/17)"),
    _at(615, 6, 17, "30MB (615/6/17)"),
    _at(462, 8, 17, "30MB (462/8/17)"),
    _at(306, 8, 26, "31MB (306/8/26)"),
    _at(615, 4, 26, "31MB (615/4/26)"),
    _at(1024, 4, 17, "34MB (1024/4/17)"),
    _at(855, 5, 17, "35MB (855/5/17)"),
    _at(925, 5, 17, "38MB (925/5/17)"),
    _at(932, 5, 17, "38MB (932/5/17)"),
    _at(1024, 2, 40, "40MB (1024/2/40)"),
    _at(809, 6, 17, "40MB (809/6/17)"),
    _at(976, 5, 17, "40MB (976/5/17)"),
    _at(977, 5, 17, "40MB (977/5/17)"),
    _at(698, 7, 17, "40MB (698/7/17)"),
    _at(699, 7, 17, "40MB (699/7/17)"),
    _at(981, 5, 17, "40MB (981/5/17)"),
    _at(615, 8, 17, "40MB (615/8/17)"),
    _at(989, 5, 17, "41MB (989/5/17)"),
    _at(820, 4, 26, "41MB (820/4/26)"),
    _at(1024, 5, 17, "42MB (1024/5/17)"),
    _at(733, 7, 17, "42MB (733/7/17)"),
    _at(754, 7, 17, "43MB (754/7/17)"),
    _at(733, 5, 26, "46MB (733/5/26)"),
    _at(940, 6, 17, "46MB (940/6/17)"),
    _at(615, 6, 26, "46MB (615/6/26)"),
    _at(462, 8, 26, "46MB (462/8/26)"),
    _at(830, 7, 17, "48MB (830/7/17)"),
    _at(855, 7, 17, "49MB (855/7/17)"),
    _at(751, 8, 17, "49MB (751/8/17)"),
    _at(1024, 4, 26, "52MB (1024/4/26)"),
    _at(918, 7, 17, "53MB (918/7/17)"),
    _at(925, 7, 17, "53MB (925/7/17)"),
    _at(855, 5, 26, "54MB (855/5/26)"),
    _at(977, 7, 17, "56MB (977/7/17)"),
    _at(987, 7, 17, "57MB (987/7/17)"),
    _at(1024, 7, 17, "59MB (1024/7/17)"),
    _at(823, 4, 38, "61MB (823/4/38)"),
    _at(925, 8, 17, "61MB (925/8/17)"),
    _at(809, 6, 26, "61MB (809/6/26)"),
    _at(976, 5, 26, "61MB (976/5/26)"),
    _at(977, 5, 26, "62MB (977/5/26)"),
    _at(698, 7, 26, "61MB (698/7/26)"),
    _at(699, 7, 26, "62MB (699/7/26)"),
    _at(940, 8, 17, "62MB (940/8/17)"),
    _at(615, 8, 26, "62MB (615/8/26)"),
    _at(1024, 5, 26, "65MB (1024/5/26)"),
    _at(733, 7, 26, "65MB (733/7/26)"),
    _at(1024, 8, 17, "68MB (1024/8/17)"),
    _at(823, 10, 17, "68MB (823/10/17)"),
    _at(754, 11, 17, "68MB (754/11/17)"),
    _at(830, 10, 17, "68MB (830/10/17)"),
    _at(925, 9, 17, "69MB (925/9/17)"),
    _at(1224, 7, 17, "71MB (1224/7/17)"),
    _at(940, 6, 26, "71MB (940/6/26)"),
    _at(855, 7, 26, "75MB (855/7/26)"),
    _at(751, 8, 26, "76MB (751/8/26)"),
    _at(1024, 9, 17, "76MB (1024/9/17)"),
    _at(965, 10, 17, "80MB (965/10/17)"),
    _at(969, 5, 34, "80MB (969/5/34)"),
    _at(980, 10, 17, "81MB (980/10/17)"),
    _at(960, 5, 35, "82MB (960/5/35)"),
    _at(918, 11, 17, "83MB (918/11/17)"),
    _at(1024, 10, 17, "85MB (1024/10/17)"),
    _at(977, 7, 26, "86MB (977/7/26)"),
    _at(1024, 7, 26, "91MB (1024/7/26)"),
    _at(1024, 11, 17, "93MB (1024/11/17)"),
    _at(940, 8, 26, "95MB (940/8/26)"),
    _at(776, 8, 33, "100MB (776/8/33)"),
    _at(755, 16, 17, "100MB (755/16/17)"),
    _at(1024, 12, 17, "102MB (1024/12/17)"),
    _at(1024, 8, 26, "104MB (1024/8/26)"),
    _at(823, 10, 26, "104MB (823/10/26)"),
    _at(830, 10, 26, "105MB (830/10/26)"),
    _at(925, 9, 26, "105MB (925/9/26)"),
    _at(960, 9, 26, "109MB (960/9/26)"),
    _at(1024, 13, 17, "110MB (1024/13/17)"),
    _at(1224, 11, 17, "111MB (1224/11/17)"),
    _at(900, 15, 17, "112MB (900/15/17)"),
    _at(969, 7, 34, "112MB (969/7/34)"),
    _at(917, 15, 17, "114MB (917/15/17)"),
    _at(918, 15, 17, "114MB (918/15/17)"),
    _at(1524, 4, 39, "116MB (1524/4/39)"),
    _at(1024, 9, 26, "117MB (1024/9/26)"),
    _at(1024, 14, 17, "119MB (1024/14/17)"),
    _at(965, 10, 26, "122MB (965/10/26)"),
    _at(980, 10, 26, "124MB (980/10/26)"),
    _at(1020, 15, 17, "127MB (1020/15/17)"),
    _at(1023, 15, 17, "127MB (1023/15/17)"),
    _at(1024, 15, 17, "127MB (1024/15/17)"),
    _at(1024, 16, 17, "136MB (1024/16/17)"),
    _at(1224, 15, 17, "152MB (1224/15/17)"),
    _at(755, 16, 26, "153MB (755/16/26)"),
    _at(903, 8, 46, "162MB (903/8/46)"),
    _at(984, 10, 34, "163MB (984/10/34)"),
    _at(900, 15, 26, "171MB (900/15/26)"),
    _at(917, 15, 26, "174MB (917/15/26)"),
    _at(1023, 15, 26, "194MB (1023/15/26)"),
    _at(684, 16, 38, "203MB (684/16/38)"),
    _at(1930, 4, 62, "233MB (1930/4/62)"),
    _at(967, 16, 31, "234MB (967/16/31)"),
    _at(1013, 10, 63, "311MB (1013/10/63)"),
    _at(1218, 15, 36, "321MB (1218/15/36)"),
    _at(654, 16, 63, "321MB (654/16/63)"),
    _at(659, 16, 63, "324MB (659/16/63)"),
    _at(702, 16, 63, "345MB (702/16/63)"),
    _at(1002, 13, 63, "400MB (1002/13/63)"),
    _at(854, 16, 63, "420MB (854/16/63)"),
    _at(987, 16, 63, "485MB (987/16/63)"),
    _at(995, 16, 63, "489MB (995/16/63)"),
    _at(1024, 16, 63, "504MB (1024/16/63)"),
    _at(1036, 16, 63, "509MB (1036/16/63)"),
    _at(1120, 16, 59, "516MB (1120/16/59)"),
    _at(1054, 16, 63, "518MB (1054/16/63)"),
)

MARTYPC_AT_FORMATS_BY_SLUG: dict[str, MartyPCAtFormat] = {
    fmt.slug: fmt for fmt in MARTYPC_AT_FORMATS
}

# Sensible default: the entry that matches generic-target's natural 504 MiB
# alignment (1024 cyl × 16 heads × 63 spt). Same bytes as a generic-target
# VHD created with that exact size, so users transitioning between modes
# get predictable behavior.
DEFAULT_MARTYPC_AT_FORMAT_SLUG: str = "at-1024-16-63"


def lookup_martypc_at_format(slug: str) -> MartyPCAtFormat:
    fmt = MARTYPC_AT_FORMATS_BY_SLUG.get(slug)
    if fmt is None:
        raise ValueError(
            f"Unknown MartyPC AT/XT-IDE drive type slug: {slug!r}. "
            f"Expected one of {len(MARTYPC_AT_FORMATS)} entries from MartyPC's AtFormats table."
        )
    return fmt


@dataclass(frozen=True, slots=True)
class MartyPCXebecSpec:
    cylinders: int
    heads: int
    sectors_per_track: int
    write_precomp_cylinder: int
    description: str

    @property
    def total_sectors(self) -> int:
        return self.cylinders * self.heads * self.sectors_per_track

    @property
    def size_bytes(self) -> int:
        return self.total_sectors * 512


class MartyPCXebecDriveType(str, Enum):
    """MartyPC IBM/Xebec MFM controller drive types.

    These four geometries are the only sizes the Xebec HDC in MartyPC will
    accept. The emulator validates the VHD footer CHS against this exact
    table at mount time; mismatched VHDs fail with ``UnsupportedVHD``.

    Source: ``crates/marty_core/src/devices/hdc/xebec.rs`` in dbalsom/martypc.
    """

    TYPE1 = "type1"      # 10 MiB
    TYPE16 = "type16"    # 20 MiB
    TYPE2 = "type2"      # 20 MiB
    TYPE13 = "type13"    # 20 MiB

    @property
    def spec(self) -> MartyPCXebecSpec:
        return _MARTYPC_XEBEC_SPECS[self]

    @property
    def cylinders(self) -> int:
        return self.spec.cylinders

    @property
    def heads(self) -> int:
        return self.spec.heads

    @property
    def sectors_per_track(self) -> int:
        return self.spec.sectors_per_track

    @property
    def size_bytes(self) -> int:
        return self.spec.size_bytes

    @property
    def description(self) -> str:
        return self.spec.description


_MARTYPC_XEBEC_SPECS: dict[MartyPCXebecDriveType, MartyPCXebecSpec] = {
    MartyPCXebecDriveType.TYPE1: MartyPCXebecSpec(
        cylinders=306,
        heads=4,
        sectors_per_track=17,
        write_precomp_cylinder=0,
        description="10 MiB (306x4x17, Type 1)",
    ),
    MartyPCXebecDriveType.TYPE16: MartyPCXebecSpec(
        cylinders=612,
        heads=4,
        sectors_per_track=17,
        write_precomp_cylinder=0,
        description="20 MiB (612x4x17, Type 16)",
    ),
    MartyPCXebecDriveType.TYPE2: MartyPCXebecSpec(
        cylinders=615,
        heads=4,
        sectors_per_track=17,
        write_precomp_cylinder=300,
        description="20 MiB (615x4x17, Type 2)",
    ),
    MartyPCXebecDriveType.TYPE13: MartyPCXebecSpec(
        cylinders=306,
        heads=8,
        sectors_per_track=17,
        write_precomp_cylinder=128,
        description="20 MiB (306x8x17, Type 13)",
    ),
}


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
    machine_target: MachineTarget = MachineTarget.GENERIC
    martypc_xebec_drive_type: MartyPCXebecDriveType = MartyPCXebecDriveType.TYPE2
    martypc_at_drive_type_slug: str = DEFAULT_MARTYPC_AT_FORMAT_SLUG
    # Optional classic-AT-BIOS hard-drive preset. When set as a
    # ``(vendor, type_id)`` tuple, the VHD's footer CHS + total size
    # are locked to the BIOS-table spec so 86Box BIOS auto-detect
    # shows "Type N" instead of "User-defined / 86B_HD00". Custom is
    # represented by ``None`` (the default) — in that case ``size_bytes``
    # is used as today and the footer gets the 16h/63s canonical CHS.
    bios_drive_type: tuple[BIOSVendor, int] | None = None
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
    def martypc_at_drive_type(self) -> MartyPCAtFormat:
        return lookup_martypc_at_format(self.martypc_at_drive_type_slug)


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
