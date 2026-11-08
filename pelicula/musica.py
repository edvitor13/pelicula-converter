"""Música na montagem (1.8, ARQUITETURA §46; sem Qt): as batidas de um arquivo no tempo da sequência, o plano para
encaixar uma música numa duração (cortando ou repetindo compassos inteiros) e o plano de abaixar a música sob a voz
(chaves de volume comuns). Nada aqui mexe na sequência sem que se peça (`apply_fit`, `apply_duck`); a interface roda
essas funções dentro de `TimelineModel.apply_edit` (um passo do desfazer).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from . import batidas, editparams, timeline
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


# ------------------------------------------------------------------ abaixar a música sob a voz
DUCK_DB = -12.0         # quanto abaixar (dB), o padrão do diálogo
ATTACK_S = 0.3          # a música desce nesse tempo antes da voz
RELEASE_S = 0.6         # e volta nesse tempo depois dela
MERGE_S = 1.0           # falas separadas por menos que isto viram uma só (a música não sobe e desce no meio)
VOICE_RATE = 16000      # a detecção de fala olha o som nesta taxa
VOICE_FRAME_S = 0.02    # janelas de 20 ms, a cada 10 ms
VOICE_HOP_S = 0.01
VOICE_RANGE_DB = 30.0   # fala = até 30 dB abaixo das partes mais fortes da voz...
VOICE_FLOOR_DB = -55.0  # ...e nunca abaixo disto (dBFS)
VOICE_FLAT_MAX = 0.35   # planura espectral (100 Hz a 4 kHz) acima disto é ruído (o branco dá ~0,56), não fala
VOICE_HANG_S = 0.2      # a fala continua por este tempo depois da última janela com voz (consoantes, respiro)
VOICE_MIN_S = 0.1       # trechos mais curtos que isto não são fala (estalos)


def _decimate(x: np.ndarray, rate: int) -> np.ndarray:
    """Mono em `VOICE_RATE` (média por blocos e interpolação linear: a fala está bem abaixo de 8 kHz)."""
    x = np.asarray(x, np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if rate == VOICE_RATE or not len(x):
        return x
    k = max(1, int(rate // VOICE_RATE))
    if k > 1:
        n = len(x) // k * k
        x = x[:n].reshape(-1, k).mean(axis=1)
        rate = rate / k
    n = int(len(x) * VOICE_RATE / rate)
    return np.interp(np.arange(n) * rate / VOICE_RATE, np.arange(len(x)), x)


def speech_regions(x: np.ndarray, rate: int) -> list[tuple[float, float]]:
    """Trechos com fala [(começo, fim)] em segundos desde o começo de `x` (amostras, mono ou n × canais): janelas
    com energia perto da das partes fortes da voz (`VOICE_RANGE_DB`, nunca abaixo de `VOICE_FLOOR_DB`) e espectro
    com tom (planura < `VOICE_FLAT_MAX`: chiado e vento não contam), mais `VOICE_HANG_S` depois de cada uma; falas a
    menos de `MERGE_S` uma da outra viram uma."""
    y = _decimate(x, rate)
    n_win, hop = int(VOICE_FRAME_S * VOICE_RATE), int(VOICE_HOP_S * VOICE_RATE)
    if len(y) < n_win:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(y, n_win)[::hop]
    energy = 10.0 * np.log10(np.maximum((frames ** 2).mean(axis=1), 1e-12))
    loud = energy[energy > -80.0]
    if not loud.size:
        return []
    thr = max(float(np.percentile(loud, 95)) - VOICE_RANGE_DB, VOICE_FLOOR_DB)
    freqs = np.fft.rfftfreq(512, 1.0 / VOICE_RATE)
    band = (freqs >= 100) & (freqs <= 4000)
    win = np.hanning(n_win)
    flat = np.ones(len(frames))
    for i in range(0, len(frames), 4096):
        p = np.abs(np.fft.rfft(frames[i:i + 4096] * win, 512, axis=1)[:, band]) ** 2 + 1e-12
        flat[i:i + 4096] = np.exp(np.log(p).mean(axis=1)) / p.mean(axis=1)
    active = (energy > thr) & (flat < VOICE_FLAT_MAX)
    regions: list[list[float]] = []
    for i in np.flatnonzero(active):
        t0 = i * VOICE_HOP_S
        t1 = t0 + VOICE_FRAME_S + VOICE_HANG_S
        if regions and t0 <= regions[-1][1] + MERGE_S:
            regions[-1][1] = max(regions[-1][1], t1)
        else:
            regions.append([t0, t1])
    dur = len(y) / VOICE_RATE
    return [(a, min(b, dur)) for a, b in regions if b - a - VOICE_HANG_S >= VOICE_MIN_S]


@dataclass(frozen=True)
class Duck:
    """Uma descida da música: começa a descer em `k0`, está embaixo de `fa` a `fb` e volta ao normal em `k3`
    (quadros da sequência; `k0`/`k3` None = a ponta está fora do clipe e o clipe começa/acaba embaixo)."""
    k0: int | None
    fa: int
    fb: int
    k3: int | None


def duck_spans(clip: timeline.Clip, regions: Iterable[tuple[float, float]], fps: float,
               attack: float = ATTACK_S, release: float = RELEASE_S) -> list[Duck]:
    """As descidas de um clipe de música para as falas `regions` (segundos da sequência). Descidas que se tocariam
    (a subida de uma passando da descida da outra) viram uma."""
    att, rel = max(0, int(round(attack * fps))), max(0, int(round(release * fps)))
    spans: list[list[int]] = []
    for a, b in sorted(regions):
        fa, fb = int(np.floor(a * fps)), int(np.ceil(b * fps))
        if fb <= clip.start or fa >= clip.end:
            continue
        if spans and fa - att <= spans[-1][1] + rel:
            spans[-1][1] = max(spans[-1][1], fb)
        else:
            spans.append([fa, fb])
    last = clip.end - 1
    out = []
    for fa, fb in spans:
        k0, k3 = fa - att, fb + rel
        out.append(Duck(k0 if k0 >= clip.start and att else None, max(fa, clip.start), min(fb, last),
                        k3 if k3 <= last and rel else None))
    return out


def duck_conflicts(seq: timeline.Sequence, clip: timeline.Clip, ducks: list[Duck]) -> list[float]:
    """Quadros das chaves de volume que o clipe já tem dentro de alguma descida (de `k0` a `k3`)."""
    hit = []
    for f, _v, _e in seq.keys_of(clip, "volume"):
        for d in ducks:
            lo = d.k0 if d.k0 is not None else clip.start
            hi = d.k3 if d.k3 is not None else clip.end - 1
            if lo - 1e-6 <= f <= hi + 1e-6:
                hit.append(f)
                break
    return hit


def apply_duck(seq: timeline.Sequence, cid: str, ducks: list[Duck], depth_db: float = DUCK_DB) -> int:
    """Escreve as chaves de volume das descidas (as chaves que já estavam dentro delas saem: quem chama perguntou
    antes, `duck_conflicts`). O volume embaixo é o de cada ponto menos `depth_db`; as chaves das pontas guardam o
    volume de antes. Use dentro de `TimelineModel.apply_edit`. Devolve quantas chaves escreveu."""
    c = seq.find(cid)
    if c is None or not ducks or seq.locked(c):
        return 0
    for f in duck_conflicts(seq, c, ducks):
        seq.remove_key(cid, "volume", f)
    p = editparams.AUDIO.params["volume"]
    depth = abs(float(depth_db))

    def level(f: int) -> float:
        return float(seq.values_at(c, f)["volume"])

    keys: list[tuple[int, float]] = []
    for d in ducks:                             # todos os valores primeiro: uma chave nova não muda a conta da próxima
        if d.k0 is not None:
            keys.append((d.k0, level(d.k0)))
        keys.append((d.fa, max(p.min, level(d.fa) - depth)))
        if d.fb != d.fa:
            keys.append((d.fb, max(p.min, level(d.fb) - depth)))
        if d.k3 is not None:
            keys.append((d.k3, level(d.k3)))
    n = 0
    for f, v in keys:
        n += bool(seq.set_key(cid, "volume", f, round(v, 2)))
    return n


def voice_mix(seq: timeline.Sequence, voice_tracks: Iterable[int], skip: Iterable[str] = ()) -> timeline.Sequence:
    """Cópia da sequência só com o som das faixas de voz (sem `skip`, os clipes de música), sem solo: o que
    `audiomix.render_mix` mixa para achar as falas."""
    tracks = set(voice_tracks)
    skip = set(skip)
    mix = seq.copy()
    mix.clips = [c for c in mix.clips if c.kind != AUDIO or (c.track in tracks and c.id not in skip)]
    for tr in mix.kind_tracks(AUDIO):
        tr.solo = False
    return mix


def voice_tracks_for(seq: timeline.Sequence, music: Iterable[timeline.Clip]) -> list[int]:
    """As faixas de som que tocam junto com a música (o padrão do diálogo): as que têm clipes de som que se
    sobrepõem a ela, menos as próprias faixas da música."""
    music = list(music)
    ids = {c.id for c in music}
    own = {c.track for c in music}
    out = set()
    for c in seq.clips:
        if c.kind == AUDIO and c.id not in ids and c.track not in own:
            if any(c.start < m.end and c.end > m.start for m in music):
                out.add(c.track)
    return sorted(out)


__all__ = ["beat_frames", "snap_frames", "Piece", "Plan", "fit_plan", "fade_plan", "fit_target", "fit_blockers",
           "apply_fit", "speech_regions", "Duck", "duck_spans", "duck_conflicts", "apply_duck", "voice_mix",
           "voice_tracks_for"]
