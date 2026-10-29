"""Grão e textura da 1.6 (ARQUITETURA §30): os modelos novos que `look.build_plan` chama por ganchos pequenos.

Cada recurso começa num padrão neutro: com o ajuste no padrão, a função devolve "nada a fazer" e o plano sai
bit a bit o de antes (`tests/test_grao.py` confere com a referência gravada pela BASE). Distâncias em px@1080.

- **Maciez pelo grão** (`grao_maciez`, M2): `soft_sigma` amacia a imagem até a nitidez do próprio grão.
- **Diferença de nitidez entre camadas** (`mtf_camadas`, M7): `layer_softness` dá a cada canal a maciez da sua
  camada (MTF dos datasheets), com o mesmo desfoque da maciez (`shaders.BLUR3`, um sigma por canal).
- **Grão no negativo** (`lab_grao`, M3): `negative_grain` leva o mesmo campo do grão para a densidade de cada
  camada do negativo dentro do Laboratório (`labPath` no shader), em unidades de sigma D por camada.

Constantes calibradas por datasheets públicos (regra 8): os pontos lidos ficam em `pelicula/data/datasheets/`
com a fonte, e `tools/ajustar_grao.py` refaz o ajuste (o teste confere que as constantes daqui são as dele).
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


# ------------------------------------------------------------------ M7: nitidez por camada (MTF por canal)
# Gaussiana extra (µm na película, em quadratura) de cada camada R, G, B em relação à mais nítida, ajustada por
# `tools/ajustar_grao.py` aos pontos lidos de:
# - negativo: KODAK VISION3 250D 5207/7207, publicação H-1-5207, revisão 3-26, p. 3, "Modulation-Transfer
#   Function Curves" (5500 K, ECN-2, Status M): o azul é o mais nítido e o vermelho o mais macio;
# - cópia: KODAK VISION Color Print Film 2383/3383, H-1-2383, revisão 3-22, p. 4, figura F010_0292AC (3200 K,
#   ECP-2D, Status A): o verde é o mais nítido e o azul o mais macio.
# Películas sem datasheet usam os mesmos valores (os da Vision3 e da 2383).
MTF_NEG_DSIGMA_UM = (4.261, 2.167, 0.0)
MTF_PRINT_DSIGMA_UM = (2.291, 0.0, 4.462)
# Largura da imagem de cada bitola em mm (a conversão para px@1080 supõe um quadro 16:9 de 1920 px de largura):
# as de `look.SCAN_FORMATS` e, para as bitolas sem scan, a abertura de câmera publicada (8 mm 0,192 pol.,
# 65 mm de 5 perfurações 2,072 pol., IMAX 15/70 2,772 pol.). "Nenhuma" usa o 35 mm.
FRAME_W_MM_EXTRA = {"8mm": 4.877, "65mm": 52.63, "imax": 70.41}
REF_WIDTH_PX = 1920.0


def frame_width_mm(bitola: str) -> float:
    from .look import GAUGE_SCAN, SCAN_FORMATS
    if bitola in FRAME_W_MM_EXTRA:
        return FRAME_W_MM_EXTRA[bitola]
    x0, x1 = SCAN_FORMATS[GAUGE_SCAN.get(bitola, "35mm")]["img"][:2]
    return x1 - x0


def print_chosen(v: dict) -> bool:
    """Há uma cópia no caminho: a cópia do look ou a do Laboratório (que não seja "sem cópia")."""
    look_print = v.get("copia", "nenhuma") != "nenhuma" and float(v.get("copia_forca", 1.0)) > 0.0
    lab_print = bool(v.get("lab_on")) and v.get("lab_copia", "2383") != "nenhuma"
    return look_print or lab_print


def layer_dsigma_um(with_print: bool) -> tuple[float, float, float]:
    """Diferença de maciez de cada camada (µm, em quadratura) em relação ao canal mais nítido do caminho."""
    if not with_print:
        return MTF_NEG_DSIGMA_UM
    tot = [a * a + b * b for a, b in zip(MTF_NEG_DSIGMA_UM, MTF_PRINT_DSIGMA_UM)]
    m = min(tot)
    return tuple(math.sqrt(t - m) for t in tot)


def layer_sigmas(v: dict) -> tuple[float, float, float] | None:
    """Sigma extra (px@1080) de R, G e B da "Diferença de nitidez entre camadas"; None em 0%.
    50% = a diferença dos datasheets; 100% = o dobro (como a "Quantidade do MTF")."""
    amt = float(v.get("mtf_camadas", 0.0))
    if amt <= 0.0:
        return None
    k = 2.0 * amt * REF_WIDTH_PX / frame_width_mm(v["bitola"]) / 1000.0
    return tuple(k * x for x in layer_dsigma_um(print_chosen(v)))


def layer_softness(plan, v: dict, soft: float, scale: float) -> None:
    """Gancho de `build_plan` depois da maciez: um sigma por canal (`plan.soft_sigma3`) somado em quadratura à
    maciez escalar `soft` (px da imagem). Com 0% não mexe em nada."""
    d = layer_sigmas(v)
    if d is None:
        return
    s3 = tuple(math.sqrt(soft * soft + (x * scale) ** 2) for x in d)
    if max(s3) <= 0.05:
        return
    plan.soft_sigma3 = s3
    plan.soft_sigma = max(s3)
    plan.uniforms["u_soft_on"] = 1
    plan.uniforms["u_soft_mix"] = 1.0


# ------------------------------------------------------------------ M3: grão no negativo (densidade por camada)
# Granularidade rms difusa de cada camada R, G, B do negativo (sigma D numa abertura de 48 µm), média dos pontos
# lidos de KODAK VISION3 250D 5207/7207, H-1-5207, revisão 3-26, p. 3, "Diffuse rms Granularity Curves" (ECN-2):
# o azul tem o dobro do grão do verde e do vermelho (`tools/ajustar_grao.py`).
NEG_SIGMA_D = (0.00611, 0.00709, 0.01262)
GRAN_APERTURE_MM = 0.048
GRAIN_NORM = 2.08  # o ruído interpolado (texBicubic × 2,08) tem variância 1 por pixel
# O sigma D do datasheet é medido numa abertura; o do app é por pixel. Na referência (35 mm, ISO 250 = o 250D,
# Tamanho 1: célula do grão s = 0,8 px@1080; abertura D = 48 µm · 1920 / 24,9 mm = 3,70 px@1080), a média do
# campo do grão (variância 1 por pixel) na abertura circular tem o sigma GRAN_APERTURE_SIGMA, calculado em
# `tools/ajustar_grao.py` pela integral exata da autocovariância do campo (a da B-spline cúbica consigo mesma)
# com a das aberturas; a lei de Selwyn (sigma ∝ s / D) só vale para D muito maior que s e daria 15% a mais. Cada
# camada recebe por pixel a amplitude que dá o sigma D do datasheet nessa abertura; a bitola, o ISO, a revelação
# e a Intensidade multiplicam como no grão de sempre.
GRAN_APERTURE_PX = GRAN_APERTURE_MM * REF_WIDTH_PX / 24.9
GRAN_APERTURE_SIGMA = 0.43215
SIGMA_D_TO_PIXEL = 1.0 / GRAN_APERTURE_SIGMA
NEG_GRAIN_AMP = tuple(sd * SIGMA_D_TO_PIXEL for sd in NEG_SIGMA_D)


def negative_grain_on(v: dict) -> bool:
    return bool(v.get("lab_grao")) and bool(v.get("lab_on")) and bool(v.get("grao_on"))         and float(v.get("grao_forca", 0.0)) > 0.0


def negative_grain(U: dict, v: dict, amt: float) -> None:
    """Gancho do bloco do grão de `build_plan`: com o Laboratório e "Grão no negativo" ligados, o grão sai da
    saída e entra na densidade das camadas (`u_grain_on = 2`; `u_ngrain` = sigma D por pixel de R, G, B). `amt` é
    o multiplicador do grão de sempre (Intensidade × bitola × ISO × compensação × revelação × redes). Sem uniform
    novo nos planos de sempre: `u_ngrain` só é lido com `u_grain_on = 2`, e esse plano sempre o grava."""
    if not negative_grain_on(v):
        return
    U["u_grain_on"] = 2
    U["u_ngrain"] = tuple(a * amt for a in NEG_GRAIN_AMP)
