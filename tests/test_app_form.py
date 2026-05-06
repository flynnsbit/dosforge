from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Button, Checkbox, DirectoryTree, Input, Select

from vhdmaker.app import VhdMakerApp
from vhdmaker.models import BootMode, DiskFormat, FloppyType, FreeDOSSource, IBMDOSVersion, MSDOSInstallProfile, MediaType


def test_app_has_q_quit_binding() -> None:
    assert any(binding[0] == "q" and binding[1] == "quit" for binding in VhdMakerApp.BINDINGS)


def test_create_defaults_to_choose_and_hides_boot_specific_fields() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            assert app.query_one("#media-type", Select).value == MediaType.VHD.value
            assert app.query_one("#boot-mode", Select).value == BootMode.NONE.value
            assert app.query_one("#freedos-source", Select).value == FreeDOSSource.AUTO.value
            assert app.query_one("#dos-profile", Select).value == (
                f"{BootMode.MSDOS71.value}:{MSDOSInstallProfile.MINIMAL.value}"
            )
            assert app.query_one("#create-size", Input).display is True
            assert app.query_one("#create-format", Select).display is True
            assert app.query_one("#floppy-type", Select).display is False
            assert app.query_one("#img-system-format", Checkbox).display is False
            assert app.query_one("#freedos-source", Select).display is False
            assert app.query_one("#dos-profile", Select).display is False
            assert app.query_one("#boot-assets", Input).display is False
            assert app.query_one("#freedos-url", Input).display is False
            assert app.query_one("#fetch-freedos-btn", Button).display is False

    asyncio.run(run())


def test_request_from_form_python314_safe_select_lookup() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/example.vhd"
            app.query_one("#create-size", Input).value = "512M"
            app.query_one("#create-format", Select).value = DiskFormat.FAT32.value
            app.query_one("#boot-mode", Select).value = BootMode.MSDOS71.value
            app.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
            app.query_one("#dos-profile", Select).value = f"{BootMode.MSDOS71.value}:{MSDOSInstallProfile.FULL.value}"

            request = app._request_from_form()
            assert request.path.as_posix() == "/tmp/example.vhd"
            assert request.disk_format is DiskFormat.FAT32
            assert request.boot_mode is BootMode.MSDOS71
            assert request.freedos_source is FreeDOSSource.LOCAL
            assert request.msdos_install_profile is MSDOSInstallProfile.FULL

    asyncio.run(run())


def test_fetch_freedos_button_updates_boot_assets_path(tmp_path) -> None:
    async def run() -> None:
        app = VhdMakerApp()
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
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#boot-mode", Select).value = BootMode.FREEDOS.value
            app._sync_create_form_visibility()
            assert app.query_one("#freedos-source", Select).display is True
            assert app.query_one("#fetch-freedos-btn", Button).display is True
            assert app.query_one("#freedos-url", Input).display is True
            assert app.query_one("#boot-assets", Input).display is False
            assert app.query_one("#dos-profile", Select).display is False

            app.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
            app._sync_create_form_visibility()
            assert app.query_one("#boot-assets", Input).display is True
            assert app.query_one("#freedos-url", Input).display is False

            app.query_one("#boot-mode", Select).value = BootMode.MSDOS71.value
            app._sync_create_form_visibility()
            assert app.query_one("#dos-profile", Select).display is True
            assert app.query_one("#boot-assets", Input).display is True
            assert app.query_one("#freedos-source", Select).display is False
            assert app.query_one("#freedos-url", Input).display is False
            assert app.query_one("#fetch-freedos-btn", Button).display is False
            assert app.query_one("#dos-profile", Select).value == (
                f"{BootMode.MSDOS71.value}:{MSDOSInstallProfile.MINIMAL.value}"
            )

            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            app._sync_create_form_visibility()
            assert app.query_one("#dos-profile", Select).display is True
            assert app.query_one("#boot-assets", Input).display is True
            assert app.query_one("#dos-profile", Select).value == f"{BootMode.IBM8088.value}:{IBMDOSVersion.DOS33.value}"

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
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/ibm.vhd"
            app.query_one("#create-size", Input).value = "32M"
            app.query_one("#create-format", Select).value = DiskFormat.FAT16.value
            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            app._sync_create_form_visibility()
            app.query_one("#dos-profile", Select).value = f"{BootMode.IBM8088.value}:{IBMDOSVersion.DOS50.value}"
            request = app._request_from_form()
            assert request.boot_mode is BootMode.IBM8088
            assert request.ibm_dos_version is IBMDOSVersion.DOS50

    asyncio.run(run())


