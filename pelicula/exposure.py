"""Zebra e falsa cor da prévia (1.6): a exposição em stops em relação ao cinza de 18%, só para ver.

A luz medida é a da cena como o look a decodifica (`Engine.scene_light`: o passo base do look — a curva do
perfil de entrada `toLinear`, o gamut, a exposição e o balanço; no modo Edição sem película, a montagem lida
pelo perfil escolhido no look, `decode_values`). Nada disso entra na receita do quadro: estas funções só
desenham a camada da tela (`ui/preview_tools.py`).

- `stops(luz)`: `log2(Y / 0,18)`, com Y a luminância Rec.709 da luz linear (0 = cinza médio, +1 = o dobro).
- `false_color(stops)`: faixas de cor (`BANDS`) e o resto em cinza pela própria exposição.
- `zebra(stops, limite)`: listras diagonais onde a exposição passa do limite (`ZEBRA_LEVELS`), na posição do
  pixel (o mesmo quadro dá sempre as mesmas listras).
"""

from __future__ import annotations

import numpy as np

from .i18n import N_

GRAY = 0.18
W709 = np.array([0.2126, 0.7152, 0.0722])

# (de, até, cor RGB, nome) em stops; fora das faixas, cinza.
BANDS: tuple[tuple[float, float, tuple[float, float, float], str], ...] = (
    (-np.inf, -6.0, (0.42, 0.16, 0.62), N_("Preto (abaixo de −6)")),
    (-6.0, -4.5, (0.12, 0.36, 0.95), N_("Sombra profunda (−6 a −4,5)")),
    (-0.25, 0.25, (0.20, 0.78, 0.30), N_("Cinza médio de 18% (±0,25)")),
    (0.75, 1.25, (0.96, 0.45, 0.66), N_("Pele clara, +1 stop (+0,75 a +1,25)")),
    (4.5, 6.0, (0.98, 0.85, 0.15), N_("Quase estourado (+4,5 a +6)")),
    (6.0, np.inf, (0.92, 0.15, 0.12), N_("Estourado (acima de +6)")),
)
GRAY_RANGE = (-6.0, 6.0)   # o cinza do resto vai do escuro (−6) ao claro (+6)
ZEBRA_LEVELS = (2.5, 4.5, 6.0)
ZEBRA_DEFAULT = 4.5
ZEBRA_ALPHA = 0.85


def stops(lin) -> np.ndarray:
    """Exposição (stops em relação ao cinza de 18%) de cada pixel da luz linear (… × 3)."""
    y = np.asarray(lin, dtype=np.float64)[..., :3] @ W709
    return np.log2(np.maximum(y, 1e-9) / GRAY)


def false_color(st, cover=None) -> np.ndarray:
    """RGBA (… × 4) da falsa cor: as faixas de `BANDS` e o resto em cinza. `cover`: quanto do pixel é imagem."""
    st = np.asarray(st, dtype=np.float64)
    g = np.clip((st - GRAY_RANGE[0]) / (GRAY_RANGE[1] - GRAY_RANGE[0]), 0.0, 1.0) * 0.8 + 0.08
    rgb = np.repeat(g[..., None], 3, axis=-1)
    for lo, hi, color, _name in BANDS:
        sel = (st >= lo) & (st < hi)
        rgb[sel] = color
    a = np.ones(st.shape) if cover is None else np.clip(np.asarray(cover, dtype=np.float64), 0.0, 1.0)
    return np.concatenate([rgb, a[..., None]], axis=-1)


def band_of(stop: float) -> int | None:
    """O índice da faixa de `BANDS` de uma exposição (None = cinza)."""
    for i, (lo, hi, _c, _n) in enumerate(BANDS):
        if lo <= stop < hi:
            return i
    return None


def zebra(st, level: float = ZEBRA_DEFAULT, cover=None) -> np.ndarray:
    """RGBA (h × w × 4) com listras pretas e brancas onde a exposição é `level` ou mais."""
    st = np.asarray(st, dtype=np.float64)
    h, w = st.shape[:2]
    period = max(4, int(round(h / 90.0)))
    y, x = np.mgrid[0:h, 0:w]
    stripe = ((x + y) // period) % 2 == 0
    rgb = np.where(stripe[..., None], 1.0, 0.0) * np.ones((h, w, 3))
    over = st >= level
    a = np.where(over, ZEBRA_ALPHA, 0.0)
    if cover is not None:
        a = a * np.clip(np.asarray(cover, dtype=np.float64), 0.0, 1.0)
    return np.concatenate([rgb, a[..., None]], axis=-1)


def decode_values(values: dict | None) -> dict:
    """Ajustes do look só com a leitura da entrada (perfil, faixa, exposição e balanço) e nenhum efeito: a luz
    que a zebra e a falsa cor medem no modo Edição sem película. Os ajustes novos da seção "Entrada e exposição"
    (de qualquer versão) vêm junto."""
    from . import params
    out = params.defaults()
    v = values or {}
    entrada = next(s for s in params.SECTIONS if s.key == "entrada")
    for p in entrada.params:
        if p.key in v:
            out[p.key] = v[p.key]
    out["bitola_vinheta"] = 0.0  # a vinheta natural da bitola também é efeito
    return out
