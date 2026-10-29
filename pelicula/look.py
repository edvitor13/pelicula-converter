"""Converte os parâmetros da interface em valores para o motor (uniforms).

Tudo o que muda quadro a quadro (tremor, cintilação, vazamento de luz, semente
do grão) é calculado aqui a partir do número do quadro, então a prévia e a
exportação geram exatamente o mesmo resultado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from . import grao

# Curva neutra usada para levar vídeo Rec.709 até a luz da cena e de volta.
D_SLOPE = 0.155
D_MID = 0.45
D_P = 4.0

INPUT_IDS = {"rec709": 0, "linear": 1, "nlog": 2, "slog3": 3, "logc3": 4, "vlog": 5, "cineon": 6, "dwg": 7,
             "log3g10": 8, "bmd_gen5": 9, "logc4": 10,
             "applelog": 11, "hlg": 12, "pq": 13}

GAUGES: dict[str, dict[str, Any]] = {
    "nenhuma": dict(grain_size=1.00, grain_amt=1.00, blur=0.0, weave=1.0, vignette=0.00, hal=1.00, aspect=None),
    "8mm":     dict(grain_size=3.00, grain_amt=1.55, blur=2.4, weave=2.8, vignette=0.45, hal=1.60, aspect=1.33),
    "super8":  dict(grain_size=2.60, grain_amt=1.45, blur=1.9, weave=2.4, vignette=0.38, hal=1.50, aspect=1.36),
    "16mm":    dict(grain_size=1.80, grain_amt=1.25, blur=1.1, weave=1.6, vignette=0.20, hal=1.25, aspect=1.33),
    "super16": dict(grain_size=1.60, grain_amt=1.18, blur=0.9, weave=1.5, vignette=0.16, hal=1.20, aspect=1.66),
    "35mm":    dict(grain_size=1.00, grain_amt=1.00, blur=0.35, weave=1.0, vignette=0.06, hal=1.00, aspect=1.85),
    "65mm":    dict(grain_size=0.60, grain_amt=0.72, blur=0.0, weave=0.7, vignette=0.03, hal=0.85, aspect=2.20),
    "imax":    dict(grain_size=0.45, grain_amt=0.55, blur=0.0, weave=0.55, vignette=0.02, hal=0.75, aspect=1.43),
}

PRINTS: dict[str, dict[str, Any] | None] = {
    "nenhuma": None,
    "k2383": dict(slope=1.10, mid=0.43, black=0.012, white=0.975, ps=0.35, pt=0.15,
                  gamma=(0.98, 1.0, 1.035), offset=(0.035, 0.0, -0.05), sat=1.08),
    "k2393": dict(slope=1.20, mid=0.42, black=0.004, white=0.985, ps=0.30, pt=0.05,
                  gamma=(0.985, 1.0, 1.03), offset=(0.025, 0.0, -0.03), sat=1.1),
    "f3513": dict(slope=1.08, mid=0.44, black=0.014, white=0.975, ps=0.35, pt=0.15,
                  gamma=(1.0, 1.0, 1.0), offset=(-0.015, 0.01, 0.03), sat=1.12),
}

# Geometria real das películas em mm. x atravessa a película (0 = borda esquerda),
# y corre ao longo dela (0 = centro do quadro atual).
SCAN_FORMATS: dict[str, dict[str, Any]] = {
    "35mm": dict(film_w=35.0, pitch=19.0, img=(5.05, 29.95, 18.66, 0.45), perf=(3.41, 31.59, 2.794, 1.981),
                 perf_r=0.33, perf_phase=2.375, perf_period=4.75, text=(0.35, 1.75, 33.25, 34.65), rough=0.035),
    "16mm": dict(film_w=16.0, pitch=7.62, img=(3.55, 13.81, 7.49, 0.30), perf=(1.80, -1.0, 1.829, 1.27),
                 perf_r=0.25, perf_phase=3.81, perf_period=7.62, text=(-1.0, -1.0, 14.3, 15.6), rough=0.025),
    "super16": dict(film_w=16.0, pitch=7.62, img=(3.45, 15.9, 7.41, 0.25), perf=(1.80, -1.0, 1.829, 1.27),
                    perf_r=0.25, perf_phase=3.81, perf_period=7.62, text=(-1.0, -1.0, -1.0, -1.0), rough=0.025),
    "super8": dict(film_w=8.0, pitch=4.234, img=(1.55, 7.34, 4.01, 0.40), perf=(0.97, -1.0, 0.914, 1.143),
                   perf_r=0.13, perf_phase=2.117, perf_period=4.234, text=(-1.0, -1.0, -1.0, -1.0), rough=0.02),
}
GAUGE_SCAN = {"8mm": "super8", "super8": "super8", "16mm": "16mm", "super16": "super16",
              "35mm": "35mm", "65mm": "35mm", "imax": "35mm", "nenhuma": "35mm"}
EDGE_TEXTS = {
    "kodak_vision3": "KODAK  VISION3",
    "eastman": "EASTMAN  KODAK  SAFETY  FILM",
    "fuji": "FUJIFILM  ETERNA",
    "kodak_2383": "KODAK  2383",
}
_KODAK_35 = {50: "5203", 100: "5203", 125: "5203", 200: "5213", 250: "5207", 400: "5207", 500: "5219",
             800: "5219", 1600: "5219", 3200: "5219"}
_KODAK_NAME = {"5203": "50D", "5213": "200T", "5207": "250D", "5219": "500T"}


# MTF da película (px@1080): sigma da gaussiana fina de cada enquadramento, com "Quantidade" 50%.
MTF_SIGMA = {"nenhum": 0.0, "close": 1.6, "medio": 1.1, "aberto": 0.7, "16mm": 1.5, "super8": 2.3}


def mtf_sigma(v: dict) -> float:
    """Sigma do MTF em px@1080 (0 = desligado). Quantidade 50% = o valor do enquadramento; 100% = o dobro."""
    return MTF_SIGMA.get(v.get("mtf", "nenhum"), 0.0) * 2.0 * float(v.get("mtf_forca", 0.5))


def edge_text(v: dict) -> str:
    """Texto impresso na borda da película (o que um scan real mostraria)."""
    choice = v.get("scan_texto", "auto")
    if choice == "nenhum":
        return ""
    if choice != "auto":
        return EDGE_TEXTS.get(choice, "")
    fmt = scan_format(v)
    if fmt == "super8" or fmt == "super16":
        return ""
    code = "5222" if v.get("pb") else _KODAK_35.get(int(v.get("iso", 250)), "5207")
    if fmt == "16mm":
        code = "7" + code[1:]
    name = "DOUBLE-X" if v.get("pb") else f"VISION3  {_KODAK_NAME.get('5' + code[1:], '250D')}"
    return f"KODAK  {code}  {name}   KJ 44  2731  0815 +12"


def scan_format(v: dict) -> str:
    f = v.get("scan_formato", "bitola")
    return GAUGE_SCAN.get(v.get("bitola", "35mm"), "35mm") if f == "bitola" else f


def display_to_lin(rgb) -> tuple:
    """Inverte a curva neutra (mesma do shader) para converter uma cor da tela em luz linear."""
    out = []
    for y in rgb:
        if y >= D_MID:
            r = 1.0 - D_MID
        else:
            r = D_MID
        vv = min(abs((y - D_MID) / r), 0.99995)
        u = vv / (1 - vv ** D_P) ** (1 / D_P)
        t = math.copysign(u, y - D_MID) * r / D_SLOPE
        out.append(0.18 * 2 ** max(min(t, 8), -12))
    return tuple(out)


BW_WEIGHTS = {
    "pan": (0.25, 0.65, 0.10), "vermelho": (0.75, 0.22, 0.03), "laranja": (0.55, 0.38, 0.07),
    "amarelo": (0.40, 0.52, 0.08), "verde": (0.18, 0.72, 0.10), "azul": (0.08, 0.37, 0.55),
}

TONES = {
    "sepia": ((1.12, 0.92, 0.70), (1.06, 0.99, 0.88)),
    "selenio": ((1.00, 0.86, 0.93), (1.00, 0.99, 0.98)),
    "cianotipo": ((0.55, 0.85, 1.25), (0.85, 0.97, 1.08)),
    "ouro": ((1.15, 1.00, 0.62), (1.05, 1.02, 0.90)),
}

# Primárias (x, y) de R, G, B; todas com branco D65.
_PRIMARIES = {
    "709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "awg3": ((0.6840, 0.3130), (0.2210, 0.8480), (0.0861, -0.1020)),
    "vgamut": ((0.730, 0.280), (0.165, 0.840), (0.100, -0.030)),
    "dwg": ((0.8000, 0.3130), (0.1682, 0.9877), (0.0790, -0.1155)),
    "rwg": ((0.780308, 0.304253), (0.121595, 1.493994), (0.095612, -0.084589)),
    # Blackmagic Wide Gamut (Gen 4/5) e ARRI Wide Gamut 4 (valores publicados; branco D65)
    "bmdwg": ((0.7177215, 0.3171181), (0.2280410, 0.8615690), (0.1005841, -0.0820452)),
    "awg4": ((0.7347, 0.2653), (0.1424, 0.8576), (0.0991, -0.0308)),
}
_D65 = (0.3127, 0.3290)
INPUT_GAMUT = {"rec709": "709", "linear": "709", "cineon": "709", "nlog": "2020",
               "slog3": "sgamut3cine", "logc3": "awg3", "vlog": "vgamut", "dwg": "dwg", "log3g10": "rwg",
               "bmd_gen5": "bmdwg", "logc4": "awg4", "applelog": "2020", "hlg": "2020", "pq": "2020"}

# Domínio de cada curva de entrada: em que escala o fabricante escreveu a fórmula.
#
# O decodificador (media.FrameReader, `in_range=limited`) expande o vídeo YUV de faixa legal para a
# faixa cheia: o shader recebe v = (código − 64)/876 em 10 bits (a fração de "IRE", o mesmo valor que
# o DaVinci Resolve mostra para um clipe "Video levels"). Imagens RGB e vídeo de faixa cheia chegam
# como v = código/1023.
#
# - "cv": a fórmula usa o código de 10 bits normalizado CV = código/1023, que a câmera grava como está,
#   mesmo num arquivo marcado como faixa legal (o código 420 do S-Log3 é 420 no arquivo). Com a fonte
#   em faixa legal o shader volta ao código, CV = (v·876 + 64)/1023, antes da fórmula; em faixa cheia,
#   CV = v. Fontes (do próprio fabricante):
#     Sony S-Log3, "Technical Summary for S-Gamut3.Cine/S-Log3 and S-Gamut3/S-Log3": "in = S-Log3 10bit
#       Code / 1023.0"; preto 95 (3,5% IRE), cinza 18% = 420 (41%), branco 90% = 598 (61%); e "S-Log3 is
#       recorded as Full range in XAVC, MPEG and HDCAM SR File ... There is no option to select Legal range".
#     Panasonic V-Log, "V-Log/V-Gamut Reference Manual": "in = IN10BIT/1023"; preto 128 (7,3%), cinza 18% =
#       433 (42%), branco 90% = 602 (61%).
#     Nikon N-Log, "N-Log Specification Document": "x is the N-Log 10-bit code value"; cinza 18% = 372
#       (35%, calculado pela fórmula). Exceção: gravação externa por HDMI com a saída em "Limited" chega já
#       reescalada para 64–940 (guia de edição da Nikon) — `log_reescalado` desliga a volta ao código.
# - "sinal": a fórmula usa o próprio sinal E′ (0 = preto, 1 = branco nominal), gravado com a quantização
#   padrão (faixa legal: código = 64 + 876·E′; cheia: 1023·E′); o valor expandido v já é E′. Fontes:
#     ARRI LogC3, "ALEXA Log C Curve – Usage in VFX": o cinza 18% é o valor 0,391 = 400/1023 num código
#       "linearmente normalizado" (DPX, faixa cheia); "An ALEXA always records ProRes and DNxHD clips using
#       legal range encoding" (ALEXA Pocket Guide) e as tabelas da "ARRI LogC False Color Specification"
#       batem com 64 + 876·t (cinza ≈ 406,5 no ProRes).
#     ARRI LogC4, "ARRI LogC4 Logarithmic Color Space Specification", apêndice C: 18% → E′ = 0,2784 = código
#       308 em 10 bits legal / 285 em cheia; E′ = 1 → 940 legal / 1023 cheia (legal = 64 + 876·E′).
#     Blackmagic Film Gen 5, "Blackmagic Generation 5 Color Science": coluna "10-bit Video Levels" com
#       0 → 145, 18% → 400, 1,0 → 529 (= 64 + 876·y).
#     DaVinci Intermediate ("DaVinci Resolve 17 Wide Gamut Intermediate") e RED Log3G10 ("White Paper on
#       REDWideGamutRGB and Log3G10"): curvas em ponto flutuante (18% → 0,336 e 1/3), sem código de 10 bits;
#       num vídeo YUV viajam escaladas na faixa legal, como as gravações ProRes da RED e da Blackmagic.
#     Cineon (Kodak, "Conversion of 10-bit Log Film Data to 8-bit Linear or Video Data"): código do DPX RGB
#       de faixa cheia (branco 685, Dmin 95, 0,002 D por código); num vídeo YUV viaja escalado.
#     Apple Log ("Apple Log Profile White Paper", 2023): P em [0, 1] gravado em buffers "video range" de 10
#       bits (não conferido no documento original: está atrás do login de desenvolvedor da Apple).
#     Rec.709 (curva neutra do app), linear e HLG/PQ (ITU-R BT.2100: E′ com D = 876·E′ + 64 em 10 bits).
# Os LUTs externos e os .cube exportados usam o domínio da própria curva (código de 10 bits nas curvas
# "cv"): é a convenção dos LUTs dos fabricantes ("N-Log-Full", LUTs "Full range" da Sony) e das IDTs do
# ACES, que aplicam a fórmula direto no valor de entrada.
INPUT_DOMAIN = {"rec709": "sinal", "linear": "sinal", "nlog": "cv", "slog3": "cv", "logc3": "sinal",
                "vlog": "cv", "cineon": "sinal", "dwg": "sinal", "log3g10": "sinal", "bmd_gen5": "sinal",
                "logc4": "sinal", "applelog": "sinal", "hlg": "sinal", "pq": "sinal"}

# HLG e PQ: luz de cena normalizada E (0..1 no HLG) → luz linear do app (cinza médio = 0,18). O cinza
# de referência da ITU-R BT.2408 (cartão 18% em 38% do sinal HLG: E = 0,38²/3) vira 0,18; o branco de
# referência (75% HLG = 203 cd/m² em PQ) fica em ≈ 0,99. As constantes se repetem em shaders.COMMON e
# no plugin do Resolve (tests/test_entrada.py confere).
HLG_GRAY_SIGNAL = 0.38
HLG_SCALE = 0.18 / (HLG_GRAY_SIGNAL ** 2 / 3.0)  # ≈ 3,7396
HLG_A = 0.17883277                               # ITU-R BT.2100, tabela 5 (HLG)
HLG_B = 1.0 - 4.0 * HLG_A                        # 0,28466892
HLG_C = 0.5 - HLG_A * math.log(4.0 * HLG_A)      # 0,55991073
PQ_M1 = 2610 / 16384                             # SMPTE ST 2084 / BT.2100, tabela 4 (PQ)
PQ_M2 = 2523 / 4096 * 128
PQ_C1 = 3424 / 4096
PQ_C2 = 2413 / 4096 * 32
PQ_C3 = 2392 / 4096 * 32
PQ_NOMINAL_PEAK = 1000.0  # cd/m²: pico nominal do HLG na conversão PQ → luz de cena (BT.2408, γ = 1,2)


def code_value_curve(entrada: str) -> bool:
    """A curva do perfil é escrita no código de 10 bits (código/1023)? (veja INPUT_DOMAIN)"""
    return INPUT_DOMAIN.get(entrada) == "cv"


def _npm(prim, white=_D65) -> np.ndarray:
    xyz = []
    for x, y in prim:
        xyz.append((x / y, 1.0, (1 - x - y) / y))
    m = np.array(xyz).T
    wx, wy = white
    w = np.array([wx / wy, 1.0, (1 - wx - wy) / wy])
    s = np.linalg.solve(m, w)
    return m * s


def gamut_to_709(name: str) -> np.ndarray:
    return np.linalg.inv(_npm(_PRIMARIES["709"])) @ _npm(_PRIMARIES[name])


def mat3_uniform(m: np.ndarray) -> tuple:
    """GLSL espera matrizes por coluna."""
    return tuple(float(v) for v in np.asarray(m, dtype=np.float64).T.flatten())


def _hash(i: int, s: int) -> float:
    x = (i * 0x9E3779B1 + s * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return x / 0xFFFFFFFF


def _vnoise(x: float, s: int) -> float:
    i = math.floor(x)
    f = x - i
    u = f * f * (3 - 2 * f)
    return (_hash(i, s) * (1 - u) + _hash(i + 1, s) * u) * 2 - 1


def _hsv_tint(hue_deg: float, amount: float) -> tuple:
    h = (hue_deg % 360) / 60.0
    c = 1.0
    x = c * (1 - abs(h % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h) % 6]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return tuple((v - luma) * amount * 0.09 for v in (r, g, b))


def _softness_p(v: float) -> float:
    return 4.0 + (1.15 - 4.0) * float(v)


# ================================================================== laboratório (densidade)
# Modelo de densidade de um laboratório de cinema, com valores aproximados e artísticos (nada de
# dados ou curvas dos fabricantes):
#
#   cena linear ──matriz de sensibilidade──► exposição de cada camada (R, G, B)
#     log10(exposição / 0,18) ──curva característica do negativo──► densidade do negativo
#     luz da copiadora − densidade do negativo = log da exposição da cópia
#     ──curva característica da cópia──► densidade de cada camada de corante (ciano, magenta, amarelo)
#     matriz de diafonia dos corantes (+ chave/prata) ──► densidade vista em R, G, B
#     10^(−densidade/2,6) ──► valor de exibição (projeção com gama 2,6; base limpa = 1,0)
#
# Curva característica (densidade × log da exposição): duas "softplus" com a mesma largura, que dão
# pé (toe) e ombro suaves e um trecho reto com inclinação gama entre eles:
#   D(x) = gama · w · [softplus((x − pé)/w) − softplus((x − ombro)/w)],  softplus(z) = ln(1 + e^z)
# A densidade é relativa à base (0 = base + véu), nunca diminui e satura em gama·(ombro − pé).
# Com a mesma largura nas duas pontas a curva é sempre crescente.
#
# A luz da copiadora de cada camada é calibrada (em Python, guardada em cache) para que o cinza
# médio (luz 0,18) saia neutro em 0,45 — o mesmo cinza da curva neutra do app. As luzes que o
# usuário escolhe são somadas depois: 1 ponto = 0,025 log E = 1/12 de stop.

LAB_VIEW_GAMMA = 2.6          # projeção de cinema (DCI): densidade → exibição
LAB_MID_CODE = 0.45           # cinza médio na saída (igual a D_MID)
LAB_TARGET_D = -LAB_VIEW_GAMMA * math.log10(LAB_MID_CODE)  # densidade do cinza médio na cópia (≈ 0,90)
LAB_POINT = 0.025             # log E por ponto da copiadora
LOG10_2 = math.log10(2.0)     # 1 stop em log10

# Matrizes de sensibilidade (linhas = camadas R, G, B do filme; colunas = luz Rec.709 linear): a
# sobreposição das faixas de cor que cada camada enxerga. Só valores positivos e cada linha soma 1,
# então o cinza continua cinza e luzes estouradas nunca dão exposição negativa.
_SENS_V3 = ((0.92, 0.07, 0.01), (0.04, 0.92, 0.04), (0.01, 0.07, 0.92))
_SENS_V3T = ((0.91, 0.08, 0.01), (0.05, 0.91, 0.04), (0.01, 0.08, 0.91))
_SENS_ETERNA = ((0.88, 0.10, 0.02), (0.05, 0.88, 0.07), (0.02, 0.11, 0.87))
_SENS_VIVID = ((0.94, 0.05, 0.01), (0.03, 0.94, 0.03), (0.01, 0.05, 0.94))
_SENS_ECN2 = ((0.84, 0.13, 0.03), (0.07, 0.85, 0.08), (0.03, 0.13, 0.84))
_SENS_V2 = ((0.91, 0.08, 0.01), (0.05, 0.90, 0.05), (0.01, 0.08, 0.91))
_SENS_EXR = ((0.88, 0.10, 0.02), (0.06, 0.88, 0.06), (0.02, 0.10, 0.88))
_SENS_PAN = ((0.25, 0.65, 0.10),) * 3  # P&B pancromático: as três "camadas" veem a mesma coisa

# Negativos: gama, pé e ombro (log10 relativo ao cinza médio; 0,301 = 1 stop), largura das curvas e
# efeito entre camadas ("interimage", acopladores DIR): na densidade, cada camada se afasta da média
# das três (dn' = dn + k·(dn − média)), o que satura sem mexer no cinza. Filmes antigos têm pouco.
NEGATIVES: dict[str, dict[str, Any]] = {
    "vision3_50d": dict(sens=_SENS_V3, gamma=(0.62, 0.62, 0.63), toe=(-1.50, -1.50, -1.45),
                        shoulder=(2.05, 2.05, 2.00), width=0.22, interimage=0.42),
    "vision3_250d": dict(sens=_SENS_V3, gamma=(0.60, 0.60, 0.61), toe=(-1.60, -1.60, -1.55),
                         shoulder=(2.00, 2.00, 1.95), width=0.24, interimage=0.38),
    "vision3_200t": dict(sens=_SENS_V3T, gamma=(0.60, 0.61, 0.59), toe=(-1.60, -1.62, -1.58),
                         shoulder=(2.00, 2.00, 1.95), width=0.24, interimage=0.37),
    "vision3_500t": dict(sens=_SENS_V3T, gamma=(0.57, 0.58, 0.58), toe=(-1.72, -1.72, -1.66),
                         shoulder=(1.90, 1.90, 1.85), width=0.28, interimage=0.36),
    "eterna_250d": dict(sens=_SENS_ETERNA, gamma=(0.55, 0.56, 0.55), toe=(-1.62, -1.65, -1.62),
                        shoulder=(2.10, 2.10, 2.05), width=0.30, interimage=0.28),
    "eterna_vivid": dict(sens=_SENS_VIVID, gamma=(0.64, 0.65, 0.64), toe=(-1.50, -1.50, -1.48),
                         shoulder=(1.90, 1.90, 1.85), width=0.25, interimage=0.56),
    "exr_5248": dict(sens=_SENS_V3, gamma=(0.64, 0.65, 0.66), toe=(-1.40, -1.42, -1.40),
                     shoulder=(1.75, 1.75, 1.70), width=0.24, interimage=0.38),
    "ecn2_5247": dict(sens=_SENS_ECN2, gamma=(0.67, 0.65, 0.62), toe=(-1.30, -1.32, -1.28),
                      shoulder=(1.60, 1.60, 1.55), width=0.22, interimage=0.25),
    # Negativos de outras épocas (aproximações artísticas): quanto mais antigo, mais mistura entre
    # camadas, menos latitude e menos efeito entre camadas.
    "vision2_5201": dict(sens=_SENS_V2, gamma=(0.63, 0.63, 0.64), toe=(-1.45, -1.46, -1.42),
                         shoulder=(1.88, 1.88, 1.84), width=0.23, interimage=0.44),
    "ecn2_5297": dict(sens=_SENS_EXR, gamma=(0.64, 0.63, 0.61), toe=(-1.36, -1.38, -1.34),
                      shoulder=(1.72, 1.72, 1.66), width=0.24, interimage=0.32),
    "vision_5246": dict(sens=_SENS_EXR, gamma=(0.61, 0.61, 0.61), toe=(-1.48, -1.50, -1.46),
                        shoulder=(1.85, 1.85, 1.80), width=0.25, interimage=0.36),
    "vision_5263": dict(sens=_SENS_V3T, gamma=(0.58, 0.59, 0.58), toe=(-1.56, -1.58, -1.52),
                        shoulder=(1.80, 1.80, 1.75), width=0.27, interimage=0.33),
    "vision2_5229": dict(sens=_SENS_V3T, gamma=(0.52, 0.53, 0.52), toe=(-1.66, -1.68, -1.62),
                         shoulder=(1.95, 1.95, 1.90), width=0.32, interimage=0.30),
    "double_x": dict(sens=_SENS_PAN, gamma=(0.65, 0.65, 0.65), toe=(-1.40, -1.40, -1.40),
                     shoulder=(1.80, 1.80, 1.80), width=0.25, interimage=0.0),
}

# Cópias: gama, densidade máxima (acima da base) e largura (o pé da cópia é a rolagem das altas luzes).
# A matriz de diafonia tem linhas = densidade vista em R, G, B e colunas = camadas ciano, magenta, amarelo.
LAB_PRINTS: dict[str, dict[str, Any] | None] = {
    "2383": dict(gamma=(3.00, 2.95, 2.85), dmax=(4.0, 4.0, 3.95), width=0.22,
                 dye=((1.00, 0.08, 0.02), (0.06, 1.00, 0.08), (0.02, 0.14, 1.00))),
    "2393": dict(gamma=(3.20, 3.15, 3.05), dmax=(4.2, 4.2, 4.15), width=0.20,
                 dye=((1.00, 0.07, 0.02), (0.05, 1.00, 0.07), (0.02, 0.12, 1.00))),
    "3513": dict(gamma=(2.95, 2.95, 2.92), dmax=(4.0, 4.0, 4.0), width=0.23,
                 dye=((1.00, 0.07, 0.03), (0.08, 1.00, 0.06), (0.03, 0.12, 1.00))),
    # Cópias Eastman mais antigas: gama um pouco menor, menos densidade máxima e corantes menos puros.
    "e5386": dict(gamma=(2.90, 2.85, 2.74), dmax=(3.85, 3.85, 3.78), width=0.24,
                  dye=((1.00, 0.10, 0.03), (0.07, 1.00, 0.10), (0.03, 0.16, 1.00))),
    "e5385": dict(gamma=(2.80, 2.74, 2.62), dmax=(3.65, 3.65, 3.55), width=0.25,
                  dye=((1.00, 0.12, 0.04), (0.08, 1.00, 0.12), (0.04, 0.18, 1.00))),
    "2302": dict(gamma=(2.70, 2.70, 2.70), dmax=(3.8, 3.8, 3.8), width=0.22,
                 dye=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))),
    "nenhuma": None,
}

# Processos especiais (caminho B). Os registros da câmera Technicolor são negativos preto e branco
# de pouca latitude; a matriz de separação (filtros estreitos) satura mais que um filme de três camadas.
_TECH_RECORD = dict(gamma=(0.68, 0.68, 0.68), toe=(-1.20, -1.20, -1.20), shoulder=(1.45, 1.45, 1.45), width=0.20)
LAB_PROCESSES: dict[str, dict[str, Any] | None] = {
    "normal": None,
    "prata": None,  # caminho A + densidade de prata retida (média das camadas), sem caminho B
    # Filtros de separação estreitos: pouca sobreposição e "interimage" alto (o efeito de máscara das matrizes).
    "tech3": dict(sens=((0.97, 0.03, 0.0), (0.02, 0.96, 0.02), (0.0, 0.03, 0.97)), **_TECH_RECORD, interimage=0.65,
                  print=dict(gamma=(2.40, 2.40, 2.40), dmax=(3.6, 3.6, 3.6), width=0.15,
                             dye=((1.00, 0.05, 0.01), (0.04, 1.00, 0.05), (0.01, 0.08, 1.00))),
                  key=(0.0, 1.0, 0.0)),  # a chave preta sai do registro verde (camada magenta)
    # Duas cores: registro vermelho-laranja → corante verde-azulado (absorve vermelho); registro
    # verde-azul → corante vermelho-laranja (absorve verde e azul). A terceira camada não existe.
    "tech2": dict(sens=((0.78, 0.22, 0.0), (0.0, 0.55, 0.45), (0.0, 0.55, 0.45)), **_TECH_RECORD, interimage=0.0,
                  print=dict(gamma=(2.30, 2.30, 2.30), dmax=(3.4, 3.4, 3.4), width=0.16,
                             dye=((1.00, 0.10, 0.0), (0.25, 0.85, 0.0), (0.12, 1.00, 0.0))),
                  key=(0.0, 0.0, 0.0)),
}


# Separação de cores (Hue Split), na densidade do negativo: no plano perpendicular ao cinza (as três
# camadas iguais) estica ao longo de um eixo e encolhe na perpendicular, puxando as cores para os dois
# polos do eixo (padrão laranja ↔ verde-azulado) e afastando umas das outras. Como é feita em log
# (densidade), age igual em qualquer exposição; o cinza e a densidade média não mudam. Junta-se à
# matriz do efeito entre camadas (u_la_ii).
SPLIT_STRETCH = 0.60   # esticar ao longo do eixo com força 1
SPLIT_SQUEEZE = 0.45   # encolher na perpendicular com força 1
_W709 = np.array([0.2126, 0.7152, 0.0722])


def _hue_rgb(hue_deg: float) -> np.ndarray:
    """Cor pura de matiz `hue_deg` (o mesmo setor HSV de _hsv_tint e pc_hsv_tint)."""
    h = (hue_deg % 360) / 60.0
    x = 1 - abs(h % 2 - 1)
    return np.array([(1, x, 0), (x, 1, 0), (0, 1, x), (0, x, 1), (x, 0, 1), (1, 0, x)][int(h) % 6], dtype=np.float64)


def split_axes(hue_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Eixos u (polo quente) e v (perpendicular) do plano perpendicular a (1, 1, 1), unitários."""
    c = _hue_rgb(hue_deg)
    u = c - c.mean()
    u = u / np.linalg.norm(u)
    v = np.cross(np.ones(3) / math.sqrt(3.0), u)
    return u, v / np.linalg.norm(v)


