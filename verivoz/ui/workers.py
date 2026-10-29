"""Runs long tasks in threads without freezing the interface.

`run_task(fn, ...)` runs fn(*args, report=..., cancel=..., **kwargs) in a
QThread. Signals are relayed through an object living in the main thread, so
callbacks always run on the UI thread.
"""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.engine import Cancelled

_RUNNING: set = set()


class _Relay(QObject):
    progress = Signal(object)
    done = Signal(object)
    error = Signal(str)
    cancelled = Signal()


class _Worker(QObject):
    progress = Signal(object)
    done = Signal(object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, fn, args, kwargs, cancel_event):
        super().__init__()
        self.fn, self.args, self.kwargs, self.cancel_event = fn, args, kwargs, cancel_event

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, report=self.progress.emit, cancel=self.cancel_event, **self.kwargs)
        except Cancelled:
            self.cancelled.emit()
        except Exception:
            self.error.emit(traceback.format_exc())
        else:
            self.done.emit(result)


class Task:
    def __init__(self, fn, *args, on_progress=None, on_done=None, on_error=None, on_cancel=None, **kwargs):
        self.cancel_event = threading.Event()
        self.relay = _Relay()
        self.thread = QThread()
        self.worker = _Worker(fn, args, kwargs, self.cancel_event)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        for sig in ("progress", "done", "error", "cancelled"):
            getattr(self.worker, sig).connect(getattr(self.relay, sig))
        for sig in ("done", "error", "cancelled"):
            getattr(self.worker, sig).connect(self.thread.quit)
        if on_progress:
            self.relay.progress.connect(on_progress)
        if on_done:
            self.relay.done.connect(on_done)
        if on_error:
            self.relay.error.connect(on_error)
        if on_cancel:
            self.relay.cancelled.connect(on_cancel)
        self.thread.finished.connect(self._finished)
        _RUNNING.add(self)
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()

    def is_running(self) -> bool:
        return self.thread.isRunning()

    def wait(self, ms: int = 15000) -> bool:
        return self.thread.wait(ms)

    def _finished(self):
        _RUNNING.discard(self)


def run_task(fn, *args, **kwargs) -> Task:
    return Task(fn, *args, **kwargs)


def running_tasks() -> list[Task]:
    return list(_RUNNING)
