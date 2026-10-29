"""Grão físico (M1 da 1.6, ARQUITETURA §30.7): o modelo booleano de Nutting e de Newson na densidade do negativo.

Sem Qt. Um modo novo do "Grão no negativo" (`lab_grao_modelo = "fisico"`, módulo Beta `grao_fisico`); o padrão
(`"ruido"`) é o grão no negativo da M3 como sempre foi, bit a bit.

**O modelo.** Cada camada R, G, B do negativo é um modelo booleano: discos opacos de raio `r` (os grãos de prata
revelados / nuvens de corante), com centros num processo de Poisson. A intensidade do processo vem do próprio valor
local da camada pela lei da cobertura:

- Nutting (1913): a transmitância de uma camada de grãos opacos é `T = 1 − cobertura`, e a densidade `D = −log10 T`;
- Newson, Delon e Galerne (2017, "A Stochastic Film Grain Model for Resolution-Independent Rendering", Computer
  Graphics Forum 36(8)): para cobrir a fração `u` com discos de raio `r`, a intensidade é
  `λ(u) = −ln(1 − u) / (π · E[r²])`.

Juntas: `λ · π r² = D · ln 10`. Um processo só, com um conjunto só de parâmetros globais (o raio, igual em toda a
imagem; a semente; a fração dos centros que as três camadas compartilham): nada é escolhido por faixa de brilho ou
de densidade, não há mattes nem placas de grão gravadas, e nada é estimado de um quadro ou de um scan. O
comportamento visível nasce da lei: onde a camada é fina, grãos isolados; onde é densa, buracos isolados; a
variância da cobertura é máxima no meio (`u(1 − u)` no ponto) e a assimetria troca de sinal.

**A imagem.** O pixel vê a cobertura filtrada por um "spot" (o do scan): `N_SAMPLES` pontos fixos, de distribuição
gaussiana com sigma `FILTER_K · r`, em px@1080 (`offsets()`): a estatística é a mesma em qualquer resolução. A
transmitância do pixel é `T̂ = 1 − û` (û = fração dos pontos cobertos). O grão real (frações de µm) é muito menor que
um pixel de 1080 e daria só um ruído gaussiano; o app usa o tamanho visível do grão de sempre
(`r = R_K · grao.grain_size_1080`, que segue a bitola, o ISO e o Tamanho) e calibra a amplitude: só a fração
`a = KAPPA · multiplicador do grão` da transmitância varia com os grãos resolvidos,
`T' = (1 − a) · T + a · T̂` (a média é a mesma `T`: a luz da copiadora não muda), e o desvio de densidade é
`dD = −log10(T' / T) = −log10(1 + a · (T̂ − T) / T)`, somado à densidade da camada em `labPath`.

**Calibração.** `KAPPA` de cada camada faz a granularidade rms difusa numa abertura de 48 µm, na densidade de
referência (a da camada no cinza médio da Vision3 250D do Laboratório), ser a `grao.NEG_SIGMA_D` (H-1-5207: azul >
verde > vermelho). A conta é exata e offline (`tools/ajustar_grao.py`): a covariância da cobertura do modelo
booleano é `(1 − u)² · (e^(λ·γ(h)) − 1)`, com `γ(h)` a área comum de dois discos a uma distância `h`, integrada com
a das aberturas e a do spot.

**Na GPU** (`GLSL`, `FINAL_PG`): grade de células de lado `CELL` (em raios); em cada célula um processo de Poisson
por chegadas no eixo da intensidade (`t_i` = soma de exponenciais de um hash de (célula, processo, semente)): o
disco `i` existe para a camada se `t_i < λ · área`. A contagem é Poisson e aninhada (mais densidade = os mesmos
grãos e mais alguns), então uma borda da imagem não embaralha o grão. Um processo comum às três camadas (fração
`1 − grao_cor` dos centros) e um próprio de cada uma (fração `grao_cor`): a união é um processo de Poisson com a
mesma `λ`, e "Grão colorido" decide quanto as camadas se parecem. Cada disco perto do ponto é testado nos
`N_SAMPLES` pontos do spot. Mesmo número de pontos na prévia e na exportação; tudo do quadro e da semente.
"""

from __future__ import annotations

import math

import numpy as np

from . import grao