def split_matrix(amount: float, hue_deg: float) -> np.ndarray:
    """Matriz 3×3 da separação na densidade (identidade com força 0; mantém (1, 1, 1) e a média)."""
    if amount == 0:
        return np.eye(3)
    u, v = split_axes(hue_deg)
    a = SPLIT_STRETCH * amount
    b = SPLIT_SQUEEZE * amount
    return np.full((3, 3), 1.0 / 3.0) + (1 + a) * np.outer(u, u) + (1 - b) * np.outer(v, v)


# ------------------------------------------------------------------ depois da cópia (no valor de exibição)
def _curve_np(t, slope, mid, black, white, ps, pt):
    t = np.asarray(t, dtype=np.float64)
    rw = max(white - mid, 1e-4)
    rb = max(mid - black, 1e-4)
    r = np.where(t >= 0, rw, rb)
    p = np.where(t >= 0, ps, pt)
    u = t * slope / r
    return mid + r * u / (1.0 + np.abs(u) ** p) ** (1.0 / p)


def _disp_to_stops(y) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    r = np.where(y >= D_MID, 1.0 - D_MID, D_MID)
    a = np.minimum(np.abs((y - D_MID) / r), 0.99995)
    u = a / (1 - a ** D_P) ** (1 / D_P)
    return np.clip(np.sign(y - D_MID) * u * r / D_SLOPE, -12.0, 12.0)


