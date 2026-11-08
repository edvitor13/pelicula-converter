"""1.9, tempo da imagem (`tempo_imagem.py`, frente F5; ARQUITETURA §53): deflicker, ruído temporal e mistura de quadros.

Sem GPU: ajustes neutros e esparsos, módulo Beta, registro na pilha, a média móvel, a análise de um vídeo sem perdas
(média do luma de cada quadro, carimbo do arquivo), a janela da mistura (0,5×, 1×, rampa, reverso = espelho, congelado,
obturador nos rápidos) e os vizinhos só com o ruído temporal ligado. Na GPU (vídeos sem perdas feitos com numpy e o
ffmpeg): a cintilação some e a rampa de luz fica, cena parada e efeito sem análise bit a bit, dividir o clipe não muda
nada, prévia == exportação; o ruído cai numa cena parada, a borda que anda não deixa fantasma, `grab` == leitor; a
mistura a 0,5× == referência numpy na luz linear e 1× bit a bit.
"""

from __future__ import annotations

import os
import subprocess

import numpy as np
import pytest

from pelicula import editparams, look, media, modules, sequence, tempo_imagem as ti, vfx
from pelicula import timeline as tl
from pelicula.frame import Recipe

W, H = 64, 36


# ------------------------------------------------------------------ ajudas
def _dec(code):
    """A curva Rec.709 do app (a de `toLinear` com a entrada rec709) em numpy."""
    return 0.18 * np.exp2(np.clip(look._disp_to_stops(np.asarray(code, dtype=np.float64)), -12, 12))


def _enc(lin):
    return look._stops_to_disp(np.log2(np.maximum(np.asarray(lin, dtype=np.float64), 1e-12) / 0.18))


def _video(ffmpeg, path, frames: np.ndarray, fps: int = 24) -> str:
    """Um vídeo sem perdas (FFV1 RGB) com estes quadros (n × h × w × 3, uint8)."""
    n, h, w, _c = frames.shape
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0", str(path)]
    res = subprocess.run(cmd, input=np.ascontiguousarray(frames).tobytes(), capture_output=True)
    if res.returncode != 0:
        pytest.skip(res.stderr.decode("utf-8", "replace"))
    return str(path)


def _seq(path, fps="24/1"):
    seq = tl.Sequence(width=W, height=H, fps_str=fps)
    c = seq.insert_media(media.probe_source(str(path)), at=0, with_audio=False)[0]
    return seq, c


def _set(seq, c, **kw):
    seq.set_values(c.id, {**c.values, **kw})


