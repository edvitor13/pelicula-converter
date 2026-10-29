"""Grão e textura da 1.6 (ARQUITETURA §30): os modelos novos que `look.build_plan` chama por ganchos pequenos.

Cada recurso começa num padrão neutro: com o ajuste no padrão, a função devolve "nada a fazer" e o plano sai
bit a bit o de antes (`tests/test_grao.py` confere com a referência gravada pela BASE). Distâncias em px@1080.

- **Maciez pelo grão** (`grao_maciez`, M2): `soft_sigma` amacia a imagem até a nitidez do próprio grão.
"""

from __future__ import annotations

import math

# ------------------------------------------------------------------ M2: maciez pelo grão
# O ruído do grão é uma grade de gaussianas (uma por célula de `s` px) interpolada por B-spline cúbica
# (`texBicubic` no FINAL; `pc_noise` no plugin). A B-spline cúbica é a convolução de quatro caixas de uma
# célula, com variância 4 · s²/12 = s²/3 por eixo: o detalhe mais fino do grão tem o envelope de uma gaussiana
# de sigma s/√3. Com 100%, a imagem recebe essa mesma gaussiana (somada em quadratura às outras maciezes).
GRAIN_SOFT_K = 1.0 / math.sqrt(3.0)


def grain_size_1080(v: dict, gauge: dict) -> float:
    """Tamanho natural do grão (a célula do ruído) em px@1080, como no bloco do grão de `build_plan`."""
    iso_size = (float(v["iso"]) / 250.0) ** 0.18
    return 0.8 * float(v["grao_tamanho"]) * gauge["grain_size"] * iso_size


def soft_sigma(v: dict, gauge: dict) -> float:
    """Sigma (px@1080) da "Maciez pelo grão"; 0 com o ajuste em 0% ou sem grão."""
    amt = float(v.get("grao_maciez", 0.0))
    if amt <= 0.0 or not v.get("grao_on") or float(v.get("grao_forca", 0.0)) <= 0.0:
        return 0.0
    return GRAIN_SOFT_K * grain_size_1080(v, gauge) * amt