# ------------------------------------------------------------------ constantes do modelo (globais)
FILTER_K = 0.75    # sigma do spot do pixel, em raios (na referência: 0,46 px@1080)
N_SAMPLES = 16     # pontos do spot (fixos; os mesmos na prévia, na exportação e no plugin)
D_MAX = 3.0        # densidade máxima do modelo (u = 0,999); só um limite de segurança, o negativo não chega lá
AMP_MAX = 0.95     # a fração com grão resolvido nunca passa disto (T' > 0 sempre)
CAP = 64           # no máximo CAP grãos por célula e processo (a média vai até ~15 em D_MAX)
LN10 = math.log(10.0)

# Calibração (tools/ajustar_grao.py, `_physical`), na referência (35 mm, ISO 250, Tamanho 1):
# - R_K: raio do grão = R_K · tamanho natural do grão (grao.grain_size_1080), em px@1080; o que dá à cobertura vista
#   pelo spot o comprimento de correlação (meia altura) do grão de sempre (0,99 célula) na densidade de referência do
#   verde: o mesmo tamanho visível do modelo "ruido", outra estrutura;
# - KAPPA: fração da transmitância de cada camada R, G, B com o grão resolvido, para que o sigma D numa abertura de
#   48 µm, na densidade da camada no cinza médio da Vision3 250D, seja o NEG_SIGMA_D do datasheet H-1-5207.
R_K = 0.759
KAPPA = (0.02564, 0.02975, 0.05393)
REF_DENSITY = (0.96198, 0.96198, 0.94202)  # densidade de cada camada no cinza médio (look.lab_paths, 250D)

GOLDEN = math.pi * (3.0 - math.sqrt(5.0))

# 1.6 (fase 3): *Tamanho do cristal* e *Variação do tamanho* (ARQUITETURA §30.8). A variação dá a cada grão um raio
# log-normal ρ = e^(s·z − s²) / √c (z gaussiana cortada em ±Z_CLIP, s = VAR_SIGMA × variação, c = a média de
# e^(2·s·z − 2·s²) com o corte: E[ρ²] = 1, então λ·π·E[r²] = D·ln 10 continua e a densidade média não muda).
Z_CLIP = 2.5
VAR_SIGMA = 0.5
# Compensação do KAPPA de cada camada R, G, B (tools/ajustar_grao.py, `physical_extra_constants`): o sigma D na
# abertura de 48 µm, na densidade de referência, continua o NEG_SIGMA_D com qualquer cristal e qualquer variação (o
# cristal muda a textura, não a granularidade do datasheet; o Tamanho do grão da seção Grão muda os dois).
CRYSTAL_KNOTS = (0.5, 0.594604, 0.707107, 0.840896, 1.0, 1.189207, 1.414214, 1.681793, 2.0)
CRYSTAL_K = ((1.8075, 1.54748, 1.33032, 1.14958, 1.0, 0.87733, 0.77815, 0.69958, 0.6388),
             (1.8075, 1.54748, 1.33032, 1.14958, 1.0, 0.87733, 0.77815, 0.69958, 0.6388),
             (1.8073, 1.54734, 1.33023, 1.14953, 1.0, 0.87737, 0.77824, 0.69971, 0.63898))
VARIATION_KNOTS = (0.0, 0.25, 0.5, 0.75, 1.0)
VARIATION_K = ((1.0, 0.98101, 0.92682, 0.84782, 0.75929),
               (1.0, 0.98101, 0.92682, 0.84782, 0.75929),
               (1.0, 0.98089, 0.92639, 0.84708, 0.75838))


def radius_params(variation: float) -> tuple[float, float, float]:
    """(s, 1/√c, ρ máximo) da *Variação do tamanho* (0–1): os raios relativos ρ = e^(s·z − s²)/√c, z em ±Z_CLIP."""
    s = VAR_SIGMA * min(max(float(variation), 0.0), 1.0)
    if s == 0.0:
        return 0.0, 1.0, 1.0
    a = Z_CLIP

    def phi(x: float) -> float:
        return 0.5 * math.erfc(-x / math.sqrt(2.0))
    c = (phi(a - 2 * s) - phi(-a - 2 * s)) + math.exp(-2 * s * s) * phi(-a) * (math.exp(2 * s * a) + math.exp(-2 * s * a))
    inv = 1.0 / math.sqrt(c)
    return s, inv, math.exp(s * a - s * s) * inv


def _interp_row(x: float, knots, row) -> float:
    return float(np.interp(x, knots, row))


