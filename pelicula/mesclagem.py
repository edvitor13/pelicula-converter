"""1.9, modos de mesclagem novos do clipe (ARQUITETURA §49.6): GLSL e referência em numpy. Sem GPU nem Qt.

Os sete modos de antes (`compositor.BLEND_IDS` 0 a 6) continuam no `blend()` do `editshaders.CLIP`, que tem o texto
fixo. Os novos (ids 7 em diante, na ordem das opções de `mesclagem` em `editparams.py`) vivem numa variante do
programa (`editshaders._with_blend`), usada só quando a camada traz `u_blend >= 7`: as montagens de sempre usam o
programa de sempre, bit a bit.

`b` é a tela embaixo (base) e `s` a cor do clipe, no código do vídeo (o que o `CLIP` mistura). Fórmulas da
especificação de composição do W3C (Compositing and Blending Level 1), com a luminância Rec.709 do app no lugar da
de lá; os modos que não fazem sentido fora de 0–1 cortam as entradas em 0–1 (como o "Sobrepor" de antes).
"""

from __future__ import annotations

import numpy as np

# id do modo (u_blend) → chave da opção (`editparams`, "mesclagem"); só acrescentar no fim, nunca renomear.
MODES = {7: "diferenca", 8: "exclusao", 9: "luz_suave", 10: "luz_forte", 11: "subtrair", 12: "dividir",
         13: "matiz", 14: "saturacao_m", 15: "cor", 16: "luminosidade"}
W709 = np.array([0.2126, 0.7152, 0.0722])

GLSL = """
// ---------------------------------------------------------------- 1.9: mesclagens novas (mesclagem.py)
float bxLum(vec3 c) { return dot(c, W709); }
vec3 bxClipColor(vec3 c) {
    float l = bxLum(c);
    float n = min(c.r, min(c.g, c.b));
    float x = max(c.r, max(c.g, c.b));
    if (n < 0.0) c = l + (c - l) * l / max(l - n, 1e-6);
    if (x > 1.0) c = l + (c - l) * (1.0 - l) / max(x - l, 1e-6);
    return c;
}
vec3 bxSetLum(vec3 c, float l) { return bxClipColor(c + (l - bxLum(c))); }
float bxSat(vec3 c) { return max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b)); }
vec3 bxSetSat(vec3 c, float s) {
    float mn = min(c.r, min(c.g, c.b));
    float mx = max(c.r, max(c.g, c.b));
    return mx > mn ? (c - mn) * s / (mx - mn) : vec3(0.0);
}
vec3 bxSoftD(vec3 b) {
    return mix(sqrt(b), ((16.0 * b - 12.0) * b + 4.0) * b, vec3(lessThanEqual(b, vec3(0.25))));
}
vec3 blendExtra(vec3 b, vec3 s) {
    vec3 bb = clamp(b, 0.0, 1.0);
    vec3 ss = clamp(s, 0.0, 1.0);
    if (u_blend == 7) return abs(b - s);
    if (u_blend == 8) return bb + ss - 2.0 * bb * ss;
    if (u_blend == 9) return mix(bb + (2.0 * ss - 1.0) * (bxSoftD(bb) - bb), bb - (1.0 - 2.0 * ss) * bb * (1.0 - bb),
                                 vec3(lessThanEqual(ss, vec3(0.5))));
    if (u_blend == 10) return mix(1.0 - 2.0 * (1.0 - bb) * (1.0 - ss), 2.0 * bb * ss, vec3(lessThanEqual(ss, vec3(0.5))));
    if (u_blend == 11) return max(b - s, vec3(0.0));
    if (u_blend == 12) {
        vec3 q = min(bb / max(ss, vec3(1e-5)), vec3(1.0));
        return mix(q, vec3(greaterThan(bb, vec3(0.0))), vec3(lessThanEqual(ss, vec3(0.0))));
    }
    if (u_blend == 13) return bxSetLum(bxSetSat(ss, bxSat(bb)), bxLum(bb));
    if (u_blend == 14) return bxSetLum(bxSetSat(bb, bxSat(ss)), bxLum(bb));
    if (u_blend == 15) return bxSetLum(ss, bxLum(bb));
    if (u_blend == 16) return bxSetLum(bb, bxLum(ss));
    return s;
}
vec3 blend(vec3 b, vec3 s) { return u_blend >= 7 ? blendExtra(b, s) : blendBase(b, s); }
"""


# ------------------------------------------------------------------ referência em numpy
def _lum(c: np.ndarray) -> np.ndarray:
    return (c * W709).sum(-1, keepdims=True)


def _clip_color(c: np.ndarray) -> np.ndarray:
    lum = _lum(c)
    n = c.min(-1, keepdims=True)
    x = c.max(-1, keepdims=True)
    c = np.where(n < 0, lum + (c - lum) * lum / np.maximum(lum - n, 1e-6), c)  # o máximo é o de antes, como no GLSL
    return np.where(x > 1, lum + (c - lum) * (1 - lum) / np.maximum(x - lum, 1e-6), c)


def _set_lum(c: np.ndarray, lum: np.ndarray) -> np.ndarray:
    return _clip_color(c + (lum - _lum(c)))


def _sat(c: np.ndarray) -> np.ndarray:
    return c.max(-1, keepdims=True) - c.min(-1, keepdims=True)


def _set_sat(c: np.ndarray, s: np.ndarray) -> np.ndarray:
    mn = c.min(-1, keepdims=True)
    mx = c.max(-1, keepdims=True)
    return np.where(mx > mn, (c - mn) * s / np.where(mx > mn, mx - mn, 1.0), 0.0)


def apply(mode: str, b: np.ndarray, s: np.ndarray) -> np.ndarray:
    """O modo `mode` (chave da opção) com a base `b` e o clipe `s` (h × w × 3, float). Mesma conta do GLSL."""
    b = np.asarray(b, dtype=np.float64)
    s = np.asarray(s, dtype=np.float64)
    bb, ss = np.clip(b, 0, 1), np.clip(s, 0, 1)
    if mode == "diferenca":
        return np.abs(b - s)
    if mode == "exclusao":
        return bb + ss - 2 * bb * ss
    if mode == "luz_suave":
        d = np.where(bb <= 0.25, ((16 * bb - 12) * bb + 4) * bb, np.sqrt(bb))
        return np.where(ss <= 0.5, bb - (1 - 2 * ss) * bb * (1 - bb), bb + (2 * ss - 1) * (d - bb))
    if mode == "luz_forte":
        return np.where(ss <= 0.5, 2 * bb * ss, 1 - 2 * (1 - bb) * (1 - ss))
    if mode == "subtrair":
        return np.maximum(b - s, 0.0)
    if mode == "dividir":
        q = np.minimum(bb / np.maximum(ss, 1e-5), 1.0)
        return np.where(ss <= 0, (bb > 0).astype(np.float64), q)
    if mode == "matiz":
        return _set_lum(_set_sat(ss, _sat(bb)), _lum(bb))
    if mode == "saturacao_m":
        return _set_lum(_set_sat(bb, _sat(ss)), _lum(bb))
    if mode == "cor":
        return _set_lum(ss, _lum(bb))
    if mode == "luminosidade":
        return _set_lum(bb, _lum(ss))
    return s
