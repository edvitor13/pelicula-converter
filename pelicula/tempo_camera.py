"""Tempo da câmera de cinema (1.6, ARQUITETURA §33): obturador e manivela. Sem Qt; a mistura roda na GPU
(`Engine.temporal_blend`) com os programas `ACC` e `ENC` daqui.

**Obturador** (`obturador_on`, `obturador_angulo` do look). Uma câmera de cinema expõe cada quadro só enquanto o
obturador está aberto: 180° = metade do período do quadro (1/48 s a 24 qps). Com uma fonte de pelo menos o dobro
dos quadros por segundo da saída (50/60/120 → 24/25/30), o quadro da saída é a média, **na luz linear**, dos quadros
da fonte que caem dentro da janela aberta: o rastro de movimento da película. Cada quadro da fonte ocupa um
intervalo inteiro do tempo da fonte e pesa pela sobreposição com a janela (`window_weights`): os pesos somam 1
(a energia se conserva) e só dependem do número do quadro e das taxas (determinismo). Desligado, ou com a fonte a
menos do dobro da saída, nada muda: o quadro mais próximo, como sempre (bit a bit).

- Modo Película com o arquivo direto: a saída da exportação (`Recipe.fps`) contra a taxa do arquivo
  (`file_window`). A janela começa no instante do quadro da saída e cada quadro da fonte ocupa [k − ½, k + ½) em
  quadros da fonte, então com a janela fechando (ângulo → 0) o quadro escolhido é o mesmo do filtro `fps` do
  ffmpeg (o mais próximo). A prévia da janela e o "Salvar quadro" mostram a taxa do arquivo (nada a misturar); a
  prévia da janela de exportação mostra a mistura (o mesmo caminho da exportação).
- Modo Edição: **por clipe** (`Sequence.src_window`), na taxa da sequência. Cada clipe mistura os quadros do
  próprio arquivo na curva dele (o perfil de câmera do clipe ou a entrada do look), antes dos ajustes: o rastro é
  da câmera que filmou, títulos, geradores e o movimento animado no enquadramento continuam nítidos, e o custo é o
  de decodificar mais quadros só nos clipes rápidos (montar várias telas inteiras custaria a montagem toda N vezes).
  A troca de taxa da sequência para a da exportação continua pelo quadro mais próximo.

**Manivela** (`editparams` "manivela", por clipe; `Sequence.src_frame`): o clipe foi "filmado" a 16/18 qps e é
projetado na taxa da sequência; escolher a cadência acelera o clipe (24 ÷ 16 = 1,5×, `crank_factor`) e o som segue
pela velocidade de sempre. A oscilação da mão (`manivela_oscila`) desloca o instante de cada imagem por um ruído
suave e limitado (`crank_offset`, no máximo `CRANK_JITTER_S`): a velocidade varia uns por cento sem acumular atraso.
O som não acompanha a oscilação (no máximo `CRANK_JITTER_S` de diferença com 100%).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MIN_RATIO = 2.0          # a fonte precisa de pelo menos o dobro dos quadros por segundo da saída
MAX_FRAMES = 24          # quadros da fonte por quadro da saída (240 → 24 a 360° são 10)
EPS = 1e-9



def shutter_angle(values: dict | None) -> float:
    """O ângulo do obturador do look em graus (0 = desligado)."""
    if not values or not values.get("obturador_on"):
        return 0.0
    try:
        return max(0.0, min(360.0, float(values.get("obturador_angulo", "180"))))
    except (TypeError, ValueError):
        return 0.0


def window_weights(u0: float, length: float, origin: float = 0.0, last: int | None = None) -> list[tuple[int, float]]:
    """Pesos dos quadros da fonte numa janela [u0, u0 + length) medida em quadros da fonte; o quadro k ocupa
    [k + origin, k + 1 + origin). Os pesos são a sobreposição sobre `length` e somam 1. `last`: o último quadro
    que existe (os de fora viram o mais próximo que existe). Janela de largura 0: o quadro que contém u0."""
    if length <= EPS:
        ks = [(int(math.floor(u0 - origin + EPS)), 1.0)]
    else:
        a, b = u0, u0 + length
        k0 = int(math.floor(a - origin + EPS))
        k1 = int(math.ceil(b - origin - EPS)) - 1
        ks = []
        for k in range(k0, max(k0, k1) + 1):
            lo, hi = max(a, k + origin), min(b, k + 1 + origin)
            if hi - lo > EPS:
                ks.append((k, (hi - lo) / length))
        if not ks:
            ks = [(k0, 1.0)]
    out: dict[int, float] = {}
    for k, w in ks:
        k = max(0, k if last is None else min(k, last))
        out[k] = out.get(k, 0.0) + w
    total = sum(out.values())
    items = sorted(out.items())[:MAX_FRAMES]
    total = sum(w for _k, w in items) or total or 1.0
    return [(k, w / total) for k, w in items]


def active(angle: float, src_fps: float, out_fps: float) -> bool:
    """Há o que misturar: obturador ligado e a fonte com pelo menos `MIN_RATIO` vezes a taxa da saída."""
    return angle > 0.0 and out_fps > 0.0 and src_fps >= MIN_RATIO * out_fps - 1e-6


def file_window(index: int, out_fps: float, src_fps: float, angle: float,
                frames: int | None = None) -> list[tuple[int, float]] | None:
    """Quadros do arquivo (e pesos) do quadro `index` da saída; None = sem mistura (o quadro mais próximo)."""
    if not active(angle, src_fps, out_fps):
        return None
    ratio = src_fps / out_fps
    last = None if not frames else max(0, int(frames) - 1)
    return window_weights(index * ratio, angle / 360.0 * ratio, -0.5, last)


def clip_window(s0: float, s1: float, src_fps: float, frames: int, angle: float,
                reverse: bool = False) -> list[tuple[int, float]] | None:
    """Quadros do arquivo de um clipe no quadro da sequência que vai de `s0` a `s1` segundos do arquivo (s1 < s0 no
    reverso). None = sem mistura (o clipe tem menos que `MIN_RATIO` quadros do arquivo por quadro da sequência)."""
    span = abs(s1 - s0) * src_fps
    if angle <= 0.0 or span < MIN_RATIO - 1e-6:
        return None
    u0 = (s1 if reverse else s0) * src_fps
    return window_weights(u0, angle / 360.0 * span, 0.0, max(0, int(frames) - 1))


@dataclass
class Stack:
    """Quadros da fonte para um quadro da saída, com os pesos do obturador (`Recipe.montage` mistura)."""
    images: list[np.ndarray]
    weights: list[float]
    frames: list[int] = field(default_factory=list)

    @property
    def shape(self):  # como uma imagem (o tamanho é o do primeiro quadro)
        return self.images[0].shape


class WindowReader:
    """Leitor em ordem da exportação no modo Película com o obturador: devolve um `Stack` por quadro da saída.

    Lê o arquivo na taxa dele (sem o filtro `fps` do ffmpeg) e guarda só os quadros que a janela ainda usa."""

    def __init__(self, info, w: int, h: int, depth: int, first: int, count: int | None, out_fps: float,
                 angle: float, **kw: Any):
        self.info, self.w, self.h, self.depth = info, int(w), int(h), int(depth)
        self.first, self.count, self.out_fps, self.angle = int(first), count, float(out_fps), float(angle)
        self.kw = kw
        self.i = 0
        self.reader = None
        self.next = 0
        self.cache: dict[int, np.ndarray] = {}
        self.eof = False
        self.error = ""

    def window(self, i: int) -> list[tuple[int, float]]:
        win = file_window(self.first + i, self.out_fps, float(self.info.fps), self.angle, self.info.frames)
        if win is None:  # não acontece com o leitor certo; por garantia, o quadro mais próximo
            k = int(round((self.first + i) * float(self.info.fps) / self.out_fps))
            win = [(k, 1.0)]
        return win

    def _open(self, k: int) -> None:
        from . import media
        self.close()
        self.reader = media.FrameReader(self.info, self.w, self.h, self.depth, max(0, k), None, None, **self.kw)
        self.next = max(0, k)

    def read(self) -> Stack | None:
        if self.count is not None and self.i >= self.count:
            return None
        win = self.window(self.i)
        self.i += 1
        lo, hi = win[0][0], win[-1][0]
        if self.reader is None:
            self._open(lo)
        while self.next <= hi and not self.eof:
            img = self.reader.read()
            if img is None:
                self.eof = True
                self.error = self.error or self.reader.error
                break
            if self.next >= lo:
                self.cache[self.next] = img
            self.next += 1
        for k in [k for k in self.cache if k < lo]:
            del self.cache[k]
        got = [(k, w) for k, w in win if k in self.cache]
        if not got:
            if not self.cache:
                return None
            k = max(self.cache)
            got = [(k, 1.0)]
        total = sum(w for _k, w in got) or 1.0
        return Stack([self.cache[k] for k, _w in got], [w / total for _k, w in got], [k for k, _w in got])

    def close(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None


def grab_window(info, win: list[tuple[int, float]], w: int, h: int, depth: int, **kw: Any) -> Stack:
    """Os quadros de uma janela lidos de uma vez (prévia da janela de exportação)."""
    from . import media
    lo, hi = win[0][0], win[-1][0]
    reader = media.FrameReader(info, w, h, depth, lo, hi - lo + 1, None, **kw)
    imgs: dict[int, np.ndarray] = {}
    try:
        for k in range(lo, hi + 1):
            img = reader.read()
            if img is None:
                break
            imgs[k] = img
    finally:
        reader.close()
    got = [(k, wt) for k, wt in win if k in imgs] or ([(max(imgs), 1.0)] if imgs else [])
    if not got:
        raise RuntimeError(reader.error or "nenhum quadro lido")
    total = sum(wt for _k, wt in got) or 1.0
    return Stack([imgs[k] for k, _w in got], [wt / total for _k, wt in got], [k for k, _w in got])


def blend_numpy(stack: Stack, decode, encode) -> np.ndarray:
    """Referência em numpy da mistura (testes): encode(Σ peso · decode(quadro))."""
    acc = None
    for img, wt in zip(stack.images, stack.weights):
        x = decode(np.asarray(img, dtype=np.float64))
        acc = x * wt if acc is None else acc + x * wt
    return encode(acc)


# ------------------------------------------------------------------ manivela (por clipe, `Sequence.src_frame`)
CRANKS = [("nenhuma", "Normal (sem manivela)"), ("16", "16 qps (cinema mudo)"), ("18", "18 qps (Super 8, manivela)"),
          ("20", "20 qps"), ("22", "22 qps")]
CRANK_JITTER_S = 0.05   # s: deslocamento máximo do instante de cada imagem com 100% de oscilação
CRANK_HZ = 1.1          # ritmo da mão na manivela (variações por segundo)


def crank_rate(value: Any) -> float:
    """Quadros por segundo da manivela (0 = sem manivela)."""
    try:
        return float(value) if value not in (None, "", "nenhuma") else 0.0
    except (TypeError, ValueError):
        return 0.0


def crank_factor(seq_fps: float, value: Any) -> float:
    """Quanto a manivela acelera o clipe: a taxa da sequência sobre a da manivela (1 sem manivela)."""
    c = crank_rate(value)
    return float(seq_fps) / c if c > 0 else 1.0


def _hash(i: int, s: int) -> float:
    from .look import _hash as h
    return h(i, s)


def _vnoise(x: float, s: int) -> float:
    i = math.floor(x)
    f = x - i
    u = f * f * (3 - 2 * f)
    return (_hash(i, s) * (1 - u) + _hash(i + 1, s) * u) * 2 - 1


def crank_offset(tau: float, amount: float, seed: int) -> float:
    """Segundos a somar ao instante do arquivo no tempo `tau` (s) do clipe: a mão que gira a manivela sem ritmo
    perfeito. Ruído suave e limitado (nada acumula): a velocidade oscila e o clipe termina no lugar."""
    if amount <= 0.0:
        return 0.0
    n = 0.7 * _vnoise(tau * CRANK_HZ, 9000 + int(seed)) + 0.3 * _vnoise(tau * CRANK_HZ * 2.7, 9100 + int(seed))
    return float(amount) * CRANK_JITTER_S * n


# ------------------------------------------------------------------ GLSL da mistura (Engine.temporal_blend)
def _programs() -> tuple[str, str]:
    from . import shaders
    acc = shaders.COMMON + """
