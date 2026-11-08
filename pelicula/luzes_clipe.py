"""1.9, luzes e lente do clipe (#68, módulo Beta "luzes_lente"; ARQUITETURA §52): desfoque de lente, listra
anamórfica, flares e raios de luz. Sem Qt nem GPU.

Quatro efeitos da pilha de `vfx.py`, no espaço da textura do clipe e na luz da curva do look (`fxDec`/`fxEnc`), todos
em px@1080 do clipe (`Ctx.px`):

- **Desfoque de lente** (`desfoque_lente_*`, ordem 400): um passo leva a imagem à luz (pré-multiplicada, com mipmaps,
  cortada em `BOKEH_CLAMP_STOPS` acima do cinza para um céu estourado não incendiar tudo em volta) e outro junta
  `BOKEH_SAMPLES` amostras numa espiral de ângulo áureo dentro do disco (ou do hexágono) do raio do pixel, lendo o nível
  de mipmap do espaçamento entre elas. Na luz, as altas luzes viram discos claros, como numa lente. O raio do pixel é o
  raio × a máscara: a imagem toda, o degradê (`masks.gradMask`: o lado marcado desfoca) ou, depois da integração da
  frente F2, uma máscara de forma por `MASK_SOURCES` (o gancho; veja abaixo).
- **Listra anamórfica** (`listra_*`, 500): as luzes acima do limiar (stops acima do cinza de 18%, `extract`) numa
  textura de meia resolução, espalhadas numa direção pelo passo `streak` da base (duas gaussianas, uma longa e uma
  curta), tingidas e somadas à luz.
- **Flare** (`flare_*`, 510): "automático" espelha as luzes fortes pelo centro do quadro em `GHOSTS` escalas (cada uma
  um fantasma colorido com um pouco de aberração cromática), como numa lente de verdade: os fantasmas ficam na linha da
  luz ao centro. "Um ponto escolhido" desenha os fantasmas (discos com borda) e o brilho a partir do ponto, sem ler a
  imagem.
- **Raios de luz** (`raios_*`, 520): as luzes acima do limiar puxadas para a origem por dois passos de desfoque radial
  (24 amostras com decaimento + 24 que preenchem os vãos), tingidas e somadas.

Os que somam luz gravam `c + fxEnc(luz + brilho) − fxEnc(luz)`: onde o brilho é zero (abaixo do limiar), o pixel sai
bit a bit. A energia somada é a extraída × intensidade × ganho (desfoques normalizados).

**Máscara de forma (gancho para a F2):** `MASK_SOURCES[escolha] = fn(ctx) -> [Pass] | None` — passos que deixam a
máscara (canal r, 0 a 1, no uv do clipe) no último; a escolha `escolha` de `desfoque_lente_mascara` passa a usá-la
(com prioridade sobre as escolhas daqui). A integração acrescenta as opções "dentro/fora da máscara" no fim de
`desfoque_lente_mascara` e registra as duas aqui (ARQUITETURA §52.5).
"""

from __future__ import annotations

import math
from typing import Callable

from . import masks, vfx

MODULE = "luzes_lente"
LIGHT_CLAMP_STOPS = 3.0      # o brilho extraído é limitado com suavidade a 2^(limiar + isto) × 0,18 (estourado ≠ ∞)
BOKEH_CLAMP_STOPS = 7.0      # luz máxima no desfoque de lente (stops acima do cinza de 18%)
BOKEH_SAMPLES = 80
STREAK_GAIN = 1.0            # energia da listra = extraída × intensidade × ganho
STREAK_SHORT = (1.0 / 6.0, 0.4)  # gaussiana curta da listra: fração do desvio da longa e peso (a longa leva o resto)
FLARE_GAIN = 0.15            # fantasmas automáticos: fração da luz espelhada
FLARE_GHOST_LIGHT = 0.15     # fantasmas de um ponto: luz de cada um (× intensidade × peso da tabela)
FLARE_GLOW_LIGHT = 1.0       # brilho no ponto do flare
RAYS_GAIN = 1.0
RAYS_TAPS = 24

