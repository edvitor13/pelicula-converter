"""Lente anamórfica (1.6, módulo Beta "anamorfico"): desespremer, risco de luz horizontal, barril e bordas macias.

Tudo no look (seção "anamorfico", desligada por padrão), pelo caminho único da prévia e da exportação:

- **Desespremer** (`anam_compressao`): o vídeo foi filmado com um adaptador anamórfico (1,33×, 1,5×, 1,8× ou 2×) e
  chega espremido na horizontal. A imagem é esticada na largura do quadro e, como o quadro de saída não muda de
  tamanho, aparece numa caixa de letra (faixas pretas em cima e embaixo): a proporção final é a do vídeo × a
  compressão (16:9 × 1,33 = 2,37:1). No BASE (`shaders.filmLight`), antes da vinheta: tudo o que vem depois
  (halação, grão, defeitos) vê o quadro já desespremido.
- **Barril horizontal** (`anam_barril`, o "mumps"): o centro da imagem estica um pouco na horizontal, mais na
  linha do meio do que em cima e embaixo, como nas lentes anamórficas de cilindro na frente.
- **Bordas macias** (`anam_bordas`): o desfoque horizontal cresce com o quadrado da distância do centro (até
  `EDGE_PX` px@1080 nas laterais).
- **Risco de luz** (`anam_flare`): as luzes fortes (acima do limiar em stops, como o bloom) espalham uma linha
  horizontal longa e colorida (azul, por padrão), uma cadeia como a do bloom só na horizontal
  (`Engine._streak`, cadeia "streak"). Fica na luz da cena, antes da cor do filme.

Com o scan da película ligado, a imagem fica espremida dentro do quadro do negativo, como num scan de verdade de
um negativo anamórfico (desespremer, barril e bordas valem só sem o scan; o risco de luz vale sempre).

Desligado, o plano é o de sempre (os uniforms só entram com o efeito; `look.SPARSE_UNIFORMS` e
`Engine.FINAL_NEUTRAL` mandam o neutro), e o BASE devolve a mesma conta, bit a bit.

O plugin do DaVinci não tem o anamórfico (o nó Textura do plugin não tem passos de desfoque horizontal longo nem
mudança de geometria): fica documentado em docs/DAVINCI.md.
"""

from __future__ import annotations

from typing import Any

SQUEEZES = {"nenhuma": 1.0, "1.33": 1.33, "1.5": 1.5, "1.8": 1.8, "2.0": 2.0}
EDGE_PX = 6.0          # maciez das bordas com 100%, px@1080 nas laterais
BARREL_MAX = 0.12      # estiramento do centro com 100%
STREAK_GAIN = 0.35     # intensidade do risco com 100%


def squeeze(v: dict) -> float:
    """A compressão da lente (1 = nenhuma) com a seção ligada."""
    if not v.get("anam_on"):
        return 1.0
    return SQUEEZES.get(str(v.get("anam_compressao", "nenhuma")), 1.0)


def output_aspect(v: dict, width: int, height: int) -> float:
    """Proporção da imagem visível (a caixa de letra) num quadro width × height."""
    return width / height * squeeze(v)


def image_box(v: dict, width: int, height: int) -> tuple[float, float]:
    """(topo, base) da imagem desespremida em linhas do quadro (o resto é preto)."""
    hh = height / squeeze(v)
    return (height - hh) / 2.0, (height + hh) / 2.0


def base_uniforms(U: dict[str, Any], v: dict) -> None:
    """`u_anam` (compressão, barril, bordas, ligado) só com a seção ligada e algo a fazer."""
    if not v.get("anam_on"):
        return
    s = squeeze(v)
    barrel = float(v.get("anam_barril", 0.0)) * BARREL_MAX
    edges = float(v.get("anam_bordas", 0.0)) * EDGE_PX
    if s == 1.0 and barrel == 0.0 and edges == 0.0:
        return
    U["u_anam"] = (s, barrel, edges, 1.0)


def streak(plan, U: dict[str, Any], v: dict, scale: float) -> None:
    """A cadeia "streak" (limiar em luz linear, comprimento em px da resolução atual) e os uniforms do FINAL."""
    if not v.get("anam_on") or float(v.get("anam_flare", 0.0)) <= 0.0:
        return
    from .look import Chain
    plan.chains.append(Chain("streak", 0.18 * 2 ** float(v["anam_flare_limiar"]),
                             float(v["anam_flare_comprimento"]) * scale, 8.0, True))
    U["u_streak_on"] = 1
    U["u_streak_amt"] = float(v["anam_flare"]) * STREAK_GAIN
    U["u_streak_col"] = tuple(float(c) for c in v["anam_flare_cor"])
