"""Perfil de câmera por clipe no modo Edição (1.6, `camera.py`): clipes de câmeras diferentes numa montagem só.

Um clipe com perfil próprio é convertido para a entrada do look (`editshaders.CAMERA`) e a montagem vai ao look em
float32; o resultado tem que ser o do look lendo o arquivo daquele clipe com o perfil dele (o modo Película). Com
todos os clipes em "Igual ao do look" nada muda (referência da BASE em `tests/test_entrada_base.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from pelicula import camera, editparams, look, media, params, presets, project, sequence, timeline as tl
from pelicula.frame import Recipe

sys.path.insert(0, str(Path(__file__).resolve().parent))
import entrada_base as base  # noqa: E402

W, H = 64, 16


def one_clip(w=W, h=H, **values):
    s = tl.Source("cena.png", w, h, 24.0, "24/1", 1, 0.0, is_image=True, has_audio=False)
    seq = tl.Sequence.for_source(s)
    c = seq.clips[0]
    if values:
        seq.set_values(c.id, {**c.values, **values})
    return seq, seq.clips[0]


# ------------------------------------------------------------------ sem GPU
def test_clip_section_is_neutral_and_sparse():
    sec = next(s for s in editparams.VIDEO_SECTIONS if s.key == "camera")
    assert [p.key for p in sec.params] == list(camera.KEYS)
    d = editparams.VIDEO.defaults()
    assert (d["camera_entrada"], d["camera_reescalado"], d["camera_ei"]) == ("look", False, "800")
    choices = [k for k, _l in editparams.VIDEO.params["camera_entrada"].choices]
    assert choices == ["look"] + [k for k, _l in params.ENTRADAS]           # os perfis do look, na mesma ordem
    assert set(camera.KEYS) <= editparams.SPARSE_KEYS
    assert not set(camera.KEYS) & set(editparams.color_keys())               # "Restaurar cor" não mexe no perfil
    assert not any(editparams.VIDEO.params[k].animatable for k in camera.KEYS)


def test_profile_helpers():
    assert camera.clip_profile({"camera_entrada": "look"}) is None and camera.clip_profile({}) is None
    assert camera.clip_profile({"camera_entrada": "vlog"}) == "vlog"
    assert camera.target_of(None, True) == camera.Target()
    t = camera.target_of(dict(params.defaults(), entrada="slog3"), True)
    assert t == camera.Target(look.INPUT_IDS["slog3"], True, "sgamut3cine")
    assert not camera.target_of(dict(params.defaults(), entrada="slog3"), False).cv
    assert not camera.target_of(dict(params.defaults(), entrada="slog3", log_reescalado=True), True).cv
    assert camera.target_of(dict(params.defaults(), entrada="logc3", logc3_ei="1600"), True).id == \
        look.LOGC3_EI_ID + 10
    # o mesmo espaço das transições da 1.5 (misturam na luz da entrada do look)
    from pelicula import transitions
    v = dict(params.defaults(), entrada="vlog")
    t = camera.target_of(v, True)
    assert (t.id, t.cv) == transitions.light_of(v, True)


def test_uniforms_of_a_clip():
    src = tl.Source("a.mov", W, H, 24.0, "24/1", 2, 2 / 24, pix_fmt="yuv422p10le", color_range="tv")
    t = camera.target_of(dict(params.defaults(), entrada="slog3"), True)
    assert camera.uniforms({"camera_entrada": "look"}, src, t) is None
    U = camera.uniforms({"camera_entrada": "vlog", "camera_reescalado": False, "camera_ei": "800"}, src, t)
    assert U["u_cam_in"] == look.INPUT_IDS["vlog"] and U["u_cam_in_cv"] == 1
    assert U["u_cam_out"] == look.INPUT_IDS["slog3"] and U["u_cam_out_cv"] == 1
    m_in = np.array(U["u_cam_gamut"]).reshape(3, 3).T                       # mat3 por coluna
    np.testing.assert_allclose(m_in, look.gamut_to_709("vgamut"), atol=1e-12)
    m_out = np.array(U["u_lut_gamut"]).reshape(3, 3).T
    np.testing.assert_allclose(m_out @ look.gamut_to_709("sgamut3cine"), np.eye(3), atol=1e-12)
    # faixa cheia, log reescalado e LogC3 com outro EI
    full = tl.Source("b.mov", W, H, 24.0, "24/1", 2, 2 / 24, pix_fmt="yuv444p10le", color_range="pc")
    assert camera.uniforms({"camera_entrada": "vlog"}, full, t)["u_cam_in_cv"] == 0
    assert camera.uniforms({"camera_entrada": "vlog", "camera_reescalado": True}, src, t)["u_cam_in_cv"] == 0
    assert camera.uniforms({"camera_entrada": "logc3", "camera_ei": "1600"}, src, t)["u_cam_in"] == \
        look.LOGC3_EI_ID + 10
    assert camera.read_profile({"camera_entrada": "vlog"}) == "vlog" and camera.read_profile({}) is None


def test_json_round_trip_and_format_4():
    seq, c = one_clip()
    assert not camera.uses_profiles(seq)
    assert seq.is_trivial() == "cena.png"
    plain = seq.to_json()
    assert not any(k in plain["clipes"][0]["valores"] for k in camera.KEYS)    # o JSON de sempre
    assert "ajustes_clipe_1_6" not in seq.features()
    seq.set_values(c.id, {**c.values, "camera_entrada": "clog3"})
    assert camera.uses_profiles(seq) and seq.is_trivial() is None                # agora a montagem muda a imagem
    data = seq.to_json()
    assert data["clipes"][0]["valores"]["camera_entrada"] == "clog3"
    back = tl.Sequence.from_json(data)
    assert back.clips[0].values["camera_entrada"] == "clog3" and back.to_json() == data
    feats = seq.features()
    assert "ajustes_clipe_1_6" in feats and project.needed_format(feats, True) == project.FORMAT == 4
    # o retrato da 1.5 não tem as chaves: qualquer valor fora do padrão pede o formato 4
    for k, v in (("camera_reescalado", True), ("camera_ei", "1600")):
        s2, c2 = one_clip(**{k: v})
        assert "ajustes_clipe_1_6" in s2.features(), k


def test_plain_montage_recipe_does_not_ask_for_the_camera_path():
    seq, _c = one_clip()

    class Spy:
        kw = None

        def compose(self, *a, **kw):
            Spy.kw = kw
            return np.zeros((H, W, 3), np.uint8)

    r = Recipe.for_source(params.defaults(), 24.0, 8, legal=True, seq=seq, size=(W, H))
    fl = sequence.FrameLayers(0, [sequence.LayerImage(l, np.zeros((H, W, 3), np.uint8)) for l in seq.layers_at(0)])
    r.montage(Spy(), fl)
    assert "camera" not in Spy.kw and "float_out" not in Spy.kw
    seq.set_values(seq.clips[0].id, {**seq.clips[0].values, "camera_entrada": "slog3"})
    r = Recipe.for_source(params.defaults(), 24.0, 8, legal=True, seq=seq, size=(W, H))
    r.montage(Spy(), fl)
    assert Spy.kw["camera"] == camera.Target() and Spy.kw["float_out"] is True
    r = Recipe.for_source(None, 24.0, 8, legal=True, seq=seq, size=(W, H))      # sem look: a saída é a montagem
    r.montage(Spy(), fl)
    assert Spy.kw["float_out"] is False and Spy.kw["camera"] == camera.Target()
    # prévia do modo Edição sem película: o espaço continua sendo o da entrada do look
    r = Recipe.for_source(None, 24.0, 8, legal=True, seq=seq, size=(W, H),
                          look_input=dict(params.defaults(), entrada="vlog"))
    r.montage(Spy(), fl)
    assert Spy.kw["float_out"] is False and Spy.kw["camera"].id == look.INPUT_IDS["vlog"]


# ------------------------------------------------------------------ na GPU, sem arquivos
def _layers(seq, img):
    return sequence.FrameLayers(0, [sequence.LayerImage(l, img) for l in seq.layers_at(0)])


@pytest.mark.gpu
@pytest.mark.parametrize("pid", ["original", "vision3_500t"])
@pytest.mark.parametrize("look_in", ["slog3", "logc4", "rec709", "linear", "hlg", "pq", "clog3", "logc3"])
def test_rec709_clip_in_a_log_look_is_the_rec709_look(gl_engine, test_rgb, pid, look_in):
    """Um clipe Rec.709 numa montagem cujo look lê outro perfil: o resultado é o look em Rec.709 sobre o clipe."""
    h, w = test_rgb.shape[:2]
    seq, _c = one_clip(w, h, camera_entrada="rec709")
    vals = dict(presets.builtin_values(pid), entrada=look_in)
    got = Recipe.for_source(vals, 24.0, 16, legal=False, seq=seq, size=(w, h)).render(gl_engine,
                                                                                       _layers(seq, test_rgb), 3)
    want = Recipe.for_source(dict(vals, entrada="rec709"), 24.0, 16, legal=False).render(gl_engine, test_rgb, 3)
    diff = np.abs(got.astype(np.int64) - want.astype(np.int64))
    # até um degrau do meio-float (f2) em que o look guarda a imagem perto de 1,0 (2^-10 = 64/65535); no PQ, cuja
    # curva é muito inclinada, um ou outro pixel dá alguns degraus
    assert (diff.max(-1) <= 64).mean() >= 0.999 and diff.max() <= 256, f"{diff.max()} / 65535"


@pytest.mark.gpu
def test_clips_that_follow_the_look_are_untouched_by_the_camera_pass(gl_engine, test_rgb):
    h, w = test_rgb.shape[:2]
    seq, _c = one_clip(w, h)
    fl = _layers(seq, test_rgb)
    plain = gl_engine.compose(fl, seq, w, h, 8)
    t = camera.target_of(dict(params.defaults(), entrada="slog3"), True)
    np.testing.assert_array_equal(gl_engine.compose(fl, seq, w, h, 8, camera=t), plain)
    f = gl_engine.compose(fl, seq, w, h, 8, camera=t, float_out=True)
    assert f.dtype == np.float32 and f.shape == (h, w, 3)
    np.testing.assert_allclose(f, test_rgb / 255.0, atol=2e-5)            # a tela em float, sem arredondar


@pytest.mark.gpu
def test_float_canvas_carries_light_above_one(gl_engine):
    """Um clipe em luz linear acima de 1,0 (16 bits não guardam: float32 de um log) passa à tela sem corte."""
    seq, c = one_clip(8, 4, camera_entrada="linear")
    img = np.full((4, 8, 3), 3.5, np.float32)
    img[:, :4] = 0.25
    t = camera.target_of(dict(params.defaults(), entrada="linear"), False)
    out = gl_engine.compose(_layers(seq, img), seq, 8, 4, 16, camera=t, float_out=True)
    np.testing.assert_allclose(out[:, 4:], 3.5, rtol=1e-6)
    np.testing.assert_allclose(out[:, :4], 0.25, rtol=1e-6)
    # e com o look em S-Log3: o código de 3,5 em S-Log3 (abaixo de 1, sem corte)
    t = camera.target_of(dict(params.defaults(), entrada="slog3"), False)
    out = gl_engine.compose(_layers(seq, img), seq, 8, 4, 16, camera=t, float_out=True)
    want = (420.0 + np.log10((3.5 + 0.01) / 0.19) * 261.5) / 1023.0
    np.testing.assert_allclose(out[:, 4:], want, rtol=1e-5)


@pytest.mark.gpu
def test_camera_pass_keeps_the_transparency(gl_engine):
    seq, c = one_clip(8, 4, camera_entrada="slog3")
    seq.background = (0.2, 0.4, 0.6)
    rgba = np.zeros((4, 8, 4), np.uint8)
    rgba[:, 4:] = (120, 90, 60, 255)                                       # metade opaca, metade transparente
    t = camera.target_of(dict(params.defaults(), entrada="rec709"), False)
    out = gl_engine.compose(_layers(seq, rgba), seq, 8, 4, 16, camera=t, float_out=True)
    np.testing.assert_allclose(out[:, :4], np.broadcast_to((0.2, 0.4, 0.6), (4, 4, 3)), atol=1e-6)
    opaque = gl_engine.compose(_layers(seq, np.ascontiguousarray(rgba[..., :3])), seq, 8, 4, 16, camera=t,
                               float_out=True)
    np.testing.assert_allclose(out[:, 4:], opaque[:, 4:], atol=2e-6)


# ------------------------------------------------------------------ dois clipes log de verdade (ffmpeg)
PATCHES = [(0.0, 0.0, 0.0), (0.02, 0.02, 0.02), (0.09, 0.09, 0.09), (0.18, 0.18, 0.18), (0.9, 0.9, 0.9),
           (5.0, 5.0, 5.0), (30.0, 30.0, 30.0), (0.4, 0.05, 0.02), (0.02, 0.3, 0.05), (0.03, 0.05, 0.5),
           (0.3, 0.25, 0.02), (2.0, 0.4, 0.1), (0.05, 0.4, 0.6), (0.5, 0.1, 0.45), (1.0, 1.0, 0.2), (0.1, 0.1, 0.1)]


def slog3_cv(x):
    x = np.asarray(x, np.float64)
    hi = (420.0 + np.log10((np.maximum(x, 0.01125) + 0.01) / 0.19) * 261.5) / 1023.0
    return np.where(x >= 0.01125, hi, (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0)


def vlog_cv(x):
    x = np.asarray(x, np.float64)
    return np.where(x < 0.01, 5.6 * x + 0.125, 0.241514 * np.log10(np.maximum(x, 0.01) + 0.00873) + 0.598206)


def _log_file(path: Path, cv_of) -> None:
    """Vídeo 10 bits 4:4:4 de faixa legal com as manchas (4 colunas cada) no código da câmera."""
    rgb = np.repeat(np.asarray(PATCHES, np.float64)[None], H, axis=0).repeat(4, axis=1)   # (H, W, 3) linear
    v = (cv_of(rgb) * 1023.0 - 64.0) / 876.0                                              # valor expandido
    y = v @ np.array([0.2126, 0.7152, 0.0722])
    cb, cr = (v[..., 2] - y) / 1.8556, (v[..., 0] - y) / 1.5748
    yuv = np.stack([64 + 876 * y, 512 + 896 * cb, 512 + 896 * cr], -1)
    base.synthetic_video(path, "yuv444p10le", np.clip(np.round(yuv), 0, 1023).astype(np.uint16))


@pytest.fixture(scope="module")
def log_files(ffmpeg_ok, tmp_path_factory):
    if not media.has_zscale():
        pytest.skip("ffmpeg sem zscale (a leitura do log em float precisa dele)")
    d = tmp_path_factory.mktemp("camera")
    a, b = d / "sony.mkv", d / "panasonic.mkv"
    _log_file(a, slog3_cv)
    _log_file(b, vlog_cv)
    return str(a), str(b)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("pid", ["original", "vision3_500t"])
def test_two_log_clips_in_one_montage_are_each_decoded_right(gl_engine, log_files, pid):
    """S-Log3 e V-Log na mesma montagem, com o look lendo S-Log3: cada quadro sai como o look lendo o arquivo
    daquele clipe com o perfil dele (Película), inclusive os super-brancos (código acima de 940)."""
    pa, pb = log_files
    sa, sb = media.probe_source(pa), media.probe_source(pb)
    seq = tl.Sequence(W, H, "24/1")
    seq.insert_media(sa)
    seq.insert_media(sb)
    ca, cb = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    seq.set_values(cb.id, {**cb.values, "camera_entrada": "vlog"})
    seq.set_values(ca.id, {**ca.values, "camera_entrada": "slog3"})
    vals = dict(presets.builtin_values(pid), entrada="slog3")
    legal = sequence.legal_range(seq)
    assert legal
    for clip, path, prof in ((ca, pa, "slog3"), (cb, pb, "vlog")):
        t = seq.find(clip.id).start
        fl = sequence.grab(seq, t, W, H, 16, hq=True)
        assert fl.layers[0].image.dtype == np.float32 and fl.layers[0].image.max() > 1.0   # super-brancos lidos
        got = Recipe.for_source(vals, 24.0, 16, legal=legal, seq=seq, size=(W, H)).render(gl_engine, fl, 5)
        img = media.grab_frame(media.probe(path), 0, W, H, 16, hq=True, profile=prof)
        want = Recipe.for_source(dict(vals, entrada=prof), 24.0, 16, legal=True).render(gl_engine, img, 5)
        diff = np.abs(got.astype(np.int64) - want.astype(np.int64))
        assert diff.max() <= 4, f"{prof}: {diff.max()} / 65535"
    # a mesma montagem lida em sequência (exportação) dá os mesmos quadros
    rd = sequence.SequenceReader(seq, W, H, 16, hq=True)
    try:
        frames = [rd.read() for _ in range(seq.duration)]
    finally:
        rd.close()
    for t, fl in enumerate(frames):
        np.testing.assert_array_equal(fl.layers[0].image, sequence.grab(seq, t, W, H, 16, hq=True).layers[0].image)