DOF_KEYS = ("desfoque_lente_raio", "desfoque_lente_forma", "desfoque_lente_mascara", "desfoque_lente_degrade",
            "desfoque_lente_angulo", "desfoque_lente_x", "desfoque_lente_y", "desfoque_lente_circulo",
            "desfoque_lente_suavidade", "desfoque_lente_inverter")
STREAK_KEYS = ("listra_intensidade", "listra_limiar", "listra_comprimento", "listra_cor", "listra_angulo")
FLARE_KEYS = ("flare_intensidade", "flare_fonte", "flare_x", "flare_y", "flare_fantasmas", "flare_limiar",
              "flare_tamanho", "flare_cor")
RAYS_KEYS = ("raios_intensidade", "raios_x", "raios_y", "raios_comprimento", "raios_decaimento", "raios_limiar",
             "raios_cor")

# Gancho da máscara de forma (F2): escolha de `desfoque_lente_mascara` → fn(ctx) -> [Pass] (último: máscara em r).
MASK_SOURCES: dict[str, Callable[[vfx.Ctx], list[vfx.Pass] | None]] = {}

# ------------------------------------------------------------------ GLSL
# Cópia da entrada do efeito (quando outro efeito veio antes: o passo final precisa dela e "orig" é a de antes de todos).
COPY = """
void main() {
    f_out = texture(t_prev, v_uv);
}
"""

# Luzes acima do limiar (luz linear, × cobertura), limitadas com suavidade; `u_lum` = só a luminância.
EXTRACT = """
uniform float u_thr;
uniform float u_limit;
uniform int u_lum;
void main() {
    vec4 c = texture(t_prev, v_uv);
    vec3 lin = max(fxDec(c.rgb), vec3(0.0));
    float l = dot(lin, W709);
    vec3 e = l > u_thr ? lin * ((l - u_thr) / l) : vec3(0.0);
    e = e / (1.0 + e / u_limit);
    e *= clamp(c.a, 0.0, 1.0);
    if (u_lum == 1) e = vec3(dot(e, W709));
    f_out = vec4(e, 1.0);
}
"""

# Soma o brilho (um ou dois) à luz da entrada do efeito, mexendo só no que muda.
ADD = """
uniform sampler2D t_base;
uniform sampler2D t_glow;
uniform sampler2D t_glow2;
uniform vec3 u_gain;
uniform vec3 u_gain2;
void main() {
    vec4 b = texelFetch(t_base, ivec2(gl_FragCoord.xy), 0);
    vec3 g = texture(t_glow, v_uv).rgb * u_gain + texture(t_glow2, v_uv).rgb * u_gain2;
    if (dot(g, g) <= 0.0) {
        f_out = b;
        return;
    }
    vec3 lin = fxDec(b.rgb);
    f_out = vec4(b.rgb + fxEnc(lin + g) - fxEnc(lin), b.a);
}
"""

# Fantasmas e cores do flare (as duas variantes leem a mesma tabela).
_GHOST_TABLE = """
const float GS[8] = float[8](-0.55, -1.25, -0.3, 0.45, -0.85, -1.7, 0.25, -2.1);
const float GT[8] = float[8](0.45, 0.75, 1.1, 1.35, 1.6, 1.85, 2.1, 0.25);
const float GR[8] = float[8](0.55, 0.3, 1.0, 0.45, 1.5, 0.35, 0.8, 0.2);
const float GW[8] = float[8](0.6, 0.35, 0.7, 0.3, 0.45, 0.25, 0.35, 0.2);
const vec3 GC[8] = vec3[8](vec3(1.0, 0.65, 0.35), vec3(0.45, 0.8, 1.0), vec3(0.65, 1.0, 0.55), vec3(1.0, 0.45, 0.85),
                           vec3(0.95, 0.9, 0.5), vec3(0.5, 0.6, 1.0), vec3(1.0, 0.75, 0.45), vec3(0.6, 1.0, 0.95));
"""

