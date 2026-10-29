"""Ajustes por clipe do modo Edição: uniforms (compositor.py) e montagem na GPU (Engine.compose)."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from pelicula import compositor, editparams, editshaders, sequence
from pelicula import timeline as tl

W, H = 320, 180
_SIZES = {"int": 1, "float": 1, "vec2": 2, "vec3": 3, "vec4": 4, "mat3": 9}


def _declared(src: str = editshaders.CLIP) -> dict[str, tuple[str, int]]:
    out = {}
    for typ, name, arr in re.findall(r"uniform\s+(\w+)\s+(u_\w+)\s*(?:\[(\d+)\])?\s*;", src):
        out[name] = (typ, int(arr) if arr else 1)
    return out


DECLARED = _declared()
DECLARED_CS = _declared(editshaders.CLIP_CS)  # 1.6: os da cor simples só vêm com ela (`colorsimple.uniforms`)
GEOMETRY = {"degrade_tipo", "degrade_angulo", "degrade_x", "degrade_y", "degrade_raio", "degrade_suavidade",
            "degrade_inverter"}


def one_clip(w=W, h=H, image=True, **values):
    s = tl.Source("cena.png" if image else "cena.mp4", w, h, 24.0, "24/1", 1 if image else 48, 0.0 if image else 2.0,
                  is_image=image, has_audio=False)
    seq = tl.Sequence.for_source(s)
    c = seq.clips[0]
    if values:
        seq.set_values(c.id, {**c.values, **values})
    return seq, c


def uniforms(seq, c, tex=(W, H), canvas=(W, H), neutral=False, layer=None):
    layer = layer or seq.layers_at(c.start)[0]
    return compositor.clip_uniforms(seq, layer, tex[0], tex[1], canvas[0], canvas[1], neutral)


def assert_matches_shader(U: dict):
    declared = DECLARED_CS if "u_cs_on" in U else DECLARED
    for k, val in U.items():
        assert k in declared, f"{k} não existe no shader CLIP"
        typ, n = declared[k]
        got = len(val) if isinstance(val, (tuple, list)) else 1
        assert got == _SIZES[typ] * n, f"{k}: {typ}[{n}] recebeu {val!r}"
        assert not isinstance(val, list), f"{k}: use tupla"
        for x in (val if isinstance(val, tuple) else (val,)):
            if typ == "int":
                assert isinstance(x, int)
            else:
                assert isinstance(x, (int, float)) and math.isfinite(x), f"{k}: {x!r}"


# ------------------------------------------------------------------ uniforms (sem GPU)
def test_neutral_clip_is_exact_passthrough():
    seq, c = one_clip()
    U, mip = uniforms(seq, c)
    assert U["u_cc_on"] == 0 and U["u_det_on"] == 0 and U["u_exact"] == 1 and not mip
    assert U["u_alpha"] == 1.0 and U["u_fade"][3] == 0.0 and U["u_blend"] == 0
    assert_matches_shader(U)


def test_every_uniform_of_the_shader_is_filled():
    seq, c = one_clip()
    U, _mip = uniforms(seq, c)
    assert set(DECLARED) == set(U), set(DECLARED) ^ set(U)


def _non_default(p):
    if p.kind == "float":
        return p.max if p.default != p.max else p.min
    if p.kind == "bool":
        return not p.default
    if p.kind == "choice":
        return next(v for v, _l in p.choices if v != p.default)
    if p.kind == "wheel":
        return [0.6, 0.3]
    raise AssertionError(p.kind)


@pytest.mark.parametrize("key", list(editparams.VIDEO.params))
def test_every_video_param_gives_valid_uniforms(key):
    p = editparams.VIDEO.params[key]
    seq, c = one_clip(**{key: _non_default(p)})
    U, _mip = uniforms(seq, c)
    assert_matches_shader(U)
    if key in editparams.color_keys() and key not in compositor.DETAIL_KEYS and key != "vinheta_tamanho":
        assert U["u_cc_on"] == 1, key
    if key in compositor.DETAIL_KEYS:
        assert U["u_det_on"] == 1
    Un, _ = uniforms(seq, c, neutral=True)
    assert Un["u_cc_on"] == 0 and Un["u_det_on"] == 0


def test_transform_identity_scale_flip_and_rotation():
    seq, c = one_clip()
    m = compositor.transform(seq, c, W, H)
    np.testing.assert_allclose(m @ [W / 2, H / 2, 1], [0.5, 0.5, 1])
    np.testing.assert_allclose(m @ [0, 0, 1], [0, 0, 1], atol=1e-12)
    seq.set_values(c.id, {**c.values, "escala": 0.5})
    m = compositor.transform(seq, c, W, H)
    np.testing.assert_allclose(m @ [W / 4, H / 4, 1], [0, 0, 1], atol=1e-12)  # canto do clipe reduzido
    seq.set_values(c.id, {**c.values, "escala": 1.0, "espelhar_h": True})
    np.testing.assert_allclose(compositor.transform(seq, c, W, H) @ [0, 0, 1], [1, 0, 1], atol=1e-12)
    seq.set_values(c.id, {**c.values, "espelhar_h": False, "pos_x": 0.25, "pos_y": -0.5})
    np.testing.assert_allclose(compositor.transform(seq, c, W, H) @ [W * 0.75, 0, 1], [0.5, 0.5, 1])
    sq, cq = one_clip(100, 100)
    sq.set_values(cq.id, {**cq.values, "rotacao": 90.0})
    m = compositor.transform(sq, cq, 100, 100)
    # 90° no sentido horário: o topo do clipe vai para a direita da tela
    np.testing.assert_allclose(m @ [100, 50, 1], [0.5, 0.0, 1], atol=1e-9)
    assert uniforms(sq, cq, (100, 100), (100, 100))[0]["u_exact"] == 0


def test_fit_modes():
    s = tl.Source("v.png", 400, 300, is_image=True)  # 4:3 numa tela 16:9
    seq = tl.Sequence(width=1600, height=900)
    (c,) = seq.insert_media(s)
    assert compositor.fit_box(seq, c, 1600, 900) == pytest.approx((1200, 900))
    seq.set_values(c.id, {**c.values, "encaixe": "preencher"})
    assert compositor.fit_box(seq, c, 1600, 900) == pytest.approx((1600, 1200))
    seq.set_values(c.id, {**c.values, "encaixe": "esticar"})
    assert compositor.fit_box(seq, c, 1600, 900) == (1600, 900)


def test_wheel_convention():
    red = compositor.wheel_tint([1.0, 0.0])
    green = compositor.wheel_tint([math.cos(math.radians(120)), math.sin(math.radians(120))])
    assert red[0] > 0 > red[1] and green[1] > 0 > green[0]
    for t in (red, green, compositor.wheel_tint([0.3, -0.4])):
        assert sum(a * b for a, b in zip(t, compositor.W709)) == pytest.approx(0.0, abs=1e-9)
    assert compositor.wheel_tint([0, 0]) == (0.0, 0.0, 0.0)
    assert compositor.wheel_hue([0.0, 1.0]) == pytest.approx(90.0)


def test_layer_alpha_and_fade_go_to_uniforms():
    seq, c = one_clip(opacidade=0.5, mesclagem="multiplicar")
    layer = tl.Layer(c, 0, alpha=0.5, fade_color=(1.0, 1.0, 1.0), fade=0.25)
    U, _ = uniforms(seq, c, layer=layer)
    assert U["u_alpha"] == pytest.approx(0.25) and U["u_fade"] == (1.0, 1.0, 1.0, 0.25) and U["u_blend"] == 2


def test_auto_adjust_directions():
    rng = np.linspace(0.05, 0.35, 64)
    img = np.zeros((64, 64, 3))
    img[:] = rng[None, :, None]
    img[..., 2] *= 1.25  # escuro e azulado
    out = compositor.auto_adjust((np.clip(img, 0, 1) * 255).astype(np.uint8))
    assert out["exposicao"] > 0
    assert out["temperatura"] > 0  # esquenta para tirar o azul
    for k, v in out.items():
        p = editparams.VIDEO.params[k]
        assert p.min <= v <= p.max
    assert compositor.auto_adjust(np.zeros((0, 0, 3), np.uint8)) == {}


# ------------------------------------------------------------------ GPU
pytest_gpu = pytest.mark.gpu


def frame_of(seq, img):
    return sequence.FrameLayers(0, [sequence.LayerImage(l, img) for l in seq.layers_at(0)])


@pytest_gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_compose_neutral_is_bit_exact(gl_engine, test_rgb, depth):
    img = test_rgb if depth == 8 else test_rgb.astype(np.uint16) * 257 + 5
    seq, c = one_clip()
    out = gl_engine.compose(frame_of(seq, img), seq, W, H, depth)
    assert out.dtype == img.dtype and np.array_equal(out, img)
    seq.set_values(c.id, {**c.values, "exposicao": 2.0, "saturacao": -1.0, "nitidez": 0.5})
    assert np.array_equal(gl_engine.compose(frame_of(seq, img), seq, W, H, depth, neutral=True), img)


@pytest_gpu
def test_compose_every_param_runs(gl_engine, test_rgb):
    transition_keys = {p.key for s in editparams.VIDEO_SECTIONS if s.key == "transicao" for p in s.params}
    for key, p in editparams.VIDEO.params.items():
        if key in ("velocidade", "congelar") or key in transition_keys:  # transições: tests/test_transitions.py
            continue
        if key.startswith("camera_"):  # perfil de câmera do clipe (1.6): pela receita, tests/test_entrada_camera.py
            continue
        seq, c = one_clip(**{key: _non_default(p)})
        out = gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8)
        assert out.shape == (H, W, 3)
        # encaixe: mesma proporção da tela; 1.6: a janela da pele, a cor escolhida e a forma do degradê só valem
        # com os ajustes deles
        alone = ("pele_centro", "alvo_matiz", "alvo_largura") + tuple(k for k in editparams.VIDEO.params
                                                                  if k.startswith("degrade_") and k in GEOMETRY)
        if key not in ("vinheta_tamanho", "mesclagem", "encaixe") + alone:
            assert not np.array_equal(out, test_rgb), f"{key} não mudou a imagem"


@pytest_gpu
def test_compose_directions(gl_engine, test_rgb):
    base = test_rgb.astype(np.float64)

    def run(**v):
        seq, _c = one_clip(**v)
        return gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8).astype(np.float64)

    assert run(exposicao=1.0).mean() > base.mean() + 10
    assert run(exposicao=-1.0).mean() < base.mean() - 10
    gray = run(saturacao=-1.0)
    assert np.abs(gray[..., 0] - gray[..., 2]).max() <= 2
    warm = run(temperatura=60)
    assert (warm[..., 0] - warm[..., 2]).mean() > (base[..., 0] - base[..., 2]).mean() + 5
    assert run(pretos=0.8).min() > base.min() + 5  # pretos levantados
    small = run(escala=0.5)
    assert small[2, 2].max() == 0  # o canto vira fundo (preto)
    cropped = run(corte_esq=0.5)
    assert cropped[:, :W // 2 - 2].max() == 0 and cropped[:, W // 2 + 2:].max() > 0
    assert run(opacidade=0.5).mean() == pytest.approx(base.mean() / 2, abs=1.5)


@pytest_gpu
def test_compose_background_layers_and_blend(gl_engine, test_rgb):
    seq, c = one_clip()
    seq.background = (1.0, 0.0, 0.0)
    empty = gl_engine.compose(sequence.FrameLayers(0, []), seq, W, H, 8)
    assert (empty[..., 0] == 255).all() and (empty[..., 1:] == 0).all()
    seq.background = (0.0, 0.0, 0.0)
    top, = seq.insert_media(tl.Source("cima.png", W, H, is_image=True), at=0, vtrack=1)
    white = np.full_like(test_rgb, 255)
    half = np.full_like(test_rgb, 128)
    seq.set_values(top.id, {**top.values, "mesclagem": "multiplicar"})
    layers = seq.layers_at(0)
    fl = sequence.FrameLayers(0, [sequence.LayerImage(layers[0], white), sequence.LayerImage(layers[1], half)])
    out = gl_engine.compose(fl, seq, W, H, 8)
    assert np.abs(out.astype(int) - 128).max() <= 1
    fade = tl.Layer(c, 0, 1.0, (1.0, 1.0, 1.0), 1.0)
    out = gl_engine.compose(sequence.FrameLayers(0, [sequence.LayerImage(fade, test_rgb)]), seq, W, H, 8)
    assert (out == 255).all()


@pytest_gpu
def test_compose_smaller_decode_is_scaled(gl_engine, test_rgb):
    seq, c = one_clip()
    half = test_rgb[::2, ::2].copy()
    fl = sequence.FrameLayers(0, [sequence.LayerImage(seq.layers_at(0)[0], half)])
    out = gl_engine.compose(fl, seq, W, H, 8)
    assert out.shape == (H, W, 3)
    assert abs(out.astype(float).mean() - test_rgb.astype(float).mean()) < 3


@pytest_gpu
def test_compose_is_deterministic(gl_engine, test_rgb):
    seq, c = one_clip(clareza=0.7, desfoque=0.3, reducao_ruido=0.5, hsl_azul_matiz=0.8, roda_sombras=[0.2, 0.5])
    a = gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8)
    b = gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8)
    assert np.array_equal(a, b)


def test_quick_looks_reset_color_and_keep_framing():
    seq, c = one_clip(exposicao=1.0, escala=0.5, rotacao=10.0)
    for key, _label, look in editparams.QUICK_LOOKS:
        v = editparams.apply_quick_look(c.values, key)
        assert v["escala"] == 0.5 and v["rotacao"] == 10.0
        assert v["exposicao"] == look.get("exposicao", 0.0)
        for k, val in look.items():
            assert v[k] == pytest.approx(val)
    assert editparams.apply_quick_look(c.values, "nao_existe")["exposicao"] == 0.0
