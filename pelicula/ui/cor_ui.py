"""Ferramentas de cor da 1.6 na janela: um ponto só de ligação com a `MainWindow`.

`install(win)` cria as camadas da prévia (`preview_tools.PreviewTools`), o cartão "Cor por planos"
(`planes_ui.PlanesUI`, módulo Beta "cor_planos"), as ferramentas de cor simples do inspetor do modo Edição
(`color_tools.ColorTools`, módulo "cor_simples") e os botões da prévia (zebra, falsa cor e referência,
`preview_tools.PreviewBar`, módulo "scopes"). A janela só chama `install`, `after_render` depois de cada
`render_now`, `module_tools` em `_module_tools` e `apply_modules` em `apply_modules`.
"""

from __future__ import annotations


def install(win) -> None:
    from . import planes_ui, preview_tools
    win.preview_tools = preview_tools.PreviewTools(win)
    cards = {c.section.key: c for c in win.cards}
    win.planes_ui = planes_ui.PlanesUI(win, cards["planos"])


def after_render(win, recipe) -> None:
    tools = getattr(win, "preview_tools", None)
    if tools is not None:
        tools.refresh(recipe)


def module_tools(win) -> dict[str, list]:
    cards = {c.section.key: c for c in win.cards}
    return {"cor_planos": [cards["planos"]]}


def apply_modules(win, on: set[str]) -> None:
    ui = getattr(win, "planes_ui", None)
    if ui is not None:
        ui.apply_module("cor_planos" in on)


def cancel_pick(win) -> bool:
    """Esc: cancela um conta-gotas ligado (True se havia um)."""
    if win.viewer.picking:
        win.viewer.cancel_pick()
        return True
    return False
