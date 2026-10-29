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
quase constante pela exposição; vale a média dos pontos lidos.
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


def constants() -> dict:
    neg, prt = load("H-1-5207"), load("H-1-2383")
    ref_n, dn = layer_dsigma_um(neg["mtf"])
    ref_p, dp = layer_dsigma_um(prt["mtf"])
    return {"MTF_NEG_REF": ref_n, "MTF_NEG_DSIGMA_UM": tuple(round(dn[c], 3) for c in LAYERS),
            "MTF_PRINT_REF": ref_p, "MTF_PRINT_DSIGMA_UM": tuple(round(dp[c], 3) for c in LAYERS),
            "NEG_SIGMA_D": tuple(round(v, 5) for v in mean_sigma_d(neg["granularidade"]).values())}


def main() -> int:
    for k, v in constants().items():
        print(f"{k} = {v!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
