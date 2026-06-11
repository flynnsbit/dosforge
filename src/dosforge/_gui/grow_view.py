"""Grow Disk view: resize an existing VHD via the dosforge grow pipeline.

Exposes the same surface as the ``dosforge grow`` CLI:

* Target VHD (pre-filled from the currently selected image).
* New size (human-friendly: ``128M``, ``2G``).
* Boot mode (one of the four growable modes).  Auto-detected from
  the current VHD when the user picks one or refreshes.
* Optional staging directories (host source + DOS dest path).
* Boot-probe and keep-backup checkboxes.

Pressing **Grow** runs the same :func:`dosforge.grow.grow_vhd` API
the CLI invokes, surfacing any :class:`ValidationError` in the
status bar / log panel.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..errors import DosForgeError, ValidationError
from ..grow import GROWABLE_BOOT_MODES, GrowManifest, StagingSource, grow_vhd
from ..inspect import inspect_vhd
from ..models import BootMode
from ..size import parse_size
from .widgets import Card


# Map of (BootMode -> human label) for the boot-mode combo.  Kept in
# sync with GROWABLE_BOOT_MODES; reorder only by changing this tuple.
_GROW_BOOT_MODE_OPTIONS: tuple[tuple[BootMode, str], ...] = (
    (BootMode.COMPAQ331, "Compaq DOS 3.31 (compaq331, FAT16 BIGDOS)"),
    (BootMode.MSDOS622, "MS-DOS 6.22 (msdos622, FAT16)"),
    (BootMode.MSDOS71, "MS-DOS 7.10 / Win95 OSR2 (msdos71, FAT16/32)"),
    (BootMode.FREEDOS, "FreeDOS (freedos, FAT16/32)"),
)


class GrowView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self._theme = app.theme

        self.var_target = tk.StringVar()
        self.var_current = tk.StringVar(value="(select a VHD via Browse first)")
        self.var_new_size = tk.StringVar(value="")
        self.var_boot_mode = tk.StringVar()
        self.var_boot_probe = tk.BooleanVar(value=True)
        self.var_keep_backup = tk.BooleanVar(value=True)

        self._boot_mode_label_to_value: dict[str, BootMode] = {
            label: mode for mode, label in _GROW_BOOT_MODE_OPTIONS
        }
        self._boot_mode_value_to_label: dict[BootMode, str] = {
            mode: label for mode, label in _GROW_BOOT_MODE_OPTIONS
        }
        self._staging: list[tuple[Path, str]] = []

        self._build()
        self.refresh_target()

    def _build(self) -> None:
        card = Card(self, self.app.theme, title="Grow an existing VHD")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body
        body.columnconfigure(1, weight=1)
        body.rowconfigure(9, weight=1)

        # ── Target row ─────────────────────────────────────────────
        ttk.Label(body, text="Target VHD:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        target_row = ttk.Frame(body)
        target_row.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        target_row.columnconfigure(0, weight=1)
        ttk.Entry(target_row, textvariable=self.var_target).grid(row=0, column=0, sticky="ew")
        ttk.Button(target_row, text="...", command=self._browse_target, takefocus=False).grid(
            row=0, column=1, padx=(8, 0)
        )

        ttk.Label(body, textvariable=self.var_current, style="Muted.TLabel").grid(
            row=1, column=1, sticky="w", pady=(0, 10)
        )

        # ── New size ───────────────────────────────────────────────
        ttk.Label(body, text="New size:").grid(row=2, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(body, textvariable=self.var_new_size, width=16).grid(
            row=2, column=1, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            body,
            text="Examples: 128M, 256M, 1G, 2G  (must be larger than current size + within the same cluster band)",
            style="Muted.TLabel",
        ).grid(row=3, column=1, sticky="w", pady=(0, 10))

        # ── Boot mode ──────────────────────────────────────────────
        ttk.Label(body, text="Boot mode:").grid(row=4, column=0, sticky="w", pady=(0, 4))
        self._boot_combo = ttk.Combobox(
            body,
            textvariable=self.var_boot_mode,
            state="readonly",
            values=[label for _, label in _GROW_BOOT_MODE_OPTIONS],
        )
        self._boot_combo.grid(row=4, column=1, sticky="ew", pady=(0, 10))

        # ── Options ────────────────────────────────────────────────
        opts = ttk.Frame(body)
        opts.grid(row=5, column=1, sticky="w", pady=(0, 10))
        ttk.Checkbutton(
            opts,
            text="Headless boot probe (verify the grown VHD boots before swap)",
            variable=self.var_boot_probe,
        ).pack(side="top", anchor="w")
        ttk.Checkbutton(
            opts,
            text="Keep original VHD as <target>.bak",
            variable=self.var_keep_backup,
        ).pack(side="top", anchor="w")

        # ── Staging sources ────────────────────────────────────────
        ttk.Label(body, text="Staging sources:").grid(row=6, column=0, sticky="nw", pady=(0, 4))
        staging_frame = ttk.Frame(body)
        staging_frame.grid(row=6, column=1, sticky="ew", pady=(0, 4))
        staging_frame.columnconfigure(0, weight=1)

        self._staging_list = tk.Listbox(staging_frame, height=4)
        self._staging_list.grid(row=0, column=0, sticky="ew")

        staging_btns = ttk.Frame(staging_frame)
        staging_btns.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ttk.Button(
            staging_btns, text="Add directory…", command=self._add_staging, takefocus=False
        ).pack(side="top", fill="x")
        ttk.Button(
            staging_btns, text="Remove selected", command=self._remove_staging, takefocus=False
        ).pack(side="top", fill="x", pady=(4, 0))
        ttk.Label(
            body,
            text="Each staging source: pick a host directory, then enter the DOS destination (e.g. C:\\GAMES).",
            style="Muted.TLabel",
        ).grid(row=7, column=1, sticky="w", pady=(0, 10))

        # ── Grow button + output ───────────────────────────────────
        action_row = ttk.Frame(body)
        action_row.grid(row=8, column=1, sticky="w", pady=(0, 10))
        ttk.Button(
            action_row,
            text="Grow VHD",
            command=self._grow,
            takefocus=False,
            style="Accent.TButton",
        ).pack(side="left")
        ttk.Button(
            action_row,
            text="Refresh inferred boot mode",
            command=self.refresh_target,
            takefocus=False,
        ).pack(side="left", padx=(8, 0))

        out = tk.Text(body, height=12, wrap="word", relief="flat", borderwidth=0)
        out.grid(row=9, column=0, columnspan=2, sticky="nsew")
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

    def refresh_theme(self) -> None:
        self._apply_text_theme()

    def refresh_target(self) -> None:
        """Re-read the currently-selected image and auto-fill fields.

        Idempotent: if no image is selected (or the file doesn't
        exist) the form is left in whatever state the user has
        already entered.
        """
        image = self.app.selected_image
        if image is not None:
            self.var_target.set(str(image))
            self._try_autoinfer(image)
        elif self.var_target.get():
            # No selected_image but user may have hand-typed a path.
            self._try_autoinfer(Path(self.var_target.get()))
        else:
            self.var_current.set("(select a VHD via Browse first)")

    def _try_autoinfer(self, target: Path) -> None:
        """Read VHD metadata and pre-fill current-size + boot-mode.

        Errors (file missing, malformed VHD) are silently ignored;
        the form just stays empty/unchanged so the user can hand-fill.
        """
        try:
            info = inspect_vhd(target)
        except (DosForgeError, OSError):
            self.var_current.set(f"(cannot read {target.name} — fill fields manually)")
            return
        current_size_mb = info.file_size_bytes / (1024 * 1024)
        self.var_current.set(
            f"Current: {current_size_mb:.0f} MiB  •  "
            f"{info.fat_format.value}  •  cluster {info.cluster_size_bytes:,} bytes  •  "
            f"inferred boot: {info.inferred_boot_mode.value if info.inferred_boot_mode else 'unknown'}"
        )
        if info.inferred_boot_mode in self._boot_mode_value_to_label:
            self.var_boot_mode.set(
                self._boot_mode_value_to_label[info.inferred_boot_mode]
            )

    def _browse_target(self) -> None:
        path_str = filedialog.askopenfilename(
            title="Select VHD to grow",
            filetypes=[("VHD files", "*.vhd"), ("All files", "*.*")],
        )
        if path_str:
            self.var_target.set(path_str)
            self._try_autoinfer(Path(path_str))

    def _add_staging(self) -> None:
        host_dir = filedialog.askdirectory(title="Choose host directory to stage")
        if not host_dir:
            return
        # Quick prompt for DOS destination path.
        dialog = tk.Toplevel(self)
        dialog.title("DOS destination path")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text=f"Stage {host_dir}\nto which DOS path? (e.g. C:\\GAMES)",
        ).pack(padx=16, pady=(16, 8))
        var_dest = tk.StringVar(value="C:\\")
        entry = ttk.Entry(dialog, textvariable=var_dest, width=32)
        entry.pack(padx=16, pady=(0, 8))
        entry.focus_set()

        result: dict[str, str | None] = {"dest": None}

        def _ok():
            result["dest"] = var_dest.get().strip()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(pady=(0, 12))
        ttk.Button(btn_row, text="OK", command=_ok).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=_cancel).pack(side="left", padx=4)
        dialog.bind("<Return>", lambda _e: _ok())
        dialog.bind("<Escape>", lambda _e: _cancel())
        dialog.wait_window()

        if result["dest"]:
            self._staging.append((Path(host_dir), result["dest"]))
            self._staging_list.insert(
                "end", f"{host_dir}  ->  {result['dest']}"
            )

    def _remove_staging(self) -> None:
        selection = self._staging_list.curselection()
        if not selection:
            return
        index = selection[0]
        self._staging_list.delete(index)
        del self._staging[index]

    def _grow(self) -> None:
        target_str = self.var_target.get().strip()
        new_size_str = self.var_new_size.get().strip()
        boot_label = self.var_boot_mode.get().strip()

        if not target_str:
            self.app.status.set_status("Pick a target VHD first.", error=True)
            return
        if not new_size_str:
            self.app.status.set_status(
                "Enter a new size (e.g. 256M or 1G).", error=True
            )
            return
        if boot_label not in self._boot_mode_label_to_value:
            self.app.status.set_status(
                "Pick a boot mode from the list.", error=True
            )
            return

        try:
            new_size_bytes = parse_size(new_size_str)
        except ValidationError as exc:
            self.app.status.set_status(str(exc), error=True)
            return

        boot_mode = self._boot_mode_label_to_value[boot_label]
        manifest = GrowManifest(
            target_vhd=Path(target_str),
            new_size_bytes=new_size_bytes,
            boot_mode=boot_mode,
            staging_sources=tuple(
                StagingSource(src=src, dest=dest) for src, dest in self._staging
            ),
            boot_probe=self.var_boot_probe.get(),
            keep_backup=self.var_keep_backup.get(),
        )

        def work():
            grow_vhd(manifest)
            return manifest

        def done(_):
            backup = (
                f"  Backup: {manifest.target_vhd}.bak"
                if manifest.keep_backup
                else "  (no backup kept)"
            )
            self._write_output(
                f"Grew {manifest.target_vhd} to {manifest.new_size_bytes:,} bytes.\n{backup}"
            )

        self.app.run_operation(
            "grow",
            work,
            done,
            busy_msg=f"Growing {manifest.target_vhd.name}…",
            success_msg=f"Grew {manifest.target_vhd.name}.",
        )

    def _write_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
        self._output.configure(state="disabled")
