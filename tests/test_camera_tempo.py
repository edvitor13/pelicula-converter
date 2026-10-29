"""1.6, tempo da câmera de cinema (`tempo_camera.py`): obturador a partir de vídeo rápido e manivela por clipe.

Obturador: pesos da janela (somam 1, 180° = metade do período, fechado = o quadro mais próximo), mistura na luz linear
na GPU contra a referência em numpy, barras em movimento num vídeo sem perdas (rastro do tamanho certo, energia
conservada), desligado = leitura de sempre, prévia da exportação = exportação, `grab` = `SequenceReader` no modo
Edição. Manivela: tabelas do quadro do arquivo por quadro da sequência, oscilação limitada e determinística, a
velocidade (e o som) acompanhando a cadência num passo só.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from pelicula import editparams, export, look, media, params, sequence, tempo_camera as tc
from pelicula import timeline as tl
from pelicula.frame import Recipe


# ------------------------------------------------------------------ pesos da janela
@pytest.mark.parametrize("src,out", [(60, 24), (50, 25), (120, 24), (59.94, 23.976), (120, 30), (50, 24)])
@pytest.mark.parametrize("angle", [45.0, 90.0, 172.8, 180.0, 270.0, 360.0])
def test_window_weights_sum_to_one_and_cover_the_open_shutter(src, out, angle):
    for i in range(0, 40):
        win = tc.file_window(i, out, src, angle, 10_000)
        assert win is not None
        assert sum(w for _k, w in win) == pytest.approx(1.0, abs=1e-12)
        ks = [k for k, _w in win]
        assert ks == sorted(ks) and len(set(ks)) == len(ks)
        # o comprimento da janela em quadros da fonte = ângulo/360 × (fonte/saída)
        length = angle / 360.0 * src / out
        assert len(ks) <= int(np.ceil(length)) + 1
        u = i * src / out
        assert ks[0] == int(np.floor(u + 0.5 + 1e-9)), "a janela começa no quadro mais próximo do instante"


def test_window_off_below_twice_the_rate_and_closed_is_nearest():
    assert tc.file_window(5, 24, 30, 180) is None, "30 → 24 não tem o dobro: o quadro de sempre"
    assert tc.file_window(5, 24, 47.9, 180) is None
    assert tc.file_window(5, 24, 60, 0.0) is None, "obturador desligado"
    for i in range(30):  # janela fechando: o quadro mais próximo, como o filtro fps do ffmpeg
        assert tc.window_weights(i * 2.5, 0.0, -0.5) == [(int(np.floor(i * 2.5 + 0.5)), 1.0)]


def test_180_is_half_the_period():
    # 60 → 24: o período da saída tem 2,5 quadros da fonte; 180° abre 1,25
    assert tc.file_window(0, 24, 60, 180) == [(0, pytest.approx(0.4)), (1, pytest.approx(0.6))]
    assert tc.file_window(0, 24, 60, 360) == [(0, pytest.approx(0.2)), (1, pytest.approx(0.4)),
                                              (2, pytest.approx(0.4))]
    # 120 → 24 a 180°: 2,5 quadros
    win = tc.file_window(0, 24, 120, 180)
    assert [k for k, _w in win] == [0, 1, 2] and win[0][1] == pytest.approx(0.2)


def test_window_clamps_to_the_file_and_is_deterministic():
    win = tc.file_window(400, 24, 60, 360, frames=1000)
    assert all(0 <= k <= 999 for k, _w in win)
    assert sum(w for _k, w in win) == pytest.approx(1.0)
    assert tc.file_window(7, 24, 60, 180, 99) == tc.file_window(7, 24, 60, 180, 99)


def test_shutter_param_is_neutral_by_default():
    v = params.defaults()
    assert v["obturador_on"] is False and tc.shutter_angle(v) == 0.0
    assert Recipe.for_source(v, 24, 8, legal=True).shutter == 0.0
    assert tc.shutter_angle({**v, "obturador_on": True}) == 180.0
    assert tc.shutter_angle({**v, "obturador_on": True, "obturador_angulo": "172.8"}) == pytest.approx(172.8)
    assert not params.PARAMS["obturador_angulo"].animatable, "a escolha do ângulo não anima"


# ------------------------------------------------------------------ mistura na GPU
def _app_curve_decode(code):
    return 0.18 * np.exp2(np.clip(look._disp_to_stops(code), -12, 12))


@pytest.mark.gpu
@pytest.mark.parametrize("curve,cv", [(0, False), (1, False), (3, True), (4, False)])
def test_gpu_blend_matches_numpy_in_linear_light(gl_engine, curve, cv):
    rng = np.random.default_rng(3)
    imgs = [rng.integers(30, 220, (6, 8, 3), dtype=np.uint8) for _ in range(5)]
    ws = [0.1, 0.3, 0.2, 0.25, 0.15]
    out = gl_engine.temporal_blend(imgs, ws, curve, cv)
    assert out.dtype == np.float32 and out.shape == (6, 8, 3)
    same = gl_engine.temporal_blend([imgs[0]] * 3, [0.2, 0.5, 0.3], curve, cv)
    assert np.allclose(same, imgs[0] / 255.0, atol=2e-5), "quadros iguais: a mesma imagem (ida e volta da curva)"
    if curve == 1:  # linear: a média direta
        ref = sum(i.astype(np.float64) / 255.0 * w for i, w in zip(imgs, ws))
        assert np.allclose(out, ref, atol=1e-5)
    if curve == 0:  # Rec.709 do app: a média na luz da curva neutra
        lin = sum(_app_curve_decode(i.astype(np.float64) / 255.0) * w for i, w in zip(imgs, ws))
        back = gl_engine.temporal_blend([out.astype(np.float32)], [1.0], 0, False)
        assert np.allclose(_app_curve_decode(back.astype(np.float64)), lin, rtol=2e-3, atol=1e-6)
        mid = sum(i.astype(np.float64) / 255.0 * w for i, w in zip(imgs, ws))
        assert not np.allclose(out, mid, atol=1e-3), "não é a média dos códigos"


@pytest.mark.gpu
def test_gpu_blend_rgba_mixes_by_coverage(gl_engine):
    a = np.zeros((2, 2, 4), np.uint8)
    b = np.zeros((2, 2, 4), np.uint8)
    b[..., :3] = 200
    b[..., 3] = 255
    out = gl_engine.temporal_blend([a, b], [0.5, 0.5], 1, False)
    assert out.shape == (2, 2, 4)
    assert np.allclose(out[..., 3], 0.5) and np.allclose(out[..., :3], 0.5 * 200 / 255, atol=1e-5)


# ------------------------------------------------------------------ vídeo de barras em movimento
SPEED_PX = 6
BAR_W = 8


def _bars_video(ffmpeg, path, fps=60, n=60, w=96, h=16):
    frames = np.zeros((n, h, w, 3), np.uint8)
    for k in range(n):
        x = (10 + k * SPEED_PX) % (w - BAR_W)
        frames[k, :, x:x + BAR_W] = 200  # cinza claro: longe do fim da curva (o branco satura nela)
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0", str(path)]
    res = subprocess.run(cmd, input=frames.tobytes(), capture_output=True)
    if res.returncode != 0:
        pytest.skip(res.stderr.decode("utf-8", "replace"))
    return str(path), frames


@pytest.fixture(scope="module")
def bars(ffmpeg_ok, tmp_path_factory):
    return _bars_video(ffmpeg_ok, tmp_path_factory.mktemp("barras") / "barras60.mkv")


def _shutter_values(angle="180", **kw):
    return params.sanitize({"obturador_on": True, "obturador_angulo": angle, **kw})


def _settings(fps="24"):
    s = export.ExportSettings(codec="ffv1", container="mkv", pix="bgr0", fps=fps, audio="none")
    return s


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("angle,extra", [("180", 7.5), ("360", 15.0), ("90", 3.75)])
def test_moving_bar_gets_the_motion_of_the_open_shutter(gl_engine, bars, angle, extra):
    path, frames = bars
    info = media.probe(path)
    assert info.fps == pytest.approx(60)
    v = _shutter_values(angle)
    s = _settings("24")
    rec = export.frame_pipeline(info, v, s)
    assert rec.fps == 24 and rec.shutter == float(angle)
    f = rec.fit
    reader, skip = export.open_reader(info, rec, 0, 10, "24", media.Perf())
    assert isinstance(reader, tc.WindowReader) and skip == 0
    try:
        for i in range(1, 6):
            st = reader.read()
            assert isinstance(st, tc.Stack) and len(st.images) >= 1
            blended = rec.montage(gl_engine, st)
            row = blended[8].astype(np.float64)
            if blended.dtype != np.float32:  # um quadro só (90°): a imagem passa direto
                row /= float(np.iinfo(blended.dtype).max)
            lin = _app_curve_decode(row).mean(axis=1)  # uma linha, luz por coluna
            mx = float(np.iinfo(st.images[0].dtype).max)
            single = _app_curve_decode(st.images[0][8].astype(np.float64) / mx).mean(axis=1)
            assert lin.sum() == pytest.approx(single.sum(), rel=2e-3), "a energia se conserva"
            ref = sum(_app_curve_decode(im[8].astype(np.float64) / mx).mean(axis=1) * wt
                      for im, wt in zip(st.images, st.weights))
            assert np.allclose(lin, ref, rtol=2e-3, atol=1e-6), "a média dos quadros na luz linear"
            lit = np.flatnonzero(lin > single.max() * 0.004)
            width = lit[-1] - lit[0] + 1
            assert width == BAR_W + SPEED_PX * (len(st.frames) - 1), f"rastro de {width} px no quadro {i}"
            length = extra / SPEED_PX  # quadros da fonte com o obturador aberto (ângulo/360 × 60/24)
            assert int(np.ceil(length - 1e-9)) <= len(st.frames) <= int(np.ceil(length)) + 1
    finally:
        reader.close()


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_shutter_off_reads_like_before(bars):
    path, _frames = bars
    info = media.probe(path)
    rec = export.frame_pipeline(info, params.defaults(), _settings("24"))
    reader, skip = export.open_reader(info, rec, 0, 5, "24", media.Perf())
    try:
        assert isinstance(reader, media.FrameReader), "desligado: o leitor de sempre (filtro fps do ffmpeg)"
    finally:
        reader.close()
    rec = export.frame_pipeline(info, _shutter_values(), _settings("original"))
    reader, _skip = export.open_reader(info, rec, 0, 5, None, media.Perf())
    try:
        assert isinstance(reader, media.FrameReader), "mesma taxa: nada a misturar"
    finally:
        reader.close()


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_preview_equals_the_export_frame(gl_engine, bars):
    path, _frames = bars
    info = media.probe(path)
    v = _shutter_values("180", grao_on=True)
    s = _settings("24")
    rec = export.frame_pipeline(info, v, s, depth=16)
    reader, _skip = export.open_reader(info, rec, 0, 9, "24", media.Perf())
    try:
        stacks = [reader.read() for _ in range(9)]
    finally:
        reader.close()
    for i in (2, 4, 8):
        out = rec.render(gl_engine, stacks[i], i)
        prev = export.preview_frame(gl_engine, info, v, s, int(round(i * 60 / 24)), depth=16)
        assert np.array_equal(out, prev), f"quadro {i}"
        again = rec.render(gl_engine, stacks[i], i)
        assert np.array_equal(out, again), "determinístico"


# ------------------------------------------------------------------ modo Edição: por clipe
def _seq_with(path, fps="24/1"):
    src = media.probe_source(path)
    seq = tl.Sequence(width=src.width, height=src.height, fps_str=fps)
    seq.insert_media(src, at=0)
    return seq, next(c for c in seq.clips if c.kind == tl.VIDEO)


@pytest.mark.ffmpeg
def test_clip_window_only_for_fast_clips(bars):
    path, _frames = bars
    seq, clip = _seq_with(path)
    win = seq.src_window(clip, 3, 180.0)
    assert win is not None and sum(w for _k, w in win) == pytest.approx(1.0)
    assert win[0][0] == seq.src_frame(clip, 3), "a janela começa no quadro de sempre"
    assert seq.src_window(clip, 3, 0.0) is None
    same, c2 = _seq_with(path, "60/1")
    assert same.src_window(c2, 3, 180.0) is None, "na mesma taxa não há o que misturar"
    seq.set_speed(clip.id, 0.5)
    assert seq.src_window(clip, 3, 180.0) is None, "câmera lenta: 1,25 quadro do arquivo por quadro"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_edit_grab_equals_reader_and_render(gl_engine, bars):
    path, _frames = bars
    seq, clip = _seq_with(path)
    w, h = seq.width, seq.height
    v = _shutter_values()
    rec = Recipe.for_source(v, seq.fps, 8, legal=sequence.legal_range(seq), seq=seq, size=(w, h))
    assert rec.shutter == 180.0
    reader = sequence.SequenceReader(seq, w, h, 8, shutter=rec.shutter)
    try:
        got = [reader.read() for _ in range(seq.duration)]
    finally:
        reader.close()
    sequence.clear_cache()
    for fl in got:
        ref = sequence.grab(seq, fl.frame, w, h, 8, shutter=rec.shutter)
        (a,), (b,) = fl.layers, ref.layers
        assert a.stack is not None and b.stack is not None
        assert a.stack[1] == b.stack[1]
        assert all(np.array_equal(x, y) for x, y in zip(a.stack[0], b.stack[0])), f"quadro {fl.frame}"
        assert np.array_equal(rec.render(gl_engine, fl, fl.frame), rec.render(gl_engine, ref, fl.frame))
    plain = sequence.grab(seq, 2, w, h, 8)
    assert plain.layers[0].stack is None, "sem obturador nada muda na leitura"


# ------------------------------------------------------------------ manivela
def _crank_seq(src_fps=24.0, frames=240, seq_fps="24/1"):
    src = tl.Source(path="C:/v/manivela.mp4", width=320, height=180, fps=src_fps, frames=frames,
                    duration=frames / src_fps, has_audio=True)
    seq = tl.Sequence(width=320, height=180, fps_str=seq_fps)
    seq.insert_media(src, at=0)
    return seq, next(c for c in seq.clips if c.kind == tl.VIDEO)


@pytest.mark.parametrize("cadence,table", [
    ("16", [0, 1, 3, 4, 6, 7, 9, 10, 12, 13, 15, 16]),
    ("18", [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]),
])
def test_crank_frame_mapping_tables(cadence, table):
    seq, clip = _crank_seq()
    seq.set_values(clip.id, {**clip.values, "manivela": cadence})
    assert clip.speed == pytest.approx(24 / float(cadence))
    audio = next(c for c in seq.clips if c.kind == tl.AUDIO)
    assert audio.speed == pytest.approx(clip.speed), "o som segue pela velocidade (ligado ao vídeo)"
    assert clip.dur == round(240 / clip.speed)
    assert [seq.src_frame(clip, t) for t in range(12)] == table


def test_crank_from_60fps_is_evenly_stepped():
    seq, clip = _crank_seq(src_fps=60.0, frames=600)
    seq.set_values(clip.id, {**clip.values, "manivela": "16"})
    got = [seq.src_frame(clip, t) for t in range(9)]
    assert got == [int(np.floor(t * 60 / 16 + 1e-6)) for t in range(9)]


def test_crank_back_to_normal_restores_speed_and_keeps_a_manual_speed():
    seq, clip = _crank_seq()
    seq.set_values(clip.id, {**clip.values, "velocidade": 2.0})
    seq.set_values(clip.id, {**clip.values, "manivela": "16"})
    assert clip.speed == pytest.approx(3.0)
    seq.set_values(clip.id, {**clip.values, "manivela": "nenhuma"})
    assert clip.speed == pytest.approx(2.0)


def test_crank_wobble_is_bounded_deterministic_and_neutral_off():
    seq, clip = _crank_seq(src_fps=60.0, frames=6000)
    seq.set_values(clip.id, {**clip.values, "manivela": "18"})
    base = [seq.src_frame(clip, t) for t in range(clip.dur)]
    seq.set_values(clip.id, {**clip.values, "manivela_oscila": 1.0, "manivela_semente": 4})
    a = [seq.src_frame(clip, t) for t in range(clip.dur)]
    assert a == [seq.src_frame(clip, t) for t in range(clip.dur)], "determinístico"
    diff = np.array(a) - np.array(base)
    assert np.abs(diff).max() <= int(np.ceil(tc.CRANK_JITTER_S * 60)) + 1, "limitado: nada acumula"
    assert np.count_nonzero(diff) > len(diff) // 4, "a mão oscila"
    assert all(b >= x for x, b in zip(a, a[1:])), "a imagem nunca volta"
    seq.set_values(clip.id, {**clip.values, "manivela_semente": 5})
    assert [seq.src_frame(clip, t) for t in range(clip.dur)] != a, "outra semente, outra mão"


def test_crank_params_are_sparse_and_neutral():
    v = editparams.VIDEO.defaults()
    assert v["manivela"] == "nenhuma" and v["manivela_oscila"] == 0.0
    assert {"manivela", "manivela_oscila", "manivela_semente"} <= editparams.SPARSE_KEYS
    assert "manivela" not in editparams.stored_values("video", v)
    seq, clip = _crank_seq()
    assert [seq.src_frame(clip, t) for t in range(10)] == list(range(10))


def test_module_camera_cinema_is_beta_and_detected():
    from pelicula import modules
    m = modules.get("camera_cinema")
    assert m.status == modules.BETA and not modules.default_enabled("camera_cinema")
    assert "camera_cinema" not in modules.used_by(params.defaults())
    assert "camera_cinema" in modules.used_by(_shutter_values())
    seq, clip = _crank_seq()
    assert "camera_cinema" not in modules.used_by({}, seq)
    seq.set_values(clip.id, {**clip.values, "manivela": "18"})
    assert "camera_cinema" in modules.used_by({}, seq)
