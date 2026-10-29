"""Luz por plano e fotômetro da película (1.6) na janela: um ponto só de ligação com a `MainWindow`.

- Marcação de luz por plano (`ui/luz_plano_ui.py`): o painel do cartão "Luz da copiadora" do inspetor e os atalhos
  Ctrl+Alt+R/G/B/D (com Shift: menos). Faz parte do módulo "laboratorio" (some com ele).

A janela só chama `install` (depois de montar o inspetor), `module_tools` em `_module_tools` e `apply_modules` em
`apply_modules`. A renderização nunca consulta `modules`.
"""

from __future__ import annotations


def install(win) -> None:
    from . import luz_plano_ui
    luz_plano_ui.install(win)


def module_tools(win) -> dict[str, list]:
    return {}


def apply_modules(win, on: set[str]) -> None:
    from . import luz_plano_ui
    luz_plano_ui.apply_modules(win, on)
