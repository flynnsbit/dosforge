"""Smoke tests for the Win32-ish Combobox polish helper.

These tests construct a hidden Tk root, so they are skipped on any
environment without a display / Tk runtime (CI for the Linux release
runner is headless; the Windows CI job has a desktop session via the
GitHub Actions windows-latest image).
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
ttk = pytest.importorskip("tkinter.ttk")


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless skip path
        pytest.skip(f"No Tk display available: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_polish_removes_combobox_wheel_class_binding(root):
    """The ``<MouseWheel>`` class binding on TCombobox should be empty."""

    from dosforge._gui.widgets import apply_combobox_polish

    # Sanity: Tk installs a non-empty binding by default on most builds.
    # We don't assert it's non-empty (some Tk builds ship empty), only
    # that after polish it is definitely empty.
    apply_combobox_polish(root)
    assert root.bind_class("TCombobox", "<MouseWheel>") == ""


def test_polish_is_idempotent(root):
    """Calling apply_combobox_polish twice must not raise or duplicate."""

    from dosforge._gui.widgets import apply_combobox_polish

    apply_combobox_polish(root)
    apply_combobox_polish(root)  # no exception, no duplicate install
    assert getattr(root, "_dosforge_combo_polish_installed", False) is True


def test_polish_installs_outside_click_handler(root):
    """A ``<Button-1>`` binding must be installed at the ``all`` level."""

    from dosforge._gui.widgets import apply_combobox_polish

    apply_combobox_polish(root)
    # bind_all() returns the registered Tcl script for the "all" tag.
    script = root.bind_all("<Button-1>")
    assert script, "expected a <Button-1> bind_all script to be present"


def test_outside_click_releases_combobox_focus(root):
    """Synthesizing a click outside the combobox must defocus it."""

    from dosforge._gui.widgets import apply_combobox_polish

    apply_combobox_polish(root)

    combo = ttk.Combobox(root, state="readonly", values=["a", "b"])
    combo.pack()
    label = ttk.Label(root, text="elsewhere")
    label.pack()
    root.update_idletasks()

    combo.focus_set()
    root.update_idletasks()
    if root.focus_get() is not combo:
        pytest.skip("window manager did not grant focus to the combobox")

    # Send a synthetic Button-1 to the unrelated label. We invoke the
    # bound handler directly via Tcl's `event generate` because the
    # window may not be mapped in the test environment.
    label.event_generate("<Button-1>", when="now")
    root.update_idletasks()

    focused = root.focus_get()
    assert focused is not combo, (
        f"expected focus to leave the combobox, still on: {focused!r}"
    )
