"""Phase 14B strict-authenticity tests.

The DOS authenticity rule (saved as a hard project rule in session
memory) requires every boot mode to produce an image byte-equivalent
to a real install from that DOS's own install media.  This test file
locks in the new default behavior: missing CONFIG.SYS / AUTOEXEC.BAT
on the install media is a hard error, not silent synthesis.

Tests in this file do NOT enable the DOSFORGE_ALLOW_SYNTHESIZED_STARTUP
opt-out -- they exercise the strict path explicitly.

Legacy synthesis tests live in tests/test_boot_assets.py with an
autouse fixture that re-enables synthesis for those test cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.boot import BootAssetResolver
from dosforge.commands import CommandRunner
from dosforge.errors import ValidationError


def _touch(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@pytest.fixture
def resolver(tmp_path: Path) -> BootAssetResolver:
    return BootAssetResolver(
        runner=CommandRunner(),
        cache_root=tmp_path / "cache",
    )


def test_strict_missing_config_sys_raises_validation_error(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No env opt-out + missing CONFIG.SYS = hard fail."""
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    files: dict[str, Path] = {}  # neither CONFIG.SYS nor AUTOEXEC.BAT present
    with pytest.raises(ValidationError) as exc_info:
        resolver._ensure_msdos_startup_files(
            files,
            defaults_root=tmp_path / "defaults",
            install_dir="C:\\DOS",
            pre_dos5=False,
        )
    msg = str(exc_info.value)
    assert "CONFIG.SYS" in msg
    assert "AUTOEXEC.BAT" in msg
    assert "authenticity" in msg.lower()


