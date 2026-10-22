"""Configurações › Recursos: ligar e desligar módulos e escolher um perfil (provisório)."""

from __future__ import annotations

from ...i18n import _
from ._base import PageBase


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Recursos"))
        self.finish()
