"""Laboratório da 1.6: tipo de scanner do "Sem cópia" (M6), película vencida e pré-exposição (flashing).

Os três mexem dentro do caminho negativo → cópia (`look.LabPath`), então valem na prévia, na exportação, no LUT
exportado e no nó Laboratório do plugin do DaVinci. Desligados (o padrão) nada muda: o plano não ganha nenhum
uniform novo e o Engine usa o FINAL/BAKE de sempre. Ligados, o plano traz `u_lx_on` e o Engine usa a variante
FINAL_LX/BAKE_LX (o mesmo texto com `labPathX` no lugar de `labPath` nas chamadas do `labPipe`), compilada só
quando usada; todos os `u_lx_*` vão juntos em todo plano que a usa, então nenhum fica com valor velho.

**Exposição somada.** Véu da película vencida e pré-exposição são luz (ou o equivalente químico dela) que chega
a todo o quadro antes da imagem: na exposição de cada camada, `e = sens · luz + soma`, com
`soma = sens · flash + véu`. Levanta as sombras do negativo (a densidade mínima sobe) e quase não mexe nas altas
luzes; o cinza continua calibrado (a calibração das luzes da copiadora usa a mesma soma).

**Película vencida** (`lab_vencida`, anos guardada em temperatura ambiente; 0 = fresca): regra prática dos
laboratórios, não uma medida — por década, perde ~1/2 stop de sensibilidade (`AGE_SPEED` log E: pé e ombro andam
para a direita), 10% do contraste (`AGE_GAMMA`) e ganha um véu de 2% da exposição do cinza (`AGE_FOG`, medido na
sensibilidade da própria película vencida, então a densidade mínima só sobe com os anos). A camada mais rápida
(a do azul, a de grão maior: `grao.NEG_SIGMA_D`) envelhece mais (`AGE_W`; num preto e branco as três igual): o
véu na camada do azul é mais amarelo no negativo, menos amarelo na cópia, e as sombras ficam **azuladas** e
lavadas; o azul perde mais contraste e as altas luzes ficam **amareladas**. Determinístico (só depende dos anos).

**Pré-exposição** (`lab_pre_exposicao`): uma exposição uniforme de `0,18 · 2^(−stops)` (stops abaixo do cinza),
na cor escolhida (normalizada na luminância), antes da curva do negativo.

**Scanner de luz branca** (M6, `lab_scanner = "branca"`, só no Sem cópia): o scanner RGB estreito (o de sempre)
lê cada camada sozinha; o de luz branca vê em cada canal a mistura das transmitâncias das camadas,
`T_c = Σ_k M_ck · 10^(−(d_k + Dmin_k))`, com `M` tirado das curvas de densidade espectral do 250D (datasheet
H-1-5207) vistas pelo observador CIE 1931 em Rec.709 sob luz de 5500 K (`tools/ajustar_lab.py`, `scan_mix`) e
`Dmin` = base + máscara lidas do mesmo datasheet. A inversão usa, por canal, o gama efetivo no cinza
(`Σ_k J_ck · gama_k`, `J` = peso de cada camada no cinza), então o cinza sai igual ao do RGB estreito e as cores
perdem saturação (as camadas se misturam).
"""

from __future__ import annotations

import math

import numpy as np

LOG10_2 = math.log10(2.0)

# ------------------------------------------------------------------ constantes
# tools/ajustar_lab.py: scan_luz_branca (linhas = canais R, G, B; colunas = camadas C, M, Y; somam 1) e scan_dmin.
SCAN_WHITE = ((0.644, 0.294, 0.062), (0.115, 0.765, 0.12), (0.066, 0.07, 0.864))
SCAN_DMIN = (0.175, 0.574, 0.834)
AGE_W = (0.484, 0.562, 1.0)   # grao.NEG_SIGMA_D / máximo: a camada mais rápida (azul) envelhece mais
AGE_SPEED = 0.15              # log E por década (≈ 1/2 stop)
AGE_GAMMA = 0.10              # perda de contraste por década (gama / (1 + 0,10 · décadas))
AGE_FOG = 0.02                # véu por década, em fração da exposição do cinza
FLASH_COLORS = {              # cor da pré-exposição (antes de normalizar na luminância)
    "neutra": (1.0, 1.0, 1.0),
    "ambar": (1.0, 0.72, 0.38),
    "azul": (0.62, 0.82, 1.0),
    "verde": (0.55, 1.0, 0.55),
    "magenta": (1.0, 0.55, 1.0),
}
_W709 = np.array([0.2126, 0.7152, 0.0722])


