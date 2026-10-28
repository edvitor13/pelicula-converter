"""Títulos do modo Edição (clipes sem arquivo de tipo `"texto"`): texto, estilo, posição e animações.

`Source.data` de um título (chaves sem acento; o que faltar fica no padrão):

- `texto`: o texto (quebras de linha valem); `nome`: o nome na Mídia (a primeira linha).
- `estilo`: `textrender.TextStyle.to_json()` — fonte, peso, itálico, tamanho (px@1080), cor, contorno, sombra,
  caixa, alinhamento, entrelinha, largura máxima…
- `pos_x`, `pos_y`: onde o bloco fica, em frações do quadro (0–1). Na horizontal, o ponto é a borda esquerda,
  o centro ou a borda direita do bloco, conforme o alinhamento; na vertical, o meio do bloco.
- `entrada`, `saida` (`ANIMATIONS`) e `dur_entrada`, `dur_saida` (segundos).
- `estilo_pronto`: o id do estilo pronto (`PRESETS`) de que o título partiu (só informativo).

Desenho (`render`, o `sequence.RENDERERS["texto"]`): o texto sai do `textrender` (as fontes do app, iguais em
qualquer sistema) com alfa direto e é pré-multiplicado aqui; tudo o que a animação faz (opacidade, deslocamento,
zoom com reamostragem bilinear, máscaras de revelar e de letra por letra) são contas elemento a elemento em
float32 e polinômios (nada de seno, ângulo ou aleatório): o mesmo quadro bit a bit em qualquer computador, na
prévia e na exportação. O tempo da animação é o do clipe: a entrada começa no primeiro quadro (opacidade 0) e a
saída termina no último (opacidade 0); "Créditos rolando" ocupa o clipe inteiro (do pé ao alto do quadro). As
chaves de animação do clipe (posição, escala, opacidade, cor) vêm depois, no shader CLIP, como em todo clipe.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from . import textrender, timeline
from .i18n import N_, _
from .textrender import TextStyle

KIND = "texto"  # `timeline.SOURCE_KINDS`

# Animações de entrada e saída (id ASCII gravado no projeto: nunca renomear; acrescente no fim).
ANIMATIONS: tuple[tuple[str, str], ...] = (
    ("nenhuma", N_("Nenhuma")),
    ("aparecer", N_("Aparecer")),
    ("subir", N_("Subir")),
    ("deslizar", N_("Deslizar")),
    ("maquina", N_("Máquina de escrever")),
    ("letra", N_("Letra por letra")),
    ("zoom", N_("Zoom suave")),
    ("creditos", N_("Créditos rolando")),
    ("revelar", N_("Revelar com máscara")),
)
ANIMATION_IDS = tuple(a for a, _l in ANIMATIONS)
RISE = 40.0          # "Subir": px@1080
SLIDE = 160.0        # "Deslizar": px@1080
ZOOM_IN = 0.8        # "Zoom suave": escala no começo da entrada
ZOOM_OUT = 1.1       # e no fim da saída
REVEAL_SOFT = 60.0   # "Revelar com máscara": largura da borda suave (px@1080)
LETTER_OVERLAP = 4.0  # "Letra por letra": quantas letras aparecem ao mesmo tempo


@dataclass(frozen=True)
class Title:
    text: str = ""
    style: TextStyle = TextStyle()
    pos_x: float = 0.5
    pos_y: float = 0.5
    enter: str = "nenhuma"
    leave: str = "nenhuma"
    enter_s: float = 0.0
    leave_s: float = 0.0


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi) if math.isfinite(v) else default


def title_of(data: dict) -> Title:
    """O título de `Source.data`, com cada valor conferido."""
    d = data if isinstance(data, dict) else {}
    text = d.get("texto")
    return Title(text=text if isinstance(text, str) else "", style=TextStyle.from_json(d.get("estilo")),
                 pos_x=_num(d.get("pos_x"), 0.5, -0.5, 1.5), pos_y=_num(d.get("pos_y"), 0.5, -0.5, 1.5),
                 enter=d.get("entrada") if d.get("entrada") in ANIMATION_IDS else "nenhuma",
                 leave=d.get("saida") if d.get("saida") in ANIMATION_IDS else "nenhuma",
                 enter_s=_num(d.get("dur_entrada"), 0.0, 0.0, 30.0), leave_s=_num(d.get("dur_saida"), 0.0, 0.0, 30.0))


# ------------------------------------------------------------------ estilos prontos
@dataclass(frozen=True)
class Preset:
    id: str            # ASCII, nunca renomear
    label: str         # N_()
    text: str          # texto inicial (N_(): entra traduzido)
    style: TextStyle
    pos: tuple[float, float]
    enter: tuple[str, float]
    leave: tuple[str, float]


PRESETS: tuple[Preset, ...] = (
    Preset("titulo_grande", N_("Título grande"), N_("Título"),
           TextStyle(family="bebas", size=170.0, shadow=0.45, shadow_y=4.0, shadow_blur=10.0, letter_spacing=2.0),
           (0.5, 0.5), ("zoom", 0.8), ("aparecer", 0.6)),
    Preset("terco_inferior", N_("Terço inferior"), N_("Nome Sobrenome\nFunção"),
           TextStyle(family="atkinson", weight=700, size=50.0, align="esquerda", line_spacing=1.1, box=0.7,
                     box_color=(0.06, 0.06, 0.07), box_padding=16.0, box_radius=4.0, box_mode="bloco"),
           (0.07, 0.82), ("deslizar", 0.5), ("aparecer", 0.4)),
    Preset("cartela_cinema", N_("Cartela de cinema"), N_("Era uma vez,\nnuma cidade do interior…"),
           TextStyle(family="dm_serif", size=74.0, color=(0.94, 0.9, 0.81), line_spacing=1.25, wrap=1300.0),
           (0.5, 0.5), ("aparecer", 1.0), ("aparecer", 1.0)),
    Preset("creditos", N_("Créditos"), N_("Direção\nNome Sobrenome\n\nFotografia\nNome Sobrenome\n\n"
                                          "Montagem\nNome Sobrenome"),
           TextStyle(family="crimson", size=52.0, line_spacing=1.35, wrap=1400.0),
           (0.5, 0.5), ("creditos", 0.0), ("nenhuma", 0.0)),
    Preset("legenda_filme", N_("Legenda de filme"), N_("Uma fala curta, em duas linhas no máximo."),
           TextStyle(family="atkinson", size=46.0, outline=2.5, shadow=0.6, shadow_y=2.0, shadow_blur=3.0,
                     wrap=1500.0),
           (0.5, 0.88), ("nenhuma", 0.0), ("nenhuma", 0.0)),
    Preset("maquina", N_("Máquina de escrever"), N_("Em algum lugar, em 1974."),
           TextStyle(family="courier_prime", size=56.0, align="esquerda"),
           (0.1, 0.85), ("maquina", 1.6), ("aparecer", 0.5)),
)
PRESET_IDS = tuple(p.id for p in PRESETS)
DEFAULT_PRESET = "titulo_grande"


def preset(preset_id: str) -> Preset:
    return next((p for p in PRESETS if p.id == preset_id), PRESETS[0])


def preset_data(preset_id: str, text: str | None = None) -> dict:
    """Os campos de um estilo pronto (com o texto inicial traduzido, ou `text`)."""
    p = preset(preset_id)
    return {"texto": _(p.text) if text is None else text, "estilo": p.style.to_json(), "pos_x": p.pos[0],
            "pos_y": p.pos[1], "entrada": p.enter[0], "dur_entrada": p.enter[1], "saida": p.leave[0],
            "dur_saida": p.leave[1], "estilo_pronto": p.id}


def display_name(text: str) -> str:
    """O nome do título na Mídia: a primeira linha com texto (curta)."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    if not line:
        return _("Título")
    return line if len(line) <= 40 else line[:39].rstrip() + "…"


