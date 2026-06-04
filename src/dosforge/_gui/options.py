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
    IBMDOSVersion,
    MSDOSInstallProfile,
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
    MARTYPC_AT_FORMATS,
    iter_bios_drive_types,
)

MEDIA_TYPE_OPTIONS = [
    ("VHD (fixed-size hard disk)", MediaType.VHD.value),
    ("IMG (floppy)", MediaType.IMG.value),
]

MACHINE_TARGET_OPTIONS = [
    ("Generic (86Box / QEMU / etc.)", MachineTarget.GENERIC.value),
    ("MartyPC IBM/Xebec MFM", MachineTarget.MARTYPC_XEBEC.value),
    ("MartyPC XT-IDE (Rev 2 PIO)", MachineTarget.MARTYPC_XTIDE.value),
    ("MartyPC JR-IDE (PCjr sidecar)", MachineTarget.MARTYPC_JRIDE.value),
]

MARTYPC_XEBEC_DRIVE_TYPE_OPTIONS = [
    (drive_type.description, drive_type.value) for drive_type in MartyPCXebecDriveType
]

MARTYPC_AT_DRIVE_TYPE_OPTIONS = [
    (
        f"{fmt.description}  [{fmt.cylinders}x{fmt.heads}x{fmt.sectors_per_track}]",
        fmt.slug,
    )
    for fmt in MARTYPC_AT_FORMATS
]

BIOS_CUSTOM_VALUE = ""
BIOS_DRIVE_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("Custom - use size field", BIOS_CUSTOM_VALUE),
]
for _vendor in (BIOSVendor.PHOENIX, BIOSVendor.AMI):
    for _spec in iter_bios_drive_types(_vendor):
        BIOS_DRIVE_TYPE_OPTIONS.append((_spec.description, _spec.slug))

DISK_FORMAT_OPTIONS = [
    ("FAT12 (MartyPC Xebec Type 1 only)", DiskFormat.FAT12.value),
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
    ("FreeDOS bootable", BootMode.FREEDOS.value),
    ("MS-DOS 7.1 bootable", BootMode.MSDOS71.value),
    ("IBM PC 8088/V20 (DOS 3.3 / 5.0)", BootMode.IBM8088.value),
    ("MS-DOS 3.3 bootable", BootMode.MSDOS33.value),
    ("MS-DOS 3.31 bootable", BootMode.MSDOS331.value),
    ("MS-DOS 5.0 bootable", BootMode.MSDOS5.value),
    ("MS-DOS 6.22 bootable", BootMode.MSDOS622.value),
    ("PC-DOS bootable", BootMode.PCDOS.value),
    ("PC-DOS 7.0 bootable (XDF media)", BootMode.PCDOS7.value),
    ("PC-DOS 7.1 bootable (FAT32)", BootMode.PCDOS71.value),
    ("Compaq DOS 3.31 bootable", BootMode.COMPAQ331.value),
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
    ("IBM DOS 3.3 (max 32MB)", IBMDOSVersion.DOS33.value),
    ("IBM DOS 5.0 (max ~504MB)", IBMDOSVersion.DOS50.value),
]
