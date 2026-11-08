"""Som de película (1.8, módulo Beta "som_pelicula"; ARQUITETURA §45): o som final passa pela trilha da cópia.

Uma cópia de cinema carregava o som ao lado das imagens: uma faixa ótica (luz que atravessa a película e chega a uma
célula) ou, no Super 8 sonoro, uma tarja magnética. A trilha limitava a faixa de frequências e saturava perto do
volume máximo, o grão e a fita somavam chiado, as emendas estalavam, a poeira crepitava, a velocidade da película
oscilava (wow e flutter) e o projetor fazia barulho na sala. Aqui tudo isso é calculado em numpy, sem amostras
gravadas, sobre o som que já saiu da montagem (`audiomix.render_mix`) ou do arquivo:

- `process(amostras, taxa, valores, fps, amostra_inicial, eventos, before=)`: o motor puro. Tudo vem do índice
  ABSOLUTO da amostra, do fps e da semente (`somf_semente`): nada de `random` nem relógio. Cada etapa tem memória
  finita (filtros FIR de fase mínima, atraso do wow, reverberação), e `before` traz o som logo antes do trecho (até
  `preroll_samples`): processar um trecho dá as mesmas amostras que o mesmo pedaço do som inteiro processado.
- Eventos que a imagem também usa: o wow lento é `look.weave` (o tremor do quadro); os estalos caem nos quadros de
  `look.emenda_frames` (Defeitos → Emendas), `montagem_filme.splice_frames` (A montagem na película) e
  `montagem_filme.reel_frames` (a troca de rolo de Super 8), a mesma conta que desenha a emenda e o pulo
  (`events_for`).
- `process_wav`: o motor em blocos, de um WAV para um WAV PCM de 24 bits (memória limitada em som longo).
- `export_sound`: o gancho da exportação (`export.run_job`); a prévia usa `process_wav` pela `ui/som_pelicula_ui.py`.

Com `somf_on` desligado (ou sem look) nada passa por aqui: o som sai bit a bit igual.

Ordem: mono (trilhas mono) → wow e flutter → saturação da trilha → chiado, ronco, poeira e estalos (estão na
película) → curva de leitura da trilha → projetor na sala → sala de cinema → limite suave (nunca passa de 0,98).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import numpy as np

RATE = 48000
PREROLL_S = 1.1        # contexto antes do trecho: sala (0,85 s) + curva da trilha (85 ms) + wow (~2 ms) + cliques
CHUNK_S = 8.0          # bloco de `process_wav` (s)
FIR_TAPS = 4096        # filtros de fase mínima (85 ms a 48 kHz)
SINC_TAPS = 16         # interpolação do wow (sinc com janela de Hann)
BASE_DELAY = 10        # amostras: o wow só lê o passado (a sinc olha 8 amostras à frente)
WOW_S = 0.3e-3         # atraso do wow lento com 100% e tremor de bitola 1 (35 mm)
FLUTTER = 0.0008       # flutter da roda dentada (furos × fps) com 100%: 0,08% de afinação
CELL = 120             # amostras por célula da poeira (2,5 ms a 48 kHz)
CRACKLE_RATE = 80.0    # cliques por segundo com 100% de poeira na trilha e na imagem
DUST_BASE = 0.3        # poeira da imagem que vale quando os Defeitos (ou a Poeira) estão desligados
POP_S = 0.25           # duração de um estalo de emenda (o baque grave some até lá)
CLICK_S = 0.03         # duração do clique do mecanismo do projetor
ROOM_S = 0.85          # resposta da sala
LIMIT_KNEE, LIMIT_CEIL = 0.85, 0.98

# Furos por quadro (a roda dentada passa um furo de cada vez: o flutter dela é furos × fps).
PERFS = {"8mm": 1, "super8": 1, "16mm": 1, "super16": 1, "35mm": 4, "65mm": 5, "imax": 15}


@dataclass(frozen=True)
class Track:
    """Uma trilha da cópia: a curva de leitura ((Hz, dB), interpolada no log da frequência), mono, o joelho da
    saturação (linear abaixo dele) e o fundo (chiado e ronco em dBFS, antes da curva)."""
    curve: tuple[tuple[float, float], ...]
    mono: bool
    knee: float
    hiss_db: float
    rumble_db: float


# Números de referência (ARQUITETURA §45, com as fontes):
# - "otica_antiga": a curva da Academia (1938): plana de 100 Hz a 1,6 kHz, −7 dB em 40 Hz, −10 dB em 5 kHz, −18 dB em
#   8 kHz; o grão da trilha dos anos 30 chiava muito (a curva existia para escondê-lo).
# - "otica_16": 16 mm ótico, ~90 Hz a 6,5 kHz, relação sinal/ruído de 35 a 40 dB.
# - "otica_35": 35 mm ótico de área variável dos anos 70 e 80 (estéreo matricial), ~40 Hz a 12 kHz, fundo baixo.
# - "magnetica_s8": tarja magnética do Super 8, ~40/80 Hz a 10 kHz (18 qps) e 12 kHz (24 qps), chiado de fita.
TRACKS: dict[str, Track] = {
    "otica_35": Track(((20, -12), (40, -3), (60, 0), (8000, 0), (12000, -3), (14000, -12), (16000, -30),
                       (20000, -50)), False, 0.6, -56.0, -62.0),
    "otica_16": Track(((30, -24), (60, -10), (90, -3), (120, 0), (4000, 0), (6500, -3), (8000, -14),
                       (10000, -30), (16000, -60)), True, 0.55, -40.0, -52.0),
    "magnetica_s8": Track(((30, -18), (50, -8), (80, -3), (120, 0), (6000, 0), (10000, -3), (12000, -10),
                           (15000, -30), (20000, -50)), True, 0.4, -46.0, -90.0),
    "otica_antiga": Track(((20, -14), (40, -7), (100, 0), (1600, 0), (5000, -10), (8000, -18), (10000, -30),
                           (14000, -50), (20000, -60)), True, 0.55, -36.0, -48.0),
}

# "Igual à bitola": as bitolas de 35 mm para cima e as de foto usam a ótica de 35 mm.
GAUGE_TRACK = {"16mm": "otica_16", "super16": "otica_16", "super8": "magnetica_s8", "8mm": "magnetica_s8"}

# Ajustes do look que mudam o som (a prévia refaz só o processamento quando um deles muda: `sound_key`).
SOUND_KEYS = ("bitola", "tremor_vel", "desg_on", "poeira_on", "poeira", "emenda_on", "emenda", "desgaste_semente",
              "mfilme_on", "mfilme_emenda", "mfilme_semente", "rolo_on", "rolo_cadencia")


# ------------------------------------------------------------------ o que vale
def active(values: dict | None) -> bool:
    """Se o som de película está ligado nestes valores do look (None = sem look)."""
    return bool(values) and bool(values.get("somf_on"))


def film_values(values: dict | None, no_effects: bool = False) -> dict | None:
    """Os valores do look que valem para o som (None = o som passa direto): sem look, com "Desligar todos os efeitos"
    ou com a seção desligada, nada muda."""
    return values if (not no_effects and active(values)) else None


def track_of(values: dict) -> str:
    """O tipo de trilha: o escolhido, ou o da bitola em "Igual à bitola"."""
    t = values.get("somf_trilha", "auto")
    if t in TRACKS:
        return t
    return GAUGE_TRACK.get(values.get("bitola", "35mm"), "otica_35")


def sound_key(values: dict | None) -> str:
    """Impressão digital do que muda o som de película nestes valores ("" = desligado)."""
    if not active(values):
        return ""
    keys = sorted(k for k in values if k.startswith("somf_")) + list(SOUND_KEYS)
    return json.dumps({k: values.get(k) for k in keys}, sort_keys=True)


def preroll_samples(rate: int = RATE) -> int:
    """Quantas amostras antes do trecho o motor precisa (`before`) para o trecho sair igual ao som inteiro."""
    return int(math.ceil(PREROLL_S * rate))


def projection_fps(values: dict, fps: float) -> float:
    """A taxa do mecanismo do projetor: a do vídeo, ou a dos rolos de Super 8 (A montagem na película)."""
    if values.get("mfilme_on") and values.get("rolo_on"):
        return float(values.get("rolo_cadencia", "18"))
    return float(fps or 24.0)


def events_for(values: dict, fps: float, frames: int, seq=None) -> list[int]:
    """Os quadros dos estalos: onde a imagem mostra a emenda dos defeitos, a fita dos cortes da montagem e o pulo da
    troca de rolo de Super 8 (1.8, também no arquivo direto: os rolos contam o tempo da saída)."""
    from . import look, montagem_filme
    frames = max(0, int(frames))
    out = set(look.emenda_frames(values, fps, 0, frames))
    out.update(montagem_filme.splice_frames(seq, values, fps, 0, frames))
    out.update(montagem_filme.reel_frames(values, fps, 0, frames))
    return sorted(out)


# ------------------------------------------------------------------ ruído determinístico (vetorizado)
def hash_array(i: np.ndarray, s: int) -> np.ndarray:
    """`look._hash` para um vetor de inteiros (os mesmos valores, em float64 de 0 a 1)."""
    x = (np.asarray(i, np.int64) * 0x9E3779B1 + (s * 0x85EBCA77 + 0x165667B1)) & 0xFFFFFFFF
    x = x.astype(np.uint64)
    x ^= x >> np.uint64(15)
    x = (x * np.uint64(0x2C1B3C6D)) & np.uint64(0xFFFFFFFF)
    x ^= x >> np.uint64(12)
    x = (x * np.uint64(0x297A2D39)) & np.uint64(0xFFFFFFFF)
    x ^= x >> np.uint64(15)
    return x.astype(np.float64) / 0xFFFFFFFF


def vnoise_array(x: np.ndarray, s: int) -> np.ndarray:
    """`look._vnoise` para um vetor (ruído de valor suave, −1 a 1)."""
    x = np.asarray(x, np.float64)
    i = np.floor(x)
    f = x - i
    u = f * f * (3 - 2 * f)
    i = i.astype(np.int64)
    return (hash_array(i, s) * (1 - u) + hash_array(i + 1, s) * u) * 2 - 1


def white(idx: np.ndarray, s: int) -> np.ndarray:
    """Ruído branco de valor eficaz 1 preso ao índice absoluto da amostra."""
    return (hash_array(idx, s) * 2 - 1) * math.sqrt(3.0)


# ------------------------------------------------------------------ filtros
def _conv(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Convolução causal pela FFT: as primeiras len(x) amostras de x * h (por canal; `h` 1-D ou um por canal)."""
    n = x.shape[0]
    m = h.shape[0]
    size = 1 << int(math.ceil(math.log2(max(2, n + m - 1))))
    X = np.fft.rfft(x, size, axis=0)
    H = np.fft.rfft(h, size, axis=0)
    if H.ndim == 1:
        H = H[:, None]
    return np.fft.irfft(X * H, size, axis=0)[:n]


