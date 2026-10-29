"""Máscaras da 1.6 (`pelicula/masks.py`): pele e degradê, o numpy de referência e o GLSL na GPU."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import masks

# Escala Monk Skin Tone (Ellis Monk/Google, CC BY 4.0, https://skintone.google): os 10 tons, do mais claro ao
# mais escuro, como publicados (sRGB).
MONK = ["f6ede4", "f3e7db", "f7ead0", "eadaba", "d7bd96", "a07e56", "825c43", "604134", "3a312a", "292420"]

# O que a máscara da pele não pode pegar: laranja saturado, madeira, areia e cinza.
NOT_SKIN = {
    "laranja": "ff7f00", "laranja escuro": "ff8c00", "laranja queimado": "e8650a", "abóbora": "ff7518",
    "cenoura": "ed9121",
    "mogno": "c04000", "cerejeira": "6e2a12", "nogueira": "773f1a", "madeira escura": "8b4513",
    "ouro velho": "b8860b",
    "areia": "c2b280", "areia de praia": "e2ca76",
    "cinza": "808080", "cinza escuro": "202020", "cinza claro": "d0d0d0", "branco": "ffffff", "preto": "000000",
}


def code(hexes) -> np.ndarray:
    return np.array([[int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] for h in hexes])


def under(c: np.ndarray, stops: float) -> np.ndarray:
    """A mesma cor `stops` abaixo (luz × 2^-stops, de volta ao vídeo com gama 2,2)."""
    return c * 2.0 ** (-stops / 2.2)


# ------------------------------------------------------------------ pele
@pytest.mark.parametrize("stops", [0.0, 1.0])
def test_skin_mask_catches_the_whole_monk_scale(stops):
    m = masks.skin_mask(under(code(MONK), stops))
    assert m.min() >= 0.95, dict(zip(MONK, np.round(m, 3)))


def test_skin_mask_does_not_catch_orange_wood_sand_or_gray():
    m = masks.skin_mask(code(NOT_SKIN.values()))
    caught = {k: round(float(v), 3) for k, v in zip(NOT_SKIN, m) if v >= 0.05}
    assert not caught


def test_skin_mask_ignores_exposure_for_hue_and_saturation():
    """O OkLab é a raiz cúbica da luz: matiz e C/L não mudam com a exposição (só a claridade)."""
    lin = masks.code_to_lin(code(MONK[3:8]))
    for k in (0.25, 0.5, 2.0):
        L0, C0, h0 = masks.oklch(lin)
        L1, C1, h1 = masks.oklch(lin * k)
        assert np.allclose(h0, h1, atol=1e-9)
        assert np.allclose(C0 / L0, C1 / L1, atol=1e-9)


def test_eyedropper_centers_the_window_on_the_picked_skin():
    tone = code(["a07e56"])
    hue = masks.skin_hue_of(tone)
    _L, _C, h = masks.oklch(masks.code_to_lin(tone))
    assert hue == pytest.approx(float(h[0]) % 360.0)
    # um centro bem longe deixa a cor de fora; o do conta-gotas a traz de volta mesmo com a janela estreita
    assert masks.skin_mask(tone, hue=hue + 90.0)[0] == 0.0
    assert masks.skin_mask(tone, hue=hue, width=4.0)[0] == pytest.approx(1.0)
    assert masks.skin_hue_of(code(["808080"])) is None
    assert masks.skin_hue_of(np.zeros((3, 3, 3))) is None
    # uma área: a média da luz
    area = np.concatenate([code(["a07e56"]), code(["825c43"])])
    assert masks.skin_hue_of(area) is not None


def test_oklab_round_trip_and_white_point():
    rng = np.random.default_rng(3)
    lin = rng.uniform(0.0, 4.0, (200, 3))
    assert np.allclose(masks.oklab_to_lin(masks.oklab(lin)), lin, atol=1e-7)
    lab = masks.oklab(np.ones(3))
    assert lab[0] == pytest.approx(1.0, abs=1e-4) and abs(lab[1]) < 1e-4 and abs(lab[2]) < 1e-4


# ------------------------------------------------------------------ degradê
def test_linear_gradient_points_like_a_compass():
    top, bottom, left, right = (0.0, -400.0), (0.0, 400.0), (-400.0, 0.0), (400.0, 0.0)
    pts = np.array([top, bottom, left, right])
    up = masks.gradient_mask(pts, "linear", angle=0.0, soft=100.0)
    assert up.tolist() == [1.0, 0.0, 0.5, 0.5]
    assert masks.gradient_mask(pts, "linear", angle=90.0, soft=100.0)[2:].tolist() == pytest.approx([0.0, 1.0])
    assert masks.gradient_mask(pts, "linear", angle=180.0, soft=100.0)[:2].tolist() == pytest.approx([0.0, 1.0])
    assert masks.gradient_mask(pts, "linear", angle=0.0, soft=100.0, invert=True).tolist() == [0.0, 1.0, 0.5, 0.5]
    # a linha passa pelo centro escolhido; suavidade 0 = borda seca
    line = masks.gradient_mask(np.array([[0.0, -10.0], [0.0, 10.0]]), "linear", cy=-20.0, soft=0.0)
    assert line.tolist() == [0.0, 0.0]
    assert masks.gradient_mask(np.array([[0.0, -30.0]]), "linear", cy=-20.0, soft=0.0).tolist() == [1.0]


def test_radial_gradient_is_one_inside_the_circle():
    pts = np.array([[0.0, 0.0], [300.0, 0.0], [0.0, 360.0], [900.0, 500.0]])
    m = masks.gradient_mask(pts, "radial", radius=360.0, soft=0.0)
    assert m.tolist() == [1.0, 1.0, 1.0, 0.0]
    m = masks.gradient_mask(pts, "radial", radius=360.0, soft=240.0)
    assert m[0] == 1.0 and m[2] == pytest.approx(0.5) and m[3] == 0.0
    off = masks.gradient_mask(np.array([[500.0, 0.0]]), "radial", cx=500.0, radius=10.0, soft=0.0)
    assert off.tolist() == [1.0]


@pytest.mark.parametrize("w,h", [(64, 36), (256, 144), (1920, 1080)])
def test_masks_do_not_depend_on_the_resolution(w, h):
    """px@1080: o mesmo lugar do quadro dá o mesmo valor em qualquer resolução."""
    p = masks.frame_points(w, h)
    assert p[0, 0, 1] == pytest.approx(-540.0 + 540.0 / h)
    assert p[0, 0, 0] == pytest.approx(-540.0 * w / h + 540.0 / h)
    for kind in ("linear", "radial"):
        m = masks.gradient_mask(p, kind, cx=100.0, cy=-50.0, angle=30.0, radius=300.0, soft=200.0)
        ref = masks.gradient_mask(masks.frame_points(1920, 1080), kind, cx=100.0, cy=-50.0, angle=30.0,
                                  radius=300.0, soft=200.0)
        assert m.mean() == pytest.approx(ref.mean(), abs=0.01)
    # a pele é por pixel: a mesma imagem ampliada tem a mesma fração de pele
    tones = code(MONK + list(NOT_SKIN.values())).reshape(3, 9, 3)
    small = masks.skin_mask(tones)
    big = masks.skin_mask(np.repeat(np.repeat(tones, 7, axis=0), 7, axis=1))
    assert big.mean() == pytest.approx(small.mean())


def test_gradient_uniform_packs_the_glsl_arguments():
    g, k = masks.gradient_uniform("radial", 10.0, -20.0, 90.0, 300.0, 50.0, True)
    assert g == pytest.approx((10.0, -20.0, np.pi / 2, 50.0)) and k == (300.0, 1.0, 1.0, 0.0)
    _g, k = masks.gradient_uniform("linear", 0, 0, 0, 1, 0, False)
    assert k[1:3] == (0.0, 0.0)


# ------------------------------------------------------------------ GLSL × numpy
_PROBE = """
#version 330
in vec2 v_uv;
out vec4 f_out;
uniform sampler2D t_code;
uniform vec2 u_win;
uniform vec4 u_g;
uniform vec4 u_k;
""" + masks.GLSL + """
void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy);
    vec2 size = vec2(textureSize(t_code, 0));
    vec3 c = texelFetch(t_code, ip, 0).rgb;
    vec3 back = oklabToLin(linToOklab(c));
    f_out = vec4(skinMask(c, u_win), gradMask(framePoint(gl_FragCoord.xy / size, size.x / size.y), u_g, u_k),
                 linToOklab(c).x, back.g);
}
"""


def _probe(engine, img: np.ndarray, win, g, k) -> np.ndarray:
    import moderngl

    from pelicula import shaders
    ctx = engine.ctx
    h, w = img.shape[:2]
    tex = ctx.texture((w, h), 3, data=np.ascontiguousarray(img, dtype="f4").tobytes(), dtype="f4")
    tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    out = ctx.texture((w, h), 4, dtype="f4")
    fbo = ctx.framebuffer(color_attachments=[out])
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=_PROBE)
    vbo = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
    vao = ctx.vertex_array(prog, [(vbo, "2f", "in_pos")])
    try:
        fbo.use()
        tex.use(location=0)
        prog["t_code"].value = 0
        prog["u_win"].value = tuple(win)
        prog["u_g"].value = tuple(g)
        prog["u_k"].value = tuple(k)
        vao.render(moderngl.TRIANGLE_STRIP)
        return np.frombuffer(fbo.read(components=4, dtype="f4"), dtype="f4").reshape(h, w, 4).astype(np.float64)
    finally:
        for obj in (vao, vbo, prog, fbo, out, tex):
            obj.release()


@pytest.mark.gpu
@pytest.mark.parametrize("kind,invert", [("linear", False), ("radial", False), ("linear", True)])
def test_glsl_masks_match_numpy(gl_engine, kind, invert):
    rng = np.random.default_rng(11)
    h, w = 36, 64
    img = rng.uniform(0.0, 1.0, (h, w, 3))
    img[:3, :10] = code(MONK)[None]          # pele de verdade e cores perto das bordas das janelas
    img[3:5, :17] = code(NOT_SKIN.values())[None]
    win = (masks.SKIN_HUE, masks.SKIN_WIDTH)
    g, k = masks.gradient_uniform(kind, 40.0, -30.0, 35.0, 300.0, 180.0, invert)
    got = _probe(gl_engine, img, win, g, k)
    assert np.abs(got[..., 0] - masks.skin_mask(img)).max() < 2e-3
    ref = masks.gradient_mask(masks.frame_points(w, h), kind, 40.0, -30.0, 35.0, 300.0, 180.0, invert)
    assert np.abs(got[..., 1] - ref).max() < 1e-4
    assert np.abs(got[..., 2] - masks.oklab(img)[..., 0]).max() < 1e-5
    assert np.abs(got[..., 3] - img[..., 1]).max() < 1e-4
