"""Mixer do modo Edição (1.8, ARQUITETURA §43.4): uma tira por faixa de áudio (nome, balanço, fader em dB, medidor de
pico, mudo e solo) e a tira da mixagem com o pico e o loudness do medidor da prévia.

É o ponto de ligação com a janela (como `aninhar_ui`): `MainWindow` instala; o painel fica no lugar do inspetor, à
direita, e o botão "Mixer" da barra da linha do tempo (ou Ctrl+Alt+M) troca um pelo outro. Toda mudança passa por
`TimelineModel.set_track` (arrastar o fader ou o balanço é um passo só do desfazer, como a barrinha de volume do cabeçalho
da faixa), então o cabeçalho e o mixer andam juntos pelos dois lados.

Medidores: a mixagem da prévia grava ao lado do WAV o pico de cada faixa a cada 10 ms (`somcache.save_peaks`, calculado na
thread da mixagem com os mesmos pedaços do cache); aqui só se indexa esse arquivo pelo relógio da prévia. Nada é
decodificado na interface.
"""

from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from .. import somcache, timeline
from ..i18n import _, fmt_decimal
from ..timeline import AUDIO
from . import icons, theme
from .meter import CLIP_DB, FALL_DB_S, FLOOR, HOLD_S, RED_DB, YELLOW_DB, fmt_level, level_to_t

SHORTCUT = "Ctrl+Alt+M"   # mostrar/esconder o mixer (livre em `MainWindow._shortcuts`)
DB_MIN, DB_MAX = -60.0, 12.0  # a faixa do volume da faixa (`TimelineModel.set_track`, cabeçalho)
STRIP_W = 70


def db_to_t(db: float) -> float:
    """Posição do fader (0 = embaixo, 1 = em cima): linear em dB, como a barrinha do cabeçalho da faixa."""
    return (min(max(db, DB_MIN), DB_MAX) - DB_MIN) / (DB_MAX - DB_MIN)


def t_to_db(t: float) -> float:
    return round(min(max(t, 0.0), 1.0) * (DB_MAX - DB_MIN) + DB_MIN, 1)


def fmt_db(db: float) -> str:
    return (fmt_decimal(db, 1) if abs(db) >= 0.05 else "0").replace("-", "−") + " dB"


def fmt_pan(pan: float) -> str:
    """"C" no centro; "E 40" / "D 40" puxando para a esquerda / direita (em %)."""
    if abs(pan) < 0.005:
        return _("C")
    return (_("E {n}") if pan < 0 else _("D {n}")).format(n=int(round(abs(pan) * 100)))


# ------------------------------------------------------------------ controles
class Fader(QWidget):
    """Fader vertical do volume da faixa em dB. Arrastar emite `moved`; soltar, `released` (um passo do desfazer).
    Dois cliques voltam a 0 dB; a roda do mouse anda 0,5 dB."""

    moved = Signal(float)
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.dragging = False
        self.setMinimumHeight(120)
        self.setFixedWidth(26)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(_("Volume da faixa (dois cliques voltam a 0 dB)"))

    def set_value(self, db: float) -> None:
        if not self.dragging and abs(db - self.value) > 1e-9:
            self.value = db
            self.update()

    def _span(self) -> tuple[float, float]:
        return 10.0, max(20.0, self.height() - 10.0)

    def _db_at(self, y: float) -> float:
        top, bottom = self._span()
        return t_to_db((bottom - y) / (bottom - top))

    def _set(self, db: float) -> None:
        if abs(db - self.value) > 1e-9:
            self.value = db
            self.update()
            self.moved.emit(db)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._set(self._db_at(e.position().y()))

    def mouseMoveEvent(self, e):
        if self.dragging:
            self._set(self._db_at(e.position().y()))

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.released.emit()

    def mouseDoubleClickEvent(self, e):
        self.dragging = False
        self._set(0.0)
        self.released.emit()

    def wheelEvent(self, e):
        step = 0.5 if e.angleDelta().y() > 0 else -0.5
        self._set(min(max(round((self.value + step) * 2) / 2, DB_MIN), DB_MAX))
        self.released.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top, bottom = self._span()
        cx = self.width() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.PANEL3))
        p.drawRoundedRect(QRectF(cx - 2.5, top, 5, bottom - top), 2.5, 2.5)
        for db in (12, 6, 0, -6, -12, -24, -36, -48, -60):
            y = bottom - (bottom - top) * db_to_t(db)
            p.setPen(QPen(QColor(255, 255, 255, 120 if db == 0 else 34), 1))
            p.drawLine(QPointF(cx - (9 if db == 0 else 6), y), QPointF(cx - 4, y))
        y = bottom - (bottom - top) * db_to_t(self.value)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.CLIP_AUDIO_HI))
        p.drawRoundedRect(QRectF(cx - 2.5, y, 5, bottom - y), 2.5, 2.5)
        p.setBrush(QColor(theme.TEXT if self.isEnabled() else theme.FAINT))
        p.drawRoundedRect(QRectF(cx - 10, y - 4, 20, 8), 2, 2)
        p.setBrush(QColor(theme.PANEL))
        p.drawRect(QRectF(cx - 7, y - 0.5, 14, 1))
        p.end()


