"""Abas das sequências do projeto (#57, ARQUITETURA §41.6): uma fileira fina acima da linha do tempo do modo Edição.

Sempre visível, também com uma sequência só, com um "+" no fim: é por ali que se descobre que o projeto pode ter
várias. Aqui só se desenha e se ouve a pessoa; quem muda o projeto é o `TimelineModel` (cada operação, um passo do
desfazer) e a janela liga os dois.

- clique abre a aba; dois cliques (ou o menu) renomeiam ali mesmo; arrastar muda a ordem;
- botão direito: Renomear, Duplicar, Configurar…, Apagar (desligado quando só resta uma);
- os nomes se cortam com "…" e a dica traz o nome inteiro, o tamanho e os quadros por segundo;
- com abas demais para a largura, a roda do mouse anda pela fileira.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLineEdit, QMenu, QSizePolicy, QWidget

from ..i18n import _
from . import icons, theme

TAB_H = 30
TAB_MAX = 190         # largura da aba com bastante espaço
TAB_MIN = 70          # abaixo disto a fileira rola em vez de apertar mais
PLUS_W = 34
GAP = 3
ICON = 14
DRAG_PX = 6           # quanto o mouse anda antes de virar arrasto


@dataclass
class TabInfo:
    id: str
    name: str
    tip: str = ""


class SequenceTabs(QWidget):
    activated = Signal(str)            # id da aba escolhida
    addRequested = Signal()            # "+"
    renamed = Signal(str, str)         # (id, nome novo) — o nome digitado na aba
    duplicateRequested = Signal(str)
    settingsRequested = Signal(str)
    deleteRequested = Signal(str)
    moved = Signal(str, int)           # (id, posição nova) — arrastada

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceTabs")
        self.setFixedHeight(TAB_H + 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs: list[TabInfo] = []
        self.active = ""
        self._scroll = 0.0
        self._hover = -2                    # índice da aba sob o mouse; len(tabs) = o "+"; -1/-2 = nenhum
        self._press: tuple[int, QPoint] | None = None
        self._drag: dict | None = None      # {"i": índice de origem, "dx": deslocamento do mouse, "x": posição atual}
        self._editor: QLineEdit | None = None
        self._editing = ""
        self._plus = icons.icon("plus", theme.MUTED, 14)
        self._plus_hi = icons.icon("plus", theme.ACCENT_HI, 14)
        self._tab_icon = {False: icons.icon("sequence", theme.MUTED, ICON),
                          True: icons.icon("sequence", theme.ACCENT_HI, ICON)}

    # -------------------------------------------------------- API
    def set_tabs(self, tabs: list[TabInfo], active: str) -> None:
        if list(tabs) == self.tabs and active == self.active:
            return  # nada mudou (a janela avisa a cada mudança da montagem): o nome em edição e a rolagem ficam
        self._cancel_edit()
        self.tabs = list(tabs)
        self.active = active
        self._drag = None
        self._press = None
        self._clamp()
        self._reveal(active)
        self.update()

    def index_of(self, sid: str) -> int:
        return next((i for i, t in enumerate(self.tabs) if t.id == sid), -1)

    def tab_rect(self, i: int) -> QRectF:
        """O retângulo da aba `i` (do "+", se `i` == len(tabs)), já com a rolagem."""
        w = self._tab_w()
        x = GAP - self._scroll + i * (w + GAP)
        return QRectF(x, 3, PLUS_W if i >= len(self.tabs) else w, TAB_H)

    # -------------------------------------------------------- medidas
    def _avail(self) -> float:
        return max(1.0, self.width() - PLUS_W - GAP * 3)

    def _tab_w(self) -> float:
        n = max(1, len(self.tabs))
        return min(float(TAB_MAX), max(float(TAB_MIN), (self._avail() - GAP * (n - 1)) / n))

    def _content_w(self) -> float:
        return len(self.tabs) * (self._tab_w() + GAP)

    def _clamp(self) -> None:
        self._scroll = min(max(0.0, self._scroll), max(0.0, self._content_w() - self._avail()))

    def _reveal(self, sid: str) -> None:
        i = self.index_of(sid)
        if i < 0:
            return
        w = self._tab_w()
        left, right = i * (w + GAP), i * (w + GAP) + w
        if left < self._scroll:
            self._scroll = left
        elif right > self._scroll + self._avail():
            self._scroll = right - self._avail()
        self._clamp()

    def sizeHint(self) -> QSize:
        return QSize(400, TAB_H + 6)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, TAB_H + 6)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._clamp()
        self._reveal(self.active)

    def _at(self, pos: QPointF) -> int:
        """Índice da aba sob o ponto; len(tabs) = "+"; -1 = nenhuma."""
        if self._plus_rect().contains(pos):
            return len(self.tabs)
        if pos.x() < self.width() - PLUS_W - GAP * 2:  # a rolagem esconde as abas embaixo do "+"
            for i in range(len(self.tabs)):
                if self.tab_rect(i).contains(pos):
                    return i
        return -1

    def _plus_rect(self) -> QRectF:
        """O "+" fica logo depois da última aba, ou colado à direita quando a fileira rola."""
        x = min(GAP - self._scroll + self._content_w(), self.width() - PLUS_W - GAP)
        return QRectF(x, 3, PLUS_W, TAB_H)

    # -------------------------------------------------------- desenho
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), QColor(theme.BORDER))
        fm = QFontMetrics(theme.font(9))
        clip = QRectF(0, 0, self.width() - PLUS_W - GAP * 2, self.height())
        p.save()
        p.setClipRect(clip)
        order = [i for i in range(len(self.tabs)) if not (self._drag and self._drag["i"] == i)]
        for i in order:
            self._paint_tab(p, i, self.tab_rect(i), fm)
        if self._drag:
            r = self.tab_rect(self._drag["i"])
            r.moveLeft(self._drag["x"])
            self._paint_tab(p, self._drag["i"], r, fm, lifted=True)
            self._paint_slot(p)
        p.restore()
        pr = self._plus_rect()
        hot = self._hover == len(self.tabs)
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.PANEL2))
            p.drawRoundedRect(pr, 7, 7)
        (self._plus_hi if hot else self._plus).paint(p, pr.toRect(), Qt.AlignmentFlag.AlignCenter)
        p.end()

    def _paint_slot(self, p: QPainter) -> None:
        """A barra âmbar que mostra onde a aba arrastada vai cair."""
        to = self._drop_index()
        w = self._tab_w()
        x = GAP - self._scroll + to * (w + GAP) - GAP / 2 + (w + GAP if to > self._drag["i"] else 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(x - 1, 5, 2, TAB_H - 4), 1, 1)

    def _paint_tab(self, p: QPainter, i: int, r: QRectF, fm: QFontMetrics, lifted: bool = False) -> None:
        tab = self.tabs[i]
        on = tab.id == self.active
        hot = i == self._hover and not lifted
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        if lifted:
            p.setBrush(QColor(theme.PANEL3))
        elif on:
            p.setBrush(QColor(theme.PANEL3))
        elif hot:
            p.setBrush(QColor(theme.PANEL2))
        else:
            p.setBrush(QColor(theme.PANEL))
        p.drawPath(path)
        if on:
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(r.left() + 8, r.top(), r.width() - 16, 2.2), 1.1, 1.1)
        if lifted:
            p.setPen(QPen(QColor(theme.ACCENT_DIM), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        self._tab_icon[on].paint(p, int(r.left() + 9), int(r.center().y() - ICON / 2), ICON, ICON)
        tr = QRectF(r.left() + 9 + ICON + 6, r.top(), max(0.0, r.width() - ICON - 9 - 6 - 9), r.height())
        if self._editing == tab.id and self._editor is not None:
            return  # o campo do nome está sobre a aba
        p.setFont(theme.font(9, QFont.Weight.DemiBold if on else QFont.Weight.Normal))
        p.setPen(QColor(theme.TEXT if on or hot else theme.MUTED))
        text = fm.elidedText(tab.name, Qt.TextElideMode.ElideRight, int(tr.width()))
        p.drawText(tr, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)

    # -------------------------------------------------------- mouse
    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            i, start = self._press
            if self._drag is None and len(self.tabs) > 1 and (e.position().toPoint() - start).manhattanLength() > DRAG_PX:
                self._drag = {"i": i, "dx": start.x() - self.tab_rect(i).left(), "x": self.tab_rect(i).left()}
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._drag is not None:
                self._drag["x"] = pos.x() - self._drag["dx"]
                self.update()
            return
        hover = self._at(pos)
        if hover != self._hover:
            self._hover = hover
            if 0 <= hover < len(self.tabs):
                self.setToolTip(self.tabs[hover].tip or self.tabs[hover].name)
            else:
                self.setToolTip(_("Nova sequência") if hover == len(self.tabs) else "")
            self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._cancel_edit()
            i = self._at(e.position())
            if i == len(self.tabs):
                self.addRequested.emit()
            elif i >= 0:
                self._press = (i, e.position().toPoint())
                if self.tabs[i].id != self.active:
                    self.activated.emit(self.tabs[i].id)
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            drag, self._drag, self._press = self._drag, None, None
            self.unsetCursor()
            if drag is not None:
                self._drag = drag
                to = self._drop_index()
                self._drag = None
                if to != drag["i"]:
                    self.moved.emit(self.tabs[drag["i"]].id, to)
            self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        i = self._at(e.position())
        if e.button() == Qt.MouseButton.LeftButton and 0 <= i < len(self.tabs):
            self.rename(self.tabs[i].id)

    def leaveEvent(self, e) -> None:
        self._hover = -2
        self.update()
        super().leaveEvent(e)

    def wheelEvent(self, e) -> None:
        d = e.angleDelta().x() or e.angleDelta().y()
        if d and self._content_w() > self._avail():
            self._scroll += -d / 120 * (self._tab_w() + GAP)
            self._clamp()
            self.update()
            e.accept()
        else:
            super().wheelEvent(e)

    def _drop_index(self) -> int:
        """Onde a aba arrastada cai: pelo centro dela entre os centros das outras."""
        d = self._drag
        if d is None:
            return -1
        w = self._tab_w()
        centre = d["x"] + w / 2 + self._scroll - GAP
        return min(max(0, int(centre // (w + GAP))), len(self.tabs) - 1)

    # -------------------------------------------------------- menu e nome
    def contextMenuEvent(self, e) -> None:
        i = self._at(QPointF(e.pos()))
        if not 0 <= i < len(self.tabs):
            return
        self.menu_for(self.tabs[i].id).exec(e.globalPos())

    def menu_for(self, sid: str) -> QMenu:
        """O menu do botão direito numa aba."""
        menu = QMenu(self)
        menu.addAction(_("Renomear"), lambda: self.rename(sid))
        menu.addAction(_("Duplicar"), lambda: self.duplicateRequested.emit(sid))
        menu.addAction(_("Configurar…"), lambda: self.settingsRequested.emit(sid))
        menu.addSeparator()
        act = menu.addAction(_("Apagar"), lambda: self.deleteRequested.emit(sid))
        act.setEnabled(len(self.tabs) > 1)  # a última sequência do projeto não se apaga
        return menu

    def rename(self, sid: str) -> None:
        """Abre o campo de nome sobre a aba."""
        i = self.index_of(sid)
        if i < 0:
            return
        self._cancel_edit()
        self._reveal(sid)
        r = self.tab_rect(i)
        ed = QLineEdit(self.tabs[i].name, self)
        ed.setGeometry(int(r.left() + 6), int(r.top() + 3), int(r.width() - 12), int(r.height() - 6))
        ed.setFont(theme.font(9))
        ed.selectAll()
        ed.editingFinished.connect(self._finish_edit)
        self._editor, self._editing = ed, sid
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()
        self.update()

    def eventFilter(self, obj, ev):
        if obj is self._editor and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self._cancel_edit()
            return True
        return super().eventFilter(obj, ev)

    def _finish_edit(self) -> None:
        ed, sid = self._editor, self._editing
        if ed is None or self.sender() not in (None, ed):  # o aviso de um campo velho, que já saiu
            return
        text = ed.text().strip()
        self._editor, self._editing = None, ""
        ed.blockSignals(True)
        ed.deleteLater()
        self.update()
        old = next((t.name for t in self.tabs if t.id == sid), "")
        if text and text != old:
            self.renamed.emit(sid, text)

    def _cancel_edit(self) -> None:
        ed = self._editor
        if ed is not None:
            self._editor, self._editing = None, ""
            ed.blockSignals(True)
            ed.deleteLater()
            self.update()


__all__ = ["SequenceTabs", "TabInfo"]
