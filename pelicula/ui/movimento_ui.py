"""1.9, estabilização e rastreio na janela (F3, #68; ARQUITETURA §51.4). Módulo "movimento" (Beta, começa desligado).

Ligado por `vfx_ui.FRONT_UIS` (`install(vfxui)`), sem mexer na janela:

- Cartão **Estabilizar** (depois de "Transformar"): o interruptor `estab_on`, os ajustes do esquema e o botão
  **Analisar**, que mede o movimento do arquivo num trabalho de CPU da fila (`estabilizacao.analyze`; progresso e
  Cancelar na barra de status). O resultado vai para a fonte (`Source.analysis`, fora do desfazer, mas o projeto fica
  com alterações a salvar) e liga a estabilização do clipe, se estava desligada (um passo do desfazer).
- Cartão **Rastrear ponto**: **Rastrear ponto** liga o conta-gotas da prévia; o clique escolhe o ponto no quadro do
  cursor e o rastreio roda na fila (`rastreio.run`). O rastro vai para o clipe (um passo do desfazer).
  **Aplicar a…** abre os alvos (`rastreio.targets_for`), **Reaplicar** assa de novo no último alvo e **Apagar o
  rastro** tira o rastro do clipe (as chaves já assadas ficam). Uma camada da prévia marca o ponto no quadro.

Sem atalhos novos. A renderização não passa por aqui: só as chaves e os ajustes que este módulo grava.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from .. import estabilizacao, jobs, rastreio
from ..i18n import _
from ..timeline import VIDEO
from .job_bridge import bridge

MODULE = estabilizacao.MODULE
ANALYZE_KEY = "movimento_analise"
TRACK_KEY = "movimento_rastreio"
OVERLAY = "rastreio"


class MotionUI(QObject):
    message = Signal(str)

    def __init__(self, vfxui):
        super().__init__(vfxui.win)
        self.vfx = vfxui
        self.win = win = vfxui.win
        self.job: jobs.Job | None = None
        # ---- Estabilizar
        self.card_estab = vfxui.add_section("estabilizar", MODULE, after="transformar")
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        self.btn_analyze = QPushButton(_("Analisar"))
        self.btn_analyze.setObjectName("estab_analisar")
        self.btn_analyze.setToolTip(_("Mede o tremor do arquivo inteiro (uma vez por arquivo); a análise fica guardada "
                                      "no projeto"))
        self.btn_analyze.clicked.connect(self.analyze)
        row.addWidget(self.btn_analyze)
        row.addStretch(1)
        bl.addLayout(row)
        self.lbl_estab = QLabel()
        self.lbl_estab.setObjectName("estab_status")
        self.lbl_estab.setWordWrap(True)
        bl.addWidget(self.lbl_estab)
        self.card_estab.body.layout().addWidget(box)
        # ---- Rastrear ponto
        self.card_track = vfxui.add_section("rastreio", MODULE, after="estabilizar")
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        self.btn_track = QPushButton(_("Rastrear ponto"))
        self.btn_track.setObjectName("rastreio_ponto")
        self.btn_track.setToolTip(_("Clique num ponto com detalhe na prévia: ele é seguido no arquivo para a frente e "
                                    "para trás"))
        self.btn_track.clicked.connect(self.start_track)
        self.btn_apply = QToolButton()
        self.btn_apply.setObjectName("rastreio_aplicar")
        self.btn_apply.setText(_("Aplicar a…"))
        self.btn_apply.setToolTip(_("Transforma o rastro em chaves de animação de um alvo"))
        self.btn_apply.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.apply_menu = QMenu(self.btn_apply)
        self.apply_menu.aboutToShow.connect(self._fill_apply_menu)
        self.btn_apply.setMenu(self.apply_menu)
        for w in (self.btn_track, self.btn_apply):
            row.addWidget(w)
        row.addStretch(1)
        bl.addLayout(row)
        row = QHBoxLayout()
        self.btn_reapply = QToolButton()
        self.btn_reapply.setObjectName("rastreio_reaplicar")
        self.btn_reapply.setText(_("Reaplicar"))
        self.btn_reapply.setToolTip(_("Refaz as chaves no último alvo (depois de mover, aparar ou rastrear de novo)"))
        self.btn_reapply.clicked.connect(self.reapply)
        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("rastreio_apagar")
        self.btn_clear.setText(_("Apagar o rastro"))
        self.btn_clear.setToolTip(_("Tira o rastro do clipe (as chaves já aplicadas ficam)"))
        self.btn_clear.clicked.connect(self.clear_track)
        for w in (self.btn_reapply, self.btn_clear):
            row.addWidget(w)
        row.addStretch(1)
        bl.addLayout(row)
        self.lbl_track = QLabel()
        self.lbl_track.setObjectName("rastreio_status")
        self.lbl_track.setWordWrap(True)
        bl.addWidget(self.lbl_track)
        self.card_track.body.layout().addWidget(box)
        # ---- barra de status: progresso e Cancelar
        self.bar = QWidget()
        hl = QHBoxLayout(self.bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.bar_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(80)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.btn_cancel = QToolButton()
        self.btn_cancel.setObjectName("movimento_cancelar")
        self.btn_cancel.setText(_("Cancelar"))
        self.btn_cancel.clicked.connect(self.cancel)
        for w in (self.bar_label, self.progress, self.btn_cancel):
            hl.addWidget(w)
        self.bar.hide()
        status = win.statusBar()
        status.addPermanentWidget(self.bar)
        self.message.connect(lambda text: status.showMessage(text, 10000))
        bridge().changed.connect(self._job_changed)
        win.model.selectionChanged.connect(self.refresh)
        win.model.changed.connect(lambda _k: self.refresh())
        vfxui.add_overlay(OVERLAY, MODULE, self.overlay)
        self.refresh()

    # -------------------------------------------------------- estado
    def clip(self):
        c = self.win.inspector.current_clip()
        return c if c is not None and c.kind == VIDEO else None

    def source(self, c=None):
        c = c if c is not None else self.clip()
        return self.win.model.seq.sources.get(c.src) if c is not None else None

    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def refresh(self) -> None:
        c = self.clip()
        src = self.source(c)
        video = src is not None and src.is_file and not src.is_image and src.has_video
        idle = not self.busy()
        self.btn_analyze.setEnabled(video and idle)
        self.btn_track.setEnabled(video and idle)
        if not video:
            self.lbl_estab.setText(_("Só um clipe de vídeo pode ser estabilizado."))
        else:
            text = estabilizacao.describe(src)
            if estabilizacao.entry_of(src) is not None and c.values.get("estab_on"):
                z = estabilizacao.zoom_of(src, c.values)
                if z > 1.0005:
                    text += " " + _("Ampliado em {p}%.").format(p=round((z - 1.0) * 100))
            self.lbl_estab.setText(text)
        tr = rastreio.track_of(c) if c is not None else None
        self.lbl_track.setText(rastreio.describe(tr) if video or tr is not None
                               else _("Só dá para rastrear um ponto num vídeo."))
        seq = self.win.model.seq
        self.btn_apply.setEnabled(tr is not None and bool(rastreio.targets_for(seq, c)))
        self.btn_reapply.setEnabled(tr is not None and bool(tr.target))
        self.btn_clear.setEnabled(tr is not None)

    # -------------------------------------------------------- trabalhos
    def _submit(self, fn, title: str, key: str, done) -> None:
        self.job = bridge().submit(fn, title, kind=jobs.CPU, key=key, on_finished=done)
        self.bar_label.setText(title)
        self.progress.setRange(0, 0)
        self.bar.show()
        self.refresh()

    def _job_changed(self, job) -> None:
        if job is not self.job:
            return
        p = job.progress
        if p is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(p * 1000))

    def _finished(self, job) -> bool:
        """Fecha a barra; True se o trabalho concluiu (erro: a mensagem vai para a barra de status)."""
        if job is self.job:
            self.job = None
        self.bar.hide()
        self.refresh()
        if job.state == jobs.ERRO:
            self.message.emit(job.error)
            return False
        return job.state == jobs.CONCLUIDO

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()

    # -------------------------------------------------------- estabilizar
    def analyze(self) -> None:
        c = self.clip()
        src = self.source(c)
        if c is None or src is None or self.busy():
            return
        try:
            estabilizacao.check_source(src)
        except estabilizacao.AnalysisError as e:
            self.message.emit(str(e))
            return
        if not estabilizacao.available():
            self.message.emit(_("Este ffmpeg não tem a vid.stab: a análise usa o método interno (mais lento)."))
        path, cid = src.path, c.id

        def run(job: jobs.Job):
            job.report(_("Analisando o movimento…"))
            return estabilizacao.analyze(src, job.cancel_event, lambda d, t: job.report(None, d, t))

        self._submit(run, _("Analisar o movimento"), ANALYZE_KEY, lambda j: self._analyzed(j, path, cid))

    def _analyzed(self, job, path: str, cid: str) -> None:
        if not self._finished(job):
            return
        model = self.win.model
        src = model.seq.sources.get(path)
        if src is None:
            return
        src.analysis = {**(src.analysis or {}), estabilizacao.KIND: job.result}
        c = model.seq.find(cid)
        if c is not None and not c.values.get("estab_on"):
            model.update_clip_values({cid: {"estab_on": True}})
        else:
            model.changed.emit("values")
        self.message.emit(estabilizacao.describe(src))

    # -------------------------------------------------------- rastrear
    def start_track(self) -> None:
        c = self.clip()
        if c is None or self.busy():
            return
        self.message.emit(_("Clique no ponto a seguir na prévia."))
        self.vfx.pick_point(lambda fx, fy, cid=c.id: self._picked(cid, fx, fy))

    def _picked(self, cid: str, fx: float, fy: float) -> None:
        seq = self.win.model.seq
        c = seq.find(cid)
        src = self.source(c) if c is not None else None
        if c is None or src is None:
            return
        t = int(getattr(self.win, "frame_idx", c.start))
        if not c.start <= t < c.end:
            self.message.emit(_("Ponha o cursor sobre o clipe para escolher o ponto."))
            return
        uv = rastreio.clip_uv(seq, c, t, fx, fy)
        if uv is None:
            self.message.emit(_("O ponto escolhido está fora da imagem do clipe."))
            return
        ref = seq.src_frame(c, t)
        first, last = rastreio.source_frames(seq, c)
        v = seq.values_at(c, t)
        box, search = float(v.get("rastreio_caixa", 64.0)), float(v.get("rastreio_busca", 48.0))

        def run(job: jobs.Job):
            job.report(_("Rastreando o ponto…"))
            return rastreio.run(src, ref, uv, first, last, box, search, job.cancel_event,
                                lambda d, n: job.report(None, d, n))

        self._submit(run, _("Rastrear o ponto"), TRACK_KEY, lambda j: self._tracked(j, cid))

    def _tracked(self, job, cid: str) -> None:
        if not self._finished(job):
            return
        track = job.result
        model = self.win.model
        if model.seq.find(cid) is None:
            return
        model.apply_edit(lambda seq: rastreio.store(seq.find(cid), track), "values")
        self.message.emit(rastreio.describe(track))

    def _edit(self, fn) -> None:
        """Uma edição do rastreio num passo do desfazer; o motivo da recusa vai para a barra de status."""
        try:
            self.win.model.apply_edit(fn, "values")
        except rastreio.TrackError as e:
            self.message.emit(str(e))

    def _fill_apply_menu(self) -> None:
        self.apply_menu.clear()
        c = self.clip()
        if c is None:
            return
        seq = self.win.model.seq
        for target, dest in rastreio.targets_for(seq, c):
            label = _(target.label)
            if dest.id != c.id:
                label = f"{label}: {self.source(dest).name if self.source(dest) else dest.id}"
            act = self.apply_menu.addAction(label)
            act.setObjectName(f"rastreio_alvo_{target.id}_{dest.id}")
            act.triggered.connect(lambda _c=False, tid=target.id, did=dest.id, cid=c.id:
                                  self._edit(lambda s: rastreio.apply(s, cid, tid, did)))

    def reapply(self) -> None:
        c = self.clip()
        if c is not None:
            self._edit(lambda s, cid=c.id: rastreio.reapply(s, cid))

    def clear_track(self) -> None:
        c = self.clip()
        if c is not None:
            self._edit(lambda s, cid=c.id: rastreio.store(s.find(cid), None))

    # -------------------------------------------------------- prévia
    def overlay(self, ctx):
        """O ponto rastreado no quadro da prévia (só no modo Edição, com o clipe escolhido)."""
        if getattr(self.win, "mode", "") != "edicao":
            return None
        c = self.clip()
        tr = rastreio.track_of(c) if c is not None else None
        seq = self.win.model.seq
        t = ctx.frame
        if tr is None or not c.start <= t < c.end:
            return None
        uv = tr.at(seq.src_frame(c, t))
        if uv is None:
            return None
        p = rastreio.canvas_point(seq, c, t, uv)
        w, h = ctx.size
        return self.vfx.points_overlay((w, h), [(p[0] / seq.width, p[1] / seq.height)],
                                       radius=max(3.0, h / 180.0))


def install(vfxui) -> MotionUI:
    return MotionUI(vfxui)
