"""Static option lists (label, value) for the create form selects.

These mirror the Textual app's option lists exactly (``app.py`` lines 51-98
and the inline boot/media/format selects) but are defined here against the
``models`` enums so the GUI never imports the Textual app.
"""

from __future__ import annotations

from ..models import (
    BIOSVendor,
    BootMode,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    GeometrySource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    DiskController,
    MediaType,
    iter_bios_drive_types,
)

MEDIA_TYPE_OPTIONS = [
    ("VHD (fixed-size hard disk)", MediaType.VHD.value),
    ("IMG (floppy)", MediaType.IMG.value),
]

DISK_CONTROLLER_OPTIONS = [
    ("Auto-detect from boot mode", ""),
    ("IDE (AT-class)", DiskController.IDE.value),
    ("MFM (XT-class, ST-225 era)", DiskController.MFM.value),
    ("XT-IDE (XT-class, MartyPC default)", DiskController.XTIDE.value),
]

GEOMETRY_SOURCE_OPTIONS = [
    ("Static size (auto geometry)", GeometrySource.SIZE.value),
    ("BIOS preset (Phoenix / AMI / MartyPC-Xebec type table)", GeometrySource.PRESET.value),
    ("Custom CHS (cylinders, heads, sectors)", GeometrySource.CUSTOM_CHS.value),
]


BIOS_CUSTOM_VALUE = ""
BIOS_DRIVE_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("Custom - use size field", BIOS_CUSTOM_VALUE),
]
for _vendor in (BIOSVendor.PHOENIX, BIOSVendor.AMI, BIOSVendor.MARTYPC_XEBEC):
    for _spec in iter_bios_drive_types(_vendor):
        BIOS_DRIVE_TYPE_OPTIONS.append((_spec.description, _spec.slug))

DISK_FORMAT_OPTIONS = [
    ("FAT12 (MFM / DOS 2.x-3.x)", DiskFormat.FAT12.value),
    ("FAT16", DiskFormat.FAT16.value),
    ("FAT32", DiskFormat.FAT32.value),
]

FLOPPY_OPTIONS = [
    ("160K", FloppyType.F160K.value),
    ("180K", FloppyType.F180K.value),
    ("360K", FloppyType.F360K.value),
    ("720K", FloppyType.F720K.value),
    ("1.84M (XDF)", FloppyType.F1840K.value),
    ("1.2M", FloppyType.F1200K.value),
    ("1.44M", FloppyType.F1440K.value),
    ("2.88M", FloppyType.F2880K.value),
]

BOOT_MODE_OPTIONS = [
    ("None (data disk only)", BootMode.NONE.value),
    ("FreeDOS", BootMode.FREEDOS.value),
    ("MS-DOS 7.10 / Win95 OSR2 (4.00.1111, FAT16/FAT32)", BootMode.MSDOS71.value),
    ("IBM PC 8088/V20 (DOS 3.3 or 5.0)", BootMode.IBM8088.value),
    ("MS-DOS 3.30", BootMode.MSDOS33.value),
    ("MS-DOS 3.31", BootMode.MSDOS331.value),
    ("MS-DOS 5.0", BootMode.MSDOS5.value),
    ("MS-DOS 6.0", BootMode.MSDOS6.value),
    ("MS-DOS 6.22", BootMode.MSDOS622.value),
    ("IBM PC-DOS 3.00 (1984, 360k DSDD)", BootMode.PCDOS3.value),
    ("MS-DOS 3.00 Compaq OEM (1985, 360k DSDD)", BootMode.COMPAQ3.value),
    ("IBM PC-DOS 7.0 (XDF media)", BootMode.PCDOS7.value),
    ("IBM PC-DOS 2000 (6-floppy set)", BootMode.PCDOS2000.value),
    ("IBM PC-DOS 7.1 (FAT32)", BootMode.PCDOS71.value),
    ("Compaq DOS 2.11 (1984, 360k DSDD or 10 MiB MFM VHD)", BootMode.COMPAQ2.value),
    ("Compaq DOS 3.31", BootMode.COMPAQ331.value),
    ("Digital Research DR DOS 6.0 (1991, 720k DSDD)", BootMode.DRDOS6.value),
    ("Caldera DR-DOS 7.03 (1999, FAT16 BIGDOS)", BootMode.DRDOS7.value),
]

FREEDOS_SOURCE_OPTIONS = [
    ("Local FreeDOS assets", FreeDOSSource.LOCAL.value),
    ("Auto-download FreeDOS image", FreeDOSSource.AUTO.value),
]

DOS_INSTALL_PROFILE_OPTIONS = [
    ("Boot files only", MSDOSInstallProfile.MINIMAL.value),
    ("Core DOS tools + startup files", MSDOSInstallProfile.FULL.value),
]

IBM_DOS_VERSION_OPTIONS = [
    ("MS-DOS 3.3 (max 32MB)", IBMDOSVersion.MSDOS33.value),
    ("PC-DOS 3.x (max 16MB, FAT12)", IBMDOSVersion.PCDOS3.value),
    ("MS-DOS 5.0 (max ~504MB)", IBMDOSVersion.MSDOS5.value),
    ("PC-DOS 5.x (max ~504MB)", IBMDOSVersion.PCDOS5.value),
]
