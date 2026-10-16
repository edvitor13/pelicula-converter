"""Valores atuais dos parâmetros, com desfazer/refazer."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .. import params


class ParamStore(QObject):
    changed = Signal(str)  # chave alterada, ou "*" quando tudo muda
    historyChanged = Signal()

    def __init__(self, values: dict[str, Any] | None = None):
        super().__init__()
        self.values = params.sanitize(values or params.defaults())
        self._hist = [copy.deepcopy(self.values)]
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.commit)

    def get(self, key: str) -> Any:
        return self.values[key]

    def set(self, key: str, value: Any, record: bool = True) -> None:
        p = params.PARAMS[key]
        if p.kind == "color":
            value = [float(c) for c in value]
        if self.values.get(key) == value:
            return
        self.values[key] = value
        self.changed.emit(key)
        if record:
            self._timer.start()

    def set_all(self, values: dict[str, Any], record: bool = True) -> None:
        self._timer.stop()
        self.values = params.sanitize(values)
        self.changed.emit("*")
        if record:
            self.commit()

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.values)

    def commit(self) -> None:
        self._timer.stop()
        if self._hist[self._pos] != self.values:
            self._hist = self._hist[: self._pos + 1] + [copy.deepcopy(self.values)]
            if len(self._hist) > 300:
                self._hist.pop(0)
            self._pos = len(self._hist) - 1
            self.historyChanged.emit()

    def can_undo(self) -> bool:
        return self._pos > 0 or self._timer.isActive()

    def can_redo(self) -> bool:
        return self._pos < len(self._hist) - 1

    def undo(self) -> None:
        self.commit()
        if self._pos > 0:
            self._pos -= 1
            self.values = copy.deepcopy(self._hist[self._pos])
            self.changed.emit("*")
            self.historyChanged.emit()

    def redo(self) -> None:
        self.commit()
        if self._pos < len(self._hist) - 1:
            self._pos += 1
            self.values = copy.deepcopy(self._hist[self._pos])
            self.changed.emit("*")
            self.historyChanged.emit()
