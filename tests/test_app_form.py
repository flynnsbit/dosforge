from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import DirectoryTree, Input, Select

from vhdmaker.app import VhdMakerApp
from vhdmaker.models import BootMode, DiskFormat, FreeDOSSource, MSDOSInstallProfile


def test_app_has_q_quit_binding() -> None:
    assert any(binding[0] == "q" and binding[1] == "quit" for binding in VhdMakerApp.BINDINGS)


def test_create_defaults_to_freedos_auto() -> None:
    async def run() -> None:
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            assert app.query_one("#boot-mode", Select).value == BootMode.FREEDOS.value
            assert app.query_one("#freedos-source", Select).value == FreeDOSSource.AUTO.value
            assert app.query_one("#msdos-profile", Select).value == MSDOSInstallProfile.MINIMAL.value

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
            app.query_one("#msdos-profile", Select).value = MSDOSInstallProfile.FULL.value

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
            app.query_one("#freedos-source", Select).value = FreeDOSSource.AUTO.value
            app._handle_fetch_freedos()
            assert app.query_one("#boot-assets", Input).value == str(tmp_path / "freedos")
            assert app.query_one("#freedos-source", Select).value == FreeDOSSource.LOCAL.value

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


def test_browser_starts_in_current_working_directory(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        monkeypatch.chdir(tmp_path)
        app = VhdMakerApp()
        app.manager.preflight = lambda request=None: None  # type: ignore[assignment]

        async with app.run_test():
            tree = app.query_one("#vhd-tree", DirectoryTree)
            assert Path(str(tree.path)).resolve() == tmp_path.resolve()

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
