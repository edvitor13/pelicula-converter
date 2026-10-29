"""Cor por planos (1.6, `pelicula/planes.py`): a seção do look, o numpy de referência e o BASE_CP na GPU."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import look, masks, params, planes, shaders

W, H = 192, 108


def values(**kw) -> dict:
    v = params.defaults()
    v.update(bitola="nenhuma", proj_on=False, lente_on=False, bitola_vinheta=0.0, grao_on=False, hal_on=False,
             bloom_on=False, desg_on=False, mold_on=False, scan_on=False)
    v.update(kw)
    return params.sanitize(v)


def scene() -> np.ndarray:
    """Pele (escala Monk), céu, verde e rampas: 8 bits."""
    from test_masks import MONK, code
    y, x = np.mgrid[0:H, 0:W]
    img = np.stack([x / W, 0.3 + 0.4 * y / H, 1.0 - x / W], axis=-1)
    tones = code(MONK)
    for i, t in enumerate(tones):
        img[40:70, 8 + i * 18:24 + i * 18] = t
    img[:20] = (0.45, 0.62, 0.85)
    img[85:] = (0.25, 0.5, 0.2)
    return np.rint(np.clip(img, 0, 1) * 255).astype(np.uint8)


# ------------------------------------------------------------------ esquema
def test_section_is_appended_with_neutral_defaults():
    keys = [s.key for s in params.SECTIONS]
    i = keys.index("planos")
    # 1.6, frente E (câmera e formato): seções acrescentadas depois da Cor por planos
    assert all(k in ("obturador", "anamorfico", "data", "montagem_filme") for k in keys[i + 1:]), keys[i + 1:]
    sec = params.SECTIONS[i]
    assert sec.toggle == "planos_on" and params.PARAMS["planos_on"].default is False
    for k in planes.EFFECT_KEYS:
        assert params.PARAMS[k].default == 0.0, k
    assert params.PARAMS["planos_proteger_pele"].default is True
    assert params.PARAMS["planos_pele_centro"].default == masks.SKIN_HUE
    assert params.PARAMS["planos_pele_largura"].default == masks.SKIN_WIDTH
    for k in planes.GEOMETRY_KEYS + planes.SKIN_WINDOW_KEYS + planes.EFFECT_KEYS:
        assert k in params.PARAMS and k.isascii()


def test_nothing_to_do_keeps_the_plan_of_the_base():
    """Desligada, ou ligada com os ajustes em zero, a seção não põe nada no plano: o look segue no BASE."""
    base = look.build_plan(values(), W, H, 3, 24.0).uniforms
    for v in (values(planos_on=True), values(planos_fundo_exposicao=-1.0),
              values(planos_on=True, planos_tipo="radial", planos_raio=50.0, planos_proteger_pele=False)):
        assert planes.uniforms(v) == {}
        assert look.build_plan(v, W, H, 3, 24.0).uniforms.keys() == base.keys()
    on = look.build_plan(values(planos_on=True, planos_fundo_exposicao=-1.0), W, H, 3, 24.0).uniforms
    assert {k for k in on if k not in base} == set(planes.uniforms(values(planos_on=True,
                                                                           planos_fundo_exposicao=-1.0)))


def test_only_the_planes_hook_differs_from_the_base_program():
    src = planes.BASE_CP
    assert "vec3 imageLinRaw(vec2 uv) {" in src and "return planes(imageLinRaw(uv), uv);" in src
    rebuilt = src.replace("vec3 imageLinRaw(vec2 uv) {", "vec3 imageLin(vec2 uv) {")
    hook = planes.GLSL + "\nvec3 imageLin(vec2 uv) { return planes(imageLinRaw(uv), uv); }\n\n"
    assert rebuilt.replace(hook, "") == shaders.BASE


def test_prontos_only_fill_the_controls():
    v = planes.apply_pronto(values(planos_frente_saturacao=40.0), "destacar")
    assert v["planos_on"] and v["planos_tipo"] == "radial" and v["planos_fundo_exposicao"] == -0.5
    assert v["planos_frente_saturacao"] == 0.0  # zera o que o pronto não usa
    assert set(planes.apply_pronto(values(), "pele_natural")) == set(values())
    assert len({i for i, _n, _v in planes.PRONTOS}) == len(planes.PRONTOS)


# ------------------------------------------------------------------ matemática (numpy)
def test_skin_is_protected_from_front_and_back():
    from test_masks import MONK, code
    lin = masks.code_to_lin(code(MONK))  # luz "de vídeo"; a máscara vê a pele pela curva neutra
    lin = 0.18 * np.exp2(look._disp_to_stops(code(MONK)))
    p = np.zeros((len(MONK), 2))
    on = values(planos_on=True, planos_fundo_exposicao=-1.0, planos_frente_exposicao=-1.0)
    assert np.allclose(planes.apply(lin, p, on), lin, rtol=0, atol=1e-6 * lin.max())
    off = dict(on, planos_proteger_pele=False)
    assert np.allclose(planes.apply(lin, p, off), lin * 0.5, rtol=1e-9)


def test_front_and_back_follow_the_gradient():
    lin = np.full((3, 3), 0.18)
    p = np.array([[0.0, -500.0], [0.0, 0.0], [0.0, 500.0]])  # em cima, no centro, embaixo
    v = values(planos_on=True, planos_fundo_exposicao=-1.0, planos_frente_exposicao=1.0, planos_suavidade=200.0)
    out = planes.apply(lin, p, v)[:, 1] / 0.18
    assert out[0] == pytest.approx(0.5) and out[2] == pytest.approx(2.0) and out[1] == pytest.approx(1.25)
    radial = dict(v, planos_tipo="radial", planos_raio=100.0, planos_suavidade=0.0)
    out = planes.apply(lin, p, radial)[:, 1] / 0.18
    assert out.tolist() == pytest.approx([0.5, 2.0, 0.5])
    swapped = dict(radial, planos_inverter=True)
    assert (planes.apply(lin, p, swapped)[:, 1] / 0.18).tolist() == pytest.approx([2.0, 0.5, 2.0])


def test_plane_controls():
    lin = np.array([[0.18, 0.18, 0.18], [0.36, 0.09, 0.05], [0.72, 0.72, 0.72]])
    p = np.zeros((3, 2))
    base = dict(planos_on=True, planos_proteger_pele=False, planos_tipo="radial", planos_raio=500.0,
                planos_suavidade=0.0)
    gray = planes.apply(lin, p, values(**base, planos_frente_saturacao=-100.0))
    assert np.allclose(gray[1], gray[1].mean(), atol=0) or np.ptp(gray[1]) < 1e-12
    con = planes.apply(lin, p, values(**base, planos_frente_contraste=100.0))
    assert con[0] == pytest.approx(lin[0]) and con[2] == pytest.approx(0.18 * 4.0 ** 1.5)
    warm = planes.apply(lin, p, values(**base, planos_frente_temperatura=50.0))[0]
    assert warm[0] > 0.18 > warm[2]


def test_even_skin_keeps_the_lightness():
    from test_masks import MONK, code
    lab = masks.oklab(masks.code_to_lin(code(MONK)))
    even = masks.skin_even(lab, masks.SKIN_HUE, 1.0)
    assert np.allclose(even[:, 0], lab[:, 0])
    h0 = masks.hue_distance(np.degrees(np.arctan2(lab[:, 2], lab[:, 1])), masks.SKIN_HUE)
    h1 = masks.hue_distance(np.degrees(np.arctan2(even[:, 2], even[:, 1])), masks.SKIN_HUE)
    assert np.all(h1 <= h0 + 1e-9) and np.allclose(h1, 0.3 * h0)


# ------------------------------------------------------------------ GPU
@pytest.mark.gpu
def test_neutral_section_renders_the_same_bits(gl_engine):
    from pelicula import frame
    img = scene()
    for depth in (8, 16):
        src = img if depth == 8 else img.astype(np.uint16) * 257
        a = frame.Recipe.for_source(values(), 24.0, depth, legal=True).render(gl_engine, src, 5)
        b = frame.Recipe.for_source(values(planos_on=True), 24.0, depth, legal=True).render(gl_engine, src, 5)
        assert np.array_equal(a, b)


@pytest.mark.gpu
@pytest.mark.parametrize("extra", [
    dict(planos_fundo_exposicao=-1.0, planos_fundo_saturacao=-50.0, planos_frente_temperatura=30.0),
    dict(planos_tipo="radial", planos_raio=300.0, planos_frente_contraste=60.0, planos_fundo_tonalidade=-40.0,
         planos_proteger_pele=False),
    dict(planos_pele_matiz=-10.0, planos_pele_saturacao=30.0, planos_pele_luz=0.5, planos_pele_uniformizar=0.8,
         planos_frente_exposicao=0.5),
])
def test_gpu_planes_match_numpy(gl_engine, extra):
    v_off = values()
    v_on = values(planos_on=True, **extra)
    gl_engine.set_input(scene())
    lin = gl_engine.scene_light(look.build_plan(v_off, W, H, 0, 24.0))[..., :3].astype(np.float64)
    got = gl_engine.scene_light(look.build_plan(v_on, W, H, 0, 24.0))[..., :3].astype(np.float64)
    want = planes.apply(lin, masks.frame_points(W, H), v_on)
    err = np.abs(got - want) / (1.0 + np.abs(want))
    assert np.percentile(err, 99.5) < 2e-3 and err.max() < 3e-2
    assert np.abs(got - lin).max() > 0.01  # e fez alguma coisa


@pytest.mark.gpu
def test_view_shows_the_masks_and_export_is_unchanged(gl_engine):
    v = values(planos_on=True, planos_tipo="radial", planos_raio=250.0, planos_suavidade=100.0)
    gl_engine.set_input(scene())
    plan = look.build_plan(v, W, H, 0, 24.0)
    lin = gl_engine.scene_light(plan)[..., :3].astype(np.float64)
    view = gl_engine.plane_view(plan, v)
    front, skin = planes.weights(lin, masks.frame_points(W, H), v)
    assert np.abs(view[..., 2] - skin).max() < 3e-3
    assert np.abs(view[..., 0] - front * (1.0 - skin)).max() < 3e-3
    assert np.allclose(view[..., 3], 1.0)
    # mostrar os planos não muda o quadro seguinte nem o LUT exportado
    from pelicula import frame
    r = frame.Recipe.for_source(values(planos_on=True, planos_fundo_exposicao=-1.0), 24.0, 8, legal=True)
    a = r.render(gl_engine, scene(), 2)
    gl_engine.plane_view(plan, v)
    assert np.array_equal(r.render(gl_engine, scene(), 2), a)
    assert np.array_equal(gl_engine.bake_lut(values(planos_on=True, planos_fundo_exposicao=-1.0), 9),
                          gl_engine.bake_lut(values(), 9))


@pytest.mark.gpu
def test_planes_do_not_depend_on_the_resolution(gl_engine):
    v = values(planos_on=True, planos_tipo="radial", planos_raio=300.0, planos_fundo_exposicao=-1.0)
    means = []
    for w, h in ((W, H), (W * 3, H * 3)):
        img = np.repeat(np.repeat(scene(), w // W, axis=0), w // W, axis=1)
        gl_engine.set_input(img)
        out = gl_engine.scene_light(look.build_plan(v, w, h, 0, 24.0))[..., :3]
        means.append(float(out.mean()))
    assert means[0] == pytest.approx(means[1], rel=0.01)
