"""Chaves de animação na interface: os losangos.

- `KeyRows`: o losango (e as setas para a chave anterior e a próxima) ao lado de cada ajuste animável de um
  conjunto de `SectionCard` — o inspetor do clipe (modo Edição) e o painel do look (modo Película). Os
  controles mostram o valor no quadro do cursor (`ParamStore.view_frame` / `shown`); mexer num ajuste animado
  grava uma chave ali (chave automática, `ParamStore.set`); sem chaves, o controle troca o valor fixo como
  sempre.
- O **alvo** das chaves: `ClipKeys` (um clipe do `TimelineModel`, quadros da sequência) ou o próprio
  `ParamStore` do look (quadros do arquivo ou da montagem que entra no look). Os dois têm a mesma API:
  `add_key`, `remove_key`, `clear_keys`, `move_keys`, `remove_keys` (e `can_key`, opcional).
- `KeyStrip`: a faixa fina com as chaves do look ao longo do tempo (sob a barra da prévia no modo Película e na
  linha "Look" no alto da linha do tempo da Edição). Clique seleciona e leva o cursor; arrastar move (no
  quadro inteiro, com ímã no cursor); Delete apaga; Shift soma à seleção.
- `merged_marks` / `paint_diamond`: o que a linha do tempo usa para desenhar as chaves do clipe selecionado.

Nada aqui avalia chaves para a imagem: isso é só `keyframes.values_at` (pela receita do quadro).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from .. import keyframes
from ..i18n import _
from . import theme

NONE, ANIMATED, ON = "fixo", "animado", "chave"   # estados do losango
SNAP_PX = 8                                       # ímã do cursor ao arrastar chaves
HIT_PX = 6                                        # distância que ainda pega um losango


# ------------------------------------------------------------------ desenho
def diamond(cx: float, cy: float, r: float) -> QPolygonF:
    return QPolygonF([QPointF(cx, cy - r), QPointF(cx + r, cy), QPointF(cx, cy + r), QPointF(cx - r, cy)])


def paint_diamond(p: QPainter, cx: float, cy: float, r: float, fill: QColor | None, edge: QColor,
                  width: float = 1.3) -> None:
    p.setPen(QPen(edge, width))
    p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
    p.drawPolygon(diamond(cx, cy, r))


def merged_marks(keys: dict[str, list[keyframes.Key]], to_frame: Callable[[float], float] = float
                 ) -> list[tuple[float, list[str]]]:
    """As chaves de todos os ajustes juntas por quadro: [(quadro, [ajustes])], em ordem."""
    out: dict[float, list[str]] = {}
    for name, track in keys.items():
        for k in track:
            out.setdefault(round(float(to_frame(k.t)), 6), []).append(name)
    return sorted(out.items())


def param_names(schema, names) -> str:
    """Os nomes (traduzidos) dos ajustes, para a dica de um losango."""
    labels = []
    for n in names:
        p = schema.params.get(n)
        labels.append(_(p.label) if p is not None else n)
    return ", ".join(labels)


# ------------------------------------------------------------------ botões
class KeyButton(QToolButton):
    """O losango de um ajuste: cheio = há chave neste quadro; vazado = o ajuste está animado; apagado = valor
    fixo (clique grava a primeira chave)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = NONE
        self.setObjectName("KeyButton")
        self.setAutoRaise(True)
        self.setFixedSize(18, 18)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tip()

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._tip()
            self.update()

    def _tip(self) -> None:
        tips = {NONE: _("Animar: grava uma chave com o valor atual neste quadro. Botão direito: mais opções."),
                ANIMATED: _("Gravar uma chave neste quadro. Mexer no ajuste fora de uma chave também grava uma. "
                            "Botão direito: curva, remover, limpar."),
                ON: _("Há uma chave neste quadro. Mexer no ajuste troca o valor dela. Botão direito: curva, "
                      "remover, limpar.")}
        self.setToolTip(tips[self.state])

    def sizeHint(self) -> QSize:
        return QSize(18, 18)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse() and self.isEnabled()
        if not self.isEnabled():
            edge, fill = QColor(theme.BORDER), None
        elif self.state == ON:
            edge, fill = QColor(theme.ACCENT_HI if hover else theme.ACCENT), QColor(theme.ACCENT)
        elif self.state == ANIMATED:
            edge, fill = QColor(theme.ACCENT_HI if hover else theme.ACCENT), None
        else:
            edge, fill = QColor(theme.MUTED if hover else theme.FAINT), None
        paint_diamond(p, self.width() / 2, self.height() / 2, 5.0, fill, edge, 1.4)
        p.end()


