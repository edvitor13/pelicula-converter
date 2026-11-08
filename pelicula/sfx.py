"""Efeitos sonoros feitos pelo app (1.8, módulo Beta "efeitos_sonoros"; ARQUITETURA §47): whoosh, swish, riser,
impacto, clique, máquina de escrever e obturador, sintetizados em numpy, sem amostras gravadas.

Um efeito é uma fonte sem arquivo (`timeline.Source` de tipo `"efeito"`, numa faixa de ÁUDIO) com os campos em
`Source.data`: `efeito` (o tipo, `EFFECTS`), `nome`, os ajustes do tipo (`Field`, chaves sem acento) e, posto pelo
"Pôr efeitos sonoros…" (`sfx_auto.py`), `toques`/`retornos` (segundos desde o começo do clipe: as batidas da máquina
de escrever num título) e `auto` (a marca dos clipes postos sozinhos).

**O efeito ocupa o clipe**: como um título, ele se ajusta ao trecho que o clipe mostra (esticar o clipe deixa o
whoosh mais longo; o riser acaba no pico no último quadro; a cauda do impacto cabe no clipe). Clique e obturador têm
o tamanho deles e silêncio depois; a máquina de escrever bate durante o clipe inteiro (`ritmo`) ou nos `toques`.

**Como toca** (o mesmo caminho de todo som da montagem, `audiomix` + `somcache`): `audiomix.segments` trata o clipe
como um clipe de arquivo cuja entrada é um WAV gerado aqui (`effect_input`, como o WAV de uma sequência aninhada ou a
entrada limpa da §44): o nome do WAV sai de tudo que muda as amostras (`VERSION`, os campos, o trecho), ele fica em
`effect_dir()` (`somcache.CONTENT_NAMED_DIRS`) e é gravado antes dos pedaços pelo `somcache.PRERENDER`
(`render_inputs`). Volume, chaves de volume, equalização, balanço, fades, mudo/solo, ganho e balanço da faixa, stems e
o som de película valem sem regra nova; prévia = exportação.

**Determinismo** (regra 2): o ruído sai de um hash inteiro do índice da amostra e da semente (`semente`), nada de
`random` nem relógio; o mesmo efeito no mesmo trecho dá as mesmas amostras. Nível: o pico do efeito inteiro vale
`PEAK × intensidade` (−1 dBFS em 100%: nunca satura).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import timeline
from .generators import Field
from .i18n import N_, _

KIND = "efeito"             # `timeline.SOURCE_KINDS`
RATE = 48000
VERSION = 1                 # muda quando a síntese muda (os WAVs de antes deixam de valer)
PEAK = 10.0 ** (-1.0 / 20)  # pico com intensidade 100% (−1 dBFS)
MARGIN_S = 0.1              # silêncio antes e depois do efeito no WAV (rampa e reverso pedem sobra)
END_FADE_S = 0.004          # o fim do trecho nunca corta o som de repente
EFFECT_DIR = "pelicula_som_efeitos"
EFFECT_MAX_BYTES = 512 * 1024 ** 2
N_FFT = 1024                # ruído moldado: quadros da STFT
HOP = N_FFT // 4
NOISE_BLOCK = 512          # quadros da STFT por vez
MAX_SECONDS = 120.0        # um efeito mais longo que isso fica em silêncio depois (memória limitada)


# ------------------------------------------------------------------ catálogo
@dataclass(frozen=True)
class Effect:
    id: str                          # ASCII, gravado no projeto: nunca renomear
    label: str                       # N_(): menu "Novo ▸ Efeito sonoro" e o nome na Mídia
    seconds: float                   # duração do clipe novo
    fields: tuple[Field, ...]
    synth: Callable[[dict, int, int], np.ndarray]   # (valores, amostras, semente) → (n, 2) float64 sem nível
    tip: str = ""


def _common(intensity: float = 0.7, bright: float = 0.5, width: float = 0.5) -> tuple[Field, ...]:
    return (Field("intensidade", N_("Intensidade"), "numero", intensity, 0.0, 1.0, 0.01, 2,
                  tip=N_("O pico do efeito: 100% chega a −1 dBFS, sem saturar.")),
            Field("brilho", N_("Brilho"), "numero", bright, 0.0, 1.0, 0.01, 2,
                  tip=N_("Mais grave (0%) ou mais agudo (100%).")),
            Field("largura", N_("Largura estéreo"), "numero", width, 0.0, 1.0, 0.01, 2,
                  tip=N_("0% é mono, no centro; mais que isso abre o som e o movimento entre os lados.")),
            Field("semente", N_("Variação"), "numero", 1, 0, 9999, 1, 0,
                  tip=N_("Outro número dá outra versão do mesmo efeito (o mesmo número sempre soa igual).")))


# ------------------------------------------------------------------ ruído determinístico
def _hash(idx: np.ndarray, seed: int) -> np.ndarray:
    """Hash inteiro de 32 bits do índice e da semente (lowbias32): igual em qualquer computador."""
    x = np.asarray(idx, np.uint64).astype(np.uint32) * np.uint32(0x9E3779B1)
    x ^= np.uint32((int(seed) * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF)
    x ^= x >> np.uint32(16)
    x *= np.uint32(0x7FEB352D)
    x ^= x >> np.uint32(15)
    x *= np.uint32(0x846CA68B)
    x ^= x >> np.uint32(16)
    return x


def white(n: int, seed: int) -> np.ndarray:
    """Ruído branco de −1 a 1 (n amostras), só do índice e da semente."""
    return _hash(np.arange(int(n)), seed).astype(np.float64) / 2147483648.0 - 1.0


def _unit(seed: int, k: int) -> float:
    """Um sorteio de 0 a 1 (o k-ésimo da semente)."""
    return float(_hash(np.array([k]), seed)[0]) / 4294967296.0


_WIN = np.sin(np.pi * (np.arange(N_FFT) + 0.5) / N_FFT)  # seno: janela de análise e de síntese (soma² = 2 no salto)
_FREQS = np.fft.rfftfreq(N_FFT, 1.0 / RATE)


def shaped_noise(n: int, seed: int, center: Callable[[np.ndarray], np.ndarray], octaves: float,
                 tilt: float = 0.0) -> np.ndarray:
    """Ruído (n amostras) por um passa-banda que anda no tempo: em cada quadro da STFT, um sino no logaritmo da
    frequência em volta de `center(u)` (Hz; u = 0…1, o tempo do quadro) com `octaves` de largura (meia altura), e
    `tilt` dB por oitava acima de 1 kHz. Tudo vetorizado; reconstrução exata do ruído com a máscara = 1."""
    n = int(n)
    if n <= 0:
        return np.zeros(0)
    frames = -(-(n + N_FFT) // HOP)
    total = (frames - 1) * HOP + N_FFT
    x = white(total, seed)
    lf = np.log2(np.maximum(_FREQS, 1.0))[None, :]
    sigma = max(octaves, 0.05) / 2.3548
    hops = N_FFT // HOP
    out = np.zeros((frames + hops - 1, HOP))  # a saída em blocos de HOP amostras (sobreposição e soma por fatias)
    for f0 in range(0, frames, NOISE_BLOCK):  # em blocos de quadros: memória limitada num efeito longo
        f1 = min(frames, f0 + NOISE_BLOCK)
        fr = np.arange(f0, f1)
        idx = fr[:, None] * HOP + np.arange(N_FFT)[None, :]
        spec = np.fft.rfft(x[idx] * _WIN, axis=1)
        u = np.clip(((fr * HOP + N_FFT / 2) - N_FFT) / max(1, n), 0.0, 1.0)
        fc = np.maximum(np.asarray(center(u), np.float64), 20.0)
        mask = np.exp(-0.5 * ((lf - np.log2(fc)[:, None]) / sigma) ** 2)
        if tilt:
            mask *= 10.0 ** (tilt * np.maximum(lf - 10.0, 0.0) / 20.0)
        mask[:, 0] = 0.0
        y = np.fft.irfft(spec * mask, n=N_FFT, axis=1) * _WIN
        for k in range(hops):
            out[f0 + k: f1 + k] += y[:, k * HOP:(k + 1) * HOP]
    return out.reshape(-1)[N_FFT: N_FFT + n] / 2.0  # janela seno² com salto de N/4: a soma é 2


def _frames_curve(n: int, fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Uma curva por amostra a partir de u = 0…1."""
    return fn(np.arange(int(n)) / max(1, int(n) - 1))


