"""Interface dos geradores (`pelicula/generators.py`): o menu "Novo" da Mídia e os campos no inspetor.

O menu cria a fonte (`generators.new_source`) e a janela a põe na Mídia e na linha do tempo
(`MainWindow.new_generated`). O painel de campos fica no alto do inspetor do clipe (`ClipInspector.add_source_editor`)
e aparece só quando o clipe escolhido é de um gerador: cada mudança vai para `TimelineModel.set_source_data`
(desfazer; arrastar um controle agrupa em 400 ms). Os controles são os mesmos dos ajustes (`SectionCard` com um
`params.Schema` montado a partir dos `generators.Field`).
"""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from .. import generators, params
from ..i18n import _
from ..textrender import color_hex, parse_color
from ..timeline import VIDEO
from . import icons, theme
from .edit_model import TimelineModel
from .store import ParamStore
from .widgets import SectionCard

MENU_ORDER = (generators.KIND_COLOR, generators.GRADIENT, generators.LEADER)
# Outros itens do menu "Novo" (o título acrescenta o seu): (id, rótulo N_(), dica N_(), fn(seq) -> Source).
# Acrescente no fim.
EXTRA_ITEMS: list[tuple[str, str, str, Callable]] = []


def maker_of(item_id: str) -> Callable | None:
    """Quem cria a fonte do item `item_id` do menu "Novo" (fn(seq) -> Source), ou None."""
    if item_id in generators.GENERATORS:
        return lambda seq: generators.new_source(item_id, seq)
    return next((fn for i, _l, _t, fn in EXTRA_ITEMS if i == item_id), None)


def new_menu(parent, chosen: Callable[[str], None]) -> QMenu:
    """O menu "Novo" da Mídia: um item por gerador (e os de `EXTRA_ITEMS`); `chosen(id)` cria o item."""
    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    for gid in MENU_ORDER:
        gen = generators.GENERATORS[gid]
        act = menu.addAction(icons.icon("wand", theme.TEXT, 16), _(gen.label), lambda g=gid: chosen(g))
        act.setToolTip(_(gen.tip))
        act.setObjectName(f"novo_{gid}")
    for gid, label, tip, _fn in EXTRA_ITEMS:
        act = menu.addAction(icons.icon("wand", theme.TEXT, 16), _(label), lambda g=gid: chosen(g))
        act.setToolTip(_(tip))
        act.setObjectName(f"novo_{gid}")
    return menu


def schema_of(gen: generators.Generator) -> params.Schema:
    """O esquema dos controles do gerador (cores como [r, g, b] na interface, #rrggbb no projeto)."""
    out = []
    for f in gen.fields:
        if f.kind == "cor":
            out.append(params.COR(f.key, f.label, parse_color(f.default), f.tip))
        elif f.kind == "bool":
            out.append(params.B(f.key, f.label, bool(f.default), f.tip))
        elif f.kind == "escolha":
            out.append(params.C(f.key, f.label, f.default, list(f.choices), f.tip))
        else:
            out.append(params.F(f.key, f.label, float(f.default), f.lo, f.hi, f.step, f.decimals, f.suffix, f.tip))
    return params.Schema([params.Section(gen.id, gen.label, None, out)])


def to_store(gen: generators.Generator, data: dict) -> dict:
    vals = generators.values(gen, data)
    return {f.key: (list(parse_color(vals[f.key])) if f.kind == "cor" else vals[f.key]) for f in gen.fields}


def from_store(gen: generators.Generator, values: dict, data: dict) -> dict:
    """`Source.data` com os valores dos controles (o resto — nome, tipo do gerador — fica como estava)."""
    out = copy.deepcopy(dict(data))
    for f in gen.fields:
        v = values.get(f.key, f.default)
        out[f.key] = color_hex(parse_color(v)) if f.kind == "cor" else f.clean(v)
    return out


class GeneratorEditor(QWidget):
    """Os campos do gerador do clipe de imagem escolhido; escondido para os outros clipes."""

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.path: str | None = None
        self.gen: generators.Generator | None = None
        self.allowed = True  # módulo "Títulos e geradores" ligado (`set_allowed`)
        self._pages: dict[str, tuple[ParamStore, SectionCard]] = {}
        self._loading = False
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        model.selectionChanged.connect(self.sync)
        model.changed.connect(lambda _k: self.sync())
        self.sync()

    def _clip_source(self):
        c = self.model.primary()
        if c is None:
            return None, None
        if c.kind != VIDEO:
            c = next((g for g in self.model.seq.group(c) if g.kind == VIDEO), None)
        src = self.model.seq.sources.get(c.src) if c is not None else None
        if src is None or src.is_file:
            return None, None
        return src, generators.generator_of(src)

    def _page(self, gen: generators.Generator) -> tuple[ParamStore, SectionCard]:
        if gen.id not in self._pages:
            store = ParamStore(None, schema=schema_of(gen))
            card = SectionCard(store.schema.sections[0], store, expanded=True)
            card.setObjectName(f"gerador_{gen.id}")
            store.changed.connect(lambda key, g=gen, s=store: self._changed(g, s, key))
            self.lay.addWidget(card)
            self._pages[gen.id] = (store, card)
        return self._pages[gen.id]

    def sync(self) -> None:
        """Mostra os campos do gerador do clipe escolhido (ou esconde o painel)."""
        src, gen = self._clip_source()
        self.path = src.path if gen is not None else None
        self.gen = gen
        for gid, (_store, card) in self._pages.items():
            card.setVisible(gen is not None and gid == gen.id)
        self.setVisible(gen is not None and self.allowed)
        if gen is None or not self.allowed:
            return
        store, card = self._page(gen)
        card.setVisible(True)
        vals = to_store(gen, src.data)
        if store.values != vals:
            self._loading = True
            try:
                store.set_all(vals, record=False)
            finally:
                self._loading = False
        self._visibility(gen, src.data, card)

    def set_allowed(self, on: bool) -> None:
        """Módulo "Títulos e geradores" desligado: o painel não aparece (o clipe continua igual na imagem)."""
        self.allowed = bool(on)
        self.sync()

    def _visibility(self, gen: generators.Generator, data: dict, card: SectionCard) -> None:
        vals = generators.values(gen, data)
        fields = {f.key: f for f in gen.fields}
        for row in card.rows:
            f = fields.get(row.param.key)
            row.setVisible(f is None or f.visible(vals))

    def _changed(self, gen: generators.Generator, store: ParamStore, key: str) -> None:
        if self._loading or self.path is None or self.gen is not gen:
            return
        src = self.model.seq.sources.get(self.path)
        if src is None:
            return
        data = from_store(gen, store.values, src.data)
        if not self.model.set_source_data(self.path, data, record=False):
            self.sync()  # faixa travada: volta ao que está no projeto
