"""Painel de looks: miniaturas de cada preset aplicadas ao quadro atual."""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from . import theme

THUMB_W, THUMB_H = 122, 69


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


class LookThumb(QWidget):
    clicked = Signal(str)

    def __init__(self, pid: str, name: str, desc: str, parent=None):
        super().__init__(parent)
        self.pid, self.name = pid, name
        self.img: QImage | None = None
        self.selected = False
        self._hover = False
        self.setToolTip(f"<b>{name}</b><br>{desc}" if desc else name)
        self.setFixedSize(QSize(THUMB_W + 6, THUMB_H + 40))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_image(self, img: QImage | None) -> None:
        self.img = img
        self.update()

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.pid)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(3, 3, THUMB_W, THUMB_H)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.save()
        p.setClipPath(path)
        if self.img is not None:
            p.drawImage(r, self.img)
        else:
            p.fillRect(r, QColor(theme.PANEL3))
        if self._hover and not self.selected:
            p.fillRect(r, QColor(255, 255, 255, 22))
        p.restore()
        if self.selected:
            p.setPen(QPen(QColor(theme.ACCENT), 2.4))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 30 if self._hover else 14), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        f = theme.font(8.2, theme.QFont.Weight.DemiBold if self.selected else theme.QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(theme.ACCENT_HI if self.selected else theme.TEXT))
        fm = QFontMetrics(f)
        text = fm.elidedText(self.name, Qt.TextElideMode.ElideRight, (THUMB_W - 4) * 2 - 20)
        p.drawText(QRectF(4, THUMB_H + 7, THUMB_W - 2, 32),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
        p.end()


class LooksPanel(QWidget):
    presetChosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(THUMB_W * 2 + 42)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 6, 6)
        lay.setSpacing(8)
        k = QLabel("LOOKS")
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel("Presets de película")
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 12.5pt;")
        lay.addWidget(t)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar look…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)
        self.inner = QWidget()
        self.vl = QVBoxLayout(self.inner)
        self.vl.setContentsMargins(0, 0, 6, 0)
        self.vl.setSpacing(4)
        self.scroll.setWidget(self.inner)
        self.thumbs: dict[str, LookThumb] = {}
        self.groups: list[tuple[QLabel, QWidget, list[LookThumb]]] = []
        self.selected: str | None = None

    def rebuild(self, items: list[dict]) -> None:
        while self.vl.count():
            it = self.vl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        old = {pid: t.img for pid, t in self.thumbs.items()}
        self.thumbs.clear()
        self.groups.clear()
        order: list[str] = []
        by_group: dict[str, list[dict]] = {}
        for it in items:
            g = it["grupo"]
            if g not in by_group:
                by_group[g] = []
                order.append(g)
            by_group[g].append(it)
        for g in order:
            lab = QLabel(g.upper())
            lab.setObjectName("Kicker")
            lab.setStyleSheet(f"color: {theme.MUTED}; margin-top: 10px;")
            self.vl.addWidget(lab)
            box = QWidget()
            grid = QGridLayout(box)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(2)
            lst = []
            for i, it in enumerate(by_group[g]):
                th = LookThumb(it["id"], it["nome"], it.get("desc", ""))
                th.clicked.connect(self.presetChosen)
                th.set_image(old.get(it["id"]))
                th.selected = it["id"] == self.selected
                grid.addWidget(th, i // 2, i % 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.thumbs[it["id"]] = th
                lst.append(th)
            self.vl.addWidget(box)
            self.groups.append((lab, box, lst))
        self.vl.addStretch(1)
        self._filter(self.search.text())

    def set_images(self, images: dict[str, QImage]) -> None:
        for pid, img in images.items():
            if pid in self.thumbs:
                self.thumbs[pid].set_image(img)

    def set_selected(self, pid: str | None) -> None:
        self.selected = pid
        for k, t in self.thumbs.items():
            sel = k == pid
            if t.selected != sel:
                t.selected = sel
                t.update()

    def _filter(self, text: str) -> None:
        q = _norm(text.strip())
        for lab, box, lst in self.groups:
            grid: QGridLayout = box.layout()
            vis = [t for t in lst if not q or q in _norm(t.name)]
            for t in lst:
                grid.removeWidget(t)
                t.setVisible(t in vis)
            for i, t in enumerate(vis):
                grid.addWidget(t, i // 2, i % 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lab.setVisible(bool(vis))
            box.setVisible(bool(vis))