def _bump(u: np.ndarray, peak: float) -> np.ndarray:
    """Sobe de 0 a 1 até `peak` e desce de volta a 0 no fim (seno², sem quina)."""
    u = np.clip(u, 0.0, 1.0)
    up = np.sin(0.5 * np.pi * np.clip(u / peak, 0, 1)) ** 2
    down = np.cos(0.5 * np.pi * np.clip((u - peak) / max(1e-9, 1 - peak), 0, 1)) ** 2
    return np.where(u < peak, up, down)


def _pan(x: np.ndarray, p: np.ndarray | float) -> np.ndarray:
    """Mono → estéreo com potência constante (p de −1 a 1; 0 = os dois lados em 1)."""
    a = (np.asarray(p, np.float64) + 1.0) * np.pi / 4.0
    return np.stack([x * np.cos(a) * math.sqrt(2.0), x * np.sin(a) * math.sqrt(2.0)], axis=1)


def _wide(mid: np.ndarray, side: np.ndarray, width: float, pan: np.ndarray | float = 0.0) -> np.ndarray:
    """Estéreo de um sinal e de um gêmeo descorrelacionado (`side`): a largura abre os dois lados."""
    st = _pan(mid, pan)
    s = side * (0.45 * width)
    return st + np.stack([s, -s], axis=1)


