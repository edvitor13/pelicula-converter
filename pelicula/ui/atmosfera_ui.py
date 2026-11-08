"""1.9 F4, luz e atmosfera na janela (#68; ARQUITETURA §52.6): os cartões do inspetor e os pontos na prévia.

Ligado por `vfx_ui.FRONT_UIS` (`install(vfx_ui)`, no fim do `VfxUI.__init__`), sem mexer na janela:

- Cartões "Desfoque de lente" e "Luz (listra, flares, raios)" (módulo Beta "luzes_lente") e "Névoa" e "Partículas"
  (módulo Beta "atmosfera"), logo depois do cartão "Efeitos", somem com o módulo desligado. Os controles saem sozinhos de
  `editparams.VIDEO_SECTIONS` (bloco da F4).
- Botões "Escolher na prévia" no cartão de luz: o próximo clique na prévia acerta o ponto do flare (e liga a origem
  "Um ponto escolhido") ou a origem dos raios, em px@1080 do clipe (`VfxUI.pick_point` + `clip_point`), num passo do
  desfazer.
- Camada de prévia (só na tela): o ponto do flare e a origem dos raios do clipe selecionado, quando estão em uso.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QPushButton

from .. import compositor, vfx
from ..i18n import N_, _
from ..timeline import VIDEO

AFTER = "efeitos"  # os cartões da F4 vêm logo depois do cartão "Efeitos" (vinheta e desbotado)
# (seção, módulo), na ordem em que aparecem
SECTIONS = (("desfoque_lente", "luzes_lente"), ("luzes", "luzes_lente"), ("nevoa", "atmosfera"),
            ("particulas", "atmosfera"))
# botão de escolher na prévia: (nome, linha depois da qual ele entra, chaves x/y, valores a mais, rótulo, dica)
PICKS = (
    ("flare", "flare_y", ("flare_x", "flare_y"), {"flare_fonte": "ponto"}, N_("Escolher o ponto do flare na prévia"),
     N_("Clique depois na prévia, onde a luz está: o flare passa a sair desse ponto.")),
    ("raios", "raios_y", ("raios_x", "raios_y"), {}, N_("Escolher a origem dos raios na prévia"),
     N_("Clique depois na prévia, de onde a luz vem (o sol, uma janela).")),
)


def clip_aspect(seq, clip) -> float:
    """Largura / altura da textura do clipe (a da fonte; a camada de ajuste e um clipe de sequência: a tela)."""
    src = seq.sources.get(clip.src)
    w, h = (getattr(src, "width", 0), getattr(src, "height", 0)) if src is not None else (0, 0)
    if not w or not h or vfx.is_adjustment(seq, clip):
        w, h = seq.width, seq.height
    return float(w) / float(max(1, h))


def uv_to_px1080(aspect: float, u: float, v: float) -> tuple[float, float]:
    """uv do clipe (0 a 1, y para baixo) → px@1080 a partir do centro do clipe (o que os ajustes guardam)."""
    return (u - 0.5) * aspect * 1080.0, (v - 0.5) * 1080.0


def px1080_to_uv(aspect: float, x: float, y: float) -> tuple[float, float]:
    return x / (aspect * 1080.0) + 0.5, y / 1080.0 + 0.5


class AtmosferaUI:
    def __init__(self, vfxui):
        self.vfxui = vfxui
        self.win = vfxui.win
        self.cards = {}
        prev = AFTER
        for key, module_id in SECTIONS:
            self.cards[key] = vfxui.add_section(key, module_id, after=prev)
            prev = key
        self.buttons: dict[str, QPushButton] = {}
        card = self.cards["luzes"]
        lay = card.body.layout()
        rows = {r.param.key: r for r in card.rows}
        for name, after, keys, extra, label, tip in PICKS:
            btn = QPushButton(_(label))
            btn.setObjectName(f"atmosfera_escolher_{name}")
            btn.setToolTip(_(tip))
            btn.clicked.connect(lambda _c=False, k=keys, e=extra: self.pick(k, e))
            row = rows.get(after)
            lay.insertWidget(lay.indexOf(row) + 1 if row is not None else lay.count(), btn)
            self.buttons[name] = btn
        vfxui.add_overlay("luzes_pontos", "luzes_lente", self.overlay)

    # -------------------------------------------------------- escolher na prévia
    def pick(self, keys: tuple[str, str], extra: dict) -> None:
        win = self.win
        clip = win.inspector.current_clip()
        if clip is None or clip.kind != VIDEO:
            win.statusBar().showMessage(_("Selecione um clipe de vídeo primeiro."), 5000)
            return
        win.statusBar().showMessage(_("Clique na prévia, dentro do clipe selecionado."), 8000)
        self.vfxui.pick_point(lambda fx, fy, cid=clip.id: self.picked(cid, keys, extra, fx, fy))

    def picked(self, cid: str, keys: tuple[str, str], extra: dict, fx: float, fy: float) -> None:
        win = self.win
        seq = win.model.seq
        clip = seq.find(cid)
        if clip is None:
            return
        uv = self.vfxui.clip_point(clip, fx, fy)
        if uv is None:
            win.statusBar().showMessage(_("Clique dentro do clipe selecionado, no quadro do cursor."), 6000)
            return
        x, y = uv_to_px1080(clip_aspect(seq, clip), *uv)
        values = {**clip.values, **extra, keys[0]: round(x), keys[1]: round(y)}
        win.model.set_clip_values(cid, values)
        win.statusBar().showMessage(_("Ponto escolhido."), 4000)

    # -------------------------------------------------------- camada da prévia
    def points_of(self, seq, clip, values: dict) -> list[tuple[float, float]]:
        """Os pontos em uso no clipe (uv do clipe): o do flare de um ponto escolhido e a origem dos raios."""
        aspect = clip_aspect(seq, clip)
        out = []
        if float(values.get("flare_intensidade", 0.0)) > 0 and values.get("flare_fonte") == "ponto":
            out.append(px1080_to_uv(aspect, float(values["flare_x"]), float(values["flare_y"])))
        if float(values.get("raios_intensidade", 0.0)) > 0:
            out.append(px1080_to_uv(aspect, float(values["raios_x"]), float(values["raios_y"])))
        return out

    def overlay(self, ctx):
        win = self.win
        clip = win.inspector.current_clip()
        if clip is None or clip.kind != VIDEO or getattr(win, "mode", "") != "edicao":
            return None
        seq = win.model.seq
        t = int(getattr(win, "frame_idx", clip.start))
        if not clip.start <= t < clip.start + clip.dur:
            return None
        values = seq.values_at(clip, t)
        pts = self.points_of(seq, clip, values)
        if not pts:
            return None
        w, h = ctx.size
        m = np.linalg.inv(compositor.transform(seq, clip, w, h, values))
        frac = []
        for u, v in pts:
            x, y, z = m @ np.array([u, v, 1.0])
            frac.append((x / z / w, y / z / h))
        return self.vfxui.points_overlay((w, h), frac, radius=5.0)


def install(vfxui) -> AtmosferaUI:
    return AtmosferaUI(vfxui)
