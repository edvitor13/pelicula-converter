"""Fila de tarefas em segundo plano: downloads de componentes hoje; análises e IA nas próximas versões.

O núcleo não usa Qt. Um `Job` tem título, tipo (`CPU`, `GPU` ou `REDE`), etapa, progresso, resultado,
erro e pedido de cancelamento. A função do trabalho recebe o próprio job:

    def baixar(job):
        for i in range(10):
            job.check_cancel()                  # levanta Cancelled se pediram para cancelar
            job.report(_("Baixando…"), i, 10)   # etapa, feito, total (total 0 = sem porcentagem)
        return resultado                        # vira job.result

    job = jobs.shared().submit(baixar, _("Baixar o Whisper"), kind=jobs.REDE, key="componente:whisper")

Regras:

- No máximo `limits[tipo]` trabalhos de cada tipo rodando ao mesmo tempo, e **um só de GPU** (um
  contexto OpenGL por thread e memória de vídeo limitada: o trabalho de GPU cria o seu `Engine`
  dentro da função, nunca usa o da janela). Dentro de cada tipo vale a ordem de chegada; um tipo
  lotado não segura os outros.
- Cancelar um trabalho na espera tira ele da fila; rodando, liga `job.cancel_event` e a função para
  quando conferir (`check_cancel()` ou `cancelled`). Termina como `CANCELADO`.
- Erros não derrubam a fila: o trabalho termina como `ERRO`, com a mensagem em `job.error` e a
  exceção em `job.exception`.
- Ouvintes (`add_listener`) recebem `(evento, job)` na thread em que o evento acontece: `ADDED`,
  `STARTED`, `PROGRESS` e `FINISHED`. A interface usa `ui/job_bridge.py`, que entrega tudo na thread
  principal por sinais do Qt (e chama `on_finished` lá).
- `shared()` é a fila do app inteiro; ao fechar o Python os trabalhos em andamento são cancelados
  (`atexit`), para que limpem as pastas temporárias.

Base para as análises e a IA: o resultado fica em `job.result`; quem guarda no projeto é quem pediu
o trabalho, na thread principal (`on_finished` da ponte do Qt). Nada daqui entra no caminho de
renderização (regra de determinismo por quadro).
"""

from __future__ import annotations

import atexit
import itertools
import sys
import threading
import time
import traceback
from typing import Any, Callable

CPU = "cpu"
GPU = "gpu"
REDE = "rede"
KINDS = (CPU, GPU, REDE)

# Estados de um trabalho
ESPERANDO = "esperando"
RODANDO = "rodando"
CONCLUIDO = "concluido"
ERRO = "erro"
CANCELADO = "cancelado"
FINAL_STATES = (CONCLUIDO, ERRO, CANCELADO)

# Eventos para os ouvintes
ADDED = "added"
STARTED = "started"
PROGRESS = "progress"
FINISHED = "finished"

DEFAULT_LIMITS = {CPU: 2, GPU: 1, REDE: 3}
HISTORY = 50  # trabalhos terminados guardados em jobs()

Listener = Callable[[str, "Job"], None]


class Cancelled(Exception):
    """O trabalho foi cancelado (levantada por `Job.check_cancel()`; downloads usam uma subclasse)."""


_ids = itertools.count(1)


