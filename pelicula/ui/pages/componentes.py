"""Configurações › Componentes: ferramentas externas baixadas e programas do sistema (provisório)."""

from __future__ import annotations

from ...i18n import _
from ._base import PageBase


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Componentes"))
        self.finish()
