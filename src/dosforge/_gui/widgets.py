"""Reusable Fluent-style widgets for the dosforge GUI.

All widgets are thin wrappers over ttk so the Sun Valley theme styles them
automatically; custom styles come from :mod:`dosforge._gui.theme`.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container. Add content to ``self.body``."""

    def __init__(self, parent, theme, **kwargs) -> None:
        super().__init__(parent, style="Content.TFrame", **kwargs)
        self._theme = theme
        pal = theme.palette
        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            background=pal.window_bg,
            bd=0,
        )
        self._scroll = ttk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview
        )
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.body = ttk.Frame(self._canvas, style="Content.TFrame")
        self._window = self._canvas.create_window(
            (0, 0), window=self.body, anchor="nw"
        )

        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # Scope the mouse wheel to this canvas while hovered.
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def refresh_theme(self) -> None:
        self._canvas.configure(background=self._theme.palette.window_bg)

    def _on_body_configure(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event) -> None:
        self._canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")


class Card(ttk.Frame):
    """A Fluent 'card' panel with an optional heading. Add to ``self.body``."""

    def __init__(self, parent, title: str | None = None, **kwargs) -> None:
        super().__init__(parent, style="Card.TFrame", padding=18, **kwargs)
        if title:
            ttk.Label(self, text=title, style="Heading.TLabel").pack(
                anchor="w", pady=(0, 12)
            )
        self.body = ttk.Frame(self, style="Card.TFrame")
        self.body.pack(fill="both", expand=True)


class StatusBar(ttk.Frame):
    """Bottom status strip with a message + indeterminate busy bar."""

    def __init__(self, parent, theme) -> None:
        super().__init__(parent, style="Window.TFrame", padding=(16, 6))
        self._theme = theme
        self._label = ttk.Label(self, text="Ready.", style="Status.TLabel")
        self._label.pack(side="left", fill="x", expand=True)
        self._progress = ttk.Progressbar(self, mode="indeterminate", length=160)

    def set_status(self, message: str, *, error: bool = False) -> None:
        # Status text is single-line; collapse newlines for the strip.
        text = " ".join(message.splitlines()) if message else ""
        self._label.configure(
            text=text or "Ready.",
            style="StatusError.TLabel" if error else "Status.TLabel",
        )

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._progress.pack(side="right", padx=(12, 0))
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()


class NavRail(ttk.Frame):
    """Vertical Fluent NavigationView: one flat button per view."""

    def __init__(
        self,
        parent,
        items: list[tuple[str, str]],
        on_select: Callable[[str], None],
        theme,
    ) -> None:
        super().__init__(parent, style="Nav.TFrame", padding=(8, 12))
        self._on_select = on_select
        self._buttons: dict[str, ttk.Button] = {}
        self._active: str | None = None
        for key, label in items:
            btn = ttk.Button(
                self,
                text=label,
                style="Nav.TButton",
                takefocus=False,
                command=lambda k=key: self._on_select(k),
            )
            btn.pack(fill="x", pady=2)
            self._buttons[key] = btn

    def set_active(self, key: str) -> None:
        self._active = key
        for k, btn in self._buttons.items():
            btn.configure(style="NavActive.TButton" if k == key else "Nav.TButton")


class Field:
    """A labeled form control that can be shown/hidden while keeping order.

    Uses ``grid`` + ``grid_remove`` so hiding a field doesn't disturb the
    layout of the others. ``row`` is assigned at build time.
    """

    def __init__(
        self,
        parent,
        key: str,
        label: str,
        control: tk.Widget,
        *,
        browse_command: Callable[[], None] | None = None,
        help_text: str | None = None,
    ) -> None:
        self.key = key
        self.control = control
        self._frame = ttk.Frame(parent, style="Card.TFrame")
        if label:
            ttk.Label(self._frame, text=label, style="FieldLabel.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, 2)
            )

        control_row = ttk.Frame(self._frame, style="Card.TFrame")
        control_row.grid(row=1, column=0, sticky="ew")
        control_row.columnconfigure(0, weight=1)
        control.grid(in_=control_row, row=0, column=0, sticky="ew")
        if browse_command is not None:
            ttk.Button(
                control_row, text="Browse…", command=browse_command, takefocus=False
            ).grid(row=0, column=1, padx=(8, 0))
        if help_text:
            ttk.Label(self._frame, text=help_text, style="Muted.TLabel").grid(
                row=2, column=0, sticky="w", pady=(2, 0)
            )
        self._frame.columnconfigure(0, weight=1)
        self._row = 0
        self._visible = True

    def place_at(self, row: int) -> None:
        self._row = row
        self._frame.grid(row=row, column=0, sticky="ew", pady=8)

    def set_visible(self, visible: bool) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        if visible:
            self._frame.grid()
        else:
            self._frame.grid_remove()
