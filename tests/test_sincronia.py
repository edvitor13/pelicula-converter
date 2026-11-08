"""Sincronizar pelo som (`sincronia.py`, 1.8, ARQUITETURA §44.5): o atraso pela correlação, a confiança, a referência
e o plano com arquivos de verdade."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from pelicula import sincronia
from pelicula import timeline as tl

R = sincronia.RATE


def bursts(secs, seed, rate=R) -> np.ndarray:
    """Rajadas de ruído de 30 a 120 ms em instantes aleatórios: um som que só bate com ele mesmo."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(secs * rate))
    for t in rng.uniform(0, secs - 0.15, int(secs * 6)):
        n = int(rng.uniform(0.03, 0.12) * rate)
        i = int(t * rate)
        x[i:i + n] += rng.standard_normal(n) * rng.uniform(0.1, 0.5)
    return x


def test_lag_found_within_a_millisecond():
    src = bursts(6.0, 1)
    a = src[int(2.0 * R):int(4.0 * R)]                  # 2 s da referência
    b = src[int(2.0 * R) - int(1.23 * R):int(5.0 * R)]  # o outro começa 1,23 s antes: a[i] = b[i + 1,23 s]
    lag = sincronia.find_lag(a, b, 0, int(3 * R))
    assert lag.ok and abs(lag.samples / R - 1.23) < 0.001, lag
    rng = np.random.default_rng(9)
    noisy = 0.5 * b + rng.standard_normal(len(b)) * 0.05   # −6 dB e ruído por cima
    lag = sincronia.find_lag(a, noisy, 0, int(3 * R))
    assert lag.ok and abs(lag.samples / R - 1.23) < 0.001, lag
    flipped = sincronia.find_lag(a, -b, 0, int(3 * R))     # polaridade invertida também serve
    assert flipped.ok and abs(flipped.samples / R - 1.23) < 0.001


def test_fractional_lag_and_negative_range():
    fine = np.convolve(bursts(4.0, 2, rate=8 * R), np.ones(32) / 32, "same")   # até ~2 kHz, amostrado 8× mais fino
    a = fine[0::8][R:3 * R]                  # a[i] = som em 8·(R + i)
    b = fine[4::8]                           # b[k] = som em 8·k + 4: meia amostra de diferença
    lag = sincronia.find_lag(a, b, -R, 2 * R)
    assert lag.ok and abs(lag.samples - (R - 0.5)) < 0.2, lag
    late = sincronia.find_lag(a, fine[4::8][2 * R:4 * R], -2 * R, R)   # b começa depois: atraso negativo
    assert late.ok and abs(late.samples - (-R - 0.5)) < 0.2, late


def test_unrelated_sound_is_refused():
    a = bursts(2.0, 3)
    b = bursts(4.0, 4)
    lag = sincronia.find_lag(a, b, 0, int(2 * R))
    assert not lag.ok, lag
    assert not sincronia.find_lag(np.zeros(R), b, 0, R).ok   # silêncio
    t = np.arange(4 * R) / R
    beat = (np.sin(2 * np.pi * 2 * t) > 0.99) * np.sin(2 * np.pi * 800 * t)   # ritmo repetido: ambíguo
    assert not sincronia.find_lag(beat[:2 * R], beat, 0, 2 * R).ok


# ------------------------------------------------------------------ na montagem
def src(path, secs=3.0, video=False) -> tl.Source:
    return tl.Source(path, 640, 360, 24.0, "24/1", int(secs * 24), secs, has_video=video, has_audio=True)


def test_candidates_and_reference():
    seq = tl.Sequence(640, 360, "24/1")
    cam2 = seq.insert_media(src("C:/v/cam2.mp4", video=True), at=0, vtrack=0, atrack=0)
    cam1 = seq.insert_media(src("C:/v/cam1.mp4", video=True), at=200, vtrack=0, atrack=0)
    rec = seq.insert_media(src("C:/v/gravador.wav"), at=0, atrack=1)
    seq.add_track(tl.VIDEO)
    for c in cam2:   # a câmera 2 sobe para a V2
        if c.kind == tl.VIDEO:
            c.track = 1
    ids = [c.id for c in rec + cam2 + cam1]
    clips = sincronia.candidates(seq, ids)
    assert [c.kind for c in clips] == [tl.AUDIO] * 3 and len({c.id for c in clips}) == 3
    ref = sincronia.reference_of(seq, clips)
    assert ref.link == next(c.link for c in cam1)   # o som ligado ao vídeo da V1
    only_audio = sincronia.candidates(seq, [rec[0].id])
    assert sincronia.reference_of(seq, only_audio) is only_audio[0]


def write_mono(path, x, rate=48000) -> str:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


@pytest.mark.ffmpeg
def test_plan_with_real_files(ffmpeg_ok, tmp_path):
    full = bursts(4.3, 5, rate=48000)
    a = write_mono(tmp_path / "camera.wav", full[int(1.23 * 48000):int(4.23 * 48000)])   # 3 s
    b = write_mono(tmp_path / "gravador.wav", full[:3 * 48000])                         # começou 1,23 s antes
    other = write_mono(tmp_path / "outro.wav", bursts(3.0, 6, rate=48000))
    seq = tl.Sequence(640, 360, "24/1")
    ca = seq.insert_media(src(a), at=48, atrack=0)[0]
    cb = seq.insert_media(src(b), at=48, atrack=1)[0]
    co = seq.insert_media(src(other), at=48, atrack=2)[0]
    p = sincronia.plan(seq, [ca.id, cb.id, co.id])
    assert p.reference == ca.id
    (mv,) = p.moves
    # o gravador anda 1,23 s para trás: 29,52 quadros → 30, sobra de +0,02 s
    assert mv.clip == cb.id and mv.frames == -30 and mv.residue == pytest.approx(0.02, abs=0.001)
    assert p.refused == [(co.id, p.refused[0][1])]
    seq.set_speed(cb.id, 2.0)
    p = sincronia.plan(seq, [ca.id, cb.id])
    assert not p.moves and p.refused[0][0] == cb.id