def _decay(n: int, tau: float, attack: float = 0.0015) -> np.ndarray:
    """Envelope exponencial (τ em s) com um ataque curto (sem estalo no começo)."""
    t = np.arange(int(n)) / RATE
    env = np.exp(-t / max(tau, 1e-4))
    if attack > 0:
        env *= np.clip(t / attack, 0.0, 1.0)
    return env


def _sweep(freq: np.ndarray) -> np.ndarray:
    """Fase acumulada de uma frequência que muda a cada amostra."""
    return 2.0 * np.pi * np.cumsum(freq) / RATE


def _place(out: np.ndarray, sound: np.ndarray, at: int) -> None:
    """Soma `sound` (m, 2) em `out` a partir da amostra `at` (o que passa do fim fica de fora)."""
    if at >= len(out) or at + len(sound) <= 0:
        return
    a = max(0, at)
    b = min(len(out), at + len(sound))
    out[a:b] += sound[a - at: b - at]


# ------------------------------------------------------------------ os efeitos
def _whoosh_like(v: dict, n: int, seed: int, peak: float, lo: float, hi: float) -> np.ndarray:
    b = float(v["brilho"])
    f_lo = lo * 2.0 ** (b - 0.5)
    f_hi = hi * 2.0 ** (2.0 * (b - 0.5))

    def center(u):
        return f_lo * (f_hi / f_lo) ** _bump(u, peak)

    mid = shaped_noise(n, seed, center, 1.3)
    side = shaped_noise(n, seed + 7919, center, 1.3)
    env = _frames_curve(n, lambda u: _bump(u, peak) ** 1.6)
    w = float(v["largura"])
    pan = _frames_curve(n, lambda u: w * (2.0 * u - 1.0))  # passa da esquerda para a direita
    return _wide(mid * env, side * env, w, pan)


def synth_whoosh(v: dict, n: int, seed: int) -> np.ndarray:
    """Whoosh: ruído num passa-banda que sobe e desce (o "doppler" de algo que passa) e anda de um lado ao outro."""
    return _whoosh_like(v, n, seed, 0.62, 300.0, 3800.0)


def synth_swish(v: dict, n: int, seed: int) -> np.ndarray:
    """Swish: um whoosh curto e mais agudo, que chega rápido ao pico."""
    return _whoosh_like(v, n, seed, 0.42, 650.0, 7000.0)


