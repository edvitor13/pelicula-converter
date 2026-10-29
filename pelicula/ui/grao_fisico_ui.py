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


EXTRA_KEYS = ("lab_grao_cristal", "lab_grao_variacao")  # 1.6 (fase 3): só valem no modelo físico


def module_tools(win) -> dict[str, list]:
    r = row(win.cards)
    rows = [r] if r is not None else []
    rows += [x for card in win.cards for x in card.rows if x.param.key in EXTRA_KEYS]
    return {"grao_fisico": rows} if rows else {}
