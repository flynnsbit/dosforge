"""Pytest configuration for the dosforge test suite.

On Windows we focus exclusively on the CLI matrix test
(``test_windows_cli_matrix.py``) while iterating on the Windows port.
All other tests carry Linux-only assumptions (``os.getuid()``,
``/dev/`` paths, etc.) and skipping them at collection time keeps the
Windows feedback loop fast and the matrix output readable.

Linux behavior is unchanged.
"""

from __future__ import annotations

import sys

import pytest


# Files that are allowed to run on Windows. Everything else is skipped
# by ``pytest_collection_modifyitems`` below.
_WINDOWS_ALLOWED_TEST_FILES = frozenset(
    {
        "test_windows_cli_matrix.py",
    }
)


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "Disabled on Windows during the CLI matrix iteration. "
            "Linux-only assumptions (sudo, /dev/, os.getuid) make these "
            "tests unsafe to run here. Re-enable per-file once the "
            "broader Windows refactor is complete."
        )
    )
    for item in items:
        filename = item.path.name if hasattr(item, "path") else item.fspath.basename
        if filename not in _WINDOWS_ALLOWED_TEST_FILES:
            item.add_marker(skip_marker)
