"""Pytest configuration for the dosforge test suite.

On Windows we run the Windows CLI matrix test + every platform-neutral
unit test (test files that don't reach for ``os.getuid()`` / ``/dev/`` /
``qemu-nbd`` / sudo / etc). The Linux-only files are still skipped to
keep the Windows feedback loop fast and the matrix output readable.

Linux behavior is unchanged: every test runs.
"""

from __future__ import annotations

import sys

import pytest


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
