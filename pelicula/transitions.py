"""Transições de película da 1.5: fusão ótica, exposição, queima, emenda, ponta, íris, empurrar, cortina e zoom.

Funções puras (sem GPU nem Qt). `Sequence.layers_at` descreve a transição em cada camada (`timeline.Transition`:
tipo, lado, papel, andamento, quadro e dono); `compositor.clip_uniforms` chama `apply`, que acrescenta os uniforms
de `editshaders.CLIP_TR` e, nas que mexem na geometria (empurrar, zoom e o pulo da emenda), troca a matriz do
enquadramento `u_xf`. As transições de antes (dissolver, preto, branco, transparente) não passam por aqui:
continuam no programa `editshaders.CLIP`, bit a bit.

- **Luz**: misturas e ganhos são feitos na luz da curva de entrada do look (`look.INPUT_IDS`, com o domínio da
  curva e a faixa do arquivo, como em `look.build_plan(..., legal=...)`): `light_of(values, legal)`. Sem look (modo
  Edição sem película) a curva é a do vídeo comum (rec709), a mesma do look "Original" que a exportação sem
  película usa. A fórmula corrigida do shader (`lightMix`) dá as pontas exatas, mantém o cinza neutro e só
  troca a mistura no código pela mistura na luz.
- **Determinismo**: o ruído (borda da queima, poeira e riscos da ponta, linha da emenda) vem de `seed_of(id do
  clipe dono)` e do quadro dentro da transição (`Transition.index`): o mesmo clipe dá o mesmo quadro em qualquer
  ponto da linha do tempo, na prévia e na exportação.
- **px@1080**: distâncias do esquema são pixels de um quadro de 1080 linhas (`scale = altura da tela / 1080`).
- **Pontas** (`active`): andamento 1 no clipe que entra, ou 0 no que sai e na base, é o clipe puro — a camada
  volta ao caminho de sempre. No andamento 0 do clipe que entra só se vê o que está por baixo, ou o começo da
  transição (preto na exposição, a ponta, o clarão da emenda).
"""

from __future__ import annotations

import math
import zlib
from typing import Any

import numpy as np

KIND_IDS = {"fusao": 1, "exposicao": 2, "queima": 3, "emenda": 4, "ponta": 5, "iris": 6, "empurrar": 7,
            "cortina": 8, "zoom": 9}
ROLE_IDS = {"entra": 0, "sai": 1, "base": 2}
GEOMETRIC = ("empurrar", "zoom")     # a cauda do clipe anterior (papel "base") também se move
TWO_CLIP = ("fusao", "queima", "iris", "empurrar", "cortina", "zoom")  # = editparams.EXTRA_TWO_CLIP
DIRECTIONS = {"direita": (1.0, 0.0), "esquerda": (-1.0, 0.0), "baixo": (0.0, 1.0), "cima": (0.0, -1.0)}
REC709 = (0, False)                  # (curva `look.INPUT_IDS`, código de 10 bits em faixa legal)

EMENDA_FLASH = (1.0, 0.45, 0.18)     # força do clarão nos quadros 1, 2 e 3 da emenda
EMENDA_JUMP = (8.0, 3.0)             # px@1080 que a imagem desce nos dois primeiros quadros (a emenda pula)
EMENDA_VEIL = 0.05                   # véu de luz (luz linear) por EV de clarão: o preto também estoura
PONTA_HOLE = 55.0                    # px@1080: raio do furo de perfuração no quadro do meio da ponta
BURN_REACH = 400.0                   # px@1080 além do canto: contorno irregular + brilho + chamuscado (shader)

# Ajustes de cada tipo (a interface mostra só estes; a duração fica sempre à vista, menos na emenda).
PARAMS = {
    ("entrada", "fusao"): (),
    ("entrada", "exposicao"): (),
    ("entrada", "queima"): ("entrada_centro_x", "entrada_centro_y", "entrada_suavidade"),
    ("entrada", "emenda"): ("entrada_quadros", "entrada_clarao"),
    ("entrada", "ponta"): ("entrada_ponta",),
    ("entrada", "iris"): ("entrada_centro_x", "entrada_centro_y", "entrada_suavidade", "entrada_anel"),
    ("entrada", "empurrar"): ("entrada_direcao",),
    ("entrada", "cortina"): ("entrada_direcao", "entrada_suavidade"),
    ("entrada", "zoom"): ("entrada_centro_x", "entrada_centro_y", "entrada_zoom"),
    ("saida", "exposicao"): (),
    ("saida", "queima"): ("saida_centro_x", "saida_centro_y", "saida_suavidade"),
    ("saida", "iris"): ("saida_centro_x", "saida_centro_y", "saida_suavidade", "saida_anel"),
}
EXTRA_KEYS = tuple(sorted({k for keys in PARAMS.values() for k in keys}))  # todas em editparams.SPARSE_KEYS


