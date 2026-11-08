"""Busca de sons livres CC0 (1.8, módulo Beta "efeitos_sonoros"; ARQUITETURA §47): Openverse e Freesound, sem Qt.

- **Openverse** (`https://api.openverse.org`) não pede chave: é a busca de sempre.
- **Freesound** só com a chave da API da própria pessoa (Configurações › Sons livres, `KEY_FREESOUND` nas preferências;
  nunca no projeto). O arquivo original do Freesound pede login (OAuth): baixamos a prévia de alta qualidade (MP3).
- Só resultados com licença **CC0** (domínio público) ficam (`parse_openverse`, `parse_freesound`).
- Rede: só quando a pessoa clica em "Buscar", "Ouvir" ou "Adicionar à Mídia" (a interface roda numa thread de
  trabalho); `TIMEOUT` s por pedido; `User-Agent` genérico (`PeliculaConverter/<versão>`, nunca dado da pessoa);
  `urllib` da biblioteca padrão (`opener` troca nos testes: nada de rede nos testes).
- O arquivo baixado vai para `<projeto>_sons/` ao lado do projeto (ou `sons_cc0/` na pasta do app, sem projeto salvo:
  `target_dir`) e entra na Mídia com o crédito na fonte (`timeline.Source.credit`, "credito" no JSON).
- **Créditos na exportação**: se o trecho exportado usa um som com crédito, `<saída>.creditos.txt` (uma linha por som:
  título — autor — licença — URL) fica ao lado do arquivo (`export_credits`, chamado por `export.run_job` e
  `somexport.run`); o terminal lista os créditos em `info` (`project_credits`).
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__, timeline
from .i18n import _

OPENVERSE_URL = "https://api.openverse.org/v1/audio/"
FREESOUND_URL = "https://freesound.org/apiv2/search/text/"
FREESOUND_KEY_HELP = "https://freesound.org/apiv2/apply/"
KEY_FREESOUND = "sons_cc0/freesound_chave"   # preferência (QSettings); nunca no projeto
USER_AGENT = f"PeliculaConverter/{__version__}"
TIMEOUT = 10.0
PAGE_SIZE = 20
MAX_JSON = 4 * 1024 ** 2
MAX_DOWNLOAD = 200 * 1024 ** 2
MAX_PREVIEW = 40 * 1024 ** 2
CHUNK = 256 * 1024
LICENSE = "CC0 1.0"
SOUND_EXT = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".aiff", ".aif")
UNSAVED_DIR = "sons_cc0"


class NetError(RuntimeError):
    """Erro de rede ou de resposta, com o texto para a pessoa (PT-BR)."""


@dataclass(frozen=True)
class Result:
    origem: str          # "openverse" | "freesound"
    id: str
    titulo: str
    autor: str
    duracao: float       # segundos (0 = desconhecida)
    pagina: str          # página do som (vai para o crédito)
    arquivo: str         # o que "Adicionar à Mídia" baixa
    previa: str          # o que "Ouvir" baixa
    ext: str             # ".mp3", ".wav"…

    @property
    def origin_label(self) -> str:
        return "Openverse" if self.origem == "openverse" else "Freesound"


# ------------------------------------------------------------------ endereços
def openverse_url(query: str, page_size: int = PAGE_SIZE) -> str:
    q = urllib.parse.urlencode({"q": query.strip(), "license": "cc0", "page_size": int(page_size)})
    return f"{OPENVERSE_URL}?{q}"


def freesound_url(query: str, key: str) -> str:
    q = urllib.parse.urlencode({"query": query.strip(), "filter": 'license:"Creative Commons 0"',
                                "fields": "id,name,username,license,previews,duration,url", "token": key.strip()})
    return f"{FREESOUND_URL}?{q}"


# ------------------------------------------------------------------ respostas
def _text(value: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _ext_of(url: str, filetype: Any = None) -> str:
    ft = str(filetype or "").lower().strip(".")
    if ft and f".{ft}" in SOUND_EXT:
        return f".{ft}"
    path = urllib.parse.urlparse(url).path.lower()
    ext = os.path.splitext(path)[1]
    return ext if ext in SOUND_EXT else ".mp3"


def _https(url: Any) -> str:
    u = str(url or "").strip()
    return u if u.startswith(("https://", "http://")) else ""


def is_cc0_openverse(item: dict) -> bool:
    return str(item.get("license") or "").lower() == "cc0"


def is_cc0_freesound(item: dict) -> bool:
    lic = str(item.get("license") or "").lower()
    return "publicdomain/zero" in lic or lic in ("creative commons 0", "cc0")


def parse_openverse(data: Any) -> list[Result]:
    """Os sons CC0 de uma resposta do Openverse (`results`; a duração vem em milissegundos)."""
    out = []
    for it in (data.get("results") if isinstance(data, dict) else None) or []:
        if not isinstance(it, dict) or not is_cc0_openverse(it):
            continue
        url = _https(it.get("url"))
        if not url:
            continue
        try:
            dur = max(0.0, float(it.get("duration") or 0) / 1000.0)
        except (TypeError, ValueError):
            dur = 0.0
        out.append(Result("openverse", _text(it.get("id"), 80), _text(it.get("title")) or _("Sem título"),
                          _text(it.get("creator")) or _("Autor desconhecido"), dur,
                          _https(it.get("foreign_landing_url")) or url, url, url, _ext_of(url, it.get("filetype"))))
    return out


def parse_freesound(data: Any) -> list[Result]:
    """Os sons CC0 de uma resposta do Freesound (`results`; prévia MP3 de alta qualidade)."""
    out = []
    for it in (data.get("results") if isinstance(data, dict) else None) or []:
        if not isinstance(it, dict) or not is_cc0_freesound(it):
            continue
        prev = it.get("previews") if isinstance(it.get("previews"), dict) else {}
        hq = _https(prev.get("preview-hq-mp3")) or _https(prev.get("preview-lq-mp3"))
        if not hq:
            continue
        try:
            dur = max(0.0, float(it.get("duration") or 0))
        except (TypeError, ValueError):
            dur = 0.0
        sid = _text(it.get("id"), 40)
        page = _https(it.get("url")) or (f"https://freesound.org/s/{sid}/" if sid else hq)
        out.append(Result("freesound", sid, _text(it.get("name")) or _("Sem título"),
                          _text(it.get("username")) or _("Autor desconhecido"), dur, page, hq, hq, ".mp3"))
    return out


def merge(*groups: list[Result]) -> list[Result]:
    """Junta as listas sem repetir o mesmo som (o Openverse também indexa o Freesound: mesmo título e autor)."""
    seen: set[tuple[str, str]] = set()
    out = []
    for group in groups:
        for r in group:
            key = (r.titulo.casefold(), r.autor.casefold())
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


# ------------------------------------------------------------------ rede
def _request(url: str, accept: str = "application/json") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})


def _friendly(exc: BaseException, origin: str) -> NetError:
    if isinstance(exc, urllib.error.HTTPError):
        if origin == "Freesound" and exc.code in (401, 403):
            return NetError(_("O Freesound recusou a chave da API (confira em Configurações › Sons livres)."))
        if exc.code == 429:
            return NetError(_("{origem}: muitas buscas seguidas. Espere um pouco e tente de novo.").format(
                origem=origin))
        return NetError(_("{origem} respondeu com erro {codigo}.").format(origem=origin, codigo=exc.code))
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc):
        return NetError(_("{origem} não respondeu em {s} s.").format(origem=origin, s=int(TIMEOUT)))
    if isinstance(exc, urllib.error.URLError):
        return NetError(_("Não deu para falar com {origem}: confira a conexão com a internet.").format(origem=origin))
    return NetError(_("{origem}: {erro}").format(origem=origin, erro=exc))


def fetch_json(url: str, origin: str, opener: Callable | None = None) -> Any:
    """GET de um JSON com `TIMEOUT` e o `User-Agent` do app. NetError com o texto para a pessoa."""
    open_ = opener or urllib.request.urlopen
    try:
        with open_(_request(url), timeout=TIMEOUT) as r:
            raw = r.read(MAX_JSON + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _friendly(exc, origin) from exc
    if len(raw) > MAX_JSON:
        raise NetError(_("{origem}: resposta grande demais.").format(origem=origin))
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NetError(_("{origem} respondeu algo que não é uma lista de sons.").format(origem=origin)) from exc


def search(query: str, freesound_key: str = "", opener: Callable | None = None) -> tuple[list[Result], list[str]]:
    """Busca no Openverse e, com a chave, no Freesound. Devolve (sons CC0, erros de cada fonte que falhou)."""
    if not query.strip():
        return [], []
    groups: list[list[Result]] = []
    errors: list[str] = []
    try:
        groups.append(parse_openverse(fetch_json(openverse_url(query), "Openverse", opener)))
    except NetError as exc:
        errors.append(str(exc))
    if freesound_key.strip():
        try:
            groups.insert(0, parse_freesound(fetch_json(freesound_url(query, freesound_key), "Freesound", opener)))
        except NetError as exc:
            errors.append(str(exc))
    return merge(*groups), errors


def safe_name(text: str, limit: int = 60) -> str:
    """Um nome de arquivo seguro em Windows e Linux (sem caracteres proibidos, sem pontos nas pontas)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text)
    s = re.sub(r"\s+", " ", s).strip(" .")[:limit].strip(" .")
    return s or "som"


