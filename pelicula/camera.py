"""Perfil de câmera por clipe no modo Edição (1.6, "Normalizar"): clipes de câmeras diferentes numa montagem só.

O look de película lê a montagem inteira com o perfil de entrada dele (`params` "entrada", com a faixa do arquivo e
o EI). Um clipe com o perfil "Igual ao do look" (o padrão, `FOLLOW`) entra na montagem como sempre, bit a bit. Um
clipe com um perfil próprio (`editparams` "camera_entrada") é convertido para o espaço do look antes dos ajustes
dele: a curva e o gamut do clipe → luz linear Rec.709 → o gamut e a curva da entrada do look (`editshaders.CAMERA`,
num passo antes do `CLIP`; o código de cor do `CLIP` não muda). Os ajustes de cor do clipe, as transições e o look
veem então todos os clipes no mesmo espaço, como se viessem da câmera do look.

Com algum clipe assim na sequência (`uses_profiles`), a montagem também passa a luz inteira ao look: os clipes de
log são lidos em ponto flutuante com os super-brancos (`media.float_input`), a tela da montagem (RGBA de 32 bits)
vai ao look em float32, sem cortar em 1,0 nem arredondar a 8 ou 16 bits (`Engine.compose(float_out=True)`).
Montagens sem perfil de clipe ficam exatamente como antes.

Funções puras (sem GPU nem Qt), como `compositor.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

FOLLOW = "look"  # "Igual ao do look": o clipe usa a entrada do look (como antes da 1.6)
KEYS = ("camera_entrada", "camera_reescalado", "camera_ei")


@dataclass(frozen=True)
class Target:
    """O espaço comum da montagem: a entrada do look (curva `id` de `look.input_id`, gamut `gamut` de
    `look.INPUT_GAMUT`) e se o look volta ao código de 10 bits (`cv`: curva "cv" num arquivo de faixa legal)."""
    id: int = 0
    cv: bool = False
    gamut: str = "709"


def clip_profile(values: dict[str, Any] | None) -> str | None:
    """O perfil próprio do clipe (uma chave de `params.ENTRADAS`), ou None se ele segue o look."""
    p = (values or {}).get("camera_entrada", FOLLOW)
    return None if p in (None, "", FOLLOW) else str(p)


def uses_profiles(seq) -> bool:
    """Algum clipe de vídeo da sequência tem perfil de câmera próprio? (liga a conversão e a tela em float)"""
    if seq is None:
        return False
    from . import timeline
    return any(c.kind == timeline.VIDEO and clip_profile(c.values) is not None for c in seq.clips)


def read_profile(values: dict[str, Any] | None) -> str | None:
    """O perfil para ler o arquivo do clipe (`media.FrameReader(profile=)`): o próprio dele, senão None (a leitura
    de sempre). Log de câmera em faixa legal vem em float32, com os super-brancos."""
    return clip_profile(values)


def target_of(look_values: dict[str, Any] | None, legal: bool) -> Target:
    """O espaço da entrada do look (`legal`: a faixa da montagem, `sequence.legal_range`). Sem look: Rec.709."""
    from . import look
    if not look_values:
        return Target()
    entrada = look_values.get("entrada", "rec709")
    cv = look.code_value_curve(entrada) and not look_values.get("log_reescalado") and bool(legal)
    return Target(look.input_id(look_values), bool(cv), look.INPUT_GAMUT.get(entrada, "709"))


def clip_values(values: dict[str, Any]) -> dict[str, Any]:
    """Os ajustes de entrada do clipe no formato do look ("entrada", "log_reescalado", "logc3_ei")."""
    return {"entrada": clip_profile(values) or "rec709", "log_reescalado": bool(values.get("camera_reescalado")),
            "logc3_ei": str(values.get("camera_ei", "800"))}


def uniforms(values: dict[str, Any], source, target: Target) -> dict[str, Any] | None:
    """Uniforms de `editshaders.CAMERA` para o clipe (`values`, os ajustes dele; `source`, a `timeline.Source`
    do arquivo, que dá a faixa), ou None se ele segue o look (nada muda)."""
    if clip_profile(values) is None:
        return None
    from . import look, media
    cv = clip_values(values)
    legal = bool(source is not None and source.has_video and media.legal_range(source))
    in_cv = look.code_value_curve(cv["entrada"]) and not cv["log_reescalado"] and legal
    to_look = np.linalg.inv(look.gamut_to_709(target.gamut))
    return {
        "u_cam_in": look.input_id(cv),
        "u_cam_in_cv": 1 if in_cv else 0,
        "u_cam_gamut": look.mat3_uniform(look.gamut_to_709(look.INPUT_GAMUT.get(cv["entrada"], "709"))),
        "u_cam_out": int(target.id),
        "u_cam_out_cv": 1 if target.cv else 0,
        "u_lut_gamut": look.mat3_uniform(to_look),
    }
