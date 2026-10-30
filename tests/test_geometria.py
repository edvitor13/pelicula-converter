"""Geometria do clipe e da sequência (1.7, ARQUITETURA §37): escala por eixo, desespremer por clipe e janela útil."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import anamorfico, compositor, editparams, keyframes, params, project, sequence
from pelicula import timeline as tl

W, H = 320, 180
pytest_gpu = pytest.mark.gpu


def one_clip(w=W, h=H, canvas=(W, H), **values):
    s = tl.Source("cena.png", w, h, 24.0, "24/1", 1, 0.0, is_image=True, has_audio=False)
    seq = tl.Sequence(width=canvas[0], height=canvas[1])
    (c,) = seq.insert_media(s)
    if values:
        seq.set_values(c.id, {**c.values, **values})
    return seq, c


def white(w=W, h=H, depth=8):
    return np.full((h, w, 3), 255 if depth == 8 else 65535, np.uint8 if depth == 8 else np.uint16)


def frame_of(seq, img, frame=0):
    return sequence.FrameLayers(frame, [sequence.LayerImage(l, img) for l in seq.layers_at(frame)])


def lit_box(img, thr=128) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da parte acesa de um quadro (fundo preto), medida na imagem."""
    peak = 255 if img.dtype == np.uint8 else 65535
    on = img[..., 0] >= thr * peak / 255
    ys, xs = np.nonzero(on)
    assert xs.size, "nada aceso no quadro"
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


# ------------------------------------------------------------------ #54: escala por eixo
def test_axis_scale_params_are_neutral_animatable_and_sparse():
    for key, label in (("escala_x", "Escala horizontal"), ("escala_y", "Escala vertical")):
        p = editparams.VIDEO.params[key]
        ref = editparams.VIDEO.params["escala"]
        assert p.label == label and p.default == 1.0 and (p.min, p.max) == (ref.min, ref.max)
        assert key in editparams.ANIMATABLE_VIDEO and p.animatable and key in editparams.SPARSE_KEYS
    keys = [p.key for s in editparams.VIDEO_SECTIONS if s.key == "transformar" for p in s.params]
    assert keys.index("escala_x") == keys.index("escala") + 1 and keys.index("escala_y") == keys.index("escala") + 2


def test_axis_scale_defaults_give_the_same_uniforms():
    seq, c = one_clip(escala=1.7, rotacao=12.0, pos_x=0.1, pos_y=-0.2)
    v = dict(c.values)
    base = {k: v[k] for k in v if k not in ("escala_x", "escala_y")}
    assert compositor.axis_scale(base) == compositor.axis_scale(v) == (1.7, 1.7)
    np.testing.assert_array_equal(compositor.transform(seq, c, W, H, base), compositor.transform(seq, c, W, H, v))
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H)
    assert U["u_px_per_uv"] == (1.7 * W, 1.7 * H) and U["u_exact"] == 0


def test_axis_scale_multiplies_the_scale_and_comes_before_the_rotation():
    seq, c = one_clip(100, 100, (100, 100), escala=2.0, escala_x=1.5, rotacao=90.0)
    assert compositor.axis_scale(c.values) == (3.0, 2.0)
    m = compositor.transform(seq, c, 100, 100)
    # 90° no sentido horário: a largura do clipe (300 px) fica na vertical e a altura (200 px) na horizontal.
    np.testing.assert_allclose(m @ [50, 50 + 150, 1], [1.0, 0.5, 1], atol=1e-9)
    np.testing.assert_allclose(m @ [50 - 100, 50, 1], [0.5, 1.0, 1], atol=1e-9)


def test_axis_scale_uniforms_and_identity():
    seq, c = one_clip(escala_x=2.0)
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H)
    assert U["u_px_per_uv"] == (2.0 * W, H) and U["u_exact"] == 0
    assert not compositor.is_identity(seq, c, W, H, W, H)
    seq.set_values(c.id, {**c.values, "escala_x": 1.0})
    assert compositor.is_identity(seq, c, W, H, W, H)


def test_decode_size_per_axis_uses_the_largest_animated_value_and_the_file_cap():
    seq, c = one_clip(1920, 1080, (640, 360), escala_x=2.0)
    assert sequence.decode_size(seq, c, 640, 360) == (1280, 360)
    seq.set_values(c.id, {**c.values, "escala_x": 1.0, "escala_y": 1.5})
    assert sequence.decode_size(seq, c, 640, 360) == (640, 540)
    seq.set_values(c.id, {**c.values, "escala_y": 1.0, "escala": 2.0, "escala_x": 2.0})
    assert sequence.decode_size(seq, c, 640, 360) == (1920, 720)  # 640 × 4 passaria do arquivo
    seq.set_values(c.id, {**c.values, "escala": 1.0, "escala_x": 1.0})
    assert sequence.decode_size(seq, c, 640, 360) == (640, 360)
    c.keys["escala_x"] = [keyframes.Key(0.0, 1.0, "linear"), keyframes.Key(10.0, 3.0, "linear")]
    assert sequence.decode_size(seq, c, 640, 360) == (1920, 360)
    # Reduzir não reduz a decodificação abaixo da caixa (como a escala de sempre).
    c.keys.clear()
    seq.set_values(c.id, {**c.values, "escala_x": 0.5})
    assert sequence.decode_size(seq, c, 640, 360) == (640, 360)


