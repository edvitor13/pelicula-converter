"""Grão e textura da 1.6 (`pelicula/grao.py`, ARQUITETURA §30): o que cada ajuste novo faz quando ligado.

A neutralidade (padrão = BASE bit a bit) fica em `tests/test_grao.py`; aqui ficam o modelo (sem GPU), a medição
na GPU (resposta em frequência, estatísticas do grão) e o determinismo.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pelicula import grao, look, params


def vals(**kw) -> dict:
    """Ajustes neutros (sem bitola, sem lente) com as mudanças pedidas, já limpos."""
    v = params.defaults()
    v.update(bitola="nenhuma", bitola_vinheta=0.0)
    v.update(kw)
    return params.sanitize(v)


def plan(v, w=1920, h=1080, frame=0):
    return look.build_plan(v, w, h, frame, 24.0, None, dither=False)


def render(engine, img, v, frame=0, depth=16):
    h, w = img.shape[:2]
    engine.set_input(img)
    out = engine.render(plan(v, w, h, frame), depth)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


def grating(w: int, h: int, period: float, amp: float = 0.02, base: float = 0.45) -> np.ndarray:
    """Cinza com uma senoide fraca ao longo de x, igual nos três canais (16 bits)."""
    x = np.arange(w, dtype=np.float64)
    row = base + amp * np.sin(2 * np.pi * x / period)
    img = np.repeat(np.repeat(row[None, :, None], h, axis=0), 3, axis=2)
    return np.rint(img * 65535).astype(np.uint16)


def modulation(img: np.ndarray, period: float) -> np.ndarray:
    """Amplitude da senoide de período `period` em cada canal (longe das bordas)."""
    h, w = img.shape[:2]
    m = int(4 * period)
    x = np.arange(m, w - m, dtype=np.float64)
    seg = img[h // 4: 3 * h // 4, m:w - m].mean(axis=0)  # média das linhas: (n, 3)
    seg = seg - seg.mean(axis=0)
    s, c = np.sin(2 * np.pi * x / period), np.cos(2 * np.pi * x / period)
    return 2.0 * np.sqrt((seg * s[:, None]).mean(axis=0) ** 2 + (seg * c[:, None]).mean(axis=0) ** 2)


def gauss_mtf(sigma: float, period: float) -> float:
    return math.exp(-2.0 * math.pi ** 2 * sigma ** 2 / period ** 2)


# ------------------------------------------------------------------ M2: maciez pelo grão
def test_grain_softness_is_off_by_default_and_without_grain():
    assert params.PARAMS["grao_maciez"].default == 0.0
    assert grao.soft_sigma(vals(grao_on=True), look.GAUGES["35mm"]) == 0.0
    assert grao.soft_sigma(vals(grao_on=False, grao_maciez=1.0), look.GAUGES["35mm"]) == 0.0
    assert grao.soft_sigma(vals(grao_on=True, grao_forca=0.0, grao_maciez=1.0), look.GAUGES["35mm"]) == 0.0
    off = plan(vals(grao_on=False, grao_maciez=1.0))
    assert off.soft_sigma == 0.0 and off.uniforms["u_soft_on"] == 0


def test_grain_softness_is_the_bspline_width_of_the_grain():
    """100% = sigma s/√3 da B-spline cúbica que interpola a grade do ruído (s = célula do grão em px@1080)."""
    v = vals(grao_on=True, grao_maciez=1.0)
    p = plan(v)
    # 0,8 px@1080 sem bitola, ISO 250 (a grade do ruído tem no mínimo 1 px: o tamanho de projeto é que vale)
    assert grao.grain_size_1080(v, look.GAUGES["nenhuma"]) == pytest.approx(0.8) and p.grain_size == 1.0
    assert p.soft_sigma == pytest.approx(0.8 / math.sqrt(3.0))
    half = plan(vals(grao_on=True, grao_maciez=0.5, grao_tamanho=2.0, iso="500"))
    assert half.soft_sigma == pytest.approx(0.5 * 2.0 * 0.8 * 2 ** 0.18 / math.sqrt(3.0))


def test_grain_softness_adds_in_quadrature_with_gauge_lens_and_mtf():
    v = vals(bitola="16mm", grao_on=True, grao_maciez=0.7, lente_on=True, maciez=0.3, mtf="medio")
    g = look.GAUGES["16mm"]
    sig_r = 0.7 * 0.8 * g["grain_size"] / math.sqrt(3.0)
    want = math.sqrt(g["blur"] ** 2 + (v["raio_maciez"] * 0.3 * 2.0) ** 2 + look.mtf_sigma(v) ** 2 + sig_r ** 2)
    assert plan(v).soft_sigma == pytest.approx(want)


@pytest.mark.parametrize("h", [540, 1080, 2160])
def test_grain_softness_is_in_px1080(h):
    v = vals(bitola="super8", grao_on=True, grao_maciez=1.0)
    assert plan(v, h * 16 // 9, h).soft_sigma == pytest.approx(plan(v).soft_sigma * h / 1080)


@pytest.mark.gpu
def test_grain_softness_frequency_response(gl_engine):
    """Senoide fina: com 100% a resposta cai como a gaussiana de sigma s/√3 (e nada muda em 0%)."""
    img = grating(512, 1080, 4.0)
    sharp = vals(grao_on=True, grao_forca=0.01, grao_tamanho=1.5)
    soft = dict(sharp, grao_maciez=1.0)
    m0 = modulation(render(gl_engine, img, sharp), 4.0)
    m1 = modulation(render(gl_engine, img, soft), 4.0)
    want = gauss_mtf(1.5 * 0.8 / math.sqrt(3.0), 4.0)
    np.testing.assert_allclose(m1 / m0, want, rtol=0.04)
    np.testing.assert_allclose(m0 / m0.mean(), 1.0, atol=0.01)
