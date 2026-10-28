"""Mostrar transparência na tela: o quadro RGBA sobre um xadrez (prévia, miniaturas da Mídia, prévia da exportação).

Só para ver: o que é gravado nunca passa por aqui. Numpy puro (sem Qt), 8 bits na saída.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

CELL = 8                       # lado de cada casa do xadrez (px da tela)
LIGHT, DARK = 0x99, 0x66       # cinzas das casas


@lru_cache(maxsize=8)
def checker(w: int, h: int, cell: int = CELL) -> np.ndarray:
    """Xadrez h × w × 3 (uint8, só leitura)."""
    yy, xx = np.indices((h, w))
    board = np.where(((yy // cell) + (xx // cell)) % 2 == 0, LIGHT, DARK).astype(np.uint8)
    out = np.repeat(board[:, :, None], 3, axis=2)
    out.setflags(write=False)
    return out


def to8(img: np.ndarray) -> np.ndarray:
    return img if img.dtype == np.uint8 else (img >> 8).astype(np.uint8)


def over_checker(rgba: np.ndarray, premultiplied: bool = False, cell: int = CELL) -> np.ndarray:
    """RGBA (8 ou 16 bits; cor direta ou `premultiplied`) sobre o xadrez → RGB 8 bits. 3 canais passam direto."""
    img = to8(rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        return np.ascontiguousarray(img)
    h, w = img.shape[:2]
    a = img[..., 3:4].astype(np.uint32)
    rgb = img[..., :3].astype(np.uint32)
    bg = checker(w, h, cell).astype(np.uint32)
    if premultiplied:
        out = rgb + (bg * (255 - a) + 127) // 255
    else:
        out = (rgb * a + bg * (255 - a) + 127) // 255
    return np.minimum(out, 255).astype(np.uint8)
