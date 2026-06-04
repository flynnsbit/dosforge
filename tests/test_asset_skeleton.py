"""Tests for dosforge.asset_skeleton — the wheel-bundled readme skeleton
materializer used by ``dosforge init-assets``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge import asset_skeleton


# ---------------------------------------------------------------------------
# Bundle inventory
# ---------------------------------------------------------------------------


def test_skeleton_has_modes() -> None:
    modes = asset_skeleton.iter_skeleton_modes()
    assert modes, "_skeleton package shipped no modes"
    # Every known critical mode must be present so the Linux user gets
    # a populated folder for the boot modes our docs reference.
    for required in ("msdos622", "msdos71", "pcdos71", "freedos", "msdos33"):
        assert required in modes, f"{required} missing from bundled skeleton"


def test_skeleton_readmes_nonempty() -> None:
    root = asset_skeleton.skeleton_root()
    for mode in asset_skeleton.iter_skeleton_modes():
        readme = root / mode / "readme.txt"
        assert readme.is_file(), f"{mode}/readme.txt missing"
        content = readme.read_text(encoding="utf-8")
        assert content.strip(), f"{mode}/readme.txt is empty"


# ---------------------------------------------------------------------------
# materialize() behaviour
# ---------------------------------------------------------------------------


def test_materialize_creates_skeleton(tmp_path: Path) -> None:
    target = tmp_path / "dosassets"
    resolved, created, updated, skipped = asset_skeleton.materialize(target)
    assert resolved == target
    assert created == len(asset_skeleton.iter_skeleton_modes())
    assert updated == 0
    assert skipped == 0
    for mode in asset_skeleton.iter_skeleton_modes():
        assert (target / mode / "readme.txt").is_file()


def test_materialize_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "dosassets"
    asset_skeleton.materialize(target)
    _, created, updated, skipped = asset_skeleton.materialize(target)
    assert created == 0
    assert updated == 0
    assert skipped == len(asset_skeleton.iter_skeleton_modes())


def test_materialize_force_refreshes(tmp_path: Path) -> None:
    target = tmp_path / "dosassets"
    asset_skeleton.materialize(target)
    # Hand-edit one readme so we can confirm --force overwrites it.
    edited = target / "msdos622" / "readme.txt"
    edited.write_text("user-tampered\n", encoding="utf-8")
    _, created, updated, skipped = asset_skeleton.materialize(target, force=True)
    assert created == 0
    assert updated == len(asset_skeleton.iter_skeleton_modes())
    assert skipped == 0
    assert "user-tampered" not in edited.read_text(encoding="utf-8")


def test_materialize_preserves_existing_user_media(tmp_path: Path) -> None:
    """User install media sitting next to a readme must never be touched."""
    target = tmp_path / "dosassets"
    asset_skeleton.materialize(target)
    user_blob = target / "msdos622" / "DISK1.IMG"
    user_blob.write_bytes(b"FAKE IMG" * 100)
    blob_before = user_blob.read_bytes()
    asset_skeleton.materialize(target, force=True)
    assert user_blob.read_bytes() == blob_before
    assert user_blob.is_file()


def test_default_target_honors_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    target = asset_skeleton.default_target()
    assert target == tmp_path / "xdg" / "dosforge" / "dosassets"


def test_default_target_falls_back_to_local_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # On Windows HOME is ignored by Path.home(); skip if needed.
    home = Path.home()
    expected = home / ".local" / "share" / "dosforge" / "dosassets"
    target = asset_skeleton.default_target()
    assert target == expected


# ---------------------------------------------------------------------------
# Shadowing guard: a readme-only skeleton must not shadow real install
# media that lives in a lower-priority well-known root.
# ---------------------------------------------------------------------------


def test_resolve_prefers_real_media_over_readme_only_skeleton(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If XDG holds only a skeleton readme, but ~/.dosforge holds real
    install media for the same mode, the resolver must pick the real one.
    """
    from dosforge import paths

    xdg = tmp_path / "xdg"
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.delenv("DOSFORGE_DOSASSETS_DIR", raising=False)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: home))

    # XDG skeleton: only readme.txt, no install media.
    asset_skeleton.materialize(xdg / "dosforge" / "dosassets")
    # Legacy ~/.dosforge with real install media for msdos622.
    legacy_mode = home / ".dosforge" / "dosassets" / "msdos622"
    legacy_mode.mkdir(parents=True)
    (legacy_mode / "readme.txt").write_text("legacy\n", encoding="utf-8")
    (legacy_mode / "DISK1.IMG").write_bytes(b"FAKE")

    # Run resolution from a cwd that has no local dosassets/.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    resolved = paths.resolve_dos_asset_dir("msdos622")
    assert resolved == legacy_mode
    # Sanity check: a mode that has *only* the XDG skeleton still resolves
    # to the XDG location (no real media anywhere else).
    resolved_skel = paths.resolve_dos_asset_dir("freedos")
    assert resolved_skel == xdg / "dosforge" / "dosassets" / "freedos"
