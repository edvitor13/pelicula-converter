"""Layouts que acompanham a largura dos painéis.

- `FlowLayout`: põe os itens lado a lado e quebra em linhas quando falta espaço (barras de
  ferramentas, botões de ajustes rápidos, grade de looks). Numa linha só, espaçadores que expandem
  (`add_stretch`) empurram os itens seguintes para a direita, como num QHBoxLayout.
- `AdaptiveBar`: barra que encolhe em etapas antes de quebrar a linha — primeiro os botões ficam só
  com o ícone (o texto vai para a dica), depois somem os itens opcionais.

Assim os painéis da janela podem ficar mais estreitos ou mais largos sem cortar opções.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QLabel, QLayout, QLayoutItem, QSizePolicy, QSpacerItem, QToolButton, QWidget,
                               QWidgetItem)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, hspacing: int = 4, vspacing: int = 4,
                 center_rows: bool = True):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = hspacing
        self._v = vspacing
        self._center = center_rows  # alinha os itens de cada linha pelo meio da altura

    # ------------------------------------------------------------ QLayout
    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def add_stretch(self) -> None:
        """Espaço que cresce quando tudo cabe numa linha (e some quando a linha quebra)."""
        self.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

    def add_spacing(self, w: int) -> None:
        self.addItem(QSpacerItem(w, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int) -> QLayoutItem | None:
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int) -> QLayoutItem | None:
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        m = self.contentsMargins()
        w = self.single_row_width()
        h = max((it.sizeHint().height() for it in self._visible() if not it.spacerItem()), default=0)
        return QSize(w, h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        m = self.contentsMargins()
        size = QSize()
        for it in self._visible():
            if not it.spacerItem():
                size = size.expandedTo(it.minimumSize())
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ------------------------------------------------------------ cálculo
    def _visible(self) -> list[QLayoutItem]:
        out = []
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            out.append(it)
        return out

    def _is_stretch(self, it: QLayoutItem) -> bool:
        sp = it.spacerItem()
        return sp is not None and bool(sp.expandingDirections() & Qt.Orientation.Horizontal)

    def single_row_width(self) -> int:
        """Largura para caber tudo numa linha só (com os espaços fixos, sem os que expandem)."""
        m = self.contentsMargins()
        items = [it for it in self._visible() if not self._is_stretch(it)]
        w = sum(it.sizeHint().width() for it in items) + self._h * max(0, len(items) - 1)
        return w + m.left() + m.right()

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        items = self._visible()
        # Quebra em linhas (espaçadores que expandem não ocupam lugar na conta).
        rows: list[list[QLayoutItem]] = []
        row: list[QLayoutItem] = []
        x = 0
        for it in items:
            if self._is_stretch(it):
                row.append(it)
                continue
            w = it.sizeHint().width()
            real = [r for r in row if not self._is_stretch(r)]
            if real and x + self._h + w > area.width():
                rows.append(row)
                row, x = [], 0
                real = []
            x += (self._h if real else 0) + w
            row.append(it)
        if row:
            rows.append(row)
        y = area.y()
        single = len(rows) == 1
        for r in rows:
            real = [it for it in r if not self._is_stretch(it)]
            if not real:
                continue
            height = max(it.sizeHint().height() for it in real)
            used = sum(it.sizeHint().width() for it in real) + self._h * (len(real) - 1)
            stretches = [it for it in r if self._is_stretch(it)] if single else []
            extra = max(0, area.width() - used)
            share = extra // len(stretches) if stretches else 0
            x = area.x()
            first = True
            for it in r:
                if self._is_stretch(it):
                    if stretches:
                        x += share
                    continue
                if not first:
                    x += self._h
                first = False
                hint = it.sizeHint()
                w = min(hint.width(), area.width())
                h = hint.height()
                if apply:
                    yy = y + (height - h) // 2 if self._center else y
                    it.setGeometry(QRect(QPoint(x, yy), QSize(w, h)))
                x += w
            y += height + self._v
        total = y - self._v - area.y() if rows else 0
        return max(0, total) + m.top() + m.bottom()


def flow_widget(widgets: list[QWidget], hspacing: int = 4, vspacing: int = 4) -> QWidget:
    """Um QWidget com os widgets dados num FlowLayout."""
    box = QWidget()
    lay = FlowLayout(box, hspacing, vspacing)
    lay.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        lay.addWidget(w)
    sp = box.sizePolicy()
    sp.setHeightForWidth(True)
    box.setSizePolicy(sp)
    return box


class AdaptiveBar(QWidget):
    """Barra (com FlowLayout ou QHBoxLayout) que encolhe em etapas para caber na largura.

    Etapa 0: tudo como foi montado. Etapa 1: os botões de `compact` ficam só com o ícone.
    Etapa 2: os widgets de `optional` somem. Se ainda não couber e o layout for um FlowLayout, a
    barra quebra em mais de uma linha.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.compact: list[QToolButton] = []
        self.optional: list[QWidget] = []
        self.level = 0
        self._busy = False
        self._compact_min = 0
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def set_adaptive(self, compact: list[QToolButton] = (), optional: list[QWidget] = ()) -> None:
        self.compact = [b for b in compact if b is not None]
        self.optional = [w for w in optional if w is not None]
        for b in self.compact:
            if b.text() and not b.toolTip():
                b.setToolTip(b.text())
        lay = self.layout()
        if lay is not None and not isinstance(lay, FlowLayout):
            # Barra de uma linha só: o mínimo é o da etapa mais compacta (o layout não impõe o seu).
            lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
            self._apply(2)
            lay.invalidate()
            self._compact_min = lay.minimumSize().width()
            self._apply(0)
        self._adapt(self.width())
        self.updateGeometry()

    def _needed(self) -> int:
        lay = self.layout()
        lay.invalidate()
        if isinstance(lay, FlowLayout):
            return lay.single_row_width()
        return lay.sizeHint().width()

    def _apply(self, level: int) -> None:
        style = (Qt.ToolButtonStyle.ToolButtonIconOnly if level >= 1
                 else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for b in self.compact:
            if b.text() and b.toolButtonStyle() != style:
                b.setToolButtonStyle(style)
        for w in self.optional:
            hide = level >= 2
            if bool(w.property("adaptive_hidden")) != hide:
                w.setProperty("adaptive_hidden", hide)
                w.setVisible(not hide)

    def _adapt(self, width: int) -> None:
        if self._busy or width <= 0 or self.layout() is None:
            return
        self._busy = True
        try:
            for level in (0, 1, 2):
                self._apply(level)
                self.level = level
                if self._needed() <= width:
                    break
        finally:
            self._busy = False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._adapt(e.size().width())

    def minimumSizeHint(self) -> QSize:
        lay = self.layout()
        if lay is None:
            return super().minimumSizeHint()
        size = lay.minimumSize()
        if self._compact_min and not isinstance(lay, FlowLayout):
            size.setWidth(self._compact_min)
        return size

    def hasHeightForWidth(self) -> bool:
        lay = self.layout()
        return lay is not None and lay.hasHeightForWidth()

    def heightForWidth(self, w: int) -> int:
        lay = self.layout()
        return lay.heightForWidth(w) if lay is not None else -1


def widget_item(w: QWidget) -> QWidgetItem:
    return QWidgetItem(w)


class ElideLabel(QLabel):
    """Rótulo de uma linha que encolhe com o painel e corta o texto com "…" (o texto inteiro vai na dica)."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, r.width())
        p.drawText(r, int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()
