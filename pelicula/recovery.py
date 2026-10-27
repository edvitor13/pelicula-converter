"""Recuperação depois de um travamento (sem Qt): marcador da sessão, cópias automáticas e fila guardada.

Tudo fica numa pasta do app — nunca no `.plc` da pessoa, que só muda quando ela salva:

    <pasta do app>/recuperacao/
        sessoes/<sessão>.json        marcador de cada janela aberta (pid, início, versão do app, sessão, "vivo_em")
        <sessão>/copia-000007.json   cópias automáticas do projeto (só as `versoes` mais novas ficam)
        <sessão>/fila.json           exportações esperando ou rodando, para refazer depois de um travamento

**Sessão.** Ao abrir, o app grava o marcador (`Session.start`); ao fechar normalmente, apaga o marcador e a
pasta da sessão (`Session.close`). Sobrou um marcador cujo processo não existe mais = a sessão travou (ou o
computador desligou). Outra janela do app ainda aberta **não** é travamento: o pid dela está vivo.

**Pid vivo** (`process_info`, sem dependências): no Windows `OpenProcess` + `GetExitCodeProcess` e a hora de
criação do processo (`GetProcessTimes`); no Linux `os.kill(pid, 0)` e a hora de início em `/proc/<pid>/stat`.
Cuidado com a reutilização de pid: o sistema pode dar o pid de um processo morto a outro programa. Por isso o
processo só conta como "a mesma sessão" se começou antes do marcador (`START_TOLERANCE`); quando não dá para
saber a hora de início (sem permissão, sem `/proc`), vale o pid e um marcador sem sinal de vida
(`vivo_em`, renovado pela janela) há mais de `STALE_BEAT` conta como abandonado. Um processo de outro
programa com o mesmo pid e sem hora de início conhecida pode esconder um travamento até lá — é o único caso.

**Cópia automática** (`Session.autosave`): JSON gravado de uma vez (`system.atomic_write`) com o projeto no
mesmo formato do `.plc` (`project.Project.to_json`, inclusive a montagem do modo Edição) com caminhos
absolutos, o caminho do `.plc` original ("" se nunca foi salvo) e o estado da tela (modo, quadro, seleção,
zoom da linha do tempo). A janela grava a cada minuto só quando há mudanças não salvas (`ui/recovery_ui.py`).

O módulo `recuperacao` desligado só para as cópias e a fila guardada; o marcador continua (é ele que diz
quais relatórios de travamento são de janelas abertas, `crashlog.prune`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME, __version__, crashlog, deps, system

DIR_NAME = "recuperacao"
SESSIONS = "sessoes"
QUEUE_FILE = "fila.json"
COPY_PREFIX = "copia-"
FORMAT = 1
_COPY_RE = re.compile(re.escape(COPY_PREFIX) + r"(\d+)\.json")

KEY_INTERVAL = "recuperacao/intervalo"  # minutos entre as cópias automáticas
KEY_VERSIONS = "recuperacao/versoes"    # quantas cópias ficam por sessão
INTERVALS = (1, 2, 5, 10, 15)
DEFAULT_INTERVAL = 1
DEFAULT_VERSIONS = 5
MAX_VERSIONS = 20

START_TOLERANCE = 10.0          # s: um processo que começou depois do marcador é outro programa
STALE_BEAT = 7 * 24 * 3600.0    # s sem sinal de vida (quando não se sabe a hora de início do processo)
ORPHAN_AGE = 30 * 24 * 3600.0   # s: pasta de sessão sem marcador é lixo depois disso
BEAT_INTERVAL = 5 * 60          # s entre os sinais de vida da janela


def recovery_dir() -> Path:
    return deps.app_data_dir() / DIR_NAME


def new_session_id() -> str:
    """Id da sessão: data e hora + 8 dígitos aleatórios (sem "-", que separa campos nos nomes dos logs)."""
    return time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:8]


def _int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def interval_minutes(settings) -> int:
    v = _int(settings.value(KEY_INTERVAL, DEFAULT_INTERVAL) if settings is not None else None, DEFAULT_INTERVAL)
    return v if v in INTERVALS else DEFAULT_INTERVAL


def versions(settings) -> int:
    v = _int(settings.value(KEY_VERSIONS, DEFAULT_VERSIONS) if settings is not None else None, DEFAULT_VERSIONS)
    return min(max(v, 1), MAX_VERSIONS)


# ------------------------------------------------------------------ processos
def _win_process(pid: int) -> tuple[bool, float | None]:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # Acesso negado: o processo existe (de outro usuário ou com administrador). Senão, não existe.
        return ctypes.get_last_error() == 5, None
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return False, None
        times = [wintypes.FILETIME() for _i in range(4)]
        if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return True, None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime  # 100 ns desde 1601
        return True, ticks / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(handle)


def _posix_process(pid: int) -> tuple[bool, float | None]:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        pass  # existe, de outro usuário
    except OSError:
        return False, None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        rest = stat[stat.rindex(")") + 2:].split()
        if rest[0] in ("Z", "X"):  # zumbi: já terminou, só falta o pai recolher
            return False, None
        btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                     if line.startswith("btime "))
        return True, btime + int(rest[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return True, None


def process_info(pid: int) -> tuple[bool, float | None]:
    """(existe, hora de início em segundos desde 1970 ou None se não dá para saber)."""
    if pid <= 0:
        return False, None
    try:
        if sys.platform == "win32":
            return _win_process(pid)
        return _posix_process(pid)
    except Exception:  # noqa: BLE001 — na dúvida, vivo (nunca tratar uma janela aberta como travada)
        return True, None


Probe = Callable[[int], tuple[bool, "float | None"]]


def pid_alive(pid: int, started: float | None = None, beat: float | None = None, now: float | None = None,
              probe: Probe | None = None) -> bool:
    """O processo `pid` ainda é a sessão que gravou o marcador (começou em `started`)?"""
    exists, start = (probe or process_info)(int(pid or 0))
    if not exists:
        return False
    if start is not None and started:
        return start <= float(started) + START_TOLERANCE
    now = time.time() if now is None else now
    if beat and now - float(beat) > STALE_BEAT:
        return False
    return True


# ------------------------------------------------------------------ arquivos
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with system.atomic_write(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def copies(folder: Path) -> list[Path]:
    """Cópias automáticas de uma pasta de sessão, da mais nova para a mais antiga."""
    try:
        found = [(int(m.group(1)), p) for p in Path(folder).iterdir()
                 if (m := _COPY_RE.fullmatch(p.name)) and p.is_file()]
    except OSError:
        return []
    return [p for _n, p in sorted(found, key=lambda x: x[0], reverse=True)]


def make_payload(project_json: dict, original: str = "", ui: dict | None = None, name: str = "",
                 session_id: str = "") -> dict:
    """Conteúdo de uma cópia automática."""
    return {"app": APP_NAME, "tipo": "recuperacao", "formato": FORMAT, "sessao": session_id,
            "salvo_em": time.time(), "versao_app": __version__, "projeto_original": original or "",
            "nome": name, "projeto": project_json, "interface": dict(ui or {})}


def read_copy(path: Path) -> dict | None:
    """Uma cópia automática válida, ou None (arquivo de outro programa, quebrado ou de formato novo demais)."""
    data = _read_json(path)
    if (not isinstance(data, dict) or data.get("app") != APP_NAME or data.get("tipo") != "recuperacao"
            or not isinstance(data.get("projeto"), dict) or _int(data.get("formato"), 0) > FORMAT):
        return None
    return data


def project_from_copy(data: dict):
    """(projeto, caminho do .plc original ou "", estado da tela) de uma cópia (`read_copy`).

    O projeto não tem `path`: quem restaura decide (o .plc original, se houver)."""
    from . import project
    p = project.from_json(data["projeto"], "")
    original = str(data.get("projeto_original") or "")
    ui = data.get("interface") if isinstance(data.get("interface"), dict) else {}
    return p, original, ui


def read_queue(folder: Path) -> list[dict]:
    data = _read_json(Path(folder) / QUEUE_FILE)
    if not isinstance(data, dict) or data.get("app") != APP_NAME:
        return []
    return [j for j in data.get("trabalhos") or [] if isinstance(j, dict)]


# ------------------------------------------------------------------ sessão
class Session:
    """A sessão desta janela: marcador, cópias automáticas e fila guardada."""

    def __init__(self, root: Path | None = None, session_id: str | None = None):
        self.root = Path(root) if root is not None else recovery_dir()
        self.id = session_id or new_session_id()
        self.pid = os.getpid()
        self.started = time.time()
        self.closed = False

    @property
    def marker(self) -> Path:
        return self.root / SESSIONS / f"{self.id}.json"

    @property
    def folder(self) -> Path:
        return self.root / self.id

    def _marker_data(self) -> dict:
        return {"app": APP_NAME, "sessao": self.id, "pid": self.pid, "inicio": self.started,
                "versao_app": __version__, "vivo_em": time.time(), "executavel": sys.executable}

    def start(self) -> "Session":
        try:
            _write_json(self.marker, self._marker_data())
        except OSError:
            pass
        return self

    def beat(self) -> None:
        """Sinal de vida (a janela chama de tempos em tempos)."""
        if not self.closed:
            try:
                _write_json(self.marker, self._marker_data())
            except OSError:
                pass

    def autosave(self, payload: dict, keep: int = DEFAULT_VERSIONS) -> Path:
        """Grava uma cópia nova e apaga as mais antigas (ficam `keep`)."""
        old = copies(self.folder)
        n = max((int(_COPY_RE.fullmatch(p.name).group(1)) for p in old), default=0) + 1
        path = self.folder / f"{COPY_PREFIX}{n:06d}.json"
        _write_json(path, payload)
        for p in copies(self.folder)[max(1, int(keep)):]:
            system.remove_file(p)
        return path

    def copies(self) -> list[Path]:
        return copies(self.folder)

    def save_queue(self, items: list[dict]) -> None:
        """Guarda as exportações esperando ou rodando (lista vazia apaga o arquivo)."""
        path = self.folder / QUEUE_FILE
        if not items:
            system.remove_file(path)
            return
        _write_json(path, {"app": APP_NAME, "tipo": "fila", "salvo_em": time.time(), "trabalhos": list(items)})

    def clear_copies(self) -> int:
        n = 0
        for p in copies(self.folder):
            system.remove_file(p)
            n += 1
        return n

    def close(self) -> None:
        """Fechamento normal: some tudo da sessão (as cópias só servem depois de um travamento)."""
        self.closed = True
        shutil.rmtree(self.folder, ignore_errors=True)
        system.remove_file(self.marker)


# ------------------------------------------------------------------ depois de um travamento
@dataclass
class Crashed:
    """Uma sessão que não fechou direito."""
    session: str
    pid: int = 0
    started: float = 0.0
    version: str = ""
    folder: Path = field(default_factory=Path)
    marker: Path | None = None
    copies: list[Path] = field(default_factory=list)
    queue: list[dict] = field(default_factory=list)
    report: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.copies or self.queue)

    def latest(self) -> dict | None:
        """A cópia mais nova que dá para ler (se a última está quebrada, a anterior)."""
        for p in self.copies:
            data = read_copy(p)
            if data is not None:
                return data
        return None


def _markers(root: Path) -> list[tuple[Path, dict]]:
    out = []
    try:
        items = sorted((Path(root) / SESSIONS).glob("*.json"))
    except OSError:
        return []
    for m in items:
        data = _read_json(m)
        out.append((m, data if isinstance(data, dict) else {}))
    return out


def _alive(data: dict, probe: Probe | None, now: float | None) -> bool:
    return pid_alive(_int(data.get("pid"), 0), data.get("inicio"), data.get("vivo_em"), now, probe)


def live_sessions(root: Path | None = None, probe: Probe | None = None, now: float | None = None) -> set[str]:
    """Sessões com a janela aberta agora (inclusive esta)."""
    root = Path(root) if root is not None else recovery_dir()
    return {str(d.get("sessao") or m.stem) for m, d in _markers(root) if _alive(d, probe, now)}


def scan(root: Path | None = None, current: str = "", logs: Path | None = None, probe: Probe | None = None,
         now: float | None = None) -> list[Crashed]:
    """Sessões que travaram (a mais recente primeiro), com as cópias, a fila e o relatório do travamento.

    Ignora a sessão `current` e as de outras janelas ainda abertas. Pastas de sessão sem marcador e muito
    antigas (`ORPHAN_AGE`) são apagadas.
    """
    root = Path(root) if root is not None else recovery_dir()
    now = time.time() if now is None else now
    found: list[Crashed] = []
    known = set()
    for m, data in _markers(root):
        sid = str(data.get("sessao") or m.stem)
        known.add(sid)
        if sid == current or _alive(data, probe, now):
            continue
        folder = root / sid
        found.append(Crashed(session=sid, pid=_int(data.get("pid"), 0), started=float(data.get("inicio") or 0.0),
                             version=str(data.get("versao_app") or ""), folder=folder, marker=m,
                             copies=copies(folder), queue=read_queue(folder),
                             report=crashlog.report_for(sid, logs)))
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and p.name != SESSIONS]
    except OSError:
        folders = []
    for f in folders:
        if f.name in known or f.name == current:
            continue
        try:
            age = now - f.stat().st_mtime
        except OSError:
            continue
        if age > ORPHAN_AGE:
            shutil.rmtree(f, ignore_errors=True)
    found.sort(key=lambda c: c.started, reverse=True)
    return found


def forget(crashed: Crashed) -> None:
    """Apaga as cópias, a fila e o marcador de uma sessão travada (a pessoa já decidiu o que fazer)."""
    shutil.rmtree(crashed.folder, ignore_errors=True)
    if crashed.marker is not None:
        system.remove_file(crashed.marker)


def usage(root: Path | None = None) -> tuple[int, int]:
    """(número de cópias, bytes) na pasta de recuperação."""
    root = Path(root) if root is not None else recovery_dir()
    n = size = 0
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and p.name != SESSIONS]
    except OSError:
        return 0, 0
    for f in folders:
        for p in copies(f):
            n += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass
    return n, size


def delete_copies(root: Path | None = None, current: str = "", probe: Probe | None = None,
                  now: float | None = None) -> int:
    """Botão "Apagar cópias": as cópias desta sessão e tudo das sessões que já acabaram (travadas).
    As de outras janelas abertas ficam. Devolve quantas cópias saíram."""
    root = Path(root) if root is not None else recovery_dir()
    n = 0
    if current:
        for p in copies(root / current):
            system.remove_file(p)
            n += 1
    for c in scan(root, current, probe=probe, now=now):
        n += len(c.copies)
        forget(c)
    return n