def test_ibm_boot_mode_sets_default_size_to_32m() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#create-path", Input).value = "/tmp/ibm-default.vhd"
            app.query_one("#create-size", Input).value = "512M"
            app.query_one("#boot-mode", Select).value = BootMode.IBM8088.value
            request = app._request_from_form()
            assert request.size_bytes == 32 * 1024 * 1024

    asyncio.run(run())


def test_request_from_form_img_sets_floppy_size_and_system_mode() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            app.query_one("#media-type", Select).value = MediaType.IMG.value
            app.query_one("#create-path", Input).value = "/tmp/dos.img"
            app.query_one("#floppy-type", Select).value = FloppyType.F720K.value
            app.query_one("#img-system-format", Checkbox).value = True
            app.query_one("#boot-mode", Select).value = BootMode.PCDOS.value

            request = app._request_from_form()
            assert request.media_type is MediaType.IMG
            assert request.floppy_type is FloppyType.F720K
            assert request.size_bytes == FloppyType.F720K.size_bytes
            assert request.img_system_format is True
            assert request.boot_mode is BootMode.PCDOS
            assert request.disk_format is DiskFormat.FAT16

    asyncio.run(run())


def test_request_from_form_img_without_system_mode_forces_non_bootable() -> None:
    async def run() -> None:
        app = VhdMakerApp()
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


def test_selecting_vhd_sets_create_path_and_size(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = VhdMakerApp()
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
        app = VhdMakerApp()
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


def test_browser_starts_in_current_working_directory(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        monkeypatch.chdir(tmp_path)
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            tree = app.query_one("#vhd-tree", DirectoryTree)
            assert Path(str(tree.path)).resolve() == tmp_path.resolve()

    asyncio.run(run())


def test_create_controls_share_horizontal_alignment() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            create_path = app.query_one("#create-path", Input)
            create_format = app.query_one("#create-format", Select)
            boot_mode = app.query_one("#boot-mode", Select)
            diag_button = app.query_one("#diag-btn", Button)
            create_button = app.query_one("#create-btn", Button)

            assert create_format.region.x == create_path.region.x
            assert create_format.region.width == create_path.region.width
            assert boot_mode.region.x == create_path.region.x
            assert boot_mode.region.width == create_path.region.width
            assert diag_button.content_region.x == create_path.content_region.x
            assert diag_button.content_region.width == create_path.content_region.width
            assert create_button.content_region.x == create_path.content_region.x
            assert create_button.content_region.width == create_path.content_region.width

    asyncio.run(run())


def test_create_refreshes_browser_tree(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        def fake_create(request) -> None:
            request.path.parent.mkdir(parents=True, exist_ok=True)
            request.path.write_bytes(b"")

        refresh_calls = {"count": 0}

        def fake_refresh_browser_tree() -> None:
            refresh_calls["count"] += 1

        app.manager.create_and_prepare = fake_create  # type: ignore[assignment]
        monkeypatch.setattr(app, "_refresh_browser_tree", fake_refresh_browser_tree)

        async with app.run_test():
            app.query_one("#create-path", Input).value = str(tmp_path / "newdisk.vhd")
            app.query_one("#create-size", Input).value = "512M"
            app._handle_create()
            assert refresh_calls["count"] == 1

    asyncio.run(run())
