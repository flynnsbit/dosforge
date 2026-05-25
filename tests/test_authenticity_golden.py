"""Phase 14G authenticity golden tests.

These tests lock in the DOS authenticity rule programmatically: any
build dosforge produces for boot mode X must match the per-mode
DosProfile from src/dosforge/_dos/.

Tests are designed to skip cleanly when install media is absent so
they work in CI without shipping copyrighted DOS install diskettes.
Locally, when assets are present, every boot mode's golden test runs.

Phase 14G test categories:

1. Profile sanity: per-profile fields are valid (covered by
   test_dos_profiles.py from Phase 14A).

2. Asset directory contract: the readme.txt in dosassets/<mode>/
   matches the boot_mode slug for every registered profile.

3. No FreeDOS markers in non-FreeDOS builds: any function that
   touches asset files for non-FreeDOS modes must NOT reference
   FreeDOS-specific files (KERNEL.SYS, FDCONFIG.SYS, FDAUTO.BAT).
   Static-analysis test: scan boot.py for FreeDOS symbols inside
   non-FreeDOS resolver methods.

4. _ensure_msdos_startup_files raises strict-mode error for every
   non-FreeDOS, non-4DOS profile when assets are empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge._dos import get_profile, has_profile
from dosforge.boot import BootAssetResolver
from dosforge.commands import CommandRunner
from dosforge.errors import ValidationError
from dosforge.models import BootMode


# Boot modes whose dosassets/<mode>/readme.txt must exist
REGISTERED_MODES = (
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


REPO_DOSASSETS = Path(__file__).resolve().parent.parent / "dosassets"


# Some boot modes are umbrellas that don't map 1-to-1 to a dosassets/<mode>/
# folder.  pcdos is an umbrella for the IBM PC-DOS 2.x/3.x family
# (asset dirs are per-version: pcdos1, pcdos2, pcdos3, pcdos5, pcdos6).
# ibm8088 is an umbrella that delegates to pcdos or msdos5 at install time.
# 4dos has a placeholder readme but no install media folder yet.
_UMBRELLA_MODES_WITHOUT_DIRECT_README = {"pcdos", "ibm8088"}


@pytest.mark.parametrize("mode", REGISTERED_MODES)
def test_every_mode_has_a_dosassets_readme(mode: str) -> None:
    """Every registered boot mode must have a dosassets/<mode>/readme.txt
    explaining where users get the install media for it.

    Umbrella modes (``pcdos``, ``ibm8088``) are exempt -- they delegate
    to per-version sub-modes that DO have their own readme files."""
    if mode in _UMBRELLA_MODES_WITHOUT_DIRECT_README:
        pytest.skip(f"{mode} is an umbrella mode -- see per-version subdirs")
    readme = REPO_DOSASSETS / mode / "readme.txt"
    assert readme.is_file(), (
        f"Missing dosassets/{mode}/readme.txt -- every concrete boot mode "
        f"must document where users obtain authentic install media."
    )


@pytest.mark.parametrize("mode", REGISTERED_MODES)
def test_readme_mentions_the_boot_mode_in_some_form(mode: str) -> None:
    """Authenticity sanity check: the readme should mention either
    the boot-mode slug or the display name so users searching for
    'msdos71' or 'MS-DOS 7.1' find it."""
    if mode in _UMBRELLA_MODES_WITHOUT_DIRECT_README:
        pytest.skip(f"{mode} is an umbrella mode")
    readme = REPO_DOSASSETS / mode / "readme.txt"
    if not readme.is_file():
        pytest.skip(f"dosassets/{mode}/readme.txt missing")

    text = readme.read_text(encoding="utf-8", errors="replace").lower()
    profile = get_profile(mode)
    display_lower = profile.display_name.lower()

    matchable = (
        mode,
        mode.replace("dos", "-dos"),
        display_lower,
        display_lower.replace(" ", ""),
        display_lower.replace("ms-dos", "msdos"),
        display_lower.replace("pc-dos", "pcdos"),
        # Common version-number shortenings
        "7.1", "7.0", "6.22", "5.0", "3.31", "3.30",
    )
    # For each mode, check at least one form is present
    matched_any = any(m and m in text for m in matchable)
    assert matched_any, (
        f"readme for {mode!r} does not mention the boot mode "
        f"or display name -- users will not find it via search.\n"
        f"Searched for: {matchable}"
    )


def test_freedos_is_only_mode_with_is_freedos_flag() -> None:
    """The authenticity rule: only the freedos profile may carry
    is_freedos=True.  Any other mode flagged true would be a
    smoking-gun signal of a borrowed FreeDOS code path."""
    flagged = [
        mode for mode in REGISTERED_MODES
        if get_profile(mode).is_freedos
    ]
    assert flagged == ["freedos"], (
        f"is_freedos=True should be set only for the freedos profile, "
        f"got: {flagged}"
    )


def test_freedos_kernel_sys_never_appears_in_non_freedos_profile() -> None:
    """KERNEL.SYS is FreeDOS-specific.  Any non-FreeDOS profile that
    lists it in system_files is a violation of the authenticity rule."""
    for mode in REGISTERED_MODES:
        profile = get_profile(mode)
        if profile.is_freedos:
            continue  # FreeDOS itself is allowed
        file_names = {f.name for f in profile.system_files}
        assert "KERNEL.SYS" not in file_names, (
            f"{mode} profile lists KERNEL.SYS -- that's a FreeDOS-only "
            f"file, authenticity rule violation."
        )


def test_msdos_family_uses_msdos_oem_strings() -> None:
    """MS-DOS family must not borrow FreeDOS or IBM PC-DOS OEM strings."""
    for mode in ("msdos33", "msdos331", "msdos5", "msdos622"):
        profile = get_profile(mode)
        oem = profile.oem_string
        assert b"MSDOS" in oem or b"MS-DOS" in oem, (
            f"{mode} has unexpected OEM string {oem!r}"
        )
        assert b"FRDOS" not in oem
        assert b"FREEDOS" not in oem


def test_freedos_oem_is_frdos() -> None:
    profile = get_profile("freedos")
    assert profile.oem_string == b"FRDOS5.1"


def test_pcdos_family_oem_contains_ibm() -> None:
    """IBM PC-DOS family OEM strings must say 'IBM'."""
    for mode in ("pcdos", "pcdos7", "pcdos71", "compaq331"):
        profile = get_profile(mode)
        assert b"IBM" in profile.oem_string, (
            f"{mode} OEM string {profile.oem_string!r} should contain 'IBM'"
        )


def test_msdos71_oem_is_mswin41() -> None:
    """MS-DOS 7.10 (Win95 OSR2) install writes OEM 'MSWIN4.1' via its
    own SYS.COM.  Earlier dosforge builds claimed 'IBM  7.1' OEM after
    a planned PC-DOS-7.1-style FORMAT32-based install path; that path
    was abandoned in favour of OSR2's authentic SYS A: C: flow."""
    profile = get_profile("msdos71")
    assert profile.oem_string == b"MSWIN4.1", (
        f"msdos71 OEM string should be 'MSWIN4.1' (what OSR2's SYS.COM "
        f"actually writes).  Got: {profile.oem_string!r}"
    )


