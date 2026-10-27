"""Ponte entre a fila de tarefas (`pelicula/jobs.py`, sem Qt) e a interface.

Os eventos da fila chegam em qualquer thread; a ponte os leva para a thread principal e emite sinais
do Qt: `added`, `changed` (começou ou andou; o progresso vem no máximo a cada `THROTTLE` segundos
por trabalho) e `finished` (concluído, erro ou cancelado). `submit(..., on_finished=f)` chama
`f(job)` na thread principal quando o trabalho termina — é ali que a interface mexe em widgets,
preferências ou no projeto.

    from .job_bridge import bridge
    job = bridge().submit(fn, _("Baixar…"), kind=jobs.REDE, key="componente:x", on_finished=self._done)
    bridge().finished.connect(self._on_job_finished)   # todos os trabalhos (filtre por job.key)

A ponte compartilhada (`bridge()`) usa a fila do app (`jobs.shared()`), é filha da QApplication e
vive até o fim do app. Crie e use na thread principal. Prefira ligar sinais a métodos de widgets
(o Qt desliga sozinho quando o widget some) e deixe `on_finished` para o que precisa acontecer
mesmo com a janela fechada.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot

from .. import jobs


class JobBridge(QObject):
    added = Signal(object)     # Job
    changed = Signal(object)   # Job (começou ou andou)
    finished = Signal(object)  # Job (concluído, erro ou cancelado)
    _relay = Signal(str, object)

    THROTTLE = 0.05

    def __init__(self, queue: jobs.JobQueue, parent: QObject | None = None):
        super().__init__(parent)
        self.queue = queue
        self._callbacks: dict[int, list[Callable[[jobs.Job], None]]] = {}
        self._cb_lock = threading.Lock()
        self._last: dict[int, tuple[float, str]] = {}
        self._relay.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        queue.add_listener(self._on_event)

    def detach(self) -> None:
        """Para de ouvir a fila (a ponte não emite mais nada)."""
        self.queue.remove_listener(self._on_event)

    def submit(self, fn: Callable[[jobs.Job], Any], title: str, kind: str = jobs.CPU, key: str = "",
               data: Any = None, on_finished: Callable[[jobs.Job], None] | None = None) -> jobs.Job:
        """Põe um trabalho na fila; `on_finished(job)` roda na thread principal quando ele terminar."""
        job = jobs.Job(fn, title, kind, key, data)
        if on_finished is not None:
            with self._cb_lock:
                self._callbacks.setdefault(job.id, []).append(on_finished)
        return self.queue.submit(job)

    # ------------------------------------------------------------ qualquer thread
    def _on_event(self, event: str, job: jobs.Job) -> None:
        if event == jobs.PROGRESS:
            now = time.monotonic()
            last_t, last_stage = self._last.get(job.id, (0.0, None))
            if now - last_t < self.THROTTLE and job.stage == last_stage:
                return
            self._last[job.id] = (now, job.stage)
        try:
            self._relay.emit(event, job)
        except RuntimeError:
            pass  # a ponte já foi destruída (fim do app)

    # ------------------------------------------------------------ thread principal
    @Slot(str, object)
    def _dispatch(self, event: str, job: jobs.Job) -> None:
        if event == jobs.ADDED:
            self.added.emit(job)
        elif event in (jobs.STARTED, jobs.PROGRESS):
            if not job.finished:
                self.changed.emit(job)
        elif event == jobs.FINISHED:
            self._last.pop(job.id, None)
            with self._cb_lock:
                callbacks = self._callbacks.pop(job.id, [])
            for fn in callbacks:
                try:
                    fn(job)
                except Exception:  # noqa: BLE001 — um callback com defeito não derruba a interface
                    if sys.stderr is not None:
                        traceback.print_exc()
            self.finished.emit(job)


_shared: JobBridge | None = None


def bridge() -> JobBridge:
    """A ponte da fila do app inteiro (criada na primeira chamada, na thread principal)."""
    global _shared
    if _shared is None:
        _shared = JobBridge(jobs.shared(), QCoreApplication.instance())
    return _shared
