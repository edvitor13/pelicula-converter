"""Aviso de módulo desligado no topo de uma página de Configurações, com o botão "Ligar".

Usado pelas páginas de recursos que são módulos (Notificações, Recuperação): com o módulo desligado a
página explica o que fica parado e oferece religar (`modules.set_enabled` + `settings_changed("modulos")`,
como a página Recursos). A página acompanha o estado por `refresh()` (também quando a página Recursos
muda o módulo com a janela aberta).
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ... import modules
from ...i18n import _
from .. import theme


class ModuleOffBox(QFrame):
    def __init__(self, page, module_id: str, text: str):
        super().__init__()
        self.page = page
        self.module_id = module_id
        self.setObjectName("ModuleOff")
        self.setStyleSheet(f"QFrame#ModuleOff {{ background: #2a1f10; border: 1px solid {theme.ACCENT_DIM};"
                           f" border-radius: 10px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self.text = QLabel(text)
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.btn = QPushButton(_("Ligar"))
        self.btn.setObjectName("Primary")
        self.btn.setToolTip(_("Liga este recurso (também dá para mudar em Configurações › Recursos)"))
        self.btn.clicked.connect(self.enable)
        lay.addWidget(self.btn)

    def module_on(self) -> bool:
        return modules.is_enabled(self.page.settings, self.module_id)

    def refresh(self) -> bool:
        """Mostra o aviso só com o módulo desligado. Devolve se o módulo está ligado."""
        on = self.module_on()
        self.setVisible(not on)
        return on

    def enable(self) -> None:
        modules.set_enabled(self.page.settings, self.module_id, True)
        self.page.dialog.settings_changed.emit("modulos")
        self.page.refresh()
