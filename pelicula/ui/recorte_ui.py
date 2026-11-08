"""1.9, recorte por cor ou pelo brilho na interface (#68; ARQUITETURA §50): o cartão "Recorte (chroma/luma)" do
inspetor do clipe (módulo Beta `recorte_mascaras`) com o conta-gotas da cor do fundo.

Ligado por `vfx_ui.FRONT_UIS` (`install(vfx_ui)`). O conta-gotas usa `VfxUI.pick_point` e lê a cor **do arquivo** no
ponto clicado (`ColorTools.clip_color_at`, o mesmo do conta-gotas da cor simples): a cor que o recorte compara é a da
imagem do clipe, antes da cor do clipe e do look. Escolher a cor troca o tipo para "Uma cor escolhida" (um passo do
desfazer).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .. import recorte
from ..i18n import _
from ..timeline import VIDEO
from . import icons, sem_efeitos_ui, theme

SECTION = "recorte"


class RecorteUI:
    def __init__(self, vfxui):
        self.vfx = vfxui
        self.win = vfxui.win
        self.card = vfxui.add_section(SECTION, recorte.MODULE, after="transformar")
        self.btn_pick = QToolButton()
        self.btn_pick.setObjectName("recorte_conta_gotas")
        self.btn_pick.setText(_("Conta-gotas do fundo"))
        self.btn_pick.setIcon(icons.icon("eyedropper", theme.ACCENT_HI, 14))
        self.btn_pick.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_pick.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pick.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_pick.setToolTip(_("Clique no fundo na prévia: o recorte passa a tirar essa cor (Esc cancela)"))
        self.btn_pick.clicked.connect(self.start_pick)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 2, 0, 4)
        hl.addWidget(self.btn_pick)
        hl.addStretch(1)
        self.card.body.layout().insertWidget(0, row)

    def start_pick(self) -> None:
        win = self.win
        c = win.inspector.current_clip()
        if c is None or c.kind != VIDEO:
            return
        if sem_efeitos_ui.refuses_tool(win):
            return
        tools = getattr(win, "color_tools", None)
        if tools is None or tools.is_nested(c):
            win.statusBar().showMessage(_("Não vale para um clipe de sequência: use nos clipes de dentro dela."),
                                        6000)
            return
        win.statusBar().showMessage(_("Clique no fundo que deve sair (Esc cancela)."), 6000)
        self.vfx.pick_point(self.picked)

    def picked(self, fx: float, fy: float) -> bool:
        """O clique do conta-gotas: acerta `chave_cor` e o tipo "cor" num passo do desfazer. True se acertou."""
        win = self.win
        status = win.statusBar()
        tools = getattr(win, "color_tools", None)
        c, rgb = tools.clip_color_at(fx, fy) if tools is not None else (None, None)
        if c is None or rgb is None:
            status.showMessage(_("Clique dentro do clipe selecionado, no quadro do cursor."), 6000)
            return False
        color = recorte.picked_color(rgb)
        if color is None:
            status.showMessage(_("Essa cor é quase cinza: clique no fundo verde, azul ou de outra cor."), 6000)
            return False
        vals = dict(c.values)
        vals.update(chave_tipo="cor", chave_cor=list(color))
        win.model.set_clip_values(c.id, vals)
        self.card.set_expanded(True)
        status.showMessage(_("Cor do fundo escolhida: acerte a tolerância e a suavidade se sobrar fundo."), 6000)
        return True


def install(vfxui) -> RecorteUI:
    return RecorteUI(vfxui)
