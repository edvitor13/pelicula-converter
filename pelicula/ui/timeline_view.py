"""Linha do tempo do modo Edição: régua, faixas, clipes e ferramentas.

Desenhada à mão com QPainter (sem QGraphicsView): a faixa V1 fica logo acima da divisória e as
faixas de vídeo maiores sobem; as de áudio (A1, A2…) ficam embaixo. Toda edição passa pelo
`TimelineModel` (que grava o desfazer); durante o arraste só um "fantasma" é desenhado e a
mudança é aplicada ao soltar o mouse.

Marcadores ficam na régua, na cor de cada um (ponto branco = capítulo): clique seleciona e leva o
cursor até ele, arrastar move, dois cliques editam, Delete apaga, M põe um no cursor e Shift+↑/↓
vão ao anterior/próximo.

As chaves de animação do clipe selecionado aparecem como losangos no meio do clipe (todos os ajustes
juntos por quadro; a dica diz quais): clique seleciona e leva o cursor, arrastar move (um passo do
desfazer), Delete apaga, Shift soma à seleção. Veja os métodos `key_*`.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QInputDialog, QMenu, QScrollBar, QSizePolicy,
                               QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import timeline
from ..i18n import _, decimal_sep, fmt_decimal
from ..timeline import AUDIO, VIDEO, Clip
from . import icons, theme
from .edit_model import TimelineModel
from .markers import ChaptersDialog, MarkerDialog, marker_color, marker_tooltip, youtube_chapters
from .flow import AdaptiveBar, FlowLayout
from . import tempo_ui
from .keyframes_ui import merged_marks, paint_diamond, param_names
from .widgets import FilmSlider, timecode

PEAKS_PER_SECOND = 100       # o provedor de ondas devolve picos (0..1) nesta taxa
HEADER_W = 156               # coluna dos nomes e botões das faixas
RULER_H = 28
VIDEO_H = 56
AUDIO_H = 46
GAP_H = 8                    # divisória entre vídeo e áudio
EDGE_PX = 7                  # área das bordas que apara o clipe
SNAP_PX = 9
MIN_PPF, MAX_PPF = 0.01, 40.0  # pixels por quadro
MIME_SOURCE = "application/x-pelicula-source"
BTN = 20                     # botões do cabeçalho das faixas
MARKER_W = 10                # largura do marcador na régua
MARKER_HIT = 6               # distância (px) que ainda pega um marcador

# Passos da régua em segundos (o menor que deixa ~90 px entre rótulos é usado).
_RULER_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]


def _elide(fm: QFontMetrics, text: str, width: float) -> str:
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0, int(width)))


class TimelineCanvas(QWidget):
    """Área desenhada: régua, faixas e clipes. A rolagem e o zoom ficam aqui."""

    seekRequested = Signal(int)
    scrubbing = Signal(bool)
    filesDropped = Signal(list, int, str, int)
    filesInserted = Signal(list, int, str, int)   # soltos no modo inserir: o resto anda para a direita
    viewChanged = Signal()
    clipActivated = Signal(str)
    toolChanged = Signal(str)

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.ppf = 4.0            # pixels por quadro
        self.scroll = 0.0         # primeiro quadro visível
        self.yscroll = 0.0        # rolagem vertical (px)
        self.playhead = 0
        self.inp: int | None = None
        self.outp: int | None = None
        self.tool = "select"      # "select" | "blade"
        self.snap = True
        self.insert_mode = False  # soltar/mover empurra o resto (inserir) em vez de cobrir; Ctrl inverte
        self.follow = True        # rola sozinho para acompanhar o cursor na reprodução
        self.peaks_provider: Callable[[str], np.ndarray | None] | None = None
        self._drag: dict | None = None
        self._hover_x: float | None = None
        self._snap_x: float | None = None
        self._drop: tuple[float, str, int, bool] | None = None
        self.key_clip: str | None = None     # chaves selecionadas: o clipe e os quadros (da sequência)
        self.key_sel: set[float] = set()
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER_H + VIDEO_H + GAP_H + AUDIO_H + 4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        model.changed.connect(self._model_changed)
        model.selectionChanged.connect(self.update)

    # ------------------------------------------------------------ geometria
    @property
    def seq(self):
        return self.model.seq

    def rows(self) -> list[tuple[str, int, float, float]]:
        """(tipo, faixa, y, altura) na ordem da tela."""
        out = []
        y = RULER_H - self.yscroll
        nv = len(self.seq.kind_tracks(VIDEO))
        for i in reversed(range(nv)):
            out.append((VIDEO, i, y, float(VIDEO_H)))
            y += VIDEO_H
        y += GAP_H
        for i in range(len(self.seq.kind_tracks(AUDIO))):
            out.append((AUDIO, i, y, float(AUDIO_H)))
            y += AUDIO_H
        return out

    def content_height(self) -> float:
        return (len(self.seq.kind_tracks(VIDEO)) * VIDEO_H + GAP_H
                + len(self.seq.kind_tracks(AUDIO)) * AUDIO_H)

    def lanes_width(self) -> float:
        return max(1.0, self.width() - HEADER_W)

    def visible_frames(self) -> float:
        return self.lanes_width() / self.ppf

    def frame_to_x(self, f: float) -> float:
        return HEADER_W + (f - self.scroll) * self.ppf

    def x_to_frame(self, x: float) -> float:
        return self.scroll + (x - HEADER_W) / self.ppf

    def track_rect(self, kind: str, idx: int) -> QRectF | None:
        for k, i, y, h in self.rows():
            if k == kind and i == idx:
                return QRectF(HEADER_W, y, self.lanes_width(), h)
        return None

    def track_at(self, y: float) -> tuple[str, int] | None:
        for k, i, ty, h in self.rows():
            if ty <= y < ty + h:
                return k, i
        return None

    def clip_rect(self, clip: Clip) -> QRectF | None:
        r = self.track_rect(clip.kind, clip.track)
        if r is None:
            return None
        x0 = self.frame_to_x(clip.start)
        x1 = self.frame_to_x(clip.end)
        return QRectF(x0, r.top() + 3, max(1.0, x1 - x0), r.height() - 6)

    def hit(self, pos: QPointF) -> tuple[Clip | None, str]:
        """Clipe sob o ponto e a zona: "left" / "right" (aparar) ou "body" (mover)."""
        if pos.x() < HEADER_W or pos.y() < RULER_H:
            return None, ""
        for c in reversed(self.seq.clips):
            r = self.clip_rect(c)
            if r is None or not r.adjusted(0, -3, 0, 3).contains(pos):
                continue
            edge = min(EDGE_PX, r.width() / 4)
            if pos.x() - r.left() <= edge:
                return c, "left"
            if r.right() - pos.x() <= edge:
                return c, "right"
            return c, "body"
        return None, ""

    # ------------------------------------------------------------ vista
    def set_ppf(self, ppf: float, anchor_x: float | None = None) -> None:
        ppf = min(max(float(ppf), MIN_PPF), MAX_PPF)
        if anchor_x is None:
            anchor_x = HEADER_W + self.lanes_width() / 2
        f = self.x_to_frame(anchor_x)
        self.ppf = ppf
        self.scroll = max(0.0, f - (anchor_x - HEADER_W) / ppf)
        self.viewChanged.emit()
        self.update()

    def set_scroll(self, frames: float) -> None:
        self.scroll = max(0.0, float(frames))
        self.viewChanged.emit()
        self.update()

    def set_yscroll(self, px: float) -> None:
        top = max(0.0, self.content_height() - (self.height() - RULER_H))
        self.yscroll = min(max(0.0, float(px)), top)
        self.viewChanged.emit()
        self.update()

    def zoom_fit(self) -> None:
        dur = max(self.seq.duration, int(self.seq.fps * 10))
        self.ppf = min(max((self.lanes_width() - 24) / max(dur, 1), MIN_PPF), MAX_PPF)
        self.scroll = 0.0
        self.viewChanged.emit()
        self.update()

    def set_playhead(self, frame: int) -> None:
        frame = max(0, int(frame))
        if frame == self.playhead:
            return
        self.playhead = frame
        if self.follow and self._drag is None:
            x = self.frame_to_x(frame)
            if x > self.width() - 20 or x < HEADER_W:
                self.scroll = max(0.0, frame - self.visible_frames() * 0.1)
                self.viewChanged.emit()
        self.update()

    def set_inout(self, a: int | None, b: int | None) -> None:
        self.inp, self.outp = a, b
        self.update()

    def set_tool(self, tool: str) -> None:
        if tool not in ("select", "blade") or tool == self.tool:
            return
        self.tool = tool
        self.setCursor(Qt.CursorShape.IBeamCursor if tool == "blade" else Qt.CursorShape.ArrowCursor)
        self.toolChanged.emit(tool)
        self.update()

    def _model_changed(self, _kind: str) -> None:
        self.set_yscroll(self.yscroll)
        self.viewChanged.emit()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.set_yscroll(self.yscroll)

    # ------------------------------------------------------------ ímã
    def snap_points(self, exclude: set[str]) -> list[int]:
        pts = {0, int(self.playhead)}
        if self.inp is not None:
            pts.add(int(self.inp))
        if self.outp is not None:
            pts.add(int(self.outp) + 1)
        for c in self.seq.clips:
            if c.id not in exclude:
                pts.add(c.start)
                pts.add(c.end)
        return sorted(pts)

    def snap_frame(self, frame: float, exclude: set[str], enabled: bool | None = None) -> tuple[int, int | None]:
        """Quadro arredondado e, se o ímã pegou, o ponto onde grudou."""
        enabled = self.snap if enabled is None else enabled
        f = int(round(frame))
        if not enabled:
            return f, None
        tol = SNAP_PX / self.ppf
        best, dist = None, tol
        for p in self.snap_points(exclude):
            d = abs(p - frame)
            if d <= dist:
                best, dist = p, d
        return (best, best) if best is not None else (f, None)

    # ------------------------------------------------------------ desenho
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.BG))
        rows = self.rows()
        p.save()
        p.setClipRect(QRectF(HEADER_W, RULER_H, w - HEADER_W, h - RULER_H))
        for n, (kind, idx, y, rh) in enumerate(rows):
            tr = self.seq.track(kind, idx)
            col = QColor(theme.TRACK_BG if n % 2 == 0 else theme.TRACK_BG2)
            p.fillRect(QRectF(HEADER_W, y, w - HEADER_W, rh), col)
            p.fillRect(QRectF(HEADER_W, y + rh - 1, w - HEADER_W, 1), QColor(theme.BORDER))
            if tr is not None and tr.locked:
                p.fillRect(QRectF(HEADER_W, y, w - HEADER_W, rh), QColor(255, 255, 255, 8))
        if rows:
            gap_y = next((y for k, _i, y, _h in rows if k == AUDIO), None)
            if gap_y is not None:
                p.fillRect(QRectF(HEADER_W, gap_y - GAP_H, w - HEADER_W, GAP_H), QColor(theme.PANEL))
        self._paint_inout_lanes(p, h)
        fm = QFontMetrics(theme.font(8.5))
        x_min, x_max = HEADER_W - 2, w + 2
        moving = self._moving_ids()
        for c in self.seq.clips:
            r = self.clip_rect(c)
            if r is None or r.right() < x_min or r.left() > x_max:
                continue
            self._paint_clip(p, c, r, fm, dim=c.id in moving)
        self._paint_audio_transitions(p, x_min, x_max)
        self._paint_ghosts(p)
        self._paint_keys(p)
        if not self.seq.clips:
            p.setPen(QColor(theme.FAINT))
            p.setFont(theme.font(9.5))
            p.drawText(QRectF(HEADER_W, RULER_H, w - HEADER_W, h - RULER_H), Qt.AlignmentFlag.AlignCenter,
                       _("Arraste vídeos, imagens ou músicas para cá\nou use Importar e \"Adicionar à linha do tempo\"."))
        if self._drop is not None:
            x = self._drop[0]
            if self._drop[3]:
                self._paint_insert_mark(p, x, h)
            else:
                p.setPen(QPen(QColor(theme.ACCENT_HI), 2))
                p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        if self.tool == "blade" and self._hover_x is not None and self._hover_x >= HEADER_W:
            p.setPen(QPen(QColor(theme.DANGER), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(self._hover_x, RULER_H), QPointF(self._hover_x, h))
        if self._snap_x is not None:
            p.setPen(QPen(QColor(theme.ACCENT_HI), 1))
            p.drawLine(QPointF(self._snap_x, RULER_H), QPointF(self._snap_x, h))
        for mk, frame in self._marker_frames():
            col = marker_color(mk.color)
            col.setAlpha(150 if mk.id == self.model.marker_sel else 70)
            x = self.frame_to_x(frame)
            p.setPen(QPen(col, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        xp = self.frame_to_x(self.playhead)
        p.setPen(QPen(QColor(theme.PLAYHEAD), 1.5))
        p.drawLine(QPointF(xp, RULER_H), QPointF(xp, h))
        p.restore()
        self._paint_ruler(p, w)
        self._paint_headers(p, rows, h)
        p.end()

    def _paint_inout_lanes(self, p: QPainter, h: float) -> None:
        if self.inp is None and self.outp is None:
            return
        a = self.frame_to_x(self.inp or 0)
        b = self.frame_to_x((self.outp + 1) if self.outp is not None else max(self.seq.duration, 1))
        p.fillRect(QRectF(a, RULER_H, max(b - a, 1), h - RULER_H), QColor(240, 166, 58, 14))

    def _clip_colors(self, c: Clip) -> tuple[QColor, QColor]:
        if c.kind == AUDIO:
            return QColor(theme.CLIP_AUDIO), QColor(theme.CLIP_AUDIO_HI)
        src = self.seq.sources.get(c.src)
        if src is not None and src.is_image:
            return QColor(theme.CLIP_IMAGE), QColor(theme.CLIP_VIDEO_HI)
        return QColor(theme.CLIP_VIDEO), QColor(theme.CLIP_VIDEO_HI)

    def _paint_clip(self, p: QPainter, c: Clip, r: QRectF, fm: QFontMetrics, dim: bool = False) -> None:
        base, hi = self._clip_colors(c)
        selected = c.id in self.model.selection
        muted = c.kind == AUDIO and bool(c.values.get("mudo"))
        if muted or dim:
            base.setAlpha(110)
        p.setPen(QPen(QColor(theme.ACCENT_HI) if selected else base.darker(160), 2 if selected else 1))
        p.setBrush(base)
        p.drawRoundedRect(r, 5, 5)
        p.save()
        p.setClipRect(r.adjusted(1, 1, -1, -1))
        if c.kind == AUDIO:
            self._paint_wave(p, c, r)
        else:
            self._paint_transitions(p, c, r)
        # Rótulo: nome, velocidade, ligação.
        p.setFont(theme.font(8.5, theme.QFont.Weight.DemiBold))
        p.setPen(QColor("#fff6e8") if not muted else QColor(theme.MUTED))
        text_x = max(r.left(), HEADER_W) + 6
        src = self.seq.sources.get(c.src)
        label = c.name or (src.name if src is not None else "")
        extra = []
        if abs(c.speed - 1.0) > 1e-6:
            extra.append(f"{c.speed:g}".replace(".", decimal_sep()) + "×")
        if c.frozen:
            extra.append(_("congelado"))
        if c.ramp and not c.frozen:
            extra.append(_("rampa"))
        if muted:
            extra.append(_("mudo"))
        full = label + (("  •  " + "  ".join(extra)) if extra else "")
        avail = r.right() - text_x - 6
        if avail > 16:
            p.drawText(QRectF(text_x, r.top() + 2, avail, 16), Qt.AlignmentFlag.AlignVCenter,
                       _elide(fm, full, avail))
            if c.kind == VIDEO and r.height() > 34 and avail > 60:
                p.setFont(theme.font(7.8))
                p.setPen(QColor(255, 246, 232, 150))
                p.drawText(QRectF(text_x, r.bottom() - 16, avail, 14), Qt.AlignmentFlag.AlignVCenter,
                           _elide(fm, timecode(c.dur, self.seq.fps), avail))
        p.restore()

    def _paint_transitions(self, p: QPainter, c: Clip, r: QRectF) -> None:
        v = c.values
        fps = self.seq.fps
        p.setPen(Qt.PenStyle.NoPen)
        if v.get("entrada_tipo", "corte") != "corte":
            wpx = min(r.width(), v["entrada_dur"] * fps * self.ppf)
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left() + wpx, r.top())
            path.lineTo(r.left(), r.top())
            path.closeSubpath()
            col = QColor(255, 255, 255, 60) if v["entrada_tipo"] in ("branco", "dissolver") else QColor(0, 0, 0, 90)
            p.setBrush(col)
            p.drawPath(path)
        if v.get("saida_tipo", "corte") != "corte":
            wpx = min(r.width(), v["saida_dur"] * fps * self.ppf)
            path = QPainterPath()
            path.moveTo(r.right(), r.bottom())
            path.lineTo(r.right() - wpx, r.top())
            path.lineTo(r.right(), r.top())
            path.closeSubpath()
            col = QColor(255, 255, 255, 60) if v["saida_tipo"] in ("branco", "transparente") else QColor(0, 0, 0, 90)
            p.setBrush(col)
            p.drawPath(path)

    def audio_transition_span(self, c: Clip) -> tuple[float, float] | None:
        """(x inicial, x final) da transição de som que entra em `c`, na largura que de fato cabe."""
        if c.kind != AUDIO or not c.values.get("transicao"):
            return None
        prev, before, after = self.seq.audio_crossfade(c)
        if prev is None:
            return None
        fps = self.seq.fps
        return self.frame_to_x(c.start - before * fps), self.frame_to_x(c.start + after * fps)

    def _paint_audio_transitions(self, p: QPainter, x_min: float, x_max: float) -> None:
        """Transição de som: as curvas seno (entra) e cosseno (sai) cruzando sobre o corte. Sem sobra de
        arquivo para ela, só um traço vermelho no corte."""
        for c in self.seq.clips:
            span = self.audio_transition_span(c)
            r = self.clip_rect(c) if span else None
            if r is None or span[1] < x_min or span[0] > x_max:
                continue
            x0, x1 = span
            top, bot = r.top() + 3, r.bottom() - 3
            if x1 - x0 < 2:
                p.setPen(QPen(QColor(theme.DANGER), 2))
                p.drawLine(QPointF(r.left(), top), QPointF(r.left(), bot))
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(QRectF(x0, top, x1 - x0, bot - top), 3, 3)
            n = max(8, int((x1 - x0) / 3))
            rise, fall = QPainterPath(), QPainterPath()
            for i in range(n + 1):
                k = i / n
                x = x0 + k * (x1 - x0)
                y_in = bot - (bot - top) * math.sin(k * math.pi / 2)
                y_out = bot - (bot - top) * math.cos(k * math.pi / 2)
                if i == 0:
                    rise.moveTo(x, y_in)
                    fall.moveTo(x, y_out)
                else:
                    rise.lineTo(x, y_in)
                    fall.lineTo(x, y_out)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.ACCENT_HI), 1.4))
            p.drawPath(rise)
            p.drawPath(fall)

    def _paint_wave(self, p: QPainter, c: Clip, r: QRectF) -> None:
        peaks = self.peaks_provider(c.src) if self.peaks_provider else None
        mid = r.top() + 18 + (r.height() - 20) / 2
        amp_h = (r.height() - 22) / 2
        gain = 10 ** (float(c.values.get("volume", 0.0)) / 20.0)
        x0 = max(r.left(), HEADER_W)
        x1 = min(r.right(), self.width())
        if x1 <= x0:
            return
        if peaks is None or len(peaks) == 0:
            p.setPen(QPen(QColor(255, 255, 255, 45), 1))
            p.drawLine(QPointF(x0, mid), QPointF(x1, mid))
            return
        n = int(x1 - x0) + 1
        xs = np.linspace(x0, x1, n)
        frames = self.scroll + (xs - HEADER_W) / self.ppf
        if c.retimed:  # rampa ou reverso: o segundo do arquivo vem do mapa do clipe (o mesmo do som)
            m = self.seq.time_map(c)
            t = np.array([m.src_at((f - c.start) / self.seq.fps) for f in frames])
        else:
            t = c.src_in + (frames - c.start) / self.seq.fps * c.speed
        idx = np.clip((t * PEAKS_PER_SECOND).astype(np.int64), 0, len(peaks) - 1)
        step = max(1, int(round(c.speed * PEAKS_PER_SECOND / (self.seq.fps * self.ppf))))
        if step > 1:
            # Afastado: o maior pico entre duas colunas (para não sumir com os transientes).
            ends = np.minimum(idx + step, len(peaks))
            vals = np.array([peaks[a:b].max() if b > a else peaks[a] for a, b in zip(idx, ends)])
        else:
            vals = np.asarray(peaks)[idx]
        vals = np.clip(vals * gain, 0.0, 1.0)
        fade_in = float(c.values.get("fade_in", 0.0))
        fade_out = float(c.values.get("fade_out", 0.0))
        if fade_in > 0 or fade_out > 0:
            pos = (frames - c.start) / self.seq.fps
            rest = (c.end - frames) / self.seq.fps
            env = np.ones_like(pos)
            if fade_in > 0:
                env = np.minimum(env, np.clip(pos / fade_in, 0, 1))
            if fade_out > 0:
                env = np.minimum(env, np.clip(rest / fade_out, 0, 1))
            vals = vals * env
        path = QPainterPath()
        path.moveTo(xs[0], mid - vals[0] * amp_h)
        for x, v in zip(xs[1:], vals[1:]):
            path.lineTo(x, mid - v * amp_h)
        for x, v in zip(xs[::-1], vals[::-1]):
            path.lineTo(x, mid + v * amp_h)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(210, 255, 245, 120))
        p.drawPath(path)

    def _moving_ids(self) -> set[str]:
        d = self._drag
        if not d or d.get("mode") not in ("move", "left", "right") or not d.get("active"):
            return set()
        return set(self._drag_ids(d))

    @staticmethod
    def _drag_ids(d: dict) -> list[str]:
        """Clipes que o arraste muda: o grupo, ou só o clipe ao aparar com Alt (corte J/L)."""
        return [d["clip"]] if d.get("solo") and d["mode"] != "move" else list(d["group"])

    def _paint_insert_mark(self, p: QPainter, x: float, h: float) -> None:
        """Ponto de inserção: linha cheia com setas para a direita (o que vem depois vai andar)."""
        p.setPen(QPen(QColor(theme.ACCENT_HI), 2))
        p.drawLine(QPointF(x, RULER_H), QPointF(x, h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT_HI))
        for y in (RULER_H + 2, h - 12):
            p.drawPolygon(QPolygonF([QPointF(x + 2, y), QPointF(x + 10, y + 5), QPointF(x + 2, y + 10)]))

    def _paint_ghosts(self, p: QPainter) -> None:
        d = self._drag
        if not d or not d.get("active") or d.get("mode") not in ("move", "left", "right"):
            return
        ghosts = self.ghosts()
        if d["mode"] == "move" and d.get("insert") and ghosts:
            self._paint_insert_mark(p, self.frame_to_x(min(g[0] for g in ghosts.values())), self.height())
        p.setPen(QPen(QColor(theme.ACCENT_HI), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(QColor(240, 166, 58, 40))
        for cid, (start, dur, kind, track) in ghosts.items():
            tr = self.track_rect(kind, track)
            if tr is None:
                # Faixa nova (arrastou acima da última): desenha logo acima/abaixo.
                rows = [r for r in self.rows() if r[0] == kind]
                if not rows:
                    continue
                k, i, y, h = rows[0] if kind == VIDEO else rows[-1]
                tr = QRectF(HEADER_W, y - h if kind == VIDEO else y + h, self.lanes_width(), h)
            x0 = self.frame_to_x(start)
            x1 = self.frame_to_x(start + dur)
            p.drawRoundedRect(QRectF(x0, tr.top() + 3, max(1.0, x1 - x0), tr.height() - 6), 5, 5)

    def ghosts(self) -> dict[str, tuple[int, int, str, int]]:
        """Posição prevista de cada clipe arrastado: id → (início, duração, tipo, faixa)."""
        d = self._drag
        if not d or d.get("mode") not in ("move", "left", "right"):
            return {}
        out = {}
        for cid in self._drag_ids(d):
            c = self.seq.find(cid)
            if c is None:
                continue
            o_start, o_dur, o_track = d["orig"][cid]
            if d["mode"] == "move":
                track = d["track"] if cid == d["clip"] else o_track
                out[cid] = (max(0, o_start + d["delta"]), o_dur, c.kind, track)
            elif d["mode"] == "left":
                ns = min(o_start + d["delta"], o_start + o_dur - 1)
                ns = max(0, ns)
                out[cid] = (ns, o_start + o_dur - ns, c.kind, o_track)
            else:
                out[cid] = (o_start, max(1, o_dur + d["delta"]), c.kind, o_track)
        return out

    def _paint_ruler(self, p: QPainter, w: float) -> None:
        p.fillRect(QRectF(0, 0, w, RULER_H), QColor(theme.PANEL))
        p.fillRect(QRectF(0, RULER_H - 1, w, 1), QColor(theme.BORDER))
        fps = self.seq.fps
        if self.inp is not None or self.outp is not None:
            a = self.frame_to_x(self.inp or 0)
            b = self.frame_to_x((self.outp + 1) if self.outp is not None else max(self.seq.duration, 1))
            p.fillRect(QRectF(max(a, HEADER_W), RULER_H - 7, max(b - max(a, HEADER_W), 0), 6),
                       QColor(240, 166, 58, 110))
        px_per_sec = self.ppf * fps
        step = next((s for s in _RULER_STEPS if s * px_per_sec >= 90), _RULER_STEPS[-1])
        label_frames = step * fps
        if px_per_sec * 1 > 90 * 4 and self.ppf >= 6:
            # Muito perto: rótulos a cada poucos quadros.
            nominal = max(1, int(round(fps)))
            fstep = next((k for k in (1, 2, 5, 10) if k * self.ppf >= 90), nominal)
            label_frames = fstep
        f0 = self.x_to_frame(HEADER_W)
        f1 = self.x_to_frame(w)
        p.setFont(theme.font(7.8))
        fm = QFontMetrics(p.font())
        minor = label_frames / 5.0
        if minor * self.ppf >= 6:
            k = math.floor(f0 / minor)
            pen = QPen(QColor(255, 255, 255, 40), 1)
            p.setPen(pen)
            while k * minor <= f1:
                x = self.frame_to_x(k * minor)
                if x >= HEADER_W:
                    p.drawLine(QPointF(x, RULER_H - 5), QPointF(x, RULER_H - 1))
                k += 1
        k = math.floor(f0 / label_frames)
        while k * label_frames <= f1:
            f = k * label_frames
            x = self.frame_to_x(f)
            if x >= HEADER_W - 1:
                p.setPen(QPen(QColor(255, 255, 255, 90), 1))
                p.drawLine(QPointF(x, RULER_H - 11), QPointF(x, RULER_H - 1))
                txt = timecode(int(round(f)), fps)
                p.setPen(QColor(theme.MUTED))
                p.drawText(QPointF(x + 4, 13), _elide(fm, txt, label_frames * self.ppf - 6))
            k += 1
        self._paint_markers(p, w)
        xp = self.frame_to_x(self.playhead)
        if xp >= HEADER_W - 6:
            path = QPainterPath()
            path.moveTo(xp - 6, RULER_H - 12)
            path.lineTo(xp + 6, RULER_H - 12)
            path.lineTo(xp + 6, RULER_H - 6)
            path.lineTo(xp, RULER_H)
            path.lineTo(xp - 6, RULER_H - 6)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.PLAYHEAD))
            p.drawPath(path)
        # Canto da régua sobre a coluna das faixas: tempo do cursor.
        p.fillRect(QRectF(0, 0, HEADER_W, RULER_H), QColor(theme.PANEL))
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(8.5))
        p.drawText(QRectF(10, 0, HEADER_W - 12, RULER_H), Qt.AlignmentFlag.AlignVCenter,
                   timecode(self.playhead, fps))
        p.fillRect(QRectF(HEADER_W - 1, 0, 1, self.height()), QColor(theme.BORDER))

    # ------------------------------------------------------------ marcadores
    def _marker_frames(self) -> list[tuple["timeline.Marker", int]]:
        """(marcador, quadro na tela): o que está sendo arrastado aparece onde vai ficar."""
        d = self._drag or {}
        moving = d.get("id") if d.get("mode") == "marker" and d.get("active") else None
        return [(mk, d["frame"] if mk.id == moving else mk.frame) for mk in self.seq.sorted_markers()]

    def _paint_markers(self, p: QPainter, w: float) -> None:
        top, bottom = RULER_H - 15.0, RULER_H - 1.0
        half = MARKER_W / 2
        for mk, frame in self._marker_frames():
            x = self.frame_to_x(frame)
            if x < HEADER_W - half or x > w + half:
                continue
            path = QPainterPath()
            path.moveTo(x - half, top)
            path.lineTo(x + half, top)
            path.lineTo(x + half, bottom - 5)
            path.lineTo(x, bottom)
            path.lineTo(x - half, bottom - 5)
            path.closeSubpath()
            col = marker_color(mk.color)
            selected = mk.id == self.model.marker_sel
            p.setPen(QPen(QColor(theme.TEXT), 1.6) if selected else QPen(col.darker(170), 1))
            p.setBrush(col)
            p.drawPath(path)
            if mk.chapter:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(QPointF(x, top + 4.5), 1.8, 1.8)

    def marker_at(self, pos: QPointF):
        """Marcador sob o ponto da régua (o mais perto), ou None."""
        if pos.y() >= RULER_H or pos.x() < HEADER_W - MARKER_HIT:
            return None
        best, dist = None, MARKER_HIT + 0.5
        for mk, frame in self._marker_frames():
            dx = abs(self.frame_to_x(frame) - pos.x())
            if dx <= dist:
                best, dist = mk, dx
        return best

    def add_marker_at(self, frame: int | None = None):
        """Marcador no quadro (padrão: no cursor); se já há um ali, só o seleciona."""
        return self.model.add_marker(self.playhead if frame is None else max(0, int(frame)))

    def goto_marker(self, step: int) -> None:
        """Leva o cursor ao próximo (step > 0) ou ao anterior marcador."""
        mk = self.seq.next_marker(self.playhead) if step > 0 else self.seq.previous_marker(self.playhead)
        if mk is not None:
            self.model.select_marker(mk.id)
            self.seekRequested.emit(mk.frame)

    def edit_marker(self, mid: str) -> None:
        mk = self.seq.marker(mid)
        if mk is None:
            return
        self.model.select_marker(mid)
        dlg = MarkerDialog(self, mk, self.seq.fps)
        if not dlg.exec():
            return
        if dlg.removed:
            self.model.remove_marker(mid)
        else:
            self.model.update_marker(mid, **dlg.values())

    def copy_chapters(self) -> None:
        """Capítulos para o YouTube (contados da entrada, se há um trecho marcado, como na exportação)."""
        start = int(self.inp or 0)
        end = int(self.outp) + 1 if self.outp is not None else self.seq.duration
        text, problems = youtube_chapters(self.seq, start, end)
        note = _("Tempos contados a partir da entrada (I), como na exportação do trecho.") if start else ""
        ChaptersDialog(self, text, problems, note).exec()

    def header_buttons(self, kind: str, idx: int, y: float, h: float) -> dict[str, QRectF]:
        """Retângulos dos botões do cabeçalho de uma faixa."""
        top = y + 6
        out = {"lock": QRectF(HEADER_W - 8 - BTN, top, BTN, BTN),
               "mute": QRectF(HEADER_W - 12 - 2 * BTN, top, BTN, BTN)}
        if kind == AUDIO:
            out["solo"] = QRectF(HEADER_W - 16 - 3 * BTN, top, BTN, BTN)
            out["volume"] = QRectF(10, y + h - 12, HEADER_W - 26, 6)
        return out

    @staticmethod
    def volume_to_t(db: float) -> float:
        return (min(max(db, -60.0), 12.0) + 60.0) / 72.0

    @staticmethod
    def t_to_volume(t: float) -> float:
        return round(min(max(t, 0.0), 1.0) * 72.0 - 60.0, 1)

    def _paint_headers(self, p: QPainter, rows, h: float) -> None:
        p.save()
        p.setClipRect(QRectF(0, RULER_H, HEADER_W, h - RULER_H))
        p.fillRect(QRectF(0, RULER_H, HEADER_W - 1, h - RULER_H), QColor(theme.PANEL))
        for kind, idx, y, rh in rows:
            tr = self.seq.track(kind, idx)
            if tr is None:
                continue
            p.fillRect(QRectF(0, y + rh - 1, HEADER_W, 1), QColor(theme.BORDER))
            mark = QColor(theme.CLIP_VIDEO if kind == VIDEO else theme.CLIP_AUDIO)
            p.fillRect(QRectF(0, y + 4, 3, rh - 8), mark)
            p.setPen(QColor(theme.TEXT if not tr.muted else theme.FAINT))
            p.setFont(theme.font(9, theme.QFont.Weight.DemiBold, title=True))
            p.drawText(QRectF(12, y + 6, 40, BTN), Qt.AlignmentFlag.AlignVCenter, tr.name)
            btns = self.header_buttons(kind, idx, y, rh)
            if kind == VIDEO and idx == 0 and self.seq.magnetic:
                # Faixa principal magnética (Configurar a sequência): ímã no lugar do botão "solo" do áudio.
                r = QRectF(HEADER_W - 16 - 3 * BTN, y + 6, BTN, BTN).toRect()
                p.drawPixmap(r, icons.icon("magnet", theme.ACCENT_HI if not tr.locked else theme.FAINT,
                                           16).pixmap(QSize(16, 16)))
            states = {"lock": ("lock" if tr.locked else "unlock", tr.locked),
                      "mute": ((("eye_off" if tr.muted else "eye") if kind == VIDEO
                                else ("mute" if tr.muted else "volume")), tr.muted)}
            if kind == AUDIO:
                states["solo"] = ("headphones", tr.solo)
            for name, (ic, on) in states.items():
                r = btns[name]
                if on:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(theme.ACCENT_DIM))
                    p.drawRoundedRect(r, 4, 4)
                color = theme.ACCENT_HI if on else theme.MUTED
                p.drawPixmap(r.toRect(), icons.icon(ic, color, 16).pixmap(QSize(16, 16)))
            if kind == AUDIO and "volume" in btns:
                r = btns["volume"]
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.PANEL3))
                p.drawRoundedRect(r, 3, 3)
                t = self.volume_to_t(tr.volume)
                p.setBrush(QColor(theme.CLIP_AUDIO_HI))
                p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * t, r.height()), 3, 3)
                zero = r.left() + r.width() * self.volume_to_t(0.0)
                p.setBrush(QColor(255, 255, 255, 120))
                p.drawRect(QRectF(zero - 0.5, r.top() - 1, 1, r.height() + 2))
        p.restore()

    # ------------------------------------------------------------ mouse
    def _header_hit(self, pos: QPointF) -> tuple[str, int, str] | None:
        if pos.x() >= HEADER_W or pos.y() < RULER_H:
            return None
        for kind, idx, y, h in self.rows():
            if y <= pos.y() < y + h:
                for name, r in self.header_buttons(kind, idx, y, h).items():
                    if r.adjusted(-2, -3, 2, 3).contains(pos):
                        return kind, idx, name
                return kind, idx, ""
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        self.setFocus()
        if e.button() == Qt.MouseButton.RightButton:
            self._context_menu(e)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        mk = self.marker_at(pos)
        if mk is not None:
            self.model.select_marker(mk.id)
            self._drag = {"mode": "marker", "id": mk.id, "press_x": pos.x(), "orig": mk.frame, "frame": mk.frame,
                          "active": False}
            return
        if pos.y() < RULER_H and pos.x() >= HEADER_W:
            self._drag = {"mode": "scrub"}
            self.scrubbing.emit(True)
            self.seekRequested.emit(max(0, int(round(self.x_to_frame(pos.x())))))
            return
        hh = self._header_hit(pos)
        if hh is not None:
            kind, idx, name = hh
            tr = self.seq.track(kind, idx)
            if tr is None:
                return
            if name == "lock":
                self.model.set_track(kind, idx, locked=not tr.locked)
            elif name == "mute":
                self.model.set_track(kind, idx, muted=not tr.muted)
            elif name == "solo":
                self.model.set_track(kind, idx, solo=not tr.solo)
            elif name == "volume":
                self._drag = {"mode": "volume", "kind": kind, "idx": idx}
                self._set_volume_from(pos.x())
            return
        if self.tool != "blade" and self.key_press(pos, e.modifiers()):
            return
        clip, zone = self.hit(pos)
        mods = e.modifiers()
        if clip is None:
            if not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                self.model.select([])
            return
        if self.tool == "blade":
            f, _snapped = self.snap_frame(self.x_to_frame(pos.x()), set())
            if clip.start < f < clip.end:
                self.model.split_clip(clip.id, f)
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.model.select_group(clip.id, toggle=True)
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            self.model.select_group(clip.id, add=True)
        elif clip.id not in self.model.selection:
            self.model.select_group(clip.id)
        if self.seq.locked(clip):
            return
        group = [g.id for g in self.seq.group(clip) if not self.seq.locked(g)]
        self._drag = {"mode": "move" if zone == "body" else zone, "clip": clip.id, "group": group,
                      "press_x": pos.x(), "press_frame": self.x_to_frame(pos.x()), "delta": 0,
                      "track": clip.track, "active": False,
                      "orig": {g: (self.seq.find(g).start, self.seq.find(g).dur, self.seq.find(g).track)
                               for g in group}}

    def _set_volume_from(self, x: float) -> None:
        d = self._drag
        r = QRectF(10, 0, HEADER_W - 26, 1)
        t = (x - r.left()) / r.width()
        self.model.set_track(d["kind"], d["idx"], volume=self.t_to_volume(t))

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._hover_x = pos.x()
        d = self._drag
        if d is None:
            self._update_cursor(pos)
            if self.tool == "blade":
                self.update()
            return
        mode = d["mode"]
        if mode == "keys":
            self.key_drag(pos, e.modifiers())
            return
        if mode == "scrub":
            self.seekRequested.emit(max(0, int(round(self.x_to_frame(pos.x())))))
            return
        if mode == "volume":
            self._set_volume_from(pos.x())
            return
        if mode == "marker":
            if not d["active"] and abs(pos.x() - d["press_x"]) < 3:
                return
            d["active"] = True
            snap_on = self.snap != bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            f, s = self.snap_frame(d["orig"] + (pos.x() - d["press_x"]) / self.ppf, set(), snap_on)
            d["frame"] = max(0, f)
            self._snap_x = self.frame_to_x(s) if s is not None else None
            self.update()
            return
        clip = self.seq.find(d["clip"])
        if clip is None:
            self._drag = None
            return
        if not d["active"]:
            same_row = self.track_at(pos.y()) == (clip.kind, d["track"])
            if abs(pos.x() - d["press_x"]) < 3 and (mode != "move" or same_row):
                return
        d["active"] = True
        d["insert"] = self.insert_for(e.modifiers())
        d["solo"] = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
        exclude = set(d["group"])
        raw = self.x_to_frame(pos.x()) - d["press_frame"]
        o_start, o_dur, _o_track = d["orig"][d["clip"]]
        snap_on = self.snap != bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._snap_x = None
        if mode == "move":
            delta = int(round(raw))
            if snap_on:
                tol = SNAP_PX / self.ppf
                best = None
                for edge in (o_start, o_start + o_dur):
                    target = edge + raw
                    f, s = self.snap_frame(target, exclude, True)
                    if s is not None and (best is None or abs(f - target) < best[0]):
                        best = (abs(f - target), f - edge, f)
                if best is not None and best[0] <= tol:
                    delta = int(best[1])
                    self._snap_x = self.frame_to_x(best[2])
            min_start = min(st for st, _du, _tr in d["orig"].values())
            d["delta"] = max(delta, -min_start)
            hit = self.track_at(pos.y())
            rows = [r for r in self.rows() if r[0] == clip.kind]
            if hit is not None and hit[0] == clip.kind:
                d["track"] = hit[1]
            elif rows and clip.kind == VIDEO and pos.y() < rows[0][2]:
                d["track"] = len(rows)  # acima da última faixa de vídeo: cria uma nova
            elif rows and clip.kind == AUDIO and pos.y() >= rows[-1][2] + rows[-1][3]:
                d["track"] = len(rows)  # abaixo da última faixa de áudio: cria uma nova
        else:
            edge = o_start if mode == "left" else o_start + o_dur
            f, s = self.snap_frame(edge + raw, exclude, snap_on)
            d["delta"] = f - edge
            if s is not None:
                self._snap_x = self.frame_to_x(s)
        self.update()

    def mouseReleaseEvent(self, e):
        d = self._drag
        self._drag = None
        self._snap_x = None
        if d is None:
            return
        mode = d["mode"]
        if mode == "keys":
            self.key_release(d)
            return
        if mode == "scrub":
            self.scrubbing.emit(False)
            self.seekRequested.emit(max(0, int(round(self.x_to_frame(e.position().x())))))
            return
        if mode == "volume":
            self.model.commit()
            return
        if mode == "marker":
            if d["active"]:
                if d["frame"] != d["orig"]:
                    self.model.move_marker(d["id"], d["frame"])
            else:
                self.seekRequested.emit(d["orig"])  # clique simples: o cursor vai até o marcador
            self.update()
            return
        if not d.get("active"):
            self.update()
            return
        cid = d["clip"]
        o_start, o_dur, o_track = d["orig"][cid]
        mods = e.modifiers()
        solo = bool(mods & Qt.KeyboardModifier.AltModifier) or bool(d.get("solo"))
        if mode == "move":
            if d["delta"] or d["track"] != o_track:
                self.model.move_clip(cid, o_start + d["delta"], d["track"] if d["track"] != o_track else None,
                                     insert=self.insert_for(mods))
        elif mode == "left":
            if d["delta"]:
                self.model.trim_start(cid, o_start + d["delta"], solo=solo)
        elif mode == "right":
            if d["delta"]:
                self.model.trim_end(cid, o_start + o_dur + d["delta"], solo=solo)
        self.update()

    # ------------------------------------------------------------ chaves do clipe selecionado
    def key_clips(self) -> list[Clip]:
        """Clipes cujas chaves aparecem: os selecionados que têm animação."""
        return [c for c in self.model.selected_clips() if c.keys]

    def key_marks(self, c: Clip) -> list[tuple[float, list[str]]]:
        """Chaves do clipe juntas por quadro da sequência, só as que caem dentro dele."""
        return [(f, names) for f, names in merged_marks(c.keys, lambda tau: self.seq.seq_time(c, tau))
                if c.start <= f < c.end]

    def key_y(self, r: QRectF) -> float:
        return r.top() + r.height() * 0.55

    def key_at(self, pos: QPointF) -> tuple[Clip, float] | None:
        """(clipe, quadro) do losango sob o ponto."""
        best = None
        for c in self.key_clips():
            r = self.clip_rect(c)
            if r is None or abs(pos.y() - self.key_y(r)) > 7 or not (r.left() - 6 <= pos.x() <= r.right() + 6):
                continue
            for f, _names in self.key_marks(c):
                dx = abs(self.frame_to_x(f) - pos.x())
                if dx <= 6 and (best is None or dx < best[0]):
                    best = (dx, c, f)
        return (best[1], best[2]) if best else None

    def _key_offset(self) -> float:
        d = self._drag
        return d["delta"] if d is not None and d.get("mode") == "keys" else 0

    def _paint_keys(self, p: QPainter) -> None:
        sel_clip = self.key_clip if self.seq.find(self.key_clip or "") is not None else None
        off = self._key_offset()
        for c in self.key_clips():
            r = self.clip_rect(c)
            if r is None or r.width() < 10:
                continue
            p.save()
            p.setClipRect(r.adjusted(-6, -2, 6, 2))
            cy = self.key_y(r)
            for f, _names in self.key_marks(c):
                chosen = c.id == sel_clip and f in self.key_sel
                x = self.frame_to_x(f + (off if chosen else 0))
                if chosen:
                    paint_diamond(p, x, cy, 5.0, QColor(theme.PLAYHEAD), QColor("#1a120a"), 1.4)
                else:
                    paint_diamond(p, x, cy, 4.5, QColor("#fff6e8"), QColor("#1a120a"), 1.2)
            p.restore()

    def key_press(self, pos: QPointF, mods) -> bool:
        """Clique num losango: seleciona (Shift soma ou tira) e leva o cursor. True se pegou um."""
        hit = self.key_at(pos)
        if hit is None:
            if self.key_sel:
                self.key_sel = set()
                self.update()
            return False
        c, f = hit
        add = bool(mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier))
        if c.id != self.key_clip:
            self.key_clip, self.key_sel = c.id, set()
        if add:
            self.key_sel ^= {f}
        elif f not in self.key_sel:
            self.key_sel = {f}
        if f in self.key_sel and not self.seq.locked(c):
            self._drag = {"mode": "keys", "clip": c.id, "grab": f, "press_x": pos.x(), "delta": 0, "active": False}
        self.seekRequested.emit(int(round(f)))
        self.update()
        return True

    def key_drag(self, pos: QPointF, mods) -> None:
        d = self._drag
        c = self.seq.find(d["clip"])
        if c is None or not self.key_sel:
            return
        if not d["active"] and abs(pos.x() - d["press_x"]) < 3:
            return
        d["active"] = True
        snap_on = self.snap != bool(mods & Qt.KeyboardModifier.ShiftModifier)
        f, s = self.snap_frame(d["grab"] + (pos.x() - d["press_x"]) / self.ppf, {c.id}, snap_on)
        lo, hi = c.start - min(self.key_sel), c.end - 1 - max(self.key_sel)  # nenhuma sai do clipe
        d["delta"] = int(min(max(f - d["grab"], lo), hi))
        self._snap_x = self.frame_to_x(s) if s is not None and d["delta"] == f - d["grab"] else None
        self.update()

    def key_release(self, d: dict) -> None:
        delta = d["delta"] if d.get("active") else 0
        c = self.seq.find(d["clip"])
        if c is not None and delta:
            moves = [(name, f, f + delta) for f, names in self.key_marks(c) if f in self.key_sel for name in names]
            if self.model.move_keys(c.id, moves):
                self.key_sel = {f + delta for f in self.key_sel}
                self.seekRequested.emit(int(round(d["grab"] + delta)))
        self.update()

    def delete_keys(self) -> bool:
        """Delete com chaves selecionadas: apaga as chaves (um passo do desfazer), não o clipe."""
        c = self.seq.find(self.key_clip or "")
        if c is None or not self.key_sel or c.id not in {x.id for x in self.key_clips()}:
            self.key_sel = set()
            return False
        items = [(name, f) for f, names in self.key_marks(c) if f in self.key_sel for name in names]
        self.key_sel = set()
        self.model.remove_keys(c.id, items)
        self.update()
        return bool(items)

    def key_tooltip(self, pos: QPointF) -> str | None:
        hit = self.key_at(pos)
        if hit is None:
            return None
        c, f = hit
        names = next(n for t, n in self.key_marks(c) if t == f)
        from .. import editparams
        return _("Chave em {tempo}: {ajustes}").format(tempo=timecode(int(round(f)), self.seq.fps),
                                                       ajustes=param_names(editparams.SCHEMAS[c.kind], names))

    def insert_for(self, mods) -> bool:
        """Inserir (empurrar) ou sobrescrever: o modo da barra, invertido enquanto o Ctrl está apertado."""
        return self.insert_mode != bool(mods & Qt.KeyboardModifier.ControlModifier)

    def set_insert_mode(self, on: bool) -> None:
        if self.insert_mode != bool(on):
            self.insert_mode = bool(on)
            self.toolChanged.emit(self.tool)

    def mouseDoubleClickEvent(self, e):
        pos = e.position()
        mk = self.marker_at(pos)
        if mk is not None:
            self._drag = None
            self.edit_marker(mk.id)
            return
        hh = self._header_hit(pos)
        if hh is not None and hh[2] == "volume":
            self.model.set_track(hh[0], hh[1], volume=0.0)
            return
        clip, _zone = self.hit(pos)
        if clip is not None:
            self.model.select_group(clip.id)
            self.clipActivated.emit(clip.id)

    def leaveEvent(self, _e):
        self._hover_x = None
        self.update()

    def _update_cursor(self, pos: QPointF) -> None:
        if self.tool == "blade":
            self.setCursor(Qt.CursorShape.IBeamCursor)
            return
        if pos.y() < RULER_H:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            mk = self.marker_at(pos)
            self.setToolTip(marker_tooltip(mk, self.seq.fps) if mk is not None else "")
            return
        key_tip = self.key_tooltip(pos)
        if key_tip is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(key_tip)
            return
        clip, zone = self.hit(pos)
        if clip is not None and zone in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif clip is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        tip = ""
        hh = self._header_hit(pos)
        if hh is not None:
            kind, idx, name = hh
            tr = self.seq.track(kind, idx)
            tips = {"lock": _("Travar a faixa (nada muda nela)"),
                    "mute": _("Esconder a faixa") if kind == VIDEO else _("Silenciar a faixa"),
                    "solo": _("Solo: ouvir só esta faixa"),
                    "volume": _("Volume da faixa: {db} dB (duplo clique volta a 0)").format(
                        db=f"{tr.volume:+.1f}".replace(".", decimal_sep()) if tr else "0")}
            tip = tips.get(name, "")
        self.setToolTip(tip)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        dx = e.angleDelta().x()
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if dy:
                self.set_ppf(self.ppf * (1.25 if dy > 0 else 0.8), e.position().x())
            e.accept()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier and dy:
            self.set_yscroll(self.yscroll - dy / 120 * 30)
            e.accept()
            return
        move = (dx if dx else dy) / 120.0
        if move:
            self.set_scroll(self.scroll - move * 80 / self.ppf)
        e.accept()

    # ------------------------------------------------------------ menu
    def marker_menu(self, menu: QMenu, mk) -> None:
        m = self.model
        menu.addAction(_("Editar marcador…"), lambda: self.edit_marker(mk.id))
        act = menu.addAction(_("Capítulo (YouTube e arquivo exportado)"))
        act.setCheckable(True)
        act.setChecked(mk.chapter)
        act.toggled.connect(lambda on: m.update_marker(mk.id, chapter=on))
        colors = menu.addMenu(_("Cor"))
        for key, label in timeline.MARKER_COLORS:
            a = colors.addAction(icons.icon("dot", theme.MARKER_COLORS[key], 16), _(label))
            a.setCheckable(True)
            a.setChecked(key == mk.color)
            a.triggered.connect(lambda _on=False, k=key: m.update_marker(mk.id, color=k))
        menu.addSeparator()
        menu.addAction(_("Remover marcador"), lambda: m.remove_marker(mk.id))

    def ruler_menu(self, menu: QMenu, frame: int) -> None:
        menu.addAction(_("Adicionar marcador aqui"), lambda: self.add_marker_at(frame))
        menu.addAction(_("Adicionar marcador no cursor (M)"), lambda: self.add_marker_at())
        menu.addSeparator()
        menu.addAction(_("Copiar capítulos para o YouTube…"), self.copy_chapters)
        act = menu.addAction(_("Remover todos os marcadores"), self.model.clear_markers)
        act.setEnabled(bool(self.seq.markers))

    def _context_menu(self, e) -> None:
        pos = e.position()
        menu = QMenu(self)
        mk = self.marker_at(pos)
        if mk is not None:
            self.model.select_marker(mk.id)
            self.marker_menu(menu, mk)
            menu.exec(e.globalPosition().toPoint())
            return
        if pos.y() < RULER_H and pos.x() >= HEADER_W:
            self.ruler_menu(menu, max(0, int(round(self.x_to_frame(pos.x())))))
            menu.exec(e.globalPosition().toPoint())
            return
        clip, _zone = self.hit(pos)
        m = self.model
        if clip is not None:
            if clip.id not in m.selection:
                m.select_group(clip.id)
            menu.addAction(_("Dividir no cursor"), lambda: m.split_at(self.playhead))
            menu.addAction(_("Excluir"), lambda: m.delete_selected())
            menu.addAction(_("Excluir e fechar o espaço"), lambda: m.delete_selected(ripple=True))
            if clip.link:
                menu.addAction(_("Desligar áudio e vídeo"), m.unlink_selected)
            elif len(m.selection) >= 2:
                menu.addAction(_("Ligar os clipes selecionados"), m.link_selected)
            menu.addSeparator()
            if clip.kind == VIDEO:
                menu.addAction(_("Copiar ajustes de cor"), lambda: m.copy_values(clip.id))
                act = menu.addAction(_("Colar ajustes de cor"), lambda: m.paste_values(m.selection))
                act.setEnabled(m.has_clipboard())
            menu.addAction(_("Velocidade…"), lambda: self.ask_speed(clip.id))
            tempo_ui.add_clip_actions(menu, self, clip)  # rampa, reverso, congelar este quadro
            menu.addAction(_("Restaurar ajustes"), lambda: m.reset_values(clip.id))
            if clip.kind == AUDIO:
                self.audio_transition_action(menu, clip, pos.x())
            self.split_edit_actions(menu, clip, pos.x())
            menu.addSeparator()
            menu.addAction(_("Remover espaços da faixa"), lambda: self._close_gaps(clip.kind, clip.track))
        else:
            hit = self.track_at(pos.y())
            if hit is not None:
                kind, idx = hit
                menu.addAction(_("Remover espaços da faixa"), lambda: self._close_gaps(kind, idx))
                act = menu.addAction(_("Remover esta faixa"), lambda: m.remove_track(kind, idx))
                act.setEnabled(len(self.seq.kind_tracks(kind)) > 1)
                menu.addSeparator()
            menu.addAction(_("Adicionar faixa de vídeo"), lambda: m.add_track(VIDEO))
            menu.addAction(_("Adicionar faixa de áudio"), lambda: m.add_track(AUDIO))
        menu.addSeparator()
        menu.addAction(_("Adicionar marcador no cursor (M)"), lambda: self.add_marker_at())
        menu.exec(e.globalPosition().toPoint())

    def audio_cut_near(self, clip: Clip, x: float) -> Clip | None:
        """O clipe que entra no corte de som mais perto do clique (`x`) dentro de `clip`: o próprio clipe
        se o clique foi na metade da esquerda e há um clipe colado antes; o próximo, se foi na da direita
        e há um colado depois. None se o clipe não encosta em nenhum outro na faixa."""
        seq = self.seq
        prev, nxt = seq.previous_on_track(clip), seq.next_on_track(clip)
        r = self.clip_rect(clip)
        left = r is None or x < r.center().x()
        if prev is not None and (left or nxt is None):
            return clip
        return nxt

    def audio_transition_action(self, menu: QMenu, clip: Clip, x: float):
        """"Transição de som (potência constante)" no corte mais perto do clique: liga com a duração padrão
        ou tira (a duração se ajusta no inspetor do clipe que entra)."""
        incoming = self.audio_cut_near(clip, x)
        act = menu.addAction(_("Transição de som (potência constante)"))
        act.setCheckable(True)
        if incoming is None or self.seq.locked(incoming):
            act.setEnabled(False)
            return act
        act.setChecked(float(incoming.values.get("transicao", 0.0)) > 0)
        act.triggered.connect(lambda on: self.set_audio_transition(incoming.id, on))
        return act

    def set_audio_transition(self, cid: str, on: bool) -> None:
        from .edit_model import AUDIO_TRANSITION_S
        got = self.model.set_audio_transition(cid, AUDIO_TRANSITION_S if on else 0.0)
        if not on:
            return
        c = self.seq.find(cid)
        r = self.clip_rect(c) if c is not None else None
        where = self.mapToGlobal(r.topLeft().toPoint()) if r is not None else self.mapToGlobal(self.rect().center())
        if got <= 1e-6:
            QToolTip.showText(where, _("Sem sobra de som além do corte: a transição precisa de um pedaço do "
                                       "arquivo depois do fim do clipe da esquerda ou antes do começo do da "
                                       "direita."), self)
        elif got < AUDIO_TRANSITION_S - 1e-3:
            QToolTip.showText(where, _("Transição de {s} s: é o que sobra do arquivo além do corte.").format(
                s=fmt_decimal(got, 2)), self)

    def split_edit_actions(self, menu: QMenu, clip: Clip, x: float) -> list:
        """"Corte J" / "Corte L" / "Alinhar o som com a imagem" no corte entre dois pares imagem + som ligados
        mais perto do clique (a metade da esquerda do clipe escolhe o corte do começo). Nada se ali não há um
        corte assim (`Sequence.cut_pair`)."""
        from ..timeline import SPLIT_EDIT_S
        seq = self.seq
        r = self.clip_rect(clip)
        near_left = r is None or x < r.center().x()
        left = next((s for s in (near_left, not near_left) if seq.cut_pair(clip, s) is not None), None)
        if left is None:
            return []
        _pv, _pa, nv, na = seq.cut_pair(clip, left)
        off = na.start - nv.start
        n = seq.frames_for(SPLIT_EDIT_S)
        acts = []
        for text, want, on in ((_("Corte J (o som do próximo entra antes da imagem)"), -n, off < 0),
                               (_("Corte L (o som continua depois do corte da imagem)"), n, off > 0)):
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(on)
            a.triggered.connect(lambda _on=False, w=want: self.split_edit(clip.id, left, w))
            acts.append(a)
        a = menu.addAction(_("Alinhar o som com o corte da imagem"))
        a.setEnabled(off != 0)
        a.triggered.connect(lambda _on=False: self.split_edit(clip.id, left, 0))
        acts.append(a)
        return acts

    def split_edit(self, cid: str, left: bool, offset: int) -> None:
        got = self.model.split_edit(cid, left, offset)
        if got is None or got == offset or not offset:
            return
        r = self.clip_rect(self.seq.find(cid)) if self.seq.find(cid) is not None else None
        where = self.mapToGlobal(r.topLeft().toPoint()) if r is not None else self.mapToGlobal(self.rect().center())
        if got == 0:
            QToolTip.showText(where, _("Sem sobra de som além do corte: o corte J precisa de um pedaço do arquivo "
                                       "antes do começo do clipe da direita; o corte L, depois do fim do da "
                                       "esquerda."), self)
        else:
            QToolTip.showText(where, _("Coube {s} s: é o que sobra do arquivo além do corte.").format(
                s=fmt_decimal(abs(got) / self.seq.fps, 2)), self)

    def _close_gaps(self, kind: str, idx: int) -> None:
        self.model.close_gaps(kind, idx)

    def ask_speed(self, cid: str) -> None:
        c = self.seq.find(cid)
        if c is None:
            return
        val, ok = QInputDialog.getDouble(self, _("Velocidade"), _("Velocidade do clipe (1 = normal, 2 = o dobro, "
                                                                  "0,5 = câmera lenta):"), c.speed, 0.1, 8.0, 2)
        if ok:
            self.model.set_speed(cid, val)

    # ------------------------------------------------------------ teclado
    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if k == Qt.Key.Key_A:
                self.model.select([c.id for c in self.seq.clips])
                return
            e.ignore()
            return
        m = self.model
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_M and not shift:
            self.add_marker_at()
        elif k in (Qt.Key.Key_Up, Qt.Key.Key_Down) and shift:
            self.goto_marker(1 if k == Qt.Key.Key_Down else -1)
        elif k == Qt.Key.Key_S:
            m.split_at(self.playhead)
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self.delete_keys():
                m.delete_selected(ripple=bool(mods & Qt.KeyboardModifier.ShiftModifier))
        elif k == Qt.Key.Key_B:
            self.set_tool("blade")
        elif k == Qt.Key.Key_V:
            self.set_tool("select")
        elif k == Qt.Key.Key_N:
            self.snap = not self.snap
            self.toolChanged.emit(self.tool)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_ppf(self.ppf * 1.25, self.frame_to_x(self.playhead))
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.set_ppf(self.ppf * 0.8, self.frame_to_x(self.playhead))
        elif k == Qt.Key.Key_Escape:
            self.key_sel = set()
            m.select([])
            self.set_tool("select")
        else:
            e.ignore()

    # ------------------------------------------------------------ arrastar e soltar
    @staticmethod
    def _paths(mime: QMimeData) -> list[str]:
        if mime.hasFormat(MIME_SOURCE):
            raw = bytes(mime.data(MIME_SOURCE)).decode("utf-8", "replace")
            return [x for x in raw.split("\n") if x]
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def drop_target(self, pos: QPointF) -> tuple[int, str, int]:
        """(quadro, tipo, faixa) de um arquivo solto neste ponto."""
        f, _s = self.snap_frame(self.x_to_frame(max(pos.x(), HEADER_W)), set())
        hit = self.track_at(pos.y())
        if hit is None:
            rows = self.rows()
            audio_top = next((y for k, _i, y, _h in rows if k == AUDIO), None)
            kind = AUDIO if (audio_top is not None and pos.y() >= audio_top) else VIDEO
            hit = (kind, 0)
        return max(0, f), hit[0], hit[1]

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_SOURCE) or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not (e.mimeData().hasFormat(MIME_SOURCE) or e.mimeData().hasUrls()):
            return
        f, kind, idx = self.drop_target(e.position())
        self._drop = (self.frame_to_x(f), kind, idx, self.insert_for(e.modifiers()))
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, _e):
        self._drop = None
        self.update()

    def dropEvent(self, e):
        self._drop = None
        paths = self._paths(e.mimeData())
        if paths:
            f, kind, idx = self.drop_target(e.position())
            e.acceptProposedAction()
            sig = self.filesInserted if self.insert_for(e.modifiers()) else self.filesDropped
            sig.emit(paths, f, kind, idx)
        self.update()


class TimelineEditor(QWidget):
    """Linha do tempo com barra de ferramentas e barras de rolagem."""

    seekRequested = Signal(int)
    scrubbing = Signal(bool)
    filesDropped = Signal(list, int, str, int)
    filesInserted = Signal(list, int, str, int)
    clipActivated = Signal(str)

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setObjectName("Panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.canvas = TimelineCanvas(model)
        lay.addWidget(self._toolbar())
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)
        mid.addWidget(self.canvas, 1)
        self.vbar = QScrollBar(Qt.Orientation.Vertical)
        self.vbar.valueChanged.connect(lambda v: self.canvas.set_yscroll(v))
        mid.addWidget(self.vbar)
        lay.addLayout(mid, 1)
        self.hbar = QScrollBar(Qt.Orientation.Horizontal)
        self.hbar.valueChanged.connect(self._hbar_moved)
        lay.addWidget(self.hbar)
        c = self.canvas
        c.seekRequested.connect(self.seekRequested)
        c.scrubbing.connect(self.scrubbing)
        c.filesDropped.connect(self.filesDropped)
        c.filesInserted.connect(self.filesInserted)
        c.clipActivated.connect(self.clipActivated)
        c.viewChanged.connect(self._sync_bars)
        c.toolChanged.connect(self._sync_tools)
        model.selectionChanged.connect(self._sync_actions)
        model.changed.connect(lambda _k: self._sync_actions())
        self._syncing = False
        self._sync_actions()
        self._sync_tools(c.tool)

    def add_lane(self, widget: QWidget) -> None:
        """Uma faixa fina entre a barra de ferramentas e as faixas, alinhada com elas pelo `canvas.frame_to_x`
        (a linha "Look" das chaves do look: `keyframes_ui.KeyStrip`)."""
        self.layout().insertWidget(1, widget)
        self.canvas.viewChanged.connect(widget.update)

    def _btn(self, icon: str, tip: str, text: str = "", checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(icons.icon(icon, theme.TEXT, 18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return b

    def _toolbar(self) -> QWidget:
        bar = AdaptiveBar()
        bar.setObjectName("ViewerBar")
        hl = FlowLayout(bar, 2, 2)
        hl.setContentsMargins(8, 4, 8, 4)
        c = self.canvas
        m = self.model
        self.btn_select = self._btn("pointer", _("Selecionar e mover (V)"), checkable=True)
        self.btn_blade = self._btn("scissors", _("Lâmina: clique num clipe para cortar ali (B)"), checkable=True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (self.btn_select, self.btn_blade):
            grp.addButton(b)
            hl.addWidget(b)
        self.btn_select.clicked.connect(lambda: c.set_tool("select"))
        self.btn_blade.clicked.connect(lambda: c.set_tool("blade"))
        hl.add_spacing(8)
        self.btn_split = self._btn("split", _("Dividir no cursor (S)"), _("Dividir"))
        self.btn_split.clicked.connect(lambda: m.split_at(c.playhead))
        self.btn_delete = self._btn("trash", _("Excluir os clipes selecionados (Delete)"))
        self.btn_delete.clicked.connect(lambda: m.delete_selected())
        self.btn_ripple = self._btn("ripple_delete", _("Excluir e fechar o espaço (Shift+Delete)"))
        self.btn_ripple.clicked.connect(lambda: m.delete_selected(ripple=True))
        self.btn_link = self._btn("unlink", _("Desligar o áudio do vídeo"))
        self.btn_link.clicked.connect(self._toggle_link)
        self.btn_snap = self._btn("magnet", _("Ímã: grudar nos cortes e no cursor (N). Shift inverte ao arrastar."),
                                  checkable=True)
        self.btn_snap.setChecked(c.snap)
        self.btn_snap.toggled.connect(self._set_snap)
        self.btn_insert = self._btn("insert_mode", _("Inserir: soltar ou mover um clipe empurra o que vem depois, "
                                                     "em vez de cobrir. Ctrl inverte ao arrastar."), checkable=True)
        self.btn_insert.setChecked(c.insert_mode)
        self.btn_insert.toggled.connect(c.set_insert_mode)
        for b in (self.btn_split, self.btn_delete, self.btn_ripple, self.btn_link, self.btn_snap, self.btn_insert):
            hl.addWidget(b)
        hl.add_spacing(8)
        self.btn_marker = self._btn("marker", _("Adicionar marcador no cursor (M)"), _("Marcador"))
        self.btn_marker.clicked.connect(lambda: c.add_marker_at())
        self.btn_markers = self._btn("chapters", _("Marcadores e capítulos"))
        self.btn_markers.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mm = QMenu(self.btn_markers)
        self.act_prev_marker = mm.addAction(_("Marcador anterior (Shift+↑)"), lambda: c.goto_marker(-1))
        self.act_next_marker = mm.addAction(_("Próximo marcador (Shift+↓)"), lambda: c.goto_marker(1))
        self.act_edit_marker = mm.addAction(_("Editar o marcador selecionado…"), self._edit_selected_marker)
        mm.addSeparator()
        mm.addAction(_("Copiar capítulos para o YouTube…"), c.copy_chapters)
        mm.addSeparator()
        self.act_clear_markers = mm.addAction(_("Remover todos os marcadores"), m.clear_markers)
        self.btn_markers.setMenu(mm)
        hl.addWidget(self.btn_marker)
        hl.addWidget(self.btn_markers)
        hl.add_spacing(8)
        self.btn_add_v = self._btn("track_add", _("Nova faixa de vídeo"), _("Vídeo"))
        self.btn_add_v.clicked.connect(lambda: m.add_track(VIDEO))
        self.btn_add_a = self._btn("track_add", _("Nova faixa de áudio"), _("Áudio"))
        self.btn_add_a.clicked.connect(lambda: m.add_track(AUDIO))
        hl.addWidget(self.btn_add_v)
        hl.addWidget(self.btn_add_a)
        hl.add_stretch()
        zo = self._btn("zoom_out", _("Afastar (−). Ctrl + roda do mouse também."))
        zo.clicked.connect(lambda: c.set_ppf(c.ppf * 0.8))
        self.zoom = FilmSlider(0.0, 1.0, 0.001, self._ppf_to_t(4.0))
        self.zoom.setFixedWidth(110)
        self.zoom.setToolTip(_("Zoom da linha do tempo"))
        self.zoom.valueChanged.connect(lambda t: c.set_ppf(self._t_to_ppf(t)))
        zi = self._btn("zoom_in", _("Aproximar (+). Ctrl + roda do mouse também."))
        zi.clicked.connect(lambda: c.set_ppf(c.ppf * 1.25))
        fit = self._btn("fit", _("Mostrar a sequência inteira"), _("Ajustar"))
        fit.clicked.connect(self.zoom_fit)
        for b in (zo, self.zoom, zi, fit):
            hl.addWidget(b)
        # Linha do tempo estreita: botões só com ícone, some o slider de zoom e, se precisar, quebra a linha.
        bar.set_adaptive(compact=[self.btn_split, self.btn_marker, self.btn_add_v, self.btn_add_a, fit],
                         optional=[self.zoom])
        return bar

    def _edit_selected_marker(self) -> None:
        if self.model.marker_sel:
            self.canvas.edit_marker(self.model.marker_sel)

    @staticmethod
    def _ppf_to_t(ppf: float) -> float:
        return math.log(ppf / MIN_PPF) / math.log(MAX_PPF / MIN_PPF)

    @staticmethod
    def _t_to_ppf(t: float) -> float:
        return MIN_PPF * (MAX_PPF / MIN_PPF) ** t

    def _set_snap(self, on: bool) -> None:
        self.canvas.snap = on

    def _toggle_link(self) -> None:
        if self.model.selection_linked():
            self.model.unlink_selected()
        else:
            self.model.link_selected()

    def _sync_tools(self, tool: str) -> None:
        self.btn_select.setChecked(tool == "select")
        self.btn_blade.setChecked(tool == "blade")
        for b, on in ((self.btn_snap, self.canvas.snap), (self.btn_insert, self.canvas.insert_mode)):
            if b.isChecked() != on:
                b.blockSignals(True)
                b.setChecked(on)
                b.blockSignals(False)

    def _sync_actions(self) -> None:
        m = self.model
        sel = bool(m.selection)
        self.btn_delete.setEnabled(sel or m.marker_sel is not None)
        self.btn_ripple.setEnabled(sel)
        has_markers = bool(m.seq.markers)
        for a in (self.act_prev_marker, self.act_next_marker, self.act_clear_markers):
            a.setEnabled(has_markers)
        self.act_edit_marker.setEnabled(m.marker_sel is not None)
        linked = m.selection_linked()
        self.btn_link.setEnabled(linked or len(m.selection) >= 2)
        self.btn_link.setIcon(icons.icon("unlink" if linked or not sel else "link", theme.TEXT, 18))
        self.btn_link.setToolTip(_("Desligar o áudio do vídeo") if linked or not sel
                                 else _("Ligar os clipes selecionados (andam juntos)"))
        self.btn_split.setEnabled(bool(m.seq.clips))

    def _sync_bars(self) -> None:
        c = self.canvas
        self._syncing = True
        total = max(c.seq.duration + c.visible_frames() * 0.5, c.visible_frames())
        self.hbar.setRange(0, max(0, int(math.ceil(total - c.visible_frames()))))
        self.hbar.setPageStep(max(1, int(c.visible_frames())))
        self.hbar.setSingleStep(max(1, int(40 / c.ppf)))
        self.hbar.setValue(int(round(c.scroll)))
        top = max(0, int(math.ceil(c.content_height() - (c.height() - RULER_H))))
        self.vbar.setRange(0, top)
        self.vbar.setPageStep(max(1, c.height() - RULER_H))
        self.vbar.setVisible(top > 0)
        self.vbar.setValue(int(c.yscroll))
        self.zoom.setValue(self._ppf_to_t(c.ppf))
        self._syncing = False

    def _hbar_moved(self, v: int) -> None:
        if not self._syncing:
            self.canvas.set_scroll(v)

    # ------------------------------------------------------------ API
    def set_playhead(self, frame: int) -> None:
        self.canvas.set_playhead(frame)

    def set_inout(self, a: int | None, b: int | None) -> None:
        self.canvas.set_inout(a, b)

    def set_peaks_provider(self, fn: Callable[[str], np.ndarray | None]) -> None:
        self.canvas.peaks_provider = fn
        self.canvas.update()

    def peaks_ready(self, path: str) -> None:
        if any(c.src == path for c in self.model.seq.clips if c.kind == AUDIO):
            self.canvas.update()

    def zoom_fit(self) -> None:
        self.canvas.zoom_fit()

    def set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)

    def keyPressEvent(self, e):
        self.canvas.keyPressEvent(e)
