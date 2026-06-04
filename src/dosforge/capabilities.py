"""UI-agnostic capability gating shared by the GUI (and re-usable by the TUI).

The Textual app decides which mount / image-tool / diagnostics controls to
show in ``on_mount`` based on the platform backend. This module centralizes
those rules so the GUI and TUI can't drift.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UICapabilities:
    """Which optional UI affordances should be exposed for a backend/platform."""

    supports_mount: bool
    supports_mtools_image_tools: bool
    supports_privilege_diagnostics: bool
    mount_requires_admin_hint: bool


def ui_capabilities(manager, platform: str | None = None) -> UICapabilities:
    """Derive UI capabilities from a :class:`DiskManager` and platform string.

    Mirrors ``app.py:on_mount`` gating:

    * Mount/unmount UI shows on Linux (kernel mount) and on Windows
      (``Mount-DiskImage``, admin required at runtime).
    * mtools ls/extract image tools show on Windows always (the no-admin
      alternative; also the only way to read IMG floppies).
    * Privilege diagnostics only make sense on sudo-backed backends.
    * On Windows, mounting needs Administrator — surfaced as a hint.
    """
    plat = platform if platform is not None else sys.platform
    is_windows = plat == "win32"
    backend = manager.backend

    supports_mount = bool(backend.supports_kernel_mount) or is_windows
    supports_mtools = is_windows
    supports_diag = bool(backend.requires_sudo_for_disk_ops)
    mount_admin_hint = is_windows

    return UICapabilities(
        supports_mount=supports_mount,
        supports_mtools_image_tools=supports_mtools,
        supports_privilege_diagnostics=supports_diag,
        mount_requires_admin_hint=mount_admin_hint,
    )
