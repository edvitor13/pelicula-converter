"""Silêncios (níveis em janelas, limiar relativo, duração mínima, folga) e "Cortar pelo texto"."""

from __future__ import annotations

import subprocess
import threading

import numpy as np
import pytest

from pelicula import silences as sl, tools
from pelicula.subtitles import Word

RATE = sl.RATE


def tone(seconds: float, db: float, freq: float = 440.0) -> np.ndarray:
    t = np.arange(int(round(seconds * RATE))) / RATE
    amp = 10 ** (db / 20) * np.sqrt(2)          # seno com esse RMS em dBFS
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def noise(seconds: float, db: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)           # determinístico
    return (rng.standard_normal(int(round(seconds * RATE))) * 10 ** (db / 20)).astype(np.float32)


def speech_like(loud_db: float = -18.0, floor_db: float = -65.0) -> np.ndarray:
    """1 s de "fala", 1 s de silêncio (ruído baixo), 0,3 s de fala, 0,2 s de silêncio, 1 s de fala, 0,8 s mudo."""
    return np.concatenate([tone(1.0, loud_db), noise(1.0, floor_db), tone(0.3, loud_db), noise(0.2, floor_db, 2),
                           tone(1.0, loud_db), np.zeros(int(0.8 * RATE), np.float32)])


def test_levels_from_samples():
    lv = sl.levels_from_samples(tone(1.0, -20.0), start=5.0)
    assert len(lv.rms_db) == 100 and lv.window == pytest.approx(0.01) and lv.start == 5.0
    assert np.allclose(lv.rms_db, -20.0, atol=0.2)
    assert np.allclose(lv.peak_db, -17.0, atol=0.2)              # pico do seno = RMS + 3 dB
    assert lv.reference() == pytest.approx(-20.0, abs=0.2)
    silent = sl.levels_from_samples(np.zeros(800, np.float32))
    assert (silent.rms_db == sl.FLOOR_DB).all() and silent.reference() == sl.FLOOR_DB
    assert len(sl.levels_from_samples(np.zeros(RATE // 100 * 3 + 79, np.float32)).rms_db) == 3   # sobra < meia janela


def test_detect_relative_threshold_min_duration_and_padding():
    lv = sl.levels_from_samples(speech_like(), start=10.0)
    found = sl.detect(lv, threshold=-30, min_duration=0.5, padding=0.1)
    assert [(round(s.start, 2), round(s.end, 2)) for s in found] == [(11.1, 11.9), (13.6, 14.3)]
    assert found[0].level == pytest.approx(-65.0, abs=1.0)
    assert found[1].level == sl.FLOOR_DB                         # o fim mudo; sem folga no fim do trecho
    short = sl.detect(lv, threshold=-30, min_duration=0.15, padding=0.0)
    assert [(round(s.start, 2), round(s.end, 2)) for s in short] == [(11.0, 12.0), (12.3, 12.5), (13.5, 14.3)]


def test_relative_threshold_ignores_overall_gain():
    quiet = sl.detect(sl.levels_from_samples(speech_like(-38.0, -85.0)), threshold=-30, padding=0)
    loud = sl.detect(sl.levels_from_samples(speech_like(-8.0, -55.0)), threshold=-30, padding=0)
    assert [(round(s.start, 2), round(s.end, 2)) for s in quiet] == [(round(s.start, 2), round(s.end, 2)) for s in loud]
    # absoluto: o mesmo limiar em dBFS acha coisas diferentes
    a = sl.detect(sl.levels_from_samples(speech_like(-38.0, -85.0)), threshold=-60, relative=False, padding=0)
    b = sl.detect(sl.levels_from_samples(speech_like(-8.0, -55.0)), threshold=-60, relative=False, padding=0)
    assert len(a) == 2 and len(b) == 1                            # o ruído de -55 dBFS não passa de -60 dBFS


def test_short_click_does_not_break_a_silence():
    x = np.concatenate([tone(1.0, -20), np.zeros(int(0.5 * RATE), np.float32), tone(0.03, -10),
                        np.zeros(int(0.6 * RATE), np.float32), tone(1.0, -20)])
    found = sl.detect(sl.levels_from_samples(x), threshold=-30, min_duration=0.5, padding=0.0)
    assert len(found) == 1 and found[0].duration == pytest.approx(1.13, abs=0.02)
    split = sl.detect(sl.levels_from_samples(x), threshold=-30, min_duration=0.5, padding=0.0, bridge=0.0)
    assert len(split) == 2


def test_nothing_to_find():
    assert sl.detect(sl.levels_from_samples(tone(2.0, -20))) == []
    assert sl.detect(sl.levels_from_samples(np.zeros(0, np.float32))) == []
    whole = sl.detect(sl.levels_from_samples(np.zeros(RATE, np.float32)), padding=0.2)
    assert [(s.start, s.end) for s in whole] == [(0.0, 1.0)]     # tudo mudo: sem folga (não encosta em som)


@pytest.mark.ffmpeg
def test_levels_from_a_file_match_the_samples(ffmpeg_ok, tmp_path):
    x = speech_like()
    raw = tmp_path / "som.f32"
    raw.write_bytes(x.astype("<f4").tobytes())
    wav = tmp_path / "som.wav"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(raw),
                    "-c:a", "pcm_f32le", str(wav)], check=True)
    lv = sl.levels(str(wav), start=1.0, duration=3.0)
    ref = sl.levels_from_samples(x[RATE: 4 * RATE], start=1.0)
    assert len(lv.rms_db) == len(ref.rms_db) and lv.start == 1.0
    assert np.allclose(lv.rms_db, ref.rms_db, atol=0.5)
    found = sl.find_silences(str(wav), threshold=-30, min_duration=0.5, padding=0.1)
    assert [(round(s.start, 2), round(s.end, 2)) for s in found] == [(1.1, 1.9), (3.6, 4.3)]
    assert sl.ranges(found) == [(s.start, s.end) for s in found]


@pytest.mark.ffmpeg
def test_levels_errors_and_cancel(ffmpeg_ok, sample_video, tmp_path):
    silent = tmp_path / "mudo.mp4"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True)
    with pytest.raises(sl.SilenceError, match="não tem som"):
        sl.levels(str(silent))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(tools.Cancelled):
        sl.levels(sample_video, cancel=cancel)


