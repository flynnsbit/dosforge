"""PC-DOS 5 install profile + DiskManager descriptor smoke tests (v0.9.47)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.disk import DiskManager, _legacy_dos_install_descriptor
from dosforge.legacy_dos_install import pcdos5_profile, pcdos7_profile
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)


def test_pcdos5_profile_uses_ibm_system_files(tmp_path: Path) -> None:
    install_img = tmp_path / "Disk01.img"
    install_img.write_bytes(b"\0" * 1024)
    profile = pcdos5_profile(install_img)
    assert profile.label == "IBM PC-DOS 5.0"
    assert profile.install_image == install_img
    assert profile.required_system_files == ("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM")
    assert profile.install_method == "format"
    assert profile.supports_fdisk_mbr is True
    assert profile.format_yes_input == b"Y\r\nY\r\n\r\n"


def test_pcdos5_profile_distinct_from_pcdos7(tmp_path: Path) -> None:
    """PC-DOS 5 and 7 are different DOS generations with different
    labels; they share the FORMAT C: /S pipeline but the labels must
    not collide (used as cache keys + diagnostic strings)."""
    img = tmp_path / "Disk01.img"
    img.write_bytes(b"\0")
    five = pcdos5_profile(img)
    seven = pcdos7_profile(img)
    assert five.label != seven.label


def test_disk_manager_descriptor_for_pcdos5_uses_pcdos5_profile() -> None:
    """``_legacy_dos_install_descriptor`` is the dispatch point for
    every legacy DOS install pipeline.  For BootMode.PCDOS5 it must
    return the pcdos5 descriptor (not msdos5 / pcdos7) so the right
    install assets + AUTOEXEC are used."""
    manager = DiskManager()
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        boot_mode=BootMode.PCDOS5,
        msdos_install_profile=MSDOSInstallProfile.MINIMAL,
    )
    del manager  # silence unused warning; descriptor lookup is stateless
    descriptor = _legacy_dos_install_descriptor(request)
    assert descriptor is not None
    assert descriptor.label == "IBM PC-DOS 5.0"
    assert descriptor.profile_builder is pcdos5_profile


def test_disk_manager_descriptor_for_ibm8088_pcdos5_routes_to_pcdos5_profile() -> None:
    """v0.9.47: picking PC-DOS 5.x under the IBM 8088 boot mode must
    route to ``pcdos5_profile`` (not the MSDOS5 default) so the
    correct IBMBIO/IBMDOS system files are installed."""
    request = CreateRequest(
        path=Path("/tmp/x.vhd"),
        size_bytes=64 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        media_type=MediaType.VHD,
        boot_mode=BootMode.IBM8088,
        ibm_dos_version=IBMDOSVersion.PCDOS5,
        msdos_install_profile=MSDOSInstallProfile.MINIMAL,
    )
    descriptor = _legacy_dos_install_descriptor(request)
    assert descriptor is not None
    assert descriptor.profile_builder is pcdos5_profile


def test_ibm_dos_version_helpers() -> None:
    """The IBMDOSVersion helper properties drive 4-way dispatch in
    disk.py / formlogic.py / boot.py / size.py.  Lock the contract."""
    assert IBMDOSVersion.MSDOS33.is_dos3_class is True
    assert IBMDOSVersion.PCDOS3.is_dos3_class is True
    assert IBMDOSVersion.MSDOS5.is_dos3_class is False
    assert IBMDOSVersion.PCDOS5.is_dos3_class is False

    assert IBMDOSVersion.MSDOS5.is_dos5_class is True
    assert IBMDOSVersion.PCDOS5.is_dos5_class is True
    assert IBMDOSVersion.MSDOS33.is_dos5_class is False
    assert IBMDOSVersion.PCDOS3.is_dos5_class is False

    assert IBMDOSVersion.MSDOS33.asset_dir_name == "msdos33"
    assert IBMDOSVersion.PCDOS3.asset_dir_name == "pcdos3"
    assert IBMDOSVersion.MSDOS5.asset_dir_name == "msdos5"
    assert IBMDOSVersion.PCDOS5.asset_dir_name == "pcdos5"

    # Per-version partition caps (drives size.validate_size_for_ibm_dos
    # and formlogic._state_aware_max_mb).
    assert IBMDOSVersion.PCDOS3.max_size_bytes == 16 * 1024 * 1024
    assert IBMDOSVersion.MSDOS33.max_size_bytes == 32 * 1024 * 1024
    assert IBMDOSVersion.MSDOS5.max_size_bytes == 504 * 1024 * 1024
    assert IBMDOSVersion.PCDOS5.max_size_bytes == 504 * 1024 * 1024


@pytest.mark.parametrize(
    "wire_value, expected",
    [
        ("msdos33", IBMDOSVersion.MSDOS33),
        ("pcdos3", IBMDOSVersion.PCDOS3),
        ("msdos5", IBMDOSVersion.MSDOS5),
        ("pcdos5", IBMDOSVersion.PCDOS5),
        # Legacy v0.9.46-and-earlier wire values must still parse so
        # old state.json files don't break.
        ("dos33", IBMDOSVersion.MSDOS33),
        ("dos50", IBMDOSVersion.MSDOS5),
    ],
)
def test_ibm_dos_version_parse_all_wire_values(wire_value: str, expected: IBMDOSVersion) -> None:
    assert IBMDOSVersion(wire_value) is expected
