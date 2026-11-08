"""1.9, máscara de forma do clipe na interface (#68; ARQUITETURA §50): o cartão "Máscara" do inspetor (módulo Beta
`recorte_mascaras`) e as alças na prévia (`ui/alcas.py`).

Ligado por `vfx_ui.FRONT_UIS` (`install(vfx_ui)`). As alças aparecem no modo Edição para o clipe do inspetor com uma
forma, quando ele está sob o cursor (e com os efeitos ligados):

- **Retângulo e elipse**: arrastar o centro (ou o meio da forma) move; os cantos mudam a largura e a altura (em volta do
  centro); a bolinha de cima gira (Shift: de 15 em 15°).
- **Polígono**: "Desenhar polígono" (ou clicar na prévia com o polígono ainda sem pontos) começa; cada clique põe um
  ponto, dois cliques (ou clicar no primeiro ponto) fecham com 3 ou mais, Esc cancela. Fechado: arrastar um ponto o
  move; arrastar dentro move o polígono inteiro (o centro).

Mexer numa alça passa pelo `vstore` do inspetor, como um slider: um ajuste com chaves de animação ganha uma chave no
cursor (chave automática); ao soltar, um passo do desfazer. Os pontos do polígono (`Clip.fx`) mudam num passo do
desfazer (`TimelineModel.apply_edit`). Nada disso entra na exportação: só os ajustes e os pontos que ficaram no clipe.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .. import compositor, mascaras_clipe as mk, sequence, vfx
from ..i18n import _
from ..timeline import VIDEO
from . import alcas

SECTION = "mascara"
ROT_PX = 28.0  # distância (px do widget) da bolinha de girar até a borda de cima da forma


@dataclass
class State:
    """O clipe do inspetor no quadro do cursor e a matriz tela ↔ uv do clipe (a da prévia e da exportação)."""
    seq: object
    clip: object
    values: dict
    m: np.ndarray        # px da tela → uv do clipe (com a geometria dos efeitos)
    inv: np.ndarray
    canvas: tuple[int, int]
    tex: tuple[int, int]
    points: list

    def frac(self, p) -> tuple[float, float]:
        """px@1080 do clipe → fração da imagem."""
        u, v = mk.clip_uv(p, *self.tex)
        x, y, w = self.inv @ np.array([u, v, 1.0])
        return float(x / w / self.canvas[0]), float(y / w / self.canvas[1])

    def clip_px(self, fx: float, fy: float) -> np.ndarray:
        """Fração da imagem → px@1080 do clipe."""
        u, v, w = self.m @ np.array([fx * self.canvas[0], fy * self.canvas[1], 1.0])
        return mk.clip_px([u / w, v / w], *self.tex)


class MaskHandles(alcas.Handles):
    def __init__(self, win):
        self.win = win
        self.draft: list[np.ndarray] | None = None   # polígono sendo desenhado (px@1080 do clipe)
        self.draft_clip = ""
        self._drag: dict | None = None

    # -------------------------------------------------------- estado
    def state(self) -> State | None:
        win = self.win
        if getattr(win, "mode", "") != "edicao" or getattr(win, "no_effects", False):
            return None
        c = win.inspector.current_clip()
        seq = win.model.seq
        if c is None or c.kind != VIDEO:
            return None
        src = seq.sources.get(c.src)
        if src is None or src.is_nested:  # um clipe de sequência não tem pilha de efeitos (§41.5)
            return None
        t = int(getattr(win, "frame_idx", c.start))
        layer = next((x for x in seq.layers_at(t) if x.clip.id == c.id), None)
        if layer is None:
            return None
        v = layer.values if layer.values is not None else c.values
        if not mk.active(v) and self.draft is None:
            return None
        cw, ch = int(seq.width), int(seq.height)
        m = vfx.geometry(seq, layer, compositor.transform(seq, c, cw, ch, v), cw, ch)
        tex = (cw, ch) if vfx.is_adjustment(seq, c) else sequence.decode_size(seq, c, cw, ch)
        try:
            inv = np.linalg.inv(m)
        except np.linalg.LinAlgError:
            return None
        return State(seq, c, v, m, inv, (cw, ch), tex, mk.points_of(c))

    def visible(self) -> bool:
        return self.state() is not None

    def _widget(self, st: State, view: alcas.View, p) -> QPointF:
        return view.to_widget(*st.frac(p))

    def _points(self, st: State, view: alcas.View) -> dict:
        """As alças em px do widget: centro, cantos, girar (ou os pontos do polígono)."""
        v = st.values
        out = {"centro": self._widget(st, view, mk.to_clip([[0.0, 0.0]], v)[0])}
        if v["mascara_forma"] == "poligono":
            out["pontos"] = [self._widget(st, view, p) for p in mk.to_clip(st.points, v)] if st.points else []
            return out
        hw, hh = 0.5 * float(v["mascara_largura"]), 0.5 * float(v["mascara_altura"])
        corners = mk.to_clip([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]], v)
        out["cantos"] = [self._widget(st, view, p) for p in corners]
        top, above = (self._widget(st, view, p) for p in mk.to_clip([[0.0, -hh], [0.0, -hh - 1.0]], v))
        d = above - top
        n = math.hypot(d.x(), d.y()) or 1.0
        out["topo"] = top
        out["girar"] = top + d * (ROT_PX / n)
        return out

    # -------------------------------------------------------- desenho
    def paint(self, p, view) -> None:
        st = self.state()
        if st is None:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.draft is not None:
            pts = [self._widget(st, view, q) for q in self.draft]
            p.setPen(alcas.pen(dash=True))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            for i, q in enumerate(pts):
                alcas.draw_square(p, q, filled=i != 0)
            return
        v = st.values
        line = mk.outline(v, st.points)
        if len(line):
            path = QPainterPath()
            ws = [self._widget(st, view, q) for q in line]
            path.moveTo(ws[0])
            for q in ws[1:]:
                path.lineTo(q)
            path.closeSubpath()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(alcas.pen("#000000", 3.0))
            p.drawPath(path)
            p.setPen(alcas.pen())
            p.drawPath(path)
        hp = self._points(st, view)
        if "girar" in hp:
            p.setPen(alcas.pen())
            p.drawLine(hp["topo"], hp["girar"])
            alcas.draw_dot(p, hp["girar"], 4.5)
        for q in hp.get("cantos", []) + hp.get("pontos", []):
            alcas.draw_square(p, q)
        alcas.draw_dot(p, hp["centro"])

    # -------------------------------------------------------- mouse
    def _hit(self, st: State, view, pos: QPointF) -> tuple[str, int] | None:
        hp = self._points(st, view)
        if "girar" in hp and alcas.near(pos, hp["girar"]):
            return "girar", 0
        for i, q in enumerate(hp.get("cantos", [])):
            if alcas.near(pos, q):
                return "canto", i
        for i, q in enumerate(hp.get("pontos", [])):
            if alcas.near(pos, q):
                return "ponto", i
        if alcas.near(pos, hp["centro"]):
            return "mover", 0
        fx, fy = view.to_frac(pos)
        q = mk.to_local(st.clip_px(fx, fy), st.values)
        if mk.ready(st.values, st.points) and mk.distance(q[None], st.values, st.points)[0] < 0:
            return "mover", 0
        return None

    def cursor(self, view, pos):
        st = self.state()
        if st is None:
            return None
        if self.draft is not None or (st.values["mascara_forma"] == "poligono" and len(st.points) < 3):
            return Qt.CursorShape.CrossCursor
        hit = self._hit(st, view, pos)
        if hit is None:
            return None
        return Qt.CursorShape.SizeAllCursor if hit[0] == "mover" else Qt.CursorShape.PointingHandCursor

    def press(self, view, pos, modifiers) -> bool:
        st = self.state()
        if st is None:
            return False
        p = st.clip_px(*view.to_frac(pos))
        if self.draft is None and st.values["mascara_forma"] == "poligono" and len(st.points) < 3:
            self.start_draft(st.clip.id)
        if self.draft is not None:
            if self.draft_clip != st.clip.id:
                self.draft = None
                return False
            if len(self.draft) >= 3 and alcas.near(pos, self._widget(st, view, self.draft[0])):
                self.close_draft()
            elif len(self.draft) < mk.MAX_POINTS:
                self.draft.append(p)
            return True
        hit = self._hit(st, view, pos)
        if hit is None:
            return False
        self.win.model.commit()
        self._drag = {"kind": hit[0], "i": hit[1], "p0": p, "values": dict(st.values), "points": list(st.points),
                      "clip": st.clip.id, "state": st}
        return True

    def drag(self, view, pos, modifiers) -> None:
        d = self._drag
        if d is None:
            return
        st: State = d["state"]
        p = st.clip_px(*view.to_frac(pos))
        v0 = d["values"]
        kind = d["kind"]
        if kind == "mover":
            c = np.array([v0["mascara_x"], v0["mascara_y"]]) + (p - d["p0"])
            self._set({"mascara_x": c[0], "mascara_y": c[1]})
        elif kind == "canto":
            q = np.abs(mk.to_local(p, v0))
            self._set({"mascara_largura": max(1.0, 2 * q[0]), "mascara_altura": max(1.0, 2 * q[1])})
        elif kind == "girar":
            r = p - np.array([v0["mascara_x"], v0["mascara_y"]])
            deg = math.degrees(math.atan2(r[0], -r[1]))
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                deg = round(deg / 15.0) * 15.0
            self._set({"mascara_rotacao": (deg + 180.0) % 360.0 - 180.0})
        elif kind == "ponto":
            pts = list(d["points"])
            pts[d["i"]] = tuple(mk.to_local(p, v0))
            clip = self.win.model.seq.find(d["clip"])
            if clip is not None:  # ao vivo, sem desfazer; o passo fica para o soltar
                mk.set_points(clip, pts)
                d["moved"] = pts
                self.win.model.changed.emit("values")

    def release(self, view, pos, modifiers) -> None:
        d, self._drag = self._drag, None
        if d is None:
            return
        if d["kind"] == "ponto":
            pts = d.get("moved")
            clip = self.win.model.seq.find(d["clip"])
            if pts is None or clip is None:
                return
            mk.set_points(clip, d["points"])  # volta ao de antes para o desfazer ver a mudança
            cid = d["clip"]
            self.win.model.apply_edit(lambda seq: mk.set_points(seq.find(cid), pts), "values")
            return
        self.win.model.commit()

    def double_click(self, view, pos) -> bool:
        if self.draft is None:
            return False
        if len(self.draft) >= 3:
            self.close_draft()
        return True

    def escape(self) -> bool:
        if self.draft is None:
            return False
        self.draft = None
        self.win.statusBar().showMessage(_("Polígono cancelado."), 4000)
        return True

    # -------------------------------------------------------- valores
    def _set(self, changes: dict) -> None:
        """Ajustes da forma pelo `vstore` do inspetor (chave automática no cursor, como os sliders)."""
        store = self.win.inspector.vstore
        for key, value in changes.items():
            store.set(key, round(float(value), 2), record=False)

    def start_draft(self, cid: str) -> None:
        self.draft = []
        self.draft_clip = cid
        self.win.statusBar().showMessage(_("Clique na prévia para pôr os pontos do polígono; dois cliques (ou o "
                                           "primeiro ponto) fecham. Esc cancela."), 8000)

    def close_draft(self) -> bool:
        """Fecha o polígono desenhado num passo do desfazer: os pontos ficam relativos ao centro (o centro vai ao meio
        dos pontos, se não estiver animado). False com menos de 3 pontos."""
        pts, cid = self.draft, self.draft_clip
        self.draft = None
        if not pts or len(pts) < 3:
            return False
        model = self.win.model
        frame = int(getattr(self.win, "frame_idx", 0))

        def edit(seq):
            clip = seq.find(cid)
            if clip is None:
                return
            vals = copy.deepcopy(clip.values)
            vals["mascara_forma"] = "poligono"
            now = seq.values_at(clip, frame)
            if not any(k in clip.keys for k in ("mascara_x", "mascara_y")):
                cx, cy = np.mean(np.asarray(pts), axis=0)
                vals["mascara_x"], vals["mascara_y"] = round(float(cx), 2), round(float(cy), 2)
                now = {**now, "mascara_x": vals["mascara_x"], "mascara_y": vals["mascara_y"]}
            seq.set_values(cid, vals)
            mk.set_points(seq.find(cid), [tuple(mk.to_local(p, now)) for p in pts])

        model.apply_edit(edit, "values")
        self.win.statusBar().showMessage(_("Polígono fechado: arraste os pontos ou o meio para ajustar."), 5000)
        return True


class MascarasUI:
    def __init__(self, vfxui):
        self.vfx = vfxui
        self.win = vfxui.win
        after = "recorte" if vfxui.card("recorte") is not None else "transformar"
        self.card = vfxui.add_section(SECTION, mk.MODULE, after=after)
        self.handles = MaskHandles(self.win)
        vfxui.add_handles("mascara", mk.MODULE, self.handles)
        self.btn_draw = QPushButton(_("Desenhar polígono"))
        self.btn_draw.setObjectName("mascara_desenhar")
        self.btn_draw.setToolTip(_("Clique na prévia para pôr os pontos; dois cliques fecham (Esc cancela)"))
        self.btn_draw.clicked.connect(self.draw_polygon)
        self.btn_clear = QPushButton(_("Apagar os pontos"))
        self.btn_clear.setObjectName("mascara_apagar")
        self.btn_clear.setToolTip(_("Tira os pontos do polígono deste clipe"))
        self.btn_clear.clicked.connect(self.clear_points)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 2, 0, 4)
        hl.addWidget(self.btn_draw)
        hl.addWidget(self.btn_clear)
        hl.addStretch(1)
        self.card.body.layout().insertWidget(0, row)

    def draw_polygon(self) -> None:
        """Começa um polígono no clipe do inspetor (a forma vira "Polígono")."""
        win = self.win
        c = win.inspector.current_clip()
        if c is None or c.kind != VIDEO:
            return
        if c.values.get("mascara_forma") != "poligono":
            win.model.set_clip_values(c.id, {**c.values, "mascara_forma": "poligono"})
        self.handles.start_draft(c.id)
        win.viewer.update()

    def clear_points(self) -> None:
        c = self.win.inspector.current_clip()
        if c is None or not mk.points_of(c):
            return
        cid = c.id
        self.win.model.apply_edit(lambda seq: mk.set_points(seq.find(cid), []), "values")


def install(vfxui) -> MascarasUI:
    return MascarasUI(vfxui)
