"""Relatórios de erro e de travamento (sem Qt). Nada é enviado: tudo fica em `<pasta do app>/logs/`.

Duas fontes, um formato legível:

- **Travamento** (o processo morreu: falha de memória no driver de vídeo, `abort`...): o `faulthandler` do
  Python escreve as pilhas de todas as threads em `falha-<sessão>.log`. O arquivo é aberto ao iniciar e
  fica vazio enquanto nada acontece; num fechamento normal ele é apagado (`CrashLog.close`). Sobrou cheio
  depois de uma sessão que não fechou direito = relatório do travamento.
- **Erro sem tratamento** (uma exceção que escapou numa função da interface ou numa thread): `sys.excepthook`
  e `threading.excepthook` gravam `erro-<data>-<sessão>.txt` com o traceback, a versão do app, o sistema,
  o Python, o Qt e a placa de vídeo (quando já se sabe). O app continua aberto; a interface mostra um
  aviso pequeno (`ui/crash_dialog.py`) com "Copiar relatório" e "Abrir pasta".

Este registro fica ligado mesmo com o módulo `recuperacao` desligado: é diagnóstico, não muda nada no
trabalho da pessoa. A pasta tem tamanho limitado: no máximo `MAX_FILES` arquivos (os mais antigos saem)
e `MAX_BYTES` por relatório.
"""

from __future__ import annotations

import faulthandler
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__, deps, system

FAULT_PREFIX = "falha-"
REPORT_PREFIX = "erro-"
MAX_FILES = 20
MAX_BYTES = 256 * 1024
READ_LIMIT = 64 * 1024


def logs_dir() -> Path:
    return deps.app_data_dir() / "logs"


def fault_path(folder: Path, session_id: str) -> Path:
    return Path(folder) / f"{FAULT_PREFIX}{session_id}.log"


def _qt_version() -> str:
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        return f"Qt {qVersion()} • PySide6 {PySide6.__version__}"
    except Exception:  # noqa: BLE001
        return "Qt ?"


def environment(gpu: str = "") -> str:
    """Versão do app, sistema, Python, Qt e placa de vídeo (uma linha cada)."""
    frozen = " (executável)" if getattr(sys, "frozen", False) else ""
    lines = [f"{APP_NAME} {__version__}{frozen}",
             f"Sistema: {platform.platform()} ({platform.machine()})",
             f"Python: {platform.python_version()} ({sys.executable})",
             _qt_version()]
    if gpu:
        lines.append(f"GPU: {gpu}")
    return "\n".join(lines)


def format_report(exc_type, exc, tb, where: str = "", gpu: str = "") -> str:
    """Relatório de uma exceção: quando, onde, ambiente e traceback."""
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    head = f"{APP_NAME} — relatório de erro\nData: {when}\n"
    if where:
        head += f"Onde: {where}\n"
    body = "".join(traceback.format_exception(exc_type, exc, tb))
    return f"{head}{environment(gpu)}\n\n{body}"


def _read_tail(path: Path, limit: int = READ_LIMIT) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    return ("…\n" + text) if size > limit else text


def _session_of(name: str) -> str:
    """Sessão de um arquivo de log pelo nome (`falha-<sessão>.log`, `erro-<data>-<sessão>.txt`)."""
    stem = Path(name).stem
    if stem.startswith(FAULT_PREFIX):
        return stem[len(FAULT_PREFIX):]
    if stem.startswith(REPORT_PREFIX):
        return stem.rsplit("-", 1)[-1]
    return ""


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _log_files(folder: Path) -> list[Path]:
    """Relatórios e `falha-*.log` da pasta, do mais novo para o mais antigo."""
    try:
        items = [p for p in Path(folder).iterdir() if p.is_file() and p.name.startswith((FAULT_PREFIX, REPORT_PREFIX))]
    except OSError:
        return []
    return sorted(items, key=lambda p: (_mtime(p), p.name), reverse=True)


def prune(folder: Path, live_sessions: set[str] | frozenset[str] | None = None) -> None:
    """Mantém a pasta pequena: deixa só os `MAX_FILES` relatórios mais novos e apaga os `falha-*.log` vazios
    de sessões que já acabaram.

    `live_sessions`: sessões rodando agora (`recovery.live_sessions`). `None` = não se sabe: nenhum
    `falha-*.log` é tocado (o de outra janela aberta pode estar em uso), só o número de arquivos é limitado.
    """
    removable = []
    for p in _log_files(folder):
        if p.name.startswith(FAULT_PREFIX):
            if live_sessions is None or _session_of(p.name) in live_sessions:
                continue
            try:
                empty = p.stat().st_size == 0
            except OSError:
                continue
            if empty:
                system.remove_file(p)
                continue
        removable.append(p)
    for p in removable[MAX_FILES:]:
        system.remove_file(p)


