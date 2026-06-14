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


_COMBOBOX_POPDOWN_MARKERS = (".popdown.", "popdown.f.l")


def apply_combobox_polish(root: tk.Misc) -> None:
    """Make ttk.Combobox behave like a Win32 ComboBox in two ways.

    1) Strip Tk's ``<MouseWheel>`` class binding from ``TCombobox`` so a
       wheel scroll over a readonly combobox does NOT cycle its value
       and never blocks the page-level scroll handler installed by
       :class:`ScrollableFrame`.

    2) Install a single ``bind_all("<Button-1>", …, add="+")`` handler
       that releases focus from any focused combobox whenever the user
       clicks outside it (or its popup listbox). Native Win32 ComboBoxes
       lose focus this way; Tk does not by default, which is why the
       focus highlight on (for example) the DOS Version picker persists
       after the user clicks another field.

    Idempotent — calling it more than once on the same root removes the
    class binding (no-op the second time) and installs the click handler
    with the same tag so duplicate registrations are still safe.
    """

    root.unbind_class("TCombobox", "<MouseWheel>")
    root.unbind_class("TCombobox", "<Button-4>")
    root.unbind_class("TCombobox", "<Button-5>")

    def _release_combobox_focus(event: tk.Event) -> None:
        target = event.widget
        if isinstance(target, str):
            try:
                target = root.nametowidget(target)
            except KeyError:
                return
        try:
            path = str(target)
        except Exception:
            path = ""
        if any(marker in path for marker in _COMBOBOX_POPDOWN_MARKERS):
            return
        node: tk.Misc | None = target
        while node is not None:
            if isinstance(node, ttk.Combobox):
                return
            node = node.master
        try:
            focused = root.focus_get()
        except KeyError:
            focused = None
        if isinstance(focused, ttk.Combobox):
            try:
                focused.selection_clear()
            except tk.TclError:
                pass
            try:
                root.focus_set()
            except tk.TclError:
                pass

    if getattr(root, "_dosforge_combo_polish_installed", False):
        return
    root.bind_all("<Button-1>", _release_combobox_focus, add="+")
    root._dosforge_combo_polish_installed = True  # type: ignore[attr-defined]


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
    """Bottom status strip: status line + indeterminate busy bar + an
    expandable log panel that shows step-by-step subprocess output.

    The log panel is collapsed by default and toggled via the "Show log"
    chevron button. When an operation runs, the GUI's run_operation
    redirects stdout/stderr to ``append_log`` so users see progress
    instead of guessing whether the app is still working.
    """

    _LOG_LINES_VISIBLE = 8

    def __init__(self, parent, theme) -> None:
        pal = theme.palette
        super().__init__(parent, bg=pal.window_bg)
        self._theme = theme

        status_row = tk.Frame(self, bg=pal.window_bg)
        status_row.pack(fill="x", padx=16, pady=(6, 4))
        self._status_row = status_row
        self._label = ttk.Label(status_row, text="Ready.", style="Status.TLabel")
        self._label.pack(side="left", fill="x", expand=True)
        self._toggle_btn = ttk.Button(
            status_row,
            text="Show log",
            command=self._toggle_log,
            takefocus=False,
        )
        self._toggle_btn.pack(side="right")
        self._copy_btn = ttk.Button(
            status_row,
            text="Copy log",
            command=self.copy_log_to_clipboard,
            takefocus=False,
        )
        self._copy_btn.pack(side="right", padx=(0, 6))
        self._progress = ttk.Progressbar(status_row, mode="indeterminate", length=160)

        # Log panel — kept packed-but-hidden so toggling is fast.
        log_holder = tk.Frame(self, bg=pal.window_bg)
        self._log_holder = log_holder
        self._log_text = tk.Text(
            log_holder,
            height=self._LOG_LINES_VISIBLE,
            wrap="none",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9),
        )
        self._log_scroll = ttk.Scrollbar(
            log_holder, orient="vertical", command=self._log_text.yview
        )
        self._log_text.configure(yscrollcommand=self._log_scroll.set, state="disabled")
        self._log_scroll.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self._log_visible = False
        self._apply_log_theme()

    def set_status(self, message: str, *, error: bool = False) -> None:
        text = " ".join(message.splitlines()) if message else ""
        self._label.configure(
            text=text or "Ready.",
            style="StatusError.TLabel" if error else "Status.TLabel",
        )

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._progress.pack(side="right", padx=(12, 8))
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def append_log(self, text: str) -> None:
        if not text:
            return
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        # Trim to keep the buffer from growing unbounded.
        line_count = int(self._log_text.index("end-1c").split(".")[0])
        if line_count > 500:
            self._log_text.delete("1.0", f"{line_count - 500}.0")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def show_log(self) -> None:
        if not self._log_visible:
            self._log_holder.pack(fill="both", expand=False, padx=16, pady=(0, 6))
            self._toggle_btn.configure(text="Hide log")
            self._log_visible = True

    def copy_log_to_clipboard(self) -> None:
        """Copy the full log buffer to the OS clipboard.

        Works on Windows / macOS / X11 / Wayland via Tk's clipboard
        bridge.  The buffer is read in its entirety (capped at 500
        lines by ``append_log``'s ring-buffer trim) so the user can
        share complete subprocess output without manually selecting
        text inside the read-only Text widget.
        """
        content = self._log_text.get("1.0", "end-1c")
        if not content.strip():
            self.set_status("Log is empty -- nothing to copy.")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update_idletasks()  # flush to X selection on Linux.
        except Exception as exc:
            self.set_status(f"Copy failed: {exc}", error=True)
            return
        line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
        self.set_status(f"Copied {line_count} log line(s) to clipboard.")

    def _toggle_log(self) -> None:
        if self._log_visible:
            self._log_holder.pack_forget()
            self._toggle_btn.configure(text="Show log")
            self._log_visible = False
        else:
            self.show_log()

    def refresh_theme(self) -> None:
        pal = self._theme.palette
        self.configure(bg=pal.window_bg)
        self._status_row.configure(bg=pal.window_bg)
        self._log_holder.configure(bg=pal.window_bg)
        self._apply_log_theme()

    def _apply_log_theme(self) -> None:
        pal = self._theme.palette
        self._log_text.configure(
            background=pal.surface_alt,
            foreground=pal.text,
            insertbackground=pal.text,
        )


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
