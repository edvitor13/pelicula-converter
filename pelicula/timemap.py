"""Tempo de um clipe: instante da saída → segundo do arquivo, com velocidade, rampa e reverso. Puro e exato.

A **rampa de velocidade** de um clipe (`timeline.Clip.ramp`) é uma lista de âncoras `(s, r)`: no segundo `s` do
arquivo a velocidade relativa é `r` (multiplica a `velocidade` do clipe). Presas à imagem, as âncoras não mudam
quando o clipe é aparado, dividido, movido ou acelerado. Entre duas âncoras a velocidade muda em linha reta no
tempo da saída (como numa rampa do Resolve); na conta, r² é linear em s, e cada trecho tem forma fechada (sem
integração numérica, igual em toda máquina):

- G(s) = ∫ ds / r(s): o "tempo de saída a 1×" desde a primeira âncora até s;
- no trecho k (âncoras s_k e s_{k+1}, Δ = s_{k+1} − s_k, b = (r_{k+1}² − r_k²) / Δ), com x = s − s_k:
  g = 2x / (r_k + √(r_k² + b·x)); o inverso é x = r_k·g + (b/4)·g²;
- antes da primeira âncora e depois da última a velocidade fica constante (r_0 e r_n).

Com velocidade V e entrada `src_in` (o segundo do arquivo no começo do clipe), o arquivo no instante x da saída
(segundos desde o começo do clipe) é G⁻¹(G(src_in) + V·x); no **reverso**, G⁻¹(G(src_in) − V·x): o arquivo corre
para trás a partir de `src_in`, que no reverso é o ponto mais alto do trecho usado. Sem rampa nem reverso a conta
é a de sempre, `src_in + V·x`, e `timeline.Sequence` nem passa por aqui (os mesmos bits de antes).

Quem usa: só `timeline.Sequence` (`src_time`, `src_frame`, durações, aparar, dividir, a V1 magnética) e o som
(`audiomix`: os trechos de velocidade constante, `TimeMap.pieces`). Os presets (`PRESETS`) só geram âncoras.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Any, Iterable

from .i18n import N_

R_MIN, R_MAX = 0.05, 20.0     # velocidade relativa aceita numa âncora
MAX_ANCHORS = 64
PIECE_S = 0.1                 # s da saída: tamanho dos trechos do som numa transição de velocidade
MAX_PIECES = 400

# Presets (ids ASCII; o rótulo é traduzido). Só desenham a rampa: o projeto guarda as âncoras.
PRESETS: list[tuple[str, str]] = [
    ("acelerar", N_("Acelerar")),
    ("desacelerar", N_("Desacelerar")),
    ("impacto", N_("Impacto (rápido–lento–rápido)")),
    ("lento_meio", N_("Câmera lenta no meio")),
    ("entrada_lenta", N_("Entrada em câmera lenta")),
    ("saida_lenta", N_("Saída em câmera lenta")),
]
PRESET_IDS = tuple(k for k, _label in PRESETS)
AMOUNT_DEFAULT = 0.5          # intensidade (0 a 1): lento = 1 / (1 + 3·i), rápido = 1 + 3·i
RAMP_S_DEFAULT = 0.5          # duração de cada transição de velocidade, em segundos do arquivo


# ------------------------------------------------------------------ âncoras
def clean_ramp(raw: Any) -> list[tuple[float, float]]:
    """Âncoras válidas, em ordem, sem tempos repetidos (a última vale); [] se não há rampa de verdade."""
    out: dict[float, float] = {}
    if isinstance(raw, (list, tuple)):
        for item in list(raw)[: MAX_ANCHORS * 4]:
            try:
                s, r = float(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if not (math.isfinite(s) and math.isfinite(r)) or s < 0 or r <= 0:
                continue
            out[round(s, 6)] = min(max(r, R_MIN), R_MAX)
    anchors = sorted(out.items())[:MAX_ANCHORS]
    if not anchors or all(abs(r - 1.0) < 1e-9 for _s, r in anchors):
        return []
    return [(float(s), float(r)) for s, r in anchors]


def ramp_json(ramp: Iterable[tuple[float, float]]) -> list[list[float]]:
    return [[round(float(s), 6), round(float(r), 6)] for s, r in ramp]


# ------------------------------------------------------------------ o mapa
class TimeMap:
    """O tempo de um clipe (veja o cabeçalho). `x` = segundos da saída desde o começo do clipe (pode passar das
    pontas: a velocidade da ponta continua); `s` = segundos do arquivo."""

    def __init__(self, src_in: float, speed: float, ramp: Iterable[tuple[float, float]] = (), reverse: bool = False):
        self.src_in = float(src_in)
        self.speed = max(1e-9, float(speed))
        self.reverse = bool(reverse)
        self.dir = -1.0 if self.reverse else 1.0
        a = list(ramp)
        self.sk = [float(s) for s, _r in a]
        self.rk = [float(r) for _s, r in a]
        self.bk: list[float] = []
        self.gk: list[float] = [0.0] if a else []
        for k in range(len(a) - 1):
            d = self.sk[k + 1] - self.sk[k]
            r0, r1 = self.rk[k], self.rk[k + 1]
            self.bk.append((r1 * r1 - r0 * r0) / d if d > 0 else 0.0)
            self.gk.append(self.gk[-1] + (2.0 * d / (r0 + r1) if d > 0 else 0.0))
        self.g_in = self.G(self.src_in)

    @property
    def ramped(self) -> bool:
        return bool(self.sk)

    # -------------------------------------------------------- G e o inverso
    def G(self, s: float) -> float:
        sk, rk = self.sk, self.rk
        if not sk:
            return float(s)
        if s <= sk[0]:
            return (s - sk[0]) / rk[0]
        if s >= sk[-1]:
            return self.gk[-1] + (s - sk[-1]) / rk[-1]
        k = bisect_right(sk, s) - 1
        x, r0, b = s - sk[k], rk[k], self.bk[k]
        return self.gk[k] + 2.0 * x / (r0 + math.sqrt(max(0.0, r0 * r0 + b * x)))

    def G_inv(self, g: float) -> float:
        sk, rk, gk = self.sk, self.rk, self.gk
        if not sk:
            return float(g)
        if g <= 0.0:
            return sk[0] + g * rk[0]
        if g >= gk[-1]:
            return sk[-1] + (g - gk[-1]) * rk[-1]
        k = bisect_right(gk, g) - 1
        y = g - gk[k]
        return min(sk[k] + rk[k] * y + self.bk[k] / 4.0 * y * y, sk[k + 1])

    def r_at(self, s: float) -> float:
        """Velocidade relativa da rampa no segundo `s` do arquivo."""
        sk, rk = self.sk, self.rk
        if not sk:
            return 1.0
        if s <= sk[0]:
            return rk[0]
        if s >= sk[-1]:
            return rk[-1]
        k = bisect_right(sk, s) - 1
        return math.sqrt(max(0.0, rk[k] * rk[k] + self.bk[k] * (s - sk[k])))

    # -------------------------------------------------------- saída ↔ arquivo
    def src_at(self, x: float) -> float:
        """Segundo do arquivo no instante `x` da saída."""
        if not self.sk:
            return self.src_in + self.dir * self.speed * x
        return self.G_inv(self.g_in + self.dir * self.speed * x)

    def out_at(self, s: float) -> float:
        """Instante da saída em que o arquivo passa por `s` (o inverso de `src_at`)."""
        return self.dir * (self.G(s) - self.g_in) / self.speed

    def rate_at(self, x: float) -> float:
        """Velocidade efetiva (arquivo por saída, sempre positiva) no instante `x`."""
        return self.speed * self.r_at(self.src_at(x))

    def room_after(self, length: float) -> float:
        """Segundos de saída do começo do clipe até o arquivo acabar (no sentido em que ele toca)."""
        end = 0.0 if self.reverse else float(length)
        return max(0.0, self.out_at(end))

    def room_before(self, length: float) -> float:
        """Segundos de saída antes do começo do clipe até a outra ponta do arquivo (o quanto o começo volta)."""
        start = float(length) if self.reverse else 0.0
        return max(0.0, -self.out_at(start))

    # -------------------------------------------------------- som
    def pieces(self, x0: float, x1: float) -> list[tuple[float, float, float, float]]:
        """O trecho [x0, x1) da saída em pedaços de velocidade (quase) constante: [(xa, xb, sa, sb)].

        Onde a velocidade é constante (fora das transições), um pedaço só; numa transição, pedaços de até
        `PIECE_S` da saída. As pontas de cada pedaço caem exatamente no mapa (sem erro acumulado): o som de cada
        um vai de `sa` a `sb` do arquivo no tempo xb − xa."""
        if x1 <= x0:
            return []
        cuts = {x0, x1}
        for s in self.sk:
            x = self.out_at(s)
            if x0 < x < x1:
                cuts.add(x)
        edges = sorted(cuts)
        spans = list(zip(edges[:-1], edges[1:]))
        moving = []
        for xa, xb in spans:
            mid = self.src_at((xa + xb) / 2)
            k = bisect_right(self.sk, mid) - 1
            varies = 0 <= k < len(self.sk) - 1 and abs(self.rk[k + 1] - self.rk[k]) > 1e-12
            moving.append(varies)
        total = sum(xb - xa for (xa, xb), mv in zip(spans, moving) if mv)
        step = max(PIECE_S, total / MAX_PIECES) if total else PIECE_S
        out = []
        for (xa, xb), mv in zip(spans, moving):
            n = max(1, int(math.ceil((xb - xa) / step - 1e-9))) if mv else 1
            for i in range(n):
                a = xa + (xb - xa) * i / n
                b = xa + (xb - xa) * (i + 1) / n if i < n - 1 else xb
                out.append((a, b, self.src_at(a), self.src_at(b)))
        return out


# ------------------------------------------------------------------ presets
def preset_shape(pid: str, amount: float = AMOUNT_DEFAULT, w: float = 0.2) -> list[tuple[float, float]]:
    """A forma do preset: [(u, r)], com u de 0 a 1 ao longo do trecho do arquivo (na ordem em que ele toca) e w a
    largura de cada transição (fração do trecho)."""
    i = min(max(float(amount), 0.0), 1.0)
    slow, fast = 1.0 / (1.0 + 3.0 * i), 1.0 + 3.0 * i
    if pid == "acelerar":
        w = min(w, 0.9)
        return [(0.5 - w / 2, 1.0), (0.5 + w / 2, fast)]
    if pid == "desacelerar":
        w = min(w, 0.9)
        return [(0.5 - w / 2, 1.0), (0.5 + w / 2, slow)]
    if pid == "impacto":
        w = min(w, 0.3)
        return [(0.4 - w, fast), (0.4, slow), (0.6, slow), (0.6 + w, fast)]
    if pid == "lento_meio":
        w = min(w, 0.3)
        return [(0.35 - w, 1.0), (0.35, slow), (0.65, slow), (0.65 + w, 1.0)]
    if pid == "entrada_lenta":
        w = min(w, 0.6)
        return [(0.3, slow), (0.3 + w, 1.0)]
    if pid == "saida_lenta":
        w = min(w, 0.6)
        return [(0.7 - w, 1.0), (0.7, slow)]
    raise KeyError(pid)


def preset_anchors(pid: str, lo: float, hi: float, reverse: bool = False, amount: float = AMOUNT_DEFAULT,
                   ramp_s: float = RAMP_S_DEFAULT) -> list[tuple[float, float]]:
    """As âncoras do preset para o trecho [lo, hi] do arquivo (o que o clipe mostra; no reverso ele toca de `hi`
    para `lo`). `ramp_s`: duração de cada transição, em segundos do arquivo."""
    span = max(1e-6, float(hi) - float(lo))
    w = min(max(float(ramp_s) / span, 0.02), 1.0)
    pts = []
    for u, r in preset_shape(pid, amount, w):
        u = min(max(u, 0.0), 1.0)
        s = hi - u * span if reverse else lo + u * span
        pts.append((s, r))
    return clean_ramp(pts)


__all__ = ["AMOUNT_DEFAULT", "MAX_ANCHORS", "PRESETS", "PRESET_IDS", "RAMP_S_DEFAULT", "R_MAX", "R_MIN", "TimeMap",
           "clean_ramp", "preset_anchors", "preset_shape", "ramp_json"]
