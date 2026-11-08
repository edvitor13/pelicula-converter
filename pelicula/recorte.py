"""1.9, recorte por cor ou por brilho do clipe (chroma key e luma key; #68, ARQUITETURA §50). Sem GPU nem Qt.

Um efeito da pilha de clipe (`vfx.py`, ordem "recorte": o primeiro), módulo Beta `recorte_mascaras`. Os ajustes ficam na
seção "recorte" de `editparams` (bloco `# 1.9 F2`); `chave_tipo = "nenhuma"` (o padrão) não gera passo nenhum.

**Recorte por cor** ("verde", "azul" ou "cor", a cor do conta-gotas em `chave_cor`): a imagem vai à luz linear da curva
(`fxDec`, a luz das transições) e cada pixel vira uma **cromaticidade** parecida com o YCbCr, `(B − Y, R − Y)`
dividida pelo maior canal (`chroma`): não muda com a exposição, então um fundo com luz desigual tem uma cor só, e o
cinza fica na origem. A distância até a cromaticidade da cor do fundo, relativa ao tamanho dela (o cinza fica a 1,0 de
qualquer fundo), passa por uma rampa: até `chave_tolerancia` sai inteiro, depois de `tolerancia + suavidade` fica
inteiro. A cor do fundo vai ao shader em código (como a imagem) e passa pela mesma curva.

**Recorte pelo brilho** ("luma"): o brilho é a luminância da luz levada à curva de exibição neutra do app
(`stopsToDisp(linToStops(Y))`, 0 a 1); sai o que fica abaixo de `chave_luma_min` ou acima de `chave_luma_max`, com
a rampa de `chave_suavidade` para fora.

**Encolher a borda** (`chave_limpar`, px@1080): o recorte desfocado com σ = |limpar| e cortado no nível em que a borda
anda σ (Φ(1) ≈ 0,84 para encolher, 0,16 para aumentar): `min` (ou `max`) com o recorte de antes.
**Reflexo do fundo** (`chave_spill`): na luz, o canal da cor do fundo fica limitado ao maior dos outros dois (cinzas e
brancos não mudam; o amarelo não vira laranja). **Luz do fundo na borda** (`chave_luz_borda`, `chave_luz_largura`):
a tela embaixo do clipe (`fxBelow`, luz até o branco difuso `WRAP_MAX`) desfocada, somada na luz onde o recorte
desfocado é menor que 1 (só perto da borda). Os dois mexem na cor por diferença (`fxEnc(nova) − fxEnc(antiga)`), então desligados não mudam um bit.

A saída tem cobertura (`Effect.alpha`): a do clipe vezes o recorte; a pilha grava pré-multiplicado com a conta inversa
do `clipAlpha` (`editshaders.FX_STORE`). Referência em numpy (`matte`) para a curva de vídeo (Rec.709) e a linear.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import vfx

MODULE = "recorte_mascaras"
EFFECT_ID = "recorte"
KEYS = ("chave_tipo", "chave_cor", "chave_tolerancia", "chave_suavidade", "chave_limpar", "chave_spill",
        "chave_luz_borda", "chave_luz_largura", "chave_luma_min", "chave_luma_max")
# A cor de cada fundo pronto, em código de vídeo (como a imagem): um verde e um azul de tela de recorte comuns.
KEY_COLORS = {"verde": (0.15, 0.70, 0.25), "azul": (0.10, 0.25, 0.75)}
CHROMA_EPS = 0.005     # some ao maior canal na cromaticidade (só o preto quase puro perde a cor)
MIN_KEY_CHROMA = 0.05  # cromaticidade mínima da cor do fundo (uma cor quase cinza recortaria os cinzas)
SOFT_MIN = 1e-4
WRAP_MAX = 1.0         # a luz do fundo na borda vai até o branco difuso (luz linear 1,0)
CHOKE_LEVELS = {"encolher": (0.69, 0.99), "aumentar": (0.01, 0.31)}  # rampas em volta de Φ(1) e Φ(−1)

MATTE = """
uniform int u_ck_mode;      // 1 = cor (verde, azul ou a escolhida), 2 = brilho
uniform vec3 u_ck_key;      // cor do fundo, em código (como a imagem)
uniform float u_ck_tol;
uniform float u_ck_soft;
uniform float u_ck_lo;
uniform float u_ck_hi;

