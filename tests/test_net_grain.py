""""Grão para redes" (exportação por plataforma): `look.build_plan(..., net_grain=)`.

Desligado (o padrão) o plano é idêntico ao de sempre; ligado, o grão tem pelo menos `NET_GRAIN_MIN_PX` pixels do
arquivo exportado, fica um pouco mais forte e menos colorido, e continua determinístico por quadro.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import export, look, presets
from pelicula.export import ExportSettings


def _film(**over) -> dict:
    v = presets.builtin_values("vision3_500t")
    v.update({"grao_on": True, "grao_forca": 1.0, **over})
    return v


def _same(a: look.Plan, b: look.Plan) -> bool:
    ua, ub = a.uniforms, b.uniforms
    return (ua.keys() == ub.keys() and all(np.array_equal(np.asarray(ua[k]), np.asarray(ub[k])) for k in ua)
            and (a.grain_size, a.grain_seed, a.soft_sigma, a.lut_path, a.edge_text)
            == (b.grain_size, b.grain_seed, b.soft_sigma, b.lut_path, b.edge_text))


@pytest.mark.parametrize("pid", ["vision3_500t", "super8_kodachrome", "original", "double_x"])
@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (320, 180)])
def test_off_is_exactly_the_old_plan(pid, size):
    v = presets.builtin_values(pid)
    for frame in (0, 17):
        old = look.build_plan(v, *size, frame, 24.0, None)
        assert _same(old, look.build_plan(v, *size, frame, 24.0, None, net_grain=0))
        assert _same(old, look.build_plan(v, *size, frame, 24.0, None, net_grain=0.0, legal=True))


def test_on_sets_a_minimum_size_in_output_pixels_and_a_bit_more_strength():
    v = _film(grao_tamanho=0.3)  # grão fino: some na recompressão das redes
    off = look.build_plan(v, 1080, 1920, 5, 30.0, None)
    on = look.build_plan(v, 1080, 1920, 5, 30.0, None, net_grain=1.0)
    assert off.grain_size < look.NET_GRAIN_MIN_PX <= on.grain_size
    assert on.uniforms["u_grain_amt"] > off.uniforms["u_grain_amt"]
    assert on.uniforms["u_grain_chroma"] == pytest.approx(off.uniforms["u_grain_chroma"] * look.NET_GRAIN_CHROMA)
    assert on.grain_seed == off.grain_seed  # o mesmo grão, só maior
    # prévia reduzida à metade: o mínimo acompanha (2 px da saída = 1 px da prévia)
    half = look.build_plan(v, 540, 960, 5, 30.0, None, net_grain=0.5)
    assert half.grain_size == pytest.approx(max(1.0, look.NET_GRAIN_MIN_PX * 0.5))
    # grão já grande não encolhe
    big = _film(grao_tamanho=4.0)
    assert look.build_plan(big, 1080, 1920, 5, 30.0, None, net_grain=1.0).grain_size == pytest.approx(
        look.build_plan(big, 1080, 1920, 5, 30.0, None).grain_size)


def test_on_without_grain_changes_nothing():
    v = _film(grao_on=False)
    assert _same(look.build_plan(v, 1080, 1920, 3, 24.0, None), look.build_plan(v, 1080, 1920, 3, 24.0, None,
                                                                                 net_grain=1.0))


def test_on_is_deterministic_per_frame():
    v = _film(grao_tamanho=0.3, grao_animado=True)
    a = look.build_plan(v, 1080, 1920, 9, 24.0, None, net_grain=1.0)
    assert _same(a, look.build_plan(v, 1080, 1920, 9, 24.0, None, net_grain=1.0))
    assert a.grain_seed != look.build_plan(v, 1080, 1920, 10, 24.0, None, net_grain=1.0).grain_seed


def test_export_passes_the_output_scale(make_info):
    info = make_info(width=1920, height=1080)
    assert export.frame_pipeline(info, {}, ExportSettings()).net_grain == 0.0
    assert export.frame_pipeline(info, {}, ExportSettings(net_grain=True)).net_grain == 1.0
    assert export.frame_pipeline(info, {}, ExportSettings(net_grain=True), scale=0.25).net_grain == 0.25


@pytest.mark.gpu
def test_render_with_net_grain_is_deterministic_and_differs_from_off(gl_engine, test_rgb):
    v = _film(grao_tamanho=0.3, grao_animado=True)
    h, w = test_rgb.shape[:2]
    outs = []
    for net in (1.0, 1.0, 0.0):
        gl_engine.set_input(test_rgb)
        outs.append(gl_engine.render(look.build_plan(v, w, h, 4, 24.0, None, net_grain=net), 8))
    assert np.array_equal(outs[0], outs[1])
    assert not np.array_equal(outs[0], outs[2])
