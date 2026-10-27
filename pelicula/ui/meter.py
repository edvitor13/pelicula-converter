"""Medidor de som ao lado da prévia: picos de L e R em dBFS (com retenção) e loudness EBU R128.

Só mostra o que a janela manda (`push`), lido do mesmo som que está tocando; nada daqui vai para a
exportação. M = momentânea (400 ms), S = curto prazo (3 s), I = integrada desde o início da
reprodução (recomeça ao pular ou parar) e TP = maior true peak.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n import _, fmt_decimal
from . import theme

FLOOR = -60.0              # base da escala (dBFS)
MARKS = (0, -6, -12, -18, -24, -36, -48, -60)
HOLD_S = 1.5               # retenção do pico
FALL_DB_S = 24.0           # queda das barras
CLIP_DB = -0.1             # acende o aviso de pico no topo
YELLOW_DB, RED_DB = -18.0, -6.0


def level_to_t(db: float) -> float:
    """Posição (0 = base, 1 = topo) de um nível em dBFS: a parte de cima da escala ganha mais espaço."""
    if db is None or db <= FLOOR:
        return 0.0
    return min(1.0, (db - FLOOR) / -FLOOR) ** 1.5


def fmt_level(v: float | None) -> str:
    """Valor com uma casa decimal (vírgula em português); "—" sem medida e "−∞" no silêncio."""
    if v is None:
        return "—"
    if not math.isfinite(v) or v < -99.0:
        return "−∞"
    return fmt_decimal(v, 1).replace("-", "−")


class AudioMeter(QWidget):
    """Barras L/R com escala em dBFS e retenção de pico, e as leituras M, S, I (LUFS) e TP (dBTP)."""

    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AudioMeter")
        self.setFixedWidth(88)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Medidor de som da prévia. Barras: picos de cada canal em dBFS (o traço fica 1,5 s "
                          "no maior). Loudness EBU R128 em LUFS: M momentânea (0,4 s), S curto prazo (3 s), "
                          "I integrada desde o play (recomeça ao pular ou parar). TP: maior true peak.\n"
                          "Referências: −14 LUFS no YouTube e no Spotify, −23 LUFS na TV; picos abaixo de −1 dBTP.\n"
                          "Clique para recomeçar a medição."))
        self.channels = 2
        self.clear()

    # ------------------------------------------------------------ estado
    def clear(self) -> None:
        """Sem medição (fonte nova ou sem som)."""
        self.level = [FLOOR] * self.channels
        self.hold = [FLOOR] * self.channels
        self._hold_t = [0.0] * self.channels
        self.clip = [False] * self.channels
        self.momentary = self.short_term = self.integrated = None
        self.true_peak: float | None = None
        self.active = False
        self.waiting = False
        self._t = time.monotonic()
        self.update()

    def restart(self) -> None:
        """Medição nova (play, busca): zera as leituras e os picos."""
        self.clear()
        self.active = True

    def set_waiting(self, on: bool) -> None:
        """O som do arquivo ainda está sendo preparado para o medidor."""
        self.waiting = bool(on)
        self.update()

    def idle(self) -> None:
        """Parou de tocar: as barras descem e as leituras ficam (apagadas) até o próximo play."""
        self.active = False
        self.level = [FLOOR] * self.channels
        self.hold = [FLOOR] * self.channels
        self.update()

    def push(self, peaks_db, momentary=None, short_term=None, integrated=None, true_peak=None,
             now: float | None = None) -> None:
        """Novo bloco tocado: picos (dBFS) de cada canal e as medidas atuais."""
        now = time.monotonic() if now is None else now
        dt = max(0.0, now - self._t)
        self._t = now
        peaks = list(peaks_db) if peaks_db is not None else []
        if len(peaks) == 1:
            peaks = peaks * 2
        if peaks and len(peaks) != self.channels:
            peaks = (peaks + [FLOOR] * self.channels)[:self.channels]
        for c in range(self.channels):
            p = peaks[c] if peaks else FLOOR
            p = FLOOR if p is None or not math.isfinite(p) else max(FLOOR, p)
            self.level[c] = max(p, self.level[c] - FALL_DB_S * dt)
            if p >= self.hold[c] or now - self._hold_t[c] > HOLD_S:
                self.hold[c] = max(p, self.level[c])
                self._hold_t[c] = now
            if p >= CLIP_DB:
                self.clip[c] = True
        self.momentary, self.short_term, self.integrated = momentary, short_term, integrated
        self.true_peak = true_peak
        self.active = True
        self.waiting = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clip = [False] * self.channels
            self.resetRequested.emit()
            self.update()

    # ------------------------------------------------------------ desenho
    def _bar_color(self, db: float) -> QColor:
        if db >= RED_DB:
            return QColor(theme.METER_HIGH)
        if db >= YELLOW_DB:
            return QColor(theme.METER_MID)
        return QColor(theme.METER_LOW)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        p.fillRect(QRectF(0, 0, 1, h), QColor(theme.BORDER))
        small = theme.font(7.2)
        mono = theme.mono_font(7.6)
        fm = QFontMetrics(mono)
        rows = 4
        row_h = fm.height() + 2
        readout_h = rows * row_h + 8
        top, bottom = 14.0, h - readout_h - 8.0
        bar_w, gap = 9.0, 3.0
        x_bars = w - 10 - 2 * bar_w - gap
        span = max(10.0, bottom - top)

        def y_of(db: float) -> float:
            return bottom - span * level_to_t(db)

        # escala
        p.setFont(small)
        for mark in MARKS:
            y = y_of(mark)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(2, y - 6, x_bars - 5, 12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       str(mark).replace("-", "−"))
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))
            p.drawLine(QPointF(x_bars - 3, y), QPointF(x_bars + 2 * bar_w + gap, y))
        # barras
        dim = not self.active
        for c in range(self.channels):
            x = x_bars + c * (bar_w + gap)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.PANEL3))
            p.drawRoundedRect(QRectF(x, top, bar_w, span), 2, 2)
            lvl = self.level[c]
            if lvl > FLOOR:
                for lo, hi in ((FLOOR, YELLOW_DB), (YELLOW_DB, RED_DB), (RED_DB, 0.0)):
                    if lvl <= lo:
                        break
                    y0, y1 = y_of(min(lvl, hi)), y_of(lo)
                    col = self._bar_color(lo + 0.01)
                    if dim:
                        col.setAlpha(110)
                    p.setBrush(col)
                    p.drawRect(QRectF(x, y0, bar_w, max(0.0, y1 - y0)))
            if self.hold[c] > FLOOR:
                col = self._bar_color(self.hold[c])
                p.setBrush(col)
                p.drawRect(QRectF(x, y_of(self.hold[c]) - 1, bar_w, 2))
            p.setBrush(QColor(theme.METER_HIGH) if self.clip[c] else QColor(theme.PANEL3))
            p.drawRoundedRect(QRectF(x, 4, bar_w, 6), 1.5, 1.5)
            p.setPen(QColor(theme.MUTED))
            p.setFont(small)
            p.drawText(QRectF(x - 2, bottom + 1, bar_w + 4, 12), Qt.AlignmentFlag.AlignCenter, "LR"[c] if c < 2 else "")
            p.setPen(Qt.PenStyle.NoPen)
        # leituras
        y = h - readout_h
        p.fillRect(QRectF(4, y - 4, w - 8, 1), QColor(theme.BORDER))
        vals = [("M", self.momentary), ("S", self.short_term), ("I", self.integrated), ("TP", self.true_peak)]
        for label, v in vals:
            p.setFont(small)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(6, y, 18, row_h), Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(mono)
            p.setPen(QColor(theme.TEXT if self.active else theme.FAINT))
            if label == "I" and v is not None and self.active:
                p.setPen(QColor(theme.ACCENT_HI))
            p.drawText(QRectF(22, y, w - 28, row_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt_level(v))
            y += row_h
        p.setFont(small)
        p.setPen(QColor(theme.FAINT))
        unit = _("preparando…") if self.waiting else "LUFS · dBTP"
        p.drawText(QRectF(2, h - 12, w - 4, 11), Qt.AlignmentFlag.AlignCenter, unit)
        p.end()
