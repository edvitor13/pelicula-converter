"""Geometria do clipe e da sequência (1.7, ARQUITETURA §37): escala por eixo, desespremer por clipe e janela útil."""

from __future__ import annotations

import numpy as np
import pytest

from helpers import read_all
from pelicula import anamorfico, colorsimple, compositor, editparams, export, fit, frame, keyframes, media, params
from pelicula import presets, project, sequence
from pelicula import subtitles as sb
from pelicula import titles
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings

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


# ------------------------------------------------------------------ #55: proporção e janela útil
def windowed(ratio=2.39, w=W, h=H, canvas=(W, H), **values):
    seq, c = one_clip(w, h, canvas, **values)
    seq.window = ratio
    return seq, c


def test_aspect_size_is_even_for_every_ratio():
    assert tl.aspect_size(1920, 1080, 2.39) == (1920, 804)
    assert tl.aspect_size(1920, 1080, 1.33) == (1436, 1080)
    assert tl.aspect_size(1920, 1080, 0.0) == (1920, 1080)
    assert tl.aspect_size(1920, 1080, 1.78) == (1920, 1080)  # 1,78 é o 16:9 de verdade: sem faixa de um pixel
    assert tl.aspect_size(1440, 1080, 1.33) == (1440, 1080)  # 1,33 é o 4:3
    for fw, fh in ((1920, 1080), (3840, 2160), (1280, 720), (1080, 1920), (1080, 1080), (1920, 804)):
        for ratio in (1.33, 1.37, 1.43, 1.78, 1.85, 2.0, 2.2, 2.39, 2.76, 2.1, 1.0, 4.0):
            w, h = tl.aspect_size(fw, fh, ratio)
            assert w % 2 == 0 and h % 2 == 0, (fw, fh, ratio)
            assert w <= fw and h <= fh and (w == fw or h == fh)
            assert abs(w / h - ratio) < 2.0 / min(w, h) + tl.RATIO_TOLERANCE + 1e-9, (fw, fh, ratio, w, h)


def test_window_rect_letterbox_pillarbox_and_scale():
    seq = tl.Sequence(width=1920, height=1080)
    assert seq.window_rect(1920, 1080) == (0, 0, 1920, 1080)  # sem janela: a tela inteira
    seq.window = 2.39
    assert seq.window_rect(1920, 1080) == (0, 138, 1920, 804)
    x, y, w, h = seq.window_rect(960, 540)  # a prévia reduzida concorda com a exportação
    assert (x, w) == (0, 960) and h % 2 == 0
    assert abs(y / 540 - 138 / 1080) < 2 / 540 and abs(h / 540 - 804 / 1080) < 2 / 540
    seq.window = 1.33
    assert seq.window_rect(1920, 1080) == (242, 0, 1436, 1080)
    x, y, w, h = seq.window_rect(640, 360)
    assert (y, h) == (0, 360) and w % 2 == 0 and abs(x / 640 - 242 / 1920) < 2 / 640 and x * 2 + w == 640
    seq.window = 1.78
    assert seq.window_rect(1920, 1080) == (0, 0, 1920, 1080) and seq.window_rect(640, 360) == (0, 0, 640, 360)


def test_window_json_round_trip_format_5_and_trivial():
    s = tl.Source("v.mp4", W, H, 24.0, "24/1", 48, 2.0, has_audio=False)
    seq = tl.Sequence.for_source(s)
    base = seq.to_json()
    assert "janela" not in base and seq.features() == set() and base["formato"] != tl.FORMAT
    assert seq.is_trivial() == "v.mp4"
    seq.window = 2.39
    js = seq.to_json()
    assert js["janela"] == 2.39 and seq.features() == {"janela_util"} and js["formato"] == tl.FORMAT
    assert seq.is_trivial() is None and seq.direct_file() is None
    assert tl.Sequence.from_json(js).window == 2.39 and seq.copy().to_json() == js
    p = project.Project(media_path="v.mp4", sequence=js)
    assert p.to_json()["formato"] == 5 and p.to_json()["recursos"] == ["janela_util"]
    seq.window = 0.0
    assert seq.to_json() == base
    assert tl.Sequence.from_json({**base, "janela": "x"}).window == 0.0
    assert tl.Sequence.from_json({**base, "janela": 9.0}).window == 0.0
    assert tl.Sequence.from_json({**base, "janela": -2}).window == 0.0


