"""Limpeza do som na interface (1.8, ARQUITETURA §44): o que os cartões de som do inspetor têm além das linhas do
esquema.

- Cartão "Limpar o som": botão "Aprender o ruído" (o trecho de `somlimpo.learn_range`, conferido numa thread de
  trabalho pela fila de tarefas) e as linhas do trecho aprendido escondidas; "Detectar" ao lado do zumbido
  (`somlimpo.detect_hum_file` no trecho usado do clipe).
- Cartão "Equalizar e limpar": menu "Predefinições" (`editparams.AUDIO_PRESETS`, um passo do desfazer).
- "Sincronizar pelo som" no menu do botão direito da linha do tempo (2 ou mais grupos com som escolhidos):
  `SyncController` roda `sincronia.plan` na fila de tarefas, com progresso e Cancelar na barra de status, e move os
  grupos com `TimelineModel.move_groups` (um passo do desfazer).

Ganchos: `ClipInspector` cria o `InspectorSound`; o menu da linha do tempo chama `add_clip_actions`; a janela chama
`install` (o controlador e a barra de status). Tudo o que muda o clipe passa pelo `TimelineModel` (um passo do
desfazer); a mixagem lê os valores (`audiomix`, `somlimpo`).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QToolButton, QWidget)

from .. import editparams, jobs, sincronia, somlimpo
from ..i18n import _, fmt_decimal
from ..timeline import AUDIO
from .job_bridge import bridge

LEARN_KEY = "aprender_ruido"
SYNC_KEY = "sincronizar_som"
HUM_KEY = "detectar_zumbido"
LEARN_STRENGTH = 0.8   # força posta ao aprender, se estava em 0 (para o resultado se ouvir logo)


def _seconds(t: float) -> str:
    return fmt_decimal(t, 2) + " s"


class InspectorSound:
    """Liga os botões dos cartões de som do inspetor ao clipe escolhido."""

    def __init__(self, inspector):
        self.ins = inspector
        self.model = inspector.model
        self.store = inspector.astore
        self.job: jobs.Job | None = None
        cards = {c.section.key: c for c in inspector.acards}
        self.clean_card = cards.get("limpar")
        self.rows = {r.param.key: r for r in self.clean_card.rows} if self.clean_card is not None else {}
        for key in ("ruido_ini", "ruido_fim"):  # o trecho aprendido não se edita à mão
            if key in self.rows:
                self.rows[key].setVisible(False)
        self.btn_learn = QPushButton(_("Aprender o ruído"))
        self.btn_learn.setObjectName("learn_noise")
        self.btn_learn.setToolTip(_("Ouve um trecho só com o ruído deste clipe: a entrada e a saída marcadas na linha do "
                                    "tempo, se estão dentro do clipe, ou 1 s a partir do cursor."))
        self.btn_learn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_learn.clicked.connect(self.learn)
        self.learned = QLabel()
        self.learned.setObjectName("Faint")
        self.learned.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.hide()
        if self.clean_card is not None:
            body = self.clean_card.body.layout()
            at = body.indexOf(self.rows["ruido_perfil"]) + 1 if "ruido_perfil" in self.rows else 0
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(self.btn_learn)
            hl.addWidget(self.learned, 1)
            body.insertWidget(at, line)
            body.insertWidget(at + 1, self.status)
        self.hum_job: jobs.Job | None = None
        self.btn_hum = QPushButton(_("Detectar"))
        self.btn_hum.setObjectName("detect_hum")
        self.btn_hum.setToolTip(_("Ouve o clipe e escolhe 50 Hz ou 60 Hz se um dos dois zumbidos se destaca."))
        self.btn_hum.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_hum.clicked.connect(self.detect_hum)
        hum = self.rows.get("zumbido")
        if hum is not None:  # o botão ao lado da caixa de escolha
            lay = hum.layout()
            at = lay.indexOf(hum.combo)
            lay.removeWidget(hum.combo)
            line = QHBoxLayout()
            line.setSpacing(6)
            line.addWidget(hum.combo, 1)
            line.addWidget(self.btn_hum)
            lay.insertLayout(at, line)
        self.btn_presets = QToolButton()
        self.btn_presets.setObjectName("eq_presets")
        self.btn_presets.setText(_("Predefinições"))
        self.btn_presets.setToolTip(_("Ajustes prontos de graves, médios, agudos, voz e cortes (Ctrl+Z desfaz)"))
        self.btn_presets.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_presets.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.presets_menu = QMenu(self.btn_presets)
        for key, label, _values in editparams.AUDIO_PRESETS:
            act = self.presets_menu.addAction(_(label), lambda k=key: self.apply_preset(k))
            act.setObjectName(f"preset_{key}")
        self.btn_presets.setMenu(self.presets_menu)
        eq = cards.get("eq")
        if eq is not None:
            eq.body.layout().insertWidget(0, self.btn_presets)
        self.store.changed.connect(self._changed)
        self.model.selectionChanged.connect(lambda: self.say(""))
        self.update()

    # -------------------------------------------------------- estado
    def _changed(self, key: str) -> None:
        if key in ("*", "ruido_ini", "ruido_fim"):
            self.update()

    def update(self) -> None:
        a, b = float(self.store.get("ruido_ini")), float(self.store.get("ruido_fim"))
        self.learned.setText(_("Aprendido: {ini} a {fim} do arquivo.").format(ini=_seconds(a), fim=_seconds(b))
                             if b - a > 1e-9 else _("Nenhum ruído aprendido."))

    def say(self, text: str) -> None:
        """Mensagem no cartão e, com a janela, na barra de status."""
        self.status.setText(text)
        self.status.setVisible(bool(text))
        win = self.ins.window()
        if text and hasattr(win, "statusBar") and win is not self.ins:
            win.statusBar().showMessage(text, 7000)

    def _marks(self) -> tuple[int | None, int | None]:
        win = self.ins.window()
        return getattr(win, "inp", None), getattr(win, "outp", None)

    def _clip(self):
        c = self.ins.current_clip()
        return c if c is not None and c.kind == AUDIO else None

    # -------------------------------------------------------- aprender o ruído
    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def learn(self) -> jobs.Job | None:
        """Confere o trecho (`somlimpo.learn_range`) e o som dele numa thread de trabalho; no fim grava o trecho no
        clipe num passo do desfazer. None (com a explicação na mensagem) se o trecho não serve."""
        c = self._clip()
        if c is None or self.busy:
            return None
        seq = self.model.seq
        path = somlimpo.source_path(seq, c)
        if path is None:
            self.say(_("Este clipe não tem som de arquivo para aprender o ruído."))
            return None
        try:
            t0, t1 = somlimpo.learn_range(seq, c, self.ins.playhead, *self._marks())
        except somlimpo.CleanError as exc:
            self.say(str(exc))
            return None
        if not os.path.exists(path):
            self.say(_("O som desta sequência ainda não foi mixado: toque a prévia e tente de novo."))
            return None
        cid = c.id

        def run(job: jobs.Job):
            job.report(_("Ouvindo o ruído…"))
            somlimpo.profile_for(path, t0, t1, job.cancel_event)
            return t0, t1

        self.btn_learn.setEnabled(False)
        self.say(_("Ouvindo o ruído…"))
        self.job = bridge().submit(run, _("Aprender o ruído"), kind=jobs.CPU, key=LEARN_KEY,
                                   on_finished=lambda job: self._learned(job, cid))
        return self.job

    def _learned(self, job: jobs.Job, cid: str) -> None:
        if job is not self.job:
            return
        self.btn_learn.setEnabled(True)
        if job.state == jobs.ERRO:
            self.say(job.error)
            return
        c = self.model.seq.find(cid)
        if job.state != jobs.CONCLUIDO or c is None:
            self.say("")
            return
        t0, t1 = job.result
        vals = {**c.values, "ruido_ini": float(t0), "ruido_fim": float(t1)}
        if float(vals["ruido_perfil"]) <= 0:
            vals["ruido_perfil"] = LEARN_STRENGTH
        self.model.set_clip_values(cid, vals)
        self.say(_("Ruído aprendido de {ini} a {fim} do arquivo.").format(ini=_seconds(t0), fim=_seconds(t1)))

    # -------------------------------------------------------- predefinições do "eq"
    def apply_preset(self, key: str) -> None:
        """Uma predefinição de `editparams.AUDIO_PRESETS` no clipe, num passo do desfazer."""
        c = self._clip()
        if c is not None:
            self.model.set_clip_values(c.id, editparams.apply_audio_preset(c.values, key))

    # -------------------------------------------------------- zumbido
    def detect_hum(self) -> jobs.Job | None:
        """Ouve o trecho usado do clipe (até `somlimpo.HUM_MAX_S`) numa thread de trabalho e escolhe 50 ou 60 Hz se um
        dos dois se destaca; senão diz isso e não muda nada."""
        c = self._clip()
        if c is None or (self.hum_job is not None and self.hum_job.active):
            return None
        seq = self.model.seq
        path = somlimpo.source_path(seq, c)
        if path is None or not os.path.exists(path):
            self.say(_("Este clipe não tem som de arquivo para ouvir."))
            return None
        t0, t1 = seq.source_range(c)
        cid = c.id

        def run(job: jobs.Job):
            job.report(_("Procurando o zumbido…"))
            return somlimpo.detect_hum_file(path, t0, t1, job.cancel_event)

        self.btn_hum.setEnabled(False)
        self.say(_("Procurando o zumbido…"))
        self.hum_job = bridge().submit(run, _("Detectar o zumbido"), kind=jobs.CPU, key=HUM_KEY,
                                       on_finished=lambda job: self._hum_found(job, cid))
        return self.hum_job

    def _hum_found(self, job: jobs.Job, cid: str) -> None:
        if job is not self.hum_job:
            return
        self.btn_hum.setEnabled(True)
        c = self.model.seq.find(cid)
        if job.state == jobs.ERRO:
            self.say(job.error)
        elif job.state != jobs.CONCLUIDO or c is None:
            self.say("")
        elif job.result is None:
            self.say(_("Nenhum zumbido de 50 ou 60 Hz se destaca neste clipe: nada mudou."))
        else:
            if c.values["zumbido"] != job.result:
                self.model.set_clip_values(cid, {**c.values, "zumbido": job.result})
            self.say(_("Zumbido de {hz} Hz encontrado: os entalhes já estão no clipe.").format(hz=job.result))


# ------------------------------------------------------------------ sincronizar pelo som
class SyncController(QObject):
    """"Sincronizar pelo som": o plano numa thread de trabalho e, no fim, os grupos movidos num passo do desfazer.
    `message` leva o resultado (a janela mostra na barra de status); `bar` é o progresso com Cancelar."""

    message = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.job: jobs.Job | None = None
        self.last: sincronia.Plan | None = None
        self.bar = QWidget()
        hl = QHBoxLayout(self.bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.label = QLabel(_("Sincronizando pelo som…"))
        self.progress = QProgressBar()
        self.progress.setFixedWidth(120)
        self.progress.setTextVisible(False)
        self.btn_cancel = QToolButton()
        self.btn_cancel.setObjectName("sync_cancel")
        self.btn_cancel.setText(_("Cancelar"))
        self.btn_cancel.clicked.connect(self.cancel)
        for w in (self.label, self.progress, self.btn_cancel):
            hl.addWidget(w)
        self.bar.hide()
        bridge().changed.connect(self._progress)

    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def can_sync(self, ids) -> bool:
        return len(sincronia.candidates(self.model.seq, ids)) >= 2

    def start(self, ids) -> jobs.Job | None:
        """Começa a sincronizar os clipes `ids` (com os ligados). None se já está rodando ou faltam clipes com som."""
        ids = list(ids)
        if self.busy:
            return None
        if not self.can_sync(ids):
            self.message.emit(_("Escolha dois ou mais clipes com som para sincronizar."))
            return None
        seq = self.model.seq.copy()   # o trabalho lê uma cópia (outra thread)

        def run(job: jobs.Job):
            job.report(_("Comparando o som dos clipes…"))
            return sincronia.plan(seq, ids, cancel=job.cancel_event,
                                  progress=lambda done, total: job.report(None, done, total))

        self.progress.setRange(0, 0)
        self.bar.show()
        self.job = bridge().submit(run, _("Sincronizar pelo som"), kind=jobs.CPU, key=SYNC_KEY,
                                   on_finished=self._finished)
        return self.job

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()

    def _progress(self, job: jobs.Job) -> None:
        if job is self.job and job.total:
            self.progress.setRange(0, job.total)
            self.progress.setValue(job.done)

    def _name(self, cid: str) -> str:
        c = self.model.seq.find(cid)
        src = self.model.seq.sources.get(c.src) if c is not None else None
        return (c.name if c is not None and c.name else "") or (src.name if src is not None else "?")

    def _finished(self, job: jobs.Job) -> None:
        if job is not self.job:
            return
        self.bar.hide()
        if job.state == jobs.ERRO:
            self.message.emit(job.error)
            return
        if job.state != jobs.CONCLUIDO:
            self.message.emit(_("Sincronização cancelada: nada mudou."))
            return
        p: sincronia.Plan = job.result
        self.last = p
        moves = [(m.clip, m.frames) for m in p.moves if m.frames]
        self.model.move_groups(moves)
        parts = []
        if p.moves:
            worst = max(abs(m.residue) for m in p.moves) * 1000
            parts.append(_("{n} clipe(s) sincronizado(s) pelo som; sobra abaixo de um quadro: até {ms} ms.").format(
                n=len(p.moves), ms=fmt_decimal(worst, 1)))
        for cid, why in p.refused:
            parts.append(_("{nome} ficou onde estava: {motivo}.").format(nome=self._name(cid), motivo=why))
        self.message.emit(" ".join(parts) or _("Nada para sincronizar."))


def controller_for(canvas) -> SyncController:
    """O controlador da janela (`install`) ou, sem ela (testes), um preso à linha do tempo."""
    ctl = getattr(canvas.window(), "som_sync", None)
    if ctl is None:
        ctl = getattr(canvas, "_som_sync", None)
        if ctl is None:
            ctl = canvas._som_sync = SyncController(canvas.model, canvas)
    return ctl


def add_clip_actions(menu: QMenu, canvas, clip) -> None:
    """"Sincronizar pelo som" no menu do botão direito com 2 ou mais grupos com som escolhidos."""
    ids = list(canvas.model.selection)
    if len(sincronia.candidates(canvas.model.seq, ids)) < 2:
        return
    ctl = controller_for(canvas)
    act = menu.addAction(_("Sincronizar pelo som"), lambda: ctl.start(ids))
    act.setObjectName("sync_sound")
    act.setToolTip(_("Alinha os clipes escolhidos pelo som com o da referência (o som ligado ao vídeo da faixa mais "
                     "baixa); procura até {s} s para cada lado. Ctrl+Z desfaz.").format(s=int(sincronia.SEARCH_S)))
    act.setEnabled(not ctl.busy)


def install(win) -> SyncController:
    """O controlador da janela, com o progresso na barra de status e o resultado na mensagem dela."""
    ctl = SyncController(win.model, win)
    win.statusBar().addPermanentWidget(ctl.bar)
    ctl.message.connect(lambda text: win.statusBar().showMessage(text, 10000))
    return ctl


__all__ = ["InspectorSound", "SyncController", "add_clip_actions", "controller_for", "install"]
