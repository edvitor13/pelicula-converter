"""Geradores do modo Edição: cor sólida, degradê e a ponta com contagem (clipes sem arquivo).

Cada gerador é um tipo de `GENERATORS` (id ASCII, nunca renomear) com os campos que o inspetor mostra
(`Field`, gravados em `Source.data` com chaves sem acento) e uma função de desenho pura e determinística:
o quadro depende só dos campos, do quadro da fonte e do tamanho pedido (regra 2). A cor sólida é a fonte de
tipo `"cor"`; os outros são fontes `"gerador"` com `data["gerador"]` = id. Os dois tipos se registram em
`sequence.RENDERERS` quando `sequence` é importado (o registro fica mesmo com o módulo desligado: a
renderização nunca consulta `modules`).

- **Cor sólida** (`"cor"`): `cor` (#rrggbb). Opaca.
- **Degradê** (`"degrade"`): `forma` linear ou radial, `cores` (2 ou 3), `cor1`…`cor3`, `meio` (posição da
  cor do meio, com 3 cores) e `angulo` (graus; 0° = da esquerda para a direita, 90° = de cima para baixo).
  A mistura é nos códigos do vídeo (como um degradê de editor de imagens); em 8 bits leva um pontilhado
  ordenado (Bayer 4 × 4, fixo por pixel) contra faixas.
- **Ponta com contagem** (`"contagem"`): a ponta de cinema que conta de 8 a 2 — cada número dura um segundo,
  com a varredura do relógio, os dois círculos e a cruz; o "2" fica um quadro só, com o bipe de 1 kHz
  (`audiomix.TONES`, exato à amostra: prévia = exportação), e depois é preto até o fim (8 s no total). Os
  números são desenhados com as fontes do app (`textrender`). `bipe` liga ou desliga o som.

Medidas em px@1080 (`escala = altura / 1080`); y para baixo (linha 0 = topo), como os shaders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import numpy as np

from . import timeline
from .i18n import N_, _

KIND_COLOR = "cor"          # `timeline.SOURCE_KINDS`: a cor sólida
KIND_GENERATOR = "gerador"  # os outros geradores (`data["gerador"]`)
GRADIENT = "degrade"
LEADER = "contagem"

LEADER_SECONDS = 8.0        # 8 → 2 (um segundo cada), o "2" de um quadro e o preto até o programa
LEADER_FIRST = 8
LEADER_LAST = 2
BEEP_HZ = 1000.0
BEEP_DB = -20.0             # o bipe de referência das pontas (−20 dBFS)


# ------------------------------------------------------------------ campos
@dataclass(frozen=True)
class Field:
    """Um campo do gerador no inspetor (gravado em `Source.data[key]`)."""
    key: str
    label: str                       # N_(): traduzido na tela
    kind: str                        # "cor" | "numero" | "escolha" | "bool"
    default: Any
    lo: float = 0.0
    hi: float = 1.0
    step: float = 1.0
    decimals: int = 0
    suffix: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    tip: str = ""
    when: tuple[str, Any] | None = None  # só aparece quando data[chave] == valor (ex.: a 3ª cor)

    def clean(self, value: Any) -> Any:
        """O valor conferido (o que vier errado fica no padrão)."""
        if self.kind == "cor":
            from .textrender import color_hex, parse_color
            return color_hex(parse_color(value, parse_color(self.default)))
        if self.kind == "bool":
            return value if isinstance(value, bool) else bool(self.default)
        if self.kind == "escolha":
            ok = {k for k, _l in self.choices}
            return value if value in ok else self.default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.default
        if not math.isfinite(v):
            return self.default
        v = min(max(v, self.lo), self.hi)
        return int(round(v)) if self.decimals == 0 else round(v, self.decimals)

    def visible(self, data: dict) -> bool:
        if self.when is None:
            return True
        key, want = self.when
        return data.get(key) == want


@dataclass(frozen=True)
class Generator:
    id: str                          # ASCII, gravado no projeto: nunca renomear
    label: str                       # N_(): nome no menu "Novo" e na Mídia
    source_kind: str                 # "cor" | "gerador"
    seconds: float | None            # duração da fonte (None = sem fim, como uma imagem)
    alpha: bool                      # desenha com transparência
    fields: tuple[Field, ...]
    render: Callable[[dict, int, float, int, int, int], np.ndarray]  # (dados, quadro, fps, w, h, prof.)
    tip: str = ""


def _cor(key, label, default, **kw) -> Field:
    return Field(key, label, "cor", default, **kw)


# ------------------------------------------------------------------ desenho
def _peak(depth: int) -> float:
    return 255.0 if depth == 8 else 65535.0


def _to_depth(img: np.ndarray, depth: int) -> np.ndarray:
    mx = _peak(depth)
    return np.clip(np.rint(img * mx), 0, mx).astype(np.uint8 if depth == 8 else np.uint16)


def _rgb(value: Any) -> np.ndarray:
    from .textrender import parse_color
    return np.array(parse_color(value, (0.0, 0.0, 0.0)), dtype=np.float64)


def render_color(data: dict, frame: int, fps: float, w: int, h: int, depth: int) -> np.ndarray:
    """Cor sólida (opaca, h × w × 3)."""
    c = _to_depth(_rgb(data.get("cor")), depth)
    return np.ascontiguousarray(np.broadcast_to(c, (h, w, 3)))


_BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float64) + 0.5) / 16.0 - 0.5


@lru_cache(maxsize=8)
def _gradient_t(shape: str, angle: float, w: int, h: int) -> np.ndarray:
    """Posição 0–1 no degradê de cada pixel (centro dos pixels; só leitura)."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    x = xs + 0.5 - w / 2.0
    y = ys + 0.5 - h / 2.0
    if shape == "radial":
        t = np.hypot(x, y) / max(1e-9, math.hypot(w / 2.0, h / 2.0))
    else:
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        ext = max(1e-9, (abs(dx) * w + abs(dy) * h) / 2.0)
        t = (x * dx + y * dy) / ext * 0.5 + 0.5
    t = np.clip(t, 0.0, 1.0)
    t.setflags(write=False)
    return t