def test_quadro_real_needs_no_new_feature():
    seq, _c = one_clip(canvas=(1920, 804))
    assert seq.features() == set() and "janela" not in seq.to_json()


def test_fit_box_and_position_are_of_the_window():
    seq, c = windowed(canvas=(1920, 1080), w=1920, h=1080)
    assert compositor.fit_box(seq, c, 1920, 1080) == pytest.approx((1920 * 804 / 1080, 804))
    seq.set_values(c.id, {**c.values, "encaixe": "preencher"})
    assert compositor.fit_box(seq, c, 1920, 1080) == pytest.approx((1920, 1080))
    seq.set_values(c.id, {**c.values, "encaixe": "esticar"})
    assert compositor.fit_box(seq, c, 1920, 1080) == (1920, 804)
    m = compositor.transform(seq, c, 1920, 1080)
    np.testing.assert_allclose(m @ [960, 540, 1], [0.5, 0.5, 1], atol=1e-9)  # centrado na janela
    np.testing.assert_allclose(m @ [0, 138, 1], [0, 0, 1], atol=1e-9)
    seq.set_values(c.id, {**c.values, "pos_y": 0.5})
    np.testing.assert_allclose(compositor.transform(seq, c, 1920, 1080) @ [960, 540 + 402, 1], [0.5, 0.5, 1], atol=1e-9)
    assert sequence.decode_size(seq, c, 1920, 1080) == (1920, 804)


def test_without_window_every_number_is_the_same():
    a, ca = one_clip(escala=1.3, pos_x=0.2, rotacao=7.0)
    b, cb = one_clip(escala=1.3, pos_x=0.2, rotacao=7.0)
    b.window = 2.39
    b.window = 0.0
    np.testing.assert_array_equal(compositor.transform(a, ca, W, H), compositor.transform(b, cb, W, H))
    assert compositor.fit_box(a, ca, W, H) == compositor.fit_box(b, cb, W, H) == (W, H)
    assert b.window_rect(W, H) == (0, 0, W, H)


def test_generator_fills_the_window_and_keeps_its_aspect_when_capped():
    seq = tl.Sequence(width=3840, height=2160)
    src = tl.Source.virtual("cor", 1920, 1080, "24/1", 2.0)
    (c,) = seq.insert_media(src)
    assert compositor.fit_box(seq, c, 3840, 2160) == (3840, 2160)
    assert sequence.decode_size(seq, c, 3840, 2160) == (1920, 1080)
    seq.window = 2.39
    x, y, w, h = seq.window_rect(3840, 2160)
    assert compositor.fit_box(seq, c, 3840, 2160) == (w, h) == (3840, 1606)
    dw, dh = sequence.decode_size(seq, c, 3840, 2160)
    assert (dw, dh) == (1920, 803) and abs(dw / dh - w / h) < 0.01
    assert sequence.decode_size(seq, c, 1920, 1080) == (1920, 804)


def test_transitions_use_the_window():
    seq = tl.Sequence(width=1000, height=1000)
    a = tl.Source("a.png", 1000, 1000, 24.0, "24/1", 1, 0.0, is_image=True, has_audio=False)
    (c,) = seq.insert_media(a)
    seq.set_values(c.id, {**c.values, "entrada_tipo": "cortina", "entrada_dur": 1.0, "entrada_direcao": "baixo"})
    layer = seq.layers_at(5)[0]
    U, _ = compositor.clip_uniforms(seq, layer, 1000, 1000, 1000, 1000)
    assert U["u_tr_a"][0][2] == 1000.0 and U["u_tr_b"][0][0] == 1000.0  # a tela inteira
    seq.window = 2.0
    U, _ = compositor.clip_uniforms(seq, layer, 1000, 500, 1000, 1000)
    assert U["u_tr_a"][0][2] == 750.0 and U["u_tr_b"][0][0] == 500.0  # da base da janela (250 + 500), 500 de percurso
    seq.set_values(c.id, {**c.values, "entrada_tipo": "iris", "entrada_centro_y": 0.5})
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(5)[0], 1000, 500, 1000, 1000)
    assert U["u_tr_a"][0][:2] == (500.0, 750.0)  # fração da janela


