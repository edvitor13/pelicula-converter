"""Silêncios e "Cortar pelo texto" (sem Qt): trechos de um arquivo para tirar da montagem.

Tudo devolve tempos **do arquivo** (segundos, como `timeline.Clip.src_in`); aplicar os cortes na linha
do tempo é com a montagem (`timeline`), que leva esses trechos para os clipes que os mostram.

Silêncios
---------
O som do trecho é decodificado pelo ffmpeg (mono, 16 kHz, em blocos: a memória não cresce com a duração)
e medido em janelas de 10 ms (`Levels`: RMS e pico em dBFS). Uma janela é silenciosa quando o RMS fica
abaixo do limiar; o limiar é **relativo ao volume do próprio trecho** (o nível alto típico, percentil 95
das janelas com som) — assim a mesma regulagem serve para uma gravação baixa e para uma alta — ou
absoluto em dBFS. Estalos curtos dentro de um silêncio não o quebram (`bridge`); silêncios mais curtos que
`min_duration` ficam; cada silêncio encolhe `padding` do lado que encosta na fala (respiro).

Cortar pelo texto
-----------------
Com as palavras da transcrição (`subtitles.Word`, tempos do arquivo), escolher palavras (índices ou trechos
do texto) dá os trechos a remover: cada sequência de palavras escolhidas vai do fim da palavra que fica
antes até o começo da que fica depois (os vãos somem junto), com uma folga pequena para não comer o começo
ou o fim das palavras vizinhas; trechos encostados viram um só.
"""

from __future__ import annotations

import math
import subprocess
import threading
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .i18n import _

RATE = 16_000              # Hz da análise
WINDOW = 0.01              # s por janela
FLOOR_DB = -120.0          # nível de uma janela muda (dBFS)
REF_PERCENTILE = 95.0      # nível de referência do trecho (o "alto típico")

Range = tuple[float, float]


class SilenceError(RuntimeError):
    """Falha com mensagem para o usuário (PT-BR)."""


@dataclass(frozen=True)
class Levels:
    """Nível do som em janelas de `window` segundos a partir de `start` (tempo do arquivo)."""
    rms_db: np.ndarray
    peak_db: np.ndarray
    window: float = WINDOW
    start: float = 0.0

    @property
    def duration(self) -> float:
        return len(self.rms_db) * self.window

    def reference(self) -> float:
        """Nível alto típico (dBFS) do trecho: o percentil 95 das janelas que têm algum som."""
        live = self.rms_db[self.rms_db > FLOOR_DB + 1]
        return float(np.percentile(live, REF_PERCENTILE)) if live.size else FLOOR_DB


@dataclass(frozen=True)
class Silence:
    start: float               # s do arquivo
    end: float
    level: float               # RMS médio no trecho (dBFS)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _db(x: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return np.maximum(20.0 * np.log10(np.maximum(x, 1e-12)), FLOOR_DB).astype(np.float32)


