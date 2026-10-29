"""Máscaras da 1.6: pele (cor) e degradê (posição), em GLSL para os shaders e em numpy para os testes e a interface.

As mesmas funções servem o look ("Cor por planos", `planes.py`) e os ajustes de clipe do modo Edição ("Pele
natural" e "Degradê", `editshaders.CLIP_CS`). Nada aqui usa Qt nem OpenGL; `GLSL` é texto incluído nos shaders e
`tests/test_masks.py` confere que o GLSL e o numpy dão o mesmo resultado na GPU.

**Pele** (`skin_mask`, GLSL `skinMask`): a cor é lida como vídeo (código de 0 a 1, Rec.709) e levada à luz com
gama 2,2 — no modo Edição é o próprio clipe; no look, a luz da cena passa antes pela curva neutra de exibição
(`stopsToDisp(linToStops(...))`, a mesma do look), então a máscara vê a pele como ela aparece. Da luz vem o OkLab
(Björn Ottosson, 2020, https://bottosson.github.io/posts/oklab/ — matrizes publicadas em domínio público/MIT) e
o OkLCh: matiz `h`, croma `C` e claridade `L`. A máscara é o produto de três janelas suaves (`smoothstep`):

- matiz perto do centro (`SKIN_HUE`, que o conta-gotas troca pela pele do quadro), com meia largura `SKIN_WIDTH`
  e borda `SKIN_EDGE`;
- "saturação" `C/L` (não muda com a exposição: o OkLab é a raiz cúbica da luz) entre `SKIN_SAT[0:2]` (tira os
  cinzas) e `SKIN_SAT[2:4]` (tira laranjas fortes, madeiras avermelhadas e tijolo);
- claridade acima de `SKIN_L` (só o preto quase puro sai: pele muito escura entra).

Os padrões foram acertados com a escala Monk Skin Tone (Ellis Monk/Google, CC BY 4.0, https://skintone.google;
os 10 tons em `tests/test_masks.py`): todos entram, no quadro e 1 stop abaixo. Uma máscara só de cor não separa a
pele de uma madeira clara ou areia da mesma cor; para isso servem o conta-gotas e a largura.

**Degradê** (`gradient_mask`, GLSL `gradMask`): posição em px@1080 a partir do centro do quadro (y para baixo,
`frame_points`). Linear: uma linha pelo centro (`cx`, `cy`); o lado marcado (valor 1) é o da direção `angle`
(graus, 0° = para cima, 90° = para a direita, como numa bússola). Radial: 1 dentro do círculo de raio `radius`.
`soft` é a largura da transição (px@1080; 0 = borda seca). `invert` troca os lados.
"""

from __future__ import annotations

import math

import numpy as np

# OkLab: RGB linear (primárias Rec.709/sRGB) → LMS → raiz cúbica → Lab.
OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                  [0.2119034982, 0.6806995451, 0.1073969566],
                  [0.0883024619, 0.2817188376, 0.6299787005]])
OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                  [1.9779984951, -2.4285922050, 0.4505937099],
                  [0.0259040371, 0.7827717662, -0.8086757660]])
OK_M1_INV = np.linalg.inv(OK_M1)
OK_M2_INV = np.linalg.inv(OK_M2)

SKIN_HUE = 64.5        # centro do matiz OkLCh da pele (graus)
SKIN_WIDTH = 21.0      # meia largura da janela de matiz (graus)
SKIN_EDGE = 7.0        # borda suave da janela de matiz (graus)
SKIN_SAT = (0.004, 0.014, 0.17, 0.21)   # C/L: entra entre os dois primeiros, sai entre os dois últimos
SKIN_L = (0.10, 0.20)  # claridade OkLab: sai abaixo do primeiro, entra acima do segundo
SKIN_MIN_SAT = SKIN_SAT[1]  # o conta-gotas só acerta o matiz de uma cor com pelo menos esta saturação
# "Uniformizar" / "Pele natural" com força 1: o matiz chega `SKIN_EVEN[0]` mais perto do centro e a saturação C/L
# acima de `SKIN_EVEN[1]` (manchas avermelhadas, pele queimada de sol) cai pela fração `SKIN_EVEN[2]`. Só a cor:
# a claridade não muda, então a textura da pele fica como está.
SKIN_EVEN = (0.7, 0.12, 0.5)


