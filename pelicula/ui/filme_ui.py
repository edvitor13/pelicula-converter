"""Câmera, formato e montagem da 1.6 na janela: um ponto só de ligação com a `MainWindow`.

Os recursos são parâmetros comuns (os cartões do look e os do inspetor saem do esquema); aqui fica só o que some
quando o módulo é desligado (`module_tools`) e o que precisa de código de janela (`install`). A renderização nunca
consulta `modules`: um projeto que use um recurso desligado sai igual.

- "camera_cinema" (Beta): o cartão "Obturador de película" do look e o cartão "Manivela" do inspetor.
- "anamorfico" (Beta): o cartão "Lente anamórfica".
- "data_impressa" (Beta): o cartão "Data impressa".
- "montagem_pelicula" (Beta): o cartão "A montagem na película".
- "maquina_tempo" (estável): o botão "Máquina do tempo…" do painel de looks (modo Película; `ui/maquina_ui.py`).
"""

from __future__ import annotations

LOOK_CARDS = {"camera_cinema": ("obturador",), "anamorfico": ("anamorfico",), "data_impressa": ("data",),
              "montagem_pelicula": ("montagem_filme",)}
CLIP_CARDS = {"camera_cinema": ("manivela",)}


def install(win) -> None:
    """O botão da máquina do tempo no painel de looks (logo abaixo da busca)."""
    from PySide6.QtWidgets import QPushButton

    from ..i18n import _
    from . import maquina_ui
    win.btn_time_machine = QPushButton(_("Máquina do tempo…"))
    win.btn_time_machine.setToolTip(_("Um ano e onde o filme passava viram a bitola, o filme, a cor, o grão e o "
                                      "desgaste da época (um passo só de desfazer)"))
    win.btn_time_machine.clicked.connect(lambda: maquina_ui.open_dialog(win))
    lay = win.looks.layout()
    lay.insertWidget(lay.indexOf(win.looks.search) + 1, win.btn_time_machine)


def module_tools(win) -> dict[str, list]:
    cards = {c.section.key: c for c in win.cards}
    insp = getattr(win, "inspector", None)
    vcards = {c.section.key: c for c in getattr(insp, "vcards", [])}
    out: dict[str, list] = {}
    if getattr(win, "btn_time_machine", None) is not None:
        out["maquina_tempo"] = [win.btn_time_machine]
    for module_id, keys in LOOK_CARDS.items():
        out.setdefault(module_id, []).extend(cards[k] for k in keys if k in cards)
    for module_id, keys in CLIP_CARDS.items():
        out.setdefault(module_id, []).extend(vcards[k] for k in keys if k in vcards)
    return out


def apply_modules(win, on: set[str]) -> None:
    """Casos especiais além de esconder as ferramentas (nenhum por enquanto)."""
