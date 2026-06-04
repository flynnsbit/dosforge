"""Background operation worker for the dosforge GUI.

All :class:`~dosforge.disk.DiskManager` work runs on a single background
thread so the Tk event loop never blocks. Results are marshaled back onto the
main thread via a :class:`queue.Queue` that the GUI polls with ``root.after``.

There is no concurrency: only one operation runs at a time. There is no
cancellation — backend subprocess commands aren't safely killable — so the UI
shows a persistent "Working…" status instead of a fake Cancel button.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OperationResult:
    """Outcome of a background operation."""

    operation: str
    ok: bool
    value: Any = None
    error: BaseException | None = None


class OperationWorker:
    """Runs callables on a single worker thread and marshals results back.

    Parameters
    ----------
    root:
        The Tk root, used for ``after`` polling on the main thread.
    poll_ms:
        Polling interval for draining completed results.
    """

    def __init__(self, root, poll_ms: int = 60) -> None:
        self._root = root
        self._poll_ms = poll_ms
        self._results: queue.Queue[tuple[OperationResult, Callable | None]] = (
            queue.Queue()
        )
        self._busy = False
        self._thread: threading.Thread | None = None
        self._root.after(self._poll_ms, self._drain)

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(
        self,
        operation: str,
        func: Callable[[], Any],
        on_done: Callable[[OperationResult], None],
    ) -> bool:
        """Run ``func`` off-thread; call ``on_done`` on the main thread.

        Returns ``False`` (and does nothing) if an operation is already in
        flight, so callers can guard against double submission.
        """
        if self._busy:
            return False
        self._busy = True

        def runner() -> None:
            try:
                value = func()
                result = OperationResult(operation, True, value=value)
            except BaseException as exc:  # noqa: BLE001 - surfaced to UI
                result = OperationResult(operation, False, error=exc)
            self._results.put((result, on_done))

        self._thread = threading.Thread(
            target=runner, name=f"dosforge-op-{operation}", daemon=True
        )
        self._thread.start()
        return True

    def _drain(self) -> None:
        try:
            while True:
                result, on_done = self._results.get_nowait()
                self._busy = False
                if on_done is not None:
                    try:
                        on_done(result)
                    except Exception:
                        # A callback error must not kill the poll loop.
                        pass
        except queue.Empty:
            pass
        finally:
            self._root.after(self._poll_ms, self._drain)