def test_axis_scale_json_is_sparse_and_writes_format_5():
    seq, c = one_clip()
    video = next(x for x in seq.to_json()["clipes"] if x.get("tipo", "video") == "video")
    assert "escala_x" not in str(video) and "escala_y" not in str(video)
    assert seq.features() == set()
    seq.set_values(c.id, {**c.values, "escala_x": 1.5})
    js = seq.to_json()
    assert "escala_x" in str(js["clipes"]) and "escala_y" not in str(js["clipes"])
    assert "ajustes_clipe_1_7" in seq.features() and js["formato"] == tl.FORMAT
    back = tl.Sequence.from_json(js)
    assert back.clips[0].values["escala_x"] == 1.5 and back.clips[0].values["escala_y"] == 1.0
    assert "escala_x" not in params.known_1_6()["video"]
    p = project.Project(media_path="C:/v/cena.png", sequence=js)
    assert p.to_json()["formato"] == 5 and "ajustes_clipe_1_7" in p.to_json()["recursos"]


def test_axis_scale_breaks_is_trivial_and_neutral_keeps_it():
    s = tl.Source("v.mp4", W, H, 24.0, "24/1", 48, 2.0, has_audio=False)
    seq = tl.Sequence.for_source(s)
    assert seq.is_trivial() == "v.mp4"
    c = seq.clips[0]
    seq.set_values(c.id, {**c.values, "escala_y": 1.01})
    assert seq.is_trivial() is None
    seq.set_values(c.id, {**c.values, "escala_y": 1.0})
    assert seq.is_trivial() == "v.mp4"


def test_the_look_lens_table_did_not_change():
    assert anamorfico.SQUEEZES == {"nenhuma": 1.0, "1.33": 1.33, "1.5": 1.5, "1.8": 1.8, "2.0": 2.0}


@pytest_gpu
def test_escala_x_doubles_only_the_width_in_the_frame(gl_engine):
    seq, c = one_clip(80, 40, (320, 160), encaixe="esticar", escala=0.25, escala_x=2.0)
    img = gl_engine.compose(frame_of(seq, white(80, 40)), seq, 320, 160, 8)
    assert lit_box(img) == (80, 60, 160, 40)


@pytest_gpu
def test_escala_y_doubles_only_the_height_in_the_frame(gl_engine):
    seq, c = one_clip(80, 40, (320, 160), encaixe="esticar", escala=0.25, escala_y=2.0)
    img = gl_engine.compose(frame_of(seq, white(80, 40)), seq, 320, 160, 8)
    assert lit_box(img) == (120, 40, 80, 80)


@pytest_gpu
def test_scale_comes_before_the_rotation_in_the_frame(gl_engine):
    seq, c = one_clip(40, 40, (200, 200), encaixe="esticar", escala=0.2, escala_x=3.0, rotacao=90.0)
    img = gl_engine.compose(frame_of(seq, white(40, 40)), seq, 200, 200, 8)
    # 120 × 40 antes de girar; depois de 90°, 40 de largura por 120 de altura.
    assert lit_box(img) == (80, 40, 40, 120)


# ------------------------------------------------------------------ #52: desespremer por clipe
def test_desqueeze_table_and_manual_rate():
    d = editparams.VIDEO.defaults()
    assert d["desespremer"] == "nao" and d["desespremer_taxa"] == 1.0
    assert [k for k, _label in editparams.VIDEO.params["desespremer"].choices] == [
        "nao", "1.33", "1.5", "1.55", "1.8", "2.0", "manual"]
    assert compositor.desqueeze(d) == 1.0
    for key, want in (("1.33", 1.33), ("1.5", 1.5), ("1.55", 1.55), ("1.8", 1.8), ("2.0", 2.0)):
        assert compositor.desqueeze({"desespremer": key, "desespremer_taxa": 1.9}) == want  # taxa só com "manual"
    assert compositor.desqueeze({"desespremer": "manual", "desespremer_taxa": 1.73}) == 1.73
    assert compositor.desqueeze({"desespremer": "manual", "desespremer_taxa": 9.0}) == 2.5
    assert compositor.desqueeze({"desespremer": "manual", "desespremer_taxa": 0.5}) == 1.0
    assert compositor.desqueeze({}) == 1.0
    p = editparams.VIDEO.params["desespremer_taxa"]
    assert (p.min, p.max, p.step) == (1.0, 2.5, 0.01) and not p.animatable
    assert not editparams.VIDEO.params["desespremer"].animatable


