"""Gráfico "Curva" (ui/labcurve.py): eixo dos cinzas de um LUT assado com o look."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import presets
from pelicula.ui.labcurve import SIZE, gray_axis


def _identity_lut(n: int) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, n, dtype=np.float32)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([r, g, b], axis=-1).reshape(-1, 3)  # ordem .cube: R mais rápido


def test_gray_axis_of_identity_is_the_diagonal():
    lut = _identity_lut(SIZE)
    g = gray_axis(lut)
    assert g.shape == (SIZE, 3)
    expected = np.linspace(0.0, 1.0, SIZE)
    for c in range(3):
        np.testing.assert_allclose(g[:, c], expected, atol=1e-6)


def test_gray_axis_reads_only_the_neutral_entries():
    n = 5
    lut = _identity_lut(n).copy()
    lut[:, 0] += 0.25  # muda tudo no vermelho...
    g = gray_axis(lut, n)
    np.testing.assert_allclose(g[:, 0], np.linspace(0, 1, n) + 0.25, atol=1e-6)


@pytest.mark.gpu
def test_curve_follows_the_look(gl_engine):
    neutral = gray_axis(gl_engine.bake_lut(presets.builtin_values("original"), SIZE))
    np.testing.assert_allclose(neutral, np.repeat(np.linspace(0, 1, SIZE)[:, None], 3, axis=1), atol=2e-3)
    night = gray_axis(gl_engine.bake_lut(presets.builtin_values("lab_v3_500t_noite"), SIZE))
    assert np.all(np.diff(night, axis=0) >= -1e-4)          # monótona
    lows = night[4:12]
    assert np.mean(lows[:, 2] - lows[:, 0]) > 0.005          # sombras mais azuis que vermelhas (noite fria)
