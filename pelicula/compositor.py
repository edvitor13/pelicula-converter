"""Ajustes por clipe do modo Edição → uniforms do shader `editshaders.CLIP`.

Funções puras (sem GPU nem Qt): o mesmo clipe, a mesma camada e o mesmo tamanho de tela dão sempre
os mesmos valores, então a prévia, o "Salvar quadro" e a exportação mostram exatamente a mesma
montagem. `Engine.compose()` desenha as camadas de um quadro com estes valores.

Como cada ajuste é interpretado (valores de vídeo Rec.709 de 0 a 1, chamados "código"):

- **Exposição e balanço de branco** em luz (código^2,2): `× 2^EV` e ganhos por canal com a mesma
  mistura de temperatura/tonalidade do look de película.
- **Tons** (mesma função em R, G e B): pontos preto/branco, realces e sombras (curvas suaves que
  não mexem nas pontas), curva de 4 faixas, brilho dos tons médios (expoente) e contraste em S
  (`x − k·sen(2πx)/2π`, fixa o 0, o 0,5 e o 1).
- **Rodas de cor**: levantar/gama/ganho por canal. A roda guarda um ponto [x, y] no disco unitário:
  ângulo de `atan2(y, x)` = matiz (0° vermelho, 120° verde, 240° azul, sentido anti-horário com y
  para cima) e distância = força.
- **Cor**: saturação e vibração em torno da luminância Rec.709, rotação de matiz no plano Cb/Cr e
  HSL de 8 faixas (partição suave entre as faixas vizinhas, sem efeito em cinzas).
- **Detalhe**: redução de ruído bilateral 5×5, desfoque por mipmap, nitidez (máscara de nitidez) e
  clareza (contraste local contra um mipmap bem desfocado). Raios proporcionais à altura do clipe.
- **Enquadramento**: desespremer (`desqueeze`), encaixe (mostrar inteiro, preencher, esticar), escala (e por eixo:
  `axis_scale`), posição (fração da tela, y para baixo), rotação (graus, positivo = horário na tela), espelhos e corte.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import editparams, timeline

BLEND_IDS = {"normal": 0, "tela": 1, "multiplicar": 2, "sobrepor": 3, "adicionar": 4, "clarear": 5,
             "escurecer": 6}
DETAIL_KEYS = ("nitidez", "clareza", "desfoque", "reducao_ruido")
W709 = (0.2126, 0.7152, 0.0722)

_DEFAULTS = editparams.VIDEO.defaults()
_COLOR_KEYS = [k for k in editparams.color_keys() if k not in DETAIL_KEYS]
# Taxas do desespremer do clipe. Tabela própria: a da Lente anamórfica do look (`anamorfico.SQUEEZES`) não tem 1,55.
DESQUEEZE = {"nao": 1.0, "1.33": 1.33, "1.5": 1.5, "1.55": 1.55, "1.8": 1.8, "2.0": 2.0}


def mat3_uniform(m: np.ndarray) -> tuple:
    """GLSL espera matrizes por coluna (igual a `look.mat3_uniform`)."""
    return tuple(float(x) for x in np.asarray(m, dtype=np.float64).T.flatten())


def hue_rgb(hue_deg: float) -> tuple[float, float, float]:
    """Cor pura (saturação e valor 1) de um matiz em graus."""
    h = (hue_deg % 360.0) / 60.0
    x = 1.0 - abs(h % 2.0 - 1.0)
    return [(1.0, x, 0.0), (x, 1.0, 0.0), (0.0, 1.0, x), (0.0, x, 1.0), (x, 0.0, 1.0), (1.0, 0.0, x)][int(h) % 6]


def wheel_tint(w) -> tuple[float, float, float]:
    """Desvio de cor (sem mudar a luminância) de um ponto da roda [x, y].

    Mesma convenção da interface: matiz = atan2(y, x) em graus como no HSV — 0° vermelho em +x,
    sentido anti-horário com y para cima (60° amarelo, 120° verde, 180° ciano, 240° azul,
    300° magenta) — e força = distância ao centro (≤ 1).
    """
    x, y = float(w[0]), float(w[1])
    r = min(1.0, math.hypot(x, y))
    if r < 1e-6:
        return (0.0, 0.0, 0.0)
    rgb = hue_rgb(math.degrees(math.atan2(y, x)))
    luma = sum(a * b for a, b in zip(rgb, W709))
    return tuple((c - luma) * r for c in rgb)


def wheel_hue(w) -> float:
    """Matiz (graus) de um ponto da roda; útil para desenhar o anel de cores na interface."""
    return math.degrees(math.atan2(float(w[1]), float(w[0]))) % 360.0


def wb_gains_ev(temp: float, tint: float) -> tuple[float, float, float]:
    """Ganhos em EV por canal para temperatura e tonalidade de -100 a 100 (mesma mistura do look)."""
    t, ti = temp / 100.0, tint / 100.0
    return (0.28 * t + 0.08 * ti, -0.22 * ti, -0.38 * t + 0.08 * ti)


def color_active(v: dict[str, Any]) -> bool:
    return any(v.get(k) != _DEFAULTS[k] for k in _COLOR_KEYS)


def detail_active(v: dict[str, Any]) -> bool:
    return any(v.get(k) != _DEFAULTS[k] for k in DETAIL_KEYS)


def desqueeze(v: dict[str, Any]) -> float:
    """Quanto o clipe fica mais largo antes do encaixe (1 = sem desespremer); a taxa manual só vale com "manual"."""
    kind = v.get("desespremer", "nao")
    if kind == "manual":
        return min(max(float(v.get("desespremer_taxa", 1.0)), 1.0), 2.5)
    return DESQUEEZE.get(kind, 1.0)


def fit_box(seq: timeline.Sequence, clip: timeline.Clip, canvas_w: int, canvas_h: int,
            values: dict[str, Any] | None = None) -> tuple[float, float]:
    """Tamanho (px da tela) do clipe com escala 1, conforme o encaixe e na proporção já desespremida ("Esticar"
    ocupa a área e ignora o desespremer), dentro da janela útil da sequência (sem janela, a tela). Um clipe sem arquivo
    (título, cor…) não tem proporção própria: com janela, ele nasce do tamanho dela. `values`: os ajustes no quadro
    (`Layer.values`, com as chaves de animação); None = os do clipe."""
    src = seq.sources.get(clip.src)
    _x, _y, aw, ah = seq.window_rect(canvas_w, canvas_h)
    sw = float(src.width if src and src.width else aw)
    sh = float(src.height if src and src.height else ah)
    if seq.window and src is not None and not src.is_file:
        sw, sh = float(aw), float(ah)
    v = values if values is not None else clip.values
    mode = v.get("encaixe", "ajustar")
    if mode == "esticar":
        return float(aw), float(ah)
    sw *= desqueeze(v)
    f = min(aw / sw, ah / sh) if mode == "ajustar" else max(aw / sw, ah / sh)
    return sw * f, sh * f


def axis_scale(v: dict[str, Any]) -> tuple[float, float]:
    """Escala final de cada eixo do clipe, antes da rotação: `escala × escala_x` e `escala × escala_y`."""
    s = float(v["escala"])
    return s * float(v.get("escala_x", 1.0)), s * float(v.get("escala_y", 1.0))


def transform(seq: timeline.Sequence, clip: timeline.Clip, canvas_w: int, canvas_h: int,
              values: dict[str, Any] | None = None) -> np.ndarray:
    """Matriz 3×3 que leva um pixel da tela (x, y, 1) ao uv do clipe (0 a 1)."""
    v = values if values is not None else clip.values
    bw, bh = fit_box(seq, clip, canvas_w, canvas_h, v)
    sx, sy = axis_scale(v)
    th = math.radians(float(v["rotacao"]))
    cs, sn = math.cos(th), math.sin(th)
    ax0, ay0, aw, ah = seq.window_rect(canvas_w, canvas_h)  # a posição é fração da janela útil (sem janela, da tela)
    cx = ax0 + aw / 2.0 + float(v["pos_x"]) * aw
    cy = ay0 + ah / 2.0 + float(v["pos_y"]) * ah
    fx = -1.0 if v["espelhar_h"] else 1.0
    fy = -1.0 if v["espelhar_v"] else 1.0
    ax = fx / (sx * bw)
    ay = fy / (sy * bh)
    # q = R(-θ)(p - c);  u = 0,5 + fx·q.x / (sx·bw);  v = 0,5 + fy·q.y / (sy·bh)
    return np.array([
        [ax * cs, ax * sn, 0.5 - ax * (cs * cx + sn * cy)],
        [-ay * sn, ay * cs, 0.5 - ay * (-sn * cx + cs * cy)],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)


def is_identity(seq: timeline.Sequence, clip: timeline.Clip, tex_w: int, tex_h: int, canvas_w: int,
                canvas_h: int, values: dict[str, Any] | None = None) -> bool:
    """O clipe cobre a tela pixel a pixel (sem reamostrar): a saída pode ser bit a bit."""
    if (tex_w, tex_h) != (canvas_w, canvas_h):
        return False
    v = values if values is not None else clip.values
    if any(v[k] for k in ("corte_esq", "corte_dir", "corte_topo", "corte_base", "espelhar_h", "espelhar_v")):
        return False
    m = transform(seq, clip, canvas_w, canvas_h, v)
    ref = np.array([[1.0 / canvas_w, 0, 0], [0, 1.0 / canvas_h, 0], [0, 0, 1]])
    return bool(np.allclose(m, ref, atol=1e-12, rtol=0))


def clip_uniforms(seq: timeline.Sequence, layer: timeline.Layer, tex_w: int, tex_h: int, canvas_w: int,
                  canvas_h: int, neutral: bool = False, tex_alpha: bool = False,
                  light: tuple[int, bool] | None = None) -> tuple[dict[str, Any], bool]:
    """Uniforms de uma camada. Devolve (uniforms, precisa_de_mipmap).

    `neutral=True` mantém enquadramento, opacidade e transições, mas desliga cor e detalhe (a imagem
    "original" da comparação no modo Edição). `tex_alpha`: a imagem tem 4 canais (RGBA pré-multiplicado de
    uma fonte com transparência, `sequence.LayerImage`). `light`: a luz das transições da 1.5
    (`transitions.light_of`; None = rec709); com uma delas na camada, os uniforms são os de `CLIP_TR`.
    """
    clip = layer.clip
    # Os ajustes neste quadro: com chaves de animação, já avaliados (`Sequence.values_at` → `Layer.values`).
    v = layer.values if layer.values is not None else clip.values
    bw, bh = fit_box(seq, clip, canvas_w, canvas_h, v)
    sx, sy = axis_scale(v)
    U: dict[str, Any] = {
        "u_canvas": (float(canvas_w), float(canvas_h)),
        "u_clip_px": (float(tex_w), float(tex_h)),
        "u_xf": mat3_uniform(transform(seq, clip, canvas_w, canvas_h, v)),
        "u_px_per_uv": (float(sx * bw), float(sy * bh)),
        "u_exact": 1 if is_identity(seq, clip, tex_w, tex_h, canvas_w, canvas_h, v) else 0,
        "u_crop": (float(v["corte_esq"]), float(v["corte_topo"]), float(v["corte_dir"]), float(v["corte_base"])),
        "u_alpha": float(v["opacidade"]) * float(layer.alpha),
        "u_tex_alpha": 1 if tex_alpha else 0,
        "u_blend": BLEND_IDS.get(v["mesclagem"], 0),
        "u_fade": tuple(float(c) for c in layer.fade_color) + (float(layer.fade),),
    }
    cc = (not neutral) and color_active(v)
    det = (not neutral) and detail_active(v)
    U["u_cc_on"] = 1 if cc else 0
    U["u_det_on"] = 1 if det else 0
    mip = False

    # ---- detalhe
    U["u_texel"] = max(1.0, tex_h / 1080.0)
    U["u_sharp"] = float(v["nitidez"]) if det else 0.0
    U["u_denoise"] = float(v["reducao_ruido"]) if det else 0.0
    U["u_blur"] = float(v["desfoque"]) * 0.02 * tex_h if det else 0.0
    U["u_clarity"] = float(v["clareza"]) if det else 0.0
    U["u_clarity_lod"] = max(0.0, math.log2(max(1.0, 0.025 * tex_h)))
    if det and (U["u_blur"] > 0 or U["u_clarity"] != 0):
        mip = True

    # ---- cor
    gains = wb_gains_ev(v["temperatura"], v["tonalidade"])
    U["u_exp"] = float(v["exposicao"])
    U["u_wb"] = tuple(float(2.0 ** g) for g in gains)
    U["u_levels"] = (-0.1 * float(v["pretos"]), 1.0 - 0.15 * float(v["brancos"]))
    U["u_hs"] = (float(v["realces"]), float(v["sombras"]))
    U["u_curve"] = (float(v["curva_sombras"]), float(v["curva_escuros"]), float(v["curva_claros"]),
                    float(v["curva_realces"]))
    U["u_bright"] = float(2.0 ** (-0.8 * float(v["brilho"])))
    U["u_contrast"] = 0.8 * float(v["contraste"])
    ts, tm, th = wheel_tint(v["roda_sombras"]), wheel_tint(v["roda_meios"]), wheel_tint(v["roda_luzes"])
    U["u_lift"] = tuple(0.12 * float(v["roda_sombras_luz"]) + 0.15 * c for c in ts)
    U["u_gamma"] = tuple(float(2.0 ** (-(0.6 * float(v["roda_meios_luz"]) + 0.7 * c))) for c in tm)
    U["u_cgain"] = tuple(1.0 + 0.35 * float(v["roda_luzes_luz"]) + 0.3 * c for c in th)
    U["u_sat"] = 1.0 + float(v["saturacao"])
    U["u_vib"] = float(v["vibracao"])
    U["u_hue_rot"] = math.radians(float(v["matiz"]))
    hh, hs, hl = [], [], []
    for key, _label, _hue in editparams.HSL_COLORS:
        hh.append(float(v[f"hsl_{key}_matiz"]))
        hs.append(float(v[f"hsl_{key}_sat"]))
        hl.append(float(v[f"hsl_{key}_luz"]))
    U["u_hsl_on"] = 1 if any(hh + hs + hl) else 0
    U["u_hsl_h"], U["u_hsl_s"], U["u_hsl_l"] = tuple(hh), tuple(hs), tuple(hl)
    U["u_vig"] = (float(v["vinheta"]), 0.2 + 0.8 * float(v["vinheta_tamanho"]))
    U["u_fadeblk"] = float(v["desbotar"])
    if cc:  # 1.6: cor simples (`colorsimple.py`); sem ela, {} e o programa é o `CLIP` de sempre
        from . import colorsimple
        U.update(colorsimple.uniforms(v))
    if layer.transitions:  # 1.5: transições de película (`transitions.py`, programa `editshaders.CLIP_TR`)
        from . import transitions
        U = transitions.apply(U, seq, layer, transform(seq, clip, canvas_w, canvas_h, v), canvas_w, canvas_h, light)
    return U, mip


# ------------------------------------------------------------------ ajuste automático
def _to_float(img: np.ndarray, step: int = 4) -> np.ndarray:
    sub = np.asarray(img)[::step, ::step]
    scale = 65535.0 if sub.dtype == np.uint16 else 255.0 if sub.dtype == np.uint8 else 1.0
    px = sub.reshape(-1, sub.shape[-1]).astype(np.float64) / scale
    if px.shape[1] == 4:  # transparência (RGBA pré-multiplicado): só a parte quase opaca, com a cor do clipe
        keep = px[px[:, 3] >= 0.5]
        if len(keep):
            return keep[:, :3] / keep[:, 3:4]
        px = px[:, :3]
    return px[:, :3]


def _snap(v: float, key: str) -> float:
    p = editparams.VIDEO.params[key]
    v = min(max(v, p.min), p.max)
    return round(round(v / p.step) * p.step, 4) if p.step else v


def auto_adjust(img: np.ndarray) -> dict[str, float]:
    """Exposição, balanço de branco e níveis automáticos para um quadro (numpy RGB 8/16 bits).

    Usa a mesma matemática do shader: o resultado aplicado ao quadro deixa o cinza médio perto de
    0,42, os tons médios neutros e estica pretos e brancos sem cortar mais que 0,5% da imagem.
    """
    rgb = _to_float(img)
    if rgb.size == 0:
        return {}
    lum = rgb @ np.array(W709)
    out: dict[str, float] = {}

    # Balanço de branco (mundo cinza nos tons médios pouco saturados).
    lin = np.maximum(rgb, 0.0) ** 2.2
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    mask = (lum > 0.12) & (lum < 0.88) & (sat < 0.5)
    temp = tint = 0.0
    if mask.sum() > 50:
        means = lin[mask].mean(axis=0)
        logs = np.log2(np.maximum(means, 1e-6))
        want = logs.mean() - logs  # ganho que iguala os canais (EV)
        # want = e·[1,1,1] + T·[0,28, 0, -0,38] + Ti·[0,08, -0,22, 0,08]
        a = np.array([[1.0, 0.28, 0.08], [1.0, 0.0, -0.22], [1.0, -0.38, 0.08]])
        _e, t, ti = np.linalg.solve(a, want)
        temp = float(np.clip(t * 100.0 * 0.8, -60, 60))
        tint = float(np.clip(ti * 100.0 * 0.8, -60, 60))
    out["temperatura"] = _snap(temp, "temperatura")
    out["tonalidade"] = _snap(tint, "tonalidade")
    gains = 2.0 ** np.array(wb_gains_ev(out["temperatura"], out["tonalidade"]))

    # Exposição: mediana da luminância perto de 0,42 (com amortecimento).
    med = float(np.median(lum))
    ev = 0.0
    if med > 1e-3:
        ev = float(np.clip(2.2 * math.log2(0.42 / med) * 0.6, -2.0, 2.0))
    out["exposicao"] = _snap(ev, "exposicao")
    exposed = np.clip((lin * gains * 2.0 ** out["exposicao"]) ** (1 / 2.2), 0, None)
    lum2 = exposed @ np.array(W709)

    # Níveis: 0,5% mais escuro vira preto e 0,5% mais claro vira branco (sem exagero).
    lo, hi = np.percentile(lum2, [0.5, 99.5])
    bp = max(0.0, float(lo) - 0.01) * 0.8
    wp = min(1.0, float(hi) + 0.01)
    wp = 1.0 - (1.0 - wp) * 0.8
    out["pretos"] = _snap(-bp / 0.1, "pretos")
    out["brancos"] = _snap((1.0 - wp) / 0.15, "brancos")
    return out