def _smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _hue_ang(c) -> float:
    c = np.asarray(c, dtype=np.float64)
    y = c @ _W709
    return float(np.arctan2((c[0] - y) / 1.5748, (c[2] - y) / 1.8556))


SKIN_HUE = _hue_ang((0.8, 0.55, 0.45))


def skin_adjust(y, rot: float, sat: float) -> np.ndarray:
    """Giro de matiz e saturação só nos tons de pele (labSkin do shader / hueAdjust do look)."""
    y = np.asarray(y, dtype=np.float64)
    Y = y @ _W709
    cx = (y[..., 2] - Y) / 1.8556
    cy = (y[..., 0] - Y) / 1.5748
    h = np.arctan2(cy, cx)
    d = np.abs(np.mod(h - SKIN_HUE + math.pi, 2 * math.pi) - math.pi)
    ws = _smoothstep(0.8, 0.0, d)
    a = rot * ws
    nx = np.cos(a) * cx - np.sin(a) * cy
    ny = np.sin(a) * cx + np.cos(a) * cy
    k = np.maximum(0.0, 1.0 + sat * ws)
    nx, ny = nx * k, ny * k
    r = Y + 1.5748 * ny
    b = Y + 1.8556 * nx
    g = (Y - 0.2126 * r - 0.0722 * b) / 0.7152
    out = np.stack([r, g, b], axis=-1)
    tiny = np.hypot(cx, cy) < 1e-5
    return np.where(tiny[..., None], y, out)


