"""Luz por plano e fotômetro da película (1.6) na janela: um ponto só de ligação com a `MainWindow`.

- Marcação de luz por plano (`ui/luz_plano_ui.py`): o painel do cartão "Luz da copiadora" do inspetor e os atalhos
  Alt+R/G/B/D (com Shift: menos). Faz parte do módulo "laboratorio" (some com ele).
- Fotômetro da película (`ui/fotometro_ui.py`, módulo Beta "fotometro"): o botão da barra da prévia, a latitude e a
  camada (`preview_tools`), só na tela.

A janela só chama `install` (depois de `cor_ui.install`, que cria as camadas da prévia, e do inspetor),
`module_tools` em `_module_tools` e `apply_modules` em `apply_modules`. A renderização nunca consulta `modules`.
"""

from __future__ import annotations


def install(win) -> None:
    from . import fotometro_ui, luz_plano_ui
    luz_plano_ui.install(win)
    tools = getattr(win, "preview_tools", None)
    win.film_meter = fotometro_ui.FilmMeter(win, tools) if tools is not None else None


def module_tools(win) -> dict[str, list]:
    meter = getattr(win, "film_meter", None)
    return {"fotometro": meter.module_tools()} if meter is not None else {}


def apply_modules(win, on: set[str]) -> None:
    from . import luz_plano_ui
    luz_plano_ui.apply_modules(win, on)
    meter = getattr(win, "film_meter", None)
    if meter is not None:
        meter.apply_module("fotometro" in on)
