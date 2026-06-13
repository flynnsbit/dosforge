"""Grow Disk view: resize an existing VHD via the dosforge grow pipeline.

Exposes the same surface as the ``dosforge grow`` CLI:

* Target VHD (pre-filled from the currently selected image).
* New size (human-friendly: ``128M``, ``2G``).
* Optional staging directories (host source + DOS dest path).
* Boot-probe and keep-backup checkboxes.

Boot mode is **auto-detected** from the source VHD's root files
(KERNEL.SYS → FreeDOS, IBMBIO.COM → Compaq, ``[Paths]`` MSDOS.SYS
→ MS-DOS 7.10, else MS-DOS 6.22) the same way the Linux CLI / TUI
do since v0.9.35, so the user doesn't have to remember which DOS
family the VHD was built with.

Pressing **Grow** runs the same :func:`dosforge.grow.grow_vhd` API
the CLI invokes, surfacing any :class:`ValidationError` in the
status bar / log panel.  Per-step progress messages
(``Step 3/8: Extracting...`` etc.) are streamed live into the
output panel via ``progress_callback`` (v0.9.34 parity).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..errors import DosForgeError, ValidationError
from ..grow import GROWABLE_BOOT_MODES, GrowManifest, StagingSource, grow_vhd
from ..inspect import inspect_vhd
from ..size import parse_size
from .widgets import Card


_GROW_HELP_TEXT = """Grow VHD — supported modes and limits

Supported boot modes (4):
  • FreeDOS              — FAT16 (up to ~2 GiB) or FAT32 (up to ~32 GiB practical)
  • MS-DOS 7.10 / Win95  — FAT16 (up to ~2 GiB) or FAT32 (up to ~32 GiB practical)
  • MS-DOS 6.22          — FAT16 (up to ~2 GiB)
  • Compaq DOS 3.31      — FAT16 BIGDOS (up to ~504 MiB)

dosforge auto-detects the boot mode from the source VHD's root files
(KERNEL.SYS → FreeDOS, IBMBIO.COM → Compaq, MSDOS.SYS [Paths] header
→ MS-DOS 7.10, else MS-DOS 6.22). You don't have to pick anything.

Hard limits:
  • Container   : VHD only (fixed-format Microsoft Virtual PC).
                  No dynamic / differencing VHDs.
                  No floppy IMGs (.img / .ima / .vfd) — rebuild with
                  'dosforge create'.
  • Direction   : grow only. Never shrinks.
  • Cluster band: the new size must stay within the same cluster band
                  as the source (mformat picks different cluster sizes
                  at certain thresholds). Crossing a band is rejected
                  after extraction with a clear error.

What it preserves:
  • All system files (IO.SYS / KERNEL.SYS / MSDOS.SYS / COMMAND.COM /
    IBMBIO.COM / IBMDOS.COM / …).
  • CONFIG.SYS, AUTOEXEC.BAT, FDCONFIG.SYS, FDAUTO.BAT.
  • Every user directory and file under C:\\, with mtimes preserved.

NOT supported — rebuild via 'dosforge create':
  • MS-DOS 2.x / 3.3 / 3.31 (32 MiB FAT12 cap)
  • DR-DOS 6.0 / 7.x
  • IBM PC-DOS 7.0 / 7.1 SGTK / PC-DOS 2000
  • MS-DOS 5.0
  • Any image that isn't a fixed-format VHD

The grow pipeline runs 8 steps end-to-end:
  1. Snapshot source VHD geometry
  2. Validate new size + cluster band
  3. Extract files from source VHD via mtools
  4. Build fresh VHD at the new size
  5. Inject extracted files into new VHD via batched mcopy
  6. Stage any additional host → DOS directories
  7. Headless boot probe (optional; ~60-90s) — verifies the new VHD
     actually boots before the swap
  8. Atomic swap (original → <target>.bak, new → target)