LAB_DENS_K = 0.5  # escurecimento por unidade de densidade extra numa cor 100% dominante


@dataclass(frozen=True)
class LabPost:
    """O que vem depois da cópia, já no valor de exibição (u_lab_ops e companhia)."""

    ops: int          # bits: 2 rolagem, 4 saturação, 8 densidades, 16 pele (1 fica livre)
    tone: tuple       # expoentes (altas luzes, sombras) da curva de rolagem
    sat: float
    dens: tuple       # densidade − 1 por primária (R, G, B)
    skin: tuple       # giro de matiz da pele (rad), saturação da pele

    def post(self, y) -> np.ndarray:
        y = np.asarray(y, dtype=np.float64)
        if self.ops & 2:
            y = _curve_np(_disp_to_stops(y), D_SLOPE, D_MID, 0.0, 1.0, self.tone[0], self.tone[1])
        if self.ops & 4:
            L = (y @ _W709)[..., None]
            y = L + (y - L) * self.sat
        if self.ops & 8:
            w = np.stack([np.maximum(0.0, y[..., 0] - np.maximum(y[..., 1], y[..., 2])),
                          np.maximum(0.0, y[..., 1] - np.maximum(y[..., 0], y[..., 2])),
                          np.maximum(0.0, y[..., 2] - np.maximum(y[..., 0], y[..., 1]))], axis=-1)
            f = np.clip(1.0 - LAB_DENS_K * (w @ np.asarray(self.dens)), 0.2, 2.0)
            y = y * f[..., None]
        if self.ops & 16:
            y = skin_adjust(y, self.skin[0], self.skin[1])
        return y


def lab_post(v: dict) -> LabPost:
    ops = 0
    hi, lo = float(v["lab_luzes_rolagem"]), float(v["lab_sombras_rolagem"])
    if hi > 0 or lo > 0:
        ops |= 2
    if float(v["lab_saturacao"]) != 1.0:
        ops |= 4
    dens = tuple(float(v[k]) - 1.0 for k in ("lab_dens_r", "lab_dens_g", "lab_dens_b"))
    if any(d != 0.0 for d in dens):
        ops |= 8
    skin = (math.radians(float(v["lab_pele_matiz"])), float(v["lab_pele_sat"]))
    if skin != (0.0, 0.0):
        ops |= 16
    return LabPost(ops, (_softness_p(hi), _softness_p(lo)), float(v["lab_saturacao"]), dens, skin)