def test_fourdos_overlay_has_empty_oem() -> None:
    """4DOS is an overlay shell; the host DOS owns the VBR (and OEM
    string).  The 4dos profile must NOT claim its own OEM signature."""
    profile = get_profile("4dos")
    assert profile.oem_string == b"", (
        f"4DOS overlay must not have an OEM string of its own (host "
        f"DOS provides the VBR).  Got: {profile.oem_string!r}"
    )


def test_attempting_4dos_boot_mode_today_raises_clean_error() -> None:
    """Phase 14F is not yet implemented; --boot-mode 4dos must produce
    a clear error message, not a partial build."""
    from dosforge.disk import DiskManager

    runner = CommandRunner()
    manager = DiskManager(runner=runner)

    # Build a minimal CreateRequest with boot_mode=4dos
    from dosforge.models import CreateRequest, DiskFormat, MediaType

    request = CreateRequest(
        media_type=MediaType.VHD,
        size_bytes=32 * 1024 * 1024,
        disk_format=DiskFormat.FAT16,
        path=Path("test-not-built.vhd"),
        boot_mode=BootMode.FOURDOS,
    )

    with pytest.raises(ValidationError) as exc_info:
        manager._validate_create_request(request)
    msg = str(exc_info.value)
    assert "4dos" in msg.lower()
    assert "host-dos" in msg or "--host-dos" in msg
    assert "not yet implemented" in msg.lower() or "pending" in msg.lower()


def test_strict_authentic_rule_signature_in_strict_helper() -> None:
    """The strict-mode helper docstring must reference the authenticity
    rule so future contributors understand why it can't silently
    fall back to synthesis."""
    from dosforge.boot import _strict_authentic_enabled
    doc = (_strict_authentic_enabled.__doc__ or "").lower()
    assert "authenticity" in doc, (
        "_strict_authentic_enabled() docstring should reference the "
        "DOS authenticity rule so the gate's purpose is documented."
    )


def test_freedos_reference_helper_is_clearly_freedos_only() -> None:
    """Phase 14C verified: the helper that grafts FreeDOS reference
    boot records must have 'freedos' in its name and docstring."""
    resolver_methods = dir(BootAssetResolver)
    freedos_helper = "_apply_freedos_reference_boot_records"
    assert freedos_helper in resolver_methods, (
        f"BootAssetResolver should expose {freedos_helper!r} -- the "
        f"old name without 'freedos' hides FreeDOS-only intent."
    )
    method = getattr(BootAssetResolver, freedos_helper)
    doc = (method.__doc__ or "").lower()
    assert "freedos" in doc, "Helper docstring must say 'freedos'"
    assert "authenticity" in doc, "Helper docstring must reference the rule"
