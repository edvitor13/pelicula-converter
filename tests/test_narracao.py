"""Gravar narração sem Qt nem dispositivo (1.8, #39, ARQUITETURA §48): o gravador recebe blocos sintéticos e grava o WAV de
48 kHz em 24 bits. Conferido: conteúdo e tamanho exatos, 44,1 → 48 kHz, mono/estéreo, formatos de amostra, blocos
cortados no meio de um quadro, atraso do microfone, duração máxima, cancelar sem deixar nada, a fila em segundo plano e
as contas de pasta, intervalo e faixa."""

from __future__ import annotations

import os
import threading

import numpy as np
import pytest

from pelicula import narracao, timeline as tl
from pelicula.audiomix import RATE, WavReader


def sine(n: int, rate: int, freq: float = 1000.0, amp: float = 0.5, phase: float = 0.0) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(n) / rate + phase)).astype(np.float64)


def pcm16(x: np.ndarray, channels: int = 1) -> bytes:
    """Mono repetido (ou 2 canais iguais) em inteiros de 16 bits intercalados."""
    v = np.rint(np.asarray(x) * 32767.0).astype("<i2")
    return np.repeat(v[:, None], channels, axis=1).tobytes()


def read(path) -> np.ndarray:
    r = WavReader(str(path))
    assert r.rate == RATE
    return r.read(0, r.frames).astype(np.float64)


def record(tmp_path, data: bytes, rate: int, channels: int = 1, fmt: str = "int16", chunk: int | None = None, **kw):
    path = tmp_path / "gravacao.wav"
    rec = narracao.Recorder(str(path), rate, channels, fmt, **kw)
    if chunk is None:
        rec.feed(data)
    else:
        for i in range(0, len(data), chunk):
            rec.feed(data[i:i + chunk])
    return rec, path, rec.finish()


def test_48k_mono_is_centered_stereo_and_exact(tmp_path):
    x = sine(RATE, RATE)
    rec, path, take = record(tmp_path, pcm16(x), RATE)
    assert take is not None and take.frames == RATE and take.seconds == 1.0
    y = read(path)
    assert y.shape == (RATE, 2) and np.array_equal(y[:, 0], y[:, 1])
    assert np.max(np.abs(y[:, 0] - np.rint(x * 32767.0) / 32768.0)) < 2e-7   # 16 → 24 bits sem perda (±1 LSB de 24)
    assert not os.path.exists(rec.partial)


def test_stereo_is_kept_and_extra_channels_are_dropped(tmp_path):
    n = 4800
    left, right = sine(n, RATE, 440.0), sine(n, RATE, 880.0)
    inter = np.empty(n * 2, "<i2")
    inter[0::2], inter[1::2] = np.rint(left * 32767), np.rint(right * 32767)
    _rec, path, take = record(tmp_path, inter.tobytes(), RATE, channels=2)
    y = read(path)
    assert take.frames == n and np.max(np.abs(y[:, 0] - left)) < 1e-4 and np.max(np.abs(y[:, 1] - right)) < 1e-4
    quad = np.zeros((n, 4), "<i2")
    quad[:, 0], quad[:, 1], quad[:, 2], quad[:, 3] = inter[0::2], inter[1::2], 9999, 9999
    _rec, path, take = record(tmp_path, quad.tobytes(), RATE, channels=4)
    z = read(path)
    assert np.allclose(z, y, atol=1e-7)


@pytest.mark.parametrize("fmt", ["uint8", "int16", "int32", "float32"])
def test_sample_formats(tmp_path, fmt):
    x = sine(2400, RATE, 500.0, 0.4)
    dtype = {"uint8": None, "int16": "<i2", "int32": "<i4", "float32": "<f4"}[fmt]
    if fmt == "uint8":
        data = np.clip(np.rint(x * 128 + 128), 0, 255).astype(np.uint8).tobytes()
        tol = 1 / 128
    elif fmt == "float32":
        data, tol = x.astype(dtype).tobytes(), 1e-6
    else:
        data, tol = np.rint(x * (2 ** (8 * np.dtype(dtype).itemsize - 1) - 1)).astype(dtype).tobytes(), 1e-4
    _rec, path, take = record(tmp_path, data, RATE, fmt=fmt)
    y = read(path)
    assert take.frames == 2400 and np.max(np.abs(y[:, 0] - x)) < tol


