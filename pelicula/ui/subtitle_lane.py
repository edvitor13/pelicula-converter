"""Faixa "Legendas" da linha do tempo (modo Edição), embaixo das faixas de som.

Cada legenda é um bloco com o texto, no tempo da sequência (`SubtitleController.items`). Clique escolhe (e
leva o cursor ao começo), arrastar o meio move, arrastar as pontas apara (o ímã da linha do tempo vale aqui
também; Shift inverte), dois cliques editam o texto no painel, dois cliques num lugar vazio criam uma legenda
ali, Delete apaga a escolhida e o botão direito tem dividir no cursor e juntar com a próxima. As legendas
presas a um arquivo acompanham os cortes sozinhas; as da sequência (tempo fixo) têm a borda tracejada.

A faixa é desenhada pela própria `TimelineCanvas`, que só chama os ganchos daqui (`canvas.lane`): altura
extra (`height`), desenho (`paint`, `paint_header`), mouse e teclado. Sem faixa (`canvas.lane = None`) a
linha do tempo é a de sempre.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QMenu

from ..i18n import _
from . import theme
from .subtitles_ui import SubtitleController
from .timeline_view import EDGE_PX, GAP_H, HEADER_W, TimelineCanvas

LANE_H = 30
CUE = "#4f63a8"
CUE_HI = "#8193d6"
CUE_FIXED = "#5a5470"


class SubtitleLane:
    def __init__(self, canvas: TimelineCanvas, ctl: SubtitleController):
        self.canvas = canvas
        self.ctl = ctl
        self.visible = True
        self.active = False          # o último clique foi aqui (Delete apaga a legenda, não o clipe)
        self._drag: dict | None = None
        canvas.lane = self
        ctl.changed.connect(canvas.update)
        ctl.selectionChanged.connect(canvas.update)

    # ------------------------------------------------------------ geometria
    def set_visible(self, on: bool) -> None:
        self.visible = bool(on)
        if not on:
            self.active = False
            self._drag = None
        self.canvas.set_yscroll(self.canvas.yscroll)
        self.canvas.viewChanged.emit()
        self.canvas.update()

    def height(self) -> float:
        return float(GAP_H + LANE_H) if self.visible else 0.0

    def rect(self) -> QRectF | None:
        if not self.visible:
            return None
        rows = self.canvas.rows()
        if not rows:
            return None
        _k, _i, y, h = rows[-1]
        return QRectF(HEADER_W, y + h + GAP_H, self.canvas.lanes_width(), float(LANE_H))

    def contains(self, pos: QPointF) -> bool:
        r = self.rect()
        return r is not None and r.top() <= pos.y() < r.bottom()

    def _x(self, t: float) -> float:
        return self.canvas.frame_to_x(t * self.ctl.fps)

    def item_rect(self, item, start: float | None = None, end: float | None = None) -> QRectF | None:
        r = self.rect()
        if r is None:
            return None
        a = item.cue.start if start is None else start
        b = item.cue.end if end is None else end
        x0, x1 = self._x(a), self._x(b)
        return QRectF(x0, r.top() + 3, max(2.0, x1 - x0), r.height() - 6)

    def hit(self, pos: QPointF):
        """(item, zona) sob o ponto: "left"/"right" apara, "body" move."""
        if not self.contains(pos) or pos.x() < HEADER_W:
            return None, ""
        sel = set(self.ctl.selection)
        for it in reversed(sorted(self.ctl.items(), key=lambda it: it.ref in sel)):  # a escolhida por cima
            r = self.item_rect(it)
            if r is None or not r.adjusted(0, -3, 0, 3).contains(pos):
                continue
            edge = min(EDGE_PX, r.width() / 4)
            if pos.x() - r.left() <= edge:
                return it, "left"
            if r.right() - pos.x() <= edge:
                return it, "right"
            return it, "body"
        return None, ""

    # ------------------------------------------------------------ desenho
    def _shown(self, item):
        """Início e fim na tela (durante o arraste, onde a legenda vai ficar)."""
        d = self._drag
        if d is None or not d.get("active") or d["item"].ref != item.ref or d["item"].cue != item.cue:
            return item.cue.start, item.cue.end
        a, b = item.cue.start, item.cue.end
        if d["mode"] == "body":
            return a + d["dt"], b + d["dt"]
        if d["mode"] == "left":
            return min(a + d["dt"], b - 0.1), b
        return a, max(b + d["dt"], a + 0.1)

    def paint(self, p: QPainter, w: float, _h: float) -> None:
        r = self.rect()
        if r is None:
            return
        p.fillRect(QRectF(HEADER_W, r.top() - GAP_H, w - HEADER_W, GAP_H), QColor(theme.PANEL))
        p.fillRect(QRectF(HEADER_W, r.top(), w - HEADER_W, r.height()), QColor(theme.TRACK_BG))
        p.fillRect(QRectF(HEADER_W, r.bottom() - 1, w - HEADER_W, 1), QColor(theme.BORDER))
        fm = QFontMetrics(theme.font(8.5))
        p.setFont(theme.font(8.5))
        sel = set(self.ctl.selection)
        items = self.ctl.items()
        if not items:
            p.setPen(QColor(theme.FAINT))
            p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter,
                       _("Sem legendas: dois cliques aqui criam uma, ou use o painel Legendas."))
            return
        x_min, x_max = HEADER_W - 2, w + 2
        for it in sorted(items, key=lambda it: it.ref in sel):
            a, b = self._shown(it)
            rr = self.item_rect(it, a, b)
            if rr is None or rr.right() < x_min or rr.left() > x_max:
                continue
            chosen = it.ref in sel
            base = QColor(CUE_FIXED if it.fixed else CUE)
            p.setPen(QPen(QColor(theme.ACCENT_HI if chosen else CUE_HI), 1.6 if chosen else 1,
                          Qt.PenStyle.DashLine if it.fixed else Qt.PenStyle.SolidLine))
            p.setBrush(base)
            p.drawRoundedRect(rr, 4, 4)
            if rr.width() > 14:
                p.setPen(QColor(theme.TEXT))
                text = it.cue.text.replace("\n", " ")
                p.drawText(rr.adjusted(5, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rr.width() - 9)))

    def paint_header(self, p: QPainter) -> None:
        r = self.rect()
        if r is None:
            return
        top = max(r.top(), 28.0)
        if r.bottom() <= top:
            return
        p.save()
        p.setClipRect(QRectF(0, top, HEADER_W, r.bottom() - top))
        p.fillRect(QRectF(0, r.top(), HEADER_W - 1, r.height()), QColor(theme.PANEL))
        p.fillRect(QRectF(0, r.top() + 4, 3, r.height() - 8), QColor(CUE))
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(9, theme.QFont.Weight.DemiBold, title=True))
        p.drawText(QRectF(12, r.top(), HEADER_W - 16, r.height()), Qt.AlignmentFlag.AlignVCenter, _("Legendas"))
        p.restore()

    # ------------------------------------------------------------ mouse
    def press(self, e) -> bool:
        pos = e.position()
        if not self.contains(pos):
            self.active = False
            return False
        self.active = True
        if pos.x() < HEADER_W:
            return True
        it, zone = self.hit(pos)
        if e.button() == Qt.MouseButton.RightButton:
            if it is not None and it.ref not in self.ctl.selection:
                self.ctl.select([it.ref])
            self.context_menu(e, it)
            return True
        if e.button() != Qt.MouseButton.LeftButton:
            return True
        if it is None:
            self.ctl.select([])
            return True
        self.ctl.select([it.ref], seek=zone == "body")
        self._drag = {"item": it, "mode": zone, "press_x": pos.x(), "dt": 0.0, "active": False}
        return True

    def move(self, e) -> bool:
        d = self._drag
        pos = e.position()
        if d is None:
            if not self.contains(pos):
                return False
            it, zone = self.hit(pos)
            c = self.canvas
            if it is not None and zone in ("left", "right"):
                c.setCursor(Qt.CursorShape.SizeHorCursor)
            elif it is not None:
                c.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                c.setCursor(Qt.CursorShape.ArrowCursor)
            c.setToolTip(self._tip(it) if it is not None else "")
            return True
        if not d["active"] and abs(pos.x() - d["press_x"]) < 3:
            return True
        d["active"] = True
        c = self.canvas
        fps = self.ctl.fps
        it = d["item"]
        raw = (pos.x() - d["press_x"]) / c.ppf / fps          # segundos
        snap_on = c.snap != bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        edges = {"body": (it.cue.start, it.cue.end), "left": (it.cue.start,), "right": (it.cue.end,)}[d["mode"]]
        best = None
        c._snap_x = None
        if snap_on:
            for edge in edges:
                target = (edge + raw) * fps
                f, s = c.snap_frame(target, set(), True)
                if s is not None and (best is None or abs(f - target) < best[0]):
                    best = (abs(f - target), f / fps - edge, f)
        if best is not None:
            d["dt"] = best[1]
            c._snap_x = c.frame_to_x(best[2])
        else:
            d["dt"] = raw
        if d["mode"] == "body":
            d["dt"] = max(d["dt"], -it.cue.start)
        c.update()
        return True

    def release(self, e) -> bool:
        d = self._drag
        if d is None:
            return False
        self._drag = None
        self.canvas._snap_x = None
        if d["active"] and abs(d["dt"]) > 1e-6:
            it = d["item"]
            if d["mode"] == "body":
                self.ctl.move(it, d["dt"])
            elif d["mode"] == "left":
                self.ctl.set_times(it, start=min(it.cue.start + d["dt"], it.cue.end - 0.1))
            else:
                self.ctl.set_times(it, end=max(it.cue.end + d["dt"], it.cue.start + 0.1))
        self.canvas.update()
        return True

    def double_click(self, e) -> bool:
        pos = e.position()
        if not self.contains(pos) or pos.x() < HEADER_W:
            return False
        self._drag = None
        it, _zone = self.hit(pos)
        if it is not None:
            self.ctl.select([it.ref])
            self.ctl.textRequested.emit()
        else:
            f = max(0, int(round(self.canvas.x_to_frame(pos.x()))))
            if self.ctl.add_at(f):
                self.ctl.textRequested.emit()
        return True

    def key(self, e) -> bool:
        if not self.active or not self.ctl.selection:
            return False
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.ctl.delete_selected()
            return True
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.ctl.textRequested.emit()
            return True
        if e.key() == Qt.Key.Key_Escape:
            self.ctl.select([])
            self.active = False
            return True
        return False

    def _tip(self, it) -> str:
        from .widgets import timecode
        fps = self.ctl.fps
        where = _("Tempo fixo na sequência") if it.fixed else _("Presa ao arquivo: acompanha os cortes")
        return f"{timecode(self.ctl.frame_of(it.cue.start), fps)} – {timecode(self.ctl.frame_of(it.cue.end), fps)}\n" \
               f"{it.cue.text}\n{where}"

    def context_menu(self, e, it) -> None:
        menu = QMenu(self.canvas)
        ctl = self.ctl
        f = max(0, int(round(self.canvas.x_to_frame(e.position().x()))))
        menu.addAction(_("Nova legenda aqui"), lambda: ctl.add_at(f) and ctl.textRequested.emit())
        if it is not None:
            menu.addAction(_("Editar o texto…"), ctl.textRequested.emit)
            a = menu.addAction(_("Dividir no cursor"), lambda: ctl.split(it))
            a.setEnabled(it.cue.start < ctl.playhead / ctl.fps < it.cue.end)
            a = menu.addAction(_("Juntar com a próxima"), lambda: ctl.merge_next(it))
            from .. import subedit
            nxt = subedit.neighbor(ctl.items(), it, 1)
            a.setEnabled(nxt is not None and nxt.ref.path == it.ref.path)
            menu.addSeparator()
            menu.addAction(_("Excluir a legenda"), ctl.delete_selected)
        menu.exec(e.globalPosition().toPoint())
