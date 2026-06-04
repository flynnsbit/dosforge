"""Tests for :mod:`dosforge.capabilities` — platform/backend UI gating."""

from __future__ import annotations

from dataclasses import dataclass

from dosforge.capabilities import ui_capabilities


@dataclass
class _FakeBackend:
    supports_kernel_mount: bool
    requires_sudo_for_disk_ops: bool


@dataclass
class _FakeManager:
    backend: _FakeBackend


def _linux_manager() -> _FakeManager:
    return _FakeManager(_FakeBackend(supports_kernel_mount=True, requires_sudo_for_disk_ops=True))


def _windows_manager() -> _FakeManager:
    return _FakeManager(_FakeBackend(supports_kernel_mount=False, requires_sudo_for_disk_ops=False))


def test_windows_caps():
    caps = ui_capabilities(_windows_manager(), platform="win32")
    assert caps.supports_mount is True  # Mount-DiskImage
    assert caps.supports_mtools_image_tools is True
    assert caps.supports_privilege_diagnostics is False
    assert caps.mount_requires_admin_hint is True


def test_linux_caps():
    caps = ui_capabilities(_linux_manager(), platform="linux")
    assert caps.supports_mount is True  # kernel mount
    assert caps.supports_mtools_image_tools is False
    assert caps.supports_privilege_diagnostics is True
    assert caps.mount_requires_admin_hint is False


def test_linux_without_kernel_mount_hides_mount():
    mgr = _FakeManager(_FakeBackend(supports_kernel_mount=False, requires_sudo_for_disk_ops=True))
    caps = ui_capabilities(mgr, platform="linux")
    assert caps.supports_mount is False
