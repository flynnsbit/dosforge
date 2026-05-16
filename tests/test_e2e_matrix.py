from __future__ import annotations

from vhdmaker.models import BootMode, DiskFormat, MediaType

from vhdmaker.e2e_matrix import generate_e2e_cases, valid_e2e_cases


def test_valid_e2e_matrix_has_unique_case_ids() -> None:
    cases = valid_e2e_cases()
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))


def test_valid_e2e_matrix_covers_all_boot_modes_for_vhd() -> None:
    cases = [case for case in valid_e2e_cases() if case.media_type is MediaType.VHD]
    covered = {case.boot_mode for case in cases}
    assert covered == set(BootMode)


def test_valid_e2e_matrix_covers_all_boot_modes_for_img_system_format() -> None:
    cases = [case for case in valid_e2e_cases() if case.media_type is MediaType.IMG and case.img_system_format]
    covered = {case.boot_mode for case in cases}
    assert covered == {mode for mode in BootMode if mode is not BootMode.NONE}


def test_valid_e2e_matrix_covers_vhd_fat_formats_for_supported_modes() -> None:
    cases = [case for case in valid_e2e_cases() if case.media_type is MediaType.VHD]
    by_mode: dict[BootMode, set[DiskFormat]] = {}
    for case in cases:
        assert case.disk_format is not None
        by_mode.setdefault(case.boot_mode, set()).add(case.disk_format)

    assert by_mode[BootMode.NONE] == {DiskFormat.FAT16, DiskFormat.FAT32}
    assert by_mode[BootMode.FREEDOS] == {DiskFormat.FAT16, DiskFormat.FAT32}
    assert by_mode[BootMode.MSDOS71] == {DiskFormat.FAT16, DiskFormat.FAT32}
    # Legacy/IBM modes remain FAT16-only by contract.
    assert by_mode[BootMode.IBM8088] == {DiskFormat.FAT16}
    assert by_mode[BootMode.MSDOS33] == {DiskFormat.FAT16}


def test_generate_e2e_cases_superset_of_valid_cases() -> None:
    generated = generate_e2e_cases()
    valid = valid_e2e_cases()
    assert len(generated) >= len(valid)
