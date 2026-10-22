"""Aviso de erro inesperado: uma exceção escapou numa função da interface ou numa thread.

O relatório já foi gravado por `pelicula/crashlog.py` (na pasta de logs do app; nada é enviado). Aqui só
aparece uma janela pequena, na thread principal, com o relatório e os botões "Copiar relatório" e
"Abrir pasta". No máximo `MAX_DIALOGS` por sessão e um de cada vez; os outros erros ficam só no arquivo
(e numa mensagem na barra de status).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .. import crashlog, system
from ..i18n import _
from . import icons, theme

MAX_DIALOGS = 3


class ErrorDialog(QDialog):
    def __init__(self, parent, text: str, path: str = ""):
        super().__init__(parent)
        self.text = text
        self.path = path
        self.setWindowTitle(_("Erro inesperado"))
        self.setWindowIcon(icons.app_icon())
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)
        head = QLabel(_("O PeliculaConverter encontrou um erro inesperado, mas continua aberto."))
        head.setStyleSheet("font-weight: 600;")
        head.setWordWrap(True)
        lay.addWidget(head)
        sub = QLabel(_("Se algo parecer estranho, salve o projeto e abra o app de novo. O relatório abaixo fica só "
                       "neste computador: nada é enviado."))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.details = QPlainTextEdit(text)
        self.details.setReadOnly(True)
        self.details.setFont(theme.mono_font(8.5))
        self.details.setMinimumHeight(180)
        lay.addWidget(self.details, 1)
        row = QHBoxLayout()
        self.btn_copy = QPushButton(_("Copiar relatório"))
        self.btn_copy.clicked.connect(self.copy)
        row.addWidget(self.btn_copy)
        self.btn_folder = QPushButton(_("Abrir pasta"))
        self.btn_folder.setIcon(icons.icon("folder", theme.TEXT, 15))
        self.btn_folder.clicked.connect(self.open_folder)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        close = QPushButton(_("Fechar"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.btn_copy.setText(_("Copiado"))

    def open_folder(self) -> None:
        if self.path and Path(self.path).is_file():
            system.reveal(self.path)
        else:
            folder = Path(self.path).parent if self.path else crashlog.logs_dir()
            folder.mkdir(parents=True, exist_ok=True)
            system.open_path(folder)


class CrashUi(QObject):
    """Leva os relatórios do `CrashLog` (qualquer thread) para um `ErrorDialog` na thread principal."""

    report = Signal(str, str)

    def __init__(self, crash: crashlog.CrashLog, parent_getter: Callable[[], object] | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.crash = crash
        self.parent_getter = parent_getter or (lambda: None)
        self.shown = 0
        self._open = False
        self.report.connect(self._show, Qt.ConnectionType.QueuedConnection)
        crash.on_report = self._relay

    def _relay(self, text: str, path, _main_thread: bool) -> None:
        try:
            self.report.emit(text, str(path or ""))
        except RuntimeError:
            pass  # a interface já foi destruída

    def make_dialog(self, text: str, path: str) -> ErrorDialog:
        return ErrorDialog(self.parent_getter(), text, path)

    @Slot(str, str)
    def _show(self, text: str, path: str) -> None:
        win = self.parent_getter()
        if self._open or self.shown >= MAX_DIALOGS:
            sb = getattr(win, "statusBar", None)
            if callable(sb):
                sb().showMessage(_("Outro erro inesperado foi registrado na pasta de relatórios."), 8000)
            return
        self._open = True
        self.shown += 1
        try:
            self.make_dialog(text, path).exec()
        finally:
            self._open = False
