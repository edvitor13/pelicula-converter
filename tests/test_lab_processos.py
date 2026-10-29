"""Laboratório da 1.6: scanner de luz branca (M6), película vencida, pré-exposição e processos novos (reversível e
revelação cruzada). O que cada um faz, que desligados nada muda e que a GPU (prévia e LUT) segue o numpy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from pelicula import labx, look, params

W709 = np.array([0.2126, 0.7152, 0.0722])
STOPS = np.arange(-8.0, 5.0, 1.0)


def lab_values(**over) -> dict:
    v = params.defaults()
    v.update(lab_on=True, bitola="nenhuma", cor_on=False, copia="nenhuma")
    v.update(over)
    return params.sanitize(v)


def grey(stops) -> np.ndarray:
    return np.stack([0.18 * 2.0 ** np.asarray(stops, dtype=np.float64)] * 3, axis=-1)


def neg_dmin(v: dict) -> np.ndarray:
    """Densidade do negativo (acima da base) sem luz nenhuma: só o véu e a pré-exposição."""
    a, _b = look.lab_paths_for(v)
    le = np.log10(np.maximum(np.asarray(a.add), 1e-7) / 0.18)
    return look.lab_curve(le, a.ng, a.nt, a.ns, a.nw) @ np.asarray(a.ii).T


def sat(y) -> np.ndarray:
    y = np.asarray(y)
    return y.max(axis=-1) - y.min(axis=-1)


# ------------------------------------------------------------------ desligado = igual
def test_defaults_are_neutral_and_add_no_uniform():
    v = lab_values()
    assert v["lab_scanner"] == "rgb" and v["lab_vencida"] == 0.0 and v["lab_pre_exposicao"] is False
    a, _b = look.lab_paths_for(v)
    assert a.add == (0.0, 0.0, 0.0) and a.white is False
    for over in ({}, dict(lab_copia="nenhuma"), dict(lab_processo="tech3"), dict(lab_pre_exposicao_stops=2.0,
                                                                                  lab_pre_exposicao_cor="azul")):
        U = look.build_plan(lab_values(**over), 320, 180, 0, 24.0, None, dither=False).uniforms
        assert not [k for k in U if k.startswith("u_lx_")], over


def test_white_scanner_only_acts_without_a_print():
    rgb = look.lab_eval(lab_values(), grey(STOPS))
    np.testing.assert_array_equal(rgb, look.lab_eval(lab_values(lab_scanner="branca"), grey(STOPS)))


# ------------------------------------------------------------------ película vencida
@pytest.mark.parametrize("neg", ["vision3_250d", "vision3_500t", "eterna_250d", "ecn2_5247", "vision3_250d_v2",
                                 "double_x"])
def test_fog_raises_dmin_monotonically_with_age(neg):
    prev = np.zeros(3)
    for years in range(1, 31):
        d = neg_dmin(lab_values(lab_negativo=neg, lab_vencida=float(years)))
        assert (d > prev).all(), (years, d, prev)
        prev = d
    if neg == "double_x":
        assert np.ptp(prev) < 1e-12  # preto e branco: o véu é cinza
    else:
        assert prev[2] > prev[1] > prev[0]  # a camada do azul (a mais rápida) envelhece mais


def test_expired_film_keeps_grey_lifts_blacks_and_turns_shadows_blue():
    fresh = look.lab_eval(lab_values(), grey(STOPS))
    old = look.lab_eval(lab_values(lab_vencida=20.0), grey(STOPS))
    np.testing.assert_allclose(old[8], 0.45, atol=1e-6)            # 0 stop: cinza calibrado
    assert old[0].mean() > fresh[0].mean() + 0.02                  # preto lavado (o véu)
    sh, hi = old[2], old[10]                                       # −6 e +2 stops
    assert sh[2] > sh[0] and sh[2] > sh[1]                         # sombras azuladas
    assert hi[2] < hi[0] and hi[2] < hi[1]                         # altas luzes amareladas
    # o contraste no cinza cai (menos gama no negativo)
    s_f = look.lab_eval(lab_values(), grey([-0.5, 0.5]))
    s_o = look.lab_eval(lab_values(lab_vencida=20.0), grey([-0.5, 0.5]))
    assert (s_o[1] - s_o[0]).mean() < (s_f[1] - s_f[0]).mean()


def test_age_weights_follow_the_negative_granularity():
    from pelicula import grao
    w = np.asarray(grao.NEG_SIGMA_D) / max(grao.NEG_SIGMA_D)
    np.testing.assert_allclose(labx.AGE_W, w, atol=6e-4)


# ------------------------------------------------------------------ pré-exposição
def test_flashing_lifts_shadows_monotonically_and_keeps_highlights():
    base = look.lab_eval(lab_values(), grey(STOPS))
    prev = base
    for stops in (8.0, 6.0, 5.0, 4.0, 3.0, 2.0):
        y = look.lab_eval(lab_values(lab_pre_exposicao=True, lab_pre_exposicao_stops=stops), grey(STOPS))
        np.testing.assert_allclose(y[8], 0.45, atol=1e-6)          # cinza calibrado
        assert (y[:4].mean(axis=1) > prev[:4].mean(axis=1)).all()  # −8 a −5 stops sobem a cada passo
        prev = y
        if stops >= 4.0:
            assert np.abs(y[11:] - base[11:]).max() < 0.012        # +3 e +4 stops quase iguais
    assert prev[0].mean() > 3 * base[0].mean()


def test_flash_colour_tints_the_shadows():
    y = look.lab_eval(lab_values(lab_pre_exposicao=True, lab_pre_exposicao_stops=3.0,
                                 lab_pre_exposicao_cor="ambar"), grey([-6.0]))[0]
    n = look.lab_eval(lab_values(lab_pre_exposicao=True, lab_pre_exposicao_stops=3.0), grey([-6.0]))[0]
    assert y[0] - y[2] > n[0] - n[2] + 0.005
    for k, _l in params.CORES_PRE_EXPOSICAO:
        assert float(labx.flash_rgb(k) @ W709) == pytest.approx(1.0)


# ------------------------------------------------------------------ scanner de luz branca (M6)
def test_white_light_scan_keeps_grey_and_lowers_saturation():
    rng = np.random.default_rng(3)
    cols = rng.uniform(0.02, 0.6, size=(64, 3))
    for neg in ("vision3_250d", "vision3_500t_v2", "ecn2_5247"):
        rgb = look.lab_eval(lab_values(lab_negativo=neg, lab_copia="nenhuma"), cols)
        white = look.lab_eval(lab_values(lab_negativo=neg, lab_copia="nenhuma", lab_scanner="branca"), cols)
        assert (sat(white) <= sat(rgb) + 1e-9).all()
        assert sat(white).mean() < 0.8 * sat(rgb).mean()
        g = look.lab_eval(lab_values(lab_negativo=neg, lab_copia="nenhuma", lab_scanner="branca"), grey(STOPS))
        np.testing.assert_allclose(g[8], look.lab_eval(lab_values(lab_negativo=neg, lab_copia="nenhuma"),
                                                       grey([0.0]))[0], atol=1e-9)
        assert np.ptp(g[3:12], axis=1).max() < 0.03  # a escala de cinza continua quase neutra


def test_white_light_scan_saturation_grows_with_the_scene_saturation():
    """Mais saturação na cena = mais saturação no scan de luz branca (só menos que no RGB estreito)."""
    v = lab_values(lab_copia="nenhuma", lab_scanner="branca")
    k = np.linspace(0.0, 0.9, 10)[:, None]
    cols = 0.18 * ((1 - k) * np.ones(3) + k * np.array([1.6, 0.6, 0.4]))
    s = sat(look.lab_eval(v, cols))
    assert (np.diff(s) > 0).all()


def test_scan_matrix_is_the_datasheet_fit():
    path = Path(__file__).resolve().parents[1] / "tools" / "ajustar_lab.py"
    spec = importlib.util.spec_from_file_location("ajustar_lab", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = mod.constants()
    np.testing.assert_allclose(labx.SCAN_WHITE, c["scan_luz_branca"], atol=1e-12)
    np.testing.assert_allclose(labx.SCAN_DMIN, c["scan_dmin"], atol=1e-12)
    np.testing.assert_allclose(np.sum(labx.SCAN_WHITE, axis=1), 1.0, atol=1e-12)


# ------------------------------------------------------------------ processos novos
def test_reversal_has_no_print_and_more_contrast():
    a = look.lab_eval(lab_values(lab_processo="reversivel"), grey(STOPS))
    for cop in ("2393", "3513", "nenhuma", "2383_v2"):
        np.testing.assert_array_equal(a, look.lab_eval(lab_values(lab_processo="reversivel", lab_copia=cop),
                                                       grey(STOPS)))
    n = look.lab_eval(lab_values(), grey([-0.5, 0.5]))
    r = look.lab_eval(lab_values(lab_processo="reversivel"), grey([-0.5, 0.5]))
    assert (r[1] - r[0]).mean() > 1.3 * (n[1] - n[0]).mean()       # mais contraste no cinza
    normal = look.lab_eval(lab_values(), grey(STOPS))
    assert a[0].mean() < normal[0].mean()                          # preto mais denso (dmax do slide)
    assert a[12].mean() > normal[12].mean()                        # e as altas luzes estouram antes


def test_cross_processing_shifts_as_documented():
    n = look.lab_eval(lab_values(), grey([-0.5, 0.5]))
    # slide no C-41: contraste alto, sombras azuladas e altas luzes amareladas
    e6 = look.lab_eval(lab_values(lab_processo="cruzado_e6c41"), grey([-0.5, 0.5, -4.0, 2.0]))
    assert (e6[1] - e6[0]).mean() > 1.3 * (n[1] - n[0]).mean()
    assert e6[2][2] > e6[2][0] and e6[3][2] < e6[3][0]
    # negativo no E-6: pouco contraste, preto lavado, altas luzes quentes e sombras azuladas
    c41 = look.lab_eval(lab_values(lab_processo="cruzado_c41e6"), grey([-0.5, 0.5, -4.0, 2.0, -12.0]))
    assert (c41[1] - c41[0]).mean() < (n[1] - n[0]).mean()
    assert c41[4].mean() > 0.08
    assert c41[2][2] > c41[2][0] and c41[3][0] > c41[3][2]


@pytest.mark.parametrize("proc", ["reversivel", "cruzado_e6c41", "cruzado_c41e6"])
def test_new_processes_keep_grey_and_mix(proc):
    for forca in (0.0, 0.4, 1.0):
        v = lab_values(lab_processo=proc, lab_processo_forca=forca, lab_vencida=7.0, lab_pre_exposicao=True)
        np.testing.assert_allclose(look.lab_eval(v, np.full(3, 0.18)), 0.45, atol=1e-6)


def test_new_ids_are_appended_at_the_end():
    procs = [k for k, _l in params.PROCESSOS]
    assert procs[:4] == ["normal", "tech3", "tech2", "prata"]
    assert procs[4:] == ["reversivel", "cruzado_e6c41", "cruzado_c41e6"]
    assert list(look.LAB_PROCESSES)[-3:] == procs[4:]


# ------------------------------------------------------------------ GPU: prévia e LUT = numpy; desligado = igual
def _display_ref(v, lin):
    from test_lab import display_to_lin
    ref = look.lab_eval(v, lin)
    return look._stops_to_disp(np.clip(np.log2(display_to_lin(ref) / 0.18), -12, 12))


CASES = [dict(lab_copia="nenhuma", lab_scanner="branca"), dict(lab_vencida=18.0),
         dict(lab_pre_exposicao=True, lab_pre_exposicao_stops=2.5, lab_pre_exposicao_cor="verde"),
         dict(lab_processo="reversivel", lab_vencida=6.0), dict(lab_processo="cruzado_c41e6", lab_processo_forca=0.6)]


@pytest.mark.gpu
@pytest.mark.parametrize("over", CASES, ids=[str(i) for i in range(len(CASES))])
def test_gpu_lut_and_preview_follow_numpy(gl_engine, over):
    from test_lab import display_to_lin
    v = lab_values(**over)
    n = 9
    lut = gl_engine.bake_lut(v, n)
    axis = np.linspace(0, 1, n)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)
    assert np.abs(lut - _display_ref(v, display_to_lin(grid))).max() < 0.004
    rng = np.random.default_rng(5)
    img = rng.integers(0, 65536, size=(24, 32, 3), dtype=np.uint16)
    vv = dict(v, grao_on=False, hal_on=False, bloom_on=False, lente_on=False, bitola_vinheta=0.0)
    gl_engine.set_input(img)
    plan = look.build_plan(vv, 32, 24, 0, 24.0, None, dither=False)
    assert ("u_lx_on" in plan.uniforms) == any(k in over for k in ("lab_scanner", "lab_vencida", "lab_pre_exposicao"))
    out = gl_engine.render(plan, 16).astype(np.float64) / 65535.0
    ref = _display_ref(vv, display_to_lin(img.astype(np.float64) / 65535.0))
    assert np.abs(out - ref).max() < 0.006
    # determinístico: o mesmo quadro duas vezes
    np.testing.assert_array_equal(gl_engine.render(plan, 16), gl_engine.render(plan, 16))


@pytest.mark.gpu
def test_gpu_defaults_keep_the_lut_bit_identical(gl_engine):
    """O LUT exportado só muda quando as opções novas são usadas: com elas desligadas, igual bit a bit ao de antes
    (a variante FINAL_LX/BAKE_LX nem é usada) e com o processo normal, igual ao de qualquer valor das opções."""
    v = lab_values(lab_negativo="vision3_500t", lab_copia="2393", lab_luz_r=2.0)
    a = gl_engine.bake_lut(v, 17)
    b = gl_engine.bake_lut(dict(v, lab_pre_exposicao_stops=2.0, lab_pre_exposicao_cor="azul", lab_scanner="branca"),
                           17)
    np.testing.assert_array_equal(a, b)  # escolhas sem efeito (pré-exposição desligada; scanner só no Sem cópia)
    c = gl_engine.bake_lut(dict(v, lab_vencida=5.0), 17)
    assert np.abs(a - c).max() > 1e-3