def test_44k1_to_48k_is_accurate_and_the_length_exact(tmp_path):
    n = 44100
    x = sine(n, 44100, 1000.0, 0.5)
    _rec, path, take = record(tmp_path, pcm16(x), 44100)
    assert take.frames == 48000
    y = read(path)[:, 0]
    ideal = sine(48000, 48000, 1000.0, 0.5)
    edge = narracao.HALF_TAPS * 2     # o começo e o fim sentem o silêncio de fora
    err = y[edge:-edge] - ideal[edge:-edge]
    assert np.max(np.abs(err)) < 1e-3                                     # < −60 dB do tom (pico 0,5): sem fase nem ganho errados
    assert 20 * np.log10(np.sqrt(np.mean(err ** 2)) / (0.5 / np.sqrt(2))) < -70
    assert np.abs(np.abs(y).max() - 0.5) < 1e-3                           # ganho 1


def test_resampling_does_not_depend_on_how_the_blocks_arrive(tmp_path):
    x = sine(30001, 44100, 700.0, 0.4) + sine(30001, 44100, 5200.0, 0.2)
    data = pcm16(x)
    _r, whole, a = record(tmp_path, data, 44100)
    first = read(whole)
    for chunk in (3001, 8192 * 2 + 1, 441 * 2):    # inclusive cortando um quadro de 16 bits no meio
        _r2, p2, b = record(tmp_path, data, 44100, chunk=chunk)
        assert b.frames == a.frames and np.max(np.abs(read(p2) - first)) <= 2 ** -22


