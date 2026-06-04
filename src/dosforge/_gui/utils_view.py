"""Utilities view: privilege diagnostics and dependency preflight."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..errors import DosForgeError
from .widgets import Card


class UtilsView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self._build()

    def _build(self) -> None:
        card = Card(self, title="Utilities")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body
        body.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.grid(row=0, column=0, sticky="ew")
        if self.app.capabilities.supports_privilege_diagnostics:
            ttk.Button(
                btn_row,
                text="Privilege diagnostics",
                command=self._diagnostics,
                takefocus=False,
            ).pack(side="left")
        ttk.Button(
            btn_row, text="Dependency preflight", command=self._preflight, takefocus=False
        ).pack(side="left", padx=(8, 0))

        out = tk.Text(body, height=14, wrap="word", relief="flat", borderwidth=0)
        out.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        body.rowconfigure(1, weight=1)
        out.configure(state="disabled")
        self._output = out
        self._apply_text_theme()

    def _apply_text_theme(self) -> None:
        pal = self.app.theme.palette
        self._output.configure(
            background=pal.surface_alt,
            foreground=pal.text,
            insertbackground=pal.text,
            font=("Consolas", 10),
        )

    def _write(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
        self._output.configure(state="disabled")

    def _diagnostics(self) -> None:
        def work():
            return self.app.manager.privilege_diagnostics_summary()

        def done(result):
            ok, summary = result
            self._write(("[OK] " if ok else "[ERROR] ") + summary)

        self.app.run_operation(
            "diagnostics",
            work,
            done,
            busy_msg="Checking privileges…",
            success_msg="Diagnostics complete.",
        )

    def _preflight(self) -> None:
        def work():
            self.app.manager.preflight()
            return True

        def done(_value):
            self._write("All required dependencies are available.")

        self.app.run_operation(
            "preflight",
            work,
            done,
            busy_msg="Checking dependencies…",
            success_msg="Dependencies OK.",
        )

    def refresh_theme(self) -> None:
        self._apply_text_theme()