def _curve_db(curve, freqs: np.ndarray) -> np.ndarray:
    fx = np.log10([max(f, 1.0) for f, _d in curve])
    dx = [d for _f, d in curve]
    return np.interp(np.log10(np.maximum(freqs, 1.0)), fx, dx)


@lru_cache(maxsize=32)
def _min_phase(curve: tuple, scale: float, rate: int, taps: int = FIR_TAPS) -> np.ndarray:
    """FIR de fase mínima (causal, energia no começo) com o módulo da curva (dB × `scale`), pelo cepstro real."""
    size = taps * 8
    freqs = np.fft.rfftfreq(size, 1.0 / rate)
    mag = 10.0 ** (np.maximum(_curve_db(curve, freqs) * scale, -120.0) / 20.0)
    cep = np.fft.irfft(np.log(mag), size)
    fold = np.zeros(size)
    fold[0] = cep[0]
    fold[1:size // 2] = 2 * cep[1:size // 2]
    fold[size // 2] = cep[size // 2]
    h = np.fft.irfft(np.exp(np.fft.rfft(fold)), size)[:taps]
    tail = taps // 8
    h[-tail:] *= 0.5 + 0.5 * np.cos(np.linspace(0, math.pi, tail))
    return h


def track_filter(values: dict, rate: int = RATE) -> np.ndarray:
    """O filtro da curva de leitura da trilha com a "Força da trilha" (dB × força)."""
    t = TRACKS[track_of(values)]
    return _min_phase(t.curve, round(float(values.get("somf_trilha_forca", 1.0)), 4), int(rate))


def _soft(x: np.ndarray, knee: float, ceil: float = 1.0) -> np.ndarray:
    """Saturação suave: igual abaixo do joelho, tende a `ceil` acima (nunca passa)."""
    a = np.abs(x)
    over = a > knee
    if not over.any():
        return x
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (ceil - knee) * np.tanh((a[over] - knee) / (ceil - knee)))
    return y


# ------------------------------------------------------------------ wow e flutter
def wow_curve(t: np.ndarray, fps: float, vel: float) -> np.ndarray:
    """O tremor vertical do quadro (`look.weave`, de −1 a 1) em qualquer instante: a parte lenta é a mesma e a parte
    de cada quadro vai de um quadro ao próximo com a mesma curva do ruído de valor (no instante do quadro N vale o
    sorteio do quadro N, como na imagem)."""
    return 0.7 * vnoise_array(t * 1.9 * vel, 103) + 0.3 * vnoise_array(t * fps, 104)


def wow_delay(values: dict, rate: int, fps: float, idx: np.ndarray) -> np.ndarray:
    """Atraso (em amostras, ≥ `BASE_DELAY`) do wow e do flutter nas amostras absolutas `idx`."""
    from .look import GAUGES
    gauge = values.get("bitola", "35mm")
    weave = GAUGES.get(gauge, GAUGES["nenhuma"])["weave"]
    amt = float(values.get("somf_wow", 0.0))
    t = idx / float(rate)
    slow = amt * WOW_S * weave * (1.0 + wow_curve(t, fps, float(values.get("tremor_vel", 1.0))))
    fs = PERFS.get(gauge, 1) * float(fps or 24.0)
    phase = 2 * math.pi * float(hash_array(np.array([int(values.get("somf_semente", 19))]), 851)[0])
    fast = amt * FLUTTER / (2 * math.pi * fs) * (1.0 + np.sin(2 * math.pi * fs * t + phase))
    return BASE_DELAY + (slow + fast) * rate


PHASES = 1024  # posições da tabela da sinc (1/1024 de amostra)


@lru_cache(maxsize=1)
def _sinc_table() -> np.ndarray:
    """Pesos da sinc com janela de Hann para cada fração de amostra (PHASES + 1 linhas, soma 1 em cada)."""
    half = SINC_TAPS // 2
    k = np.arange(-half + 1, half + 1)
    d = (np.arange(PHASES + 1) / PHASES)[:, None] - k[None, :]
    w = np.sinc(d) * (0.5 + 0.5 * np.cos(np.pi * d / (half + 1)))
    return w / w.sum(axis=1, keepdims=True)


def _wow(x: np.ndarray, values: dict, rate: int, fps: float, s0: int) -> np.ndarray:
    """Lê o som com o atraso do wow (sinc de `SINC_TAPS` pontos com janela de Hann, tabela de `PHASES` frações):
    só amostras do passado."""
    n = x.shape[0]
    out = np.empty_like(x)
    half = SINC_TAPS // 2
    k = np.arange(-half + 1, half + 1)
    table = _sinc_table()
    block = 1 << 15
    for b0 in range(0, n, block):
        j = np.arange(b0, min(n, b0 + block))
        pos = j - wow_delay(values, rate, fps, s0 + j)
        i0 = np.floor(pos).astype(np.int64)
        w = table[np.round((pos - i0) * PHASES).astype(np.int64)]
        taps = np.clip(i0[:, None] + k[None, :], 0, n - 1)
        for c in range(x.shape[1]):
            out[j, c] = np.einsum("ij,ij->i", x[taps, c], w)
    return out


# ------------------------------------------------------------------ o que está na película
def _crackle(values: dict, rate: int, s0: int, n: int) -> np.ndarray:
    """Cliques da poeira na trilha: no máximo um por célula, posição, força e sinal sorteados pela semente."""
    sp = float(values.get("somf_poeira", 0.0))
    dust = float(values.get("poeira", 0.0)) if (values.get("desg_on") and values.get("poeira_on")) else DUST_BASE
    p = CRACKLE_RATE * sp * dust * CELL / rate
    if p <= 0:
        return np.zeros(n)
    sd = int(values.get("somf_semente", 19))
    kern = np.exp(-np.arange(64) / 5.0)
    c = np.arange((s0 - 64) // CELL, (s0 + n) // CELL + 1)
    hit = hash_array(c, sd + 701) < p
    c = c[hit]
    pos = c * CELL + np.floor(hash_array(c, sd + 702) * CELL).astype(np.int64)
    amp = (0.015 + 0.25 * hash_array(c, sd + 703) ** 4) * np.where(hash_array(c, sd + 704) < 0.5, -1.0, 1.0)
    imp = np.zeros(n + 64)
    ok = (pos >= s0 - 64) & (pos < s0 + n)
    np.add.at(imp, pos[ok] - s0 + 64, amp[ok])
    return _conv(imp[:, None], kern)[64:, 0]


def _pops(values: dict, rate: int, fps: float, s0: int, n: int, events: Iterable[int]) -> np.ndarray:
    """Estalos das emendas: um clique seco (ruído preso à amostra) e um baque grave, a partir da amostra exata do
    quadro (quadro / fps × taxa)."""
    out = np.zeros(n)
    amt = float(values.get("somf_estalos", 0.0))
    if amt <= 0:
        return out
    sd = int(values.get("somf_semente", 19))
    L = int(POP_S * rate)
    j = np.arange(L)
    for f in events:
        o = int(round(f / fps * rate))
        if o + L <= s0 or o >= s0 + n:
            continue
        h = hash_array(int(f) * 3 + np.arange(3), sd + 801)  # força, sinal e tom do baque deste estalo
        a = 0.55 * amt * (0.7 + 0.3 * h[0])
        sign = 1.0 if h[1] < 0.5 else -1.0
        noise = hash_array(o + j, sd + 811) * 2 - 1
        noise[0] = sign
        click = a * noise * np.exp(-j / (0.0012 * rate))
        f0 = 45.0 + 30.0 * h[2]
        thump = 0.5 * a * sign * np.sin(2 * math.pi * f0 * j / rate) * np.exp(-j / (0.04 * rate))
        p = click + thump
        lo, hi = max(o, s0), min(o + L, s0 + n)
        out[lo - s0:hi - s0] += p[lo - o:hi - o]
    return out


def _film_noise(values: dict, track: Track, rate: int, s0: int, n: int, ch: int) -> np.ndarray:
    """Chiado do grão ou da fita e o ronco grave, presos às amostras absolutas."""
    f = float(values.get("somf_trilha_forca", 1.0))
    out = np.zeros((n, ch))
    if f <= 0:
        return out
    sd = int(values.get("somf_semente", 19))
    idx = np.arange(s0, s0 + n)
    hiss = 10.0 ** (track.hiss_db / 20.0) * f
    for c in range(ch):
        out[:, c] = hiss * white(idx, sd + (901 if track.mono else 901 + c))
    if track.rumble_db > -80:
        out += (10.0 ** (track.rumble_db / 20.0) * f * vnoise_array(idx * (80.0 / rate), sd + 921))[:, None]
    return out


# ------------------------------------------------------------------ projetor e sala
FAN_CURVE = ((60, -30), (150, -8), (300, 0), (1500, -3), (4000, -15), (10000, -35), (20000, -50))


@lru_cache(maxsize=4)
def _click_kernel(rate: int) -> np.ndarray:
    j = np.arange(int(CLICK_S * rate)) / rate
    return (0.6 * np.sin(2 * math.pi * 1900 * j) * np.exp(-j / 0.0015)
            + 0.4 * np.sin(2 * math.pi * 3300 * j + 0.5) * np.exp(-j / 0.0008)
            + 0.3 * np.sin(2 * math.pi * 520 * j) * np.exp(-j / 0.006))


def _projector(values: dict, rate: int, fps: float, s0: int, n: int) -> np.ndarray:
    """O projetor na sala: o mecanismo intermitente (um clique por quadro projetado), o zumbido do motor e a
    ventoinha da lâmpada. Mono (o projetor fica atrás da plateia)."""
    sd = int(values.get("somf_semente", 19))
    pf = projection_fps(values, fps)
    kern = _click_kernel(rate)
    L = len(kern)
    k = np.arange(int(math.floor((s0 - L) / rate * pf)) - 1, int(math.ceil((s0 + n) / rate * pf)) + 2)
    on = np.round(k / pf * rate).astype(np.int64)
    ok = (on >= s0 - L) & (on < s0 + n)
    imp = np.zeros(n + L)
    np.add.at(imp, on[ok] - s0 + L, 0.8 + 0.2 * hash_array(k[ok], sd + 941))
    clicks = _conv(imp[:, None], kern)[L:, 0]
    idx = np.arange(s0, s0 + n)
    t = idx / float(rate)
    ph = hash_array(np.arange(3), sd + 942) * 2 * math.pi
    hum = 0.15 * np.sin(2 * math.pi * 60 * t + ph[0]) + 0.08 * np.sin(2 * math.pi * 120 * t + ph[1]) \
        + 0.04 * np.sin(2 * math.pi * 180 * t + ph[2])
    fan = _conv(white(np.arange(s0 - FIR_TAPS, s0 + n), sd + 931)[:, None],
                _min_phase(FAN_CURVE, 1.0, rate))[FIR_TAPS:, 0]
    return 10.0 ** (-22 / 20.0) * (0.5 * clicks + hum + 0.12 * fan)


@lru_cache(maxsize=4)
def room_ir(rate: int, seed: int) -> np.ndarray:
    """Resposta procedural de uma sala pequena de cinema (L e R diferentes): reflexões iniciais e uma cauda que
    some em ~0,8 s nos graves e ~0,35 s nos agudos. Energia 1 em cada canal."""
    L = int(ROOM_S * rate)
    j = np.arange(L)
    t = j / rate
    pre = int(0.012 * rate)
    out = np.zeros((L, 2))
    for c in range(2):
        n = white(j, seed + 951 + c)
        lp = np.convolve(n, np.ones(12) / 12, mode="full")[:L]
        tail = lp * np.exp(-6.9 * t / 0.8) + (n - lp) * np.exp(-6.9 * t / 0.35)
        tail[:pre] = 0.0
        ir = 0.35 * tail
        h = hash_array(np.arange(6) + 10 * c, seed + 961)
        for r in range(6):
            at = pre + int((0.004 + 0.035 * h[r]) * rate)
            ir[at] += (0.6 - 0.07 * r) * (1 if h[(r + 3) % 6] < 0.5 else -1)
        out[:, c] = ir / math.sqrt(float((ir ** 2).sum()))
    return out


# ------------------------------------------------------------------ o motor
def process(samples: np.ndarray, rate: int, values: dict | None, fps: float, start_sample: int,
            events: Iterable[int] = (), before: np.ndarray | None = None) -> np.ndarray:
    """O som de película sobre `samples` ((n, canais) ou (n,), de −1 a 1), cuja primeira amostra é a amostra absoluta
    `start_sample` (amostra = tempo × taxa desde o quadro 0). `events`: quadros dos estalos (`events_for`), no
    mesmo `fps`. `before`: o som imediatamente antes (até `preroll_samples(rate)` amostras; o que falta é silêncio):
    com ele, o trecho sai igual ao mesmo pedaço do som inteiro processado (a menos do arredondamento da FFT).

    Desligado (`somf_on` falso ou sem valores), devolve `samples` como veio, bit a bit."""
    if not active(values):
        return samples
    v = values
    x = np.asarray(samples, np.float64)
    flat = x.ndim == 1
    if flat:
        x = x[:, None]
    n, ch = x.shape
    fps = float(fps or 24.0)
    P = preroll_samples(rate)
    buf = np.zeros((P + n, ch))
    if before is not None and len(before):
        b = np.asarray(before, np.float64)
        b = (b[:, None] if b.ndim == 1 else b)[-P:]
        buf[P - len(b):P] = b[:, :ch]
    buf[P:] = x
    s0 = int(start_sample) - P
    m = P + n
    track = TRACKS[track_of(v)]
    f = float(v.get("somf_trilha_forca", 1.0))
    if track.mono and ch > 1 and f > 0:
        buf += f * (buf.mean(axis=1, keepdims=True) - buf)
    if float(v.get("somf_wow", 0.0)) > 0:
        buf = _wow(buf, v, rate, fps, s0)
    if f > 0:
        buf += f * (_soft(buf, track.knee) - buf)
    buf += _film_noise(v, track, rate, s0, m, ch)
    buf += (_crackle(v, rate, s0, m) + _pops(v, rate, fps, s0, m, events))[:, None]
    if f > 0:
        buf = _conv(buf, track_filter(v, rate))
    proj = float(v.get("somf_projetor", 0.0))
    if proj > 0:
        buf += proj * _projector(v, rate, fps, s0, m)[:, None]
    room = float(v.get("somf_sala", 0.0))
    if room > 0:
        ir = room_ir(int(rate), int(v.get("somf_semente", 19)))[:, :ch]
        buf = buf * (1.0 - 0.3 * room) + 0.5 * room * _conv(buf, ir)
    out = _soft(buf[P:], LIMIT_KNEE, LIMIT_CEIL)
    return out[:, 0] if flat else out


# ------------------------------------------------------------------ arquivos
def _write_pcm24(wav: wave.Wave_write, x: np.ndarray) -> None:
    q = np.clip(np.round(x * 8388608.0), -8388608, 8388607).astype("<i4")
    wav.writeframes(q.view(np.uint8).reshape(-1, 4)[:, :3].tobytes())


def process_wav(src: str, dst: str, values: dict, fps: float, start_sample: int = 0, events: Iterable[int] = (),
                *, skip: int = 0, before: np.ndarray | None = None, cancel: threading.Event | None = None) -> bool:
    """Processa o WAV `src` em blocos e grava `dst` (PCM 24 bits, mesma taxa e canais). A amostra 0 de `src` é a
    absoluta `start_sample`; `before` é o som antes dela; as primeiras `skip` amostras de `src` só servem de contexto
    e não vão para `dst`. False se foi cancelado (o `dst` incompleto é apagado)."""
    from .audiomix import WavReader
    reader = WavReader(src)
    rate = reader.rate
    events = list(events)
    P = preroll_samples(rate)
    ctx = None if before is None else np.asarray(before, np.float64)[-P:]
    step = int(CHUNK_S * rate)
    with wave.open(dst, "wb") as out:
        out.setnchannels(reader.channels)
        out.setsampwidth(3)
        out.setframerate(rate)
        pos = 0
        while pos < reader.frames:
            if cancel is not None and cancel.is_set():
                break
            x = reader.read(pos, step).astype(np.float64)
            if not len(x):
                break
            y = process(x, rate, values, fps, start_sample + pos, events, before=ctx)
            cut = max(0, skip - pos)
            if cut < len(y):
                _write_pcm24(out, y[cut:])
            ctx = x[-P:] if ctx is None or len(x) >= P else np.concatenate([ctx, x])[-P:]
            pos += len(x)
    if cancel is not None and cancel.is_set():
        _remove(dst)
        return False
    return True


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def decode_range(path: str, out_path: str, start_s: float, dur_s: float, cancel: threading.Event | None = None,
                 perf=None) -> bool:
    """O som do arquivo de `start_s` por `dur_s` s num WAV estéreo de 48 kHz em 24 bits (as mesmas conversões de
    `audiomix.decode_wav`, que a prévia usa). False se não deu (sem som, erro ou cancelado)."""
    from . import media
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-nostdin", "-hide_banner"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.6f}"]
    cmd += ["-t", f"{max(dur_s, 0.001):.6f}", "-i", path, "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(RATE),
            "-c:a", "pcm_s24le", "-f", "wav", out_path]
    kw = (perf or media.Perf()).popen_kwargs()
    if "creationflags" not in kw and media.NO_WINDOW:
        kw["creationflags"] = media.NO_WINDOW
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                **kw)
    except OSError:
        return False
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            _remove(out_path)
            return False
        time.sleep(0.03)
    if proc.returncode != 0:
        _remove(out_path)
        return False
    return True