"""


class GrowView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self._theme = app.theme

        self.var_target = tk.StringVar()
        self.var_current = tk.StringVar(value="(select a VHD via Browse first)")
        self.var_new_size = tk.StringVar(value="")
        self.var_boot_probe = tk.BooleanVar(value=True)
        self.var_keep_backup = tk.BooleanVar(value=True)

        self._staging: list[tuple[Path, str]] = []

        self._build()
        self.refresh_target()

    def _build(self) -> None:
        card = Card(self, self.app.theme, title="Grow an existing VHD")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body
        body.columnconfigure(1, weight=1)
        body.rowconfigure(9, weight=1)

        # ── Supported-modes inline header ──────────────────────────
        supported_label = ttk.Label(
            body,
            text=(
                "Supported boot modes:\n"
                "  • FreeDOS / MS-DOS 7.10  - FAT16 \u2264 2 GiB,  FAT32 \u2264 32 GiB\n"
                "  • MS-DOS 6.22            - FAT16 \u2264 2 GiB\n"
                "  • Compaq DOS 3.31        - FAT16 BIGDOS \u2264 504 MiB\n"
                "Other boot modes must be rebuilt via 'dosforge create'.  "
                "Press ? for full details."
            ),
            style="Muted.TLabel",
            justify="left",
        )
        supported_label.grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        # ── Target row ─────────────────────────────────────────────
        ttk.Label(body, text="Target VHD:").grid(row=1, column=0, sticky="w", pady=(0, 4))
        target_row = ttk.Frame(body)
        target_row.grid(row=1, column=1, sticky="ew", pady=(0, 4))
        target_row.columnconfigure(0, weight=1)
        ttk.Entry(target_row, textvariable=self.var_target).grid(row=0, column=0, sticky="ew")
        ttk.Button(target_row, text="...", command=self._browse_target, takefocus=False).grid(
            row=0, column=1, padx=(8, 0)
        )

        ttk.Label(body, textvariable=self.var_current, style="Muted.TLabel").grid(
            row=2, column=1, sticky="w", pady=(0, 10)
        )

        # ── New size ───────────────────────────────────────────────
        ttk.Label(body, text="New size:").grid(row=3, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(body, textvariable=self.var_new_size, width=16).grid(
            row=3, column=1, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            body,
            text="Examples: 128M, 256M, 1G, 2G  (must be larger than current size + within the same cluster band)",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w", pady=(0, 10))

        # ── Options ────────────────────────────────────────────────
        opts = ttk.Frame(body)
        opts.grid(row=5, column=1, sticky="w", pady=(0, 10))
        ttk.Checkbutton(
            opts,
            text="Headless boot probe (verify the grown VHD boots before swap; adds ~60-90s)",
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
            text="Refresh VHD info",
            command=self.refresh_target,
            takefocus=False,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            action_row,
            text="?",
            width=3,
            command=self._show_help_dialog,
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
        """Read VHD metadata and pre-fill current-size + inferred boot mode.

        Errors (file missing, malformed VHD) are silently ignored;
        the form just stays empty/unchanged so the user can hand-fill.
        The inferred boot mode is *displayed only* — the grow backend
        auto-detects independently from root files at run time.
        """
        try:
            info = inspect_vhd(target)
        except (DosForgeError, OSError):
            self.var_current.set(f"(cannot read {target.name} — fill fields manually)")
            return
        current_size_mb = info.file_size_bytes / (1024 * 1024)
        if info.inferred_boot_mode is None:
            verdict = "?  Verdict unknown (auto-detect at grow time)"
        elif info.inferred_boot_mode in GROWABLE_BOOT_MODES:
            verdict = "\u2713 Growable"
        else:
            verdict = "\u2717 Not growable — rebuild via 'dosforge create'"
        self.var_current.set(
            f"Current: {current_size_mb:.0f} MiB  •  "
            f"{info.fat_format.value}  •  cluster {info.cluster_size_bytes:,} bytes  •  "
            f"inferred boot: {info.inferred_boot_mode.value if info.inferred_boot_mode else 'unknown (auto-detect at grow time)'}  •  "
            f"{verdict}"
        )

    def _show_help_dialog(self) -> None:
        """Open the Grow VHD supported-modes help dialog.

        Centered Toplevel modeled on the v0.9.39 staging dialog so
        the user can't miss it. Contains the full _GROW_HELP_TEXT in
        a scrollable Text widget.
        """
        dialog = tk.Toplevel(self)
        dialog.title("Grow VHD — help")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(True, True)

        container = ttk.Frame(dialog, padding=18)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Grow VHD — supported modes & limits",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        body_frame = ttk.Frame(container)
        body_frame.pack(fill="both", expand=True, pady=(8, 12))

        scroll = ttk.Scrollbar(body_frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            body_frame,
            wrap="word",
            relief="flat",
            borderwidth=0,
            height=24,
            width=80,
            yscrollcommand=scroll.set,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)

        pal = self.app.theme.palette
        text.configure(
            background=pal.surface_alt,
            foreground=pal.text,
            insertbackground=pal.text,
            font=("Consolas", 10),
        )
        text.insert("1.0", _GROW_HELP_TEXT)
        text.configure(state="disabled")

        def _close():
            dialog.destroy()

        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x")
        ttk.Button(
            btn_row,
            text="Close",
            command=_close,
            takefocus=False,
            style="Accent.TButton",
        ).pack(side="right")

        dialog.bind("<Return>", lambda _e: _close())
        dialog.bind("<Escape>", lambda _e: _close())
        dialog.protocol("WM_DELETE_WINDOW", _close)

        dialog.update_idletasks()
        parent = self.winfo_toplevel()
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
        except tk.TclError:
            px = py = 0
            pw = parent.winfo_screenwidth()
            ph = parent.winfo_screenheight()
        dw = max(dialog.winfo_reqwidth(), 640)
        dh = max(dialog.winfo_reqheight(), 480)
        x = px + max(0, (pw - dw) // 2)
        y = py + max(0, (ph - dh) // 3)
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

        dialog.wait_window()

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
        # Modal dialog asking for the DOS destination path.  Built as a
        # proper Toplevel that is centered over the main app window and
        # styled with header/body/footer rows so the user can't miss it
        # (early versions landed in the screen top-left at 1x1 px).
        dialog = tk.Toplevel(self)
        dialog.title("DOS destination path")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)

        # Body container with consistent padding.
        container = ttk.Frame(dialog, padding=18)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Stage directory to DOS path",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            container,
            text=f"Host source:\n{host_dir}",
            justify="left",
            wraplength=420,
        ).pack(anchor="w", pady=(8, 4))
        ttk.Label(
            container,
            text="DOS destination path (e.g. C:\\GAMES):",
            justify="left",
        ).pack(anchor="w", pady=(8, 4))

        var_dest = tk.StringVar(value="C:\\")
        entry = ttk.Entry(container, textvariable=var_dest, width=40)
        entry.pack(fill="x", pady=(0, 12))
        entry.focus_set()
        entry.icursor("end")

        result: dict[str, str | None] = {"dest": None}

        def _ok():
            result["dest"] = var_dest.get().strip()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x")
        ttk.Button(
            btn_row, text="Cancel", command=_cancel, takefocus=False
        ).pack(side="right")
        ttk.Button(
            btn_row,
            text="OK",
            command=_ok,
            takefocus=False,
            style="Accent.TButton",
        ).pack(side="right", padx=(0, 8))

        dialog.bind("<Return>", lambda _e: _ok())
        dialog.bind("<Escape>", lambda _e: _cancel())
        dialog.protocol("WM_DELETE_WINDOW", _cancel)

        # Center over the parent app window so the user can't miss it
        # in a corner of the screen.
        dialog.update_idletasks()
        parent = self.winfo_toplevel()
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
        except tk.TclError:
            px = py = 0
            pw = parent.winfo_screenwidth()
            ph = parent.winfo_screenheight()
        dw = max(dialog.winfo_reqwidth(), 460)
        dh = max(dialog.winfo_reqheight(), 220)
        x = px + max(0, (pw - dw) // 2)
        y = py + max(0, (ph - dh) // 3)
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

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

        if not target_str:
            self.app.status.set_status("Pick a target VHD first.", error=True)
            return
        if not new_size_str:
            self.app.status.set_status(
                "Enter a new size (e.g. 256M or 1G).", error=True
            )
            return

        try:
            new_size_bytes = parse_size(new_size_str)
        except ValidationError as exc:
            self.app.status.set_status(str(exc), error=True)
            return

        manifest = GrowManifest(
            target_vhd=Path(target_str),
            new_size_bytes=new_size_bytes,
            boot_mode=None,
            staging_sources=tuple(
                StagingSource(src=src, dest=dest) for src, dest in self._staging
            ),
            boot_probe=self.var_boot_probe.get(),
            keep_backup=self.var_keep_backup.get(),
        )

        # Reset output panel so the user sees a fresh per-step trace.
        self._write_output("")

        def work():
            # Each progress message just print()s -- the GUI worker
            # has redirected sys.stdout to a queue that pumps onto
            # the main thread and into the status log + this panel.
            def _on_progress(stage: str) -> None:
                print(stage, flush=True)

            grow_vhd(manifest, progress_callback=_on_progress)
            return manifest

        def done(_):
            backup = (
                f"  Backup: {manifest.target_vhd}.bak"
                if manifest.keep_backup
                else "  (no backup kept)"
            )
            self._append_output(
                f"\nGrew {manifest.target_vhd} to "
                f"{manifest.new_size_bytes:,} bytes.\n{backup}\n"
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

    def _append_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.insert("end", text)
        self._output.see("end")
        self._output.configure(state="disabled")