def kappa_factor(crystal: float, variation: float) -> tuple[float, float, float]:
    """Fator do KAPPA de cada camada para o cristal (interpolado em log2) e a variação (linear); (1, 1, 1) no padrão."""
    lc = math.log2(min(max(float(crystal), CRYSTAL_KNOTS[0]), CRYSTAL_KNOTS[-1]))
    lk = [math.log2(k) for k in CRYSTAL_KNOTS]
    v = min(max(float(variation), 0.0), 1.0)
    return tuple(_interp_row(lc, lk, CRYSTAL_K[i]) * _interp_row(v, VARIATION_KNOTS, VARIATION_K[i]) for i in range(3))


def offsets() -> np.ndarray:
    """(N_SAMPLES, 2) pontos do spot em raios: espiral de Vogel com os raios nos quantis de uma gaussiana 2D de
    sigma FILTER_K (cada ponto vale 1/N da mesma área de probabilidade)."""
    k = np.arange(N_SAMPLES, dtype=np.float64)
    rho = FILTER_K * np.sqrt(-2.0 * np.log(1.0 - (k + 0.5) / N_SAMPLES))
    a = k * GOLDEN
    pts = np.stack([rho * np.cos(a), rho * np.sin(a)], axis=1)
    return pts.astype(np.float32).astype(np.float64)  # os mesmos valores de float32 do shader


REACH = 1.0 + float(np.max(np.hypot(*offsets().T)))  # distância máxima (em raios) de um centro que cobre um ponto
CELL = REACH       # lado da célula da grade, em raios


def disc_mean(d) -> np.ndarray:
    """λ · área da célula (r = 1) para a densidade `d` da camada (a média de grãos por célula e processo)."""
    return np.clip(np.asarray(d, dtype=np.float64), 0.0, D_MAX) * (LN10 * CELL * CELL / math.pi)


# ------------------------------------------------------------------ estatística exata do modelo (sem simulação)
def overlap_area(h) -> np.ndarray:
    """γ(h): área comum de dois discos de raio 1 com centros à distância h."""
    h = np.minimum(np.abs(np.asarray(h, dtype=np.float64)), 2.0)
    return 2.0 * np.arccos(h / 2.0) - (h / 2.0) * np.sqrt(np.maximum(4.0 - h * h, 0.0))


def covariance(h, density: float) -> np.ndarray:
    """Cov(cobertura em x, cobertura em x + h) do modelo booleano (r = 1) numa camada de densidade `density`:
    P(nenhum dos dois coberto) = (1 − u)² · e^(λ·γ(h)), então Cov = (1 − u)² · (e^(λ·γ(h)) − 1)."""
    d = float(np.clip(density, 0.0, D_MAX))
    lam = d * LN10 / math.pi
    t = 10.0 ** -d
    return t * t * (np.exp(lam * overlap_area(h)) - 1.0)


def pixel_stats(density: float) -> tuple[float, float]:
    """(média, variância) exatas de û, a cobertura vista pelo spot de N_SAMPLES pontos."""
    o = offsets()
    d = np.linalg.norm(o[:, None] - o[None], axis=-1)
    u = 1.0 - 10.0 ** -float(np.clip(density, 0.0, D_MAX))
    return u, float(covariance(d, density).mean())


# ------------------------------------------------------------------ plano (gancho de look.build_plan)
def on(v: dict) -> bool:
    """O grão no negativo ligado e no modelo físico."""
    return grao.negative_grain_on(v) and v.get("lab_grao_modelo", "ruido") == "fisico"


def radius_1080(v: dict, gauge: dict) -> float:
    """Raio do grão em px@1080 (segue a bitola, o ISO e o Tamanho, como o grão de sempre)."""
    return R_K * grao.grain_size_1080(v, gauge)