vec2 ckChroma(vec3 lin) {
    float y = dot(lin, W709);
    float v = max(max(lin.r, lin.g), lin.b);
    return vec2(lin.b - y, lin.r - y) / (max(v, 0.0) + %(eps)r);
}
float ckMatte(vec3 c) {
    vec3 lin = max(fxDec(c), vec3(0.0));
    float soft = max(u_ck_soft, %(soft)r);
    if (u_ck_mode == 2) {
        float l = stopsToDisp(linToStops(vec3(dot(lin, W709)))).x;
        return smoothstep(u_ck_lo - soft, u_ck_lo, l) * (1.0 - smoothstep(u_ck_hi, u_ck_hi + soft, l));
    }
    vec2 k = ckChroma(max(fxDec(u_ck_key), vec3(0.0)));
    float d = length(ckChroma(lin) - k) / max(length(k), %(kmin)r);
    return smoothstep(u_ck_tol, u_ck_tol + soft, d);
}
void main() {
    float m = ckMatte(texture(t_prev, v_uv).rgb);
    f_out = vec4(m, m, m, 1.0);
}
""" % {"eps": CHROMA_EPS, "soft": SOFT_MIN, "kmin": MIN_KEY_CHROMA}

CHOKE = """
uniform sampler2D t_m;      // o recorte
uniform sampler2D t_b;      // o recorte desfocado (σ = |limpar|)
uniform float u_ck_grow;    // > 0 encolhe, < 0 aumenta
void main() {
    float m = texture(t_m, v_uv).r;
    float b = texture(t_b, v_uv).r;
    float r = u_ck_grow > 0.0 ? min(m, smoothstep(%r, %r, b)) : max(m, smoothstep(%r, %r, b));
    f_out = vec4(r, r, r, 1.0);
}
""" % (*CHOKE_LEVELS["encolher"], *CHOKE_LEVELS["aumentar"])

# A luz da tela embaixo do clipe, no espaço do clipe (sem cobertura, sem luz), até o branco difuso (`WRAP_MAX`): na
# curva de vídeo o código 1,0 é luz sem fim, e um fundo branco estouraria a pessoa inteira.
BELOW_LIGHT = """
void main() {
    vec4 b = fxBelow(v_uv);
    f_out = vec4(clamp(fxDec(b.rgb), 0.0, %r) * clamp(b.a, 0.0, 1.0), 1.0);
}
""" % WRAP_MAX

KEY = """
uniform sampler2D t_img;    // a imagem do clipe (cor direta e cobertura)
uniform sampler2D t_matte;  // o recorte
uniform sampler2D t_bg;     // a luz da tela embaixo, desfocada (só com a luz na borda)
uniform sampler2D t_edge;   // o recorte desfocado (só com a luz na borda)
uniform int u_ck_chan;      // canal da cor do fundo (0 r, 1 g, 2 b; -1 = nenhum)
uniform float u_ck_spill;
uniform float u_ck_wrap;
void main() {
    vec4 c = texture(t_img, v_uv);
    float m = texture(t_matte, v_uv).r;
    vec3 rgb = c.rgb;
    if ((u_ck_spill > 0.0 && u_ck_chan >= 0) || u_ck_wrap > 0.0) {
        vec3 lin = fxDec(c.rgb);
        vec3 n = lin;
        if (u_ck_spill > 0.0 && u_ck_chan >= 0) {
            float lim = max(u_ck_chan == 0 ? lin.g : lin.r, u_ck_chan == 2 ? lin.g : lin.b);
            float k = u_ck_chan == 0 ? lin.r : (u_ck_chan == 1 ? lin.g : lin.b);
            float v = mix(k, min(k, lim), u_ck_spill);
            if (u_ck_chan == 0) n.r = v; else if (u_ck_chan == 1) n.g = v; else n.b = v;
        }
        if (u_ck_wrap > 0.0) {
            float e = texture(t_edge, v_uv).r;
            n += texture(t_bg, v_uv).rgb * (1.0 - clamp(e, 0.0, 1.0)) * u_ck_wrap;
        }
        rgb = c.rgb + (fxEnc(n) - fxEnc(lin));
    }
    f_out = vec4(rgb, c.a * m);
}
"""


# ------------------------------------------------------------------ valores → uniforms
def mode_of(values: dict | None) -> int:
    """0 = sem recorte, 1 = por cor, 2 = pelo brilho."""
    kind = (values or {}).get("chave_tipo", "nenhuma")
    return {"verde": 1, "azul": 1, "cor": 1, "luma": 2}.get(kind, 0)


def active(values: dict | None) -> bool:
    return mode_of(values) != 0


def key_color(values: dict) -> tuple[float, float, float]:
    """A cor do fundo em código de vídeo (0 a 1): a pronta do tipo, ou a do conta-gotas em "cor"."""
    kind = values.get("chave_tipo", "nenhuma")
    if kind in KEY_COLORS:
        return KEY_COLORS[kind]
    c = values.get("chave_cor") or KEY_COLORS["verde"]
    return float(c[0]), float(c[1]), float(c[2])


def key_channel(values: dict) -> int:
    """O canal que o reflexo do fundo levanta (o maior da cor do fundo); -1 no recorte pelo brilho."""
    if mode_of(values) != 1:
        return -1
    return int(np.argmax(np.asarray(key_color(values))))


def matte_uniforms(values: dict) -> dict[str, Any]:
    return {"u_ck_mode": mode_of(values), "u_ck_key": key_color(values),
            "u_ck_tol": float(values["chave_tolerancia"]), "u_ck_soft": float(values["chave_suavidade"]),
            "u_ck_lo": float(values["chave_luma_min"]), "u_ck_hi": float(values["chave_luma_max"])}


def passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    out = [vfx.Pass("recorte", MATTE, uniforms=matte_uniforms(v), dtype="f2")]
    matte = "pass:recorte"
    grow = float(v["chave_limpar"])
    if grow != 0.0:
        out += [vfx.Pass("recorte_suave", kind="blur", sigma=ctx.px(abs(grow)), inputs={"t_src": "pass:recorte"},
                         dtype="f2"),
                vfx.Pass("recorte_limpo", CHOKE, uniforms={"u_ck_grow": grow},
                         inputs={"t_m": "pass:recorte", "t_b": "pass:recorte_suave"}, dtype="f2")]
        matte = "pass:recorte_limpo"
    inputs = {"t_img": "orig", "t_matte": matte}
    wrap = float(v["chave_luz_borda"])
    if wrap > 0.0:
        sigma = ctx.px(float(v["chave_luz_largura"]))
        out += [vfx.Pass("fundo", BELOW_LIGHT, size=0.5, dtype="f2"),
                vfx.Pass("fundo_suave", kind="blur", sigma=sigma * 0.5, inputs={"t_src": "pass:fundo"}, size=0.5,
                         dtype="f2"),
                vfx.Pass("borda_suave", kind="blur", sigma=sigma, inputs={"t_src": matte}, size=0.5, dtype="f2")]
        inputs.update(t_bg="pass:fundo_suave", t_edge="pass:borda_suave")
    out.append(vfx.Pass("chave", KEY, inputs=inputs,
                        uniforms={"u_ck_chan": key_channel(v), "u_ck_spill": float(v["chave_spill"]),
                                  "u_ck_wrap": wrap}))
    return out


EFFECT = vfx.register(vfx.Effect(EFFECT_ID, MODULE, vfx.ORDER["recorte"], active=active, passes=passes, alpha=active,
                                 keys=KEYS))


# ------------------------------------------------------------------ referência em numpy (testes, conta-gotas)
def decode(code, light: tuple[int, bool] | None = None) -> np.ndarray:
    """Código → luz linear da curva (`fxDec`) para a curva de vídeo (id 0, a das transições sem look) e a linear (1)."""
    from .look import _disp_to_stops
    curve = 0 if light is None else int(light[0])
    c = np.asarray(code, dtype=np.float64)
    if curve == 0:
        return 0.18 * np.exp2(_disp_to_stops(c))
    if curve == 1:
        return c
    raise NotImplementedError(f"curva {curve} sem referência em numpy")


def chroma(lin) -> np.ndarray:
    """A cromaticidade do recorte: (B − Y, R − Y) / (maior canal + ε), na luz linear (… × 3 → … × 2)."""
    lin = np.maximum(np.asarray(lin, dtype=np.float64), 0.0)
    y = lin @ np.array([0.2126, 0.7152, 0.0722])
    v = np.maximum(lin.max(axis=-1), 0.0) + CHROMA_EPS
    return np.stack([lin[..., 2] - y, lin[..., 0] - y], axis=-1) / v[..., None]


def _smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def brightness(lin) -> np.ndarray:
    """O brilho do recorte pelo brilho: a luminância na curva de exibição neutra (0 a 1)."""
    from .look import D_MID, D_P, D_SLOPE, _curve_np
    y = np.maximum(np.asarray(lin, dtype=np.float64), 0.0) @ np.array([0.2126, 0.7152, 0.0722])
    stops = np.clip(np.log2(np.maximum(y, 1e-7) / 0.18), -12.0, 12.0)
    return _curve_np(stops, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P)


def matte(code, values: dict, light: tuple[int, bool] | None = None) -> np.ndarray:
    """O recorte (1 = fica, 0 = sai) de uma imagem em código (h × w × 3, 0 a 1), sem encolher a borda: a conta do
    `MATTE`."""
    lin = np.maximum(decode(np.asarray(code, dtype=np.float64)[..., :3], light), 0.0)
    soft = max(float(values["chave_suavidade"]), SOFT_MIN)
    mode = mode_of(values)
    if mode == 2:
        lum = brightness(lin)
        lo, hi = float(values["chave_luma_min"]), float(values["chave_luma_max"])
        return _smoothstep(lo - soft, lo, lum) * (1.0 - _smoothstep(hi, hi + soft, lum))
    if mode == 0:
        return np.ones(lin.shape[:-1])
    k = chroma(np.maximum(decode(np.asarray(key_color(values)), light), 0.0))
    d = np.linalg.norm(chroma(lin) - k, axis=-1) / max(float(np.linalg.norm(k)), MIN_KEY_CHROMA)
    tol = float(values["chave_tolerancia"])
    return _smoothstep(tol, tol + soft, d)


def picked_color(rgb) -> tuple[float, float, float] | None:
    """A cor do conta-gotas (código de 0 a 1, a do arquivo no ponto) como `chave_cor`, ou None se é quase cinza (um
    fundo cinza recortaria todos os cinzas da imagem)."""
    c = np.clip(np.asarray(rgb, dtype=np.float64).reshape(3), 0.0, 1.0)
    if float(np.linalg.norm(chroma(decode(c)))) < MIN_KEY_CHROMA * 2:
        return None
    return tuple(round(float(x), 4) for x in c)
