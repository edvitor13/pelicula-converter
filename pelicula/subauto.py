"""Legendas automáticas da montagem (sem Qt): o que transcrever, o trabalho da fila e a junção no projeto.

A transcrição em si é de `transcribe` (whisper.cpp no próprio computador). Aqui fica a decisão de *o quê*:

- no modo Película, o arquivo aberto inteiro;
- no modo Edição, cada arquivo com som que a montagem usa (ou só os dos clipes escolhidos), no trecho que os
  clipes mostram (`spans_for`): a união dos trechos de cada arquivo, juntando os que estão perto. As legendas
  saem presas ao arquivo (`Subtitles.sources`) e acompanham os cortes que vierem depois, em vez de ficarem no
  tempo fixo da sequência (que é o que a mixagem inteira daria, `transcribe.transcribe_sequence`).

`make_job` monta o trabalho para a fila (`jobs`, o mesmo tipo e a mesma chave de `transcribe.make_job`): um
trecho só é o próprio `transcribe.make_job`; vários rodam um depois do outro no mesmo trabalho (um cancelar
para tudo, e a placa de vídeo cai para o processador sozinha em `transcribe.run_engine`). `apply` põe todos os
resultados com `transcribe.merge` — a interface chama dentro de um passo de desfazer só.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import jobs, subtitles as sb, transcribe
from .i18n import N_, _

GAP = 30.0        # s: trechos do mesmo arquivo mais perto que isto viram um só (uma chamada do whisper)
# Idiomas além dos de `transcribe.LANGUAGES` (o whisper reconhece muitos; estes são os mais pedidos).
MORE_LANGUAGES = {"fr": N_("Francês"), "it": N_("Italiano"), "de": N_("Alemão"), "ja": N_("Japonês")}


@dataclass(frozen=True)
class Span:
    """Um trecho de arquivo a transcrever, em segundos do arquivo (`end` 0 = até o fim)."""
    path: str
    start: float = 0.0
    end: float = 0.0


def languages() -> dict[str, str]:
    """Idioma → rótulo (N_), com "Detectar o idioma" primeiro."""
    return {**transcribe.LANGUAGES, **MORE_LANGUAGES}


def _merge(ranges: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def spans_for(seq, clip_ids: Iterable[str] | None = None, gap: float = GAP) -> list[Span]:
    """Os trechos dos arquivos com som que a montagem mostra (os clipes de `subtitles.clips_for`: o som do arquivo
    ou, sem som na sequência, a imagem). `clip_ids`: só esses clipes e os ligados a eles. Faixas mudas ficam de
    fora."""
    wanted = {c.id for c in seq.expand(clip_ids)} if clip_ids is not None else None
    out: list[Span] = []
    for path in sorted({c.src for c in seq.clips}):
        src = seq.sources.get(path)
        if src is None or not src.is_file or src.is_image or not src.has_audio:
            continue
        ranges = []
        for c in sb.clips_for(seq, path):
            tr = seq.track(c.kind, c.track)
            if (wanted is not None and c.id not in wanted) or (tr is not None and tr.muted):
                continue
            a, b = seq.src_time(c, c.start), seq.src_time(c, c.end)
            if b > a + sb.EPS:
                ranges.append((max(0.0, a), b))
        out += [Span(path, a, b) for a, b in _merge(ranges, gap)]
    return out


def whole_file(path: str) -> list[Span]:
    return [Span(path, 0.0, 0.0)]


def make_job(opts: transcribe.Options, title: str, spans: list[Span], root=None, perf=None) -> jobs.Job:
    """O trabalho da fila. O resultado (`job.result`) é sempre uma lista de `transcribe.Result`."""
    spans = list(spans)
    if len(spans) == 1:
        sp = spans[0]
        one = transcribe.make_job(opts, title, path=sp.path, start=sp.start, end=sp.end, root=root, perf=perf)
        inner = one.fn
        one.fn = lambda job: [inner(job)]
        return one

    def fn(job: jobs.Job) -> list[transcribe.Result]:
        out = []
        for n, sp in enumerate(spans, 1):
            job.check_cancel()
            prefix = _("Trecho {n} de {total}").format(n=n, total=len(spans))

            def cb(stage=None, done=0, total=0, _p=prefix):
                job.report(f"{_p} • {stage}" if stage else None, done, total)

            out.append(transcribe.transcribe_file(sp.path, opts, sp.start, sp.end, cb, job.cancel_event, perf, root))
        return out

    return jobs.Job(fn, title, kind=transcribe.job_kind(opts), key=transcribe.JOB_KEY)


def apply(doc: sb.Subtitles, results: Iterable[transcribe.Result]) -> int:
    """Põe os resultados nas legendas (trocando as que havia em cada trecho). Devolve quantas legendas vieram."""
    n = 0
    for r in results:
        transcribe.merge(doc, r)
        n += len(r.cues)
    return n
