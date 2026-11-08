"""Batidas da música (1.8, ARQUITETURA §46.1; sem Qt): tempo, batidas e começo dos compassos de um arquivo de som,
só com numpy (sem IA e sem dependência nova). Determinístico: o mesmo arquivo dá sempre o mesmo resultado.

- **Leitura**: mono a `RATE` = 22 050 Hz pelo ffmpeg (`somlimpo.read_range`), no máximo `MAX_SECONDS`.
- **Força dos ataques** (`onset_envelope`): STFT (Hann de `N_FFT`, salto `HOP`: ~86 quadros por segundo) em blocos,
  energia em `N_BANDS` faixas na escala mel, em dB (até `TOP_DB` abaixo do máximo); o fluxo espectral é a subida de
  cada faixa de um quadro para o outro (só a parte positiva), na média das faixas. Tira-se a média local (`MEAN_S`) e
  fica só a parte positiva. Um segundo envelope, só das faixas graves (até `LOW_HZ`), pesa o acento do compasso.
- **Tempo** (`_tempo`): autocorrelação do envelope nos atrasos de `BPM_MIN` a `BPM_MAX`, pesada por uma preferência
  em volta de `BPM_PRIOR` (gaussiana no log, `PRIOR_OCTAVES` de desvio), com a fração do atraso por uma parábola. A
  metade e o dobro vão em `Beats.candidates`.
- **Batidas** (`_track`): programação dinâmica como em D. Ellis, "Beat Tracking by Dynamic Programming" (2007): cada
  quadro soma a força dele e a melhor batida anterior a um período de distância, com custo `TIGHTNESS`·log²(intervalo ÷
  período); a melhor sequência é lida de trás para a frente. Batidas fracas nas pontas saem. Cada batida é refinada
  no som (`_refine`): o começo do ataque, no meio da subida da energia de 2 ms, até ±`REFINE_S`.
- **Compasso** (`_downbeats`): compasso de `BAR` = 4 batidas; a fase com o maior acento médio (graves + todos) é a do
  primeiro tempo. É uma **estimativa** (`bar_confidence`): a interface diz isso. O acento de cada batida fica no
  resultado (`Beats.accents`) para a correção à mão refazer os compassos sem decodificar o som de novo.
- **Correção à mão** (`corrected`, §46.5): andamento ×2 ou ÷2 e compasso de 3 ou de 4, aplicados em cima do resultado
  cru (que o cache guarda como foi detectado). Pura e determinística.
- **Confiança** (0–1): o tempo de cada janela de `WINDOW_S` concorda com o geral (a música não muda de andamento), as
  batidas estão em linha reta no tempo e caem em ataques. `CONFIDENT` é o mínimo para encaixar a música por compassos.
- **BPM** final: a reta das batidas refinadas (mais exata que o atraso da autocorrelação).

Cache: em memória e em disco (`cache_dir()`, um JSON por arquivo), pelo carimbo do arquivo (caminho, data e tamanho)
e `VERSION`: analisar de novo o mesmo arquivo não decodifica nada.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import jobs, somlimpo
from .i18n import _

RATE = 22050
N_FFT = 1024
HOP = 256
FRAME_RATE = RATE / HOP          # ~86,1 quadros de análise por segundo
N_BANDS = 40
F_MIN, F_MAX = 30.0, 8000.0
LOW_HZ = 200.0                   # faixas "graves" do acento do compasso
TOP_DB = 80.0
MEAN_S = 1.0                     # média local tirada do envelope
BPM_MIN, BPM_MAX = 60.0, 200.0
BPM_PRIOR = 120.0
PRIOR_OCTAVES = 1.0
TIGHTNESS = 100.0
WINDOW_S, WINDOW_HOP_S = 12.0, 6.0   # janelas que conferem se o andamento não muda
AGREE = 0.04                     # tempo de uma janela concorda com o geral (±4%, ou a metade/o dobro)
REFINE_S = 0.03                  # o ataque é procurado até ±30 ms da batida
REFINE_WIN_S = 0.002             # energia de 2 ms
REFINE_MIN_DB = 6.0              # subida mínima para mover a batida até o ataque
REFINE_PART = 0.75               # o ataque começa onde a subida chega a 75% da maior (em dB)
BAR = 4
CONFIDENT = 0.5
MAX_SECONDS = 30 * 60.0
BLOCK_FRAMES = 2048              # quadros da STFT por bloco (memória limitada em músicas longas)
VERSION = 2                    # muda com o algoritmo: o cache de antes deixa de valer
CACHE_DIR = "pelicula_batidas"
CACHE_ENV = "PELICULA_SOM_CACHE"  # a mesma pasta-base do cache de som dos clipes (`somcache.CACHE_ENV`)
MEM_ITEMS = 64


class BeatError(RuntimeError):
    """Falha com mensagem para o usuário (PT-BR)."""


@dataclass(frozen=True)
class Beats:
    """Batidas de um arquivo. Tempos em segundos **do arquivo** (como `timeline.Clip.src_in`)."""
    times: tuple[float, ...]
    bpm: float
    downbeats: tuple[float, ...]       # começo de cada compasso de 4 (estimativa)
    confidence: float                  # 0–1 (`CONFIDENT` para encaixar por compassos)
    candidates: tuple[float, ...] = ()  # outros andamentos possíveis (metade e dobro)
    bar_confidence: float = 0.0        # 0–1: o quanto o primeiro tempo se destaca dos outros
    duration: float = 0.0              # segundos analisados
    accents: tuple[float, ...] = ()    # acento de cada batida (uma por `times`; vazio = não medido): refaz os compassos
    bar: int = BAR                     # batidas por compasso (4 como detectado; 3 só pela correção à mão)

    @property
    def confident(self) -> bool:
        return self.confidence >= CONFIDENT and len(self.times) >= 2 * self.bar

    @property
    def period(self) -> float:
        """Segundos por batida."""
        return 60.0 / self.bpm if self.bpm > 0 else 0.0

    def to_json(self) -> dict:
        r = lambda v: round(float(v), 6)  # noqa: E731
        return {"versao": VERSION, "batidas": [r(t) for t in self.times], "bpm": r(self.bpm),
                "compassos": [r(t) for t in self.downbeats], "confianca": r(self.confidence),
                "candidatos": [r(b) for b in self.candidates], "confianca_compasso": r(self.bar_confidence),
                "duracao": r(self.duration), **({"acentos": [r(a) for a in self.accents]} if self.accents else {}),
                **({"batidas_por_compasso": self.bar} if self.bar != BAR else {})}

    @classmethod
    def from_json(cls, d: dict) -> "Beats":
        f = lambda k: tuple(float(v) for v in d.get(k, []))  # noqa: E731
        return cls(f("batidas"), float(d.get("bpm", 0.0)), f("compassos"), float(d.get("confianca", 0.0)),
                   f("candidatos"), float(d.get("confianca_compasso", 0.0)), float(d.get("duracao", 0.0)),
                   f("acentos"), int(d.get("batidas_por_compasso", BAR)))


# ------------------------------------------------------------------ força dos ataques
def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m, dtype=np.float64) / 2595.0) - 1.0)


def _filterbank() -> tuple[np.ndarray, np.ndarray]:
    """Triângulos na escala mel (`N_BANDS` × bins) e a frequência central de cada faixa."""
    bins = np.arange(N_FFT // 2 + 1) * RATE / N_FFT
    edges = _mel_to_hz(np.linspace(_hz_to_mel(F_MIN), _hz_to_mel(F_MAX), N_BANDS + 2))
    fb = np.zeros((N_BANDS, len(bins)))
    for k in range(N_BANDS):
        lo, mid, hi = edges[k], edges[k + 1], edges[k + 2]
        up = (bins - lo) / max(mid - lo, 1e-9)
        down = (hi - bins) / max(hi - mid, 1e-9)
        fb[k] = np.maximum(0.0, np.minimum(up, down))
    return fb, edges[1:-1]


def _mel_power(x: np.ndarray) -> np.ndarray:
    """Energia em faixas mel por quadro (quadro i centrado na amostra i·HOP), em blocos."""
    x = x.astype(np.float32)
    pad = np.pad(x, N_FFT // 2)
    n = 1 + len(x) // HOP
    frames = np.lib.stride_tricks.sliding_window_view(pad, N_FFT)[::HOP][:n]
    win = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    fb, _centers = _filterbank()
    out = np.empty((n, N_BANDS))
    for b0 in range(0, n, BLOCK_FRAMES):
        spec = np.fft.rfft(frames[b0:b0 + BLOCK_FRAMES] * win, axis=1)
        out[b0:b0 + BLOCK_FRAMES] = (spec.real ** 2 + spec.imag ** 2) @ fb.T
    return out


def _moving_mean(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n) | 1)
    c = np.concatenate([[0.0], np.cumsum(np.pad(x, n // 2, mode="edge"))])
    return (c[n:] - c[:-n]) / n


def onset_envelope(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(força dos ataques, energia dos graves), um valor por quadro de análise (`FRAME_RATE`). A energia dos graves é
    linear (não em dB: um ruído fraco nos graves não pode valer como um bumbo) e serve ao acento do compasso."""
    p = _mel_power(x)
    db = 10.0 * np.log10(np.maximum(p, 1e-10))
    db = np.maximum(db, db.max() - TOP_DB) if db.size else db
    rise = np.maximum(0.0, np.diff(db, axis=0, prepend=db[:1]))
    rise[:N_FFT // (2 * HOP) + 1] = 0.0  # o começo do arquivo (janela com os zeros de antes) não é um ataque
    flux = rise.mean(axis=1)
    env = np.maximum(0.0, flux - _moving_mean(flux, round(MEAN_S * FRAME_RATE)))
    _fb, centers = _filterbank()
    return env, p[:, centers <= LOW_HZ].sum(axis=1)


# ------------------------------------------------------------------ tempo
_SMOOTH = np.exp(-0.5 * np.arange(-3, 4) ** 2.0)


def _prior(bpm):
    return np.exp(-0.5 * (np.log2(np.asarray(bpm, dtype=np.float64) / BPM_PRIOR) / PRIOR_OCTAVES) ** 2)


def _acf(env: np.ndarray) -> np.ndarray:
    # Raiz da força (um ataque forte, como a caixa, não apaga um mais fraco, como o bumbo: bumbo e caixa alternados
    # não viram a metade do andamento) e um pouco de desfoque (gaussiana de 1 quadro: um ataque entre dois quadros não
    # perde força num atraso inteiro).
    x = np.convolve(np.sqrt(env), _SMOOTH, mode="same")
    x = x - x.mean()
    n = len(x)
    f = np.fft.rfft(x, 2 * n)
    a = np.fft.irfft(f.real ** 2 + f.imag ** 2)[:n]
    a = a / np.maximum(n - np.arange(n), 1)
    return a / a[0] if a[0] > 0 else np.zeros(n)


def _tempo(env: np.ndarray) -> tuple[float, float]:
    """(BPM, pontuação) do envelope; (0, 0) se curto demais ou sem ritmo."""
    lag_lo = int(math.floor(60.0 * FRAME_RATE / BPM_MAX))
    lag_hi = int(math.ceil(60.0 * FRAME_RATE / BPM_MIN))
    if len(env) < 2 * lag_hi + 2:
        return 0.0, 0.0
    a = _acf(env)
    lags = np.arange(lag_lo, lag_hi + 1)
    score = a[lags] * _prior(60.0 * FRAME_RATE / lags)
    i = int(np.argmax(score))
    if score[i] <= 0:
        return 0.0, 0.0
    lag = float(lags[i])
    if 0 < i < len(lags) - 1:  # parábola pelos vizinhos (fração do atraso)
        y0, y1, y2 = score[i - 1], score[i], score[i + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            lag += 0.5 * (y0 - y2) / den
    return 60.0 * FRAME_RATE / lag, float(score[i])


def _stability(env: np.ndarray, bpm: float) -> float:
    """Fração das janelas de `WINDOW_S` cujo tempo concorda com `bpm` (ou com a metade/o dobro); 1 se a música é
    curta demais para ter duas janelas."""
    w, hop = int(WINDOW_S * FRAME_RATE), int(WINDOW_HOP_S * FRAME_RATE)
    if len(env) < w + hop:
        return 1.0
    agree = total = 0
    for a in range(0, len(env) - w + 1, hop):
        b, _s = _tempo(env[a:a + w])
        if b <= 0:
            continue
        total += 1
        err = min(abs(math.log(b / bpm)), abs(math.log(b / (2 * bpm))), abs(math.log(2 * b / bpm)))
        agree += err < math.log(1.0 + AGREE)
    return agree / total if total else 0.0


# ------------------------------------------------------------------ batidas (programação dinâmica)
def _track(env: np.ndarray, period: float) -> np.ndarray:
    """Quadros das batidas (inteiros) para o período `period` (quadros por batida)."""
    n = len(env)
    sd = env.std()
    if n == 0 or sd <= 0:
        return np.zeros(0, np.int64)
    norm = env / sd
    half = int(round(period))
    k = np.arange(-half, half + 1)
    local = np.convolve(norm, np.exp(-0.5 * (k * 32.0 / period) ** 2), mode="same")
    offs = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    cost = -TIGHTNESS * np.log(-offs / period) ** 2
    cum = np.zeros(n)
    back = np.full(n, -1, np.int64)
    started = False
    floor = 0.01 * local.max()
    for i in range(n):
        prev = i + offs
        ok = prev >= 0
        if not started and local[i] < floor:
            cum[i] = local[i]
            continue
        started = True
        if ok.any():
            cand = cost[ok] + cum[prev[ok]]
            j = int(np.argmax(cand))
            cum[i] = local[i] + cand[j]
            back[i] = prev[ok][j]
        else:
            cum[i] = local[i]
    # Última batida: o último máximo local do acumulado acima da metade da mediana dos máximos.
    peaks = np.flatnonzero((cum[1:-1] >= cum[:-2]) & (cum[1:-1] > cum[2:])) + 1
    if not peaks.size:
        return np.zeros(0, np.int64)
    med = np.median(cum[peaks])
    last = int(peaks[cum[peaks] >= 0.5 * med][-1])
    beats = [last]
    while back[beats[-1]] >= 0:
        beats.append(int(back[beats[-1]]))
    beats = np.array(beats[::-1], np.int64)
    # Batidas fracas nas pontas (silêncio ou ruído antes e depois da música) saem.
    smooth = np.convolve(local, np.hanning(5), mode="same")
    thr = max(0.5 * math.sqrt(float(np.mean(smooth ** 2))), 0.4 * float(np.median(smooth[beats])))
    strong = np.flatnonzero(smooth[beats] >= thr)
    if not strong.size:
        return np.zeros(0, np.int64)
    return beats[strong[0]:strong[-1] + 1]


def _subframe(env: np.ndarray, i: int) -> float:
    """O quadro `i` com a fração do pico do envelope (parábola pelos vizinhos)."""
    if 0 < i < len(env) - 1:
        y0, y1, y2 = env[i - 1], env[i], env[i + 1]
        den = y0 - 2 * y1 + y2
        if den < 0 and y1 >= y0 and y1 >= y2:
            return i + min(0.5, max(-0.5, 0.5 * (y0 - y2) / den))
    return float(i)


def _refine(x: np.ndarray, t: float) -> float:
    """O começo do ataque mais forte a até ±`REFINE_S` de `t` (s): a primeira amostra em que a subida da energia de
    2 ms passa da metade (em dB) da maior subida. Sem subida clara (`REFINE_MIN_DB`), devolve `t`."""
    w = max(1, int(round(REFINE_WIN_S * RATE)))
    look = int(round(0.01 * RATE))            # a subida conta contra o mínimo dos 10 ms anteriores
    a = int(round((t - REFINE_S) * RATE))
    b = int(round((t + REFINE_S) * RATE))
    lo = a - look - w
    if lo < 0 or b > len(x):
        return t
    seg = x[lo:b].astype(np.float64)
    c = np.concatenate([[0.0], np.cumsum(seg * seg)])
    energy = (c[w:] - c[:-w]) / w             # energia das w amostras que terminam em cada ponto
    level = 10.0 * np.log10(np.maximum(energy, 1e-12))
    base = np.lib.stride_tricks.sliding_window_view(level, look).min(axis=1)
    rise = level[look:] - base[:len(level) - look]  # rise[j]: amostra lo + w - 1 + look + j
    first = a - (lo + w - 1 + look)
    rise = rise[first:]
    if not rise.size or rise.max() < REFINE_MIN_DB:
        return t
    j = int(np.argmax(rise >= REFINE_PART * rise.max()))
    return (a + j) / RATE


def _accents(frames: np.ndarray, env: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Acento de cada batida: quanto a energia dos graves sobe nela (o bumbo) mais a força do ataque, cada um dividido
    pela sua média nas batidas."""
    n = len(env)
    lows = np.array([max(0.0, float(low[f:min(n, f + 4)].max() - low[max(0, f - 4):f + 1].min())) for f in frames])
    hits = np.array([float(env[max(0, f - 2):f + 3].max()) for f in frames])
    return lows / (lows.mean() or 1.0) + hits / (hits.mean() or 1.0)


def _phase(accent: np.ndarray, bar: int) -> tuple[int, float]:
    """(fase, confiança) do primeiro tempo de um compasso de `bar` batidas: a fase com o maior acento médio; a
    confiança é o quanto ela se destaca da segunda melhor."""
    score = np.array([accent[k::bar].mean() for k in range(bar)])
    k = int(np.argmax(score))
    rest = np.sort(score)[-2]
    conf = float(max(0.0, (score[k] - rest) / score[k])) if score[k] > 0 else 0.0
    return k, min(1.0, conf * 4.0)


def _downbeats(times: np.ndarray, frames: np.ndarray, env: np.ndarray, low: np.ndarray,
               bar: int = BAR) -> tuple[np.ndarray, float]:
    """(compassos, confiança): a fase de `bar` batidas com o maior acento médio (`_accents`, `_phase`)."""
    if len(frames) < bar:
        return times[:0], 0.0
    k, conf = _phase(_accents(frames, env, low), bar)
    return times[k::bar], conf


def analyze(x: np.ndarray, rate: int = RATE, cancel: threading.Event | None = None) -> Beats:
    """Batidas de amostras mono (float, −1..1) na taxa `RATE`. Música sem ritmo dá poucas batidas e confiança baixa."""
    if rate != RATE:
        raise ValueError("taxa")
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    dur = len(x) / RATE
    env, low = onset_envelope(x)
    if cancel is not None and cancel.is_set():
        raise jobs.Cancelled()
    bpm0, _score = _tempo(env)
    if bpm0 <= 0:
        return Beats((), 0.0, (), 0.0, duration=dur)
    frames = _track(env, 60.0 * FRAME_RATE / bpm0)
    if cancel is not None and cancel.is_set():
        raise jobs.Cancelled()
    times = np.array([_refine(x, _subframe(env, int(f)) / FRAME_RATE) for f in frames])
    bpm = bpm0
    reg = 0.0
    if len(times) >= 4:
        idx = np.arange(len(times))
        slope, icpt = np.polyfit(idx, times, 1)
        if slope > 0:
            bpm = 60.0 / slope
            resid = float(np.sqrt(np.mean((times - (slope * idx + icpt)) ** 2)))
            reg = max(0.0, 1.0 - resid / slope / 0.12)
    on = [float(env[max(0, int(f) - 2):int(f) + 3].max()) for f in frames]
    ratio = (float(np.mean(on)) / float(env.mean())) if len(on) and env.mean() > 0 else 0.0
    strength = min(1.0, max(0.0, (ratio - 1.0) / 1.5))
    stab = min(1.0, max(0.0, (_stability(env, bpm0) - 0.5) / 0.4))
    conf = stab * reg * strength
    downs, bar_conf = _downbeats(times, frames, env, low)
    accent = _accents(frames, env, low) if len(frames) else np.zeros(0)
    return Beats(tuple(float(t) for t in times), float(bpm), tuple(float(t) for t in downs), float(conf),
                 _candidates(bpm), float(bar_conf), dur, tuple(round(float(a), 6) for a in accent))


def _candidates(bpm: float) -> tuple[float, ...]:
    """Os outros andamentos possíveis: a metade e o dobro."""
    return tuple(round(b, 3) for b in (bpm / 2, bpm * 2) if 30.0 <= b <= 400.0)


# ------------------------------------------------------------------ correção à mão
def corrected(beats: Beats, factor: float = 1.0, bar: int = BAR) -> Beats:
    """As batidas com a correção feita à mão em cima do resultado cru do detector (§46.5). Pura e determinística.

    - `factor` 2: uma batida nova no meio exato de cada par de batidas (o andamento dobra); 0.5: fica uma batida sim,
      outra não, na paridade que guarda mais começos de compasso detectados (se empatar, a de maior acento somado; se
      empatar, a das batidas de índice par). Outro valor vale 1.
    - `bar` 3 ou 4: batidas por compasso. Os compassos são refeitos pela fase de maior acento médio (`_phase`, a mesma
      conta do detector); a batida inserida pelo ×2 tem acento 0 (é contratempo). Sem os acentos (resultado montado à
      mão), a fase é a que mantém o primeiro começo de compasso que já havia.
    - A confiança é a do detector; `candidates` refaz a metade e o dobro do andamento novo.
    Sem correção (1 e 4) devolve o próprio `beats`."""
    factor = float(factor) if float(factor) in (0.5, 2.0) else 1.0
    bar = 3 if int(bar) == 3 else BAR
    if factor == 1.0 and bar == beats.bar:
        return beats
    times = list(beats.times)
    acc = list(beats.accents) if len(beats.accents) == len(times) else []
    downs = set(round(t, 6) for t in beats.downbeats)
    bpm = beats.bpm
    if factor == 2.0 and len(times) >= 2:
        new, new_acc = [], []
        for i, t in enumerate(times):
            new.append(t)
            new_acc.append(acc[i] if acc else 0.0)
            if i + 1 < len(times):
                new.append((t + times[i + 1]) / 2.0)
                new_acc.append(0.0)
        times, acc, bpm = new, (new_acc if acc else []), bpm * 2.0
    elif factor == 0.5 and len(times) >= 2:
        def kept(p: int) -> tuple[int, float]:
            return sum(round(t, 6) in downs for t in times[p::2]), (sum(acc[p::2]) if acc else 0.0)
        p = 1 if kept(1) > kept(0) else 0
        times, acc, bpm = times[p::2], (acc[p::2] if acc else []), bpm / 2.0
    if len(times) < bar:
        return Beats(tuple(times), bpm, (), beats.confidence, _candidates(bpm), 0.0, beats.duration, tuple(acc), bar)
    if acc:
        k, conf = _phase(np.array(acc), bar)
    else:
        first = next((i for i, t in enumerate(times) if round(t, 6) in downs), 0)
        k, conf = first % bar, beats.bar_confidence
    return Beats(tuple(times), bpm, tuple(times[k::bar]), beats.confidence, _candidates(bpm), float(conf),
                 beats.duration, tuple(acc), bar)


def corrected_by(beats: Beats, fix: dict | None) -> Beats:
    """`corrected` com a correção como a fonte a guarda (`timeline.Source.beats_fix`: "fator" e "compasso"; o que falta
    é neutro)."""
    fix = fix or {}
    return corrected(beats, fix.get("fator", 1.0), fix.get("compasso", BAR))


# ------------------------------------------------------------------ arquivo e cache
def _stamp(path: str) -> list:
    try:
        st = os.stat(path)
        return [os.path.abspath(path), st.st_mtime, st.st_size]
    except OSError:
        return [os.path.abspath(path), 0, 0]


def cache_dir() -> Path:
    """Pasta dos resultados (um JSON pequeno por arquivo), ao lado do cache de som dos clipes."""
    return Path(os.environ.get(CACHE_ENV) or tempfile.gettempdir()) / CACHE_DIR


def _cache_path(path: str) -> Path:
    key = hashlib.sha1(json.dumps([VERSION, _stamp(path)]).encode("utf-8")).hexdigest()
    return cache_dir() / f"{key}.json"


_MEM: OrderedDict = OrderedDict()
_LOCK = threading.Lock()


def _remember(key: str, beats: Beats) -> None:
    with _LOCK:
        _MEM[key] = beats
        _MEM.move_to_end(key)
        while len(_MEM) > MEM_ITEMS:
            _MEM.popitem(last=False)


def cached(path: str) -> Beats | None:
    """O resultado já calculado para o arquivo como ele está agora (memória, depois disco), sem analisar."""
    p = _cache_path(path)
    key = p.name
    with _LOCK:
        hit = _MEM.get(key)
    if hit is not None:
        return hit
    try:
        beats = Beats.from_json(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    _remember(key, beats)
    return beats


def analyze_file(path: str, cancel: threading.Event | None = None) -> Beats:
    """Batidas do arquivo (do cache, se o arquivo não mudou). Levanta `BeatError` (mensagem para o usuário) ou
    `jobs.Cancelled`."""
    hit = cached(path)
    if hit is not None:
        return hit
    if not os.path.exists(path):
        raise BeatError(_("O arquivo da música não foi encontrado."))
    x = somlimpo.read_range(path, 0.0, MAX_SECONDS, rate=RATE, channels=1, cancel=cancel)
    if cancel is not None and cancel.is_set():
        raise jobs.Cancelled()
    if len(x) < RATE * 2:
        raise BeatError(_("Este clipe não tem som suficiente para achar as batidas."))
    beats = analyze(x[:, 0], RATE, cancel)
    p = _cache_path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        part = p.with_suffix(f".{os.getpid()}_{threading.get_ident()}.parcial")
        part.write_text(json.dumps(beats.to_json()), encoding="utf-8")
        os.replace(part, p)
    except OSError:
        pass  # sem cache em disco: fica o da memória
    _remember(p.name, beats)
    return beats


__all__ = ["Beats", "BeatError", "analyze", "analyze_file", "cached", "cache_dir", "onset_envelope", "CONFIDENT",
           "corrected", "corrected_by"]
