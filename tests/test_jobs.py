"""Fila de tarefas em segundo plano (pelicula/jobs.py): ordem, limites por tipo, cancelamento, erros e threads."""

from __future__ import annotations

import threading
import time

import pytest

from pelicula import deps, jobs

WAIT = 10.0


class Recorder:
    """Ouvinte que guarda (evento, id, estado) com uma trava (os eventos chegam de várias threads)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[tuple[str, int, str]] = []

    def __call__(self, event, job):
        with self.lock:
            self.events.append((event, job.id, job.state))

    def of(self, job) -> list[str]:
        with self.lock:
            return [e for e, jid, _s in self.events if jid == job.id]


@pytest.fixture
def queue():
    q = jobs.JobQueue()
    yield q
    q.shutdown(cancel=True, timeout=WAIT)


def test_result_progress_and_event_order(queue):
    rec = Recorder()
    queue.add_listener(rec)

    def work(job):
        for i in range(3):
            job.report("passo", i + 1, 3)
        return "pronto"

    job = queue.submit(work, "Trabalho", kind=jobs.CPU, key="k:1", data={"x": 1})
    assert job.wait(WAIT)
    assert job.state == jobs.CONCLUIDO and job.result == "pronto" and job.error == ""
    assert job.stage == "passo" and job.progress == 1.0 and job.finished and not job.active
    assert job.data == {"x": 1} and job.key == "k:1"
    assert rec.of(job) == [jobs.ADDED, jobs.STARTED, jobs.PROGRESS, jobs.PROGRESS, jobs.PROGRESS, jobs.FINISHED]
    assert job.started_at is not None and job.finished_at >= job.started_at
    assert job in queue.jobs() and queue.active() == []


def test_progress_without_total_is_indeterminate():
    job = jobs.Job(lambda j: None, "x")
    assert job.progress is None
    job.report("baixando", 5, 0)
    assert job.progress is None and job.stage == "baixando"
    job.report(None, 15, 10)
    assert job.progress == 1.0 and job.stage == "baixando"  # etapa mantida, fração limitada a 1
    cb = job.progress_callback()
    cb("outra", 1, 4)
    assert job.stage == "outra" and job.progress == 0.25


def test_error_is_reported_and_queue_keeps_going(queue):
    def bad(job):
        raise ValueError("deu ruim")

    j1 = queue.submit(bad, "Falha")
    j2 = queue.submit(lambda job: 42, "Depois")
    assert j1.wait(WAIT) and j2.wait(WAIT)
    assert j1.state == jobs.ERRO and j1.error == "deu ruim" and isinstance(j1.exception, ValueError)
    assert j2.state == jobs.CONCLUIDO and j2.result == 42


def test_error_without_message_uses_the_exception_name(queue):
    def bad(job):
        raise KeyError

    job = queue.submit(bad, "x")
    assert job.wait(WAIT) and job.state == jobs.ERRO and job.error == "KeyError"


def test_cancel_running_job_is_cooperative(queue):
    started = threading.Event()

    def long(job):
        started.set()
        while True:
            job.check_cancel()
            time.sleep(0.005)

    job = queue.submit(long, "Longo")
    assert started.wait(WAIT)
    assert job.state == jobs.RODANDO and job.active
    job.cancel()
    assert job.wait(WAIT)
    assert job.state == jobs.CANCELADO and job.cancelled and job.error == ""


def test_cancel_waiting_job_never_runs(queue):
    gate = threading.Event()
    ran = []
    rec = Recorder()
    queue.add_listener(rec)
    blocker = queue.submit(lambda job: gate.wait(WAIT), "GPU 1", kind=jobs.GPU)
    waiting = queue.submit(lambda job: ran.append(1), "GPU 2", kind=jobs.GPU)
    assert waiting.state == jobs.ESPERANDO
    queue.cancel(waiting)
    assert waiting.wait(WAIT) and waiting.state == jobs.CANCELADO
    assert rec.of(waiting) == [jobs.ADDED, jobs.FINISHED]  # nunca começou
    gate.set()
    assert blocker.wait(WAIT) and blocker.state == jobs.CONCLUIDO
    assert queue.wait_all(WAIT)
    assert ran == []


def test_exception_after_cancel_counts_as_cancelled(queue):
    """Downloads levantam o próprio erro (deps.DownloadCancelled ou outro) quando cancelados."""
    started = threading.Event()

    def download(job):
        started.set()
        job.cancel_event.wait(WAIT)
        raise OSError("conexão interrompida")

    job = queue.submit(download, "Baixar", kind=jobs.REDE)
    assert started.wait(WAIT)
    job.cancel()
    assert job.wait(WAIT) and job.state == jobs.CANCELADO

    def cancelled_download(job):
        raise deps.DownloadCancelled()

    job2 = queue.submit(cancelled_download, "Baixar")
    assert job2.wait(WAIT) and job2.state == jobs.CANCELADO  # DownloadCancelled é um jobs.Cancelled
    assert issubclass(deps.DownloadCancelled, jobs.Cancelled)


def test_only_one_gpu_job_at_a_time_and_other_kinds_run_alongside():
    q = jobs.JobQueue(limits={jobs.GPU: 4, jobs.CPU: 3})
    assert q.limits[jobs.GPU] == 1  # GPU é sempre 1, mesmo pedindo mais
    lock = threading.Lock()
    running = {jobs.GPU: 0, jobs.CPU: 0}
    peak = {jobs.GPU: 0, jobs.CPU: 0}
    cpu_gate = threading.Event()

    def work(kind):
        def fn(job):
            with lock:
                running[kind] += 1
                peak[kind] = max(peak[kind], running[kind])
            try:
                if kind == jobs.CPU:
                    cpu_gate.wait(WAIT)
                else:
                    time.sleep(0.03)
            finally:
                with lock:
                    running[kind] -= 1
        return fn

    gpu_jobs = [q.submit(work(jobs.GPU), f"gpu {i}", kind=jobs.GPU) for i in range(4)]
    cpu_jobs = [q.submit(work(jobs.CPU), f"cpu {i}", kind=jobs.CPU) for i in range(3)]
    # As de CPU começam juntas mesmo com a fila de GPU cheia.
    deadline = time.monotonic() + WAIT
    while q.running(jobs.CPU) < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert q.running(jobs.CPU) == 3
    assert q.running(jobs.GPU) <= 1
    cpu_gate.set()
    assert q.wait_all(WAIT)
    assert peak[jobs.GPU] == 1 and peak[jobs.CPU] == 3
    assert all(j.state == jobs.CONCLUIDO for j in gpu_jobs + cpu_jobs)
    # Ordem de chegada dentro do tipo.
    starts = [j.started_at for j in gpu_jobs]
    assert starts == sorted(starts)
    q.shutdown()


def test_limits_reject_unknown_kinds():
    with pytest.raises(ValueError):
        jobs.JobQueue(limits={"disco": 1})
    with pytest.raises(ValueError):
        jobs.Job(lambda j: None, "x", kind="disco")


def test_submit_from_many_threads_is_safe():
    q = jobs.JobQueue(limits={jobs.CPU: 4, jobs.REDE: 4})
    rec = Recorder()
    q.add_listener(rec)
    total = 0
    total_lock = threading.Lock()
    created: list[jobs.Job] = []
    created_lock = threading.Lock()

    def add(n):
        def fn(job):
            nonlocal total
            job.report("x", 1, 2)
            with total_lock:
                total += n
            return n
        return fn

    def producer(base):
        for i in range(25):
            kind = (jobs.CPU, jobs.GPU, jobs.REDE)[(base + i) % 3]
            j = q.submit(add(1), f"t{base}-{i}", kind=kind)
            with created_lock:
                created.append(j)

    threads = [threading.Thread(target=producer, args=(b,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT)
    assert q.wait_all(WAIT * 3)
    assert len(created) == 200 and len({j.id for j in created}) == 200
    assert total == 200
    assert all(j.state == jobs.CONCLUIDO and j.result == 1 for j in created)
    finished = [e for e in rec.events if e[0] == jobs.FINISHED]
    assert len(finished) == 200 and len({jid for _e, jid, _s in finished}) == 200
    assert q.active() == [] and q.running() == 0
    q.shutdown()


def test_find_active_job_by_key(queue):
    gate = threading.Event()
    a = queue.submit(lambda job: gate.wait(WAIT), "a", kind=jobs.REDE, key="componente:x")
    b = queue.submit(lambda job: gate.wait(WAIT), "b", kind=jobs.REDE, key="componente:x")
    assert queue.find("componente:x") is b
    assert queue.find("componente:y") is None
    assert {j.id for j in queue.active("componente:x")} == {a.id, b.id}
    gate.set()
    assert queue.wait_all(WAIT)
    assert queue.find("componente:x") is None


def test_listener_errors_do_not_break_the_queue(queue, capsys):
    def broken(event, job):
        raise RuntimeError("ouvinte com defeito")

    rec = Recorder()
    queue.add_listener(broken)
    queue.add_listener(rec)
    job = queue.submit(lambda j: "ok", "x")
    assert job.wait(WAIT) and job.result == "ok"
    assert jobs.FINISHED in rec.of(job)
    queue.remove_listener(broken)
    queue.remove_listener(broken)  # remover duas vezes não é erro
    capsys.readouterr()


def test_wait_all_times_out_and_shutdown_cancels_everything():
    q = jobs.JobQueue()
    started = threading.Event()

    def long(job):
        started.set()
        while not job.cancelled:
            time.sleep(0.005)
        job.check_cancel()

    running = q.submit(long, "longo", kind=jobs.GPU)
    waiting = q.submit(long, "esperando", kind=jobs.GPU)
    assert started.wait(WAIT)
    assert not q.wait_all(0.05)
    assert q.shutdown(cancel=True, timeout=WAIT)
    assert running.state == jobs.CANCELADO and waiting.state == jobs.CANCELADO
    with pytest.raises(RuntimeError):
        q.submit(lambda j: None, "depois de fechar")


def test_job_cannot_be_submitted_twice(queue):
    job = jobs.Job(lambda j: 1, "x")
    queue.submit(job)
    with pytest.raises(ValueError):
        queue.submit(job)
    assert job.wait(WAIT)


def test_cancel_before_start_skips_the_function(queue):
    ran = []
    job = jobs.Job(lambda j: ran.append(1), "x")
    job.cancel()  # ainda fora da fila: só marca
    queue.submit(job)
    assert job.wait(WAIT) and job.state == jobs.CANCELADO and ran == []


def test_history_is_bounded():
    q = jobs.JobQueue()
    for i in range(jobs.HISTORY + 15):
        q.submit(lambda j: None, f"t{i}")
    assert q.wait_all(WAIT)
    assert len(q.jobs()) == jobs.HISTORY
    q.shutdown()


def test_shared_queue_is_a_singleton():
    assert jobs.shared() is jobs.shared()
    job = jobs.shared().submit(lambda j: "ok", "compartilhada")
    assert job.wait(WAIT) and job.result == "ok"