def new_source(seq: timeline.Sequence, preset_id: str = DEFAULT_PRESET, text: str | None = None) -> timeline.Source:
    """Título novo no tamanho e no fps da sequência, sem duração (estica como uma imagem; começa com 5 s)."""
    data = preset_data(preset_id, text)
    data = {"nome": display_name(data["texto"]), **data}
    return timeline.Source.virtual(KIND, seq.width, seq.height, seq.fps_str, seconds=None, data=data, alpha=True)


def missing(data: dict) -> str:
    """Caracteres do texto que a fonte escolhida não tem (aparecem como um retângulo)."""
    t = title_of(data)
    text = t.text.upper() if t.style.uppercase else t.text
    chars = "".join(ch for ch in text if not ch.isspace())
    return textrender.missing_chars(chars, t.style.family, t.style.weight, t.style.italic)


# ------------------------------------------------------------------ animação
@dataclass(frozen=True)
class Motion:
    opacity: float = 1.0
    dx: float = 0.0           # px@1080
    dy: float = 0.0
    scale: float = 1.0
    reveal: tuple[tuple[str, float, bool], ...] = ()   # (tipo, progresso 0–1, saída?) para as máscaras
    scroll: float = -1.0      # créditos: progresso 0–1 do rolar (−1 = sem)


