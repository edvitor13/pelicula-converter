"""Estrutura pela densidade (M1 da 1.6, fase 3; ARQUITETURA §30.8): a forma do grão muda com a densidade local.

Sem Qt. Dois ajustes da seção Grão: `grao_estrutura` (0–100%, padrão 0% = o grão de sempre, bit a bit: o plano não
grava nada e o Engine usa o FINAL de sempre) e `grao_aglomeracao` (avançado, 0–100%, padrão 0% = o tamanho calibrado).

**As camadas.** Três "camadas" de grão, cada uma com o tamanho, a aglomeração e a assimetria de um ponto do modelo
booleano (Matheron 1975; Newson, Delon e Galerne 2017; o mesmo modelo do grão físico, `grao_fisico.py`, com o mesmo
spot do pixel e a lei de Nutting `D = −log10(1 − u)`):

- **fina** (D = 0,05, u ≈ 0,11): grãos soltos, assimetria +1,74, um pouco maior (11%);
- **média** (D = 0,3, u ≈ 0,5): a variância máxima, quase sem assimetria, 9% maior;
- **densa** (D = 1, u ≈ 0,9): buracos soltos, assimetria −1,90, o tamanho do grão de sempre (como o `R_K` do grão
  físico); a *Aglomeração* a deixa até 2,3× maior (a amostra grossa do ruído).

A assimetria vem de uma transformação não linear do campo gaussiano do grão de sempre (a mesma grade, as mesmas
sementes e a mesma mistura de aspereza e cor): `T_s(g) = (e^(s·g − s²/2) − 1) / (sinal(s)·√(e^(s²) − 1))`, média 0 e
variância 1 exatas, assimetria `(e^(s²) + 2)·√(e^(s²) − 1)`. O tamanho vem da fração da amostra grossa do ruído (a da
*Aspereza*). Os parâmetros das três camadas se misturam por pesos suaves (smoothstep no log da densidade) da
densidade local da camada de cor: um padrão só, aninhado (mais densidade = o mesmo grão com outra forma), sem emendas
num degradê. `tools/ajustar_grao.py` (`structure_layers`) calcula as assimetrias exatas e os tamanhos.

**A força por densidade** vem do datasheet H-1-5207 (granularidade rms difusa, abertura de 48 µm, p. 3): o sigma D
de cada camada em função da densidade relativa ao cinza `ρ = (D − Dmin) / (D_cinza − Dmin)`, lida na mesma figura
(as curvas cheias de densidade e os pontos tracejados; `pelicula/data/datasheets/H-1-5207.json`). Pico suave nas
exposições baixas e médias, queda nas altas, azul > verde ≈ vermelho (`STRUCT_SIGMA_D_Q`, nós em √ρ).

- **Grão de sempre** (`u_grain_on = 1`, depois da cor): a densidade relativa de cada canal sai da exposição da cena
  (`linToStops(lin)` antes do `colorPipe`) pela curva da mesma figura (`STRUCT_RHO_X`, −8 a +8 stops); a força é
  relativa ao cinza (`sigma D(ρ) / sigma D(1)`) vezes a razão das camadas no cinza (`STRUCT_RATIO`, média do Rec.709
  = 1: o brilho do grão nos tons médios fica o de antes). Os pesos por tom (*Nas sombras*, *Nos tons médios*, *Nas
  altas luzes*) continuam multiplicando como antes: eles dizem quanto a cópia mostra o grão; a estrutura diz como o
  negativo o fez.
- **Grão no negativo, modelo "ruido"** (`u_grain_on = 2`, M3): a densidade relativa é a de cada camada no `labPath`
  (`dn / nmid`, cada caminho do Laboratório com a sua) e a força é o sigma D absoluto do datasheet naquela densidade
  (`sigma D(ρ) / NEG_SIGMA_D`, que já está em `u_ngrain`). O modelo "fisico" não usa a estrutura (ele é a estrutura).

Com *Estrutura* em `s`: assimetria `s · s_camada`, fração grossa `aspereza + (1 − aspereza)·s·δ_camada` e força
`1 + s·(envelope − 1)`; em 0 tudo volta exatamente ao grão de sempre (e nem se usa este programa).

**Na GPU** o FINAL ganha a variante `final_gs` (`FINAL_GS`, por substituição de texto de `shaders.FINAL`, compilada só
quando o plano traz `u_gs_amt`); com véu, pré-exposição ou scanner, `final_gs_lx` (`labx.patch_glsl` copia a `labPath`
já com a estrutura). O BAKE não muda: o LUT exportado nunca tem grão.
"""

