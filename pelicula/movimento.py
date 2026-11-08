"""1.9, núcleo do movimento (F3, #68; ARQUITETURA §51): o que a estabilização e o rastreio de ponto medem. Só numpy.

Tudo aqui é puro (sem GPU, sem Qt, sem ffmpeg, menos `read_gray`) e roda nos trabalhos de CPU da fila (`jobs`), nunca no
caminho de render: a imagem só usa o resultado guardado (`estabilizacao.py`, `rastreio.py`).

- **Coordenadas**: pixels contínuos de um quadro de 1080 linhas da fonte (px@1080: o quadro tem `1080 × largura/altura`
  por 1080; o pixel i cobre [i, i + 1)), y para baixo. O centro das rotações é o meio do quadro.
- **Movimento entre dois quadros** (`fit_similarity`): uma semelhança (translação, rotação, escala) em torno do centro,
  p1 = c + s·R(a)·(p0 − c) + t, que leva um ponto da cena no quadro anterior (p0) ao lugar dele no quadro atual (p1).
  Guardada como (tx, ty, ângulo em radianos, log da escala); ângulo positivo gira no sentido horário da tela.
- **Vetores locais** (`local_vectors`): correlação de fase por FFT em blocos (com o deslocamento global de antes),
  pico com refinamento por parábola; o ajuste robusto (mediana + mínimos quadrados repesados de Tukey) ignora o que se
  move sozinho na cena.
- **Trajetória** (`trajectory`): o produto dos movimentos desde o primeiro quadro do arquivo; suavizada por uma gaussiana
  sobre o arquivo inteiro com as pontas espelhadas (`smooth`). A correção de cada quadro é T·S⁻¹ (`corrections`): a
  imagem estabilizada no ponto y mostra o quadro original em T(S⁻¹(y)).
- **Zoom automático** (`auto_zoom`): o menor zoom (em volta do centro) que esconde as bordas em todos os quadros.
"""

from __future__ import annotations

import math
from typing import Callable, Iterator

import numpy as np

ANALYSIS_H = 540          # altura da decodificação das análises (px); fonte menor fica no tamanho dela
MAX_ZOOM = 1.6            # zoom automático máximo (um tremor maior que isso fica com bordas)
W709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# ------------------------------------------------------------------ quadros em cinza
def gray(img: np.ndarray) -> np.ndarray:
    """Luminância Rec.709 (float32, 0 a 1) de um quadro RGB/RGBA de 8 ou 16 bits (ou float)."""
    a = np.asarray(img)
    if a.dtype == np.uint8:
        f = a[..., :3].astype(np.float32) / 255.0
    elif a.dtype == np.uint16:
        f = a[..., :3].astype(np.float32) / 65535.0
    else:
        f = a[..., :3].astype(np.float32)
    if a.ndim == 2:
        return f
    return f @ W709


def analysis_size(width: int, height: int, target: int = ANALYSIS_H) -> tuple[int, int]:
    """Tamanho par da decodificação das análises: `target` linhas (ou a altura da fonte, se menor)."""
    h = min(int(height), int(target))
    h -= h % 2
    w = int(round(width * h / max(1, height)))
    w -= w % 2
    return max(2, w), max(2, h)


def read_gray(info, first: int, count: int, size: tuple[int, int],
              cancel: Callable[[], bool] | None = None) -> Iterator[tuple[int, np.ndarray]]:
    """Quadros `first` … `first + count − 1` do arquivo em cinza, no tamanho `size`, pelo leitor de sempre
    (`media.FrameReader`): (quadro, imagem float32). Para cedo se `cancel()` ficar verdadeiro."""
    from . import media
    reader = media.FrameReader(info, size[0], size[1], 8, start_frame=int(first), max_frames=int(count))
    try:
        for i in range(int(count)):
            if cancel is not None and cancel():
                return
            img = reader.read()
            if img is None:
                return
            yield int(first) + i, gray(img)
    finally:
        reader.close()


