"""Textual UI for VHD/IMG creation and mount workflows."""

from __future__ import annotations

import subprocess
import sys
import time
from itertools import cycle
from pathlib import Path
from typing import Callable
from typing import cast
from dataclasses import replace as fl_replace

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Checkbox,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets._directory_tree import DirEntry
from textual.widgets._select import SelectCurrent, SelectOverlay
from textual import on as _textual_on

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

from .disk import DiskManager
from .errors import DosForgeError, ValidationError
from . import __version__
from . import formlogic as fl
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    GeometrySource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    DiskController,
    MediaType,
    BIOSVendor,
    iter_bios_drive_types,
    lookup_bios_drive_type,
    parse_bios_drive_slug,
)
from .size import parse_size


class SingleClickSelect(Select):
    """A :class:`Select` that opens its dropdown on the first mouse click.

    Textual's default ``Select`` requires two clicks: the first only
    settles focus, the second runs the Toggle.  We open the overlay
    eagerly on ``MouseDown`` so it appears on the first press.

    **Root cause of the v0.7.5–v0.7.8 close-the-open-dropdown bug:**
    the previous patches all assumed the event order on the *second*
    click was ``MouseDown → Toggle``.  Empirical tracing with
    ``Pilot.click`` shows the real order is::

        SelectOverlay loses focus
        → SelectOverlay.Dismiss(lost_focus=True) handled by parent
        → self.expanded = False (and ``_watch_expanded(False)`` fires)
        → MouseDown delivered to us, sees ``expanded == False``
        → our handler "helpfully" calls ``action_show_overlay()`` →
          reopens the dropdown that the user just clicked closed
        → SelectCurrent.Toggle arrives, our handler sees the
          "just opened on MouseDown" flag and leaves expanded True
        → dropdown stays open forever.

    Fix: record the timestamp of every blur-driven Dismiss; if a
    ``MouseDown`` lands on us within a few milliseconds of one, the
    user is clicking us to close the already-open dropdown (the blur
    dismiss closed it for us) so we must *not* re-open in
    ``MouseDown``.

    Subclass-only: drop-in replacement for ``Select``.
    """

    _just_opened_on_mouse_down: bool = False
    _last_blur_dismiss_monotonic: float = 0.0
    _BLUR_DISMISS_GRACE_SECONDS: float = 0.15

    @_textual_on(SelectOverlay.Dismiss)
    def _track_blur_dismiss(self, event: SelectOverlay.Dismiss) -> None:
        # Record the time of every blur-driven dismiss.  The parent
        # class's own ``@on(SelectOverlay.Dismiss)`` handler still
        # runs after this one and sets ``expanded = False`` — we do
        # NOT call ``event.prevent_default()`` here.  We only need
        # the timestamp so the next ``MouseDown`` can recognize that
        # the click landing on us caused the blur-dismiss and avoid
        # the otherwise-immediate re-open.
        if getattr(event, "lost_focus", False):
            self._last_blur_dismiss_monotonic = time.monotonic()

    def _on_mouse_down(self, event) -> None:
        # A blur-driven dismiss that fired in the last few ms was
        # almost certainly caused by this same click landing on us
        # (focus shifted off the overlay before MouseDown reached
        # us).  In that case the user clicked to close the dropdown
        # — the parent's dismiss handler did the close for us, so
        # don't re-open here.
        if (
            time.monotonic() - self._last_blur_dismiss_monotonic
            < self._BLUR_DISMISS_GRACE_SECONDS
        ):
            self._last_blur_dismiss_monotonic = 0.0
            return
        # Otherwise: open on the first MouseDown.
        if not self.expanded:
            self.action_show_overlay()
            self._just_opened_on_mouse_down = True

    @_textual_on(SelectCurrent.Toggle)
    def _single_click_toggle(self, event: SelectCurrent.Toggle) -> None:
        # Always block the parent's ``expanded = not expanded`` flip.
        # MouseDown above already put us in the right state.
        event.stop()
        event.prevent_default()
        if self._just_opened_on_mouse_down:
            self._just_opened_on_mouse_down = False
            return
        # MouseDown was a no-op (because a blur-dismiss had already
        # closed the overlay before we got the MouseDown).
        # ``expanded`` is already False at this point — nothing to do.


_DOS_INSTALL_PROFILE_OPTIONS = [
    ("Boot files only", MSDOSInstallProfile.MINIMAL.value),
    ("Core DOS tools + startup files", MSDOSInstallProfile.FULL.value),
]
_IBM_DOS_VERSION_OPTIONS = [
    ("MS-DOS 3.3 (max 32MB)", IBMDOSVersion.MSDOS33.value),
    ("PC-DOS 3.x (max 32MB, FAT12/16)", IBMDOSVersion.PCDOS3.value),
    ("MS-DOS 5.0 (max ~504MB)", IBMDOSVersion.MSDOS5.value),
    ("PC-DOS 5.x (max ~504MB)", IBMDOSVersion.PCDOS5.value),
]
_DISK_CONTROLLER_OPTIONS = [
    ("Auto-detect from boot mode", ""),
    ("IDE (AT-class)", DiskController.IDE.value),
    ("MFM (XT-class, ST-225 era)", DiskController.MFM.value),
    ("XT-IDE (XT-class, MartyPC default)", DiskController.XTIDE.value),
]

_GEOMETRY_SOURCE_OPTIONS = [
    ("Static size (auto geometry)", GeometrySource.SIZE.value),
    ("BIOS preset (Phoenix / AMI / MartyPC-Xebec type table)", GeometrySource.PRESET.value),
    ("Custom CHS (cylinders, heads, sectors)", GeometrySource.CUSTOM_CHS.value),
]

_BIOS_CUSTOM_VALUE = ""
_BIOS_DRIVE_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("Custom — use size field", _BIOS_CUSTOM_VALUE),
]
for _vendor in (BIOSVendor.PHOENIX, BIOSVendor.AMI, BIOSVendor.MARTYPC_XEBEC):
    for _spec in iter_bios_drive_types(_vendor):
        _BIOS_DRIVE_TYPE_OPTIONS.append((_spec.description, _spec.slug))
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


_GROW_HELP_TEXT = """Grow VHD — supported modes and limits

Supported boot modes (4):
  • FreeDOS              — FAT16 (up to ~2 GiB) or FAT32 (up to ~32 GiB practical)
  • MS-DOS 7.10 / Win95  — FAT16 (up to ~2 GiB) or FAT32 (up to ~32 GiB practical)
  • MS-DOS 6.22          — FAT16 (up to ~2 GiB)
  • Compaq DOS 3.31      — FAT16 BIGDOS (up to ~504 MiB)

dosforge auto-detects the boot mode from the source VHD's root files
(KERNEL.SYS → FreeDOS, IBMBIO.COM → Compaq, MSDOS.SYS '[Paths]' header
→ MS-DOS 7.10, else MS-DOS 6.22).  You don't have to pick anything.

Hard limits:
  • Container        : VHD only (fixed-format Microsoft Virtual PC).
                       No dynamic / differencing VHDs.
                       No floppy IMGs (.img / .ima / .vfd) — those
                       have fixed geometry; rebuild with 'dosforge create'.
  • Direction        : grow only.  Never shrinks.
  • Cluster band     : the new size must stay within the same cluster
                       band as the source (mformat picks different
                       cluster sizes at certain size thresholds).
                       Crossing a band is rejected after extraction
                       with a clear error.

What it preserves:
  • All system files (IO.SYS / KERNEL.SYS / MSDOS.SYS / COMMAND.COM /
    IBMBIO.COM / IBMDOS.COM / …).
  • CONFIG.SYS, AUTOEXEC.BAT, FDCONFIG.SYS, FDAUTO.BAT.
  • Every user directory and file under C:\\, with mtimes preserved.

What it does NOT support — rebuild via 'dosforge create':
  • MS-DOS 2.x / 3.3 / 3.31 (32 MiB FAT12 cap)
  • DR-DOS 6.0 / 7.x
  • IBM PC-DOS 7.0 / 7.1 SGTK / PC-DOS 2000
  • MS-DOS 5.0
  • Any image that isn't a fixed-format VHD

The grow pipeline runs 8 steps end-to-end:
  1. Snapshot source VHD geometry
  2. Validate new size + cluster band
  3. Extract files from source VHD via mtools
  4. Build fresh VHD at the new size (may need sudo for qemu-nbd on Linux)
  5. Inject extracted files into new VHD via batched mcopy
  6. Stage any additional host → DOS directories
  7. Headless boot probe (optional; ~60-90s) — verifies the new VHD
     actually boots before the swap
  8. Atomic swap (original → <target>.bak, new → target)

Press Esc, Enter, or Close to dismiss this help."""


