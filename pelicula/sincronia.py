"""Sincronizar pelo som (1.8, ARQUITETURA §44.5; sem Qt).

Duas gravações do mesmo momento (o som da câmera e o de um gravador, duas câmeras) ficam alinhadas pelo próprio som:
o trecho usado do clipe de referência é procurado no som do outro, numa janela de ±`SEARCH_S` (no máximo
`MAX_SEARCH_S`) em volta de onde ele está agora.

- **Leitura**: mono a 8 kHz (`somlimpo.read_range`), com pré-ênfase (x[n] − 0,97·x[n−1]) para o pico da correlação
  ficar estreito. Só o trecho em que os dois podem se sobrepor (no máximo `MAX_ANALYSIS_S`): a memória não cresce
  com a duração dos clipes.
- **Correlação cruzada normalizada** por FFT (`find_lag`): para cada atraso, Σ a·b dividido pela energia de `a` e
  pela de `b` sob ele (soma acumulada), então um trecho mais alto de `b` não ganha só por ser alto. O pico (em módulo:
  um microfone com a polaridade invertida também serve) é refinado por uma parábola (fração de amostra).
- **Confiança**: o pico contra o segundo pico (fora de ±`EXCLUDE_S`) e contra o RMS da correlação. Abaixo de
  `MIN_RATIO` ou `MIN_SNR` o clipe não é movido (som sem relação, ritmo repetido, silêncio).
- **Plano** (`plan`): a referência é o som ligado ao vídeo da faixa de vídeo mais baixa (V1 antes de V2), se algum
  grupo escolhido tem vídeo; senão o primeiro escolhido. Cada outro grupo (o clipe e os ligados) anda o atraso
  arredondado para quadros; o resto (abaixo de meio quadro) vai para a mensagem. Quem move é
  `TimelineModel.move_groups` (um passo do desfazer).

Por ora só clipes na velocidade 1×, sem rampa, reverso nem quadro congelado (o tempo do arquivo é o da sequência).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import somlimpo, timeline
from .i18n import _

RATE = 8000
SEARCH_S = 10.0
MAX_SEARCH_S = 60.0
MAX_ANALYSIS_S = 120.0
EXCLUDE_S = 0.05
MIN_RATIO = 1.5
MIN_SNR = 8.0
PRE_EMPHASIS = 0.97


@dataclass(frozen=True)
class Lag:
    """`b` atrasado `samples` em relação a `a`: a[i] ≈ b[i + samples]."""
    samples: float
    peak: float      # correlação normalizada no pico (0–1)
    ratio: float     # pico ÷ segundo pico
    snr: float       # pico ÷ RMS da correlação

    @property
    def ok(self) -> bool:
        return self.ratio >= MIN_RATIO and self.snr >= MIN_SNR


def _emphasis(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float64).reshape(-1)
    return np.concatenate([x[:1], x[1:] - PRE_EMPHASIS * x[:-1]]) if len(x) else x


def find_lag(a: np.ndarray, b: np.ndarray, lo: int, hi: int, rate: int = RATE) -> Lag:
    """O atraso L (amostras, de `lo` a `hi`) com a maior correlação normalizada entre `a` e `b` deslocado. Os dois
    em mono; `b` é zero fora dele."""
    a, b = _emphasis(a), _emphasis(b)
    na, nb = len(a), len(b)
    ea = float(np.dot(a, a))
    if na == 0 or nb == 0 or ea <= 1e-12:
        return Lag(0.0, 0.0, 0.0, 0.0)
    bp = np.concatenate([np.zeros(na), b, np.zeros(na)])   # L' = L + na ≥ 0
    n = 1 << int(np.ceil(np.log2(na + len(bp))))
    corr = np.fft.irfft(np.conj(np.fft.rfft(a, n)) * np.fft.rfft(bp, n), n)
    cs = np.concatenate([[0.0], np.cumsum(bp * bp)])
    lo_, hi_ = max(0, lo + na), min(len(bp) - 1, hi + na)
    if hi_ < lo_:
        return Lag(0.0, 0.0, 0.0, 0.0)
    idx = np.arange(lo_, hi_ + 1)
    energy = cs[np.minimum(idx + na, len(bp))] - cs[idx]
    ncc = np.where(energy > ea * 1e-9, corr[idx] / np.sqrt(ea * np.maximum(energy, 1e-30)), 0.0)
    mag = np.abs(ncc)
    k = int(np.argmax(mag))
    peak = float(mag[k])
    frac = 0.0
    if 0 < k < len(mag) - 1:  # parábola nos três pontos do pico
        y0, y1, y2 = mag[k - 1], mag[k], mag[k + 1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-12:
            frac = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
    ex = int(round(EXCLUDE_S * rate))
    rest = np.concatenate([mag[:max(0, k - ex)], mag[k + ex + 1:]])
    second = float(rest.max()) if len(rest) else 0.0
    rms = float(np.sqrt(np.mean(mag * mag)))
    return Lag(float(idx[k] - na) + frac, peak, peak / max(second, 1e-9), peak / max(rms, 1e-9))


# ------------------------------------------------------------------ na montagem
@dataclass
class Move:
    clip: str              # o clipe de som do grupo (os ligados vão junto)
    frames: int            # deslocamento na sequência (quadros)
    residue: float         # o que sobrou abaixo de um quadro (s)
    lag: Lag


@dataclass
class Plan:
    reference: str | None
    moves: list[Move] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)   # (clipe, motivo para o usuário)


def _has_sound(seq: timeline.Sequence, c: timeline.Clip) -> bool:
    return c.kind == timeline.AUDIO and somlimpo.source_path(seq, c) is not None


def candidates(seq: timeline.Sequence, ids) -> list[timeline.Clip]:
    """O clipe de som de cada grupo escolhido (um por grupo ligado), na ordem da escolha."""
    out: list[timeline.Clip] = []
    seen: set[str] = set()
    for cid in ids:
        c = seq.find(cid)
        if c is None:
            continue
        group = seq.group(c)
        key = c.link or c.id
        if key in seen:
            continue
        snd = c if _has_sound(seq, c) else next((g for g in group if _has_sound(seq, g)), None)
        if snd is not None:
            seen.add(key)
            out.append(snd)
    return out


def reference_of(seq: timeline.Sequence, clips: list[timeline.Clip]) -> timeline.Clip | None:
    """O som ligado ao vídeo da faixa de vídeo mais baixa; sem vídeo nos grupos, o primeiro."""
    best = None
    for c in clips:
        video = [g for g in seq.group(c) if g.kind == timeline.VIDEO]
        if video:
            track = min(v.track for v in video)
            if best is None or track < best[0]:
                best = (track, c)
    return best[1] if best else (clips[0] if clips else None)


def _plain(c: timeline.Clip) -> bool:
    return abs(c.speed - 1.0) < 1e-9 and not c.retimed and not c.frozen


def _read(path: str, t0: float, dur: float, cancel) -> np.ndarray:
    """Mono a `RATE` de [t0, t0 + dur) do arquivo, com zeros antes do começo e depois do fim."""
    n = int(round(dur * RATE))
    out = np.zeros(n)
    skip = int(round(max(0.0, -t0) * RATE))
    if skip >= n:
        return out
    x = somlimpo.read_range(path, max(0.0, t0), (n - skip) / RATE, rate=RATE, channels=1, cancel=cancel)[:, 0]
    out[skip:skip + len(x)] = x[:n - skip]
    return out


def plan(seq: timeline.Sequence, ids, window: float = SEARCH_S, cancel: threading.Event | None = None,
         progress: Callable[[int, int], None] | None = None) -> Plan:
    """O que mover para sincronizar os clipes escolhidos pelo som (nada muda na sequência)."""
    window = max(0.1, min(MAX_SEARCH_S, float(window)))
    clips = candidates(seq, ids)
    ref = reference_of(seq, clips)
    out = Plan(ref.id if ref else None)
    if ref is None:
        return out
    fps = seq.fps
    others = [c for c in clips if c is not ref]
    if not _plain(ref):
        out.refused = [(c.id, _("o clipe de referência tem velocidade, rampa, reverso ou quadro congelado"))
                       for c in others]
        return out
    ref_path = somlimpo.source_path(seq, ref)
    t_r, len_r = ref.start / fps, ref.dur / fps
    for i, o in enumerate(others):
        if cancel is not None and cancel.is_set():
            break
        if progress is not None:
            progress(i, len(others))
        if not _plain(o):
            out.refused.append((o.id, _("tem velocidade, rampa, reverso ou quadro congelado")))
            continue
        t_o, len_o = o.start / fps, o.dur / fps
        s0, s1 = max(t_r, t_o - window), min(t_r + len_r, t_o + len_o + window)
        if s1 - s0 < 0.5:
            out.refused.append((o.id, _("fica longe demais do clipe de referência")))
            continue
        s1 = min(s1, s0 + MAX_ANALYSIS_S)
        a = _read(ref_path, ref.src_in + (s0 - t_r), s1 - s0, cancel)
        b = _read(somlimpo.source_path(seq, o), o.src_in + (s0 - window - t_o), s1 - s0 + 2 * window, cancel)
        if cancel is not None and cancel.is_set():
            break
        lag = find_lag(a, b, 0, int(round(2 * window * RATE)))
        if not lag.ok:
            out.refused.append((o.id, _("o som não bate com o da referência")))
            continue
        delta = window - lag.samples / RATE          # segundos que o clipe anda
        frames = int(round(delta * fps))
        out.moves.append(Move(o.id, frames, delta - frames / fps, lag))
    if progress is not None:
        progress(len(others), len(others))
    return out


__all__ = ["Lag", "Move", "Plan", "find_lag", "candidates", "reference_of", "plan", "SEARCH_S", "MAX_SEARCH_S"]