class PanSlider(QWidget):
    """Balanço da faixa: −1 (esquerda) a 1 (direita). Dois cliques voltam ao centro."""

    moved = Signal(float)
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.dragging = False
        self.setFixedHeight(14)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip(_("Balanço da faixa: para a esquerda ou para a direita (dois cliques voltam ao centro)"))

    def set_value(self, pan: float) -> None:
        if not self.dragging and abs(pan - self.value) > 1e-9:
            self.value = pan
            self.update()

    def _pan_at(self, x: float) -> float:
        w = max(1.0, self.width() - 8.0)
        return timeline.clean_pan(((x - 4.0) / w) * 2.0 - 1.0)

    def _set(self, pan: float) -> None:
        if abs(pan) < 0.03:
            pan = 0.0  # o centro gruda
        if abs(pan - self.value) > 1e-9:
            self.value = pan
            self.update()
            self.moved.emit(pan)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._set(self._pan_at(e.position().x()))

    def mouseMoveEvent(self, e):
        if self.dragging:
            self._set(self._pan_at(e.position().x()))

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.released.emit()

    def mouseDoubleClickEvent(self, e):
        self.dragging = False
        self._set(0.0)
        self.released.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(4, h / 2 - 2.5, w - 8, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.PANEL3))
        p.drawRoundedRect(r, 2.5, 2.5)
        cx = r.left() + r.width() / 2
        x = cx + self.value * r.width() / 2
        p.setBrush(QColor(theme.CLIP_AUDIO_HI))
        p.drawRect(QRectF(min(cx, x), r.top(), abs(x - cx), r.height()))
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRect(QRectF(cx - 0.5, r.top() - 2, 1, r.height() + 4))
        p.setBrush(QColor(theme.TEXT))
        p.drawEllipse(QPointF(x, h / 2), 4.5, 4.5)
        p.end()