from __future__ import annotations

import math

import numpy as np

from . import grao_fisico

# ------------------------------------------------------------------ constantes (tools/ajustar_grao.py)
# Tabelas do datasheet H-1-5207 (structure_tables): cinza na figura da granularidade, sigma D de R, G, B nos nós de
# √ρ (0; 0,1; ...; 1,6), sigma D no cinza, ρ nos stops da cena (−8 a +8) e a razão das camadas no cinza.
STRUCT_LOG_E_GREY = 2.527
STRUCT_SIGMA_D_Q = (
    (0.0061, 0.0061, 0.00677, 0.00833, 0.00967, 0.00989, 0.00926, 0.00849, 0.00771, 0.00694, 0.00625, 0.00589, 0.0055,
     0.00533, 0.0049, 0.0048, 0.0045),
    (0.0067, 0.0067, 0.00728, 0.00883, 0.01028, 0.01056, 0.00981, 0.00876, 0.00776, 0.00699, 0.00625, 0.0063, 0.0066,
     0.00688, 0.00636, 0.00601, 0.00513),
    (0.0147, 0.0147, 0.0147, 0.01499, 0.01555, 0.0158, 0.01524, 0.01395, 0.01279, 0.01255, 0.01275, 0.01335, 0.01367,
     0.01275, 0.01149, 0.00951, 0.0079),
)
STRUCT_SIGMA_D_GREY = (0.00625, 0.00625, 0.01275)
STRUCT_RHO_X = (
    (0.0, 0.0, 0.0, 0.0219, 0.0988, 0.2696, 0.507, 0.7554, 1.0, 1.2132, 1.436, 1.6706, 1.9047, 2.121, 2.3124, 2.4574,
     2.5181),
    (0.0, 0.0, 0.0037, 0.0247, 0.1033, 0.2814, 0.5243, 0.7683, 1.0, 1.2202, 1.4641, 1.7015, 1.939, 2.1737, 2.3717,
     2.5159, 2.5675),
    (0.0102, 0.0168, 0.0198, 0.0592, 0.16, 0.319, 0.5363, 0.7764, 1.0, 1.2191, 1.4409, 1.6754, 1.89, 2.0873, 2.2535,
     2.3867, 2.4462),
)
STRUCT_RATIO = (0.93016, 0.93016, 1.89752)
# As camadas (structure_layers): densidade, assimetria exata da cobertura vista pelo spot, o s de T_s, o tamanho em
# relação à camada densa e a fração da amostra grossa que dá esse tamanho.
STRUCT_LAYER_D = (0.05, 0.3, 1.0)
STRUCT_SKEW = (1.739, -0.146, -1.895)
STRUCT_SIGMA = (0.4976, -0.0486, -0.5304)
STRUCT_SIZE = (1.1115, 1.0876, 1.0)
STRUCT_COARSE = (0.3183, 0.2916, 0.0)

Q_KNOTS = 17          # nós de √ρ: 0 a 1,6 de 0,1 em 0,1
Q_STEP = 0.1
X_KNOTS = 17          # nós dos stops da cena: −8 a +8
SKEW_EPS = 1e-4       # |s| abaixo disto: T_s = identidade (o erro relativo é < s/2)
RHO_MIN_MID = 1e-3    # densidade do cinza mínima (divisão)