def _ease(p: float) -> float:
    """Desacelera no fim (cúbica): polinômio, igual em qualquer computador."""
    q = 1.0 - min(max(p, 0.0), 1.0)
    return 1.0 - q * q * q


def motion(t: Title, elapsed: float, total: float, fps: float) -> Motion:
    """Como o título está no tempo `elapsed` (s desde o primeiro quadro do clipe) de um clipe de `total` s."""
    last = max(0.0, total - 1.0 / fps)          # tempo do último quadro
    opacity, dx, dy, scale = 1.0, 0.0, 0.0, 1.0
    reveal: list[tuple[str, float, bool]] = []
    scroll = -1.0
    if t.enter == "creditos":
        scroll = min(max(elapsed / last, 0.0), 1.0) if last > 0 else 0.0
    for kind, dur, leaving in ((t.enter, t.enter_s, False), (t.leave, t.leave_s, True)):
        if kind in ("nenhuma", "creditos") or (leaving and t.enter == "creditos"):
            continue
        p = 1.0 if dur <= 0 else min(max((last - elapsed if leaving else elapsed) / dur, 0.0), 1.0)
        e = _ease(p)
        if kind == "aparecer":
            opacity *= p
        elif kind == "subir":
            opacity *= p
            dy += (-RISE if leaving else RISE) * (1.0 - e)
        elif kind == "deslizar":
            opacity *= p
            dx += (SLIDE if leaving else -SLIDE) * (1.0 - e)
        elif kind == "zoom":
            opacity *= p
            scale *= (ZOOM_OUT + (1.0 - ZOOM_OUT) * e) if leaving else (ZOOM_IN + (1.0 - ZOOM_IN) * e)
        elif kind in ("maquina", "letra"):
            reveal.append((kind, p, leaving))
        elif kind == "revelar":
            reveal.append((kind, e, leaving))
    return Motion(opacity, dx, dy, scale, tuple(reveal), scroll)


# ------------------------------------------------------------------ desenho
@lru_cache(maxsize=32)
def _glyph_map(text: str, style: TextStyle, height: int, offset: tuple[float, float], left: int, top: int,
               w: int, h: int) -> tuple[np.ndarray, int]:
    """(índice do glifo de cada pixel da imagem do texto, total de glifos), na ordem de leitura: cada linha da
    imagem pertence à linha de texto mais perto; cada coluna, ao glifo que começa antes dela."""
    lay = textrender.measure(text, style, height)
    s = lay.scale
    track = style.letter_spacing * s
    ox, oy = offset
    gmap = np.zeros((h, w), np.int32)
    n = 0
    lines = []
    for ln in lay.lines:
        starts: list[float] = []
        for wi in ln.words:
            wb = lay.words[wi]
            sh = textrender.shape(lay.face, wb.text)
            starts += [ox + wb.x + gx * lay.em + track * i - left for i, gx in enumerate(sh.xs)]
        lines.append((ln, starts, n))
        n += len(starts)
    if not lines:
        return gmap, 0
    ys = np.arange(h, dtype=np.float64) + top - oy + 0.5   # y de cada linha da imagem no espaço do bloco
    centers = np.array([ln.y + ln.h / 2.0 for ln, _s, _n in lines])
    row_line = np.argmin(np.abs(ys[:, None] - centers[None, :]), axis=1)
    xs = np.arange(w, dtype=np.float64) + 0.5
    for li, (ln, starts, first) in enumerate(lines):
        rows = row_line == li
        if not rows.any():
            continue
        if starts:
            idx = np.searchsorted(np.array(starts), xs, side="right") - 1
            cols = first + np.clip(idx, 0, len(starts) - 1)
        else:  # linha vazia: conta como o glifo seguinte
            cols = np.full(w, first)
        gmap[rows] = cols[None, :].astype(np.int32)
    gmap.setflags(write=False)
    return gmap, n


