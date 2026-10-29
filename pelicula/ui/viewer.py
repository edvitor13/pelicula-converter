"""Visualizador com comparação (dividido, lado a lado, original), zoom, tela cheia e arrastar-e-soltar."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget

from .. import platforms
from ..i18n import _
from . import icons, theme

MIN_ZOOM = 0.1  # 10%
MAX_ZOOM = 16.0  # 1600%
ZOOM_STEP = 1.25  # cada clique na lupa, tecla + / − ou passo da roda
MARGIN = 14  # borda em volta da imagem (0 na tela cheia)
HINT_MS = 4500


class Viewer(QWidget):
    openRequested = Signal()
    testRequested = Signal()
    filesDropped = Signal(list)
    zoomChanged = Signal(str)
    picked = Signal(float, float)  # 1.6: conta-gotas — ponto clicado na imagem (fração 0 a 1, y para baixo)
    pickCanceled = Signal()

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
        self._hint = False
        self.safe_area = ""  # área segura desenhada por cima (platforms.SAFE_AREAS); "" = nenhuma
        self.label_proc = _("PELÍCULA")
        # 1.6 (`ui/preview_tools.py`, `ui/planes_ui.py`): só na tela, a exportação nunca passa por aqui.
        self.overlay: QImage | None = None      # zebra, falsa cor ou "Ver planos" por cima da prévia
        self.reference: QImage | None = None    # quadro fixado ou imagem para comparar
        self.compare_reference = False          # True: a comparação mostra a referência no lugar do original
        self._pick = False                      # conta-gotas ligado: o clique escolhe um ponto da imagem
        self._build_empty()
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

    def resizeEvent(self, e):
        self.empty.setGeometry(self.rect())
        super().resizeEvent(e)
        if self.zoom is None:
            self._emit_zoom()

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

    def set_overlay(self, img: QImage | None) -> None:
        """Imagem (RGBA, do tamanho da prévia) desenhada por cima do quadro processado. Só na tela."""
        self.overlay = img
        self.update()

    def set_reference(self, img: QImage | None) -> None:
        self.reference = img
        if img is None:
            self.compare_reference = False
        self.update()

    def set_compare_reference(self, on: bool) -> None:
        self.compare_reference = bool(on) and self.reference is not None
        self.update()

    def _other(self) -> tuple[QImage | None, str]:
        """O que fica do outro lado da comparação: a referência (se escolhida) ou o original."""
        if self.compare_reference and self.reference is not None:
            return self.reference, _("REFERÊNCIA")
        return self.orig, _("ORIGINAL")

    def start_pick(self) -> None:
        """Conta-gotas: o próximo clique na imagem emite `picked` (Esc ou o botão direito cancelam)."""
        self._pick = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    def cancel_pick(self) -> None:
        if self._pick:
            self._pick = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.pickCanceled.emit()

    def pick_at(self, fx: float, fy: float) -> None:
        """Termina o conta-gotas no ponto (fração da imagem) e emite `picked`."""
        self._pick = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.picked.emit(float(fx), float(fy))

    @property
    def picking(self) -> bool:
        return self._pick

    def image_point(self, pos: QPointF) -> tuple[float, float] | None:
        """Fração (0 a 1) da imagem processada sob um ponto da tela, ou None fora dela."""
        if self.proc is None:
            return None
        area = self._area()
        if self.mode == "side" and self._other()[0] is not None:
            half = (area.width() - 10) / 2
            sub = QRectF(area.left() + half + 10, area.top(), half, area.height())
            s = min(sub.width() / self.proc.width(), sub.height() / self.proc.height())
            r = QRectF(sub.center().x() - self.proc.width() * s / 2, sub.center().y() - self.proc.height() * s / 2,
                       self.proc.width() * s, self.proc.height() * s)
        else:
            r = self._image_rect(self.proc, area)
        fx = (pos.x() - r.left()) / max(r.width(), 1e-6)
        fy = (pos.y() - r.top()) / max(r.height(), 1e-6)
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            return None
        return fx, fy

    @staticmethod
    def _fit_in(img: QImage, r: QRectF) -> QRectF:
        """`r` para uma imagem da mesma proporção; outra proporção (uma referência) fica inteira e centralizada."""
        if img.width() <= 0 or img.height() <= 0 or r.height() <= 0:
            return r
        a, b = img.width() / img.height(), r.width() / r.height()
        if abs(a - b) < 1e-3 * b:
            return r
        if a > b:
            h = r.width() / a
            return QRectF(r.left(), r.center().y() - h / 2, r.width(), h)
        w = r.height() * a
        return QRectF(r.center().x() - w / 2, r.top(), w, r.height())

    def _draw_overlay(self, p: QPainter, r: QRectF, clip: QRectF | None = None) -> None:
        if self.overlay is None or self.overlay.isNull():
            return
        p.save()
        if clip is not None:
            p.setClipRect(clip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, r.width() < self.overlay.width())
        p.drawImage(r, self.overlay)
        p.restore()

    def set_safe_area(self, kind: str) -> None:
        """Mostra (ou esconde, com "") a área segura de uma plataforma por cima da prévia. Só na tela: a
        exportação nunca passa por aqui."""
        self.safe_area = kind if kind in platforms.SAFE_BY_ID else ""
        self.update()

    def set_zoom(self, z: float | None) -> None:
        self.zoom = None if z is None else min(max(z, MIN_ZOOM), MAX_ZOOM)
        if z is None:
            self.center = QPointF(0.5, 0.5)
        self._emit_zoom()
        self.update()

    def _emit_zoom(self) -> None:
        self.zoomChanged.emit("fit" if self.zoom is None else f"{self.zoom:g}")

    def set_fullscreen(self, on: bool) -> None:
        """Modo de tela cheia da prévia: sem borda, fundo preto e dica das teclas por alguns segundos."""
        self.fullscreen = on
        self.margin = 0 if on else MARGIN
        self._hint = on
        if on:
            self.hint_timer.start()
        else:
            self.hint_timer.stop()
        if self.zoom is None:
            self._emit_zoom()
        self.update()

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

    def safe_geometry(self, r: QRectF) -> tuple[QRectF, list[QRectF]]:
        """Onde a área segura cai na imagem desenhada em `r`: (quadro da plataforma, retângulos livres).

        As zonas de TikTok, Reels e Shorts foram medidas no quadro 9:16; num vídeo de outra proporção elas
        ficam no recorte 9:16 do centro (o que sai com "Cortar para preencher")."""
        area = platforms.SAFE_BY_ID.get(self.safe_area)
        if area is None:
            return QRectF(r), []
        f = QRectF(r)
        if area.aspect:
            if r.width() / max(r.height(), 1e-6) > area.aspect:
                w = r.height() * area.aspect
                f = QRectF(r.center().x() - w / 2, r.top(), w, r.height())
            else:
                h = r.width() / area.aspect
                f = QRectF(r.left(), r.center().y() - h / 2, r.width(), h)
        rects = [QRectF(f.left() + x, f.top() + y, w, h)
                 for x, y, w, h in platforms.safe_rects(area.id, f.width(), f.height())]
        return f, rects

    def _draw_safe(self, p: QPainter, r: QRectF) -> None:
        area = platforms.SAFE_BY_ID.get(self.safe_area)
        if area is None:
            return
        f, rects = self.safe_geometry(r)
        p.save()
        p.setClipRect(QRectF(self.rect()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if area.dim:
            free = QPainterPath()
            for q in rects:
                free.addRect(q)
            whole = QPainterPath()
            whole.addRect(QRectF(r))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawPath(whole.subtracted(free.simplified()))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, q in enumerate(rects):
            color = QColor(theme.ACCENT) if i == 0 or area.dim else QColor(255, 255, 255, 170)
            p.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
            p.drawRect(q)
        p.restore()
        self._pill(p, f.left() + 10, min(f.bottom(), self.height()) - 32,
                   _("ÁREA SEGURA: {nome}").format(nome=_(area.name)).upper())

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
        other, other_label = self._other()
        showing_other = (self._peek or self.mode == "orig") and other is not None
        proc = other if showing_other else self.proc
        if self.mode == "side" and other is not None and not self._peek:
            half = (area.width() - 10) / 2
            for i, (img, lab) in enumerate(((other, other_label), (self.proc, self.label_proc))):
                sub = QRectF(area.left() + i * (half + 10), area.top(), half, area.height())
                s = min(sub.width() / img.width(), sub.height() / img.height())
                r = QRectF(sub.center().x() - img.width() * s / 2, sub.center().y() - img.height() * s / 2,
                           img.width() * s, img.height() * s)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1)
                p.drawImage(r, img)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                if i == 1:
                    self._draw_overlay(p, r)
                    self._draw_safe(p, r)
                self._pill(p, r.left() + 10, r.top() + 10, lab)
            if self._hint:
                self._draw_hint(p)
            p.end()
            return
        r = self._image_rect(self.proc, area)  # a referência pode ter outro tamanho: vai no lugar do quadro
        s = r.width() / proc.width()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
        p.drawImage(self._fit_in(proc, r), proc)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        split = self.mode == "split" and other is not None and not self._peek
        if not showing_other:
            xs0 = r.left() + r.width() * self.split if split else r.left()
            self._draw_overlay(p, r, QRectF(xs0, r.top(), r.right() - xs0, r.height()) if split else None)
        if not split:
            self._draw_safe(p, r)
        if self._peek or self.mode == "orig":
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, other_label if other is not None else _("ORIGINAL"))
        elif self.mode == "split" and other is not None:
            xs = r.left() + r.width() * self.split
            clip = QRectF(r.left(), r.top(), xs - r.left(), r.height()).intersected(QRectF(self.rect()))
            p.save()
            p.setClipRect(clip)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
            p.drawImage(self._fit_in(other, r), other)
            p.restore()
            self._draw_safe(p, r)
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
            self._pill(p, xs - 10, top + 10, other_label, right=True)
            self._pill(p, xs + 10, top + 10, self.label_proc)
        else:
            self._pill(p, r.left() + 10, max(r.top(), 0) + 10, self.label_proc)
        if self._hint:
            self._draw_hint(p)
        p.end()

    # ------------------------------------------------------------ mouse
    def _split_x(self) -> float | None:
        if self.proc is None or self.mode != "split" or self._other()[0] is None:
            return None
        r = self._image_rect(self.proc, self._area())
        return r.left() + r.width() * self.split

    def _hover_cursor(self, x: float) -> None:
        if self._pick:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        xs = self._split_x()
        if xs is not None and abs(x - xs) < 22:
            self.setCursor(Qt.CursorShape.SplitHCursor)
        elif self._pannable():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if self.proc is None:
            return
        if self._pick:
            if e.button() == Qt.MouseButton.LeftButton:
                pt = self.image_point(e.position())
                if pt is not None:
                    self.pick_at(*pt)
            else:
                self.cancel_pick()
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


def safe_area_icon(color: str, size: int = 18) -> QIcon:
    """Ícone da área segura (um celular em pé com a área livre tracejada), desenhado aqui."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 18
    p.setPen(QPen(QColor(color), 1.5 * s))
    p.drawRoundedRect(QRectF(4.5 * s, 1.5 * s, 9 * s, 15 * s), 2 * s, 2 * s)
    p.setPen(QPen(QColor(color), 1.0 * s, Qt.PenStyle.DotLine))
    p.drawRect(QRectF(6.5 * s, 4 * s, 5 * s, 7.5 * s))
    p.end()
    return QIcon(pm)


