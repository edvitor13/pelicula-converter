"""Recuperação depois de um travamento (sem Qt): sessão, cópias automáticas, fila guardada e a detecção.

Tudo numa pasta temporária (`root=`), e a pasta do app (`LOCALAPPDATA`/`XDG_DATA_HOME`) também aponta
para uma pasta temporária: nada toca a pasta real do usuário. O travamento é simulado de verdade num
subprocesso (`os._exit(1)` e uma falha de memória com `faulthandler`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from pelicula import APP_NAME, __version__, crashlog, export, project, recovery, system, timeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _app_data(monkeypatch, tmp_path):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    return local


class Settings(dict):
    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, value):
        self[key] = value


def dead(_pid):
    return False, None


def alive_since(t):
    return lambda _pid: (True, t)


def sequence_json(tmp_path) -> dict:
    a = tmp_path / "a.mp4"
    a.write_bytes(b"x")
    src = timeline.Source(path=str(a), width=320, height=180, frames=48, duration=2.0)
    return timeline.Sequence.for_source(src).to_json()


def project_json(tmp_path, with_seq=True) -> dict:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"x")
    p = project.Project(media_path=str(media), frame=12, in_point=2, out_point=30, mode="edicao" if with_seq else "pelicula",
                        sequence=sequence_json(tmp_path) if with_seq else None)
    p.values["grao_forca"] = 1.25
    return p.to_json()


# ------------------------------------------------------------------ pasta e preferências
def test_recovery_dir_follows_the_app_data_dir(_app_data):
    assert recovery.recovery_dir() == _app_data / APP_NAME / "recuperacao"
    assert crashlog.logs_dir() == _app_data / APP_NAME / "logs"


def test_interval_and_versions_preferences():
    assert recovery.interval_minutes(Settings()) == 1 and recovery.versions(Settings()) == 5
    assert recovery.interval_minutes(None) == 1 and recovery.versions(None) == 5
    s = Settings({recovery.KEY_INTERVAL: "5", recovery.KEY_VERSIONS: "12"})
    assert recovery.interval_minutes(s) == 5 and recovery.versions(s) == 12
    s = Settings({recovery.KEY_INTERVAL: "7", recovery.KEY_VERSIONS: "999"})
    assert recovery.interval_minutes(s) == 1 and recovery.versions(s) == recovery.MAX_VERSIONS
    s = Settings({recovery.KEY_INTERVAL: "abc", recovery.KEY_VERSIONS: "0"})
    assert recovery.interval_minutes(s) == 1 and recovery.versions(s) == 1


def test_session_ids_are_unique_and_without_dashes():
    ids = {recovery.new_session_id() for _i in range(50)}
    assert len(ids) == 50 and all("-" not in i and i.isalnum() for i in ids)


# ------------------------------------------------------------------ sessão
def test_session_marker_and_clean_close(tmp_path):
    s = recovery.Session(tmp_path).start()
    data = json.loads(s.marker.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid() and data["sessao"] == s.id and data["versao_app"] == __version__
    assert abs(data["inicio"] - time.time()) < 60 and data["vivo_em"] >= data["inicio"]
    s.autosave(recovery.make_payload(project_json(tmp_path), "", {}, "x", s.id))
    s.save_queue([{"id": "1"}])
    assert s.folder.is_dir()
    s.close()
    assert not s.marker.exists() and not s.folder.exists()
    assert recovery.scan(tmp_path, probe=dead) == []


def test_autosave_keeps_the_newest_versions(tmp_path):
    s = recovery.Session(tmp_path).start()
    for i in range(7):
        s.autosave(recovery.make_payload({"app": APP_NAME, "n": i}, "", {}, "", s.id), keep=3)
    names = [p.name for p in s.copies()]
    assert names == ["copia-000007.json", "copia-000006.json", "copia-000005.json"]
    assert [json.loads(p.read_text(encoding="utf-8"))["projeto"]["n"] for p in s.copies()] == [6, 5, 4]
    assert not any(system.PARTIAL in p.name for p in s.folder.iterdir())  # gravado de uma vez
    assert s.clear_copies() == 3 and s.copies() == []


def test_copy_round_trip_restores_project_and_ui_state(tmp_path):
    s = recovery.Session(tmp_path).start()
    plc = str(tmp_path / "meu.plc")
    ui = {"modo": "edicao", "quadro": 12, "selecao": ["c1"], "linha_zoom": 3.5, "linha_rolagem": 40.0}
    path = s.autosave(recovery.make_payload(project_json(tmp_path), plc, ui, "meu", s.id))
    data = recovery.read_copy(path)
    assert data["projeto_original"] == plc and data["versao_app"] == __version__ and data["sessao"] == s.id
    p, original, ui2 = recovery.project_from_copy(data)
    assert original == plc and ui2 == ui
    assert p.path == "" and p.frame == 12 and (p.in_point, p.out_point) == (2, 30) and p.mode == "edicao"
    assert p.values["grao_forca"] == 1.25
    assert os.path.isabs(p.media_path) and p.sequence["fontes"][0]["caminho"].endswith("a.mp4")


@pytest.mark.parametrize("content", ["", "{quebrado", json.dumps({"app": "Outro"}),
                                     json.dumps({"app": APP_NAME, "tipo": "recuperacao", "formato": 99,
                                                 "projeto": {}})])
def test_invalid_copies_are_ignored(tmp_path, content):
    f = tmp_path / "copia-000001.json"
    f.write_text(content, encoding="utf-8")
    assert recovery.read_copy(f) is None


def test_queue_file(tmp_path):
    s = recovery.Session(tmp_path).start()
    s.save_queue([{"id": "a", "status": "aguardando"}, "lixo"])
    assert recovery.read_queue(s.folder) == [{"id": "a", "status": "aguardando"}]
    s.save_queue([])
    assert not (s.folder / recovery.QUEUE_FILE).exists() and recovery.read_queue(s.folder) == []


# ------------------------------------------------------------------ processos
def test_this_process_is_alive_and_a_finished_one_is_not():
    exists, start = recovery.process_info(os.getpid())
    assert exists
    if start is not None:
        assert start <= time.time() + 1
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert recovery.process_info(proc.pid)[0] is False
    assert recovery.process_info(0) == (False, None) and recovery.process_info(-5) == (False, None)


def test_pid_alive_rules():
    t0 = 1_000_000.0
    assert recovery.pid_alive(10, t0, probe=alive_since(t0 - 3))           # a mesma janela, ainda aberta
    assert recovery.pid_alive(10, t0, probe=alive_since(t0 + 5))           # dentro da tolerância
    assert not recovery.pid_alive(10, t0, probe=alive_since(t0 + 3600))    # pid reaproveitado por outro programa
    assert not recovery.pid_alive(10, t0, probe=dead)
    unknown = alive_since(None)  # sem saber quando o processo começou: vale o sinal de vida
    assert recovery.pid_alive(10, t0, beat=t0, now=t0 + 3600, probe=unknown)
    assert not recovery.pid_alive(10, t0, beat=t0, now=t0 + recovery.STALE_BEAT + 1, probe=unknown)


# ------------------------------------------------------------------ depois de um travamento
def write_marker(root: Path, sid: str, pid: int = 4242, started: float = 1000.0, beat: float | None = None):
    m = root / recovery.SESSIONS / f"{sid}.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"app": APP_NAME, "sessao": sid, "pid": pid, "inicio": started, "versao_app": "1.3.0",
                             "vivo_em": beat or started}), encoding="utf-8")
    return m


def test_scan_finds_crashed_sessions_and_skips_live_ones(tmp_path):
    root = tmp_path / "rec"
    logs = tmp_path / "logs"
    crashed = recovery.Session(root, "20260101000000aaaa0001")
    crashed.autosave(recovery.make_payload(project_json(tmp_path), "", {}, "x", crashed.id))
    crashed.save_queue([{"id": "j1", "status": "exportando"}])
    write_marker(root, crashed.id, pid=111, started=2000.0)
    write_marker(root, "20260101000000bbbb0002", pid=222, started=1000.0)  # outra janela aberta
    write_marker(root, "atual", pid=os.getpid())
    logs.mkdir()
    (logs / f"falha-{crashed.id}.log").write_text("Fatal Python error: Segmentation fault", encoding="utf-8")

    def probe(pid):
        return (True, 999.0) if pid == 222 else (True, 5.0) if pid == os.getpid() else (False, None)

    found = recovery.scan(root, current="atual", logs=logs, probe=probe)
    assert [c.session for c in found] == [crashed.id]
    c = found[0]
    assert c.pid == 111 and c.version == "1.3.0" and c.has_content
    assert len(c.copies) == 1 and c.queue == [{"id": "j1", "status": "exportando"}]
    assert "Segmentation fault" in c.report
    assert c.latest()["tipo"] == "recuperacao"
    assert recovery.live_sessions(root, probe=probe) == {"20260101000000bbbb0002", "atual"}
    recovery.forget(c)
    assert not c.folder.exists() and not c.marker.exists()
    assert recovery.scan(root, current="atual", logs=logs, probe=probe) == []


def test_latest_skips_a_broken_newest_copy(tmp_path):
    s = recovery.Session(tmp_path)
    s.autosave(recovery.make_payload({"app": APP_NAME, "n": 1}, "", {}, "", s.id))
    newest = s.autosave(recovery.make_payload({"app": APP_NAME, "n": 2}, "", {}, "", s.id))
    newest.write_text("{quebrado", encoding="utf-8")
    write_marker(tmp_path, s.id, pid=1)
    c = recovery.scan(tmp_path, probe=dead)[0]
    assert c.latest()["projeto"]["n"] == 1


def test_crash_without_content_and_unreadable_marker(tmp_path):
    (tmp_path / recovery.SESSIONS).mkdir(parents=True)
    (tmp_path / recovery.SESSIONS / "vazio.json").write_text("", encoding="utf-8")
    found = recovery.scan(tmp_path, probe=dead)
    assert [c.session for c in found] == ["vazio"] and not found[0].has_content and found[0].latest() is None


def test_old_orphan_folders_are_removed(tmp_path):
    old = tmp_path / "sem_marcador"
    old.mkdir()
    (old / "copia-000001.json").write_text("{}", encoding="utf-8")
    recovery.scan(tmp_path, probe=dead, now=time.time() + 10)
    assert old.exists()
    recovery.scan(tmp_path, probe=dead, now=time.time() + recovery.ORPHAN_AGE + 10)
    assert not old.exists()


def test_delete_copies_keeps_other_open_windows(tmp_path):
    me = recovery.Session(tmp_path, "eu").start()
    other = recovery.Session(tmp_path, "outra")
    gone = recovery.Session(tmp_path, "travou")
    for s in (me, other, gone):
        s.autosave(recovery.make_payload({"app": APP_NAME}, "", {}, "", s.id))
    write_marker(tmp_path, "outra", pid=222, started=1000.0)
    write_marker(tmp_path, "travou", pid=333)
    assert recovery.usage(tmp_path)[0] == 3 and recovery.usage(tmp_path)[1] > 0

    def probe(pid):
        return (True, 10.0) if pid in (222, os.getpid()) else (False, None)

    assert recovery.delete_copies(tmp_path, current="eu", probe=probe) == 2
    assert me.copies() == [] and len(other.copies()) == 1 and not gone.folder.exists()
    assert me.marker.exists()  # a sessão desta janela continua


# ------------------------------------------------------------------ projeto e fila
def test_project_from_json_without_a_file_keeps_absolute_paths(tmp_path):
    data = project_json(tmp_path)
    data["midia"]["relativo"] = "outra/video.mp4"
    p = project.from_json(data)
    assert p.path == "" and p.name == "" and p.media_path == data["midia"]["caminho"]
    with pytest.raises(project.ProjectError):
        project.from_json({"app": "Outro"})
    plc = tmp_path / "p.plc"
    plc.write_text(json.dumps(data), encoding="utf-8")
    q = project.load(str(plc))
    assert q.path == str(plc.resolve()) and q.name == "p"


def test_export_job_round_trip(tmp_path, make_info):
    seq = timeline.Sequence.from_json(sequence_json(tmp_path))
    s = export.ExportSettings(codec="x265", quality=20, resolution="1080")
    job = export.ExportJob(info=make_info(path=str(tmp_path / "a.mp4")), values={"grao_forca": 1.5}, settings=s,
                           out_path=str(tmp_path / "saida.mp4"), start_frame=3, end_frame=40, name="Corte",
                           sequence=seq, chapters=[(0, "Abertura"), (240, "Cena 2")])
    job.status = "exportando"
    d = json.loads(json.dumps(job.to_dict()))  # vai para um arquivo JSON
    assert d["status"] == "exportando" and d["config"]["codec"] == "x265"
    new = export.ExportJob.from_dict(d)
    assert new.status == "aguardando" and new.id != job.id and new.done == 0  # recomeça do início
    assert new.info == job.info and new.settings == s and new.out_path == job.out_path
    assert (new.start_frame, new.end_frame, new.name) == (3, 40, "Corte")
    assert new.values["grao_forca"] == 1.5
    assert new.sequence.to_json() == seq.to_json()
    assert new.chapters == [(0, "Abertura"), (240, "Cena 2")]  # um trabalho recuperado não perde os capítulos
    simple = export.ExportJob.from_dict({k: v for k, v in d.items() if k != "capitulos"} | {"edicao": None})
    assert simple.sequence is None and simple.chapters == []  # fila guardada antes dos capítulos
    for broken in ({}, {**d, "midia": {"path": "x"}}, {**d, "saida": ""}, "lixo"):
        with pytest.raises(ValueError):
            export.ExportJob.from_dict(broken)


# ------------------------------------------------------------------ travamento de verdade (subprocesso)
CRASH = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from pelicula import crashlog, recovery
    root, logs, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    s = recovery.Session(root).start()
    crash = crashlog.CrashLog(logs, s.id).install()
    payload = recovery.make_payload({"app": "PeliculaConverter", "formato": 1, "nome": "travou"},
                                    "C:/projetos/a.plc", {"modo": "pelicula", "quadro": 7}, "a", s.id)
    s.autosave(payload)
    s.save_queue([{"id": "j1", "status": "exportando", "saida": "C:/x.mp4"}])
    print(s.id, flush=True)
    if mode == "segfault":
        import faulthandler
        faulthandler._sigsegv()
    os._exit(1)
""")