class PeakMeter(QWidget):
    """Barra de pico em dBFS (a escala e as cores do medidor da prévia), com retenção."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(9)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.idle()

    def idle(self) -> None:
        self.level = self.hold = FLOOR
        self.clip = False
        self._t = self._hold_t = time.monotonic()
        self.update()

    def push(self, peak: float, now: float | None = None) -> None:
        """Pico linear (0…1) do trecho tocado desde o último toque."""
        now = time.monotonic() if now is None else now
        dt = max(0.0, now - self._t)
        self._t = now
        db = 20.0 * math.log10(peak) if peak > 1e-9 else FLOOR
        db = max(FLOOR, db)
        self.level = max(db, self.level - FALL_DB_S * dt)
        if db >= self.hold or now - self._hold_t > HOLD_S:
            self.hold = max(db, self.level)
            self._hold_t = now
        self.clip = self.clip or db >= CLIP_DB
        self.update()

    def mousePressEvent(self, _e):
        self.clip = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        top, bottom = 10.0, h - 10.0
        span = max(10.0, bottom - top)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.PANEL3))
        p.drawRect(QRectF(0, top, w, span))
        for lo, hi, col in ((FLOOR, YELLOW_DB, theme.METER_LOW), (YELLOW_DB, RED_DB, theme.METER_MID),
                            (RED_DB, 0.0, theme.METER_HIGH)):
            if self.level <= lo:
                break
            y0 = bottom - span * level_to_t(min(self.level, hi))
            y1 = bottom - span * level_to_t(lo)
            p.setBrush(QColor(col))
            p.drawRect(QRectF(0, y0, w, max(0.0, y1 - y0)))
        if self.hold > FLOOR:
            p.setBrush(QColor(theme.TEXT))
            p.drawRect(QRectF(0, bottom - span * level_to_t(self.hold) - 1, w, 2))
        p.setBrush(QColor(theme.METER_HIGH) if self.clip else QColor(theme.PANEL3))
        p.drawRect(QRectF(0, 2, w, 5))
        p.end()


def _toggle(icon: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setObjectName("Flat")
    b.setCheckable(True)
    b.setIcon(icons.icon(icon, theme.TEXT, 16))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Strip(QFrame):
    """A tira de uma faixa de áudio."""

    changed = Signal(int, dict, bool)   # (faixa, atributos, gravar no desfazer agora)
    gestureEnded = Signal()

    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.setObjectName("MixerStrip")
        self.setFixedWidth(STRIP_W)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 6, 4, 6)
        vl.setSpacing(4)
        self.name = QLabel()
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        vl.addWidget(self.name)
        self.pan = PanSlider()
        self.pan.moved.connect(lambda v: self.changed.emit(self.idx, {"pan": v}, False))
        self.pan.released.connect(self.gestureEnded)
        vl.addWidget(self.pan)
        self.pan_label = QLabel()
        self.pan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pan_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        vl.addWidget(self.pan_label)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addStretch(1)
        self.fader = Fader()
        self.fader.moved.connect(lambda v: self.changed.emit(self.idx, {"volume": v}, False))
        self.fader.released.connect(self.gestureEnded)
        row.addWidget(self.fader)
        self.meter = PeakMeter()
        row.addWidget(self.meter)
        row.addStretch(1)
        vl.addLayout(row, 1)
        self.db_label = QLabel()
        self.db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.db_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        vl.addWidget(self.db_label)
        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(2)
        self.mute = _toggle("mute", _("Mudo (a faixa não toca)"))
        self.mute.clicked.connect(lambda on: self.changed.emit(self.idx, {"muted": bool(on)}, True))
        self.solo = _toggle("headphones", _("Solo (só as faixas em solo tocam)"))
        self.solo.clicked.connect(lambda on: self.changed.emit(self.idx, {"solo": bool(on)}, True))
        btns.addWidget(self.mute)
        btns.addWidget(self.solo)
        vl.addLayout(btns)

    def sync(self, tr: timeline.Track) -> None:
        self.name.setText(tr.name)
        self.name.setToolTip(tr.name)
        self.fader.set_value(tr.volume)
        self.pan.set_value(tr.pan)
        self.db_label.setText(fmt_db(tr.volume))
        self.pan_label.setText(fmt_pan(tr.pan))
        for b, on in ((self.mute, tr.muted), (self.solo, tr.solo)):
            if b.isChecked() != on:
                b.setChecked(on)
        locked = tr.locked
        for w in (self.fader, self.pan, self.mute, self.solo):
            w.setEnabled(not locked)


class MasterStrip(QFrame):
    """A mixagem: pico dos dois canais somados e o loudness do medidor da prévia (M, S, I), quando ele está ligado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MixerStrip")
        self.setFixedWidth(STRIP_W + 8)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 6, 4, 6)
        vl.setSpacing(4)
        name = QLabel(_("Mixagem"))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(f"color: {theme.ACCENT_HI}; font-weight: 600;")
        vl.addWidget(name)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.meter = PeakMeter()
        self.meter.setFixedWidth(14)
        row.addWidget(self.meter)
        row.addStretch(1)
        vl.addLayout(row, 1)
        self.readout = QLabel()
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.readout.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        self.readout.setToolTip(_("Loudness da prévia em LUFS: M momentânea, S curto prazo, I integrada desde o play "
                                  "(o mesmo do medidor ao lado da prévia; com ele desligado, nada é medido)."))
        vl.addWidget(self.readout)
        self.set_loudness(None, None, None)

    def set_loudness(self, m, s, i) -> None:
        self.readout.setText("M {m}\nS {s}\nI {i}".format(m=fmt_level(m), s=fmt_level(s), i=fmt_level(i)))


