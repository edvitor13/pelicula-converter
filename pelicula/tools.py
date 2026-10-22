"""Componentes externos: ferramentas que o app baixa e programas que ele encontra no computador.

O registro (`TOOLS`) diz, para cada componente, o que é, para que serve, a licença, a fonte oficial,
que módulos usam (`modules.MODULES`) e, para cada sistema, o arquivo a baixar (`Artifact`): versão,
URL, SHA-256 e tamanho **fixos no código** — nunca lidos do mesmo servidor na hora do download.

Tipos (`Tool.kind`):

- `BAIXADO`: o app baixa da fonte oficial — o binário do próprio autor quando ele publica checksums
  (`origin=OFICIAL`); senão, compilado no CI do PeliculaConverter a partir do código oficial e
  publicado na release do projeto com `SHA256SUMS.txt` (`origin=CI`). O SHA-256 é conferido
  **antes** de extrair; a instalação vai para `deps.app_data_dir()/ferramentas/<id>/<versão>/`,
  montada numa pasta temporária ao lado e trocada de uma vez (`rename`), com `pelicula-origem.json`
  (URL, SHA-256, data). Fica uma versão só, salvo `keep_old=True`.
- `SISTEMA`: programa instalado pelo usuário (DaVinci Resolve agora; Blender depois). O app só
  detecta (`DETECTORS`), sem download.

Exceção documentada: o **ffmpeg** (`backend="ffmpeg"`) mantém o fluxo de `deps.py` — o build mais
recente do gyan.dev (Windows) ou do BtbN (Linux), conferido com o arquivo de checksum publicado
pelo autor do build — e aparece aqui só para a página Componentes mostrar, atualizar e remover.

Sem Qt. A página `ui/pages/componentes.py` mostra o registro e baixa pela fila de tarefas
(`jobs.py`). Funções que gravam aceitam `root` (a pasta `ferramentas`) para os testes usarem uma
pasta temporária.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__, deps
from .i18n import N_, _, fmt_decimal

BAIXADO = "baixado"
SISTEMA = "sistema"
KINDS = (BAIXADO, SISTEMA)

OFICIAL = "oficial"  # binário oficial do autor, com checksum publicado por ele
CI = "ci"            # compilado no CI do PeliculaConverter a partir do código-fonte oficial
ORIGINS = (OFICIAL, CI)

ARCHIVES = ("zip", "tar.gz", "tar.xz", "arquivo")  # "arquivo" = um executável só, sem pacote
PLATFORMS = ("win32", "linux", "darwin")

# Estados (Status.state)
AUSENTE = "ausente"            # não instalado / não encontrado no computador
INSTALADO = "instalado"
DESATUALIZADO = "desatualizado"
INDISPONIVEL = "indisponivel"  # sem download para este sistema

MARKER = "pelicula-origem.json"
STAGING_PREFIX = ".novo-"
TRASH_PREFIX = ".removendo-"
STALE_SECONDS = 12 * 3600      # pastas temporárias esquecidas (app fechado no meio) somem depois disso
CHUNK = 1 << 20

Progress = Callable[[str, int, int], None]


class ToolError(RuntimeError):
    """Falha ao baixar, instalar ou remover um componente (mensagem pronta para o usuário)."""


Cancelled = deps.DownloadCancelled


@dataclass(frozen=True)
class Artifact:
    """O arquivo a baixar de uma ferramenta, num sistema. Tudo fixo no código."""
    platform: str                      # "win32", "linux" ou "darwin" (deps.platform_key())
    version: str                       # vira o nome da pasta: letras, números, ".", "_" e "-"
    url: str                           # https; para origin=CI, a release do PeliculaConverter
    sha256: str                        # 64 dígitos hexadecimais (minúsculos)
    size: int                          # bytes do arquivo baixado
    archive: str = "zip"               # um de ARCHIVES
    executables: tuple[str, ...] = ()  # caminhos dentro da pasta da versão, com "/"
    unpacked_size: int = 0             # bytes depois de extrair (0 = não se sabe)
    origin: str = OFICIAL


@dataclass(frozen=True)
class Tool:
    """Um componente externo. Textos em PT-BR (N_), traduzidos com _() ao mostrar."""
    id: str                            # chave ASCII sem acento, nunca renomear (é o nome da pasta)
    name: str
    description: str                   # para que serve, em uma ou duas frases
    icon: str                          # nome de um ícone de ui/icons.py
    homepage: str                      # site oficial (https)
    license: str                       # licença (SPDX ou nome curto)
    license_url: str                   # texto da licença (https)
    kind: str = BAIXADO
    modules: tuple[str, ...] = ()      # ids de modules.MODULES que usam
    core: bool = False                 # faz parte do núcleo (abrir, prévia, exportar)
    artifacts: tuple[Artifact, ...] = ()
    consent: str = ""                  # condições da licença que o usuário aceita antes de baixar
    backend: str = ""                  # "" = registro; "ffmpeg" = fluxo próprio de deps.py
    source_url: str = ""               # código-fonte oficial (obrigatório quando um artefato é origin=CI)

    def artifact(self, platform: str | None = None) -> Artifact | None:
        """O arquivo deste sistema (ou do sistema dado), se houver."""
        key = platform or deps.platform_key()
        return next((a for a in self.artifacts if a.platform == key), None)


FFMPEG = Tool(
    id="ffmpeg", name="ffmpeg",
    description=N_("Lê e grava todos os formatos de vídeo e de som. Sem ele o app não abre nem exporta vídeos."),
    icon="video", homepage="https://ffmpeg.org", license="GPL-3.0", license_url="https://ffmpeg.org/legal.html",
    kind=BAIXADO, core=True, backend="ffmpeg")

DAVINCI_RESOLVE = Tool(
    id="davinci_resolve", name="DaVinci Resolve",
    description=N_("Editor e corretor de cor da Blackmagic Design. O app instala nele o plugin OpenFX, os DCTLs "
                   "e os LUTs do PeliculaConverter."),
    icon="davinci", homepage="https://www.blackmagicdesign.com/products/davinciresolve",
    license=N_("Proprietária (Blackmagic Design)"),
    license_url="https://www.blackmagicdesign.com/products/davinciresolve",
    kind=SISTEMA, modules=("davinci",))

# Ordem da página Componentes: o ffmpeg primeiro. Ferramenta nova: veja a receita "Nova ferramenta
# externa" no AGENTS.md (fonte oficial, versão e SHA-256 fixos, licença, testes).
TOOLS: tuple[Tool, ...] = (FFMPEG, DAVINCI_RESOLVE)


def all_tools() -> tuple[Tool, ...]:
    return TOOLS


def get(tool_id: str) -> Tool:
    for t in all_tools():
        if t.id == tool_id:
            return t
    raise KeyError(tool_id)


def used_by(tool: Tool) -> list[str]:
    """Módulos que usam a ferramenta: os de `tool.modules` e os que a pedem em `Module.requires`."""
    from . import modules
    ids = list(tool.modules)
    for m in modules.MODULES:
        if tool.id in m.requires and m.id not in ids:
            ids.append(m.id)
    return ids


# ------------------------------------------------------------------ pastas e tamanhos
def tools_dir() -> Path:
    """Pasta das ferramentas baixadas: <pasta do app>/ferramentas."""
    return deps.app_data_dir() / "ferramentas"


def tool_dir(tool: Tool, root: str | Path | None = None) -> Path:
    """Pasta de uma ferramenta: <ferramentas>/<id> (cada versão numa subpasta)."""
    return (Path(root) if root is not None else tools_dir()) / tool.id


def ffmpeg_home() -> Path:
    """Pasta do ffmpeg baixado pelo app (bin/ + ORIGEM.txt)."""
    return deps.ffmpeg_dir().parent


def dir_size(path: str | Path) -> int:
    """Bytes de todos os arquivos dentro da pasta (sem seguir links)."""
    total = 0
    stack = [Path(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def fmt_size(n: int) -> str:
    """Tamanho para o usuário: 980 KB, 9,8 MB, 120 MB, 1,2 GB (separador decimal do idioma)."""
    n = max(0, int(n))
    if n < 1024:
        return f"{n} B"
    value, unit = float(n), "B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1023.5 or unit == "TB":  # 1023,9 KB vira "1,0 MB", não "1024 KB"
            break
    return f"{fmt_decimal(value, 1 if value < 10 else 0)} {unit}"


def disk_usage(root: str | Path | None = None, include_ffmpeg: bool = True) -> int:
    """Espaço que os componentes baixados pelo app ocupam (ferramentas + ffmpeg)."""
    total = dir_size(Path(root) if root is not None else tools_dir())
    if include_ffmpeg and ffmpeg_home().is_dir():
        total += dir_size(ffmpeg_home())
    return total


# ------------------------------------------------------------------ o que está instalado
@dataclass
class Installed:
    version: str
    path: Path
    size: int
    sha256: str = ""
    url: str = ""
    installed_at: str = ""


def version_key(version: str) -> tuple:
    """Ordem de versões: números comparados como números (1.10 > 1.9)."""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-_+]", version or "") if p)


def _read_marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def installed(tool: Tool, root: str | Path | None = None) -> list[Installed]:
    """Versões instaladas pelo app (a mais nova primeiro). Pastas sem o marcador não contam."""
    if tool.backend == "ffmpeg" or tool.kind != BAIXADO:
        return []
    base = tool_dir(tool, root)
    out = []
    try:
        entries = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for d in entries:
        data = _read_marker(d)
        if not data or data.get("id") != tool.id:
            continue
        out.append(Installed(version=str(data.get("versao") or d.name), path=d, size=dir_size(d),
                             sha256=str(data.get("sha256") or ""), url=str(data.get("url") or ""),
                             installed_at=str(data.get("instalado_em") or "")))
    out.sort(key=lambda i: version_key(i.version), reverse=True)
    return out


def _pick_current(tool: Tool, found: list[Installed]) -> Installed | None:
    if not found:
        return None
    art = tool.artifact()
    if art is not None:
        for i in found:
            if i.version == art.version:
                return i
    return found[0]


def current(tool: Tool, root: str | Path | None = None) -> Installed | None:
    """A versão em uso: a fixada no código se estiver instalada; senão a mais nova instalada."""
    return _pick_current(tool, installed(tool, root))


def executable(tool: Tool, name: str | None = None, root: str | Path | None = None) -> Path | None:
    """Caminho de um executável da versão em uso (o primeiro de `executables`, ou o que termina em `name`).

    É o que os módulos chamam para usar a ferramenta: `tools.executable(tools.get("whisper"))`.
    """
    if tool.backend == "ffmpeg":
        from . import media
        try:
            return Path(media.ffmpeg() if name in (None, "ffmpeg") else media.ffprobe())
        except RuntimeError:
            return None
    inst = current(tool, root)
    if inst is None:
        return None
    key = deps.platform_key()
    art = next((a for a in tool.artifacts if a.version == inst.version and a.platform == key), None) or tool.artifact()
    rels = list(art.executables) if art else []
    if name:
        rels = [r for r in rels if r.rsplit("/", 1)[-1] in (name, name + ".exe")]
    for rel in rels:
        p = inst.path / rel
        if p.is_file():
            return p
    return None


# ------------------------------------------------------------------ programas do sistema
@dataclass
class Detected:
    found: bool
    version: str = ""
    path: str = ""                       # pasta do programa (para "Abrir pasta")
    notes: list[str] = field(default_factory=list)


def _win_uninstall_version(pattern: str) -> tuple[str, str]:
    """(versão, pasta) de um programa instalado no Windows, pelo nome na lista de desinstalação."""
    if sys.platform != "win32":
        return "", ""
    import winreg
    rx = re.compile(pattern)
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        if not rx.match(name):
                            continue
                        version = str(winreg.QueryValueEx(k, "DisplayVersion")[0])
                        try:
                            where = str(winreg.QueryValueEx(k, "InstallLocation")[0])
                        except OSError:
                            where = ""
                        return version, where
                except OSError:
                    continue
    return "", ""


def resolve_executables() -> list[Path]:
    """Onde o instalador oficial do DaVinci Resolve põe o programa em cada sistema."""
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        return [Path(pf) / "Blackmagic Design" / "DaVinci Resolve" / "Resolve.exe"]
    if sys.platform == "darwin":
        return [Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")]
    return [Path("/opt/resolve/bin/resolve")]


def detect_resolve() -> Detected:
    """DaVinci Resolve: o executável nas pastas padrão ou a pasta de LUTs que o instalador cria
    (`resolve.lut_dirs()`), mais o estado do plugin do PeliculaConverter (OpenFX e DCTLs/LUTs)."""
    from . import ofx, resolve
    exe = next((p for p in resolve_executables() if p.exists()), None)
    luts = [d for d in resolve.lut_dirs() if d.is_dir()]
    if exe is None and not luts:
        return Detected(False)
    version, where = _win_uninstall_version(r"^DaVinci Resolve( Studio)?$")
    folder = str(exe.parent) if exe is not None else (where or str(luts[0]))
    notes = []
    ofx_ver = ofx.installed_version()
    notes.append(_("Plugin OpenFX do PeliculaConverter: versão {versao}").format(versao=ofx_ver) if ofx_ver
                 else _("Plugin OpenFX do PeliculaConverter: não instalado"))
    dctl_ver = resolve.installed_version(resolve.default_install_dir()) if luts else None
    notes.append(_("DCTLs e LUTs do PeliculaConverter: versão {versao}").format(versao=dctl_ver) if dctl_ver
                 else _("DCTLs e LUTs do PeliculaConverter: não instalados"))
    return Detected(True, version, folder, notes)


# id da ferramenta → função que detecta (só leitura, nada é instalado)
DETECTORS: dict[str, Callable[[], Detected]] = {"davinci_resolve": detect_resolve}


def detect(tool: Tool) -> Detected:
    fn = DETECTORS.get(tool.id)
    if fn is None:
        return Detected(False)
    try:
        return fn()
    except Exception:  # noqa: BLE001 — detecção nunca derruba a página
        return Detected(False)


# ------------------------------------------------------------------ estado para a interface
@dataclass
class Status:
    tool: Tool
    state: str
    version: str = ""                  # versão em uso ou instalada ("" = nenhuma)
    available: str = ""                # versão para baixar (fixada no código; no ffmpeg, a mais nova publicada)
    update_available: bool = False
    downloadable: bool = False         # há download para este sistema
    path: str = ""                     # o que está em uso (executável ou pasta)
    folder: str = ""                   # pasta para "Abrir pasta"
    size: int = 0                      # bytes instalados pelo app (o que "Remover" libera)
    download_size: int = 0             # bytes a baixar (0 = não se sabe)
    managed: bool = False              # há uma cópia instalada pelo app (dá para remover)
    in_use_managed: bool = False       # a cópia em uso é a do app
    verified: bool = False             # a cópia do app foi conferida com SHA-256 ao instalar
    sha256: str = ""
    source_name: str = ""              # de onde vem o download
    source_url: str = ""
    origin: str = ""                   # OFICIAL ou CI (ferramentas do registro)
    where_note: str = ""               # ao lado do caminho: "(baixado pelo app)" ou "(do sistema)"
    notes: list[str] = field(default_factory=list)  # linhas extras (ex.: estado do plugin no Resolve)

    @property
    def installed(self) -> bool:
        return self.state in (INSTALADO, DESATUALIZADO)


def _is_sha(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", (text or "").lower()))


def _ffmpeg_origin() -> dict[str, str]:
    """Campos do ORIGEM.txt gravado por deps.download_ffmpeg (URL, fonte, SHA-256)."""
    out = {}
    try:
        for line in (ffmpeg_home() / "ORIGEM.txt").read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return out


def _has_files(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def _ffmpeg_status(tool: Tool, latest: str) -> Status:
    from . import media
    src = deps.SOURCES.get(deps.platform_key())
    st = Status(tool, AUSENTE, downloadable=deps.platform_supported() and src is not None,
                source_name=_(src["name"]) if src else "", source_url=src.get("page", "") if src else "")
    try:
        path = media.ffmpeg()
        media.ffprobe()
    except RuntimeError:
        path = ""
    home = ffmpeg_home()
    st.managed = _has_files(deps.ffmpeg_dir())
    if st.managed:
        st.size = dir_size(home)
        st.sha256 = _ffmpeg_origin().get("sha-256", "").lower()
        st.verified = _is_sha(st.sha256)
    st.available = latest
    if path:
        info = deps.inspect(path)
        newer = deps.parse_version(latest)
        st.path, st.folder = path, str(Path(path).parent)
        st.version = info.label if info else "?"
        outdated = bool(info and info.outdated)
        st.state = DESATUALIZADO if outdated else INSTALADO
        st.update_available = outdated or bool(info and info.version and newer and info.version < newer)
        try:
            st.in_use_managed = st.managed and Path(path).resolve().parent == deps.ffmpeg_dir().resolve()
        except OSError:
            st.in_use_managed = False
        st.where_note = _("(baixado pelo app)") if st.in_use_managed else _("(do sistema)")
    elif st.managed:
        st.folder = str(home)
    if not st.downloadable and not path:
        st.state = INDISPONIVEL
    return st


def status(tool: Tool, root: str | Path | None = None, latest: str = "") -> Status:
    """Estado de um componente para a página Componentes (só lê o disco; no ffmpeg roda `-version`).

    `latest`: versão mais nova publicada do ffmpeg, se já foi consultada (`deps.latest_version()`).
    """
    if tool.backend == "ffmpeg":
        return _ffmpeg_status(tool, latest)
    if tool.kind == SISTEMA:
        det = detect(tool)
        return Status(tool, INSTALADO if det.found else AUSENTE, version=det.version, path=det.path,
                      folder=det.path, notes=list(det.notes), source_name=_(tool.name), source_url=tool.homepage)
    art = tool.artifact()
    st = Status(tool, AUSENTE if art is not None else INDISPONIVEL, downloadable=art is not None)
    if art is not None:
        st.available, st.download_size, st.origin = art.version, art.size, art.origin
        st.source_url = tool.source_url if art.origin == CI and tool.source_url else tool.homepage
    found = installed(tool, root)
    inst = _pick_current(tool, found)
    if inst is not None:
        st.version, st.path, st.folder = inst.version, str(inst.path), str(inst.path)
        st.managed = st.in_use_managed = True
        st.size = sum(i.size for i in found)
        st.sha256 = inst.sha256
        st.verified = _is_sha(inst.sha256)
        st.update_available = art is not None and inst.version != art.version
        st.state = DESATUALIZADO if st.update_available else INSTALADO
    return st


# ------------------------------------------------------------------ download
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(tool_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(tool_id, threading.Lock())


def check_url(url: str) -> None:
    """Só https (ou arquivo local / servidor local, usados nos testes). O SHA-256 fixo protege o conteúdo."""
    u = urllib.parse.urlparse(url)
    ok = u.scheme == "https" and bool(u.netloc)
    ok = ok or u.scheme == "file"
    ok = ok or (u.scheme == "http" and (u.hostname or "") in ("127.0.0.1", "localhost", "::1"))
    if not ok:
        raise ToolError(_("Endereço de download não permitido: {url}").format(url=url))


def _open(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={**deps.UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — esquema conferido em check_url


def _fetch(url: str, dest: Path, report: Progress, cancel: threading.Event, expected_size: int,
           stage: str) -> str:
    """Baixa para `dest` calculando o SHA-256; para no meio se passar do tamanho esperado."""
    h = hashlib.sha256()
    done = 0
    with _open(url) as r, open(dest, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0) or expected_size
        if expected_size and total != expected_size:
            raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
        report(stage, 0, total)
        while True:
            if cancel.is_set():
                raise Cancelled()
            chunk = r.read(CHUNK)
            if not chunk:
                break
            done += len(chunk)
            if expected_size and done > expected_size:
                raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
            fh.write(chunk)
            h.update(chunk)
            report(stage, done, total)
    if expected_size and done != expected_size:
        raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
    return h.hexdigest()


def _clean_stale(base: Path, max_age: float = STALE_SECONDS) -> None:
    """Apaga pastas temporárias esquecidas: as de remoção sempre; as de instalação depois de `max_age`."""
    try:
        entries = list(base.iterdir())
    except OSError:
        return
    now = time.time()
    for p in entries:
        if p.name.startswith(TRASH_PREFIX):
            shutil.rmtree(p, ignore_errors=True)
        elif p.name.startswith(STAGING_PREFIX):
            try:
                old = now - p.stat().st_mtime > max_age
            except OSError:
                continue
            if old:
                shutil.rmtree(p, ignore_errors=True)


def _check_space(folder: Path, art: Artifact) -> None:
    need = art.size + (art.unpacked_size or art.size * 3) + (64 << 20)
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if free < need:
        raise ToolError(_("Espaço insuficiente em {pasta}: são precisos {precisa} e há {livre} livres.").format(
            pasta=folder, precisa=fmt_size(need), livre=fmt_size(free)))


def _move_aside(path: Path, parent: Path) -> Path:
    """Tira uma pasta do caminho com um `rename` (instantâneo); devolve onde ela ficou."""
    trash = parent / f"{TRASH_PREFIX}{path.name}-{secrets.token_hex(4)}"
    path.rename(trash)
    return trash


def download(tool: Tool, progress: Progress | None = None, cancel: threading.Event | None = None,
             root: str | Path | None = None, keep_old: bool = False) -> Installed:
    """Baixa, confere o SHA-256 fixo, extrai e instala de uma vez. Devolve a versão instalada.

    Nada é extraído antes de o SHA-256 conferir; qualquer falha (hash, tamanho, caminho suspeito no
    pacote, cancelamento) deixa a instalação anterior como estava e não deixa sobras. Levanta
    `ToolError` (mensagem para o usuário) ou `Cancelled`.
    """
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    if tool.backend == "ffmpeg":
        dest = deps.download_ffmpeg(progress, cancel)
        origin = _ffmpeg_origin()
        info = deps.inspect(str(dest / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")))
        return Installed(version=info.label if info else "", path=dest.parent, size=dir_size(dest.parent),
                         sha256=origin.get("sha-256", ""), url=origin.get("baixado de", ""))
    if tool.kind != BAIXADO:
        raise ToolError(_("{nome} é um programa do sistema: instale pelo site oficial.").format(nome=_(tool.name)))
    art = tool.artifact()
    if art is None:
        raise ToolError(_("{nome} ainda não tem download para este sistema.").format(nome=_(tool.name)))
    check_url(art.url)
    base = tool_dir(tool, root)
    with _lock_for(tool.id):
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError(_("Não foi possível instalar em {pasta}:\n{erro}").format(pasta=base, erro=exc)) from exc
        _clean_stale(base)
        _check_space(base, art)
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=base))
        try:
            name = art.url.rsplit("/", 1)[-1].split("?", 1)[0] or "download"
            archive = staging / ("pacote-" + re.sub(r"[^A-Za-z0-9._-]", "_", name))
            stage = _("Baixando {nome}…").format(nome=_(tool.name))
            try:
                digest = _fetch(art.url, archive, report, cancel, art.size, stage)
            except (ToolError, Cancelled):
                raise
            except OSError as exc:
                raise ToolError(_("Falha no download de {nome}: {erro}").format(nome=_(tool.name), erro=exc)) from exc
            report(_("Conferindo o SHA-256…"))
            if digest.lower() != art.sha256.lower():
                raise ToolError(_("O arquivo baixado não confere com o SHA-256 fixado no app. Nada foi instalado."))
            if cancel.is_set():
                raise Cancelled()
            report(_("Extraindo…"))
            content = staging / "conteudo"
            if art.archive == "arquivo":
                content.mkdir()
                rel = art.executables[0] if art.executables else name
                if not deps.safe_member(rel):
                    raise ToolError(_("Caminho suspeito dentro do arquivo: {caminho}").format(caminho=rel))
                (content / rel).parent.mkdir(parents=True, exist_ok=True)
                archive.replace(content / rel)
            else:
                try:
                    deps.extract_archive(archive, content, art.archive)
                except ToolError:
                    raise
                except Exception as exc:  # noqa: BLE001 — pacote ruim ou caminho suspeito
                    raise ToolError(str(exc)) from exc
                archive.unlink(missing_ok=True)
            for rel in art.executables:
                p = content / rel
                if not deps.safe_member(rel) or not p.is_file():
                    raise ToolError(_("{arquivo} não foi encontrado no pacote baixado.").format(arquivo=rel))
                if sys.platform != "win32":
                    p.chmod(p.stat().st_mode | 0o755)
            if cancel.is_set():
                raise Cancelled()
            report(_("Instalando…"))
            marker = {"id": tool.id, "versao": art.version, "plataforma": art.platform, "url": art.url,
                      "sha256": art.sha256.lower(), "tamanho": art.size, "origem": art.origin,
                      "instalado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "app": f"{APP_NAME} {__version__}"}
            (content / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            final = base / art.version
            aside = None
            try:
                if final.exists():
                    aside = _move_aside(final, staging)  # a mesma versão de novo: a antiga sai inteira
                content.rename(final)
            except OSError as exc:
                if aside is not None and not final.exists():
                    try:
                        aside.rename(final)  # devolve a instalação anterior
                    except OSError:
                        pass
                raise ToolError(_("Não foi possível instalar em {pasta}: algum arquivo está em uso? Feche o que "
                                  "estiver usando {nome} e tente de novo.\n\n{erro}").format(
                    pasta=final, nome=_(tool.name), erro=exc)) from exc
            if not keep_old:
                for other in installed(tool, root):
                    if other.path != final:
                        try:
                            shutil.rmtree(_move_aside(other.path, base), ignore_errors=True)
                        except OSError:
                            pass  # em uso: fica para a próxima vez
            report(_("Pronto."), 1, 1)
            return Installed(version=art.version, path=final, size=dir_size(final), sha256=art.sha256.lower(),
                             url=art.url, installed_at=marker["instalado_em"])
        finally:
            shutil.rmtree(staging, ignore_errors=True)


# ------------------------------------------------------------------ remover
def remove(tool: Tool, root: str | Path | None = None, version: str | None = None) -> int:
    """Remove o que o app instalou (uma versão ou todas). Devolve os bytes liberados.

    A pasta sai do lugar com um `rename` (instantâneo) e só depois é apagada; se algum arquivo
    estiver em uso, nada muda e vem um `ToolError`.
    """
    if tool.backend == "ffmpeg":
        target, parent = ffmpeg_home(), deps.app_data_dir()
    elif tool.kind != BAIXADO:
        raise ToolError(_("{nome} é um programa do sistema: desinstale pelo próprio sistema.").format(
            nome=_(tool.name)))
    else:
        if version is not None and (not version or not deps.safe_member(version) or "/" in version
                                    or "\\" in version or version.startswith(".")):
            raise ValueError(f"versão inválida: {version!r}")
        base = tool_dir(tool, root)
        target, parent = (base / version if version else base), (base if version else base.parent)
    _clean_stale(parent)
    if not target.exists():
        return 0
    size = dir_size(target)
    try:
        trash = _move_aside(target, parent)
    except OSError as exc:
        raise ToolError(_("Não foi possível remover {nome}: algum arquivo está em uso. Feche o que estiver usando "
                          "e tente de novo.\n\n{erro}").format(nome=_(tool.name), erro=exc)) from exc
    shutil.rmtree(trash, ignore_errors=True)
    return size
