"""Zebra e falsa cor da prévia (1.6): stops em relação ao cinza de 18% na luz que o look decodifica."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import exposure, look, params


def gray(stop: float) -> np.ndarray:
    return np.full((1, 1, 3), 0.18 * 2.0 ** stop)


def test_stops_are_relative_to_18_percent_gray():
    assert abs(exposure.stops(gray(0.0))[0, 0]) < 1e-12
    assert abs(exposure.stops(gray(1.0))[0, 0] - 1.0) < 1e-12
    assert abs(exposure.stops(gray(-3.5))[0, 0] + 3.5) < 1e-12
    assert np.isfinite(exposure.stops(np.zeros((2, 2, 3)))).all()
    # luminância Rec.709: um vermelho puro de 0,18 fica abaixo do cinza
    assert exposure.stops(np.array([[[0.18, 0.0, 0.0]]]))[0, 0] < -2.0


@pytest.mark.parametrize("stop,band", [(-7.0, 0), (-5.0, 1), (0.1, 2), (1.0, 3), (5.0, 4), (6.5, 5), (-2.0, None),
                                       (0.5, None), (3.0, None)])
def test_false_color_bands(stop, band):
    assert exposure.band_of(stop) == band
    rgba = exposure.false_color(exposure.stops(gray(stop)))[0, 0]
    if band is None:
        assert rgba[0] == rgba[1] == rgba[2]  # cinza
    else:
        assert tuple(rgba[:3]) == exposure.BANDS[band][2]
    assert rgba[3] == 1.0


def test_false_color_gray_follows_the_exposure_and_respects_cover():
    st = np.array([[-3.0, 2.0, 3.0]])
    fc = exposure.false_color(st, cover=np.array([[1.0, 1.0, 0.0]]))
    assert fc[0, 0, 0] < fc[0, 1, 0]
    assert fc[0, 2, 3] == 0.0 and fc[0, 0, 3] == 1.0


def test_zebra_marks_only_above_the_level_with_fixed_stripes():
    h, w = 180, 320
    st = np.full((h, w), 3.0)
    st[:, 160:] = 5.0
    z = exposure.zebra(st, 4.5)
    assert (z[:, :160, 3] == 0).all() and (z[:, 160:, 3] == exposure.ZEBRA_ALPHA).all()
    over = z[:, 160:, 0]
    assert set(np.unique(over)) == {0.0, 1.0}  # listras pretas e brancas
    assert np.array_equal(z, exposure.zebra(st, 4.5))  # determinístico
    assert (exposure.zebra(st, 6.0)[..., 3] == 0).all()
    # a largura das listras acompanha a altura do quadro (o mesmo desenho em qualquer tamanho de prévia)
    big = exposure.zebra(np.full((1440, 16), 9.0), 4.5)[:, 0, 0]
    small = exposure.zebra(np.full((360, 16), 9.0), 4.5)[:, 0, 0]
    assert np.argmax(big != big[0]) == 4 * np.argmax(small != small[0])


def test_decode_values_keep_only_the_input_reading():
    v = {**params.defaults(), "entrada": "slog3", "exposicao": 1.5,
         "temperatura": 20.0, "tint": -10.0, "grao_on": True, "lab_on": True, "planos_on": True,
         "planos_fundo_exposicao": -1.0, "lente_on": True, "vinheta": 0.8}
    d = exposure.decode_values(v)
    entrada = next(s for s in params.SECTIONS if s.key == "entrada")
    for p in entrada.params:
        assert d[p.key] == v[p.key]
    base = params.defaults()
    for k in ("grao_on", "lab_on", "planos_on", "lente_on", "vinheta", "cor_on", "scan_on"):
        assert d[k] == base[k]
    assert d["bitola_vinheta"] == 0.0
    plan = look.build_plan(d, 64, 36, 0, 24.0, dither=False)
    assert plan is not None


# ------------------------------------------------------------------ GPU
@pytest.mark.gpu
@pytest.mark.parametrize("ev", [0.0, 1.0, -2.0])
def test_meter_light_is_the_decoded_scene_light(gl_engine, ev):
    img = np.full((36, 64, 3), 46, np.uint8)  # 46/255 ≈ 0,18 no perfil "linear" (o arquivo já é luz)
    v = exposure.decode_values({**params.defaults(), "entrada": "linear", "exposicao": ev, "grao_on": True})
    plan = look.build_plan(v, 64, 36, 0, 24.0, dither=False)
    gl_engine.set_input(img)
    light = gl_engine.scene_light(plan)
    st = exposure.stops(light[..., :3])
    want = np.log2((46 / 255) / 0.18) + ev
    assert np.abs(st - want).max() < 0.02
    assert np.allclose(light[..., 3], 1.0)
