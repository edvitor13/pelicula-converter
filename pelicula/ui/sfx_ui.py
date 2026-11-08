"""Interface dos efeitos sonoros (1.8, módulo Beta "efeitos_sonoros"; `pelicula/sfx.py`, ARQUITETURA §47).

- "Novo ▸ Efeito sonoro ▸" na Mídia: cria a fonte (`sfx.new_source`), põe na Mídia e no cursor, na faixa de som mais
  baixa que está livre ali (uma nova, se nenhuma está), escolhida para ajustar no inspetor (`SfxUI.new_effect`).
- `EffectEditor`: os campos do efeito no alto da página de som do inspetor; cada mudança vai para
  `TimelineModel.set_source_data` (desfazer; arrastar agrupa em 400 ms), que refaz a mixagem como qualquer ajuste.
- O botão "Novo" é do módulo "titulos_geradores": com ele desligado e este ligado, o botão aparece só com o submenu dos
  efeitos (`apply_modules`).
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from .. import params, sfx, timeline
from ..i18n import _
from ..timeline import AUDIO
from . import icons, theme
from .edit_model import TimelineModel
from .store import ParamStore
from .widgets import SectionCard

MODULE = "efeitos_sonoros"


def schema_of(eff: sfx.Effect) -> params.Schema:
    """Os controles do efeito (os de 0 a 1 em %)."""
    out = []
    for f in eff.fields:
        if f.kind == "bool":
            out.append(params.B(f.key, f.label, bool(f.default), f.tip))
        elif f.kind == "escolha":
            out.append(params.C(f.key, f.label, f.default, list(f.choices), f.tip))
        elif f.lo == 0.0 and f.hi == 1.0:
            out.append(params.F(f.key, f.label, float(f.default), 0.0, 1.0, 0.01, 2, "", f.tip, percent=True))
        else:
            out.append(params.F(f.key, f.label, float(f.default), f.lo, f.hi, f.step, f.decimals, f.suffix, f.tip))
    return params.Schema([params.Section(f"efeito_{eff.id}", eff.label, None, out)])


def to_store(eff: sfx.Effect, data: dict) -> dict:
    vals = sfx.values(eff, data)
    return {f.key: vals[f.key] for f in eff.fields}


def from_store(eff: sfx.Effect, values: dict, data: dict) -> dict:
    """`Source.data` com os valores dos controles (nome, tipo, `toques` e a marca `auto` ficam como estavam)."""
    out = dict(data)
    for f in eff.fields:
        out[f.key] = f.clean(values.get(f.key, f.default))
    return out


class EffectEditor(QWidget):
    """Os campos do efeito sonoro do clipe de som escolhido; escondido para os outros clipes."""

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.setObjectName("editor_efeito")
        self.model = model
        self.path: str | None = None
        self.eff: sfx.Effect | None = None
        self.allowed = False  # módulo "efeitos_sonoros" ligado (`set_allowed`)
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
        if c is not None and c.kind != AUDIO:
            c = next((g for g in self.model.seq.group(c) if g.kind == AUDIO), None)
        src = self.model.seq.sources.get(c.src) if c is not None else None
        eff = sfx.effect_of(src)
        return (src, eff) if eff is not None else (None, None)

    def _page(self, eff: sfx.Effect) -> tuple[ParamStore, SectionCard]:
        if eff.id not in self._pages:
            store = ParamStore(None, schema=schema_of(eff))
            card = SectionCard(store.schema.sections[0], store, expanded=True)
            card.setObjectName(f"efeito_{eff.id}")
            card.setToolTip(_(eff.tip))
            store.changed.connect(lambda key, e=eff, s=store: self._changed(e, s, key))
            self.lay.addWidget(card)
            self._pages[eff.id] = (store, card)
        return self._pages[eff.id]

    def sync(self) -> None:
        src, eff = self._clip_source()
        self.path = src.path if eff is not None else None
        self.eff = eff
        for eid, (_store, card) in self._pages.items():
            card.setVisible(eff is not None and eid == eff.id)
        self.setVisible(eff is not None and self.allowed)
        if eff is None or not self.allowed:
            return
        store, card = self._page(eff)
        card.setVisible(True)
        vals = to_store(eff, src.data)
        if store.values != vals:
            self._loading = True
            try:
                store.set_all(vals, record=False)
            finally:
                self._loading = False
        tapped = bool(sfx.values(eff, src.data).get("toques"))
        for row in card.rows:  # com as batidas de um título, o ritmo não vale
            row.setVisible(not (tapped and row.param.key == "ritmo"))

    def set_allowed(self, on: bool) -> None:
        self.allowed = bool(on)
        self.sync()

    def _changed(self, eff: sfx.Effect, store: ParamStore, key: str) -> None:
        if self._loading or self.path is None or self.eff is not eff:
            return
        src = self.model.seq.sources.get(self.path)
        if src is None:
            return
        if not self.model.set_source_data(self.path, from_store(eff, store.values, src.data), record=False):
            self.sync()  # faixa travada: volta ao que está no projeto


def free_audio_track(seq: timeline.Sequence, at: int, dur: int, name: str | None = None) -> int:
    """A faixa de som mais baixa, destravada e sem nada em [at, at + dur) (uma nova abaixo de todas, se não há).
    Com `name`, só as faixas com esse nome contam (o "Pôr efeitos sonoros…" usa a faixa "Efeitos")."""
    n = len(seq.kind_tracks(AUDIO))
    for t in range(n):
        tr = seq.track(AUDIO, t)
        if tr is None or tr.locked or (name is not None and tr.name != name):
            continue
        if all(c.end <= at or c.start >= at + dur for c in seq.clips_on(AUDIO, t)):
            return t
    return n


class SfxUI:
    """O submenu dos efeitos no "Novo" da Mídia e o editor no inspetor (`install`)."""

    def __init__(self, win):
        self.win = win
        self.editor = EffectEditor(win.model)
        win.inspector.audio_page.layout().insertWidget(0, self.editor)
        menu: QMenu = win.bin.btn_new.menu()
        self.gen_actions = list(menu.actions())  # os itens dos geradores e do título (módulo "titulos_geradores")
        self.sep = menu.addSeparator()
        self.submenu = QMenu(_("Efeito sonoro"), menu)
        self.submenu.setObjectName("novo_efeito_sonoro")
        self.submenu.setToolTipsVisible(True)
        self.submenu.setIcon(icons.icon("wand", theme.TEXT, 16))
        for eid in sfx.MENU_ORDER:
            eff = sfx.EFFECTS[eid]
            act = self.submenu.addAction(_(eff.label), lambda e=eid: self.new_effect(e))
            act.setToolTip(_(eff.tip))
            act.setObjectName(f"novo_efeito_{eid}")
        self.sub_action = menu.addMenu(self.submenu)
        self.extra_actions = [self.sep, self.sub_action]  # o "Buscar sons (CC0)…" entra aqui (`ui/sons_cc0_ui.py`)

    # -------------------------------------------------------- criar
    def new_effect(self, effect_id: str) -> None:
        """Cria o efeito no cursor, na faixa de som livre mais baixa (ou numa nova), e o escolhe no inspetor."""
        win = self.win
        if effect_id not in sfx.EFFECTS:
            return
        if win.mode != "edicao":
            win.set_mode("edicao")
        win.stop_play()
        seq = win.model.seq
        src = sfx.new_source(effect_id, seq)
        win.adopt_source(src)
        win._generated_seen[src.path] = json.dumps(src.data, sort_keys=True)
        at = max(0, int(win.frame_idx)) if seq.clips else 0
        track = free_audio_track(seq, at, seq.default_dur(src))
        win.model.insert_media(src, at=at, atrack=track)
        win.statusBar().showMessage(_("{nome} na faixa A{faixa}: ajuste no inspetor, à direita.").format(
            nome=src.name, faixa=track + 1), 6000)

    # -------------------------------------------------------- módulo
    def apply_modules(self, on: set[str]) -> None:
        """Liga ou desliga o submenu e o editor. O botão "Novo" aparece com qualquer um dos dois módulos."""
        mine = MODULE in on
        gens = "titulos_geradores" in on
        self.win.bin.btn_new.setVisible(gens or mine)
        for act in self.gen_actions:
            act.setVisible(gens)
        for act in self.extra_actions:
            act.setVisible(mine)
        self.sep.setVisible(mine and gens)
        self.editor.set_allowed(mine)


def install(win) -> SfxUI:
    return SfxUI(win)

