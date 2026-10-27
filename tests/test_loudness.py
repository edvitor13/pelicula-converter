"""Loudness (ITU-R BS.1770-4 / EBU R128) e picos: casos da EBU Tech 3341/3342 e o ebur128 do ffmpeg."""

from __future__ import annotations

import math
import re
import struct
import subprocess

import numpy as np
import pytest

from pelicula import loudness as L

RATE = 48000


def tone(dbfs, secs, freq=1000.0, rate=RATE, channels=2, phase=0.0) -> np.ndarray:
    t = np.arange(int(round(secs * rate))) / rate
    x = 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t + phase)
    return np.repeat(x[:, None], channels, axis=1)


def silence(secs, rate=RATE, channels=2) -> np.ndarray:
    return np.zeros((int(round(secs * rate)), channels))


def write_wav_f32(path, x: np.ndarray, rate: int) -> None:
    data = np.asarray(x, dtype="<f4").tobytes()
    ch = x.shape[1]
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        fh.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, ch, rate, rate * 4 * ch, 4 * ch, 32))
        fh.write(b"data" + struct.pack("<I", len(data)) + data)


# ------------------------------------------------------------------ ponderação K
def test_k_weighting_coefficients_and_response():
    # o protótipo analógico em 48 kHz reproduz a tabela da norma
    for (b, a), (bt, at) in zip(L.k_weighting_analog(48000), L.K_48K):
        assert np.allclose(b, bt, atol=1e-9) and np.allclose(a, at, atol=1e-9)
    assert L.k_weighting(48000) is L.K_48K
    assert abs(L.k_response_db(48000, 997) - 0.691) < 0.01  # o −0,691 da fórmula compensa isso
    assert L.k_response_db(48000, 20) < -12 and 3.9 < L.k_response_db(48000, 10000) < 4.2
    for rate in (32000, 44100, 96000, 192000):
        assert abs(L.k_response_db(rate, 997) - 0.691) < 0.05, rate  # como no libebur128
    h = L.k_impulse(48000)
    assert 1000 < len(h) < 48000 and abs(h.sum()) < 1e-9  # passa-altas: nada de nível contínuo


# ------------------------------------------------------------------ EBU Tech 3341
@pytest.mark.parametrize("rate", [48000, 44100, 96000])
def test_stereo_sine_at_minus_23_reads_minus_23(rate):
    m = L.measure(tone(-23.0, 20, rate=rate), rate)
    for v in (m.integrated, m.momentary_max, m.short_term_max):
        assert abs(v + 23.0) <= 0.1, (rate, v)
    assert abs(m.sample_peak + 23.0) < 0.01


def test_stereo_sine_at_minus_20():
    m = L.measure(tone(-20.0, 10), RATE)
    assert abs(m.integrated + 20.0) <= 0.1 and abs(m.short_term_max + 20.0) <= 0.1


def test_silence_and_quiet_parts_are_gated():
    assert L.measure(silence(5), RATE).integrated is None
    meter = L.LoudnessMeter(RATE)
    meter.add(silence(1))
    assert meter.momentary() == -math.inf and meter.integrated() is None and meter.short_term() is None
    # Tech 3341, caso 4: os trechos em −72 e −36 dBFS ficam fora (portas absoluta e relativa)
    x = np.concatenate([tone(-72, 10), tone(-36, 10), tone(-23, 60), tone(-36, 10), tone(-72, 10)])
    assert abs(L.measure(x, RATE).integrated + 23.0) <= 0.1
    x = np.concatenate([tone(-23, 10), silence(10)])
    assert abs(L.measure(x, RATE).integrated + 23.0) <= 0.1


def test_momentary_and_short_term_windows():
    m = L.LoudnessMeter(RATE)
    m.add(tone(-23, 0.3))
    assert m.momentary() is None
    m.add(tone(-23, 0.1))
    assert abs(m.momentary() + 23) < 0.1 and m.short_term() is None
    m.add(tone(-23, 2.6))
    assert abs(m.short_term() + 23) < 0.1
    m.reset()
    assert m.momentary() is None and m.integrated() is None and m.true_peak_db() == -math.inf