def synth_riser(v: dict, n: int, seed: int) -> np.ndarray:
    """Riser: ruído que sobe de tom e de volume com um tom em glissando (três oitavas), terminando no pico."""
    b = float(v["brilho"])
    top = 6500.0 * 2.0 ** (b - 0.5)

    def center(u):
        return 220.0 * (top / 220.0) ** (u ** 1.3)

    w = float(v["largura"])
    rise = _frames_curve(n, lambda u: u ** 2.2)
    noise = _wide(shaped_noise(n, seed, center, 1.6) * rise, shaped_noise(n, seed + 7919, center, 1.6) * rise, w)
    out = noise * 0.7
    if v["tom"]:
        u = np.arange(n) / max(1, n - 1)
        base = 110.0 * 2.0 ** ((b - 0.5) + 3.0 * u ** 1.5)
        amp = u ** 2.0
        for side, cents in ((0, -4.0), (1, 4.0)):  # um pouco desafinado entre os lados: largura
            f = base * 2.0 ** (cents * w / 1200.0)
            ph = _sweep(f)
            tone = sum(np.sin(k * ph) / k for k in (1, 2, 3, 4))
            out[:, side] += 0.35 * tone * amp
    return out


def synth_impact(v: dict, n: int, seed: int) -> np.ndarray:
    """Impacto: um estrondo grave que cai de tom, o golpe (ruído curto e brilhante) e uma cauda que cabe no clipe."""
    t = np.arange(n) / RATE
    T = n / RATE
    b = float(v["brilho"])
    w = float(v["largura"])
    f = 38.0 + 60.0 * np.exp(-t / 0.07)
    ph = _sweep(f)
    boom = (np.sin(ph) + 0.25 * np.sin(2 * ph)) * _decay(n, min(0.55, max(0.08, T / 3.0)), 0.002)
    hit_c = 2600.0 * 2.0 ** (2.0 * (b - 0.5))
    hit = _wide(shaped_noise(n, seed, lambda u: np.full_like(u, hit_c), 3.0),
                shaped_noise(n, seed + 7919, lambda u: np.full_like(u, hit_c), 3.0), w) * _decay(n, 0.014)[:, None]
    tail_c = 380.0 * 2.0 ** (b - 0.5)
    tail = _wide(shaped_noise(n, seed + 31, lambda u: np.full_like(u, tail_c), 2.6),
                 shaped_noise(n, seed + 8111, lambda u: np.full_like(u, tail_c), 2.6), w)
    tail *= _decay(n, max(0.05, T / 4.0), 0.004)[:, None]
    g = float(v["grave"])
    return _pan(boom * (0.3 + 1.2 * g), 0.0) + hit * 0.9 + tail * 0.45


def _click(n: int, seed: int, freq: float, decay: float, noise_decay: float, width: float, k: int = 0) -> np.ndarray:
    """Um clique curto: um seno amortecido e um sopro de ruído (estéreo pela largura)."""
    t = np.arange(n) / RATE
    tone = np.sin(2 * np.pi * freq * t) * _decay(n, decay, 0.0003)
    nz = white(n, seed + 101 * k) * _decay(n, noise_decay, 0.0002)
    nz2 = white(n, seed + 101 * k + 53) * _decay(n, noise_decay, 0.0002)
    return _wide(0.8 * tone + 0.6 * nz, nz2, width)


def synth_click(v: dict, n: int, seed: int) -> np.ndarray:
    """Clique de interface ou de texto: dois toques muito curtos (8 ms entre eles); o resto do clipe é silêncio."""
    out = np.zeros((n, 2))
    f = 2400.0 * 2.0 ** (1.5 * (float(v["brilho"]) - 0.5))
    m = int(0.03 * RATE)
    w = float(v["largura"])
    _place(out, _click(m, seed, f, 0.003, 0.0012, w), 0)
    _place(out, 0.35 * _click(m, seed, f * 1.4, 0.002, 0.0008, w, 1), int(0.008 * RATE))
    return out