def test_strict_with_both_files_present_succeeds(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User supplies CONFIG.SYS + AUTOEXEC.BAT = no error, no rewrite."""
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    config_path = tmp_path / "CONFIG.SYS"
    autoexec_path = tmp_path / "AUTOEXEC.BAT"
    original_config = b"DEVICE=C:\\DOS\\HIMEM.SYS\r\nFILES=30\r\n"
    original_autoexec = b"@ECHO OFF\r\nPROMPT $P$G\r\nPATH=C:\\DOS;C:\\UTIL\r\n"
    _touch(config_path, original_config)
    _touch(autoexec_path, original_autoexec)
    files: dict[str, Path] = {"CONFIG.SYS": config_path, "AUTOEXEC.BAT": autoexec_path}

    # Should not raise
    resolver._ensure_msdos_startup_files(
        files,
        defaults_root=tmp_path / "defaults",
        install_dir="C:\\DOS",
        pre_dos5=False,
    )

    # Files still point at the originals
    assert files["CONFIG.SYS"] == config_path
    assert files["AUTOEXEC.BAT"] == autoexec_path


def test_strict_normalize_does_not_rewrite_install_media_files(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In strict mode, normalize_msdos_startup_files is a no-op.

    The user's CONFIG.SYS / AUTOEXEC.BAT land byte-verbatim -- no PATH
    rewrites, no DEVICE-line stripping, no normalization at all.
    """
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    config_path = tmp_path / "CONFIG.SYS"
    autoexec_path = tmp_path / "AUTOEXEC.BAT"
    original_config = (
        b"DEVICE=A:\\DOS\\HIMEM.SYS\r\n"  # A:\DOS path that would be rewritten
        b"DEVICE=ANSI.SYS\r\n"
        b"FILES=20\r\n"
    )
    original_autoexec = (
        b"@ECHO OFF\r\n"
        b"PATH=A:\\DOS;A:\\UTIL\r\n"  # A:\... path that would be rewritten
        b"SET PROMPT=$P$G\r\n"
    )
    _touch(config_path, original_config)
    _touch(autoexec_path, original_autoexec)
    files: dict[str, Path] = {"CONFIG.SYS": config_path, "AUTOEXEC.BAT": autoexec_path}

    resolver._normalize_msdos_startup_files(
        files,
        defaults_root=tmp_path / "defaults",
        install_dir="C:\\DOS",
    )

    # Files remain pointed at the originals
    assert files["CONFIG.SYS"] == config_path
    assert files["AUTOEXEC.BAT"] == autoexec_path
    # Contents are unchanged on disk
    assert config_path.read_bytes() == original_config
    assert autoexec_path.read_bytes() == original_autoexec


def test_legacy_opt_in_still_synthesizes(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With DOSFORGE_ALLOW_SYNTHESIZED_STARTUP=1, the old synthesis path runs."""
    monkeypatch.setenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", "1")

    files: dict[str, Path] = {}
    resolver._ensure_msdos_startup_files(
        files,
        defaults_root=tmp_path / "defaults",
        install_dir="C:\\DOS",
        pre_dos5=False,
    )

    # Synthesized files are now in `files`
    assert "CONFIG.SYS" in files
    assert "AUTOEXEC.BAT" in files
    assert files["CONFIG.SYS"].exists()
    assert files["AUTOEXEC.BAT"].exists()


def test_strict_error_mentions_opt_out_workaround(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strict-mode error message must point users at the opt-out."""
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        resolver._ensure_msdos_startup_files(
            {},
            defaults_root=tmp_path / "defaults",
            install_dir="C:\\DOS",
        )
    msg = str(exc_info.value)
    assert "DOSFORGE_ALLOW_SYNTHESIZED_STARTUP" in msg


def test_pre_dos5_skips_strict_require_and_synthesizes(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.8.4: Pre-DOS-5 install media (MS-DOS 3.x, IBM PC-DOS 3.x,
    Compaq DOS 2.x/3.x) legitimately did not ship CONFIG.SYS /
    AUTOEXEC.BAT -- those files were user-created during personalization.
    SETUP.EXE wasn't introduced until DOS 5.0.  Strict authenticity
    mode now skips the require check for pre_dos5=True and falls
    through to synthesis (era-appropriate FILES=30 / BUFFERS=20)."""
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    defaults_root = tmp_path / "defaults"
    files: dict[str, Path] = {}
    # Should NOT raise even though strict mode is on, because pre_dos5=True.
    resolver._ensure_msdos_startup_files(
        files,
        defaults_root=defaults_root,
        install_dir="C:\\DOS",
        pre_dos5=True,
        boot_mode_label="MS-DOS 3.30",
    )
    assert "CONFIG.SYS" in files
    assert "AUTOEXEC.BAT" in files
    assert files["CONFIG.SYS"].exists()
    assert files["AUTOEXEC.BAT"].exists()
    # Synthesized CONFIG.SYS uses the pre-DOS-5 minimal subset
    # (no DOS=HIGH, no HIMEM device, no LASTDRIVE).
    config_text = files["CONFIG.SYS"].read_bytes()
    assert b"FILES=30" in config_text
    assert b"BUFFERS=20" in config_text
    assert b"DOS=HIGH" not in config_text  # DOS 3.x doesn't understand DOS=HIGH


def test_pre_dos5_preserves_user_supplied_startup_files(
    resolver: BootAssetResolver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the user dropped their own CONFIG.SYS / AUTOEXEC.BAT into the
    asset dir, the synthesis loop's 'if already exists, keep it' branch
    must preserve them even in pre_dos5 mode."""
    monkeypatch.delenv("DOSFORGE_ALLOW_SYNTHESIZED_STARTUP", raising=False)

    user_config = tmp_path / "user-config.sys"
    user_auto = tmp_path / "user-autoexec.bat"
    _touch(user_config, b"FILES=99\r\nBUFFERS=99\r\n")
    _touch(user_auto, b"@ECHO Hello world\r\n")
    files = {"CONFIG.SYS": user_config, "AUTOEXEC.BAT": user_auto}

    resolver._ensure_msdos_startup_files(
        files,
        defaults_root=tmp_path / "defaults",
        install_dir="C:\\DOS",
        pre_dos5=True,
        boot_mode_label="MS-DOS 3.30",
    )
    # User-supplied paths kept exactly -- synthesis didn't overwrite.
    assert files["CONFIG.SYS"] == user_config
    assert files["AUTOEXEC.BAT"] == user_auto
    assert b"FILES=99" in files["CONFIG.SYS"].read_bytes()
