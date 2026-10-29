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


# ------------------------------------------------------------------ M3: grão no negativo
def lab(**kw) -> dict:
    """Laboratório ligado (Vision3 250D → 2383), sem o look paramétrico, com o grão ligado."""
    base = dict(bitola="35mm", bitola_desfoque_on=False, bitola_vinheta=0.0, lab_on=True, cor_on=False,
                copia="nenhuma", grao_on=True)
    base.update(kw)
    return vals(**base)


def test_negative_grain_constants_are_the_datasheet_fit():
    c = _tool().constants()
    assert grao.NEG_SIGMA_D == pytest.approx(c["NEG_SIGMA_D"], abs=1e-12)
    r, g, b = grao.NEG_SIGMA_D
    assert b > g > r  # o azul tem mais grão (H-1-5207, p. 3)
    assert grao.NEG_GRAIN_AMP == pytest.approx(tuple(x * grao.SIGMA_D_TO_PIXEL for x in grao.NEG_SIGMA_D))
    # 48 µm no 35 mm: 3,70 px@1080; o grão de 0,8 px tem sigma 0,432 nessa abertura (integral exata)
    assert grao.GRAN_APERTURE_PX == pytest.approx(3.7012, abs=1e-3)
    assert grao.GRAN_APERTURE_SIGMA == pytest.approx(c["GRAN_APERTURE_SIGMA"], abs=2e-5)
    assert grao.SIGMA_D_TO_PIXEL == pytest.approx(1.0 / c["GRAN_APERTURE_SIGMA"], rel=1e-4)


def test_aperture_sigma_of_the_bspline_grain_field():
    """Simulação: o desvio do campo do grão (B-spline cúbica de uma grade gaussiana, variância 1 por pixel) médio
    numa abertura circular é o da integral exata de `tools/ajustar_grao.py` (a menos do ruído da amostra)."""
    rng = np.random.default_rng(1234)
    s, n = 6, 160                                   # célula de 6 px (o campo é quase contínuo), 160 células
    a = rng.standard_normal((n + 4, n + 4))
    t = (np.arange(s) + 0.5) / s
    w = np.stack([(1 - t) ** 3, 3 * t ** 3 - 6 * t ** 2 + 4, -3 * t ** 3 + 3 * t ** 2 + 3 * t + 1, t ** 3]) / 6
    rows = sum(w[k][None, :, None] * a[k:k + n, None, :] for k in range(4)).reshape(n * s, n + 4)
    f = sum(rows[:, k:k + n, None] * w[k][None, None, :] for k in range(4)).reshape(n * s, n * s)
    norm = 1.0 / f.std()
    assert norm == pytest.approx(grao.GRAIN_NORM, rel=0.03)
    f = f * norm
    d = s * grao.GRAN_APERTURE_PX / 0.8              # a mesma razão abertura/célula da referência
    r = int(math.ceil(d / 2))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disc = ((xx ** 2 + yy ** 2) <= (d / 2) ** 2).astype(np.float64)
    disc /= disc.sum()
    from numpy.fft import irfft2, rfft2
    k = np.zeros_like(f)
    k[:disc.shape[0], :disc.shape[1]] = disc
    avg = irfft2(rfft2(f) * rfft2(k), s=f.shape)[2 * r:-2 * r, 2 * r:-2 * r]
    assert avg.std() == pytest.approx(grao.GRAN_APERTURE_SIGMA, rel=0.04)
    assert _tool().aperture_sigma(d / s) == pytest.approx(grao.GRAN_APERTURE_SIGMA, abs=2e-5)
    # a lei de Selwyn (abertura muito maior que o grão) daria uns 15% a mais nesta abertura
    assert grao.GRAIN_NORM * s / (d * math.sqrt(math.pi) / 2) > 1.1 * grao.GRAN_APERTURE_SIGMA


def test_negative_grain_is_off_by_default():
    assert params.PARAMS["lab_grao"].default is False
    for v in (lab(), lab(lab_grao=True, lab_on=False), lab(lab_grao=True, grao_on=False),
              lab(lab_grao=True, grao_forca=0.0)):
        assert plan(v).uniforms["u_grain_on"] != 2 and "u_ngrain" not in plan(v).uniforms
    assert plan(lab()).uniforms["u_grain_on"] == 1