def flash_rgb(cor: str) -> np.ndarray:
    c = np.asarray(FLASH_COLORS.get(cor, FLASH_COLORS["neutra"]), dtype=np.float64)
    return c / float(c @ _W709)


def flash_light(v: dict) -> tuple:
    """Luz da pré-exposição (Rec.709 linear, somada à cena antes da sensibilidade) ou zeros, desligada."""
    if not v.get("lab_pre_exposicao"):
        return (0.0, 0.0, 0.0)
    amt = 0.18 * 2.0 ** (-float(v["lab_pre_exposicao_stops"]))
    return tuple(round(float(x), 6) for x in flash_rgb(v["lab_pre_exposicao_cor"]) * amt)


def white_scan(v: dict) -> bool:
    return v.get("lab_scanner", "rgb") == "branca"


def age_weights(sens) -> np.ndarray:
    """Quanto cada camada envelhece: `AGE_W`, ou a média num filme preto e branco (as três "camadas" iguais)."""
    m = np.asarray(sens, dtype=np.float64)
    if (m[0] == m[1]).all() and (m[1] == m[2]).all():
        return np.full(3, (AGE_W[0] + AGE_W[1] + AGE_W[2]) / 3.0)
    return np.asarray(AGE_W, dtype=np.float64)


def aged(gamma, toe, shoulder, years: float, sens):
    """Curvas do negativo depois de `years` anos (gama, pé, ombro por camada)."""
    a = float(years) / 10.0
    w = age_weights(sens)
    return (np.asarray(gamma) / (1.0 + AGE_GAMMA * a * w), np.asarray(toe) + AGE_SPEED * a * w,
            np.asarray(shoulder) + AGE_SPEED * a * w)


def added_exposure(sens, flash, years: float) -> np.ndarray:
    """Exposição somada a cada camada: pré-exposição vista pela sensibilidade + véu da idade."""
    add = np.asarray(sens, dtype=np.float64) @ np.asarray(flash, dtype=np.float64)
    aw = (float(years) / 10.0) * age_weights(sens)
    # o véu é medido na sensibilidade da própria película vencida (anda junto com o pé): a densidade mínima só sobe
    return add + 0.18 * AGE_FOG * aw * 10.0 ** (AGE_SPEED * aw)


def white_scan_stops(dn, mid, pg, off) -> np.ndarray:
    """Stops da inversão do scanner de luz branca (mesma conta de `lxWhiteScan` e `pc_lx_white`)."""
    M = np.asarray(SCAN_WHITE)
    dmin = np.asarray(SCAN_DMIN)
    tm = 10.0 ** (-(np.asarray(mid) + dmin))
    Tm = tm @ M.T
    T = (10.0 ** (-(np.asarray(dn) + dmin))) @ M.T
    geff = ((tm * np.asarray(pg)) @ M.T) / Tm
    dc = -np.log10(np.maximum(T, 1e-30))
    dmc = -np.log10(Tm)
    return (dc - dmc) / (geff * LOG10_2) - np.asarray(off) / LOG10_2


# ------------------------------------------------------------------ plano
def uniforms(U: dict, a, b) -> None:
    """Uniforms da variante (só quando algum recurso está ligado; `a`, `b` são os `look.LabPath`)."""
    on = a.white or any(a.add) or (b is not None and any(b.add))
    if not on:
        return
    U["u_lx_on"] = 1
    U["u_lx_add_a"] = tuple(float(x) for x in a.add)
    U["u_lx_add_b"] = tuple(float(x) for x in b.add) if b is not None else (0.0, 0.0, 0.0)
    U["u_lx_white"] = 1 if a.white else 0


# ------------------------------------------------------------------ GLSL (variante do FINAL e do BAKE)
def _vec3(v) -> str:
    return "vec3(" + ", ".join(repr(float(x)) for x in v) + ")"


def _mat3_rows(m) -> str:
    m = np.asarray(m, dtype=np.float64)
    return "mat3(" + ", ".join(repr(float(m[r, c])) for c in range(3) for r in range(3)) + ")"  # coluna a coluna