def _window_stats(samples: np.ndarray, hop: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(samples) // hop
    if n <= 0:
        return np.zeros(0, np.float32), np.zeros(0, np.float32)
    blk = samples[: n * hop].reshape(n, hop).astype(np.float64)
    rms = np.sqrt(np.mean(blk * blk, axis=1))
    peak = np.max(np.abs(blk), axis=1)
    return _db(rms), _db(peak)


def levels_from_samples(samples: np.ndarray, rate: int = RATE, window: float = WINDOW, start: float = 0.0) -> Levels:
    """Níveis de amostras mono (float, -1..1). A última janela incompleta conta se tiver metade ou mais."""
    hop = max(1, int(round(rate * window)))
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    rest = len(x) % hop
    if rest >= hop / 2:
        x = np.concatenate([x, np.zeros(hop - rest, np.float32)])
    rms, peak = _window_stats(x, hop)
    return Levels(rms, peak, hop / rate, start)


def levels(path: str, start: float = 0.0, duration: float = 0.0, window: float = WINDOW,
           cancel: threading.Event | None = None, perf=None) -> Levels:
    """Níveis do som do arquivo no trecho [start, start + duration) (duration 0 = até o fim), lidos do ffmpeg
    em blocos. Levanta SilenceError (mensagem para o usuário) ou tools.Cancelled."""
    from . import media, tools
    cmd = [media.ffmpeg(), "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    cmd += ["-i", path]
    if duration > 0:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"]
    hop = max(1, int(round(RATE * window)))
    block = hop * 4 * 2000                      # 20 s por leitura
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **(perf or media.Perf()).popen_kwargs())
    err: list[bytes] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    rms_parts, peak_parts = [], []
    pending = b""
    try:
        while True:
            if cancel is not None and cancel.is_set():
                tools.kill_tree(proc)
                raise tools.Cancelled()
            data = proc.stdout.read(block)
            if not data:
                break
            pending += data
            usable = len(pending) // (4 * hop) * (4 * hop)
            if usable:
                r, p = _window_stats(np.frombuffer(pending[:usable], dtype="<f4"), hop)
                rms_parts.append(r)
                peak_parts.append(p)
                pending = pending[usable:]
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            tools.kill_tree(proc)
        reader.join(5)
        proc.stdout.close()
    if rc != 0:
        text = b"".join(err).decode("utf-8", "replace").strip()
        if "matches no streams" in text or "does not contain any stream" in text:
            raise SilenceError(_("O arquivo não tem som."))
        raise SilenceError(_("Não foi possível ler o som:\n{erro}").format(erro=text[-1500:]))
    tail = np.frombuffer(pending[: len(pending) // 4 * 4], dtype="<f4")
    if len(tail) >= hop / 2:
        r, p = _window_stats(np.concatenate([tail, np.zeros(hop - len(tail), np.float32)]), hop)
        rms_parts.append(r)
        peak_parts.append(p)
    cat = (lambda parts: np.concatenate(parts) if parts else np.zeros(0, np.float32))
    return Levels(cat(rms_parts), cat(peak_parts), hop / RATE, start)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Trechos [i, j) onde a máscara é verdadeira."""
    if not mask.size:
        return []
    m = np.concatenate([[False], mask.astype(bool), [False]])
    edges = np.flatnonzero(m[1:] != m[:-1])
    return [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2])]


def detect(lv: Levels, threshold: float = -30.0, min_duration: float = 0.5, padding: float = 0.1,
           relative: bool = True, bridge: float = 0.06) -> list[Silence]:
    """Silêncios do trecho medido. `threshold`: dB abaixo do nível do trecho (`relative`) ou dBFS
    absolutos; `min_duration` e `padding` em segundos (veja o cabeçalho do módulo)."""
    n = len(lv.rms_db)
    if n == 0:
        return []
    thr = lv.reference() + threshold if relative else threshold
    thr = min(max(thr, FLOOR_DB + 1), 0.0)
    silent = lv.rms_db < thr
    # estalos curtos (até `bridge`) entre duas partes silenciosas não quebram o silêncio
    gap = max(0, int(round(bridge / lv.window)))
    if gap:
        for a, b in _runs(~silent):
            if 0 < a and b < n and b - a <= gap:
                silent[a:b] = True
    out: list[Silence] = []
    for a, b in _runs(silent):
        t0, t1 = lv.start + a * lv.window, lv.start + b * lv.window
        if t1 - t0 + 1e-9 < min_duration:
            continue
        s = t0 + (padding if a > 0 else 0.0)        # o lado que encosta no som ganha folga
        e = t1 - (padding if b < n else 0.0)
        if e - s <= 1e-9:
            continue
        lin = 10 ** (lv.rms_db[a:b].astype(np.float64) / 20.0)
        level = float(20 * math.log10(max(float(np.sqrt(np.mean(lin * lin))), 1e-12)))
        out.append(Silence(round(s, 6), round(e, 6), max(level, FLOOR_DB)))
    return out


def find_silences(path: str, start: float = 0.0, duration: float = 0.0, threshold: float = -30.0,
                  min_duration: float = 0.5, padding: float = 0.1, relative: bool = True,
                  cancel: threading.Event | None = None, perf=None) -> list[Silence]:
    """Mede o som do arquivo (ffmpeg) e devolve os silêncios em tempo do arquivo."""
    return detect(levels(path, start, duration, cancel=cancel, perf=perf), threshold, min_duration, padding, relative)


def ranges(items: Iterable[Silence]) -> list[Range]:
    return [(s.start, s.end) for s in items]


# ------------------------------------------------------------------ cortar pelo texto
def transcript(words: Sequence) -> str:
    """O texto das palavras separado por espaços (as posições dos trechos de `text_spans` contam aqui)."""
    return " ".join(w.text for w in words)


def word_spans(words: Sequence) -> list[tuple[int, int]]:
    """(início, fim) de cada palavra dentro de `transcript(words)`."""
    out, pos = [], 0
    for w in words:
        out.append((pos, pos + len(w.text)))
        pos += len(w.text) + 1
    return out


def indices_for_text(words: Sequence, spans: Iterable[tuple[int, int]]) -> list[int]:
    """Palavras tocadas por trechos [a, b) do texto de `transcript(words)` (seleção no editor de texto):
    uma palavra entra quando o trecho cobre algum caractere dela (o corte sempre pega palavras inteiras)."""
    pos = word_spans(words)
    chosen = set()
    for a, b in spans:
        a, b = int(a), int(b)
        if b <= a:
            continue
        for i, (s, e) in enumerate(pos):
            if s < b and a < e:
                chosen.add(i)
    return sorted(chosen)


def text_cut_ranges(words: Sequence, selection: Iterable[int], padding: float = 0.03,
                    merge_gap: float = 0.15) -> list[Range]:
    """Trechos do arquivo a remover para tirar as palavras de índice `selection`.

    Cada sequência de palavras escolhidas vai do fim da palavra de antes (+ `padding`) até o começo da de
    depois (− `padding`), sem nunca entrar nelas; sem vizinha, até `padding` além da palavra. Trechos
    separados por menos de `merge_gap` viram um só."""
    ws = sorted(words, key=lambda w: (w.start, w.end))
    n = len(ws)
    chosen = sorted({int(i) for i in selection if 0 <= int(i) < n})
    if not chosen:
        return []
    groups: list[list[int]] = [[chosen[0]]]
    for i in chosen[1:]:
        if i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    out: list[Range] = []
    for g in groups:
        i, j = g[0], g[-1]
        first, last = ws[i], ws[j]
        if i > 0:   # do fim da palavra de antes (com folga), sem passar do começo da primeira escolhida
            prev_end = ws[i - 1].end
            a = max(prev_end, min(prev_end + padding, first.start))
        else:
            a = max(0.0, first.start - padding)
        if j + 1 < n:   # até o começo da palavra de depois (com folga), sem ficar antes do fim da última
            next_start = ws[j + 1].start
            b = max(last.end, next_start - padding)
            if next_start >= last.end:
                b = min(b, next_start)
        else:
            b = last.end + padding
        if b > a:
            out.append((round(a, 6), round(b, 6)))
    merged: list[Range] = []
    for a, b in out:
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def remaining_words(words: Sequence, cuts: Iterable[Range]) -> list:
    """As palavras que sobram depois dos cortes (o meio da palavra fora de todos os trechos)."""
    cuts = list(cuts)
    return [w for w in words if not any(a <= (w.start + w.end) / 2 < b for a, b in cuts)]
