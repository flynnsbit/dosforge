"""Reusable Fluent-style widgets for the dosforge GUI.

Cards are deliberately built from plain :class:`tkinter.Frame` (not ttk),
because sv_ttk's ``Card.TFrame`` uses a custom ``Card.field`` element with
its own panel border — nesting two ``Card.TFrame`` widgets renders two
borders, which is what caused the visible "boxes inside boxes" in v0.5.0-
gui-pre1. Plain frames let us paint a single, predictable surface color
and one outer border per section.

ttk widgets hosted on these surfaces (labels, checkbuttons) use the
``DfCard*`` styles configured in :mod:`theme` so their backgrounds match
the surface — ttk does NOT inherit ``bg`` from its tk parent.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class ScrollableFrame(tk.Frame):
    """A vertically scrollable container. Add content to ``self.body``."""

    def __init__(self, parent, theme, **kwargs) -> None:
        pal = theme.palette
        super().__init__(parent, bg=pal.window_bg, **kwargs)
        self._theme = theme
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

        self.body = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window(
            (0, 0), window=self.body, anchor="nw"
        )

        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def refresh_theme(self) -> None:
        pal = self._theme.palette
        self.configure(bg=pal.window_bg)
        self._canvas.configure(background=pal.window_bg)

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
    """A Fluent card panel using sv_ttk's ``Card.TFrame`` style.

    The body is a plain ttk.Frame (no Card style), so widgets nested
    inside don't get a second panel border. Add content to ``self.body``.
    """

    def __init__(self, parent, theme, title: str | None = None, **kwargs) -> None:
        super().__init__(parent, style="Card.TFrame", padding=16, **kwargs)
        self._theme = theme
        self._title_label: ttk.Label | None = None
        if title:
            self._title_label = ttk.Label(
                self, text=title, style="Heading.TLabel"
            )
            self._title_label.pack(anchor="w", pady=(0, 8))
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)

    def refresh_theme(self) -> None:
        # sv_ttk handles bg via its sprite; nothing to refresh here.
        pass


class StatusBar(tk.Frame):
    """Bottom status strip with a message + indeterminate busy bar."""

    def __init__(self, parent, theme) -> None:
        pal = theme.palette
        super().__init__(parent, bg=pal.window_bg)
        self._theme = theme
        inner = tk.Frame(self, bg=pal.window_bg)
        inner.pack(fill="x", padx=16, pady=6)
        self._inner = inner
        self._label = ttk.Label(inner, text="Ready.", style="Status.TLabel")
        self._label.pack(side="left", fill="x", expand=True)
        self._progress = ttk.Progressbar(inner, mode="indeterminate", length=160)

    def set_status(self, message: str, *, error: bool = False) -> None:
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

    def refresh_theme(self) -> None:
        pal = self._theme.palette
        self.configure(bg=pal.window_bg)
        self._inner.configure(bg=pal.window_bg)


class NavRail(tk.Frame):
    """Vertical Fluent NavigationView: one flat button per view."""

    def __init__(
        self,
        parent,
        items: list[tuple[str, str]],
        on_select: Callable[[str], None],
        theme,
    ) -> None:
        pal = theme.palette
        super().__init__(parent, bg=pal.nav_bg)
        self._theme = theme
        self._on_select = on_select
        self._buttons: dict[str, ttk.Button] = {}
        self._active: str | None = None
        inner = tk.Frame(self, bg=pal.nav_bg)
        inner.pack(fill="both", expand=True, padx=8, pady=12)
        self._inner = inner
        for key, label in items:
            btn = ttk.Button(
                inner,
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

    def refresh_theme(self) -> None:
        pal = self._theme.palette
        self.configure(bg=pal.nav_bg)
        self._inner.configure(bg=pal.nav_bg)


class Field:
    """A labeled form control that can be shown/hidden while keeping order.

    The control is constructed by a caller-supplied factory whose argument
    is the field's inner frame — this guarantees the control's actual
    parent matches its layout master. (Using ``grid(in_=other_frame)`` on
    a widget whose parent is elsewhere can render the widget invisibly,
    which is exactly what bit us in v0.5.0-gui-pre2.)
    """

    def __init__(
        self,
        parent,
        theme,
        key: str,
        label: str,
        control_factory: Callable[[ttk.Frame], tk.Widget],
        *,
        browse_command: Callable[[], None] | None = None,
        help_text: str | None = None,
    ) -> None:
        self.key = key
        self._frame = ttk.Frame(parent)
        self._frame.columnconfigure(0, weight=1)

        row = 0
        if label:
            ttk.Label(
                self._frame, text=label, style="FieldLabel.TLabel"
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
            row += 1
        control = control_factory(self._frame)
        self.control = control
        if browse_command is not None:
            control.grid(row=row, column=0, sticky="ew")
            ttk.Button(
                self._frame,
                text="Browse...",
                command=browse_command,
                takefocus=False,
            ).grid(row=row, column=1, padx=(8, 0))
        else:
            control.grid(row=row, column=0, columnspan=2, sticky="ew")
        if help_text:
            ttk.Label(
                self._frame, text=help_text, style="Muted.TLabel"
            ).grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self._row = 0
        self._visible = True

    def place_at(self, row: int) -> None:
        self._row = row
        self._frame.grid(row=row, column=0, sticky="ew", pady=4)

    def set_visible(self, visible: bool) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        if visible:
            self._frame.grid()
        else:
            self._frame.grid_remove()