def _key_hit(seed: int, k: int, bright: float, width: float, pan: float) -> np.ndarray:
    """Uma tecla da máquina de escrever: o estalo do tipo no papel, o corpo da tecla e o "clac" do mecanismo."""
    m = int(0.07 * RATE)
    t = np.arange(m) / RATE
    body_f = 170.0 + 90.0 * _unit(seed, 3 * k)
    clack_f = (1200.0 + 600.0 * _unit(seed, 3 * k + 1)) * 2.0 ** (bright - 0.5)
    body = np.sin(2 * np.pi * body_f * t) * _decay(m, 0.022, 0.0008)
    clack = np.sin(2 * np.pi * clack_f * t) * _decay(m, 0.007, 0.0003)
    snap = white(m, seed + 977 * k) * _decay(m, 0.0016, 0.0001)
    snap2 = white(m, seed + 977 * k + 13) * _decay(m, 0.0016, 0.0001)
    gain = 0.8 + 0.4 * _unit(seed, 3 * k + 2)
    return _wide((0.7 * body + 0.5 * clack + 0.9 * snap) * gain, snap2 * gain, width, pan)


def _bell(seed: int, bright: float) -> np.ndarray:
    """O sino do fim da linha (parciais de um sino pequeno)."""
    m = int(0.9 * RATE)
    t = np.arange(m) / RATE
    f0 = 2100.0 * 2.0 ** (0.5 * (bright - 0.5))
    x = sum(a * np.sin(2 * np.pi * f0 * r * t) * _decay(m, d, 0.0005)
            for r, a, d in ((1.0, 1.0, 0.45), (2.76, 0.45, 0.2), (5.4, 0.25, 0.08)))
    return _pan(0.5 * x, 0.0)


def _carriage(seed: int, width: float) -> np.ndarray:
    """O retorno do carro: a catraca (seis estalos) e o deslizar."""
    m = int(0.42 * RATE)
    out = np.zeros((m, 2))
    for j in range(6):
        _place(out, 0.5 * _click(int(0.03 * RATE), seed + 400, 900.0 + 80 * j, 0.004, 0.002, width, j),
               int((0.02 + 0.03 * j) * RATE))
    slide = shaped_noise(m, seed + 600, lambda u: 700.0 + 900.0 * u, 2.0) * _bump(np.arange(m) / m, 0.3)
    return out + _pan(0.6 * slide, np.linspace(width, -width, m))


LINE_KEYS = 30          # teclas por linha quando a máquina bate sozinha (o sino e o retorno depois)
RETURN_PAUSE_S = 0.55   # a pausa do retorno do carro


def typewriter_times(v: dict, seconds: float, seed: int) -> tuple[list[float], list[float]]:
    """(toques, retornos) em segundos: os gravados em `v` (`toques`, `retornos`, do "Pôr efeitos sonoros…") ou, sem
    eles, `ritmo` teclas por segundo com um pouco de irregularidade e um retorno a cada `LINE_KEYS` teclas."""
    hits = _times(v.get("toques"))
    if hits:
        return hits, _times(v.get("retornos"))
    rate = max(1.0, float(v["ritmo"]))
    out, rets = [], []
    t, k = 0.03, 0
    while t < seconds - 0.04 and k < 100000:
        out.append(t)
        k += 1
        if v["sino"] and k % LINE_KEYS == 0:
            rets.append(t + 0.06)
            t += RETURN_PAUSE_S
        t += (1.0 + 0.5 * (_unit(seed, 7000 + k) - 0.5)) / rate
    return out, rets


def _times(value: Any) -> list[float]:
    """Uma lista de tempos (s) do JSON, conferida e em ordem."""
    if not isinstance(value, list):
        return []
    out = []
    for x in value:
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and f >= 0:
            out.append(f)
    return sorted(out)