@pytest.mark.parametrize("rate, frames", [(8000, 8000 // 2), (16000, 16000), (22050, 22050), (32000, 32000), (96000, 96000),
                                          (11025, 11025)])
def test_other_rates_keep_the_duration(tmp_path, rate, frames):
    _rec, path, take = record(tmp_path, pcm16(sine(frames, rate, 300.0)), rate)
    assert take.frames == int(np.floor(frames * RATE / rate + 0.5))
    y = read(path)[:, 0]
    mid = y[200:-200]
    assert np.max(np.abs(mid - sine(take.frames, RATE, 300.0)[200:-200])) < 2e-3


def test_downsampling_removes_what_is_above_the_new_nyquist(tmp_path):
    # 96 kHz com um tom de 40 kHz: acima do Nyquist de 48 kHz (24 kHz), não pode virar um tom "dobrado" de 8 kHz
    x = sine(96000, 96000, 40000.0, 0.5) + sine(96000, 96000, 2000.0, 0.25)
    _rec, path, _take = record(tmp_path, pcm16(x), 96000)
    y = read(path)[100:-100, 0]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / len(y) * 4
    bins = np.fft.rfftfreq(len(y), 1 / RATE)
    wanted = spec[np.argmin(np.abs(bins - 2000.0))]
    alias = spec[np.argmin(np.abs(bins - 8000.0))]
    assert wanted > 0.2 and alias < wanted * 10 ** (-60 / 20)


def test_levels_and_the_silent_microphone(tmp_path):
    path = tmp_path / "n.wav"
    rec = narracao.Recorder(str(path), RATE, 1, "int16")
    lv = rec.feed(pcm16(np.full(4800, 0.5)))
    assert lv.peak == pytest.approx(0.5, abs=1e-3) and lv.rms == pytest.approx(0.5, abs=1e-3)
    assert lv.peak_db == pytest.approx(-6.0, abs=0.05)
    assert narracao.db(0.0) == -120.0
    assert rec.silent_run == 0
    rec.feed(pcm16(np.zeros(2400)))
    rec.feed(pcm16(np.zeros(2400)))
    assert rec.silent_run == 4800 and rec.level.peak == 0.0
    rec.feed(pcm16(np.full(10, 0.1)))
    assert rec.silent_run == 0 and rec.peak == pytest.approx(0.5, abs=1e-3)
    rec.cancel()


def test_microphone_delay_drops_the_start_to_the_sample(tmp_path):
    x = sine(RATE, RATE, 300.0, 0.5)
    _r, path, take = record(tmp_path, pcm16(x), RATE, skip_s=0.1)
    skip = int(round(0.1 * RATE))
    assert take.frames == RATE - skip
    assert np.max(np.abs(read(path)[:, 0] - x[skip:])) < 1e-4
    rec = narracao.Recorder(str(tmp_path / "vazia.wav"), RATE, 1, "int16", skip_s=1.0)   # mais atraso que gravação
    rec.feed(pcm16(x[:3000]))
    assert rec.finish() is None
    assert not (tmp_path / "vazia.wav").exists() and not os.path.exists(system_partial(tmp_path / "vazia.wav"))


def system_partial(path) -> str:
    from pelicula import system
    return system.partial_path(str(path))


def test_the_maximum_duration_cuts_exactly_and_flags_full(tmp_path):
    x = sine(RATE * 2, RATE)
    path = tmp_path / "m.wav"
    rec = narracao.Recorder(str(path), RATE, 1, "int16", max_s=0.5)
    rec.feed(pcm16(x[:10000]))
    assert not rec.full and rec.frames == 10000
    rec.feed(pcm16(x[10000:40000]))
    assert rec.full and rec.frames == 24000
    rec.feed(pcm16(x[40000:]))                        # depois de cheio, o resto é ignorado
    take = rec.finish()
    assert take.frames == 24000 and read(path).shape[0] == 24000


def test_cancel_leaves_nothing_and_nothing_is_written_after(tmp_path):
    path = tmp_path / "c.wav"
    rec = narracao.Recorder(str(path), 44100, 1, "int16")
    rec.feed(pcm16(sine(44100, 44100)))
    assert os.path.exists(rec.partial)                # durante a gravação só existe o parcial
    assert not path.exists()
    rec.cancel()
    assert list(tmp_path.iterdir()) == []
    rec.feed(pcm16(sine(100, 44100)))                  # depois de fechar, ignora
    assert rec.finish() is None and list(tmp_path.iterdir()) == []


def test_an_empty_recording_leaves_nothing(tmp_path):
    path = tmp_path / "v.wav"
    rec = narracao.Recorder(str(path), RATE, 1, "int16")
    assert rec.finish() is None and list(tmp_path.iterdir()) == []


def test_the_folder_is_created_and_an_existing_take_is_never_overwritten(tmp_path):
    folder = tmp_path / "sub" / "pasta"
    first = narracao.next_take_path(folder)
    assert first.name == "narracao_001.wav"
    rec = narracao.Recorder(str(first), RATE, 1, "int16")
    rec.feed(pcm16(sine(480, RATE)))
    rec.finish()
    (folder / "narracao_007.WAV").write_bytes(b"x")
    (folder / "outra.wav").write_bytes(b"x")
    assert narracao.next_take_path(folder).name == "narracao_008.wav"


def test_background_recorder_matches_the_direct_one(tmp_path):
    x = sine(44100, 44100, 600.0, 0.4)
    data = pcm16(x)
    _r, direct, a = record(tmp_path, data, 44100)
    path = tmp_path / "bg.wav"
    bg = narracao.BackgroundRecorder(str(path), 44100, 1, "int16")
    for i in range(0, len(data), 3000):
        bg.feed(data[i:i + 3000])
    take = bg.finish()
    assert take.frames == a.frames and np.array_equal(read(path), read(direct))
    assert not any(t.name == "narracao" and t.is_alive() for t in threading.enumerate())
    assert bg.level.peak > 0.0


def test_background_recorder_cancel_and_write_error(tmp_path):
    path = tmp_path / "bc.wav"
    bg = narracao.BackgroundRecorder(str(path), RATE, 1, "int16")
    bg.feed(pcm16(sine(4800, RATE)))
    bg.cancel()
    assert list(tmp_path.iterdir()) == []
    path2 = tmp_path / "be.wav"
    bg = narracao.BackgroundRecorder(str(path2), RATE, 1, "int16")

    def boom(_data):
        raise OSError("disco cheio")
    bg.rec.feed = boom
    bg.feed(b"\0\0" * 100)
    with pytest.raises(OSError, match="disco cheio"):
        bg.finish()
    assert list(tmp_path.iterdir()) == []


def test_take_folder_next_to_the_project_or_in_the_app_data(tmp_path, monkeypatch):
    folder, beside = narracao.take_folder(str(tmp_path / "filme.plc"))
    assert beside and folder == tmp_path / "filme_narracao"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    folder, beside = narracao.take_folder(None)
    assert not beside and folder.name == "narracao" and str(tmp_path / "local") in str(folder)


def test_span_starts_at_in_or_at_the_playhead_and_stops_at_out():
    assert narracao.plan_span(100, None, None, 25.0) == (100, None)
    assert narracao.plan_span(100, 40, None, 25.0) == (40, None)
    assert narracao.plan_span(100, 40, 90, 25.0) == (40, 2.0)
    assert narracao.plan_span(100, None, 150, 25.0) == (100, 2.0)
    assert narracao.plan_span(100, None, 50, 25.0) == (100, None)    # saída antes do começo: ignorada
    assert narracao.plan_span(-5, None, None, 25.0) == (0, None)


def make_seq() -> tl.Sequence:
    seq = tl.Sequence(320, 180, "25/1")
    seq.insert_media(tl.Source.virtual("cor", 320, 180, "25/1", data={"cor": "#336699"}))
    return seq


def audio_src(seconds: float = 2.0, name: str = "n") -> tl.Source:
    return tl.Source(path=f"/x/{name}.wav", width=0, height=0, fps=24.0, fps_str="24/1", frames=1, duration=seconds,
                     is_image=False, has_video=False, has_audio=True, codec="")


def test_track_choice_prefers_the_narration_track_then_a_free_one_then_a_new_one():
    seq = make_seq()
    src = audio_src()                                              # 2 s = 50 quadros
    assert len(seq.kind_tracks(tl.AUDIO)) <= 1
    track, new = narracao.place_take(seq, src, 0)                  # a montagem só tem imagem: A1 está livre
    assert (track, new) == (0, False) and len(seq.kind_tracks(tl.AUDIO)) == 1
    seq.insert_media(audio_src(10.0, "musica"), at=0)              # a música ocupa A1 de 0 a 250
    track, new = narracao.place_take(seq, src, 100)
    assert (track, new) == (1, True)
    assert seq.track(tl.AUDIO, 1).name == narracao.track_name() == "Narração"
    seq.insert_media(src, at=100, atrack=1)
    assert narracao.place_take(seq, src, 300) == (1, False)        # a "Narração" livre tem a preferência
    seq.track(tl.AUDIO, 1).locked = True
    assert narracao.place_take(seq, src, 300) == (0, False)        # travada: a primeira livre depois da música
    seq.track(tl.AUDIO, 1).locked = False
    seq.track(tl.AUDIO, 1).name = "A2"
    assert narracao.place_take(seq, src, 300) == (0, False)        # sem nome de narração, a primeira livre
    assert narracao.place_take(seq, src, 90) == (2, True)          # as duas ocupadas em 90–140
    assert [t.name for t in seq.kind_tracks(tl.AUDIO)][-1] == "Narração"