def _softplus(z):
    z = np.asarray(z, dtype=np.float64)
    return np.maximum(z, 0.0) + np.log1p(np.exp(-np.abs(z)))


def lab_curve(x, gamma, toe, shoulder, width):
    """Curva característica (densidade acima da base) — a mesma `labCurve` do shader."""
    x = np.asarray(x, dtype=np.float64)
    return np.asarray(gamma) * width * (_softplus((x - np.asarray(toe)) / width)
                                        - _softplus((x - np.asarray(shoulder)) / width))


def _lab_curve_slope(x, gamma, toe, shoulder, width):
    x = np.asarray(x, dtype=np.float64)
    a = 1.0 / (1.0 + np.exp(-(x - np.asarray(toe)) / width))
    b = 1.0 / (1.0 + np.exp(-(x - np.asarray(shoulder)) / width))
    return np.asarray(gamma) * (a - b)


def _stops_to_disp(t) -> np.ndarray:
    """Curva neutra de exibição (stopsToDisp do shader) em numpy."""
    t = np.asarray(t, dtype=np.float64)
    r = np.where(t >= 0, 1.0 - D_MID, D_MID)
    u = t * D_SLOPE / r
    return D_MID + r * u / (1.0 + np.abs(u) ** D_P) ** (1.0 / D_P)


def _t3(a) -> tuple:
    return tuple(float(x) for x in np.asarray(a, dtype=np.float64).reshape(3))


def _t3x3(m) -> tuple:
    return tuple(tuple(float(x) for x in row) for row in np.asarray(m, dtype=np.float64).reshape(3, 3))


@dataclass(frozen=True)
class LabPath:
    """Um caminho negativo → cópia já calibrado (vira os uniforms `u_la_*` ou `u_lb_*`)."""

    sens: tuple       # 3x3 (linhas = camadas)
    ng: tuple         # gama do negativo por camada
    nt: tuple         # pé do negativo (log10 relativo ao cinza)
    ns: tuple         # ombro do negativo
    nw: float         # largura das curvas do negativo
    ii: tuple         # 3x3 efeito entre camadas, aplicado à densidade do negativo (linhas somam 1)
    pg: tuple         # gama da cópia (sem cópia: gama nominal do negativo, para a inversão)
    pt: tuple         # pé da cópia (0: a calibração escolhe a posição)
    ps: tuple         # ombro da cópia (pé + dmax/gama)
    pw: float         # largura das curvas da cópia
    dye: tuple        # 3x3 diafonia (linhas = R, G, B; colunas = camadas)
    key: tuple        # pesos da chave/prata (densidade somada igual nos três canais)
    mid: tuple        # densidade do negativo no cinza médio (para a inversão do scan)
    off: tuple        # luz da copiadora calibrada (log E), antes das luzes do usuário
    scan: bool        # sem cópia: o negativo é invertido digitalmente

    def eval(self, lin, lights=(0.0, 0.0, 0.0)) -> np.ndarray:
        """Mesmo cálculo do `labPath` do shader, em numpy (lin: (..., 3) luz linear Rec.709)."""
        lin = np.asarray(lin, dtype=np.float64)
        e = np.maximum(lin @ np.asarray(self.sens).T, 1e-7)
        le = np.log10(e / 0.18)
        dn = lab_curve(le, self.ng, self.nt, self.ns, self.nw) @ np.asarray(self.ii).T
        off = np.asarray(self.off) + np.asarray(lights)
        if self.scan:
            st = (dn - np.asarray(self.mid)) / (np.asarray(self.pg) * LOG10_2) - off / LOG10_2
            return _stops_to_disp(np.clip(st, -12.0, 12.0))
        dl = lab_curve(off - dn, self.pg, self.pt, self.ps, self.pw)
        d = dl @ np.asarray(self.dye).T + (dl @ np.asarray(self.key))[..., None]
        return 10.0 ** (-d / LAB_VIEW_GAMMA)


def _calibrate_print(dn_mid, gamma, shoulder, width, dye: np.ndarray, key: np.ndarray) -> np.ndarray:
    """Luz da copiadora (log E por camada) que leva o cinza médio a LAB_TARGET_D nos três canais.

    Newton com mínimos quadrados: no Technicolor de duas cores só duas camadas existem, então a
    solução é a de menor norma e o cinza pode guardar um leve tom (como no processo real).
    """
    toe = np.zeros(3)
    M = dye + np.outer(np.ones(3), key)
    target = np.full(3, LAB_TARGET_D)
    off = dn_mid + 0.35  # começa no trecho reto da cópia
    for _ in range(100):
        xp = off - dn_mid
        F = M @ lab_curve(xp, gamma, toe, shoulder, width) - target
        if np.max(np.abs(F)) < 1e-11:
            break
        J = M * _lab_curve_slope(xp, gamma, toe, shoulder, width)[None, :]
        step = np.linalg.lstsq(J, F, rcond=1e-9)[0]
        off = off - np.clip(step, -0.5, 0.5)
    return off


def _neutral3(a, t: float) -> np.ndarray:
    """Aproxima os três canais da média deles (t = 0: igual; t = 1: os três iguais)."""
    a = np.asarray(a, dtype=np.float64)
    return a + (np.full(3, a.mean()) - a) * t


def _aij(a1: float, b1: float, a2: float, b2: float) -> tuple[float, float]:
    """Produto de matrizes da forma a·I + b·J (J = todos 1): continua nessa forma."""
    return a1 * a2, a1 * b2 + b1 * a2 + 3.0 * b1 * b2


BYPASS_NEG_CONTRAST = 0.5  # bleach bypass no negativo: contraste neutro a mais
BYPASS_NEG_DYE = 0.3       # e quanto da cor dos corantes a prata esconde


def ii_coefs(interimage: float, film_sat: float, bypass_neg: float) -> tuple[float, float]:
    """Matriz da densidade do negativo: dn' = A·dn + B·(soma de dn).

    Efeito entre camadas (A = 1 + k, B = −k/3), saturação do filme (s·I + (1 − s)/3·J, mantém a
    média) e prata retida no negativo ((1 − d)·I + (c + d)/3·J: a prata é densidade neutra que soma
    contraste, c = 0,5 × bleach bypass, e dilui a cor dos corantes, d = 0,3 × bleach bypass).
    """
    k = float(interimage)
    a, b = 1.0 + k, -k / 3.0
    s = float(film_sat)
    a, b = _aij(s, (1.0 - s) / 3.0, a, b)
    c, d = BYPASS_NEG_CONTRAST * float(bypass_neg), BYPASS_NEG_DYE * float(bypass_neg)
    a, b = _aij(1.0 - d, (c + d) / 3.0, a, b)
    return a, b


@dataclass(frozen=True)
class LabMods:
    """Ajustes do usuário que mudam as curvas (entram na calibração e na chave do cache)."""

    film_sat: float = 1.0
    bypass_neg: float = 0.0
    neutral_neg: float = 0.0
    neutral_print: float = 0.0
    toe: float = 0.0      # pé da cópia: positivo lava os pretos (menos densidade máxima)
    split: float = 0.0    # separação de cores (Hue Split), na densidade do negativo
    split_hue: float = 35.0


def _make_path(neg: dict, pr: dict | None, push: float, crosstalk: float, key,
               mods: LabMods = LabMods()) -> LabPath:
    gamma = _neutral3(neg["gamma"], mods.neutral_neg)
    ng = gamma * (1.0 + 0.12 * push)                                       # forçar = mais contraste
    nt = _neutral3(neg["toe"], mods.neutral_neg) + 0.08 * push             # ... e sombras mais fechadas
    ns = _neutral3(neg["shoulder"], mods.neutral_neg)
    nw = float(neg["width"])
    a_ii, b_ii = ii_coefs(neg.get("interimage", 0.0), mods.film_sat, mods.bypass_neg)
    ii = np.eye(3) * a_ii + b_ii  # dn' = A·dn + B·(soma): linhas somam A + 3B
    if mods.split:
        ii = split_matrix(mods.split, mods.split_hue) @ ii  # comuta com A·I + B·J
    dn_mid = ii @ lab_curve(np.zeros(3), ng, nt, ns, nw)
    sens = _t3x3(neg["sens"])
    if pr is None:
        # Sem cópia o campo `pg` guarda o gama nominal (sem forçar) usado na inversão do scan: assim
        # a revelação forçada aparece como mais contraste, como num scan com inversão fixa.
        return LabPath(sens, _t3(ng), _t3(nt), _t3(ns), nw, _t3x3(ii), _t3(gamma), (0.0, 0.0, 0.0),
                       (1.0, 1.0, 1.0), 0.2, _t3x3(np.eye(3)), (0.0, 0.0, 0.0), _t3(dn_mid), (0.0, 0.0, 0.0), True)
    pg = _neutral3(pr["gamma"], mods.neutral_print)
    dmax = _neutral3(pr["dmax"], mods.neutral_print) * 2.0 ** (-0.6 * mods.toe)
    ps = dmax / pg
    pw = float(pr["width"])
    eye = np.eye(3)
    raw = np.asarray(pr["dye"], dtype=np.float64)
    used = np.abs(raw).sum(axis=0) > 0  # colunas de camadas que existem (Technicolor 2 cores: só duas)
    dye = (eye + crosstalk * (raw - eye)) * used[None, :]
    key = np.asarray(key, dtype=np.float64)
    off = _calibrate_print(dn_mid, pg, ps, pw, dye, key)
    return LabPath(sens, _t3(ng), _t3(nt), _t3(ns), nw, _t3x3(ii), _t3(pg), (0.0, 0.0, 0.0), _t3(ps), pw,
                   _t3x3(dye), _t3(key), _t3(dn_mid), _t3(off), False)


