"""Ferramentas de cor da 1.6 na janela: um ponto só de ligação com a `MainWindow`.

`install(win)` cria as camadas da prévia (`preview_tools.PreviewTools`), o cartão "Cor por planos"
(`planes_ui.PlanesUI`, módulo Beta "cor_planos"), as ferramentas de cor simples do inspetor do modo Edição
(`color_tools.ColorTools`, módulo "cor_simples") e os botões da prévia (zebra, falsa cor e referência,
`preview_bar.PreviewBar`, módulo "scopes"). A janela só chama `install`, `after_render` depois de cada
`render_now`, `module_tools` em `_module_tools` e `apply_modules` em `apply_modules`.
"""

from __future__ import annotations


def install(win) -> None:
    from . import color_tools, planes_ui, preview_bar, preview_tools
    win.preview_tools = preview_tools.PreviewTools(win)
    cards = {c.section.key: c for c in win.cards}
    win.planes_ui = planes_ui.PlanesUI(win, cards["planos"])       # camada "Ver planos" (por baixo)
    win.preview_bar = preview_bar.PreviewBar(win, win.preview_tools)  # falsa cor e zebra (por cima) e referência
    win.color_tools = color_tools.ColorTools(win)


def after_render(win, recipe) -> None:
    tools = getattr(win, "preview_tools", None)
    if tools is not None:
        tools.refresh(recipe)


def module_tools(win) -> dict[str, list]:
    cards = {c.section.key: c for c in win.cards}
    out = {"cor_planos": [cards["planos"]]}
    tools = getattr(win, "color_tools", None)
    if tools is not None:
        out["cor_simples"] = tools.module_tools()
    return out


def apply_modules(win, on: set[str]) -> None:
    ui = getattr(win, "planes_ui", None)
    if ui is not None:
        ui.apply_module("cor_planos" in on)
    tools = getattr(win, "color_tools", None)
    if tools is not None:
        tools.apply_module("cor_simples" in on)
    bar = getattr(win, "preview_bar", None)
    if bar is not None:  # zebra, falsa cor e referência fazem parte dos scopes (fora de `_module_tools`)
        bar.apply_module("scopes" in on)


def auto_whole_clip(win, cid: str) -> bool:
    """"Automático" do clipe inteiro (`color_tools.ColorTools.auto_whole_clip`); False = o do quadro atual."""
    tools = getattr(win, "color_tools", None)
    return tools is not None and tools.auto_whole_clip(cid)


def cancel_pick(win) -> bool:
    """Esc: cancela um conta-gotas ligado (True se havia um)."""
    if win.viewer.picking:
        win.viewer.cancel_pick()
        return True
    return False
