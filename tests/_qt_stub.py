# Qt-free stand-in for PySide6.QtCore so the worker imports headless: install()
# must run BEFORE mahad.worker is imported. Set MAHAD_REAL_QT=1 to skip stubbing.
from __future__ import annotations

import os
import sys
import types


class BoundSignal:
    # emit records into .emissions; connect/disconnect are inert
    def __init__(self) -> None:
        self.emissions: list[tuple] = []
        self._slots: list = []

    def connect(self, slot, *args, **kwargs) -> None:
        self._slots.append(slot)

    def disconnect(self, *args, **kwargs) -> None:
        self._slots.clear()

    def emit(self, *args) -> None:
        self.emissions.append(args)


class Signal:
    def __init__(self, *types_, **kwargs) -> None:
        self._name: str | None = None

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        key = f"__stub_signal_{self._name or id(self)}"
        sig = instance.__dict__.get(key)
        if sig is None:
            sig = BoundSignal()
            instance.__dict__[key] = sig
        return sig


def Slot(*args, **kwargs):
    def _wrap(fn):
        return fn
    return _wrap


class QTimer:
    # never fires on its own; tests drive the slots manually
    def __init__(self, parent=None) -> None:
        self.timeout = BoundSignal()
        self.interval_ms: int | None = None
        self.active = False

    def setInterval(self, ms: int) -> None:  # noqa: N802 (Qt API)
        self.interval_ms = int(ms)

    def start(self, *args) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    @staticmethod
    def singleShot(ms: int, fn) -> None:  # noqa: N802 (Qt API)
        # recorded, never run; scheduling is event-loop behaviour
        _SINGLESHOTS.append((ms, fn))


_SINGLESHOTS: list[tuple[int, object]] = []


class QObject:
    def __init__(self, parent=None) -> None:
        self._parent = parent


def install() -> bool:
    if os.environ.get("MAHAD_REAL_QT") == "1":
        return False
    if "mahad.worker" in sys.modules:           # already imported - too late
        return "PySide6.QtCore" in sys.modules and isinstance(
            sys.modules["PySide6.QtCore"], types.ModuleType)
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = QObject
    qtcore.QTimer = QTimer
    qtcore.Signal = Signal
    qtcore.Slot = Slot
    pyside = sys.modules.get("PySide6") or types.ModuleType("PySide6")
    pyside.QtCore = qtcore
    sys.modules.setdefault("PySide6", pyside)
    sys.modules["PySide6.QtCore"] = qtcore
    return True
