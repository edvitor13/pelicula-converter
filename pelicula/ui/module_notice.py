"""Aviso discreto da janela: o projeto ou o look usa recursos desligados (Configurações › Recursos).

A renderização nunca consulta `modules`, então a imagem e a exportação não mudam; a faixa só
diz quais ferramentas estão escondidas e oferece religá-las ("Ligar") ou fechar o aviso.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton

from .. import modules
from ..i18n import _
from . import icons, theme


def module_names(ids) -> str:
    """Nomes traduzidos dos módulos, na ordem do registro, separados por vírgula."""
    order = {m.id: i for i, m in enumerate(modules.MODULES)}
    known = sorted((m for m in ids if modules.exists(m)), key=order.get)
    return ", ".join(_(modules.get(m).name) for m in known)


class ModuleNotice(QFrame):
    """Faixa abaixo da barra do topo. `show_modules([])` esconde; os botões emitem os ids mostrados."""

    enableRequested = Signal(list)  # "Ligar": religar estes módulos
    dismissed = Signal(list)        # fechou o aviso sem religar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModuleNotice")
        self.setStyleSheet(f"QFrame#ModuleNotice {{ background: {theme.PANEL2}; border: none;"
                           f" border-bottom: 1px solid {theme.BORDER}; }}")
        self.ids: list[str] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 5, 10, 5)
        lay.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.icon("eye_off", theme.ACCENT, 16).pixmap(16, 16))
        lay.addWidget(icon)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.btn_on = QPushButton(_("Ligar"))
        self.btn_on.setToolTip(_("Ligar de novo estes recursos (Configurações › Recursos)"))
        self.btn_on.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_on.setStyleSheet("QPushButton { padding: 3px 14px; }")
        self.btn_on.clicked.connect(lambda: self.enableRequested.emit(list(self.ids)))
        lay.addWidget(self.btn_on)
        self.btn_close = QToolButton()
        self.btn_close.setObjectName("Flat")
        self.btn_close.setIcon(icons.icon("close", theme.MUTED, 14))
        self.btn_close.setIconSize(QSize(14, 14))
        self.btn_close.setToolTip(_("Fechar o aviso"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self._dismiss)
        lay.addWidget(self.btn_close)
        self.setVisible(False)

    def show_modules(self, ids) -> None:
        """Mostra o aviso para estes módulos (lista vazia esconde)."""
        self.ids = [m for m in ids if modules.exists(m)]
        if not self.ids:
            self.setVisible(False)
            return
        names = f"<b>{html.escape(module_names(self.ids))}</b>"
        main = _("Recursos desligados em uso: {lista}.").format(lista=names)
        detail = _("A imagem e a exportação não mudam; só as ferramentas ficam escondidas.")
        self.text.setText(f"{main} <span style='color:{theme.MUTED}'>{detail}</span>")
        self.setVisible(True)

    def _dismiss(self) -> None:
        ids = list(self.ids)
        self.setVisible(False)
        self.dismissed.emit(ids)
