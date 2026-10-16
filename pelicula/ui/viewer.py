"""Visualizador com comparação (dividido, lado a lado, original), zoom, tela cheia e arrastar-e-soltar."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from ..i18n import _
from . import icons, theme

MIN_ZOOM = 0.1  # 10%
MAX_ZOOM = 16.0  # 1600%
ZOOM_STEP = 1.25  # cada clique na lupa, tecla + / − ou passo da roda
MARGIN = 14  # borda em volta da imagem (0 na tela cheia)
IDLE_MS = 2500  # na tela cheia, some o cursor e a barra depois disso parado
HINT_MS = 4500


class Viewer(QWidget):
    openRequested = Signal()
    testRequested = Signal()
    filesDropped = Signal(list)
    zoomChanged = Signal(str)
    fullscreenExitRequested = Signal()

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
        self.fullscreen = False
        self.margin = MARGIN
        self._drag_split = False
        self._pan = None
        self._peek = False
        self._drop_hover = False
        self._idle = False
        self._hint = False
        self.label_proc = _("PELÍCULA")
        self._build_empty()
        self._build_hud()
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(IDLE_MS)
        self.idle_timer.timeout.connect(self._go_idle)
        self.hint_timer = QTimer(self)
        self.hint_timer.setSingleShot(True)
        self.hint_timer.setInterval(HINT_MS)
        self.hint_timer.timeout.connect(self._hide_hint)

    def _build_empty(self) -> None:
        self.empty = QWidget(self)
        lay = QVBoxLayout(self.empty)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.icon("film", theme.ACCENT, 64).pixmap(64, 64))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = QLabel(_("Arraste um vídeo ou uma imagem para cá"))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 15pt;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = QLabel(_("MP4, MOV, MKV, ProRes, DNxHR, PNG, TIFF, JPEG… ou arquivos .cube e presets .json"))
        s.setObjectName("Muted")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b1 = QPushButton("  " + _("Abrir arquivo"))
        b1.setObjectName("Primary")
        b1.setIcon(icons.icon("open", "#1b1205", 18))
        b1.clicked.connect(self.openRequested)
        b2 = QPushButton("  " + _("Usar cena de teste"))
        b2.setIcon(icons.icon("image", theme.TEXT, 18))
        b2.clicked.connect(self.testRequested)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)

    def _build_hud(self) -> None:
        """Barra flutuante da tela cheia: zoom e sair. Some com o mouse parado."""
        self.hud = QWidget(self)
        self.hud.setObjectName("ViewerHud")
        self.hud.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hud.setStyleSheet(
            "#ViewerHud { background: rgba(14, 13, 12, 215); border: 1px solid rgba(255, 255, 255, 38);"
            " border-radius: 12px; }"
            "#ViewerHud QToolButton { background: transparent; border: none; border-radius: 8px; padding: 5px 7px;"
            f" color: {theme.TEXT}; }}"
            "#ViewerHud QToolButton:hover { background: rgba(255, 255, 255, 30); }"
            f"#ViewerHud QLabel {{ color: {theme.TEXT}; padding: 0 2px; }}")
        hl = QHBoxLayout(self.hud)
        hl.setContentsMargins(6, 4, 6, 4)
        hl.setSpacing(2)

        def button(icon: str, tip: str, fn, text: str = "") -> QToolButton:
            b = QToolButton(self.hud)
            b.setIcon(icons.icon(icon, theme.TEXT, 18))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if text:
                b.setText(text)
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.clicked.connect(fn)
            hl.addWidget(b)
            return b

        self.hud_out = button("zoom_out", _("Menos zoom (−)"), lambda: self.zoom_step(-1))
        self.hud_pct = QLabel("")
        self.hud_pct.setMinimumWidth(52)
        self.hud_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(self.hud_pct)
        self.hud_in = button("zoom_in", _("Mais zoom (+)"), lambda: self.zoom_step(1))
        self.hud_fit = button("fit", _("Ajustar à tela (F)"), lambda: self.set_zoom(None))
        self.hud_exit = button("fullscreen_exit", _("Sair da tela cheia (Esc ou F11)"),
                               self.fullscreenExitRequested.emit, _("Sair"))
        self.hud.hide()

    def resizeEvent(self, e):
        self.empty.setGeometry(self.rect())
        self._place_hud()
        super().resizeEvent(e)
        if self.zoom is None:
            self._emit_zoom()

    def _place_hud(self) -> None:
        self.hud.adjustSize()
        self.hud.move(self.width() - self.hud.width() - 16, 16)

    # ------------------------------------------------------------ estado
    def set_images(self, proc: QImage | None, orig: QImage | None) -> None:
        old = self.proc.size() if self.proc is not None else None
        self.proc, self.orig = proc, orig
        self.empty.setVisible(proc is None and orig is None)
        if proc is not None and proc.size() != old:
            self._emit_zoom()
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def set_zoom(self, z: float | None) -> None:
        self.zoom = None if z is None else min(max(z, MIN_ZOOM), MAX_ZOOM)
        if z is None:
            self.center = QPointF(0.5, 0.5)
        self._emit_zoom()
        self.update()

    def _emit_zoom(self) -> None:
        s = self.scale()
        self.hud_pct.setText("" if s is None else f"{s * 100:.0f}%")
        self.zoomChanged.emit("fit" if self.zoom is None else f"{self.zoom:g}")

    def set_fullscreen(self, on: bool) -> None:
        """Modo de tela cheia da prévia: sem borda, fundo preto, barra flutuante e dica de teclas."""
        self.fullscreen = on
        self.margin = 0 if on else MARGIN
        self._idle = False
        self.idle_timer.stop()
        self.unsetCursor()
        if on:
            self._hint = True
            self.hint_timer.start()
            self.hud.show()
            self.hud.raise_()
            self._place_hud()
            self.idle_timer.start()
        else:
            self._hint = False
            self.hint_timer.stop()
            self.hud.hide()
        if self.zoom is None:
            self._emit_zoom()
        self.update()

    def _go_idle(self) -> None:
        if not self.fullscreen or self._pan is not None or self._drag_split or self.hud.underMouse():
            if self.fullscreen:
                self.idle_timer.start()
            return
        self._idle = True
        self.hud.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _wake(self) -> None:
        if not self.fullscreen:
            return
        if self._idle:
            self._idle = False
            self.unsetCursor()
            self.hud.show()
            self.hud.raise_()
        self.idle_timer.start()

    def _hide_hint(self) -> None:
        self._hint = False
        self.update()

    # ------------------------------------------------------------ geometria
    def _area(self) -> QRectF:
        m = self.margin
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def fit_scale(self) -> float | None:
        if self.proc is None:
            return None
        area = self._area()
        return min(area.width() / self.proc.width(), area.height() / self.proc.height())

    def scale(self) -> float | None:
        """Escala atual (1.0 = um pixel da prévia por pixel da tela); None sem imagem."""
        if self.proc is None:
            return None
        return self.fit_scale() if self.zoom is None else self.zoom

    def _scale(self, img: QImage, area: QRectF) -> float:
        if self.zoom is None:
            return min(area.width() / img.width(), area.height() / img.height())
        return self.zoom

    def _image_rect(self, img: QImage, area: QRectF) -> QRectF:
        s = self._scale(img, area)
        w, h = img.width() * s, img.height() * s
        if self.zoom is None:
            return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
        # Num eixo em que a imagem cabe inteira, ela fica centralizada (não dá para arrastar para fora).
        cx = area.center().x() - (self.center.x() - 0.5) * w if w > area.width() else area.center().x()
        cy = area.center().y() - (self.center.y() - 0.5) * h if h > area.height() else area.center().y()
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _pannable(self) -> bool:
        if self.proc is None or self.zoom is None:
            return False
        area = self._area()
        return self.proc.width() * self.zoom > area.width() or self.proc.height() * self.zoom > area.height()

    def zoom_step(self, direction: int, pos: QPointF | None = None) -> None:
        """Um passo de zoom (+1 aproxima, -1 afasta). Ao cruzar o "ajustar à tela", para nele."""
        if self.proc is None:
            return
        area = self._area()
        cur = self.scale()
        fit = self.fit_scale()
        new = cur * (ZOOM_STEP if direction > 0 else 1 / ZOOM_STEP)
        new = min(max(new, MIN_ZOOM), MAX_ZOOM)
        crossed = (cur < fit * 0.999 and new >= fit * 0.999) or (cur > fit * 1.001 and new <= fit * 1.001)
        if self.zoom is not None and crossed:
            self.set_zoom(None)
            return
        if abs(new - cur) < 1e-9:
            return
        self._zoom_at(new, pos if pos is not None else area.center())

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

    def _draw_hint(self, p: QPainter) -> None:
        text = _("Esc sai da tela cheia  •  + / − ou roda do mouse: zoom  •  arraste para mover  •  "
                 "C compara  •  Espaço reproduz")
        f = theme.font(9.5)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 36
        r = QRectF((self.width() - w) / 2, self.height() - 64, w, 36)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 13, 12, 215))
        p.drawRoundedRect(r, 18, 18)
        p.setPen(QColor(theme.TEXT))
        p.setFont(f)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000" if self.fullscreen else "#0b0a09"))
        if self._drop_hover:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(240, 166, 58, 18))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(12, 12, -12, -12), 16, 16)
        if self.proc is None:
            p.end()
            return
        area = self._area()
        proc = self.orig if (self._peek or self.mode == "orig") and self.orig is not None else self.proc
        if self.mode == "side" and self.orig is not None and not self._peek:
            half = (area.width() - 10) / 2
            for i, (img, lab) in enumerate(((self.orig, _("ORIGINAL")), (self.proc, self.label_proc))):
                sub = QRectF(area.left() + i * (half + 10), area.top(), half, area.height())
                s = min(sub.width() / img.width(), sub.height() / img.height())
                r = QRectF(sub.center().x() - img.width() * s / 2, sub.center().y() - img.height() * s / 2,
                           img.width() * s, img.height() * s)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1)
                p.drawImage(r, img)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                self._pill(p, r.left() + 10, r.top() + 10, lab)
            if self._hint:
                self._draw_hint(p)
            p.end()
            return
        r = self._image_rect(proc, area)
        s = r.width() / proc.width()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
        p.drawImage(r, proc)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._peek or self.mode == "orig":
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, _("ORIGINAL"))
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
            self._pill(p, xs - 10, top + 10, _("ORIGINAL"), right=True)
            self._pill(p, xs + 10, top + 10, self.label_proc)
        else:
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, self.label_proc)
        if self._hint:
            self._draw_hint(p)
        p.end()

    # ------------------------------------------------------------ mouse
    def _split_x(self) -> float | None:
        if self.proc is None or self.mode != "split":
            return None
        r = self._image_rect(self.proc, self._area())
        return r.left() + r.width() * self.split

    def _hover_cursor(self, x: float) -> None:
        xs = self._split_x()
        if xs is not None and abs(x - xs) < 22:
            self.setCursor(Qt.CursorShape.SplitHCursor)
        elif self._pannable():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        self._wake()
        if self.proc is None:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._peek = True
            self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        xs = self._split_x()
        if xs is not None and (abs(e.position().x() - xs) < 22 or not self._pannable()):
            self._drag_split = True
            self._move_split(e.position().x())
        elif self._pannable():
            self._pan = (e.position(), QPointF(self.center))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _move_split(self, x: float) -> None:
        r = self._image_rect(self.proc, self._area())
        self.split = min(max((x - r.left()) / max(r.width(), 1), 0.0), 1.0)
        self.update()

    def mouseMoveEvent(self, e):
        self._wake()
        if self._drag_split:
            self._move_split(e.position().x())
        elif self._pan is not None and self.proc is not None:
            start, c0 = self._pan
            r = self._image_rect(self.proc, self._area())
            d = e.position() - start
            self.center = QPointF(min(max(c0.x() - d.x() / r.width(), 0), 1), min(max(c0.y() - d.y() / r.height(), 0), 1))
            self.update()
        else:
            self._hover_cursor(e.position().x())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton and self._peek:
            self._peek = False
            self.update()
        self._drag_split = False
        self._pan = None
        self._hover_cursor(e.position().x())

    def mouseDoubleClickEvent(self, e):
        if self.proc is None or e.button() != Qt.MouseButton.LeftButton:
            return
        if self.zoom is None:
            self._zoom_at(1.0, e.position())
        else:
            self.set_zoom(None)

    def wheelEvent(self, e):
        self._wake()
        if self.proc is None or e.angleDelta().y() == 0:
            return
        self.zoom_step(1 if e.angleDelta().y() > 0 else -1, e.position())

    def _zoom_at(self, z: float, pos: QPointF) -> None:
        z = min(max(z, MIN_ZOOM), MAX_ZOOM)
        area = self._area()
        r = self._image_rect(self.proc, area)
        fx = min(max((pos.x() - r.left()) / r.width(), 0), 1)
        fy = min(max((pos.y() - r.top()) / r.height(), 0), 1)
        self.zoom = z
        w, h = self.proc.width() * z, self.proc.height() * z
        self.center = QPointF(fx - (pos.x() - area.center().x()) / w, fy - (pos.y() - area.center().y()) / h)
        self._emit_zoom()
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
