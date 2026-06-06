"""Tests for dosforge.pcdos71_fetch — the IBM SGTK fetch library.

All network I/O is stubbed (no live downloads in CI). 7-Zip is
faked with a Python implementation that copies a fixture tree into
the destination so we can exercise the staging + verification path
without needing 7z.exe installed on the test host.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from dosforge import pcdos71_fetch
from dosforge.errors import DependencyError, ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_fake_sgtk_extract(root: Path) -> dict[str, bytes]:
    """Create a fake extracted-SGTK tree under ``root``.

    Mirrors the relevant layout: ``<root>/sgdeploy/sgtk/DOS/<file>``
    for each entry in ``EXPECTED_SHA256``, plus a bootable VFD at
    ``<root>/sgdeploy/sgtk/tk_raid.vfd``. Returns a mapping of
    {filename -> bytes} so tests can assert the verification hashes
    match the bytes that landed on disk.
    """
    dos_dir = root / "sgdeploy" / "sgtk" / "DOS"
    dos_dir.mkdir(parents=True)
    contents: dict[str, bytes] = {}
    for name in pcdos71_fetch.EXPECTED_SHA256:
        # Make deterministic bytes whose SHA-256 is what we're going
        # to monkey-patch into EXPECTED_SHA256 for the test run.
        payload = f"fake-{name}-payload".encode("ascii")
        (dos_dir / name).write_bytes(payload)
        contents[name] = payload

    vfd = root / "sgdeploy" / "sgtk" / "tk_raid.vfd"
    vfd.write_bytes(b"VFD-stub" * 32)
    return contents


def _override_expected_hashes(
    monkeypatch: pytest.MonkeyPatch, contents: dict[str, bytes]
) -> None:
    """Swap EXPECTED_SHA256 to match whatever the fake extract wrote."""
    fake = {
        name: hashlib.sha256(data).hexdigest() for name, data in contents.items()
    }
    monkeypatch.setattr(pcdos71_fetch, "EXPECTED_SHA256", fake)


@pytest.fixture
def fake_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, bytes]]:
    """Stand up cache + target dirs, a fake 7-Zip, and a fake SGTK extract.

    Returns ``(target_dir, cache_dir, file_contents)``. The 7-Zip
    invocation is patched out: instead of running 7z.exe, we copy
    a pre-built fake-extract tree to where 7-Zip would have written
    it. The download step is also patched to drop a stub archive
    (whose SHA-1 we re-pin via _download monkeypatch).
    """
    target_dir = tmp_path / "target"
    cache_dir = tmp_path / "cache"

    # Fake the SGTK archive itself so the SHA-1 check passes.
    stub_archive_bytes = b"FAKE-SGTK-SELF-EXTRACTOR" * 100
    monkeypatch.setattr(
        pcdos71_fetch, "SGTK_SIZE", len(stub_archive_bytes)
    )
    monkeypatch.setattr(
        pcdos71_fetch,
        "SGTK_SHA1",
        hashlib.sha1(stub_archive_bytes).hexdigest(),
    )

    # Pre-build the SGTK extract under a side dir so the patched
    # _extract can copy it into place when invoked.
    extract_source = tmp_path / "_seed_extract"
    extract_source.mkdir()
    file_contents = _build_fake_sgtk_extract(extract_source)
    _override_expected_hashes(monkeypatch, file_contents)

    # Patch download to just write the stub archive bytes.
    def fake_download(url, dest, *, expected_size, expected_sha1, progress):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(stub_archive_bytes)
        if progress:
            progress(f"  saved: {dest} ({expected_size:,} bytes, SHA-1 verified)")

    monkeypatch.setattr(pcdos71_fetch, "_download", fake_download)

    # Patch _extract to copy our pre-built tree into the dest.
    def fake_extract(seven_zip, archive, dest, *, progress):
        dest.mkdir(parents=True, exist_ok=True)
        for entry in extract_source.iterdir():
            target = dest / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target)
            else:
                shutil.copy2(entry, target)
        if progress:
            progress(f"  extracted to {dest}")

    monkeypatch.setattr(pcdos71_fetch, "_extract", fake_extract)

    # Patch find_sevenzip to return a placeholder path (we don't run it).
    fake_7z = tmp_path / "fake-7z.exe"
    fake_7z.write_bytes(b"")
    monkeypatch.setattr(pcdos71_fetch, "find_sevenzip", lambda: fake_7z)

    return target_dir, cache_dir, file_contents


# ---------------------------------------------------------------------------
# Happy-path + observability
# ---------------------------------------------------------------------------


def test_progress_callback_receives_all_documented_stages(
    fake_environment: tuple[Path, Path, dict[str, bytes]]
) -> None:
    target_dir, cache_dir, _ = fake_environment
    stages: list[str] = []
    result = pcdos71_fetch.fetch_pcdos71_assets(
        target_dir=target_dir,
        cache_dir=cache_dir,
        progress=stages.append,
    )
    assert result.staged_count == result.total_count
    assert result.vfd_filename == "tk_raid.vfd"
    # Every documented stage label must show up at least once.
    for stage in pcdos71_fetch.PROGRESS_STAGES:
        assert stage in stages, f"progress missed stage {stage!r}"


def test_staging_writes_all_dos_files_and_install_floppy(
    fake_environment: tuple[Path, Path, dict[str, bytes]]
) -> None:
    target_dir, cache_dir, contents = fake_environment
    result = pcdos71_fetch.fetch_pcdos71_assets(
        target_dir=target_dir,
        cache_dir=cache_dir,
    )
    assert result.target_dir == target_dir
    assert result.staged_count == len(contents)
    assert result.missing == ()
    assert result.vfd_filename == "tk_raid.vfd"
    for name, expected_bytes in contents.items():
        staged = target_dir / "DOS" / name
        assert staged.is_file(), f"{name} missing from staged DOS dir"
        assert staged.read_bytes() == expected_bytes


# ---------------------------------------------------------------------------
# Cache short-circuit
# ---------------------------------------------------------------------------


def test_cache_hit_reuses_existing_extract(
    fake_environment: tuple[Path, Path, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_dir, cache_dir, _ = fake_environment
    # First run primes the cache (and the extract gets cleaned by default).
    pcdos71_fetch.fetch_pcdos71_assets(
        target_dir=target_dir,
        cache_dir=cache_dir,
        keep_extract=True,
    )

    # Second run: replace _extract with a tripwire that fails the test
    # if invoked. The cache-hit logic should keep us out of it.
    def tripwire(*args, **kwargs):
        raise AssertionError("_extract should not be called on cache hit")

    monkeypatch.setattr(pcdos71_fetch, "_extract", tripwire)

    second_target = target_dir.parent / "second"
    result = pcdos71_fetch.fetch_pcdos71_assets(
        target_dir=second_target,
        cache_dir=cache_dir,
    )
    assert result.staged_count == result.total_count


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_sevenzip_raises_clean_dependency_error(
    fake_environment: tuple[Path, Path, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_dir, cache_dir, _ = fake_environment

    def boom():
        raise DependencyError(
            "7-Zip (7z.exe) not found. Install from https://www.7-zip.org/ "
            "or set DOSFORGE_SEVENZIP_EXE to the path."
        )

    monkeypatch.setattr(pcdos71_fetch, "find_sevenzip", boom)

    with pytest.raises(DependencyError, match="7-Zip"):
        pcdos71_fetch.fetch_pcdos71_assets(
            target_dir=target_dir, cache_dir=cache_dir
        )


def test_sha256_mismatch_on_staging_raises_validation_error(
    fake_environment: tuple[Path, Path, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_dir, cache_dir, _ = fake_environment
    # Replace one expected hash with a deliberately wrong value so
    # _copy_with_verification rejects that file.
    bad = dict(pcdos71_fetch.EXPECTED_SHA256)
    bad["IBMBIO.COM"] = "0" * 64
    monkeypatch.setattr(pcdos71_fetch, "EXPECTED_SHA256", bad)

    with pytest.raises(ValidationError) as excinfo:
        pcdos71_fetch.fetch_pcdos71_assets(
            target_dir=target_dir, cache_dir=cache_dir
        )
    assert "IBMBIO.COM" in str(excinfo.value)
    assert "SHA-256 mismatch" in str(excinfo.value)


def test_missing_dos_dir_raises_validation_error(
    fake_environment: tuple[Path, Path, dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_dir, cache_dir, _ = fake_environment

    # Patch _extract to write a tree with no DOS dir at all.
    def empty_extract(seven_zip, archive, dest, *, progress):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "JUNK.TXT").write_text("no DOS files here")

    monkeypatch.setattr(pcdos71_fetch, "_extract", empty_extract)

    with pytest.raises(ValidationError, match="DOS"):
        pcdos71_fetch.fetch_pcdos71_assets(
            target_dir=target_dir, cache_dir=cache_dir, force=True
        )


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------


def test_default_target_dir_is_under_dos_assets_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """default_target_dir must follow dos_assets_root() resolution."""
    monkeypatch.setenv("DOSFORGE_DOSASSETS_DIR", str(tmp_path))
    target = pcdos71_fetch.default_target_dir()
    assert target == tmp_path / "pcdos71"


def test_default_cache_dir_is_under_app_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dosforge import paths as paths_module

    monkeypatch.setattr(paths_module, "app_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pcdos71_fetch, "app_cache_dir", lambda: tmp_path)
    assert pcdos71_fetch.default_cache_dir() == tmp_path / "pcdos71-fetch"
