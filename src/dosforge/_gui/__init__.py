"""dosforge desktop GUI shell (tkinter + Sun Valley theme).

Public surface:

* :class:`GuiUnavailable` — raised when no display / Tk is available.
* :func:`run_gui` — DPI-aware entry point used by ``cli.py``.
"""

from __future__ import annotations

from pathlib import Path

from ..disk import DiskManager
from ..errors import DosForgeError
from .theme import enable_dpi_awareness


class GuiUnavailable(RuntimeError):
    """Raised when the GUI cannot start (no display, Tk/sv_ttk missing)."""


def run_gui(manager: DiskManager | None = None) -> int:
    """Launch the GUI. Sets DPI awareness first, then builds the Tk root.

    Raises :class:`GuiUnavailable` if Tk or the theme can't be initialized so
    the caller can fall back to the TUI.
    """
    # MUST run before any Tk window exists.
    enable_dpi_awareness()
    try:
        import tkinter as tk  # noqa: F401
        import sv_ttk  # noqa: F401
    except Exception as exc:  # pragma: no cover - import guard
        raise GuiUnavailable(f"GUI toolkit unavailable: {exc}") from exc

    try:
        app = DosForgeGUI(manager=manager)
    except GuiUnavailable:
        raise
    except Exception as exc:  # pragma: no cover - display/init failure
        raise GuiUnavailable(f"Could not initialize the GUI: {exc}") from exc

    app.run()
    return 0


class DosForgeGUI:
    """Top-level application window with a Fluent navigation rail."""

    _NAV_ITEMS = [
        ("create", "New Disk"),
        ("browse", "Browse"),
        ("tools", "Image Tools"),
        ("mounts", "Mounts"),
        ("utils", "Utilities"),
    ]

    def __init__(self, manager: DiskManager | None = None) -> None:
        import tkinter as tk
        from tkinter import ttk

        from ..capabilities import ui_capabilities
        from .theme import ThemeManager, set_window_icon
        from .widgets import NavRail, StatusBar
        from .worker import OperationWorker

        self.manager = manager or DiskManager()
        self.capabilities = ui_capabilities(self.manager)
        self.selected_image: Path | None = None

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise GuiUnavailable(f"No display available: {exc}") from exc
        self.root.title("DosForge")
        self.root.minsize(960, 640)
        self._center(1180, 780)

        self.theme = ThemeManager(self.root)
        self.theme.apply()
        set_window_icon(self.root)

        self.worker = OperationWorker(self.root)

        # Header: title + theme toggle.
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 14, 20, 8))
        header.pack(side="top", fill="x")
        ttk.Label(header, text="DosForge", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Build, browse, and mount DOS-friendly disk images",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(8, 0))
        self._theme_btn = ttk.Button(
            header,
            text="Toggle theme",
            command=self._toggle_theme,
            takefocus=False,
        )
        self._theme_btn.pack(side="right")

        # Body: nav rail + content router.
        body = ttk.Frame(self.root, style="Window.TFrame")
        body.pack(side="top", fill="both", expand=True)

        nav_items = self._enabled_nav_items()
        self.nav = NavRail(body, nav_items, self._select_view, self.theme)
        self.nav.pack(side="left", fill="y", padx=(12, 0), pady=12)

        self.content = ttk.Frame(body, style="Content.TFrame", padding=(16, 12))
        self.content.pack(side="left", fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        # Status strip.
        self.status = StatusBar(self.root, self.theme)
        self.status.pack(side="bottom", fill="x")

        self._views: dict = {}
        self._build_views(nav_items)

        first = nav_items[0][0]
        self._select_view(first)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── layout helpers ─────────────────────────────────────────────────
    def _center(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _enabled_nav_items(self) -> list[tuple[str, str]]:
        items = []
        for key, label in self._NAV_ITEMS:
            if key == "tools" and not self.capabilities.supports_mtools_image_tools:
                continue
            if key == "mounts" and not self.capabilities.supports_mount:
                continue
            items.append((key, label))
        return items

    def _build_views(self, nav_items: list[tuple[str, str]]) -> None:
        from .browse_view import BrowseView
        from .create_view import CreateView
        from .mounts_view import MountsView
        from .tools_view import ToolsView
        from .utils_view import UtilsView

        factories = {
            "create": CreateView,
            "browse": BrowseView,
            "tools": ToolsView,
            "mounts": MountsView,
            "utils": UtilsView,
        }
        for key, _label in nav_items:
            view = factories[key](self.content, self)
            view.grid(row=0, column=0, sticky="nsew")
            self._views[key] = view

    def _select_view(self, key: str) -> None:
        view = self._views.get(key)
        if view is None:
            return
        if key == "tools" and hasattr(view, "refresh_target"):
            view.refresh_target()
        if key == "mounts" and hasattr(view, "refresh_mounts"):
            view.refresh_mounts()
        view.tkraise()
        self.nav.set_active(key)

    # ── theming ─────────────────────────────────────────────────────────
    def _toggle_theme(self) -> None:
        self.theme.toggle()
        for view in self._views.values():
            if hasattr(view, "refresh_theme"):
                try:
                    view.refresh_theme()
                except Exception:
                    pass

    # ── shared operation runner ─────────────────────────────────────────
    def run_operation(
        self,
        name: str,
        func,
        on_success=None,
        *,
        busy_msg: str = "Working…",
        success_msg: str = "Done.",
    ) -> None:
        """Run a backend op on the worker thread with status + busy feedback."""
        if self.worker.busy:
            self.status.set_status("Please wait for the current operation to finish.")
            return
        self.status.set_status(busy_msg)
        self.status.set_busy(True)

        def done(result):
            self.status.set_busy(False)
            if result.ok:
                self.status.set_status(success_msg)
                if on_success is not None:
                    try:
                        on_success(result.value)
                    except DosForgeError as exc:
                        self.status.set_status(str(exc), error=True)
                    except Exception as exc:  # noqa: BLE001
                        self.status.set_status(str(exc), error=True)
            else:
                err = result.error
                self.status.set_status(str(err) if err else "Operation failed.", error=True)

        if not self.worker.submit(name, func, done):
            self.status.set_busy(False)
            self.status.set_status(
                "Please wait for the current operation to finish."
            )

    # ── image selection ─────────────────────────────────────────────────
    def set_selected_image(self, path: Path) -> None:
        self.selected_image = path
        self.status.set_status(f"Selected image: {path}")
        tools = self._views.get("tools")
        if tools is not None and hasattr(tools, "refresh_target"):
            tools.refresh_target()

    # ── lifecycle ───────────────────────────────────────────────────────
    def _on_close(self) -> None:
        if self.worker.busy:
            from tkinter import messagebox

            if not messagebox.askokcancel(
                "Operation in progress",
                "A disk operation is still running. Quitting now may leave a "
                "partial image or a leaked mount.\n\nQuit anyway?",
                icon="warning",
                default="cancel",
                parent=self.root,
            ):
                return
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
