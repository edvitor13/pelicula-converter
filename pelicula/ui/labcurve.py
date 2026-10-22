"""Gráfico "Mostrar curva": a curva de transferência do look (entrada × saída) em R, G e B.

A curva vem do mesmo caminho de cor do app: o look é assado num LUT pequeno na GPU
(`Engine.bake_lut`, que roda `colorPipe` — Laboratório, cor da película, cópia, LUT) e o
gráfico mostra o eixo dos cinzas desse LUT. Assim ele vale para qualquer combinação de
ajustes e de perfil de entrada, sem reimplementar nada na interface.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n import _
from . import theme

SIZE = 33  # pontos do LUT assado (só o eixo dos cinzas é usado)


def gray_axis(lut: np.ndarray, n: int = SIZE) -> np.ndarray:
    """Saída (n, 3) para entradas cinzas 0..1 de um LUT na ordem .cube (R mais rápido)."""
    idx = np.arange(n) * (1 + n + n * n)
    return np.asarray(lut, dtype=np.float32).reshape(-1, 3)[idx]


class CurveGraph(QWidget):
    """Curvas R, G e B da entrada (código do vídeo) para a saída, com a diagonal "sem efeito"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(140)
        self.curves: np.ndarray | None = None
        self.setToolTip(_("Curva do look: como cada valor de entrada (eixo horizontal, do preto ao branco do "
                          "vídeo) sai depois da cor da película. A diagonal tracejada é \"sem efeito\"."))

    def set_curves(self, curves: np.ndarray | None) -> None:
        self.curves = None if curves is None else np.clip(np.asarray(curves, dtype=np.float32), 0.0, 1.0)
        self.update()

    def update_from(self, engine, values: dict, legal: bool = True) -> None:
        """Assa o look atual (GPU, thread principal) e mostra o eixo dos cinzas (`legal`: faixa da fonte)."""
        try:
            self.set_curves(gray_axis(engine.bake_lut(values, SIZE, legal=legal)))
        except Exception:  # noqa: BLE001
            self.set_curves(None)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor("#100f0e"))
        p.drawRoundedRect(r, 9, 9)
        area = r.adjusted(10, 10, -10, -10)
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for i in range(1, 4):
            x = area.left() + area.width() * i / 4
            y = area.top() + area.height() * i / 4
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        pen = QPen(QColor(255, 255, 255, 60), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(area.left(), area.bottom()), QPointF(area.right(), area.top()))
        if self.curves is None:
            p.setPen(QColor(theme.FAINT))
            p.setFont(theme.font(8.5))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, _("Curva indisponível"))
            p.end()
            return
        cols = [QColor(235, 80, 70), QColor(80, 200, 120), QColor(70, 130, 245)]
        n = len(self.curves)
        for c in range(3):
            path = QPainterPath()
            for i in range(n):
                x = area.left() + area.width() * i / (n - 1)
                y = area.bottom() - area.height() * float(self.curves[i, c])
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(cols[c], 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()
