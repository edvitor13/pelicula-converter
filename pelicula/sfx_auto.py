"""Pôr efeitos sonoros sozinho (1.8, módulo Beta "efeitos_sonoros"; ARQUITETURA §47): o planejador puro por trás do
"Pôr efeitos sonoros…" do modo Edição.

`plan(seq, options)` olha a montagem e devolve onde cada efeito (`sfx.EFFECTS`) entra, em quadros da sequência:

- **whoosh nas transições**: cada transição de entrada ou de saída de um clipe de imagem (tudo que não é "Corte
  seco"); o whoosh dura a transição (de `MIN_WHOOSH_S` a `MAX_WHOOSH_S`) e termina no corte: no fim da transição de
  entrada (a imagem nova inteira) ou no fim do clipe, na de saída;
- **impacto nos cortes secos** (desligado por padrão): corte seco na V1 entre fontes diferentes, o impacto começa no
  corte;
- **swish na entrada dos títulos**: o pico do swish cai no primeiro quadro do título;
- **máquina de escrever (ou cliques) nos títulos "Máquina de escrever"**: uma tecla por letra, nos quadros exatos em
  que cada letra aparece (`titles.motion`, a mesma conta do desenho), com o sino e o retorno do carro na troca de
  linha; os tempos vão em `toques`/`retornos` da fonte do efeito;
- **obturador nos quadros congelados e nas imagens paradas depois de um corte**: começa no primeiro quadro;
- **riser antes dos marcadores** com "!" no nome (ou da cor escolhida): termina no quadro do marcador.

Cada efeito leva em `Source.data["auto"]` uma marca do que o pediu (`"transicao:<clipe>:entrada"`, `"titulo:<clipe>"`,
`"marcador:<id>"`…): rodar de novo não repete o que já está na montagem. `apply(seq, placements)` põe os clipes numa
faixa de som chamada "Efeitos" (a primeira livre no trecho; uma nova se nenhuma está), sem cobrir clipe nenhum. A
interface (`ui/sfx_ui.py`) faz tudo num passo só do desfazer. Nada aqui depende do Qt, a não ser a contagem de letras
de um título (`textrender`, que precisa de uma `QGuiApplication`; os testes podem passar `glyphs=`).
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from typing import Callable

from . import sfx, timeline
from .i18n import _

TRACK_NAME = "Efeitos"          # o nome da faixa (o traduzido também vale: `effects_tracks`)
MIN_WHOOSH_S = 0.4
MAX_WHOOSH_S = 2.0
SWISH_S = 0.4
SWISH_LEAD_S = 0.17             # o pico do swish (42% de 0,4 s) cai no primeiro quadro do título
RISER_S = 3.0
MIN_RISER_S = 0.5
TYPE_TAIL_S = 0.6               # depois da última tecla (o sino e o carro)
RETURN_AFTER_S = 0.06           # o sino logo depois da última letra da linha


@dataclass
class Options:
    """O que pôr (as caixas da janela "Pôr efeitos sonoros…"). O impacto começa desligado."""
    transicoes: bool = True
    impactos: bool = False
    titulos: bool = True
    maquina: bool = True
    tecla: str = "maquina"          # "maquina" | "clique": o som das letras de um título "Máquina de escrever"
    congelados: bool = True
    marcadores: bool = True
    cor_marcador: str = ""          # cor de marcador que também ganha riser ("" = só os com "!" no nome)


@dataclass
class Placement:
    effect: str                     # `sfx.EFFECTS`
    start: int                      # primeiro quadro na sequência
    dur: int                        # quadros
    tag: str                        # `Source.data["auto"]`
    data: dict = field(default_factory=dict)  # campos do efeito além dos padrões (`toques`, `tecla`…)

    @property
    def end(self) -> int:
        return self.start + self.dur


# ------------------------------------------------------------------ ajudas
def seed_of(tag: str) -> int:
    """Semente estável por marca: cada whoosh soa um pouco diferente, sempre igual no mesmo lugar."""
    return 1 + zlib.crc32(tag.encode("utf-8")) % 9999


def existing_tags(seq: timeline.Sequence) -> set[str]:
    """Marcas dos efeitos postos antes que ainda estão na montagem."""
    return {str(s.data.get("auto")) for s in seq.used_sources() if s.kind == sfx.KIND and s.data.get("auto")}


def _frames(seq: timeline.Sequence, seconds: float) -> int:
    return max(1, int(round(seconds * seq.fps)))


def _video_clips(seq: timeline.Sequence) -> list[timeline.Clip]:
    return sorted((c for c in seq.clips if c.kind == timeline.VIDEO), key=lambda c: (c.start, c.track, c.id))


def title_glyphs(src: timeline.Source, height: int) -> tuple[int, list[int]]:
    """(letras do título, índice da primeira letra de cada linha depois da primeira): a mesma contagem do desenho
    (`titles._glyph_map`: só os glifos das palavras, linha por linha)."""
    from . import textrender, titles
    t = titles.title_of(src.data)
    if not t.text.strip():
        return 0, []
    textrender.ensure_app()
    lay = textrender.measure(t.text, t.style, max(2, int(height)))
    n, starts = 0, []
    for li, ln in enumerate(lay.lines):
        if li > 0 and n > 0:
            starts.append(n)
        for wi in ln.words:
            n += len(textrender.shape(lay.face, lay.words[wi].text).xs)
    return n, sorted(set(s for s in starts if 0 < s < n))


def typewriter_hits(seq: timeline.Sequence, clip: timeline.Clip, n: int,
                    line_starts: list[int] = ()) -> tuple[list[float], list[float]]:
    """(toques, retornos) em segundos desde o começo do clipe: uma tecla por letra no quadro em que ela aparece
    (`titles.motion` com `titles.clip_time`, como `titles.render`); várias letras no mesmo quadro se espalham dentro
    dele. Os retornos ficam logo depois da última letra de cada linha."""
    from . import titles
    src = seq.sources[clip.src]
    t = titles.title_of(src.data)
    if n <= 0 or t.enter != "maquina":
        return [], []
    fps = src.fps if src.fps > 0 else seq.fps
    hits: list[float] = []
    shown_before = 0
    for f in range(clip.start, clip.end):
        elapsed, total = titles.clip_time(seq, clip, seq.src_frame(clip, f), fps)
        m = titles.motion(t, elapsed, total, fps)
        p = next((q for kind, q, leaving in m.reveal if kind == "maquina" and not leaving), 1.0)
        shown = min(n, int(math.floor(p * n + 1e-9)))
        k = shown - shown_before
        for j in range(max(0, k)):
            hits.append((f - clip.start + j / k) / seq.fps)
        shown_before = max(shown_before, shown)
        if shown_before >= n:
            break
    rets = [hits[g - 1] + RETURN_AFTER_S for g in line_starts if 0 < g <= len(hits)]
    return [round(h, 6) for h in hits], [round(r, 6) for r in rets]


def _marker_wants_riser(m: timeline.Marker, opts: Options) -> bool:
    return "!" in m.name or (bool(opts.cor_marcador) and m.color == opts.cor_marcador)


# ------------------------------------------------------------------ o plano
def plan(seq: timeline.Sequence, options: Options | None = None,
         glyphs: Callable[[timeline.Source], tuple[int, list[int]]] | None = None) -> list[Placement]:
    """Os efeitos que faltam na montagem, em ordem de tempo. `glyphs(fonte) -> (letras, começos de linha)` conta as
    letras de um título (padrão: `title_glyphs`, com o `textrender`)."""
    from . import titles
    o = options or Options()
    count = glyphs or (lambda src: title_glyphs(src, seq.height))
    have = existing_tags(seq)
    out: list[Placement] = []

    def add(effect: str, start: int, dur: int, tag: str, **data) -> None:
        if tag in have or dur <= 0:
            return
        have.add(tag)
        out.append(Placement(effect, max(0, int(start)), int(dur), tag, {"semente": seed_of(tag), **data}))

    lo_w, hi_w = _frames(seq, MIN_WHOOSH_S), _frames(seq, MAX_WHOOSH_S)
    for c in _video_clips(seq):
        src = seq.sources.get(c.src)
        if src is None:
            continue
        v = c.values
        if o.transicoes:
            if v.get("entrada_tipo", "corte") != "corte":
                n = seq.transition_frames(c, "entrada")
                end = c.start + n
                dur = min(max(n, lo_w), hi_w, end)
                add("whoosh", end - dur, dur, f"transicao:{c.id}:entrada")
            if v.get("saida_tipo", "corte") != "corte":
                nxt = seq.next_on_track(c)
                if not (nxt is not None and nxt.values.get("entrada_tipo", "corte") != "corte"):
                    n = seq.transition_frames(c, "saida")
                    dur = min(max(n, lo_w), hi_w, c.end)
                    add("whoosh", c.end - dur, dur, f"transicao:{c.id}:saida")
        if o.impactos and c.track == 0 and v.get("entrada_tipo", "corte") == "corte":
            prev = seq.previous_on_track(c)
            if prev is not None and prev.src != c.src and src.kind != "ajuste":
                add("impacto", c.start, _frames(seq, sfx.EFFECTS["impacto"].seconds), f"corte:{c.id}")
        if src.kind == titles.KIND:
            t = titles.title_of(src.data)
            if t.enter == "maquina":
                if o.maquina:
                    n, lines = count(src)
                    hits, rets = typewriter_hits(seq, c, n, lines)
                    if hits:
                        dur = min(c.dur, int(math.ceil((hits[-1] + TYPE_TAIL_S) * seq.fps)))
                        add("maquina", c.start, max(1, dur), f"titulo:{c.id}", toques=hits, retornos=rets,
                            tecla=o.tecla if o.tecla in ("maquina", "clique") else "maquina")
            elif o.titulos:
                add("swish", c.start - _frames(seq, SWISH_LEAD_S), _frames(seq, SWISH_S), f"titulo:{c.id}")
        if o.congelados and (c.frozen or (src.is_image and seq.previous_on_track(c) is not None)):
            add("obturador", c.start, _frames(seq, sfx.EFFECTS["obturador"].seconds), f"parado:{c.id}")
    if o.marcadores:
        lo_r, hi_r = _frames(seq, MIN_RISER_S), _frames(seq, RISER_S)
        for m in sorted(seq.markers, key=lambda m: (m.frame, m.id)):
            if _marker_wants_riser(m, o):
                dur = min(hi_r, m.frame)
                if dur >= lo_r:
                    add("riser", m.frame - dur, dur, f"marcador:{m.id}")
    out.sort(key=lambda p: (p.start, p.tag))
    return out


# ------------------------------------------------------------------ na montagem
def effects_tracks(seq: timeline.Sequence) -> list[int]:
    """As faixas de som chamadas "Efeitos" (ou o nome traduzido), destravadas."""
    names = {TRACK_NAME, _(TRACK_NAME)}
    return [i for i, t in enumerate(seq.kind_tracks(timeline.AUDIO)) if t.name in names and not t.locked]


def _free(seq: timeline.Sequence, track: int, a: int, b: int) -> bool:
    return all(c.end <= a or c.start >= b for c in seq.clips_on(timeline.AUDIO, track))


def apply(seq: timeline.Sequence, placements: list[Placement]) -> list[timeline.Clip]:
    """Põe os efeitos na montagem: uma fonte por efeito (com a marca `auto`) e o clipe na primeira faixa "Efeitos"
    livre no trecho (uma faixa nova com esse nome se nenhuma está). Nunca cobre um clipe. Devolve os clipes novos."""
    made: list[timeline.Clip] = []
    for p in placements:
        if p.effect not in sfx.EFFECTS or p.dur <= 0:
            continue
        track = next((t for t in effects_tracks(seq) if _free(seq, t, p.start, p.end)), None)
        if track is None:
            track = seq.add_track(timeline.AUDIO)
            seq.kind_tracks(timeline.AUDIO)[track].name = _(TRACK_NAME)
        src = sfx.new_source(p.effect, seq, auto=p.tag, **p.data)
        seq.add_source(src)
        c = timeline.Clip(timeline.new_id(), timeline.AUDIO, src.path, track, p.start, p.dur, 0.0, "", src.name)
        seq.clips.append(c)
        made.append(c)
    return made


def describe(placements: list[Placement]) -> str:
    """Resumo para a janela ("3 whoosh, 1 riser")."""
    if not placements:
        return _("Nada a pôr: os efeitos que caberiam já estão na montagem.")
    counts: dict[str, int] = {}
    for p in placements:
        counts[p.effect] = counts.get(p.effect, 0) + 1
    parts = [f"{n} × {_(sfx.EFFECTS[e].label)}" for e, n in counts.items()]
    return _("Vai pôr: {lista}.").format(lista=", ".join(parts))

