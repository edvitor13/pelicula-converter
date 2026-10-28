"""Valores atuais dos parâmetros, com desfazer/refazer (e as chaves de animação do look)."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .. import keyframes, params


class ParamStore(QObject):
    """Valores de um esquema (`params.FILM` por padrão; o modo Edição usa os de `editparams`).

    `keys`: chaves de animação dos ajustes (`keyframes.py`; {ajuste: [Key]}), em quadros do arquivo ou da
    montagem que entra no look. Cada passo do desfazer guarda os valores e as chaves juntos. A interface das
    chaves (losangos na linha do tempo) fica para depois: `add_key`/`move_key`/`remove_key`/`keys_of`/`value_at`
    são a API dela.
    """

    changed = Signal(str)  # chave alterada, ou "*" quando tudo muda
    historyChanged = Signal()

    def __init__(self, values: dict[str, Any] | None = None, schema: params.Schema | None = None):
        super().__init__()
        self.schema = schema or params.FILM
        self.values = self.schema.sanitize(values or self.schema.defaults())
        self.keys: dict[str, list] = {}
        self._hist = [self._entry()]
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.commit)

    def _entry(self) -> tuple[dict[str, Any], dict[str, list]]:
        return copy.deepcopy(self.values), keyframes.to_json(self.keys)

    def _restore(self, entry) -> None:
        values, keys = entry
        self.values = copy.deepcopy(values)
        self.keys = keyframes.clean_keys(self.schema, keys)

    def get(self, key: str) -> Any:
        return self.values[key]

    def set(self, key: str, value: Any, record: bool = True) -> None:
        p = self.schema.params[key]
        if p.kind in params.LIST_KINDS:
            value = [float(c) for c in value]
        if self.values.get(key) == value:
            return
        self.values[key] = value
        self.changed.emit(key)
        if record:
            self._timer.start()

    def set_all(self, values: dict[str, Any], record: bool = True, keys: dict | None = None) -> None:
        """Troca todos os valores. `keys` (o JSON de `Project.look_keys`, ou {}) troca também as chaves; None
        mantém as que estão."""
        self._timer.stop()
        self.values = self.schema.sanitize(values)
        if keys is not None:
            self.keys = keyframes.clean_keys(self.schema, keys)
        self.changed.emit("*")
        if record:
            self.commit()

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.values)

    # ---------------------------------------------------------------- chaves de animação
    def keys_json(self) -> dict[str, list]:
        """As chaves no formato do projeto (`keyframes.to_json`)."""
        return keyframes.to_json(self.keys)

    def keys_of(self, key: str) -> list[tuple[float, Any, str]]:
        """Chaves de um ajuste: [(quadro, valor, curva)]."""
        return [(k.t, keyframes._copy(k.v), k.e) for k in self.keys.get(key, [])]

    def value_at(self, key: str, frame: float) -> Any:
        """O valor do ajuste no quadro (com as chaves; sem elas, o valor fixo)."""
        return self.values_at(frame)[key]

    def values_at(self, frame: float) -> dict[str, Any]:
        """Todos os ajustes no quadro (o que a receita do quadro usa: `keyframes.look_values_at`)."""
        return keyframes.values_at(self.schema, self.values, self.keys, frame)

    def add_key(self, key: str, frame: float, value: Any = None, easing: str = keyframes.LINEAR) -> bool:
        """Chave no quadro (`value` None = o valor que o ajuste tem ali; mesmo quadro = troca a chave)."""
        p = keyframes.animatable(self.schema).get(key)
        if p is None:
            raise KeyError(key)
        if value is None:
            value = self.value_at(key, frame)
        return self._set_track(key, keyframes.set_key(self.keys.get(key), float(frame), params._clean(p, value),
                                                      easing))

    def move_key(self, key: str, frame_from: float, frame_to: float) -> bool:
        return self._set_track(key, keyframes.move_key(self.keys.get(key), float(frame_from), float(frame_to)))

    def remove_key(self, key: str, frame: float) -> bool:
        return self._set_track(key, keyframes.remove_key(self.keys.get(key), float(frame)))

    def clear_keys(self, key: str | None = None) -> bool:
        """Tira a animação de um ajuste (ou de todos, com `key` None); o valor fixo volta a valer."""
        if key is None:
            if not self.keys:
                return False
            self.keys = {}
            self.changed.emit("*")
            self.commit()
            return True
        return self._set_track(key, [])

    def _set_track(self, key: str, track: list) -> bool:
        if track == self.keys.get(key, []):
            return False
        keys = dict(self.keys)
        if track:
            keys[key] = track
        else:
            keys.pop(key, None)
        self.keys = keys
        self.changed.emit(key)
        self.commit()  # cada mudança de chave é um passo do desfazer
        return True

    # ---------------------------------------------------------------- desfazer
    def commit(self) -> None:
        self._timer.stop()
        entry = self._entry()
        if self._hist[self._pos] != entry:
            self._hist = self._hist[: self._pos + 1] + [entry]
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
            self._restore(self._hist[self._pos])
            self.changed.emit("*")
            self.historyChanged.emit()

    def redo(self) -> None:
        self.commit()
        if self._pos < len(self._hist) - 1:
            self._pos += 1
            self._restore(self._hist[self._pos])
            self.changed.emit("*")
            self.historyChanged.emit()
