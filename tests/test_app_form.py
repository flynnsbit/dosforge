from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Button, Checkbox, DirectoryTree, Input, Select

from dosforge.app import DosForgeApp
from dosforge.errors import DosForgeError
from dosforge.models import BootMode, DiskFormat, FloppyType, FreeDOSSource, IBMDOSVersion, MSDOSInstallProfile, MediaType


def test_app_has_q_quit_binding() -> None:
    assert any(binding[0] == "q" and binding[1] == "quit" for binding in DosForgeApp.BINDINGS)


def test_create_defaults_to_choose_and_hides_boot_specific_fields() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            assert app.query_one("#media-type", Select).value == MediaType.VHD.value
            assert app.query_one("#boot-mode", Select).value == BootMode.NONE.value
            assert app.query_one("#freedos-source", Select).value == FreeDOSSource.AUTO.value
            assert app.query_one("#dos-profile", Select).value == MSDOSInstallProfile.MINIMAL.value
            assert app.query_one("#create-size", Input).display is True
            assert app.query_one("#create-format", Select).display is True
            assert app.query_one("#floppy-type", Select).display is False
            assert app.query_one("#img-system-format", Checkbox).display is False
            assert app.query_one("#freedos-source", Select).display is False
            assert app.query_one("#dos-profile", Select).display is False
            assert app.query_one("#ibm-dos-version", Select).display is False
            assert app.query_one("#boot-assets-row").display is False
            assert app.query_one("#freedos-url", Input).display is False
            assert app.query_one("#fetch-freedos-btn", Button).display is False

    asyncio.run(run())


def test_request_from_form_python314_safe_select_lookup() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/example.vhd"
            app.query_one("#create-size", Input).value = "512M"
            app.query_one("#create-format", Select).value = DiskFormat.FAT32.value
            app.query_one("#boot-mode", Select).value = BootMode.MSDOS71.value
            app.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
            app.query_one("#dos-profile", Select).value = MSDOSInstallProfile.FULL.value

            request = app._request_from_form()
            assert request.path.as_posix() == "/tmp/example.vhd"
            assert request.disk_format is DiskFormat.FAT32
            assert request.boot_mode is BootMode.MSDOS71
            assert request.freedos_source is FreeDOSSource.LOCAL
            assert request.msdos_install_profile is MSDOSInstallProfile.FULL
            assert app.query_one("#custom-payload", Input).display is True

    asyncio.run(run())


