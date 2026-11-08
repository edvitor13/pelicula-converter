"""Música na montagem (1.8, ARQUITETURA §46; sem Qt): as batidas de um arquivo no tempo da sequência, o plano para
encaixar uma música numa duração (cortando ou repetindo compassos inteiros) e o plano de abaixar a música sob a voz
(chaves de volume comuns). Nada aqui mexe na sequência sem que se peça (`apply_fit`, `apply_duck`); a interface roda
essas funções dentro de `TimelineModel.apply_edit` (um passo do desfazer).
"""

from __future__ import annotations

from typing import Iterable

from . import batidas, timeline
from .timeline import AUDIO


# ------------------------------------------------------------------ batidas no tempo da sequência
def beat_frames(seq: timeline.Sequence, clip: timeline.Clip, beats: batidas.Beats) -> list[tuple[float, bool]]:
    """[(quadro da sequência, é começo de compasso)] das batidas que o clipe toca, pelo tempo do clipe (aparar,
    velocidade e, com rampa ou reverso, o mapa exato `TimeMap.out_at`). Quadro congelado: nenhuma."""
    if clip.frozen or not beats.times:
        return []
    fps = seq.fps
    downs = set(round(t, 6) for t in beats.downbeats)
    m = seq.time_map(clip) if clip.retimed else None
    out = []
    for t in beats.times:
        x = m.out_at(t) if m is not None else (t - clip.src_in) / clip.speed
        f = clip.start + x * fps
        if clip.start - 1e-6 <= f < clip.end - 1e-6:
            out.append((f, round(t, 6) in downs))
    out.sort()
    return out


def snap_frames(seq: timeline.Sequence, beats_of, exclude: Iterable[str] = ()) -> set[int]:
    """Quadros (inteiros) das batidas de todos os clipes de som com batidas conhecidas (`beats_of(caminho)` → Beats ou
    None), menos os clipes de `exclude` (os que estão sendo arrastados)."""
    skip = set(exclude)
    pts: set[int] = set()
    for c in seq.clips:
        if c.kind != AUDIO or c.id in skip:
            continue
        b = beats_of(c.src)
        if b is not None:
            pts.update(int(round(f)) for f, _down in beat_frames(seq, c, b))
    return pts


__all__ = ["beat_frames", "snap_frames"]