def run_crash(tmp_path, mode):
    root, logs = tmp_path / "rec", tmp_path / "logs"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONFAULTHANDLER="")
    proc = subprocess.run([sys.executable, "-c", CRASH, str(root), str(logs), mode], cwd=str(ROOT), env=env,
                          capture_output=True, timeout=120)
    assert proc.returncode != 0
    sid = proc.stdout.decode().strip().splitlines()[0]
    return root, logs, sid


def test_crash_simulation_finds_the_autosave(tmp_path):
    root, logs, sid = run_crash(tmp_path, "exit")
    found = recovery.scan(root, current=recovery.new_session_id(), logs=logs)
    assert [c.session for c in found] == [sid]
    c = found[0]
    data = c.latest()
    assert data["projeto"]["nome"] == "travou" and data["projeto_original"] == "C:/projetos/a.plc"
    assert data["interface"] == {"modo": "pelicula", "quadro": 7}
    assert c.queue[0]["id"] == "j1"
    assert c.report == ""  # os._exit não é falha de memória: o falha-*.log ficou vazio
    crashlog.prune(logs, recovery.live_sessions(root))
    assert not (logs / f"falha-{sid}.log").exists()  # vazio, de sessão que acabou: sai


def test_crash_simulation_keeps_the_fault_report(tmp_path):
    root, logs, sid = run_crash(tmp_path, "segfault")
    c = recovery.scan(root, logs=logs)[0]
    assert c.session == sid and c.latest() is not None
    assert "fatal" in c.report.lower() and "falha-" in c.report
    path, text = crashlog.last_report(logs)
    assert path.name == f"falha-{sid}.log" and "fatal" in text.lower()