def render_gradient(data: dict, frame: int, fps: float, w: int, h: int, depth: int) -> np.ndarray:
    """Degradê linear ou radial de 2 ou 3 cores (opaco, h × w × 3). Não anda com o tempo: guardado por tamanho."""
    three = str(data.get("cores")) == "3"
    key = (str(data.get("forma")), float(data.get("angulo", 0.0)), three, str(data.get("cor1")),
           str(data.get("cor2")), str(data.get("cor3")) if three else "", float(data.get("meio", 0.5)) if three else 0.5)
    return _gradient(*key, int(w), int(h), int(depth)).copy()


@lru_cache(maxsize=8)
def _gradient(shape: str, angle: float, three: bool, col1: str, col2: str, col3: str, mid: float, w: int, h: int,
              depth: int) -> np.ndarray:
    t = _gradient_t(shape, angle, w, h)[..., None]
    c1, c2, c3 = _rgb(col1), _rgb(col2), _rgb(col3)
    if three:
        m = min(max(mid, 0.01), 0.99)
        lo = c1 + (c2 - c1) * (t / m)
        hi = c2 + (c3 - c2) * ((t - m) / (1.0 - m))
        img = np.where(t <= m, lo, hi)
    else:
        img = c1 + (c2 - c1) * t
    mx = _peak(depth)
    if depth == 8:  # pontilhado ordenado contra faixas (fixo por pixel: determinístico)
        dither = np.tile(_BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w, None]
        out = np.clip(np.floor(img * mx + 0.5 + dither), 0, mx).astype(np.uint8)
    else:
        out = _to_depth(img, depth)
    out.setflags(write=False)
    return out


# Ponta com contagem: tons e medidas (px@1080), à moda da ponta universal (SMPTE).
LEADER_BG = 0.62          # cinza do fundo
LEADER_SWEEP = 0.38       # cinza da parte já varrida
LEADER_LINE = 0.04        # cruz e números
LEADER_RING = 0.93        # círculos
RING_RADII = (0.43, 0.37)  # raios dos círculos (× altura)
RING_WIDTH = 7.0
CROSS_WIDTH = 3.0
NUMBER_SIZE = 620.0       # tamanho do número (px@1080)


def leader_state(frame: int, fps: float) -> tuple[int, float]:
    """(número, fração da varredura) da ponta no quadro `frame` da fonte; número 0 = preto (depois do "2").

    O "2" é o primeiro quadro em 6 s (`two_frame`), um quadro só, sem varredura."""
    n2 = two_frame(fps)
    if frame > n2:
        return 0, 0.0
    if frame == n2:
        return LEADER_LAST, 0.0
    t = max(0, frame) / fps
    sec = int(math.floor(t + 1e-9))
    return LEADER_FIRST - sec, min(max(t - sec, 0.0), 1.0)


def two_frame(fps: float) -> int:
    """Quadro da fonte do "2" (e do bipe): o primeiro quadro em 6 s."""
    return int(math.ceil((LEADER_FIRST - LEADER_LAST) * float(fps) - 1e-6))


