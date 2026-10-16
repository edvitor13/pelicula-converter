"""Converte os parâmetros da interface em valores para o motor (uniforms).

Tudo o que muda quadro a quadro (tremor, cintilação, vazamento de luz, semente
do grão) é calculado aqui a partir do número do quadro, então a prévia e a
exportação geram exatamente o mesmo resultado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Curva neutra usada para levar vídeo Rec.709 até a luz da cena e de volta.
D_SLOPE = 0.155
D_MID = 0.45
D_P = 4.0

INPUT_IDS = {"rec709": 0, "linear": 1, "nlog": 2, "slog3": 3, "logc3": 4, "vlog": 5, "cineon": 6, "dwg": 7,
             "log3g10": 8}

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
}
_D65 = (0.3127, 0.3290)
INPUT_GAMUT = {"rec709": "709", "linear": "709", "cineon": "709", "nlog": "2020",
               "slog3": "sgamut3cine", "logc3": "awg3", "vlog": "vgamut", "dwg": "dwg", "log3g10": "rwg"}


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
               lut_info: tuple | None = None, dither: bool = True) -> Plan:
    """Monta todos os valores do quadro `frame` para uma imagem width x height."""
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
    sig_g = gauge["blur"] * v["bitola_resolucao"]
    sig_u = (v["raio_maciez"] * v["maciez"] * 2.0) if lente else 0.0
    soft = math.sqrt(sig_g ** 2 + sig_u ** 2) * scale
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
    U["u_bw"] = 1 if v["pb"] else 0
    U["u_bw_w"] = BW_WEIGHTS.get(v["pb_filtro"], BW_WEIGHTS["pan"])
    tone = TONES.get(v["virada"])
    U["u_tone_amt"] = v["virada_forca"] if (tone and v["pb"]) else 0.0
    U["u_tone_sh"], U["u_tone_hi"] = tone if tone else ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    U["u_age"] = v["envelhecimento"] if v["cor_on"] else 0.0

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
        U["u_lut_in"] = INPUT_IDS.get(v["lut_entrada"], 0)
        U["u_lut_size"] = float(size)
        U["u_lut_dmin"] = tuple(dmin)
        U["u_lut_dmax"] = tuple(dmax)
        U["u_lut_gamut"] = mat3_uniform(np.linalg.inv(gamut_to_709(INPUT_GAMUT.get(v["lut_entrada"], "709"))))
        plan.lut_path = v["lut_arquivo"]

    # ---- Grão
    U["u_grain_on"] = 0
    if v["grao_on"] and v["grao_forca"] > 0:
        size = 0.8 * v["grao_tamanho"] * gauge["grain_size"] * iso_size * scale
        plan.grain_size = max(size, 1.0)
        plan.grain_seed = int(v["grao_semente"]) * 7919 + (frame if v["grao_animado"] else 0)
        U["u_grain_on"] = 1
        # Grão menor que 1 px some na prévia reduzida; compensa um pouco a intensidade.
        comp = min(1.0, size) ** 0.5
        U["u_grain_amt"] = 0.011 * v["grao_forca"] * gauge["grain_amt"] * iso_amt * comp
        U["u_grain_rough"] = v["grao_aspereza"]
        U["u_grain_chroma"] = v["grao_cor"]
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