def smoothstep(e0: float, e1: float, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ------------------------------------------------------------------ OkLab
def oklab(lin) -> np.ndarray:
    """Luz linear Rec.709 (… × 3) → OkLab (… × 3: L, a, b)."""
    lin = np.maximum(np.asarray(lin, dtype=np.float64), 0.0)
    return np.cbrt(lin @ OK_M1.T) @ OK_M2.T


def oklab_to_lin(lab) -> np.ndarray:
    lms = np.asarray(lab, dtype=np.float64) @ OK_M2_INV.T
    return (lms ** 3) @ OK_M1_INV.T


def oklch(lin) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(L, C, h em graus de −180 a 180) da luz linear."""
    lab = oklab(lin)
    return lab[..., 0], np.hypot(lab[..., 1], lab[..., 2]), np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))


def code_to_lin(code) -> np.ndarray:
    return np.maximum(np.asarray(code, dtype=np.float64), 0.0) ** 2.2


def hue_distance(h, center: float) -> np.ndarray:
    """Distância angular (graus, 0 a 180)."""
    return np.abs(np.mod(np.asarray(h, dtype=np.float64) - center + 540.0, 360.0) - 180.0)


# ------------------------------------------------------------------ pele
def skin_mask(code, hue: float = SKIN_HUE, width: float = SKIN_WIDTH) -> np.ndarray:
    """Quanto cada pixel é pele (0 a 1). `code`: vídeo Rec.709 de 0 a 1 (… × 3)."""
    L, C, h = oklch(code_to_lin(code))
    s = C / np.maximum(L, 1e-4)
    wh = 1.0 - smoothstep(width, width + SKIN_EDGE, hue_distance(h, hue))
    ws = smoothstep(SKIN_SAT[0], SKIN_SAT[1], s) * (1.0 - smoothstep(SKIN_SAT[2], SKIN_SAT[3], s))
    wl = smoothstep(SKIN_L[0], SKIN_L[1], L)
    return np.where(C < 1e-6, 0.0, wh * ws * wl)


def skin_hue_of(code) -> float | None:
    """Conta-gotas da pele: o matiz OkLCh (graus, 0 a 360) da cor (média de uma área, vídeo de 0 a 1), ou None se
    ela é quase cinza (sem matiz confiável)."""
    rgb = np.asarray(code, dtype=np.float64).reshape(-1, 3)
    lin = code_to_lin(rgb).mean(axis=0)
    L, C, h = oklch(lin)
    if float(L) <= 1e-4 or float(C) / float(L) < SKIN_MIN_SAT:
        return None
    return float(h) % 360.0


def lch_adjust(lab, hue_shift: float = 0.0, chroma: float = 1.0) -> np.ndarray:
    """Gira o matiz (graus) e multiplica o croma de cores OkLab (a claridade fica)."""
    lab = np.asarray(lab, dtype=np.float64)
    a = math.radians(hue_shift)
    ca, sa = math.cos(a) * chroma, math.sin(a) * chroma
    return np.stack([lab[..., 0], ca * lab[..., 1] - sa * lab[..., 2], sa * lab[..., 1] + ca * lab[..., 2]], axis=-1)


def skin_even(lab, hue: float = SKIN_HUE, k: float = 1.0) -> np.ndarray:
    """"Uniformizar": matiz para perto do centro e menos saturação nas partes muito saturadas (OkLab)."""
    lab = np.asarray(lab, dtype=np.float64)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    if k <= 0.0:
        return lab
    h = np.degrees(np.arctan2(b, a))
    dh = np.mod(h - hue + 540.0, 360.0) - 180.0
    h = np.radians(hue + dh * (1.0 - SKIN_EVEN[0] * k))
    Lp = np.maximum(L, 1e-4)
    s = C / Lp
    s = np.where(s > SKIN_EVEN[1], SKIN_EVEN[1] + (s - SKIN_EVEN[1]) * (1.0 - SKIN_EVEN[2] * k), s)
    C2 = s * Lp
    out = np.stack([L, C2 * np.cos(h), C2 * np.sin(h)], axis=-1)
    return np.where((C < 1e-6)[..., None], lab, out)


# ------------------------------------------------------------------ degradê
def frame_points(w: int, h: int) -> np.ndarray:
    """Centro de cada pixel em px@1080 a partir do centro do quadro (h × w × 2, y para baixo)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    u = (x + 0.5) / w - 0.5
    v = (y + 0.5) / h - 0.5
    return np.stack([u * (w / h) * 1080.0, v * 1080.0], axis=-1)


def gradient_mask(p, kind: str = "linear", cx: float = 0.0, cy: float = 0.0, angle: float = 0.0,
                  radius: float = 360.0, soft: float = 240.0, invert: bool = False) -> np.ndarray:
    """Degradê (0 a 1) nos pontos `p` (… × 2, px@1080 do centro do quadro, y para baixo)."""
    p = np.asarray(p, dtype=np.float64)
    q = p - np.array([cx, cy])
    if kind == "radial":
        d = radius - np.hypot(q[..., 0], q[..., 1])
    else:
        a = math.radians(angle)
        d = q[..., 0] * math.sin(a) - q[..., 1] * math.cos(a)
    m = smoothstep(-0.5 * soft, 0.5 * soft, d) if soft > 0.5 else (d >= 0.0).astype(np.float64)
    return 1.0 - m if invert else m


def gradient_uniform(kind: str, cx: float, cy: float, angle: float, radius: float, soft: float,
                     invert: bool) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Os dois vec4 de `gradMask`: (cx, cy, ângulo em radianos, suavidade) e (raio, radial, inverter, 0)."""
    return ((float(cx), float(cy), math.radians(float(angle)), float(soft)),
            (float(radius), 1.0 if kind == "radial" else 0.0, 1.0 if invert else 0.0, 0.0))


# ------------------------------------------------------------------ GLSL
def _mat(m: np.ndarray) -> str:
    cols = [", ".join(f"{float(m[r, c]):.10f}" for r in range(3)) for c in range(3)]  # GLSL: por coluna
    return "mat3(" + ", ".join(cols) + ")"


GLSL = f"""
// ---------------------------------------------------------------- máscaras da 1.6 (pelicula/masks.py)
const mat3 OK_M1 = {_mat(OK_M1)};
const mat3 OK_M2 = {_mat(OK_M2)};
const mat3 OK_M1_INV = {_mat(OK_M1_INV)};
const mat3 OK_M2_INV = {_mat(OK_M2_INV)};
const vec4 SKIN_SAT = vec4({SKIN_SAT[0]}, {SKIN_SAT[1]}, {SKIN_SAT[2]}, {SKIN_SAT[3]});
const vec2 SKIN_L = vec2({SKIN_L[0]}, {SKIN_L[1]});
const float SKIN_EDGE = {SKIN_EDGE};
const vec3 SKIN_EVEN = vec3({SKIN_EVEN[0]}, {SKIN_EVEN[1]}, {SKIN_EVEN[2]});

vec3 linToOklab(vec3 lin) {{
    vec3 lms = max(OK_M1 * max(lin, vec3(0.0)), vec3(0.0));
    return OK_M2 * pow(lms, vec3(1.0 / 3.0));
}}
vec3 oklabToLin(vec3 lab) {{
    vec3 lms = OK_M2_INV * lab;
    return OK_M1_INV * (lms * lms * lms);
}}
float hueDist(float h, float c) {{ return abs(mod(h - c + 540.0, 360.0) - 180.0); }}

// Pele: `code` em vídeo Rec.709 (0 a 1); `win` = (centro do matiz, meia largura) em graus OkLCh.
float skinMask(vec3 code, vec2 win) {{
    vec3 lab = linToOklab(pow(max(code, vec3(0.0)), vec3(2.2)));
    float C = length(lab.yz);
    if (C < 1e-6) return 0.0;
    float s = C / max(lab.x, 1e-4);
    float h = degrees(atan(lab.z, lab.y));
    float wh = 1.0 - smoothstep(win.y, win.y + SKIN_EDGE, hueDist(h, win.x));
    float ws = smoothstep(SKIN_SAT.x, SKIN_SAT.y, s) * (1.0 - smoothstep(SKIN_SAT.z, SKIN_SAT.w, s));
    float wl = smoothstep(SKIN_L.x, SKIN_L.y, lab.x);
    return wh * ws * wl;
}}

// Gira o matiz (graus) e multiplica o croma de uma cor OkLab.
vec3 lchAdjust(vec3 lab, float hueShift, float chroma) {{
    float a = radians(hueShift);
    float ca = cos(a) * chroma, sa = sin(a) * chroma;
    return vec3(lab.x, ca * lab.y - sa * lab.z, sa * lab.y + ca * lab.z);
}}

// "Uniformizar" a pele (OkLab): matiz para perto de `hue` e menos saturação acima de SKIN_EVEN.y; força `k`.
vec3 skinEven(vec3 lab, float hue, float k) {{
    float C = length(lab.yz);
    if (C < 1e-6 || k <= 0.0) return lab;
    float h = degrees(atan(lab.z, lab.y));
    float dh = mod(h - hue + 540.0, 360.0) - 180.0;
    h = radians(hue + dh * (1.0 - SKIN_EVEN.x * k));
    float Lp = max(lab.x, 1e-4);
    float s = C / Lp;
    if (s > SKIN_EVEN.y) s = SKIN_EVEN.y + (s - SKIN_EVEN.y) * (1.0 - SKIN_EVEN.z * k);
    return vec3(lab.x, s * Lp * cos(h), s * Lp * sin(h));
}}

// Degradê: `p` em px@1080 do centro do quadro (y para baixo); g = (cx, cy, ângulo rad, suavidade),
// k = (raio, radial, inverter, 0) — `masks.gradient_uniform`.
float gradMask(vec2 p, vec4 g, vec4 k) {{
    vec2 q = p - g.xy;
    float d = (k.y > 0.5) ? k.x - length(q) : q.x * sin(g.z) - q.y * cos(g.z);
    float m = (g.w > 0.5) ? smoothstep(-0.5 * g.w, 0.5 * g.w, d) : step(0.0, d);
    return (k.z > 0.5) ? 1.0 - m : m;
}}

// px@1080 de um uv (0 a 1) num quadro de proporção `aspect` (largura / altura).
vec2 framePoint(vec2 uv, float aspect) {{ return (uv - 0.5) * vec2(aspect, 1.0) * 1080.0; }}
"""