def test_feeding_in_pieces_gives_the_same_result():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((RATE * 6, 2)) * 0.05
    whole = L.LoudnessMeter(RATE)
    whole.add(x)
    parts = L.LoudnessMeter(RATE)
    pos = 0
    while pos < len(x):
        n = int(rng.integers(1, 5000))
        parts.add(x[pos:pos + n])
        pos += n
    assert np.allclose(whole.subblocks, parts.subblocks, rtol=1e-9, atol=1e-15)
    assert abs(whole.integrated() - parts.integrated()) < 1e-9
    assert np.allclose(whole.true_peak, parts.true_peak) and np.allclose(whole.sample_peak, parts.sample_peak)


def test_mono_and_channel_weights():
    assert list(L.channel_weights(2)) == [1.0, 1.0]
    assert list(L.channel_weights(6)) == [1.0, 1.0, 1.0, 0.0, 1.41, 1.41]
    mono = L.measure(tone(-23, 5, channels=1), RATE).integrated
    assert abs(mono + 26.01) < 0.1  # metade da potência do estéreo
    with pytest.raises(ValueError):
        L.LoudnessMeter(RATE, 2).add(np.zeros((10, 3)))


# ------------------------------------------------------------------ true peak e LRA
def test_true_peak_finds_the_peak_between_samples():
    # seno em fs/4 com fase de 45°: as amostras ficam em 0,707 A e a onda passa por A entre elas
    x = tone(-6.0, 1, freq=RATE / 4, phase=math.pi / 4)
    ramp = np.clip(np.arange(len(x)) / (0.05 * RATE), 0, 1)[:, None]  # sem degrau no começo
    m = L.measure(x * (0.5 - 0.5 * np.cos(np.pi * ramp)), RATE)
    assert abs(m.sample_peak + 9.01) < 0.05
    assert abs(m.true_peak + 6.0) < 0.1
    assert (L.oversampling(48000), L.oversampling(96000), L.oversampling(192000)) == (4, 2, 1)


def test_loudness_range_tech3342_case_1():
    x = np.concatenate([tone(-20, 20), tone(-30, 20)])
    assert abs(L.measure(x, RATE).lra - 10.0) <= 1.0
    assert L.measure(tone(-20, 10), RATE).lra < 0.1


# ------------------------------------------------------------------ ffmpeg
def mixed_signal() -> np.ndarray:
    rng = np.random.default_rng(11)

    def noise(secs, dbfs):
        n = int(secs * RATE)
        w = rng.standard_normal((n + 63, 2))
        k = np.hanning(64)
        x = np.stack([np.convolve(w[:, c], k, mode="valid") for c in range(2)], axis=1)[:n]
        return x / np.sqrt(np.mean(x ** 2)) * 10 ** (dbfs / 20)

    left_heavy = tone(-25, 4, freq=220) * np.array([1.0, 0.5])
    return np.concatenate([noise(3, -20), left_heavy, silence(2), noise(5, -32), tone(-14, 3, freq=3000),
                           noise(4, -45), tone(-21, 3, freq=60), noise(3, -18)])


