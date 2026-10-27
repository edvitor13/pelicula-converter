"""Configurações › Recuperação: cópias de segurança automáticas do projeto e o relatório de travamento.

Intervalo das cópias (`recuperacao/intervalo`, padrão 1 minuto) e quantas ficam por sessão
(`recuperacao/versoes`, padrão 5), gravados na hora e avisados com `settings_changed("recuperacao")` (o
`RecoveryController` da janela reage). "Abrir pasta de recuperação", "Apagar cópias" (as desta janela e as de
sessões que travaram; nunca as de outra janela aberta) e o último relatório de travamento ou de erro (ver,
copiar, abrir a pasta dos relatórios). Com o módulo `recuperacao` desligado a página explica e oferece religar;
o relatório continua (é diagnóstico, não muda nada no trabalho).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ... import crashlog, recovery, system, tools
from ...i18n import _
from .. import icons, theme
from ._base import PageBase
from ._module_box import ModuleOffBox


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Recuperação"),
                         _("Cópias de segurança do projeto para recuperar o trabalho se o app fechar de repente. Elas "
                           "ficam numa pasta do app — o seu arquivo .plc só muda quando você salva."))
        main = dialog.main
        self.controller = getattr(main, "recovery", None) if main is not None else None
        if self.controller is not None:
            self.root = Path(self.controller.session.root)
            self.logs = Path(self.controller.logs) if self.controller.logs is not None else crashlog.logs_dir()
            self.current = self.controller.session.id
        else:
            self.root, self.logs, self.current = recovery.recovery_dir(), crashlog.logs_dir(), ""

        self.off_box = ModuleOffBox(self, "recuperacao",
                                    _("A recuperação automática está desligada: nenhuma cópia de segurança é gravada. "
                                      "O registro de travamentos continua, porque não muda nada no seu trabalho."))
        self.body.addWidget(self.off_box)

        self.options = QWidget()
        lay = QVBoxLayout(self.options)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.body.addWidget(self.options)
        lay.addWidget(self._kicker(_("Cópias automáticas")))
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Gravar uma cópia a cada")))
        self.cmb_interval = QComboBox()
        for minutes in recovery.INTERVALS:
            self.cmb_interval.addItem(_("{n} min").format(n=minutes), minutes)
        self.cmb_interval.setCurrentIndex(self.cmb_interval.findData(recovery.interval_minutes(self.settings)))
        self.cmb_interval.currentIndexChanged.connect(self._set_interval)
        row.addWidget(self.cmb_interval)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Cópias guardadas")))
        self.spin_versions = QSpinBox()
        self.spin_versions.setRange(1, recovery.MAX_VERSIONS)
        self.spin_versions.setValue(recovery.versions(self.settings))
        self.spin_versions.setToolTip(_("Quantas cópias de cada janela ficam guardadas; as mais antigas saem"))
        self.spin_versions.valueChanged.connect(self._set_versions)
        row.addWidget(self.spin_versions)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(_("A cópia só é gravada quando há mudanças não salvas, e também antes de exportar e de importar "
                        "arquivos. Ao fechar o app normalmente, as cópias são apagadas."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.kicker(_("Pasta"))
        self.usage = QLabel()
        self.usage.setObjectName("Muted")
        self.body.addWidget(self.usage)
        row = QHBoxLayout()
        self.btn_folder = QPushButton(_("Abrir pasta de recuperação"))
        self.btn_folder.setIcon(icons.icon("folder", theme.TEXT, 15))
        self.btn_folder.clicked.connect(self.open_folder)
        row.addWidget(self.btn_folder)
        self.btn_delete = QPushButton(_("Apagar cópias"))
        self.btn_delete.setObjectName("Danger")
        self.btn_delete.setToolTip(_("Apaga as cópias desta janela e as que sobraram de travamentos"))
        self.btn_delete.clicked.connect(self.delete_copies)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        self.body.addLayout(row)

        self.kicker(_("Último relatório de travamento"))
        self.report_info = QLabel()
        self.report_info.setObjectName("Muted")
        self.report_info.setWordWrap(True)
        self.body.addWidget(self.report_info)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setFont(theme.mono_font(8.5))
        self.report.setFixedHeight(160)
        self.body.addWidget(self.report)
        row = QHBoxLayout()
        self.btn_copy = QPushButton(_("Copiar relatório"))
        self.btn_copy.clicked.connect(self.copy_report)
        row.addWidget(self.btn_copy)
        self.btn_logs = QPushButton(_("Abrir pasta"))
        self.btn_logs.setIcon(icons.icon("folder", theme.TEXT, 15))
        self.btn_logs.setToolTip(_("Pasta dos relatórios (ficam só neste computador: nada é enviado)"))
        self.btn_logs.clicked.connect(self.open_logs)
        row.addWidget(self.btn_logs)
        row.addStretch(1)
        self.body.addLayout(row)

        self.finish()
        dialog.settings_changed.connect(self._settings_changed)
        self.refresh()

    def _kicker(self, text: str) -> QLabel:
        k = QLabel(text.upper())
        k.setObjectName("Kicker")
        return k

    # ------------------------------------------------------------ estado
    def refresh(self) -> None:
        self.options.setEnabled(self.off_box.refresh())
        n, size = recovery.usage(self.root)
        self.usage.setText(_("Nenhuma cópia guardada agora.") if not n else
                           _("{n} cópia(s) guardada(s) • {tamanho}").format(n=n, tamanho=tools.fmt_size(size)))
        self.btn_delete.setEnabled(n > 0)
        exclude = recovery.live_sessions(self.root) if self.root.exists() else set()
        found = crashlog.last_report(self.logs, exclude)
        self.report_text = found[1] if found else ""
        self.report_path = found[0] if found else None
        if found:
            self.report_info.setText(_("Arquivo: {caminho}").format(caminho=found[0]))
        else:
            self.report_info.setText(_("Nenhum travamento nem erro registrado."))
        self.report.setPlainText(self.report_text)
        self.report.setVisible(bool(found))
        self.btn_copy.setEnabled(bool(found))

    def _settings_changed(self, key: str) -> None:
        if key == "modulos":
            self.refresh()

    # ------------------------------------------------------------ ações
    def _set_interval(self, _i: int) -> None:
        self.settings.setValue(recovery.KEY_INTERVAL, int(self.cmb_interval.currentData()))
        self.dialog.settings_changed.emit("recuperacao")

    def _set_versions(self, n: int) -> None:
        self.settings.setValue(recovery.KEY_VERSIONS, int(n))
        self.dialog.settings_changed.emit("recuperacao")

    def open_folder(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        system.open_path(self.root)

    def open_logs(self) -> None:
        if self.report_path is not None and Path(self.report_path).is_file():
            system.reveal(self.report_path)
            return
        self.logs.mkdir(parents=True, exist_ok=True)
        system.open_path(self.logs)

    def _confirm(self, title: str, text: str) -> bool:
        r = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def delete_copies(self) -> int:
        """Apaga as cópias desta janela e as que sobraram de travamentos (as de outra janela aberta ficam)."""
        if not self._confirm(_("Apagar cópias"), _("Apagar as cópias de segurança? O trabalho não salvo desta janela "
                                                   "continua aberto; só as cópias saem.")):
            return 0
        if self.controller is not None:
            n = self.controller.delete_copies()
        else:
            n = recovery.delete_copies(self.root, self.current)
        self.refresh()
        return n

    def copy_report(self) -> None:
        if self.report_text:
            QGuiApplication.clipboard().setText(self.report_text)
            self.btn_copy.setText(_("Copiado"))
