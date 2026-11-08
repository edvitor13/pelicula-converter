"""Batidas da música (`batidas.py`, 1.8, ARQUITETURA §46.1): andamento, batidas e compassos em trilhas de clique
sintéticas (limpas, com ruído e com o tempo humano), mudança de andamento, determinismo e o cache pelo carimbo do
arquivo."""

from __future__ import annotations

import os
import wave

import numpy as np
import pytest

from pelicula import batidas, somlimpo

R = batidas.RATE


def click_track(bpm: float, secs: float = 24.0, noise: float = 0.0, jitter: float = 0.0, accent: bool = True,
                start: float = 0.5, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Cliques (rajadas de ruído de 5 ms) a `bpm`, o primeiro de cada 4 mais forte; `noise` = ruído branco com esta
    fração da amplitude dos cliques; `jitter` = deslocamento aleatório de até esta fração do período (tocado à mão)."""
    rng = np.random.default_rng(seed)
    n = int(secs * R)
    x = np.zeros(n, np.float32)
    k = np.arange(int(0.03 * R))
    burst = (np.exp(-k / (0.005 * R)) * rng.standard_normal(len(k))).astype(np.float32)
    per = 60.0 / bpm
    times, i, t = [], 0, start
    while t < secs - 0.1:
        tt = t + (rng.uniform(-jitter, jitter) * per if jitter else 0.0)
        s = int(round(tt * R))
        x[s:s + len(burst)] += (0.8 if accent and i % 4 == 0 else 0.4) * burst[:n - s]
        times.append(tt)
        t += per
        i += 1
    if noise:
        x += (noise * 0.4 * rng.standard_normal(n)).astype(np.float32)
    return x, np.array(times)


def nearest(a: np.ndarray, b) -> np.ndarray:
    """Distância de cada valor de `b` ao mais próximo de `a`."""
    return np.array([np.min(np.abs(a - v)) for v in b])


@pytest.mark.parametrize("bpm", [90, 120, 150])
def test_clean_click_tracks(bpm):
    x, clicks = click_track(bpm)
    b = batidas.analyze(x)
    assert abs(b.bpm - bpm) / bpm < 0.01, b.bpm
    assert b.confident and b.confidence > 0.9
    assert nearest(clicks, b.times).max() < 0.015       # toda batida num clique
    assert nearest(np.array(b.times), clicks).max() < 0.015   # todo clique tem a batida
    assert any(abs(c - bpm / 2) < 1 for c in b.candidates) and any(abs(c - bpm * 2) < 2 for c in b.candidates)
    assert abs(b.downbeats[0] - clicks[0]) < 0.015      # o clique forte abre o compasso
    assert np.allclose(np.diff(b.downbeats), 4 * 60.0 / bpm, atol=0.015)


@pytest.mark.parametrize("bpm", [90, 120, 150])
def test_noisy_and_hand_played_click_tracks(bpm):
    x, clicks = click_track(bpm, noise=0.3, seed=bpm)
    b = batidas.analyze(x)
    assert abs(b.bpm - bpm) / bpm < 0.01, b.bpm
    assert b.confident
    found = nearest(np.array(b.times), clicks)
    assert np.mean(found < 0.015) >= 0.95
    inner = [t for t in b.times if clicks[0] - 0.1 < t < clicks[-1] + 0.1]   # uma batida a mais numa ponta é ruído
    assert nearest(clicks, inner).max() < 0.015
    x, clicks = click_track(bpm, jitter=0.03, seed=bpm + 1)
    b = batidas.analyze(x)
    assert abs(b.bpm - bpm) / bpm < 0.01, b.bpm
    assert nearest(clicks, b.times).max() < 0.015     # as batidas vão até o clique de verdade, não à grade


def test_tempo_change_and_noise_are_not_confident():
    a, _ = click_track(100, secs=20.0)
    c, _ = click_track(140, secs=20.0, start=0.3)
    b = batidas.analyze(np.concatenate([a, c]))
    assert not b.confident and b.confidence < batidas.CONFIDENT, b.confidence
    rng = np.random.default_rng(2)
    b = batidas.analyze((0.2 * rng.standard_normal(R * 20)).astype(np.float32))
    assert not b.confident
    assert not batidas.analyze(np.zeros(R * 10, np.float32)).confident


def test_deterministic_and_json_round_trip():
    x, _ = click_track(128, noise=0.1)
    a, b = batidas.analyze(x), batidas.analyze(x.copy())
    assert a == b
    again = batidas.Beats.from_json(a.to_json())
    assert np.allclose(again.times, a.times, atol=1e-6) and abs(again.bpm - a.bpm) < 1e-6
    assert np.allclose(again.downbeats, a.downbeats, atol=1e-6) and again.confident == a.confident


def write_wav(path: str, x: np.ndarray, rate: int = 44100) -> None:
    src = np.arange(int(len(x) * rate / R)) * R / rate
    y = np.interp(src, np.arange(len(x)), x)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        pcm = (np.clip(y, -1, 1) * 32000).astype("<i2")
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


@pytest.mark.ffmpeg
def test_file_analysis_is_cached_by_the_file_stamp(ffmpeg_ok, tmp_path, monkeypatch):
    path = str(tmp_path / "musica.wav")
    x, clicks = click_track(120, secs=12.0)
    write_wav(path, x)
    assert batidas.cached(path) is None
    b = batidas.analyze_file(path)
    assert abs(b.bpm - 120) < 1.2 and b.confident
    assert nearest(clicks, b.times).max() < 0.015
    assert any(p.suffix == ".json" for p in batidas.cache_dir().iterdir())

    def boom(*_a, **_k):
        raise AssertionError("decodificou de novo")

    monkeypatch.setattr(somlimpo, "read_range", boom)
    assert batidas.analyze_file(path) == b          # da memória
    batidas._MEM.clear()
    assert batidas.cached(path) == batidas.Beats.from_json(b.to_json())   # do disco
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 10))  # o arquivo mudou: o resultado de antes não vale
    assert batidas.cached(path) is None
    monkeypatch.undo()
    with pytest.raises(batidas.BeatError):
        batidas.analyze_file(str(tmp_path / "nao_existe.wav"))


@pytest.mark.ffmpeg
def test_cancel(ffmpeg_ok, tmp_path):
    import threading

    from pelicula import jobs
    path = str(tmp_path / "musica.wav")
    write_wav(path, click_track(120, secs=6.0)[0])
    ev = threading.Event()
    ev.set()
    with pytest.raises(jobs.Cancelled):
        batidas.analyze_file(path, cancel=ev)
    assert batidas.cached(path) is None
