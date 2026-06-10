"""Tests for the ``dosforge grow`` request contract.

Pinned to schema_version 1 of :class:`dosforge.grow.GrowManifest`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dosforge.errors import ValidationError
from dosforge.grow import (
    GROWABLE_BOOT_MODES,
    MANIFEST_SCHEMA_VERSION,
    GrowManifest,
    StagingSource,
    grow_vhd,
    load_manifest_from_dict,
    load_manifest_from_json,
    validate_grow_request,
)
from dosforge.models import BootMode


# 1 KiB of zero data + 8-byte 'conectix' footer magic + 504-byte filler
# = 1536 bytes total; matches the structural shape validate_grow_request
# probes for. Real fixed VHDs are megabytes; only the footer magic and
# size threshold matter for these surface-level tests.
def _write_fake_fixed_vhd(path: Path, *, data_bytes: int = 1024) -> None:
    data = b"\x00" * data_bytes
    footer = b"conectix" + b"\x00" * 504
    path.write_bytes(data + footer)


def _base_manifest(target: Path) -> GrowManifest:
    return GrowManifest(
        target_vhd=target,
        new_size_bytes=4 * 1024 * 1024,
        boot_mode=BootMode.MSDOS622,
    )


class TestGrowableBootModes:
    def test_supported_set_matches_design(self) -> None:
        assert GROWABLE_BOOT_MODES == frozenset({
            BootMode.COMPAQ331,
            BootMode.MSDOS622,
            BootMode.MSDOS71,
            BootMode.FREEDOS,
        })


class TestManifestSerialization:
    def test_round_trip_through_dict(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=2 * 1024 * 1024 * 1024,
            boot_mode=BootMode.MSDOS71,
            staging_sources=(
                StagingSource(src=tmp_path / "games", dest="C:\\GAMES"),
            ),
            boot_probe=False,
            keep_backup=False,
        )
        payload = manifest.to_dict()
        assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION
        round_tripped = load_manifest_from_dict(payload)
        assert round_tripped == manifest

    def test_round_trip_through_json_file(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        manifest = _base_manifest(target)
        manifest_path = tmp_path / "plan.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
        loaded = load_manifest_from_json(manifest_path)
        assert loaded == manifest

    def test_human_size_string_is_parsed(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "target_vhd": str(target),
            "new_size_bytes": "2G",
            "boot_mode": "msdos71",
        }
        loaded = load_manifest_from_dict(payload)
        assert loaded.new_size_bytes == 2 * 1024 * 1024 * 1024

    def test_unsupported_schema_version_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION + 1,
            "target_vhd": str(target),
            "new_size_bytes": 1024 * 1024,
            "boot_mode": "msdos622",
        }
        with pytest.raises(ValidationError, match="schema_version"):
            load_manifest_from_dict(payload)

    def test_missing_required_field_rejected(self, tmp_path: Path) -> None:
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "target_vhd": str(tmp_path / "exo.vhd"),
            # missing new_size_bytes and boot_mode
        }
        with pytest.raises(ValidationError, match="missing required field"):
            load_manifest_from_dict(payload)

    def test_unknown_boot_mode_rejected(self, tmp_path: Path) -> None:
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "target_vhd": str(tmp_path / "exo.vhd"),
            "new_size_bytes": 1024 * 1024,
            "boot_mode": "not-a-real-os",
        }
        with pytest.raises(ValidationError, match="Unknown boot_mode"):
            load_manifest_from_dict(payload)

    def test_malformed_staging_source_rejected(self, tmp_path: Path) -> None:
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "target_vhd": str(tmp_path / "exo.vhd"),
            "new_size_bytes": 1024 * 1024,
            "boot_mode": "msdos622",
            "staging_sources": [{"src": "/tmp/games"}],  # missing 'dest'
        }
        with pytest.raises(ValidationError, match="staging_sources"):
            load_manifest_from_dict(payload)


class TestValidate:
    def test_supported_mode_with_valid_target_passes(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        validate_grow_request(
            GrowManifest(
                target_vhd=target,
                new_size_bytes=2 * 1024 * 1024,
                boot_mode=BootMode.MSDOS622,
            )
        )  # no raise

    @pytest.mark.parametrize(
        "mode", [BootMode.DRDOS6, BootMode.PCDOS71, BootMode.MSDOS33, BootMode.IBM8088]
    )
    def test_unsupported_boot_mode_rejected(self, tmp_path: Path, mode: BootMode) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=mode,
        )
        with pytest.raises(ValidationError, match="does not support boot mode"):
            validate_grow_request(manifest)

    def test_missing_target_vhd_rejected(self, tmp_path: Path) -> None:
        manifest = _base_manifest(tmp_path / "nope.vhd")
        with pytest.raises(ValidationError, match="does not exist"):
            validate_grow_request(manifest)

    def test_non_vhd_footer_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        target.write_bytes(b"\x00" * 4096)  # zeros, no conectix magic
        manifest = _base_manifest(target)
        with pytest.raises(ValidationError, match="conectix"):
            validate_grow_request(manifest)

    def test_shrink_request_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=8 * 1024 * 1024)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=1024 * 1024,
            boot_mode=BootMode.MSDOS622,
        )
        with pytest.raises(ValidationError, match="strictly larger"):
            validate_grow_request(manifest)

    def test_fat16_cap_enforced(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=3 * 1024 * 1024 * 1024,  # 3 GiB > FAT16 2 GiB cap
            boot_mode=BootMode.MSDOS622,
        )
        with pytest.raises(ValidationError, match="FAT16 hard cap"):
            validate_grow_request(manifest)

    def test_missing_staging_source_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=BootMode.MSDOS622,
            staging_sources=(
                StagingSource(src=tmp_path / "nonexistent", dest="C:\\GAMES"),
            ),
        )
        with pytest.raises(ValidationError, match="Staging source does not exist"):
            validate_grow_request(manifest)

    def test_staging_file_instead_of_dir_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        staging = tmp_path / "regular-file.zip"
        staging.write_bytes(b"not a dir")
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=BootMode.MSDOS622,
            staging_sources=(StagingSource(src=staging, dest="C:\\GAMES"),),
        )
        with pytest.raises(ValidationError, match="must be a directory"):
            validate_grow_request(manifest)

    @pytest.mark.parametrize("bad_dest", ["", "GAMES", "relative\\path"])
    def test_relative_or_unix_dest_rejected(self, tmp_path: Path, bad_dest: str) -> None:
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=BootMode.MSDOS622,
            staging_sources=(StagingSource(src=games_dir, dest=bad_dest),),
        )
        with pytest.raises(ValidationError, match="absolute DOS path"):
            validate_grow_request(manifest)


class TestGrowVhd:
    def test_invalid_manifest_raises_validation_first(self, tmp_path: Path) -> None:
        # Grow stub should validate BEFORE invoking the implementation
        # so downstream callers (exodosconverter) get actionable
        # validation errors instead of mtools/qemu-img failures.
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=BootMode.DRDOS6,
        )
        with pytest.raises(ValidationError, match="does not support boot mode"):
            grow_vhd(manifest)

    def test_unparseable_vhd_raises_validation(self, tmp_path: Path) -> None:
        # _snapshot_vhd should reject a "VHD" with no MBR signature
        # before the grow pipeline starts touching files. The fake
        # VHD in this test file has the conectix footer but no MBR
        # 55 AA signature, so snapshot bails immediately.
        target = tmp_path / "exo.vhd"
        _write_fake_fixed_vhd(target, data_bytes=1024 * 1024)
        manifest = GrowManifest(
            target_vhd=target,
            new_size_bytes=4 * 1024 * 1024,
            boot_mode=BootMode.MSDOS622,
        )
        with pytest.raises(ValidationError, match="no valid MBR signature"):
            grow_vhd(manifest)