def _temp_wav(prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".wav")
    os.close(fd)
    return path


def export_sound(values: dict, info, seq, start: int, end: int, mix_path: str | None,
                 cancel: threading.Event | None = None, perf=None) -> str | None:
    """O som de película da exportação do trecho [start, end) (quadros de `info`): um WAV novo (o chamador apaga),
    ou None se não há som. Com montagem, processa a mixagem do trecho (`mix_path`), com a mixagem de um pouco antes
    como contexto; com o arquivo, decodifica o trecho com o contexto antes. As amostras são as da prévia nos mesmos
    instantes (a prévia processa o som inteiro a partir do quadro 0)."""
    fps = float(info.fps or 24.0)
    rate = RATE
    P = preroll_samples(rate)
    events = events_for(values, fps, info.frames, seq)
    s_abs = int(round(start / fps * rate))
    out = _temp_wav("pelicula_somfilme_")
    tmp = None
    try:
        if seq is not None:
            if not mix_path:
                _remove(out)
                return None
            before = None
            first = max(0, start - int(math.ceil(PREROLL_S * fps)) - 1)
            if first < start:
                from . import audiomix
                tmp = _temp_wav("pelicula_somfilme_antes_")
                if audiomix.render_mix(seq, tmp, first, start, cancel, perf):
                    from .audiomix import WavReader
                    r = WavReader(tmp)
                    before = r.read(0, r.frames).astype(np.float64)[-P:]
            ok = process_wav(mix_path, out, values, fps, s_abs, events, before=before, cancel=cancel)
        else:
            t0 = start / fps
            pre = min(PREROLL_S, t0)
            a_abs = int(round((t0 - pre) * rate))
            tmp = _temp_wav("pelicula_somfilme_arquivo_")
            if not decode_range(info.path, tmp, a_abs / rate, (end - start) / fps + (s_abs - a_abs) / rate, cancel,
                                perf):
                _remove(out)
                return None
            ok = process_wav(tmp, out, values, fps, a_abs, events, skip=s_abs - a_abs, cancel=cancel)
        if not ok:
            _remove(out)
            return None
        return out
    except Exception:
        _remove(out)
        raise
    finally:
        if tmp:
            _remove(tmp)
