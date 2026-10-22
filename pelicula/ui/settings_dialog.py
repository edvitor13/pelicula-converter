"""Janela de Configurações: páginas numa barra lateral (Geral, Recursos, Componentes...).

Cada página é a classe `Page(dialog)` de um arquivo em `ui/pages/`, criada só quando aparece
pela primeira vez. A página lê e grava em `dialog.settings` e avisa a janela principal com
`dialog.settings_changed.emit(chave)` (ex.: "modulos" quando um recurso liga ou desliga).
Página nova: crie o arquivo em `ui/pages/` e acrescente uma linha em `PAGES`.
"""

from __future__ import annotations

import importlib

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..i18n import N_, _
from . import icons, theme

# (id, título, ícone, módulo com a classe Page)
PAGES = (
    ("geral", N_("Geral"), "settings", "pelicula.ui.pages.geral"),
    ("recursos", N_("Recursos"), "check", "pelicula.ui.pages.recursos"),
    ("componentes", N_("Componentes"), "folder", "pelicula.ui.pages.componentes"),
    ("notificacoes", N_("Notificações"), "volume", "pelicula.ui.pages.notificacoes"),
    ("recuperacao", N_("Recuperação"), "save", "pelicula.ui.pages.recuperacao"),
)


class SettingsDialog(QDialog):
    settings_changed = Signal(str)

    def __init__(self, parent, settings, page: str = "geral", main=None):
        super().__init__(parent)
        self.settings = settings
        self.main = main if main is not None else parent  # janela principal (pode ser None em testes)
        self.setWindowTitle(_("Configurações"))
        self.setWindowIcon(icons.app_icon())
        self.resize(900, 620)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(210)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setStyleSheet(
            f"QListWidget#SettingsNav {{ background: {theme.PANEL}; border: none; border-right: 1px solid {theme.BORDER};"
            f" padding: 12px 8px; outline: none; }}"
            f"QListWidget#SettingsNav::item {{ padding: 9px 10px; border-radius: 7px; margin: 1px 0; }}"
            f"QListWidget#SettingsNav::item:selected {{ background: {theme.PANEL3}; color: {theme.TEXT}; }}")
        for pid, title, icon, _module in PAGES:
            item = QListWidgetItem(icons.icon(icon, theme.TEXT, 18), _(title))
            item.setData(256, pid)
            self.nav.addItem(item)
        root.addWidget(self.nav)

        right = QVBoxLayout()
        right.setContentsMargins(22, 18, 22, 14)
        right.setSpacing(10)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(_("Fechar"))
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 1)

        self._pages: dict[str, QWidget] = {}
        self.nav.currentRowChanged.connect(self._show_row)
        self.show_page(page)

    def page_ids(self) -> list[str]:
        return [p[0] for p in PAGES]

    def show_page(self, page_id: str) -> None:
        ids = self.page_ids()
        self.nav.setCurrentRow(ids.index(page_id) if page_id in ids else 0)

    def page(self, page_id: str) -> QWidget:
        """A página (criada na primeira vez)."""
        w = self._pages.get(page_id)
        if w is None:
            module = next(p[3] for p in PAGES if p[0] == page_id)
            w = importlib.import_module(module).Page(self)
            self._pages[page_id] = w
            self.stack.addWidget(w)
        return w

    def _show_row(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentWidget(self.page(PAGES[row][0]))