def file_name(r: Result) -> str:
    """O nome do arquivo baixado: título, autor, origem e id (o mesmo som sempre no mesmo arquivo)."""
    return f"{safe_name(r.titulo)} - {safe_name(r.autor, 30)} [{r.origem} {safe_name(r.id, 40)}]{r.ext}"


def target_dir(project_path: str | None) -> Path:
    """A pasta dos sons baixados: `<projeto>_sons/` ao lado do projeto salvo, ou `sons_cc0/` na pasta do app."""
    if project_path:
        p = Path(project_path)
        return p.with_name(f"{p.stem}_sons")
    from .deps import config_dir
    return config_dir() / UNSAVED_DIR


def download(url: str, dest: str | os.PathLike, opener: Callable | None = None, max_bytes: int = MAX_DOWNLOAD,
             cancel: threading.Event | None = None, origin: str = "") -> str:
    """Baixa `url` para `dest` (num parcial; troca no fim). Já existe: devolve sem baixar de novo."""
    dest = Path(dest)
    if dest.is_file() and dest.stat().st_size > 0:
        return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + f".{os.getpid()}.parte")
    open_ = opener or urllib.request.urlopen
    try:
        try:
            with open_(_request(url, "*/*"), timeout=TIMEOUT) as r, open(part, "wb") as fh:
                total = 0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise NetError(_("Download cancelado."))
                    block = r.read(CHUNK)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise NetError(_("O arquivo passa de {mb} MB: grande demais para um efeito.").format(
                            mb=max_bytes // 1024 ** 2))
                    fh.write(block)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise _friendly(exc, origin or urllib.parse.urlparse(url).netloc) from exc
        if total == 0:
            raise NetError(_("O download veio vazio."))
        os.replace(part, dest)
    finally:
        try:
            os.remove(part)
        except OSError:
            pass
    return str(dest)


def credit_of(r: Result) -> dict[str, str]:
    """O crédito do som (`timeline.Source.credit`)."""
    return {"titulo": r.titulo, "autor": r.autor, "licenca": LICENSE, "url": r.pagina, "origem": r.origin_label}


# ------------------------------------------------------------------ créditos
def _key(c: dict) -> tuple[str, str]:
    return (c.get("titulo", ""), c.get("url", ""))


def credits_for(seq: timeline.Sequence, start: int = 0, end: int = -1, depth: int = 0) -> list[dict[str, str]]:
    """Os créditos dos sons que tocam em [start, end) (quadros da sequência; mudo e solo valem), também dentro de
    sequências aninhadas no trecho que o clipe mostra. Sem repetir, na ordem em que aparecem."""
    b = seq.duration if end < 0 else int(end)
    a = max(0, int(start))
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(c: dict) -> None:
        if c and _key(c) not in seen:
            seen.add(_key(c))
            out.append(dict(c))

    for c in sorted(seq.audio_clips(), key=lambda c: (c.start, c.track)):
        if c.end <= a or c.start >= b:
            continue
        src = seq.sources.get(c.src)
        if src is None:
            continue
        add(src.credit)
        inner = seq.nested(c)
        if inner is not None and depth < timeline.MAX_NEST:
            f0 = seq.src_frame(c, max(c.start, a))
            f1 = seq.src_frame(c, min(c.end, b) - 1)
            for cr in credits_for(inner, min(f0, f1), max(f0, f1) + 1, depth + 1):
                add(cr)
    return out


def project_credits(seq: timeline.Sequence) -> list[dict[str, str]]:
    """Os créditos de todas as sequências do projeto (o `info` do terminal)."""
    out, seen = [], set()
    for s in seq.family():
        for src in s.used_sources():
            if src.credit and _key(src.credit) not in seen:
                seen.add(_key(src.credit))
                out.append(dict(src.credit))
    return out


def credit_line(c: dict) -> str:
    return " — ".join(x for x in (c.get("titulo", ""), c.get("autor", ""), c.get("licenca", ""), c.get("url", "")) if x)


def credits_text(credits: list[dict]) -> str:
    head = _("Sons usados (CC0, domínio público: o crédito não é obrigatório, mas é uma gentileza com quem gravou)")
    return "\n".join([head, ""] + [credit_line(c) for c in credits]) + "\n"


def credits_path(out_path: str) -> str:
    """`<saída>.creditos.txt`: o nome do arquivo exportado sem a extensão."""
    p = Path(out_path)
    return str(p.with_name(f"{p.stem}.creditos.txt"))


def write_credits(seq: timeline.Sequence | None, start: int, end: int, out_path: str) -> str | None:
    """Grava os créditos do trecho ao lado da exportação; None se nenhum som com crédito toca nele."""
    if seq is None:
        return None
    credits = credits_for(seq, start, end)
    if not credits:
        return None
    path = credits_path(out_path)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(credits_text(credits))
    return path


def export_credits(job, start: int, end: int) -> None:
    """Gancho do fim da exportação (`export.run_job`, `somexport.run`): grava `<saída>.creditos.txt` e diz onde em
    `job.note`. Se não der para gravar, a exportação continua concluída e a nota diz o que faltou."""
    try:
        path = write_credits(getattr(job, "sequence", None), start, end, job.out_path)
    except OSError as exc:
        job.note = _("Não foi possível gravar os créditos dos sons: {erro}").format(erro=exc)
        return
    if path:
        job.note = _("Créditos dos sons em {arquivo}").format(arquivo=path)
