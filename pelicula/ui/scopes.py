"""Monitores de imagem: histograma, forma de onda, parada RGB e vetorscópio.

Substitui o `widgets.Histogram` (mesmo `set_image`). Tudo é calculado com numpy numa versão
reduzida do quadro, então cabe em cada atualização da prévia.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from ..i18n import N_, _
from . import theme

MODES: list[tuple[str, str, str]] = [
    ("hist", N_("Histograma"), N_("Quantos pixels há em cada nível de brilho, por canal")),
    ("wave", N_("Onda"), N_("Forma de onda: brilho de cada coluna da imagem (0% embaixo, 100% em cima)")),
    ("parade", N_("RGB"), N_("Parada RGB: forma de onda separada do vermelho, verde e azul")),
    ("vector", N_("Vetor"), N_("Vetorscópio: matiz (ângulo) e saturação (distância do centro). "
                               "A linha marca o tom de pele.")),
]
MAX_W = 320          # largura máxima da imagem analisada
WAVE_H = 128         # níveis verticais da forma de onda
VEC_N = 128          # resolução do vetorscópio
_W709 = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _subsample(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    step = max(1, int(math.ceil(w / MAX_W)))
    sub = img[::step, ::step]
    if sub.dtype != np.uint8:
        sub = (sub >> 8).astype(np.uint8)
    return np.ascontiguousarray(sub[..., :3])


def histogram(sub: np.ndarray) -> np.ndarray:
    """(3, 64) normalizado 0..1 (raiz quadrada, como o histograma do painel de ajustes)."""
    hs = np.array([np.bincount(sub[..., c].ravel() >> 2, minlength=64).astype(np.float32) for c in range(3)])
    hs = np.sqrt(hs)
    m = hs[:, 1:-1].max() if hs.shape[1] > 2 else hs.max()
    return np.clip(hs / (m or 1.0), 0, 1)


def waveform(values: np.ndarray, levels: int = WAVE_H) -> np.ndarray:
    """Contagem (levels, largura) de um canal 0..255 por coluna; nível 0 = embaixo."""
    h, w = values.shape
    lv = (values.astype(np.int32) * (levels - 1) + 127) // 255
    idx = lv * w + np.arange(w)[None, :]
    counts = np.bincount(idx.ravel(), minlength=levels * w).reshape(levels, w).astype(np.float32)
    return counts[::-1]


def vectorscope(sub: np.ndarray, n: int = VEC_N) -> np.ndarray:
    """Densidade (n, n) de Cb/Cr BT.709; centro = sem cor; y para cima = Cr positivo."""
    rgb = sub.reshape(-1, 3).astype(np.float32) / 255.0
    y = rgb @ _W709
    cb = (rgb[:, 2] - y) / 1.8556
    cr = (rgb[:, 0] - y) / 1.5748
    # ±0,5 cobre o gamut inteiro; o círculo de 75% fica bem dentro.
    xi = np.clip(((cb / 0.5) * 0.5 + 0.5) * (n - 1), 0, n - 1).astype(np.int32)
    yi = np.clip((0.5 - (cr / 0.5) * 0.5) * (n - 1), 0, n - 1).astype(np.int32)
    return np.bincount(yi * n + xi, minlength=n * n).reshape(n, n).astype(np.float32)


def _intensity(counts: np.ndarray, gain: float) -> np.ndarray:
    m = float(counts.max()) or 1.0
    return np.clip(np.sqrt(counts / m) * gain, 0, 1)


def _to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(np.clip(rgb, 0, 255).astype(np.uint8))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class Scopes(QWidget):
    """Monitor com seletor de modo; `set_image()` aceita o quadro (h, w, 3) uint8/uint16."""

    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(130)
        self._mode = "hist"
        self._sub: np.ndarray | None = None
        self._hist: np.ndarray | None = None
        self._img: QImage | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.setSpacing(2)
        bar.addStretch(1)
        self.buttons: dict[str, QToolButton] = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for key, label, tip in MODES:
            b = QToolButton()
            b.setObjectName("Seg")
            b.setText(_(label))
            b.setToolTip(_(tip))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QToolButton { padding: 2px 7px; font-size: 8pt; }")
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            grp.addButton(b)
            bar.addWidget(b)
            self.buttons[key] = b
        self.buttons[self._mode].setChecked(True)
        lay.addLayout(bar)
        lay.addStretch(1)

    # ------------------------------------------------------------ API
    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        self.set_mode(value)

    def set_mode(self, mode: str) -> None:
        if mode not in self.buttons:
            return
        self.buttons[mode].setChecked(True)
        if mode == self._mode:
            return
        self._mode = mode
        self._compute()
        self.modeChanged.emit(mode)
        self.update()

    def set_image(self, img: np.ndarray | None) -> None:
        self._sub = None if img is None else _subsample(img)
        self._compute()
        self.update()

    # ------------------------------------------------------------ cálculo
    def _compute(self) -> None:
        self._hist = None
        self._img = None
        sub = self._sub
        if sub is None or sub.size == 0:
            return
        if self._mode == "hist":
            self._hist = histogram(sub)
        elif self._mode == "wave":
            luma = (sub.astype(np.float32) @ _W709).clip(0, 255)
            inten = _intensity(waveform(luma), 1.6)
            col = np.array([255, 214, 150], np.float32)
            self._img = _to_qimage(inten[..., None] * col)
        elif self._mode == "parade":
            parts = []
            cols = ([255, 90, 80], [90, 225, 120], [90, 150, 255])
            for c in range(3):
                inten = _intensity(waveform(sub[..., c]), 1.6)
                parts.append(inten[..., None] * np.array(cols[c], np.float32))
                parts.append(np.zeros((WAVE_H, 2, 3), np.float32))
            self._img = _to_qimage(np.concatenate(parts[:-1], axis=1))
        elif self._mode == "vector":
            inten = _intensity(vectorscope(sub), 2.2)
            n = inten.shape[0]
            yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
            cb = (xx / (n - 1) - 0.5)
            cr = (0.5 - yy / (n - 1))
            # Cada ponto com a própria cor (Y fixo), para ler o matiz com facilidade.
            yv = 0.6
            r = yv + 1.5748 * cr
            b = yv + 1.8556 * cb
            g = (yv - 0.2126 * r - 0.0722 * b) / 0.7152
            rgb = np.clip(np.stack([r, g, b], -1), 0, 1) * 0.55 + 0.45
            self._img = _to_qimage(inten[..., None] * rgb * 255)

    # ------------------------------------------------------------ desenho
    def _plot_rect(self) -> QRectF:
        top = 28
        return QRectF(0.5, top + 0.5, self.width() - 1, self.height() - top - 1)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor("#100f0e"))
        p.drawRoundedRect(r, 9, 9)
        inner = r.adjusted(6, 6, -6, -6)
        if self._mode == "hist":
            self._paint_hist(p, r)
        elif self._mode == "vector":
            side = min(inner.width(), inner.height())
            sq = QRectF(inner.center().x() - side / 2, inner.center().y() - side / 2, side, side)
            if self._img is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                p.drawImage(sq, self._img)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._paint_vector_grid(p, sq)
        else:
            if self._img is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                p.drawImage(inner, self._img)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))
            for i in range(5):
                y = inner.bottom() - inner.height() * i / 4
                p.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))
        p.end()

    def _paint_hist(self, p: QPainter, r: QRectF) -> None:
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4
            p.drawLine(QPointF(x, r.top() + 6), QPointF(x, r.bottom() - 6))
        if self._hist is None:
            return
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        cols = [QColor(235, 80, 70, 150), QColor(80, 200, 120, 150), QColor(70, 130, 245, 160)]
        w = r.width() - 12
        hh = r.height() - 14
        for c in range(3):
            path = QPainterPath()
            path.moveTo(r.left() + 6, r.bottom() - 6)
            n = len(self._hist[c])
            for i, v in enumerate(self._hist[c]):
                path.lineTo(r.left() + 6 + w * i / (n - 1), r.bottom() - 6 - hh * float(v))
            path.lineTo(r.left() + 6 + w, r.bottom() - 6)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cols[c])
            p.drawPath(path)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def _paint_vector_grid(self, p: QPainter, sq: QRectF) -> None:
        c = sq.center()
        rad = sq.width() / 2
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawEllipse(c, rad * 0.75 * 0.9, rad * 0.75 * 0.9)
        p.drawLine(QPointF(c.x() - rad, c.y()), QPointF(c.x() + rad, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - rad), QPointF(c.x(), c.y() + rad))
        # Alvos das cores primárias e secundárias a 75%.
        for rgb, name in (((0.75, 0, 0), "R"), ((0.75, 0.75, 0), "Am"), ((0, 0.75, 0), "G"),
                          ((0, 0.75, 0.75), "Ci"), ((0, 0, 0.75), "B"), ((0.75, 0, 0.75), "Mg")):
            x, y = self.vector_pos(rgb, sq)
            p.setPen(QPen(QColor(int(rgb[0] * 255 + 60), int(rgb[1] * 255 + 60), int(rgb[2] * 255 + 60), 170), 1))
            p.drawRect(QRectF(x - 4, y - 4, 8, 8))
        # Linha do tom de pele.
        x, y = self.vector_pos((0.8, 0.55, 0.45), sq)
        ang = math.atan2(y - c.y(), x - c.x())
        p.setPen(QPen(QColor(240, 166, 58, 140), 1, Qt.PenStyle.DashLine))
        p.drawLine(c, QPointF(c.x() + math.cos(ang) * rad, c.y() + math.sin(ang) * rad))

    @staticmethod
    def vector_pos(rgb, sq: QRectF) -> tuple[float, float]:
        """Posição na tela de uma cor RGB (0..1) no vetorscópio desenhado em `sq`."""
        r, g, b = rgb
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        cb = (b - y) / 1.8556
        cr = (r - y) / 1.5748
        return sq.left() + (cb + 0.5) * sq.width(), sq.top() + (0.5 - cr) * sq.height()


__all__ = ["Scopes", "MODES", "histogram", "waveform", "vectorscope"]