def test_fit_box_takes_the_desqueezed_aspect():
    seq, c = one_clip(1920, 1080, (1920, 1080), desespremer="2.0")
    assert compositor.fit_box(seq, c, 1920, 1080) == pytest.approx((1920, 540))  # mostrar inteiro: caixa de letra
    seq.set_values(c.id, {**c.values, "encaixe": "preencher"})
    assert compositor.fit_box(seq, c, 1920, 1080) == pytest.approx((3840, 1080))
    seq.set_values(c.id, {**c.values, "encaixe": "esticar"})
    assert compositor.fit_box(seq, c, 1920, 1080) == (1920, 1080)  # esticar ignora


def test_desqueeze_then_user_scale_order():
    seq, c = one_clip(320, 180, desespremer="2.0", escala_x=0.5)
    bw, bh = compositor.fit_box(seq, c, W, H)
    assert (bw, bh) == pytest.approx((320, 90))
    m = compositor.transform(seq, c, W, H)
    np.testing.assert_allclose(m @ [W / 2 - 80, H / 2 - 45, 1], [0, 0, 1], atol=1e-9)  # 320 × 0,5 = 160 de largura


def test_decode_size_of_a_desqueezed_clip_is_capped_by_the_file():
    seq, c = one_clip(1920, 1080, (1920, 1080), desespremer="2.0")
    assert sequence.decode_size(seq, c, 1920, 1080) == (1920, 540)
    seq.set_values(c.id, {**c.values, "encaixe": "preencher"})
    assert sequence.decode_size(seq, c, 1920, 1080) == (1920, 1080)  # a caixa de 3840 não passa do arquivo


def test_desqueeze_neutral_json_and_format():
    seq, c = one_clip()
    assert "desespremer" not in str(seq.to_json()["clipes"]) and seq.features() == set()
    seq.set_values(c.id, {**c.values, "desespremer": "manual", "desespremer_taxa": 1.4})
    js = seq.to_json()
    assert "desespremer" in str(js["clipes"]) and "ajustes_clipe_1_7" in seq.features()
    back = tl.Sequence.from_json(js).clips[0].values
    assert (back["desespremer"], back["desespremer_taxa"]) == ("manual", 1.4)
    s = tl.Source("v.mp4", W, H, 24.0, "24/1", 48, 2.0, has_audio=False)
    q = tl.Sequence.for_source(s)
    assert q.is_trivial() == "v.mp4"
    q.set_values(q.clips[0].id, {**q.clips[0].values, "desespremer": "1.33"})
    assert q.is_trivial() is None


@pytest_gpu
def test_show_whole_2x_clip_has_letterbox_bars_of_the_right_height(gl_engine):
    seq, _c = one_clip(desespremer="2.0")
    img = gl_engine.compose(frame_of(seq, white()), seq, W, H, 8)
    assert lit_box(img) == (0, 45, W, 90)
    assert img[:45].max() == 0 and img[135:].max() == 0


@pytest_gpu
def test_fill_with_desqueeze_crops_the_sides(gl_engine):
    y, x = np.mgrid[0:H, 0:W]
    ramp = np.dstack([x * 255 // (W - 1)] * 3).astype(np.uint8)
    seq, _c = one_clip(desespremer="2.0", encaixe="preencher")
    img = gl_engine.compose(frame_of(seq, ramp), seq, W, H, 8)
    # Caixa de 640 × 180: só a metade do meio do clipe aparece.
    assert abs(int(img[90, 0, 0]) - 64) <= 2 and abs(int(img[90, W - 1, 0]) - 191) <= 2


@pytest_gpu
def test_stretch_ignores_the_desqueeze(gl_engine, test_rgb):
    a, _c = one_clip(encaixe="esticar")
    b, _c = one_clip(encaixe="esticar", desespremer="1.8")
    assert np.array_equal(gl_engine.compose(frame_of(a, test_rgb), a, W, H, 8),
                          gl_engine.compose(frame_of(b, test_rgb), b, W, H, 8))


@pytest_gpu
def test_desqueeze_then_escala_x_measured(gl_engine):
    seq, _c = one_clip(desespremer="2.0", escala_x=0.5)
    img = gl_engine.compose(frame_of(seq, white()), seq, W, H, 8)
    assert lit_box(img) == (80, 45, 160, 90)
