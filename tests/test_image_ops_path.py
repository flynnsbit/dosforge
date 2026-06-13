"""Regression tests for dosforge.image_ops._normalize_dos_path.

The function converts user-supplied DOS paths into the ``::path`` form
expected by mtools (which configures the drive via ``-i <image>``).
A leading drive letter like ``C:\\`` is meaningless to mtools and must
be stripped — otherwise mcopy reports ``File "::/C:/..." not found``
(reported by a Windows GUI user against v0.9.42 on the Image Tools tab).
"""

from __future__ import annotations

import pytest

from dosforge.image_ops import _normalize_dos_path as n


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Drive-letter prefixes (the regression).
        ("C:\\CONFIG.SYS", "::/CONFIG.SYS"),
        ("c:CONFIG.SYS", "::/CONFIG.SYS"),
        ("C:\\DOS\\HIMEM.SYS", "::/DOS/HIMEM.SYS"),
        ("C:", "::/"),
        ("C:\\", "::/"),
        # Plain DOS paths (forward + backslash).
        ("/CONFIG.SYS", "::/CONFIG.SYS"),
        ("CONFIG.SYS", "::/CONFIG.SYS"),
        ("\\CONFIG.SYS", "::/CONFIG.SYS"),
        # Root and empties.
        ("/", "::/"),
        ("", "::/"),
        # Stray leading colons (already handled before this regression).
        (":CONFIG.SYS", "::/CONFIG.SYS"),
        # Nested directory survives drive strip.
        ("D:\\GAMES\\DOOM\\DOOM.EXE", "::/GAMES/DOOM/DOOM.EXE"),
    ],
)
def test_normalize_dos_path(raw: str, expected: str) -> None:
    assert n(raw) == expected