def report_for(session_id: str, folder: Path | None = None) -> str:
    """Tudo o que ficou registrado de uma sessão: o travamento (`faulthandler`) e os erros, do mais antigo
    para o mais novo. "" se nada."""
    folder = Path(folder) if folder is not None else logs_dir()
    parts = []
    for p in reversed(_log_files(folder)):
        if _session_of(p.name) != session_id:
            continue
        text = _read_tail(p).strip()
        if not text:
            continue
        if p.name.startswith(FAULT_PREFIX):
            text = f"{APP_NAME} — travamento (faulthandler)\nArquivo: {p}\n\n{text}"
        parts.append(text)
    return ("\n\n" + "-" * 60 + "\n\n").join(parts)


def last_report(folder: Path | None = None, exclude: set[str] | frozenset[str] = frozenset()) -> tuple[Path, str] | None:
    """O relatório mais recente (erro ou travamento), ignorando os `falha-*.log` das sessões em `exclude` (as
    que estão rodando: o arquivo delas só tem algo se a sessão travar)."""
    folder = Path(folder) if folder is not None else logs_dir()
    for p in _log_files(folder):
        if p.name.startswith(FAULT_PREFIX) and _session_of(p.name) in exclude:
            continue
        text = _read_tail(p).strip()
        if text:
            return p, text
    return None


class CrashLog:
    """Liga o `faulthandler` e os ganchos de exceção de uma sessão.

    `on_report(texto, caminho, thread_principal)` é chamado depois de gravar um relatório de exceção (em
    qualquer thread: a interface leva o aviso para a thread principal). `gpu` pode ser preenchido depois
    (nome da placa de vídeo, quando o `Engine` existir).
    """

    def __init__(self, folder: Path | None, session_id: str):
        self.folder = Path(folder) if folder is not None else logs_dir()
        self.session_id = session_id
        self.gpu = ""
        self.on_report: Callable[[str, Path | None, bool], None] | None = None
        self.reports = 0
        self._fh = None
        self._old_hooks = None

    @property
    def fault_file(self) -> Path:
        return fault_path(self.folder, self.session_id)

    def install(self) -> "CrashLog":
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.fault_file, "w", encoding="utf-8")
            faulthandler.enable(file=self._fh, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            self._fh = None
        self._old_hooks = (sys.excepthook, threading.excepthook)
        sys.excepthook = self._excepthook
        threading.excepthook = self._thread_excepthook
        return self

    def uninstall(self) -> None:
        if self._old_hooks is not None:
            sys.excepthook, threading.excepthook = self._old_hooks
            self._old_hooks = None
        if self._fh is not None:
            try:
                faulthandler.disable()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def close(self, clean: bool = True) -> None:
        """Fim da sessão. Num fechamento normal o `falha-*.log` (vazio) sai."""
        self.uninstall()
        if clean:
            system.remove_file(self.fault_file)
        prune(self.folder)

    # ------------------------------------------------------------ ganchos
    def write_report(self, text: str) -> Path | None:
        """Grava um relatório (cortado em `MAX_BYTES`) e mantém a pasta pequena."""
        data = text.encode("utf-8", "replace")
        if len(data) > MAX_BYTES:
            data = data[: MAX_BYTES // 4] + b"\n...\n" + data[-(MAX_BYTES * 3 // 4):]
        now = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"{int(now * 1000) % 1000:03d}"
        path = self.folder / f"{REPORT_PREFIX}{stamp}-{self.session_id}.txt"
        n = 1
        while path.exists():  # dois erros no mesmo milésimo de segundo
            n += 1
            path = self.folder / f"{REPORT_PREFIX}{stamp}_{n}-{self.session_id}.txt"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with system.atomic_write(path, "wb") as fh:
                fh.write(data)
        except OSError:
            return None
        self.reports += 1
        prune(self.folder)
        return path

    def handle(self, exc_type, exc, tb, where: str = "", main_thread: bool = True) -> Path | None:
        text = format_report(exc_type, exc, tb, where, self.gpu)
        path = self.write_report(text)
        if self.on_report is not None:
            try:
                self.on_report(text, path, main_thread)
            except Exception:  # noqa: BLE001
                pass
        return path

    def _excepthook(self, exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            (self._old_hooks or (sys.__excepthook__,))[0](exc_type, exc, tb)
            return
        if sys.stderr is not None:
            try:
                traceback.print_exception(exc_type, exc, tb)
            except Exception:  # noqa: BLE001
                pass
        self.handle(exc_type, exc, tb, where=threading.current_thread().name,
                    main_thread=threading.current_thread() is threading.main_thread())

    def _thread_excepthook(self, args) -> None:
        if args.exc_type is SystemExit:
            return
        if sys.stderr is not None:
            try:
                traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
            except Exception:  # noqa: BLE001
                pass
        name = args.thread.name if args.thread is not None else "?"
        self.handle(args.exc_type, args.exc_value, args.exc_traceback, where=f"thread {name}", main_thread=False)