def negative_grain(plan, U: dict, v: dict, gauge: dict, scale: float, amt: float, net_grain: float = 0.0) -> None:
    """Gancho do bloco do grão de `build_plan`, depois de `grao.negative_grain`: no modelo "fisico", o grão no
    negativo passa a ser o modelo booleano (`u_grain_on = 3`, programa `FINAL_PG`). `amt` é o multiplicador do grão
    sem a compensação de prévia reduzida (Intensidade × bitola × ISO × revelação × redes): o modelo é igual em
    qualquer resolução. Com "ruido" (o padrão) não mexe em nada."""
    if not on(v) or U.get("u_grain_on") != 2:
        return
    from .look import NET_GRAIN_CHROMA, NET_GRAIN_MIN_PX
    s = grao.grain_size_1080(v, gauge)
    chroma = float(v["grao_cor"])
    if net_grain > 0:  # "Grão para redes": o mesmo tamanho mínimo em pixels da saída do grão de sempre
        s = max(s, NET_GRAIN_MIN_PX * float(net_grain) / scale)
        chroma *= NET_GRAIN_CHROMA
    U["u_grain_on"] = 3
    U.pop("u_ngrain", None)
    U["u_pg_r"] = R_K * s
    U["u_pg_k"] = float(np.float32(1.0 / scale))  # px@1080 por pixel da imagem
    U["u_pg_amp"] = tuple(min(k * float(amt), AMP_MAX) for k in KAPPA)
    U["u_pg_chroma"] = chroma
    U["u_pg_seed"] = int(plan.grain_seed % 2147483647)
    plan.grain_size = 0.0  # a grade do ruído não é usada
    extras(U, v, amt)  # 1.6 (fase 3): tamanho do cristal e variação do tamanho (nada no padrão)


# ------------------------------------------------------------------ GLSL (FINAL_PG)
def _glsl_float(x: float) -> str:
    s = repr(float(np.float32(x)))
    return s if ("." in s or "e" in s) else s + ".0"


def _ofs_glsl() -> str:
    o = offsets()
    items = ", ".join(f"vec2({_glsl_float(a)}, {_glsl_float(b)})" for a, b in o)
    return f"const vec2 PG_OFS[{N_SAMPLES}] = vec2[{N_SAMPLES}]({items});\n"