def synth_typewriter(v: dict, n: int, seed: int) -> np.ndarray:
    """Máquina de escrever: uma tecla por toque, o carro andando da esquerda para a direita, e o sino com o retorno
    no fim de cada linha."""
    out = np.zeros((n, 2))
    hits, rets = typewriter_times(v, n / RATE, seed)
    w = float(v["largura"])
    b = float(v["brilho"])
    line_start = 0.0
    nxt = iter(rets)
    ret = next(nxt, None)
    clicks = v["tecla"] == "clique"
    click = synth_click(v, int(0.03 * RATE), seed) if clicks else None
    for k, t in enumerate(hits):
        while ret is not None and ret <= t:
            line_start = ret
            ret = next(nxt, None)
        if clicks:  # um clique por letra (o mesmo de "Clique", um pouco variado no volume)
            _place(out, click * (0.8 + 0.4 * _unit(seed, 3 * k + 2)), int(round(t * RATE)))
            continue
        pos = min(1.0, (t - line_start) * 0.12)  # o carro anda: a tecla soa mais à direita ao longo da linha
        _place(out, _key_hit(seed, k, b, w, w * (2.0 * pos - 1.0) * 0.6), int(round(t * RATE)))
    if v["sino"] and not clicks:
        for t in rets:
            _place(out, _bell(seed, b) * 0.6, int(round(t * RATE)))
            _place(out, _carriage(seed, w) * 0.8, int(round((t + 0.12) * RATE)))
    return out


def synth_shutter(v: dict, n: int, seed: int) -> np.ndarray:
    """Obturador de câmera: o estalo de abrir (com a batida do espelho) e o de fechar, `intervalo` ms depois."""
    out = np.zeros((n, 2))
    w = float(v["largura"])
    b = float(v["brilho"])
    m = int(0.12 * RATE)
    t = np.arange(m) / RATE
    for j, (at, gain) in enumerate(((0.0, 1.0), (float(v["intervalo"]) / 1000.0, 0.8))):
        thump = np.sin(2 * np.pi * (110.0 + 30 * j) * t) * _decay(m, 0.03, 0.001)
        click = _click(m, seed, (850.0 + 250 * j) * 2.0 ** (b - 0.5), 0.012, 0.003, w, j)
        _place(out, gain * (click + _pan(0.6 * thump, 0.0)), int(round(at * RATE)))
    return out


EFFECTS: dict[str, Effect] = {
    "whoosh": Effect("whoosh", N_("Whoosh"), 1.0, _common(), synth_whoosh,
                     N_("Algo passando rápido: ruído que sobe e desce e cruza de um lado ao outro.")),
    "swish": Effect("swish", N_("Swish"), 0.4, _common(0.6, 0.6), synth_swish,
                    N_("Um whoosh curto e agudo, para a entrada de um título ou um movimento rápido.")),
    "riser": Effect("riser", N_("Riser"), 3.0,
                    _common() + (Field("tom", N_("Tom subindo"), "bool", True,
                                       tip=N_("Um tom que sobe junto com o ruído.")),),
                    synth_riser, N_("Tensão que cresce até o pico no fim do clipe: ponha antes de um corte forte.")),
    "impacto": Effect("impacto", N_("Impacto"), 2.0,
                      _common(0.8, 0.4) + (Field("grave", N_("Grave"), "numero", 0.7, 0.0, 1.0, 0.01, 2,
                                                 tip=N_("Quanto do estrondo grave entra.")),),
                      synth_impact, N_("Um golpe grave com cauda: para um corte seco ou uma revelação.")),
    "clique": Effect("clique", N_("Clique"), 0.2, _common(0.5, 0.6, 0.3), synth_click,
                     N_("Um clique curto de interface ou de texto.")),
    "maquina": Effect("maquina", N_("Máquina de escrever"), 3.0,
                      _common(0.6, 0.5, 0.4) + (
                          Field("ritmo", N_("Teclas por segundo"), "numero", 9.0, 2.0, 20.0, 0.5, 1,
                                tip=N_("A velocidade de quem datilografa (sem as batidas de um título).")),
                          Field("sino", N_("Sino e retorno do carro"), "bool", True,
                                tip=N_("O sino e o retorno do carro no fim de cada linha.")),
                          Field("tecla", N_("Som das teclas"), "escolha", "maquina",
                                choices=(("maquina", N_("Máquina de escrever")), ("clique", N_("Clique"))),
                                tip=N_("Teclas de máquina de escrever ou um clique curto por letra (sem sino)."))),
                      synth_typewriter, N_("Teclas de uma máquina de escrever durante o clipe, com o sino no fim da "
                                           "linha.")),
    "obturador": Effect("obturador", N_("Obturador"), 0.5,
                        _common(0.6, 0.5, 0.3) + (Field("intervalo", N_("Abrir → fechar"), "numero", 90.0, 30.0,
                                                        300.0, 1.0, 0, " ms",
                                                        tip=N_("O tempo entre os dois estalos do obturador.")),),
                        synth_shutter, N_("O obturador de uma câmera fotográfica: dois estalos mecânicos.")),
}
MENU_ORDER = ("whoosh", "swish", "riser", "impacto", "clique", "maquina", "obturador")


