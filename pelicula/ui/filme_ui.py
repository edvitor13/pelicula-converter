"""Câmera, formato e montagem da 1.6 na janela: um ponto só de ligação com a `MainWindow`.

Os recursos são parâmetros comuns (os cartões do look e os do inspetor saem do esquema); aqui fica só o que some
quando o módulo é desligado (`module_tools`) e o que precisa de código de janela (`install`). A renderização nunca
consulta `modules`: um projeto que use um recurso desligado sai igual.

- "camera_cinema" (Beta): o cartão "Obturador de película" do look e o cartão "Manivela" do inspetor.
- "anamorfico" (Beta): o cartão "Lente anamórfica".
- "data_impressa" (Beta): o cartão "Data impressa".
"""

from __future__ import annotations

LOOK_CARDS = {"camera_cinema": ("obturador",), "anamorfico": ("anamorfico",), "data_impressa": ("data",)}
CLIP_CARDS = {"camera_cinema": ("manivela",)}


def install(win) -> None:
    """Nada a montar por enquanto além dos cartões do esquema."""


def module_tools(win) -> dict[str, list]:
    cards = {c.section.key: c for c in win.cards}
    insp = getattr(win, "inspector", None)
    vcards = {c.section.key: c for c in getattr(insp, "vcards", [])}
    out: dict[str, list] = {}
    for module_id, keys in LOOK_CARDS.items():
        out.setdefault(module_id, []).extend(cards[k] for k in keys if k in cards)
    for module_id, keys in CLIP_CARDS.items():
        out.setdefault(module_id, []).extend(vcards[k] for k in keys if k in vcards)
    return out


def apply_modules(win, on: set[str]) -> None:
    """Casos especiais além de esconder as ferramentas (nenhum por enquanto)."""
