"""1.9: modos de mesclagem novos (`mesclagem.py`) e a camada de ajuste (`vfx.is_adjustment`; ARQUITETURA §49.6–49.7)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import aninhar, compositor, editparams, editshaders, mesclagem, modules, sequence, vfx
from pelicula import timeline as tl

W, H = 64, 36
KIND = "gerador"


def gen(seq, clip, frame, w, h, depth):
    """Degradês diferentes por fonte (a cor da fonte), cobrindo de escuro a claro."""
    src = seq.sources[clip.src]
    r, g, b = src.data.get("cor", [1.0, 0.5, 0.0])
    x, y = np.meshgrid(np.linspace(0.02, 0.98, w), np.linspace(0.05, 0.95, h))
    img = np.stack([r * y, g * x, (1 - x) * (1 - y) * b + 0.1 * x], axis=2)
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def vsrc(cor):
    return tl.Source.virtual(KIND, W, H, "24/1", seconds=2.0, data={"nome": "Degradê", "cor": list(cor)}, alpha=False)


def base_seq():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    low = seq.insert_media(vsrc((0.9, 0.6, 0.3)), at=0)[0]
    return seq, low


def add_adjustment(seq, at=0, track=1):
    src = vfx.new_adjustment(seq)
    return seq.insert_media(src, at=at, vtrack=track)[0]


def compose(engine, seq, t=3, depth=16, neutral=False):
    return engine.compose(sequence.grab(seq, t, W, H, depth), seq, W, H, depth, neutral=neutral)


# ------------------------------------------------------------------ sem GPU
def test_new_blend_choices_are_appended_with_their_ids():
    choices = [k for k, _l in editparams.VIDEO.params["mesclagem"].choices]
    assert choices[:7] == ["normal", "tela", "multiplicar", "sobrepor", "adicionar", "clarear", "escurecer"]
    assert choices[7:] == list(mesclagem.MODES.values())
    assert all(compositor.BLEND_IDS[k] == i for i, k in mesclagem.MODES.items())
    assert [compositor.BLEND_IDS[k] for k in choices] == list(range(len(choices)))


def test_blend_variants_keep_the_pinned_programs():
    for name, base in (("clip_bx", editshaders.CLIP), ("clip_tr_bx", editshaders.CLIP_TR),
                       ("clip_cs_bx", editshaders.CLIP_CS), ("clip_tr_cs_bx", editshaders.CLIP_TR_CS)):
        src = editshaders.clip_source(name)
        assert src != base and "blendBase" in src and src.count("void main()") == 1
    adj = editshaders.clip_source("clip_tr_cs_bx_adj")
    assert adj.count("camada de ajuste") == 1 and adj.count("void main()") == 1


def test_numpy_reference_of_known_points():
    b = np.array([[[0.2, 0.5, 0.8]]])
    s = np.array([[[0.6, 0.5, 0.1]]])
    assert np.allclose(mesclagem.apply("diferenca", b, s), [[[0.4, 0.0, 0.7]]])
    assert np.allclose(mesclagem.apply("subtrair", b, s), [[[0.0, 0.0, 0.7]]])
    assert np.allclose(mesclagem.apply("luz_forte", b, np.full_like(s, 0.5)), b)  # 0,5 neutro na luz forte
    assert np.allclose(mesclagem.apply("luz_suave", b, np.full_like(s, 0.5)), b)
    lum = (mesclagem.apply("luminosidade", b, s) * mesclagem.W709).sum()
    assert lum == pytest.approx((s * mesclagem.W709).sum())
    grey = np.full_like(b, 0.4)
    assert np.allclose(mesclagem.apply("cor", grey, grey), grey)


def test_adjustment_source_and_features():
    seq, low = base_seq()
    assert "camada_ajuste" not in seq.features()
    adj = add_adjustment(seq)
    assert vfx.is_adjustment(seq, adj) and not vfx.is_adjustment(seq, low)
    assert seq.sources[adj.src].kind == "ajuste" and not seq.sources[adj.src].has_audio
    assert "camada_ajuste" in seq.features() and seq.block_format() == tl.FORMAT
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert vfx.is_adjustment(back, back.find(adj.id))
    assert sequence.grab(seq, 0, W, H).layers[1].image is sequence._NO_IMAGE


def test_adjustment_counts_as_its_module_not_as_a_generator():
    seq, low = base_seq()
    before = modules.used_by(None, seq)
    add_adjustment(seq)
    after = modules.used_by(None, seq)
    assert after - before == {"efeitos_clipe"}
    assert modules.get("efeitos_clipe").status == modules.BETA
    assert not modules.default_enabled("efeitos_clipe")
    assert modules.get("efeitos_clipe").group == "efeitos_visuais"


def test_undo_and_redo_bring_the_adjustment_back():
    seq, low = base_seq()
    hist = tl.History(seq)
    adj = add_adjustment(seq)
    seq.set_values(adj.id, {"exposicao": 0.5})
    assert hist.push(seq)
    back = hist.undo(seq)
    assert back.find(adj.id) is None
    again = hist.redo(back)
    assert vfx.is_adjustment(again, again.find(adj.id)) and again.find(adj.id).values["exposicao"] == 0.5


def test_nesting_an_adjustment_without_what_is_under_it_is_refused():
    seq, low = base_seq()
    adj = add_adjustment(seq)
    with pytest.raises(aninhar.Refusal) as err:
        aninhar.nest(seq, [adj.id])
    assert "camada de ajuste" in err.value.text
    seq2, low2 = base_seq()
    adj2 = add_adjustment(seq2)
    res = aninhar.nest(seq2, [adj2.id, low2.id])
    assert res.inner is not None


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.parametrize("mode", list(mesclagem.MODES.values()))
def test_each_new_blend_mode_matches_numpy(gl_engine, renderer, mode):
    seq, low = base_seq()
    top = seq.insert_media(vsrc((0.2, 0.9, 0.7)), at=0, vtrack=1)[0]
    seq.set_values(top.id, {"mesclagem": mode})
    got = compose(gl_engine, seq).astype(np.float64) / 65535
    f = seq.layers_at(3)[0].src_frame
    b = gen(seq, low, f, W, H, 16).astype(np.float64) / 65535
    s = gen(seq, top, f, W, H, 16).astype(np.float64) / 65535
    ref = np.clip(mesclagem.apply(mode, b, s), 0, 1)
    assert np.abs(got - ref).max() <= 3e-5, mode


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_neutral_adjustment_layer_is_bit_exact(gl_engine, renderer, depth):
    seq, low = base_seq()
    seq.set_values(low.id, {"escala": 0.8, "rotacao": 5.0})
    before = compose(gl_engine, seq, depth=depth)
    adj = add_adjustment(seq)
    assert np.array_equal(compose(gl_engine, seq, depth=depth), before)
    seq.set_values(adj.id, {"opacidade": 0.5})
    assert np.array_equal(compose(gl_engine, seq, depth=depth), before)


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_exposure_on_an_adjustment_equals_it_on_a_full_frame_clip(gl_engine, renderer, depth):
    seq, low = base_seq()
    adj = add_adjustment(seq)
    seq.set_values(adj.id, {"exposicao": 0.7, "saturacao": 1.3})
    got = compose(gl_engine, seq, depth=depth)
    ref_seq, ref_low = base_seq()
    ref_seq.set_values(ref_low.id, {"exposicao": 0.7, "saturacao": 1.3})
    ref = compose(gl_engine, ref_seq, depth=depth)
    assert int(np.abs(got.astype(np.int64) - ref.astype(np.int64)).max()) == 0
    assert np.array_equal(compose(gl_engine, seq, depth=depth, neutral=True),
                          compose(gl_engine, base_seq()[0], depth=depth))


@pytest.mark.gpu
def test_adjustment_only_inside_its_time_and_with_opacity(gl_engine, renderer):
    seq, low = base_seq()
    adj = add_adjustment(seq, at=10)
    seq.set_values(adj.id, {"exposicao": 1.0})
    plain = compose(gl_engine, base_seq()[0], t=3)
    assert np.array_equal(compose(gl_engine, seq, t=3), plain)  # antes da camada de ajuste
    full = compose(gl_engine, seq, t=12).astype(np.float64)
    seq.set_values(adj.id, {"exposicao": 1.0, "opacidade": 0.5})  # set_values troca todos os ajustes
    half = compose(gl_engine, seq, t=12).astype(np.float64)
    orig = compose(gl_engine, base_seq()[0], t=12).astype(np.float64)
    ok = full < 65535  # a tela guarda o que passa do branco; a saída corta
    assert np.abs(half - (orig + full) / 2)[ok].max() <= 2.0


@pytest.mark.gpu
def test_adjustment_on_a_transparent_canvas_keeps_the_coverage(gl_engine, renderer):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", transparent=True)
    low = seq.insert_media(vsrc((0.9, 0.6, 0.3)), at=0)[0]
    seq.set_values(low.id, {"escala": 0.5})
    plain = gl_engine.compose(sequence.grab(seq, 3, W, H, 16), seq, W, H, 16, alpha=True)
    adj = add_adjustment(seq)
    seq.set_values(adj.id, {"exposicao": 0.5})
    got = gl_engine.compose(sequence.grab(seq, 3, W, H, 16), seq, W, H, 16, alpha=True)
    assert np.array_equal(got[..., 3], plain[..., 3])
    inside = plain[..., 3] == 65535
    assert (got[..., :3][inside].astype(np.int64) > plain[..., :3][inside].astype(np.int64)).any()