# Automático: as luzes espelhadas pelo centro em cada escala do fantasma (com aberração cromática), apagando perto da
# borda do quadro.
GHOSTS = _GHOST_TABLE + """
uniform sampler2D t_src;
uniform int u_n;
void main() {
    vec3 acc = vec3(0.0);
    for (int i = 0; i < 8; i++) {
        if (i >= u_n) break;
        vec2 d = (v_uv - 0.5) * GS[i];
        vec2 uv = 0.5 + d;
        float edge = 1.0 - smoothstep(0.3, 0.5, max(abs(d.x), abs(d.y)));
        if (edge <= 0.0) continue;
        vec3 s = vec3(texture(t_src, 0.5 + d * 1.025).r, texture(t_src, uv).g, texture(t_src, 0.5 + d * 0.975).b);
        acc += s * GC[i] * (GW[i] * edge);
    }
    f_out = vec4(acc, 1.0);
}
"""

# Um ponto escolhido: brilho no ponto e fantasmas (discos com borda) na linha do ponto ao centro, somados à luz.
POINT_FLARE = _GHOST_TABLE + """
uniform vec2 u_src;          // ponto do flare (px@1080 do centro do clipe)
uniform float u_size;        // raio de referência dos fantasmas (px@1080)
uniform int u_n;
uniform vec3 u_gain;         // intensidade × cor
uniform float u_ghost;
uniform float u_glow;
void main() {
    vec4 b = texture(t_prev, v_uv);
    vec2 P = framePoint(v_uv, u_fx_clip_px.x / u_fx_clip_px.y);
    float sg = 0.6 * u_size;
    vec2 dp = P - u_src;
    vec3 acc = vec3(exp(-dot(dp, dp) / (2.0 * sg * sg)) * u_glow);
    for (int i = 0; i < 8; i++) {
        if (i >= u_n) break;
        vec2 ctr = u_src - u_src * GT[i];
        float r = u_size * GR[i];
        float d = length(P - ctr);
        float disc = 1.0 - smoothstep(0.8 * r, r, d);
        float ring = 0.55 + 0.45 * smoothstep(0.4 * r, r, d);
        acc += GC[i] * (GW[i] * disc * ring * u_ghost);
    }
    vec3 g = acc * u_gain;
    vec3 lin = fxDec(b.rgb);
    f_out = vec4(b.rgb + fxEnc(lin + g) - fxEnc(lin), b.a);
}
"""

# Desfoque radial para a origem (uv do clipe): `u_len` = fração do caminho; peso `u_k`^i por amostra; fora do quadro
# não conta.
RADIAL = """
uniform sampler2D t_src;
uniform vec2 u_center;
uniform float u_len;
uniform float u_k;
const int TAPS = %(taps)d;
void main() {
    vec2 d = v_uv - u_center;
    vec3 acc = vec3(0.0);
    float ws = 0.0;
    float w = 1.0;
    for (int i = 0; i < TAPS; i++) {
        vec2 uv = v_uv - d * (float(i) / float(TAPS) * u_len);
        if (all(greaterThanEqual(uv, vec2(0.0))) && all(lessThanEqual(uv, vec2(1.0)))) acc += texture(t_src, uv).rgb * w;
        ws += w;
        w *= u_k;
    }
    f_out = vec4(acc / ws, 1.0);
}
""" % {"taps": RAYS_TAPS}

# Desfoque de lente, passo 1: luz pré-multiplicada (cortada em u_clamp), com mipmaps.
DOF_LIGHT = """
uniform float u_clamp;
void main() {
    vec4 c = texture(t_prev, v_uv);
    float a = clamp(c.a, 0.0, 1.0);
    vec3 lin = min(max(fxDec(c.rgb), vec3(0.0)), vec3(u_clamp));
    f_out = vec4(lin * a, a);
}
"""

