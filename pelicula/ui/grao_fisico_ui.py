"""Grão físico na janela (1.6, módulo Beta "grao_fisico", `pelicula/grao_fisico.py`).

O controle é um ajuste comum do look (`lab_grao_modelo`, na seção Laboratório), então o cartão já o mostra; o módulo
só decide se a linha aparece. Desligado, a linha some e um projeto ou preset com o modelo físico sai igual (a
renderização nunca consulta `modules`; a janela avisa por `modules.used_by`). A janela só chama `module_tools` em
`_module_tools`.
"""

from __future__ import annotations

KEY = "lab_grao_modelo"


def row(cards) -> object | None:
    """A linha do "Modelo do grão no negativo" entre os cartões das seções (None se não existir)."""
    for card in cards:
        for r in card.rows:
            if r.param.key == KEY:
                return r
    return None


def module_tools(win) -> dict[str, list]:
    r = row(win.cards)
    return {"grao_fisico": [r]} if r is not None else {}
