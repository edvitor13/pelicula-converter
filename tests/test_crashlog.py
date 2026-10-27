"""Relatórios de erro e de travamento (`pelicula/crashlog.py`), numa pasta temporária.

O `faulthandler` de verdade só é ligado em subprocesso (`test_recovery.py`): aqui os ganchos são chamados
direto, sem trocar os do pytest.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from pelicula import APP_NAME, __version__, crashlog


def boom():
    raise ValueError("deu errado aqui")


def exc_info():
    try:
        boom()
    except ValueError:
        return sys.exc_info()


def test_report_is_readable():
    text = crashlog.format_report(*exc_info(), where="MainThread", gpu="NVIDIA GeForce RTX")
    assert text.startswith(f"{APP_NAME} — relatório de erro")
    for part in (f"{APP_NAME} {__version__}", "Sistema:", "Python:", "Qt", "GPU: NVIDIA GeForce RTX",
                 "Onde: MainThread", "Traceback", "ValueError: deu errado aqui", "boom"):
        assert part in text


def test_excepthook_writes_a_report_and_tells_the_interface(tmp_path):
    crash = crashlog.CrashLog(tmp_path, "sessao1")
    seen = []
    crash.on_report = lambda text, path, main: seen.append((text, path, main))
    crash._excepthook(*exc_info())
    assert crash.reports == 1 and len(seen) == 1
    text, path, main = seen[0]
    assert main is True and path.parent == tmp_path and path.name.startswith("erro-")
    assert path.name.endswith("-sessao1.txt") and path.read_text(encoding="utf-8") == text
    assert crashlog.report_for("sessao1", tmp_path) == text.strip()
    assert crashlog.report_for("outra", tmp_path) == ""


def test_thread_excepthook(tmp_path, monkeypatch):
    crash = crashlog.CrashLog(tmp_path, "s2")
    seen = []
    crash.on_report = lambda text, path, main: seen.append((text, main))
    monkeypatch.setattr(threading, "excepthook", crash._thread_excepthook)
    t = threading.Thread(target=boom, name="trabalho")
    t.start()
    t.join()
    assert len(seen) == 1 and seen[0][1] is False
    assert "Onde: thread trabalho" in seen[0][0] and "deu errado aqui" in seen[0][0]


def test_keyboard_interrupt_and_system_exit_are_not_reports(tmp_path):
    crash = crashlog.CrashLog(tmp_path, "s3")
    crash._old_hooks = (lambda *a: None, threading.excepthook)
    crash._excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    class Args:
        exc_type, exc_value, exc_traceback, thread = SystemExit, SystemExit(), None, None
    crash._thread_excepthook(Args)
    assert crash.reports == 0 and not list(tmp_path.iterdir())


def test_reports_are_bounded(tmp_path, monkeypatch):
    crash = crashlog.CrashLog(tmp_path, "s4")
    big = "x" * (crashlog.MAX_BYTES * 3)
    path = crash.write_report(big)
    assert path.stat().st_size <= crashlog.MAX_BYTES + 16
    monkeypatch.setattr(crashlog, "MAX_FILES", 5)
    for i in range(9):
        crash.write_report(f"relatório {i}")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 5
    newest = crashlog.last_report(tmp_path)
    assert newest[1] == "relatório 8"


def test_prune_handles_fault_files_by_session(tmp_path):
    (tmp_path / "falha-viva.log").write_text("", encoding="utf-8")
    (tmp_path / "falha-acabou.log").write_text("", encoding="utf-8")
    (tmp_path / "falha-travou.log").write_text("Fatal Python error", encoding="utf-8")
    crashlog.prune(tmp_path, None)  # sem saber quem está aberto: nenhum falha-*.log é tocado
    assert len(list(tmp_path.iterdir())) == 3
    crashlog.prune(tmp_path, {"viva"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["falha-travou.log", "falha-viva.log"]
    assert crashlog.last_report(tmp_path, exclude={"travou"}) is None
    assert crashlog.last_report(tmp_path)[0].name == "falha-travou.log"
    report = crashlog.report_for("travou", tmp_path)
    assert "travamento (faulthandler)" in report and "Fatal Python error" in report


def test_install_and_close_in_a_subprocess(tmp_path):
    """install() liga o faulthandler num arquivo da sessão; close() limpa tudo num fechamento normal."""
    import subprocess
    code = ("import sys, faulthandler, threading\n"
            "from pathlib import Path\n"
            "from pelicula import crashlog\n"
            "c = crashlog.CrashLog(Path(sys.argv[1]), 'abc').install()\n"
            "assert faulthandler.is_enabled() and c.fault_file.exists()\n"
            "assert sys.excepthook == c._excepthook and threading.excepthook == c._thread_excepthook\n"
            "c.close()\n"
            "assert not c.fault_file.exists() and sys.excepthook is sys.__excepthook__\n"
            "print('ok')\n")
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=str(root), capture_output=True,
                          timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert proc.stdout.decode().strip() == "ok", proc.stderr.decode("utf-8", "replace")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name,session", [("falha-abc.log", "abc"), ("erro-20261022-101010123-abc.txt", "abc"),
                                          ("outro.txt", "")])
def test_session_of_log_names(name, session):
    assert crashlog._session_of(name) == session