def test_fetch_freedos_button_updates_boot_assets_path(tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        def fake_fetch(destination=None, download_url=None):
            del destination, download_url
            target = tmp_path / "freedos"
            target.mkdir(parents=True, exist_ok=True)
            return target

        app.manager.fetch_freedos_assets = fake_fetch  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#boot-mode", Select).value = BootMode.FREEDOS.value
            app.query_one("#freedos-source", Select).value = FreeDOSSource.AUTO.value
            app._handle_fetch_freedos()
            assert app.query_one("#boot-assets", Input).value == str(tmp_path / "freedos")
            assert app.query_one("#freedos-source", Select).value == FreeDOSSource.LOCAL.value

    asyncio.run(run())


def test_progressive_disclosure_for_boot_modes() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#boot-mode", Select).value = BootMode.FREEDOS.value
            app._sync_create_form_visibility()
            assert app.query_one("#freedos-source", Select).display is True
            assert app.query_one("#fetch-freedos-btn", Button).display is True
            assert app.query_one("#freedos-url", Input).display is True
            assert app.query_one("#boot-assets-row").display is False
            assert app.query_one("#dos-profile", Select).display is False

            app.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
            app._sync_create_form_visibility()
            assert app.query_one("#boot-assets-row").display is True
            assert app.query_one("#freedos-url", Input).display is False

            app.query_one("#boot-mode", Select).value = BootMode.MSDOS71.value
            app._sync_create_form_visibility()
            assert app.query_one("#dos-profile", Select).display is True
            assert app.query_one("#boot-assets-row").display is True
            assert app.query_one("#freedos-source", Select).display is False
            assert app.query_one("#freedos-url", Input).display is False
            assert app.query_one("#fetch-freedos-btn", Button).display is False
            assert app.query_one("#dos-profile", Select).value == MSDOSInstallProfile.MINIMAL.value
            assert app.query_one("#ibm-dos-version", Select).display is False

            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            app._sync_create_form_visibility()
            assert app.query_one("#dos-profile", Select).display is True
            assert app.query_one("#boot-assets-row").display is True
            assert app.query_one("#ibm-dos-version", Select).display is True
            assert app.query_one("#ibm-dos-version", Select).value == IBMDOSVersion.DOS33.value

            app.query_one("#boot-mode", Select).value = BootMode.PCDOS7.value
            app._sync_create_form_visibility()
            assert app.query_one("#dos-profile", Select).display is True
            assert app.query_one("#ibm-dos-version", Select).display is False
            assert app.query_one("#boot-assets-row").display is True

            app.query_one("#media-type", Select).value = MediaType.IMG.value
            app._sync_create_form_visibility()
            assert app.query_one("#create-size", Input).display is False
            assert app.query_one("#create-format", Select).display is False
            assert app.query_one("#floppy-type", Select).display is True
            assert app.query_one("#img-system-format", Checkbox).display is True
            assert app.query_one("#boot-mode", Select).display is False

            app.query_one("#img-system-format", Checkbox).value = True
            app._sync_create_form_visibility()
            assert app.query_one("#boot-mode", Select).display is True

    asyncio.run(run())


def test_request_from_form_reads_ibm_dos_profile() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/ibm.vhd"
            app.query_one("#create-size", Input).value = "32M"
            app.query_one("#create-format", Select).value = DiskFormat.FAT16.value
            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            app._sync_create_form_visibility()
            app.query_one("#ibm-dos-version", Select).value = IBMDOSVersion.DOS50.value
            request = app._request_from_form()
            assert request.boot_mode is BootMode.IBM8088
            assert request.ibm_dos_version is IBMDOSVersion.DOS50

    asyncio.run(run())


def test_ibm_boot_mode_sets_default_size_to_32m() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/ibm-default.vhd"
            app.query_one("#create-size", Input).value = "512M"
            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            request = app._request_from_form()
            assert request.size_bytes == 32 * 1024 * 1024

    asyncio.run(run())


def test_request_from_form_img_without_system_mode_forces_non_bootable() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#media-type", Select).value = MediaType.IMG.value
            app.query_one("#create-path", Input).value = "/tmp/plain.img"
            app.query_one("#floppy-type", Select).value = FloppyType.F360K.value
            app.query_one("#img-system-format", Checkbox).value = False
            app.query_one("#boot-mode", Select).value = BootMode.MSDOS71.value

            request = app._request_from_form()
            assert request.boot_mode is BootMode.NONE
            assert request.img_system_format is False

    asyncio.run(run())


def test_request_from_form_img_supports_2880k_floppy() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#media-type", Select).value = MediaType.IMG.value
            app.query_one("#create-path", Input).value = "/tmp/ed.img"
            app.query_one("#floppy-type", Select).value = FloppyType.F2880K.value
            app.query_one("#img-system-format", Checkbox).value = False

            request = app._request_from_form()
            assert request.floppy_type is FloppyType.F2880K
            assert request.size_bytes == FloppyType.F2880K.size_bytes
            assert request.img_system_format is False

    asyncio.run(run())


def test_request_from_form_img_supports_1840k_pcdos7_floppy() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#media-type", Select).value = MediaType.IMG.value
            app.query_one("#create-path", Input).value = "/tmp/xdf.img"
            app.query_one("#floppy-type", Select).value = FloppyType.F1840K.value
            app.query_one("#img-system-format", Checkbox).value = True
            app.query_one("#boot-mode", Select).value = BootMode.PCDOS7.value

            request = app._request_from_form()
            assert request.floppy_type is FloppyType.F1840K
            assert request.size_bytes == FloppyType.F1840K.size_bytes
            assert request.img_system_format is True
            assert request.boot_mode is BootMode.PCDOS7

    asyncio.run(run())


def test_request_from_form_vhd_supports_full_profile_for_legacy_mode() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/full-legacy.vhd"
            app.query_one("#create-size", Input).value = "128M"
            app.query_one("#create-format", Select).value = DiskFormat.FAT16.value
            app.query_one("#boot-mode", Select).value = BootMode.PCDOS7.value
            app.query_one("#dos-profile", Select).value = MSDOSInstallProfile.FULL.value

            request = app._request_from_form()
            assert request.boot_mode is BootMode.PCDOS7
            assert request.msdos_install_profile is MSDOSInstallProfile.FULL

    asyncio.run(run())


def test_request_from_form_vhd_allows_missing_size_with_custom_payload() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/custom.vhd"
            app.query_one("#create-size", Input).value = ""
            app.query_one("#create-format", Select).value = DiskFormat.FAT16.value
            app.query_one("#custom-payload", Input).value = "/tmp/payload"

            request = app._request_from_form()
            assert request.size_bytes == 1
            assert request.custom_payload_path is not None
            assert request.custom_payload_path.as_posix() == "/tmp/payload"

    asyncio.run(run())


def test_selecting_vhd_sets_create_path_and_size(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        vhd_path = tmp_path / "selected.vhd"
        vhd_path.write_bytes(b"\0" * (256 * 1024**2))
        monkeypatch.chdir(tmp_path)

        async with app.run_test():
            app.on_directory_tree_file_selected(SimpleNamespace(path=str(vhd_path)))
            assert app.query_one("#create-path", Input).value == str(vhd_path.resolve())
            assert app.query_one("#create-size", Input).value == "256M"

    asyncio.run(run())


def test_selecting_img_sets_media_type_and_floppy(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        img_path = tmp_path / "selected.img"
        img_path.write_bytes(b"\0" * FloppyType.F1440K.size_bytes)
        monkeypatch.chdir(tmp_path)

        async with app.run_test():
            app.on_directory_tree_file_selected(SimpleNamespace(path=str(img_path)))
            assert app.query_one("#create-path", Input).value == str(img_path.resolve())
            assert app.query_one("#media-type", Select).value == MediaType.IMG.value
            assert app.query_one("#floppy-type", Select).value == FloppyType.F1440K.value

    asyncio.run(run())


def test_selecting_directory_sets_boot_assets_when_picker_is_visible(tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        assets_dir = tmp_path / "dos33"
        assets_dir.mkdir(parents=True, exist_ok=True)

        async with app.run_test():
            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            app._sync_create_form_visibility()
            # Wizard-redesign: the picker is now explicit. Tapping the
            # browse button next to #boot-assets sets path_picker_target;
            # we simulate that here without invoking the native dialog.
            app._start_path_picker("boot-assets")
            app.on_directory_tree_directory_selected(SimpleNamespace(path=str(assets_dir)))
            assert app.query_one("#boot-assets", Input).value == str(assets_dir.resolve())

    asyncio.run(run())


def test_browser_starts_in_current_working_directory(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        monkeypatch.chdir(tmp_path)
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            tree = app.query_one("#vhd-tree", DirectoryTree)
            assert Path(str(tree.path)).resolve() == tmp_path.resolve()

    asyncio.run(run())


def test_create_controls_share_horizontal_alignment() -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            # Wizard redesign: step-1 controls live in one container and
            # share alignment. Cross-step alignment (e.g. boot-mode is in
            # step-2) is no longer meaningful since steps render
            # sequentially — assert alignment within the visible step.
            create_path_row = app.query_one("#create-path-row")
            create_path_input = app.query_one("#create-path", Input)
            create_format = app.query_one("#create-format", Select)

            assert create_format.region.x == create_path_row.region.x
            assert create_format.region.width == create_path_row.region.width
            assert create_path_input.region.x == create_path_row.region.x

    asyncio.run(run())


def test_browse_buttons_start_path_picker_and_apply_selection(tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        payload_dir = tmp_path / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        boot_img = tmp_path / "boot.img"
        boot_img.write_bytes(b"")

        async with app.run_test():
            app._pick_path_with_dialog = lambda target: None  # type: ignore[assignment]
            app.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="browse-custom-payload-btn")))
            assert app.path_picker_target == "custom-payload"
            app.on_directory_tree_directory_selected(SimpleNamespace(path=str(payload_dir)))
            assert app.query_one("#custom-payload", Input).value == str(payload_dir.resolve())
            assert app.path_picker_target is None

            app.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="browse-boot-assets-btn")))
            assert app.path_picker_target == "boot-assets"
            app.on_directory_tree_file_selected(SimpleNamespace(path=str(boot_img)))
            assert app.query_one("#boot-assets", Input).value == str(boot_img.resolve())
            assert app.path_picker_target is None

    asyncio.run(run())


