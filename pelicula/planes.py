"""Cor por planos (1.6, etapa A, módulo Beta "cor_planos"): frente, fundo e pele com ajustes próprios no look.

A seção "Cor por planos" (`params.SECTIONS`, chaves `planos_*`) separa o quadro em **frente** e **fundo** por um
degradê (`masks.gradMask`; linear: o fundo fica do lado da direção, 0° = em cima; radial: a frente fica dentro do
círculo) e acha a **pele** pela cor (`masks.skinMask`). Cada plano tem cinco ajustes — exposição (EV), temperatura,
tonalidade, saturação e contraste — e a pele tem matiz, saturação, luz (EV) e "Uniformizar" (só a cor: a
claridade da pele não muda, nada de alisar a textura). "Proteger a pele" (ligado por padrão) deixa os ajustes de
frente e fundo fora da pele.

Onde entra: no passo BASE do look, na luz da cena, logo depois da entrada, do gamut, da exposição e do balanço
(`imageLin`) e antes da vinheta e do negativo. Fica **fora do `colorPipe`**: o LUT exportado e o plugin do DaVinci
não têm a Cor por planos (dependem do lugar e da cor de cada pixel; `docs/DAVINCI.md`).

- **Matemática** (a mesma em `apply` e no GLSL): exposição e balanço = ganho por canal `2^(EV + mistura da
  temperatura/tonalidade do look)`; contraste em torno do cinza 18% em stops da luminância
  (`Y' = 0,18·2^(log2(Y/0,18)·(1 + 0,5·contraste))`, a cor escala junto); saturação em torno da luminância Rec.709 (saturação e contraste em %).
  Os dois planos são calculados a partir da mesma luz e misturados pelo degradê. A pele é ajustada na cor como
  ela aparece (curva neutra de exibição → vídeo → OkLab), com o resultado de volta à luz pela curva inversa, e
  a luz da pele é um ganho na luz da cena.
- **Bit a bit**: com a seção desligada, ou ligada com todos os ajustes em zero, `uniforms()` devolve `{}` e o
  look usa o programa BASE de sempre (`shaders.BASE`, letra por letra). Com ajuste, `Engine` usa `BASE_CP` (o
  mesmo BASE com `imageLin` passando por `planes()`), compilado só na primeira vez.
- **"Ver planos"** (`Engine.plane_masks`): o mesmo programa com `u_cp_view = 1` devolve (frente, fundo, pele) no
  lugar da cor, alinhado com a prévia; a janela pinta por cima. Só na tela, nunca na exportação.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import masks
from .i18n import N_

PLANE_CONTROLS = ("exposicao", "temperatura", "tonalidade", "saturacao", "contraste")
SKIN_CONTROLS = ("matiz", "saturacao", "luz", "uniformizar")
PLANES = ("frente", "fundo")
CONTRAST_K = 0.5  # contraste 100% = 1,5× a inclinação em stops
W709 = np.array([0.2126, 0.7152, 0.0722])

GEOMETRY_KEYS = ("planos_tipo", "planos_angulo", "planos_pos_x", "planos_pos_y", "planos_raio", "planos_suavidade",
                 "planos_inverter")
SKIN_WINDOW_KEYS = ("planos_pele_centro", "planos_pele_largura")


def plane_keys(plane: str) -> list[str]:
    return [f"planos_{plane}_{c}" for c in PLANE_CONTROLS]


def skin_keys() -> list[str]:
    return [f"planos_pele_{c}" for c in SKIN_CONTROLS]


EFFECT_KEYS = tuple(plane_keys("frente") + plane_keys("fundo") + skin_keys())

# Prontos: só preenchem os controles (nada fica guardado além dos próprios ajustes).
PRONTOS: list[tuple[str, str, dict[str, Any]]] = [
    ("destacar", N_("Destacar o assunto"),
     {"planos_tipo": "radial", "planos_fundo_exposicao": -0.5, "planos_fundo_saturacao": -25.0,
      "planos_fundo_temperatura": -10.0}),
    ("frio_quente", N_("Fundo frio, pele quente"),
     {"planos_fundo_temperatura": -25.0, "planos_fundo_tonalidade": -5.0, "planos_pele_saturacao": 10.0,
      "planos_pele_matiz": -3.0, "planos_proteger_pele": True}),
    ("aerea", N_("Perspectiva aérea"),
     {"planos_tipo": "linear", "planos_angulo": 0.0, "planos_fundo_contraste": -35.0,
      "planos_fundo_saturacao": -30.0, "planos_fundo_exposicao": 0.2, "planos_fundo_temperatura": -12.0}),
    ("pele_natural", N_("Pele natural"), {"planos_pele_uniformizar": 0.5, "planos_proteger_pele": True}),
]


def apply_pronto(values: dict[str, Any], pid: str) -> dict[str, Any]:
    """Os ajustes da seção com um pronto: zera os efeitos e aplica os do pronto (liga a seção)."""
    from . import params
    out = dict(values)
    for k in EFFECT_KEYS:
        out[k] = params.PARAMS[k].default
    out.update(next(v for i, _n, v in PRONTOS if i == pid))
    out["planos_on"] = True
    return out


def active(v: dict[str, Any]) -> bool:
    """A seção ligada com algum ajuste fora do zero."""
    return bool(v.get("planos_on")) and any(float(v.get(k, 0.0) or 0.0) != 0.0 for k in EFFECT_KEYS)


def _wb_ev(ev: float, temp: float, tint: float) -> tuple[float, float, float]:
    t, ti = temp / 100.0, tint / 100.0  # mesma mistura do look (`look.build_plan`) e dos clipes
    return (ev + 0.28 * t + 0.08 * ti, ev - 0.22 * ti, ev - 0.38 * t + 0.08 * ti)


def _plane(v: dict[str, Any], plane: str) -> tuple[tuple, tuple]:
    ev, temp, tint, sat, con = (float(v.get(k, 0.0)) for k in plane_keys(plane))  # saturação e contraste em %
    return (tuple(float(2.0 ** g) for g in _wb_ev(ev, temp, tint)), (1.0 + sat / 100.0, CONTRAST_K * con / 100.0))


def _geometry(v: dict[str, Any]):
    kind = v.get("planos_tipo", "linear")
    # gradMask marca o lado da direção (linear) ou o miolo (radial); a frente é o miolo e o lado oposto.
    invert = bool(v.get("planos_inverter")) != (kind != "radial")
    return masks.gradient_uniform(kind, v.get("planos_pos_x", 0.0), v.get("planos_pos_y", 0.0),
                                  v.get("planos_angulo", 0.0), v.get("planos_raio", 400.0),
                                  v.get("planos_suavidade", 300.0), invert)


def uniforms(v: dict[str, Any], view: bool = False) -> dict[str, Any]:
    """Uniforms de `BASE_CP`; `{}` sem nada a fazer (o look segue no BASE de sempre). `view`: "Ver planos"."""
    if not view and not active(v):
        return {}
    g, k = _geometry(v)
    fg, fsc = _plane(v, "frente")
    bg, bsc = _plane(v, "fundo")
    fb_on = any(float(v.get(x, 0.0)) != 0.0 for x in plane_keys("frente") + plane_keys("fundo"))
    hue_s, sat_s, luz_s, even_s = (float(v.get(x, 0.0)) for x in skin_keys())
    skin_on = any(x != 0.0 for x in (hue_s, sat_s, luz_s, even_s))
    return {
        "u_cp_on": 1,
        "u_cp_view": 1 if view else 0,
        "u_cp_grad": g,
        "u_cp_gradk": k,
        "u_cp_fgain": fg, "u_cp_fsc": fsc,
        "u_cp_bgain": bg, "u_cp_bsc": bsc,
        "u_cp_fb_on": 1 if fb_on else 0,
        "u_cp_skin": (float(v.get("planos_pele_centro", masks.SKIN_HUE)),
                      float(v.get("planos_pele_largura", masks.SKIN_WIDTH))),
        "u_cp_skinadj": (hue_s, 1.0 + sat_s / 100.0, float(2.0 ** luz_s), even_s),
        "u_cp_skin_on": 1 if skin_on else 0,
        "u_cp_protect": 1.0 if v.get("planos_proteger_pele", True) else 0.0,
    }


# ------------------------------------------------------------------ referência em numpy (testes)
def _display(lin):
    from . import look
    return look._stops_to_disp(np.clip(np.log2(np.maximum(lin, 1e-7) / 0.18), -12.0, 12.0))


def _from_display(d):
    from . import look
    return 0.18 * np.exp2(look._disp_to_stops(d))


def _adjust(lin, gain, sc):
    c = lin * np.asarray(gain)
    Y = c @ W709
    if sc[1] != 0.0:
        safe = np.maximum(Y, 1e-30)
        Yc = 0.18 * np.exp2(np.clip(np.log2(safe / 0.18), -12.0, 12.0) * (1.0 + sc[1]))
        c = np.where((Y > 0.0)[..., None], c * (Yc / safe)[..., None], c)
        Y = np.where(Y > 0.0, Yc, Y)
    if sc[0] != 1.0:
        c = np.maximum(Y[..., None] + (c - Y[..., None]) * sc[0], 0.0)
    return c



def weights(lin, p, v: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """(frente, pele) de cada pixel: `lin` é a luz da cena (… × 3), `p` os pontos em px@1080."""
    U = uniforms(v, view=True)
    g, k = U["u_cp_grad"], U["u_cp_gradk"]
    kind = "radial" if k[1] > 0.5 else "linear"
    front = masks.gradient_mask(p, kind, g[0], g[1], math.degrees(g[2]), k[0], g[3], k[2] > 0.5)
    skin = masks.skin_mask(_display(lin), *U["u_cp_skin"])
    return front, skin


def apply(lin, p, v: dict[str, Any]) -> np.ndarray:
    """A Cor por planos na luz da cena (o mesmo que `planes()` no GLSL)."""
    lin = np.asarray(lin, dtype=np.float64)
    U = uniforms(v)
    if not U:
        return lin
    front, skin = weights(lin, p, v)
    out = lin
    if U["u_cp_fb_on"]:
        f = _adjust(lin, U["u_cp_fgain"], U["u_cp_fsc"])
        b = _adjust(lin, U["u_cp_bgain"], U["u_cp_bsc"])
        fb = f * front[..., None] + b * (1.0 - front[..., None])
        keep = 1.0 - U["u_cp_protect"] * skin
        out = lin + (fb - lin) * keep[..., None]
    if U["u_cp_skin_on"]:
        hue_s, chroma, gain, even = U["u_cp_skinadj"]
        lab = masks.oklab(masks.code_to_lin(_display(out)))
        lab = masks.lch_adjust(masks.skin_even(lab, U["u_cp_skin"][0], even), hue_s, chroma)
        d = np.maximum(masks.oklab_to_lin(lab), 0.0) ** (1.0 / 2.2)
        adj = _from_display(d) * gain
        out = out + (adj - out) * skin[..., None]
    return out


# ------------------------------------------------------------------ GLSL
GLSL = masks.GLSL + """
// ---------------------------------------------------------------- 1.6: Cor por planos (pelicula/planes.py)
uniform int u_cp_on;
uniform int u_cp_view;      // 1 = "Ver planos": devolve (frente, fundo, pele) no lugar da cor
uniform vec4 u_cp_grad;     // degradê (masks.gradient_uniform): cx, cy, ângulo, suavidade (px@1080)
uniform vec4 u_cp_gradk;    // raio, radial, inverter
uniform vec3 u_cp_fgain;    // frente: exposição e balanço (ganho por canal)
uniform vec2 u_cp_fsc;      // frente: saturação (fator), contraste (k)
uniform vec3 u_cp_bgain;    // fundo
uniform vec2 u_cp_bsc;
uniform int u_cp_fb_on;
uniform vec2 u_cp_skin;     // janela da pele: centro e meia largura do matiz (graus OkLCh)
uniform vec4 u_cp_skinadj;  // pele: giro do matiz (graus), croma (fator), luz (ganho), uniformizar
uniform int u_cp_skin_on;
uniform float u_cp_protect; // 1 = frente e fundo não mexem na pele