def neg_sigma_d() -> tuple[float, float, float]:
    from . import grao
    return grao.NEG_SIGMA_D


def dref() -> tuple[float, float, float]:
    """Densidade de cada camada no cinza no modelo do Laboratório (a mesma referência do grão físico): ρ · DREF é a
    densidade que decide a forma (a lei de Nutting)."""
    return grao_fisico.REF_DENSITY


# ------------------------------------------------------------------ plano (gancho de look.build_plan)
def on(v: dict) -> bool:
    return bool(v.get("grao_on")) and float(v.get("grao_forca", 0.0)) > 0.0 \
        and float(v.get("grao_estrutura", 0.0)) > 0.0


def structure(U: dict, v: dict) -> None:
    """Gancho do bloco do grão de `build_plan`, depois dos do grão no negativo: com *Estrutura* > 0 e o grão de sempre
    (`u_grain_on = 1`) ou o grão no negativo "ruido" (`2`), grava `u_gs_amt` e `u_gs_clump` (o Engine passa a usar o
    `final_gs`). Em 0% não grava nada; no modelo "fisico" (`3`) também não."""
    if not on(v) or U.get("u_grain_on") not in (1, 2):
        return
    U["u_gs_amt"] = float(v["grao_estrutura"])
    U["u_gs_clump"] = float(v.get("grao_aglomeracao", 0.0))


# ------------------------------------------------------------------ referência em numpy (a mesma conta do GLSL)
def _f32(x):
    return np.asarray(x, dtype=np.float64)


def rho_of_stops(x, ch: int) -> np.ndarray:
    """Densidade relativa ao cinza da camada `ch` na exposição `x` (stops da cena; grão de sempre)."""
    t = np.clip(_f32(x) + 8.0, 0.0, X_KNOTS - 1.0)
    return np.interp(t, np.arange(X_KNOTS, dtype=np.float64), np.asarray(STRUCT_RHO_X[ch], np.float64))


def sigma_d(rho, ch: int) -> np.ndarray:
    """Sigma D (48 µm) da camada `ch` na densidade relativa `rho` (interpolado nos nós de √ρ)."""
    t = np.clip(np.sqrt(np.maximum(_f32(rho), 0.0)) / Q_STEP, 0.0, Q_KNOTS - 1.0)
    return np.interp(t, np.arange(Q_KNOTS, dtype=np.float64), np.asarray(STRUCT_SIGMA_D_Q[ch], np.float64))