def test_browse_buttons_apply_dialog_selection_directly(tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        payload_dir = tmp_path / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        output_vhd = tmp_path / "selected.vhd"

        def fake_pick(target: str):
            if target == "custom-payload":
                return payload_dir
            if target == "create-path":
                return output_vhd
            return None

        async with app.run_test():
            app._pick_path_with_dialog = fake_pick  # type: ignore[assignment]
            app.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="browse-custom-payload-btn")))
            assert app.query_one("#custom-payload", Input).value == str(payload_dir.resolve())
            assert app.path_picker_target is None

            app.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="browse-create-path-btn")))
            assert app.query_one("#create-path", Input).value == str(output_vhd.resolve())
            assert app.path_picker_target is None

    asyncio.run(run())


def test_tree_parent_entry_moves_browser_root_up(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        child = tmp_path / "child"
        child.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(child)

        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            tree = app.query_one("#vhd-tree", DirectoryTree)
            await tree.reload()
            assert Path(str(tree.path)).resolve() == child.resolve()
            parent_node = next(node for node in tree.root.children if node.label.plain == "../")
            app.on_directory_tree_directory_selected(SimpleNamespace(path=str(tmp_path), node=parent_node))
            assert Path(str(tree.path)).resolve() == tmp_path.resolve()

    asyncio.run(run())


def test_parent_entry_is_only_added_at_tree_root(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        child = tmp_path / "child"
        child.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(child)

        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            tree = app.query_one("#vhd-tree", DirectoryTree)
            await tree.reload()
            root_parent_nodes = [node for node in tree.root.children if node.label.plain == "../"]
            assert len(root_parent_nodes) == 1
            parent_node = root_parent_nodes[0]
            await tree._load_directory(parent_node).wait()
            await tree._add_to_load_queue(parent_node)
            child_parent_nodes = [node for node in parent_node.children if node.label.plain == "../"]
            assert child_parent_nodes == []

    asyncio.run(run())


def test_create_refreshes_browser_tree(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        def fake_create(request) -> None:
            request.path.parent.mkdir(parents=True, exist_ok=True)
            request.path.write_bytes(b"")

        refresh_calls = {"count": 0}

        def fake_refresh_browser_tree() -> None:
            refresh_calls["count"] += 1

        app.manager.create_and_prepare = fake_create  # type: ignore[assignment]
        monkeypatch.setattr(app, "_refresh_browser_tree", fake_refresh_browser_tree)

        async with app.run_test() as pilot:
            app.query_one("#create-path", Input).value = str(tmp_path / "newdisk.vhd")
            app.query_one("#create-size", Input).value = "512M"
            app._handle_create()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert refresh_calls["count"] == 1

    asyncio.run(run())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Sudo re-auth path is Linux-only. On Windows the WindowsBackend "
        "reports requires_sudo_for_disk_ops=False, so _run_with_sudo_reauth "
        "early-returns without entering the reauth dance — by design."
    ),
)
def test_create_reauthenticates_and_retries_when_sudo_expires(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        attempts = {"count": 0}

        def fake_create(request) -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise DosForgeError(
                    "Sudo authentication is required for disk operations. Details: sudo: a password is required"
                )
            request.path.parent.mkdir(parents=True, exist_ok=True)
            request.path.write_bytes(b"")

        app.manager.create_and_prepare = fake_create  # type: ignore[assignment]
        app._reauthenticate_sudo = lambda: (True, "Sudo credentials refreshed.")  # type: ignore[assignment]
        monkeypatch.setattr(app, "_refresh_browser_tree", lambda: None)
        monkeypatch.setattr(app, "_refresh_mounts", lambda: None)

        async with app.run_test() as pilot:
            app.query_one("#create-path", Input).value = str(tmp_path / "newdisk.vhd")
            app.query_one("#create-size", Input).value = "64M"
            app._handle_create()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert attempts["count"] == 2
            assert "Created and prepared" in str(app.query_one("#status").render())

    asyncio.run(run())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Sudo re-auth path is Linux-only — see "
        "test_create_reauthenticates_and_retries_when_sudo_expires."
    ),
)
def test_create_shows_error_when_sudo_reauth_fails(tmp_path) -> None:
    async def run() -> None:
        app = DosForgeApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]
        attempts = {"count": 0}

        def fake_create(request) -> None:
            del request
            attempts["count"] += 1
            raise DosForgeError(
                "Sudo authentication is required for disk operations. Details: sudo: a password is required"
            )

        app.manager.create_and_prepare = fake_create  # type: ignore[assignment]
        app._reauthenticate_sudo = lambda: (False, "Sudo re-authentication failed.")  # type: ignore[assignment]

        async with app.run_test() as pilot:
            app.query_one("#create-path", Input).value = str(tmp_path / "newdisk.vhd")
            app.query_one("#create-size", Input).value = "64M"
            app._handle_create()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert attempts["count"] == 1
            assert "Sudo re-authentication failed." == str(app.query_one("#status").render()).strip()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Regression tests: every TUI manager call must work on the actual backend.