def _compose(engine, seq, t, depth=16, no_effects=False):
    rec = Recipe.for_source(None, seq.fps, depth, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
    return rec.render(engine, sequence.grab(seq, t, W, H, depth, no_effects=no_effects), t)


def _gradient(level: float = 1.0) -> np.ndarray:
    """Um degradê cinza-azulado (código 0–1) longe das pontas da curva."""
    x = np.linspace(0.25, 0.65, W)[None, :]
    y = np.linspace(0.85, 1.0, H)[:, None]
    base = x * y
    return np.stack([base, base * 0.95, base * 0.9], axis=2) * level


def _to8(code) -> np.ndarray:
    return np.rint(np.clip(code, 0, 1) * 255).astype(np.uint8)


# ------------------------------------------------------------------ sem GPU
def test_params_are_neutral_sparse_and_in_the_f5_block():
    keys = ("deflicker", "deflicker_janela", "ruido_temporal", "ruido_temporal_quadros", "mistura_quadros")
    sec = next(s for s in editparams.VIDEO_SECTIONS if s.key == ti.SECTION)
    assert [p.key for p in sec.params] == list(keys)
    assert editparams.VIDEO_SECTIONS.index(sec) >= editparams._N_BASE
    d = editparams.VIDEO.defaults()
    assert d["deflicker"] == 0.0 and d["ruido_temporal"] == 0.0 and d["mistura_quadros"] is False
    assert d["deflicker_janela"] == 0.5 and d["ruido_temporal_quadros"] == 2
    assert set(keys) <= editparams.SPARSE_KEYS
    assert editparams.stored_values("video", d) == editparams.stored_values("video", editparams.VIDEO.defaults())
    assert vfx.active_effects(d) == [] and vfx.neighbor_radius(d) == 0


def test_module_is_beta_off_and_follows_the_clips():
    m = modules.get(ti.MODULE)
    assert m.status == modules.BETA and m.group == "efeitos_visuais"
    assert ti.MODULE in vfx.EFFECT_MODULES and set(vfx.EFFECT_MODULES[ti.MODULE]) == {ti.DEFLICKER, ti.NOISE, ti.BLEND}
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    src = tl.Source("C:/nao/existe.mp4", W, H, 24.0, "24/1", 48, 2.0)
    c = seq.insert_media(src, at=0, with_audio=False)[0]
    assert ti.MODULE not in vfx.modules_used(seq)
    for key, value in (("deflicker", 0.5), ("ruido_temporal", 0.3), ("mistura_quadros", True)):
        _set(seq, c, **{key: value})
        assert ti.MODULE in vfx.modules_used(seq), key
        _set(seq, c, **{key: editparams.VIDEO.defaults()[key]})


def test_order_in_the_stack():
    v = {**editparams.VIDEO.defaults(), "deflicker": 1.0, "ruido_temporal": 1.0, "mistura_quadros": True}
    ids = [e.id for e in vfx.active_effects(v)]
    assert ids == [ti.NOISE, ti.DEFLICKER, ti.BLEND]
    assert all(vfx.ORDER["tempo"] <= vfx.EFFECTS[i].order < vfx.ORDER["desfoque_lente"] for i in ids)
    assert vfx.neighbor_radius(v) == 2
    assert vfx.neighbor_radius({**v, "ruido_temporal_quadros": 1}) == 1
    assert vfx.neighbor_radius({**v, "ruido_temporal": 0.0}) == 0


def test_smooth_is_a_centered_moving_average():
    m = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], np.float32)
    assert np.allclose(ti.smooth(m, 3), [1.5, 2.0, 3.0, 4.0, 5.0, 5.5])
    assert np.array_equal(ti.smooth(m, 1), m)
    const = np.full(50, 0.4123, np.float32)
    assert np.array_equal(ti.smooth(const, 13), const), "cena parada: o alvo é a própria média, bit a bit"
    assert ti.window_frames(0.5, 24) == 13 and ti.window_frames(0.5, 25) == 13 and ti.window_frames(0.01, 24) == 1


def _fsrc(frames=48, fps=24.0):
    return tl.Source("C:/nao/existe.mp4", W, H, fps, f"{int(fps)}/1", frames, frames / fps)


def _clip_seq(frames=48, fps=24.0, seq_fps="24/1"):
    seq = tl.Sequence(width=W, height=H, fps_str=seq_fps)
    c = seq.insert_media(_fsrc(frames, fps), at=0, with_audio=False)[0]
    return seq, c


def test_blend_window_half_speed():
    seq, c = _clip_seq()
    seq.set_speed(c.id, 0.5)
    assert all(ti.blend_window(seq, c, t) is None for t in range(c.dur)), "desligada: nada"
    _set(seq, c, mistura_quadros=True)
    assert ti.blend_window(seq, c, 0) is None  # u = 0: o quadro 0, bit a bit
    assert ti.blend_window(seq, c, 1) == [(0, 0.5), (1, 0.5)]
    assert ti.blend_window(seq, c, 2) is None
    assert ti.blend_window(seq, c, 7) == [(3, 0.5), (4, 0.5)]
    for t in range(c.dur):
        win = seq.frame_window(c, t)
        if win:
            assert win[0][0] == seq.src_frame(c, t) and abs(sum(w for _k, w in win) - 1.0) < 1e-12
    assert seq.frame_window(c, 3, 180.0, effects=False) is None
    seq.set_speed(c.id, 0.25)
    assert [ti.blend_window(seq, c, t) for t in range(4)] == [None, [(0, 0.75), (1, 0.25)], [(0, 0.5), (1, 0.5)],
                                                            [(0, 0.25), (1, 0.75)]]


def test_blend_window_off_at_one_and_faster_keeps_the_shutter():
    seq, c = _clip_seq()
    _set(seq, c, mistura_quadros=True)
    assert all(ti.blend_window(seq, c, t) is None for t in range(c.dur))
    fast, fc = _clip_seq(frames=240, fps=60.0)
    _set(fast, fc, mistura_quadros=True)
    for t in range(5):
        assert fast.frame_window(fc, t, 180.0) == fast.src_window(fc, t, 180.0) is not None
    low, lc = _clip_seq(frames=48, fps=12.0)  # 12 qps numa sequência de 24: meio quadro do arquivo por quadro
    _set(low, lc, mistura_quadros=True)
    assert ti.blend_window(low, lc, 1) == [(0, 0.5), (1, 0.5)]