@lru_cache(maxsize=512)
def lab_paths(negativo: str, copia: str, processo: str, push: float, crosstalk: float, chave: float,
              forca: float, mods: LabMods = LabMods(), bypass_print: float = 0.0) -> tuple[LabPath, LabPath | None]:
    """Caminhos A (negativo + cópia escolhidos) e B (processo Technicolor), já calibrados."""
    neg = NEGATIVES.get(negativo, NEGATIVES["vision3_250d"])
    pr = LAB_PRINTS.get(copia, LAB_PRINTS["2383"])
    key = (0.0, 0.0, 0.0)
    if processo == "prata":
        # Prata retida: a imagem de prata (média das três camadas) fica na cópia, como no bleach bypass.
        key = (0.8 * forca / 3.0,) * 3
        if pr is None:
            pr = LAB_PRINTS["2383"]  # a prata só existe numa cópia
    if bypass_print > 0 and pr is not None:
        key = tuple(k + 0.8 * bypass_print / 3.0 for k in key)  # bleach bypass contínuo na cópia
    a = _make_path(neg, pr, push, crosstalk, key, mods)
    proc = LAB_PROCESSES.get(processo)
    if not proc:
        return a, None
    b = _make_path(proc, proc["print"], push, crosstalk, tuple(chave * k for k in proc["key"]), mods)
    return a, b


def lab_lights(v: dict) -> tuple:
    """Luzes da copiadora escolhidas pelo usuário, em log E por canal (somadas à calibração)."""
    d = v["lab_densidade"]
    return tuple(LAB_POINT * (v[k] + d) for k in ("lab_luz_r", "lab_luz_g", "lab_luz_b"))


def _r4(x) -> float:
    return round(float(x), 4)  # chave do cache: valores de slider arredondados


def lab_paths_for(v: dict) -> tuple[LabPath, LabPath | None]:
    mods = LabMods(_r4(v["lab_saturacao_filme"]), _r4(v["lab_bypass_negativo"]), _r4(v["lab_neutro_negativo"]),
                   _r4(v["lab_neutro_copia"]), _r4(v["lab_pe"]), _r4(v["lab_separacao"]),
                   _r4(v["lab_separacao_eixo"]))
    return lab_paths(v["lab_negativo"], v["lab_copia"], v["lab_processo"], float(v["lab_revelacao"]),
                     float(v["lab_diafonia"]), float(v["lab_chave"]), float(v["lab_processo_forca"]), mods,
                     _r4(v["lab_bypass_copia"]))


def lab_eval(v: dict, lin) -> np.ndarray:
    """Resultado do laboratório (valor de exibição) em numpy, igual ao `labPipe` do shader.

    `lin`: (..., 3) luz linear Rec.709 (0,18 = cinza médio). Inclui a separação de cores (na densidade
    do negativo) e, depois da cópia, rolagens, saturação final, densidades por cor e pele.
    """
    a, b = lab_paths_for(v)
    post = lab_post(v)
    lights = lab_lights(v)
    y = a.eval(lin, lights)
    if b is not None:
        y = y + (b.eval(lin, lights) - y) * v["lab_processo_forca"]
    return post.post(y)


def _lab_post_uniforms(U: dict, post: LabPost) -> None:
    U["u_lab_ops"] = int(post.ops)
    U["u_lab_tone"] = tuple(float(x) for x in post.tone)
    U["u_lab_sat"] = float(post.sat)
    U["u_lab_dens"] = tuple(float(x) for x in post.dens)
    U["u_lab_skin"] = tuple(float(x) for x in post.skin)


def _lab_uniforms(U: dict, prefix: str, p: LabPath, lights: tuple) -> None:
    U[prefix + "sens"] = mat3_uniform(np.asarray(p.sens))
    U[prefix + "ng"], U[prefix + "nt"], U[prefix + "ns"], U[prefix + "nw"] = p.ng, p.nt, p.ns, p.nw
    U[prefix + "ii"] = mat3_uniform(np.asarray(p.ii))
    U[prefix + "pg"], U[prefix + "pt"], U[prefix + "ps"], U[prefix + "pw"] = p.pg, p.pt, p.ps, p.pw
    U[prefix + "dye"] = mat3_uniform(np.asarray(p.dye))
    U[prefix + "off"] = tuple(o + li for o, li in zip(p.off, lights))
    U[prefix + "key"] = p.key
    U[prefix + "mid"] = p.mid
    U[prefix + "scan"] = 1 if p.scan else 0


# "Grão para redes" (exportação): as plataformas recomprimem o vídeo e apagam o grão fino. Com a opção
# ligada, o grão não fica menor que NET_GRAIN_MIN_PX pixels da SAÍDA e fica NET_GRAIN_BOOST vezes mais forte;
# a cor do grão cai para NET_GRAIN_CHROMA (o croma 4:2:0 e a recompressão borram o grão colorido).
NET_GRAIN_MIN_PX = 2.0
NET_GRAIN_BOOST = 1.2
NET_GRAIN_CHROMA = 0.6


@dataclass
class Chain:
    name: str
    threshold: float  # em luz linear (0 = sem limiar)
    sigma: float      # px na resolução atual
    limit: float
    lum_only: bool
    alpha_mask: bool = False


@dataclass
class Plan:
    uniforms: dict[str, Any]
    soft_sigma: float = 0.0
    chains: list[Chain] = field(default_factory=list)
    grain_size: float = 0.0  # px na resolução atual; 0 = sem grão
    grain_seed: int = 0
    lut_path: str = ""
    edge_text: str = ""
    soft_sigma3: tuple[float, float, float] | None = None  # 1.6: sigma da maciez por canal (None = `soft_sigma`)


def aspect_target(v: dict, gauge: dict) -> float:
    if not v["mold_on"]:
        return 0.0
    p = v["proporcao"]
    if p == "original":
        return 0.0
    if p == "bitola":
        return float(gauge["aspect"] or 0.0)
    return float(p)


