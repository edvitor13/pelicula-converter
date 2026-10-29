"""Marcação de luz por plano (1.6): os pontos da copiadora de cada plano da montagem.

No laboratório, o marcador de luz (o *color timer*) assiste ao negativo montado e escolhe, plano a plano, as luzes
vermelha, verde e azul da copiadora: o TAPE padrão do LAD é 25-25-25 (as luzes no alvo, Kodak H-61), e cada ponto
é 0,025 log E (12 pontos = 1 stop da cópia; cerca de 7 pontos = 1 stop da câmera). Aqui cada clipe de vídeo tem
os ajustes `luz_r`, `luz_g`, `luz_b` e `luz_densidade` (pontos; `editparams`, cartão "Luz da copiadora"), que
**somam** às luzes do Laboratório do look (`lab_luz_*`) nos quadros em que o clipe é o plano da V1.

- `shot_lights(seq, índice, fps)`: os pontos do plano no quadro `índice` da saída (o tempo é `índice / fps`, como
  em `montagem_filme.edit_info`), ou None quando nenhum clipe da montagem tem luz própria (o plano do look não muda
  um bit). O plano é o clipe da V1 que `timeline.Sequence.layers_at` mostra; clipes nas faixas de cima (V2…) não
  mudam o plano. Numa transição de dois clipes (o "dissolver" e as da 1.5 com a cauda do anterior por baixo:
  `editparams.EXTRA_TWO_CLIP`) as luzes vão de um plano ao outro pelo andamento da transição.
- `apply(valores, luzes)`: os ajustes do look com as luzes do plano somadas (uma cópia); sem luzes, os mesmos
  valores (o mesmo dicionário).

`frame.Recipe.plan` chama os dois com o Laboratório ligado e uma montagem, então a prévia, o "Salvar quadro", a
exportação e a linha de comando dão o mesmo quadro. Com o Laboratório desligado as luzes não fazem nada (o cartão
avisa). No modo Película com o arquivo direto não há planos (não há montagem): para marcar a luz por plano, divida
o clipe no modo Edição. O plugin do DaVinci não tem a montagem (o nó Laboratorio já tem as luzes da copiadora).

**Na transição.** Uma fusão ótica copia os dois negativos, cada um com a sua luz, um sobre o outro. Aqui a montagem
mistura as duas imagens antes do look, que tem uma luz só por quadro; então a luz é interpolada linearmente em
pontos (em log E, como a copiadora anda) pelo mesmo andamento da mistura: nas pontas da transição cada plano tem a
luz dele, exata, e no meio a luz caminha sem pulo.
"""

from __future__ import annotations

import math
from typing import Any

KEYS = ("luz_r", "luz_g", "luz_b", "luz_densidade")
LOOK_KEYS = ("lab_luz_r", "lab_luz_g", "lab_luz_b")
TAPE = 25                  # TAPE padrão do LAD (Kodak H-61): 25-25-25 = luzes no alvo
POINTS_PER_PRINT_STOP = 12  # 12 × 0,025 log E = 0,30 log E ≈ 1 stop da cópia (`look.LAB_POINT`)


def points(values: dict[str, Any] | None) -> tuple[float, float, float]:
    """Pontos R, G, B próprios de um clipe (a densidade soma nas três)."""
    v = values or {}
    d = float(v.get("luz_densidade", 0.0))
    return tuple(float(v.get(k, 0.0)) + d for k in KEYS[:3])


def has_lights(values: dict[str, Any] | None) -> bool:
    return any(float((values or {}).get(k, 0.0)) != 0.0 for k in KEYS)


def uses(seq) -> bool:
    """Algum clipe de vídeo da montagem tem luz própria."""
    from . import timeline
    return seq is not None and any(getattr(c, "kind", None) == timeline.VIDEO and has_lights(getattr(c, "values", None))
                                   for c in getattr(seq, "clips", ()))


def seq_frame(seq, index: int, fps: float) -> int:
    """O quadro da sequência que o quadro `index` da saída mostra (o mesmo de `sequence.SequenceReader`)."""
    sfps = seq.fps or fps or 24.0
    if not fps or abs(float(fps) - sfps) < 1e-9:
        return int(index)
    return int(math.floor(index * sfps / float(fps) + 1e-6))


def shot_at(seq, t: int) -> list[tuple[Any, dict, float]]:
    """O plano da V1 no quadro `t` da sequência: [(clipe, valores, peso)], com dois itens numa transição de dois
    clipes (o anterior com 1 − andamento e o que entra com o andamento) e nenhum sem clipe visível na V1."""
    from . import timeline
    layers = [L for L in seq.layers_at(t) if L.clip.kind == timeline.VIDEO and L.clip.track == 0]
    main = next((L for L in reversed(layers) if not L.extension), None)
    if main is None:
        return []
    vals = main.values if main.values is not None else main.clip.values
    base = next((L for L in layers if L.extension), None)
    if base is None:
        return [(main.clip, vals, 1.0)]
    k = next((tr.progress for tr in main.transitions if tr.role == "entra"), None)
    if k is None:  # o "dissolver" de antes (o mesmo andamento de `Sequence.layers_at`)
        pos = t - main.clip.start
        n = max(1, int(round(float(main.clip.values["entrada_dur"]) * seq.fps)))
        k = (pos + 1) / (n + 1)
    bvals = base.values if base.values is not None else base.clip.values
    k = min(max(float(k), 0.0), 1.0)
    return [(base.clip, bvals, 1.0 - k), (main.clip, vals, k)]


def shot_lights(seq, index: int, fps: float) -> tuple[float, float, float] | None:
    """Pontos da copiadora do plano no quadro `index` da saída (None = nenhum clipe com luz própria)."""
    if not uses(seq):
        return None
    out = [0.0, 0.0, 0.0]
    for _clip, values, w in shot_at(seq, seq_frame(seq, index, fps)):
        for i, p in enumerate(points(values)):
            out[i] += w * p
    return (out[0], out[1], out[2])


def apply(values: dict[str, Any], lights: tuple[float, float, float] | None) -> dict[str, Any]:
    """Os ajustes do look com as luzes do plano somadas às do Laboratório (sem luzes: o mesmo dicionário)."""
    if lights is None or not any(lights):
        return values
    out = dict(values)
    for k, d in zip(LOOK_KEYS, lights):
        out[k] = float(out.get(k, 0.0)) + float(d)
    return out


def classic(look_values: dict[str, Any] | None, clip_values: dict[str, Any] | None) -> tuple[float, float, float]:
    """As luzes do plano no mostrador clássico (TAPE 25-25-25 + luzes do look + densidade do look + as do clipe)."""
    v = look_values or {}
    d = float(v.get("lab_densidade", 0.0))
    own = points(clip_values)
    return tuple(TAPE + float(v.get(k, 0.0)) + d + o for k, o in zip(LOOK_KEYS, own))
