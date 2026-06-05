"""Pytest configuration for the dosforge test suite.

On Windows we run the Windows CLI matrix test + every platform-neutral
unit test (test files that don't reach for ``os.getuid()`` / ``/dev/`` /
``qemu-nbd`` / sudo / etc). The Linux-only files are still skipped to
keep the Windows feedback loop fast and the matrix output readable.

Linux behavior is unchanged: every test runs.

In addition, the ``_isolate_asset_resolution`` autouse fixture below
ensures every test runs against an empty set of well-known dosassets
roots so that whatever the developer has under ``~/.local/share/dosforge``
/ ``~/.dosforge`` / ``/usr/share/dosforge`` (e.g. from a prior
``dosforge init-assets`` run) cannot shadow tests that monkeypatch
``Path.cwd()`` into a tmp_path. Without this fixture, tests that
assert "no dosassets found" pass in CI but fail on developer
machines that have hydrated assets.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_asset_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Isolate dosassets resolution from the developer's host state.

    1. Clear ``DOSFORGE_DOSASSETS_DIR`` so a stray env var (from a
       prior frozen-bundle run or shell export) doesn't smuggle real
       install media into otherwise-isolated tests.
    2. Pin ``HOME`` / ``USERPROFILE`` / ``XDG_DATA_HOME`` to an empty
       directory so the XDG / ``~/.dosforge`` well-known roots in
       ``dosforge.paths._wellknown_asset_roots`` resolve to fresh
       directories with no real install media on them.  This matches
       the pinning pattern already used in test_disk_validation.py
       (e.g. tests around resolve_dos_asset_dir XDG fallback) and
       keeps tests deterministic regardless of whether the developer
       has previously run ``dosforge init-assets``.

    Tests that *want* to exercise the XDG-aware resolver can re-pin
    HOME / XDG_DATA_HOME themselves; their ``monkeypatch.setenv``
    calls run after this fixture and take precedence.
    """
    monkeypatch.delenv("DOSFORGE_DOSASSETS_DIR", raising=False)
    isolated_home = tmp_path_factory.mktemp("isolated-home")
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("USERPROFILE", str(isolated_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_home / "xdg"))


# Tests known to run on Windows. Everything else is skipped by
# ``pytest_collection_modifyitems`` below. Verified via per-file audit
# for Linux-only assumptions (os.getuid, /dev/, qemu-nbd, sudo, mount).
_WINDOWS_ALLOWED_TEST_FILES = frozenset(
    {
        "test_windows_cli_matrix.py",
        # Platform-neutral unit tests (no Linux-only syscall/path
        # assumptions in their bodies):
        "test_app_form.py",
        "test_asset_skeleton.py",
        "test_boot_assets.py",
        "test_capabilities.py",
        "test_cli.py",
        "test_core_modules.py",
        "test_authenticity_golden.py",
        "test_boot_probe.py",
        "test_disk_validation.py",
        "test_disk_windows_vhd.py",
        "test_dos_boot_smoke.py",
        "test_dos_profiles.py",
        "test_dosbox_x_install.py",
        "test_e2e_emulator.py",
        "test_e2e_matrix.py",
        "test_fat12_boot_template.py",
        "test_formlogic.py",
        "test_fourdos_overlay.py",
        "test_mscompress.py",
        "test_platform_windows.py",
        "test_size.py",
        "test_strict_authenticity.py",
        "test_versioned_cache.py",
    }
)


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "Linux-only test (sudo, /dev/, os.getuid, qemu-nbd, native "
            "boot marker). Re-enable per-file once the broader Windows "
            "refactor lands."
        )
    )
    for item in items:
        filename = item.path.name if hasattr(item, "path") else item.fspath.basename
        if filename not in _WINDOWS_ALLOWED_TEST_FILES:
            item.add_marker(skip_marker)
