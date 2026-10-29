"""Ajusta as constantes do grão e da textura da 1.6 (`pelicula/grao.py`) aos pontos lidos dos datasheets.

Os pontos ficam em `pelicula/data/datasheets/<publicação>.json` (com a fonte: publicação, revisão, página,
figura, SHA-256 do PDF lido e o método da leitura). Este script só usa numpy e roda offline; o app usa as
constantes já calculadas, e `tests/test_grao_efeitos.py` confere que elas são as deste ajuste.

    python tools/ajustar_grao.py        # mostra as constantes

**Nitidez por camada (M7).** Para cada documento, a camada mais nítida é a referência e cada outra camada
ganha a gaussiana que, somada em quadratura, leva a resposta da referência à dela:
`MTF_c(f) / MTF_ref(f) ≈ exp(−2π² · Δσ_c² · f²)`. Cada ponto entre `F_MIN` e `F_MAX` ciclos/mm dá um Δσ²
(`−ln(razão) / (2π² f²)`) e vale a média deles: as curvas medidas caem mais devagar que uma gaussiana nas
frequências altas, e a média acerta a resposta nas frequências do meio (as que um quadro de 1080 a 2160 linhas
mostra numa película de 35 mm). O resultado é em micrômetros na película.

**Grão no negativo (M3).** A granularidade rms difusa (sigma D, abertura de 48 µm) de cada camada do negativo é
quase constante pela exposição; vale a média dos pontos lidos. Para levar o sigma D da abertura ao pixel, o
sigma da média do campo do grão do app (grade de gaussianas interpolada por B-spline cúbica, variância 1 por
pixel) numa abertura circular sai da integral exata `var = ∫∫ C(r) · K(r) d²r`, com `C` a autocovariância do
campo (o produto, em x e em y, da B-spline cúbica correlacionada consigo mesma, normalizada para C(0) = 1) e `K`
a das aberturas (área comum de dois círculos / área²), na referência: célula de 0,8 px@1080 e 48 µm no quadro de
24,9 mm do 35 mm.

**Grão físico (M1, `pelicula/grao_fisico.py`).** No modelo booleano (discos opacos de raio r, centros de Poisson com
`λ·πr² = D·ln 10`: Nutting 1913, Newson et al. 2017) a covariância da cobertura é `(1 − u)² · (e^(λ·γ(h)) − 1)`, com
`γ(h)` a área comum de dois discos à distância h. O sigma da transmitância média numa abertura circular de 48 µm sai
da integral exata dessa covariância com a das aberturas (área comum / área²) e a do spot de pontos fixos do pixel
(`grao_fisico.offsets`), na referência (35 mm, ISO 250, Tamanho 1: r = R_K · 0,8 px@1080) e na densidade de cada
camada no cinza médio da Vision3 250D do Laboratório (`look.lab_paths`). Só a fração `a` da transmitância vê o grão
resolvido (`T' = (1 − a)·T + a·T̂`), então o sigma D da abertura é `a · σ(T̂_A) / (T · ln 10)` e
`KAPPA = NEG_SIGMA_D · ln 10 / √(∫∫ (e^(λγ) − 1) · K)`. O raio `R_K` (em tamanhos do grão) é o que dá à cobertura
vista pelo spot o mesmo comprimento de correlação (meia altura ao longo de x) do grão de sempre na densidade de
referência do verde: o mesmo tamanho visível, outra estrutura.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "pelicula" / "data" / "datasheets"
F_MIN, F_MAX = 20.0, 62.0   # ciclos/mm: abaixo, o efeito de adjacência (> 100%) domina; acima, a cauda
LAYERS = ("R", "G", "B")
APERTURE_MM, REF_FRAME_MM, REF_WIDTH_PX, REF_GRAIN_PX = 0.048, 24.9, 1920.0, 0.8


def load(pub: str) -> dict:
    return json.loads((DATA / f"{pub}.json").read_text(encoding="utf-8"))


def layer_dsigma_um(mtf: dict) -> tuple[str, dict[str, float]]:
    """(camada de referência, {camada: Δσ em µm}) de uma tabela de MTF (`mtf` de um documento)."""
    f = np.asarray(mtf["ciclos_mm"], np.float64)
    sel = (f >= F_MIN) & (f <= F_MAX)
    resp = {c: np.asarray(mtf[c], np.float64)[sel] for c in LAYERS}
    f = f[sel]
    ref = max(LAYERS, key=lambda c: float(np.mean(np.log(resp[c]))))
    out = {}
    for c in LAYERS:
        r = np.log(resp[c] / resp[ref])
        s2 = float(np.mean(-r / (2.0 * math.pi ** 2 * f ** 2)))  # mm²
        out[c] = math.sqrt(max(s2, 0.0)) * 1000.0
    return ref, out


def mean_sigma_d(gran: dict) -> dict[str, float]:
    return {c: float(np.mean([x for x in gran[c] if x is not None])) for c in LAYERS}


def bspline3(u: np.ndarray) -> np.ndarray:
    u = np.abs(u)
    return np.where(u < 1, (4 - 6 * u ** 2 + 3 * u ** 3) / 6, np.where(u < 2, (2 - u) ** 3 / 6, 0.0))


def aperture_sigma(d_over_s: float, step: float = 1 / 200, h: float = 1 / 50) -> float:
    """Sigma da média do campo do grão (variância 1 por pixel) numa abertura circular de diâmetro `d_over_s`
    células."""
    u = np.arange(-2, 2 + step / 2, step)
    b = bspline3(u)
    b7 = np.convolve(b, b) * step                    # (β⋆β)(r), r de −4 a 4 células
    r7 = np.arange(len(b7)) * step - 4.0
    c0 = float(np.interp(0.0, r7, b7))
    d = float(d_over_s)
    ext = min(d, 4.0)
    x = np.arange(-ext, ext + h / 2, h)
    cx = np.interp(x, r7, b7, left=0.0, right=0.0) / c0
    dist = np.hypot(*np.meshgrid(x, x))
    rad = d / 2
    q = np.clip(dist / d, 0.0, 1.0)
    overlap = np.where(dist < d, 2 * rad * rad * np.arccos(q) - (dist / 2) * np.sqrt(np.maximum(d * d - dist ** 2, 0)),
                       0.0)
    k = overlap / (math.pi * rad * rad) ** 2
    return math.sqrt(float(np.sum(cx[None, :] * cx[:, None] * k)) * h * h)


def physical_aperture_rel_sigma(density: float, aperture_r: float, step: float = 0.01) -> float:
    """σ(T̂_A) / T do modelo booleano (r = 1) numa abertura circular de diâmetro `aperture_r` raios, vista pelo spot
    de pontos fixos do pixel: (1/N²) Σ_kl ∫∫ (e^(λγ(h)) − 1) · K_A(h + o_k − o_l) d²h."""
    sys.path.insert(0, str(ROOT))
    from pelicula import grao_fisico as gf
    o = gf.offsets()
    x = np.arange(-2.0, 2.0 + step / 2, step)
    X, Y = np.meshgrid(x, x)
    c = gf.covariance(np.hypot(X, Y), density) / (10.0 ** -density) ** 2
    rad = aperture_r / 2.0

    def k_ap(dist):
        q = np.clip(dist / aperture_r, 0.0, 1.0)
        ov = np.where(dist < aperture_r, 2 * rad * rad * np.arccos(q)
                      - (dist / 2) * np.sqrt(np.maximum(aperture_r ** 2 - dist ** 2, 0.0)), 0.0)
        return ov / (math.pi * rad * rad) ** 2

    tot = 0.0
    for a in o:
        for b in o:
            dx, dy = a - b
            tot += float(np.sum(c * k_ap(np.hypot(X + dx, Y + dy)))) * step * step
    return math.sqrt(tot / len(o) ** 2)


def half_correlation_noise() -> float:
    """Distância (em células) em que a autocorrelação do campo do grão de sempre ao longo de x cai a 1/2 (a B-spline
    cúbica correlacionada consigo mesma)."""
    step = 1 / 400
    u = np.arange(-2, 2 + step / 2, step)
    b7 = np.convolve(bspline3(u), bspline3(u)) * step
    r7 = np.arange(len(b7)) * step - 4.0
    pos = r7 >= 0
    c = b7[pos] / b7[pos][0]
    return float(np.interp(0.5, c[::-1], r7[pos][::-1]))


def half_correlation_physical(density: float) -> float:
    """O mesmo (em raios) para a cobertura do modelo booleano vista pelo spot do pixel, numa densidade."""
    sys.path.insert(0, str(ROOT))
    from pelicula import grao_fisico as gf
    o = gf.offsets()
    hs = np.linspace(0.0, 4.0, 1601)
    cov = np.array([gf.covariance(np.linalg.norm(o[:, None] + np.array([h, 0.0]) - o[None], axis=-1), density).mean()
                    for h in hs])
    c = cov / cov[0]
    return float(np.interp(0.5, c[::-1], hs[::-1]))


def reference_density() -> tuple[float, ...]:
    """Densidade de cada camada R, G, B no cinza médio da Vision3 250D do Laboratório (negativo + 2383)."""
    sys.path.insert(0, str(ROOT))
    from pelicula import look
    a, _b = look.lab_paths("vision3_250d", "2383", "normal", 0.0, 1.0, 0.3, 1.0)
    return tuple(float(x) for x in a.mid)


def physical_radius_k(ref: tuple[float, ...]) -> float:
    """R_K: o raio (em tamanhos do grão) que dá ao grão físico o comprimento de correlação do grão de sempre na
    densidade de referência do verde (o mesmo tamanho visível; muda a estrutura, não o tamanho)."""
    return half_correlation_noise() / half_correlation_physical(ref[1])


def physical_kappa(sigma_d: dict[str, float], r_k: float, ref: tuple[float, ...]) -> tuple[float, ...]:
    """KAPPA de cada camada R, G, B do grão físico (raio r_k · 0,8 px@1080 na referência)."""
    ap = APERTURE_MM * REF_WIDTH_PX / REF_FRAME_MM / (r_k * REF_GRAIN_PX)
    return tuple(sigma_d[c] * math.log(10.0) / physical_aperture_rel_sigma(d, ap) for c, d in zip(LAYERS, ref))


def constants() -> dict:
    neg, prt = load("H-1-5207"), load("H-1-2383")
    ref_n, dn = layer_dsigma_um(neg["mtf"])
    ref_p, dp = layer_dsigma_um(prt["mtf"])
    return {"MTF_NEG_REF": ref_n, "MTF_NEG_DSIGMA_UM": tuple(round(dn[c], 3) for c in LAYERS),
            "MTF_PRINT_REF": ref_p, "MTF_PRINT_DSIGMA_UM": tuple(round(dp[c], 3) for c in LAYERS),
            "NEG_SIGMA_D": tuple(round(v, 5) for v in mean_sigma_d(neg["granularidade"]).values()),
            "GRAN_APERTURE_SIGMA": round(aperture_sigma(APERTURE_MM * REF_WIDTH_PX / REF_FRAME_MM / REF_GRAIN_PX), 5),
            **_physical(neg)}


def _physical(neg: dict) -> dict:
    ref = reference_density()
    r_k = round(physical_radius_k(ref), 3)
    kap = physical_kappa({c: round(v, 5) for c, v in mean_sigma_d(neg["granularidade"]).items()}, r_k, ref)
    return {"R_K": r_k, "KAPPA": tuple(round(k, 5) for k in kap), "REF_DENSITY": tuple(round(d, 5) for d in ref)}


def main() -> int:
    for k, v in constants().items():
        print(f"{k} = {v!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
