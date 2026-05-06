"""Textual UI for VHD/IMG creation and mount workflows."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DirectoryTree, Footer, Header, Input, Label, Select, Static

from .disk import DiskManager
from .errors import VhdMakerError
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)
from .size import parse_size

_DOS_PROFILE_MSDOS71_MINIMAL = f"{BootMode.MSDOS71.value}:{MSDOSInstallProfile.MINIMAL.value}"
_DOS_PROFILE_MSDOS71_FULL = f"{BootMode.MSDOS71.value}:{MSDOSInstallProfile.FULL.value}"
_DOS_PROFILE_IBM_DOS33 = f"{BootMode.IBM8088.value}:{IBMDOSVersion.DOS33.value}"
_DOS_PROFILE_IBM_DOS50 = f"{BootMode.IBM8088.value}:{IBMDOSVersion.DOS50.value}"
_DOS_PROFILE_MSDOS71_OPTIONS = [
    ("MS-DOS 7.1 minimal install", _DOS_PROFILE_MSDOS71_MINIMAL),
    ("MS-DOS 7.1 full C:\\DOS install", _DOS_PROFILE_MSDOS71_FULL),
]
_DOS_PROFILE_IBM_OPTIONS = [
    ("IBM DOS 3.3 (max 32MB)", _DOS_PROFILE_IBM_DOS33),
    ("IBM DOS 5.0 (max ~504MB)", _DOS_PROFILE_IBM_DOS50),
]
_FLOPPY_OPTIONS = [
    ("160K", FloppyType.F160K.value),
    ("180K", FloppyType.F180K.value),
    ("320K", FloppyType.F320K.value),
    ("360K", FloppyType.F360K.value),
    ("720K", FloppyType.F720K.value),
    ("1.2M", FloppyType.F1200K.value),
    ("1.44M", FloppyType.F1440K.value),
]


class VhdMakerApp(App[None]):
    TITLE = "VHD Maker"
    SUB_TITLE = "Create, mount, browse, and unmount DOS-friendly disk images"
    BINDINGS = [("q", "quit", "Quit")]

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
    #right-pane Button {
      width: 100%;
      margin: 0 1 1 1;
      padding: 0 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.manager = DiskManager()
        self.selected_image: Path | None = None
        self._dos_profile_mode: BootMode | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="left-pane"):
                yield Label("Browse .vhd/.img/.ima files")
                yield DirectoryTree(str(Path.cwd()), id="vhd-tree")
                yield Static("Selected image: (none)", id="selected-vhd")
                yield Button("Mount selected image", id="mount-btn", variant="primary")
                yield Input(placeholder="Mounted path to unmount", id="unmount-input")
                yield Button("Unmount mount path", id="unmount-btn", variant="warning")
                yield Input(placeholder="Path to open in Omarchy Files", id="open-input")
                yield Button("Open path in Files", id="open-btn")
                yield Static("No active mounts tracked.", id="mounts")
            with Vertical(id="right-pane"):
                yield Label("Create disk image", id="create-title")
                yield Select(
                    options=[("VHD", MediaType.VHD.value), ("IMG (floppy)", MediaType.IMG.value)],
                    value=MediaType.VHD.value,
                    id="media-type",
                )
                yield Input(placeholder="Path (for example: ~/vhd/disk.vhd)", id="create-path")
                yield Input(value="512M", placeholder="Static size (for example: 512M)", id="create-size")
                yield Select(
                    options=[("FAT16", DiskFormat.FAT16.value), ("FAT32", DiskFormat.FAT32.value)],
                    value=DiskFormat.FAT16.value,
                    id="create-format",
                )
                yield Select(
                    options=_FLOPPY_OPTIONS,
                    value=FloppyType.F1440K.value,
                    id="floppy-type",
                )
                yield Checkbox("System format (bootable DOS IMG)", id="img-system-format")
                yield Select(
                    options=[
                        ("Choose", BootMode.NONE.value),
                        ("FreeDOS bootable", BootMode.FREEDOS.value),
                        ("MS-DOS 7.1 bootable", BootMode.MSDOS71.value),
                        ("IBM PC 8088/V20 (DOS 3.3 / 5.0)", BootMode.IBM8088.value),
                        ("PC-DOS bootable", BootMode.PCDOS.value),
                        ("Compaq DOS 3.31 bootable", BootMode.COMPAQ331.value),
                    ],
                    value=BootMode.NONE.value,
                    id="boot-mode",
                )
                yield Select(
                    options=[
                        ("Local FreeDOS assets", FreeDOSSource.LOCAL.value),
                        ("Auto-download FreeDOS image", FreeDOSSource.AUTO.value),
                    ],
                    value=FreeDOSSource.AUTO.value,
                    id="freedos-source",
                )
                yield Select(
                    options=_DOS_PROFILE_MSDOS71_OPTIONS,
                    value=_DOS_PROFILE_MSDOS71_MINIMAL,
                    id="dos-profile",
                )
                yield Input(placeholder="Boot assets path (dir or .img)", id="boot-assets")
                yield Input(placeholder="FreeDOS download URL (optional)", id="freedos-url")
                yield Button("Fetch latest FreeDOS into ./freedos", id="fetch-freedos-btn")
                yield Button("Run privilege diagnostics", id="diag-btn")
                yield Input(placeholder="Volume label (optional)", id="volume-label")
                yield Checkbox("Overwrite existing image", id="overwrite")
                yield Button("Create + format VHD", id="create-btn", variant="success")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.manager.preflight()
            self._set_status("Preflight check passed. Select or create an image to begin.")
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
        self._sync_create_form_visibility()
        self._refresh_mounts()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        selected = Path(event.path).expanduser().resolve()
        suffix = selected.suffix.lower()
        if suffix not in {".vhd", ".img", ".ima"}:
            self._set_status("Selected file is not a supported disk image.", error=True)
            return
        self.selected_image = selected
        size_bytes = selected.stat().st_size
        self.query_one("#selected-vhd", Static).update(f"Selected image: {selected}")
        self.query_one("#create-path", Input).value = str(selected)
        if suffix == ".vhd":
            self.query_one("#media-type", Select).value = MediaType.VHD.value
            self.query_one("#create-size", Input).value = self._format_size_for_input(size_bytes)
        else:
            self.query_one("#media-type", Select).value = MediaType.IMG.value
            floppy_type = self._floppy_type_for_size(size_bytes)
            if floppy_type is not None:
                self.query_one("#floppy-type", Select).value = floppy_type.value
            self.query_one("#img-system-format", Checkbox).value = False
        self._sync_create_form_visibility()
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
        elif button_id == "diag-btn":
            self._handle_privilege_diagnostics()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "media-type":
            media_type = MediaType(str(event.value))
            if media_type is MediaType.IMG:
                self.query_one("#img-system-format", Checkbox).value = False
                self.query_one("#boot-mode", Select).value = BootMode.NONE.value
            self._sync_create_form_visibility()
            return
        if event.select.id == "boot-mode":
            media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
            if media_type is MediaType.VHD and str(event.value) == BootMode.IBM8088.value:
                self._apply_ibm_default_size(force=True)
            self._sync_create_form_visibility()
            return
        if event.select.id == "freedos-source":
            self._sync_create_form_visibility()
            return
        if event.select.id == "dos-profile":
            media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
            boot_mode_value = cast(str, self.query_one("#boot-mode", Select).value)
            if boot_mode_value == BootMode.IBM8088.value and str(event.value) in {
                _DOS_PROFILE_IBM_DOS33,
                _DOS_PROFILE_IBM_DOS50,
            } and media_type is MediaType.VHD:
                self._apply_ibm_default_size(force=False)
            self._sync_create_form_visibility()
            return
        if event.select.id == "floppy-type":
            self._sync_create_form_visibility()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "img-system-format":
            if not event.value:
                self.query_one("#boot-mode", Select).value = BootMode.NONE.value
            self._sync_create_form_visibility()

    def _sync_create_form_visibility(self) -> None:
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        boot_mode = BootMode(cast(str, self.query_one("#boot-mode", Select).value))
        freedos_source = FreeDOSSource(cast(str, self.query_one("#freedos-source", Select).value))
        img_system_format = self.query_one("#img-system-format", Checkbox).value

        is_vhd = media_type is MediaType.VHD
        boot_controls_active = is_vhd or img_system_format

        show_freedos = boot_controls_active and boot_mode is BootMode.FREEDOS
        show_dos_profile = boot_controls_active and boot_mode in {BootMode.MSDOS71, BootMode.IBM8088}
        show_boot_assets = show_dos_profile or (show_freedos and freedos_source is FreeDOSSource.LOCAL)
        show_freedos_url = show_freedos and freedos_source is FreeDOSSource.AUTO

        self.query_one("#create-title", Label).update("Create fixed-size VHD" if is_vhd else "Create floppy IMG")
        self.query_one("#create-path", Input).placeholder = (
            "Path (for example: ~/vhd/disk.vhd)" if is_vhd else "Path (for example: ~/floppy/disk.img)"
        )
        self.query_one("#create-btn", Button).label = "Create + format VHD" if is_vhd else "Create + format IMG"
        self.query_one("#create-size", Input).display = is_vhd
        self.query_one("#create-format", Select).display = is_vhd
        self.query_one("#floppy-type", Select).display = not is_vhd
        self.query_one("#img-system-format", Checkbox).display = not is_vhd
        self.query_one("#boot-mode", Select).display = boot_controls_active
        self.query_one("#freedos-source", Select).display = show_freedos
        self.query_one("#fetch-freedos-btn", Button).display = show_freedos
        self.query_one("#dos-profile", Select).display = show_dos_profile
        self.query_one("#boot-assets", Input).display = show_boot_assets
        self.query_one("#freedos-url", Input).display = show_freedos_url

        if boot_controls_active and boot_mode in {BootMode.MSDOS71, BootMode.IBM8088}:
            self._configure_dos_profile_for_boot_mode(boot_mode)
        else:
            self._dos_profile_mode = None

    def _configure_dos_profile_for_boot_mode(self, boot_mode: BootMode) -> None:
        dos_profile = self.query_one("#dos-profile", Select)
        if boot_mode is BootMode.MSDOS71:
            options = _DOS_PROFILE_MSDOS71_OPTIONS
            default_value = _DOS_PROFILE_MSDOS71_MINIMAL
        else:
            options = _DOS_PROFILE_IBM_OPTIONS
            default_value = _DOS_PROFILE_IBM_DOS33

        current_value = dos_profile.value if isinstance(dos_profile.value, str) else default_value
        valid_values = {value for _, value in options}
        if current_value not in valid_values:
            current_value = default_value

        if self._dos_profile_mode is not boot_mode:
            dos_profile.set_options(options)
            self._dos_profile_mode = boot_mode

        if dos_profile.value != current_value:
            dos_profile.value = current_value

    def _handle_create(self) -> None:
        try:
            request = self._request_from_form()
            self.manager.create_and_prepare(request)
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        self._set_status(f"Created and prepared: {request.path}")
        self.selected_image = request.path.expanduser().resolve()
        self.query_one("#selected-vhd", Static).update(f"Selected image: {self.selected_image}")
        self._refresh_browser_tree()
        self._refresh_mounts()

    def _handle_mount_selected(self) -> None:
        if self.selected_image is None:
            path_text = self.query_one("#create-path", Input).value.strip()
            if path_text:
                self.selected_image = Path(path_text).expanduser().resolve()
        if self.selected_image is None:
            self._set_status("Select a .vhd/.img/.ima file first.", error=True)
            return

        try:
            record = self.manager.mount_vhd(self.selected_image)
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

    def _handle_privilege_diagnostics(self) -> None:
        ok, summary = self.manager.privilege_diagnostics_summary()
        label = "[OK]" if ok else "[ERROR]"
        self.query_one("#status", Static).update(f"{label} {summary}")

    def _request_from_form(self) -> CreateRequest:
        path_text = self.query_one("#create-path", Input).value.strip()
        if not path_text:
            raise VhdMakerError("Create path is required.")
        size_text = self.query_one("#create-size", Input).value.strip()
        media_select = self.query_one("#media-type", Select)
        format_select = self.query_one("#create-format", Select)
        floppy_select = self.query_one("#floppy-type", Select)
        boot_select = self.query_one("#boot-mode", Select)
        source_select = self.query_one("#freedos-source", Select)
        dos_profile_select = self.query_one("#dos-profile", Select)

        media_value = cast(str, media_select.value)
        format_value = cast(str, format_select.value)
        floppy_value = cast(str, floppy_select.value)
        boot_value = cast(str, boot_select.value)
        source_value = cast(str, source_select.value)
        dos_profile_value = cast(str, dos_profile_select.value)
        img_system_format = self.query_one("#img-system-format", Checkbox).value

        media_type = MediaType(media_value)
        floppy_type = FloppyType(floppy_value)
        if media_type is MediaType.VHD and not size_text:
            raise VhdMakerError("Create size is required.")

        msdos_install_profile = (
            MSDOSInstallProfile.FULL if dos_profile_value == _DOS_PROFILE_MSDOS71_FULL else MSDOSInstallProfile.MINIMAL
        )
        ibm_dos_version = IBMDOSVersion.DOS50 if dos_profile_value == _DOS_PROFILE_IBM_DOS50 else IBMDOSVersion.DOS33

        boot_assets_text = self.query_one("#boot-assets", Input).value.strip()
        boot_assets_path = Path(boot_assets_text).expanduser() if boot_assets_text else None
        freedos_url = self.query_one("#freedos-url", Input).value.strip() or None
        label_text = self.query_one("#volume-label", Input).value.strip() or None
        overwrite = self.query_one("#overwrite", Checkbox).value
        if (
            media_type is MediaType.VHD
            and boot_value == BootMode.IBM8088.value
            and size_text.upper() == "512M"
        ):
            size_text = "32M"

        size_bytes = parse_size(size_text) if media_type is MediaType.VHD else floppy_type.size_bytes
        request_boot_mode = BootMode(boot_value) if (media_type is MediaType.VHD or img_system_format) else BootMode.NONE
        disk_format = DiskFormat(format_value) if media_type is MediaType.VHD else DiskFormat.FAT16

        return CreateRequest(
            path=Path(path_text).expanduser(),
            size_bytes=size_bytes,
            disk_format=disk_format,
            media_type=media_type,
            floppy_type=floppy_type,
            img_system_format=img_system_format,
            label=label_text,
            overwrite=overwrite,
            boot_mode=request_boot_mode,
            freedos_source=FreeDOSSource(source_value),
            boot_assets_path=boot_assets_path,
            freedos_download_url=freedos_url,
            msdos_install_profile=msdos_install_profile,
            ibm_dos_version=ibm_dos_version,
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

    def _refresh_browser_tree(self) -> None:
        self.query_one("#vhd-tree", DirectoryTree).reload()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        label = "[ERROR] " if error else "[OK] "
        self.query_one("#status", Static).update(f"{label}{message}")

    def _apply_ibm_default_size(self, *, force: bool) -> None:
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        if media_type is not MediaType.VHD:
            return
        size_input = self.query_one("#create-size", Input)
        if force or size_input.value.strip().upper() in {"", "512M"}:
            size_input.value = "32M"

    def _format_size_for_input(self, size_bytes: int) -> str:
        if size_bytes % (1024**3) == 0:
            return f"{size_bytes // (1024**3)}G"
        if size_bytes % (1024**2) == 0:
            return f"{size_bytes // (1024**2)}M"
        if size_bytes % 1024 == 0:
            return f"{size_bytes // 1024}K"
        return str(size_bytes)

    def _floppy_type_for_size(self, size_bytes: int) -> FloppyType | None:
        for floppy_type in FloppyType:
            if floppy_type.size_bytes == size_bytes:
                return floppy_type
        return None