# ------------------------------------------------------------------ cortar pelo texto
WORDS = [Word(0.50, 0.80, "Bom"), Word(0.85, 1.20, "dia,"), Word(1.60, 1.90, "é,"), Word(2.00, 2.30, "tipo,"),
         Word(2.40, 2.90, "pessoal."), Word(3.50, 3.90, "Vamos"), Word(3.95, 4.40, "lá.")]


def test_text_cut_ranges_snap_to_word_boundaries():
    # tirar "é, tipo,": do fim de "dia," (+folga) ao começo de "pessoal." (−folga)
    assert sl.text_cut_ranges(WORDS, [2, 3], padding=0.03) == [(1.23, 2.37)]
    # a primeira palavra: começa um pouco antes dela; a última: termina um pouco depois
    assert sl.text_cut_ranges(WORDS, [0], padding=0.03) == [(0.47, 0.82)]
    assert sl.text_cut_ranges(WORDS, [6], padding=0.03) == [(3.93, 4.43)]
    # vizinha perto: a folga fica antes dela
    assert sl.text_cut_ranges(WORDS, [5], padding=0.03) == [(2.93, 3.92)]
    # vão menor que a folga: o vão inteiro fica (o corte para no fim da palavra tirada)
    assert sl.text_cut_ranges(WORDS, [5], padding=0.08) == [(2.98, 3.9)]
    # dois trechos perto viram um; longe ficam separados
    assert sl.text_cut_ranges(WORDS, [2, 4], padding=0.03, merge_gap=0.15) == [(1.23, 1.97), (2.33, 3.47)]
    assert sl.text_cut_ranges(WORDS, [2, 4], padding=0.03, merge_gap=0.5) == [(1.23, 3.47)]
    assert sl.text_cut_ranges(WORDS, []) == [] and sl.text_cut_ranges(WORDS, [99]) == []


def test_text_spans_and_remaining_words():
    text = sl.transcript(WORDS)
    assert text == "Bom dia, é, tipo, pessoal. Vamos lá."
    a = text.index("é,")
    assert sl.indices_for_text(WORDS, [(a, a + len("é, tipo"))]) == [2, 3]
    assert sl.indices_for_text(WORDS, [(text.index("ssoal"), text.index("ssoal") + 2)]) == [4]   # pedaço = inteira
    assert sl.indices_for_text(WORDS, [(5, 5)]) == []
    cuts = sl.text_cut_ranges(WORDS, sl.indices_for_text(WORDS, [(a, a + 7)]))
    assert [w.text for w in sl.remaining_words(WORDS, cuts)] == ["Bom", "dia,", "pessoal.", "Vamos", "lá."]