def _resample(img: np.ndarray, scale: float, cx: float, cy: float) -> tuple[np.ndarray, int, int]:
    """Amplia/reduz a imagem pré-multiplicada (h × w × 4, float32) em volta de (cx, cy), bilinear.
    Devolve (imagem nova, deslocamento x, y da nova em relação à antiga)."""
    h, w = img.shape[:2]
    x0 = int(math.floor(cx + (0 - cx) * scale)) - 1
    y0 = int(math.floor(cy + (0 - cy) * scale)) - 1
    x1 = int(math.ceil(cx + (w - cx) * scale)) + 1
    y1 = int(math.ceil(cy + (h - cy) * scale)) + 1
    ow, oh = max(1, x1 - x0), max(1, y1 - y0)
    inv = np.float32(1.0 / scale)
    u = (np.arange(ow, dtype=np.float32) + np.float32(x0 + 0.5) - np.float32(cx)) * inv + np.float32(cx - 0.5)
    v = (np.arange(oh, dtype=np.float32) + np.float32(y0 + 0.5) - np.float32(cy)) * inv + np.float32(cy - 0.5)
    iu, iv = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    fu, fv = (u - iu).astype(np.float32), (v - iv).astype(np.float32)
    pad = np.zeros((h + 2, w + 2, 4), np.float32)
    pad[1:-1, 1:-1] = img
    cu0, cu1 = np.clip(iu + 1, 0, w + 1), np.clip(iu + 2, 0, w + 1)
    cv0, cv1 = np.clip(iv + 1, 0, h + 1), np.clip(iv + 2, 0, h + 1)
    top = pad[cv0][:, cu0] * (1 - fu)[None, :, None] + pad[cv0][:, cu1] * fu[None, :, None]
    bot = pad[cv1][:, cu0] * (1 - fu)[None, :, None] + pad[cv1][:, cu1] * fu[None, :, None]
    out = top * (1 - fv)[:, None, None] + bot * fv[:, None, None]
    return out.astype(np.float32), x0, y0


