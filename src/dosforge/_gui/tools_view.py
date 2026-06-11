"""Image Tools view: read/extract files from an image via mtools (no admin)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..errors import DosForgeError
from .widgets import Card


class ToolsView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self.var_extract = tk.StringVar()
        self._build()
        self.refresh_target()

    def _build(self) -> None:
        card = Card(self, self.app.theme, title="Image tools (mtools)")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body
        body.columnconfigure(0, weight=1)

        self._target_lbl = ttk.Label(
            body, text="No image selected.", style="Muted.TLabel"
        )
        self._target_lbl.grid(row=0, column=0, sticky="w", pady=(0, 10))

        btn_row = ttk.Frame(body)
        btn_row.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            btn_row, text="Inspect VHD", command=self._inspect, takefocus=False
        ).pack(side="left")
        ttk.Button(
            btn_row, text="List contents", command=self._ls, takefocus=False
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            btn_row, text="Open in file manager", command=self._open, takefocus=False
        ).pack(side="left", padx=(8, 0))

        extract_row = ttk.Frame(body)
        extract_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        extract_row.columnconfigure(0, weight=1)
        ttk.Entry(extract_row, textvariable=self.var_extract).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            extract_row, text="Extract", command=self._extract, takefocus=False
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            body,
            text="Enter a DOS path to extract, e.g. /CONFIG.SYS",
            style="Muted.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(2, 12))

        out = tk.Text(body, height=16, wrap="none", relief="flat", borderwidth=0)
        out.grid(row=4, column=0, sticky="nsew")
        body.rowconfigure(4, weight=1)
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

    def refresh_target(self) -> None:
        image = self.app.selected_image
        if image is None:
            self._target_lbl.configure(text="No image selected.")
        else:
            self._target_lbl.configure(text=f"Selected image: {image}")

    def _image(self) -> Path | None:
        image = self.app.selected_image
        if image is None:
            self.app.status.set_status(
                "Select a .vhd / .img / .ima / .vfd file first (Browse).", error=True
            )
            return None
        return image

    def _write_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
        self._output.configure(state="disabled")

    def _inspect(self) -> None:
        image = self._image()
        if image is None:
            return
        from ..inspect import inspect_vhd

        def work():
            return inspect_vhd(image)

        def done(info):
            # Render the same human-readable summary the CLI prints.
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
            lines.append("")
            lines.append(f"  BPB OEM         : {info.bpb_oem!r}")
            lines.append(f"  FAT format      : {info.fat_format.value}")
            lines.append(
                f"  Cluster size    : {info.cluster_size_bytes:,} bytes "
                f"({info.bytes_per_sector} bytes/sector x {info.sectors_per_cluster} sectors/cluster)"
            )
            lines.append(f"  Cluster count   : {info.cluster_count:,}")
            lines.append(f"  Total sectors   : {info.total_sectors:,}")
            lines.append(f"  Reserved        : {info.reserved_sectors}")
            lines.append(f"  Num FATs        : {info.num_fats}")
            lines.append(f"  Sectors/FAT     : {info.sectors_per_fat}")
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
            lines.append("")
            if info.root_system_files:
                lines.append(f"  Root system files: {', '.join(info.root_system_files)}")
            else:
                lines.append("  Root system files: (none detected)")
            self._write_output("\n".join(lines))

        self.app.run_operation(
            "inspect",
            work,
            done,
            busy_msg=f"Inspecting {image.name}…",
            success_msg=f"Inspected {image.name}.",
        )

    def _ls(self) -> None:
        image = self._image()
        if image is None:
            return
        from .. import image_ops

        def work():
            return image_ops.ls(image, "/", all_files=True)

        def done(listing):
            self._write_output(listing or "(empty)")

        self.app.run_operation(
            "ls",
            work,
            done,
            busy_msg=f"Listing {image.name}…",
            success_msg=f"Listed {image.name}.",
        )

    def _extract(self) -> None:
        image = self._image()
        if image is None:
            return
        dos_path = self.var_extract.get().strip()
        if not dos_path:
            self.app.status.set_status(
                "Enter a DOS path to extract (e.g. /CONFIG.SYS).", error=True
            )
            return
        from .. import image_ops

        basename = dos_path.replace("\\", "/").rstrip("/").split("/")[-1] or "FILE"
        local_dest = image.parent / basename

        def work():
            return image_ops.get(image, dos_path, local_dest)

        def done(written):
            self._write_output(f"Extracted {image.name}:{dos_path} -> {written}")

        self.app.run_operation(
            "extract",
            work,
            done,
            busy_msg=f"Extracting {dos_path}…",
            success_msg=f"Extracted {dos_path}.",
        )

    def _open(self) -> None:
        image = self._image()
        if image is None:
            return
        try:
            self.app.manager.open_in_files(image.parent)
        except DosForgeError as exc:
            self.app.status.set_status(str(exc), error=True)
            return
        self.app.status.set_status(f"Opened {image.parent} in file manager.")

    def refresh_theme(self) -> None:
        self._apply_text_theme()
