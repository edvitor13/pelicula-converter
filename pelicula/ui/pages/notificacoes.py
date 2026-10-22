"""Configurações › Notificações: avisos do sistema quando algo termina com a janela em segundo plano.

Um liga/desliga por tipo de aviso (`notify.KINDS`, aparecem sozinhos), "só quando a janela não está em
foco", som, piscar o ícone na barra de tarefas e o botão "Testar notificação" (usa o notificador da
janela principal, `MainWindow.notifier`). Tudo gravado na hora em `notificacoes/...` (`notify.set_kind` /
`notify.set_option`); o notificador lê as preferências a cada aviso, então não há sinal para a janela.
Com o módulo `notificacoes` desligado a página explica e oferece religar.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ... import notify
from ...i18n import _
from ._base import PageBase
from ._module_box import ModuleOffBox


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Notificações"),
                         _("Avisos do sistema quando uma exportação termina e em outros eventos, mesmo com o "
                           "PeliculaConverter em segundo plano. Os avisos ficam neste computador: nada é enviado."))
        self.off_box = ModuleOffBox(self, "notificacoes",
                                    _("As notificações estão desligadas. Sem elas, o ícone na barra de tarefas só "
                                      "pisca quando uma exportação termina."))
        self.body.addWidget(self.off_box)

        self.options = QWidget()
        lay = QVBoxLayout(self.options)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.body.addWidget(self.options)
        prefs = notify.load(self.settings)

        lay.addWidget(self._kicker(_("Avisar quando")))
        self.kind_checks: dict[str, QCheckBox] = {}
        for kind in notify.KINDS:
            chk = QCheckBox(_(kind.label))
            chk.setToolTip(_(kind.description))
            chk.setChecked(prefs.kind_on(kind.id))
            chk.toggled.connect(lambda on, k=kind.id: notify.set_kind(self.settings, k, on))
            lay.addWidget(chk)
            self.kind_checks[kind.id] = chk

        lay.addWidget(self._kicker(_("Como avisar")))
        self.chk_unfocused = self._option(lay, notify.KEY_ONLY_UNFOCUSED, prefs.only_unfocused,
                                          _("Só quando a janela não está em foco"),
                                          _("Com o PeliculaConverter na frente, o resultado já aparece na janela"))
        self.chk_sound = self._option(lay, notify.KEY_SOUND, prefs.sound, _("Tocar um som"),
                                      _("O som de aviso do sistema"))
        self.chk_flash = self._option(lay, notify.KEY_FLASH, prefs.flash, _("Piscar o ícone na barra de tarefas"),
                                      _("Chama a atenção para a janela sem tirar você do que está fazendo"))

        lay.addWidget(self._kicker(_("Testar")))
        row = QHBoxLayout()
        main = dialog.main
        self.notifier = getattr(main, "notifier", None) if main is not None else None
        self.btn_test = QPushButton(_("Testar notificação"))
        self.btn_test.setEnabled(self.notifier is not None)
        self.btn_test.clicked.connect(self.test)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        lay.addLayout(row)
        self.test_status = QLabel()
        self.test_status.setObjectName("Muted")
        self.test_status.setWordWrap(True)
        lay.addWidget(self.test_status)

        self.finish()
        dialog.settings_changed.connect(self._settings_changed)
        self.refresh()

    def _kicker(self, text: str) -> QLabel:
        k = QLabel(text.upper())
        k.setObjectName("Kicker")
        return k

    def _option(self, lay, key: str, value: bool, text: str, tip: str) -> QCheckBox:
        chk = QCheckBox(text)
        chk.setToolTip(tip)
        chk.setChecked(value)
        chk.toggled.connect(lambda on: notify.set_option(self.settings, key, on))
        lay.addWidget(chk)
        return chk

    # ------------------------------------------------------------ estado
    def refresh(self) -> None:
        self.options.setEnabled(self.off_box.refresh())

    def _settings_changed(self, key: str) -> None:
        if key == "modulos":
            self.refresh()

    def test(self) -> None:
        if self.notifier is None:
            return
        if self.notifier.test():
            self.test_status.setText(_("Notificação enviada. Se ela não apareceu, confira se as notificações do "
                                       "sistema estão permitidas para o PeliculaConverter."))
        else:
            self.test_status.setText(_("Não foi possível mostrar uma notificação neste sistema. O ícone na barra de "
                                       "tarefas ainda pisca, se essa opção estiver ligada."))
