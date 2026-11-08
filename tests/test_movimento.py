"""1.9 (F3): núcleo do movimento (`movimento.py`; ARQUITETURA §51) com imagens sintéticas de movimento conhecido.

Uma textura fixa "filmada" por uma câmera que treme (`movimento_sinteticos.shaken`): o movimento medido entre dois quadros
fica a menos de 0,5 px@1080 do verdadeiro em todo o quadro; a trajetória, a suavização e o zoom automático são conferidos
com contas fechadas. Sem ffmpeg nem GPU.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import movimento_sinteticos as ms
from pelicula import movimento


def _grid_error(a, b, w1080: float) -> float:
    """Maior distância (px@1080) entre as duas semelhanças numa grade 5 × 5 do quadro inteiro."""
    center = (w1080 / 2.0, 540.0)
    ma = movimento.similarity_matrix(a, center)
    mb = movimento.similarity_matrix(b, center)
    xs, ys = np.meshgrid(np.linspace(0, w1080, 5), np.linspace(0, 1080, 5))
    pts = np.stack([xs.ravel(), ys.ravel(), np.ones(xs.size)])
    return float(np.hypot(*((ma - mb) @ pts)[:2]).max())


def test_phase_correlation_finds_whole_and_fractional_shifts():
    tex = ms.texture(300, 300, seed=2)
    a = tex[100:164, 100:164]
    fy = np.fft.fftfreq(300)[:, None]
    fx = np.fft.fftfreq(300)[None, :]
    # o que sobra para um bloco depois do deslocamento global é pouco: a janela puxa só ~1% para o zero
    for dx, dy in ((3.0, -5.0), (0.25, 0.5), (-2.6, 1.3), (0.4, -0.3)):
        # deslocamento exato pela fase da textura inteira (a reamostragem bilinear também borra e puxaria o pico para o
        # inteiro); o bloco vem do meio, sem a volta da FFT
        moved = np.real(np.fft.ifft2(np.fft.fft2(tex) * np.exp(-2j * np.pi * (fx * dx + fy * dy))))
        b = moved[100:164, 100:164]  # b(x) = a(x − d)
        gx, gy, peak = movimento.phase_correlate(a, b)
        assert abs(gx - dx) < 0.06 and abs(gy - dy) < 0.06, (dx, dy, gx, gy)
        assert peak > 0.2


def test_ncc_map_finds_the_template():
    tex = ms.texture(120, 160, seed=4)
    tpl = tex[40:72, 70:102]
    m = movimento.ncc_map(tex[20:100, 40:140], tpl)
    y, x, v = movimento.subpixel_peak(m)
    assert (round(y), round(x)) == (20, 30) and v == pytest.approx(1.0, abs=1e-6)
    assert m.shape == (80 - 32 + 1, 100 - 32 + 1) and float(m.min()) >= -1.0


def test_similarity_matrix_and_params_round_trip():
    c = (960.0, 540.0)
    for p in ((10.0, -4.0, 0.03, 0.01), (0.0, 0.0, 0.0, 0.0), (-55.5, 20.25, -0.2, -0.05)):
        got = movimento.params_of(movimento.similarity_matrix(p, c), c)
        assert np.allclose(got, p, atol=1e-9)
    m = movimento.similarity_matrix((0.0, 0.0, math.radians(90), 0.0), c)
    assert np.allclose(m @ [960.0 + 100.0, 540.0, 1.0], [960.0, 640.0, 1.0])  # +x vai para +y: horário na tela


def test_fit_similarity_ignores_points_that_do_not_follow_the_camera():
    rng = np.random.default_rng(5)
    c = (960.0, 540.0)
    truth = (12.0, -7.5, math.radians(0.8), math.log(1.004))
    m = movimento.similarity_matrix(truth, c)
    p0 = rng.uniform([0, 0], [1920, 1080], (60, 2))
    p1 = (np.c_[p0, np.ones(60)] @ m.T)[:, :2] + rng.normal(0, 0.05, (60, 2))
    p1[:18] += rng.uniform(-60, 60, (18, 2))  # 30% de pontos de algo que anda sozinho na cena
    got, w = movimento.fit_similarity(p0, p1, c)
    assert _grid_error(got, truth, 1920.0) < 0.2
    assert float(w[:18].max()) < float(w[18:].min())


@pytest.mark.parametrize("seed", [3, 11])
def test_frame_motion_matches_the_known_shake(seed):
    """Tremor de mão (até 30 px@1080, 0,5°, 0,5% de escala por quadro) medido a menos de 0,5 px@1080 em todo o quadro,
    no tamanho das análises (540 linhas)."""
    rng = np.random.default_rng(seed)
    n, w, h = 5, 960, 540
    mot = np.zeros((n, 4))
    mot[1:, 0] = rng.uniform(-30, 30, n - 1)
    mot[1:, 1] = rng.uniform(-20, 20, n - 1)
    mot[1:, 2] = np.radians(rng.uniform(-0.5, 0.5, n - 1))
    mot[1:, 3] = np.log(rng.uniform(0.995, 1.005, n - 1))
    frames = ms.shaken(mot, w, h, seed=seed, margin=200)
    for k in range(1, n):
        got = movimento.frame_motion(frames[k - 1], frames[k], 1080.0 / h)
        assert _grid_error(got, mot[k], 1920.0) < 0.5, (k, got, mot[k])


def test_estimate_returns_identity_for_the_first_frame():
    mot = np.zeros((3, 4))
    mot[1:, 0] = (8.0, -4.0)
    frames = ms.shaken(mot, 640, 360, margin=60)
    calls = []
    got = movimento.estimate(iter(enumerate(frames)), 3, 1080.0 / 360, lambda d, t: calls.append((d, t)))
    assert got.shape == (3, 4) and got.dtype == np.float32 and np.all(got[0] == 0)
    assert np.allclose(got[1:, 0], (8.0, -4.0), atol=0.5) and calls[-1] == (3, 3)


def test_trajectory_composes_the_motions():
    c = (960.0, 540.0)
    mot = np.array([[0, 0, 0, 0], [5.0, 0, 0.01, 0], [5.0, 0, 0.01, 0], [-3.0, 2.0, -0.02, 0.001]])
    path = movimento.trajectory(mot, c)
    t = np.eye(3)
    for k in range(1, 4):
        t = movimento.similarity_matrix(mot[k], c) @ t
        assert np.allclose(movimento.similarity_matrix(path[k], c), t, atol=1e-9)
    assert np.allclose(path[0], 0.0)


def test_smoothing_keeps_constant_and_straight_paths_up_to_the_ends():
    n = 40
    straight = np.stack([np.arange(n) * 3.0, np.full(n, 7.0), np.arange(n) * 0.001, np.zeros(n)], axis=1)
    for sigma in (2.0, 24.0, 200.0):
        assert np.allclose(movimento.smooth(straight, sigma), straight, atol=1e-9)
    rng = np.random.default_rng(1)
    shake = straight + rng.normal(0, 4.0, straight.shape) * [1, 1, 0, 0]
    soft = movimento.smooth(shake, 6.0)
    assert np.std(np.diff(soft[:, 0], 2)) < 0.2 * np.std(np.diff(shake[:, 0], 2))
    assert np.array_equal(movimento.smooth(shake, 0.0), shake)


def test_corrections_keep_a_pan_and_remove_the_shake():
    c = (960.0, 540.0)
    n = 60
    pan = np.zeros((n, 4))
    pan[1:, 0] = 4.0                                  # panorâmica: 4 px@1080 por quadro
    corr = movimento.corrections(pan, c, 12.0)
    assert np.allclose(corr, np.eye(3), atol=1e-6)
    rng = np.random.default_rng(2)
    shake = pan.copy()
    shake[1:, :2] += rng.normal(0, 6.0, (n - 1, 2))
    shake[1:, 2] = rng.normal(0, 0.004, n - 1)
    corr = movimento.corrections(shake, c, 12.0)
    path = movimento.trajectory(shake, c)
    # o ponto do meio do quadro estabilizado anda quase em linha reta
    centers = []
    for k in range(n):
        shown = corr[k] @ [c[0], c[1], 1.0]                     # o ponto do quadro original que aparece no meio
        scene = np.linalg.inv(movimento.similarity_matrix(path[k], c)) @ shown  # onde ele está na cena
        centers.append(scene[:2])
    jerk = np.abs(np.diff(np.array(centers), 2, axis=0)).max()
    raw_jerk = np.abs(np.diff(path[:, :2], 2, axis=0)).max()
    assert jerk < 0.25 * raw_jerk
    no_rot = movimento.corrections(shake, c, 12.0, rotation=False)
    assert all(abs(movimento.params_of(m, c)[2]) < 1e-9 for m in no_rot)


def test_auto_zoom_hides_the_borders():
    w, h = 1920.0, 1080.0
    c = (w / 2, h / 2)
    shift = np.array([movimento.similarity_matrix((48.0, 0.0, 0.0, 0.0), c), np.eye(3)])
    z = movimento.auto_zoom(shift, w, h)
    assert z == pytest.approx(960.0 / (960.0 - 48.0))
    m = shift[0] @ movimento.zoom_matrix(z, c)
    corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], float).T
    got = m @ corners
    assert got[0].min() >= -1e-9 and got[0].max() <= w + 1e-9
    assert movimento.auto_zoom(np.array([np.eye(3)]), w, h) == 1.0
    huge = np.array([movimento.similarity_matrix((1500.0, 0.0, 0.0, 0.0), c)])
    assert movimento.auto_zoom(huge, w, h) == movimento.MAX_ZOOM
    rot = np.array([movimento.similarity_matrix((0.0, 0.0, math.radians(2.0), 0.0), c)])
    zr = movimento.auto_zoom(rot, w, h)
    got = (rot[0] @ movimento.zoom_matrix(zr, c)) @ corners
    assert 1.0 < zr < 1.1 and got[0].min() >= -1e-6 and got[1].max() <= h + 1e-6


def test_analysis_size_is_even_and_never_bigger_than_the_source():
    assert movimento.analysis_size(1920, 1080) == (960, 540)
    assert movimento.analysis_size(320, 180) == (320, 180)
    assert movimento.analysis_size(1080, 1920) == (304, 540)
    w, h = movimento.analysis_size(4096, 1716)
    assert h == 540 and w % 2 == 0 and h % 2 == 0