# Desfoque de lente, passo 2: espiral de ângulo áureo no disco (ou hexágono) do raio deste pixel.
DOF_GATHER = """
uniform sampler2D t_lin;
uniform sampler2D t_base;
uniform sampler2D t_mask;
uniform float u_radius;      // texels do clipe
uniform int u_mask;          // 0 = a imagem toda; 1 = degradê; 2 = máscara de forma (t_mask.r)
uniform vec4 u_g;
uniform vec4 u_k;
uniform int u_hex;
uniform float u_clamp;
const int N = %(n)d;
const float PI = 3.14159265;
float hexRadius(float th) {
    float a = mod(th, PI / 3.0) - PI / 6.0;
    return cos(PI / 6.0) / cos(a);
}
void main() {
    vec4 b = texelFetch(t_base, ivec2(gl_FragCoord.xy), 0);
    float m = 1.0;
    if (u_mask == 1) m = gradMask(framePoint(v_uv, u_fx_clip_px.x / u_fx_clip_px.y), u_g, u_k);
    else if (u_mask == 2) m = clamp(texture(t_mask, v_uv).r, 0.0, 1.0);
    float r = u_radius * m;
    if (r < 0.5) {
        f_out = b;
        return;
    }
    float lod = max(0.0, log2(r * 1.7724539 / sqrt(float(N))));  // espaçamento entre as amostras: r·√(π/N)
    vec4 acc = vec4(0.0);
    for (int k = 0; k < N; k++) {
        float t = sqrt((float(k) + 0.5) / float(N));
        float th = float(k) * 2.39996323;
        vec2 o = vec2(cos(th), sin(th)) * t;
        if (u_hex == 1) o *= hexRadius(th);
        acc += textureLod(t_lin, v_uv + o * r / u_fx_size, lod);
    }
    acc /= float(N);
    vec3 lb = acc.a > 1e-6 ? acc.rgb / acc.a : vec3(0.0);
    vec3 lc = min(max(fxDec(b.rgb), vec3(0.0)), vec3(u_clamp));
    f_out = vec4(b.rgb + fxEnc(lb) - fxEnc(lc), acc.a);
}
""" % {"n": BOKEH_SAMPLES}

EXTRACT_GLSL = EXTRACT
GHOSTS_GLSL = GHOSTS
POINT_FLARE_GLSL = masks.GLSL + POINT_FLARE
DOF_GATHER_GLSL = masks.GLSL + DOF_GATHER


# ------------------------------------------------------------------ comum
def threshold(stops: float) -> float:
    """O limiar em luz linear: `stops` acima do cinza de 18%."""
    return 0.18 * 2.0 ** float(stops)


def entry(ctx: vfx.Ctx, effect_id: str) -> tuple[str, list[vfx.Pass]]:
    """A entrada do efeito para o passo final: "orig" se ele é o primeiro da pilha; senão, um passo que copia a saída
    do efeito anterior (os passos seguintes do mesmo efeito leem "pass:entrada")."""
    me = vfx.EFFECTS[effect_id]
    before = [e for e in vfx.active_effects(ctx.values) if (e.order, e.id) < (me.order, me.id)]
    if not before:
        return "orig", []
    return "pass:entrada", [vfx.Pass("entrada", COPY)]


def _extract(stops: float, lum: bool, size=0.5) -> vfx.Pass:
    thr = threshold(stops)
    return vfx.Pass("brilho", EXTRACT_GLSL, size=size, dtype="f2",
                    uniforms={"u_thr": thr, "u_limit": thr * 2.0 ** LIGHT_CLAMP_STOPS, "u_lum": int(lum)})


def _color(v: dict, key: str, default=(1.0, 1.0, 1.0)) -> tuple[float, float, float]:
    c = v.get(key) or default
    return float(c[0]), float(c[1]), float(c[2])


def clip_uv(ctx: vfx.Ctx, x: float, y: float) -> tuple[float, float]:
    """Um ponto em px@1080 do centro do clipe (y para baixo) no uv da textura do clipe."""
    aspect = ctx.tex_w / max(1, ctx.tex_h)
    return x / (aspect * 1080.0) + 0.5, y / 1080.0 + 0.5