uniform sampler2D t_prev;
uniform sampler2D t_f0;
uniform sampler2D t_f1;
uniform sampler2D t_f2;
uniform sampler2D t_f3;
uniform int u_prev;
uniform int u_n;
uniform vec4 u_w;
uniform int u_curve;
uniform int u_cv;
uniform int u_alpha;

vec4 term(sampler2D t, float w) {
    vec4 s = texelFetch(t, ivec2(gl_FragCoord.xy), 0);
    if (u_alpha == 1) {
        vec3 c = s.a > 0.0 ? s.rgb / s.a : vec3(0.0);
        return vec4(toLinear(c, u_curve, u_cv == 1) * s.a, s.a) * w;
    }
    return vec4(toLinear(s.rgb, u_curve, u_cv == 1), 1.0) * w;
}

void main() {
    vec4 acc = (u_prev == 1) ? texelFetch(t_prev, ivec2(gl_FragCoord.xy), 0) : vec4(0.0);
    if (u_n > 0) acc += term(t_f0, u_w.x);
    if (u_n > 1) acc += term(t_f1, u_w.y);
    if (u_n > 2) acc += term(t_f2, u_w.z);
    if (u_n > 3) acc += term(t_f3, u_w.w);
    f_out = acc;
}
"""
    enc = shaders.COMMON + """