GLSL_LX = f"""
// ---------------------------------------------------------------- 1.6: laboratório (labx.py)
// Exposição somada (véu da película vencida + pré-exposição) e scanner de luz branca no Sem cópia.
uniform int u_lx_on;
uniform vec3 u_lx_add_a;
uniform vec3 u_lx_add_b;
uniform int u_lx_white;
const mat3 LX_SCAN_M = {_mat3_rows(SCAN_WHITE)};
const vec3 LX_SCAN_DMIN = {_vec3(SCAN_DMIN)};

// Scanner de luz branca: cada canal vê a mistura das transmitâncias das camadas; inverte com o gama efetivo no cinza.
vec3 lxWhiteScan(vec3 dn, vec3 nmid, vec3 pg, vec3 off) {{
    vec3 tm = exp2(-(nmid + LX_SCAN_DMIN) * 3.32192809);
    vec3 Tm = LX_SCAN_M * tm;
    vec3 T = LX_SCAN_M * exp2(-(dn + LX_SCAN_DMIN) * 3.32192809);
    vec3 geff = (LX_SCAN_M * (tm * pg)) / Tm;
    vec3 dc = -log2(max(T, vec3(1e-30))) * 0.30102999566;
    vec3 dmc = -log2(Tm) * 0.30102999566;
    return (dc - dmc) / (geff * 0.30103) - off / 0.30103;
}}
"""

_LAB_PATH_HEAD = "vec3 labPath(vec3 lin, mat3 sens,"
_LAB_PIPE_HEAD = "vec3 labPipe(vec3 lin) {"
_GLSL_FIX = (
    ("vec3 labPath(vec3 lin, mat3 sens, vec3 ng, vec3 nt, vec3 ns, float nw, mat3 ii, vec3 pg, vec3 pt, vec3 ps,\n"
     "             float pw, mat3 dye, vec3 off, vec3 key, vec3 nmid, int scan) {",
     "vec3 labPathX(vec3 lin, mat3 sens, vec3 ng, vec3 nt, vec3 ns, float nw, mat3 ii, vec3 pg, vec3 pt, vec3 ps,\n"
     "              float pw, mat3 dye, vec3 off, vec3 key, vec3 nmid, int scan, vec3 add, int white) {"),
    ("    vec3 e = max(sens * lin, vec3(1e-7));",
     "    vec3 e = max(sens * lin + add, vec3(1e-7));"),
    ("        vec3 st = (dn - nmid) / (pg * 0.30103) - off / 0.30103;\n",
     "        vec3 st = (dn - nmid) / (pg * 0.30103) - off / 0.30103;\n"
     "        if (white == 1) st = lxWhiteScan(dn, nmid, pg, off);\n"),
)
_PIPE_FIX = (
    ("    vec3 a = labPath(lin, u_la_sens,", "    vec3 a = labPathX(lin, u_la_sens,"),
    ("u_la_pw, u_la_dye, u_la_off, u_la_key, u_la_mid, u_la_scan);",
     "u_la_pw, u_la_dye, u_la_off, u_la_key, u_la_mid, u_la_scan, u_lx_add_a, u_lx_white);"),
    ("    vec3 b = labPath(lin, u_lb_sens,", "    vec3 b = labPathX(lin, u_lb_sens,"),
    ("u_lb_pw, u_lb_dye, u_lb_off, u_lb_key, u_lb_mid, u_lb_scan);",
     "u_lb_pw, u_lb_dye, u_lb_off, u_lb_key, u_lb_mid, u_lb_scan, u_lx_add_b, 0);"),
)


def _replace_once(src: str, a: str, b: str) -> str:
    assert src.count(a) == 1, a
    return src.replace(a, b)


def _function(src: str, head: str) -> str:
    """Texto de uma função GLSL (do cabeçalho até a chave que fecha no começo da linha)."""
    i = src.index(head)
    j = src.index("\n}\n", i)
    return src[i:j + 3]


def patch_glsl(src: str) -> str:
    """FINAL ou BAKE com o `labPipe` chamando `labPathX` (cópia de `labPath` com as extensões)."""
    fn = _function(src, _LAB_PATH_HEAD)
    for a, b in _GLSL_FIX:
        fn = _replace_once(fn, a, b)
    pipe = _function(src, _LAB_PIPE_HEAD)
    new_pipe = pipe
    for a, b in _PIPE_FIX:
        new_pipe = _replace_once(new_pipe, a, b)
    return _replace_once(src, pipe, GLSL_LX + "\n" + fn + "\n" + new_pipe)


_PROGRAMS: dict[str, str] = {}


def program(name: str) -> str:
    """Fonte da variante `final_lx`, `bake_lx` ou `final_pg_lx` (com o grão físico, grao_fisico.py; texto gerado uma
    vez)."""
    if name not in _PROGRAMS:
        from . import shaders
        if name == "final_pg_lx":
            from . import grao_fisico
            src = grao_fisico.FINAL_PG
        else:
            src = {"final_lx": shaders.FINAL, "bake_lx": shaders.BAKE}[name]
        _PROGRAMS[name] = patch_glsl(src)
    return _PROGRAMS[name]


