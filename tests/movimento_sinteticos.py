"""Imagens sintéticas dos testes do movimento (1.9, F3): uma textura com detalhe em várias escalas e quadros "filmados"
por uma câmera que treme com movimentos conhecidos (semelhanças em px@1080). Só numpy; não é coletado como teste."""

from __future__ import annotations

import numpy as np

from pelicula import movimento


def texture(h: int, w: int, seed: int = 7) -> np.ndarray:
    """Textura (float32, 0 a 1) com manchas grandes e detalhe fino: boa para correlação."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w))
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    for sigma, amp in ((0.01, 1.0), (0.04, 0.6), (0.12, 0.35)):
        f = np.fft.fft2(rng.standard_normal((h, w))) * np.exp(-(fx ** 2 + fy ** 2) / (2 * sigma ** 2))
        layer = np.real(np.fft.ifft2(f))
        out += amp * layer / (np.abs(layer).max() + 1e-12)
    out -= out.min()
    return (out / out.max()).astype(np.float32)


def sample(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear em coordenadas contínuas (o pixel i cobre [i, i + 1)); fora da imagem, a borda."""
    h, w = img.shape
    xf = np.clip(x - 0.5, 0, w - 1.000001)
    yf = np.clip(y - 0.5, 0, h - 1.000001)
    x0 = np.floor(xf).astype(np.int64)
    y0 = np.floor(yf).astype(np.int64)
    ax = xf - x0
    ay = yf - y0
    a = img[y0, x0] * (1 - ax) + img[y0, x0 + 1] * ax
    b = img[y0 + 1, x0] * (1 - ax) + img[y0 + 1, x0 + 1] * ax
    return (a * (1 - ay) + b * ay).astype(np.float32)


def warp(big: np.ndarray, m_inv: np.ndarray, w: int, h: int, offset=(0.0, 0.0)) -> np.ndarray:
    """Quadro w × h que mostra, no pixel p, a textura em `offset + m_inv·p` (m_inv: 3×3, pixels contínuos)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    pts = np.stack([xx.ravel(), yy.ravel(), np.ones(xx.size)])
    src = m_inv @ pts
    return sample(big, src[0].reshape(h, w) + offset[0], src[1].reshape(h, w) + offset[1])


def shaken(motions: np.ndarray, w: int, h: int, seed: int = 7, margin: int = 80) -> list[np.ndarray]:
    """Quadros w × h (pixels de um quadro de `h` linhas) de uma cena fixa filmada com estes movimentos entre quadros
    (`movimento.trajectory`, em px@1080 da altura `h`: escala 1080/h). O quadro k mostra a cena em T_k⁻¹."""
    s = 1080.0 / h
    center = movimento.frame_center(w, h)
    path = movimento.trajectory(motions, center)
    big = texture(h + 2 * margin, w + 2 * margin, seed)
    to_px = np.diag([1.0 / s, 1.0 / s, 1.0])
    out = []
    for p in path:
        t = movimento.similarity_matrix(p, center)            # px@1080: cena → quadro
        m_inv = to_px @ np.linalg.inv(t) @ np.linalg.inv(to_px)  # px do quadro → px da cena
        out.append(warp(big, m_inv, w, h, (margin, margin)))
    return out
