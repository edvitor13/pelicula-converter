"""Capítulos a partir dos marcadores da sequência (sem Qt).

Um capítulo é um marcador com "Capítulo" ligado (`timeline.Marker.chapter`). Daqui saem:

- o texto para a descrição do YouTube (`youtube_text`), conferido contra as regras do YouTube
  (`youtube_problems`: o primeiro em 00:00, pelo menos 3 capítulos, cada um com 10 s ou mais);
- o arquivo FFMETADATA (`ffmetadata`) que a exportação passa ao ffmpeg como mais uma entrada com
  `-map_chapters`, para MP4, MOV e MKV (`CONTAINERS`).

Os tempos são sempre contados a partir do começo do trecho exportado (`relative`): o capítulo que já
estava valendo no começo do trecho passa a começar em 0.
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Iterable

from .i18n import _

CONTAINERS = ("mp4", "mov", "mkv")   # recipientes que guardam capítulos
YT_MIN_COUNT = 3                     # regras do YouTube para capítulos na descrição
YT_MIN_SECONDS = 10.0


def points(seq) -> list[tuple[int, str]]:
    """(quadro, título) dos capítulos da sequência; sem nome vira "Capítulo N"."""
    out = []
    for n, mk in enumerate(seq.chapters(), 1):
        title = " ".join(mk.name.split()) or _("Capítulo {n}").format(n=n)
        out.append((mk.frame, title))
    return out


def relative(pts: Iterable[tuple[int, str]], start: int, end: int, fps: float) -> list[tuple[float, str]]:
    """(segundos desde `start`, título) dos capítulos dentro de [start, end) quadros.

    O último capítulo que começa antes de (ou em) `start` ainda vale ali: entra em 0 s.
    """
    fps = fps if fps and fps > 0 else 24.0
    active = None
    out: list[tuple[float, str]] = []
    for f, title in sorted(pts, key=lambda p: p[0]):
        if f <= start:
            active = title
        elif f < end:
            out.append(((f - start) / fps, title))
    if active is not None:
        out.insert(0, (0.0, active))
    return out


def _secs(t: float) -> int:
    return int(math.floor(t + 1e-6))


def stamp(t: float, hours: bool = False) -> str:
    """Tempo no formato do YouTube: "MM:SS" (ou "H:MM:SS" em vídeos de uma hora ou mais)."""
    s = _secs(t)
    if hours:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def youtube_text(chs: list[tuple[float, str]], total: float) -> str:
    """Uma linha por capítulo ("00:00 Abertura"), pronta para colar na descrição do vídeo."""
    hours = total >= 3600 or any(t >= 3600 for t, _title in chs)
    return "\n".join(f"{stamp(t, hours)} {title}" for t, title in chs)


def youtube_problems(chs: list[tuple[float, str]], total: float) -> list[str]:
    """O que impede o YouTube de mostrar os capítulos (lista vazia = tudo certo)."""
    if not chs:
        return [_("Nenhum marcador é capítulo. Dê dois cliques num marcador e ligue \"Capítulo\".")]
    out = []
    hours = total >= 3600
    if _secs(chs[0][0]) > 0:
        out.append(_("O primeiro capítulo precisa começar em {zero}; o primeiro está em {tempo}. Ponha um "
                     "capítulo no início.").format(zero=stamp(0, hours), tempo=stamp(chs[0][0], hours)))
    if len(chs) < YT_MIN_COUNT:
        out.append(_("O YouTube pede pelo menos {n} capítulos; há {m}.").format(n=YT_MIN_COUNT, m=len(chs)))
    short = []
    for i, (t, title) in enumerate(chs):
        nxt = _secs(chs[i + 1][0]) if i + 1 < len(chs) else total
        if nxt - _secs(t) < YT_MIN_SECONDS:
            short.append(f"{stamp(t, hours)} {title}")
    if short:
        out.append(_("Cada capítulo precisa de pelo menos {s} segundos. Curtos demais: {lista}.").format(
            s=int(YT_MIN_SECONDS), lista="; ".join(short)))
    return out


def _escape(text: str) -> str:
    text = " ".join(str(text).split())
    for ch in ("\\", "=", ";", "#"):
        text = text.replace(ch, "\\" + ch)
    return text


def ffmetadata(chs: list[tuple[float, str]], total: float) -> str:
    """Texto FFMETADATA1 com um [CHAPTER] por capítulo (base de tempo em milissegundos)."""
    lines = [";FFMETADATA1"]
    for i, (t, title) in enumerate(chs):
        a = int(round(t * 1000))
        b = int(round((chs[i + 1][0] if i + 1 < len(chs) else total) * 1000))
        if b <= a:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={a}", f"END={b}", "title=" + _escape(title)]
    return "\n".join(lines) + "\n"


def export_file(pts: list[tuple[int, str]], container: str, start: int, end: int, fps: float) -> str | None:
    """Grava o FFMETADATA do trecho [start, end) num arquivo temporário (quem chama apaga).

    None quando o recipiente não guarda capítulos ou não há capítulo no trecho.
    """
    if not pts or container not in CONTAINERS or end <= start:
        return None
    chs = relative(pts, start, end, fps)
    if not chs:
        return None
    fd, path = tempfile.mkstemp(prefix="pelicula_capitulos_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ffmetadata(chs, (end - start) / (fps if fps and fps > 0 else 24.0)))
    return path