class Job:
    """Um trabalho da fila. Os campos são lidos pela interface; só a fila e a função do trabalho escrevem."""

    def __init__(self, fn: Callable[["Job"], Any], title: str, kind: str = CPU, key: str = "", data: Any = None):
        if kind not in KINDS:
            raise ValueError(f"tipo de trabalho desconhecido: {kind!r} (use {', '.join(KINDS)})")
        self.id = next(_ids)
        self.fn = fn
        self.title = title
        self.kind = kind
        self.key = key            # identificador livre para a interface achar o trabalho ("componente:ffmpeg")
        self.data = data          # o que quem pediu quiser guardar junto
        self.state = ESPERANDO
        self.stage = ""
        self.done = 0
        self.total = 0
        self.result: Any = None
        self.error = ""
        self.exception: BaseException | None = None
        self.cancel_event = threading.Event()
        self.created = time.monotonic()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._settled = threading.Event()
        self._queue: JobQueue | None = None

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.kind} {self.state} {self.title!r}>"

    # ------------------------------------------------------------ estado
    @property
    def cancelled(self) -> bool:
        """Se pediram para cancelar (a função confere de tempos em tempos)."""
        return self.cancel_event.is_set()

    @property
    def active(self) -> bool:
        return self.state in (ESPERANDO, RODANDO)

    @property
    def finished(self) -> bool:
        return self.state in FINAL_STATES

    @property
    def progress(self) -> float | None:
        """Fração de 0 a 1, ou None quando não dá para saber (total 0)."""
        if self.total <= 0:
            return None
        return max(0.0, min(1.0, self.done / self.total))

    # ------------------------------------------------------------ usado pela função do trabalho
    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def report(self, stage: str | None = None, done: int = 0, total: int = 0) -> None:
        """Etapa (texto para o usuário) e progresso; total 0 = sem porcentagem."""
        if stage is not None:
            self.stage = stage
        self.done, self.total = int(done), int(total)
        q = self._queue
        if q is not None:
            q._emit(PROGRESS, self)

    def progress_callback(self) -> Callable[..., None]:
        """Adaptador para funções que recebem `progress(etapa, feito, total)` (deps e tools)."""
        return lambda stage=None, done=0, total=0: self.report(stage, done, total)

    # ------------------------------------------------------------ usado por quem pediu
    def cancel(self) -> None:
        if self._queue is not None:
            self._queue.cancel(self)
        else:
            self.cancel_event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Espera o trabalho terminar (e os ouvintes serem avisados). True se terminou."""
        return self._settled.wait(timeout)


class JobQueue:
    """Fila de trabalhos com limite de simultâneos por tipo (GPU sempre 1). Segura para várias threads."""

    def __init__(self, limits: dict[str, int] | None = None):
        self.limits = dict(DEFAULT_LIMITS)
        if limits:
            for kind, n in limits.items():
                if kind not in KINDS:
                    raise ValueError(f"tipo de trabalho desconhecido: {kind!r}")
                self.limits[kind] = max(1, int(n))
        self.limits[GPU] = 1
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._pending: list[Job] = []
        self._running: list[Job] = []
        self._history: list[Job] = []
        self._unsettled: set[int] = set()
        self._listeners: list[Listener] = []
        self._closed = False

    # ------------------------------------------------------------ ouvintes
    def add_listener(self, fn: Listener) -> None:
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _emit(self, event: str, job: Job) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event, job)
            except Exception:  # noqa: BLE001 — um ouvinte com defeito não pode travar a fila
                if sys.stderr is not None:
                    traceback.print_exc()

    # ------------------------------------------------------------ pedir e cancelar
    def submit(self, fn: Callable[[Job], Any] | Job, title: str = "", kind: str = CPU, key: str = "",
               data: Any = None) -> Job:
        """Põe um trabalho na fila (uma função que recebe o job, ou um `Job` pronto) e devolve o job."""
        job = fn if isinstance(fn, Job) else Job(fn, title, kind, key, data)
        with self._lock:
            if self._closed:
                raise RuntimeError("a fila de tarefas foi encerrada")
            if job._queue is not None:
                raise ValueError("este trabalho já foi enviado para uma fila")
            job._queue = self
            self._pending.append(job)
            self._unsettled.add(job.id)
        self._emit(ADDED, job)
        self._schedule()
        return job

    def cancel(self, job: Job) -> None:
        """Cancela: na espera, sai da fila na hora; rodando, a função para quando conferir."""
        job.cancel_event.set()
        with self._lock:
            waiting = job in self._pending
            if waiting:
                self._pending.remove(job)
        if waiting:
            self._finish(job, CANCELADO)

    def cancel_all(self, kind: str | None = None) -> None:
        for job in self.active():
            if kind is None or job.kind == kind:
                self.cancel(job)

    # ------------------------------------------------------------ consultas
    def jobs(self) -> list[Job]:
        """Rodando, na espera e os últimos terminados (cópia)."""
        with self._lock:
            return list(self._running) + list(self._pending) + list(self._history)

    def active(self, key: str | None = None) -> list[Job]:
        """Trabalhos rodando ou na espera (de uma chave, se dada)."""
        with self._lock:
            out = list(self._running) + list(self._pending)
        return [j for j in out if key is None or j.key == key]

    def find(self, key: str) -> Job | None:
        """O trabalho ativo mais recente com esta chave."""
        found = self.active(key)
        return max(found, key=lambda j: j.id) if found else None

    def running(self, kind: str | None = None) -> int:
        with self._lock:
            return sum(1 for j in self._running if kind is None or j.kind == kind)

    def wait_all(self, timeout: float | None = None) -> bool:
        """Espera todos os trabalhos terminarem (e os ouvintes serem avisados). True se terminaram."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._changed:
            while self._unsettled:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._changed.wait(left)
        return True

    def shutdown(self, cancel: bool = True, timeout: float | None = 2.0) -> bool:
        """Não aceita trabalhos novos; cancela os que existem (se `cancel`) e espera até `timeout`."""
        with self._lock:
            self._closed = True
        if cancel:
            self.cancel_all()
        return self.wait_all(timeout)

    # ------------------------------------------------------------ execução
    def _limit(self, kind: str) -> int:
        return 1 if kind == GPU else self.limits.get(kind, 1)

    def _schedule(self) -> None:
        start: list[Job] = []
        with self._lock:
            if self._closed and not self._pending:
                return
            counts = {k: 0 for k in KINDS}
            for j in self._running:
                counts[j.kind] += 1
            for job in list(self._pending):
                if counts[job.kind] < self._limit(job.kind):
                    self._pending.remove(job)
                    job.state = RODANDO
                    job.started_at = time.monotonic()
                    self._running.append(job)
                    counts[job.kind] += 1
                    start.append(job)
        for job in start:
            self._emit(STARTED, job)
            threading.Thread(target=self._run, args=(job,), daemon=True, name=f"tarefa-{job.id}-{job.kind}").start()

    def _run(self, job: Job) -> None:
        state, result, error, exc = CONCLUIDO, None, "", None
        try:
            job.check_cancel()
            result = job.fn(job)
        except Cancelled:
            state = CANCELADO
        except BaseException as e:  # noqa: BLE001 — o erro vira estado do trabalho
            if job.cancel_event.is_set():
                state = CANCELADO
            else:
                state, error, exc = ERRO, (str(e) or e.__class__.__name__), e
        self._finish(job, state, result, error, exc)

    def _finish(self, job: Job, state: str, result: Any = None, error: str = "",
                exc: BaseException | None = None) -> None:
        with self._lock:
            if job.finished:
                return
            if job in self._running:
                self._running.remove(job)
            if job in self._pending:
                self._pending.remove(job)
            job.state, job.result, job.error, job.exception = state, result, error, exc
            job.finished_at = time.monotonic()
            self._history.append(job)
            del self._history[:-HISTORY]
        self._emit(FINISHED, job)
        with self._changed:
            self._unsettled.discard(job.id)
            job._settled.set()
            self._changed.notify_all()
        self._schedule()


_shared: JobQueue | None = None
_shared_lock = threading.Lock()


def shared() -> JobQueue:
    """A fila do app inteiro (criada na primeira chamada)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = JobQueue()
            atexit.register(_shutdown_shared)
        return _shared


def _shutdown_shared() -> None:
    q = _shared
    if q is not None:
        q.shutdown(cancel=True, timeout=2.0)
