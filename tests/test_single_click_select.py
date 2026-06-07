"""Regression tests for ``SingleClickSelect``.

These guard the single-click open/close behavior of the TUI's
``Select`` widget, which has been broken three times
(v0.7.5 / v0.7.7 / v0.7.8) by misreading the actual event order.
The root cause: when the user clicks the chevron of an already-open
dropdown, the ``SelectOverlay`` loses focus and posts
``Dismiss(lost_focus=True)`` BEFORE the ``MouseDown`` reaches the
``Select`` widget — so by the time ``_on_mouse_down`` fires,
``self.expanded`` has already been flipped to ``False`` by the
parent's dismiss handler, and naively re-opening would
re-display the dropdown immediately.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from dosforge.app import SingleClickSelect


class _Repro(App):
    def compose(self) -> ComposeResult:
        yield SingleClickSelect(
            [("None", "none"), ("FreeDOS", "freedos"), ("MS-DOS", "msdos")],
            value="none",
            id="sel",
        )
        yield Static("body", id="body")


def test_single_click_alternates_open_and_close() -> None:
    """Clicking the Select must alternate open/close on each click."""

    async def run() -> None:
        app = _Repro()
        async with app.run_test() as pilot:
            sel = app.query_one(SingleClickSelect)
            assert sel.expanded is False

            # First click opens the dropdown.
            await pilot.click("#sel")
            await pilot.pause()
            assert sel.expanded is True, "first click must open"

            # Second click on the (now open) chevron closes the
            # dropdown.  This is the case all of v0.7.5/v0.7.7/v0.7.8
            # got wrong.
            await pilot.click("#sel")
            await pilot.pause()
            assert sel.expanded is False, "second click must close"

            # Wait past the blur-dismiss grace window so the third
            # click is treated as a fresh open (not a debounced
            # re-open of the just-closed dropdown).
            await asyncio.sleep(
                SingleClickSelect._BLUR_DISMISS_GRACE_SECONDS * 2
            )

            # Third click re-opens.
            await pilot.click("#sel")
            await pilot.pause()
            assert sel.expanded is True, "third click must re-open"

            # Fourth click closes again.
            await pilot.click("#sel")
            await pilot.pause()
            assert sel.expanded is False, "fourth click must close again"

    asyncio.run(run())