def test_blend_window_freeze_image_and_file_end():
    seq, c = _clip_seq(frames=10)
    seq.set_speed(c.id, 0.5)
    _set(seq, c, mistura_quadros=True)
    last = max(t for t in range(c.dur) if seq.src_frame(c, t) == 9)
    assert ti.blend_window(seq, c, last) is None, "no último quadro do arquivo não há o seguinte"
    _set(seq, c, congelar=True)
    assert all(ti.blend_window(seq, c, t) is None for t in range(c.dur))
    img = tl.Sequence(width=W, height=H, fps_str="24/1")
    ic = img.insert_media(tl.Source("C:/nao/foto.png", W, H, 0.0, "0/1", 1, 0.0, is_image=True), at=0)[0]
    _set(img, ic, mistura_quadros=True)
    assert ti.blend_window(img, ic, 3) is None


def test_blend_window_ramp_and_reverse_mirror():
    from pelicula import timemap
    seq, c = _clip_seq(frames=96)
    _set(seq, c, mistura_quadros=True)
    seq.retime(c.id, timemap.preset_anchors("lento_meio", 0.0, 4.0, amount=1.0))
    got = [seq.frame_window(c, t) for t in range(c.dur)]
    assert any(got) and not all(got), "a rampa mistura só no trecho lento"
    for t, win in enumerate(got):
        if win:
            assert win[0][0] == seq.src_frame(c, t)
            assert (seq.src_time(c, t + 1) - seq.src_time(c, t)) * 24.0 < 1.0
    fwd, fc = _clip_seq(frames=24)
    fwd.set_speed(fc.id, 0.5)
    _set(fwd, fc, mistura_quadros=True)
    rev, rc = _clip_seq(frames=24)
    rev.set_speed(rc.id, 0.5)
    _set(rev, rc, mistura_quadros=True)
    rev.retime(rc.id, reverse=True)
    assert rc.dur == fc.dur
    n = fc.dur
    for t in range(n):
        assert rev.frame_window(rc, t) == fwd.frame_window(fc, n - 1 - t), f"quadro {t}"
        assert rev.src_frame(rc, t) == fwd.src_frame(fc, n - 1 - t)


@pytest.mark.ffmpeg
def test_analysis_reads_the_luma_of_every_frame_and_stamps_the_file(ffmpeg_ok, tmp_path):
    rng = np.random.default_rng(5)
    levels = 0.6 + 0.3 * rng.random(30)
    frames = np.stack([_to8(_gradient(lv)) for lv in levels])
    path = _video(ffmpeg_ok, tmp_path / "f.mkv", frames)
    seq, c = _seq(path)
    src = seq.sources[c.src]
    entry = ti.analyze(src)
    means = ti.means_of(entry)
    # o código que o render lê (o leitor de 16 bits, o mesmo da análise)
    seen = np.stack([sequence.grab(seq, t, W, H, 16).layers[0].image for t in range(30)]).astype(np.float64) / 65535
    ref = (seen @ np.array([0.2126, 0.7152, 0.0722])).mean(axis=(1, 2))
    assert means.dtype == np.float32 and means.shape == (30,) and entry["quadros"] == 30 and entry["fps"] == 24.0
    assert np.abs(means - ref).max() < 1e-4
    assert entry["carimbo"] == vfx.stamp(path)
    src.analysis[ti.DEFLICKER] = entry
    assert not vfx.stale(src, ti.DEFLICKER)
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 10))
    assert vfx.stale(src, ti.DEFLICKER)
    import threading
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError):
        ti.analyze(src, stop)
    with pytest.raises(ValueError):
        ti.analyze(tl.Source.virtual("cor", W, H, "24/1", None, {"nome": "x"}))


@pytest.mark.ffmpeg
def test_neighbors_only_with_noise_reduction_and_never_without_effects(ffmpeg_ok, tmp_path):
    frames = np.stack([_to8(_gradient(0.8 + 0.01 * k)) for k in range(12)])
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "n.mkv", frames))
    assert sequence.grab(seq, 5, W, H, 8).layers[0].neighbors is None
    _set(seq, c, ruido_temporal=0.5, ruido_temporal_quadros=1)
    assert [k for k, _i in sequence.grab(seq, 5, W, H, 8).layers[0].neighbors] == [-1, 1]
    _set(seq, c, ruido_temporal_quadros=2)
    assert [k for k, _i in sequence.grab(seq, 5, W, H, 8).layers[0].neighbors] == [-2, -1, 1, 2]
    assert sequence.grab(seq, 5, W, H, 8, no_effects=True).layers[0].neighbors is None


