"""Data impressa (1.6, módulo Beta "data_impressa"): a data laranja das câmeras compactas e de vídeo dos anos 80/90.

As câmeras com data (o "quartz date" das compactas de 35 mm) acendiam um mostrador de sete segmentos atrás do
filme e expunham os números direto no negativo, no canto do quadro. Por isso a data é luz da cena no passo BASE
(`shaders.dateMask`, somada depois da vinheta e antes de tudo o que vem da película): passa pela halação (o brilho
alaranjado em volta dos números), pela cor do negativo e da cópia, e o grão fica por cima, como na foto de verdade.
O desenho é procedural (segmentos com bordas suaves, sem fonte nem imagem), em px@1080 do quadro da câmera: o
mesmo lugar e o mesmo tamanho em qualquer resolução. Com o anamórfico desespremido, a data fica no quadro da
câmera (dentro da caixa de letra).

Nada de relógio: a data é um parâmetro (ano, mês e dia), o quadro sai igual em qualquer dia.
"""

from __future__ import annotations

from typing import Any

# segmentos a=1, b=2, c=4, d=8, e=16, f=32, g=64 (sentido horário a partir do topo; g = o do meio)
DIGITS = {"0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66, "5": 0x6D, "6": 0x7D, "7": 0x07, "8": 0x7F,
          "9": 0x6F, "'": 128, " ": 0}
ADVANCE = {"'": 0.32, " ": 0.5}  # largura de cada glifo na altura do dígito; dígitos: DIGIT_ADVANCE
DIGIT_ADVANCE = 0.78
DIGIT_W = 0.56          # largura do desenho do dígito (o resto do avanço é o espaço até o próximo)
SLANT = 0.1             # itálico (o topo vai para a direita)
MAX_GLYPHS = 12
GAIN = 4.0              # intensidade 100% = 4 × a cor em luz linear (o mostrador estoura no negativo)

FORMATS = ("aa_mm_dd", "mm_dd_aa", "dd_mm_aa", "aaaa_mm_dd")
CORNERS = ("inf_dir", "inf_esq", "sup_dir", "sup_esq")


def text(v: dict) -> str:
    """O texto do mostrador: "'98 10 29" (aa mm dd), "10 29 '98", "29 10 '98" ou "1998 10 29"."""
    y = int(v.get("data_ano", 1998))
    m = int(v.get("data_mes", 1))
    d = int(v.get("data_dia", 1))
    yy = f"'{y % 100:02d}"
    fmt = v.get("data_formato", "aa_mm_dd")
    if fmt == "mm_dd_aa":
        return f"{m:02d} {d:02d} {yy}"
    if fmt == "dd_mm_aa":
        return f"{d:02d} {m:02d} {yy}"
    if fmt == "aaaa_mm_dd":
        return f"{y:04d} {m:02d} {d:02d}"
    return f"{yy} {m:02d} {d:02d}"


def _advance(ch: str) -> float:
    return ADVANCE.get(ch, DIGIT_ADVANCE)


def text_width(s: str) -> float:
    """Largura do desenho em alturas de dígito (do primeiro segmento ao último, com o itálico)."""
    x, right = 0.0, 0.0
    for ch in s:
        if ch == "'":
            right = x + 0.16
        elif ch != " ":
            right = x + DIGIT_W
        x += _advance(ch)
    return right + SLANT


def _camera_size(v: dict, width: int, height: int) -> tuple[float, float]:
    """O quadro da câmera em px@1080. Com o scan da película, o quadro do negativo (o anamórfico fica espremido nele,
    como num scan de verdade)."""
    from . import anamorfico
    if v.get("scan_on"):
        return width / height * 1080.0, 1080.0
    return anamorfico.output_aspect(v, width, height) * 1080.0, 1080.0


def layout(v: dict, width: int, height: int) -> tuple[float, float, float]:
    """(x, y, altura) do canto de cima à esquerda do texto, em px@1080 do quadro da câmera."""
    cw, ch = _camera_size(v, width, height)
    h = float(v.get("data_tamanho", 34.0))
    m = float(v.get("data_margem", 60.0))
    w = text_width(text(v)) * h
    corner = v.get("data_canto", "inf_dir")
    x = cw - m - w if corner.endswith("dir") else m
    y = ch - m - h if corner.startswith("inf") else m
    return x, y, h


def box_px(v: dict, width: int, height: int) -> tuple[float, float, float, float]:
    """A caixa do texto em pixels do quadro de saída (x0, y0, x1, y1; y para baixo), para os testes e a interface."""
    from . import anamorfico
    x, y, h = layout(v, width, height)
    cw, ch = _camera_size(v, width, height)
    top, bottom = anamorfico.image_box(v, width, height)
    sx, sy = width / cw, (bottom - top) / ch
    w = text_width(text(v)) * h
    return x * sx, top + y * sy, (x + w) * sx, top + (y + h) * sy


def uniforms(U: dict[str, Any], v: dict, width: int, height: int) -> None:
    if not v.get("data_on") or float(v.get("data_intensidade", 0.0)) <= 0.0:
        return
    from .look import display_to_lin
    s = text(v)[:MAX_GLYPHS]
    codes = [float(DIGITS.get(c, 0)) for c in s] + [0.0] * (MAX_GLYPHS - len(s))
    x, y, h = layout(v, width, height)
    U["u_date_on"] = 1
    U["u_date_box"] = (x, y, h, float(len(s)))
    U["u_date_g0"], U["u_date_g1"], U["u_date_g2"] = (tuple(codes[0:4]), tuple(codes[4:8]), tuple(codes[8:12]))
    gain = GAIN * float(v["data_intensidade"])
    U["u_date_col"] = tuple(c * gain for c in display_to_lin(v["data_cor"]))
