"""Browse view: a lazy filesystem tree to pick an existing disk image."""

from __future__ import annotations

from pathlib import Path
from tkinter import ttk

from .widgets import Card

_IMAGE_SUFFIXES = {".vhd", ".img", ".ima", ".vfd"}


class BrowseView(ttk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, style="Content.TFrame")
        self.app = app
        self._build()

    def _build(self) -> None:
        card = Card(self, title="Browse for a disk image")
        card.pack(fill="both", expand=True, padx=2, pady=2)
        body = card.body

        tree = ttk.Treeview(body, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree = tree
        tree.bind("<<TreeviewOpen>>", self._on_open)
        tree.bind("<<TreeviewSelect>>", self._on_select)

        controls = ttk.Frame(self, style="Content.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        self._use_btn = ttk.Button(
            controls,
            text="Use selected image",
            style="Accent.TButton",
            command=self._use_selected,
            state="disabled",
        )
        self._use_btn.pack(side="left")

        self._populate_roots()

    def _populate_roots(self) -> None:
        roots: list[Path] = []
        home = Path.home()
        roots.append(home)
        cwd = Path.cwd()
        if cwd != home:
            roots.append(cwd)
        import string
        import sys

        if sys.platform == "win32":
            for letter in string.ascii_uppercase:
                drive = Path(f"{letter}:\\")
                if drive.exists():
                    roots.append(drive)
        else:
            roots.append(Path("/"))

        for root in roots:
            node = self._tree.insert(
                "", "end", text=str(root), values=(str(root),), open=False
            )
            self._add_placeholder(node)

    def _add_placeholder(self, node: str) -> None:
        self._tree.insert(node, "end", text="…", values=("__placeholder__",))

    def _node_path(self, node: str) -> Path:
        return Path(self._tree.item(node, "values")[0])

    def _on_open(self, _event) -> None:
        node = self._tree.focus()
        children = self._tree.get_children(node)
        if children and self._tree.item(children[0], "values")[0] == "__placeholder__":
            self._tree.delete(children[0])
            self._fill(node)

    def _fill(self, node: str) -> None:
        path = self._node_path(node)
        try:
            entries = sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except OSError:
            return
        for entry in entries:
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                child = self._tree.insert(
                    node, "end", text=entry.name, values=(str(entry),), open=False
                )
                self._add_placeholder(child)
            elif entry.suffix.lower() in _IMAGE_SUFFIXES:
                self._tree.insert(
                    node, "end", text=entry.name, values=(str(entry),)
                )

    def _on_select(self, _event) -> None:
        node = self._tree.focus()
        if not node:
            return
        path = self._node_path(node)
        is_image = path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
        self._use_btn.configure(state="normal" if is_image else "disabled")

    def _use_selected(self) -> None:
        node = self._tree.focus()
        if not node:
            return
        path = self._node_path(node)
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
            self.app.set_selected_image(path.resolve())

    def refresh_theme(self) -> None:
        pass