uniform sampler2D t_acc;
uniform int u_curve;
uniform int u_cv;
uniform int u_alpha;

// luz linear → valor da curva (o inverso de toLinear, sem gamut: a mistura fica no espaço da própria câmera)
vec3 fromLinear(vec3 n, int id) {
    vec3 o;
    if (id == 0) o = stopsToDisp(linToStops(n));
    else if (id == 1) o = n;
    else if (id == 2) o = vec3(nlogEnc(n.r), nlogEnc(n.g), nlogEnc(n.b));
    else if (id == 3) o = vec3(slog3Enc(n.r), slog3Enc(n.g), slog3Enc(n.b));
    else if (id == 4) o = vec3(logc3Enc(n.r), logc3Enc(n.g), logc3Enc(n.b));
    else if (id == 5) o = vec3(vlogEnc(n.r), vlogEnc(n.g), vlogEnc(n.b));
    else if (id == 7) o = vec3(diEnc(n.r), diEnc(n.g), diEnc(n.b));
    else if (id == 8) o = vec3(l3g10Enc(n.r), l3g10Enc(n.g), l3g10Enc(n.b));
    else if (id == 9) o = vec3(bmd5Enc(n.r), bmd5Enc(n.g), bmd5Enc(n.b));
    else if (id == 10) o = vec3(logc4Enc(n.r), logc4Enc(n.g), logc4Enc(n.b));
    else if (id == 11) o = vec3(appleEnc(n.r), appleEnc(n.g), appleEnc(n.b));
    else if (id == 12) o = vec3(hlgEnc(n.r), hlgEnc(n.g), hlgEnc(n.b));
    else if (id == 13) o = pqEnc(n);
    else if (id >= 14) o = camEnc(n, id);
    else o = vec3(cineonEnc(n.r), cineonEnc(n.g), cineonEnc(n.b));
    return u_cv == 1 ? (o * 1023.0 - 64.0) / 876.0 : o;
}

void main() {
    vec4 a = texelFetch(t_acc, ivec2(gl_FragCoord.xy), 0);
    if (u_alpha == 1) {
        vec3 lin = a.a > 0.0 ? a.rgb / a.a : vec3(0.0);
        f_out = vec4(fromLinear(lin, u_curve) * a.a, a.a);
    } else {
        f_out = vec4(fromLinear(a.rgb, u_curve), 1.0);
    }
}
"""
    return acc, enc


ACC, ENC = _programs()


def curve_of(values: dict | None, legal: bool) -> tuple[int, bool]:
    """A curva (id de `look.input_id`) e o domínio (código de 10 bits numa fonte de faixa legal) de uns ajustes de
    entrada no formato do look ("entrada", "log_reescalado", "logc3_ei")."""
    from . import look
    v = values or {}
    entrada = v.get("entrada", "rec709")
    cv = look.code_value_curve(entrada) and not v.get("log_reescalado") and bool(legal)
    return look.input_id(v), bool(cv)
