"""Cor simples do modo Edição (1.6): esquema, programa `CLIP_CS`, ferramentas puras e grupos de cor."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import colorsimple, compositor, editparams, editshaders, masks, sequence
from pelicula import timeline as tl
from test_masks import MONK, code

W, H = 320, 180
NEW_SECTIONS = ("pele", "alvo", "degrade")


def one_clip(w=W, h=H, **values):
    s = tl.Source("cena.png", w, h, 24.0, "24/1", 1, 0.0, is_image=True, has_audio=False)
    seq = tl.Sequence.for_source(s)
    c = seq.clips[0]
    if values:
        seq.set_values(c.id, {**c.values, **values})
    return seq, c


def video_seq(frames=240):
    s = tl.Source("cena.mp4", W, H, 24.0, "24/1", frames, frames / 24.0, has_audio=False)
    return tl.Sequence.for_source(s)


# ------------------------------------------------------------------ esquema
def test_new_sections_are_appended_neutral_and_sparse():
    keys = [s.key for s in editparams.VIDEO_SECTIONS]
    i = keys.index(NEW_SECTIONS[0])  # 1.6, frente E: a manivela vem depois
    assert tuple(keys[i:i + 3]) == NEW_SECTIONS and keys[i + 3:] == ["manivela", "luz_copiadora"]
    assert editparams.COLOR_SECTIONS[:7] == ("luz", "cor", "rodas", "curva", "hsl", "detalhe", "efeitos")
    assert editparams.COLOR_SECTIONS[7:] == NEW_SECTIONS
    new = {p.key for s in editparams.VIDEO_SECTIONS if s.key in NEW_SECTIONS for p in s.params}
    assert new == set(colorsimple.NEW_KEYS)
    assert new <= editparams.SPARSE_KEYS
    assert new <= set(editparams.color_keys())
    d = editparams.VIDEO.defaults()
    assert not colorsimple.active(d) and colorsimple.uniforms(d) == {}
    stored = editparams.stored_values("video", d)
    assert not (set(stored) & new)  # no padrão, nada novo no JSON
    for k in new:
        assert k.isascii()


def test_default_clip_uniforms_have_nothing_new():
    seq, c = one_clip()
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H)
    assert not any(k.startswith("u_cs_") for k in U)
    # mexer só na forma do degradê, no centro da cor escolhida ou na janela da pele não liga nada
    seq, c = one_clip(degrade_angulo=45.0, degrade_tipo="radial", alvo_matiz=200.0, pele_centro=50.0)
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H)
    assert "u_cs_on" not in U


@pytest.mark.parametrize("key,value", [("pele_natural", 0.5), ("alvo_sat", 0.3), ("degrade_exposicao", -1.0),
                                       ("degrade_saturacao", -0.4), ("alvo_desvio", 40.0)])
def test_each_effect_turns_the_simple_color_on(key, value):
    seq, c = one_clip(**{key: value})
    U, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H)
    assert U["u_cc_on"] == 1 and U["u_cs_on"] == 1
    neutral, _ = compositor.clip_uniforms(seq, seq.layers_at(0)[0], W, H, W, H, neutral=True)
    assert "u_cs_on" not in neutral  # a comparação "original" fica sem a cor do clipe


def test_clip_cs_is_clip_plus_the_hook():
    for plain, cs in ((editshaders.CLIP, editshaders.CLIP_CS), (editshaders.CLIP_TR, editshaders.CLIP_TR_CS)):
        back = cs.replace(colorsimple.GLSL + "\n", "", 1)
        back = back.replace("        vec3 c_in = c;\n", "", 1)
        back = back.replace("        if (u_cs_on == 1) c = colorSimple(c_in, c, uv);\n", "", 1)
        assert back == plain


def test_new_values_go_to_json_and_to_format_4():
    seq, c = one_clip(pele_natural=0.4)
    d = c.to_json()
    assert d["valores"]["pele_natural"] == 0.4 and "alvo_matiz" not in d["valores"]
    back = tl.Clip.from_json(json.loads(json.dumps(d)))
    assert back.values == c.values
    assert "ajustes_clipe_1_6" in seq.features() and seq.block_format() == tl.FORMAT_16


# ------------------------------------------------------------------ grupos de cor
def test_color_group_json_only_when_used_and_round_trip():
    seq = video_seq()
    c = seq.clips[0]
    assert "grupo" not in c.to_json() and "grupos_cor" not in seq.features()
    c.color_group = "g1"
    d = c.to_json()
    assert d["grupo"] == "g1"
    assert tl.Clip.from_json(json.loads(json.dumps(d))).color_group == "g1"
    assert "grupos_cor" in seq.features() and seq.block_format() == tl.FORMAT_16
    seq2 = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert seq2.clips[0].color_group == "g1"
    bad = dict(d, grupo=7)
    assert tl.Clip.from_json(bad).color_group == ""


def test_group_follows_only_the_changed_color_keys_with_undo():
    from pelicula.ui.edit_model import TimelineModel
    seq = video_seq()
    m = TimelineModel(seq)
    vids = [c for c in m.seq.clips if c.kind == tl.VIDEO]
    if len(vids) < 2:
        m.split_clip(vids[0].id, 100)
        vids = [c for c in m.seq.clips if c.kind == tl.VIDEO]
    x, y = vids[0], vids[1]
    m.set_clip_values(y.id, {**y.values, "saturacao": -0.5, "escala": 1.5})
    m.select([x.id, y.id])
    gid = m.group_selected()
    assert gid and x.color_group == y.color_group == gid
    m.set_clip_values(x.id, {**x.values, "exposicao": 1.0})
    y = m.seq.find(y.id)
    assert y.values["exposicao"] == 1.0
    assert y.values["saturacao"] == -0.5 and y.values["escala"] == 1.5  # o resto fica de cada um
    m.set_clip_values(x.id, {**m.seq.find(x.id).values, "escala": 2.0})  # enquadrar não é cor
    assert m.seq.find(y.id).values["escala"] == 1.5
    m.undo()
    m.undo()
    assert m.seq.find(y.id).values["exposicao"] == 0.0
    m.select([x.id])
    m.ungroup_selected()
    assert m.seq.find(x.id).color_group == "" and m.seq.find(y.id).color_group == gid
    m.set_clip_values(x.id, {**m.seq.find(x.id).values, "exposicao": -1.0})
    assert m.seq.find(y.id).values["exposicao"] != -1.0


# ------------------------------------------------------------------ ferramentas (funções puras)
def _tinted_gray(temp, tint, ev=0.0, gray=0.18):
    gains = colorsimple.wb_ev(temp, tint) + ev
    return (gray * np.exp2(-gains)) ** (1 / 2.2)


@pytest.mark.parametrize("temp,tint", [(0, 0), (30, 0), (-45, 12), (60, -25), (-20, -40)])
def test_eyedropper_white_balance_makes_the_pixel_neutral(temp, tint):
    rgb = _tinted_gray(temp, tint, ev=0.3)
    wb = colorsimple.white_balance_from(rgb)
    assert abs(wb["temperatura"] - temp) <= 1 and abs(wb["tonalidade"] - tint) <= 1
    # aplicado como no shader (ganho por canal na luz), o pixel fica cinza
    lin = rgb ** 2.2 * np.exp2(colorsimple.wb_ev(wb["temperatura"], wb["tonalidade"]))
    assert np.ptp(np.log2(lin)) < 0.02


def test_eyedropper_white_balance_refuses_black_and_white():
    assert colorsimple.white_balance_from([0.01, 0.01, 0.02]) is None
    assert colorsimple.white_balance_from([1.0, 1.0, 1.0]) is None


def test_auto_whole_clip_frames_are_deterministic_and_inside():
    seq = video_seq(240)
    c = seq.clips[0]
    f = colorsimple.sample_frames(c)
    assert f == colorsimple.sample_frames(c) and len(f) == colorsimple.N_AUTO
    assert f == sorted(f) and all(c.start <= x < c.end for x in f)
    short = tl.Clip(id="s", kind=tl.VIDEO, src=c.src, track=0, start=10, dur=3)
    assert colorsimple.sample_frames(short) == [10, 11, 12]


def test_auto_over_frames_is_one_adjustment_for_the_clip(test_rgb):
    img = test_rgb[:176]  # altura múltipla de 4: a mesma amostra de `auto_adjust`
    one = compositor.auto_adjust(img)
    assert colorsimple.auto_adjust_frames([img, img, img]) == one
    dark = (img.astype(np.float64) * 0.5).astype(np.uint8)
    mixed = colorsimple.auto_adjust_frames([img, dark])
    assert compositor.auto_adjust(dark)["exposicao"] > mixed["exposicao"] > one["exposicao"] - 1e-9
    assert colorsimple.auto_adjust_frames([]) == {}


def _scene(seed=3):
    rng = np.random.default_rng(seed)
    img = np.zeros((120, 160, 3))
    img[:40] = (0.45, 0.6, 0.85)
    img[40:80] = (0.5, 0.48, 0.45)
    img[80:] = (0.3, 0.45, 0.22)
    img += rng.normal(0, 0.03, img.shape)
    return np.clip(img, 0, 1)


def _grade(code_img, ev=0.0, temp=0.0, tint=0.0):
    lin = np.maximum(code_img, 0) ** 2.2 * np.exp2(ev + colorsimple.wb_ev(temp, tint))
    return np.clip(lin ** (1 / 2.2), 0, 1)


def test_match_identical_frames_is_neutral():
    s = _scene()
    m = colorsimple.match_adjust(s, s)
    for k in colorsimple.MATCH_KEYS:
        assert abs(m[k]) < 0.02 or (k in ("temperatura", "tonalidade") and abs(m[k]) <= 1), (k, m[k])


def test_match_recovers_exposure_and_white_balance():
    ref = _scene()
    src = _grade(ref, ev=-1.0, temp=-30.0)  # mais escuro e mais frio que a referência
    m = colorsimple.match_adjust(src, ref, protect_skin=False)
    assert 0.8 < m["exposicao"] < 1.2
    assert 20 < m["temperatura"] < 40 and abs(m["tonalidade"]) < 8
    assert "pele_natural" not in m


def test_match_ignores_skin_and_protects_it():
    ref = _scene()
    src = ref.copy()
    patches = code(MONK)
    warm = _grade(patches, temp=25.0)  # a mesma cena, com a pele mais quente só no clipe: não deve puxar o balanço
    for i in range(len(patches)):
        ref[45:75, 5 + i * 15:17 + i * 15] = patches[i]
        src[45:75, 5 + i * 15:17 + i * 15] = warm[i]
    assert masks.skin_mask(warm).min() > 0.5
    with_skin = colorsimple.match_adjust(src, ref, protect_skin=True)
    assert abs(with_skin["temperatura"]) <= 2 and with_skin["pele_natural"] == 0.5
    without = colorsimple.match_adjust(src, ref, protect_skin=False)
    assert without["temperatura"] < -3


def test_match_values_add_to_the_reference_clip():
    vals = editparams.VIDEO.defaults()
    vals["nitidez"] = 0.3
    ref_vals = {**editparams.VIDEO.defaults(), "exposicao": 0.5, "temperatura": 10.0, "saturacao": 0.2}
    out = colorsimple.match_values(vals, {"exposicao": 0.5, "temperatura": 5.0, "saturacao": 0.1, "contraste": 0.0,
                                          "tonalidade": 0.0, "pele_natural": 0.5}, ref_vals)
    assert out["exposicao"] == 1.0 and out["temperatura"] == 15.0 and abs(out["saturacao"] - 0.32) < 1e-9
    assert out["nitidez"] == 0.3 and out["pele_natural"] == 0.5
    assert editparams.VIDEO.sanitize(out) == out


@pytest.mark.parametrize("rgb,hue,band", [((1.0, 0.0, 0.0), 0.0, "vermelho"), ((1.0, 0.5, 0.0), 30.0, "laranja"),
                                          ((0.1, 0.4, 0.9), 217.5, "azul"), ((0.2, 0.8, 0.8), 180.0, "ciano")])
def test_click_color_gives_hue_and_band(rgb, hue, band):
    t = colorsimple.pick_target(rgb)
    assert abs(t["alvo_matiz"] - hue) <= 0.5 and t["band"] == band


def test_click_on_gray_is_refused():
    assert colorsimple.pick_target((0.5, 0.5, 0.5)) is None
    assert colorsimple.nearest_band(200.0) == "ciano" and colorsimple.nearest_band(350.0) == "vermelho"


def test_numpy_reference_does_what_it_says():
    p = masks.frame_points(W, H)
    img = np.zeros((H, W, 3))
    img[:] = (0.5, 0.5, 0.5)
    img[:, :60] = (0.15, 0.3, 0.85)                      # azul
    img[:, 60:120] = code(MONK)[5]                       # pele
    v = {**editparams.VIDEO.defaults(), "alvo_matiz": float(colorsimple.rgb2hsv(img[0, 0])[0]), "alvo_sat": -1.0}
    out = colorsimple.apply(img, img, p, v)
    assert np.ptp(out[0, 0]) < 0.01                      # o azul perdeu a cor
    assert np.allclose(out[:, 60:], img[:, 60:])          # o resto não
    v = {**editparams.VIDEO.defaults(), "degrade_exposicao": -1.0, "degrade_suavidade": 0.0}
    out = colorsimple.apply(img, img, p, v)
    assert out[10, 200].mean() < img[10, 200].mean() and np.allclose(out[H - 10, 200], img[H - 10, 200])
    # pele natural: a pele volta à cor do arquivo depois de esfriar o clipe inteiro
    cold = _grade(img, temp=-100.0)
    v = {**editparams.VIDEO.defaults(), "pele_natural": 1.0}
    out = colorsimple.apply(img, cold, p, v)

    def ab(c):  # a cor (a, b do OkLab) relativa à claridade
        lab = masks.oklab(masks.code_to_lin(c))
        return lab[1:] / lab[0]

    assert np.linalg.norm(ab(out[90, 90]) - ab(img[90, 90])) < 0.3 * np.linalg.norm(ab(cold[90, 90]) - ab(img[90, 90]))
    L = [masks.oklab(masks.code_to_lin(c))[0] for c in (out[90, 90], cold[90, 90])]
    assert abs(L[0] - L[1]) < 1e-6                        # a claridade é a do clipe ajustado
    assert np.allclose(out[90, 200], cold[90, 200])       # o cinza continua frio


# ------------------------------------------------------------------ GPU
pytest_gpu = pytest.mark.gpu


def _frame(seq, img):
    return sequence.FrameLayers(0, [sequence.LayerImage(l, img) for l in seq.layers_at(0)])


def _test_image():
    img = np.zeros((H, W, 3))
    y, x = np.mgrid[0:H, 0:W]
    img[..., 0] = 0.15 + 0.7 * x / W
    img[..., 1] = 0.2 + 0.6 * y / H
    img[..., 2] = 0.5 + 0.3 * np.sin(x / 17.0)
    for i, t in enumerate(code(MONK)):
        img[60:120, i * 32:i * 32 + 30] = t
    return np.rint(np.clip(img, 0, 1) * 255).astype(np.uint8)


CASES = [
    {"alvo_matiz": 20.0, "alvo_largura": 40.0, "alvo_desvio": 60.0, "alvo_sat": 0.4, "alvo_luz": -0.3},
    {"degrade_exposicao": -1.2, "degrade_temperatura": -40.0, "degrade_saturacao": 0.5, "degrade_angulo": 30.0,
     "degrade_suavidade": 300.0, "degrade_y": -100.0},
    {"degrade_tipo": "radial", "degrade_raio": 300.0, "degrade_exposicao": 0.8, "degrade_inverter": True},
    {"pele_natural": 1.0},
    {"pele_natural": 0.6, "pele_centro": 55.0, "alvo_matiz": 200.0, "alvo_sat": -0.8},
]


@pytest_gpu
@pytest.mark.parametrize("case", range(len(CASES)))
def test_gpu_matches_numpy(gl_engine, case):
    img = _test_image()
    seq, c = one_clip(**CASES[case])
    out = gl_engine.compose(_frame(seq, img), seq, W, H, 8).astype(np.float64) / 255.0
    cin = img.astype(np.float64) / 255.0
    ref = np.clip(colorsimple.apply(cin, cin, masks.frame_points(W, H), c.values), 0.0, 1.0)
    err = np.abs(out - ref)
    assert err.max() < 2.5 / 255.0, (case, err.max() * 255)
    assert np.abs(out - cin).max() > 10 / 255.0  # o ajuste fez algo


@pytest_gpu
def test_gpu_neutral_settings_keep_the_clip_bits(gl_engine):
    img = _test_image()
    seq, c = one_clip(degrade_angulo=45.0, alvo_matiz=100.0, pele_centro=40.0)
    assert np.array_equal(gl_engine.compose(_frame(seq, img), seq, W, H, 8), img)