def test_clip_point_is_none_in_the_bars():
    seq, c = windowed(canvas=(1920, 1080), w=1920, h=1080, encaixe="preencher")
    layer = seq.layers_at(0)[0]
    assert colorsimple.clip_point(seq, layer, 1920, 1080, 0.5, 0.5) is not None
    assert colorsimple.clip_point(seq, layer, 1920, 1080, 0.5, 0.05) is None


def test_recipe_window_area_with_cut_and_box():
    seq = tl.Sequence(width=1920, height=1080)
    seq.window = 2.39
    img = np.zeros((1080, 1920, 3), np.uint8)
    r = frame.Recipe(None, 24.0, seq=seq)
    assert r.window_area(img) == (0, 138, 1920, 804)
    f = fit.plan(1920, 1080, 1080, 1920, fit.CORTAR, edit=True)  # a tela cobre o quadro e só o centro sai
    area = frame.Recipe(None, 24.0, seq=seq, fit=f).window_area(np.zeros((f.out_h, f.out_w, 3), np.uint8))
    assert area[0] == 0 and area[2] == 1080 and area[1] == (1920 - area[3]) // 2 and area[3] < 1920
    assert frame.Recipe(None, 24.0).window_area(img) is None
    seq.window = 0.0
    assert frame.Recipe(None, 24.0, seq=seq).window_area(img) is None


def test_window_bars_paints_only_outside_and_keeps_the_input():
    img = np.full((10, 20, 3), 200, np.uint8)
    img.setflags(write=False)
    out = frame.window_bars(img, (4, 2, 12, 6))
    assert out[2:8, 4:16].min() == 200 and out[:2].max() == 0 and out[8:].max() == 0
    assert out[:, :4].max() == 0 and out[:, 16:].max() == 0 and img.min() == 200
    rgba = np.zeros((10, 20, 4), np.uint16)
    out = frame.window_bars(rgba, (0, 2, 20, 6))
    assert out[0, 0].tolist() == [0, 0, 0, 65535] and out[5, 5].tolist() == [0, 0, 0, 0]
    box = frame.window_bars(np.full((10, 20, 3), 90, np.uint8), (5, 2, 10, 6), (5, 0, 10, 10))  # só dentro da caixa
    assert box[0, 0, 0] == 90 and box[0, 5, 0] == 0 and box[5, 5, 0] == 90


def test_subtitle_is_measured_and_placed_in_the_window(qapp):
    style = sb.STYLES["youtube"]
    b = sb.Burn.make("digital", style, [sb.Cue(0.0, 2.0, "Legenda de teste")])
    img = np.zeros((360, 640, 3), np.uint8)
    area = (0, 60, 640, 240)
    whole = b.apply(img, 0.5)
    inside = b.apply(img, 0.5, area)
    assert lit_box(whole, 40)[1] + lit_box(whole, 40)[3] > 300  # sem janela, a legenda fica na faixa de baixo
    x, y, w, h = lit_box(inside, 40)
    assert y >= 60 and y + h <= 300
    assert b.apply(img, 5.0, area) is img  # sem legenda nesse instante, o mesmo objeto


@pytest_gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_bars_are_black_at_both_depths(gl_engine, depth):
    seq, _c = windowed(encaixe="preencher")
    seq.background = (0.3, 0.6, 0.9)
    x, y, w, h = seq.window_rect(W, H)
    assert (y, h) == (23, 134)
    img = gl_engine.compose(frame_of(seq, white(depth=depth)), seq, W, H, depth)
    peak = 255 if depth == 8 else 65535
    assert img[:y].max() == 0 and img[y + h:].max() == 0 and img[y:y + h].min() == peak