def draw(t: Title, elapsed: float, total: float, fps: float, w: int, h: int, depth: int) -> np.ndarray:
    """O título num quadro w × h no tempo `elapsed` de um clipe de `total` s: RGBA pré-multiplicado."""
    out_dtype = np.uint8 if depth == 8 else np.uint16
    canvas = np.zeros((h, w, 4), out_dtype)
    if not t.text.strip():
        return canvas
    m = motion(t, elapsed, total, fps)
    if m.opacity <= 0.0:
        return canvas
    st = t.style
    s = h / textrender.REF_HEIGHT
    lay = textrender.measure(t.text, st, h)
    k = {"esquerda": 0.0, "centro": 0.5, "direita": 1.0}.get(st.align, 0.5)
    bx = t.pos_x * w - k * lay.width + m.dx * s
    by = t.pos_y * h - lay.height / 2.0 + m.dy * s
    if m.scroll >= 0.0:  # créditos: do pé (o bloco todo abaixo do quadro) ao alto (todo acima)
        probe = textrender.render(t.text, st, h, depth=16)
        start, end = h - probe.top, -(probe.top + probe.height)
        by = start + (end - start) * m.scroll + m.dy * s
    ix, iy = int(math.floor(bx)), int(math.floor(by))
    off = (round(bx - ix, 4), round(by - iy, 4))
    img = textrender.render(t.text, st, h, depth=16, offset=off)
    a = img.rgba[..., 3:4].astype(np.float32) / np.float32(65535.0)
    pm = np.concatenate([img.rgba[..., :3].astype(np.float32) / np.float32(65535.0) * a, a], axis=2)
    if m.opacity < 1.0:
        pm *= np.float32(m.opacity)
    for kind, p, leaving in m.reveal:
        if kind == "revelar":
            soft = max(1.0, REVEAL_SOFT * s)
            span = img.width + soft
            x = np.arange(img.width, dtype=np.float32) + np.float32(0.5)
            if leaving:
                mask = np.clip((x + np.float32(soft - (1.0 - p) * span)) / np.float32(soft), 0, 1)
            else:
                mask = np.clip((np.float32(p * span) - x) / np.float32(soft), 0, 1)
            pm *= mask[None, :, None]
            continue
        gmap, n = _glyph_map(t.text, st, h, off, img.left, img.top, img.width, img.height)
        if n == 0:
            continue
        if kind == "maquina":
            shown = int(math.floor(p * n + 1e-9))
            pm *= (gmap < shown).astype(np.float32)[..., None]
        else:  # letra por letra: cada letra aparece (ou some) em LETTER_OVERLAP letras
            pos = np.float32(p * (n + LETTER_OVERLAP))
            alpha = np.clip((pos - gmap.astype(np.float32)) / np.float32(LETTER_OVERLAP), 0, 1)
            if leaving:  # some da primeira para a última
                alpha = np.clip((gmap.astype(np.float32) + np.float32(LETTER_OVERLAP) -
                                 np.float32((1.0 - p) * (n + LETTER_OVERLAP))) / np.float32(LETTER_OVERLAP), 0, 1)
            pm *= alpha[..., None]
    ax, ay = ix + img.left, iy + img.top
    if abs(m.scale - 1.0) > 1e-6:
        cx = bx + lay.width / 2.0 - ax
        cy = by + lay.height / 2.0 - ay
        pm, sx, sy = _resample(pm, m.scale, cx, cy)
        ax, ay = ax + sx, ay + sy
    ph, pw = pm.shape[:2]
    x0, y0, x1, y1 = max(0, ax), max(0, ay), min(w, ax + pw), min(h, ay + ph)
    if x0 >= x1 or y0 >= y1:
        return canvas
    mx = np.float32(255.0 if depth == 8 else 65535.0)
    part = np.clip(pm[y0 - ay:y1 - ay, x0 - ax:x1 - ax], 0, 1)
    canvas[y0:y1, x0:x1] = np.floor(part * mx + np.float32(0.5)).astype(out_dtype)
    return canvas


def clip_time(seq: timeline.Sequence, clip: timeline.Clip, frame: int, fps: float) -> tuple[float, float]:
    """(tempo desde o primeiro quadro do clipe, duração do clipe), em segundos da fonte, para o quadro `frame` da
    fonte: contados em quadros da fonte entre o primeiro e o último quadro que o clipe mostra (`Sequence.src_frame`,
    com aparar e velocidade), então o primeiro quadro é sempre o começo da entrada e o último, o fim da saída."""
    if clip.frozen:  # quadro congelado: o título inteiro, parado
        return 1e6, 2e6
    f0 = seq.src_frame(clip, clip.start)
    f1 = seq.src_frame(clip, clip.end - 1)
    return (int(frame) - f0) / fps, (f1 - f0 + 1) / fps


def render(seq: timeline.Sequence, clip: timeline.Clip, frame: int, w: int, h: int, depth: int) -> np.ndarray:
    """`sequence.RENDERERS["texto"]`."""
    src = seq.sources[clip.src]
    fps = src.fps if src.fps > 0 else seq.fps
    elapsed, total = clip_time(seq, clip, int(frame), fps)
    return draw(title_of(src.data), elapsed, total, fps, int(w), int(h), int(depth))


def thumbnail_frame(src: timeline.Source) -> int:
    """Miniatura: o título já de pé (depois da entrada; nos créditos, no meio dos 5 s iniciais)."""
    t = title_of(src.data)
    if t.enter == "creditos":
        return int(round(timeline.IMAGE_SECONDS / 2 * src.fps))
    return int(math.ceil(t.enter_s * src.fps)) + 1


def register() -> None:
    """Registra o título (desenho e miniatura). Chamado por `sequence` ao ser importado."""
    from . import sequence
    sequence.RENDERERS.setdefault(KIND, render)
    sequence.THUMBNAIL_FRAME.setdefault(KIND, thumbnail_frame)


def with_text(data: dict, text: str) -> dict:
    """`data` com o texto novo (e o nome da Mídia acompanhando a primeira linha)."""
    out = copy.deepcopy(dict(data))
    out["texto"] = text
    out["nome"] = display_name(text)
    return out
