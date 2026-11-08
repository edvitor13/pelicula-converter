"""Som ao arrastar o cursor (1.8, `ui/scrub_ui.py`): o tamanho do grão, os fades, a conversão para 16 bits e o limite de
um grão por vez. Funções puras: nada toca (o caso com a janela e um sink falso fica em `mixer_ui_cases.py`)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6.QtCore")

from pelicula.ui import scrub_ui  # noqa: E402


@pytest.mark.parametrize("fps, want", [(24.0, 2000), (25.0, 1920), (30.0, 1920), (60.0, 1920), (12.0, 4000)])
def test_the_grain_is_one_frame_and_never_shorter_than_40_ms(fps, want):
    start, n = scrub_ui.grain_span(10, fps)
    assert start == round(10 / fps * 48000) and n == want
    assert n >= 0.040 * 48000


def test_the_grain_fades_in_and_out_in_5_ms():
    x = np.ones((2000, 2), np.float32)
    g = scrub_ui.make_grain(x)
    k = 240   # 5 ms a 48 kHz
    assert g.shape == (2000, 2) and g.dtype == np.float32
    assert 0 < g[0, 0] < 0.01 and 0 < g[-1, 1] < 0.01
    assert np.all(np.diff(g[:k, 0]) > 0) and np.all(np.diff(g[-k:, 0]) < 0)
    assert np.all(g[k:-k] == 1.0)
    assert np.array_equal(g[:, 0], g[:, 1])
    assert np.all(x == 1.0)   # não muda a entrada
    short = scrub_ui.make_grain(np.ones((100, 2)))   # mais curto que os dois fades: cada um fica com metade
    assert short.max() < 1.0 and short[49, 0] == pytest.approx(short[50, 0])


def test_pcm16_follows_the_preview_volume_and_clips():
    x = np.array([[0.5, -0.5], [2.0, -2.0]], np.float32)
    v = np.frombuffer(scrub_ui.to_pcm16(x, 0.5), "<i2").reshape(-1, 2)
    assert v.tolist() == [[8191, -8191], [32767, -32767]]


def test_one_grain_at_a_time():
    t = scrub_ui.Throttle()
    assert t.ready(10.0)
    t.played(10.0, 0.05)
    assert not t.ready(10.02) and not t.ready(10.049)
    assert t.ready(10.05)
