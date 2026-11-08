"""A montagem comanda a película (1.6, módulo Beta "montagem_pelicula"): emendas nos cortes e rolos de Super 8.

Numa montagem de película de verdade, cada corte é uma emenda: a fita (ou o cimento) aparece no primeiro quadro
depois do corte, a junta pode pular na janela do projetor e deixar passar um clarão. E um rolo de Super 8 (50 pés,
3 600 quadros) dura 3 min 20 s a 18 qps ou 2 min 30 s a 24: no fim do rolo a luz vela a película, e a troca de rolo
dá um pulo. Aqui a montagem (o modo Edição) diz onde estão os cortes, quadro a quadro, e o look desenha os defeitos:

- `edit_info(seq, index, fps)`: em que quadro da saída estamos desde o último corte seco da faixa principal de vídeo
  (V1; o corte com transição não é emenda). `frame.Recipe.plan` calcula e passa a `look.build_plan(edit=...)`; sem
  montagem (modo Película com o arquivo direto) não há cortes, e só os rolos valem.
- `splice_visible`/`splice_frames` (1.8): em que cortes a fita aparece e em que quadros; o som de película
  (`somfilme`) põe o estalo nesses mesmos quadros. `roll_at`/`reel_jump`/`reel_frames` (1.8): o primeiro quadro de cada
  rolo novo de Super 8, o que pula na janela (`apply`); o som põe o estalo da troca de rolo nele.
- `apply(U, v, edit, frame, fps, scale)`: no plano do quadro. A emenda usa o desenho da "Emenda" dos defeitos
  (`u_splice`), o clarão soma exposição (`u_gain`), o pulo desloca o quadro (`u_shift`) e o velamento do fim do rolo
  usa o vazamento de luz (`u_leak*`) — nenhum programa novo na GPU.

Determinístico: tudo vem do número do quadro, do fps, dos instantes dos cortes e da semente. Os rolos contam o tempo
da saída (`frame / fps`), então valem nos dois modos. O plugin do DaVinci não tem a montagem (é tempo da linha do
tempo do app): fica documentado em docs/DAVINCI.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

ROLL_FRAMES = 3600         # 50 pés de Super 8 (72 quadros por pé)
FOG_END_S = 2.5            # o velamento cresce nos últimos segundos do rolo
FOG_START_S = 0.8          # e some no começo do rolo seguinte (a ponta que pegou luz ao carregar)
FLASH_STOPS = 2.2          # clarão no quadro da emenda com 100%
JUMP_PX = 16.0             # pulo da emenda com 100%, px@1080 (o segundo quadro pula 40% disso)


@dataclass(frozen=True)
class EditInfo:
    """O quadro da saída em relação ao último corte seco: `since` quadros depois dele (0 = o primeiro quadro do
    clipe novo; None = antes do primeiro corte) e o número do corte (`cut`, para as sementes)."""
    since: int | None
    cut: int = -1


def cut_times(seq) -> list[float]:
    """Instantes (s) dos cortes secos da faixa principal de vídeo (V1), em ordem."""
    from . import timeline
    fps = seq.fps or 24.0
    out = set()
    for c in seq.clips:
        if c.kind != timeline.VIDEO or c.track != 0 or c.start <= 0:
            continue
        if c.values.get("entrada_tipo", "corte") != "corte":
            continue
        out.add(c.start / fps)
    return sorted(out)


def edit_info(seq, index: int, fps: float) -> EditInfo:
    if seq is None:
        return EditInfo(None)
    t = index / fps if fps else 0.0
    cuts = cut_times(seq)
    last = -1
    for i, c in enumerate(cuts):
        if c <= t + 1e-9:
            last = i
        else:
            break
    if last < 0:
        return EditInfo(None)
    since = int(math.floor((t - cuts[last]) * fps + 1e-6))
    return EditInfo(since, last)


def roll_length_s(v: dict) -> float:
    return ROLL_FRAMES / float(v.get("rolo_cadencia", "18"))


def roll_at(v: dict, frame: int, fps: float) -> tuple[int, float]:
    """O rolo do quadro da saída (0 = o primeiro) e o tempo (s) desde o começo dele."""
    L = roll_length_s(v)
    t = frame / fps
    roll = int(math.floor(t / L + 1e-9))
    return roll, t - roll * L


def reel_jump(v: dict, frame: int, fps: float) -> bool:
    """1.8: o quadro é o primeiro do rolo novo, o que pula na janela do projetor na troca de rolo (`apply`)."""
    roll, tr = roll_at(v, frame, fps)
    return roll > 0 and tr * fps < 0.5


def reel_frames(v: dict, fps: float, first: int, end: int) -> list[int]:
    """1.8: os quadros de [first, end) em que a troca de rolo de Super 8 pula na imagem (`reel_jump` com "Rolos de
    Super 8" ligado), para o som de película pôr o estalo no mesmo quadro (`somfilme.events_for`). Vazio com a seção
    ou os rolos desligados. A conta é a de `apply` (um quadro por troca, ou nenhum quando nenhum quadro cai na
    primeira meia duração de quadro do rolo novo)."""
    if not v.get("mfilme_on") or not v.get("rolo_on") or end <= first:
        return []
    fps = fps or 24.0
    L = roll_length_s(v)
    out = []
    k = max(1, int(math.floor(max(0, first) / fps / L)))
    while True:
        guess = math.ceil(k * L * fps - 1e-6)
        if guess - 1 >= end:
            break
        for f in (guess - 1, guess, guess + 1):  # o primeiro quadro do rolo k pela conta de `apply`
            if f >= 0 and roll_at(v, f, fps)[0] == k and reel_jump(v, f, fps):
                if first <= f < end:
                    out.append(f)
                break
        k += 1
    return out


def _hash(i: int, s: int) -> float:
    from .look import _hash as h
    return h(i, s)


def splice_visible(v: dict, cut: int) -> bool:
    """Se a fita da emenda aparece no primeiro quadro depois do corte `cut` ("Emendas visíveis" e a semente)."""
    return _hash(cut, int(v.get("mfilme_semente", 7)) + 601) < float(v["mfilme_emenda"])


def splice_frames(seq, v: dict, fps: float, first: int, end: int) -> list[int]:
    """1.8: os quadros de [first, end) em que a imagem mostra a fita da emenda de um corte (`apply` com
    `edit_info(...).since == 0` e `splice_visible`), para o som de película pôr o estalo no mesmo quadro
    (`somfilme`). Vazio com a seção desligada ou sem montagem."""
    if seq is None or not v.get("mfilme_on") or end <= first:
        return []
    fps = fps or 24.0
    out = []
    for k, c in enumerate(cut_times(seq)):
        if not splice_visible(v, k):
            continue
        guess = math.ceil(c * fps - 1e-6)
        for f in (guess - 1, guess, guess + 1):  # o primeiro quadro do corte pela conta de `edit_info`
            e = edit_info(seq, f, fps)
            if f >= 0 and e.since == 0 and e.cut == k:
                if first <= f < end:
                    out.append(f)
                break
    return out


def apply(U: dict[str, Any], v: dict, edit: EditInfo | None, frame: int, fps: float, scale: float) -> None:
    """Os defeitos da montagem no plano do quadro (nada com a seção desligada)."""
    if not v.get("mfilme_on"):
        return
    fps = fps or 24.0
    sd = int(v.get("mfilme_semente", 7))
    gain = list(U["u_gain"])
    sx, sy = U["u_shift"]
    if edit is not None and edit.since is not None and edit.since <= 1:
        k = edit.cut
        first = edit.since == 0
        if first and splice_visible(v, k):
            U["u_splice"] = (1.0, 0.1 + 0.8 * _hash(k, sd + 602))
        flash = float(v["mfilme_clarao"]) * FLASH_STOPS * (1.0 if first else 0.3)
        if flash > 0:
            gain = [gain[0] + flash, gain[1] + flash * 0.9, gain[2] + flash * 0.75]  # a luz quente da lâmpada
        jump = float(v["mfilme_salto"]) * JUMP_PX * scale * (1.0 if first else 0.4)
        sy += jump * (1.0 if _hash(k, sd + 603) < 0.7 else -1.0)
    if v.get("rolo_on"):
        L = roll_length_s(v)
        roll, tr = roll_at(v, frame, fps)
        fog = 0.0
        if tr > L - FOG_END_S:
            fog = ((tr - (L - FOG_END_S)) / FOG_END_S) ** 2
        if roll > 0 and tr < FOG_START_S:
            fog = max(fog, (1.0 - tr / FOG_START_S) ** 2)
            if tr * fps < 0.5:  # o primeiro quadro do rolo novo pula (`reel_jump`)
                sy += JUMP_PX * 1.4 * scale
        fog *= float(v["rolo_velamento"])
        if fog > 0:
            U["u_leak_on"] = 1
            U["u_leak_amt"] = max(float(U.get("u_leak_amt", 0.0)) if U.get("u_leak_on") else 0.0, 2.2 * fog)
            U["u_leak_color"] = tuple(float(c) for c in v["rolo_cor"])
            side = 0.0 if _hash(roll, sd + 610) < 0.5 else 1.0
            U["u_leak0"] = (side, 0.5, 0.75 + 0.6 * fog, 1.0)
            U["u_leak1"] = (1.0 - side, 0.2 + 0.6 * _hash(roll, sd + 611), 0.4 + 0.5 * fog, 0.6 * fog)
            gain = [g + 0.6 * fog for g in gain]
    U["u_gain"] = tuple(gain)
    U["u_shift"] = (sx, sy)
    if U["u_splice"][0] > 0:
        U["u_dmg_on"] = 1