@pytest.mark.ffmpeg
def test_matches_ffmpeg_ebur128(ffmpeg_ok, tmp_path):
    x = mixed_signal()
    path = tmp_path / "mistura.wav"
    write_wav_f32(path, x, RATE)
    res = subprocess.run([ffmpeg_ok, "-nostats", "-hide_banner", "-nostdin", "-i", str(path),
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, timeout=120)
    text = res.stderr.decode("utf-8", "replace")
    summary = text[text.rfind("Summary:"):]
    assert res.returncode == 0 and summary, text[-2000:]
    ref_i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    ref_lra = float(re.search(r"LRA:\s+(-?[\d.]+) LU", summary).group(1))
    ref_tp = float(re.search(r"True peak:\s+Peak:\s+(-?[\d.]+)", summary).group(1))
    m = L.measure(x, RATE)
    assert abs(m.integrated - ref_i) <= 0.2, (m.integrated, ref_i)
    assert abs(m.lra - ref_lra) <= 1.0, (m.lra, ref_lra)
    assert abs(m.true_peak - ref_tp) <= 0.3, (m.true_peak, ref_tp)


# ------------------------------------------------------------------ som para o medidor (audiomix)
def write_wav(path, x: np.ndarray, rate: int, bits: int, flt: bool = False, extensible: bool = False,
              extra: bool = False) -> None:
    """WAV de teste em qualquer formato que o medidor lê (com um bloco a mais antes dos dados, se pedido)."""
    ch = x.shape[1]
    if flt:
        data = np.asarray(x, dtype="<f4").tobytes()
    else:
        full = 2 ** (bits - 1)
        v = np.clip(np.round(x * full), -full, full - 1).astype(np.int64)
        if bits == 24:
            u = (v & 0xFFFFFF).astype(np.uint32)
            data = np.stack([u & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF], axis=-1).astype(np.uint8).tobytes()
        else:
            data = v.astype(f"<i{bits // 8}").tobytes()
    align = ch * bits // 8
    tag = 3 if flt else 1
    if extensible:
        guid = struct.pack("<H", tag) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt = struct.pack("<HHIIHH", 0xFFFE, ch, rate, rate * align, align, bits)
        fmt += struct.pack("<HHI", 22, bits, 3) + guid
    else:
        fmt = struct.pack("<HHIIHH", tag, ch, rate, rate * align, align, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if extra:
        body += b"LIST" + struct.pack("<I", 5) + b"abcde\x00"  # tamanho ímpar: um byte de preenchimento
    body += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


@pytest.mark.parametrize("bits,flt,extensible,tol", [(16, False, False, 1 / 32768), (24, False, True, 1 / 2 ** 23),
                                                     (32, False, False, 1e-7), (32, True, True, 0.0)])
def test_wav_reader_formats(tmp_path, bits, flt, extensible, tol):
    from pelicula.audiomix import WavReader
    x = np.stack([np.linspace(-1, 0.999, 1000), np.linspace(0.5, -0.5, 1000)], axis=1)
    path = tmp_path / "a.wav"
    write_wav(path, x, 44100, bits, flt, extensible, extra=True)
    r = WavReader(str(path))
    assert (r.rate, r.channels, r.frames) == (44100, 2, 1000)
    assert r.duration == pytest.approx(1000 / 44100)
    got = r.read(100, 300)
    assert got.shape == (300, 2) and got.dtype == np.float32
    assert np.abs(got - x[100:400]).max() <= tol + 1e-7
    assert r.read(950, 500).shape == (50, 2)            # menos no fim do arquivo
    assert r.read(2000, 10).shape == (0, 2) and r.read(-5, 0).shape == (0, 2)


def test_wav_reader_rejects_other_files_and_survives_deletion(tmp_path):
    from pelicula.audiomix import WavReader
    bad = tmp_path / "nao.wav"
    bad.write_bytes(b"isto nao e um wav")
    with pytest.raises(ValueError):
        WavReader(str(bad))
    path = tmp_path / "a.wav"
    write_wav(path, tone(-6, 0.1, channels=1), RATE, 16)
    r = WavReader(str(path))
    assert r.channels == 1 and len(r.read(0, 10)) == 10
    path.unlink()  # cada leitura abre e fecha: apagar entre uma e outra não trava nada
    with pytest.raises(OSError):
        r.read(0, 10)


@pytest.mark.ffmpeg
def test_decode_wav_gives_48k_stereo_with_the_same_loudness(ffmpeg_ok, tmp_path):
    import threading

    from pelicula import audiomix
    src = tmp_path / "fonte.wav"
    mono = tone(-23, 3, rate=44100, channels=1)
    write_wav_f32(src, mono, 44100)
    out = tmp_path / "medidor.wav"
    assert audiomix.decode_wav(str(src), str(out))
    r = audiomix.WavReader(str(out))
    assert (r.rate, r.channels, r.bits) == (48000, 2, 16)
    assert r.duration == pytest.approx(3.0, abs=0.01)
    # mono vira os dois canais a −3 dB: a leitura em estéreo é a mesma da medida do arquivo mono
    expected = L.measure(mono, 44100).integrated
    assert L.measure(r.read(0, r.frames), r.rate).integrated == pytest.approx(expected, abs=0.1)
    # sem som: não dá e não sobra arquivo
    still = tmp_path / "imagem.png"
    subprocess.run([ffmpeg_ok, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=16x16", "-frames:v", "1",
                    str(still)], check=True, capture_output=True, timeout=60)
    out2 = tmp_path / "nada.wav"
    assert not audiomix.decode_wav(str(still), str(out2)) and not out2.exists()
    # cancelado: não dá e não sobra arquivo
    cancel = threading.Event()
    cancel.set()
    out3 = tmp_path / "cancelado.wav"
    assert not audiomix.decode_wav(str(src), str(out3), cancel) and not out3.exists()