@pytest_gpu
def test_pillarbox_bars_and_background_only_inside(gl_engine):
    seq, _c = windowed(1.33, escala=0.25)
    seq.background = (0.5, 0.5, 0.5)
    x, y, w, h = seq.window_rect(W, H)
    assert (x, y, w, h) == (40, 0, 240, 180)
    img = gl_engine.compose(frame_of(seq, white()), seq, W, H, 8)
    assert img[:, :x].max() == 0 and img[:, x + w:].max() == 0
    assert img[5, x + 5, 0] in (127, 128)  # o fundo da sequência fica dentro da janela


@pytest_gpu
def test_layer_fits_the_window_and_moves_with_pos_y(gl_engine):
    seq, c = windowed()
    box = lit_box(gl_engine.compose(frame_of(seq, white()), seq, W, H, 8))
    assert box[1] == 23 and box[3] == 134 and abs(box[2] - 238) <= 1
    seq.set_values(c.id, {**c.values, "pos_y": 0.5})  # meia janela para baixo: 67 px, cortado na borda da janela
    box = lit_box(gl_engine.compose(frame_of(seq, white()), seq, W, H, 8))
    assert box[1] == 90 and box[3] == 67


@pytest_gpu
def test_look_never_dirties_the_bars(gl_engine, test_rgb):
    values = presets.builtin_values("vision3_500t")  # grão, halação, bloom, cópia
    values.update(grao_forca=1.4, desg_on=True, mold_on=True)
    seq, _c = windowed(encaixe="preencher")
    x, y, w, h = seq.window_rect(W, H)
    for depth in (8, 16):
        r = frame.Recipe.for_source(values, 24.0, depth, legal=False, seq=seq, size=(W, H))
        out = r.render(gl_engine, frame_of(seq, test_rgb), 3)
        assert out[:y].max() == 0 and out[y + h:].max() == 0 and out[y:y + h].max() > 0


@pytest_gpu
def test_transparent_background_keeps_the_bars_opaque_black(gl_engine):
    seq, _c = windowed(escala=0.25)
    seq.transparent = True
    x, y, w, h = seq.window_rect(W, H)
    r = frame.Recipe.for_source(None, 24.0, 8, legal=False, seq=seq, size=(W, H), alpha=True)
    out = r.render(gl_engine, frame_of(seq, white()), 0)
    assert out.shape == (H, W, 4)
    assert out[0, 0].tolist() == [0, 0, 0, 255] and out[H - 1, W - 1].tolist() == [0, 0, 0, 255]
    assert out[y + 2, 2, 3] == 0  # dentro da janela, sem clipe: transparente


@pytest_gpu
def test_window_with_export_fit_cut_and_borders(gl_engine, test_rgb):
    seq, _c = windowed(encaixe="preencher")
    cut = fit.plan(W, H, 180, 180, fit.CORTAR, edit=True)
    out = frame.Recipe(None, 24.0, seq=seq, fit=cut).render(gl_engine, frame_of(seq, test_rgb), 0)
    assert out.shape[:2] == (180, 180) and out[:20].max() == 0 and out[-20:].max() == 0 and out[60:120].max() > 0
    values = dict(params.FILM.defaults())
    box = fit.plan(W, H, 180, 180, fit.BORDAS, edit=True)
    r = frame.Recipe(values, 24.0, legal=False, seq=seq, fit=box)
    out = r.render(gl_engine, frame_of(seq, test_rgb), 0)
    bx, by, bw, bh = box.box
    area = seq.window_rect(bw, bh)
    assert out.shape[:2] == (180, 180) and out[by:by + area[1]].max() == 0