GLSL = """
// ---------------------------------------------------------------- 1.6: grão físico (grao_fisico.py, §30.7)
// Modelo booleano por camada: discos opacos de raio u_pg_r (px@1080), centros de Poisson com λ·πr² = D·ln 10
// (Nutting; Newson et al. 2017). Uniforms só lidos com u_grain_on = 3 (esse plano sempre os grava).
uniform float u_pg_r;       // raio do grão, px@1080
uniform float u_pg_k;       // px@1080 por pixel da imagem
uniform vec3 u_pg_amp;      // fração da transmitância com o grão resolvido (KAPPA × multiplicador do grão)
uniform float u_pg_chroma;  // fração dos centros própria de cada camada (o resto é comum às três)
uniform int u_pg_seed;
vec2 g_pg_pos = vec2(0.0);  // posição do pixel em px@1080 (só o FINAL_PG preenche)
""" + _ofs_glsl() + f"""const float PG_REACH = {_glsl_float(REACH)};
const float PG_CELL = {_glsl_float(CELL)};
const float PG_DMAX = {_glsl_float(D_MAX)};
const float PG_AMP_MAX = {_glsl_float(AMP_MAX)};
const float PG_MEAN_K = {_glsl_float(LN10 * CELL * CELL / math.pi)};  // λ · área da célula por unidade de D
""" + """
uint pgBits(uint m) {
    m = m - ((m >> 1u) & 0x55555555u);
    m = (m & 0x33333333u) + ((m >> 2u) & 0x33333333u);
    m = (m + (m >> 4u)) & 0x0F0F0F0Fu;
    return (m * 0x01010101u) >> 24u;
}

// Quais pontos do spot um disco cobre (bits); d = centro do disco − pixel, em raios.
uint pgHits(vec2 d) {
    uint m = 0u;
    for (int k = 0; k < %(N)d; k++) {
        vec2 e = d - PG_OFS[k];
        if (dot(e, e) < 1.0) m |= (1u << uint(k));
    }
    return m;
}

// Cobertura de cada camada vista pelo spot do pixel na posição p (px@1080). D: densidade de cada camada; seed: a do
// quadro. Em cada célula, chegadas t_i (soma de exponenciais) no eixo da intensidade: o disco i existe numa camada se
// t_i < λ·área (Poisson e aninhado). Processo 0 = comum às três camadas; 1, 2, 3 = o próprio de R, G, B.
vec3 physCoverage(vec3 D, vec2 p, uint seed) {
    vec3 m = clamp(D, 0.0, PG_DMAX) * PG_MEAN_K;
    vec3 ms = m * (1.0 - u_pg_chroma);
    vec3 mo = m * u_pg_chroma;
    vec2 q = p / u_pg_r;
    ivec2 c0 = ivec2(floor((q - PG_REACH) / PG_CELL));
    ivec2 c1 = ivec2(floor((q + PG_REACH) / PG_CELL));
    uint mr = 0u;
    uint mg = 0u;
    uint mb = 0u;
    for (int cy = c0.y; cy <= c1.y; cy++) {
        for (int cx = c0.x; cx <= c1.x; cx++) {
            vec2 lo = vec2(float(cx), float(cy)) * PG_CELL;
            vec2 nq = clamp(q, lo, lo + PG_CELL) - q;
            if (dot(nq, nq) >= PG_REACH * PG_REACH) continue;
            uint bx = uint(cx + 65536);
            uint by = uint(cy + 65536);
            for (int proc = 0; proc < 4; proc++) {
                float lim = (proc == 0) ? max(ms.r, max(ms.g, ms.b)) : ((proc == 1) ? mo.r : ((proc == 2) ? mo.g : mo.b));
                if (lim <= 0.0) continue;
                uint base = pcg(bx + pcg(by + pcg(seed * 4u + uint(proc))));
                float t = 0.0;
                for (uint i = 0u; i < %(CAP)du; i++) {
                    uint h = pcg(base + i);
                    uint h2 = pcg(h ^ 0x9E3779B9u);
                    t -= log((float(h2 >> 8u) + 0.5) * (1.0 / 16777216.0));
                    if (t >= lim) break;
                    vec2 c = (vec2(float(cx), float(cy))
                              + vec2(float(h & 0xFFFFu) + 0.5, float(h >> 16u) + 0.5) * (1.0 / 65536.0)) * PG_CELL;
                    vec2 d = c - q;
                    if (dot(d, d) >= PG_REACH * PG_REACH) continue;
                    uint hm = pgHits(d);
                    if (proc == 0) {
                        if (t < ms.r) mr |= hm;
                        if (t < ms.g) mg |= hm;
                        if (t < ms.b) mb |= hm;
                    } else if (proc == 1) {
                        mr |= hm;
                    } else if (proc == 2) {
                        mg |= hm;
                    } else {
                        mb |= hm;
                    }
                }
            }
        }
    }
    return vec3(float(pgBits(mr)), float(pgBits(mg)), float(pgBits(mb))) * (1.0 / %(N)d.0);
}

// Desvio da densidade de cada camada (o que labPath soma): só a fração a da transmitância vê os grãos resolvidos,
// T' = (1 − a)·T + a·T̂, dD = −log10(T'/T). Sem lógica por faixa: a mesma conta para toda densidade.
vec3 physGrain(vec3 D, vec2 p, uint seed) {
    vec3 cov = physCoverage(D, p, seed);
    vec3 T = exp2(clamp(D, 0.0, PG_DMAX) * -3.321928095);
    vec3 a = min(u_pg_amp, vec3(PG_AMP_MAX));
    return log2(vec3(1.0) + a * ((vec3(1.0) - cov) - T) / T) * -0.301029996;
}
""" % {"N": N_SAMPLES, "CAP": CAP}


def _final_pg() -> str:
    from . import shaders
    src = shaders.FINAL
    anchors = (
        ("// Um caminho completo. lin:", GLSL + "\n// Um caminho completo. lin:"),
        ("    dn += g_ng;\n", "    dn += g_ng;\n    dn += physGrain(dn, g_pg_pos, uint(u_pg_seed));  // 1.6: grão físico\n"),
        ("    vec2 uv = v_uv;\n",
         "    vec2 uv = v_uv;\n    g_pg_pos = gl_FragCoord.xy * u_pg_k;  // linha 0 da imagem: gl_FragCoord.y = 0,5\n"),
    )
    for old, new in anchors:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    return src


# O FINAL de sempre com o grão físico na densidade do negativo (Engine._final_program, compilado só no primeiro uso):
# o FINAL e o BAKE (o LUT exportado) continuam letra por letra os de antes.
FINAL_PG = _final_pg()


