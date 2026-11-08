"""1.9: pilha de efeitos do clipe (`vfx.py`, `Engine._fx_stack`; ARQUITETURA §49).

Os efeitos daqui são registrados só nos testes (`vfx.register` num fixture, tirados no fim): provam o caminho (GPU ==
numpy, efeito desligado = nenhum passo e a tela bit a bit, 8 e 16 bits, a montagem gêmea, prévia == exportação), sem
depender de nenhum efeito de verdade.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import compositor, sequence, vfx
from pelicula import timeline as tl

W, H = 64, 36
KIND = "gerador"
# O efeito de teste liga por este estado (não há ajuste de efeito no esquema da base): `mode` diz o que ele faz e
# `clips` (ids) limita a quais clipes; as cópias da sequência (leitor da exportação, aninhar) mantêm os ids.
STATE: dict = {"mode": "", "clips": None, "sigma": 30.0}


def gen(seq, clip, frame, w, h, depth):
    """Gerador de teste: um degradê com a cor da fonte e uma barra que anda com o quadro."""
    src = seq.sources[clip.src]
    r, g, b = src.data.get("cor", [1.0, 0.5, 0.0])
    x = np.linspace(0.1, 0.9, w)[None, :, None]
    y = np.linspace(0.2, 1.0, h)[:, None, None]
    img = np.concatenate([x * r * y, x * 0 + g * y * 0.7, (1 - x) * b * y], axis=2)
    img[:, (frame * 3) % w] = 1.0
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


INVERT = """
uniform float u_gain;
void main() {
    vec4 c = texture(t_prev, v_uv);
    f_out = vec4(u_gain * (1.0 - c.rgb), c.a);
}
"""

BELOW = """
void main() {
    f_out = fxBelow(v_uv);
}
"""

ROUNDTRIP = """
void main() {
    vec4 c = texture(t_prev, v_uv);
    f_out = vec4(fxEnc(fxDec(c.rgb)), c.a);
}
"""


def _passes(ctx):
    mode = STATE["mode"]
    if STATE["clips"] is not None and ctx.clip.id not in STATE["clips"]:
        return []
    if mode == "inverter":
        return [vfx.Pass("inv", INVERT, uniforms={"u_gain": 1.0})]
    if mode == "embaixo":
        return [vfx.Pass("below", BELOW)]
    if mode == "ida_e_volta":
        return [vfx.Pass("rt", ROUNDTRIP)]
    if mode == "desfoque":
        return [vfx.Pass("blur", kind="blur", sigma=ctx.px(STATE["sigma"]))]
    if mode == "listra":
        return [vfx.Pass("streak", kind="streak", sigma=ctx.px(STATE["sigma"]), angle=0.0)]
    if mode == "dois":  # dois passos, o segundo lê o primeiro pelo nome e a imagem de antes dos efeitos
        return [vfx.Pass("a", INVERT, uniforms={"u_gain": 0.5}),
                vfx.Pass("b", "uniform sampler2D t_a;\n"
                              "void main() { f_out = texture(t_a, v_uv) + vec4(texture(t_orig, v_uv).rgb * 0.5, 0.0); }",
                         inputs={"t_a": "pass:a"})]
    return []


@pytest.fixture
def test_effect():
    STATE.update(mode="", clips=None, sigma=30.0)
    eff = vfx.register(vfx.Effect("teste_fx", "efeitos_visuais", vfx.ORDER["luz"],
                                  active=lambda v: bool(STATE["mode"]), passes=_passes))
    yield eff
    vfx.unregister(eff.id)
    STATE.update(mode="", clips=None)


def vsrc(cor=(1.0, 0.5, 0.0), seconds=2.0):
    return tl.Source.virtual(KIND, W, H, "24/1", seconds=seconds, data={"nome": "Degradê", "cor": list(cor)},
                             alpha=False)


def one_clip(cor=(1.0, 0.5, 0.0)):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(vsrc(cor), at=0)[0]
    return seq, c


def compose(engine, seq, t=3, depth=8, neutral=False):
    return engine.compose(sequence.grab(seq, t, W, H, depth), seq, W, H, depth, neutral=neutral)


def fx_targets(engine):
    return {k for k in engine._targets if str(k).startswith("fx")}


# ------------------------------------------------------------------ sem GPU
def test_plan_order_and_neutral(test_effect):
    seq, c = one_clip()
    layer = seq.layers_at(0)[0]
    ctx = vfx.Ctx(seq, layer, 0, W, H, W, H)
    assert vfx.plan(ctx) == []
    STATE["mode"] = "inverter"
    got = vfx.plan(ctx)
    assert [e.id for e, _p in got] == ["teste_fx"] and got[0][1][0].name == "inv"
    assert vfx.plan(vfx.Ctx(seq, layer, 0, W, H, W, H, neutral=True)) == []
    other = vfx.register(vfx.Effect("teste_antes", "efeitos_visuais", vfx.ORDER["recorte"], active=lambda v: True,
                                    passes=lambda ctx: [vfx.Pass("x", INVERT)]))
    try:
        assert [e.id for e, _p in vfx.plan(ctx)] == ["teste_antes", "teste_fx"]
        assert "teste_antes" in vfx.EFFECT_MODULES["efeitos_visuais"]
    finally:
        vfx.unregister(other.id)
    assert "teste_antes" not in vfx.EFFECT_MODULES["efeitos_visuais"]


def test_ctx_px_and_time_follow_the_clip(test_effect):
    seq, c = one_clip()
    seq.insert_media(vsrc(), at=0)
    layer = seq.layers_at(5)[0]
    ctx = vfx.Ctx(seq, layer, 5, 1920, 1080, W, H)
    assert ctx.px(10) == 10.0 and vfx.Ctx(seq, layer, 5, 3840, 2160, W, H).px(10) == 20.0
    assert ctx.frame == seq.clip_time(layer.clip, 5) and ctx.seconds == pytest.approx(ctx.frame / 24.0)


def test_streak_steps_match_the_variance():
    for sigma in (0.3, 2.0, 15.0, 120.0, 900.0):
        steps = vfx.streak_steps(sigma)
        assert sum((2 * s) ** 2 for s in steps) == pytest.approx(sigma ** 2, rel=1e-9)
        assert all(b <= 3 * a + 1e-12 for a, b in zip(steps, steps[1:]))


def test_pack_and_unpack():
    a = (np.arange(60, dtype=np.float32).reshape(3, 4, 5) - 7.5) / 3
    p = vfx.pack(a)
    assert set(p) == {"tipo", "forma", "dados"} and p["forma"] == [3, 4, 5]
    b = vfx.unpack(p)
    assert b.dtype == np.float32 and np.array_equal(a, b) and not b.flags.writeable
    assert vfx.unpack(p) is b
    assert vfx.unpack({"dados": "!!!"}) is None and vfx.unpack(None) is None


def test_below_matrix_inverts_the_framing():
    seq, c = one_clip()
    seq.set_values(c.id, {"escala": 0.5, "pos_x": 0.2, "rotacao": 30.0})
    layer = seq.layers_at(0)[0]
    U, _mip = compositor.clip_uniforms(seq, layer, W, H, 200, 100)
    xf = np.array(U["u_xf"]).reshape(3, 3).T
    bm = np.array(vfx.below_matrix(U["u_xf"], 200, 100)).reshape(3, 3).T
    px = np.array([37.0, 61.0, 1.0])
    uv = xf @ px
    assert np.allclose(bm @ uv, [px[0] / 200, px[1] / 100, 1.0])


def test_no_geometry_providers_keep_the_uniforms():
    seq, c = one_clip()
    seq.set_values(c.id, {"escala": 0.7, "rotacao": 12.0})
    layer = seq.layers_at(0)[0]
    a, _ = compositor.clip_uniforms(seq, layer, W, H, W, H)
    m = compositor.transform(seq, c, W, H, c.values)
    assert a["u_xf"] == compositor.mat3_uniform(m)
    vfx.GEOMETRY["teste"] = lambda s, lay, mm: mm @ np.array([[1, 0, 2.0], [0, 1, 0], [0, 0, 1]])
    try:
        b, _ = compositor.clip_uniforms(seq, layer, W, H, W, H)
        n, _ = compositor.clip_uniforms(seq, layer, W, H, W, H, neutral=True)
    finally:
        del vfx.GEOMETRY["teste"]
    assert b["u_xf"] != a["u_xf"] and n["u_xf"] == a["u_xf"]


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_inactive_effect_runs_no_pass_and_is_bit_exact(gl_engine, renderer, test_effect, depth):
    seq, c = one_clip()
    vfx.unregister(test_effect.id)
    before = compose(gl_engine, seq, depth=depth)
    vfx.register(test_effect)
    targets = fx_targets(gl_engine)
    after = compose(gl_engine, seq, depth=depth)
    assert np.array_equal(before, after)
    assert fx_targets(gl_engine) == targets  # nenhum alvo novo: nenhum passo


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_glsl_pass_matches_numpy(gl_engine, renderer, test_effect, depth):
    seq, c = one_clip()
    STATE["mode"] = "inverter"
    got = compose(gl_engine, seq, depth=depth)
    mx = 255 if depth == 8 else 65535
    ref = mx - gen(seq, c, seq.layers_at(3)[0].src_frame, W, H, depth).astype(np.int64)
    assert int(np.abs(got.astype(np.int64) - ref).max()) == 0
    STATE["mode"] = "dois"
    got = compose(gl_engine, seq, depth=depth).astype(np.float64) / mx
    img = gen(seq, c, seq.layers_at(3)[0].src_frame, W, H, depth).astype(np.float64) / mx
    ref = 0.5 * (1 - img) + 0.5 * img
    assert np.abs(got - ref).max() <= 1.0 / mx
    STATE["mode"] = ""
    assert np.array_equal(compose(gl_engine, seq, depth=depth), gen(seq, c, seq.layers_at(3)[0].src_frame, W, H, depth))


@pytest.mark.gpu
def test_neutral_turns_the_stack_off(gl_engine, renderer, test_effect):
    seq, c = one_clip()
    plain = compose(gl_engine, seq)
    STATE["mode"] = "inverter"
    assert not np.array_equal(compose(gl_engine, seq), plain)
    assert np.array_equal(compose(gl_engine, seq, neutral=True), plain)


@pytest.mark.gpu
def test_below_input_sees_the_canvas_under_the_clip(gl_engine, renderer, test_effect):
    seq, c = one_clip((0.2, 0.9, 0.4))
    top = seq.insert_media(vsrc((1.0, 0.0, 0.0)), at=0, vtrack=1)[0]
    under = compose(gl_engine, seq)
    seq.set_values(top.id, {"opacidade": 0.0})
    base = compose(gl_engine, seq)
    seq.set_values(top.id, {"opacidade": 1.0})
    STATE.update(mode="embaixo", clips={top.id})
    assert not np.array_equal(under, base)
    assert np.array_equal(compose(gl_engine, seq), base)


@pytest.mark.gpu
def test_fx_dec_enc_round_trip(gl_engine, renderer, test_effect):
    seq, c = one_clip()
    plain = compose(gl_engine, seq, depth=16).astype(np.int64)
    STATE["mode"] = "ida_e_volta"
    got = compose(gl_engine, seq, depth=16).astype(np.int64)
    # A curva de vídeo (por paradas) não volta exata nas pontas (preto e branco), como o `trEnc` das transições.
    assert int(np.abs(got - plain).max()) <= 128
    assert int(np.abs(got - plain)[(plain > 3000) & (plain < 60000)].max()) <= 2


@pytest.mark.gpu
def test_blur_pass_keeps_flat_color_and_spreads_like_a_gaussian(gl_engine, renderer, test_effect, monkeypatch):
    def flat(seq, clip, frame, w, h, depth):
        img = np.full((h, w, 3), 0.25)
        img[h // 2, w // 2] = 1.0
        return np.rint(img * 65535).astype(np.uint16) if depth == 16 else np.rint(img * 255).astype(np.uint8)

    monkeypatch.setitem(sequence.RENDERERS, KIND, flat)
    seq, c = one_clip()
    STATE["mode"] = "desfoque"
    STATE["sigma"] = 60.0  # px@1080 → 2 texels numa tela de 36 linhas
    got = compose(gl_engine, seq, depth=16).astype(np.float64)[..., 0] / 65535
    assert abs(got[0, 0] - 0.25) < 1e-3 and abs(got[-1, -1] - 0.25) < 1e-3
    excess = got - 0.25
    assert excess.sum() == pytest.approx(0.75, rel=0.05)
    assert excess[H // 2, W // 2] == pytest.approx(0.75 / (2 * np.pi * 4.0), rel=0.1)  # gaussiana com σ = 2
    STATE["mode"] = "listra"
    got = compose(gl_engine, seq, depth=16).astype(np.float64)[..., 0] / 65535
    excess = got - 0.25
    assert np.abs(excess[H // 2 + 3]).max() < 1e-3  # só na horizontal
    assert excess[H // 2].sum() == pytest.approx(0.75, rel=0.05)


@pytest.mark.gpu
def test_blur_with_a_large_radius_uses_the_mipmaps(gl_engine, renderer, test_effect, monkeypatch):
    def flat(seq, clip, frame, w, h, depth):
        return np.full((h, w, 3), 128, np.uint8) if depth == 8 else np.full((h, w, 3), 128 * 257, np.uint16)

    monkeypatch.setitem(sequence.RENDERERS, KIND, flat)
    seq, c = one_clip()
    STATE["mode"] = "desfoque"
    STATE["sigma"] = 600.0
    got = compose(gl_engine, seq)
    assert int(np.abs(got.astype(np.int64) - 128).max()) <= 1


@pytest.mark.gpu
def test_nested_twin_with_an_effect_inside_is_bit_exact(gl_engine, renderer, test_effect):
    """Um clipe com efeito dentro de uma sequência (e, fora, só o clipe dela) = o mesmo clipe sem aninhar."""
    for depth in (8, 16):
        flat, c = one_clip()
        STATE["mode"] = "inverter"
        outer = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.9, 0.0, 0.0))
        inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
        outer.ensure_set().add(inner)
        outer.siblings.sync()
        outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=0)
        for t in (0, 5, 17):
            a = compose(gl_engine, flat, t, depth)
            b = compose(gl_engine, outer, t, depth)
            assert np.array_equal(a, b), f"quadro {t}, {depth} bits"


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, renderer, test_effect):
    """A prévia (`grab` + `Recipe.render`) e a exportação (`SequenceReader` + `frame_pipeline`) dão o mesmo quadro."""
    from pelicula import export, media
    from pelicula.frame import Recipe
    seq, c = one_clip()
    STATE["mode"] = "inverter"
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(6)]
    finally:
        reader.close()
    for t in range(6):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), f"quadro {t}"


def test_effect_packages_are_imported_once_before_use(monkeypatch, tmp_path):
    """Uma frente se registra com uma linha em `vfx.EFFECT_PACKAGES`: o módulo é importado antes do primeiro `plan`."""
    import sys
    import types
    calls = []
    fake = types.ModuleType("pelicula._teste_frente")
    sys.modules["pelicula._teste_frente"] = fake
    monkeypatch.setattr(vfx, "EFFECT_PACKAGES", ("_teste_frente",))
    monkeypatch.setattr(vfx, "_LOADED", False)
    monkeypatch.setattr("importlib.import_module", lambda name: calls.append(name) or fake)
    try:
        vfx.active_effects({})
        vfx.active_effects({})
    finally:
        sys.modules.pop("pelicula._teste_frente", None)
    assert calls == ["pelicula._teste_frente"]
    assert vfx.EFFECT_PACKAGES == ("_teste_frente",)
