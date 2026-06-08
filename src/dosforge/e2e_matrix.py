"""End-to-end build matrix declarations for the test suite.

Enumerates the per-boot-mode CLI invocations the e2e tests iterate
over to verify "every supported combination actually builds and
boots".

NOTE: test infrastructure only -- not imported by the runtime
CLI / GUI / TUI surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BootMode, DiskFormat, FloppyType, MSDOSInstallProfile, MediaType

_LEGACY_FAT16_ONLY = {
    BootMode.IBM8088,
    BootMode.MSDOS33,
    BootMode.MSDOS331,
    BootMode.MSDOS5,
    BootMode.MSDOS6,
    BootMode.MSDOS622,
    BootMode.PCDOS,
    BootMode.PCDOS7,
    BootMode.COMPAQ331,
}


@dataclass(frozen=True, slots=True)
class E2ECase:
    media_type: MediaType
    boot_mode: BootMode
    disk_format: DiskFormat | None
    floppy_type: FloppyType | None
    img_system_format: bool
    dos_profile: MSDOSInstallProfile
    custom_payload: bool

    @property
    def id(self) -> str:
        format_part = self.disk_format.value if self.disk_format is not None else "na"
        floppy_part = self.floppy_type.value if self.floppy_type is not None else "na"
        payload = "payload" if self.custom_payload else "nopayload"
        return (
            f"{self.media_type.value}-"
            f"{self.boot_mode.value}-"
            f"{format_part}-"
            f"{floppy_part}-"
            f"{'sysfmt' if self.img_system_format else 'nosysfmt'}-"
            f"{self.dos_profile.value}-"
            f"{payload}"
        )


def generate_e2e_cases() -> list[E2ECase]:
    cases: list[E2ECase] = []

    for boot_mode in BootMode:
        formats = [DiskFormat.FAT16, DiskFormat.FAT32]
        if boot_mode in _LEGACY_FAT16_ONLY:
            formats = [DiskFormat.FAT16]
        for disk_format in formats:
            for profile in _profiles_for_mode(boot_mode):
                for custom_payload in (False, True):
                    cases.append(
                        E2ECase(
                            media_type=MediaType.VHD,
                            boot_mode=boot_mode,
                            disk_format=disk_format,
                            floppy_type=None,
                            img_system_format=False,
                            dos_profile=profile,
                            custom_payload=custom_payload,
                        )
                    )

    for floppy in FloppyType:
        cases.append(
            E2ECase(
                media_type=MediaType.IMG,
                boot_mode=BootMode.NONE,
                disk_format=None,
                floppy_type=floppy,
                img_system_format=False,
                dos_profile=MSDOSInstallProfile.MINIMAL,
                custom_payload=False,
            )
        )
        for boot_mode in BootMode:
            if boot_mode is BootMode.NONE:
                continue
            for profile in _profiles_for_mode(boot_mode):
                for custom_payload in (False, True):
                    cases.append(
                        E2ECase(
                            media_type=MediaType.IMG,
                            boot_mode=boot_mode,
                            disk_format=None,
                            floppy_type=floppy,
                            img_system_format=True,
                            dos_profile=profile,
                            custom_payload=custom_payload,
                        )
                    )
    return cases


def valid_e2e_cases() -> list[E2ECase]:
    return [case for case in generate_e2e_cases() if _is_valid_case(case)]


def _is_valid_case(case: E2ECase) -> bool:
    if case.media_type is MediaType.IMG:
        if case.floppy_type is None:
            return False
        if case.img_system_format and case.boot_mode is BootMode.NONE:
            return False
        if not case.img_system_format and case.boot_mode is not BootMode.NONE:
            return False
        return True

    if case.disk_format is None:
        return False
    if case.boot_mode in _LEGACY_FAT16_ONLY and case.disk_format is not DiskFormat.FAT16:
        return False
    return True


def _profiles_for_mode(mode: BootMode) -> tuple[MSDOSInstallProfile, ...]:
    if mode in _dos_profile_modes():
        return (MSDOSInstallProfile.MINIMAL, MSDOSInstallProfile.FULL)
    return (MSDOSInstallProfile.MINIMAL,)


def _dos_profile_modes() -> set[BootMode]:
    return {
        BootMode.MSDOS71,
        BootMode.IBM8088,
        BootMode.MSDOS33,
        BootMode.MSDOS331,
        BootMode.MSDOS5,
        BootMode.MSDOS6,
        BootMode.MSDOS622,
        BootMode.PCDOS,
        BootMode.PCDOS7,
        BootMode.COMPAQ331,
    }
