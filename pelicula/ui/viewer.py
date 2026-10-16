"""Visualizador com comparação (dividido, lado a lado, original), zoom e arrastar-e-soltar."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import icons, theme


class Viewer(QWidget):
    openRequested = Signal()
    testRequested = Signal()
    filesDropped = Signal(list)
    zoomChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 200)
        self.proc: QImage | None = None
        self.orig: QImage | None = None
        self.mode = "split"
        self.split = 0.5
        self.zoom: float | None = None  # None = ajustar à janela
        self.center = QPointF(0.5, 0.5)  # ponto da imagem no centro da tela (fração)
        self._drag_split = False
        self._pan = None
        self._peek = False
        self._drop_hover = False
        self.label_proc = "PELÍCULA"
        self._build_empty()

    def _build_empty(self) -> None:
        self.empty = QWidget(self)
        lay = QVBoxLayout(self.empty)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.icon("film", theme.ACCENT, 64).pixmap(64, 64))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = QLabel("Arraste um vídeo ou uma imagem para cá")
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 15pt;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = QLabel("MP4, MOV, MKV, ProRes, DNxHR, PNG, TIFF, JPEG… ou arquivos .cube e presets .json")
        s.setObjectName("Muted")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b1 = QPushButton("  Abrir arquivo")
        b1.setObjectName("Primary")
        b1.setIcon(icons.icon("open", "#1b1205", 18))
        b1.clicked.connect(self.openRequested)
        b2 = QPushButton("  Usar cena de teste")
        b2.setIcon(icons.icon("image", theme.TEXT, 18))
        b2.clicked.connect(self.testRequested)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)

    def resizeEvent(self, e):
        self.empty.setGeometry(self.rect())
        super().resizeEvent(e)

    # ------------------------------------------------------------ estado
    def set_images(self, proc: QImage | None, orig: QImage | None) -> None:
        self.proc, self.orig = proc, orig
        self.empty.setVisible(proc is None and orig is None)
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def set_zoom(self, z: float | None) -> None:
        self.zoom = z
        if z is None:
            self.center = QPointF(0.5, 0.5)
        self.zoomChanged.emit("fit" if z is None else f"{z:g}")
        self.update()

    # ------------------------------------------------------------ geometria
    def _scale(self, img: QImage, area: QRectF) -> float:
        if self.zoom is None:
            return min(area.width() / img.width(), area.height() / img.height())
        return self.zoom

    def _image_rect(self, img: QImage, area: QRectF) -> QRectF:
        s = self._scale(img, area)
        w, h = img.width() * s, img.height() * s
        if self.zoom is None:
            return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
        cx = area.center().x() - (self.center.x() - 0.5) * w
        cy = area.center().y() - (self.center.y() - 0.5) * h
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _pill(self, p: QPainter, x: float, y: float, text: str, right: bool = False) -> None:
        f = theme.font(8, title=True)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 1.2)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 18
        r = QRectF(x - w if right else x, y, w, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 13, 12, 190))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(QColor(theme.TEXT))
        p.setFont(f)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0b0a09"))
        if self._drop_hover:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(240, 166, 58, 18))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(12, 12, -12, -12), 16, 16)
        if self.proc is None:
            p.end()
            return
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        proc = self.orig if (self._peek or self.mode == "orig") and self.orig is not None else self.proc
        if self.mode == "side" and self.orig is not None and not self._peek:
            half = (area.width() - 10) / 2
            for i, (img, lab) in enumerate(((self.orig, "ORIGINAL"), (self.proc, self.label_proc))):
                sub = QRectF(area.left() + i * (half + 10), area.top(), half, area.height())
                s = min(sub.width() / img.width(), sub.height() / img.height())
                r = QRectF(sub.center().x() - img.width() * s / 2, sub.center().y() - img.height() * s / 2,
                           img.width() * s, img.height() * s)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1)
                p.drawImage(r, img)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                self._pill(p, r.left() + 10, r.top() + 10, lab)
            p.end()
            return
        r = self._image_rect(proc, area)
        s = r.width() / proc.width()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
        p.drawImage(r, proc)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._peek or self.mode == "orig":
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, "ORIGINAL")
        elif self.mode == "split" and self.orig is not None:
            xs = r.left() + r.width() * self.split
            clip = QRectF(r.left(), r.top(), xs - r.left(), r.height()).intersected(QRectF(self.rect()))
            p.save()
            p.setClipRect(clip)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
            p.drawImage(r, self.orig)
            p.restore()
            top = max(r.top(), 0)
            bot = min(r.bottom(), self.height())
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            p.drawLine(QPointF(xs, top), QPointF(xs, bot))
            cy = (top + bot) / 2
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(QColor("#f6eee2"))
            p.drawEllipse(QPointF(xs, cy), 15, 15)
            p.setPen(QPen(QColor("#1b1205"), 2))
            for sgn in (-1, 1):
                path = QPainterPath()
                path.moveTo(xs + sgn * 3, cy - 5)
                path.lineTo(xs + sgn * 8, cy)
                path.lineTo(xs + sgn * 3, cy + 5)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            self._pill(p, xs - 10, top + 10, "ORIGINAL", right=True)
            self._pill(p, xs + 10, top + 10, self.label_proc)
        else:
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, self.label_proc)
        p.end()

    # ------------------------------------------------------------ mouse
    def _split_x(self) -> float | None:
        if self.proc is None or self.mode != "split":
            return None
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        r = self._image_rect(self.proc, area)
        return r.left() + r.width() * self.split

    def mousePressEvent(self, e):
        if self.proc is None:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._peek = True
            self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        xs = self._split_x()
        if xs is not None and (abs(e.position().x() - xs) < 22 or self.zoom is None):
            self._drag_split = True
            self._move_split(e.position().x())
        elif self.zoom is not None:
            self._pan = (e.position(), QPointF(self.center))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _move_split(self, x: float) -> None:
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        r = self._image_rect(self.proc, area)
        self.split = min(max((x - r.left()) / max(r.width(), 1), 0.0), 1.0)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag_split:
            self._move_split(e.position().x())
        elif self._pan is not None and self.proc is not None:
            start, c0 = self._pan
            area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
            r = self._image_rect(self.proc, area)
            d = e.position() - start
            self.center = QPointF(min(max(c0.x() - d.x() / r.width(), 0), 1), min(max(c0.y() - d.y() / r.height(), 0), 1))
            self.update()
        else:
            xs = self._split_x()
            if xs is not None and abs(e.position().x() - xs) < 22:
                self.setCursor(Qt.CursorShape.SplitHCursor)
            elif self.zoom is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and self._peek:
            self._peek = False
            self.update()
        self._drag_split = False
        self._pan = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, e):
        if self.proc is None or e.button() != Qt.MouseButton.LeftButton:
            return
        if self.zoom is None:
            self._zoom_at(1.0, e.position())
        else:
            self.set_zoom(None)

    def wheelEvent(self, e):
        if self.proc is None:
            return
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        cur = self._scale(self.proc, area)
        factor = 1.25 if e.angleDelta().y() > 0 else 0.8
        fit = min(area.width() / self.proc.width(), area.height() / self.proc.height())
        new = cur * factor
        if new <= fit * 1.001:
            self.set_zoom(None)
            return
        self._zoom_at(min(new, 16.0), e.position())

    def _zoom_at(self, z: float, pos: QPointF) -> None:
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        r = self._image_rect(self.proc, area)
        fx = min(max((pos.x() - r.left()) / r.width(), 0), 1)
        fy = min(max((pos.y() - r.top()) / r.height(), 0), 1)
        self.zoom = z
        w, h = self.proc.width() * z, self.proc.height() * z
        self.center = QPointF(fx - (pos.x() - area.center().x()) / w, fy - (pos.y() - area.center().y()) / h)
        self.zoomChanged.emit(f"{z:g}")
        self.update()

    # ------------------------------------------------------------ arrastar arquivos
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragLeaveEvent(self, e):
        self._drop_hover = False
        self.update()

    def dropEvent(self, e):
        self._drop_hover = False
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        self.update()
