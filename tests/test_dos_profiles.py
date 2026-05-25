"""Smoke tests for the per-DOS-version authenticity registry.

These tests just verify the metadata is wired up sensibly.  Behavior
tests (Phase 14G) come later once Phases 14B/14D have moved the
synthesis logic onto these profiles.
"""

from __future__ import annotations

import pytest

from dosforge._dos import DosProfile, SystemFile, get_profile, has_profile, install_dir_for_media
from dosforge.models import BootMode, MediaType


# All boot modes that have a registered profile must show up in BootMode
EXPECTED_MODES = (
    "freedos",
    "msdos33",
    "msdos331",
    "msdos5",
    "msdos622",
    "msdos71",
    "pcdos",
    "pcdos7",
    "pcdos71",
    "ibm8088",
    "compaq331",
    "4dos",
)


@pytest.mark.parametrize("mode", EXPECTED_MODES)
def test_profile_exists_for_every_mode(mode: str) -> None:
    assert has_profile(mode), f"No DosProfile registered for boot_mode={mode!r}"
    profile = get_profile(mode)
    assert isinstance(profile, DosProfile)
    assert profile.boot_mode == mode


def test_unknown_boot_mode_raises() -> None:
    assert not has_profile("does-not-exist")
    with pytest.raises(KeyError):
        get_profile("does-not-exist")


def test_only_freedos_is_freedos() -> None:
    """Authenticity rule: only the FreeDOS profile may flag is_freedos=True."""
    for mode in EXPECTED_MODES:
        profile = get_profile(mode)
        if mode == "freedos":
            assert profile.is_freedos, f"{mode} should be is_freedos=True"
        else:
            assert not profile.is_freedos, (
                f"{mode} must not be is_freedos=True -- the authenticity "
                f"rule forbids FreeDOS code paths in non-FreeDOS modes."
            )


def test_freedos_uses_kernel_sys_not_iosys() -> None:
    profile = get_profile("freedos")
    file_names = {f.name for f in profile.system_files}
    assert "KERNEL.SYS" in file_names
    assert "IO.SYS" not in file_names
    assert "MSDOS.SYS" not in file_names


def test_msdos_family_uses_iosys() -> None:
    """MS-DOS family writes IO.SYS + MSDOS.SYS."""
    for mode in ("msdos33", "msdos331", "msdos5", "msdos622", "msdos71"):
        profile = get_profile(mode)
        file_names = {f.name for f in profile.system_files}
        assert "IO.SYS" in file_names, f"{mode} missing IO.SYS"
        assert "MSDOS.SYS" in file_names, f"{mode} missing MSDOS.SYS"
        assert "KERNEL.SYS" not in file_names, f"{mode} should not have FreeDOS KERNEL.SYS"


def test_ibm_pcdos_family_uses_ibmbio() -> None:
    """IBM PC-DOS family uses IBMBIO.COM + IBMDOS.COM, not IO.SYS."""
    for mode in ("pcdos", "pcdos7", "pcdos71", "compaq331"):
        profile = get_profile(mode)
        file_names = {f.name for f in profile.system_files}
        assert "IBMBIO.COM" in file_names, f"{mode} missing IBMBIO.COM"
        assert "IBMDOS.COM" in file_names, f"{mode} missing IBMDOS.COM"
        assert "KERNEL.SYS" not in file_names, f"{mode} should not have FreeDOS KERNEL.SYS"


def test_freedos_install_dir_is_fdos() -> None:
    profile = get_profile("freedos")
    assert profile.install_dir_name == "FDOS"


def test_msdos_install_dir_is_dos() -> None:
    for mode in ("msdos33", "msdos622", "msdos71", "pcdos7"):
        profile = get_profile(mode)
        assert profile.install_dir_name == "DOS", (
            f"{mode} install_dir_name should be 'DOS', got {profile.install_dir_name!r}"
        )


def test_fourdos_install_dir_is_4dos() -> None:
    profile = get_profile("4dos")
    assert profile.install_dir_name == "4DOS"
    # 4DOS is an overlay -- it must NOT claim to provide the host DOS
    assert profile.oem_string == b"", "4DOS overlay has no VBR signature of its own"
    assert not profile.expects_dos_dir, "4DOS overlay relies on host for C:\\DOS"


def test_dos3_family_is_pre_dos5() -> None:
    """DOS 3.x family must declare pre_dos5=True so synthesizers know
    not to emit DOS=HIGH/UMB/AUTO or DEVICE=HIMEM.SYS lines."""
    for mode in ("msdos33", "msdos331", "compaq331", "pcdos"):
        profile = get_profile(mode)
        assert profile.pre_dos5, f"{mode} must be pre_dos5=True"


def test_modern_family_is_not_pre_dos5() -> None:
    for mode in ("msdos5", "msdos622", "msdos71", "pcdos7", "pcdos71", "freedos"):
        profile = get_profile(mode)
        assert not profile.pre_dos5, f"{mode} must not be pre_dos5=True"


def test_fat32_supported_only_in_fat32_families() -> None:
    """FAT32 is only supported by msdos71, pcdos71, freedos, 4dos."""
    fat32_modes = {"msdos71", "pcdos71", "freedos", "4dos"}
    for mode in EXPECTED_MODES:
        profile = get_profile(mode)
        has_fat32 = "fat32" in profile.supported_filesystems
        if mode in fat32_modes:
            assert has_fat32, f"{mode} should support fat32"
        else:
            assert not has_fat32, f"{mode} should NOT support fat32"


def test_emulator_required_modes() -> None:
    """compaq331, msdos33, msdos331, pcdos71, pcdos require emulator
    for the SYS install step."""
    must_emulate = {"compaq331", "msdos33", "msdos331", "pcdos71", "pcdos", "ibm8088"}
    for mode in EXPECTED_MODES:
        profile = get_profile(mode)
        if mode in must_emulate:
            assert profile.requires_emulator_for_sys_install, (
                f"{mode} should require emulator for SYS install"
            )


def test_install_dir_for_media_vhd() -> None:
    profile = get_profile("msdos71")
    assert install_dir_for_media(profile, MediaType.VHD) == "C:\\DOS"


def test_install_dir_for_media_img() -> None:
    profile = get_profile("msdos71")
    assert install_dir_for_media(profile, MediaType.IMG) == "A:\\DOS"


def test_install_dir_for_freedos_is_fdos() -> None:
    profile = get_profile("freedos")
    assert install_dir_for_media(profile, MediaType.VHD) == "C:\\FDOS"


def test_every_bootmode_enum_value_has_a_profile_or_is_none() -> None:
    """Forward-compat guard: every BootMode in models.py must either
    be BootMode.NONE or have a registered DosProfile.  Lets future
    boot modes fail loudly the first time they're added if the
    contributor forgets to register a profile here."""
    for boot_mode in BootMode:
        if boot_mode.value == "none":
            continue
        assert has_profile(boot_mode.value), (
            f"BootMode.{boot_mode.name} ({boot_mode.value!r}) has no "
            f"registered DosProfile in src/dosforge/_dos/.  Add one."
        )
