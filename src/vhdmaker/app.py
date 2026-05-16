"""Textual UI for VHD/IMG creation and mount workflows."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DirectoryTree, Footer, Header, Input, Label, Select, Static
from textual.widgets._directory_tree import DirEntry

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
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
    DEFAULT_MARTYPC_AT_FORMAT_SLUG,
    MARTYPC_AT_FORMATS,
    lookup_martypc_at_format,
)
from .size import parse_size

_DOS_INSTALL_PROFILE_OPTIONS = [
    ("Boot files only", MSDOSInstallProfile.MINIMAL.value),
    ("Core DOS tools + startup files", MSDOSInstallProfile.FULL.value),
]
_IBM_DOS_VERSION_OPTIONS = [
    ("IBM DOS 3.3 (max 32MB)", IBMDOSVersion.DOS33.value),
    ("IBM DOS 5.0 (max ~504MB)", IBMDOSVersion.DOS50.value),
]
_MACHINE_TARGET_OPTIONS = [
    ("Generic (86Box / QEMU / etc.)", MachineTarget.GENERIC.value),
    ("MartyPC IBM/Xebec MFM", MachineTarget.MARTYPC_XEBEC.value),
    ("MartyPC XT-IDE (Rev 2 PIO)", MachineTarget.MARTYPC_XTIDE.value),
    ("MartyPC JR-IDE (PCjr sidecar)", MachineTarget.MARTYPC_JRIDE.value),
]
_MARTYPC_XEBEC_DRIVE_TYPE_OPTIONS = [
    (drive_type.description, drive_type.value)
    for drive_type in MartyPCXebecDriveType
]
# MartyPC's AT/XT-IDE table is 127 entries; the Select widget scrolls fine.
_MARTYPC_AT_DRIVE_TYPE_OPTIONS = [
    (
        f"{fmt.description}  [{fmt.cylinders}x{fmt.heads}x{fmt.sectors_per_track}]",
        fmt.slug,
    )
    for fmt in MARTYPC_AT_FORMATS
]
_FLOPPY_OPTIONS = [
    ("160K", FloppyType.F160K.value),
    ("180K", FloppyType.F180K.value),
    ("360K", FloppyType.F360K.value),
    ("720K", FloppyType.F720K.value),
    ("1.84M (XDF)", FloppyType.F1840K.value),
    ("1.2M", FloppyType.F1200K.value),
    ("1.44M", FloppyType.F1440K.value),
    ("2.88M", FloppyType.F2880K.value),
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
    #right-pane {
      overflow-y: auto;
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
    .path-row {
      height: auto;
      margin: 0 0 1 0;
    }
    .path-row Input {
      width: 1fr;
      margin: 0;
    }
    #right-pane .path-row Button, #left-pane .path-row Button {
      width: 6;
      min-width: 6;
      max-width: 6;
      margin: 0 0 0 1;
      padding: 0;
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
        self.path_picker_target: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="left-pane"):
                yield Label("Browse images and asset folders")
                yield ParentDirectoryTree(str(Path.cwd()), id="vhd-tree")
                yield Static("Selected image: (none)", id="selected-vhd")
                yield Button("Mount selected image", id="mount-btn", variant="primary")
                yield Input(placeholder="Mounted path to unmount", id="unmount-input")
                yield Button("Unmount mount path", id="unmount-btn", variant="warning")
                with Horizontal(classes="path-row", id="open-path-row"):
                    yield Input(placeholder="Path to open in Omarchy Files", id="open-input")
                    yield Button("📁", id="browse-open-btn")
                yield Button("Open path in Files", id="open-btn")
                yield Static("No active mounts tracked.", id="mounts")
            with Vertical(id="right-pane"):
                yield Label("Create disk image", id="create-title")
                yield Select(
                    options=[("VHD", MediaType.VHD.value), ("IMG (floppy)", MediaType.IMG.value)],
                    value=MediaType.VHD.value,
                    id="media-type",
                )
                yield Select(
                    options=_MACHINE_TARGET_OPTIONS,
                    value=MachineTarget.GENERIC.value,
                    id="machine-target",
                )
                yield Select(
                    options=_MARTYPC_XEBEC_DRIVE_TYPE_OPTIONS,
                    value=MartyPCXebecDriveType.TYPE2.value,
                    id="martypc-xebec-drive-type",
                )
                yield Select(
                    options=_MARTYPC_AT_DRIVE_TYPE_OPTIONS,
                    value=DEFAULT_MARTYPC_AT_FORMAT_SLUG,
                    id="martypc-at-drive-type",
                )
                with Horizontal(classes="path-row", id="create-path-row"):
                    yield Input(placeholder="Path (for example: ~/vhd/disk.vhd)", id="create-path")
                    yield Button("📁", id="browse-create-path-btn")
                yield Input(value="512M", placeholder="Static size (for example: 512M)", id="create-size")
                yield Select(
                    options=[
                        ("FAT12 (MartyPC Xebec Type 1 only)", DiskFormat.FAT12.value),
                        ("FAT16", DiskFormat.FAT16.value),
                        ("FAT32", DiskFormat.FAT32.value),
                    ],
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
                        ("Choose OS", BootMode.NONE.value),
                        ("FreeDOS bootable", BootMode.FREEDOS.value),
                        ("MS-DOS 7.1 bootable", BootMode.MSDOS71.value),
                        ("IBM PC 8088/V20 (DOS 3.3 / 5.0)", BootMode.IBM8088.value),
                        ("MS-DOS 3.3 bootable", BootMode.MSDOS33.value),
                        ("MS-DOS 3.31 bootable", BootMode.MSDOS331.value),
                        ("MS-DOS 5.0 bootable", BootMode.MSDOS5.value),
                        ("MS-DOS 6.22 bootable", BootMode.MSDOS622.value),
                        ("PC-DOS bootable", BootMode.PCDOS.value),
                        ("PC-DOS 7.0 bootable (XDF media)", BootMode.PCDOS7.value),
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
                    options=_DOS_INSTALL_PROFILE_OPTIONS,
                    value=MSDOSInstallProfile.MINIMAL.value,
                    id="dos-profile",
                )
                yield Select(
                    options=_IBM_DOS_VERSION_OPTIONS,
                    value=IBMDOSVersion.DOS33.value,
                    id="ibm-dos-version",
                )
                with Horizontal(classes="path-row", id="boot-assets-row"):
                    yield Input(
                        placeholder="Boot assets path (dir of DOS install disks, or a single .img)",
                        id="boot-assets",
                    )
                    yield Button("📁", id="browse-boot-assets-btn")
                with Horizontal(classes="path-row", id="custom-payload-row"):
                    yield Input(
                        placeholder="Custom payload directory — extra files to copy to C:\\ root (optional)",
                        id="custom-payload",
                    )
                    yield Button("📁", id="browse-custom-payload-btn")
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
        if self.path_picker_target is not None:
            if self.path_picker_target == "custom-payload":
                self._set_status("Custom payload must be a directory. Select a folder in the tree.", error=True)
                return
            self._apply_path_picker_selection(selected)
            return
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

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        selected = Path(event.path).expanduser().resolve()
        if self._is_parent_tree_entry(event, selected):
            self._set_tree_path(selected)
            return
        if self.path_picker_target is not None:
            self._apply_path_picker_selection(selected)
            return
        if self._is_boot_assets_picker_active():
            self.query_one("#boot-assets", Input).value = str(selected)
            self._set_status(f"Boot assets path set: {selected}")
            return
        self._set_status(f"Selected directory: {selected}")

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
        elif button_id == "browse-create-path-btn":
            self._handle_browse_button("create-path")
        elif button_id == "browse-boot-assets-btn":
            self._handle_browse_button("boot-assets")
        elif button_id == "browse-custom-payload-btn":
            self._handle_browse_button("custom-payload")
        elif button_id == "browse-open-btn":
            self._handle_browse_button("open-input")

    def on_select_changed(self, event: Select.Changed) -> None:
        if len(self.query("#create-path")) == 0:
            return
        if event.select.id == "media-type":
            media_type = MediaType(str(event.value))
            if media_type is MediaType.IMG:
                self.query_one("#img-system-format", Checkbox).value = False
                self.query_one("#boot-mode", Select).value = BootMode.NONE.value
                # IMG floppies can't use a MartyPC HDC target.
                self.query_one("#machine-target", Select).value = MachineTarget.GENERIC.value
            self._sync_create_form_visibility()
            return
        if event.select.id == "machine-target":
            target = MachineTarget(str(event.value))
            if target is MachineTarget.MARTYPC_XEBEC:
                # Xebec drive type drives the disk format: Type 1 is 10 MiB
                # FAT12, Types 2 / 13 / 16 are 20 MiB FAT16.
                drive_type = MartyPCXebecDriveType(
                    cast(str, self.query_one("#martypc-xebec-drive-type", Select).value)
                )
                if drive_type is MartyPCXebecDriveType.TYPE1:
                    self.query_one("#create-format", Select).value = DiskFormat.FAT12.value
                else:
                    self.query_one("#create-format", Select).value = DiskFormat.FAT16.value
                boot_value = cast(str, self.query_one("#boot-mode", Select).value)
                xt_modes = {
                    BootMode.NONE.value,
                    BootMode.IBM8088.value,
                    BootMode.MSDOS33.value,
                    BootMode.MSDOS331.value,
                    BootMode.PCDOS.value,
                    BootMode.COMPAQ331.value,
                }
                # FAT12 requires the msdos33-style FORMAT install pipeline;
                # snap incompatible boot modes to msdos33.
                if drive_type is MartyPCXebecDriveType.TYPE1:
                    if boot_value not in (
                        BootMode.MSDOS33.value,
                        BootMode.IBM8088.value,
                        BootMode.NONE.value,
                    ):
                        self.query_one("#boot-mode", Select).value = BootMode.MSDOS33.value
                elif boot_value not in xt_modes:
                    self.query_one("#boot-mode", Select).value = BootMode.MSDOS33.value
                # Force DOS 3.3 since the Xebec drive sizes are all well
                # under the DOS 5.0 cap and FAT12 only works with DOS 3.3.
                self.query_one("#ibm-dos-version", Select).value = IBMDOSVersion.DOS33.value
            self._sync_create_form_visibility()
            return
        if event.select.id == "martypc-xebec-drive-type":
            # Drive-type change can flip FAT12 ↔ FAT16 for MartyPC Xebec
            # targets. Reapply the same rule as the machine-target handler.
            target = MachineTarget(cast(str, self.query_one("#machine-target", Select).value))
            if target is MachineTarget.MARTYPC_XEBEC:
                drive_type = MartyPCXebecDriveType(str(event.value))
                if drive_type is MartyPCXebecDriveType.TYPE1:
                    self.query_one("#create-format", Select).value = DiskFormat.FAT12.value
                    boot_value = cast(str, self.query_one("#boot-mode", Select).value)
                    if boot_value not in (
                        BootMode.MSDOS33.value,
                        BootMode.IBM8088.value,
                        BootMode.NONE.value,
                    ):
                        self.query_one("#boot-mode", Select).value = BootMode.MSDOS33.value
                else:
                    if (
                        cast(str, self.query_one("#create-format", Select).value)
                        == DiskFormat.FAT12.value
                    ):
                        self.query_one("#create-format", Select).value = DiskFormat.FAT16.value
            self._sync_create_form_visibility()
            return
        if event.select.id == "martypc-at-drive-type":
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
            self._sync_create_form_visibility()
            return
        if event.select.id == "ibm-dos-version":
            media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
            if media_type is MediaType.VHD:
                self._apply_ibm_default_size(force=False)
            self._sync_create_form_visibility()
            return
        if event.select.id == "floppy-type":
            self._sync_create_form_visibility()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if len(self.query("#create-path")) == 0:
            return
        if event.checkbox.id == "img-system-format":
            if not event.value:
                self.query_one("#boot-mode", Select).value = BootMode.NONE.value
            self._sync_create_form_visibility()

    def _sync_create_form_visibility(self) -> None:
        if len(self.query("#create-path")) == 0:
            return
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        machine_target = MachineTarget(cast(str, self.query_one("#machine-target", Select).value))
        boot_mode = BootMode(cast(str, self.query_one("#boot-mode", Select).value))
        freedos_source = FreeDOSSource(cast(str, self.query_one("#freedos-source", Select).value))
        img_system_format = self.query_one("#img-system-format", Checkbox).value

        is_vhd = media_type is MediaType.VHD
        is_martypc_xebec = is_vhd and machine_target is MachineTarget.MARTYPC_XEBEC
        is_martypc_at = is_vhd and machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        )
        is_martypc = is_martypc_xebec or is_martypc_at
        boot_controls_active = is_vhd or img_system_format

        show_freedos = boot_controls_active and boot_mode is BootMode.FREEDOS
        dos_boot_modes = {
            BootMode.MSDOS71,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.COMPAQ331,
        }
        show_dos_profile = boot_controls_active and boot_mode in dos_boot_modes
        show_ibm_dos_version = (
            boot_controls_active
            and boot_mode is BootMode.IBM8088
            # MartyPC Xebec drives are <= 32 MiB, MartyPC AT covers both
            # dos33 and dos50 sizes; hide the toggle on Xebec since dos33 is
            # forced by validation. AT keeps the toggle for user choice.
            and not is_martypc_xebec
        )
        show_boot_assets = (
            show_dos_profile
            or (show_freedos and freedos_source is FreeDOSSource.LOCAL)
        )
        show_freedos_url = show_freedos and freedos_source is FreeDOSSource.AUTO

        self.query_one("#create-title", Label).update("Create fixed-size VHD" if is_vhd else "Create floppy IMG")
        self.query_one("#create-path", Input).placeholder = (
            "Path (for example: ~/vhd/disk.vhd)" if is_vhd else "Path (for example: ~/floppy/disk.img)"
        )
        self.query_one("#create-btn", Button).label = "Create + format VHD" if is_vhd else "Create + format IMG"
        # Size + format are user-controlled only for generic VHD targets.
        # MartyPC targets derive size from the chosen drive type and require FAT16.
        self.query_one("#create-size", Input).display = is_vhd and not is_martypc
        self.query_one("#create-format", Select).display = is_vhd and not is_martypc_xebec
        self.query_one("#machine-target", Select).display = is_vhd
        self.query_one("#martypc-xebec-drive-type", Select).display = is_martypc_xebec
        self.query_one("#martypc-at-drive-type", Select).display = is_martypc_at
        self.query_one("#floppy-type", Select).display = not is_vhd
        self.query_one("#img-system-format", Checkbox).display = not is_vhd
        self.query_one("#boot-mode", Select).display = boot_controls_active
        self.query_one("#freedos-source", Select).display = show_freedos
        self.query_one("#fetch-freedos-btn", Button).display = show_freedos
        self.query_one("#dos-profile", Select).display = show_dos_profile
        self.query_one("#ibm-dos-version", Select).display = show_ibm_dos_version
        self.query_one("#boot-assets-row", Horizontal).display = show_boot_assets
        # Custom payload doesn't work with fixed-geometry MartyPC targets.
        self.query_one("#custom-payload-row", Horizontal).display = (
            (is_vhd or img_system_format) and not is_martypc
        )
        self.query_one("#freedos-url", Input).display = show_freedos_url

    def _handle_create(self) -> None:
        try:
            request = self._request_from_form()
        except VhdMakerError as exc:
            self._set_status(str(exc), error=True)
            return

        if not self._run_with_sudo_reauth(lambda: self.manager.create_and_prepare(request)):
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

        mounted_records: list[object] = []
        if not self._run_with_sudo_reauth(lambda: mounted_records.append(self.manager.mount_vhd(self.selected_image))):
            return
        if not mounted_records:
            self._set_status("Mount operation did not return a record.", error=True)
            return
        record = mounted_records[0]
        try:
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

        unmounted_records: list[object] = []
        if not self._run_with_sudo_reauth(
            lambda: unmounted_records.append(self.manager.unmount(Path(mountpoint_text)))
        ):
            return
        if not unmounted_records:
            self._set_status("Unmount operation did not return a record.", error=True)
            return
        record = unmounted_records[0]

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
        ibm_version_select = self.query_one("#ibm-dos-version", Select)
        machine_target_select = self.query_one("#machine-target", Select)
        martypc_xebec_select = self.query_one("#martypc-xebec-drive-type", Select)
        martypc_at_select = self.query_one("#martypc-at-drive-type", Select)

        media_value = cast(str, media_select.value)
        format_value = cast(str, format_select.value)
        floppy_value = cast(str, floppy_select.value)
        boot_value = cast(str, boot_select.value)
        source_value = cast(str, source_select.value)
        dos_profile_value = cast(str, dos_profile_select.value)
        ibm_version_value = cast(str, ibm_version_select.value)
        machine_target_value = cast(str, machine_target_select.value)
        martypc_xebec_value = cast(str, martypc_xebec_select.value)
        martypc_at_value = cast(str, martypc_at_select.value)
        img_system_format = self.query_one("#img-system-format", Checkbox).value

        media_type = MediaType(media_value)
        floppy_type = FloppyType(floppy_value)
        machine_target = MachineTarget(machine_target_value)
        martypc_xebec_drive_type = MartyPCXebecDriveType(martypc_xebec_value)

        msdos_install_profile = MSDOSInstallProfile(dos_profile_value)
        ibm_dos_version = IBMDOSVersion(ibm_version_value)

        boot_assets_text = self.query_one("#boot-assets", Input).value.strip()
        boot_assets_path = Path(boot_assets_text).expanduser() if boot_assets_text else None
        custom_payload_text = self.query_one("#custom-payload", Input).value.strip()
        custom_payload_path = Path(custom_payload_text).expanduser() if custom_payload_text else None
        freedos_url = self.query_one("#freedos-url", Input).value.strip() or None
        label_text = self.query_one("#volume-label", Input).value.strip() or None
        overwrite = self.query_one("#overwrite", Checkbox).value
        if (
            media_type is MediaType.VHD
            and boot_value == BootMode.IBM8088.value
            and size_text.upper() == "512M"
        ):
            size_text = "32M"

        if media_type is MediaType.VHD:
            if machine_target is MachineTarget.MARTYPC_XEBEC:
                # Size is forced by validation; provide the drive type's
                # known size so the request is internally consistent before
                # _validate_create_request runs.
                size_bytes = martypc_xebec_drive_type.size_bytes
            elif machine_target in (
                MachineTarget.MARTYPC_XTIDE,
                MachineTarget.MARTYPC_JRIDE,
            ):
                size_bytes = lookup_martypc_at_format(martypc_at_value).size_bytes
            elif size_text:
                size_bytes = parse_size(size_text)
            elif custom_payload_path is not None:
                size_bytes = 1
            else:
                raise VhdMakerError("Create size is required.")
        else:
            size_bytes = floppy_type.size_bytes
        request_boot_mode = BootMode(boot_value) if (media_type is MediaType.VHD or img_system_format) else BootMode.NONE
        disk_format = DiskFormat(format_value) if media_type is MediaType.VHD else DiskFormat.FAT16
        # MartyPC Xebec drive-type dictates the disk format:
        # Type 1 = 10 MiB FAT12, Types 2 / 13 / 16 = 20 MiB FAT16. Force
        # the right value here in case widget sync was missed.
        if machine_target is MachineTarget.MARTYPC_XEBEC:
            disk_format = (
                DiskFormat.FAT12
                if martypc_xebec_drive_type is MartyPCXebecDriveType.TYPE1
                else DiskFormat.FAT16
            )

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
            custom_payload_path=custom_payload_path,
            machine_target=machine_target,
            martypc_xebec_drive_type=martypc_xebec_drive_type,
            martypc_at_drive_type_slug=martypc_at_value,
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

    def _run_with_sudo_reauth(self, operation: Callable[[], None]) -> bool:
        try:
            operation()
            return True
        except VhdMakerError as exc:
            if not self._is_sudo_auth_error(exc):
                self._set_status(str(exc), error=True)
                return False
            ok, message = self._reauthenticate_sudo()
            if not ok:
                self._set_status(message, error=True)
                return False
            try:
                operation()
                return True
            except VhdMakerError as retry_exc:
                self._set_status(str(retry_exc), error=True)
                return False

    def _is_sudo_auth_error(self, exc: VhdMakerError) -> bool:
        message = str(exc)
        return (
            "Sudo authentication is required for disk operations." in message
            or "sudo: a password is required" in message
        )

    def _reauthenticate_sudo(self) -> tuple[bool, str]:
        password = self._request_password_dialog()
        if password is not None:
            result = subprocess.run(
                ["sudo", "--stdin", "--preserve-env=HOME,PATH", "-v"],
                input=f"{password}\n",
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return (True, "Sudo credentials refreshed.")
            detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            return (False, f"Sudo re-authentication failed. Details: {detail}")

        result = subprocess.run(["sudo", "--preserve-env=HOME,PATH", "-v"], check=False)
        if result.returncode == 0:
            return (True, "Sudo credentials refreshed.")
        return (
            False,
            "Sudo re-authentication failed or was canceled. Retry and enter your password when prompted.",
        )

    def _request_password_dialog(self) -> str | None:
        command = [
            "zenity",
            "--password",
            "--title=VHDMaker sudo authentication",
            "--text=Enter your sudo password to continue disk operations",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        password = result.stdout.strip()
        if not password:
            return None
        return password

    def _handle_browse_button(self, target: str) -> None:
        selected = self._pick_path_with_dialog(target)
        if selected is not None:
            self.path_picker_target = target
            self._apply_path_picker_selection(selected)
            return
        self._start_path_picker(target)
        self._set_status("GUI file picker unavailable or canceled. Select from the left tree.")

    def _start_path_picker(self, target: str) -> None:
        self.path_picker_target = target
        self._set_status("Select a file or folder from the left tree to populate this field.")

    def _pick_path_with_dialog(self, target: str) -> Path | None:
        if target == "custom-payload":
            mode = "directory"
            title = "Select custom payload directory"
        elif target == "boot-assets":
            mode = "file_or_directory"
            title = "Select boot assets (directory or image)"
        elif target == "create-path":
            mode = "save"
            title = "Select image output path"
        else:
            mode = "file_or_directory"
            title = "Select path"

        start_path = self._path_picker_start_path(target)
        chosen = self._run_zenity_picker(mode=mode, title=title, start_path=start_path)
        if chosen is None:
            return None
        return Path(chosen).expanduser().resolve()

    def _path_picker_start_path(self, target: str) -> Path:
        value = ""
        if target == "create-path":
            value = self.query_one("#create-path", Input).value.strip()
        elif target == "boot-assets":
            value = self.query_one("#boot-assets", Input).value.strip()
        elif target == "custom-payload":
            value = self.query_one("#custom-payload", Input).value.strip()
        elif target == "open-input":
            value = self.query_one("#open-input", Input).value.strip()
        if value:
            candidate = Path(value).expanduser()
            if candidate.exists():
                return candidate if candidate.is_dir() else candidate.parent
            if candidate.parent.exists():
                return candidate.parent
        return Path.cwd()

    def _run_zenity_picker(self, *, mode: str, title: str, start_path: Path) -> str | None:
        base = ["zenity", "--file-selection", f"--title={title}"]
        start_dir = str(start_path.expanduser().resolve())
        if start_path.is_dir():
            start_hint = start_dir.rstrip("/") + "/"
        else:
            start_hint = start_dir

        if mode == "file_or_directory":
            choice = self._run_zenity_command(
                [
                    "zenity",
                    "--list",
                    "--radiolist",
                    f"--title={title}",
                    "--text=Choose what to browse:",
                    "--column=Select",
                    "--column=Type",
                    "TRUE",
                    "File",
                    "FALSE",
                    "Folder",
                ]
            )
            if choice is None:
                return None
            mode = "directory" if choice == "Folder" else "file"

        command = list(base)
        if mode == "directory":
            command.append("--directory")
        elif mode == "save":
            command.extend(["--save", "--confirm-overwrite"])
        command.append(f"--filename={start_hint}")
        return self._run_zenity_command(command)

    def _run_zenity_command(self, command: list[str]) -> str | None:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        selected = result.stdout.strip()
        if not selected:
            return None
        return selected

    def _apply_path_picker_selection(self, selected: Path) -> None:
        target = self.path_picker_target
        if target is None:
            return
        if target == "create-path":
            self.query_one("#create-path", Input).value = str(selected)
            self._set_status(f"Create path set: {selected}")
        elif target == "boot-assets":
            self.query_one("#boot-assets", Input).value = str(selected)
            self._set_status(f"Boot assets path set: {selected}")
        elif target == "custom-payload":
            if not selected.is_dir():
                self._set_status("Custom payload must be a directory. Select a folder in the tree.", error=True)
                return
            self.query_one("#custom-payload", Input).value = str(selected)
            self._set_status(f"Custom payload path set: {selected}")
        elif target == "open-input":
            self.query_one("#open-input", Input).value = str(selected)
            self._set_status(f"Open path set: {selected}")
        self.path_picker_target = None

    def _set_tree_path(self, destination: Path) -> None:
        tree = self.query_one("#vhd-tree", DirectoryTree)
        tree.path = str(destination)
        tree.reload()
        self._set_status(f"Browsing: {destination}")

    def _is_parent_tree_entry(self, event: DirectoryTree.DirectorySelected, selected: Path) -> bool:
        node = getattr(event, "node", None)
        if node is None:
            return False
        label = getattr(node, "label", None)
        if label is None:
            return False
        plain_label = getattr(label, "plain", str(label))
        if plain_label != "../":
            return False
        tree = self.query_one("#vhd-tree", DirectoryTree)
        current = Path(str(tree.path)).expanduser().resolve()
        parent = current.parent
        return parent != current and selected == parent

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

    def _is_boot_assets_picker_active(self) -> bool:
        if len(self.query("#boot-assets")) == 0:
            return False
        return bool(self.query_one("#boot-assets", Input).display)


class ParentDirectoryTree(DirectoryTree):
    """Directory tree that injects a ../ entry for navigating to parent directory."""

    def _populate_node(self, node, content):  # type: ignore[override]
        node.remove_children()
        dir_entry = node.data
        if dir_entry is not None and node == self.root:
            parent = dir_entry.path.parent
            if parent != dir_entry.path:
                node.add("../", data=DirEntry(parent), allow_expand=True)
        for path in content:
            node.add(path.name, data=DirEntry(path), allow_expand=self._safe_is_dir(path))
        node.expand()