#
# Why: the existing form tests stub out the underlying manager methods, so
# they verify the TUI's state-machine wiring but not the manager-side
# dependency / capability checks. When fetch_freedos_assets unconditionally
# required mkfs.fat (not in the Windows bundle), the stubbed-out test passed
# while the real-world Windows TUI raised at runtime
# ("Missing required tools for FreeDOS extraction: mkfs.fat").
#
# These tests call the manager methods directly against the real backend
# WITHOUT mocking, except for the genuinely slow / external parts
# (downloading FreeDOS, real-disk QEMU install, etc.) which are stubbed
# at the deepest practical layer so the dependency / capability checks
# above them still run for real.
# ---------------------------------------------------------------------------


def test_preflight_passes_on_active_backend(monkeypatch) -> None:
    """on_mount calls manager.preflight() — must not raise on either backend."""

    from dosforge.disk import DiskManager

    # Stub _ensure_sudo_ready (Linux interactive auth) — assert_dependencies
    # is the part we actually want to exercise for real.
    monkeypatch.setattr(DiskManager, "_ensure_sudo_ready", lambda self: None)
    DiskManager().preflight()


def test_privilege_diagnostics_summary_runs_on_active_backend() -> None:
    """The 'Run privilege diagnostics' button must not crash on either platform."""

    from dosforge.disk import DiskManager

    ok, summary = DiskManager().privilege_diagnostics_summary()
    assert isinstance(ok, bool)
    assert isinstance(summary, str)
    assert summary  # non-empty