@lru_cache(maxsize=4)
def _leader_base(w: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(ângulo no sentido horário a partir do topo, raio, cobertura da cruz, cobertura dos círculos)."""
    s = h / 1080.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    x = xs + 0.5 - w / 2.0
    y = ys + 0.5 - h / 2.0
    theta = np.mod(np.arctan2(x, -y), 2.0 * math.pi)  # 0 no alto, π/2 à direita (y para baixo)
    r = np.hypot(x, y)
    half = max(0.5, CROSS_WIDTH * s / 2.0)
    cross = np.maximum(np.clip(half + 0.5 - np.abs(x), 0, 1), np.clip(half + 0.5 - np.abs(y), 0, 1))
    ring_half = max(0.5, RING_WIDTH * s / 2.0)
    rings = np.zeros_like(r)
    for k in RING_RADII:
        rings = np.maximum(rings, np.clip(ring_half + 0.5 - np.abs(r - k * h), 0, 1))
    out = tuple(np.ascontiguousarray(a, dtype=np.float32) for a in (theta, r, cross, rings))
    for a in out:
        a.setflags(write=False)
    return out


def _number_style():
    from .textrender import TextStyle
    return TextStyle(family="atkinson", weight=700, size=NUMBER_SIZE, color=(LEADER_LINE,) * 3)


def render_leader(data: dict, frame: int, fps: float, w: int, h: int, depth: int) -> np.ndarray:
    """A ponta com contagem no quadro `frame` (opaca, h × w × 3)."""
    number, sweep = leader_state(frame, fps)
    if number == 0:
        return np.zeros((h, w, 3), np.uint8 if depth == 8 else np.uint16)
    theta, r, cross, rings = _leader_base(w, h)
    img = np.full((h, w), LEADER_BG, np.float32)
    if sweep > 0:
        a = np.float32(2.0 * math.pi * sweep)
        # a borda da varredura com antialiasing (distância em pixels ≈ raio × ângulo)
        cov = np.minimum(theta, a - theta)
        cov *= np.maximum(r, np.float32(1.0))
        cov += np.float32(0.5)
        np.clip(cov, 0.0, 1.0, out=cov)
        img += np.float32(LEADER_SWEEP - LEADER_BG) * cov
    img += (np.float32(LEADER_LINE) - img) * cross
    img += (np.float32(LEADER_RING) - img) * rings
    _draw_number(img, str(number), w, h)
    out = _to_depth(img, depth)
    return np.repeat(out[..., None], 3, axis=2)


def _draw_number(canvas: np.ndarray, text: str, w: int, h: int) -> None:
    """O número no centro do quadro (o centro da tinta no centro da tela), por cima de `canvas` (cinza 0–1)."""
    from . import textrender
    style = _number_style()
    lay = textrender.measure(text, style, h)
    x0, y0, x1, y1 = lay.ink
    bx, by = w / 2.0 - (x0 + x1) / 2.0, h / 2.0 - (y0 + y1) / 2.0
    ix, iy = int(math.floor(bx)), int(math.floor(by))
    txt = textrender.render(text, style, h, depth=16, offset=(bx - ix, by - iy))
    ax, ay = ix + txt.left, iy + txt.top
    xa, ya, xb, yb = max(0, ax), max(0, ay), min(w, ax + txt.width), min(h, ay + txt.height)
    if xa >= xb or ya >= yb:
        return
    src = txt.rgba[ya - ay:yb - ay, xa - ax:xb - ax].astype(np.float32) / np.float32(65535.0)
    a = src[..., 3]
    canvas[ya:yb, xa:xb] = src[..., 0] * a + canvas[ya:yb, xa:xb] * (np.float32(1.0) - a)


# ------------------------------------------------------------------ catálogo
GENERATORS: dict[str, Generator] = {
    KIND_COLOR: Generator(
        KIND_COLOR, N_("Cor sólida"), KIND_COLOR, None, False,
        (_cor("cor", N_("Cor"), "#1f2a44"),), render_color,
        N_("Um quadro todo de uma cor: fundo para títulos, cartelas e transições.")),
    GRADIENT: Generator(
        GRADIENT, N_("Degradê"), KIND_GENERATOR, None, False,
        (Field("forma", N_("Forma"), "escolha", "linear",
               choices=(("linear", N_("Linear")), ("radial", N_("Radial (do centro)")))),
         Field("angulo", N_("Ângulo"), "numero", 90.0, -180.0, 180.0, 1.0, 0, "°",
               tip=N_("0° vai da esquerda para a direita; 90°, de cima para baixo."), when=("forma", "linear")),
         Field("cores", N_("Cores"), "escolha", "2", choices=(("2", N_("Duas")), ("3", N_("Três")))),
         _cor("cor1", N_("Primeira cor"), "#0b1a33"),
         _cor("cor2", N_("Segunda cor"), "#c25b2a"),
         _cor("cor3", N_("Terceira cor"), "#f2d27a", when=("cores", "3")),
         Field("meio", N_("Posição da cor do meio"), "numero", 0.5, 0.05, 0.95, 0.01, 2, when=("cores", "3"))),
        render_gradient, N_("Um degradê de duas ou três cores, em linha (com ângulo) ou do centro para fora.")),
    LEADER: Generator(
        LEADER, N_("Ponta com contagem"), KIND_GENERATOR, LEADER_SECONDS, False,
        (Field("bipe", N_("Bipe no 2"), "bool", True,
               tip=N_("O bipe de 1 kHz de um quadro no \"2\", para conferir o sincronismo do som.")),),
        render_leader,
        N_("A ponta de cinema que conta de 8 a 2 com a varredura, o bipe no \"2\" e preto até o começo do "
           "filme (8 segundos).")),
}


def generator_of(src: timeline.Source) -> Generator | None:
    """O gerador de uma fonte sem arquivo (None se não é um destes)."""
    if src.kind == KIND_COLOR:
        return GENERATORS[KIND_COLOR]
    if src.kind == KIND_GENERATOR:
        g = GENERATORS.get(str(src.data.get("gerador") or ""))
        return g if g is not None and g.source_kind == KIND_GENERATOR else None
    return None


def values(gen: Generator, data: dict) -> dict:
    """Os campos do gerador com os valores de `data` conferidos (o que faltar fica no padrão)."""
    return {f.key: f.clean(data.get(f.key, f.default)) for f in gen.fields}


def new_source(gen_id: str, seq: timeline.Sequence, **overrides) -> timeline.Source:
    """Fonte nova do gerador no tamanho e no fps da sequência (o nome é o do gerador, traduzido)."""
    gen = GENERATORS[gen_id]
    data: dict[str, Any] = {"nome": _(gen.label)}
    if gen.source_kind == KIND_GENERATOR:
        data["gerador"] = gen.id
    data.update({f.key: f.default for f in gen.fields})
    data.update(overrides)
    return timeline.Source.virtual(gen.source_kind, seq.width, seq.height, seq.fps_str, seconds=gen.seconds,
                                   data=data, alpha=gen.alpha)


def render(seq: timeline.Sequence, clip: timeline.Clip, frame: int, w: int, h: int, depth: int) -> np.ndarray:
    """`sequence.RENDERERS` dos tipos "cor" e "gerador": o gerador da fonte; tipo desconhecido → transparente."""
    src = seq.sources[clip.src]
    gen = generator_of(src)
    if gen is None:
        return np.zeros((h, w, 4), np.uint8 if depth == 8 else np.uint16)
    fps = src.fps if src.fps > 0 else seq.fps
    return gen.render(values(gen, src.data), int(frame), float(fps), int(w), int(h), int(depth))


def thumbnail_frame(src: timeline.Source) -> int:
    """Miniatura da ponta: o "8" no meio da varredura (as outras: o quadro 0)."""
    gen = generator_of(src)
    return int(round(src.fps * 0.6)) if gen is not None and gen.id == LEADER else 0


# ------------------------------------------------------------------ som (o bipe da ponta)
def tones(seq: timeline.Sequence, clip: timeline.Clip) -> list[tuple[int, int, float, float]]:
    """`audiomix.TONES`: [(quadro da fonte, quadros, frequência, ganho dB)] do som de um clipe gerado."""
    src = seq.sources.get(clip.src)
    gen = generator_of(src) if src is not None else None
    if gen is None or gen.id != LEADER or not values(gen, src.data)["bipe"]:
        return []
    return [(two_frame(src.fps if src.fps > 0 else seq.fps), 1, BEEP_HZ, BEEP_DB)]


def needs_text(seq: timeline.Sequence) -> bool:
    """A montagem tem um clipe que desenha texto (a ponta, os números; um título)? Quem roda sem janela
    (terminal) cria a `QGuiApplication` antes (`textrender.ensure_app`)."""
    for src in seq.sources.values():
        if src.kind == "texto":
            return True
        gen = generator_of(src) if not src.is_file else None
        if gen is not None and gen.id == LEADER:
            return True
    return False


def register() -> None:
    """Registra os geradores (desenho, som e miniatura). Chamado por `sequence` ao ser importado."""
    from . import audiomix, sequence
    for kind in (KIND_COLOR, KIND_GENERATOR):
        sequence.RENDERERS.setdefault(kind, render)
        audiomix.TONES.setdefault(kind, tones)
        sequence.THUMBNAIL_FRAME.setdefault(kind, thumbnail_frame)