@pytest_gpu
def test_title_stays_inside_the_window(gl_engine, qapp):
    seq = tl.Sequence(width=W, height=H)
    seq.window = 2.39
    src = titles.new_source(seq)
    (c,) = seq.insert_media(src, 0)
    layers = sequence.grab(seq, 10, W, H, 8)
    dw, dh = sequence.decode_size(seq, c, W, H)
    assert (dw, dh) == seq.window_rect(W, H)[2:]
    img = gl_engine.compose(layers, seq, W, H, 8)
    x, y, w, h = seq.window_rect(W, H)
    assert img[:y].max() == 0 and img[y + h:].max() == 0 and img[y:y + h].max() > 0


@pytest_gpu
def test_burned_subtitle_stays_inside_the_window_through_the_recipe(gl_engine, test_rgb, qapp):
    seq, _c = windowed(encaixe="preencher")
    x, y, w, h = seq.window_rect(W, H)
    b = sb.Burn.make("digital", sb.STYLES["youtube"], [sb.Cue(0.0, 2.0, "Legenda")])
    r = frame.Recipe.for_source(None, 24.0, 8, legal=False, seq=seq, size=(W, H), burn=b)
    plain = frame.Recipe.for_source(None, 24.0, 8, legal=False, seq=seq, size=(W, H))
    a = r.render(gl_engine, frame_of(seq, test_rgb), 6)
    p = plain.render(gl_engine, frame_of(seq, test_rgb), 6)
    changed = np.nonzero((a != p).any(axis=2))
    assert changed[0].size and changed[0].min() >= y and changed[0].max() < y + h
    assert a[:y].max() == 0 and a[y + h:].max() == 0


@pytest.mark.ffmpeg
@pytest_gpu
def test_grab_equals_reader_with_a_window(gl_engine, sample_info):
    seq = tl.Sequence.for_source(tl.Source.from_info(sample_info))
    seq.window = 2.39
    reader = sequence.SequenceReader(seq, W, H, 8, 0, 4, hq=True)
    try:
        for i in range(4):
            fl = reader.read()
            a = gl_engine.compose(fl, reader.seq, W, H, 8)
            b = gl_engine.compose(sequence.grab(reader.seq, i, W, H, 8, hq=True), reader.seq, W, H, 8)
            assert np.array_equal(a, b), i
    finally:
        reader.close()


@pytest.mark.ffmpeg
@pytest_gpu
def test_windowed_frame_is_the_same_in_export_and_preview(gl_engine, sample_video, tmp_path):
    values = presets.builtin_values("vision3_500t")
    seq = tl.Sequence.for_source(media.probe_source(sample_video))
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.set_values(v.id, {**v.values, "encaixe": "preencher", "pos_y": 0.1, "escala_x": 1.2, "desespremer": "1.33"})
    seq.window = 2.39
    seq = tl.Sequence.from_json(seq.to_json())
    info = sequence.media_info(seq)
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)
    out = tmp_path / "janela.mkv"
    job = ExportJob(info=info, values=values, settings=s, out_path=str(out), start_frame=0, end_frame=4, sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(out))
    frames = read_all(media.FrameReader(o, o.width, o.height, 16))
    w, h = sequence.canvas_size(seq)
    x, y, rw, rh = seq.window_rect(w, h)
    recipe = frame.Recipe.for_source(values, info.fps, 16, legal=sequence.legal_range(seq), seq=seq, size=(w, h))
    for n in (0, 2, 4):
        ref = frames[n]
        assert ref[:y].max() == 0 and ref[y + rh:].max() == 0 and ref[y:y + rh].max() > 0
        assert np.array_equal(export.preview_frame(gl_engine, info, values, s, n, seq=seq, depth=16), ref), n
        assert np.array_equal(recipe.render(gl_engine, sequence.grab(seq, n, w, h, 16, hq=True), n), ref), n


@pytest_gpu
def test_no_window_compose_stays_bit_exact(gl_engine, test_rgb):
    seq, _c = one_clip()
    assert np.array_equal(gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8), test_rgb)
    seq.window = 1.78  # a proporção do quadro: sem faixas e sem reamostrar
    assert np.array_equal(gl_engine.compose(frame_of(seq, test_rgb), seq, W, H, 8), test_rgb)
