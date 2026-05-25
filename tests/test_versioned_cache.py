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
