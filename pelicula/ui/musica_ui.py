"""Música na linha do tempo (1.8, ARQUITETURA §46): batidas, ímã nas batidas, encaixar a música na duração do vídeo e
abaixar a música sob a voz.

- **Batidas** (`batidas.py`): "Detectar batidas" no menu do botão direito de um clipe de som, ou sozinho quando um
  clipe de um arquivo só de som (música) com mais de `AUTO_MIN_S` entra na montagem (preferência `PREF_AUTO`,
  ligada por padrão). A análise roda na fila de tarefas (`jobs.CPU`, chave `DETECT_KEY`), com Cancelar na barra de
  status; o resultado fica no cache de `batidas` (pelo carimbo do arquivo), então reabrir o projeto mostra as batidas
  sem analisar de novo.

Ganchos: a janela chama `install` (`MainWindow.musica`); o menu da linha do tempo chama `add_clip_actions`. Sem a
janela (testes da linha do tempo sozinha), `controller_for` prende um controlador à linha do tempo.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QProgressBar, QToolButton, QWidget

from .. import batidas, jobs
from ..i18n import _, fmt_decimal
from ..timeline import AUDIO
from . import prefs
from .job_bridge import bridge

DETECT_KEY = "detectar_batidas"
PREF_AUTO = "musica/batidas_auto"        # "true"/"false"; sem valor = ligado
AUTO_MIN_S = 20.0                        # clipe de música mais longo que isto é analisado sozinho


def music_path(seq, clip) -> str | None:
    """O arquivo de som do clipe, se as batidas dele podem ser achadas (clipe de som de um arquivo com som)."""
    if clip is None or clip.kind != AUDIO:
        return None
    src = seq.sources.get(clip.src)
    if src is None or not src.is_file or not src.has_audio:
        return None
    return clip.src


def is_music(seq, clip) -> bool:
    """Clipe de som de um arquivo só de som (sem imagem): o que a análise automática olha."""
    src = seq.sources.get(clip.src) if clip is not None else None
    return music_path(seq, clip) is not None and not src.has_video and not src.is_image


class MusicUI(QObject):
    """As batidas conhecidas de cada arquivo (`beats`), a análise em segundo plano e as ações da música."""

    message = Signal(str)
    beatsChanged = Signal()

    def __init__(self, model, canvas, parent=None):
        super().__init__(parent)
        self.model = model
        self.canvas = canvas
        self.beats: dict[str, batidas.Beats] = {}
        self.jobs: dict[str, jobs.Job] = {}
        self._looked: set[str] = set()      # arquivos já procurados no cache (para não ler o disco a cada mudança)
        self._refused: set[str] = set()     # análise automática que falhou: não tenta de novo sozinha
        self.bar = QWidget()
        hl = QHBoxLayout(self.bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.label = QLabel(_("Procurando as batidas…"))
        self.progress = QProgressBar()
        self.progress.setFixedWidth(80)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.btn_cancel = QToolButton()
        self.btn_cancel.setObjectName("beats_cancel")
        self.btn_cancel.setText(_("Cancelar"))
        self.btn_cancel.clicked.connect(self.cancel)
        for w in (self.label, self.progress, self.btn_cancel):
            hl.addWidget(w)
        self.bar.hide()
        model.changed.connect(self._model_changed)
        self.beatsChanged.connect(canvas.update)
        self.scan()

    # ------------------------------------------------------------ batidas
    @property
    def auto(self) -> bool:
        return str(prefs.settings().value(PREF_AUTO, "true")) != "false"

    def beats_for(self, path: str | None) -> batidas.Beats | None:
        if not path:
            return None
        hit = self.beats.get(path)
        if hit is None and path not in self._looked:
            self._looked.add(path)
            hit = batidas.cached(path)
            if hit is not None:
                self.beats[path] = hit
        return hit

    def busy(self, path: str | None = None) -> bool:
        if path is None:
            return any(j.active for j in self.jobs.values())
        job = self.jobs.get(path)
        return job is not None and job.active

    def _model_changed(self, kind: str) -> None:
        if kind in ("structure", "*", "settings"):
            self.scan()

    def scan(self) -> None:
        """Lê do cache as batidas dos clipes de som e manda analisar as músicas longas novas (preferência)."""
        seq = self.model.seq
        auto = self.auto
        for c in seq.clips:
            path = music_path(seq, c)
            if path is None or self.beats_for(path) is not None or self.busy(path):
                continue
            if auto and path not in self._refused and is_music(seq, c) and c.dur >= AUTO_MIN_S * seq.fps:
                self.detect(path, auto=True)

    def detect(self, path: str, auto: bool = False, then=None) -> jobs.Job | None:
        """Acha as batidas do arquivo numa thread de trabalho; `then(beats)` roda no fim (thread principal)."""
        if self.busy(path):
            return None
        hit = self.beats_for(path)
        if hit is not None:
            if then is not None:
                then(hit)
            return None

        def run(job: jobs.Job):
            job.report(_("Procurando as batidas…"))
            return batidas.analyze_file(path, job.cancel_event)

        job = bridge().submit(run, _("Detectar batidas"), kind=jobs.CPU, key=DETECT_KEY,
                              on_finished=lambda j: self._detected(j, path, auto, then))
        self.jobs[path] = job
        self.bar.show()
        return job

    def cancel(self) -> None:
        for job in list(self.jobs.values()):
            job.cancel()

    def _detected(self, job: jobs.Job, path: str, auto: bool, then) -> None:
        if self.jobs.get(path) is job:
            del self.jobs[path]
        self.bar.setVisible(self.busy())
        if job.state == jobs.ERRO:
            self._refused.add(path)
            if not auto:
                self.message.emit(job.error)
            return
        if job.state != jobs.CONCLUIDO:
            if auto:
                self._refused.add(path)   # cancelada: não volta sozinha a cada mudança
            return
        b: batidas.Beats = job.result
        self.beats[path] = b
        self.beatsChanged.emit()
        self.message.emit(self.describe(b))
        if then is not None:
            then(b)

    @staticmethod
    def describe(b: batidas.Beats) -> str:
        if not b.times:
            return _("Nenhuma batida encontrada neste som.")
        text = _("{bpm} BPM, {n} batidas").format(bpm=fmt_decimal(b.bpm, 1), n=len(b.times))
        if not b.confident:
            return text + " — " + _("ritmo irregular: as batidas são só uma ajuda visual")
        return text + " — " + _("compassos de 4 estimados")


def controller_for(canvas) -> MusicUI:
    """O controlador da janela (`install`) ou, sem ela (testes), um preso à linha do tempo."""
    ctl = getattr(canvas.window(), "musica", None)
    if ctl is None:
        ctl = getattr(canvas, "_musica", None)
        if ctl is None:
            ctl = canvas._musica = MusicUI(canvas.model, canvas, canvas)
    return ctl


def add_clip_actions(menu: QMenu, canvas, clip) -> None:
    """Itens da música no menu do botão direito de um clipe de som."""
    path = music_path(canvas.model.seq, clip)
    if path is None:
        return
    ctl = controller_for(canvas)
    b = ctl.beats_for(path)
    if b is None:
        act = menu.addAction(_("Detectar batidas"), lambda: ctl.detect(path))
        act.setObjectName("detect_beats")
        act.setEnabled(not ctl.busy(path))
    else:
        act = menu.addAction(ctl.describe(b))
        act.setObjectName("beats_info")
        act.setEnabled(False)


def install(win) -> MusicUI:
    """O controlador da janela, com o progresso na barra de status e as mensagens nela."""
    ctl = MusicUI(win.model, win.tl_editor.canvas, win)
    win.statusBar().addPermanentWidget(ctl.bar)
    ctl.message.connect(lambda text: win.statusBar().showMessage(text, 10000))
    return ctl


__all__ = ["MusicUI", "add_clip_actions", "controller_for", "install", "music_path", "is_music"]
