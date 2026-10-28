"""Rampa de velocidade, reverso e congelar um quadro com o ffmpeg de verdade: os quadros que a leitura em sequência
(a exportação) entrega são os que `Sequence.src_frame` prevê, e o som segue a imagem."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from pelicula import audiomix, media, sequence, timemap
from pelicula import timeline as tl

R = 48000


def _wav24(path):
    with wave.open(str(path), "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    d = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    s = d[:, 0].astype(np.int32) | (d[:, 1].astype(np.int32) << 8) | (d[:, 2].astype(np.int32) << 16)
    s = np.where(s >= 1 << 23, s - (1 << 24), s) / float(1 << 23)
    return s.reshape(-1, ch)[:, 0]


def _write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(R)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def _bursts(path, seconds=6.0, every=0.25):
    """Estalos de 20 ms (1 kHz) a cada `every` s: o relógio do som."""
    x = np.zeros(int(R * seconds), np.float32)
    tt = np.arange(int(0.02 * R)) / R
    times = np.arange(every, seconds - 0.1, every)
    for c in times:
        i = int(round(c * R))
        x[i:i + len(tt)] = 0.8 * np.sin(2 * np.pi * 1000 * tt)
    return _write_wav(path, x), times


def _read_all(seq, w, h):
    reader = sequence.SequenceReader(seq, w, h, 8)
    got = []
    try:
        while True:
            fl = reader.read()
            if fl is None:
                break
            got.append(fl)
    finally:
        reader.close()
    return got


def _file_frames(path, w, h):
    info = media.probe(path)
    r = media.FrameReader(info, w, h, 8)
    out = []
    try:
        while True:
            img = r.read()
            if img is None:
                break
            out.append(img)
    finally:
        r.close()
    return out


# ------------------------------------------------------------------ rampa
@pytest.mark.ffmpeg
def test_ramp_frames_from_the_reader_are_the_predicted_ones(ffmpeg_ok, sample_video):
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    assert seq.retime(v.id, ramp=timemap.preset_anchors("impacto", 0.0, src.length, amount=0.8, ramp_s=0.2))
    w, h = 160, 90
    every = _file_frames(sample_video, w, h)
    sequence.clear_cache()
    got = _read_all(seq, w, h)
    assert [f.frame for f in got] == list(range(seq.duration))
    want = [seq.src_frame(v, t) for t in range(v.start, v.end)]
    steps = [b - a for a, b in zip(want, want[1:])]
    assert any(d > 1 for d in steps) and any(d == 0 for d in steps), "acelera (pula quadros) e desacelera (repete)"
    for fl, k in zip(got, want):
        (li,) = fl.layers
        assert li.layer.src_frame == k
        assert np.array_equal(li.image, every[k]), f"quadro {fl.frame}"
        ref = sequence.grab(seq, fl.frame, w, h, 8).layers[0]
        assert np.array_equal(ref.image, li.image), "a prévia (acesso direto) vê o mesmo quadro"


@pytest.mark.ffmpeg
@pytest.mark.parametrize("preset,amount,ramp_s", [("desacelerar", 0.5, 2.0), ("impacto", 1.0, 0.5)])
def test_ramp_sound_follows_the_picture(ffmpeg_ok, tmp_path, preset, amount, ramp_s):
    path, clicks = _bursts(tmp_path / "estalos.wav")
    src = media.probe_source(path)
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    clip, = seq.insert_media(src, at=0)
    assert clip.kind == tl.AUDIO
    ramp = timemap.preset_anchors(preset, 0.0, src.length, amount=amount, ramp_s=ramp_s)
    assert seq.retime(clip.id, ramp=ramp)
    out = tmp_path / "mix.wav"
    assert audiomix.render_mix(seq, str(out))
    y = _wav24(out)
    assert len(y) == pytest.approx(seq.duration / seq.fps * R, abs=R / seq.fps)
    m = seq.time_map(clip)
    end = clip.dur / seq.fps
    outs = [m.out_at(c) for c in clicks]
    # Só os estalos com folga dos vizinhos na saída (a 4× eles se juntam e o atempo pode engolir um ou outro).
    keep = [i for i, o in enumerate(outs) if o < end - 0.2 and (i == 0 or o - outs[i - 1] > 0.2)
            and (i == len(outs) - 1 or outs[i + 1] - o > 0.2)]
    assert len(keep) >= 5
    expect = np.array([m.out_at(clicks[i] + 0.01) for i in keep])  # o centro de cada estalo
    err, peaks = [], []
    for e in expect:
        a, b = int((e - 0.1) * R), int((e + 0.1) * R)
        en = y[a:b] ** 2
        assert en.sum() > 0, f"o estalo de {e:.3f} s sumiu"
        err.append((a + (np.arange(len(en)) * en).sum() / en.sum()) / R - e)
        peaks.append(np.abs(y[a:b]).max())
    err = np.array(err)
    assert np.abs(err).max() < 1 / 24, f"cada estalo no quadro dele (erro máximo {np.abs(err).max() * 1000:.1f} ms)"
    assert err.max() - err.min() < 0.03, "sem atraso acumulado ao longo da rampa"
    assert min(peaks) > 0.85 * max(peaks), f"o volume fica o mesmo ao longo da rampa: {peaks}"