# ------------------------------------------------------------------ 1.6 (fase 3): cristal e variação do tamanho
def extras(U: dict, v: dict, amt: float) -> None:
    """Gancho de `negative_grain` (modelo "fisico"): *Tamanho do cristal* multiplica o raio e *Variação do tamanho*
    espalha os raios (u_pg_var: programa `final_pgv`); o KAPPA de cada camada é compensado (`kappa_factor`) para o
    sigma D da abertura de 48 µm, na densidade de referência, continuar o do datasheet. No padrão (1 e 0%) não muda
    nada (nem os valores do plano)."""
    m = float(v.get("lab_grao_cristal", 1.0))
    var = float(v.get("lab_grao_variacao", 0.0))
    if m == 1.0 and var <= 0.0:
        return
    f = kappa_factor(m, var)
    U["u_pg_r"] = U["u_pg_r"] * m
    U["u_pg_amp"] = tuple(min(k * fi * float(amt), AMP_MAX) for k, fi in zip(KAPPA, f))
    if var > 0.0:
        U["u_pg_var"] = radius_params(var)


def _glsl_variable() -> str:
    """GLSL do grão físico com raios variáveis: cada disco ganha o seu raio de um hash próprio; o alcance da busca
    cresce com o maior raio. O GLSL de sempre (raio único) não muda."""
    src = GLSL
    pairs = (
        ("uniform int u_pg_seed;\n",
         "uniform int u_pg_seed;\n"
         "uniform vec3 u_pg_var;     // 1.6 (fase 3): variação do tamanho: s, 1/√c, maior raio relativo (final_pgv)\n"),
        ("uint pgHits(vec2 d) {", "uint pgHits(vec2 d, float r2) {"),
        ("        if (dot(e, e) < 1.0) m |= (1u << uint(k));",
         "        if (dot(e, e) < r2) m |= (1u << uint(k));"),
        ("vec3 physCoverage(vec3 D, vec2 p, uint seed) {",
         "// Raio relativo de um grão (log-normal, z gaussiana cortada em ±Z_CLIP; E[ρ²] = 1): de um hash do próprio grão\n"
         "float pgRadius(uint h2) {\n"
         "    uint h3 = pcg(h2 ^ 0x85EBCA6Bu);\n"
         "    uint h4 = pcg(h3);\n"
         "    float u1 = (float(h3 >> 8u) + 0.5) * (1.0 / 16777216.0);\n"
         "    float u2 = float(h4 >> 8u) * (1.0 / 16777216.0);\n"
         "    float z = clamp(sqrt(-2.0 * log(u1)) * cos(6.2831853 * u2), -%(Z)s, %(Z)s);\n"
         "    return exp(u_pg_var.x * z - u_pg_var.x * u_pg_var.x) * u_pg_var.y;\n"
         "}\n"
         "vec3 physCoverage(vec3 D, vec2 p, uint seed) {"),
        ("    vec2 q = p / u_pg_r;\n",
         "    vec2 q = p / u_pg_r;\n    float rv = PG_REACH - 1.0 + u_pg_var.z;  // alcance com o maior grão\n"),
        ("    ivec2 c0 = ivec2(floor((q - PG_REACH) / PG_CELL));\n    ivec2 c1 = ivec2(floor((q + PG_REACH) / PG_CELL));\n",
         "    ivec2 c0 = ivec2(floor((q - rv) / PG_CELL));\n    ivec2 c1 = ivec2(floor((q + rv) / PG_CELL));\n"),
        ("            if (dot(nq, nq) >= PG_REACH * PG_REACH) continue;\n",
         "            if (dot(nq, nq) >= rv * rv) continue;\n"),
        ("                    if (dot(d, d) >= PG_REACH * PG_REACH) continue;\n                    uint hm = pgHits(d);\n",
         "                    float rho = pgRadius(h2);\n"
         "                    float ri = PG_REACH - 1.0 + rho;\n"
         "                    if (dot(d, d) >= ri * ri) continue;\n"
         "                    uint hm = pgHits(d, rho * rho);\n"),
    )
    for old, new in pairs:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    return src.replace("%(Z)s", _glsl_float(Z_CLIP))


GLSL_V = _glsl_variable()


def _final_pgv() -> str:
    assert FINAL_PG.count(GLSL) == 1
    return FINAL_PG.replace(GLSL, GLSL_V)


_PROGRAMS: dict[str, str] = {}


def program(name: str) -> str:
    """Fonte da variante `final_pgv` (raios variáveis) ou `final_pgv_lx` (com véu, pré-exposição e scanner)."""
    if name not in _PROGRAMS:
        if name == "final_pgv":
            _PROGRAMS[name] = _final_pgv()
        else:
            assert name == "final_pgv_lx", name
            from . import labx
            _PROGRAMS[name] = labx.patch_glsl(program("final_pgv"))
    return _PROGRAMS[name]