def test_negative_grain_replaces_the_output_grain():
    """Com o Laboratório e o grão ligados, o grão sai da saída e entra na densidade, com a mesma grade."""
    old, new = plan(lab(iso="500", lab_revelacao=1.0)), plan(lab(iso="500", lab_revelacao=1.0, lab_grao=True))
    assert new.uniforms["u_grain_on"] == 2 and old.uniforms["u_grain_on"] == 1
    assert (new.grain_size, new.grain_seed) == (old.grain_size, old.grain_seed)
    k = old.uniforms["u_grain_amt"] / 0.011   # Intensidade × bitola × ISO × compensação × revelação
    assert new.uniforms["u_ngrain"] == pytest.approx(tuple(a * k for a in grao.NEG_GRAIN_AMP))


@pytest.mark.parametrize("h", [1080, 2160])
def test_negative_grain_amplitude_does_not_depend_on_resolution(h):
    v = lab(lab_grao=True, bitola="16mm")
    assert plan(v, h * 16 // 9, h).uniforms["u_ngrain"] == pytest.approx(plan(v).uniforms["u_ngrain"])


def steps_image(w=1600, h=360, stops=(-6, -4, -2, 0, 2, 4)):
    """Faixas de cinza em luz linear (stops em volta de 0,18), em código Rec.709 de 16 bits."""
    img = np.zeros((h, w, 3))
    bw = w // len(stops)
    for i, st in enumerate(stops):
        img[:, i * bw:(i + 1) * bw] = 0.18 * 2.0 ** st
    code = np.where(img < 0.018, 4.5 * img, 1.099 * np.power(np.maximum(img, 1e-9), 0.45) - 0.099)
    return np.rint(np.clip(code, 0, 1) * 65535).astype(np.uint16), bw


def band_stats(out, bw, n):
    return [(out[40:-40, i * bw + 20:(i + 1) * bw - 20].mean(axis=(0, 1)),
             out[40:-40, i * bw + 20:(i + 1) * bw - 20].std(axis=(0, 1))) for i in range(n)]


@pytest.mark.gpu
def test_the_print_curve_shapes_the_negative_grain(gl_engine):
    """O grão nasce igual em toda densidade; a cópia o esconde nos pretos e nas altas luzes estouradas e o mostra
    nos tons médios. O azul tem mais grão que o verde e o vermelho; o brilho médio quase não muda."""
    stops = (-6, -4, -2, 0, 2, 4)
    img, bw = steps_image(stops=stops)
    clean = band_stats(render(gl_engine, img, lab(grao_on=False), 7), bw, len(stops))
    st = band_stats(render(gl_engine, img, lab(lab_grao=True), 7), bw, len(stops))
    sd = np.array([s for _m, s in st])
    mid = stops.index(0)
    assert sd[mid].min() > 3 * sd[stops.index(4)].max()     # altas luzes estouradas: quase sem grão
    assert sd[mid].min() > 3 * sd[stops.index(-6)].max()    # pretos: quase sem grão
    r, g, b = sd[mid]
    assert b > g > r and b > 1.3 * g
    for (m0, _s0), (m1, _s1) in zip(clean, st):
        np.testing.assert_allclose(m1, m0, atol=3e-3)


@pytest.mark.gpu
def test_negative_grain_never_reaches_the_exported_lut(gl_engine):
    for v in (lab(), lab(lab_copia="nenhuma"), lab(lab_processo="tech3", bitola="super8")):
        a = gl_engine.bake_lut(v, 17)
        b = gl_engine.bake_lut(dict(v, lab_grao=True), 17)
        assert np.array_equal(a, b)


@pytest.mark.gpu
def test_negative_grain_is_deterministic_per_frame(gl_engine):
    img, _bw = steps_image(480, 120, stops=(0, 1))
    v = lab(lab_grao=True)
    a, b = render(gl_engine, img, v, 7), render(gl_engine, img, v, 7)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, render(gl_engine, img, v, 8))           # muda a cada quadro
    still = dict(v, grao_animado=False)
    assert np.array_equal(render(gl_engine, img, still, 7), render(gl_engine, img, still, 8))


# ------------------------------------------------------------------ halação física (reflexo na base)
def hal(**kw) -> dict:
    base = dict(hal_on=True, bitola="35mm", bitola_desfoque_on=False, grao_on=False)
    base.update(kw)
    return vals(**base)


