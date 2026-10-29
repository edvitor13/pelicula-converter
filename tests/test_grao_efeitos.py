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


# ------------------------------------------------------------------ M7: diferença de nitidez entre camadas
def _tool():
    """`tools/ajustar_grao.py` (o ajuste offline das constantes) carregado como módulo."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / "ajustar_grao.py"
    spec = importlib.util.spec_from_file_location("ajustar_grao", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_layer_constants_are_the_datasheet_fit():
    """As constantes de grao.py são as que `tools/ajustar_grao.py` tira dos pontos lidos dos datasheets."""
    c = _tool().constants()
    assert c["MTF_NEG_REF"] == "B" and c["MTF_PRINT_REF"] == "G"
    assert grao.MTF_NEG_DSIGMA_UM == pytest.approx(c["MTF_NEG_DSIGMA_UM"], abs=1e-9)
    assert grao.MTF_PRINT_DSIGMA_UM == pytest.approx(c["MTF_PRINT_DSIGMA_UM"], abs=1e-9)


@pytest.mark.parametrize("pub", ["H-1-5207", "H-1-2383"])
def test_datasheet_points_carry_their_source(pub):
    d = _tool().load(pub)
    assert d["publicacao"] == pub and d["revisao"] and len(d["sha256"]) == 64
    m = d["mtf"]
    assert m["pagina"] and m["figura"] and m["condicoes"] and m["unidade"]
    assert len(m["ciclos_mm"]) == len(m["R"]) == len(m["G"]) == len(m["B"])
    assert d["leitura"]["metodo"] and d["leitura"]["erro"]


@pytest.mark.parametrize("pub, dsig", [("H-1-5207", grao.MTF_NEG_DSIGMA_UM), ("H-1-2383", grao.MTF_PRINT_DSIGMA_UM)])
def test_layer_gaussian_follows_the_published_curves(pub, dsig):
    """Nas frequências do meio (25 a 50 ciclos/mm) a gaussiana ajustada segue a razão entre as camadas: a menos
    de 8% no negativo e de 18% na cópia (o azul da 2383 cai mais devagar que uma gaussiana)."""
    m = _tool().load(pub)["mtf"]
    f = np.asarray(m["ciclos_mm"])
    sel = (f >= 25) & (f <= 50)
    ref = np.asarray(m["G" if pub == "H-1-2383" else "B"])[sel]
    for c, d in zip("RGB", dsig):
        got = np.asarray(m[c])[sel] / ref
        want = np.exp(-2 * np.pi ** 2 * (d / 1000.0) ** 2 * f[sel] ** 2)
        np.testing.assert_allclose(got, want, rtol=0.18 if pub == "H-1-2383" else 0.08, err_msg=f"{pub} {c}")


def test_layer_softness_is_off_by_default():
    assert params.PARAMS["mtf_camadas"].default == 0.0
    assert grao.layer_sigmas(vals()) is None
    p = plan(vals(bitola="super8"))
    assert p.soft_sigma3 is None
    assert plan(vals(mtf_camadas=0.0, copia="k2383")).soft_sigma3 is None


def test_negative_layers_red_softest_blue_sharpest():
    """Sem cópia: vermelho mais macio, azul a referência (Vision3 250D); 50% = a diferença medida."""
    v = vals(bitola="35mm", bitola_desfoque_on=False, mtf_camadas=0.5)
    px_mm = 1920.0 / 24.9   # 35 mm: imagem de 24,9 mm de largura (look.SCAN_FORMATS)
    want = tuple(x / 1000.0 * px_mm for x in grao.MTF_NEG_DSIGMA_UM)
    assert grao.layer_sigmas(v) == pytest.approx(want)
    r, g, b = plan(v).soft_sigma3
    assert r > g > 0.0 and b == pytest.approx(0.0, abs=1e-9)


def test_a_print_makes_blue_softer():
    """Com uma cópia (a do look ou a do Laboratório), a 2383 amacia o azul e o verde passa a ser a referência."""
    base = dict(bitola="16mm", bitola_desfoque_on=False, mtf_camadas=1.0)
    neg = grao.layer_sigmas(vals(**base))
    for kw in (dict(copia="k2383"), dict(lab_on=True, lab_copia="2383")):
        assert grao.print_chosen(vals(**base, **kw))
        r, g, b = grao.layer_sigmas(vals(**base, **kw))
        assert g == pytest.approx(0.0, abs=1e-9) and b > 0.5 * r and b > neg[2] + 1.0
    assert not grao.print_chosen(vals(**base, lab_on=True, lab_copia="nenhuma"))
    assert not grao.print_chosen(vals(**base, copia="k2383", copia_forca=0.0))


def test_layer_softness_adds_in_quadrature_with_the_softness():
    v = vals(bitola="16mm", mtf_camadas=0.8, mtf="medio")
    p0 = plan(dict(v, mtf_camadas=0.0))
    p = plan(v)
    d = grao.layer_sigmas(v)
    assert p.soft_sigma3 == pytest.approx(tuple(math.sqrt(p0.soft_sigma ** 2 + x ** 2) for x in d))
    assert p.soft_sigma == pytest.approx(max(p.soft_sigma3)) and p.uniforms["u_soft_mix"] == 1.0


@pytest.mark.parametrize("h", [540, 1080, 2160])
def test_layer_softness_is_in_px1080(h):
    v = vals(bitola="super8", bitola_desfoque_on=False, mtf_camadas=1.0)
    got = plan(v, h * 16 // 9, h).soft_sigma3
    assert got == pytest.approx(tuple(x * h / 1080 for x in plan(v).soft_sigma3))


def test_gauge_widths_for_the_conversion():
    assert grao.frame_width_mm("35mm") == pytest.approx(24.9)
    assert grao.frame_width_mm("nenhuma") == grao.frame_width_mm("35mm")
    assert grao.frame_width_mm("super8") == pytest.approx(5.79)
    assert grao.frame_width_mm("8mm") < grao.frame_width_mm("super8") < grao.frame_width_mm("16mm")
    assert grao.frame_width_mm("16mm") < grao.frame_width_mm("super16") < grao.frame_width_mm("35mm")
    assert grao.frame_width_mm("35mm") < grao.frame_width_mm("65mm") < grao.frame_width_mm("imax")
    for k, _l in params.BITOLAS:
        assert grao.frame_width_mm(k) > 0


@pytest.mark.gpu
def test_layer_softness_frequency_response(gl_engine):
    """Senoide cinza: cada canal cai como a gaussiana do seu sigma; o brilho médio quase não muda (o desfoque é
    em luz linear, e a média do código sobe um pouco: menos de 1/1000)."""
    img = grating(512, 1080, 4.0)
    base = vals(bitola="super8", bitola_desfoque_on=False, bitola_vinheta=0.0)
    on = dict(base, mtf_camadas=1.0)
    a0, a1 = render(gl_engine, img, base), render(gl_engine, img, on)
    ratio = modulation(a1, 4.0) / modulation(a0, 4.0)
    want = [gauss_mtf(s, 4.0) for s in plan(on).soft_sigma3]
    np.testing.assert_allclose(ratio, want, rtol=0.05, atol=0.01)
    assert ratio[0] < ratio[1] < ratio[2]
    np.testing.assert_allclose(a1.mean(axis=(0, 1)), a0.mean(axis=(0, 1)), atol=1e-3)


@pytest.mark.gpu
def test_layer_softness_is_deterministic_and_preview_equals_export(gl_engine):
    img = grating(320, 180, 3.0)
    v = vals(bitola="16mm", mtf_camadas=1.0, copia="k2383", grao_on=True)
    a = render(gl_engine, img, v, 7)
    b = render(gl_engine, img, v, 7)
    assert np.array_equal(a, b)
    # a exportação usa o mesmo plano (a prévia só muda a resolução: o sigma segue em px@1080)
    small = plan(v, 320, 180, 7).soft_sigma3
    assert small == pytest.approx(tuple(x * 180 / 1080 for x in plan(v, 1920, 1080, 7).soft_sigma3))