# ------------------------------------------------------------------ deflicker na GPU
def _flicker_frames(n=48, flicker=0.12, ramp=0.0, seed=7):
    """Quadros de um degradê com a luz (linear) multiplicada por uma rampa lenta e uma cintilação por quadro."""
    rng = np.random.default_rng(seed)
    base = _dec(_gradient())
    k = np.arange(n)
    gains = (1.0 + ramp * k / max(1, n - 1)) * (1.0 + flicker * (rng.random(n) * 2 - 1))
    return np.stack([_to8(_enc(base * g)) for g in gains]), gains


def _frame_light(img16) -> float:
    return float((_dec(img16.astype(np.float64) / 65535.0) @ np.array([0.2126, 0.7152, 0.0722])).mean())


def _analysed(ffmpeg, path):
    seq, c = _seq(path)
    src = seq.sources[c.src]
    src.analysis[ti.DEFLICKER] = ti.analyze(src)
    return seq, c


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_deflicker_flattens_the_flicker_and_keeps_the_ramp(gl_engine, ffmpeg_ok, tmp_path):
    frames, _g = _flicker_frames(ramp=0.4)
    seq, c = _analysed(ffmpeg_ok, _video(ffmpeg_ok, tmp_path / "pisca.mkv", frames))
    before = np.array([_frame_light(_compose(gl_engine, seq, t)) for t in range(c.dur)])
    _set(seq, c, deflicker=1.0)
    after = np.array([_frame_light(_compose(gl_engine, seq, t)) for t in range(c.dur)])

    def jitter(x):  # a cintilação: o que sobra tirando a média móvel de 5 quadros, relativo
        return np.abs(np.log(x[2:-2]) - np.log(np.convolve(x, np.ones(5) / 5, "valid"))).mean()

    assert jitter(after) < 0.25 * jitter(before)
    rise_b = np.log(before[-6:].mean() / before[:6].mean())
    rise_a = np.log(after[-6:].mean() / after[:6].mean())
    assert rise_a > 0.6 * rise_b, "a rampa lenta de luz continua"
    _set(seq, c, deflicker=0.5)
    half = np.array([_frame_light(_compose(gl_engine, seq, t)) for t in range(c.dur)])
    assert jitter(after) < jitter(half) < jitter(before)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_deflicker_static_scene_and_no_analysis_are_bit_exact(gl_engine, ffmpeg_ok, tmp_path):
    frames = np.stack([_to8(_gradient())] * 20)
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "parado.mkv", frames))
    plain = [_compose(gl_engine, seq, t) for t in (0, 7, 19)]
    _set(seq, c, deflicker=1.0)
    targets = {k for k in gl_engine._targets if str(k).startswith("fx")}
    assert all(np.array_equal(a, _compose(gl_engine, seq, t)) for a, t in zip(plain, (0, 7, 19))), "sem análise"
    assert {k for k in gl_engine._targets if str(k).startswith("fx")} == targets, "sem análise: nenhum passo"
    seq.sources[c.src].analysis[ti.DEFLICKER] = ti.analyze(seq.sources[c.src])
    for depth in (8, 16):
        _set(seq, c, deflicker=0.0)
        ref = [_compose(gl_engine, seq, t, depth) for t in (0, 7, 19)]
        _set(seq, c, deflicker=1.0)
        got = [_compose(gl_engine, seq, t, depth) for t in (0, 7, 19)]
        assert all(np.array_equal(a, b) for a, b in zip(ref, got)), f"cena parada, {depth} bits"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_deflicker_does_not_change_when_the_clip_is_split_or_trimmed(gl_engine, ffmpeg_ok, tmp_path):
    frames, _g = _flicker_frames(n=36)
    path = _video(ffmpeg_ok, tmp_path / "corte.mkv", frames)
    seq, c = _analysed(ffmpeg_ok, path)
    _set(seq, c, deflicker=1.0)
    whole = [_compose(gl_engine, seq, t) for t in range(c.dur)]
    seq.split(14)
    assert len([x for x in seq.clips if x.kind == tl.VIDEO]) == 2
    assert all(np.array_equal(whole[t], _compose(gl_engine, seq, t)) for t in range(len(whole)))
    later, lc = _seq(path)
    later.sources[lc.src].analysis = seq.sources[c.src].analysis
    later.trim_start(lc.id, 10)
    _set(later, lc, deflicker=1.0)
    t0 = lc.start
    k = later.src_frame(lc, t0)
    assert np.array_equal(_compose(gl_engine, later, t0), whole[k]), "o mesmo quadro do arquivo, o mesmo ganho"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_deflicker_preview_equals_export(gl_engine, ffmpeg_ok, tmp_path):
    from pelicula import export
    frames, _g = _flicker_frames(n=16)
    seq, c = _analysed(ffmpeg_ok, _video(ffmpeg_ok, tmp_path / "exp.mkv", frames))
    _set(seq, c, deflicker=0.8, ruido_temporal=0.6)
    info = sequence.media_info(seq)
    pipe = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, pipe, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [pipe.render(gl_engine, reader.read(), i) for i in range(10)]
    finally:
        reader.close()
    for t in range(10):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), f"quadro {t}"