def params_for(side: str, kind: str) -> tuple[str, ...]:
    """Chaves de ajuste que o tipo `kind` do lado `side` ("entrada"/"saida") usa, além do tipo e da duração.
    Tipos de antes e o corte: nenhuma."""
    return PARAMS.get((side, kind), ())


def uses_duration(side: str, kind: str) -> bool:
    """O tipo usa a duração em segundos (`entrada_dur`/`saida_dur`)? A emenda conta quadros."""
    return kind != "corte" and not (side == "entrada" and kind == "emenda")


# ------------------------------------------------------------------ luz, semente e andamento
def light_of(values: dict[str, Any] | None, legal: bool = True) -> tuple[int, bool]:
    """(curva, código de 10 bits) da luz em que as transições misturam: a entrada do look `values` (os ajustes
    de película do quadro), na faixa do arquivo (`legal`, como `look.build_plan`). None = sem look: rec709."""
    if not values:
        return REC709
    from . import look
    entrada = values.get("entrada", "rec709")
    cv = look.code_value_curve(entrada) and not values.get("log_reescalado") and bool(legal)
    return int(look.INPUT_IDS.get(entrada, 0)), bool(cv)


def seed_of(owner: str) -> int:
    """Semente do ruído de uma transição: o hash estável do id do clipe dono (igual em toda máquina)."""
    return zlib.crc32(str(owner).encode("utf-8")) & 0x7FFFFFFF


def _unit(seed: int, k: int) -> float:
    """Número de 0 a 1 só da semente e de `k` (sem `random`)."""
    return (zlib.crc32(f"{seed}:{k}".encode("ascii")) & 0xFFFFFFFF) / 4294967296.0


def ease(p: float) -> float:
    """Suaviza o andamento nas pontas (empurrar e zoom): 3p² − 2p³."""
    p = min(max(p, 0.0), 1.0)
    return p * p * (3.0 - 2.0 * p)


def _ease_speed(p: float) -> float:
    """Derivada de `ease`: quanto o movimento anda por unidade de andamento."""
    p = min(max(p, 0.0), 1.0)
    return 6.0 * p * (1.0 - p)


def active(layer) -> list:
    """As transições da camada que mudam alguma coisa neste quadro (no máximo duas: a de entrada e a de saída).
    Fora delas a camada é desenhada pelo caminho de sempre: o clipe que entra com andamento 1, o que sai com
    andamento 0, e a base (cauda do clipe anterior) parada ou no começo."""
    out = []
    for tr in getattr(layer, "transitions", ()):
        if tr.kind not in KIND_IDS:
            continue
        if tr.role == "entra" and tr.progress >= 1.0:
            continue
        if tr.role in ("sai", "base") and tr.progress <= 0.0:
            continue
        if tr.role == "base" and tr.kind not in GEOMETRIC:
            continue
        out.append(tr)
    return out[:2]


# ------------------------------------------------------------------ geometria (px da tela)
def _translate(dx: float, dy: float) -> np.ndarray:
    """Pixel da tela → pixel da imagem parada, com a imagem deslocada de (dx, dy)."""
    return np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy], [0.0, 0.0, 1.0]])


def _scale_about(cx: float, cy: float, s: float) -> np.ndarray:
    """Pixel da tela → pixel da imagem parada, com a imagem ampliada `s` vezes em volta de (cx, cy)."""
    return np.array([[1.0 / s, 0.0, cx - cx / s], [0.0, 1.0 / s, cy - cy / s], [0.0, 0.0, 1.0]])


def _center(vals: dict[str, Any], side: str, w: int, h: int) -> tuple[float, float, float]:
    """Centro (px) e a maior distância dele até um canto da tela."""
    cx = w / 2.0 + float(vals.get(f"{side}_centro_x", 0.0)) * w
    cy = h / 2.0 + float(vals.get(f"{side}_centro_y", 0.0)) * h
    rmax = max(math.hypot(x - cx, y - cy) for x in (0.0, float(w)) for y in (0.0, float(h)))
    return cx, cy, rmax


