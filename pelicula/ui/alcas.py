"""1.9, alças na prévia (#68; ARQUITETURA §49.10 e §50): API genérica para uma ferramenta desenhar e arrastar pontos
por cima do quadro, só na tela (a exportação nunca passa por aqui).

O `Viewer` tem um lugar (`Viewer.set_handles`) e manda para ele, antes de tudo, o clique esquerdo, o arrasto, o soltar,
os dois cliques e o Esc (`MainWindow.keyPressEvent` → `Viewer.escape_handles`). A `VfxUI` põe ali uma `HandleStack`
com as alças de cada frente (`VfxUI.add_handles(nome, módulo, alças)`): só as de módulo ligado e `visible()` recebem
eventos, na ordem do registro; a primeira que aceita o clique fica com o arrasto até soltar.

Uma ferramenta implementa `Handles` (todos os métodos têm um padrão que não faz nada). As posições do mouse chegam em
pixels do widget; `View` leva da fração da imagem processada (0 a 1, y para baixo, como `Viewer.picked`) ao widget e
de volta. Para mexer em ajustes do clipe, use o `vstore` do inspetor (`ParamStore.set(..., record=False)`: a chave
automática no cursor quando o ajuste está animado, como os sliders) e feche o passo do desfazer no `release`
(`TimelineModel.commit`).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from . import theme

HIT_PX = 9.0          # distância (px do widget) que conta como clicar numa alça
HANDLE_PX = 5.0       # meio lado do quadradinho de uma alça


class View:
    """O retângulo da imagem processada no widget: fração da imagem ↔ ponto do widget."""

    def __init__(self, rect: QRectF):
        self.rect = QRectF(rect)

    def to_widget(self, fx: float, fy: float) -> QPointF:
        r = self.rect
        return QPointF(r.left() + float(fx) * r.width(), r.top() + float(fy) * r.height())

    def to_frac(self, pos: QPointF) -> tuple[float, float]:
        r = self.rect
        return (pos.x() - r.left()) / max(r.width(), 1e-6), (pos.y() - r.top()) / max(r.height(), 1e-6)


class Handles:
    """Alças de uma ferramenta (padrão: nada). `press` devolve True para ficar com o arrasto."""

    def visible(self) -> bool:
        return False

    def paint(self, p: QPainter, view: View) -> None:
        pass

    def press(self, view: View, pos: QPointF, modifiers) -> bool:
        return False

    def drag(self, view: View, pos: QPointF, modifiers) -> None:
        pass

    def release(self, view: View, pos: QPointF, modifiers) -> None:
        pass

    def double_click(self, view: View, pos: QPointF) -> bool:
        return False

    def cursor(self, view: View, pos: QPointF):
        """O cursor do mouse sobre a alça (Qt.CursorShape) ou None."""
        return None

    def escape(self) -> bool:
        """Esc: cancela o que está pela metade. True se havia algo."""
        return False


class HandleStack(Handles):
    """As alças das ferramentas registradas, filtradas por módulo ligado (`on`) e `visible()`."""

    def __init__(self):
        self.items: list[tuple[str, str, Handles]] = []
        self.on: set[str] = set()
        self._active: Handles | None = None

    def add(self, name: str, module_id: str, handles: Handles) -> None:
        self.items = [x for x in self.items if x[0] != name] + [(name, module_id, handles)]

    def shown(self) -> list[Handles]:
        return [h for _n, m, h in self.items if m in self.on and h.visible()]

    def visible(self) -> bool:
        return bool(self.shown())

    def paint(self, p, view) -> None:
        for h in self.shown():
            p.save()
            h.paint(p, view)
            p.restore()

    def press(self, view, pos, modifiers) -> bool:
        for h in reversed(self.shown()):  # a última registrada fica por cima
            if h.press(view, pos, modifiers):
                self._active = h
                return True
        return False

    def drag(self, view, pos, modifiers) -> None:
        if self._active is not None:
            self._active.drag(view, pos, modifiers)

    def release(self, view, pos, modifiers) -> None:
        h, self._active = self._active, None
        if h is not None:
            h.release(view, pos, modifiers)

    def double_click(self, view, pos) -> bool:
        return any(h.double_click(view, pos) for h in reversed(self.shown()))

    def cursor(self, view, pos):
        for h in reversed(self.shown()):
            shape = h.cursor(view, pos)
            if shape is not None:
                return shape
        return None

    def escape(self) -> bool:
        return any([h.escape() for _n, m, h in self.items if m in self.on])


# ------------------------------------------------------------------ desenho comum
def pen(color: str | QColor = "", width: float = 1.5, dash: bool = False) -> QPen:
    pn = QPen(QColor(color or theme.ACCENT_HI), width)
    if dash:
        pn.setStyle(Qt.PenStyle.DashLine)
    return pn


def draw_square(p: QPainter, at: QPointF, filled: bool = True) -> None:
    """Uma alça quadrada (contorno escuro para aparecer em qualquer imagem)."""
    r = QRectF(at.x() - HANDLE_PX, at.y() - HANDLE_PX, 2 * HANDLE_PX, 2 * HANDLE_PX)
    p.setPen(QPen(QColor(0, 0, 0, 200), 1))
    p.setBrush(QColor(theme.ACCENT_HI) if filled else QColor("#f6eee2"))
    p.drawRect(r)


def draw_dot(p: QPainter, at: QPointF, radius: float = HANDLE_PX) -> None:
    p.setPen(QPen(QColor(0, 0, 0, 200), 1))
    p.setBrush(QColor("#f6eee2"))
    p.drawEllipse(at, radius, radius)


def near(a: QPointF, b: QPointF, px: float = HIT_PX) -> bool:
    return (a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2 <= px * px
