"""1.6, fotômetro da película (`fotometro.py`): a latitude segue o negativo escolhido (Vision3 × Double-X), a revelação,
a película vencida e a pré-exposição a movem como documentado, as zonas da camada caem nos stops certos, a leitura
de um ponto e os textos; e nada disso entra na receita do quadro nem na exportação."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pelicula import fotometro as fm
from pelicula import look, modules, params

ROOT = Path(__file__).resolve().parents[1]


def _v(**kw):
    return params.sanitize({**params.defaults(), "lab_on": True, **kw})


def _lat(**kw):
    return fm.latitude(_v(**kw))


# ------------------------------------------------------------------ latitude
def test_plain_negative_limits_are_the_toe_and_the_shoulder():
    """Sem forçar e sem luz somada, o contraste relativo é ½ exatamente no pé e no ombro de cada camada."""
    for neg in ("vision3_250d", "double_x", "vision3_500t_v2"):
        lat = _lat(lab_negativo=neg)
        curve = look.NEGATIVES[neg]
        for k in range(3):
            lo, hi, lod, hid = lat.layers[k]
            assert lo == pytest.approx(curve["toe"][k] / math.log10(2), abs=0.02), (neg, k)
            assert hi == pytest.approx(curve["shoulder"][k] / math.log10(2), abs=0.02), (neg, k)
            assert lod < lo < 0 < hi < hid
        assert lat.lo == max(x[0] for x in lat.layers) and lat.hi == min(x[1] for x in lat.layers)


def test_vision3_has_more_latitude_than_double_x():
    v3, dx = _lat(lab_negativo="vision3_250d"), _lat(lab_negativo="double_x")
    assert v3.lo < dx.lo and v3.hi > dx.hi
    assert v3.lo == pytest.approx(-5.15, abs=0.02) and v3.hi == pytest.approx(6.47, abs=0.02)
    assert dx.lo == pytest.approx(-4.65, abs=0.02) and dx.hi == pytest.approx(5.97, abs=0.02)
    assert len(set(dx.layers)) == 1, "preto e branco: as três camadas iguais"


def test_without_the_laboratory_the_default_negative_is_used():
    off = fm.latitude(params.defaults())
    assert off.default and off.negative == params.defaults()["lab_negativo"]
    on = _lat()
    assert not on.default and (off.lo, off.hi) == (on.lo, on.hi)
    assert fm.latitude(None).default


def test_push_closes_the_shadows_and_pull_opens_them():
    base, push1, push2, pull = _lat(), _lat(lab_revelacao=1.0), _lat(lab_revelacao=2.0), _lat(lab_revelacao=-1.0)
    step = 0.08 / math.log10(2)  # o pé sobe 0,08 log E por stop forçado
    assert push1.lo - base.lo == pytest.approx(step, abs=0.02)
    assert push2.lo - base.lo == pytest.approx(2 * step, abs=0.02)
    assert base.lo - pull.lo == pytest.approx(step, abs=0.02)
    assert push1.hi == base.hi == pull.hi, "o ombro não muda"


def test_expired_film_loses_speed_and_shadow_detail():
    base, ten, twenty = _lat(), _lat(lab_vencida=10), _lat(lab_vencida=20)
    assert base.lo < ten.lo < twenty.lo, "menos sensibilidade e o véu: o pé sobe"
    assert base.hi < ten.hi < twenty.hi, "o ombro também anda para a direita"
    assert twenty.lo == pytest.approx(-3.29, abs=0.05) and twenty.hi == pytest.approx(7.12, abs=0.05)
    blue_shift = twenty.layers[2][0] - base.layers[2][0]
    red_shift = twenty.layers[0][0] - base.layers[0][0]
    assert blue_shift > red_shift, "a camada do azul envelhece mais"


def test_flashing_smooths_the_shadows_without_losing_faint_detail():
    base = _lat()
    f4 = _lat(lab_pre_exposicao=True, lab_pre_exposicao_stops=4.0)
    f2 = _lat(lab_pre_exposicao=True, lab_pre_exposicao_stops=2.0)
    f6 = _lat(lab_pre_exposicao=True, lab_pre_exposicao_stops=6.0)
    assert base.lo < f6.lo < f4.lo < f2.lo, "mais luz somada, mais da sombra fica no pé (mais lisa)"
    assert f4.lo == pytest.approx(-3.83, abs=0.05)
    assert f4.lo_detail == pytest.approx(base.lo_detail, abs=0.05), "o detalhe fraco fica"
    assert f6.lo_detail < base.lo_detail, "uma luz fraca ainda estende o detalhe fraco"
    assert f4.hi == pytest.approx(base.hi, abs=0.02), "as altas luzes quase não mudam"


def test_relative_slope_is_one_on_the_straight_line():
    path = fm.negative_path(_v())
    rel = fm.relative_slope(path, np.array([-2.0, 0.0, 2.0]))
    assert np.all(rel > 0.98) and np.all(rel <= 1.0)
    assert np.all(fm.relative_slope(path, np.array([-12.0, 12.0])) < 0.01)


# ------------------------------------------------------------------ camada e leitura
def test_false_color_bands_at_known_stops():
    lat = _lat()
    st = np.array([-9.0, -6.0, -3.0, 0.0, 3.0, 7.5, 9.5])
    assert [fm.ZONE_IDS[i] for i in fm.zone_index(st, lat)] == ["sem_detalhe", "pe", "reta", "reta", "reta",
                                                                "ombro", "estourado"]
    rgba = fm.false_color(st, lat)
    colors = {z: c for z, c, _n in fm.ZONES}
    assert np.allclose(rgba[0, :3], colors["sem_detalhe"]) and np.allclose(rgba[1, :3], colors["pe"])
    assert np.allclose(rgba[3, :3], fm.GRAY_COLOR), "o cinza de 18% em verde"
    assert np.allclose(rgba[2, :3], rgba[2, 0]) and rgba[2, 0] < rgba[4, 0], "a reta em cinza pela exposição"
    assert np.allclose(rgba[5, :3], colors["ombro"]) and np.allclose(rgba[6, :3], colors["estourado"])
    assert np.all(rgba[:, 3] == 1.0)
    cover = np.array([1, 1, 0.5, 0, 1, 1, 1])
    assert np.allclose(fm.false_color(st, lat, cover)[:, 3], cover)
    # as fronteiras andam com o negativo: o mesmo +6,2 stops é reta no 250D e ombro no Double-X
    assert fm.zone_of(6.2, lat) == "reta" and fm.zone_of(6.2, _lat(lab_negativo="double_x")) == "ombro"


def test_spot_reading_of_gray_and_of_a_saturated_light():
    v = _v()
    lat = fm.latitude(v)
    r = fm.spot(np.full(3, 0.18 * 4), v)
    assert r.stops == pytest.approx(2.0) and r.zone == "reta"
    assert r.above_toe == pytest.approx(2.0 - lat.lo) and r.below_shoulder == pytest.approx(lat.hi - 2.0)
    assert all(z == "reta" for _s, z in r.layers)
    red = fm.spot(np.array([0.9, 0.05, 0.02]) * 30, v)
    assert red.zone == "reta" and red.layers[0][1] == "ombro", "a luz vermelha chega ao ombro da camada do vermelho"
    assert "R ombro" in fm.spot_text(red)
    dark = fm.spot(np.full(3, 0.18 / 2 ** 8), v)
    assert dark.zone == "sem_detalhe"


def test_texts_use_the_real_minus_and_the_decimal_comma():
    from pelicula import i18n
    i18n.set_language("pt_BR")
    assert fm.latitude_text(_lat()) == "−5,1 a +6,5 stops"
    assert fm.signed(0.04) == "0,0" and fm.signed(-1.25, 2) == "−1,25"
    assert fm.negative_name("double_x").startswith("Eastman Double-X") or "Double-X" in fm.negative_name("double_x")


# ------------------------------------------------------------------ só na tela
def test_nothing_in_the_render_path_knows_the_meter():
    for name in ("frame.py", "export.py", "look.py", "engine.py", "shaders.py", "cli.py", "sequence.py",
                 "compositor.py"):
        text = (ROOT / "pelicula" / name).read_text(encoding="utf-8")
        assert "fotometro" not in text, name


def test_module_is_beta_and_off_by_default():
    m = modules.get("fotometro")
    assert m.status == modules.BETA and m.group == "pelicula"
    assert not any("fotometro" in p[3] for p in modules.PROFILES)


# ------------------------------------------------------------------ processos especiais (decisão de 29/10)
def test_special_process_measures_the_process_film():
    base = _lat()
    cross = _lat(lab_processo="cruzado_e6c41")
    assert cross.negative == "processo:cruzado_e6c41"
    assert fm.negative_name(cross.negative) == "Revelação cruzada: slide no C-41"
    assert cross.hi - cross.lo < base.hi - base.lo, "o slide no C-41 tem menos latitude que o negativo"
    weak = _lat(lab_processo="cruzado_e6c41", lab_processo_forca=0.3)
    assert weak == base, "processo abaixo de 50% da mistura: vale o negativo escolhido"


def test_reversal_measures_the_final_image():
    rev = _lat(lab_processo="reversivel")
    assert rev.negative == "processo:reversivel"
    assert -1.5 < rev.lo < -0.7 and 1.4 < rev.hi < 2.2, "latitude curta de um slide"
    assert rev.lo_detail < rev.lo < 0.0 < rev.hi < rev.hi_detail
    r = fm.spot([0.18, 0.18, 0.18], _v(lab_processo="reversivel"))
    assert r.zone == "reta"
