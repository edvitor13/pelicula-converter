"""Look de película próprio de cada sequência (#67, ARQUITETURA §42) na janela.

É o ponto único de ligação com a janela (como `sequencias_ui`): `MainWindow` instala, chama `reset` quando o projeto
recomeça (arquivo aberto, projeto aberto ou novo) e `sync` quando a montagem muda (`_model_changed`).

- O `ParamStore` da janela edita **um** look por vez: o da sequência aberta, se ela tem look próprio
  (`timeline.Sequence.look`), senão o do projeto. Trocar de aba troca o look em edição (`sync`); o que sai fica guardado
  aqui (`project`, o do projeto) ou na própria sequência, e cada look guarda o seu desfazer
  (`ParamStore.history_state`/`load`).
- Mexer no look próprio escreve na sequência na hora (`write`, chamado de `MainWindow._update_modified`), sem passo do
  desfazer da montagem: `timeline.History` guarda e compara a montagem sem os looks.
- A escolha ("Igual ao do projeto" / "Próprio desta sequência") fica na linha "Look de …" do painel de ajustes, no menu
  da aba e no menu da sequência na Mídia. Voltar a "Igual ao do projeto" descarta o look próprio (pergunta antes, se ele
  mudou).
- Uma sequência com look próprio dentro de outra entra **sem look** (decisão da #67: nada de grão ou halação em
  dobro): o look dela só vale quando ela é aberta ou exportada. O inspetor do clipe e a inserção avisam (`nested_note`).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QWidget

from .. import keyframes, params, presets, timeline
from ..i18n import _
from .widgets import compact

LONE = "_"        # a vaga da sequência sozinha (sem id no JSON)
SHARED = "projeto"
OWN = "proprio"


@dataclass
class Held:
    """Um look fora do `ParamStore` (o do projeto, enquanto o de uma sequência está em edição)."""

    values: dict
    keys: dict
    preset: str
    history: tuple | None = None


def same_look(a: timeline.SeqLook | None, values: dict, keys: dict) -> bool:
    """O look próprio é igual a estes valores e chaves (descartá-lo não perde nada)?"""
    if a is None:
        return True
    clean = keyframes.to_json(keyframes.clean_keys(params.FILM, keys))
    return params.sanitize(a.values) == params.sanitize(values) and keyframes.to_json(
        keyframes.clean_keys(params.FILM, a.keys)) == clean


class SeqLookUI(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.owner: str | None = None        # a sequência cujo look está no `ParamStore` (`_key`); None = o do projeto
        self.project: Held | None = None     # o look do projeto, enquanto o de uma sequência está em edição
        self.hist: dict[str, tuple] = {}     # o desfazer do look próprio de cada sequência (só na sessão)
        self._loading = False
        self._build_row()
        self.refresh()

    # ------------------------------------------------------------ estado
    @staticmethod
    def _key(seq: timeline.Sequence) -> str:
        return seq.id or LONE

    def _find(self, key: str | None) -> timeline.Sequence | None:
        if key is None:
            return None
        return next((s for s in self.win.model.seq.family() if self._key(s) == key), None)

    def _by_id(self, sid: str) -> timeline.Sequence | None:
        seq = self.win.model.seq
        return next((s for s in seq.family() if s.id == sid), None) if sid else seq

    def reset(self) -> None:
        """Projeto novo ou aberto: o `ParamStore` passa a ser o look do projeto (o que estiver nele)."""
        self.owner, self.project = None, None
        self.hist.clear()
        self.refresh()

    def sync(self) -> None:
        """O look em edição é o da sequência aberta (o próprio, ou o do projeto). Chamado a cada mudança da montagem e
        depois de abrir um projeto; sem troca, só a linha do painel se acerta."""
        w = self.win
        seq = w.model.seq
        want = self._key(seq) if seq.look is not None else None
        if self.owner == LONE and want not in (None, LONE) and self._find(LONE) is None:
            self.owner = want  # a sequência sozinha ganhou id (o projeto ganhou a segunda): é a mesma
        if want == self.owner:
            self.refresh()
            return
        st = w.store
        history = st.history_state()
        if self.owner is None:
            self.project = Held(copy.deepcopy(st.values), st.keys_json(), w.preset_id, history)
        else:
            self.hist[self.owner] = history
        if want is None:
            held = self.project if self.project is not None else Held(st.values, st.keys_json(), w.preset_id)
            values, keys, pid, history = held.values, held.keys, held.preset, held.history
            self.project = None
        else:
            values, keys, pid, history = seq.look.values, seq.look.keys, seq.look.preset_id, self.hist.get(want)
        self.owner = want
        self._loading = True
        try:
            w.preset_id = pid or presets.DEFAULT_ID
            st.load(values, keys, history)
        finally:
            self._loading = False
        self._show_preset()
        self.refresh()

    def _show_preset(self) -> None:
        w = self.win
        w.preset_combo.blockSignals(True)
        w.preset_combo.setCurrentIndex(max(0, w.preset_combo.findData(w.preset_id)))
        w.preset_combo.blockSignals(False)
        w.looks.set_selected(w.preset_id)
        w._update_modified()
        w._update_history()
        w._check_modules()

    def write(self) -> None:
        """O look próprio em edição vai para a sequência (a cada ajuste; não é passo do desfazer da montagem)."""
        if self._loading or self.owner is None:
            return
        seq = self._find(self.owner)
        if seq is None or seq.look is None:
            return
        st = self.win.store
        seq.look = timeline.SeqLook(copy.deepcopy(st.values), self.win.preset_id, st.keys_json())

    # ------------------------------------------------------------ o que cada um usa
    def project_look(self) -> tuple[dict, dict, str]:
        """O look do projeto (valores, chaves, preset), esteja ele em edição ou guardado: é o que o .plc grava em
        "valores", "chaves" e "preset"."""
        w = self.win
        if self.owner is None or self.project is None:
            return copy.deepcopy(w.store.values), w.store.keys_json(), w.preset_id
        p = self.project
        return copy.deepcopy(p.values), copy.deepcopy(p.keys), p.preset

    def look_of(self, seq: timeline.Sequence) -> tuple[dict, dict, str]:
        """O look que vale quando `seq` é aberta ou exportada: o próprio dela, senão o do projeto."""
        if seq.look is None:
            return self.project_look()
        if self.owner is not None and self._key(seq) == self.owner:
            w = self.win
            return copy.deepcopy(w.store.values), w.store.keys_json(), w.preset_id
        return copy.deepcopy(seq.look.values), copy.deepcopy(seq.look.keys), seq.look.preset_id

    def export_look(self, seq: timeline.Sequence) -> tuple[dict, dict, str]:
        """(valores, chaves, nome) com que `seq` sai na exportação: o que a prévia mostraria com ela aberta (sem efeitos
        ou no modo Edição sem película, só a montagem)."""
        w = self.win
        if w.no_effects:
            return presets.builtin_values("original"), {}, _("Sem efeitos")
        if w.mode == "edicao" and not w.edit_film:
            return presets.builtin_values("original"), {}, _("Sem película (só a edição)")
        values, keys, pid = self.look_of(seq)
        return values, keys, w.preset_name(pid)

    def nested_note(self, source) -> str:
        """O aviso para um clipe (ou fonte) de uma sequência com look próprio; "" se ela segue o projeto."""
        inner = self.win.model.seq.nested(source)
        if inner is None or inner.look is None:
            return ""
        return _("O look próprio de \"{nome}\" vale só quando ela é aberta ou exportada. Aqui ela entra sem look e "
                 "recebe o desta sequência, uma vez.").format(nome=inner.display_name)

    # ------------------------------------------------------------ escolha
    def has_own(self, sid: str = "") -> bool:
        seq = self._by_id(sid)
        return seq is not None and seq.look is not None

    def set_own(self, sid: str = "") -> bool:
        """A sequência ganha look próprio, começando igual ao do projeto (a imagem não muda). False = já tinha."""
        seq = self._by_id(sid)
        if seq is None or seq.look is not None:
            return False
        values, keys, pid = self.project_look()
        seq.look = timeline.SeqLook(values, pid, keys)
        self._changed(seq, _("\"{nome}\" agora tem look próprio, começando igual ao do projeto.").format(
            nome=seq.display_name))
        return True

    def confirm_discard(self, seq: timeline.Sequence) -> bool:
        """A pergunta antes de descartar um look próprio que mudou."""
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Look da sequência"))
        box.setText(_("Voltar \"{nome}\" ao look do projeto?").format(nome=seq.display_name))
        box.setInformativeText(_("O look próprio dela é descartado."))
        ok = box.addButton(_("Usar o do projeto"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    def set_shared(self, sid: str = "") -> bool:
        """A sequência volta a "Igual ao do projeto" (o look próprio sai). False = já era, ou a pessoa desistiu."""
        seq = self._by_id(sid)
        if seq is None or seq.look is None:
            return False
        own_values, own_keys, _pid = self.look_of(seq)
        values, keys, _ppid = self.project_look()
        if not same_look(timeline.SeqLook(own_values, "", own_keys), values, keys) and not self.confirm_discard(seq):
            self.refresh()
            return False
        seq.look = None
        self.hist.pop(self._key(seq), None)
        self._changed(seq, _("\"{nome}\" voltou ao look do projeto.").format(nome=seq.display_name))
        return True

    def choose(self, sid: str, own: bool) -> bool:
        return self.set_own(sid) if own else self.set_shared(sid)

    def _changed(self, seq: timeline.Sequence, message: str) -> None:
        w = self.win
        if seq is w.model.seq:
            self.sync()
        else:
            self.refresh()
        w.seqs_ui.sync()
        w._update_title()
        w.statusBar().showMessage(message, 6000)

    # ------------------------------------------------------------ interface
    def _build_row(self) -> None:
        """A linha "Look de …" no painel de ajustes, logo acima dos presets (só com mais de uma sequência, ou com a
        aberta tendo look próprio)."""
        w = self.win
        self.row = QWidget()
        h = QHBoxLayout(self.row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.label = QLabel()
        self.label.setObjectName("Muted")
        h.addWidget(self.label, 1)
        self.combo = compact(QComboBox(), 14)
        self.combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.combo.addItem(_("Igual ao do projeto"), SHARED)
        self.combo.addItem(_("Próprio desta sequência"), OWN)
        self.combo.setToolTip(_("O look de película desta sequência. \"Igual ao do projeto\" segue o look do projeto; "
                                "\"Próprio\" começa como cópia dele e muda só aqui (por exemplo, um corte com outra "
                                "película). Dentro de outra sequência, ela entra sem look e recebe o daquela."))
        self.combo.activated.connect(self._combo_chosen)
        # A caixa cabe o item mais longo no idioma em uso ("Próprio desta sequência" cortava em 14 letras); o rótulo
        # ao lado é que se encurta (com o nome inteiro na dica).
        self.combo.setMinimumContentsLength(max(len(self.combo.itemText(i)) for i in range(self.combo.count())))
        h.addWidget(self.combo)
        panel = w.preset_combo.parentWidget()
        lay = panel.layout() if panel is not None else None
        if lay is not None:
            lay.insertWidget(1, self.row)  # depois do "AJUSTES"

    def _combo_chosen(self, _i: int) -> None:
        self.choose("", self.combo.currentData() == OWN)

    def refresh(self) -> None:
        """A linha do painel como a sequência aberta está agora."""
        seq = self.win.model.seq
        show = len(seq.family()) > 1 or seq.look is not None
        self.row.setVisible(show)
        if not show:
            return
        name = seq.display_name
        self.label.setText(self.label.fontMetrics().elidedText(_("Look de \"{nome}\"").format(nome=name),
                                                               Qt.TextElideMode.ElideRight, 150))
        self.label.setToolTip(_("Look de \"{nome}\"").format(nome=name))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(1 if seq.look is not None else 0)
        self.combo.blockSignals(False)

    def add_menu(self, menu, sid: str) -> None:
        """"Look de película" num menu (o da aba e o da sequência na Mídia)."""
        sub = menu.addMenu(_("Look de película"))
        own = self.has_own(sid)
        a = sub.addAction(_("Igual ao do projeto"), lambda: self.set_shared(sid))
        a.setCheckable(True)
        a.setChecked(not own)
        b = sub.addAction(_("Próprio desta sequência"), lambda: self.set_own(sid))
        b.setCheckable(True)
        b.setChecked(own)


def install(win) -> SeqLookUI:
    return SeqLookUI(win)
