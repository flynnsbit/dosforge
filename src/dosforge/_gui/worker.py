"""Background operation worker for the dosforge GUI.

All :class:`~dosforge.disk.DiskManager` work runs on a single background
thread so the Tk event loop never blocks. Results are marshaled back onto the
main thread via a :class:`queue.Queue` that the GUI polls with ``root.after``.

There is no concurrency: only one operation runs at a time. There is no
cancellation — backend subprocess commands aren't safely killable — so the UI
shows a persistent "Working…" status instead of a fake Cancel button.

A line-buffered :class:`_LogStream` is installed in place of
``sys.stdout`` / ``sys.stderr`` for the lifetime of each operation so the
backend's progress prints stream into the GUI's log panel.
"""

from __future__ import annotations

import contextlib
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


class _LogStream:
    """File-like sink that queues text chunks for the main thread."""

    __slots__ = ("_q",)

    def __init__(self, q: "queue.Queue[str]") -> None:
        self._q = q

    def write(self, text: str) -> int:
        if text:
            self._q.put(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class OperationWorker:
    """Runs callables on a single worker thread and marshals results back.

    Parameters
    ----------
    root:
        The Tk root, used for ``after`` polling on the main thread.
    poll_ms:
        Polling interval for draining completed results.
    on_log:
        Optional callback receiving captured stdout/stderr text on the
        main thread (typically the StatusBar.append_log).
    """

    def __init__(
        self,
        root,
        poll_ms: int = 60,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self._root = root
        self._poll_ms = poll_ms
        self._on_log = on_log
        self._results: queue.Queue[tuple[OperationResult, Callable | None]] = (
            queue.Queue()
        )
        self._log_queue: queue.Queue[str] = queue.Queue()
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
        log_q = self._log_queue

        def runner() -> None:
            sink = _LogStream(log_q)
            # Redirect stdout+stderr so backend ``print()`` calls land in
            # the GUI log panel rather than disappearing into the void
            # (the bundled dosforge-gui.exe has no attached console).
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    try:
                        value = func()
                        result = OperationResult(operation, True, value=value)
                    except BaseException as exc:  # noqa: BLE001 - surfaced to UI
                        result = OperationResult(operation, False, error=exc)
            except Exception as exc:  # redirect_stdout itself failed
                result = OperationResult(operation, False, error=exc)
            self._results.put((result, on_done))

        self._thread = threading.Thread(
            target=runner, name=f"dosforge-op-{operation}", daemon=True
        )
        self._thread.start()
        return True

    def _drain(self) -> None:
        # Drain log lines first — even after completion any tail output
        # should make it to the UI before we report the result.
        if self._on_log is not None:
            try:
                while True:
                    chunk = self._log_queue.get_nowait()
                    try:
                        self._on_log(chunk)
                    except Exception:
                        pass
            except queue.Empty:
                pass

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