# ------------------------------------------------------------------ uniforms
def apply(U: dict[str, Any], seq, layer, xf: np.ndarray, canvas_w: int, canvas_h: int,
          light: tuple[int, bool] | None = None) -> dict[str, Any]:
    """Os uniforms da camada com as transições novas (programa `CLIP_TR`); sem transição ativa, `U` como veio
    (programa `CLIP`). `xf` é a matriz do enquadramento da camada (`compositor.transform`)."""
    trs = active(layer)
    if not trs:
        return U
    from .compositor import mat3_uniform
    w, h = int(canvas_w), int(canvas_h)
    sc = h / 1080.0
    kinds, roles, prog, index, seeds = [0, 0], [0, 0], [0.0, 0.0], [0, 0], [0, 0]
    A = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)]
    B = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)]
    geo = np.eye(3)
    zoom = 1.0
    blur = (0.0, 0.0, 0.0, 0.0)
    for i, tr in enumerate(trs):
        owner = layer.clip if tr.owner == layer.clip.id else seq.find(tr.owner)
        if owner is None:
            continue
        vals = layer.values if (owner is layer.clip and layer.values is not None) else owner.values
        side, kind = tr.side, tr.kind
        p = min(max(float(tr.progress), 0.0), 1.0)
        n = max(1, int(tr.frames))
        seed = seed_of(tr.owner)
        kinds[i], roles[i], prog[i] = KIND_IDS[kind], ROLE_IDS[tr.role], p
        index[i], seeds[i] = int(tr.index), seed
        soft = float(vals.get(f"{side}_suavidade", 24.0)) * sc
        if kind in ("queima", "iris"):
            cx, cy, rmax = _center(vals, side, w, h)
            A[i] = (cx, cy, rmax, soft)
            if kind == "iris":
                B[i] = (float(vals.get(f"{side}_anel", 0.0)) * sc, 0.0, 0.0, 0.0)
        elif kind in ("cortina", "empurrar"):
            dx, dy = DIRECTIONS.get(vals.get("entrada_direcao", "direita"), (1.0, 0.0))
            length = float(w if dx else h)
            if kind == "cortina":
                # pos = distância até a borda por onde o clipe entra: n·q + deslocamento
                off = (w if dx > 0 else 0.0) if dx else (h if dy > 0 else 0.0)
                A[i] = (-dx, -dy, float(off), soft)
                B[i] = (length, 0.0, 0.0, 0.0)
            else:
                e = ease(p)
                shift = (1.0 - e) * length if tr.role == "entra" else -e * length
                geo = geo @ _translate(dx * shift, dy * shift)
                speed = 0.5 * length * _ease_speed(p) / (n + 1)  # obturador de 180°: meio quadro de movimento
                if speed > 0.75:
                    blur = (1.0, dx * speed, dy * speed, 0.0)
        elif kind == "zoom":
            cx, cy, _rmax = _center(vals, side, w, h)
            z = max(1.0, float(vals.get("entrada_zoom", 2.0)))
            e = ease(p)
            s = z ** (1.0 - e) if tr.role == "entra" else z ** e
            geo = geo @ _scale_about(cx, cy, s)
            zoom *= s
            A[i] = (cx, cy, 0.0, 0.0)
            k = 0.5 * math.log(z) * _ease_speed(p) / (n + 1)
            if k * max(w, h) > 0.75:
                blur = (2.0, cx, cy, k)
        elif kind == "emenda":
            f = EMENDA_FLASH[min(tr.index, len(EMENDA_FLASH) - 1)]
            ev = float(vals.get("entrada_clarao", 2.0)) * f
            veil = EMENDA_VEIL * f * float(vals.get("entrada_clarao", 2.0))
            line_y = h * ((0.04 + 0.08 * _unit(seed, 1)) if _unit(seed, 0) < 0.5 else (0.88 + 0.08 * _unit(seed, 1)))
            side_sign = 1.0 if _unit(seed, 2) < 0.5 else -1.0
            A[i] = (float(2.0 ** ev), veil, line_y, 1.0 if tr.index == 0 else 0.0)
            B[i] = (side_sign, 0.0, 0.0, 0.0)
            if tr.index < len(EMENDA_JUMP):
                geo = geo @ _translate(0.0, EMENDA_JUMP[tr.index] * sc)
        elif kind == "ponta":
            clear = 1.0 if vals.get("entrada_ponta") == "clara" else 0.0
            hx = w * (0.22 + 0.56 * _unit(seed, 3))
            hy = h * (0.25 + 0.5 * _unit(seed, 4))
            A[i] = (clear, hx, hy, PONTA_HOLE * sc)
            B[i] = (1.0 if tr.index == n // 2 else 0.0, 0.0, 0.0, 0.0)
    U = dict(U)
    if any(tr.role == "entra" and tr.kind in TWO_CLIP and tr.progress <= 0.0 for tr in trs):
        U["u_alpha"] = 0.0  # andamento 0 de uma transição de dois clipes: só o que está por baixo, exato
    if not np.allclose(geo, np.eye(3), atol=0.0, rtol=0.0):
        U["u_xf"] = mat3_uniform(np.asarray(xf, dtype=np.float64) @ geo)
        U["u_exact"] = 0
        if zoom != 1.0:
            ppu = U["u_px_per_uv"]
            U["u_px_per_uv"] = (float(ppu[0] * zoom), float(ppu[1] * zoom))
    curve, cv = light if light is not None else REC709
    U.update({
        "u_tr_input": int(curve),
        "u_tr_cv": 1 if cv else 0,
        "u_tr_scale": float(sc),
        "u_tr_kind": tuple(kinds),
        "u_tr_role": tuple(roles),
        "u_tr_p": tuple(float(x) for x in prog),
        "u_tr_index": tuple(index),
        "u_tr_seed": tuple(seeds),
        "u_tr_a": tuple(tuple(float(x) for x in a) for a in A),
        "u_tr_b": tuple(tuple(float(x) for x in b) for b in B),
        "u_tr_blur": tuple(float(x) for x in blur),
    })
    return U