def test_list_mounts_runs_on_active_backend() -> None:
    """The TUI's _refresh_mounts() reads from list_mounts() — must work."""

    from dosforge.disk import DiskManager

    # Returns a list of MountRecord; may be empty. Just ensure no exception.
    assert isinstance(DiskManager().list_mounts(), list)


def test_fetch_freedos_assets_passes_dependency_check(monkeypatch, tmp_path) -> None:
    """Regression guard for the mkfs.fat-only-on-Linux bug.

    fetch_freedos_assets's dependency check must succeed on whichever
    backend is active. We stub only the actual download/extract step
    (export_latest_freedos_assets) so the dependency check above it
    still runs against the real find_missing + backend.tool_path.
    """

    from dosforge.disk import DiskManager

    manager = DiskManager()
    captured: dict[str, Path] = {}

    def fake_export(destination, image_url=None, *, include_full_fdos=False):
        del image_url, include_full_fdos
        captured["destination"] = destination
        destination.mkdir(parents=True, exist_ok=True)
        return destination.resolve()

    monkeypatch.setattr(manager.boot_resolver, "export_latest_freedos_assets", fake_export)
    target = manager.fetch_freedos_assets(destination=tmp_path / "freedos")
    assert target == (tmp_path / "freedos").resolve()
    assert captured["destination"] == (tmp_path / "freedos")
