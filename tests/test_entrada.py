"""Perfis de entrada: domínio de cada curva (código de 10 bits × sinal), faixa legal × cheia, HLG e PQ.

O decodificador expande o vídeo YUV de faixa legal: o shader recebe v = (código − 64)/876 (a fração de
"IRE"). As curvas da Sony, da Panasonic e da Nikon são escritas no código de 10 bits (CV = código/1023, o
número gravado no arquivo) e voltam ao código antes da fórmula; as outras usam o próprio sinal, que o valor
expandido já é. Os números de referência vêm dos documentos dos fabricantes (citados em cada caso); as
fórmulas de referência abaixo são reescritas aqui em float64, sem depender do GLSL (a biblioteca
colour-science serviu só de conferência ao escrever os números, sem ser importada).
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pelicula import cli, look, luts, media, params, presets, resolve, sequence, shaders, timeline
from pelicula import engine as engine_mod

ROOT = Path(__file__).resolve().parents[1]
ENTRADAS = [k for k, _l in params.ENTRADAS]


# ------------------------------------------------------------------ fórmulas de referência (float64)
def slog3_enc(x):  # Sony, "Technical Summary for S-Gamut3.Cine/S-Log3 and S-Gamut3/S-Log3": CV = código/1023
    if x >= 0.01125000:
        return (420.0 + math.log10((x + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    return (x * (171.2102946929 - 95.0) / 0.01125000 + 95.0) / 1023.0


def slog3_dec(y):
    if y >= 171.2102946929 / 1023.0:
        return 10.0 ** ((y * 1023.0 - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
    return (y * 1023.0 - 95.0) * 0.01125000 / (171.2102946929 - 95.0)


def vlog_enc(x):  # Panasonic, "V-Log/V-Gamut Reference Manual": V em código/1023
    return 5.6 * x + 0.125 if x < 0.01 else 0.241514 * math.log10(x + 0.00873) + 0.598206


def vlog_dec(y):
    return (y - 0.125) / 5.6 if y < 0.181 else 10.0 ** ((y - 0.598206) / 0.241514) - 0.00873


def nlog_enc(x):  # Nikon, "N-Log Specification Document": y·1023 = 650·(x + 0,0075)^(1/3) | 150·ln(x) + 619
    return 650.0 * (x + 0.0075) ** (1.0 / 3.0) / 1023.0 if x < 0.328 else (150.0 * math.log(x) + 619.0) / 1023.0


def nlog_dec(y):
    c = y * 1023.0
    return (max(c, 0.0) / 650.0) ** 3 - 0.0075 if c < 452.0 else math.exp((c - 619.0) / 150.0)


def logc3_enc(x):  # ARRI, "ALEXA Log C Curve – Usage in VFX" (Harald Brendel), EI 800
    return 0.247190 * math.log10(5.555556 * x + 0.052272) + 0.385537 if x > 0.010591 else 5.367655 * x + 0.092809


def logc3_dec(t):
    if t > 5.367655 * 0.010591 + 0.092809:
        return (10.0 ** ((t - 0.385537) / 0.247190) - 0.052272) / 5.555556
    return (t - 0.092809) / 5.367655


_C4A = (2.0 ** 18 - 16.0) / 117.45  # ARRI, "LogC4 Logarithmic Color Space – Specification" (2022)
_C4B = (1023.0 - 95.0) / 1023.0
_C4C = 95.0 / 1023.0
_C4S = (7.0 * math.log(2.0) * 2.0 ** (7.0 - 14.0 * _C4C / _C4B)) / (_C4A * _C4B)
_C4T = (2.0 ** (14.0 * (-_C4C / _C4B) + 6.0) - 64.0) / _C4A


def logc4_enc(x):
    return (math.log2(_C4A * x + 64.0) - 6.0) / 14.0 * _C4B + _C4C if x >= _C4T else (x - _C4T) / _C4S


def logc4_dec(e):
    return (2.0 ** (14.0 * (e - _C4C) / _C4B + 6.0) - 64.0) / _C4A if e >= 0.0 else e * _C4S + _C4T


_AP = dict(R0=-0.05641088, Rt=0.01, c=47.28711236, b=0.00964052, g=0.08550479, d=0.69336945)  # "Apple Log Profile"


def apple_enc(r):
    if r >= _AP["Rt"]:
        return _AP["g"] * math.log2(r + _AP["b"]) + _AP["d"]
    return _AP["c"] * (r - _AP["R0"]) ** 2 if r >= _AP["R0"] else 0.0


def apple_dec(p):
    pt = _AP["c"] * (_AP["Rt"] - _AP["R0"]) ** 2
    if p >= pt:
        return 2.0 ** ((p - _AP["d"]) / _AP["g"]) - _AP["b"]
    return math.sqrt(p / _AP["c"]) + _AP["R0"] if p >= 0.0 else _AP["R0"]


_G5 = dict(A=0.08692876065491224, B=0.005494072432257808, C=0.5300133392291939, D=8.283605932402494,
           E=0.09246575342465753)  # Blackmagic, "Blackmagic Generation 5 Color Science"


def bmd5_enc(x):
    return _G5["D"] * x + _G5["E"] if x < 0.005 else _G5["A"] * math.log(x + _G5["B"]) + _G5["C"]


def bmd5_dec(y):
    if y < _G5["D"] * 0.005 + _G5["E"]:
        return (y - _G5["E"]) / _G5["D"]
    return math.exp((y - _G5["C"]) / _G5["A"]) - _G5["B"]


def di_enc(x):  # Blackmagic, "DaVinci Resolve Wide Gamut Intermediate" (DaVinci Intermediate)
    return x * 10.44426855 if x <= 0.00262409 else (math.log2(x + 0.0075) + 7.0) * 0.07329248


def di_dec(y):
    return y / 10.44426855 if y <= 0.02740668 else 2.0 ** (y / 0.07329248 - 7.0) - 0.0075


def l3g10_enc(x):  # RED, "White Paper on REDWideGamutRGB and Log3G10"
    v = x + 0.01
    return 0.224282 * math.log10(v * 155.975327 + 1.0) if v >= 0.0 else v * 15.1927


def l3g10_dec(y):
    return (10.0 ** (y / 0.224282) - 1.0) / 155.975327 - 0.01 if y >= 0.0 else y / 15.1927 - 0.01


_CIN_BLACK = 10.0 ** ((95.0 - 685.0) / 300.0)  # Kodak Cineon: branco 685, preto 95, 300 códigos por década


def cineon_enc(x):
    return (685.0 + 300.0 * math.log10(x * (1.0 - _CIN_BLACK) + _CIN_BLACK)) / 1023.0


def cineon_dec(y):
    return (10.0 ** ((y * 1023.0 - 685.0) / 300.0) - _CIN_BLACK) / (1.0 - _CIN_BLACK)


# ITU-R BT.2100 (HLG) e BT.2408 (níveis de referência): cinza 18% em 38% do sinal, branco de referência em 75%.
_HA, _HB, _HC = 0.17883277, 0.28466892, 0.55991073
_HLG_K = 0.18 / (0.38 ** 2 / 3.0)


def hlg_dec(e):
    e_scene = e * abs(e) / 3.0 if e <= 0.5 else (math.exp((e - _HC) / _HA) + _HB) / 12.0
    return e_scene * _HLG_K


def hlg_enc(x):
    e = x / _HLG_K
    return math.copysign(math.sqrt(3.0 * abs(e)), e) if e <= 1.0 / 12.0 else _HA * math.log(12.0 * e - _HB) + _HC


# SMPTE ST 2084 (PQ) → luz da tela; OOTF inversa do HLG a 1000 cd/m² (γ = 1,2, BT.2100/BT.2408).
_M1, _M2, _C1, _C2, _C3 = 2610 / 16384, 2523 / 4096 * 128, 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
_W2020 = np.array([0.2627, 0.6780, 0.0593])


def pq_eotf(e):
    """E′ → cd/m²."""
    p = max(e, 0.0) ** (1.0 / _M2)
    return 10000.0 * (max(p - _C1, 0.0) / (_C2 - _C3 * p)) ** (1.0 / _M1)


def pq_inv_eotf(nits):
    y = (nits / 10000.0) ** _M1
    return ((_C1 + _C2 * y) / (1.0 + _C3 * y)) ** _M2


def pq_dec3(rgb):
    f = np.array([pq_eotf(float(c)) for c in rgb]) / 1000.0
    y = max(float(f @ _W2020), 1e-10)
    return f * y ** (-1.0 / 6.0) * _HLG_K


def pq_enc3(rgb):
    s = np.maximum(np.asarray(rgb, dtype=np.float64) / _HLG_K, 0.0)
    y = max(float(s @ _W2020), 1e-10)
    return np.array([pq_inv_eotf(1000.0 * float(c)) for c in s * y ** 0.2])


CURVES = {  # perfil: (codificar, decodificar) da luz linear (canal a canal) para o valor da fórmula
    "slog3": (slog3_enc, slog3_dec), "vlog": (vlog_enc, vlog_dec), "nlog": (nlog_enc, nlog_dec),
    "logc3": (logc3_enc, logc3_dec), "logc4": (logc4_enc, logc4_dec), "applelog": (apple_enc, apple_dec),
    "bmd_gen5": (bmd5_enc, bmd5_dec), "dwg": (di_enc, di_dec), "log3g10": (l3g10_enc, l3g10_dec),
    "cineon": (cineon_enc, cineon_dec), "hlg": (hlg_enc, hlg_dec),
}


def legal(code10: float) -> float:
    """Código de 10 bits de um arquivo de faixa legal → valor que o decodificador entrega (expandido)."""
    return (code10 - 64.0) / 876.0


# ------------------------------------------------------------------ domínio declarado
def test_every_profile_declares_its_domain():
    assert set(look.INPUT_DOMAIN) == set(look.INPUT_IDS) == set(ENTRADAS)
    assert set(look.INPUT_DOMAIN.values()) <= {"cv", "sinal"}
    # Sony, Panasonic e Nikon gravam o código da fórmula direto no arquivo de faixa legal.
    assert {e for e in ENTRADAS if look.code_value_curve(e)} == {"slog3", "vlog", "nlog"}
    assert set(params.PARAMS["lut_entrada"].choices[i][0] for i in range(len(params.LUT_ENTRADAS))) <= set(ENTRADAS)


def test_new_profiles_keep_the_old_ids():
    old = {"rec709": 0, "linear": 1, "nlog": 2, "slog3": 3, "logc3": 4, "vlog": 5, "cineon": 6, "dwg": 7,
           "log3g10": 8, "bmd_gen5": 9, "logc4": 10, "applelog": 11}
    assert {k: look.INPUT_IDS[k] for k in old} == old
    assert look.INPUT_IDS["hlg"] == 12 and look.INPUT_IDS["pq"] == 13
    assert ENTRADAS[-2:] == ["hlg", "pq"] and look.INPUT_GAMUT["hlg"] == look.INPUT_GAMUT["pq"] == "2020"


@pytest.mark.parametrize("entrada", ENTRADAS)
@pytest.mark.parametrize("is_legal", [True, False])
def test_plan_sends_the_range_and_the_domain(entrada, is_legal):
    v = dict(params.defaults(), entrada=entrada)
    U = look.build_plan(v, 64, 36, 0, 24.0, legal=is_legal).uniforms
    assert U["u_legal"] == int(is_legal)
    assert U["u_input_cv"] == int(look.code_value_curve(entrada))
    # log que a câmera já mandou reescalado para a faixa legal (HDMI "Limited"): sem volta ao código
    U = look.build_plan(dict(v, log_reescalado=True), 64, 36, 0, 24.0, legal=is_legal).uniforms
    assert U["u_input_cv"] == 0
    assert look.build_plan(params.defaults(), 64, 36, 0, 24.0).uniforms["u_legal"] == 1  # padrão: vídeo comum
    assert params.PARAMS["log_reescalado"].default is False and "log_reescalado" in presets.SOURCE_KEYS


def test_shader_and_plugin_constants_follow_look():
    src = shaders.COMMON
    for name, value in (("HLG_A", look.HLG_A), ("HLG_B", look.HLG_B), ("HLG_C", look.HLG_C),
                        ("HLG_K", look.HLG_SCALE), ("PQ_M1", look.PQ_M1), ("PQ_M2", look.PQ_M2),
                        ("PQ_C1", look.PQ_C1), ("PQ_C2", look.PQ_C2), ("PQ_C3", look.PQ_C3)):
        line = next(ln for ln in src.splitlines() if ln.startswith(f"const float {name} ="))
        assert float(line.split("=")[1].strip().rstrip(";")) == pytest.approx(value, rel=1e-8), name
        m = re.search(rf"#define PC_{name} (\S+)f\n", resolve.source("cor"))
        assert m and float(m.group(1)) == pytest.approx(value, rel=1e-8), name  # o plugin do Resolve
    assert look.HLG_SCALE == pytest.approx(_HLG_K) and look.HLG_B == pytest.approx(_HB)
    assert look.HLG_C == pytest.approx(_HC, abs=1e-8)


# ------------------------------------------------------------------ pontos de referência dos documentos
def test_sony_slog3_reference_points():
    # preto 95, cinza 18% = 420 (41% IRE), branco 90% = 598 (61% IRE), em código de 10 bits
    assert slog3_enc(0.0) * 1023 == pytest.approx(95.0, abs=0.01)
    assert slog3_enc(0.18) * 1023 == pytest.approx(420.0, abs=0.01)
    assert slog3_enc(0.90) * 1023 == pytest.approx(598.0, abs=0.15)
    assert legal(420) == pytest.approx(0.4064, abs=1e-4) and legal(598) == pytest.approx(0.6096, abs=1e-4)


def test_panasonic_vlog_reference_points():
    # cinza 18% = 433 (42% IRE), branco 90% = 602 (61%), preto 128 (7,3%)
    assert vlog_enc(0.18) * 1023 == pytest.approx(433.0, abs=0.1)
    assert vlog_enc(0.90) * 1023 == pytest.approx(602.0, abs=0.35)
    assert vlog_enc(0.0) * 1023 == pytest.approx(128.0, abs=0.15)


def test_nikon_nlog_reference_points():
    # fórmula no código de 10 bits; cinza 18% ≈ 372 (35% IRE), branco 90% ≈ 603 (61,5% IRE)
    assert nlog_enc(0.18) * 1023 == pytest.approx(372.0, abs=0.1)
    assert nlog_enc(0.90) * 1023 == pytest.approx(603.2, abs=0.1)
    assert nlog_dec(nlog_enc(0.18)) == pytest.approx(0.18)


def test_signal_curves_reference_points():
    assert logc3_enc(0.18) == pytest.approx(0.391007, abs=1e-6)          # ARRI: cinza 18% em 400/1023 (EI 800)
    assert logc4_enc(0.18) == pytest.approx(0.278396, abs=1e-6)          # ARRI LogC4: cinza 18%
    assert logc4_enc(0.0) == pytest.approx(95.0 / 1023.0, abs=1e-9)      # preto da LogC4
    assert apple_enc(0.18) == pytest.approx(0.488272, abs=1e-5)          # Apple Log: cinza 18%
    assert 64 + 876 * bmd5_enc(0.18) == pytest.approx(400.0, abs=0.01)   # Gen 5: cinza no código 400 de 64–940
    assert di_enc(0.18) == pytest.approx(0.336043, abs=1e-6)             # DaVinci Intermediate
    assert l3g10_enc(0.18) == pytest.approx(1.0 / 3.0, abs=1e-6)         # RED: cinza 18% em 1/3
    assert cineon_enc(1.0) * 1023 == pytest.approx(685.0) and cineon_enc(0.0) * 1023 == pytest.approx(95.0)


def test_hlg_and_pq_reference_points():
    # BT.2408: cinza 18% = 38% HLG = 26 cd/m² PQ (38% PQ); branco de referência = 75% HLG = 203 cd/m² (58% PQ)
    assert hlg_dec(0.38) == pytest.approx(0.18)
    assert hlg_dec(0.75) == pytest.approx(0.9909, abs=2e-4)
    assert hlg_dec(0.5) == pytest.approx(_HLG_K / 12.0, rel=1e-5)        # ponto de troca da OETF
    assert pq_inv_eotf(26.0) == pytest.approx(0.38, abs=1e-3)
    assert pq_inv_eotf(203.0) == pytest.approx(0.58, abs=1e-3)
    assert pq_inv_eotf(1000.0) == pytest.approx(0.7518, abs=1e-4)
    assert pq_eotf(1.0) == pytest.approx(10000.0)
    gray = pq_dec3([pq_inv_eotf(26.0)] * 3)
    assert gray[0] == pytest.approx(0.18, abs=0.002)                      # 26 cd/m² ≈ cinza do app
    white = pq_dec3([pq_inv_eotf(203.0)] * 3)
    assert white[0] == pytest.approx(hlg_dec(0.75), rel=2e-3)            # 203 cd/m² = branco do HLG
    # PQ → HLG da BT.2408: 26 cd/m² em PQ é o mesmo cinza que 38% em HLG
    assert hlg_enc(gray[0]) == pytest.approx(0.38, abs=0.003)


# ------------------------------------------------------------------ shaders na GPU
PROBE = shaders.COMMON + """
uniform sampler2D t_x;
uniform int u_id;
uniform int u_cv;
uniform int u_mode;
void main() {
    vec3 x = texelFetch(t_x, ivec2(gl_FragCoord.xy), 0).rgb;
    f_out = vec4(u_mode == 0 ? toLinear(x, u_id, u_cv == 1) : lutEncode(x, u_id), 1.0);
}
"""


class Probe:
    """Roda toLinear / lutEncode do shaders.COMMON sobre valores quaisquer (float32), no contexto dos testes."""

    def __init__(self, eng):
        self.ctx = eng.ctx
        self.prog = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=PROBE)
        self.vao = self.ctx.vertex_array(self.prog, [(eng.vbo, "2f", "in_pos")])
        self.prog["u_lut_gamut"].value = look.mat3_uniform(np.eye(3))

    def run(self, x, entrada: str, cv: bool = False, encode: bool = False) -> np.ndarray:
        import moderngl
        a = np.asarray(x, dtype=np.float32)
        a = np.repeat(a[:, None], 3, axis=1) if a.ndim == 1 else a
        n = a.shape[0]
        tex = self.ctx.texture((n, 1), 3, data=np.ascontiguousarray(a).tobytes(), dtype="f4")
        out = self.ctx.texture((n, 1), 4, dtype="f4")
        fbo = self.ctx.framebuffer([out])
        try:
            tex.use(0)
            self.prog["t_x"].value = 0
            self.prog["u_id"].value = look.INPUT_IDS[entrada]
            self.prog["u_cv"].value = int(cv)
            self.prog["u_mode"].value = int(encode)
            fbo.use()
            self.vao.render(moderngl.TRIANGLE_STRIP)
            data = fbo.read(components=3, dtype="f4")
        finally:
            fbo.release()
            out.release()
            tex.release()
        return np.frombuffer(data, np.float32).reshape(n, 3).astype(np.float64)


@pytest.fixture(scope="module")
def probe(gl_engine):
    return Probe(gl_engine)


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", sorted(CURVES))
def test_shader_curves_match_the_reference_formulas(probe, entrada):
    enc, dec = CURVES[entrada]
    xs = np.linspace(-0.05, 1.05, 221)
    got = probe.run(xs, entrada, cv=False)[:, 0]
    want = np.array([dec(float(x)) for x in xs])
    np.testing.assert_allclose(got, want, rtol=2e-4, atol=2e-6)
    lin = np.array([0.0005, 0.002, 0.01, 0.05, 0.18, 0.5, 0.9, 2.0, 8.0])
    got = probe.run(lin, entrada, cv=False, encode=True)[:, 0]
    np.testing.assert_allclose(got, [enc(float(v)) for v in lin], rtol=1e-5, atol=2e-6)


@pytest.mark.gpu
def test_pq_shader_matches_the_reference(probe):
    rng = np.random.default_rng(3)
    e = np.concatenate([np.repeat(np.linspace(0.0, 1.0, 41)[:, None], 3, axis=1), rng.random((40, 3))])
    got = probe.run(e, "pq", cv=False)
    want = np.array([pq_dec3(c) for c in e])
    np.testing.assert_allclose(got, want, rtol=5e-4, atol=1e-6)
    lin = np.abs(want) + 1e-4
    np.testing.assert_allclose(probe.run(lin, "pq", cv=False, encode=True), np.array([pq_enc3(c) for c in lin]),
                               rtol=2e-4, atol=2e-5)


@pytest.mark.gpu
def test_legal_range_code_value_curves(probe):
    """S-Log3 de faixa legal: o código 420 chega como 0,4064 e é o cinza 18%; o 598 é o branco 90%."""
    got = probe.run([legal(420), legal(598), legal(95)], "slog3", cv=True)[:, 0]
    np.testing.assert_allclose(got, [0.18, 0.90, 0.0], rtol=1.5e-3, atol=2e-4)  # 598 é o 597,9 arredondado
    # lido como se fosse o código (o erro corrigido): cinza ~0,05 stop escuro, branco ~0,3 stop claro
    wrong = probe.run([legal(420), legal(598)], "slog3", cv=False)[:, 0]
    assert math.log2(wrong[0] / 0.18) == pytest.approx(-0.05, abs=0.02)
    assert math.log2(wrong[1] / 0.90) == pytest.approx(0.30, abs=0.05)
    # faixa cheia: o arquivo já tem o código (420/1023) e nada muda
    np.testing.assert_allclose(probe.run([420 / 1023, 598 / 1023], "slog3", cv=False)[:, 0], [0.18, 0.90],
                               rtol=1.5e-3)
    # V-Log e N-Log da mesma forma
    np.testing.assert_allclose(probe.run([legal(433), legal(602)], "vlog", cv=True)[:, 0], [0.18, 0.90],
                               rtol=4e-3)  # 433 e 602 são os 433,05 e 601,7 arredondados do manual
    np.testing.assert_allclose(probe.run([legal(nlog_enc(0.18) * 1023)], "nlog", cv=True)[:, 0], [0.18],
                               rtol=1e-3)


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", sorted(CURVES))
def test_every_curve_reads_the_expanded_value_in_its_domain(probe, entrada):
    """Arquivo de faixa legal com o cinza 18% gravado pela câmera → 0,18 no app (código ou sinal)."""
    enc, _dec = CURVES[entrada]
    cv_domain = look.code_value_curve(entrada)
    code10 = enc(0.18) * 1023 if cv_domain else 64 + 876 * enc(0.18)  # o que a câmera grava no arquivo
    got = probe.run([legal(code10)], entrada, cv=cv_domain)[0, 0]
    assert got == pytest.approx(0.18, rel=1e-3)


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", [e for e in ENTRADAS if e != "rec709"])
def test_lut_encode_uses_the_curve_domain(probe, entrada):
    """O LUT externo recebe o valor no domínio da curva: o código da câmera no S-Log3/V-Log/N-Log (como os
    LUTs dos fabricantes, "Full"), o sinal nas outras; vindo de um arquivo de faixa legal ou cheia."""
    cv = look.code_value_curve(entrada)
    v = np.linspace(0.05, 0.95, 37)
    lin = probe.run(v, entrada, cv=cv)                 # arquivo de faixa legal → luz
    back = probe.run(lin, entrada, encode=True)[:, 0]  # luz → valor do LUT
    np.testing.assert_allclose(back, (v * 876 + 64) / 1023 if cv else v, atol=5e-5)
    lin = probe.run(v, entrada, cv=False)              # faixa cheia (ou o próprio código): ida e volta exata
    np.testing.assert_allclose(probe.run(lin, entrada, encode=True)[:, 0], v, atol=5e-5)


@pytest.mark.gpu
def test_slog3_lut_sees_the_sony_code_values(probe):
    """Cinza e branco de um S-Log3 de faixa legal chegam ao LUT como 420/1023 e 598/1023 (LUT da Sony)."""
    lin = probe.run([legal(420), legal(598)], "slog3", cv=True)
    np.testing.assert_allclose(probe.run(lin, "slog3", encode=True)[:, 0], [420 / 1023, 598 / 1023], atol=2e-5)


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", ENTRADAS)
def test_no_nan_for_any_input(probe, entrada):
    x = np.linspace(-0.2, 1.2, 141)
    for cv in (False, True):
        lin = probe.run(x, entrada, cv=cv)
        assert np.isfinite(lin).all(), entrada
        enc = probe.run(np.linspace(-0.5, 40.0, 141), entrada, cv=cv, encode=True)
        assert np.isfinite(enc).all(), entrada
    assert np.all(np.diff(probe.run(np.linspace(0.0, 1.1, 111), entrada, cv=False)[:, 1]) >= -1e-5)


@pytest.mark.gpu
def test_hdr_curves_on_the_gpu(probe):
    hlg = probe.run([0.38, 0.75, 1.0], "hlg", cv=False)[:, 0]
    np.testing.assert_allclose(hlg, [0.18, hlg_dec(0.75), _HLG_K], rtol=2e-5)
    pq = probe.run([pq_inv_eotf(26.0), pq_inv_eotf(203.0), pq_inv_eotf(1000.0), 1.0], "pq", cv=False)[:, 0]
    np.testing.assert_allclose(pq, [0.1786, 0.9902, _HLG_K, 25.478], rtol=1e-3)
    # acima de 1000 cd/m² a luz continua subindo, sem corte nem NaN
    assert pq[3] > pq[2] > pq[1]


# ------------------------------------------------------------------ o quadro inteiro e o LUT
def _render(eng, value, entrada, is_legal, values=None):
    img = np.full((4, 8, 3), int(round(value * 65535)), dtype=np.uint16)
    v = dict(values or presets.builtin_values("original"), entrada=entrada)
    eng.set_input(img)
    out = eng.render(look.build_plan(v, 8, 4, 0, 24.0, None, dither=False, legal=is_legal), 16)
    return out[1, 3].astype(np.float64) / 65535.0


@pytest.mark.gpu
def test_slog3_gray_card_through_the_whole_pipeline(gl_engine):
    """O cinza do S-Log3 (código 420) sai no cinza neutro do app (0,45) em faixa legal e em faixa cheia."""
    np.testing.assert_allclose(_render(gl_engine, legal(420), "slog3", True), look.D_MID, atol=2e-4)
    np.testing.assert_allclose(_render(gl_engine, 420 / 1023, "slog3", False), look.D_MID, atol=2e-4)
    # o mesmo arquivo de faixa legal lido sem a correção sai mais escuro
    assert _render(gl_engine, legal(420), "slog3", False)[0] < look.D_MID - 0.002
    # perfis de sinal não dependem da faixa: o valor expandido já é a entrada da curva
    for e in ("logc3", "logc4", "applelog", "hlg"):
        a, b = _render(gl_engine, 0.42, e, True), _render(gl_engine, 0.42, e, False)
        np.testing.assert_array_equal(a, b)


@pytest.mark.gpu
def test_bake_lut_uses_the_curve_domain_by_default(gl_engine):
    """LUT exportado: a entrada é o valor no domínio da curva (código de 10 bits no S-Log3), como os LUTs
    dos fabricantes; `legal=True` é o clipe de faixa legal expandido (padrão do plugin do Resolve)."""
    v = dict(presets.builtin_values("original"), entrada="slog3")
    native = gl_engine.bake_lut(v, 9)
    np.testing.assert_array_equal(native, gl_engine.bake_lut(v, 9, legal=False))
    assert np.abs(native - gl_engine.bake_lut(v, 9, legal=True)).max() > 0.01
    v["entrada"] = "logc3"
    np.testing.assert_array_equal(gl_engine.bake_lut(v, 9), gl_engine.bake_lut(v, 9, legal=True))


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", ["slog3", "vlog", "nlog", "logc3", "applelog", "hlg", "pq"])
def test_exported_lut_reads_back_as_the_same_profile(gl_engine, tmp_path, entrada):
    """LUT exportado com entrada X e usado como LUT externo que espera X: o mesmo domínio dos dois lados."""
    n = 33
    base = presets.builtin_values("original")
    data = gl_engine.bake_lut(dict(base, entrada=entrada), n)  # entrada = valor no domínio da curva
    path = str(tmp_path / f"{entrada}.cube")
    luts.save_cube(path, data, n, entrada)
    # As luzes que caem nos nós do eixo cinza do LUT: o caminho de volta tem que achar o mesmo nó.
    nodes = [10, 13, 16, 19]
    want = data.reshape(n, n, n, 3)[nodes, nodes, nodes]
    vals = dict(base, entrada="linear", lut_on=True, lut_arquivo=path, lut_posicao="lugar", lut_entrada=entrada)
    info = engine_mod.lut_info(path)
    for k, node in enumerate(nodes):
        code = node / (n - 1)
        lin = (pq_dec3([code] * 3)[0] if entrada == "pq" else CURVES[entrada][1](code))
        if not 0.0 < lin < 1.0:
            continue  # a entrada "linear" de 16 bits só guarda 0..1
        img = np.full((2, 2, 3), int(round(lin * 65535)), dtype=np.uint16)
        gl_engine.set_input(img)
        out = gl_engine.render(look.build_plan(vals, 2, 2, 0, 24.0, info, dither=False), 16)[0, 0] / 65535.0
        np.testing.assert_allclose(out, want[k], atol=1.5e-3, err_msg=f"{entrada} nó {node}")


# ------------------------------------------------------------------ faixa do arquivo e da montagem
@pytest.mark.parametrize("over, expected", [
    (dict(pix_fmt="yuv420p", color_range="tv"), True),
    (dict(pix_fmt="yuv420p10le", color_range=""), True),
    (dict(pix_fmt="p010le", color_range="unknown"), True),
    (dict(pix_fmt="yuv422p10le", color_range="pc"), False),
    (dict(pix_fmt="yuvj420p", color_range=""), False),
    (dict(pix_fmt="rgb48le", color_range=""), False),
    (dict(pix_fmt="gbrp10le", color_range="tv"), False),
    (dict(pix_fmt="gbrapf32le", color_range="", is_image=True), False),
])
def test_media_legal_range(make_info, over, expected):
    assert media.legal_range(make_info(**over)) is expected


def _src(path, color_range="tv", pix="yuv420p10le", image=False, transfer="bt709"):
    return timeline.Source(path=path, width=1920, height=1080, fps=24.0, fps_str="24/1", frames=48, duration=2.0,
                           is_image=image, pix_fmt=pix, color_range=color_range, color_transfer=transfer)


def _seq(*sources):
    seq = timeline.Sequence()
    for s in sources:
        seq.insert_media(s)
    return seq


def test_sequence_range_follows_the_video_clips():
    assert sequence.legal_range(timeline.Sequence()) is True
    assert sequence.legal_range(_seq(_src("a.mov"))) is True
    assert sequence.legal_range(_seq(_src("a.mov", "pc"))) is False
    # imagens (RGB, faixa cheia) não decidem quando há vídeo
    assert sequence.legal_range(_seq(_src("t.png", "", "rgb24", image=True), _src("a.mov"))) is True
    assert sequence.legal_range(_seq(_src("t.png", "", "rgb24", image=True))) is False
    # maioria dos clipes de vídeo; empate = o primeiro
    assert sequence.legal_range(_seq(_src("a.mov", "pc"), _src("b.mov"), _src("c.mov"))) is True
    assert sequence.legal_range(_seq(_src("a.mov", "pc"), _src("b.mov"))) is False


# ------------------------------------------------------------------ detecção do HDR e presets
@pytest.mark.parametrize("transfer, expected", [("arib-std-b67", "hlg"), ("smpte2084", "pq"), ("SMPTE2084", "pq"),
                                                ("bt709", None), ("", None), ("unknown", None)])
def test_detect_profile(make_info, transfer, expected):
    assert media.detect_profile(make_info(color_transfer=transfer)) == expected


@pytest.mark.parametrize("current, transfer, expected", [
    ("rec709", "arib-std-b67", "hlg"),   # vídeo HDR do celular
    ("rec709", "smpte2084", "pq"),
    ("rec709", "bt709", None),           # nada a fazer
    ("hlg", "bt709", "rec709"),          # o próximo arquivo não é HDR: volta ao padrão
    ("hlg", "smpte2084", "pq"),
    ("pq", "smpte2084", None),
    ("slog3", "arib-std-b67", None),     # perfil log escolhido à mão nunca muda
    ("applelog", "bt709", None),
])
def test_auto_profile(make_info, current, transfer, expected):
    assert media.auto_profile(current, make_info(color_transfer=transfer)) == expected


def test_presets_do_not_change_the_input_profile():
    cur = dict(params.defaults(), entrada="nlog", log_reescalado=True, exposicao=0.4)
    vals = presets.with_source(presets.builtin_values("vision3_500t"), cur)
    assert vals["entrada"] == "nlog" and vals["log_reescalado"] is True
    assert vals["exposicao"] == presets.builtin_values("vision3_500t")["exposicao"]  # o resto é do preset
    assert presets.with_source(presets.builtin_values("vision3_500t"), None)["entrada"] == "rec709"
    assert presets.same_look(presets.builtin_values("vision3_500t"), vals)
    assert not presets.same_look(presets.builtin_values("vision3_250d"), vals)
    assert not presets.same_look(None, vals)


def test_cli_detects_hdr_only_without_an_explicit_profile(make_info):
    hlg = make_info(color_transfer="arib-std-b67")
    v = presets.builtin_values("vision3_250d")
    assert cli.auto_input_profile(v, ["grao_forca=1"], hlg) == "hlg" and v["entrada"] == "hlg"
    v = dict(presets.builtin_values("vision3_250d"), entrada="rec709")
    assert cli.auto_input_profile(v, ["entrada=rec709"], hlg) is None and v["entrada"] == "rec709"
    v = dict(params.defaults(), entrada="slog3")
    assert cli.auto_input_profile(v, None, hlg) is None and v["entrada"] == "slog3"
    # um preset aplicado a um projeto mantém o perfil do projeto
    values, _pid = cli.build_values(dict(params.defaults(), entrada="vlog"), "vision3_500t", [])
    assert values["entrada"] == "vlog"


# ------------------------------------------------------------------ de ponta a ponta (ffmpeg)
def _hdr_clip(ffmpeg: str, path: Path, transfer: str, primaries: str = "bt2020", matrix: str = "bt2020nc") -> str:
    """Vídeo curto com as marcas de cor pedidas (como um vídeo HDR de celular: HLG, BT.2020, faixa legal)."""
    tags = f"setparams=color_trc={transfer}:color_primaries={primaries}:colorspace={matrix}:range=tv"
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=0.5",
           "-vf", tags, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        pytest.skip("não foi possível gerar o vídeo de teste: " + res.stderr.decode("utf-8", "replace"))
    return str(path)


@pytest.mark.ffmpeg
def test_probe_reads_the_hdr_transfer(ffmpeg_ok, tmp_path):
    hlg = media.probe(_hdr_clip(ffmpeg_ok, tmp_path / "hlg.mp4", "arib-std-b67"))
    pq = media.probe(_hdr_clip(ffmpeg_ok, tmp_path / "pq.mp4", "smpte2084"))
    assert media.detect_profile(hlg) == "hlg" and media.detect_profile(pq) == "pq"
    assert media.legal_range(hlg) and media.legal_range(pq)
    src = media.probe_source(str(tmp_path / "hlg.mp4"))
    assert media.detect_profile(src) == "hlg" and media.legal_range(src)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_cli_frame_reports_the_detected_profile(gl_engine, ffmpeg_ok, tmp_path, capsys, monkeypatch):
    from pelicula import i18n
    monkeypatch.setenv("PELICULA_LANG", "pt_BR")  # o terminal escolhe o idioma; o resto da suíte é em português
    clip = _hdr_clip(ffmpeg_ok, tmp_path / "celular.mp4", "arib-std-b67")
    try:
        assert cli.main(["quadro", clip, "-o", str(tmp_path / "q.png"), "--tempo", "#2"]) == 0
        err = capsys.readouterr().err
        assert "hlg" in err and "--set entrada" in err
        assert cli.main(["quadro", clip, "-o", str(tmp_path / "r.png"), "--set", "entrada=rec709"]) == 0
        assert "--set entrada" not in capsys.readouterr().err
    finally:
        gl_engine.ctx.__enter__()  # `quadro` cria e libera um contexto próprio nesta thread
        i18n.set_language("pt_BR")


_GUI = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
hlg, sdr = sys.argv[2], sys.argv[3]
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula.ui import prefs
st = prefs.settings()
st.setValue("auto_update", "false")
st.setValue("language", "pt_BR")
from pelicula.ui.main_window import MainWindow

def pump(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

win = MainWindow()
win.resize(1200, 800)
win.show()
win.confirm_discard = lambda: True  # sem a pergunta "Salvar projeto?" (modal) entre um arquivo e outro
win.apply_preset("vision3_250d")
assert win.store.get("entrada") == "rec709"
win.handle_files([hlg])
assert pump(lambda: win.cur is not None), "o quadro não chegou"
assert win.store.get("entrada") == "hlg", win.store.get("entrada")
assert "HDR" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
assert win._source_legal() is True
win.apply_preset("vision3_500t")              # o preset muda o look, não o perfil
assert win.store.get("entrada") == "hlg"
assert not win.mod_label.isVisibleTo(win), "preset recém-aplicado não está modificado"
win.store.undo()                               # desfaz o preset
win.store.undo()                               # desfaz a detecção
assert win.store.get("entrada") == "rec709", win.store.get("entrada")
win.store.set("entrada", "hlg")
win.store.commit()
win.handle_files([sdr])                        # arquivo sem HDR: volta para Rec.709
assert win.store.get("entrada") == "rec709"
win.store.set("entrada", "slog3")
win.store.commit()
win.handle_files([hlg])                        # perfil log escolhido à mão não muda
assert win.store.get("entrada") == "slog3"
win.new_project()                              # projeto novo: tudo no padrão
assert win.store.get("entrada") == "rec709"
win.set_mode("edicao")
win.import_paths([hlg])                        # primeiro clipe numa montagem vazia
assert win.store.get("entrada") == "hlg", win.store.get("entrada")
assert "HDR" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
print("OK")
app.exit(0)
'''


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_main_window_detects_hdr_and_presets_keep_it(gl_engine, ffmpeg_ok, tmp_path):
    hlg = _hdr_clip(ffmpeg_ok, tmp_path / "hlg.mp4", "arib-std-b67")
    sdr = _hdr_clip(ffmpeg_ok, tmp_path / "sdr.mp4", "bt709", "bt709", "bt709")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PELICULA_SETTINGS_DIR=str(tmp_path / "cfg"),
               APPDATA=str(tmp_path / "appdata"), PELICULA_LANG="pt_BR")
    res = subprocess.run([sys.executable, "-c", _GUI, str(ROOT), hlg, sdr], cwd=str(ROOT), env=env,
                         capture_output=True, timeout=180)
    out = res.stdout.decode("utf-8", "replace")
    assert res.returncode == 0 and "OK" in out, res.stderr.decode("utf-8", "replace")[-3000:] + out[-1000:]