# ------------------------------------------------------------------ plugin do DaVinci (nó Laboratório e OFX)
def tables(define, table, dialect: str) -> str:
    """Constantes do kernel: matriz e Dmin do scanner, idade e cores da pré-exposição (na ordem de params)."""
    from . import params
    out = table(dialect, "PC_LX_SCAN", [x for row in SCAN_WHITE for x in row])
    out += table(dialect, "PC_LX_DMIN", list(SCAN_DMIN))
    out += table(dialect, "PC_LX_AGEW", list(AGE_W))
    out += define("PC_LX_AGE_SPEED", AGE_SPEED) + define("PC_LX_AGE_GAMMA", AGE_GAMMA)
    out += define("PC_LX_AGE_FOG", AGE_FOG)
    out += table(dialect, "PC_LX_FLASH", [float(x) for k, _l in params.CORES_PRE_EXPOSICAO for x in flash_rgb(k)])
    return out


K_LABX_HELPERS = r"""
// ---------------------------------------------------------------- 1.6: laboratorio (labx.py)
// scanner de luz branca: cada canal ve a mistura das transmitancias das camadas
PC_DEVICE float3 pc_lx_white(float3 dn, float3 dmid, float3 g, float3 lights) {
    float3 m0 = make_float3(PC_LX_SCAN[0], PC_LX_SCAN[1], PC_LX_SCAN[2]);
    float3 m1 = make_float3(PC_LX_SCAN[3], PC_LX_SCAN[4], PC_LX_SCAN[5]);
    float3 m2 = make_float3(PC_LX_SCAN[6], PC_LX_SCAN[7], PC_LX_SCAN[8]);
    float3 dm = make_float3(PC_LX_DMIN[0], PC_LX_DMIN[1], PC_LX_DMIN[2]);
    float3 tm = make_float3(_exp2f(-(dmid.x + dm.x) * 3.32192809f), _exp2f(-(dmid.y + dm.y) * 3.32192809f),
                            _exp2f(-(dmid.z + dm.z) * 3.32192809f));
    float3 t = make_float3(_exp2f(-(dn.x + dm.x) * 3.32192809f), _exp2f(-(dn.y + dm.y) * 3.32192809f),
                           _exp2f(-(dn.z + dm.z) * 3.32192809f));
    float3 Tm = pc_mat3(m0, m1, m2, tm);
    float3 T = pc_mat3(m0, m1, m2, t);
    float3 ge = pc_mat3(m0, m1, m2, make_float3(tm.x * g.x, tm.y * g.y, tm.z * g.z));
    return make_float3((pc_log10(Tm.x) - pc_log10(T.x)) / (ge.x / Tm.x * 0.30103f) - lights.x / 0.30103f,
                       (pc_log10(Tm.y) - pc_log10(T.y)) / (ge.y / Tm.y * 0.30103f) - lights.y / 0.30103f,
                       (pc_log10(Tm.z) - pc_log10(T.z)) / (ge.z / Tm.z * 0.30103f) - lights.z / 0.30103f);
}
"""