def build_plan(v: dict[str, Any], width: int, height: int, frame: int, fps: float,
               lut_info: tuple | None = None, dither: bool = True, *, legal: bool = True,
               net_grain: float = 0.0) -> Plan:
    """Monta todos os valores do quadro `frame` para uma imagem width x height.

    `legal`: a imagem de entrada veio de vídeo em faixa legal que o decodificador expandiu para 0–1
    (`media.legal_range`); imagens RGB e vídeo de faixa cheia passam `False`. Só muda as curvas de
    câmera escritas no código de 10 bits (`INPUT_DOMAIN`), que então voltam ao código da câmera (a menos
    que `log_reescalado` diga que o arquivo já veio reescalado). O padrão `True` é o vídeo comum.

    `net_grain`: "Grão para redes" da exportação. 0 (padrão) = desligado, o plano é o de sempre. Maior que 0
    = quantos pixels desta imagem valem um pixel do arquivo exportado (1 na exportação; menos na prévia
    reduzida): o grão fica com pelo menos `NET_GRAIN_MIN_PX` pixels da saída e um pouco mais forte.
    """
    scale = height / 1080.0
    fps = fps or 24.0
    t = frame / fps
    gauge = GAUGES.get(v["bitola"], GAUGES["nenhuma"])
    iso = float(v["iso"])
    iso_amt = (iso / 250.0) ** 0.35
    iso_size = (iso / 250.0) ** 0.18
    U: dict[str, Any] = {}

    # ---- Entrada, geometria e exposição (passo base)
    U["u_res"] = (float(width), float(height))
    U["u_scale"] = scale
    U["u_input"] = INPUT_IDS.get(v["entrada"], 0)
    # Curva em código de 10 bits: volta ao código quando a fonte veio expandida (u_legal), menos quando o
    # arquivo já traz o log reescalado para a faixa legal (saída HDMI "Limited" da câmera).
    U["u_input_cv"] = 1 if (code_value_curve(v["entrada"]) and not v.get("log_reescalado")) else 0
    U["u_legal"] = 1 if legal else 0
    U["u_gamut"] = mat3_uniform(gamut_to_709(INPUT_GAMUT.get(v["entrada"], "709")))
    temp = v["temperatura"] / 100.0
    tint = v["tint"] / 100.0
    gain = [v["exposicao"] + 0.28 * temp + 0.08 * tint,
            v["exposicao"] - 0.22 * tint,
            v["exposicao"] - 0.38 * temp + 0.08 * tint]

    shift = (0.0, 0.0)
    rot = 0.0
    zoom = 1.0
    if v["proj_on"]:
        w = gauge["weave"] * scale
        vel = v["tremor_vel"]
        dx = v["tremor_x"] * w * (0.7 * _vnoise(t * 2.2 * vel, 101) + 0.3 * (_hash(frame, 102) * 2 - 1))
        dy = v["tremor_y"] * w * (0.7 * _vnoise(t * 1.9 * vel, 103) + 0.3 * (_hash(frame, 104) * 2 - 1))
        shift = (dx, dy)
        rot = math.radians(v["tremor_rot"] * gauge["weave"]) * (
            0.7 * _vnoise(t * 1.6 * vel, 105) + 0.3 * (_hash(frame, 106) * 2 - 1))
        margin = max(v["tremor_x"], v["tremor_y"]) * w * 1.1 + abs(rot) * width * 0.5
        zoom = 1.0 + 2.0 * margin / max(1.0, min(width, height))
        fl = v["cintilacao"] * (0.6 * _vnoise(t * 7.0 * v["cintilacao_vel"], 107)
                                + 0.4 * (_hash(frame, 108) * 2 - 1))
        gain = [g + fl for g in gain]
    # ---- defeitos que mexem na exposição e no enquadramento
    if v["desg_on"]:
        sd = int(v["desgaste_semente"])
        if v["queima_on"] and v["queima"] > 0:
            ep = math.floor(t / 6.0)
            if _hash(ep, sd + 401) < v["queima"] * 0.55:
                start_t = ep * 6.0 + _hash(ep, sd + 402) * 5.0
                if t >= start_t:
                    fl = math.exp(-(t - start_t) / 0.13)
                    gain = [gain[0] + 2.6 * fl, gain[1] + 2.0 * fl, gain[2] + 1.1 * fl]
        if v["cor_instavel_on"] and v["cor_instavel"] > 0:
            amt = v["cor_instavel"] * 0.12
            gain = [g + amt * (0.6 * _vnoise(t * 5.0, sd + 410 + c) + 0.4 * (_hash(frame, sd + 420 + c) * 2 - 1))
                    for c, g in enumerate(gain)]
        if v["emenda_on"] and v["emenda"] > 0:
            ep = math.floor(t / 2.5)
            if _hash(ep, sd + 501) < v["emenda"] * 0.4:
                sf = round((ep * 2.5 + _hash(ep, sd + 502) * 2.0) * fps)
                if frame in (sf, sf + 1):
                    shift = (shift[0], shift[1] + (14.0 if frame == sf else 6.0) * scale)
    U["u_shift"] = shift
    U["u_rot"] = rot
    U["u_zoom"] = zoom
    U["u_gain"] = tuple(gain)

    lente = v["lente_on"]
    U["u_dist"] = v["distorcao"] if lente else 0.0
    U["u_ca"] = (v["aberracao"] * scale / (0.5 * height)) if lente else 0.0
    vig = (v["vinheta"] if lente else 0.0) + gauge["vignette"] * v["bitola_vinheta"]
    U["u_vig"] = (min(vig, 1.5), v["vinheta_raio"], v["vinheta_suavidade"], v["vinheta_redondeza"])

    plan = Plan(U)

    # ---- Maciez / nitidez
    sig_g = gauge["blur"] * v["bitola_resolucao"] if v["bitola_desfoque_on"] else 0.0
    sig_u = (v["raio_maciez"] * v["maciez"] * 2.0) if lente else 0.0
    sig_m = mtf_sigma(v)  # MTF da película: gaussiana fina somada em quadratura
    sig_r = grao.soft_sigma(v, gauge)  # 1.6: maciez pelo grão (0 = desligada)
    soft = math.sqrt(sig_g ** 2 + sig_u ** 2 + sig_m ** 2 + sig_r ** 2) * scale
    sharp = v["nitidez"] if lente else 0.0
    if soft > 0.05:
        plan.soft_sigma = soft
        U["u_soft_on"] = 1
        U["u_soft_mix"] = 1.0
    elif sharp > 0:
        plan.soft_sigma = max(v["raio_maciez"] * scale, 0.6)
        U["u_soft_on"] = 1
        U["u_soft_mix"] = 0.0
    else:
        U["u_soft_on"] = 0
        U["u_soft_mix"] = 0.0
    U["u_sharp"] = sharp
    grao.layer_softness(plan, v, soft, scale)  # 1.6: nitidez por camada (nada com 0%)

    # ---- Halação, bloom e névoa
    U["u_hal_on"] = 0
    U["u_bloom_on"] = 0
    U["u_mist_on"] = 0
    if v["hal_on"] and v["hal_forca"] > 0:
        plan.chains.append(Chain("hal", 0.18 * 2 ** v["hal_limiar"], v["hal_raio"] * gauge["hal"] * scale, 8.0, True,
                                 bool(v["scan_on"])))
        U["u_hal_on"] = 1
        U["u_hal_amt"] = v["hal_forca"] * 0.32
        U["u_hal_color"] = tuple(v["hal_cor"])
    if v["bloom_on"] and v["bloom_forca"] > 0:
        plan.chains.append(Chain("bloom", 0.18 * 2 ** v["bloom_limiar"], v["bloom_raio"] * scale, 6.0, False))
        U["u_bloom_on"] = 1
        U["u_bloom_amt"] = v["bloom_forca"] * 0.22
    if v["bloom_on"] and v["nevoa_forca"] > 0:
        plan.chains.append(Chain("mist", 0.0, v["nevoa_raio"] * scale, 3.0, False))
        U["u_mist_on"] = 1
        U["u_mist_amt"] = v["nevoa_forca"]

    # ---- Vazamento de luz
    U["u_leak_on"] = 0
    if v["desg_on"] and v["vazamento_on"] and v["vazamento"] > 0:
        U["u_leak_on"] = 1
        U["u_leak_amt"] = v["vazamento"]
        U["u_leak_color"] = tuple(v["vazamento_cor"])
        sd = int(v["desgaste_semente"])
        tl = t * 0.35 * v["vazamento_vel"]
        blobs = []
        for k in range(2):
            side = 0.0 if _hash(k, sd + 3) < 0.5 else 1.0
            x = side + (0.12 if side == 0 else -0.12) * _vnoise(tl + k * 7.3, sd + 10 + k)
            y = 0.5 + 0.55 * _vnoise(tl * 0.8 + k * 3.1, sd + 20 + k)
            r = 0.35 + 0.2 * _vnoise(tl * 1.3 + k, sd + 30 + k)
            a = max(0.0, 0.55 + 0.6 * _vnoise(tl * 1.7 + k * 5.0, sd + 40 + k))
            blobs.append((x, y, r, a))
        U["u_leak0"], U["u_leak1"] = blobs

    # ---- Cor da película
    U["u_film_on"] = 1 if v["cor_on"] else 0
    U["u_film_mix"] = v["cor_forca"]
    U["u_slope"] = D_SLOPE * v["contraste"]
    U["u_mid"] = v["meio_tom"]
    U["u_black"] = v["preto"]
    U["u_white"] = max(v["branco"], v["meio_tom"] + 0.05)
    U["u_ps"] = _softness_p(v["rolagem_luzes"])
    U["u_pt"] = _softness_p(v["rolagem_sombras"])
    U["u_sat"] = v["saturacao"]
    U["u_density"] = v["densidade"]
    U["u_ch_gamma"] = (v["contraste_r"], v["contraste_g"], v["contraste_b"])
    U["u_ch_offset"] = (v["offset_r"], v["offset_g"], v["offset_b"])
    U["u_shadow_tint"] = _hsv_tint(v["sombras_matiz"], v["sombras_forca"])
    U["u_high_tint"] = _hsv_tint(v["luzes_matiz"], v["luzes_forca"])
    U["u_balance"] = v["equilibrio"]
    U["u_hue"] = (math.radians(v["verdes_matiz"]), math.radians(v["azuis_matiz"]), v["pele_sat"])
    U["u_skin"] = (math.radians(v["pele_matiz"]), v["pele_luz"])
    U["u_bw"] = 1 if v["pb"] else 0
    U["u_bw_w"] = BW_WEIGHTS.get(v["pb_filtro"], BW_WEIGHTS["pan"])
    tone = TONES.get(v["virada"])
    U["u_tone_amt"] = v["virada_forca"] if (tone and v["pb"]) else 0.0
    U["u_tone_sh"], U["u_tone_hi"] = tone if tone else ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    U["u_age"] = v["envelhecimento"] if v["cor_on"] else 0.0

    # ---- Laboratório (negativo → cópia por densidade); fica dentro do colorPipe, então entra nos LUTs.
    U["u_lab_on"] = 1 if v["lab_on"] else 0
    if v["lab_on"]:
        la, lb = lab_paths_for(v)
        lights = lab_lights(v)
        _lab_uniforms(U, "u_la_", la, lights)
        # Sem processo especial o caminho B recebe uma cópia do A (não é usado: u_lab_b_on = 0).
        _lab_uniforms(U, "u_lb_", lb or la, lights)
        U["u_lab_b_on"] = 1 if lb is not None else 0
        U["u_lab_mix"] = float(v["lab_processo_forca"]) if lb is not None else 0.0
        _lab_post_uniforms(U, lab_post(v))

    pr = PRINTS.get(v["copia"])
    U["u_print_on"] = 1 if pr else 0
    if pr:
        U["u_print_amt"] = v["copia_forca"]
        U["u_pr_slope"] = D_SLOPE * pr["slope"]
        U["u_pr_mid"] = pr["mid"]
        U["u_pr_black"] = pr["black"]
        U["u_pr_white"] = pr["white"]
        U["u_pr_ps"] = _softness_p(pr["ps"])
        U["u_pr_pt"] = _softness_p(pr["pt"])
        U["u_pr_gamma"] = pr["gamma"]
        U["u_pr_offset"] = pr["offset"]
        U["u_pr_sat"] = pr["sat"]

    # ---- LUT externo
    U["u_lut_on"] = 0
    if v["lut_on"] and lut_info is not None:
        size, dmin, dmax = lut_info
        U["u_lut_on"] = 1
        U["u_lut_amt"] = v["lut_forca"]
        U["u_lut_pos"] = 1 if v["lut_posicao"] == "lugar" else 0
        U["u_lut_in"] = INPUT_IDS.get(v["lut_entrada"], 0)  # o LUT recebe o domínio da própria curva
        U["u_lut_size"] = float(size)
        U["u_lut_dmin"] = tuple(dmin)
        U["u_lut_dmax"] = tuple(dmax)
        U["u_lut_gamut"] = mat3_uniform(np.linalg.inv(gamut_to_709(INPUT_GAMUT.get(v["lut_entrada"], "709"))))
        plan.lut_path = v["lut_arquivo"]

    # ---- Grão
    U["u_grain_on"] = 0
    if v["grao_on"] and v["grao_forca"] > 0:
        size = 0.8 * v["grao_tamanho"] * gauge["grain_size"] * iso_size * scale
        net = 1.0
        if net_grain > 0:  # "Grão para redes": tamanho mínimo em pixels da saída, um pouco mais forte
            size = max(size, NET_GRAIN_MIN_PX * float(net_grain))
            net = NET_GRAIN_BOOST
        plan.grain_size = max(size, 1.0)
        plan.grain_seed = int(v["grao_semente"]) * 7919 + (frame if v["grao_animado"] else 0)
        U["u_grain_on"] = 1
        # Grão menor que 1 px some na prévia reduzida; compensa um pouco a intensidade.
        comp = min(1.0, size) ** 0.5
        push = 1.15 ** float(v["lab_revelacao"]) if v["lab_on"] else 1.0  # revelação forçada aumenta o grão
        U["u_grain_amt"] = 0.011 * v["grao_forca"] * gauge["grain_amt"] * iso_amt * comp * push * net
        U["u_grain_rough"] = v["grao_aspereza"]
        U["u_grain_chroma"] = v["grao_cor"] * (NET_GRAIN_CHROMA if net_grain > 0 else 1.0)
        U["u_grain_resp"] = (v["grao_sombras"], v["grao_meios"], v["grao_luzes"])

    # ---- Defeitos desenhados por cima
    dg = bool(v["desg_on"])
    sd = int(v["desgaste_semente"])
    U["u_dust"] = v["poeira"] if (dg and v["poeira_on"]) else 0.0
    U["u_dust_size"] = v["poeira_tamanho"]
    U["u_dust_type"] = {"escura": 0, "clara": 1, "mista": 2}[v["poeira_tipo"]]
    U["u_scratch"] = v["riscos"] if (dg and v["riscos_on"]) else 0.0
    U["u_scratch_w"] = v["riscos_largura"]
    U["u_hair"] = (0.0, 0.0, 1.0, 0.0)
    if dg and v["cabelo_on"] and v["cabelo"] > 0:
        ep = math.floor(t / 3.0)
        if _hash(ep, sd + 201) < v["cabelo"] * 0.7:
            wig = 3.0 * _vnoise(t * 9.0, sd + 202) + 1.2 * (_hash(frame, sd + 203) * 2 - 1)
            U["u_hair"] = (1.0, float(ep % 100000 + sd * 7), v["cabelo_tamanho"], wig)
    U["u_stain"] = (0.0, 0.0)
    if dg and v["manchas_on"] and v["manchas"] > 0:
        ep = frame // 3
        if _hash(ep, sd + 301) < v["manchas"] * 0.18:
            U["u_stain"] = (min(1.0, 0.5 + v["manchas"]), float(ep % 9973))
    U["u_cue"] = 0.0
    if dg and v["marcas_on"]:
        per = max(8, int(round(v["marcas_intervalo"] * fps)))
        if frame % per < 4 and frame >= 4:
            U["u_cue"] = 1.0
    U["u_splice"] = (0.0, 0.5)
    if dg and v["emenda_on"] and v["emenda"] > 0:
        ep = math.floor(t / 2.5)
        if _hash(ep, sd + 501) < v["emenda"] * 0.4:
            sf = round((ep * 2.5 + _hash(ep, sd + 502) * 2.0) * fps)
            if frame == sf:
                U["u_splice"] = (1.0, 0.15 + 0.7 * _hash(ep, sd + 503))
    U["u_dmg_on"] = 1 if (U["u_dust"] > 0 or U["u_scratch"] > 0 or U["u_hair"][0] > 0 or U["u_stain"][0] > 0
                          or U["u_cue"] > 0 or U["u_splice"][0] > 0) else 0
    U["u_frame"] = int(frame)
    U["u_seed_d"] = sd

    # ---- Scan da película
    U["u_scan_on"] = 0
    U["u_text_aspect"] = 0.0
    if v["scan_on"]:
        f = SCAN_FORMATS[scan_format(v)]
        zoom = max(1.0, v["scan_zoom"])
        x0, x1, ih, cr = f["img"]
        view_w = f["film_w"] * 1.05 / zoom
        mix_c = min(1.0, (zoom - 1.0) / 0.6)
        view_cx = f["film_w"] / 2 * (1 - mix_c) + (x0 + x1) / 2 * mix_c
        U["u_scan_on"] = 1
        U["u_scan_view"] = (f["film_w"], f["pitch"], view_w, view_cx)
        U["u_scan_img"] = (x0, x1, ih, cr)
        U["u_scan_perf"] = f["perf"]
        U["u_scan_perf2"] = (f["perf_r"], f["perf_phase"], f["perf_period"])
        U["u_scan_text"] = f["text"]
        U["u_scan_fill"] = 1 if v["scan_ajuste"] == "preencher" else 0
        U["u_scan_neighbors"] = 1 if v["scan_vizinhos"] else 0
        U["u_scan_rough"] = f["rough"]
        base = display_to_lin(v["scan_base"])
        luz = v["scan_luz"]
        if v["scan_tipo"] == "negativo":
            U["u_scan_base"] = base
            U["u_scan_light"] = (0.0004, 0.0004, 0.0005)
            U["u_scan_outside"] = (0.0003, 0.0003, 0.0004)
            U["u_scan_textcol"] = tuple(c * luz for c in display_to_lin((0.86, 0.8, 0.6)))
        else:
            U["u_scan_base"] = base
            U["u_scan_light"] = tuple(c * luz for c in (2.1, 2.0, 1.85))
            U["u_scan_outside"] = tuple(c * luz for c in (1.9, 1.85, 1.75))
            U["u_scan_textcol"] = display_to_lin((0.42, 0.24, 0.07))
        plan.edge_text = edge_text(v)

    # ---- Moldura
    asp = aspect_target(v, gauge)
    U["u_frame_on"] = 1 if (v["mold_on"] and not v["scan_on"]) else 0
    U["u_aspect_t"] = asp
    U["u_corner"] = v["cantos"]
    U["u_edge_soft"] = v["borda_suave"]
    U["u_edge_rough"] = v["borda_irregular"]
    U["u_bar_color"] = tuple(v["cor_barras"])

    U["u_mix"] = v["mix_geral"]
    U["u_dither"] = 1 if dither else 0
    return plan
