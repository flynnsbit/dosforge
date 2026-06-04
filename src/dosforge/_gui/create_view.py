"""The Create view: build a new VHD/IMG with dynamic, validated options."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .. import formlogic as fl
from ..errors import DosForgeError
from . import options as opt
from .widgets import Card, Field, ScrollableFrame


class _Combo:
    """A readonly ttk.Combobox that maps display labels <-> stored values.

    Constructed lazily inside a parent frame (typically a :class:`Field`'s
    inner frame) so the widget hierarchy matches the layout hierarchy.
    """

    def __init__(self, items: list[tuple[str, str]], on_change):
        self._items = items
        self._label_by_value = {value: label for label, value in items}
        self._value_by_label = {label: value for label, value in items}
        self._on_change = on_change
        self.var = tk.StringVar()
        self.widget: ttk.Combobox | None = None

    def build(self, parent) -> ttk.Combobox:
        self.widget = ttk.Combobox(
            parent,
            state="readonly",
            values=[label for label, _ in self._items],
            textvariable=self.var,
        )
        self.widget.bind("<<ComboboxSelected>>", lambda _e: self._on_change())
        return self.widget

    def get_value(self) -> str:
        return self._value_by_label.get(self.var.get(), "")

    def set_value(self, value: str) -> None:
        label = self._label_by_value.get(value)
        if label is None:
            return
        # Call .set() so the readonly display refreshes immediately —
        # binding the StringVar alone is unreliable across ttk implementations.
        if self.widget is not None:
            self.widget.set(label)
        else:
            self.var.set(label)


class CreateView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent)
        self.app = app
        self._theme = app.theme
        self._fields: dict[str, Field] = {}
        self._summary_rows: list[tuple[ttk.Label, ttk.Label]] = []
        self._building = True
        self._build()
        self._building = False
        self._write_state(fl.default_state())
        self._sync()

    # ── construction ───────────────────────────────────────────────────
    def _build(self) -> None:
        theme = self._theme
        scroller = ScrollableFrame(self, theme)
        scroller.pack(fill="both", expand=True)
        body = scroller.body
        body.columnconfigure(0, weight=1)
        self._scroller = scroller

        self.var_path = tk.StringVar()
        self.var_size = tk.StringVar()
        self.var_label = tk.StringVar()
        self.var_boot_assets = tk.StringVar()
        self.var_payload = tk.StringVar()
        self.var_freedos_url = tk.StringVar()
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_img_sysfmt = tk.BooleanVar(value=False)

        for _var in (
            self.var_path,
            self.var_label,
            self.var_boot_assets,
            self.var_payload,
            self.var_freedos_url,
        ):
            _var.trace_add("write", lambda *_: self._on_text_change())
        self.var_overwrite.trace_add("write", lambda *_: self._on_text_change())
        self.var_size.trace_add("write", lambda *_: self._on_text_change())

        # Combobox holders (widgets built lazily via factories below).
        self.combo_media = _Combo(opt.MEDIA_TYPE_OPTIONS, self._on_media_change)
        self.combo_machine = _Combo(opt.MACHINE_TARGET_OPTIONS, self._on_machine_change)
        self.combo_xebec = _Combo(
            opt.MARTYPC_XEBEC_DRIVE_TYPE_OPTIONS, self._on_xebec_change
        )
        self.combo_at = _Combo(opt.MARTYPC_AT_DRIVE_TYPE_OPTIONS, self._on_change)
        self.combo_bios = _Combo(opt.BIOS_DRIVE_TYPE_OPTIONS, self._on_change)
        self.combo_format = _Combo(opt.DISK_FORMAT_OPTIONS, self._on_change)
        self.combo_floppy = _Combo(opt.FLOPPY_OPTIONS, self._on_change)
        self.combo_boot = _Combo(opt.BOOT_MODE_OPTIONS, self._on_boot_change)
        self.combo_freedos = _Combo(opt.FREEDOS_SOURCE_OPTIONS, self._on_change)
        self.combo_profile = _Combo(opt.DOS_INSTALL_PROFILE_OPTIONS, self._on_change)
        self.combo_ibm = _Combo(opt.IBM_DOS_VERSION_OPTIONS, self._on_ibm_change)

        row = 0

        # ── Card: Output ───────────────────────────────────────────────
        out_card = Card(body, theme, title="Output")
        out_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        ob = out_card.body
        ob.columnconfigure(0, weight=1)
        self._add_field(
            ob, fl.FIELD_OUTPUT_PATH, "Output image path",
            lambda p: ttk.Entry(p, textvariable=self.var_path),
            row=0,
            browse_command=self._browse_output,
            help_text="Destination .vhd / .img file.",
        )
        self._add_field(
            ob, fl.FIELD_VOLUME_LABEL, "Volume label (optional)",
            lambda p: ttk.Entry(p, textvariable=self.var_label),
            row=1,
        )
        self._add_field(
            ob, fl.FIELD_OVERWRITE, "",
            lambda p: ttk.Checkbutton(
                p,
                text="Overwrite if the file already exists",
                variable=self.var_overwrite,
                takefocus=False,
            ),
            row=2,
        )

        # ── Card: Media & geometry ─────────────────────────────────────
        media_card = Card(body, theme, title="Media & geometry")
        media_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        mb = media_card.body
        mb.columnconfigure(0, weight=1)
        self._add_field(mb, fl.FIELD_MEDIA_TYPE, "Media type",
                        self.combo_media.build, row=0)
        self._add_field(mb, fl.FIELD_MACHINE_TARGET, "Machine target",
                        self.combo_machine.build, row=1)
        self._add_field(mb, fl.FIELD_MARTYPC_XEBEC, "Xebec drive type",
                        self.combo_xebec.build, row=2)
        self._add_field(mb, fl.FIELD_MARTYPC_AT, "AT/XT-IDE drive type",
                        self.combo_at.build, row=3)
        size_field = self._add_field(
            mb, fl.FIELD_SIZE, "Size (e.g. 512M, 32M, 1G)",
            lambda p: ttk.Entry(p, textvariable=self.var_size),
            row=4,
        )
        self._size_entry = size_field.control
        self._add_field(mb, fl.FIELD_BIOS_DRIVE, "BIOS drive preset",
                        self.combo_bios.build, row=5)
        self._add_field(mb, fl.FIELD_FORMAT, "Filesystem",
                        self.combo_format.build, row=6)
        self._add_field(mb, fl.FIELD_FLOPPY, "Floppy size",
                        self.combo_floppy.build, row=7)
        self._add_field(
            mb, fl.FIELD_IMG_SYSTEM_FORMAT, "",
            lambda p: ttk.Checkbutton(
                p,
                text="Install DOS system files (make floppy bootable)",
                variable=self.var_img_sysfmt,
                command=self._on_img_sysfmt_change,
                takefocus=False,
            ),
            row=8,
        )

        # ── Card: Boot ─────────────────────────────────────────────────
        boot_card = Card(body, theme, title="Boot")
        boot_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        bb = boot_card.body
        bb.columnconfigure(0, weight=1)
        self._add_field(bb, fl.FIELD_BOOT_MODE, "Boot mode",
                        self.combo_boot.build, row=0)
        self._add_field(bb, fl.FIELD_FREEDOS_SOURCE, "FreeDOS source",
                        self.combo_freedos.build, row=1)
        self._add_field(
            bb, fl.FIELD_FETCH_FREEDOS, "",
            lambda p: ttk.Button(
                p,
                text="Download FreeDOS assets",
                command=self._fetch_freedos,
                takefocus=False,
            ),
            row=2,
        )
        self._add_field(bb, fl.FIELD_DOS_PROFILE, "DOS install profile",
                        self.combo_profile.build, row=3)
        self._add_field(bb, fl.FIELD_IBM_DOS_VERSION, "IBM DOS version",
                        self.combo_ibm.build, row=4)

        # ── Card: Assets & payload ─────────────────────────────────────
        assets_card = Card(body, theme, title="Assets & payload")
        assets_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        ab = assets_card.body
        ab.columnconfigure(0, weight=1)
        self._add_field(
            ab, fl.FIELD_BOOT_ASSETS, "Boot assets directory",
            lambda p: ttk.Entry(p, textvariable=self.var_boot_assets),
            row=0,
            browse_command=self._browse_boot_assets,
        )
        self._add_field(
            ab, fl.FIELD_CUSTOM_PAYLOAD, "Custom payload directory",
            lambda p: ttk.Entry(p, textvariable=self.var_payload),
            row=1,
            browse_command=self._browse_payload,
            help_text="Files copied into the image root after preparation.",
        )
        self._add_field(
            ab, fl.FIELD_FREEDOS_URL, "FreeDOS download URL (optional)",
            lambda p: ttk.Entry(p, textvariable=self.var_freedos_url),
            row=2,
        )

        # ── Card: Summary + Create ────────────────────────────────────
        summary_card = Card(body, theme, title="Summary")
        summary_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        sb = summary_card.body
        sb.columnconfigure(1, weight=1)
        for i in range(8):
            key = ttk.Label(sb, text="", style="Muted.TLabel")
            key.grid(row=i, column=0, sticky="w", padx=(0, 16), pady=1)
            val = ttk.Label(sb, text="")
            val.grid(row=i, column=1, sticky="w", pady=1)
            self._summary_rows.append((key, val))
        self._create_btn = ttk.Button(
            sb,
            text="Create image",
            style="Accent.TButton",
            command=self._create,
        )
        self._create_btn.grid(row=8, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _add_field(
        self, parent, key, label, factory, *, row, browse_command=None, help_text=None
    ) -> Field:
        field = Field(
            parent, self._theme, key, label, factory,
            browse_command=browse_command, help_text=help_text,
        )
        field.place_at(row)
        self._fields[key] = field
        return field

    # ── state read/write ───────────────────────────────────────────────
    def _read_state(self) -> fl.FormState:
        return fl.FormState(
            media_type=self.combo_media.get_value(),
            machine_target=self.combo_machine.get_value(),
            martypc_xebec_drive_type=self.combo_xebec.get_value(),
            martypc_at_drive_type=self.combo_at.get_value(),
            output_path=self.var_path.get(),
            size_text=self.var_size.get(),
            bios_drive_type=self.combo_bios.get_value(),
            disk_format=self.combo_format.get_value(),
            floppy_type=self.combo_floppy.get_value(),
            img_system_format=bool(self.var_img_sysfmt.get()),
            boot_mode=self.combo_boot.get_value(),
            freedos_source=self.combo_freedos.get_value(),
            dos_profile=self.combo_profile.get_value(),
            ibm_dos_version=self.combo_ibm.get_value(),
            boot_assets=self.var_boot_assets.get(),
            custom_payload=self.var_payload.get(),
            freedos_url=self.var_freedos_url.get(),
            volume_label=self.var_label.get(),
            overwrite=bool(self.var_overwrite.get()),
        )

    def _write_state(self, state: fl.FormState) -> None:
        prev = self._building
        self._building = True
        try:
            self._write_state_inner(state)
        finally:
            self._building = prev

    def _write_state_inner(self, state: fl.FormState) -> None:
        self.combo_media.set_value(state.media_type)
        self.combo_machine.set_value(state.machine_target)
        self.combo_xebec.set_value(state.martypc_xebec_drive_type)
        self.combo_at.set_value(state.martypc_at_drive_type)
        self.var_path.set(state.output_path)
        self.var_size.set(state.size_text)
        self.combo_bios.set_value(state.bios_drive_type)
        self.combo_format.set_value(state.disk_format)
        self.combo_floppy.set_value(state.floppy_type)
        self.var_img_sysfmt.set(state.img_system_format)
        self.combo_boot.set_value(state.boot_mode)
        self.combo_freedos.set_value(state.freedos_source)
        self.combo_profile.set_value(state.dos_profile)
        self.combo_ibm.set_value(state.ibm_dos_version)
        self.var_boot_assets.set(state.boot_assets)
        self.var_payload.set(state.custom_payload)
        self.var_freedos_url.set(state.freedos_url)
        self.var_label.set(state.volume_label)
        self.var_overwrite.set(state.overwrite)

    # ── change handlers ────────────────────────────────────────────────
    def _on_change(self) -> None:
        self._sync()

    def _on_text_change(self) -> None:
        if self._building:
            return
        self._refresh_summary(self._read_state())

    def _coerce(self, fn) -> None:
        state = self._read_state()
        state = fn(state)
        self._write_state(state)
        self._sync()

    def _on_media_change(self) -> None:
        self._coerce(fl.coerce_on_media_change)

    def _on_machine_change(self) -> None:
        self._coerce(fl.coerce_on_machine_change)

    def _on_xebec_change(self) -> None:
        self._coerce(fl.coerce_on_xebec_drive_change)

    def _on_boot_change(self) -> None:
        self._coerce(fl.coerce_on_boot_change)

    def _on_ibm_change(self) -> None:
        self._coerce(fl.coerce_on_ibm_version_change)

    def _on_img_sysfmt_change(self) -> None:
        self._coerce(fl.coerce_on_img_system_format_change)

    # ── visibility / summary ───────────────────────────────────────────
    def _sync(self) -> None:
        if self._building:
            return
        state = self._read_state()
        visible = fl.visible_fields(state)
        disabled = fl.disabled_fields(state)
        always = {
            fl.FIELD_OUTPUT_PATH,
            fl.FIELD_VOLUME_LABEL,
            fl.FIELD_OVERWRITE,
            fl.FIELD_MEDIA_TYPE,
        }
        for key, field in self._fields.items():
            field.set_visible(key in always or key in visible)

        if fl.FIELD_SIZE in disabled:
            self.var_size.set(fl.effective_size_text(state))
            self._size_entry.configure(state="readonly")
        else:
            self._size_entry.configure(state="normal")

        self._refresh_summary(state)

    def _refresh_summary(self, state: fl.FormState) -> None:
        rows = fl.build_summary(state)
        for i, (key_lbl, val_lbl) in enumerate(self._summary_rows):
            if i < len(rows):
                key_lbl.configure(text=rows[i][0])
                val_lbl.configure(text=rows[i][1])
            else:
                key_lbl.configure(text="")
                val_lbl.configure(text="")

    # ── browse dialogs ─────────────────────────────────────────────────
    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Choose output image",
            defaultextension=".vhd",
            filetypes=[
                ("Disk images", "*.vhd *.img *.ima *.vfd"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.var_path.set(path)

    def _browse_boot_assets(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Boot assets directory")
        if path:
            self.var_boot_assets.set(path)

    def _browse_payload(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Custom payload directory")
        if path:
            self.var_payload.set(path)

    # ── actions ────────────────────────────────────────────────────────
    def _fetch_freedos(self) -> None:
        url = self.var_freedos_url.get().strip() or None

        def work():
            return self.app.manager.fetch_freedos_assets(download_url=url)

        def done(target):
            self.var_boot_assets.set(str(target))
            self.combo_freedos.set_value("local")
            self._sync()

        self.app.run_operation(
            "fetch-freedos",
            work,
            done,
            busy_msg="Downloading FreeDOS assets...",
            success_msg="FreeDOS assets ready.",
        )

    def _create(self) -> None:
        try:
            request = fl.build_create_request(self._read_state())
        except DosForgeError as exc:
            self.app.status.set_status(str(exc), error=True)
            return

        def work():
            self.app.manager.create_and_prepare(request)
            return request.path.expanduser().resolve()

        def done(path: Path):
            self.app.set_selected_image(path)

        self.app.run_operation(
            "create",
            work,
            done,
            busy_msg=f"Creating {request.path}...",
            success_msg=f"Created and prepared: {request.path}",
        )

    def refresh_theme(self) -> None:
        self._scroller.refresh_theme()
