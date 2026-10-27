"""Loudness e picos (ITU-R BS.1770-4 / EBU R128), só com numpy (sem Qt).

Usado pelo medidor de som da prévia (`ui/meter.py`); nada daqui vai para a exportação.

- Ponderação K: os coeficientes da norma em 48 kHz; nas outras taxas, o protótipo analógico
  (prateleira de agudos + passa-altas RLB) levado pela transformação bilinear, como no libebur128.
  Sem scipy, o filtro é aplicado como FIR: a resposta ao impulso dos dois biquads, calculada uma vez
  até cair abaixo de 1e-14, convolvida por FFT em blocos (sobreposição e descarte, com estado).
- Sub-blocos de 100 ms: momentânea = os 4 últimos (400 ms), curta = os 30 últimos (3 s); integrada =
  blocos de 400 ms com 75 % de sobreposição, porta absoluta em −70 LUFS e relativa em −10 LU.
- LRA (EBU Tech 3342): valores curtos (3 s) a cada 100 ms, portas −70 LUFS e −20 LU, percentis 10 e 95.
- Pico de amostra e true peak: interpolador sinc janelado (Kaiser), polifásico, com sobreamostragem
  4× abaixo de 96 kHz e 2× abaixo de 192 kHz.

Unidades: LUFS (loudness), LU (diferenças), dBFS (pico de amostra) e dBTP (true peak).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

OFFSET = -0.691          # constante da BS.1770 (o seno de 1 kHz em −23 dBFS nos dois canais lê −23 LUFS)
ABS_GATE = -70.0         # LUFS
REL_GATE = -10.0         # LU (integrada)
LRA_REL_GATE = -20.0     # LU (Tech 3342)
MOMENTARY = 4            # sub-blocos de 100 ms
SHORT_TERM = 30
TP_TAPS = 32             # coeficientes por fase do interpolador do true peak
TP_BETA = 8.0            # janela de Kaiser do interpolador

# BS.1770-4, tabelas 1 e 2 (48 kHz): (b, a) de cada estágio.
K_48K = (
    ((1.53512485958697, -2.69169618940638, 1.19839281085285), (1.0, -1.69065929318241, 0.73248077421585)),
    ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621)),
)


# ------------------------------------------------------------------ ponderação K
def k_weighting(rate: int) -> tuple:
    """Os dois biquads ((b0, b1, b2), (1, a1, a2)) da ponderação K na taxa `rate`."""
    if int(rate) == 48000:
        return K_48K
    return k_weighting_analog(rate)


def k_weighting_analog(rate: float) -> tuple:
    """Ponderação K a partir do protótipo analógico (transformação bilinear), em qualquer taxa."""
    fs = float(rate)
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / fs)
    vh = 10.0 ** (gain / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf = ((vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0), \
        (1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0)
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / fs)
    a0 = 1.0 + k / q + k * k
    highpass = (1.0, -2.0, 1.0), (1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0)
    return shelf, highpass


def k_response_db(rate: int, freq: float) -> float:
    """Ganho (dB) da ponderação K em `freq` Hz (para testes e documentação)."""
    z = np.exp(-1j * 2.0 * math.pi * freq / rate)
    h = 1.0 + 0.0j
    for b, a in k_weighting(rate):
        h *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20.0 * math.log10(abs(h))


@lru_cache(maxsize=8)
def k_impulse(rate: int) -> np.ndarray:
    """Resposta ao impulso dos dois biquads em série, até tudo ficar abaixo de 1e-14 (no máximo 1 s)."""
    (b1, a1), (b2, a2) = k_weighting(rate)
    limit = max(1024, int(rate))
    out = np.zeros(limit)
    x1 = x2 = y1 = y2 = 0.0
    u1 = u2 = v1 = v2 = 0.0
    quiet = 0
    end = limit
    for n in range(limit):
        x = 1.0 if n == 0 else 0.0
        y = b1[0] * x + b1[1] * x1 + b1[2] * x2 - a1[1] * y1 - a1[2] * y2
        x2, x1, y2, y1 = x1, x, y1, y
        v = b2[0] * y + b2[1] * u1 + b2[2] * u2 - a2[1] * v1 - a2[2] * v2
        u2, u1, v2, v1 = u1, y, v1, v
        out[n] = v
        if n > 64 and max(abs(v), abs(v2), abs(y), abs(y2)) < 1e-14:
            quiet += 1
            if quiet >= 16:
                end = n + 1
                break
        else:
            quiet = 0
    return out[:end].copy()


class _FFTFilter:
    """FIR aplicado por FFT em blocos (sobreposição e descarte), com estado entre chamadas."""

    def __init__(self, h: np.ndarray, channels: int):
        self.h = np.asarray(h, dtype=np.float64)
        self.m = len(self.h)
        self.tail = np.zeros((channels, self.m - 1))
        self._spec: dict[int, np.ndarray] = {}

    def reset(self) -> None:
        self.tail[:] = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """x (canais, n) → filtrado (canais, n)."""
        n = x.shape[1]
        out = np.empty_like(x)
        step = max(self.m, 1 << 15)
        pos = 0
        while pos < n:
            k = min(step, n - pos)
            buf = np.concatenate([self.tail, x[:, pos:pos + k]], axis=1)
            size = 1 << max(1, int(math.ceil(math.log2(buf.shape[1]))))
            spec = self._spec.get(size)
            if spec is None:
                spec = self._spec[size] = np.fft.rfft(self.h, size)
            y = np.fft.irfft(np.fft.rfft(buf, size, axis=1) * spec, size, axis=1)
            out[:, pos:pos + k] = y[:, self.m - 1:self.m - 1 + k]
            self.tail = buf[:, buf.shape[1] - (self.m - 1):]
            pos += k
        return out


# ------------------------------------------------------------------ true peak
def oversampling(rate: int) -> int:
    """4× abaixo de 96 kHz, 2× abaixo de 192 kHz, sem sobreamostragem acima (BS.1770-4, anexo 2)."""
    return 4 if rate < 96000 else 2 if rate < 192000 else 1


@lru_cache(maxsize=4)
def tp_phases(factor: int) -> np.ndarray:
    """Fases (factor × TP_TAPS) do interpolador: sinc janelado; a fase 0 é a própria amostra."""
    taps = factor * TP_TAPS
    c = taps // 2
    j = np.arange(taps)
    h = np.sinc((j - c) / factor) * np.kaiser(taps + 1, TP_BETA)[:taps]
    phases = np.stack([h[p::factor] for p in range(factor)])
    return phases / phases.sum(axis=1, keepdims=True)


class _TruePeak:
    def __init__(self, rate: int, channels: int):
        self.factor = oversampling(rate)
        self.phases = tp_phases(self.factor) if self.factor > 1 else None
        self.hist = np.zeros((channels, TP_TAPS - 1))

    def reset(self) -> None:
        self.hist[:] = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """Maior valor absoluto (linear) entre as amostras sobreamostradas de cada canal."""
        if self.phases is None:
            return np.abs(x).max(axis=1)
        buf = np.concatenate([self.hist, x], axis=1)
        self.hist = buf[:, buf.shape[1] - (TP_TAPS - 1):]
        peak = np.zeros(x.shape[0])
        for c in range(x.shape[0]):
            for g in self.phases:
                peak[c] = max(peak[c], float(np.abs(np.convolve(buf[c], g, mode="valid")).max()))
        return peak


# ------------------------------------------------------------------ medidas
def channel_weights(channels: int) -> np.ndarray:
    """G de cada canal (BS.1770): 1 para L, R e C; 1,41 para os surrounds; o LFE fica de fora (5.1)."""
    if channels == 6:
        return np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41])
    return np.ones(channels)


def lufs(power: float) -> float:
    """Loudness de uma potência ponderada (−inf no silêncio)."""
    return OFFSET + 10.0 * math.log10(power) if power > 0 else -math.inf


def db(x: float) -> float:
    """Valor linear em dB (−inf no zero)."""
    return 20.0 * math.log10(x) if x > 0 else -math.inf


def _lufs_array(power: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return OFFSET + 10.0 * np.log10(power)


def _windows(subs: np.ndarray, k: int) -> np.ndarray:
    """Potência média de cada janela de k sub-blocos seguidos (passo de um sub-bloco)."""
    if len(subs) < k:
        return np.empty(0)
    c = np.concatenate([[0.0], np.cumsum(subs)])
    return (c[k:] - c[:-k]) / k


def gated_integrated(blocks: np.ndarray) -> float | None:
    """Loudness integrada dos blocos de 400 ms (portas −70 LUFS e −10 LU); None se tudo é silêncio."""
    if not len(blocks):
        return None
    keep = blocks[_lufs_array(blocks) > ABS_GATE]
    if not len(keep):
        return None
    rel = lufs(float(keep.mean())) + REL_GATE
    keep = keep[_lufs_array(keep) > rel]
    return lufs(float(keep.mean())) if len(keep) else None


def loudness_range(short_blocks: np.ndarray) -> float | None:
    """LRA (EBU Tech 3342) a partir das potências das janelas de 3 s."""
    if not len(short_blocks):
        return None
    keep = short_blocks[_lufs_array(short_blocks) > ABS_GATE]
    if len(keep) < 2:
        return None
    rel = lufs(float(keep.mean())) + LRA_REL_GATE
    vals = np.sort(_lufs_array(keep[_lufs_array(keep) > rel]))
    if len(vals) < 2:
        return 0.0 if len(vals) else None
    lo = vals[int(round((len(vals) - 1) * 0.10))]
    hi = vals[int(round((len(vals) - 1) * 0.95))]
    return float(hi - lo)


class LoudnessMeter:
    """Medidor contínuo: receba blocos de amostras com `add` e leia as medidas a qualquer momento.

    `reset()` recomeça a medição (busca, nova reprodução). As amostras são float em [−1, 1], com
    forma (n, canais).
    """

    def __init__(self, rate: int = 48000, channels: int = 2):
        self.rate = int(rate)
        self.channels = max(1, int(channels))
        self.weights = channel_weights(self.channels)
        self.step = max(1, int(round(self.rate / 10)))  # 100 ms
        self._k = _FFTFilter(k_impulse(self.rate), self.channels)
        self._tp = _TruePeak(self.rate, self.channels)
        self.reset()

    def reset(self) -> None:
        self._k.reset()
        self._tp.reset()
        self._acc = np.zeros(self.channels)
        self._acc_n = 0
        self._subs = np.zeros(256)
        self._n_subs = 0
        self.samples = 0
        self.sample_peak = np.zeros(self.channels)  # desde o reset (linear)
        self.true_peak = np.zeros(self.channels)
        self.last_peak = np.zeros(self.channels)    # do último bloco recebido

    # ------------------------------------------------------------ entrada
    def _push_subs(self, values: np.ndarray) -> None:
        need = self._n_subs + len(values)
        if need > len(self._subs):
            grown = np.zeros(max(need, 2 * len(self._subs)))
            grown[:self._n_subs] = self._subs[:self._n_subs]
            self._subs = grown
        self._subs[self._n_subs:need] = values
        self._n_subs = need

    def add(self, samples) -> None:
        x = np.asarray(samples, dtype=np.float64)
        if x.ndim == 1:
            x = x[:, None]
        if x.shape[0] == 0:
            return
        if x.shape[1] != self.channels:
            raise ValueError(f"esperava {self.channels} canais, vieram {x.shape[1]}")
        xt = np.ascontiguousarray(x.T)
        peak = np.abs(xt).max(axis=1)
        self.last_peak = peak
        self.sample_peak = np.maximum(self.sample_peak, peak)
        self.true_peak = np.maximum(self.true_peak, np.maximum(self._tp(xt), peak))
        sq = self._k(xt) ** 2
        n = sq.shape[1]
        pos = 0
        if self._acc_n:  # completa o sub-bloco que ficou pela metade
            take = min(self.step - self._acc_n, n)
            self._acc += sq[:, :take].sum(axis=1)
            self._acc_n += take
            pos = take
            if self._acc_n == self.step:
                self._push_subs(np.array([float(self.weights @ (self._acc / self.step))]))
                self._acc[:] = 0.0
                self._acc_n = 0
        full = (n - pos) // self.step
        if full:
            blocks = sq[:, pos:pos + full * self.step].reshape(self.channels, full, self.step).mean(axis=2)
            self._push_subs(self.weights @ blocks)
            pos += full * self.step
        if pos < n:
            self._acc += sq[:, pos:].sum(axis=1)
            self._acc_n += n - pos
        self.samples += n

    # ------------------------------------------------------------ medidas
    @property
    def subblocks(self) -> np.ndarray:
        """Potência ponderada de cada sub-bloco de 100 ms completo."""
        return self._subs[:self._n_subs]

    def _last(self, k: int) -> float | None:
        if self._n_subs < k:
            return None
        return lufs(float(self._subs[self._n_subs - k:self._n_subs].mean()))

    def momentary(self) -> float | None:
        """Loudness momentânea (400 ms); None antes de 400 ms de som."""
        return self._last(MOMENTARY)

    def short_term(self) -> float | None:
        """Loudness de curto prazo (3 s); None antes de 3 s de som."""
        return self._last(SHORT_TERM)

    def integrated(self) -> float | None:
        """Loudness integrada desde o reset (None enquanto não há um bloco acima de −70 LUFS)."""
        return gated_integrated(_windows(self.subblocks, MOMENTARY))

    def loudness_range(self) -> float | None:
        return loudness_range(_windows(self.subblocks, SHORT_TERM))

    def max_momentary(self) -> float | None:
        w = _windows(self.subblocks, MOMENTARY)
        return lufs(float(w.max())) if len(w) else None

    def max_short_term(self) -> float | None:
        w = _windows(self.subblocks, SHORT_TERM)
        return lufs(float(w.max())) if len(w) else None

    def sample_peak_db(self) -> float:
        return db(float(self.sample_peak.max()))

    def true_peak_db(self) -> float:
        return db(float(self.true_peak.max()))


@dataclass
class Measurement:
    integrated: float | None      # LUFS
    lra: float | None             # LU
    momentary_max: float | None   # LUFS
    short_term_max: float | None  # LUFS
    sample_peak: float            # dBFS
    true_peak: float              # dBTP


def measure(samples, rate: int) -> Measurement:
    """Todas as medidas de um trecho inteiro (amostras (n, canais) em [−1, 1])."""
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    m = LoudnessMeter(rate, x.shape[1])
    m.add(x)
    return Measurement(m.integrated(), m.loudness_range(), m.max_momentary(), m.max_short_term(),
                       m.sample_peak_db(), m.true_peak_db())