# ------------------------------------------------------------------ ruído temporal na GPU
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_noise_reduction_lowers_the_noise_of_a_static_scene(gl_engine, ffmpeg_ok, tmp_path):
    rng = np.random.default_rng(11)
    clean = _gradient()
    frames = np.stack([_to8(clean + rng.normal(0.0, 0.015, clean.shape)) for _ in range(12)])
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "ruido.mkv", frames))
    t = 6
    mean = frames.astype(np.float64).mean(axis=0) / 255.0  # o "limpo" que a sequência conhece
    noisy = _compose(gl_engine, seq, t).astype(np.float64) / 65535.0
    _set(seq, c, ruido_temporal=1.0)
    two = _compose(gl_engine, seq, t).astype(np.float64) / 65535.0
    _set(seq, c, ruido_temporal_quadros=1)
    one = _compose(gl_engine, seq, t).astype(np.float64) / 65535.0
    e0, e1, e2 = (float(np.std(x - mean)) for x in (noisy, one, two))
    assert e1 < 0.8 * e0 and e2 < 0.62 * e0 and e2 < e1, (e0, e1, e2)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_noise_reduction_leaves_no_ghost_of_a_moving_edge(gl_engine, ffmpeg_ok, tmp_path):
    frames = np.zeros((12, H, W, 3), np.uint8)
    frames[:] = 40
    for k in range(12):
        x = 4 + 5 * k
        frames[k, :, x:x + 6] = 200
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "barra.mkv", frames))
    _set(seq, c, ruido_temporal=1.0)
    for t in (3, 6):
        plain = _compose(gl_engine, seq, t, no_effects=True).astype(np.int64)
        got = _compose(gl_engine, seq, t).astype(np.int64)
        assert int(np.abs(got - plain).max()) <= 2 * 257, f"quadro {t}"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_noise_reduction_grab_equals_the_reader(gl_engine, ffmpeg_ok, tmp_path):
    rng = np.random.default_rng(2)
    frames = np.stack([_to8(_gradient() + rng.normal(0.0, 0.02, (H, W, 3))) for _ in range(10)])
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "leitor.mkv", frames))
    _set(seq, c, ruido_temporal=0.7)
    rec = Recipe.for_source(None, seq.fps, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
    reader = sequence.SequenceReader(seq, W, H, 8)
    try:
        for t in range(seq.duration):
            fl = reader.read()
            ref = sequence.grab(seq, t, W, H, 8)
            assert [k for k, _i in fl.layers[0].neighbors] == [k for k, _i in ref.layers[0].neighbors]
            assert np.array_equal(rec.render(gl_engine, fl, t), rec.render(gl_engine, ref, t)), f"quadro {t}"
        assert reader.error == ""
    finally:
        reader.close()


# ------------------------------------------------------------------ mistura de quadros na GPU
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_half_speed_blend_matches_numpy_and_one_x_is_bit_exact(gl_engine, ffmpeg_ok, tmp_path):
    frames = np.zeros((12, H, W, 3), np.uint8)
    for k in range(12):
        frames[k] = _to8(_gradient(0.7 + 0.03 * k))
        frames[k, :, 4 + 4 * k:10 + 4 * k] = 210
    path = _video(ffmpeg_ok, tmp_path / "lento.mkv", frames)
    seq, c = _seq(path)
    plain = [_compose(gl_engine, seq, t) for t in range(6)]
    _set(seq, c, mistura_quadros=True)
    assert all(np.array_equal(plain[t], _compose(gl_engine, seq, t)) for t in range(6)), "1×: bit a bit"
    seq.set_speed(c.id, 0.5)
    _set(seq, c, mistura_quadros=False)
    held = _compose(gl_engine, seq, 3)
    _set(seq, c, mistura_quadros=True)
    rec = Recipe.for_source(None, seq.fps, 16, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
    fl = sequence.grab(seq, 3, W, H, 16)
    assert fl.layers[0].stack is not None and fl.layers[0].stack[1] == (0.5, 0.5)
    mixed = rec._blend_layers(gl_engine, fl).layers[0].image.astype(np.float64)
    seen = [sequence.grab(seq, t, W, H, 16).layers[0].image / 65535.0 for t in (2, 4)]  # quadros 1 e 2 do arquivo
    ref_lin = 0.5 * _dec(seen[0]) + 0.5 * _dec(seen[1])
    assert np.allclose(_dec(mixed), ref_lin, rtol=2e-3, atol=1e-6)
    out = _compose(gl_engine, seq, 3)
    assert not np.array_equal(out, held)
    assert np.allclose(_dec(out / 65535.0), ref_lin, rtol=4e-3, atol=1e-5)
    on_frame = _compose(gl_engine, seq, 4)  # u = 2: o quadro 2 do arquivo, sem mistura
    _set(seq, c, mistura_quadros=False)
    assert np.array_equal(on_frame, _compose(gl_engine, seq, 4))


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_blend_grab_equals_the_reader_in_reverse(gl_engine, ffmpeg_ok, tmp_path):
    frames = np.stack([_to8(_gradient(0.6 + 0.04 * k)) for k in range(10)])
    seq, c = _seq(_video(ffmpeg_ok, tmp_path / "reverso.mkv", frames))
    seq.set_speed(c.id, 0.5)
    _set(seq, c, mistura_quadros=True)
    seq.retime(c.id, reverse=True)
    rec = Recipe.for_source(None, seq.fps, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
    reader = sequence.SequenceReader(seq, W, H, 8)
    try:
        for t in range(seq.duration):
            fl = reader.read()
            ref = sequence.grab(seq, t, W, H, 8)
            assert (fl.layers[0].stack is None) == (ref.layers[0].stack is None) == (seq.frame_window(c, t) is None)
            assert np.array_equal(rec.render(gl_engine, fl, t), rec.render(gl_engine, ref, t)), f"quadro {t}"
        assert reader.error == ""
    finally:
        reader.close()


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_nested_twin_with_the_time_effects_is_bit_exact(gl_engine, ffmpeg_ok, tmp_path):
    """O clipe com deflicker, ruído temporal e mistura dentro de uma sequência = o mesmo clipe sem aninhar."""
    rng = np.random.default_rng(4)
    frames, _g = _flicker_frames(n=16)
    frames = np.clip(frames.astype(np.int64) + rng.integers(-4, 5, frames.shape), 0, 255).astype(np.uint8)
    flat, c = _analysed(ffmpeg_ok, _video(ffmpeg_ok, tmp_path / "gemea.mkv", frames))
    flat.set_speed(c.id, 0.5)
    _set(flat, c, deflicker=1.0, ruido_temporal=0.8, mistura_quadros=True)
    outer = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.9, 0.0, 0.0))
    inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
    outer.ensure_set().add(inner)
    outer.siblings.sync()
    outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=0)
    assert inner.sources[c.src].analysis.get(ti.DEFLICKER)
    _set(flat, c, deflicker=0.0, ruido_temporal=0.0, mistura_quadros=False)
    plain = _compose(gl_engine, flat, 9)
    _set(flat, c, deflicker=1.0, ruido_temporal=0.8, mistura_quadros=True)
    assert not np.array_equal(plain, _compose(gl_engine, flat, 9))
    for t in (1, 4, 9):
        for depth in (8, 16):
            a = _compose(gl_engine, flat, t, depth)
            b = _compose(gl_engine, outer, t, depth)
            assert np.array_equal(a, b), f"quadro {t}, {depth} bits"
