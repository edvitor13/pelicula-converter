"""Configurações › Geral: idioma, atualizações, tela de boas-vindas e pastas do usuário."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton

from ... import i18n, luts, presets, system
from ...i18n import _
from ..timeline_view import ZOOM_PLAYHEAD_KEY, zoom_playhead_tip
from ._base import PageBase


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Geral"), _("Idioma, atualizações e pastas do PeliculaConverter."))
        main = dialog.main

        self.kicker(_("Idioma"))
        row = QHBoxLayout()
        lang = QLabel(i18n.LANGUAGES.get(i18n.language(), i18n.language()))
        row.addWidget(lang)
        row.addStretch(1)
        btn_lang = QPushButton(_("Mudar idioma…"))
        btn_lang.setEnabled(main is not None and hasattr(main, "choose_language"))
        if btn_lang.isEnabled():
            btn_lang.clicked.connect(main.choose_language)
        row.addWidget(btn_lang)
        self.body.addLayout(row)

        self.kicker(_("Ao abrir"))
        self.chk_update = QCheckBox(_("Procurar atualizações automaticamente"))
        self.chk_update.setToolTip(_("Consulta o GitHub (app) e a fonte do ffmpeg ao abrir; nada é enviado "
                                     "além do pedido de versão"))
        self.chk_update.setChecked(str(self.settings.value("auto_update", "true")) != "false")
        self.chk_update.toggled.connect(self._set_update)
        self.body.addWidget(self.chk_update)
        self.chk_welcome = QCheckBox(_("Mostrar a tela de boas-vindas"))
        self.chk_welcome.setChecked(str(self.settings.value("show_welcome", "true")) != "false")
        self.chk_welcome.toggled.connect(
            lambda on: self.settings.setValue("show_welcome", "true" if on else "false"))
        self.body.addWidget(self.chk_welcome)

        self.kicker(_("Linha do tempo"))
        self.chk_zoom = QCheckBox(_("Zoom pelo marcador de reprodução"))
        self.chk_zoom.setToolTip(zoom_playhead_tip())
        self.chk_zoom.setChecked(str(self.settings.value(ZOOM_PLAYHEAD_KEY, "true")) != "false")
        self.chk_zoom.toggled.connect(self._set_zoom)
        self.body.addWidget(self.chk_zoom)

        self.kicker(_("Pastas"))
        row = QHBoxLayout()
        b = QPushButton(_("Meus presets"))
        b.clicked.connect(lambda: system.open_path(presets.user_dir()))
        row.addWidget(b)
        b = QPushButton(_("Meus LUTs"))
        b.clicked.connect(lambda: system.open_path(luts.user_dir()))
        row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.finish()

    def _set_zoom(self, on: bool) -> None:
        self.settings.setValue(ZOOM_PLAYHEAD_KEY, "true" if on else "false")
        self.dialog.settings_changed.emit(ZOOM_PLAYHEAD_KEY)

    def _set_update(self, on: bool) -> None:
        self.settings.setValue("auto_update", "true" if on else "false")
        self.dialog.settings_changed.emit("auto_update")
