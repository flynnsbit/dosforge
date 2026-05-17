"""Platform abstraction layer for dosforge.

Selects the appropriate :class:`PlatformBackend` for the host
operating system. The backend encapsulates everything that differs
between Linux and Windows:

- where state, cache, and mount-prep directories live;
- whether the disk pipeline can rely on kernel mounts / NBD / sudo;
- how external binaries are resolved (system ``PATH`` on Linux,
  bundled ``vendor/windows/bin/*.exe`` on Windows);
- which external commands are required for a given media + boot
  combination.

The default behavior of every backend method is "Linux semantics" so
that the Windows backend only has to override what genuinely differs.
"""

from __future__ import annotations

import sys

from .base import PlatformBackend
from .linux import LinuxBackend
from .windows import WindowsBackend

__all__ = ["PlatformBackend", "LinuxBackend", "WindowsBackend", "get_backend"]


_backend: PlatformBackend | None = None


def get_backend() -> PlatformBackend:
    """Return the singleton backend appropriate for the current host."""

    global _backend
    if _backend is None:
        if sys.platform == "win32":
            _backend = WindowsBackend()
        else:
            _backend = LinuxBackend()
    return _backend


def _reset_backend_for_tests() -> None:
    """Reset the cached backend (test-only)."""

    global _backend
    _backend = None
