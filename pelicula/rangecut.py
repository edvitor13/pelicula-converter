"""Tirar trechos de tempo da montagem (sem Qt): "Remover silêncios…" e "Cortar pelo texto".

Os dois dão trechos em **segundos da sequência** e terminam no mesmo lugar, `remove_ranges`: cada trecho sai de
todas as faixas destravadas e o que vem depois encosta (uma exclusão com fechamento de espaço feita no tempo,
não por clipe). Assim o som e a imagem continuam em sincronia, as chaves de animação ficam presas à imagem
(`Clip.shift_head`, `_cut`), os marcadores andam junto (os de dentro do trecho ficam no ponto do corte) e as
legendas da sequência acompanham (`subedit.remove_time`); as presas aos arquivos seguem os clipes sozinhas.
Faixas travadas não mudam. A interface chama `TimelineModel.remove_ranges`, que faz tudo num passo de desfazer
e dentro de `Sequence.keep_main()` (faixa principal magnética).

Silêncios (`find_silences`): o som mixado da sequência (`audiomix.render_mix`, o mesmo da exportação) no
trecho pedido, medido por `silences.detect` com o limiar relativo ao nível do próprio trecho. Com clipes
escolhidos, a mixagem tem só o som deles e os silêncios ficam dentro deles.

Cortar pelo texto (`text_ranges`): as palavras na tela (`subedit.words`, segundos da sequência) e os índices
escolhidos vão para `silences.text_cut_ranges`.
"""

from __future__ import annotations

import dataclasses
import math
import os
import shutil
import tempfile
import threading
from typing import Iterable, Sequence as Seq

from . import silences
from .i18n import _
from .silences import Silence
from .timeline import AUDIO, EPS, Sequence, new_id

Range = tuple[float, float]


# ------------------------------------------------------------------ trechos
def merge(ranges: Iterable[Range], gap: float = 0.0) -> list[Range]:
    """Trechos em ordem, sem sobreposição (os que se tocam, ou ficam a menos de `gap`, viram um só)."""
    out: list[list[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in ranges if b > a):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def to_frames(seq: Sequence, ranges: Iterable[Range]) -> list[tuple[int, int]]:
    """Segundos da sequência → quadros [a, b), arredondando para dentro (nunca tira um quadro a mais do que o
    trecho pede) e sem passar do fim da sequência."""
    fps, total = seq.fps, seq.duration
    out = []
    for a, b in merge(ranges):
        fa = max(0, int(math.ceil(a * fps - EPS)))
        fb = min(total, int(math.floor(b * fps + EPS)))
        if fb > fa:
            out.append((fa, fb))
    return out


def total(ranges: Iterable[Range]) -> float:
    return sum(b - a for a, b in merge(ranges))


def remove_ranges(seq: Sequence, frames: Iterable[tuple[int, int]]) -> int:
    """Tira os trechos (quadros [a, b) da sequência) de todas as faixas destravadas e encosta o que vem depois.
    Devolve quantos quadros saíram."""
    spans = []
    for a, b in sorted((int(a), int(b)) for a, b in frames):
        a, b = max(0, a), min(seq.duration, b)
        if b <= a:
            continue
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))
    for a, b in reversed(spans):      # do fim para o começo: os quadros de antes não mudam
        _remove(seq, a, b)
    return sum(b - a for a, b in spans)