vec3 planeAdjust(vec3 lin, vec3 gain, vec2 sc) {
    vec3 c = lin * gain;
    float Y = dot(c, W709);
    if (sc.y != 0.0 && Y > 0.0) {
        float Yc = 0.18 * exp2(clamp(log2(Y / 0.18), -12.0, 12.0) * (1.0 + sc.y));
        c *= Yc / Y;
        Y = Yc;
    }
    if (sc.x != 1.0) c = max(Y + (c - Y) * sc.x, vec3(0.0));
    return c;
}

vec3 planes(vec3 lin, vec2 uv) {
    if (u_cp_view == 0 && u_cp_fb_on == 0 && u_cp_skin_on == 0) return lin;
    float front = gradMask(framePoint(uv, u_res.x / u_res.y), u_cp_grad, u_cp_gradk);
    float skin = skinMask(stopsToDisp(linToStops(lin)), u_cp_skin);
    if (u_cp_view == 1) {
        float keep = 1.0 - u_cp_protect * skin;
        return vec3(front * keep, (1.0 - front) * keep, skin);
    }
    vec3 outc = lin;
    if (u_cp_fb_on == 1) {
        vec3 fb = planeAdjust(lin, u_cp_fgain, u_cp_fsc) * front + planeAdjust(lin, u_cp_bgain, u_cp_bsc) * (1.0 - front);
        outc = lin + (fb - lin) * (1.0 - u_cp_protect * skin);
    }
    if (u_cp_skin_on == 1 && skin > 0.0) {
        vec3 lab = linToOklab(pow(max(stopsToDisp(linToStops(outc)), vec3(0.0)), vec3(2.2)));
        lab = lchAdjust(skinEven(lab, u_cp_skin.x, u_cp_skinadj.w), u_cp_skinadj.x, u_cp_skinadj.y);
        vec3 d = pow(max(oklabToLin(lab), vec3(0.0)), vec3(1.0 / 2.2));
        vec3 adj = stopsToLin(dispToStops(d)) * u_cp_skinadj.z;
        outc = outc + (adj - outc) * skin;
    }
    return outc;
}
"""


def _base_cp() -> str:
    """`shaders.BASE` com a luz da imagem passando por `planes()` (o resto do programa, letra por letra)."""
    from . import shaders
    src = shaders.BASE
    head = "vec3 imageLin(vec2 uv) {"
    assert src.count(head) == 1 and src.count("void main() {") == 1
    src = src.replace(head, "vec3 imageLinRaw(vec2 uv) {", 1)
    hook = GLSL + "\nvec3 imageLin(vec2 uv) { return planes(imageLinRaw(uv), uv); }\n\nvoid main() {"
    return src.replace("void main() {", hook, 1)


BASE_CP = _base_cp()