_K_HEAD = "PC_DEVICE float3 pc_lab_path(float3 lin,"
_K_FIX = (
    ("PC_DEVICE float3 pc_lab_path(float3 lin, float3 s0,",
     "PC_DEVICE float3 pc_lab_path_x(float age, float3 fl, int scm, float3 lin, float3 s0,"),
    ("    float3 ng = ng0 * (1.0f + 0.12f * push);\n",
     "    // 1.6 (labx): pelicula vencida = menos contraste e menos sensibilidade (mais na camada do azul) + veu;\n"
     "    // pre-exposicao vista pela sensibilidade. Desligados, nada abaixo muda um bit.\n"
     "    float3 add = pc_mat3(s0, s1, s2, fl);\n"
     "    if (age > 0.0f) {\n"
     "        float3 aw = make_float3(PC_LX_AGEW[0], PC_LX_AGEW[1], PC_LX_AGEW[2]) * (age / 10.0f);\n"
     "        if (s0.x == s1.x && s0.y == s1.y && s0.z == s1.z && s1.x == s2.x && s1.y == s2.y && s1.z == s2.z)\n"
     "            aw = pc_s3((aw.x + aw.y + aw.z) / 3.0f);  // preto e branco: o veu e cinza\n"
     "        ng0 = make_float3(ng0.x / (1.0f + PC_LX_AGE_GAMMA * aw.x), ng0.y / (1.0f + PC_LX_AGE_GAMMA * aw.y),\n"
     "                          ng0.z / (1.0f + PC_LX_AGE_GAMMA * aw.z));\n"
     "        nt0 = nt0 + aw * PC_LX_AGE_SPEED;\n"
     "        ns = ns + aw * PC_LX_AGE_SPEED;\n"
     "        add = add + make_float3(aw.x * _exp2f(PC_LX_AGE_SPEED * 3.32192809f * aw.x),\n"
     "                                aw.y * _exp2f(PC_LX_AGE_SPEED * 3.32192809f * aw.y),\n"
     "                                aw.z * _exp2f(PC_LX_AGE_SPEED * 3.32192809f * aw.z)) * (0.18f * PC_LX_AGE_FOG);\n"
     "    }\n"
     "    int lx_add = (add.x != 0.0f || add.y != 0.0f || add.z != 0.0f) ? 1 : 0;\n"
     "    float3 ng = ng0 * (1.0f + 0.12f * push);\n"),
    ("    float3 dmid = pc_mat3(i0, i1, i2, pc_lab_curve(pc_s3(0.0f), ng, nt, ns, nw));\n",
     "    float3 dmid = pc_mat3(i0, i1, i2, pc_lab_curve(pc_s3(0.0f), ng, nt, ns, nw));\n"
     "    if (lx_add == 1) {\n"
     "        float3 em = pc_mat3(s0, s1, s2, pc_s3(0.18f)) + add;\n"
     "        dmid = pc_mat3(i0, i1, i2, pc_lab_curve(make_float3(pc_log10(em.x / 0.18f), pc_log10(em.y / 0.18f),\n"
     "                                                            pc_log10(em.z / 0.18f)), ng, nt, ns, nw));\n"
     "    }\n"),
    ("    float3 e = pc_max3(pc_mat3(s0, s1, s2, lin), 1e-7f);\n",
     "    float3 e = pc_max3(pc_mat3(s0, s1, s2, lin), 1e-7f);\n"
     "    if (lx_add == 1) e = pc_max3(pc_mat3(s0, s1, s2, lin) + add, 1e-7f);\n"),
    ("                                (dn.z - dmid.z) / (ng0.z * 0.30103f) - lights.z / 0.30103f);\n",
     "                                (dn.z - dmid.z) / (ng0.z * 0.30103f) - lights.z / 0.30103f);\n"
     "        if (scm == 1) st = pc_lx_white(dn, dmid, ng0, lights);\n"),
)
_B_FIX = (
    ("        float3 gn = pc_s3(0.0f);\n",
     "        float3 gn = pc_s3(0.0f);\n"
     "        // 1.6 (labx): pelicula vencida, pre-exposicao e scanner de luz branca\n"
     "        float lx_age = v_lab_vencida;\n"
     "        float3 lx_fl = pc_s3(0.0f);\n"
     "        if (v_lab_pre_exposicao == 1) {\n"
     "            int fc = v_lab_pre_exposicao_cor * 3;\n"
     "            lx_fl = make_float3(PC_LX_FLASH[fc], PC_LX_FLASH[fc + 1], PC_LX_FLASH[fc + 2])\n"
     "                    * (0.18f * _exp2f(-v_lab_pre_exposicao_stops));\n"
     "        }\n"
     "        int lx_sc = v_lab_scanner;\n"),
    ("        float3 la = pc_lab_path(lin,", "        float3 la = pc_lab_path_x(lx_age, lx_fl, lx_sc, lin,"),
    ("            float3 lb = pc_lab_path(lin,", "            float3 lb = pc_lab_path_x(lx_age, lx_fl, 0, lin,"),
)


def kernel(k_lab: str) -> str:
    """`pc_lab_path_x`: cópia de `pc_lab_path` (de K_LAB) com idade, pré-exposição e scanner."""
    i = k_lab.index(_K_HEAD)
    j = k_lab.index("\n}\n", i)
    fn = k_lab[i:j + 3]
    for a, b in _K_FIX:
        fn = _replace_once(fn, a, b)
    return K_LABX_HELPERS + fn


def body(b_lab: str) -> str:
    for a, b in _B_FIX:
        b_lab = _replace_once(b_lab, a, b)
    return b_lab


CONTROLS = (("lab_scanner", "Lab - Tipo de scanner"), ("lab_vencida", "Lab - Pelicula vencida anos"),
            ("lab_pre_exposicao", "Lab - Pre-exposicao flashing"),
            ("lab_pre_exposicao_stops", "Lab - Pre-exposicao stops abaixo do cinza"),
            ("lab_pre_exposicao_cor", "Lab - Cor da pre-exposicao"))