# ------------------------------------------------------------------ desfoque de lente
def dof_active(v: dict) -> bool:
    return float(v.get("desfoque_lente_raio", 0.0)) > 0.0


def dof_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    base, passes = entry(ctx, "desfoque_lente")
    clamp = 0.18 * 2.0 ** BOKEH_CLAMP_STOPS
    choice = str(v.get("desfoque_lente_mascara", "tudo"))
    g, k = masks.gradient_uniform(str(v.get("desfoque_lente_degrade", "linear")), float(v.get("desfoque_lente_x", 0.0)),
                                  float(v.get("desfoque_lente_y", 0.0)), float(v.get("desfoque_lente_angulo", 0.0)),
                                  float(v.get("desfoque_lente_circulo", 400.0)),
                                  float(v.get("desfoque_lente_suavidade", 400.0)),
                                  bool(v.get("desfoque_lente_inverter", False)))
    inputs = {"t_lin": "pass:luz", "t_base": base}
    mode = 1 if choice == "degrade" else 0
    if choice in MASK_SOURCES:  # máscara de forma (F2), pelo gancho
        mask = list(MASK_SOURCES[choice](ctx) or [])
        if mask:
            passes += mask
            inputs["t_mask"] = f"pass:{mask[-1].name}"
            mode = 2
    lin_input = {"t_prev": base} if passes else {}
    passes.append(vfx.Pass("luz", DOF_LIGHT, uniforms={"u_clamp": clamp}, inputs=lin_input, dtype="f2", mip=True))
    if "t_mask" not in inputs:
        inputs["t_mask"] = "pass:luz"  # sem máscara de forma: o sampler fica preso a uma textura qualquer
    passes.append(vfx.Pass("desfoque", DOF_GATHER_GLSL, inputs=inputs,
                           uniforms={"u_radius": ctx.px(v["desfoque_lente_raio"]), "u_mask": mode, "u_g": g, "u_k": k,
                                     "u_hex": int(str(v.get("desfoque_lente_forma", "disco")) == "hexagono"),
                                     "u_clamp": clamp}))
    return passes


# ------------------------------------------------------------------ listra anamórfica
def streak_active(v: dict) -> bool:
    return float(v.get("listra_intensidade", 0.0)) > 0.0


def streak_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    base, passes = entry(ctx, "listra")
    sigma = ctx.px(v.get("listra_comprimento", 400.0)) * 0.5 * 0.5  # σ = comprimento / 2, em texels da meia resolução
    angle = float(v.get("listra_angulo", 0.0))
    amt = float(v["listra_intensidade"]) * STREAK_GAIN
    tint = _color(v, "listra_cor", (0.35, 0.6, 1.0))
    frac, w_short = STREAK_SHORT
    passes += [_extract(float(v.get("listra_limiar", 2.5)), True),
               vfx.Pass("longa", kind="streak", sigma=sigma, angle=angle, size=0.5, dtype="f2",
                        inputs={"t_src": "pass:brilho"}),
               vfx.Pass("curta", kind="streak", sigma=sigma * frac, angle=angle, size=0.5, dtype="f2",
                        inputs={"t_src": "pass:brilho"}),
               vfx.Pass("soma", ADD, inputs={"t_base": base, "t_glow": "pass:longa", "t_glow2": "pass:curta"},
                        uniforms={"u_gain": tuple(c * amt * (1.0 - w_short) for c in tint),
                                  "u_gain2": tuple(c * amt * w_short for c in tint)})]
    return passes


# ------------------------------------------------------------------ flare
def flare_active(v: dict) -> bool:
    return float(v.get("flare_intensidade", 0.0)) > 0.0


