"""1.6, frente E: lente anamórfica (`anamorfico.py`) e data impressa (`data_impressa.py`).

Desligados = o plano e os bits de sempre; desespremer = caixa de letra com a proporção certa; barril e bordas na
geometria esperada; o risco de luz só na horizontal; a data nos pixels certos (px@1080) em duas resoluções, laranja,
passando pela halação (está na luz da cena, antes da película) e com o grão por cima.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import anamorfico, data_impressa, look, modules, params
from pelicula.engine import Engine
from pelicula.frame import Recipe

W, H = 480, 270


def _render(engine, img, **kw):
    v = params.sanitize(kw)
    return Recipe.for_source(v, 24.0, 8, legal=False).render(engine, img, 3)


def _gray(w=W, h=H, level=90):
    return np.full((h, w, 3), level, np.uint8)


# ------------------------------------------------------------------ neutros
def test_sections_are_off_and_plans_unchanged():
    v = params.defaults()
    assert v["anam_on"] is False and v["data_on"] is False
    U = look.build_plan(v, W, H, 0, 24.0).uniforms
    assert "u_anam" not in U and "u_date_on" not in U and "u_streak_on" not in U
    assert look.SPARSE_UNIFORMS["u_anam"] == (1.0, 0.0, 0.0, 0.0) and look.SPARSE_UNIFORMS["u_date_on"] == 0
    assert Engine.FINAL_NEUTRAL["u_streak_on"] == 0
    # ligado sem nada a fazer: o plano de sempre
    v2 = params.sanitize({"anam_on": True, "anam_flare": 0.0, "anam_barril": 0.0, "anam_bordas": 0.0})
    assert look.build_plan(v2, W, H, 0, 24.0).uniforms == look.build_plan(v, W, H, 0, 24.0).uniforms


@pytest.mark.gpu
def test_off_after_on_is_bit_identical(gl_engine, test_rgb):
    before = _render(gl_engine, test_rgb)
    _render(gl_engine, test_rgb, anam_on=True, anam_compressao="2.0", data_on=True)
    assert np.array_equal(_render(gl_engine, test_rgb), before), "nenhum uniform fica no programa"


# ------------------------------------------------------------------ anamórfico
@pytest.mark.gpu
@pytest.mark.parametrize("sq", ["1.33", "1.5", "1.8", "2.0"])
def test_desqueeze_letterbox_has_the_right_aspect(gl_engine, sq):
    out = _render(gl_engine, _gray(level=160), anam_on=True, anam_compressao=sq, anam_flare=0.0,
                  anam_barril=0.0, anam_bordas=0.0)
    rows = out[:, W // 2, 1].astype(int)
    lit = np.flatnonzero(rows > 20)
    visible = lit[-1] - lit[0] + 1
    assert visible == pytest.approx(H / float(sq), abs=1.5)
    top, bottom = anamorfico.image_box(params.sanitize({"anam_on": True, "anam_compressao": sq}), W, H)
    assert lit[0] == pytest.approx(top, abs=1.0) and lit[-1] + 1 == pytest.approx(bottom, abs=1.0)
    assert anamorfico.output_aspect(params.sanitize({"anam_on": True, "anam_compressao": sq}), 1920, 1080) == \
        pytest.approx(16 / 9 * float(sq))


@pytest.mark.gpu
def test_desqueeze_stretches_a_circle_back(gl_engine):
    img = _gray(level=20)
    yy, xx = np.mgrid[0:H, 0:W]
    # um círculo espremido 2× na horizontal (como o adaptador grava)
    inside = ((xx - W / 2) * 2.0) ** 2 + (yy - H / 2) ** 2 < 40 ** 2
    img[inside] = 220
    out = _render(gl_engine, img, anam_on=True, anam_compressao="2.0", anam_flare=0.0, anam_barril=0.0,
                  anam_bordas=0.0)
    m = out[..., 1] > 120
    ys, xs = np.nonzero(m)
    w = xs.max() - xs.min() + 1
    h = ys.max() - ys.min() + 1
    assert w == pytest.approx(h, rel=0.08), "o círculo volta a ser redondo"


@pytest.mark.gpu
def test_barrel_moves_the_middle_row_more(gl_engine):
    img = _gray(level=20)
    x = int(W * 0.8)
    img[:, x:x + 2] = 230
    out = _render(gl_engine, img, anam_on=True, anam_flare=0.0, anam_barril=1.0, anam_bordas=0.0)
    mid = np.flatnonzero(out[H // 2, :, 1] > 120).mean()
    top = np.flatnonzero(out[3, :, 1] > 120).mean()
    assert top == pytest.approx(x + 0.5, abs=1.0)
    assert mid > top + 5, "o centro estica na horizontal"


@pytest.mark.gpu
def test_edges_get_softer_than_the_center(gl_engine):
    img = _gray(level=20)
    for x in (W // 2, 12, W - 14):
        img[:, x:x + 2] = 230
    out = _render(gl_engine, img, anam_on=True, anam_flare=0.0, anam_barril=0.0, anam_bordas=1.0)
    row = out[H // 2, :, 1].astype(int)

    def spread(x):
        seg = row[x - 8:x + 10]
        return int((seg > 40).sum())
    assert spread(W // 2) <= 3
    assert spread(12) > spread(W // 2) and spread(W - 14) > spread(W // 2)


@pytest.mark.gpu
def test_flare_streak_is_horizontal_and_tinted(gl_engine):
    img = _gray(level=10)
    img[H // 2 - 2:H // 2 + 2, W // 2 - 2:W // 2 + 2] = 255
    base = _render(gl_engine, img).astype(int)
    out = _render(gl_engine, img, anam_on=True, anam_flare=1.0, anam_flare_limiar=0.0, anam_barril=0.0,
                  anam_bordas=0.0).astype(int)
    d = out - base
    far_x = d[H // 2, W // 2 + 80]
    far_y = d[H // 2 - 40, W // 2]
    assert far_x[2] > 3 and far_x[2] > far_x[0], "risco azul a 80 px na horizontal"
    assert np.abs(far_y).max() <= 1, "nada vaza na vertical"


# ------------------------------------------------------------------ data impressa
def test_date_text_formats():
    v = params.sanitize({"data_on": True, "data_ano": 1998, "data_mes": 3, "data_dia": 7})
    assert data_impressa.text(v) == "'98 03 07"
    assert data_impressa.text({**v, "data_formato": "mm_dd_aa"}) == "03 07 '98"
    assert data_impressa.text({**v, "data_formato": "dd_mm_aa"}) == "07 03 '98"
    assert data_impressa.text({**v, "data_formato": "aaaa_mm_dd"}) == "1998 03 07"


def _orange(out):
    o = out.astype(int)
    return (o[..., 0] - o[..., 2] > 60) & (o[..., 0] > 120)


@pytest.mark.gpu
@pytest.mark.parametrize("size", [(480, 270), (960, 540)])
@pytest.mark.parametrize("corner", ["inf_dir", "sup_esq"])
def test_date_pixels_are_where_the_layout_says(gl_engine, size, corner):
    w, h = size
    v = dict(data_on=True, data_canto=corner, data_tamanho=40.0, data_margem=60.0)
    out = _render(gl_engine, _gray(w, h, level=25), **v)
    ys, xs = np.nonzero(_orange(out))
    assert len(xs) > 30
    x0, y0, x1, y1 = data_impressa.box_px(params.sanitize(v), w, h)
    s = h / 1080.0
    tol = 3.0 * s + 1.5
    assert xs.min() == pytest.approx(x0, abs=tol) and xs.max() + 1 == pytest.approx(x1, abs=tol)
    assert ys.min() == pytest.approx(y0, abs=tol) and ys.max() + 1 == pytest.approx(y1, abs=tol)
    assert (y1 - y0) == pytest.approx(40.0 * s), "altura em px@1080"
    if corner == "inf_dir":
        assert x1 == pytest.approx(w - 60.0 * s) and y1 == pytest.approx(h - 60.0 * s)


@pytest.mark.gpu
def test_date_is_scene_light_before_the_film(gl_engine):
    v = dict(data_on=True, data_intensidade=1.0, data_tamanho=60.0)
    img = _gray(level=25)
    plain = _render(gl_engine, img, **v).astype(int)
    hal = _render(gl_engine, img, hal_on=True, hal_forca=1.0, hal_limiar=0.0, **v).astype(int)
    x0, y0, x1, y1 = data_impressa.box_px(params.sanitize(v), W, H)
    yb = int(y0) - 6  # logo acima dos números
    around = slice(int(x0), int(x1))
    assert hal[yb, around, 0].mean() > plain[yb, around, 0].mean() + 2, "a halação brilha em volta da data"
    grain = _render(gl_engine, img, grao_on=True, grao_forca=1.0, **v).astype(int)
    inside = _orange(plain)
    assert np.abs(grain[inside] - plain[inside]).max() > 0, "o grão fica por cima da data"
    neg = _render(gl_engine, img, cor_on=True, contraste=1.4, **v).astype(int)
    assert not np.array_equal(neg[inside], plain[inside]), "a cor da película passa pela data"


def test_modules_are_beta_and_detected():
    for mid, key in (("anamorfico", "anam_on"), ("data_impressa", "data_on")):
        assert modules.get(mid).status == modules.BETA
        assert mid not in modules.used_by(params.defaults())
        assert mid in modules.used_by(params.sanitize({key: True}))