def _remove(seq: Sequence, a: int, b: int) -> None:
    d = b - a
    links: dict[str, str] = {}
    lefts: set[str] = set()
    for c in list(seq.clips):
        if seq.locked(c) or c.end <= a:
            continue
        if c.start >= b:
            c.start -= d
        elif c.start >= a and c.end <= b:
            seq.clips.remove(c)
        elif c.start < a and c.end > b:          # atravessa o trecho: fica o antes e o depois, encostados
            right = seq._cut(c, b)
            right.start = a
            if c.link:
                right.link = links.setdefault(c.link, new_id())
            c.dur = a - c.start
            lefts.add(c.id)
        elif c.start < a:                        # termina dentro: perde o fim
            c.dur = a - c.start
            lefts.add(c.id)
        else:                                    # começa dentro: perde o começo e encosta no corte
            cut = b - c.start
            c.src_in = seq.src_time(c, b)
            c.start = a
            c.dur -= cut
            c.shift_head(cut)
    # Como em `Sequence.split`: um ligado que ficou inteiro depois do corte vai com as partes da direita.
    for c in seq.clips:
        if c.link in links and c.id not in lefts and c.start >= a:
            c.link = links[c.link]
    for mk in seq.markers:
        if mk.frame >= b:
            mk.frame -= d
        elif mk.frame > a:
            mk.frame = a
    if seq.subtitles is not None and seq.subtitles.cues:
        from . import subedit
        subedit.remove_time(seq.subtitles, a / seq.fps, b / seq.fps)


# ------------------------------------------------------------------ silêncios
def clip_spans(seq: Sequence, ids: Iterable[str]) -> list[tuple[int, int]]:
    """Quadros que os clipes escolhidos (e os ligados) ocupam, juntos."""
    return [(int(a), int(b)) for a, b in merge((c.start, c.end) for c in seq.expand(ids))]


def _intersect(items: list[Silence], spans: list[Range], min_duration: float) -> list[Silence]:
    out = []
    for s in items:
        for a, b in spans:
            lo, hi = max(s.start, a), min(s.end, b)
            if hi - lo + 1e-9 >= min_duration:
                out.append(Silence(round(lo, 6), round(hi, 6), s.level))
    return out


def find_silences(seq: Sequence, ids: Iterable[str] | None = None, threshold: float = -30.0,
                  min_duration: float = 0.5, padding: float = 0.1, cancel: threading.Event | None = None,
                  perf=None) -> list[Silence]:
    """Silêncios do som da montagem (segundos da sequência). `ids`: só o som desses clipes (e dos ligados), e
    só dentro deles. Levanta `silences.SilenceError` (mensagem para o usuário) ou `tools.Cancelled`."""
    from . import audiomix
    fps = seq.fps
    if ids is not None:
        chosen = {c.id for c in seq.expand(ids)}
        mix = seq.copy()
        mix.clips = [c for c in mix.clips if c.kind != AUDIO or c.id in chosen]
        spans = clip_spans(seq, chosen)
        if not any(c.kind == AUDIO and c.id in chosen for c in seq.clips):
            raise silences.SilenceError(_("Os clipes escolhidos não têm som."))
    else:
        mix, spans = seq, [(0, seq.duration)]
    if not spans or spans[-1][1] <= spans[0][0]:
        raise silences.SilenceError(_("A montagem está vazia."))
    start, end = spans[0][0], spans[-1][1]
    work = tempfile.mkdtemp(prefix="pelicula_silencios_")
    try:
        wav = os.path.join(work, "mixagem.wav")
        try:
            ok = audiomix.render_mix(mix, wav, start, end, cancel, perf)
        except RuntimeError as exc:
            raise silences.SilenceError(str(exc)[-1500:]) from exc
        if cancel is not None and cancel.is_set():
            from . import tools
            raise tools.Cancelled()
        if not ok:
            raise silences.SilenceError(_("Não há som neste trecho da montagem."))
        lv = silences.levels(wav, cancel=cancel, perf=perf)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if lv.reference() <= silences.FLOOR_DB + 1:
        raise silences.SilenceError(_("Não há som neste trecho da montagem."))
    lv = dataclasses.replace(lv, start=start / fps)
    found = silences.detect(lv, threshold, min_duration, padding, relative=True)
    return _intersect(found, [(a / fps, b / fps) for a, b in spans], min_duration)


# ------------------------------------------------------------------ cortar pelo texto
def text_ranges(words: Seq, selection: Iterable[int]) -> list[Range]:
    """Trechos da sequência (segundos) que tiram as palavras escolhidas (`silences.text_cut_ranges`)."""
    return silences.text_cut_ranges(words, selection)
