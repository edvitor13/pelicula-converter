"""Configurações › Recuperação: cópias de segurança automáticas do projeto (provisório)."""

from __future__ import annotations

from ...i18n import _
from ._base import PageBase


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Recuperação"))
        self.finish()
