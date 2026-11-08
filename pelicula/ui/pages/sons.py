"""Configurações › Sons livres (1.8, módulo Beta "efeitos_sonoros"; ARQUITETURA §47): a chave da API do Freesound.

A busca de sons CC0 (`sons_cc0.py`, `ui/sons_cc0_ui.py`) usa o Openverse sem chave nenhuma; com a chave da API do
Freesound da própria pessoa, busca também lá. A chave fica nas preferências deste computador (`sons_cc0.KEY_FREESOUND`),
nunca no projeto, e aparece mascarada (o "Mostrar" a revela). Gravada na hora; nada vai para a rede daqui.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit

from ... import sons_cc0
from ...i18n import _
from ._base import PageBase
from ._module_box import ModuleOffBox


def freesound_key(settings) -> str:
    """A chave guardada (texto vazio se não há)."""
    return str(settings.value(sons_cc0.KEY_FREESOUND, "") or "").strip()


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Sons livres"),
                         _("A busca de sons CC0 (Mídia › Novo › Buscar sons) usa o Openverse, sem cadastro. Com a "
                           "chave da API do Freesound, busca também lá."))
        self.off_box = ModuleOffBox(self, "efeitos_sonoros",
                                    _("Os efeitos sonoros estão desligados: a busca de sons não aparece na Mídia."))
        self.body.addWidget(self.off_box)
        self.kicker(_("Freesound"))
        lab = QLabel(_("Chave da API do Freesound"))
        self.body.addWidget(lab)
        self.key = QLineEdit()
        self.key.setObjectName("freesound_chave")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(_("Cole aqui a chave (opcional)"))
        self.key.setText(freesound_key(self.settings))
        self.key.textChanged.connect(self._save)
        lab.setBuddy(self.key)
        self.body.addWidget(self.key)
        self.show_key = QCheckBox(_("Mostrar a chave"))
        self.show_key.toggled.connect(lambda on: self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.body.addWidget(self.show_key)
        how = QLabel(_("Para ter uma chave: crie uma conta grátis no Freesound e peça uma credencial de API em "
                       "<a href=\"{url}\">{url}</a> (o campo \"Client secret/Api key\" é a chave). Ela fica só neste "
                       "computador, nunca no projeto. O Freesound só entrega o arquivo original com login; a busca "
                       "baixa a prévia de alta qualidade (MP3).").format(url=sons_cc0.FREESOUND_KEY_HELP))
        how.setObjectName("Muted")
        how.setWordWrap(True)
        how.setOpenExternalLinks(True)
        self.body.addWidget(how)
        self.finish()
        self.refresh()

    def _save(self, text: str) -> None:
        self.settings.setValue(sons_cc0.KEY_FREESOUND, text.strip())
        self.dialog.settings_changed.emit(sons_cc0.KEY_FREESOUND)

    def refresh(self) -> None:
        self.off_box.refresh()