# ------------------------------------------------------------------ correlação
def _hann(h: int, w: int) -> np.ndarray:
    return np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)


_LOWPASS: dict[tuple[int, int], np.ndarray] = {}


def _lowpass(h: int, w: int, cutoff: float = 0.18) -> np.ndarray:
    """Peso gaussiano das frequências da correlação de fase (`cutoff` em ciclos por pixel)."""
    hit = _LOWPASS.get((h, w))
    if hit is None:
        fy = np.fft.fftfreq(h)[:, None]
        fx = np.fft.fftfreq(w)[None, :]
        hit = np.exp(-(fx * fx + fy * fy) / (2.0 * cutoff * cutoff))
        if len(_LOWPASS) > 32:
            _LOWPASS.clear()
        _LOWPASS[(h, w)] = hit
    return hit


def _parabola(a: float, b: float, c: float) -> float:
    """Vértice da parábola por três pontos em −1, 0, 1 (em −0,5…0,5)."""
    d = a - 2.0 * b + c
    if abs(d) < 1e-12:
        return 0.0
    return float(min(0.5, max(-0.5, 0.5 * (a - c) / d)))


def subpixel_peak(m: np.ndarray, wrap: bool = False) -> tuple[float, float, float]:
    """(y, x, valor) do máximo do mapa com refinamento por parábola em cada eixo. `wrap`: o mapa é circular (FFT)."""
    iy, ix = np.unravel_index(int(np.argmax(m)), m.shape)
    h, w = m.shape
    peak = float(m[iy, ix])
    if wrap:
        dy = _parabola(m[(iy - 1) % h, ix], peak, m[(iy + 1) % h, ix])
        dx = _parabola(m[iy, (ix - 1) % w], peak, m[iy, (ix + 1) % w])
    else:
        dy = _parabola(m[iy - 1, ix], peak, m[iy + 1, ix]) if 0 < iy < h - 1 else 0.0
        dx = _parabola(m[iy, ix - 1], peak, m[iy, ix + 1]) if 0 < ix < w - 1 else 0.0
    return iy + dy, ix + dx, peak


UPSAMPLE = 20  # refinamento do pico da correlação de fase: 1/20 de pixel


def _upsampled_peak(cross: np.ndarray, y: float, x: float, factor: int) -> tuple[float, float]:
    """Refina o pico (y, x) da correlação de fase pela DFT ampliada só em volta dele (Guizar-Sicairos et al., 2008,
    "Efficient subpixel image registration algorithms"): a correlação em passos de 1/`factor` numa janela de 1,5 pixel,
    sem ampliar a imagem inteira."""
    h, w = cross.shape
    size = int(math.ceil(factor * 1.5))
    mid = size // 2
    oy = mid - round(y * factor)
    ox = mid - round(x * factor)
    fy = np.fft.ifftshift(np.arange(h)) - h // 2
    fx = np.fft.ifftshift(np.arange(w)) - w // 2
    rows = np.exp((2j * math.pi / (h * factor)) * np.outer(np.arange(size) - oy, fy))
    cols = np.exp((2j * math.pi / (w * factor)) * np.outer(fx, np.arange(size) - ox))
    up = np.abs(rows @ cross @ cols)
    iy, ix = np.unravel_index(int(np.argmax(up)), up.shape)
    return round(y * factor) / factor + (iy - mid) / factor, round(x * factor) / factor + (ix - mid) / factor