def flare_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    amt = float(v["flare_intensidade"])
    tint = _color(v, "flare_cor", (1.0, 0.85, 0.7))
    n = max(1, min(8, int(v.get("flare_fantasmas", 4))))
    size = float(v.get("flare_tamanho", 80.0))
    if str(v.get("flare_fonte", "auto")) == "ponto":  # um passo só: a entrada do efeito é o "prev"
        return [vfx.Pass("flare", POINT_FLARE_GLSL,
                         uniforms={"u_src": (float(v.get("flare_x", 0.0)), float(v.get("flare_y", 0.0))),
                                   "u_size": size, "u_n": n, "u_gain": tuple(c * amt for c in tint),
                                   "u_ghost": FLARE_GHOST_LIGHT, "u_glow": FLARE_GLOW_LIGHT})]
    base, passes = entry(ctx, "flare")
    soft = ctx.px(size) * 0.1 * 0.5
    passes += [_extract(float(v.get("flare_limiar", 3.0)), False),
               vfx.Pass("macio", kind="blur", sigma=soft, size=0.5, dtype="f2", inputs={"t_src": "pass:brilho"}),
               vfx.Pass("fantasmas", GHOSTS_GLSL, inputs={"t_src": "pass:macio"}, uniforms={"u_n": n}, size=0.5,
                        dtype="f2"),
               vfx.Pass("borrar", kind="blur", sigma=soft * 2.0, size=0.5, dtype="f2"),
               vfx.Pass("soma", ADD, inputs={"t_base": base, "t_glow": "pass:borrar", "t_glow2": "pass:borrar"},
                        uniforms={"u_gain": tuple(c * amt * FLARE_GAIN for c in tint), "u_gain2": (0.0, 0.0, 0.0)})]
    return passes


# ------------------------------------------------------------------ raios de luz
def rays_active(v: dict) -> bool:
    return float(v.get("raios_intensidade", 0.0)) > 0.0


def rays_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    base, passes = entry(ctx, "raios")
    center = clip_uv(ctx, float(v.get("raios_x", 0.0)), float(v.get("raios_y", 0.0)))
    length = max(0.0, min(1.0, float(v.get("raios_comprimento", 0.5))))
    k = 1.0 - 0.15 * max(0.0, min(1.0, float(v.get("raios_decaimento", 0.5))))
    amt = float(v["raios_intensidade"]) * RAYS_GAIN
    tint = _color(v, "raios_cor", (1.0, 0.95, 0.85))
    passes += [_extract(float(v.get("raios_limiar", 1.5)), False),
               vfx.Pass("raios", RADIAL, inputs={"t_src": "pass:brilho"}, size=0.5, dtype="f2",
                        uniforms={"u_center": center, "u_len": length, "u_k": k}),
               vfx.Pass("vaos", RADIAL, inputs={"t_src": "pass:raios"}, size=0.5, dtype="f2",
                        uniforms={"u_center": center, "u_len": length / RAYS_TAPS, "u_k": 1.0}),
               vfx.Pass("soma", ADD, inputs={"t_base": base, "t_glow": "pass:vaos", "t_glow2": "pass:vaos"},
                        uniforms={"u_gain": tuple(c * amt for c in tint), "u_gain2": (0.0, 0.0, 0.0)})]
    return passes


DOF_EFFECT = vfx.register(vfx.Effect("desfoque_lente", MODULE, vfx.ORDER["desfoque_lente"], active=dof_active,
                                     passes=dof_passes, keys=DOF_KEYS))
STREAK_EFFECT = vfx.register(vfx.Effect("listra", MODULE, vfx.ORDER["luz"], active=streak_active,
                                        passes=streak_passes, keys=STREAK_KEYS))
FLARE_EFFECT = vfx.register(vfx.Effect("flare", MODULE, vfx.ORDER["luz"] + 10, active=flare_active,
                                       passes=flare_passes, keys=FLARE_KEYS))
RAYS_EFFECT = vfx.register(vfx.Effect("raios", MODULE, vfx.ORDER["luz"] + 20, active=rays_active, passes=rays_passes,
                                      keys=RAYS_KEYS))