class _GrowHelpScreen(ModalScreen):
    """Modal popup with the full Grow-VHD supported-modes + limits table."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("enter", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    _GrowHelpScreen {
        align: center middle;
    }
    _GrowHelpScreen > Vertical {
        width: 90%;
        max-width: 96;
        height: auto;
        max-height: 90%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    _GrowHelpScreen #grow-help-body {
        height: auto;
        max-height: 30;
        padding: 0 1;
    }
    _GrowHelpScreen #grow-help-actions {
        height: auto;
        align: right middle;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll(id="grow-help-body"):
                yield Static(_GROW_HELP_TEXT)
            with Horizontal(id="grow-help-actions"):
                yield Button("Close", id="grow-help-close", classes="btn-primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "grow-help-close":
            self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()


class DosForgeApp(App[None]):
    TITLE = f"DosForge v{__version__}"
    SUB_TITLE = "Build, browse, and mount DOS-friendly disk images"
    ALLOW_SELECT = False
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+1", "show_tab('tab-new')", "New Disk"),
        ("ctrl+2", "show_tab('tab-browse')", "Browse"),
        ("ctrl+3", "show_tab('tab-tools')", "Image Tools"),
        ("ctrl+4", "show_tab('tab-mounts')", "Mounts"),
        ("ctrl+5", "show_tab('tab-utils')", "Utilities"),
        ("ctrl+y", "copy_log", "Copy log"),
        ("ctrl+shift+l", "clear_log", "Clear log"),
    ]

    CSS = """
    Screen {
      layout: vertical;
      background: $surface;
    }
    Header {
      background: $primary 30%;
    }
    Button:focus {
      text-style: bold;
    }
    #context-bar {
      height: 1;
      padding: 0 2;
      color: $text 80%;
      background: $boost;
    }
    TabbedContent {
      height: 1fr;
    }
    TabPane {
      padding: 1 2 0 2;
    }
    Tabs {
      background: $surface;
    }

    /* ── New Disk wizard ────────────────────────────────────────── */
    #wizard-progress {
      height: 1;
      padding: 0 1;
      color: $primary;
      text-style: bold;
      margin: 0 0 1 0;
    }
    #wizard-layout {
      layout: horizontal;
      height: 1fr;
    }
    #wizard-main {
      width: 2fr;
      height: 1fr;
      padding: 0 1 0 0;
    }
    #wizard-side {
      width: 1fr;
      height: 1fr;
      padding: 0;
    }
    #wizard-scroll {
      height: 1fr;
      border: round $primary;
      padding: 1 2;
      background: $surface;
    }
    #wizard-scroll:focus-within {
      border: round $accent;
    }
    #create-title {
      text-style: bold;
      color: $primary;
      margin: 0 0 1 0;
      height: 1;
    }
    .wizard-step {
      height: auto;
      padding: 0;
    }
    .wizard-step-title {
      text-style: bold;
      color: $accent;
      margin: 0 0 1 0;
      height: 1;
    }
    #wizard-summary {
      border: round $primary;
      padding: 1 2;
      height: 1fr;
      color: $text;
      background: $surface;
    }
    #wizard-nav {
      height: 3;
      margin: 1 0 0 0;
      padding: 0 1;
      align: left middle;
      background: $surface;
    }
    #wizard-nav Button {
      width: 24;
      margin: 0 1 0 0;
    }
    #wizard-nav #quick-create-btn {
      width: 18;
      margin-left: 2;
    }

    /* ── Browse / tools tabs ── */
    #browse-tab, #tools-tab, #mounts-tab, #utils-tab {
      layout: vertical;
      height: 1fr;
    }
    #vhd-tree {
      height: 1fr;
      border: round $primary;
      padding: 0 1;
      background: $surface;
    }
    #vhd-tree:focus-within {
      border: round $accent;
    }
    #selected-vhd {
      height: 1;
      padding: 0 1;
      color: $text 80%;
      margin: 1 0 0 0;
    }
    #mounts {
      border: round $primary;
      padding: 1;
      height: 1fr;
      min-height: 5;
      background: $surface;
    }
    #status-current {
      height: 1;
      padding: 0 2;
      margin: 0;
      color: $accent;
      background: $boost;
    }
    #status {
      height: 7;
      padding: 0 1;
      margin: 0;
      color: $text;
      background: $boost;
      border: round $primary;
      scrollbar-size-vertical: 1;
    }
    #status:focus {
      border: round $accent;
    }

    /* ── Inputs / selects / labels: compact spacing ── */
    Label {
      margin: 0 0 0 0;
      color: $text 80%;
      height: 1;
    }
    Input, Select {
      margin: 0 0 1 0;
    }
    Checkbox {
      margin: 1 0 1 0;
      background: transparent;
    }
    .path-row {
      height: 3;
      margin: 0 0 1 0;
    }
    .path-row Input {
      width: 1fr;
      margin: 0;
    }
    .path-row Button {
      width: 5;
      min-width: 5;
      max-width: 5;
      /* Explicit longhand margins -- the shorthand 'margin: 0 0 0 1'
         was getting partially-overridden by the global 'Button {
         margin: 0 1 1 0; }' rule in Textual's CSS cascade.  Setting
         margin-left=0 keeps the '...' button flush against the right
         edge of the Input with no gap. */
      margin-top: 0;
      margin-right: 0;
      margin-bottom: 0;
      margin-left: 0;
      padding: 0;
    }

    /* Horizontal row of action buttons (e.g. Grow tab footer). Unlike
       .path-row this does NOT force a fixed 5-char button width, so
       multi-word labels like "Grow VHD" don't wrap. Compact `?`
       help buttons opt into a tighter width via .grow-help-btn. */
    .actions-row {
      height: 3;
      margin: 0 0 1 0;
    }
    .actions-row Button {
      margin-top: 0;
      margin-right: 1;
      margin-bottom: 0;
      margin-left: 0;
    }
    /* Compact `?` help buttons. Textual's Button widget has an
       implicit `border: tall` (2 cells) and we add `padding: 0 2`
       (4 cells), so a 1-char label needs 1 + 6 = 7 cells minimum.
       Earlier we forced width 5, which clipped the border/hover
       background and left a stair-step artifact protruding into
       the row gap when the button was hovered. */
    Button.grow-help-btn {
      width: 7;
      min-width: 7;
      max-width: 7;
    }

    /* ── Button palette: single blue primary, neutral secondary,
       red only for destructive. Drops the cyan/orange/green mix.
       NB: hover/focus backgrounds use SOLID colors only. Alpha
       percentages like `$primary 20%` render as a stipple pattern
       in conhost (no true alpha blending), which looks like the
       button is covered in hash marks. ── */
    Button {
      margin: 0 1 1 0;
      padding: 0 2;
      min-width: 12;
    }
    Button.btn-primary {
      background: $primary;
      color: $text;
      text-style: bold;
    }
    Button.btn-primary:hover {
      background: $accent;
      color: $text;
    }
    Button.btn-primary:focus {
      background: $accent;
      color: $text;
      text-style: bold;
    }
    Button.btn-secondary {
      background: $boost;
      color: $primary;
    }
    Button.btn-secondary:hover {
      background: $primary;
      color: $text;
    }
    Button.btn-secondary:focus {
      background: $primary;
      color: $text;
      text-style: bold;
    }
    Button.btn-destructive {
      background: $error;
      color: $text;
    }
    Button.btn-destructive:hover {
      background: $warning;
      color: $text;
    }
    Button.btn-destructive:focus {
      background: $warning;
      color: $text;
      text-style: bold;
    }
    Button.btn-ghost {
      background: transparent;
      color: $text 70%;
      min-width: 5;
    }
    Button.btn-ghost:hover {
      background: $boost;
      color: $text;
    }
    Button.btn-ghost:focus {
      background: $boost;
      color: $text;
    }

    /* Inputs and selects: solid focus backgrounds. Default alpha
       focus from Textual's stylesheet shows up as a hash pattern
       in conhost. */
    Input {
      background: $surface;
      color: $text;
    }
    Input:focus {
      background: $surface;
      border: tall $accent;
    }
    Select {
      background: $surface;
      color: $text;
    }
    Select:focus {
      background: $surface;
      border: tall $accent;
    }

    /* ── Tool rows ── */
    #extract-row, #open-row {
      height: 3;
      margin: 0 0 1 0;
    }
    #extract-row Input, #open-row Input {
      width: 1fr;
      margin: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.manager = DiskManager()
        self.selected_image: Path | None = None
        self.path_picker_target: str | None = None
        # Wizard state (1..4). Step 1 is shown by default; the rest are
        # toggled via display so the existing test_app_form.py assertions
        # against per-widget `.display` continue to read the correct
        # value (since _sync_create_form_visibility still runs).
        self._wizard_step: int = 1
        # Spinner state for long-running operations (Create + format VHD,
        # mount, unmount).  Animated via set_interval while a background
        # worker is in-flight so the user can see progress is happening.
        self._spinner_timer: Timer | None = None
        self._spinner_message: str = ""
        self._spinner_started_at: float = 0.0
        self._spinner_frames = cycle(_SPINNER_FRAMES)
        # Plain-text mirror of every line written to #status RichLog so
        # action_copy_log can return raw text on demand (RichLog.lines
        # holds rendered Strip objects which are awkward to round-trip).
        self._status_log_history: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-new"):
            # ── New Disk (wizard) ────────────────────────────────────
            with TabPane("New Disk", id="tab-new"):
                yield Static("", id="wizard-progress")
                with Horizontal(id="wizard-layout"):
                    with Vertical(id="wizard-main"):
                        with VerticalScroll(id="wizard-scroll"):
                            yield Label("Create disk image", id="create-title")

                            # Step 1: Boot OS (drives downstream media constraints)
                            with Container(id="step-1", classes="wizard-step"):
                                yield Label(
                                    "Step 1 — Boot OS",
                                    classes="wizard-step-title",
                                )
                                yield Label("Boot OS", id="boot-mode-label")
                                yield SingleClickSelect(
                                    options=[
                                        ("None (data disk only)", BootMode.NONE.value),
                                        ("FreeDOS", BootMode.FREEDOS.value),
                                        ("MS-DOS 7.10 / Win95 OSR2 (4.00.1111, FAT16/FAT32)", BootMode.MSDOS71.value),
                                        (
                                            "IBM PC 8088/V20 (DOS 3.3 or 5.0)",
                                            BootMode.IBM8088.value,
                                        ),
                                        ("MS-DOS 3.30", BootMode.MSDOS33.value),
                                        ("MS-DOS 3.31", BootMode.MSDOS331.value),
                                        ("MS-DOS 5.0", BootMode.MSDOS5.value),
                                        ("MS-DOS 6.0", BootMode.MSDOS6.value),
                                        ("MS-DOS 6.22", BootMode.MSDOS622.value),
                                        (
                                            "IBM PC-DOS 3.00 (1984, 360k DSDD)",
                                            BootMode.PCDOS3.value,
                                        ),
                                        (
                                            "MS-DOS 3.00 Compaq OEM (1985, 360k DSDD)",
                                            BootMode.COMPAQ3.value,
                                        ),
                                        (
                                            "IBM PC-DOS 7.0 (XDF media)",
                                            BootMode.PCDOS7.value,
                                        ),
                                        (
                                            "IBM PC-DOS 2000 (6-floppy set)",
                                            BootMode.PCDOS2000.value,
                                        ),
                                        (
                                            "IBM PC-DOS 7.1 (FAT32)",
                                            BootMode.PCDOS71.value,
                                        ),
                                        (
                                            "Compaq DOS 2.11 (1984, 360k DSDD or 10 MiB MFM VHD)",
                                            BootMode.COMPAQ2.value,
                                        ),
                                        ("Compaq DOS 3.31", BootMode.COMPAQ331.value),
                                        (
                                            "Digital Research DR DOS 6.0 (1991, 720k DSDD)",
                                            BootMode.DRDOS6.value,
                                        ),
                                        (
                                            "Caldera DR-DOS 7.03 (1999, FAT16 BIGDOS)",
                                            BootMode.DRDOS7.value,
                                        ),
                                    ],
                                    value=BootMode.NONE.value,
                                    id="boot-mode",
                                )
                                yield Label("FreeDOS source", id="freedos-source-label")
                                yield SingleClickSelect(
                                    options=[
                                        ("Local FreeDOS assets", FreeDOSSource.LOCAL.value),
                                        (
                                            "Auto-download FreeDOS image",
                                            FreeDOSSource.AUTO.value,
                                        ),
                                    ],
                                    value=FreeDOSSource.AUTO.value,
                                    id="freedos-source",
                                )
                                yield Label("DOS install profile", id="dos-profile-label")
                                yield SingleClickSelect(
                                    options=_DOS_INSTALL_PROFILE_OPTIONS,
                                    value=MSDOSInstallProfile.MINIMAL.value,
                                    id="dos-profile",
                                )
                                yield Label("DOS version", id="ibm-dos-version-label")
                                yield SingleClickSelect(
                                    options=_IBM_DOS_VERSION_OPTIONS,
                                    value=IBMDOSVersion.DOS33.value,
                                    id="ibm-dos-version",
                                )
                                # Boot assets directory is the LAST field in
                                # Step 1 so the user picks an OS (and, for
                                # IBM 8088 mode, the DOS version) FIRST --
                                # which lets coerce_on_boot_change /
                                # coerce_on_ibm_version_change pre-populate
                                # this Input with the right dosassets/<subdir>
                                # default (e.g. picking PC-DOS 3.x under
                                # IBM 8088 fills in "pcdos3").
                                yield Label("Boot assets directory or install image", id="boot-assets-label")
                                with Horizontal(classes="path-row", id="boot-assets-row"):
                                    yield Input(
                                        placeholder=(
                                            "Boot assets: bare name like 'msdos33' "
                                            "(looks in ./dosassets/), or full path"
                                        ),
                                        id="boot-assets",
                                    )
                                    yield Button("...", id="browse-boot-assets-btn", classes="btn-ghost")

                            # Step 2: Media (constraints inherited from Step 1)
                            with Container(id="step-2", classes="wizard-step"):
                                yield Label(
                                    "Step 2 — Media",
                                    classes="wizard-step-title",
                                )
                                yield Label("Disk type")
                                yield SingleClickSelect(
                                    options=[
                                        ("VHD (fixed-size hard disk)", MediaType.VHD.value),
                                        ("IMG (floppy)", MediaType.IMG.value),
                                    ],
                                    value=MediaType.VHD.value,
                                    id="media-type",
                                )
                                yield Label("Output path", id="create-path-label")
                                with Horizontal(classes="path-row", id="create-path-row"):
                                    yield Input(
                                        placeholder="Path (for example: ~/vhd/disk.vhd)",
                                        id="create-path",
                                    )
                                    yield Button("...", id="browse-create-path-btn", classes="btn-ghost")
                                yield Label("Disk controller", id="disk-controller-label")
                                yield SingleClickSelect(
                                    options=_DISK_CONTROLLER_OPTIONS,
                                    value="",
                                    id="disk-controller",
                                )
                                yield Label("Geometry source", id="geometry-source-label")
                                yield SingleClickSelect(
                                    options=_GEOMETRY_SOURCE_OPTIONS,
                                    value=GeometrySource.SIZE.value,
                                    id="geometry-source",
                                )
                                yield Label("Static size", id="create-size-label")
                                yield Input(
                                    value="512M",
                                    placeholder="Static size (for example: 512M)",
                                    id="create-size",
                                )
                                yield Label("BIOS preset (Phoenix / AMI / MartyPC-Xebec type table)", id="bios-drive-type-label")
                                yield SingleClickSelect(
                                    options=_BIOS_DRIVE_TYPE_OPTIONS,
                                    value=_BIOS_CUSTOM_VALUE,
                                    id="bios-drive-type",
                                )
                                yield Label("Custom CHS", id="custom-chs-label")
                                yield Input(
                                    placeholder="CYL,HEAD,SPT (for example 306,4,17)",
                                    id="custom-chs",
                                )
                                # Live geometry preview (auto-updated by
                                # _sync_create_form_visibility -> _refresh_geometry_preview).
                                # Shows the effective MB + cyl/head/spt
                                # so the user sees what they'll get before
                                # clicking Create.
                                yield Static("", id="geometry-preview")
                                yield Label("Filesystem", id="create-format-label")
                                yield SingleClickSelect(
                                    options=[
                                        ("FAT12 (MFM / DOS 2.x-3.x)", DiskFormat.FAT12.value),
                                        ("FAT16", DiskFormat.FAT16.value),
                                        ("FAT32", DiskFormat.FAT32.value),
                                    ],
                                    value=DiskFormat.FAT16.value,
                                    id="create-format",
                                )
                                yield Label("Floppy size", id="floppy-type-label")
                                yield SingleClickSelect(
                                    options=_FLOPPY_OPTIONS,
                                    value=FloppyType.F1440K.value,
                                    id="floppy-type",
                                )
                                yield Checkbox(
                                    "System format (bootable DOS IMG)",
                                    id="img-system-format",
                                )

                            # Step 3: Assets & payload
                            with Container(id="step-3", classes="wizard-step"):
                                yield Label(
                                    "Step 3 — Payload and extras",
                                    classes="wizard-step-title",
                                )
                                yield Label("Custom payload directory (optional)", id="custom-payload-label")
                                with Horizontal(classes="path-row", id="custom-payload-row"):
                                    yield Input(
                                        placeholder=(
                                            "Extra files to copy to C:\\ root (optional)"
                                        ),
                                        id="custom-payload",
                                    )
                                    yield Button(
                                        "...",
                                        id="browse-custom-payload-btn",
                                        classes="btn-ghost",
                                    )
                                yield Label("FreeDOS download URL (optional)", id="freedos-url-label")
                                yield Input(
                                    placeholder="FreeDOS download URL (optional)",
                                    id="freedos-url",
                                )
                                yield Button(
                                    "Fetch latest FreeDOS into ./freedos",
                                    id="fetch-freedos-btn",
                                    classes="btn-secondary",
                                )
                                yield Button(
                                    "Fetch IBM PC-DOS 7.1 assets (SGTK download)",
                                    id="fetch-pcdos71-btn",
                                    classes="btn-secondary",
                                )

                            # Step 4: Confirm
                            with Container(id="step-4", classes="wizard-step"):
                                yield Label(
                                    "Step 4 — Review and create",
                                    classes="wizard-step-title",
                                )
                                yield Label("Volume label (optional)")
                                yield Input(
                                    placeholder="Volume label (optional)",
                                    id="volume-label",
                                )
                                yield Checkbox(
                                    "Overwrite existing image",
                                    id="overwrite",
                                )
                                yield Button(
                                    "Create + format VHD",
                                    id="create-btn",
                                    classes="btn-primary",
                                )

                        # Wizard nav (pinned below the scroll area, always visible)
                        with Horizontal(id="wizard-nav"):
                            yield Button(
                                "< Back",
                                id="wizard-back-btn",
                                classes="btn-secondary",
                            )
                            yield Button(
                                "Next: Media >",
                                id="wizard-next-btn",
                                classes="btn-primary",
                            )
                            yield Button(
                                "Quick Create",
                                id="quick-create-btn",
                                classes="btn-ghost",
                            )

                    with Vertical(id="wizard-side"):
                        yield Static(
                            "Summary will appear here as you fill the wizard.",
                            id="wizard-summary",
                        )

            # ── Browse ───────────────────────────────────────────────
            with TabPane("Browse", id="tab-browse"):
                with Vertical(id="browse-tab"):
                    yield Label("Browse images and asset folders")
                    yield ParentDirectoryTree(str(Path.cwd()), id="vhd-tree")
                    yield Static("Selected image: (none)", id="selected-vhd")

            # ── Image Tools ──────────────────────────────────────────
            with TabPane("Image Tools", id="tab-tools"):
                with Vertical(id="tools-tab"):
                    yield Label(
                        "Inspect or extract files from the selected image "
                        "(uses mtools — no admin / kernel mount needed)."
                    )
                    yield Button(
                        "Inspect VHD (MBR + BPB + root system files)",
                        id="inspect-btn",
                        classes="btn-secondary",
                    )
                    yield Button(
                        "List contents (ls)",
                        id="ls-btn",
                        classes="btn-secondary",
                    )
                    with Horizontal(classes="path-row", id="extract-row"):
                        yield Input(
                            placeholder="DOS path inside image (e.g. /CONFIG.SYS or C:\\CONFIG.SYS)",
                            id="extract-input",
                        )
                        yield Button("Extract", id="extract-btn", classes="btn-secondary")
                    with Horizontal(classes="path-row", id="open-path-row"):
                        yield Input(
                            placeholder="Path to open in file manager",
                            id="open-input",
                        )
                        yield Button("...", id="browse-open-btn", classes="btn-ghost")
                    yield Button(
                        "Open path in Files",
                        id="open-btn",
                        classes="btn-secondary",
                    )

            # ── Grow ─────────────────────────────────────────────────
            with TabPane("Grow Disk", id="tab-grow"):
                with Vertical(id="grow-tab"):
                    yield Label(
                        "Resize an existing VHD in place (preserves system + "
                        "user files, CONFIG.SYS / AUTOEXEC.BAT, and any "
                        "directory tree).  Optionally stage new directories "
                        "at the same time."
                    )
                    yield Static(
                        "Supported boot modes:\n"
                        "  • FreeDOS / MS-DOS 7.10  - FAT16 ≤ 2 GiB,  FAT32 ≤ 32 GiB\n"
                        "  • MS-DOS 6.22            - FAT16 ≤ 2 GiB\n"
                        "  • Compaq DOS 3.31        - FAT16 BIGDOS ≤ 504 MiB\n"
                        "Other boot modes must be rebuilt via 'dosforge create'.  "
                        "Press ? for full details.",
                        id="grow-supported-info",
                    )
                    yield Static("Target VHD: (select via Browse tab first)", id="grow-target-info")
                    with Horizontal(classes="path-row", id="grow-target-row"):
                        yield Input(
                            placeholder="Target VHD path",
                            id="grow-target-input",
                        )
                        yield Button("...", id="browse-grow-target-btn", classes="btn-ghost")
                    with Horizontal(classes="path-row", id="grow-size-row"):
                        yield Input(
                            placeholder="New size (e.g. 128M, 256M, 1G, 2G)",
                            id="grow-new-size-input",
                        )
                    with Horizontal(classes="path-row", id="grow-staging-row"):
                        yield Input(
                            placeholder="Optional: stage HOST_DIR=C:\\DOS_PATH (repeatable)",
                            id="grow-staging-input",
                        )
                        yield Button("Add", id="grow-add-staging-btn", classes="btn-ghost")
                    yield Static("(no staging sources)", id="grow-staging-list")
                    yield Checkbox(
                        "Headless boot probe (adds ~60-90s; verifies new VHD boots before swap)",
                        value=True,
                        id="grow-boot-probe-check",
                    )
                    yield Checkbox(
                        "Keep original VHD as <target>.bak",
                        value=True,
                        id="grow-keep-backup-check",
                    )
                    with Horizontal(classes="actions-row", id="grow-actions-row"):
                        yield Button(
                            "Grow VHD",
                            id="grow-btn",
                            classes="btn-primary",
                        )
                        yield Button(
                            "?",
                            id="grow-help-btn",
                            classes="btn-ghost grow-help-btn",
                        )
                    yield Static("", id="grow-output")

            # ── Mounts ───────────────────────────────────────────────
            with TabPane("Mounts", id="tab-mounts"):
                with Vertical(id="mounts-tab"):
                    yield Label(
                        "Mount or unmount the currently selected disk image. "
                        "On Windows this uses Mount-DiskImage (admin required); "
                        "on Linux it uses qemu-nbd + loop mount."
                    )
                    yield Button(
                        "Mount selected image",
                        id="mount-btn",
                        classes="btn-primary",
                    )
                    yield Input(
                        placeholder="Mounted path to unmount",
                        id="unmount-input",
                    )
                    yield Button(
                        "Unmount mount path",
                        id="unmount-btn",
                        classes="btn-destructive",
                    )
                    yield Static("No active mounts tracked.", id="mounts")

            # ── Utilities ────────────────────────────────────────────
            with TabPane("Utilities", id="tab-utils"):
                with Vertical(id="utils-tab"):
                    yield Label("Diagnostics and maintenance helpers.")
                    yield Button(
                        "Run privilege diagnostics",
                        id="diag-btn",
                        classes="btn-secondary",
                    )
                    yield Static(
                        "Tip: download FreeDOS assets from the New Disk wizard "
                        "(Step 3) using the 'Fetch latest FreeDOS' button.",
                        id="utils-tip",
                    )

        yield Static("Selected image: (none)", id="context-bar")
        yield Static("", id="status-current")
        yield RichLog(
            id="status",
            max_lines=500,
            wrap=True,
            highlight=False,
            markup=False,
            auto_scroll=True,
        )
        yield Footer()

    def on_mount(self) -> None:
        # Force the Textual dark theme on every platform so the colors
        # match what we designed the CSS against, regardless of the
        # user's terminal palette or system light/dark preference.
        # Falls back silently on older Textual versions that don't
        # expose `self.theme` as a writable attribute.
        try:
            self.theme = "textual-dark"
        except Exception:
            pass
        try:
            self.manager.preflight()
            self._set_status("Preflight check passed. Select or create an image to begin.")
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
        # Backend-based gating: Linux uses kernel mount; Windows has
        # Mount-DiskImage for VHDs (admin required at runtime). Both
        # show the mount/unmount UI. On either backend we ALSO show the
        # mtools ls/extract verbs as the no-admin alternative — they're
        # the only way to browse images without admin elevation on
        # Windows, and they work for IMG floppies which Mount-DiskImage
        # doesn't support.
        import sys as _sys

        supports_mount = self.manager.backend.supports_kernel_mount or _sys.platform == "win32"
        self.query_one("#mount-btn", Button).display = supports_mount
        self.query_one("#unmount-input", Input).display = supports_mount
        self.query_one("#unmount-btn", Button).display = supports_mount
        # mtools verbs visible on Windows always; on Linux only when
        # kernel mount is unavailable (currently never).
        show_mtools_verbs = _sys.platform == "win32"
        self.query_one("#ls-btn", Button).display = show_mtools_verbs
        self.query_one("#extract-row", Horizontal).display = show_mtools_verbs
        # Privilege diagnostics button only makes sense on sudo backends.
        if not self.manager.backend.requires_sudo_for_disk_ops:
            self.query_one("#diag-btn", Button).display = False
        # Initialize wizard at step 1 (hides steps 2-4).
        self._set_wizard_step(1)
        self._sync_create_form_visibility()
        self._refresh_summary()
        self._update_context_bar()
        self._refresh_mounts()

    def action_show_tab(self, tab_id: str) -> None:
        """Keyboard shortcut handler: switch to a named tab."""
        try:
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

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
        self._update_context_bar()
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
        try:
            self.query_one("#grow-target-input", Input).value = str(selected)
        except Exception:
            pass
        try:
            self._refresh_grow_target_info()
        except Exception:
            pass
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
        elif button_id == "wizard-back-btn":
            self._handle_wizard_back()
        elif button_id == "wizard-next-btn":
            self._handle_wizard_next()
        elif button_id == "quick-create-btn":
            self._handle_quick_create()
        elif button_id == "mount-btn":
            self._handle_mount_selected()
        elif button_id == "unmount-btn":
            self._handle_unmount()
        elif button_id == "ls-btn":
            self._handle_image_ls()
        elif button_id == "inspect-btn":
            self._handle_image_inspect()
        elif button_id == "extract-btn":
            self._handle_image_extract()
        elif button_id == "open-btn":
            self._handle_open()
        elif button_id == "fetch-freedos-btn":
            self._handle_fetch_freedos()
        elif button_id == "fetch-pcdos71-btn":
            self._handle_fetch_pcdos71()
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
        elif button_id == "browse-grow-target-btn":
            self._handle_browse_button("grow-target-input")
        elif button_id == "grow-add-staging-btn":
            self._handle_grow_add_staging()
        elif button_id == "grow-btn":
            self._handle_grow()
        elif button_id == "grow-help-btn":
            self._handle_grow_help()

    def on_select_changed(self, event: Select.Changed) -> None:
        if len(self.query("#create-path")) == 0:
            return
        if event.select.id == "media-type":
            media_type = MediaType(str(event.value))
            if media_type is MediaType.IMG:
                self.query_one("#img-system-format", Checkbox).value = False
                self.query_one("#boot-mode", Select).value = BootMode.NONE.value
                self.query_one("#disk-controller", Select).value = ""
                self.query_one("#custom-chs", Input).value = ""
                self.query_one("#bios-drive-type", Select).value = _BIOS_CUSTOM_VALUE
                self.query_one("#geometry-source", Select).value = GeometrySource.SIZE.value
            self._sync_create_form_visibility()
            return
        if event.select.id == "disk-controller":
            self._sync_create_form_visibility()
            return
        if event.select.id == "bios-drive-type":
            self._apply_bios_drive_snap()
            self._sync_create_form_visibility()
            return
        if event.select.id == "geometry-source":
            # User picked a different geometry source -- clear the
            # inactive inputs so the state matches what's visible.
            self._apply_geometry_source_snap()
            self._sync_create_form_visibility()
            return
        if event.select.id == "boot-mode":
            self._apply_boot_mode_snap(BootMode(str(event.value)))
            self._sync_create_form_visibility()
            return
        if event.select.id == "freedos-source":
            self._sync_create_form_visibility()
            return
        if event.select.id == "dos-profile":
            self._sync_create_form_visibility()
            return
        if event.select.id == "ibm-dos-version":
            # CRITICAL: snap dependent fields FIRST (boot_assets,
            # disk_controller, disk_format, size_text) so the
            # form reflects the new DOS pick before any later
            # default-size or visibility pass reads stale values.
            # Without this, _resolve_legacy_dos_assets_dir silently
            # falls back to ./dosassets/msdos33/ for every IBM 8088
            # build regardless of the picked DOS version.
            self._apply_ibm_version_snap()
            media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
            if media_type is MediaType.VHD:
                self._apply_ibm_default_size(force=False)
            self._sync_create_form_visibility()
            return
        if event.select.id == "create-format":
            self._apply_format_snap()
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

    def on_tabbed_content_tab_activated(self, event) -> None:
        """Refresh the Grow tab pre-read whenever the user switches to it.

        Re-runs inspect_vhd on the currently selected image so the
        info line always reflects whatever was last picked, even if
        the selection happened on a different tab.
        """
        try:
            active = getattr(event, "tab", None)
            tab_id = getattr(active, "id", None)
            # Textual's tab IDs are prefixed; normalize to suffix.
            if tab_id and tab_id.endswith("tab-grow"):
                self._refresh_grow_target_info()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh the live geometry preview as the user types.

        Only the inputs that feed ``geometry_preview_text`` trigger a
        re-sync; everything else lets the natural event flow run so
        we don't thrash on every keystroke.
        """
        if len(self.query("#create-path")) == 0:
            return
        if event.input.id in ("create-size", "custom-chs"):
            try:
                preview = self.query_one("#geometry-preview", Static)
                preview.update(fl.geometry_preview_text(self._current_form_state()))
            except Exception:
                pass
        elif event.input.id == "grow-target-input":
            try:
                self._refresh_grow_target_info()
            except Exception:
                pass

    def _sync_create_form_visibility(self) -> None:
        if len(self.query("#create-path")) == 0:
            return
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        boot_mode = BootMode(cast(str, self.query_one("#boot-mode", Select).value))
        freedos_source = FreeDOSSource(cast(str, self.query_one("#freedos-source", Select).value))
        img_system_format = self.query_one("#img-system-format", Checkbox).value

        is_vhd = media_type is MediaType.VHD
        boot_controls_active = is_vhd or img_system_format

        show_freedos = boot_controls_active and boot_mode is BootMode.FREEDOS
        show_pcdos71 = boot_controls_active and boot_mode is BootMode.PCDOS71
        dos_boot_modes = {
            BootMode.MSDOS71,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS6,
            BootMode.MSDOS622,
                BootMode.PCDOS3,
            BootMode.PCDOS7,
            BootMode.PCDOS2000,
            BootMode.PCDOS71,
            BootMode.COMPAQ2,
            BootMode.COMPAQ3,
            BootMode.COMPAQ331,
            BootMode.DRDOS6,
            BootMode.DRDOS7,
        }
        show_dos_profile = boot_controls_active and boot_mode in dos_boot_modes
        show_ibm_dos_version = boot_controls_active and boot_mode is BootMode.IBM8088
        show_boot_assets = (
            show_dos_profile
            or (show_freedos and freedos_source is FreeDOSSource.LOCAL)
        )
        show_freedos_url = show_freedos and freedos_source is FreeDOSSource.AUTO

        bios_drive_slug = cast(str, self.query_one("#bios-drive-type", Select).value)
        geometry_source_value = cast(str, self.query_one("#geometry-source", Select).value)
        try:
            geometry_source = GeometrySource(geometry_source_value)
        except ValueError:
            geometry_source = GeometrySource.SIZE

        self.query_one("#create-title", Label).update("Create fixed-size VHD" if is_vhd else "Create floppy IMG")
        self.query_one("#create-path", Input).placeholder = (
            "Path (for example: ~/vhd/disk.vhd)" if is_vhd else "Path (for example: ~/floppy/disk.img)"
        )
        self.query_one("#create-btn", Button).label = "Create + format VHD" if is_vhd else "Create + format IMG"

        # Geometry-source picker: each value surfaces only one of the
        # three inputs (static size / BIOS preset / custom CHS).  When
        # BIOS preset is active, mirror the preset's MB into the size
        # Input as a hidden audit trail (the size Input is hidden in
        # this branch but ``effective_size_text()`` /
        # ``build_create_request()`` still read the geometry-source
        # aware code).
        size_input = self.query_one("#create-size", Input)
        if is_vhd and geometry_source is GeometrySource.PRESET and bios_drive_slug:
            try:
                vendor, type_id = parse_bios_drive_slug(bios_drive_slug)
                spec = lookup_bios_drive_type(vendor, type_id)
            except (ValueError, KeyError):
                spec = None
            if spec is not None:
                size_input.value = f"{spec.size_mb}M"
        size_input.disabled = False  # legacy disabled-state retired in v0.8.0

        # Pair each widget with its Label so the label hides too when the
        # widget hides. Otherwise you get orphan labels like "Floppy size"
        # with no select beneath them.
        def _toggle(widget_id: str, label_id: str | None, visible: bool) -> None:
            try:
                self.query_one(f"#{widget_id}").display = visible
            except Exception:
                pass
            if label_id is not None:
                try:
                    self.query_one(f"#{label_id}").display = visible
                except Exception:
                    pass

        _toggle("create-format", "create-format-label", is_vhd)
        _toggle("disk-controller", "disk-controller-label", is_vhd)
        _toggle("geometry-source", "geometry-source-label", is_vhd)
        # Conditional geometry inputs -- only one is visible at a time,
        # driven by the geometry-source Select.
        show_size_input = is_vhd and geometry_source is GeometrySource.SIZE
        show_bios_preset = is_vhd and geometry_source is GeometrySource.PRESET
        show_custom_chs = is_vhd and geometry_source is GeometrySource.CUSTOM_CHS
        _toggle("create-size", "create-size-label", show_size_input)
        _toggle("bios-drive-type", "bios-drive-type-label", show_bios_preset)
        _toggle("custom-chs", "custom-chs-label", show_custom_chs)
        # Live geometry preview (always visible in VHD mode, even when
        # the input is empty -- empty preview just renders as blank).
        try:
            preview = self.query_one("#geometry-preview", Static)
            preview.display = is_vhd
            preview.update(fl.geometry_preview_text(self._current_form_state()))
        except Exception:
            pass
        _toggle("floppy-type", "floppy-type-label", not is_vhd)
        self.query_one("#img-system-format", Checkbox).display = not is_vhd
        _toggle("boot-mode", "boot-mode-label", boot_controls_active)
        _toggle("freedos-source", "freedos-source-label", show_freedos)
        self.query_one("#fetch-freedos-btn", Button).display = show_freedos
        self.query_one("#fetch-pcdos71-btn", Button).display = show_pcdos71
        _toggle("dos-profile", "dos-profile-label", show_dos_profile)
        _toggle("ibm-dos-version", "ibm-dos-version-label", show_ibm_dos_version)
        self.query_one("#boot-assets-row", Horizontal).display = show_boot_assets
        try:
            self.query_one("#boot-assets-label").display = show_boot_assets
        except Exception:
            pass
        # Custom payload doesn't work with fixed-geometry MartyPC targets.
        custom_payload_visible = is_vhd or img_system_format
        self.query_one("#custom-payload-row", Horizontal).display = custom_payload_visible
        try:
            self.query_one("#custom-payload-label").display = custom_payload_visible
        except Exception:
            pass
        _toggle("freedos-url", "freedos-url-label", show_freedos_url)
        # Refresh the wizard's live summary card whenever form state moves.
        self._refresh_summary()

    # ── Wizard state machine ───────────────────────────────────────

    _STEP_LABELS: tuple[str, ...] = ("Boot", "Media", "Payload", "Confirm")

    def _set_wizard_step(self, step: int) -> None:
        """Show wizard step ``step`` and hide the others. Step is 1..4.

        Per-widget ``.display`` flags inside each step continue to be
        controlled by ``_sync_create_form_visibility``; this method only
        flips the step containers and updates the progress + nav button
        labels. Tests query per-widget ``.display`` so they pass even
        when an ancestor step container is hidden.
        """
        self._wizard_step = max(1, min(4, step))
        for index in range(1, 5):
            try:
                container = self.query_one(f"#step-{index}", Container)
            except Exception:
                continue
            container.display = index == self._wizard_step

        # Progress indicator (ASCII markers — guaranteed to render
        # regardless of console font; some Windows fonts lack ●○✓).
        parts: list[str] = []
        for index, label in enumerate(self._STEP_LABELS, start=1):
            if index < self._wizard_step:
                marker = "[x]"
            elif index == self._wizard_step:
                marker = "[>]"
            else:
                marker = "[ ]"
            parts.append(f"{marker} {index}. {label}")
        try:
            self.query_one("#wizard-progress", Static).update("    ".join(parts))
        except Exception:
            pass

        # Nav button labels
        try:
            back = self.query_one("#wizard-back-btn", Button)
            nxt = self.query_one("#wizard-next-btn", Button)
            back.display = self._wizard_step > 1
            if self._wizard_step >= 4:
                nxt.display = False
            else:
                nxt.display = True
                next_label = self._STEP_LABELS[self._wizard_step]
                nxt.label = f"Next: {next_label} >"
        except Exception:
            pass

    def _handle_wizard_back(self) -> None:
        self._clear_status()
        self._set_wizard_step(self._wizard_step - 1)

    def _handle_wizard_next(self) -> None:
        if self._wizard_step >= 4:
            self._handle_create()
            return
        if self._wizard_step == 2:
            error = fl.validate_media_step(self._current_form_state())
            if error:
                self._set_status(error, error=True)
                return
        self._clear_status()
        self._set_wizard_step(self._wizard_step + 1)

    def _handle_quick_create(self) -> None:
        """Skip the wizard and submit with current values."""
        self._set_wizard_step(4)
        self._handle_create()

    def _refresh_summary(self) -> None:
        """Rebuild the live summary card from current form values."""
        if len(self.query("#wizard-summary")) == 0:
            return
        try:
            media = MediaType(cast(str, self.query_one("#media-type", Select).value))
            controller = cast(str, self.query_one("#disk-controller", Select).value) or "auto"
            boot = BootMode(cast(str, self.query_one("#boot-mode", Select).value))
            profile = MSDOSInstallProfile(
                cast(str, self.query_one("#dos-profile", Select).value)
            )
            path = self.query_one("#create-path", Input).value.strip() or "(not set)"
            size = self.query_one("#create-size", Input).value.strip() or "(default)"
            fmt = cast(str, self.query_one("#create-format", Select).value)
            floppy = cast(str, self.query_one("#floppy-type", Select).value)
            img_sysfmt = self.query_one("#img-system-format", Checkbox).value
            boot_assets = self.query_one("#boot-assets", Input).value.strip() or "(auto)"
            custom_payload = (
                self.query_one("#custom-payload", Input).value.strip() or "(none)"
            )
            label_text = self.query_one("#volume-label", Input).value.strip() or "(default)"
            overwrite = self.query_one("#overwrite", Checkbox).value
        except Exception:
            return

        media_line = (
            f"VHD  size={size}  fs={fmt}" if media is MediaType.VHD
            else f"IMG floppy={floppy}  bootable={'yes' if img_sysfmt else 'no'}"
        )
        boot_line = boot.value if boot is not BootMode.NONE else "(none)"
        if boot is not BootMode.NONE and media is MediaType.VHD:
            boot_line += f"  profile={profile.value}"

        summary_lines = [
            f"[b]Output[/b]    {path}",
            f"[b]Media[/b]     {media_line}",
            f"[b]Controller[/b] {controller}",
            f"[b]Boot[/b]      {boot_line}",
            f"[b]Assets[/b]    {boot_assets}",
            f"[b]Payload[/b]   {custom_payload}",
            f"[b]Label[/b]     {label_text}",
            f"[b]Overwrite[/b] {'yes' if overwrite else 'no'}",
        ]
        self.query_one("#wizard-summary", Static).update("\n".join(summary_lines))

    def _switch_to_tab(self, tab_id: str) -> None:
        try:
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

    def _handle_create(self) -> None:
        try:
            request = self._request_from_form()
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return

        # Disable the button so the user can't double-fire while the
        # worker is in flight, and show an immediate visual indicator
        # that the long-running create+format pipeline has started.
        btn = self.query_one("#create-btn", Button)
        btn.disabled = True
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        kind = "VHD" if media_type is MediaType.VHD else "IMG"
        # Surface a known-slow-build warning (FreeDOS' 1388-file FDOS
        # tree dominates wall-clock on Windows) so the user knows the
        # spinner is going to be on-screen for several minutes vs. the
        # usual 30-90 s. Reuses the GUI/CLI's shared formlogic helper
        # so the message stays in sync across surfaces.
        from .formlogic import build_time_hint_for_boot_mode
        slow_hint = build_time_hint_for_boot_mode(request.boot_mode)
        spinner_msg = (
            f"Creating + formatting {kind} {request.path.name}… "
            f"(this can take a minute or two for VHDs with a boot install)"
        )
        if slow_hint:
            spinner_msg = (
                f"Creating + formatting {kind} {request.path.name}… "
                "(FreeDOS: ~3-5 minutes on Windows, see status log)"
            )
            # Also print the full hint once via the status bar so the
            # user can scroll the explanation; the spinner itself stays
            # compact for the elapsed-time readout.
            print(f"  [build] {slow_hint}", flush=True)
        self._start_spinner(spinner_msg)
        # Kick the actual blocking work onto a thread worker so the UI
        # event loop keeps spinning and the spinner animates instead of
        # the whole TUI freezing while qemu-img/parted/mkfs.fat/qemu run.
        self._create_worker(request)

    @work(thread=True, exclusive=True, group="create")
    def _create_worker(self, request: CreateRequest) -> None:
        try:
            success = self._run_with_sudo_reauth(
                lambda: self.manager.create_and_prepare(request)
            )
        except Exception as exc:  # noqa: BLE001 — surface any backend crash
            self.call_from_thread(self._on_create_done, request, False, exc)
            return
        self.call_from_thread(self._on_create_done, request, success, None)

    def _on_create_done(
        self,
        request: CreateRequest,
        success: bool,
        error: Exception | None,
    ) -> None:
        elapsed = time.monotonic() - self._spinner_started_at
        self._stop_spinner()
        try:
            self.query_one("#create-btn", Button).disabled = False
        except Exception:
            pass
        if error is not None:
            self._set_status(f"Create failed after {elapsed:0.1f}s: {error}", error=True)
            return
        if not success:
            # `_run_with_sudo_reauth` already wrote a descriptive error
            # status before returning False; don't clobber it.
            return
        self._set_status(
            f"✓ Created and prepared in {elapsed:0.1f}s: {request.path}"
        )
        self.selected_image = request.path.expanduser().resolve()
        self.query_one("#selected-vhd", Static).update(
            f"Selected image: {self.selected_image}"
        )
        self._update_context_bar()
        self._refresh_browser_tree()
        self._refresh_mounts()

    def _start_spinner(self, message: str) -> None:
        """Kick off the animated spinner in the bottom status bar.

        Safe to call from the UI thread; uses ``set_interval`` to tick
        the spinner frame ~10 times per second.  Callers that launch a
        background worker should call :meth:`_stop_spinner` (via
        ``call_from_thread`` if needed) when the worker completes.
        """
        self._stop_spinner()
        self._spinner_message = message
        self._spinner_started_at = time.monotonic()
        # Reset the frame iterator so each new operation starts at the
        # same visual frame for consistency.
        self._spinner_frames = cycle(_SPINNER_FRAMES)
        first = next(self._spinner_frames)
        self._set_status(f"{first} {message}")
        try:
            self._spinner_timer = self.set_interval(0.1, self._tick_spinner)
        except Exception:
            # In unit-test / no-loop environments set_interval can fail;
            # the static status line is still informative even without
            # the animation.
            self._spinner_timer = None

    def _tick_spinner(self) -> None:
        if not self._spinner_message:
            return
        try:
            frame = next(self._spinner_frames)
            elapsed = time.monotonic() - self._spinner_started_at
            self.query_one("#status-current", Static).update(
                f"{frame} {self._spinner_message}  [{elapsed:0.1f}s]"
            )
        except Exception:
            pass

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None
        self._spinner_message = ""
        try:
            self.query_one("#status-current", Static).update("")
        except Exception:
            pass

    def _update_context_bar(self) -> None:
        """Update the always-visible context strip above the tabs."""
        try:
            bar = self.query_one("#context-bar", Static)
        except Exception:
            return
        parts: list[str] = []
        if self.selected_image is not None:
            parts.append(f"image: {self.selected_image}")
        else:
            parts.append("image: (none selected)")
        try:
            boot = cast(str, self.query_one("#boot-mode", Select).value)
            media = cast(str, self.query_one("#media-type", Select).value)
            parts.append(f"media={media}")
            if boot and boot != BootMode.NONE.value:
                parts.append(f"boot={boot}")
        except Exception:
            pass
        bar.update("    ".join(parts))

    def _handle_mount_selected(self) -> None:
        if self.selected_image is None:
            path_text = self.query_one("#create-path", Input).value.strip()
            if path_text:
                self.selected_image = Path(path_text).expanduser().resolve()
        if self.selected_image is None:
            self._set_status("Select a .vhd/.img/.ima file first.", error=True)
            return

        self._set_status(f"Mounting {self.selected_image.name}…")
        mounted_records: list[object] = []
        if not self._run_with_sudo_reauth(lambda: mounted_records.append(self.manager.mount_vhd(self.selected_image))):
            return
        if not mounted_records:
            self._set_status("Mount operation did not return a record.", error=True)
            return
        record = mounted_records[0]
        try:
            self.manager.open_in_files(record.mount_point)
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return

        mountpoint_text = str(record.mount_point)
        self.query_one("#unmount-input", Input).value = mountpoint_text
        self.query_one("#open-input", Input).value = mountpoint_text
        self._refresh_mounts()
        self._set_status(f"✓ Mounted {record.vhd_path} to {record.mount_point} and opened in Files.")

    def _handle_unmount(self) -> None:
        mountpoint_text = self.query_one("#unmount-input", Input).value.strip()
        if not mountpoint_text:
            self._set_status("Enter a mounted path to unmount.", error=True)
            return

        self._set_status(f"Unmounting {mountpoint_text}…")
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
        self._set_status(f"✓ Unmounted {record.mount_point} and disconnected {record.nbd_device}.")

    def _handle_open(self) -> None:
        path_text = self.query_one("#open-input", Input).value.strip()
        if not path_text:
            self._set_status("Enter a path to open in the file manager.", error=True)
            return
        self._set_status(f"Opening {path_text} in file manager…")
        try:
            self.manager.open_in_files(Path(path_text))
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f"✓ Opened in Files: {path_text}")

    def _handle_image_ls(self) -> None:
        """List the root directory of the currently selected image via mtools.

        Cross-platform alternative to `mount`+browse — works against any
        VHD/IMG/IMA/VFD without needing kernel-mount or admin. Output is
        dumped into the status pane.
        """

        image = self._selected_image_for_image_ops()
        if image is None:
            return
        self._set_status(f"Reading directory listing from {image.name}…")
        from . import image_ops

        try:
            listing = image_ops.ls(image, "/", all_files=True)
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return
        if not listing:
            self._set_status(f"{image.name}: (empty)")
            return
        self._set_status(f"Contents of {image.name}:\n{listing}")

    def _handle_image_extract(self) -> None:
        """Extract a file from the selected image to the user's chosen path.

        Reads the DOS path from #extract-input and writes the file next
        to the image (or asks via the file picker if no path was given).
        Cross-platform via mtools.
        """

        image = self._selected_image_for_image_ops()
        if image is None:
            return
        dos_path = self.query_one("#extract-input", Input).value.strip()
        if not dos_path:
            self._set_status(
                "Enter a DOS path to extract (e.g. /CONFIG.SYS) in the box "
                "next to the Extract button.",
                error=True,
            )
            return

        self._set_status(f"Extracting {image.name}:{dos_path}…")
        from . import image_ops

        # Default destination: image directory, DOS basename.
        basename = dos_path.replace("\\", "/").rstrip("/").split("/")[-1] or "FILE"
        local_dest = image.parent / basename
        try:
            written = image_ops.get(image, dos_path, local_dest)
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f"✓ Extracted {image.name}:{dos_path} -> {written}")

    def _selected_image_for_image_ops(self) -> Path | None:
        """Resolve the image targeted by `ls` / `extract` from the form state.

        Priority: the currently selected image (from the directory tree),
        then the value of the create-path input box. Returns None and
        sets an error status if neither is usable.
        """

        if self.selected_image is not None:
            return self.selected_image
        path_text = self.query_one("#create-path", Input).value.strip()
        if path_text:
            candidate = Path(path_text).expanduser().resolve()
            if candidate.is_file():
                return candidate
        self._set_status(
            "Select a .vhd / .img / .ima / .vfd file in the tree first.",
            error=True,
        )
        return None

    def _handle_image_inspect(self) -> None:
        """Inspect the currently selected VHD via dosforge.inspect.

        Outputs the same MBR + BPB + root-system-files summary the
        ``dosforge inspect`` CLI prints (human-readable mode).  No
        worker thread needed -- inspect is pure-Python with one
        cheap ``mdir`` per known root system filename.
        """

        image = self._selected_image_for_image_ops()
        if image is None:
            return
        from .inspect import inspect_vhd

        self._set_status(f"Inspecting {image.name}…")
        try:
            info = inspect_vhd(image)
        except DosForgeError as exc:
            self._set_status(str(exc), error=True)
            return

        lines: list[str] = []
        lines.append(f"VHD: {info.path}")
        lines.append(f"  File size       : {info.file_size_bytes:,} bytes")
        lines.append(
            f"  Format          : {'Fixed VHD (conectix)' if info.is_fixed_vhd else 'Raw / unknown'}"
        )
        if info.footer_chs:
            c, h, s = info.footer_chs
            lines.append(
                f"  Footer CHS      : {c} cyl x {h} heads x {s} spt ({c*h*s:,} sectors)"
            )
        lines.append("")
        lines.append(
            f"  Partition       : type=0x{info.mbr_partition_type:02X}  "
            f"LBA={info.partition_lba_start}-{info.partition_lba_start + info.partition_sector_count - 1}"
        )
        lines.append(f"  BPB OEM         : {info.bpb_oem!r}")
        lines.append(f"  FAT format      : {info.fat_format.value}")
        lines.append(
            f"  Cluster size    : {info.cluster_size_bytes:,} bytes "
            f"({info.bytes_per_sector} bytes/sector x {info.sectors_per_cluster} sectors/cluster)"
        )
        lines.append(f"  Cluster count   : {info.cluster_count:,}")
        if info.volume_label:
            lines.append(f"  Volume label    : {info.volume_label}")
        if info.volume_serial_hex:
            lines.append(
                f"  Volume serial   : {info.volume_serial_hex[:4]}-{info.volume_serial_hex[4:]}"
            )
        lines.append("")
        if info.inferred_boot_mode:
            lines.append(f"  Inferred boot mode: {info.inferred_boot_mode.value}")
        else:
            lines.append("  Inferred boot mode: (unknown -- OEM stamp not in table)")
        if info.root_system_files:
            lines.append(f"  Root system files: {', '.join(info.root_system_files)}")
        else:
            lines.append("  Root system files: (none detected)")
        self._set_status("\n".join(lines))

    def _handle_grow_add_staging(self) -> None:
        """Add one staging entry from the SRC=DEST input box.

        Stores entries in self._grow_staging (a list[tuple[Path, str]])
        and re-renders #grow-staging-list as a multi-line summary.
        """

        raw = self.query_one("#grow-staging-input", Input).value.strip()
        if "=" not in raw:
            self._set_status(
                "Staging entry must be in the form SRC_DIR=C:\\DOS_PATH "
                "(e.g. /tmp/games=C:\\GAMES).",
                error=True,
            )
            return
        src_str, dest_str = raw.split("=", 1)
        src_str = src_str.strip()
        dest_str = dest_str.strip()
        src = Path(src_str).expanduser().resolve()
        if not src.exists() or not src.is_dir():
            self._set_status(
                f"Staging source must be an existing directory: {src}",
                error=True,
            )
            return
        if not hasattr(self, "_grow_staging") or self._grow_staging is None:
            self._grow_staging = []
        self._grow_staging.append((src, dest_str))
        self.query_one("#grow-staging-input", Input).value = ""
        lines = [f"{src}  ->  {dest}" for src, dest in self._grow_staging]
        self.query_one("#grow-staging-list", Static).update(
            "\n".join(lines) if lines else "(no staging sources)"
        )
        self._set_status(f"Staged {src} -> {dest_str}.")

    def _handle_grow_help(self) -> None:
        """Open the Grow VHD reference modal (supported modes + hard limits)."""
        self.push_screen(_GrowHelpScreen())

    def _refresh_grow_target_info(self) -> None:
        """Pre-read the selected VHD and update #grow-target-info.

        Updates the static info line above the Grow form with the
        source VHD's size, FAT format, cluster size, inferred boot
        mode, and a Growable / Not-growable verdict.  Silent no-op
        when no image is selected or it can't be parsed (e.g. the
        user pasted a path that isn't a VHD yet).
        """
        from .grow import GROWABLE_BOOT_MODES
        from .inspect import inspect_vhd

        try:
            info_widget = self.query_one("#grow-target-info", Static)
        except Exception:
            return

        image = self.selected_image
        target_str: str | None = None
        if image is not None:
            target_str = str(image)
        else:
            try:
                raw = self.query_one("#grow-target-input", Input).value.strip()
                if raw:
                    target_str = raw
            except Exception:
                pass

        if not target_str:
            info_widget.update("Target VHD: (select via Browse tab first)")
            return

        target = Path(target_str).expanduser()
        if not target.exists():
            info_widget.update(
                f"Target VHD: {target}  (file not found — pick another)"
            )
            return

        try:
            info = inspect_vhd(target)
        except (DosForgeError, OSError) as exc:
            info_widget.update(
                f"Target VHD: {target.name}  (cannot inspect: {exc})"
            )
            return

        size_mib = info.file_size_bytes / (1024 * 1024)
        inferred = (
            info.inferred_boot_mode.value
            if info.inferred_boot_mode
            else "unknown (auto-detect at grow time)"
        )
        if info.inferred_boot_mode and info.inferred_boot_mode in GROWABLE_BOOT_MODES:
            verdict = "✓ Growable"
        elif info.inferred_boot_mode:
            verdict = "✗ Not growable — rebuild via 'dosforge create' (press ? for details)"
        else:
            verdict = "? Verdict unknown — boot mode auto-detect runs at grow time"

        info_widget.update(
            f"Target VHD: {target.name}\n"
            f"  Current: {size_mib:.0f} MiB  •  {info.fat_format.value}  •  "
            f"cluster {info.cluster_size_bytes:,} bytes  •  inferred boot: {inferred}\n"
            f"  {verdict}"
        )

    def _handle_grow(self) -> None:
        """Build a GrowManifest from the Grow tab form and run grow_vhd.

        The grow can take 10-30 seconds (extract + dosforge create +
        re-inject + optional boot probe), so we run it on a worker
        thread to keep the TUI responsive.
        """

        from .grow import GrowManifest, StagingSource, grow_vhd
        from .size import parse_size

        target_str = self.query_one("#grow-target-input", Input).value.strip()
        if not target_str and self.selected_image is not None:
            target_str = str(self.selected_image)
        if not target_str:
            self._set_status(
                "Pick a target VHD (Browse tab) or paste its path into the "
                "Grow Disk form first.",
                error=True,
            )
            return

        size_str = self.query_one("#grow-new-size-input", Input).value.strip()
        if not size_str:
            self._set_status(
                "Enter a new size (e.g. 128M, 256M, 1G).", error=True
            )
            return
        try:
            new_size_bytes = parse_size(size_str)
        except ValidationError as exc:
            self._set_status(str(exc), error=True)
            return

        boot_select = None
        boot_mode = None

        staging_pairs: list[tuple[Path, str]] = list(
            getattr(self, "_grow_staging", []) or []
        )
        boot_probe = self.query_one("#grow-boot-probe-check", Checkbox).value
        keep_backup = self.query_one("#grow-keep-backup-check", Checkbox).value

        manifest = GrowManifest(
            target_vhd=Path(target_str).expanduser().resolve(),
            new_size_bytes=new_size_bytes,
            boot_mode=boot_mode,
            staging_sources=tuple(
                StagingSource(src=src, dest=dest) for src, dest in staging_pairs
            ),
            boot_probe=boot_probe,
            keep_backup=keep_backup,
        )

        try:
            btn = self.query_one("#grow-btn", Button)
            btn.disabled = True
        except Exception:
            pass
        probe_hint = (
            " + ~60-90s headless boot probe"
            if manifest.boot_probe
            else " (boot probe disabled)"
        )
        self._start_spinner(
            f"Grow {manifest.target_vhd.name} -> {manifest.new_size_bytes:,} "
            f"bytes (extract + rebuild + reinject{probe_hint})..."
        )
        self._grow_worker(manifest)

    @work(thread=True, exclusive=True, group="grow")
    def _grow_worker(self, manifest) -> None:
        from .grow import grow_vhd

        def _on_progress(stage: str) -> None:
            # Worker thread: bounce back to the UI thread for the
            # spinner update so Textual's reactive system stays
            # single-threaded (avoid the 'No active app' warnings).
            self.call_from_thread(self._set_spinner_message, stage)

        try:
            grow_vhd(manifest, progress_callback=_on_progress)
            self.call_from_thread(self._on_grow_done, manifest, None)
        except Exception as exc:
            self.call_from_thread(self._on_grow_done, manifest, exc)

    def _set_spinner_message(self, message: str) -> None:
        """Update the active spinner's message in-place.

        Used by the grow worker's progress_callback so the spinner
        narrates which of the 8 grow steps is currently burning
        wall-clock.  Falls back to a no-op if no spinner is running.
        """
        if not self._spinner_message:
            return
        self._spinner_message = message
        # Also push a one-line summary into the persistent log so the
        # user has scrollback of every stage transition.
        self._append_status_log(f"[..] {message}")

    def _on_grow_done(self, manifest, error) -> None:
        self._stop_spinner()
        try:
            btn = self.query_one("#grow-btn", Button)
            btn.disabled = False
        except Exception:
            pass
        if error is not None:
            self._set_status(f"Grow failed: {error}", error=True)
            try:
                self.query_one("#grow-output", Static).update(
                    f"Grow failed (original VHD untouched):\n{error}"
                )
            except Exception:
                pass
            return
        # Clear staging list on success so the user doesn't accidentally
        # re-add the same games to a follow-up grow.
        self._grow_staging = []
        try:
            self.query_one("#grow-staging-list", Static).update("(no staging sources)")
        except Exception:
            pass
        backup_msg = (
            f" Backup at {manifest.target_vhd}.bak."
            if manifest.keep_backup
            else " (no backup kept)"
        )
        self._set_status(
            f"✓ Grew {manifest.target_vhd} to {manifest.new_size_bytes:,} bytes.{backup_msg}"
        )
        try:
            self.query_one("#grow-output", Static).update(
                f"Grew {manifest.target_vhd} to "
                f"{manifest.new_size_bytes:,} bytes.{backup_msg}"
            )
        except Exception:
            pass

    def _handle_fetch_freedos(self) -> None:
        """Kick off FreeDOS download on a worker thread + spin until done.

        The download is ~5-15 MB and takes 5-30 s depending on
        bandwidth; running it on the UI thread would freeze the TUI.
        ``_fetch_freedos_worker`` runs in the background and reports
        completion via :meth:`_on_fetch_freedos_done`.
        """
        url_text = self.query_one("#freedos-url", Input).value.strip()
        try:
            btn = self.query_one("#fetch-freedos-btn", Button)
            btn.disabled = True
        except Exception:
            pass
        self._start_spinner(
            f"Downloading FreeDOS assets (this can take 5-30 s)…"
            + (f" from {url_text}" if url_text else "")
        )
        self._fetch_freedos_worker(url_text or None)

    @work(thread=True, exclusive=True, group="fetch-freedos")
    def _fetch_freedos_worker(self, download_url: str | None) -> None:
        try:
            target = self.manager.fetch_freedos_assets(download_url=download_url)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._on_fetch_freedos_done, None, exc)
            return
        self.call_from_thread(self._on_fetch_freedos_done, target, None)

    def _on_fetch_freedos_done(self, target: Path | None, error: Exception | None) -> None:
        elapsed = time.monotonic() - self._spinner_started_at
        self._stop_spinner()
        try:
            self.query_one("#fetch-freedos-btn", Button).disabled = False
        except Exception:
            pass
        if error is not None:
            self._set_status(
                f"FreeDOS fetch failed after {elapsed:0.1f}s: {error}",
                error=True,
            )
            return
        if target is None:
            self._set_status("FreeDOS fetch produced no target path.", error=True)
            return
        self.query_one("#boot-assets", Input).value = str(target)
        self.query_one("#freedos-source", Select).value = FreeDOSSource.LOCAL.value
        self._set_status(
            f"✓ Downloaded and extracted FreeDOS assets to {target} in {elapsed:0.1f}s"
        )

    def _handle_fetch_pcdos71(self) -> None:
        """Download + verify + stage IBM PC-DOS 7.1 assets from the SGTK.

        Synchronous (matches the FreeDOS button's UX). ~15 MB download
        + ~30 s 7-Zip extract on the first run; cached subsequent
        invocations finish in a couple seconds. Status bar updates at
        every documented stage in :data:`PROGRESS_STAGES` via the
        library's progress callback.
        """
        from .pcdos71_fetch import fetch_pcdos71_assets

        # Stage labels mirror PROGRESS_STAGES in pcdos71_fetch.
        # The worker calls back via _on_fetch_pcdos71_progress so
        # status updates land on the UI thread.
        _ = fetch_pcdos71_assets  # keep the import live (worker imports below)
        try:
            btn = self.query_one("#fetch-pcdos71-btn", Button)
            btn.disabled = True
        except Exception:
            pass
        self._start_spinner("PC-DOS 7.1 fetch: starting…")
        self._fetch_pcdos71_worker()

    _PCDOS71_STAGE_LABELS = {
        "preflight": "Checking dependencies…",
        "locating_sevenzip": "Locating 7-Zip…",
        "downloading_sgtk": "Downloading IBM SGTK from archive.org…",
        "extracting_sgtk": "Extracting SGTK with 7-Zip…",
        "locating_dos_files": "Locating PC-DOS 7.1 system files in extract…",
        "staging_files": "Verifying SHA-256s and staging files…",
        "hydrating_pcdos2000": "Hydrating C:\\DOS\\ with PC-DOS 2000 utilities…",
        "done": "Done.",
    }

    @work(thread=True, exclusive=True, group="fetch-pcdos71")
    def _fetch_pcdos71_worker(self) -> None:
        from .pcdos71_fetch import fetch_pcdos71_assets

        def _progress(line: str) -> None:
            # Marshal stage updates onto the UI thread; ignore
            # free-form download/extraction chatter to avoid spam.
            label = self._PCDOS71_STAGE_LABELS.get(line)
            if label:
                self.call_from_thread(
                    self._on_fetch_pcdos71_progress, label
                )

        try:
            result = fetch_pcdos71_assets(progress=_progress)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._on_fetch_pcdos71_done, None, exc)
            return
        self.call_from_thread(self._on_fetch_pcdos71_done, result, None)

    def _on_fetch_pcdos71_progress(self, label: str) -> None:
        # Update the spinner message so the elapsed-time counter
        # keeps incrementing while the stage label changes.
        self._spinner_message = f"PC-DOS 7.1 fetch: {label}"

    def _on_fetch_pcdos71_done(self, result, error: Exception | None) -> None:
        elapsed = time.monotonic() - self._spinner_started_at
        self._stop_spinner()
        try:
            self.query_one("#fetch-pcdos71-btn", Button).disabled = False
        except Exception:
            pass
        if error is not None:
            self._set_status(
                f"PC-DOS 7.1 fetch failed after {elapsed:0.1f}s: {error}",
                error=True,
            )
            return

        if result.vfd_filename is None:
            self._set_status(
                f"PC-DOS 7.1 fetch staged {result.staged_count}/{result.total_count} "
                f"DOS files at {result.target_dir}, but the SGTK didn't ship a "
                "bootable VFD — pcdos71_profile won't accept this directory "
                "until you produce one (see scripts/fetch-pcdos71-assets.py "
                "output for guidance).",
                error=True,
            )
            return

        self.query_one("#boot-assets", Input).value = str(result.target_dir)
        extra = ""
        if result.pcdos2000_archive and result.pcdos2000_added > 0:
            extra = (
                f", plus {result.pcdos2000_added} extra utilities from "
                f"{result.pcdos2000_archive} ({result.pcdos2000_skipped} kept SGTK)"
            )
        elif result.pcdos2000_error:
            extra = f"; PC-DOS 2000 hydration skipped: {result.pcdos2000_error}"
        self._set_status(
            f"✓ PC-DOS 7.1 assets ready in {elapsed:0.1f}s at {result.target_dir} "
            f"({result.staged_count}/{result.total_count} DOS files + "
            f"{result.vfd_filename}){extra}."
        )

    def _handle_privilege_diagnostics(self) -> None:
        self._set_status("Running privilege diagnostics…")
        ok, summary = self.manager.privilege_diagnostics_summary()
        label = "[OK]" if ok else "[ERROR]"
        self._append_status_log(f"{label} {summary}")

    def _request_from_form(self) -> CreateRequest:
        return fl.build_create_request(self._current_form_state())

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
        # On backends that don't require sudo (Windows), call the
        # operation directly — there's no privilege-escalation step
        # to wrap, and the sudo password dialog should never appear.
        if not self.manager.backend.requires_sudo_for_disk_ops:
            try:
                operation()
                return True
            except DosForgeError as exc:
                self._set_status(str(exc), error=True)
                return False

        try:
            operation()
            return True
        except DosForgeError as exc:
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
            except DosForgeError as retry_exc:
                self._set_status(str(retry_exc), error=True)
                return False

    def _is_sudo_auth_error(self, exc: DosForgeError) -> bool:
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
            "--title=DosForge sudo authentication",
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
        # Native picker unavailable or user cancelled. Set the picker
        # target so a later DirectoryTree selection routes back here,
        # then show a NON-INTRUSIVE notification + status hint. Don't
        # auto-switch tabs — that's jarring ("flashes") and loses the
        # user's place in the wizard.
        self._start_path_picker(target)
        try:
            self.notify(
                "Native file picker unavailable. Switch to the Browse "
                "tab (Ctrl+2) and select a path from the tree to fill "
                "this field.",
                title="Picker unavailable",
                severity="warning",
                timeout=6,
            )
        except Exception:
            pass
        self._set_status(
            "Picker unavailable — open the Browse tab (Ctrl+2), pick a "
            "file/folder, then return to the wizard."
        )

    def _start_path_picker(self, target: str) -> None:
        self.path_picker_target = target
        self._set_status(
            "Select a file or folder from the Browse tab tree to populate this field."
        )

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
        elif target == "grow-target-input":
            mode = "file"
            title = "Select target VHD to grow"
        elif target == "open-input":
            mode = "file_or_directory"
            title = "Select image or mount path"
        else:
            mode = "file_or_directory"
            title = "Select path"

        start_path = self._path_picker_start_path(target)
        # Windows: native Win32 file dialogs via tkinter.filedialog
        # (bundled with CPython; no extra runtime deps). Linux: zenity.
        if sys.platform == "win32":
            chosen = self._run_tkinter_picker(mode=mode, title=title, start_path=start_path)
        else:
            chosen = self._run_zenity_picker(mode=mode, title=title, start_path=start_path)
        if chosen is None:
            return None
        return Path(chosen).expanduser().resolve()

    def _run_tkinter_picker(self, *, mode: str, title: str, start_path: Path) -> str | None:
        """Native Win32 file-dialog picker via tkinter.filedialog.

        Runs in a worker thread because Textual's event loop owns the
        main thread, and tkinter's mainloop wants the main thread —
        but for a one-shot dialog we don't enter mainloop, we just
        create a hidden root, call the dialog directly, then destroy it.
        Returns the selected path string, or None if cancelled.
        """

        try:
            import tkinter
            from tkinter import filedialog
        except ImportError:
            return None

        start_dir = str(start_path.expanduser().resolve())
        initial_dir = start_dir if Path(start_dir).is_dir() else str(Path(start_dir).parent)
        initial_file = "" if Path(start_dir).is_dir() else Path(start_dir).name

        # Hidden root window so the dialog has a parent but no extra UI shows.
        root = tkinter.Tk()
        root.withdraw()
        # Bring dialog to the foreground above the terminal.
        root.attributes("-topmost", True)
        try:
            picker_mode = mode
            if picker_mode == "file_or_directory":
                # Native Win32 has no combined picker; default to "open file"
                # since most uses (boot assets) typically pick a file. The
                # in-app tree remains available for picking directories.
                picker_mode = "file"

            if picker_mode == "directory":
                result = filedialog.askdirectory(
                    parent=root, title=title, initialdir=initial_dir, mustexist=True
                )
            elif picker_mode == "save":
                result = filedialog.asksaveasfilename(
                    parent=root,
                    title=title,
                    initialdir=initial_dir,
                    initialfile=initial_file,
                    defaultextension=".vhd",
                    filetypes=[
                        ("VHD images", "*.vhd"),
                        ("Floppy images", "*.img *.ima *.vfd"),
                        ("All files", "*.*"),
                    ],
                )
            else:
                result = filedialog.askopenfilename(
                    parent=root,
                    title=title,
                    initialdir=initial_dir,
                    initialfile=initial_file,
                    filetypes=[
                        ("Disk images", "*.vhd *.img *.ima *.vfd"),
                        ("All files", "*.*"),
                    ],
                )
        finally:
            root.destroy()
        if not result:
            return None
        return str(result)

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
        elif target == "grow-target-input":
            value = self.query_one("#grow-target-input", Input).value.strip()
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
        elif target == "grow-target-input":
            if not selected.is_file():
                self._set_status(
                    "Grow target must be an existing VHD file.",
                    error=True,
                )
                return
            self.query_one("#grow-target-input", Input).value = str(selected)
            self.selected_image = selected
            try:
                self._refresh_grow_target_info()
            except Exception:
                pass
            self._set_status(f"Grow target VHD set: {selected}")
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
        self._append_status_log(f"{label}{message}")

    def _append_status_log(self, message: str) -> None:
        self._status_log_history.append(message)
        if len(self._status_log_history) > 500:
            del self._status_log_history[: len(self._status_log_history) - 500]
        try:
            self.query_one("#status", RichLog).write(message)
        except Exception:
            pass
        try:
            self.query_one("#status-current", Static).update("")
        except Exception:
            pass

    def _clear_status(self) -> None:
        """Clear only the live status row (spinner / current op).

        The persistent log panel (``#status``) intentionally keeps its
        history so the user can scroll back, copy past messages with
        ``Ctrl+Y``, or clear it explicitly with ``Ctrl+Shift+L``.
        """
        try:
            self.query_one("#status-current", Static).update("")
        except Exception:
            pass

    def action_copy_log(self) -> None:
        """Copy the persistent status log to the clipboard.

        Uses Textual's OSC 52 clipboard bridge so it works over SSH
        and inside terminal multiplexers (provided the terminal
        emulator supports OSC 52, which all modern ones do).
        """
        payload = "\n".join(self._status_log_history).rstrip()
        if not payload:
            self._append_status_log("[INFO] Log is empty -- nothing to copy.")
            return
        try:
            self.copy_to_clipboard(payload)
        except Exception:
            self._append_status_log(
                "[ERROR] copy_to_clipboard failed (terminal may not support OSC 52)."
            )
            return
        self._append_status_log(
            f"[OK] Copied {len(self._status_log_history)} log line(s) to clipboard."
        )

    def action_clear_log(self) -> None:
        """Wipe the persistent status log."""
        self._status_log_history.clear()
        try:
            self.query_one("#status", RichLog).clear()
        except Exception:
            pass

    def _apply_ibm_default_size(self, *, force: bool) -> None:
        media_type = MediaType(cast(str, self.query_one("#media-type", Select).value))
        if media_type is not MediaType.VHD:
            return
        size_input = self.query_one("#create-size", Input)
        if force or size_input.value.strip().upper() in {"", "512M"}:
            size_input.value = "32M"

    def _current_form_state(self) -> fl.FormState:
        """Snapshot the create-form widget values into a :class:`FormState`."""
        return fl.FormState(
            media_type=cast(str, self.query_one("#media-type", Select).value),
            disk_controller=cast(str, self.query_one("#disk-controller", Select).value),
            geometry_source=cast(str, self.query_one("#geometry-source", Select).value),
            custom_chs=self.query_one("#custom-chs", Input).value,
            output_path=self.query_one("#create-path", Input).value,
            size_text=self.query_one("#create-size", Input).value,
            bios_drive_type=cast(str, self.query_one("#bios-drive-type", Select).value),
            disk_format=cast(str, self.query_one("#create-format", Select).value),
            floppy_type=cast(str, self.query_one("#floppy-type", Select).value),
            img_system_format=self.query_one("#img-system-format", Checkbox).value,
            boot_mode=cast(str, self.query_one("#boot-mode", Select).value),
            freedos_source=cast(str, self.query_one("#freedos-source", Select).value),
            dos_profile=cast(str, self.query_one("#dos-profile", Select).value),
            ibm_dos_version=cast(str, self.query_one("#ibm-dos-version", Select).value),
            boot_assets=self.query_one("#boot-assets", Input).value,
            custom_payload=self.query_one("#custom-payload", Input).value,
            freedos_url=self.query_one("#freedos-url", Input).value,
            volume_label=self.query_one("#volume-label", Input).value,
            overwrite=self.query_one("#overwrite", Checkbox).value,
        )

    def _apply_boot_mode_snap(self, new_boot_mode: BootMode) -> None:
        """Apply per-boot-mode FS + size defaults when the user picks a boot mode.

        Routes through ``formlogic.coerce_on_boot_change`` so the TUI and
        GUI use the same constraint table (PCDOS71 → FAT32 + 1 GiB
        minimum, IBM8088 → 32 MB cap, etc.).  Only writes back widgets
        whose values actually changed so cursor positions / focus on
        unchanged inputs are preserved.
        """
        state = self._current_form_state()
        state = fl_replace(state, boot_mode=new_boot_mode.value)
        snapped = fl.coerce_on_boot_change(state)
        if snapped.media_type != state.media_type:
            self.query_one("#media-type", Select).value = snapped.media_type
        if snapped.disk_controller != state.disk_controller:
            self.query_one("#disk-controller", Select).value = snapped.disk_controller
        if snapped.disk_format != state.disk_format:
            self.query_one("#create-format", Select).value = snapped.disk_format
        if snapped.size_text != state.size_text:
            self.query_one("#create-size", Input).value = snapped.size_text
        if snapped.bios_drive_type != state.bios_drive_type:
            self.query_one("#bios-drive-type", Select).value = snapped.bios_drive_type
        if snapped.custom_chs != state.custom_chs:
            self.query_one("#custom-chs", Input).value = snapped.custom_chs
        if snapped.geometry_source != state.geometry_source:
            self.query_one("#geometry-source", Select).value = snapped.geometry_source
        if snapped.boot_assets != state.boot_assets:
            self.query_one("#boot-assets", Input).value = snapped.boot_assets
        self._clear_status()

    def _apply_geometry_source_snap(self) -> None:
        """Clear the inactive geometry inputs when the user changes source.

        Mirrors :func:`formlogic.coerce_on_geometry_source_change` so
        only the picked source's field is populated, matching what's
        visible in the wizard.
        """
        state = self._current_form_state()
        snapped = fl.coerce_on_geometry_source_change(state)
        if snapped.bios_drive_type != state.bios_drive_type:
            self.query_one("#bios-drive-type", Select).value = snapped.bios_drive_type
        if snapped.custom_chs != state.custom_chs:
            self.query_one("#custom-chs", Input).value = snapped.custom_chs
        self._clear_status()

    def _apply_bios_drive_snap(self) -> None:
        """Snap dependent fields when the user picks a BIOS preset.

        Mirrors :func:`formlogic.coerce_on_bios_drive_change` -- the
        MartyPC-Xebec family forces FAT12 because Type 1 (10 MiB) is
        below the FAT16 minimum.
        """
        state = self._current_form_state()
        snapped = fl.coerce_on_bios_drive_change(state)
        if snapped.disk_format != state.disk_format:
            self.query_one("#create-format", Select).value = snapped.disk_format
        self._clear_status()

    def _apply_ibm_version_snap(self) -> None:
        """Re-snap dependent fields when the IBM 8088 DOS Version changes.

        Mirrors :func:`formlogic.coerce_on_ibm_version_change` so the
        TUI matches the GUI (which routes through ``self._coerce`` in
        ``create_view.py``).  Without this, the boot-assets Input
        keeps its previous value (e.g. ``msdos33``) when the user
        switches the DOS Version picker to PC-DOS 3 / MS-DOS 5 /
        PC-DOS 5, and ``_resolve_legacy_dos_assets_dir`` silently
        falls back to the wrong asset directory -- the install runs
        with MS-DOS 3.3 P/P media regardless of which DOS was picked,
        producing IO.SYS / MSDOS.SYS instead of IBMBIO / IBMDOS
        (PCDOS3 verify fails) or never matching MSDOS5's longer
        FORMAT prompt sequence (SYS step times out at 300s).
        """
        state = self._current_form_state()
        snapped = fl.coerce_on_ibm_version_change(state)
        if snapped.boot_assets != state.boot_assets:
            self.query_one("#boot-assets", Input).value = snapped.boot_assets
        if snapped.disk_controller != state.disk_controller:
            self.query_one("#disk-controller", Select).value = snapped.disk_controller
        if snapped.disk_format != state.disk_format:
            self.query_one("#create-format", Select).value = snapped.disk_format
        if snapped.size_text != state.size_text:
            self.query_one("#create-size", Input).value = snapped.size_text
        self._clear_status()

    def _apply_format_snap(self) -> None:
        """Re-enforce size floors after a Filesystem-dropdown change.

        Mirrors :func:`formlogic.coerce_on_format_change` — picking
        FAT32 on a PCDOS71 build bumps a too-small size up to 1 GiB,
        the same floor enforced at submit time by
        :meth:`DiskManager._validate_create_request`.
        """
        state = self._current_form_state()
        snapped = fl.coerce_on_format_change(state)
        if snapped.size_text != state.size_text:
            self.query_one("#create-size", Input).value = snapped.size_text
        self._clear_status()

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
        # Use explicit picker state instead of widget visibility:
        # in the wizard layout the boot-assets row may have its own
        # display=True but live inside a hidden step container, so the
        # old `.display` check produced false positives that would
        # repurpose plain tree navigation as a boot-assets pick.
        return self.path_picker_target == "boot-assets"


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