class StepButton(QToolButton):
    """Seta para a chave anterior (-1) ou a próxima (+1) do ajuste."""

    def __init__(self, direction: int, parent=None):
        super().__init__(parent)
        self.direction = direction
        self.setObjectName("KeyPrev" if direction < 0 else "KeyNext")
        self.setAutoRaise(True)
        self.setFixedSize(12, 18)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(_("Ir para a chave anterior") if direction < 0 else _("Ir para a próxima chave"))

    def sizeHint(self) -> QSize:
        return QSize(12, 18)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(theme.TEXT if self.underMouse() else theme.MUTED) if self.isEnabled() else QColor(theme.BORDER)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        cx, cy, s = self.width() / 2, self.height() / 2, 3.2
        d = self.direction
        p.drawPolygon(QPolygonF([QPointF(cx - d * s, cy - s * 1.2), QPointF(cx + d * s, cy),
                                 QPointF(cx - d * s, cy + s * 1.2)]))
        p.end()


class KeyControl(QWidget):
    """[◀][◆][▶] de um ajuste. As setas só aparecem quando o ajuste está animado."""

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName(f"keys_{key}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 0, 0)
        lay.setSpacing(0)
        self.prev = StepButton(-1)
        self.button = KeyButton()
        self.next = StepButton(1)
        for w in (self.prev, self.button, self.next):
            lay.addWidget(w)
        self.prev.setVisible(False)
        self.next.setVisible(False)

    def set_state(self, state: str, enabled: bool, has_prev: bool, has_next: bool) -> None:
        self.button.set_state(state)
        self.button.setEnabled(enabled)
        animated = state != NONE
        self.prev.setVisible(animated)
        self.next.setVisible(animated)
        self.prev.setEnabled(has_prev)
        self.next.setEnabled(has_next)


# ------------------------------------------------------------------ alvos
class ClipKeys:
    """As chaves de um clipe da montagem, em quadros da sequência (`TimelineModel`). `clip_id()` diz qual."""

    def __init__(self, model, clip_id: Callable[[], str | None]):
        self.model = model
        self.clip_id = clip_id

    def _clip(self):
        cid = self.clip_id()
        return self.model.seq.find(cid) if cid else None

    def can_key(self, frame: float) -> bool:
        c = self._clip()
        return c is not None and not self.model.seq.locked(c) and c.start <= frame < c.end

    def add_key(self, key, frame, value=None, easing=keyframes.LINEAR) -> bool:
        c = self._clip()
        return c is not None and self.model.add_key(c.id, key, frame, value, easing)

    def remove_key(self, key, frame) -> bool:
        c = self._clip()
        return c is not None and self.model.remove_key(c.id, key, frame)

    def clear_keys(self, key=None) -> bool:
        c = self._clip()
        return c is not None and self.model.clear_keys(c.id, key)

    def move_keys(self, moves) -> bool:
        c = self._clip()
        return c is not None and self.model.move_keys(c.id, moves)

    def remove_keys(self, items) -> bool:
        c = self._clip()
        return c is not None and self.model.remove_keys(c.id, items)


# ------------------------------------------------------------------ losangos nos ajustes
class KeyRows(QObject):
    """Losangos nas linhas animáveis de `cards`, ligados às chaves de `store` (para ler) e de `target` (para
    gravar: o próprio `store`, no look, ou `ClipKeys`, no inspetor do clipe)."""

    seekRequested = Signal(int)

    def __init__(self, store, target, cards, parent=None):
        super().__init__(parent)
        self.store = store
        self.target = target
        self.cards = list(cards)
        self.anim = keyframes.animatable(store.schema)
        self.controls: dict[str, KeyControl] = {}
        for card in self.cards:
            for row in card.rows:
                key = row.param.key
                top = getattr(row, "top", None)
                if key not in self.anim or top is None or key in self.controls:
                    continue
                ctl = KeyControl(key)
                ctl.button.clicked.connect(lambda _c=False, k=key: self.add_key(k))
                ctl.button.customContextMenuRequested.connect(
                    lambda pos, k=key, b=ctl.button: self.menu_for(k).exec(b.mapToGlobal(pos)))
                ctl.prev.clicked.connect(lambda _c=False, k=key: self.step(k, -1))
                ctl.next.clicked.connect(lambda _c=False, k=key: self.step(k, 1))
                top.addWidget(ctl)
                self.controls[key] = ctl
        store.changed.connect(self._store_changed)
        self.update_states()

    # -------------------------------------------------------- cursor
    def set_frame(self, frame: float | None) -> None:
        """O cursor andou: os ajustes animados mostram o valor do novo quadro (só eles: barato na reprodução)."""
        frame = None if frame is None else float(frame)
        if frame == self.store.view_frame:
            return
        self.store.view_frame = frame
        for key in list(self.store.keys):
            for card in self.cards:
                if key in card.keys():
                    card.refresh(key)
        self.update_states()

    def can_key(self) -> bool:
        f = self.store.view_frame
        if f is None:
            return False
        check = getattr(self.target, "can_key", None)
        return check(f) if check is not None else True

    # -------------------------------------------------------- estados
    def state_of(self, key: str) -> str:
        if not self.store.keys.get(key):
            return NONE
        return ON if self.store.key_here(key) is not None else ANIMATED

    def _neighbors(self, key: str) -> tuple[float | None, float | None]:
        f = self.store.view_frame
        track = self.store.keys.get(key) or []
        if f is None or not track:
            return None, None
        before = [k.t for k in track if k.t < f - 1e-6]
        after = [k.t for k in track if k.t > f + 1e-6]
        return (before[-1] if before else None), (after[0] if after else None)

    def update_states(self, key: str | None = None) -> None:
        enabled = self.can_key()
        items = self.controls.items() if key is None else [(key, self.controls[key])] if key in self.controls else []
        for k, ctl in items:
            a, b = self._neighbors(k)
            ctl.set_state(self.state_of(k), enabled, a is not None, b is not None)

    def _store_changed(self, key: str) -> None:
        self.update_states(None if key == "*" else key)

    # -------------------------------------------------------- ações
    def add_key(self, key: str) -> bool:
        """Grava (ou atualiza) a chave do ajuste no quadro do cursor, com o valor que ele mostra."""
        if not self.can_key():
            return False
        here = self.store.key_here(key)
        return bool(self.target.add_key(key, self.store.view_frame, self.store.shown(key),
                                        here.e if here is not None else keyframes.LINEAR))

    def remove_key(self, key: str) -> bool:
        here = self.store.key_here(key)
        return here is not None and bool(self.target.remove_key(key, here.t))

    def clear(self, key: str) -> bool:
        return bool(self.store.keys.get(key)) and bool(self.target.clear_keys(key))

    def curve_key(self, key: str):
        """A chave cuja curva vale no cursor: a dali, senão a da esquerda (o trecho em que ele está)."""
        track = self.store.keys.get(key) or []
        if not track:
            return None
        here = self.store.key_here(key)
        if here is not None:
            return here
        f = self.store.view_frame
        left = [k for k in track if f is not None and k.t <= f]
        return left[-1] if left else track[0]

    def set_curve(self, key: str, easing: str) -> bool:
        k = self.curve_key(key)
        if k is None or easing not in keyframes.EASINGS or k.e == easing:
            return False
        return bool(self.target.add_key(key, k.t, k.v, easing))

    def step(self, key: str, direction: int) -> bool:
        a, b = self._neighbors(key)
        t = a if direction < 0 else b
        if t is None:
            return False
        self.seekRequested.emit(int(round(t)))
        return True

    def menu_for(self, key: str) -> QMenu:
        """O menu do botão direito do losango (curva, remover a chave, limpar a animação)."""
        m = QMenu()
        animated = bool(self.store.keys.get(key))
        a = m.addAction(_("Gravar chave neste quadro"), lambda: self.add_key(key))
        a.setObjectName("key_add")
        a.setEnabled(self.can_key())
        curve = m.addMenu(_("Curva até a próxima chave"))
        curve.setObjectName("key_curve")
        current = self.curve_key(key)
        curve.setEnabled(current is not None)
        for e in keyframes.EASINGS:
            act = curve.addAction(_(keyframes.EASING_LABELS[e]), lambda e=e: self.set_curve(key, e))
            act.setObjectName(f"curve_{e}")
            act.setCheckable(True)
            act.setChecked(current is not None and current.e == e)
        m.addSeparator()
        r = m.addAction(_("Remover a chave deste quadro"), lambda: self.remove_key(key))
        r.setObjectName("key_remove")
        r.setEnabled(self.store.key_here(key) is not None)
        c = m.addAction(_("Limpar a animação deste ajuste"), lambda: self.clear(key))
        c.setObjectName("key_clear")
        c.setEnabled(animated)
        return m


__all__ = ["ANIMATED", "ClipKeys", "KeyButton", "KeyControl", "KeyRows", "NONE", "ON", "StepButton",
           "diamond", "merged_marks", "paint_diamond", "param_names"]