def effect_of(src: timeline.Source | None) -> Effect | None:
    """O efeito de uma fonte (None se não é um efeito sonoro conhecido)."""
    if src is None or src.kind != KIND:
        return None
    return EFFECTS.get(str(src.data.get("efeito") or ""))


def values(eff: Effect, data: dict) -> dict:
    """Os campos do efeito com os valores de `data` conferidos (o que faltar fica no padrão); `toques`/`retornos`
    seguem conferidos quando há."""
    out = {f.key: f.clean(data.get(f.key, f.default)) for f in eff.fields}
    for key in ("toques", "retornos"):
        if key in data:
            out[key] = _times(data[key])
    return out


def new_source(effect_id: str, seq: timeline.Sequence, **overrides) -> timeline.Source:
    """Fonte nova do efeito (sem fim, como um título: o clipe dá a duração; o som é só de áudio)."""
    eff = EFFECTS[effect_id]
    data: dict[str, Any] = {"nome": _(eff.label), "efeito": eff.id}
    data.update({f.key: f.default for f in eff.fields})
    data.update(overrides)
    src = timeline.Source.virtual(KIND, seq.width, seq.height, seq.fps_str, seconds=None, data=data, alpha=False)
    src.has_video, src.has_audio = False, True
    src.pix_fmt = ""
    src.audio_codec = "pcm_f32le"
    return src


def default_seconds(src: timeline.Source) -> float:
    """Duração do clipe novo de um efeito (`timeline.DEFAULT_SECONDS`)."""
    eff = effect_of(src)
    return eff.seconds if eff is not None else timeline.IMAGE_SECONDS


# ------------------------------------------------------------------ síntese
def render(data: dict, n: int) -> np.ndarray:
    """O efeito de `data` em `n` amostras (48 kHz estéreo, float32), com um fade de `END_FADE_S` no fim (o trecho
    nunca termina num degrau) e o pico em `PEAK × intensidade`. Passando de `MAX_SECONDS`, o resto é silêncio. Tipo
    desconhecido: silêncio."""
    n = max(0, int(n))
    eff = EFFECTS.get(str(data.get("efeito") or ""))
    if eff is None or n == 0:
        return np.zeros((n, 2), np.float32)
    v = values(eff, data)
    k = min(n, int(MAX_SECONDS * RATE))
    x = np.asarray(eff.synth(v, k, int(v["semente"])), np.float64).reshape(k, 2)
    m = min(k, int(END_FADE_S * RATE))
    if m > 0:
        x[k - m:] *= np.linspace(1.0, 0.0, m)[:, None]
    peak = float(np.max(np.abs(x)))
    out = np.zeros((n, 2), np.float32)
    if peak > 1e-12:
        out[:k] = x * (PEAK * float(v["intensidade"]) / peak)
    return out


# ------------------------------------------------------------------ na mixagem (`audiomix.segments` + `somcache`)
def effect_dir() -> Path:
    """Pasta dos WAVs dos efeitos, no temporário do sistema (como a das sequências aninhadas)."""
    return Path(tempfile.gettempdir()) / EFFECT_DIR


def sound_data(data: dict) -> dict:
    """Os dados que mudam o som (o nome e a marca `auto` não): o nome do WAV e `audiomix.mix_key`."""
    eff = EFFECTS.get(str(data.get("efeito") or ""))
    return {"efeito": eff.id, **values(eff, data)} if eff is not None else {"efeito": None}


