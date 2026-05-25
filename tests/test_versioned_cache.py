"""Unit tests for the versioned-cache helper.

Phase: introduced to fix the MBR-cache-invalidation bug where a
constant change was masked by the persistent pre-fix cache blob.
The helper embeds a SHA-256 prefix of the content into the cache
filename so that different bytes produce different filenames.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dosforge.boot import _content_stamp, materialize_versioned_cache


def test_content_stamp_is_deterministic() -> None:
    assert _content_stamp(b"hello") == _content_stamp(b"hello")
    assert _content_stamp(b"hello") != _content_stamp(b"world")


def test_content_stamp_default_length_is_8_hex() -> None:
    stamp = _content_stamp(b"any-bytes")
    assert len(stamp) == 8
    assert all(c in "0123456789abcdef" for c in stamp)


def test_content_stamp_custom_length() -> None:
    stamp = _content_stamp(b"any-bytes", length=16)
    assert len(stamp) == 16


def test_materialize_versioned_cache_writes_file(tmp_path: Path) -> None:
    data = b"my-mbr-bytes" * 40  # 480 bytes
    cache_path = materialize_versioned_cache(
        tmp_path, base_name="test-cache", source_bytes=data, min_size=440
    )
    assert cache_path.is_file()
    assert cache_path.read_bytes() == data
    assert "test-cache-" in cache_path.name
    assert cache_path.name.endswith(".bin")


def test_distinct_bytes_produce_distinct_cache_paths(tmp_path: Path) -> None:
    """The whole point: changing the source bytes ALWAYS changes the
    filename, so a stale cache can never mask a constant change."""
    path_a = materialize_versioned_cache(
        tmp_path, base_name="mbr", source_bytes=b"A" * 440, min_size=440
    )
    path_b = materialize_versioned_cache(
        tmp_path, base_name="mbr", source_bytes=b"B" * 440, min_size=440
    )
    assert path_a != path_b
    assert path_a.read_bytes() == b"A" * 440
    assert path_b.read_bytes() == b"B" * 440


def test_identical_bytes_reuse_same_cache(tmp_path: Path) -> None:
    """Second call with same bytes returns same path -- no rewrite."""
    data = b"x" * 440
    path1 = materialize_versioned_cache(
        tmp_path, base_name="mbr", source_bytes=data, min_size=440
    )
    mtime1 = path1.stat().st_mtime_ns

    path2 = materialize_versioned_cache(
        tmp_path, base_name="mbr", source_bytes=data, min_size=440
    )
    assert path1 == path2
    # File not rewritten (same mtime)
    assert path2.stat().st_mtime_ns == mtime1


def test_cache_rewrites_when_existing_file_too_small(tmp_path: Path) -> None:
    """If a previous cache file got truncated/corrupted, regenerate."""
    data = b"y" * 440
    stamp = _content_stamp(data)
    pre_existing = tmp_path / f"mbr-{stamp}.bin"
    pre_existing.parent.mkdir(parents=True, exist_ok=True)
    pre_existing.write_bytes(b"truncated")  # 9 bytes < 440

    path = materialize_versioned_cache(
        tmp_path, base_name="mbr", source_bytes=data, min_size=440
    )
    assert path == pre_existing
    assert path.read_bytes() == data  # rewritten


def test_cache_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    # nested doesn't exist yet
    assert not nested.exists()
    path = materialize_versioned_cache(
        nested, base_name="mbr", source_bytes=b"z" * 440, min_size=440
    )
    assert path.is_file()
    assert path.parent == nested


def test_filename_format_is_basename_sha8_bin(tmp_path: Path) -> None:
    """Filename must be exactly <base>-<8-hex>.bin so users + scripts
    can predict the path."""
    data = b"k" * 100
    path = materialize_versioned_cache(
        tmp_path, base_name="some-blob", source_bytes=data, min_size=10
    )
    # Format check
    name = path.name
    assert name.startswith("some-blob-")
    assert name.endswith(".bin")
    middle = name[len("some-blob-"):-len(".bin")]
    assert len(middle) == 8
    assert all(c in "0123456789abcdef" for c in middle)


# ---------------------------------------------------------------------------
# cleanup_legacy_cache_files: housekeeping for pre-Phase-14G un-versioned
# cache files that may still exist on a user's machine.
# ---------------------------------------------------------------------------
from dosforge.boot import (  # noqa: E402  -- imported here to keep top-level imports stable
    cleanup_legacy_cache_files,
    _LEGACY_MOUNT_ROOT_CACHE_FILES,
    _LEGACY_CACHE_ROOT_CACHE_FILES,
)


def test_cleanup_removes_named_legacy_files(tmp_path: Path) -> None:
    target = tmp_path / "msdos-builtin-mbr.bin"
    target.write_bytes(b"legacy")
    other = tmp_path / "freedos-fat12-bootsect.bin"
    other.write_bytes(b"legacy2")

    removed = cleanup_legacy_cache_files(
        tmp_path,
        ("msdos-builtin-mbr.bin", "freedos-fat12-bootsect.bin"),
    )
    assert sorted(p.name for p in removed) == [
        "freedos-fat12-bootsect.bin",
        "msdos-builtin-mbr.bin",
    ]
    assert not target.exists()
    assert not other.exists()


def test_cleanup_leaves_sha_stamped_siblings_untouched(tmp_path: Path) -> None:
    """The whole safety claim: removing 'msdos-builtin-mbr.bin' must NEVER
    delete 'msdos-builtin-mbr-d9ae89cb.bin' (the new SHA-stamped version)."""
    legacy = tmp_path / "msdos-builtin-mbr.bin"
    legacy.write_bytes(b"old-bytes" * 50)
    versioned = tmp_path / "msdos-builtin-mbr-d9ae89cb.bin"
    versioned.write_bytes(b"new-bytes" * 50)

    removed = cleanup_legacy_cache_files(tmp_path, ("msdos-builtin-mbr.bin",))
    assert removed == [legacy]
    assert not legacy.exists()
    assert versioned.exists()
    assert versioned.read_bytes() == b"new-bytes" * 50


def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    legacy = tmp_path / "msdos-builtin-mbr.bin"
    legacy.write_bytes(b"x")
    first = cleanup_legacy_cache_files(tmp_path, ("msdos-builtin-mbr.bin",))
    second = cleanup_legacy_cache_files(tmp_path, ("msdos-builtin-mbr.bin",))
    assert first == [legacy]
    assert second == []


def test_cleanup_missing_directory_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert cleanup_legacy_cache_files(missing, ("msdos-builtin-mbr.bin",)) == []


def test_cleanup_ignores_unknown_files_in_directory(tmp_path: Path) -> None:
    """Files NOT in the legacy filenames tuple must be preserved."""
    keep = tmp_path / "user-data.txt"
    keep.write_bytes(b"important")
    legacy = tmp_path / "msdos-builtin-mbr.bin"
    legacy.write_bytes(b"old")

    removed = cleanup_legacy_cache_files(tmp_path, ("msdos-builtin-mbr.bin",))
    assert removed == [legacy]
    assert keep.exists()
    assert keep.read_bytes() == b"important"


def test_legacy_filename_tuples_contain_no_sha_stamped_names() -> None:
    """Safety: every legacy filename must be a non-stamped name, so the
    exact-match deletion logic never collides with new SHA-stamped
    files like 'msdos-builtin-mbr-d9ae89cb.bin'."""
    for name in _LEGACY_MOUNT_ROOT_CACHE_FILES + _LEGACY_CACHE_ROOT_CACHE_FILES:
        # Pattern '<base>-<8 hex chars>.bin' has at least 13 chars between
        # the last '-' and the '.bin' suffix.  Reject anything that looks
        # like our versioned-cache output.
        assert name.endswith(".bin"), f"legacy name should end in .bin: {name}"
        stem = name[:-len(".bin")]
        if "-" in stem:
            tail = stem.rsplit("-", 1)[1]
            assert not (
                len(tail) == 8
                and all(c in "0123456789abcdef" for c in tail.lower())
            ), (
                f"Legacy filename {name!r} looks like a versioned-cache "
                "output (base-<sha8>.bin) -- that would risk deleting "
                "live caches."
            )


def test_legacy_filenames_do_not_collide_with_live_freedos_cache() -> None:
    """The FreeDOS native-boot-records cache (still active code path) uses
    the un-stamped filenames ``fat16-native-bootsect.bin`` and
    ``fat16-native-mbr.bin``.  Adding either of those to the legacy
    cleanup list would silently delete live reference data the next
    time a user starts dosforge.  Lock that in."""
    live_freedos_names = {"fat16-native-bootsect.bin", "fat16-native-mbr.bin"}
    legacy_names = set(_LEGACY_MOUNT_ROOT_CACHE_FILES + _LEGACY_CACHE_ROOT_CACHE_FILES)
    overlap = live_freedos_names & legacy_names
    assert not overlap, (
        f"Legacy-cleanup list overlaps live FreeDOS cache filenames: "
        f"{sorted(overlap)}.  Adding those to the cleanup list would "
        f"delete live cache data on every BootAssetResolver init."
    )


def test_boot_installer_cleans_up_on_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BootInstaller.__init__ should remove legacy mount-root cache files."""
    from dosforge.boot import BootInstaller
    from dosforge.commands import CommandRunner

    legacy = tmp_path / "msdos-builtin-mbr.bin"
    legacy.write_bytes(b"old-mbr")
    versioned = tmp_path / "msdos-builtin-mbr-d9ae89cb.bin"
    versioned.write_bytes(b"new-mbr")

    BootInstaller(runner=CommandRunner(), mount_root=tmp_path)

    assert not legacy.exists()
    assert versioned.exists()


def test_boot_asset_resolver_cleans_up_on_init(tmp_path: Path) -> None:
    """BootAssetResolver.__init__ should remove legacy cache-root files."""
    from dosforge.boot import BootAssetResolver
    from dosforge.commands import CommandRunner

    legacy = tmp_path / "freedos-fat12-bootsect.bin"
    legacy.write_bytes(b"old-vbr")
    versioned = tmp_path / "freedos-fat12-bootsect-aa11bb22.bin"
    versioned.write_bytes(b"new-vbr")

    BootAssetResolver(runner=CommandRunner(), cache_root=tmp_path)

    assert not legacy.exists()
    assert versioned.exists()
