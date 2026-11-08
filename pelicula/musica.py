"""Música na montagem (1.8, ARQUITETURA §46; sem Qt): as batidas de um arquivo no tempo da sequência, o plano para
encaixar uma música numa duração (cortando ou repetindo compassos inteiros) e o plano de abaixar a música sob a voz
(chaves de volume comuns). Nada aqui mexe na sequência sem que se peça (`apply_fit`, `apply_duck`); a interface roda
essas funções dentro de `TimelineModel.apply_edit` (um passo do desfazer).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable

from . import batidas, timeline
from .i18n import _
from .timeline import AUDIO, VIDEO

KEEP_BARS = 2           # compassos guardados no começo (a introdução) e no fim (o final natural) ao encaixar
FADE_S = 2.0            # "diminuir no fim" quando o final da música é cortado (e na saída simples)
TRIM_FADE_MIN_S = 0.25  # cortar menos que isto do fim não pede a saída suave
JOINT_MAX_S = 5.0       # transição de cada emenda: uma batida, no máximo o limite de "transicao"


# ------------------------------------------------------------------ batidas no tempo da sequência
def beat_frames(seq: timeline.Sequence, clip: timeline.Clip, beats: batidas.Beats) -> list[tuple[float, bool]]:
    """[(quadro da sequência, é começo de compasso)] das batidas que o clipe toca, pelo tempo do clipe (aparar,
    velocidade e, com rampa ou reverso, o mapa exato `TimeMap.out_at`). Quadro congelado: nenhuma."""
    if clip.frozen or not beats.times:
        return []
    fps = seq.fps
    downs = set(round(t, 6) for t in beats.downbeats)
    m = seq.time_map(clip) if clip.retimed else None
    out = []
    for t in beats.times:
        x = m.out_at(t) if m is not None else (t - clip.src_in) / clip.speed
        f = clip.start + x * fps
        if clip.start - 1e-6 <= f < clip.end - 1e-6:
            out.append((f, round(t, 6) in downs))
    out.sort()
    return out


def snap_frames(seq: timeline.Sequence, beats_of, exclude: Iterable[str] = ()) -> set[int]:
    """Quadros (inteiros) das batidas de todos os clipes de som com batidas conhecidas (`beats_of(caminho)` → Beats ou
    None), menos os clipes de `exclude` (os que estão sendo arrastados)."""
    skip = set(exclude)
    pts: set[int] = set()
    for c in seq.clips:
        if c.kind != AUDIO or c.id in skip:
            continue
        b = beats_of(c.src)
        if b is not None:
            pts.update(int(round(f)) for f, _down in beat_frames(seq, c, b))
    return pts


# ------------------------------------------------------------------ encaixar a música numa duração
@dataclass(frozen=True)
class Piece:
    """Um pedaço da música encaixada: começa no quadro `start` da sequência com `src_in` (s do arquivo), dura `dur`
    quadros e entra com uma transição de som de `transition` segundos (0 no primeiro pedaço)."""
    start: int
    dur: int
    src_in: float
    transition: float = 0.0


@dataclass(frozen=True)
class Plan:
    """O plano de `fit_plan`. `ok` False = recusado, com o motivo em `reason`; `can_fade` diz se a saída simples
    (`fade_plan`) serve no lugar. `removed`/`added` = compassos tirados/repetidos; `fade_out` = "diminuir no fim" do
    último pedaço."""
    ok: bool
    reason: str = ""
    pieces: tuple[Piece, ...] = ()
    fade_out: float = 0.0
    removed: int = 0
    added: int = 0
    can_fade: bool = False

    @property
    def end(self) -> int:
        return self.pieces[-1].start + self.pieces[-1].dur if self.pieces else 0


def _refuse(reason: str, can_fade: bool = False) -> Plan:
    return Plan(False, reason, can_fade=can_fade)


def _centered(d: list[float], lo: int, hi: int, k: int, mid: float, fits) -> int | None:
    """Índice i (lo ≤ i, i + k ≤ hi) do bloco de `k` compassos [d_i, d_i+k) que `fits(tamanho)` aceita, com o centro
    mais perto de `mid`; None se nenhum."""
    best = None
    for i in range(lo, hi - k + 1):
        if fits(d[i + k] - d[i]):
            cost = abs((d[i] + d[i + k]) / 2 - mid)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, i)
    return None if best is None else best[1]


def _segments(d: list[float], a: float, b: float, shorter: bool, R: float, eps: float):
    """([(começo, fim)] dos trechos do arquivo em ordem, compassos tirados, repetidos): tira o maior bloco de
    compassos inteiros que não passa de R segundos (do arquivo), ou repete o menor que chega a R."""
    m = len(d) - 1
    lo, hi = KEEP_BARS, m - KEEP_BARS
    mid = (d[lo] + d[hi]) / 2
    if shorter:
        for k in range(hi - lo, 0, -1):
            i = _centered(d, lo, hi, k, mid, lambda size: size <= R + eps)
            if i is not None:
                return [(a, d[i]), (d[i + k], b)], k, 0
        return [(a, b)], 0, 0
    for k in range(1, hi - lo + 1):
        i = _centered(d, lo, hi, k, mid, lambda size: size >= R - eps)
        if i is not None:
            return [(a, d[i + k]), (d[i], b)], 0, k
    # nem o meio inteiro repetido uma vez basta: o meio n vezes e mais os r compassos antes do final
    whole = d[hi] - d[lo]
    n = int((R - eps) // whole)
    rest = R - n * whole
    r = next((r for r in range(hi - lo + 1) if d[hi] - d[hi - r] >= rest - eps), hi - lo)
    segs = [(a, d[hi])] + [(d[lo], d[hi])] * n + ([(d[hi - r], b)] if r else [])
    if not r:
        segs[-1] = (segs[-1][0], b)
    return segs, 0, n * (hi - lo) + r


def fit_plan(beats: batidas.Beats, clip: timeline.Clip, target_frames: int, fps: float,
             start: int | None = None) -> Plan:
    """Plano para a música do clipe durar `target_frames` quadros a partir de `start` (sem ele, o começo do clipe):
    tira ou repete compassos INTEIROS, cortando nos começos de compasso, de preferência no meio (a introdução e o
    final natural ficam: `KEEP_BARS` compassos em cada ponta), cada emenda com uma transição de som (potência
    constante) de uma batida. O que sobra (menos de um compasso) sai do fim, com "diminuir no fim" se for mais que
    `TRIM_FADE_MIN_S`. O último pedaço acaba exatamente no alvo. Puro: não mexe no clipe."""
    start = clip.start if start is None else int(start)
    target = int(target_frames)
    if clip.kind != AUDIO:
        return _refuse(_("Só um clipe de som pode ser encaixado."))
    if clip.retimed:
        return _refuse(_("Tire a rampa de velocidade e o reverso do clipe antes de encaixar a música."))
    if target < 1:
        return _refuse(_("Não há duração para encaixar a música."))
    if not beats.confident:
        return _refuse(_("As batidas desta música não são confiáveis (ritmo irregular ou sem batida clara): o "
                         "encaixe por compassos ficaria fora do tempo."), can_fade=target < clip.dur)
    s = clip.speed
    a = clip.src_in
    b = a + clip.dur / fps * s
    d = [t for t in beats.downbeats if a - 1e-6 <= t <= b + 1e-6]
    m = len(d) - 1
    if m - 2 * KEEP_BARS < 1:
        return _refuse(_("A música é curta demais para tirar ou repetir compassos (é preciso a introdução, o final e "
                         "pelo menos um compasso no meio)."), can_fade=target < clip.dur)
    T0, T = clip.dur / fps, target / fps       # segundos da sequência
    if T < ((d[KEEP_BARS] - a) + (b - d[m - KEEP_BARS])) / s - 0.5 / fps:
        return _refuse(_("A duração pedida é menor que a introdução e o final da música juntos."), can_fade=True)
    eps = 0.5 / fps * s                         # meio quadro, em segundos do arquivo
    segs, removed, added = _segments(d, a, b, T <= T0, abs(T - T0) * s, eps)
    # Cada emenda cai num quadro inteiro e o pedaço começa um pouquinho antes ou depois do começo do compasso, para
    # o compasso cair exatamente no tempo em que cairia sem o arredondamento (a música não sai do tempo).
    period = 60.0 / beats.bpm if beats.bpm > 0 else 0.5
    joint = round(min(JOINT_MAX_S, period / s), 3)
    starts: list[tuple[int, float]] = []
    t = 0.0                                     # segundos da sequência desde `start`
    for k, (u0, u1) in enumerate(segs):
        f = start + int(round(t * fps))
        starts.append((f, u0 if k == 0 else max(0.0, u0 - (t - (f - start) / fps) * s)))
        t += (u1 - u0) / s
    end = start + target
    pieces = []
    for k, (f, src_in) in enumerate(starts):
        nxt = starts[k + 1][0] if k + 1 < len(starts) else end
        pieces.append(Piece(f, nxt - f, src_in, 0.0 if k == 0 else joint))
    if any(p.dur < 1 for p in pieces):
        return _refuse(_("A duração pedida é menor que a introdução e o final da música juntos."), can_fade=True)
    cut = t - T                                 # segundos cortados do fim (o resto de menos de um compasso)
    fade = float(clip.values.get("fade_out", 0.0))
    if cut > TRIM_FADE_MIN_S:
        fade = max(fade, min(FADE_S, pieces[-1].dur / fps / 2))
    return Plan(True, "", tuple(pieces), fade, removed, added)


def fade_plan(clip: timeline.Clip, target_frames: int, fps: float, start: int | None = None) -> Plan:
    """A saída simples: a música acaba no alvo com "diminuir no fim" (sem mexer nos compassos). Só encurta."""
    start = clip.start if start is None else int(start)
    target = int(target_frames)
    if clip.kind != AUDIO or target < 1 or target >= clip.dur:
        return _refuse(_("A saída suave só encurta a música."))
    fade = max(float(clip.values.get("fade_out", 0.0)), min(FADE_S, target / fps / 2))
    return Plan(True, "", (Piece(start, target, clip.src_in),), fade)


def fit_target(seq: timeline.Sequence, clip: timeline.Clip, inp: int | None = None,
               outp: int | None = None) -> tuple[int, int] | None:
    """(começo, fim exclusivo) do alvo do encaixe: o trecho In/Out marcado (In sem Out = do In ao fim do conteúdo;
    Out sem In = do começo do clipe ao Out) ou, sem ele, do começo do clipe até o fim do conteúdo de imagem (o fim do
    último clipe de imagem). None se não há alvo depois do começo."""
    a = int(inp) if inp is not None else clip.start
    if outp is not None:
        b = int(outp) + 1
    else:
        ends = [c.end for c in seq.clips if c.kind == VIDEO]
        if not ends:
            return None
        b = max(ends)
    return (a, b) if b > a else None


def fit_blockers(seq: timeline.Sequence, clip: timeline.Clip, start: int, end: int) -> str:
    """Motivo para não encaixar na sequência (vazio = pode): faixa travada, clipe ligado a outro, outro clipe no
    caminho na mesma faixa."""
    if seq.locked(clip):
        return _("A faixa da música está travada.")
    if len(seq.group(clip)) > 1:
        return _("O clipe está ligado a outro (o som de uma câmera): desligue-o antes de encaixar a música.")
    for c in seq.clips_on(AUDIO, clip.track):
        if c.id != clip.id and c.start < end and c.end > start:
            return _("Há outro clipe na faixa da música dentro da duração pedida.")
    return ""


def apply_fit(seq: timeline.Sequence, cid: str, plan: Plan) -> list[str]:
    """Troca o clipe pelos pedaços do plano (o primeiro pedaço é o próprio clipe; os outros, clipes novos com os
    mesmos ajustes e as chaves presas à música). Devolve os ids na ordem. Use dentro de `TimelineModel.apply_edit`
    (um passo do desfazer)."""
    c = seq.find(cid)
    if c is None or not plan.ok or not plan.pieces:
        return []
    a, s, fps = c.src_in, c.speed, seq.fps
    vals, keys, key_off = copy.deepcopy(c.values), copy.deepcopy(c.keys), c.key_off
    last = len(plan.pieces) - 1
    ids = []
    for k, p in enumerate(plan.pieces):
        off = key_off + int(round((p.src_in - a) / s * fps))
        if k == 0:
            piece = c
            piece.start, piece.dur, piece.src_in, piece.key_off = p.start, p.dur, p.src_in, off
        else:
            piece = timeline.Clip(timeline.new_id(), AUDIO, c.src, c.track, p.start, p.dur, p.src_in, "", c.name,
                                  copy.deepcopy(vals), copy.deepcopy(keys), off)
            piece.values["fade_in"] = 0.0
            piece.values["transicao"] = p.transition
            seq.clips.append(piece)
        piece.values["fade_out"] = round(plan.fade_out, 3) if k == last else 0.0
        ids.append(piece.id)
    return ids


__all__ = ["beat_frames", "snap_frames", "Piece", "Plan", "fit_plan", "fade_plan", "fit_target", "fit_blockers",
           "apply_fit"]