def test_physical_halation_is_off_by_default():
    assert params.PARAMS["hal_modelo"].default == "brilho"
    p = plan(hal())
    (c,) = [c for c in p.chains if c.name == "hal"]
    assert p.uniforms["u_hal_on"] == 1 and c.threshold > 0 and c.lum_only
    assert plan(hal(hal_on=False, hal_modelo="fisica")).uniforms["u_hal_on"] == 0


@pytest.mark.parametrize("bitola", ["35mm", "16mm", "super8", "8mm", "65mm", "nenhuma"])
def test_physical_halation_chain(bitola):
    """Sem limiar, da exposição de cada canal (o FINAL usa o vermelho), raio pelo quadro da bitola, em px@1080."""
    for h in (540, 1080):
        v = hal(bitola=bitola, hal_modelo="fisica", hal_raio=10.0, hal_forca=0.5)
        p = plan(v, h * 16 // 9, h)
        (c,) = [c for c in p.chains if c.name == "hal"]
        assert c.threshold == 0.0 and not c.lum_only and c.limit == grao.HAL_PHYS_LIMIT
        assert c.sigma == pytest.approx(10.0 * 24.9 / grao.frame_width_mm(bitola) * h / 1080)
        assert p.uniforms["u_hal_on"] == 2 and p.uniforms["u_hal_amt"] == pytest.approx(0.5 * grao.HAL_PHYS_K)
    # o limiar não vale no modo físico
    a, b = plan(hal(hal_modelo="fisica", hal_limiar=0.0)), plan(hal(hal_modelo="fisica"))
    assert a.uniforms == b.uniforms and a.chains == b.chains


def code16(lin: np.ndarray) -> np.ndarray:
    c = np.where(lin < 0.018, 4.5 * lin, 1.099 * np.power(np.maximum(lin, 1e-9), 0.45) - 0.099)
    return np.rint(np.clip(c, 0, 1) * 65535).astype(np.uint16)


@pytest.mark.gpu
@pytest.mark.parametrize("level", [0.02, 0.18, 0.9, (0.7, 0.12, 0.03), (0.02, 0.3, 0.6)])
def test_physical_halation_leaves_flat_areas_alone(gl_engine, level):
    """Só o desvio local entra: uma área lisa fica igual, em qualquer cor (a parte uniforme já está nas curvas)."""
    img = code16(np.full((180, 320, 3), level, dtype=np.float64))
    off = render(gl_engine, img, hal(hal_on=False))
    on = render(gl_engine, img, hal(hal_modelo="fisica", hal_forca=3.0))
    # o halo passa por texturas de meia precisão (f2): sobra o arredondamento delas, bem abaixo de 1/4 de código de 8 bits
    assert np.abs(on - off).max() < 0.25 / 255


def test_physical_halation_source_limit_is_the_same_in_the_shader():
    from pelicula import shaders
    assert f"const float HAL_PHYS_LIMIT = {grao.HAL_PHYS_LIMIT!r};" in shaders.FINAL


def spot(w=640, h=360, r=6.0, bg=0.05):
    yy, xx = np.mgrid[0:h, 0:w]
    lin = np.full((h, w, 3), bg)
    lin[np.hypot(xx - w / 2, yy - h / 2) < r] = 1.0
    return code16(lin)


@pytest.mark.gpu
def test_physical_halation_is_a_red_halo_around_strong_lights(gl_engine):
    img = spot()
    off = render(gl_engine, img, hal(hal_on=False))
    d = render(gl_engine, img, hal(hal_modelo="fisica")) - off
    ring = d[180, 327:332].mean(axis=0)            # logo fora da luz (raio 6 px)
    assert ring[0] > 2 * ring[1] > 0 and ring[1] > ring[2] >= 0
    assert np.abs(d[20:60, 20:60]).max() < 2.5 / 65535  # longe da luz, nada


@pytest.mark.gpu
def test_physical_halation_grows_with_smaller_gauges(gl_engine):
    """O anel tem o mesmo tamanho na película: no Super 8 ele cobre mais do quadro que no 35 mm."""
    img = spot()
    off = render(gl_engine, img, hal(hal_on=False))

    def reach(bitola):
        d = (render(gl_engine, img, hal(hal_modelo="fisica", bitola=bitola)) - off)[180, 327:, 0]
        return int(np.argmax(d < 0.25 * d[0]))

    assert reach("super8") > 2 * reach("35mm") > 0
