"""Cena de teste gerada no próprio app (cartela de cores, rampa de cinza e luzes fortes)."""

from __future__ import annotations

import numpy as np

CHECKER = [
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
]


def _srgb_to_lin(c):
    c = np.asarray(c, np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def make(width: int = 1920, height: int = 1080) -> np.ndarray:
    h, w = height, width
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    fy = y / h
    top = _srgb_to_lin((28, 38, 70))
    mid = _srgb_to_lin((190, 120, 80))
    low = _srgb_to_lin((40, 28, 24))
    t = np.clip(fy / 0.62, 0, 1)[..., None]
    img = top * (1 - t) + mid * t
    floor = np.clip((fy - 0.62) / 0.06, 0, 1)[..., None]
    img = img * (1 - floor) + low * floor
    s = w / 1920.0
    size, gap = int(118 * s), int(10 * s)
    x0, y0 = int(80 * s), int(120 * s)
    for i, c in enumerate(CHECKER):
        r, k = divmod(i, 6)
        xa, ya = x0 + k * (size + gap), y0 + r * (size + gap)
        img[ya:ya + size, xa:xa + size] = _srgb_to_lin(c)
    # janela clara
    wx0, wy0, wx1, wy1 = int(1180 * s), int(110 * s), int(1520 * s), int(470 * s)
    img[wy0:wy1, wx0:wx1] = _srgb_to_lin((48, 40, 36))
    img[wy0 + int(14 * s):wy1 - int(14 * s), wx0 + int(14 * s):wx1 - int(14 * s)] = _srgb_to_lin((246, 240, 226))
    img[wy0:wy1, (wx0 + wx1) // 2 - int(7 * s):(wx0 + wx1) // 2 + int(7 * s)] = _srgb_to_lin((48, 40, 36))
    # lâmpadas com brilho
    for cx, cy, rad in ((1640, 300, 26), (1760, 520, 16), (1310, 600, 11), (980, 620, 7)):
        cx, cy, rad = cx * s, cy * s, rad * s
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        glow = np.exp(-(d / (rad * 3.2)) ** 2)[..., None] * _srgb_to_lin((255, 190, 120)) * 0.6
        img = img + glow
        img[d < rad] = 1.4
    # faixa de matiz
    hy0, hy1 = int(800 * s), int(860 * s)
    hue = (x[hy0:hy1] / w) * 6.0
    k = np.stack([(5 + hue) % 6, (3 + hue) % 6, (1 + hue) % 6], -1)
    rgb = 1 - np.clip(np.minimum(k, 4 - k), 0, 1)
    img[hy0:hy1] = _srgb_to_lin(rgb * 230 + 12)
    # rampa de cinza
    gy0, gy1 = int(900 * s), int(1000 * s)
    ramp = np.linspace(0, 1, w, dtype=np.float32)
    img[gy0:gy1] = (ramp ** 2.2)[None, :, None]
    out = (_lin_to_srgb(img) * 255.0 + 0.5).astype(np.uint8)
    return np.ascontiguousarray(out)
