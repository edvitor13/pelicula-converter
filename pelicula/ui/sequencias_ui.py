"""Várias sequências na janela (#57, ARQUITETURA §41.6): as abas sobre a linha do tempo, criar/duplicar/renomear/apagar,
a troca de uma sequência para outra e o estado que cada uma guarda enquanto o app está aberto.

É o ponto único de ligação com a janela (como `cor_ui` e `sem_efeitos_ui`): `MainWindow` só instala e repassa
`_model_changed`. O modelo (`TimelineModel`) faz as operações, cada uma um passo do desfazer; trocar de aba não é passo.

**O estado de cada sequência** (cursor, entrada e saída, zoom e rolagem da linha do tempo) fica aqui, por id, só na
sessão: uma aba aberta pela primeira vez começa no quadro 0. O projeto guarda isso só da sequência aberta, como sempre.
Desfazer numa aba pode trazer outra de volta (`timeline.History`); a troca é percebida em `model_changed`, antes de a
janela recarregar a prévia, e leva junto o estado da aba.

**Sequência vazia**: a janela se comporta como num projeto vazio do modo Edição (texto de boas-vindas, sem prévia, som
nem escopos), e a aba continua sendo salva e exportável de outro lugar.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox

from .. import chapters, sequence, subedit, timeline
from ..i18n import _
from .export_dialog import ExportTarget
from .sequence_dialog import SequenceDialog, fps_label
from .sequence_tabs import SequenceTabs, TabInfo

LONE = "_"   # a vaga do estado quando o projeto tem uma sequência só (seu id some do JSON ao reabrir)


@dataclass
class View:
    """O que a janela guarda de uma sequência enquanto outra está aberta."""

    frame: int = 0
    inp: int | None = None
    outp: int | None = None
    ppf: float = 0.0       # zoom da linha do tempo (0 = o que a janela já tem)
    scroll: float = 0.0
    yscroll: float = 0.0


def tab_tip(seq: timeline.Sequence) -> str:
    """A dica da aba: o nome inteiro, o tamanho e os quadros por segundo."""
    return f"{seq.display_name}\n{seq.width} × {seq.height} • {fps_label(seq.fps_str)}"


class SequencesUI(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.views: dict[str, View] = {}
        self.last_id = win.model.seq.id
        self.last_many = len(win.model.seq.family()) > 1
        self.tabs = SequenceTabs()
        self.tabs.activated.connect(self.activate)
        self.tabs.addRequested.connect(lambda: self.new_sequence())
        self.tabs.renamed.connect(self.rename)
        self.tabs.duplicateRequested.connect(self.duplicate)
        self.tabs.settingsRequested.connect(self.settings)
        self.tabs.deleteRequested.connect(self.delete)
        self.tabs.moved.connect(self.move)
        win.tl_editor.add_header(self.tabs)
        win.bin.extra_menu = self.bin_menu
        self._bin_seen: dict[str, tuple] = {}
        for key, step in (("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            sc = QShortcut(QKeySequence(key), win)
            sc.activated.connect(lambda s=step: self.cycle(s))
        self.sync()

    # ------------------------------------------------------------ modelo
    @property
    def model(self):
        return self.win.model

    def sync(self) -> None:
        """As abas como o modelo tem agora (nomes, ordem, a aberta)."""
        seq = self.model.seq
        self.tabs.set_tabs([TabInfo(s.id, s.display_name, tab_tip(s)) for s in seq.family()], seq.id)

    def _adopt_lone(self) -> None:
        """A sequência de um projeto antigo ganha o conjunto e um id antes da primeira operação; o estado dela fica
        guardado também na vaga do projeto de uma sequência só."""
        seq = self.model.seq
        if seq.siblings is None:
            seq.ensure_set()
        self.last_id = seq.id

    def reset(self) -> None:
        """Projeto novo ou aberto: o estado das abas recomeça e as abas mostram o projeto."""
        self.views.clear()
        self._bin_seen.clear()
        seq = self.model.seq
        self.last_id, self.last_many = seq.id, len(seq.family()) > 1
        self.sync()
        self.sync_bin()

    def sync_bin(self) -> None:
        """A Mídia lista as sequências só quando há duas ou mais (uma sozinha não tem fonte: não há onde usá-la), com o
        nome, a duração e o tamanho de agora. Entram e saem junto com `SequenceSet.sync`."""
        w = self.win
        wanted = {p: s for p, s in self.model.seq.sources.items() if s.is_nested}
        for path in [p for p, s in w._sources.items() if s.is_nested and p not in wanted]:
            w._sources.pop(path, None)
            self._bin_seen.pop(path, None)
            w.bin.remove(path)
        for path, src in wanted.items():
            key = (src.name, src.frames, src.width, src.height, src.fps_str, src.has_video)
            if w._sources.get(path) is not src or self._bin_seen.get(path) != key:
                w._sources[path] = src
                self._bin_seen[path] = key
                w.bin.add_source(src)

    def bin_menu(self, menu, paths: list[str], only: bool) -> bool:
        """O menu de um item da Mídia: `only` = pergunta se todos os itens escolhidos são sequências (o menu é só
        delas, e devolve True); sem `only`, acrescenta "Nova sequência a partir deste vídeo" ao menu dos arquivos."""
        srcs = [s for s in (self.win._sources.get(p) for p in paths) if s is not None]
        seqs = [s for s in srcs if s.is_nested]
        if only:
            if not seqs or len(seqs) != len(srcs):
                return False
            one = len(seqs) == 1
            sid = seqs[0].nested_id
            menu.addAction(_("Abrir a sequência"), lambda: self.activate(sid)).setEnabled(one)
            menu.addSeparator()
            menu.addAction(_("Adicionar ao fim da linha do tempo"), lambda: [self.win.add_to_timeline(p) for p in paths])
            menu.addAction(_("Inserir no cursor (,)"), lambda: self.win.bin.place(True))
            menu.addAction(_("Sobrescrever no cursor (.)"), lambda: self.win.bin.place(False))
            menu.addSeparator()
            menu.addAction(_("Duplicar"), lambda: self.duplicate(sid)).setEnabled(one)
            menu.addSeparator()
            menu.addAction(_("Apagar a sequência…"), lambda: self.delete(sid)).setEnabled(one)
            return True
        first = next((s for s in srcs if s.has_video and not s.is_nested), None)
        if first is not None:
            menu.addAction(_("Nova sequência a partir deste vídeo"), lambda: self.new_sequence(first))
        return False

    # ------------------------------------------------------------ estado de cada sequência
    def capture(self) -> View:
        w = self.win
        cv = w.tl_editor.canvas
        return View(int(w.frame_idx), w.inp, w.outp, float(cv.ppf), float(cv.scroll), float(cv.yscroll))

    def restore(self, v: View) -> None:
        """Põe o estado da aba na janela. A prévia ainda vai ser recarregada por quem chamou."""
        w = self.win
        cv = w.tl_editor.canvas
        w.frame_idx = int(v.frame)
        w.inp, w.outp = v.inp, v.outp
        if v.ppf > 0:
            cv.ppf = v.ppf
        cv.scroll, cv.yscroll = v.scroll, v.yscroll
        w.timeline.set_inout(w.inp, w.outp)
        w.tl_editor.set_inout(w.inp, w.outp)
        cv.set_yscroll(cv.yscroll)
        cv.viewChanged.emit()
        cv.update()

    def model_changed(self, kind: str) -> bool:
        """Chamado no começo de `MainWindow._model_changed`. Se a sequência aberta é outra (aba escolhida, ou um
        desfazer que voltou a outra), guarda o estado da que saiu e põe o da que entrou. True = trocou."""
        seq = self.model.seq
        many = len(seq.family()) > 1
        switched = seq.id != self.last_id or many != self.last_many
        if switched:
            old = self.last_id if self.last_many else LONE
            mine = self.capture()
            self.views[old] = mine
            if not self.last_many and self.last_id:
                self.views[self.last_id] = mine
            new = seq.id if many else LONE
            self.restore(self.views.get(new) or self.views.get(seq.id) or View(ppf=mine.ppf))
            self.last_id, self.last_many = seq.id, many
        ids = {s.id for s in seq.family()}
        for key in [k for k in self.views if k != LONE and k not in ids]:
            del self.views[key]
        self.sync()
        self.sync_bin()
        return switched

    def in_out_state(self) -> dict[str, tuple]:
        """Entrada e saída marcadas em cada aba (`MainWindow._state`): marcar é mudança, trocar de aba não."""
        w, seq = self.win, self.model.seq
        out = {}
        for s in seq.family():
            view = self.views.get(s.id)
            pair = (w.inp, w.outp) if s is seq else (view.inp, view.outp) if view is not None else (None, None)
            if pair != (None, None):
                out[s.id] = pair
        return out

    # ------------------------------------------------------------ operações (a janela pergunta, o modelo faz)
    def activate(self, sid: str) -> None:
        if sid and self.model.activate_sequence(sid):
            self.win.statusBar().clearMessage()

    def cycle(self, step: int) -> None:
        """Ctrl+Tab / Ctrl+Shift+Tab: a aba seguinte / anterior."""
        w = self.win
        group = self.model.seq.family()
        if w.mode != "edicao" or len(group) < 2:
            return
        at = next(i for i, s in enumerate(group) if s is self.model.seq)
        self.activate(group[(at + step) % len(group)].id)

    def new_sequence(self, source: timeline.Source | None = None) -> str:
        """"+" (os valores de partida são os da sequência aberta) ou "Nova sequência a partir deste vídeo" (os do
        vídeo, como `Sequence.for_source`; depois de criar, o vídeo já está nela). Devolve o id ("" = desistiu)."""
        w = self.win
        if w.mode != "edicao":
            w.set_mode("edicao")
            if w.mode != "edicao":
                return ""
        w.stop_play()
        self._adopt_lone()
        seq = self.model.seq
        group = seq.siblings
        name = group.free_name()
        ref = None
        if source is not None and source.has_video and source.width and source.height:
            base = timeline.Sequence.for_source(source, with_media=False)
            ref = (base.width, base.height)
        else:
            base = timeline.Sequence(width=seq.width, height=seq.height, fps_str=seq.fps_str, background=seq.background,
                                     transparent=seq.transparent, window=seq.window, magnetic=seq.magnetic,
                                     micro_fade=True)
        dlg = SequenceDialog(w, base, name=name, reference=ref, taken=[s.display_name for s in group])
        if not dlg.exec():
            return ""
        width, height, fps, bg = dlg.values()
        if source is not None:
            w.adopt_source(source)
        sid = self.model.new_sequence(width, height, fps, dlg.name_value() or name, bg, micro_fade=dlg.micro_fade(),
                                      magnetic=dlg.magnetic(), transparent=dlg.transparent(), window=dlg.window(),
                                      source=source)
        w.statusBar().showMessage(_("Sequência \"{nome}\" criada.").format(nome=self.model.seq.display_name), 5000)
        return sid

    def duplicate(self, sid: str = "") -> str:
        self.win.stop_play()
        self._adopt_lone()
        new = self.model.duplicate_sequence(sid)
        if new:
            self.win.statusBar().showMessage(_("Sequência \"{nome}\" criada.").format(
                nome=self.model.seq.display_name), 5000)
        return new

    def rename(self, sid: str, name: str) -> bool:
        if self.model.rename_sequence(sid, name):
            return True
        if name.strip() and self.model.name_taken(name, sid):
            self.win.statusBar().showMessage(_("Já existe uma sequência com o nome \"{nome}\".").format(
                nome=name.strip()), 5000)
        self.sync()
        return False

    def move(self, sid: str, to: int) -> None:
        self.model.move_sequence(sid, to)
        self.sync()

    def settings(self, sid: str = "") -> None:
        """"Configurar…" do menu da aba: abre a aba e a janela de sempre (`MainWindow.sequence_settings`)."""
        if sid:
            self.activate(sid)
        self.win.sequence_settings()

    def confirm_delete(self, seq: timeline.Sequence, users: list[tuple[timeline.Sequence, int]]) -> bool:
        """A pergunta antes de apagar. Se outras sequências usam esta como clipe, diz quantos clipes saem e de onde."""
        text = _("Apagar a sequência \"{nome}\"?").format(nome=seq.display_name)
        info = _("Dá para desfazer com Ctrl+Z.")
        if users:
            where = "\n".join(_("• {nome}: {n} clipe(s)").format(nome=s.display_name, n=n) for s, n in users)
            info = _("Ela é usada como clipe em outras sequências, e esses clipes saem junto:") + "\n" + where \
                + "\n\n" + info
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Apagar sequência"))
        box.setText(text)
        box.setInformativeText(info)
        ok = box.addButton(_("Apagar"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    def delete(self, sid: str = "") -> int:
        """Apaga a sequência (a aberta, sem `sid`) depois de perguntar. Devolve os clipes que saíram (-1: não apagou)."""
        group = self.model.seq.family()
        target = next((s for s in group if s.id == sid), None) if sid else self.model.seq
        if target is None or len(group) < 2:
            return -1
        if not self.confirm_delete(target, self.model.sequence_users(target.id)):
            return -1
        self.win.stop_play()
        name = target.display_name
        gone = self.model.remove_sequence(target.id)
        self.win.statusBar().showMessage(_("Sequência \"{nome}\" apagada. Ctrl+Z desfaz.").format(nome=name), 6000)
        return gone

    # ------------------------------------------------------------ exportação
    def can_export_other(self) -> bool:
        """Há uma sequência com o que sair (para o botão Exportar valer com a aberta vazia)?"""
        group = self.model.seq.family()
        return len(group) > 1 and any(s.clips for s in group)

    def export_targets(self) -> list[ExportTarget]:
        """As sequências que a janela de exportar oferece ([] com uma só): a aberta como a janela a mostra (entrada e
        saída marcadas, capítulos e legendas) e cada outra inteira, numa cópia (`Sequence.copy`) com o que depende
        dela pronto. As vazias não saem."""
        w = self.win
        seq = self.model.seq
        group = seq.family()
        if len(group) < 2:
            return []
        out = []
        for s in group:
            if s is seq:
                if w.info is None:
                    continue
                inout = None
                if w.inp is not None or w.outp is not None:
                    inout = (w.inp or 0, w.outp if w.outp is not None else w.info.frames - 1)
                out.append(ExportTarget(s.id, s.display_name, w.info, w.src_seq.copy() if w.src_seq is not None
                                        else None, inout, w._export_chapters(), s.subtitles, w.subs_ui.ctl.cues(),
                                        int(w.frame_idx)))
                continue
            if not s.clips:
                continue
            c = s.copy()
            info = sequence.media_info(c)
            view = self.views.get(s.id)
            frame = min(max(0, view.frame if view is not None else 0), info.frames - 1)
            cues = [it.cue for it in subedit.items(c, c.subtitles)]
            out.append(ExportTarget(s.id, s.display_name, info, c, None, chapters.points(c) if c.markers else [],
                                    c.subtitles, cues, frame))
        return out

    def problems(self, texts=()) -> None:
        """Ao abrir um projeto: o que `SequenceSet.validate` tirou dele (arquivo mexido à mão: uma sequência que sumiu
        ou que fecharia um ciclo), numa mensagem só. `Project.problems` traz os avisos da leitura do arquivo."""
        group = self.model.seq.siblings
        found = list(texts) + (list(group.problems) if group is not None else [])
        if group is not None:
            group.problems.clear()
        if found:
            QMessageBox.warning(self.win, _("Abrir projeto"), "\n".join(dict.fromkeys(found)))


def install(win) -> SequencesUI:
    return SequencesUI(win)