def phase_correlate(a: np.ndarray, b: np.ndarray, window: bool = True,
                    upsample: int = UPSAMPLE) -> tuple[float, float, float]:
    """Deslocamento (dx, dy) do conteúdo de `a` para `b` (b(x) ≈ a(x − d)) e a força do pico (0 a 1) pela correlação
    de fase. Mesmo tamanho; `window` aplica Hann (blocos); `upsample` > 1 refina o pico (`_upsampled_peak`)."""
    a = np.asarray(a, np.float64)
    b = np.asarray(b, np.float64)
    a = a - a.mean()
    b = b - b.mean()
    if window:
        win = _hann(*a.shape)
        a, b = a * win, b * win
    cross = np.fft.fft2(b) * np.conj(np.fft.fft2(a))
    mag = np.abs(cross)
    cross /= np.maximum(mag, 1e-9 * max(1.0, float(mag.max())))
    low = _lowpass(*a.shape)
    cross *= low  # as frequências mais altas (ruído, compressão, reamostragem) puxam o pico para o inteiro
    r = np.real(np.fft.ifft2(cross)) / float(low.mean())  # um deslocamento puro dá pico 1
    y, x, peak = subpixel_peak(r, wrap=True)
    h, w = a.shape
    if y > h / 2:
        y -= h
    if x > w / 2:
        x -= w
    if upsample > 1:
        y, x = _upsampled_peak(cross, y, x, int(upsample))
    return float(x), float(y), float(peak)


def _window_sums(img: np.ndarray, h: int, w: int) -> np.ndarray:
    """Somas de todas as janelas h × w de `img` (imagem integral)."""
    s = np.zeros((img.shape[0] + 1, img.shape[1] + 1), np.float64)
    s[1:, 1:] = np.cumsum(np.cumsum(img, axis=0), axis=1)
    return s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]