class SafeAreaButton(QToolButton):
    """Botão da barra da prévia que escolhe a área segura (Desligada, TikTok, Reels, Shorts, Título e ação).

    A escolha fica nas preferências (`safe_area`) e começa desligada; `changed` avisa o visualizador."""

    changed = Signal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setObjectName("Flat")
        self.setIcon(safe_area_icon(theme.TEXT))
        self.setIconSize(QSize(18, 18))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        group = QActionGroup(self)
        self.actions_by_kind = {}
        for kind, name in [("", _("Desligada"))] + [(a.id, _(a.name)) for a in platforms.SAFE_AREAS]:
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setData(kind)
            group.addAction(act)
            act.triggered.connect(lambda _checked=False, k=kind: self.set_kind(k))
            self.actions_by_kind[kind] = act
        self.setMenu(menu)
        kind = str(settings.value("safe_area", "") or "") if settings is not None else ""
        self.kind = ""
        self.set_kind(kind, save=False)

    def set_kind(self, kind: str, save: bool = True) -> None:
        kind = kind if kind in platforms.SAFE_BY_ID else ""
        self.kind = kind
        self.actions_by_kind[kind].setChecked(True)
        self.setChecked(bool(kind))
        name = _(platforms.SAFE_BY_ID[kind].name) if kind else _("desligada")
        self.setToolTip(_("Área segura da prévia: {nome}. Mostra onde os botões e a legenda do app cobrem o "
                          "vídeo vertical; só aparece aqui, nunca na exportação.").format(nome=name))
        if save and self.settings is not None:
            self.settings.setValue("safe_area", kind)
        self.changed.emit(kind)
