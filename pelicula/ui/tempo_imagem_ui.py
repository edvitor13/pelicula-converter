"""1.9, tempo da imagem na janela (#68, frente F5; ARQUITETURA §53): o cartão "Tempo da imagem" do inspetor do clipe
(módulo Beta "tempo_imagem"), ligado por `vfx_ui.FRONT_UIS`.

Os ajustes (deflicker, ruído temporal, mistura de quadros) aparecem sozinhos no cartão (`editparams`, bloco F5); daqui
vêm o botão **Analisar** (a análise do deflicker, `tempo_imagem.analyze`, num trabalho de CPU da fila: nunca na GUI nem
no `Engine` da prévia) e a linha que diz o estado da análise do arquivo do clipe (pronta, faltando, arquivo mudado). A
análise vai para `Source.analysis` (fora do desfazer; vale para todas as sequências do projeto, que dividem a Mídia) e a
prévia é refeita.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import jobs, tempo_imagem as ti, vfx
from ..i18n import _
from ..timeline import VIDEO
from .job_bridge import bridge

ANALYZE_KEY = "tempo_imagem:deflicker"   # chave dos trabalhos na fila


class TempoImagemUI:
    def __init__(self, vfxui):
        self.vfxui = vfxui
        self.win = vfxui.win
        self.jobs: dict[str, jobs.Job] = {}       # caminho do arquivo → análise rodando
        self.card = vfxui.add_section(ti.SECTION, ti.MODULE, after="tempo")
        self.btn = QPushButton(_("Analisar"))
        self.btn.setObjectName("deflicker_analisar")
        self.btn.setToolTip(_("Mede o brilho de cada quadro do arquivo deste clipe (para o deflicker). Roda em segundo "
                              "plano; a análise fica guardada no projeto."))
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn.clicked.connect(self.analyze)
        self.status = QLabel()
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        line = QWidget()
        line.setObjectName("deflicker_linha")
        hl = QHBoxLayout(line)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.status, 1)
        hl.addWidget(self.btn)
        self.card.body.layout().insertWidget(0, line)
        self.win.model.selectionChanged.connect(self.refresh)
        self.win.model.changed.connect(lambda _kind: self.refresh())
        self.refresh()

    # -------------------------------------------------------- estado
    def source(self):
        """A fonte (arquivo de vídeo) do clipe escolhido no inspetor, ou None."""
        clip = self.win.inspector.current_clip()
        if clip is None or clip.kind != VIDEO:
            return None
        src = self.win.model.seq.sources.get(clip.src)
        if src is None or not src.is_file or src.is_image or not src.has_video:
            return None
        return src

    def describe(self, src) -> str:
        """O estado da análise do deflicker do arquivo (a linha do cartão)."""
        if src is None:
            return _("O deflicker precisa de um clipe de vídeo de um arquivo.")
        job = self.jobs.get(src.path)
        if job is not None and job.active:
            return _("Analisando o brilho dos quadros…")
        entry = (src.analysis or {}).get(ti.DEFLICKER)
        if ti.means_of(entry) is None:
            return _("Sem análise: o deflicker só funciona depois de Analisar.")
        if vfx.stale(src, ti.DEFLICKER):
            return _("O arquivo mudou depois da análise: analise de novo.")
        return _("Análise pronta ({n} quadros).").format(n=int(entry.get("quadros", 0)))

    def refresh(self) -> None:
        src = self.source()
        self.status.setText(self.describe(src))
        busy = src is not None and src.path in self.jobs and self.jobs[src.path].active
        self.btn.setEnabled(src is not None and not busy)

    # -------------------------------------------------------- análise
    def analyze(self) -> jobs.Job | None:
        """Põe a análise do arquivo do clipe na fila (CPU); no fim, guarda na fonte e refaz a prévia."""
        src = self.source()
        if src is None or (src.path in self.jobs and self.jobs[src.path].active):
            return None
        path = src.path

        def run(job: jobs.Job):
            job.report(_("Medindo o brilho dos quadros…"))
            return ti.analyze(src, job.cancel_event, lambda done, total: job.report(None, done, total))

        job = bridge().submit(run, _("Analisar para o deflicker"), kind=jobs.CPU, key=ANALYZE_KEY,
                              on_finished=lambda j: self._analyzed(j, path))
        self.jobs[path] = job
        self.refresh()
        return job

    def _analyzed(self, job: jobs.Job, path: str) -> None:
        if self.jobs.get(path) is job:
            del self.jobs[path]
        if job.state == jobs.CONCLUIDO and isinstance(job.result, dict):
            src = self.win.model.seq.sources.get(path)
            if src is not None:  # as sequências do projeto dividem a Mídia: vale para todas
                src.analysis = {**(src.analysis or {}), ti.DEFLICKER: job.result}
                self.win.model.changed.emit("values")
        elif job.state == jobs.ERRO:
            self.status.setText(_("Não foi possível analisar: {erro}").format(erro=job.error))
            self.btn.setEnabled(self.source() is not None)
            return
        self.refresh()


def install(vfxui) -> TempoImagemUI:
    return TempoImagemUI(vfxui)