def effect_path(data: dict, before: int, body: int, after: int) -> str:
    """O WAV do efeito: `before` amostras de silêncio, o efeito em `body` amostras e `after` de silêncio."""
    name = hashlib.sha1(json.dumps([VERSION, sound_data(data), before, body, after],
                                   sort_keys=True).encode("utf-8")).hexdigest()
    return str(effect_dir() / f"{name}.wav")


def effect_input(seg: dict, seq: timeline.Sequence) -> float:
    """Gancho de `audiomix.segments` para um clipe de efeito: a entrada do clipe vira o WAV do efeito sobre o trecho
    da fonte que o clipe mostra (`Sequence.source_range`), com `MARGIN_S` de silêncio além dele e além das sobras de
    uma transição de som; os tempos do "arquivo" passam a contar do começo do WAV (`src_in`; numa rampa/reverso, os
    pedaços e o tamanho), como `somlimpo.clean_input`. `seg["sfx"]` leva o que `render_inputs` precisa. Devolve a
    duração do WAV (s), o tamanho do "arquivo" para a limpeza do som que vem depois."""
    c: timeline.Clip = seg["clip"]
    src = seq.sources[c.src]
    a, b = seq.source_range(c)
    if seg.get("pieces"):
        ext = [t for p in seg["pieces"] for t in (p[2], p[3])]
        sa, sb = min(ext), max(ext)
    else:
        sa, sb = seg["src_in"], seg["src_in"] + seg["src_len"]
    lo = max(0.0, min(a, sa) - MARGIN_S)
    hi = max(b, sb) + MARGIN_S
    before = int(round((a - lo) * RATE))
    body = max(1, int(round((b - a) * RATE)))
    after = max(0, int(round((hi - lo) * RATE)) - before - body)
    seg["sfx"] = {"data": copy.deepcopy(src.data), "before": before, "body": body, "after": after}
    seg["path"] = effect_path(src.data, before, body, after)
    seg["src_in"] = max(0.0, seg["src_in"] - lo)
    if seg.get("pieces"):
        seg["pieces"] = [(xa, xb, s0 - lo, s1 - lo) for xa, xb, s0, s1 in seg["pieces"]]
    total = (before + body + after) / RATE
    if seg.get("pieces"):
        seg["length"] = total
    return total


def write_effect(job: dict, path: str) -> None:
    """Grava o WAV float32 de um `seg["sfx"]` (num parcial; troca no fim)."""
    from .somcache import WavWriter
    part = f"{path[:-4]}.{os.getpid()}_{threading.get_ident()}.wav"
    try:
        with WavWriter(part, float32=True) as w:
            w.write(np.zeros((job["before"], 2), np.float32))
            w.write(render(job["data"], job["body"]))
            w.write(np.zeros((job["after"], 2), np.float32))
        os.replace(part, path)
    finally:
        try:
            os.remove(part)
        except OSError:
            pass


def render_inputs(segs: list[dict], cancel: threading.Event | None = None, perf=None) -> bool:
    """`somcache.PRERENDER`: deixa prontos os WAVs dos efeitos dos segmentos (antes da limpeza do som, que pode ler
    um deles). False se foi cancelado."""
    wanted = {seg["path"]: seg["sfx"] for seg in segs if seg.get("sfx")}
    if not wanted:
        return True
    effect_dir().mkdir(parents=True, exist_ok=True)
    from . import audiomix
    audiomix._prune_dir(effect_dir(), set(wanted), EFFECT_MAX_BYTES)
    for path, job in wanted.items():
        if cancel is not None and cancel.is_set():
            return False
        if os.path.exists(path):
            try:
                os.utime(path)
            except OSError:
                pass
            continue
        write_effect(job, path)
    return True


def uses_effects(seq: timeline.Sequence) -> bool:
    """A montagem usa um efeito sonoro (recurso `"efeito_sonoro"` do formato 6)?"""
    return any(s.kind == KIND for s in seq.used_sources())


timeline.DEFAULT_SECONDS[KIND] = default_seconds