def ncc_map(search: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Correlação cruzada normalizada (−1 a 1) do modelo em cada posição válida da janela de busca (FFT + imagens
    integrais): saída (H − h + 1) × (W − w + 1); o elemento [y, x] compara o modelo com search[y:y+h, x:x+w]."""
    s = np.asarray(search, np.float64)
    t = np.asarray(template, np.float64)
    h, w = t.shape
    H, W = s.shape
    t0 = t - t.mean()
    tn = math.sqrt(float((t0 * t0).sum()))
    n = h * w
    shape = (H + h - 1, W + w - 1)
    fs = np.fft.rfft2(s, shape)
    ft = np.fft.rfft2(t0[::-1, ::-1], shape)
    full = np.fft.irfft2(fs * ft, shape)
    num = full[h - 1:H, w - 1:W]
    s1 = _window_sums(s, h, w)
    s2 = _window_sums(s * s, h, w)
    var = np.maximum(s2 - s1 * s1 / n, 0.0)
    den = np.sqrt(var) * tn
    out = np.where(den > 1e-9 * max(1.0, tn), num / np.maximum(den, 1e-30), 0.0)
    return np.clip(out, -1.0, 1.0)


# ------------------------------------------------------------------ vetores locais
def local_vectors(prev: np.ndarray, cur: np.ndarray, block: int = 64, grid: tuple[int, int] = (8, 5),
                  min_peak: float = 0.08) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pontos correspondentes entre dois quadros em cinza do mesmo tamanho: (p0, p1, pesos), p0 no quadro anterior e
    p1 no atual (pixels contínuos do quadro dado). Primeiro o deslocamento global (correlação de fase no quadro
    inteiro, reduzido), depois um bloco por célula da grade com o bloco do atual já deslocado."""
    h, w = prev.shape
    step = max(1, min(h, w) // 256)
    gx, gy, _gp = phase_correlate(prev[::step, ::step], cur[::step, ::step])
    g = np.array([round(gx * step), round(gy * step)], dtype=np.int64)
    b = int(min(block, h // 2, w // 2))
    b -= b % 2
    if b < 8:
        return np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0)
    nx, ny = grid
    p0, p1, wt = [], [], []
    for j in range(ny):
        for i in range(nx):
            cx = int(round((i + 0.5) * w / nx))
            cy = int(round((j + 0.5) * h / ny))
            x0, y0 = cx - b // 2, cy - b // 2
            x1, y1 = x0 + int(g[0]), y0 + int(g[1])
            if not (0 <= x0 and x0 + b <= w and 0 <= y0 and y0 + b <= h and 0 <= x1 and x1 + b <= w
                    and 0 <= y1 and y1 + b <= h):
                continue
            a = prev[y0:y0 + b, x0:x0 + b]
            c = cur[y1:y1 + b, x1:x1 + b]
            if float(a.std()) < 1e-3:
                continue
            dx, dy, peak = phase_correlate(a, c)
            if peak < min_peak:
                continue
            p0.append((cx, cy))
            p1.append((cx + g[0] + dx, cy + g[1] + dy))
            wt.append(peak)
    return np.array(p0, np.float64).reshape(-1, 2), np.array(p1, np.float64).reshape(-1, 2), np.array(wt)


# ------------------------------------------------------------------ semelhança
IDENTITY = (0.0, 0.0, 0.0, 0.0)


def similarity_matrix(params, center) -> np.ndarray:
    """Matriz 3×3 da semelhança (tx, ty, ângulo, log da escala) em torno de `center`: p ↦ c + s·R·(p − c) + t."""
    tx, ty, a, ls = (float(x) for x in params)
    s = math.exp(ls)
    cs, sn = s * math.cos(a), s * math.sin(a)
    cx, cy = float(center[0]), float(center[1])
    return np.array([[cs, -sn, cx + tx - cs * cx + sn * cy],
                     [sn, cs, cy + ty - sn * cx - cs * cy],
                     [0.0, 0.0, 1.0]], dtype=np.float64)


def params_of(m: np.ndarray, center) -> tuple[float, float, float, float]:
    """(tx, ty, ângulo, log da escala) de uma matriz de semelhança, em torno de `center` (o inverso de
    `similarity_matrix`)."""
    a, b = float(m[0, 0]), float(m[1, 0])
    cx, cy = float(center[0]), float(center[1])
    tx = float(m[0, 2]) + a * cx - b * cy - cx
    ty = float(m[1, 2]) + b * cx + a * cy - cy
    return tx, ty, math.atan2(b, a), 0.5 * math.log(max(a * a + b * b, 1e-24))


def fit_similarity(p0: np.ndarray, p1: np.ndarray, center, weights: np.ndarray | None = None,
                   iters: int = 12) -> tuple[tuple[float, float, float, float], np.ndarray]:
    """A semelhança que leva p0 a p1, robusta a pontos que não seguem a câmera: começa pela mediana dos deslocamentos e
    repesa com Tukey (escala pela mediana dos resíduos). Devolve ((tx, ty, ângulo, log da escala), pesos finais); com
    menos de dois pontos, só a translação (ou nada)."""
    p0 = np.asarray(p0, np.float64).reshape(-1, 2)
    p1 = np.asarray(p1, np.float64).reshape(-1, 2)
    n = len(p0)
    if n == 0:
        return IDENTITY, np.zeros(0)
    base = np.ones(n) if weights is None else np.maximum(np.asarray(weights, np.float64), 0.0)
    c = np.asarray(center, np.float64)
    q = p0 - c
    r = p1 - c
    t = np.median(p1 - p0, axis=0)
    if n < 3:
        return (float(t[0]), float(t[1]), 0.0, 0.0), base
    sol = np.array([1.0, 0.0, t[0], t[1]])
    rows = np.zeros((2 * n, 4))
    rows[0::2] = np.stack([q[:, 0], -q[:, 1], np.ones(n), np.zeros(n)], axis=1)
    rows[1::2] = np.stack([q[:, 1], q[:, 0], np.zeros(n), np.ones(n)], axis=1)
    rhs = r.reshape(-1)
    w = base.copy()
    for _ in range(iters):
        res = (rows @ sol - rhs).reshape(-1, 2)
        e = np.hypot(res[:, 0], res[:, 1])
        scale = max(1.4826 * float(np.median(e)), 0.05)
        k = 4.685 * scale
        w = base * np.where(e < k, (1.0 - (e / k) ** 2) ** 2, 0.0)
        if np.count_nonzero(w > 0) < 3:
            break
        ww = np.repeat(w, 2)
        a = rows * ww[:, None]
        new = np.linalg.lstsq(a.T @ rows, a.T @ rhs, rcond=None)[0]
        done = float(np.abs(new - sol).max()) < 1e-7
        sol = new
        if done:
            break
    angle, ls = math.atan2(sol[1], sol[0]), 0.5 * math.log(max(sol[0] ** 2 + sol[1] ** 2, 1e-24))
    return (float(sol[2]), float(sol[3]), angle, ls), w


def warp(img: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Bilinear: a saída no pixel p mostra `img` em m·p (pixels contínuos, 3×3); fora da imagem, a borda."""
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    x = m[0, 0] * xx + m[0, 1] * yy + m[0, 2] - 0.5
    y = m[1, 0] * xx + m[1, 1] * yy + m[1, 2] - 0.5
    x = np.clip(x, 0.0, w - 1.000001)
    y = np.clip(y, 0.0, h - 1.000001)
    x0 = x.astype(np.int64)
    y0 = y.astype(np.int64)
    ax = (x - x0).astype(np.float32)
    ay = (y - y0).astype(np.float32)
    top = img[y0, x0] * (1 - ax) + img[y0, x0 + 1] * ax
    bot = img[y0 + 1, x0] * (1 - ax) + img[y0 + 1, x0 + 1] * ax
    return (top * (1 - ay) + bot * ay).astype(np.float32)


def frame_motion(prev: np.ndarray, cur: np.ndarray, scale: float = 1.0,
                 refine: bool = True) -> tuple[float, float, float, float]:
    """O movimento da câmera entre dois quadros em cinza (`fit_similarity` sobre `local_vectors`) em px@1080:
    `scale` = 1080 / altura dos quadros dados. `refine`: mede de novo com o quadro atual já desfeito pela primeira
    estimativa (a rotação deforma os blocos e a primeira medida fica 1 a 2% curta) e compõe as duas."""
    h, w = prev.shape
    center = (w * scale / 2.0, h * scale / 2.0)
    p0, p1, wt = local_vectors(prev, cur)
    params, _w = fit_similarity(p0 * scale, p1 * scale, center, wt)  # centros dos blocos: já contínuos
    if not refine or len(p0) < 3:
        return params
    to_px = np.diag([1.0 / scale, 1.0 / scale, 1.0])
    first = similarity_matrix(params, center)
    back = warp(cur, to_px @ first @ np.linalg.inv(to_px))      # ≈ prev: o atual levado de volta
    q0, q1, qw = local_vectors(prev, back)
    rest, _w = fit_similarity(q0 * scale, q1 * scale, center, qw)
    return params_of(first @ similarity_matrix(rest, center), center)


def estimate(frames: Iterator[tuple[int, np.ndarray]], total: int, scale: float,
             report: Callable[[int, int], None] | None = None) -> np.ndarray:
    """Movimento quadro a quadro de uma sequência de quadros em cinza (o caminho em numpy, sem o vid.stab): array
    (lidos, 4) float32 com (tx, ty, ângulo, log da escala) do quadro anterior para cada quadro, em px@1080, até o último
    quadro lido (no máximo `total`); o primeiro é a identidade."""
    out = np.zeros((int(total), 4), np.float32)
    prev = None
    done = 0
    last = -1
    for k, g in frames:
        if not 0 <= k < total:
            break
        if prev is not None:
            out[k] = frame_motion(prev, g, scale)
        prev = g
        last = k
        done += 1
        if report is not None:
            report(done, total)
    return out[:last + 1]


# ------------------------------------------------------------------ trajetória e correção
def frame_center(width: int, height: int) -> tuple[float, float]:
    """Centro do quadro da fonte em px@1080."""
    return 540.0 * width / max(1, height), 540.0


def trajectory(motions: np.ndarray, center) -> np.ndarray:
    """Trajetória da câmera desde o primeiro quadro: (n, 4) com os parâmetros de T_k = D_k·…·D_1 (D = `motions`)."""
    mot = np.asarray(motions, np.float64).reshape(-1, 4)
    out = np.zeros((len(mot), 4), np.float64)
    t = np.eye(3)
    for k in range(len(mot)):
        if k:
            t = similarity_matrix(mot[k], center) @ t
        out[k] = params_of(t, center)
    out[:, 2] = np.unwrap(out[:, 2])
    return out


def smooth(path: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussiana de desvio `sigma` (quadros) ao longo do eixo 0, com as pontas espelhadas em ponto (p[−i] = 2·p[0] −
    p[i]): uma panorâmica em linha reta passa igual até a ponta do arquivo (o espelho comum a dobraria ali)."""
    p = np.asarray(path, np.float64)
    n = len(p)
    if n < 2 or sigma <= 0:
        return p.copy()
    r = int(math.ceil(3.0 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    k /= k.sum()
    pad = []
    for i in range(-r, n + r):  # espelho em ponto, repetido se o raio passa do arquivo inteiro
        j, base = i, np.zeros(p.shape[1])
        sign = 1.0
        while j < 0 or j >= n:
            if j < 0:
                base, j = base + sign * 2.0 * p[0], -j
            else:
                base, j = base + sign * 2.0 * p[n - 1], 2 * (n - 1) - j
            sign = -sign
        pad.append(base + sign * p[j])
    padded = np.array(pad)
    out = np.empty_like(p)
    for j in range(p.shape[1]):
        out[:, j] = np.convolve(padded[:, j], k, mode="valid")
    return out


def corrections(motions: np.ndarray, center, sigma: float, rotation: bool = True) -> np.ndarray:
    """Correção de cada quadro, (n, 3, 3): leva um ponto da imagem estabilizada ao ponto do quadro original que ela
    mostra (T_k·S_k⁻¹, S = a trajetória suavizada). `rotation=False` não corrige a rotação."""
    path = trajectory(motions, center)
    soft = smooth(path, sigma)
    if not rotation:
        soft[:, 2] = path[:, 2]
    out = np.empty((len(path), 3, 3), np.float64)
    for k in range(len(path)):
        out[k] = similarity_matrix(path[k], center) @ np.linalg.inv(similarity_matrix(soft[k], center))
    return out


def zoom_matrix(z: float, center) -> np.ndarray:
    """y ↦ c + (y − c)/z: a imagem ampliada `z` vezes em volta do centro (o ponto que cada pixel mostra)."""
    cx, cy = float(center[0]), float(center[1])
    k = 1.0 / float(z)
    return np.array([[k, 0.0, cx - k * cx], [0.0, k, cy - k * cy], [0.0, 0.0, 1.0]])


def auto_zoom(corr: np.ndarray, width: float, height: float, limit: float = MAX_ZOOM) -> float:
    """O menor zoom (≥ 1, até `limit`) em volta do centro que deixa os quatro cantos de toda imagem corrigida dentro do
    quadro original (sem bordas). `width`/`height` em px@1080."""
    c = np.array([width / 2.0, height / 2.0])
    half = c
    corners = np.array([[0.0, 0.0], [width, 0.0], [0.0, height], [width, height]]) - c
    z = 1.0
    for m in np.asarray(corr).reshape(-1, 3, 3):
        u = m[:2, :2] @ c + m[:2, 2] - c
        if np.any(np.abs(u) >= half):
            return float(limit)
        v = corners @ m[:2, :2].T
        for axis in (0, 1):
            pos = v[:, axis] > 0
            if np.any(pos):
                z = max(z, float((v[pos, axis] / (half[axis] - u[axis])).max()))
            neg = v[:, axis] < 0
            if np.any(neg):
                z = max(z, float((-v[neg, axis] / (half[axis] + u[axis])).max()))
    return float(min(max(z, 1.0), limit))
