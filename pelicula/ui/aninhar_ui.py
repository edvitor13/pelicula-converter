"""Sequência dentro de sequência na janela (#57, ARQUITETURA §41.7): "Aninhar seleção", "Desaninhar", abrir a sequência
de um clipe, a forma de onda dele e o que as ferramentas que leem o arquivo fazem com ele.

É o ponto de ligação com a janela (como `sequencias_ui`): `MainWindow` instala e repassa três sinais da linha do tempo e a
forma de onda. As contas são de `aninhar.py` (puras, com os testes); o modelo (`TimelineModel.nest_selection` e
`unnest_clip`) faz cada operação num passo só do desfazer; aqui ficam a pergunta, a mensagem e o atalho.

Forma de onda do clipe de som de uma sequência: o WAV da mixagem dela (`audiomix.nested_mix_path`), que muda quando
qualquer clipe de dentro muda e nasce quando a mixagem de fora termina (`mix_finished`). Enquanto não existe, a linha reta.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox

from .. import aninhar, audiomix, timeline
from ..i18n import _

SHORTCUT = "Ctrl+Shift+G"   # aninhar seleção (o G de "grupo"); livre em `MainWindow._shortcuts`


class NestUI(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._wav: dict[str, str] = {}      # chave da fonte (`sequencia:<id>`) → WAV da mixagem dela, desde a última edição
        self._pending: set[str] = set()
        sc = QShortcut(QKeySequence(SHORTCUT), win)
        sc.activated.connect(lambda: win.mode == "edicao" and self.nest_selection())
        self.shortcut = sc
        win.model.changed.connect(lambda _k: self._wav.clear())
        ed = win.tl_editor
        ed.nestRequested.connect(self.nest_selection)
        ed.unnestRequested.connect(self.unnest)
        ed.openNestedRequested.connect(self.open_clip)

    @property
    def model(self):
        return self.win.model

    # ------------------------------------------------------------ aninhar e desaninhar
    def nest_selection(self) -> bool:
        """"Aninhar seleção": sem janela, tem efeito na hora. A aba continua a de fora, com o clipe novo selecionado. Uma
        recusa diz o motivo na barra de status e não muda nada."""
        w = self.win
        w.stop_play()
        status = w.statusBar()
        w.seqs_ui._adopt_lone()   # o estado da aba (cursor, zoom) passa a valer para o id que a sequência ganha
        try:
            res = self.model.nest_selection(look=dict(w.store.values))
        except aninhar.Refusal as exc:
            status.showMessage(exc.text, 9000)
            return False
        msg = _("Seleção aninhada em \"{nome}\". Ctrl+Z desfaz.").format(nome=res.inner.display_name)
        status.showMessage(" ".join([msg, *res.warnings]), 12000 if res.warnings else 7000)
        return True

    def unnest(self, cid: str) -> bool:
        """"Desaninhar": pergunta antes se algum ajuste do clipe de sequência se perderia; recusa (com o motivo) o que não
        dá, como velocidade diferente de 1× ou reverso."""
        w = self.win
        status = w.statusBar()
        clip = self.model.seq.find(cid)
        inner = self.model.seq.nested(clip) if clip is not None else None
        if inner is None:
            return False
        w.stop_play()
        try:
            loss = self.model.unnest_loss(cid)
            if loss and not self.confirm_unnest(inner.display_name, loss):
                return False
            res = self.model.unnest_clip(cid)
        except aninhar.Refusal as exc:
            status.showMessage(exc.text, 9000)
            return False
        status.showMessage(_("Sequência \"{nome}\" desaninhada: {n} clipe(s) voltaram para esta linha do tempo. "
                             "Ctrl+Z desfaz.").format(nome=inner.display_name, n=len(res.clips)), 7000)
        return True

    def confirm_unnest(self, name: str, loss: list[str]) -> bool:
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Desaninhar"))
        box.setText(_("Desaninhar \"{nome}\"?").format(nome=name))
        box.setInformativeText(_("O clipe da sequência tem ajustes que não passam para os clipes de dentro e se perdem: "
                                 "{lista}. Dá para desfazer com Ctrl+Z.").format(lista=", ".join(loss)))
        ok = box.addButton(_("Desaninhar"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    # ------------------------------------------------------------ abrir a sequência de um clipe
    def open_clip(self, cid: str, frame: int) -> bool:
        """Dois cliques num clipe de sequência: abre a aba dela com o cursor no quadro de dentro que estava sob o clique
        (`Sequence.src_frame`, preso à sequência). A aba de fora guarda o estado dela, como sempre."""
        seq = self.model.seq
        clip = seq.find(cid)
        inner = seq.nested(clip) if clip is not None else None
        if inner is None:
            return False
        t = min(max(int(frame), clip.start), clip.end - 1)
        inside = min(max(0, seq.src_frame(clip, t)), max(0, inner.duration - 1))
        self.win.seqs_ui.activate(inner.id)
        if self.model.seq is inner:
            self.win.seek(inside)
        return True

    # ------------------------------------------------------------ forma de onda
    def peaks(self, src: timeline.Source):
        """Picos do WAV da mixagem da sequência de um clipe de som (None: ainda não existe, a linha reta)."""
        seq = self.model.seq
        inner = seq.nested(src)
        if inner is None:
            return None
        path = self._wav.get(src.path)
        if path is None:
            path = self._wav[src.path] = audiomix.nested_mix_path(inner)
        w = self.win
        if path in w._peaks:
            return w._peaks[path]
        if os.path.exists(path) and path not in w._peaks_pending:
            w._peaks_pending.add(path)

            def run():
                try:
                    data = audiomix.peaks(path)
                except Exception:  # noqa: BLE001
                    data = None
                w._peaks[path] = data
                w._mix_bridge.peaks.emit("")   # qualquer clipe de sequência pode estar esperando

            threading.Thread(target=run, daemon=True, name="forma-de-onda-aninhada").start()
        return None

    def mix_finished(self) -> None:
        """A mixagem de fora terminou (e com ela os WAVs de dentro): as formas de onda que faltavam podem ser lidas."""
        self.win.tl_editor.canvas.update()


def install(win) -> NestUI:
    return NestUI(win)
