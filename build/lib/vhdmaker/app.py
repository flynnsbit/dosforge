"""Textual UI for VHD creation and mount workflows."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DirectoryTree, Footer, Header, Input, Label, Select, Static

from .disk import DiskManager
from .errors import VhdMakerError
from .models import BootMode, CreateRequest, DiskFormat, FreeDOSSource
from .size import parse_size


class VhdMakerApp(App[None]):
    TITLE = "VHD Maker"
    SUB_TITLE = "Create, mount, browse, and unmount DOS-friendly VHD files"

    CSS = """
    Screen {
      layout: vertical;
    }
    #layout {
      layout: horizontal;
      height: 1fr;
    }
    #left-pane, #right-pane {
      width: 1fr;
      padding: 0 1;
    }
    #vhd-tree {
      height: 1fr;
      border: round $panel;
    }
    #mounts, #status {
      border: round $panel;
      padding: 1;
      min-height: 5;
    }
    Input, Select, Checkbox, Button, Label {
      margin: 0 0 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.manager = DiskManager()
        self.selected_vhd: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="left-pane"):
                yield Label("Browse .vhd files")
                yield DirectoryTree(str(Path.cwd()), id="vhd-tree")
                yield Static("Selected VHD: (none)", id="selected-vhd")
                yield Button("Mount selected VHD", id="mount-btn", variant="primary")
                yield Input(placeholder="Mounted path to unmount", id="unmount-input")
                yield Button("Unmount mount path", id="unmount-btn", variant="warning")
                yield Input(placeholder="Path to open in Omarchy Files", id="open-input")
                yield Button("Open path in Files", id="open-btn")
                yield Static("No active mounts tracked.", id="mounts")
            with Vertical(id="right-pane"):
                yield Label("Create fixed-size VHD")
                yield Input(placeholder="Path (for example: ~/vhd/disk.vhd)", id="create-path")
                yield Input(value="512M", placeholder="Static size (for example: 512M)", id="create-size")
                yield Select(
                    options=[("FAT16", DiskFormat.FAT16.value), ("FAT32", DiskFormat.FAT32.value)],
                    value=DiskFormat.FAT16.value,
                    id="create-format",
                )
                yield Select(
                    options=[
                        ("No boot setup", BootMode.NONE.value),
                        ("FreeDOS bootable", BootMode.FREEDOS.value),
                        ("MS-DOS 7.1 bootable", BootMode.MSDOS71.value),
                    ],
                    value=BootMode.NONE.value,
                    id="boot-mode",
                )
                yield Select(
                    options=[
                        ("Local FreeDOS assets", FreeDOSSource.LOCAL.value),
                        ("Auto-download FreeDOS image", FreeDOSSource.AUTO.value),
                    ],
                    value=FreeDOSSource.LOCAL.value,
                    id="freedos-source",
                )
                yield Input(placeholder="Boot assets path (dir or .img)", id="boot-assets")
                yield Input(placeholder="FreeDOS download URL (optional)", id="freedos-url")
                yield Button("Fetch latest FreeDOS into ./freedos", id="fetch-freedos-btn")
                yield Input(placeholder="Volume label (optional)", id="volume-label")
                yield Checkbox("Overwrite existing .vhd", id="overwrite")
                yield Button("Create + format VHD", id="create-btn", variant="success")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.manager.preflight()
            self._set_status("Preflight check passed. Select or create a VHD to begin.")
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
        self._refresh_mounts()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        selected = Path(event.path).expanduser().resolve()
        if selected.suffix.lower() != ".vhd":
            self._set_status("Selected file is not a .vhd file.", error=True)
            return
        self.selected_vhd = selected
        self.query_one("#selected-vhd", Static).update(f"Selected VHD: {selected}")
        self.query_one("#create-path", Input).value = str(selected)
        self._set_status(f"Selected {selected}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "create-btn":
            self._handle_create()
        elif button_id == "mount-btn":
            self._handle_mount_selected()
        elif button_id == "unmount-btn":
            self._handle_unmount()
        elif button_id == "open-btn":
            self._handle_open()
        elif button_id == "fetch-freedos-btn":
            self._handle_fetch_freedos()

    def _handle_create(self) -> None:
        try:
            request = self._request_from_form()
            self.manager.create_and_prepare(request)
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        self._set_status(f"Created and prepared: {request.path}")
        self.selected_vhd = request.path.expanduser().resolve()
        self.query_one("#selected-vhd", Static).update(f"Selected VHD: {self.selected_vhd}")
        self._refresh_mounts()

    def _handle_mount_selected(self) -> None:
        if self.selected_vhd is None:
            path_text = self.query_one("#create-path", Input).value.strip()
            if path_text:
                self.selected_vhd = Path(path_text).expanduser().resolve()
        if self.selected_vhd is None:
            self._set_status("Select a .vhd file first.", error=True)
            return

        try:
            record = self.manager.mount_vhd(self.selected_vhd)
            self.manager.open_in_files(record.mount_point)
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        mountpoint_text = str(record.mount_point)
        self.query_one("#unmount-input", Input).value = mountpoint_text
        self.query_one("#open-input", Input).value = mountpoint_text
        self._refresh_mounts()
        self._set_status(f"Mounted {record.vhd_path} to {record.mount_point} and opened in Files.")

    def _handle_unmount(self) -> None:
        mountpoint_text = self.query_one("#unmount-input", Input).value.strip()
        if not mountpoint_text:
            self._set_status("Enter a mounted path to unmount.", error=True)
            return

        try:
            record = self.manager.unmount(Path(mountpoint_text))
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        self._refresh_mounts()
        self._set_status(f"Unmounted {record.mount_point} and disconnected {record.nbd_device}.")

    def _handle_open(self) -> None:
        path_text = self.query_one("#open-input", Input).value.strip()
        if not path_text:
            self._set_status("Enter a path to open in Omarchy Files.", error=True)
            return
        try:
            self.manager.open_in_files(Path(path_text))
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f"Opened in Files: {path_text}")

    def _handle_fetch_freedos(self) -> None:
        url_text = self.query_one("#freedos-url", Input).value.strip()
        try:
            target = self.manager.fetch_freedos_assets(download_url=(url_text or None))
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        self.query_one("#boot-assets", Input).value = str(target)
        self.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
        self._set_status(f"Downloaded and extracted FreeDOS assets to {target}")

    def _request_from_form(self) -> CreateRequest:
        path_text = self.query_one("#create-path", Input).value.strip()
        if not path_text:
            raise VhdMakerError("Create path is required.")
        size_text = self.query_one("#create-size", Input).value.strip()
        if not size_text:
            raise VhdMakerError("Create size is required.")

        format_select = self.query_one("#create-format", Select)
        boot_select = self.query_one("#boot-mode", Select)
        source_select = self.query_one("#freedos-source", Select)

        format_value = cast(str, format_select.value)
        boot_value = cast(str, boot_select.value)
        source_value = cast(str, source_select.value)

        boot_assets_text = self.query_one("#boot-assets", Input).value.strip()
        boot_assets_path = Path(boot_assets_text).expanduser() if boot_assets_text else None
        freedos_url = self.query_one("#freedos-url", Input).value.strip() or None
        label_text = self.query_one("#volume-label", Input).value.strip() or None
        overwrite = self.query_one("#overwrite", Checkbox).value

        return CreateRequest(
            path=Path(path_text).expanduser(),
            size_bytes=parse_size(size_text),
            disk_format=DiskFormat(format_value),
            label=label_text,
            overwrite=overwrite,
            boot_mode=BootMode(boot_value),
            freedos_source=FreeDOSSource(source_value),
            boot_assets_path=boot_assets_path,
            freedos_download_url=freedos_url,
        )

    def _refresh_mounts(self) -> None:
        mounts = self.manager.list_mounts()
        if not mounts:
            self.query_one("#mounts", Static).update("No active mounts tracked.")
            return
        lines = ["Active mounts:"]
        for item in mounts:
            lines.append(f"- {item.mount_point} <- {item.vhd_path} ({item.nbd_device})")
        self.query_one("#mounts", Static).update("\n".join(lines))

    def _set_status(self, message: str, *, error: bool = False) -> None:
        label = "[ERROR] " if error else "[OK] "
        self.query_one("#status", Static).update(f"{label}{message}")
