"""1.9, efeitos visuais na janela (#68; ARQUITETURA §49.10): o único ponto de ligação com a `MainWindow`.

A janela chama `install(win)` (depois de `sfx_ui`), `module_tools()` em `_module_tools` e `apply_modules(on)` em
`apply_modules` (depois de `self.sfx.apply_modules`). Cada frente da 1.9 liga a sua parte por aqui, sem mexer na
janela:

- **Cartões no inspetor do clipe**: as seções de `editparams.VIDEO_SECTIONS` viram cartões sozinhas
  (`ClipInspector._page`); `add_section(seção, módulo, depois_de=None)` diz de que módulo o cartão é (some com o módulo
  desligado) e, opcionalmente, depois de que cartão ele aparece; devolve o `SectionCard` para a frente pôr botões
  (`card.body.layout().addWidget(...)`).
- **Camada de prévia** (só na tela, nunca na exportação): `add_overlay(nome, módulo, provedor)` com o provedor de
  `preview_tools` (`fn(ctx) -> h × w × 4 float | None`); só roda com o módulo ligado. `points_overlay` desenha pontos.
- **Pontos na prévia**: `pick_point(fn)` liga o conta-gotas da prévia e chama `fn(fx, fy)` (fração da imagem, y para
  baixo) no clique; `clip_point(clipe, fx, fy)` leva o ponto ao uv do clipe (enquadramento e geometria dos efeitos).
- **Camada de ajuste**: Mídia › Novo › "Camada de ajuste" (módulo "efeitos_clipe"); escolhida, o inspetor esconde o
  enquadramento (fica a opacidade e a mesclagem) e o perfil de câmera.

"Desligar todos os efeitos" (Shift+D) já desliga a pilha inteira: a receita vai com `no_effects` (`vfx.plan` vazio,
sem camada de ajuste, sem janelas de tempo nem vizinhos). A renderização nunca consulta módulos.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from .. import vfx
from ..i18n import _
from ..timeline import VIDEO
from . import generators_ui, icons, theme

ADJUSTMENT_ITEM = "camada_ajuste"  # id do item no "Novo" da Mídia (`generators_ui.MODULE_MAKERS`)
# No enquadramento de uma camada de ajuste ficam só estes (ela cobre a tela inteira, pixel a pixel).
ADJUSTMENT_KEEP = ("opacidade", "mesclagem")
ADJUSTMENT_HIDE_CARDS = ("camera",)
# A interface de cada frente (`pelicula.ui.<nome>`, com `install(vfx_ui)`), chamada no fim de `VfxUI.__init__`. Frente
# nova: **uma linha** aqui.
FRONT_UIS: tuple[str, ...] = (
    "movimento_ui",  # 1.9 F3: estabilizar e rastrear ponto
)  # o perfil de câmera é do arquivo; a camada de ajuste já está no espaço do look


class VfxUI:
    def __init__(self, win):
        self.win = win
        self.sections: dict[str, str] = {}          # chave da seção → módulo
        self.overlays: dict[str, str] = {}          # nome da camada de prévia → módulo
        self.on: set[str] = set()
        self._adj_rows: list = []                   # linhas escondidas na camada de ajuste
        self._adj_cards: list = []
        generators_ui.MODULE_MAKERS[ADJUSTMENT_ITEM] = vfx.new_adjustment
        menu = win.bin.btn_new.menu()
        self.sep = menu.addSeparator()
        self.adj_action = menu.addAction(icons.icon("wand", theme.TEXT, 16), _("Camada de ajuste"),
                                         lambda: win.new_generated(ADJUSTMENT_ITEM))
        self.adj_action.setObjectName(f"novo_{ADJUSTMENT_ITEM}")
        self.adj_action.setToolTip(_("Uma camada sem imagem: a cor e os efeitos dela valem para tudo o que está "
                                     "embaixo, no tempo dela"))
        insp = win.inspector
        cards = {c.section.key: c for c in insp.vcards}
        tr = cards.get("transformar")
        self._framing = tr
        self._adj_rows = [r for r in (tr.rows if tr is not None else []) if r.param.key not in ADJUSTMENT_KEEP]
        self._adj_cards = [cards[k] for k in ADJUSTMENT_HIDE_CARDS if k in cards]
        self._adj_shown = False
        win.model.selectionChanged.connect(self._sync_inspector)
        win.model.changed.connect(self._sync_inspector)
        import importlib
        self.fronts = {name: importlib.import_module(f"{__package__}.{name}").install(self) for name in FRONT_UIS}

    # -------------------------------------------------------- para as frentes
    def card(self, section_key: str):
        """O cartão (`SectionCard`) da seção no inspetor do clipe, ou None."""
        return next((c for c in self.win.inspector.vcards if c.section.key == section_key), None)

    def add_section(self, section_key: str, module_id: str, after: str | None = None):
        """Registra o cartão da seção `section_key` (de `editparams.VIDEO_SECTIONS`) como do módulo `module_id` (some
        com ele desligado) e, com `after`, o leva para logo depois do cartão `after`. Devolve o cartão."""
        card = self.card(section_key)
        if card is None:
            raise KeyError(f"seção {section_key!r} não está em editparams.VIDEO_SECTIONS")
        self.sections[section_key] = module_id
        if after is not None:
            ref = self.card(after)
            lay = card.parentWidget().layout() if card.parentWidget() is not None else None
            if ref is not None and lay is not None:
                lay.removeWidget(card)
                lay.insertWidget(lay.indexOf(ref) + 1, card)
        card.setVisible(module_id in self.on)
        return card

    def add_overlay(self, name: str, module_id: str, provider: Callable) -> None:
        """Uma camada de prévia (`preview_tools`) que só desenha com o módulo ligado."""
        self.overlays[name] = module_id
        tools = getattr(self.win, "preview_tools", None)
        if tools is not None:
            tools.add(name, lambda ctx, m=module_id, fn=provider: fn(ctx) if m in self.on else None)

    @staticmethod
    def points_overlay(size: tuple[int, int], points, radius: float = 4.0,
                       color=(1.0, 0.8, 0.1, 1.0)) -> np.ndarray:
        """RGBA (h × w × 4, float) com um disco em cada ponto (fração da imagem, y para baixo): alças simples."""
        w, h = size
        out = np.zeros((h, w, 4), np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        for fx, fy in points:
            d = np.hypot(xx + 0.5 - fx * w, yy + 0.5 - fy * h)
            a = np.clip(radius + 0.5 - d, 0.0, 1.0)
            out[..., :3] = out[..., :3] * (1 - a[..., None]) + np.array(color[:3]) * a[..., None]
            out[..., 3] = np.maximum(out[..., 3], a * color[3])
        return out

    def pick_point(self, fn: Callable[[float, float], None]) -> None:
        """Conta-gotas da prévia: o próximo clique chama `fn(fx, fy)` (fração da imagem, y para baixo)."""
        viewer = self.win.viewer

        def done(fx, fy):
            viewer.picked.disconnect(done)
            fn(float(fx), float(fy))

        viewer.picked.connect(done)
        viewer.start_pick()

    def clip_point(self, clip, fx: float, fy: float) -> tuple[float, float] | None:
        """O ponto da prévia (fração da imagem) no uv do clipe, no quadro do cursor (None se cai fora do clipe)."""
        from .. import colorsimple
        win = self.win
        seq = win.model.seq
        t = int(getattr(win, "frame_idx", clip.start))
        layer = next((x for x in seq.layers_at(t) if x.clip.id == clip.id), None)
        img = getattr(win, "cur", None)
        if layer is None or img is None:
            return None
        h, w = img.shape[:2]
        return colorsimple.clip_point(seq, layer, w, h, fx, fy)

    # -------------------------------------------------------- módulos
    def module_tools(self) -> dict[str, list]:
        """Os cartões registrados por módulo (para `MainWindow._module_tools`)."""
        out: dict[str, list] = {}
        for key, module_id in self.sections.items():
            card = self.card(key)
            if card is not None:
                out.setdefault(module_id, []).append(card)
        return out

    def apply_modules(self, on: set[str]) -> None:
        """Depois do `SfxUI.apply_modules`: o "Novo" aparece também só com a camada de ajuste."""
        self.on = set(on)
        mine = vfx.ADJUSTMENT_MODULE in on
        if mine:  # o `SfxUI` decidiu pelos geradores e pelos efeitos sonoros; com a camada de ajuste, aparece
            self.win.bin.btn_new.setVisible(True)
        self.adj_action.setVisible(mine)
        self.sep.setVisible(mine)
        for key, module_id in self.sections.items():
            card = self.card(key)
            if card is not None:
                card.setVisible(module_id in on)

    # -------------------------------------------------------- inspetor da camada de ajuste
    def _sync_inspector(self, *_args) -> None:
        insp = self.win.inspector
        c = insp.current_clip()
        adj = c is not None and c.kind == VIDEO and vfx.is_adjustment(self.win.model.seq, c)
        if adj == self._adj_shown:
            return
        self._adj_shown = adj
        advanced = bool(getattr(self._framing, "_advanced", False))
        for r in self._adj_rows:
            r.setVisible(not adj and (not r.param.advanced or advanced))
        for card in self._adj_cards:
            show = not adj and not (card.section.key == "camera" and insp._camera_hidden)  # clipe de sequência
            card.setVisible(show)
            for p in getattr(insp.filtro, "panels", []):
                if card in getattr(p, "natural", {}):
                    p.natural[card] = show
        if self._adj_cards:
            insp.filtro.reapply()


def install(win) -> VfxUI:
    return VfxUI(win)