def smoothstep(a: float, b: float, x) -> np.ndarray:
    t = np.clip((_f32(x) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def layer_weights(rho, ch: int) -> tuple[np.ndarray, np.ndarray]:
    """(s01, s12): passagem fina → média e média → densa, suaves no log da densidade ρ · DREF."""
    lD = np.log(np.maximum(np.maximum(_f32(rho), 0.0) * dref()[ch], 1e-6))
    ld = [math.log(d) for d in STRUCT_LAYER_D]
    return smoothstep(ld[0], ld[1], lD), smoothstep(ld[1], ld[2], lD)


def layer_params(rho, ch: int, amount: float, clump: float) -> tuple[np.ndarray, np.ndarray]:
    """(s do T_s, fração grossa extra δ) misturados pela densidade, já com a *Estrutura* `amount`."""
    s01, s12 = layer_weights(rho, ch)
    sg = STRUCT_SIGMA
    sig = amount * (sg[0] + (sg[1] - sg[0]) * s01 + (sg[2] - sg[1]) * s12)
    cr = STRUCT_COARSE
    d2 = cr[2] + clump * (1.0 - cr[2])
    delta = cr[0] + (cr[1] - cr[0]) * s01 + (d2 - cr[1]) * s12
    return sig, delta


def skew_transform(g, s) -> np.ndarray:
    """T_s(g): média 0 e variância 1 para g gaussiana de variância 1; assimetria com o sinal de s."""
    g, s = np.broadcast_arrays(_f32(g), _f32(s))
    small = np.abs(s) < SKEW_EPS
    ss = np.where(small, 1.0, s)
    out = np.expm1(ss * g - 0.5 * ss * ss) / (np.sign(ss) * np.sqrt(np.expm1(ss * ss)))
    return np.where(small, g, out)


def envelope(rho, ch: int, negative: bool) -> np.ndarray:
    """Força relativa da estrutura em 100%: grão no negativo = sigma D(ρ) / NEG_SIGMA_D (o absoluto do datasheet);
    grão de sempre = sigma D(ρ) / sigma D(1) × razão da camada."""
    sd = sigma_d(rho, ch)
    if negative:
        return sd / neg_sigma_d()[ch]
    return sd / STRUCT_SIGMA_D_GREY[ch] * STRUCT_RATIO[ch]


def channel(nf, nc, ch: int, rho, rough: float, chroma: float, amount: float, clump: float,
            negative: bool) -> np.ndarray:
    """Um canal da estrutura (o `gsChannel` do GLSL): nf, nc = amostras fina e grossa do ruído (…, 4) já × 2,08."""
    nf, nc = _f32(nf), _f32(nc)
    sig, delta = layer_params(rho, ch, amount, clump)
    c = rough + (1.0 - rough) * amount * delta
    k = 1.0 / np.sqrt((1.0 - c) ** 2 + c * c)
    a = (nf[..., 3] * (1.0 - c) + nc[..., 3] * c) * k
    b = (nf[..., ch] * (1.0 - c) + nc[..., ch] * c) * k
    g = (a * (1.0 - chroma) + b * chroma) / math.sqrt((1.0 - chroma) ** 2 + chroma * chroma)
    return skew_transform(g, sig) * (1.0 + amount * (envelope(rho, ch, negative) - 1.0))


# ------------------------------------------------------------------ GLSL (FINAL_GS)
def _glsl_float(x: float) -> str:
    s = repr(float(np.float32(x)))
    return s if ("." in s or "e" in s) else s + ".0"


def _array(name: str, rows) -> str:
    vals = [v for row in rows for v in row]
    return f"const float {name}[{len(vals)}] = float[{len(vals)}](" + ", ".join(_glsl_float(v) for v in vals) + ");\n"


def _vec3(name: str, v) -> str:
    return f"const vec3 {name} = vec3(" + ", ".join(_glsl_float(x) for x in v) + ");\n"


GLSL_COMMON = """
// ---------------------------------------------------------------- 1.6: estrutura pela densidade (grao_estrutura.py)
// Três camadas do modelo booleano (fina, média, densa: assimetria e tamanho), misturadas pela densidade relativa ao
// cinza de cada camada de cor; força pelo sigma D do datasheet H-1-5207. Só no programa final_gs (o plano sempre grava
// os dois uniforms).
uniform float u_gs_amt;    // Estrutura pela densidade (0–1)
uniform float u_gs_clump;  // Aglomeração nas altas densidades (0–1)
vec3 g_gs_x = vec3(0.0);   // exposição da cena em stops (grão de sempre)
vec4 g_gs_nf = vec4(0.0);  // grão no negativo: amostras do ruído deste pixel (gsSample, no main)
vec4 g_gs_nc = vec4(0.0);
vec3 g_gs_amp = vec3(0.0); // u_ngrain
vec2 g_gs_rc = vec2(0.0);  // aspereza, grão colorido
int g_gs_neg = 0;          // 1 = gsNeg soma o grão na densidade (só no grão no negativo)
""" + _array("GS_SDQ", STRUCT_SIGMA_D_Q) + _array("GS_RHOX", STRUCT_RHO_X) \
    + _vec3("GS_SDGREY", STRUCT_SIGMA_D_GREY) + _vec3("GS_RATIO", STRUCT_RATIO) \
    + _vec3("GS_SDNEG", (0.0, 0.0, 0.0)).replace("vec3(0.0, 0.0, 0.0)", "%(SDNEG)s") \
    + _vec3("GS_DREF", (0.0, 0.0, 0.0)).replace("vec3(0.0, 0.0, 0.0)", "%(DREF)s") \
    + _vec3("GS_LLD", tuple(math.log(d) for d in STRUCT_LAYER_D)) + _vec3("GS_SIG", STRUCT_SIGMA) \
    + _vec3("GS_CRS", STRUCT_COARSE) + """
float gsSdq(int ch, float rho) {
    float t = clamp(sqrt(max(rho, 0.0)) * 10.0, 0.0, 16.0);
    int i = min(int(t), 15);
    return mix(GS_SDQ[ch * 17 + i], GS_SDQ[ch * 17 + i + 1], t - float(i));
}
float gsRhoX(int ch, float x) {
    float t = clamp(x + 8.0, 0.0, 16.0);
    int i = min(int(t), 15);
    return mix(GS_RHOX[ch * 17 + i], GS_RHOX[ch * 17 + i + 1], t - float(i));
}
// T_s(g) = (e^(s·g − s²/2) − 1) / (sinal(s)·√(e^(s²) − 1)): média 0, variância 1, assimetria com o sinal de s
// (e^x − 1 sem cancelamento em float32 perto de 0: a série até x⁴, erro < 1e-11 relativo)
float gsExpm1(float x) {
    return abs(x) < 0.01 ? x * (1.0 + x * (0.5 + x * (0.16666667 + x * 0.041666668))) : exp(x) - 1.0;
}
float gsSkew(float g, float s) {
    if (abs(s) < 1e-4) return g;
    return gsExpm1(s * g - 0.5 * s * s) / (sign(s) * sqrt(gsExpm1(s * s)));
}
// Um canal: o campo do grão com a forma da densidade rho (relativa ao cinza) e a força relativa. neg = 1: grão no
// negativo (sigma D absoluto do datasheet); 0: grão de sempre (relativo ao cinza × razão das camadas).
float gsChannel(vec4 nf, vec4 nc, int ch, float rho, float rough, float chroma, int neg) {
    float s = u_gs_amt;
    float lD = log(max(max(rho, 0.0) * GS_DREF[ch], 1e-6));
    float s01 = smoothstep(GS_LLD.x, GS_LLD.y, lD);
    float s12 = smoothstep(GS_LLD.y, GS_LLD.z, lD);
    float sig = s * (GS_SIG.x + (GS_SIG.y - GS_SIG.x) * s01 + (GS_SIG.z - GS_SIG.y) * s12);
    float d2 = GS_CRS.z + u_gs_clump * (1.0 - GS_CRS.z);
    float dl = GS_CRS.x + (GS_CRS.y - GS_CRS.x) * s01 + (d2 - GS_CRS.y) * s12;
    float c = rough + (1.0 - rough) * s * dl;
    float k = 1.0 / sqrt((1.0 - c) * (1.0 - c) + c * c);
    float a = (nf.a * (1.0 - c) + nc.a * c) * k;
    float b = (nf[ch] * (1.0 - c) + nc[ch] * c) * k;
    float g = (a * (1.0 - chroma) + b * chroma) / sqrt((1.0 - chroma) * (1.0 - chroma) + chroma * chroma);
    float sd = gsSdq(ch, rho);
    float env = (neg == 1) ? sd / GS_SDNEG[ch] : sd / GS_SDGREY[ch] * GS_RATIO[ch];
    return gsSkew(g, sig) * (1.0 + s * (env - 1.0));
}
// Grão no negativo: o desvio da densidade de cada camada (labPath; cada caminho com a sua densidade e o seu cinza)
vec3 gsNeg(vec3 dn, vec3 nmid) {
    if (g_gs_neg == 0) return vec3(0.0);
    vec3 g;
    for (int ch = 0; ch < 3; ch++)
        g[ch] = gsChannel(g_gs_nf, g_gs_nc, ch, dn[ch] / max(nmid[ch], %(RMIN)s), g_gs_rc.x, g_gs_rc.y, 1);
    return g * g_gs_amp;
}
"""

GLSL_FINAL = """
// 1.6: estrutura pela densidade no grão de sempre (depois da cor; a densidade vem da exposição da cena, g_gs_x)
vec3 applyGrainS(vec3 y, vec2 uv) {
    vec4 nf = texBicubic(t_noise, uv) * 2.08;
    vec4 nc = texBicubic(t_noise, uv * 0.4347 + vec2(0.311, 0.173)) * 2.08;
    vec3 g;
    for (int ch = 0; ch < 3; ch++)
        g[ch] = gsChannel(nf, nc, ch, gsRhoX(ch, g_gs_x[ch]), u_grain_rough, u_grain_chroma, 0);
    float L = clamp(dot(y, W709), 0.0, 1.0);
    float w = u_grain_resp.x * exp(-pow((L - 0.10) / 0.16, 2.0))
            + u_grain_resp.y * exp(-pow((L - 0.45) / 0.22, 2.0))
            + u_grain_resp.z * exp(-pow((L - 0.88) / 0.16, 2.0));
    return y + g * u_grain_amt * w;
}
// 1.6: grão no negativo com a estrutura: as amostras do ruído deste pixel para gsNeg (dentro de labPath)
void gsSample(vec2 uv) {
    g_gs_nf = texBicubic(t_noise, uv) * 2.08;
    g_gs_nc = texBicubic(t_noise, uv * 0.4347 + vec2(0.311, 0.173)) * 2.08;
    g_gs_amp = u_ngrain;
    g_gs_rc = vec2(u_grain_rough, u_grain_chroma);
    g_gs_neg = 1;
}

"""


def _glsl_common() -> str:
    return GLSL_COMMON % {"SDNEG": "vec3(" + ", ".join(_glsl_float(x) for x in neg_sigma_d()) + ")",
                          "DREF": "vec3(" + ", ".join(_glsl_float(x) for x in dref()) + ")",
                          "RMIN": _glsl_float(RHO_MIN_MID)}


def _final_gs() -> str:
    from . import shaders
    src = shaders.FINAL
    anchors = (
        ("// Um caminho completo. lin:", _glsl_common() + "\n// Um caminho completo. lin:"),
        ("    dn += g_ng;\n", "    dn += gsNeg(dn, nmid);  // 1.6: estrutura pela densidade (grão no negativo)\n"),
        ("vec3 leak(vec2 uv) {", GLSL_FINAL + "vec3 leak(vec2 uv) {"),
        ("    if (u_grain_on == 2) g_ng = negGrain(uv);\n",
         "    if (u_grain_on == 2) gsSample(uv);\n    g_gs_x = linToStops(lin);  // 1.6: a exposição da cena\n"),
        ("    if (u_grain_on == 1) y = applyGrain(y, uv);\n", "    if (u_grain_on == 1) y = applyGrainS(y, uv);\n"),
    )
    for old, new in anchors:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    return src


# O FINAL de sempre com a estrutura pela densidade (Engine._final_program, compilado só no primeiro uso): o FINAL e o
# BAKE (o LUT exportado) continuam letra por letra os de antes.
FINAL_GS = _final_gs()
_PROGRAMS: dict[str, str] = {"final_gs": FINAL_GS}


def program(name: str) -> str:
    """Fonte da variante `final_gs` ou `final_gs_lx` (com véu, pré-exposição e scanner: `labx.patch_glsl` copia a
    `labPath` já com a estrutura)."""
    if name not in _PROGRAMS:
        from . import labx
        assert name == "final_gs_lx", name
        _PROGRAMS[name] = labx.patch_glsl(FINAL_GS)
    return _PROGRAMS[name]