class MixerPanel(QWidget):
    """As tiras das faixas de áudio (com rolagem) e a da mixagem, sempre à direita."""

    changed = Signal(int, dict, bool)
    gestureEnded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.row = QHBoxLayout(self.inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.row.addStretch(1)
        self.scroll.setWidget(self.inner)
        hl.addWidget(self.scroll, 1)
        self.master = MasterStrip()
        hl.addWidget(self.master)
        self.strips: list[Strip] = []

    def sync(self, seq: timeline.Sequence) -> None:
        tracks = seq.kind_tracks(AUDIO)
        while len(self.strips) > len(tracks):
            s = self.strips.pop()
            s.setParent(None)
            s.deleteLater()
        while len(self.strips) < len(tracks):
            s = Strip(len(self.strips))
            s.changed.connect(self.changed)
            s.gestureEnded.connect(self.gestureEnded)
            self.row.insertWidget(len(self.strips), s)
            self.strips.append(s)
        for s, tr in zip(self.strips, tracks):
            s.sync(tr)

    def idle(self) -> None:
        for s in self.strips:
            s.meter.idle()
        self.master.meter.idle()


# ------------------------------------------------------------------ ligação com a janela
class MixerUI(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.panel = MixerPanel()
        self.panel.setVisible(False)
        self.panel.changed.connect(self._changed)
        self.panel.gestureEnded.connect(lambda: win.model.commit())
        panel_layout = win.inspector.parentWidget().layout()
        panel_layout.insertWidget(panel_layout.indexOf(win.inspector) + 1, self.panel, 1)
        self.button = win.tl_editor.btn_mixer
        self.button.toggled.connect(self.show_mixer)
        sc = QShortcut(QKeySequence(SHORTCUT), win)
        sc.activated.connect(lambda: win.mode == "edicao" and self.button.toggle())
        self.shortcut = sc
        self._peaks_for = ""
        self._peaks: tuple[list[int], np.ndarray, np.ndarray] | None = None
        self._block = None
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        win.model.changed.connect(lambda _k: self.sync())
        self.sync()

    # ------------------------------------------------------------ painel
    def show_mixer(self, on: bool) -> None:
        """O mixer no lugar do inspetor (e o inspetor de volta)."""
        self.panel.setVisible(on)
        self.win.inspector.setVisible(not on)
        if self.button.isChecked() != on:
            self.button.setChecked(on)
        if on:
            self.sync()
            self.timer.start()
        else:
            self.timer.stop()
            self.panel.idle()

    @property
    def visible(self) -> bool:
        return self.panel.isVisible()

    def sync(self) -> None:
        if self.button.isChecked():
            self.panel.sync(self.win.model.seq)

    def _changed(self, idx: int, attrs: dict, record: bool) -> None:
        self.win.model.set_track(AUDIO, idx, record=record, **attrs)

    # ------------------------------------------------------------ medidores
    def _load_peaks(self) -> None:
        path = self.win._mix_path if self.win._audio_src[0] == "seq" else ""
        if path == self._peaks_for:
            return
        self._peaks_for = path
        self._peaks = somcache.load_peaks(path) if path else None
        self._block = None

    def _tick(self) -> None:
        """Os picos tocados desde o último toque, pelo relógio da prévia (o mesmo do medidor de som)."""
        w = self.win
        if not w.playing or getattr(w, "_play_t0", None) is None or w.info is None or getattr(w, "_play_rate", 1) != 1:
            if self._block is not None:
                self._block = None
                self.panel.idle()
            lm = w._meter_lm
            if lm is not None:
                self.panel.master.set_loudness(lm.momentary(), lm.short_term(), lm.integrated())
            return
        self._load_peaks()
        if self._peaks is None:
            return
        tracks, peaks, master = self._peaks
        now = int((w._play_f0 / w.info.fps + time.perf_counter() - w._play_t0) * 100)
        start = now if self._block is None or now < self._block or now - self._block > 50 else self._block + 1
        self._block = now
        hi = min(now + 1, len(master))
        stamp = time.monotonic()
        for s in self.panel.strips:
            v = 0.0
            if s.idx in tracks and start < hi:
                v = float(peaks[start:hi, tracks.index(s.idx)].max())
            s.meter.push(v, stamp)
        self.panel.master.meter.push(float(master[start:hi].max()) if start < hi else 0.0, stamp)
        lm = w._meter_lm
        if lm is not None:
            self.panel.master.set_loudness(lm.momentary(), lm.short_term(), lm.integrated())


def install(win) -> MixerUI:
    return MixerUI(win)
