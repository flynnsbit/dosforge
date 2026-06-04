"""Mounts view: mount/unmount/list disk images."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..errors import DosForgeError
from .widgets import Card


class MountsView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self.var_unmount = tk.StringVar()
        self._build()
        self.refresh_mounts()

    def _build(self) -> None:
        card = Card(self, self.app.theme, title="Mounts")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body
        body.columnconfigure(0, weight=1)

        if self.app.capabilities.mount_requires_admin_hint:
            ttk.Label(
                body,
                text=(
                    "Mounting on Windows requires running as Administrator. "
                    "If mounting fails, use Image Tools to browse/extract without admin."
                ),
                style="Muted.TLabel",
                wraplength=640,
            ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        btn_row = ttk.Frame(body)
        btn_row.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            btn_row,
            text="Mount selected image",
            style="Accent.TButton",
            command=self._mount,
            takefocus=False,
        ).pack(side="left")
        ttk.Button(
            btn_row, text="Refresh", command=self.refresh_mounts, takefocus=False
        ).pack(side="left", padx=(8, 0))

        unmount_row = ttk.Frame(body)
        unmount_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        unmount_row.columnconfigure(0, weight=1)
        ttk.Entry(unmount_row, textvariable=self.var_unmount).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            unmount_row, text="Unmount", command=self._unmount, takefocus=False
        ).grid(row=0, column=1, padx=(8, 0))

        self._list_lbl = ttk.Label(
            body, text="No active mounts tracked.", style="TLabel", justify="left"
        )
        self._list_lbl.grid(row=3, column=0, sticky="w", pady=(14, 0))

    def refresh_mounts(self) -> None:
        try:
            mounts = self.app.manager.list_mounts()
        except DosForgeError as exc:
            self._list_lbl.configure(text=str(exc))
            return
        if not mounts:
            self._list_lbl.configure(text="No active mounts tracked.")
            return
        lines = ["Active mounts:"]
        for item in mounts:
            lines.append(
                f"- {item.mount_point} <- {item.vhd_path} ({item.nbd_device})"
            )
        self._list_lbl.configure(text="\n".join(lines))

    def _mount(self) -> None:
        image = self.app.selected_image
        if image is None:
            self.app.status.set_status(
                "Select a .vhd/.img/.ima file first (Browse or Create).", error=True
            )
            return

        def work():
            record = self.app.manager.mount_vhd(image)
            try:
                self.app.manager.open_in_files(record.mount_point)
            except DosForgeError:
                pass
            return record

        def done(record):
            self.var_unmount.set(str(record.mount_point))
            self.refresh_mounts()

        self.app.run_operation(
            "mount",
            work,
            done,
            busy_msg=f"Mounting {image.name}…",
            success_msg="Mounted image.",
        )

    def _unmount(self) -> None:
        text = self.var_unmount.get().strip()
        if not text:
            self.app.status.set_status("Enter a mounted path to unmount.", error=True)
            return

        def work():
            return self.app.manager.unmount(Path(text))

        def done(record):
            self.refresh_mounts()

        self.app.run_operation(
            "unmount",
            work,
            done,
            busy_msg=f"Unmounting {text}…",
            success_msg="Unmounted image.",
        )

    def refresh_theme(self) -> None:
        pass
