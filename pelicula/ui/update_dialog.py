"""Janela de atualização: mostra a versão nova, baixa, confere e instala."""

from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import __version__, updater
from ..i18n import N_, _
from . import icons, theme

ERRORS = {
    "no-public-release": N_("Não há versão publicada que o app consiga ver. O repositório precisa ser público "
                            "para as atualizações automáticas funcionarem."),
    "offline": N_("Não foi possível falar com o GitHub. Confira a sua conexão com a internet."),
    "no-checksums": N_("A versão publicada não tem o arquivo de conferência (SHA256SUMS.txt); por segurança, a "
                       "atualização automática foi cancelada. Baixe pela página da versão."),
    "checksum-mismatch": N_("O arquivo baixado não confere com o original publicado. Nada foi instalado."),
    "bad-archive": N_("O pacote baixado não tem o formato esperado. Nada foi instalado."),
    "unsupported": N_("Este tipo de instalação não pode ser atualizado automaticamente. Baixe pela página da versão."),
    "cancelled": N_("Download cancelado."),
}


def error_text(code: str) -> str:
    if code in ERRORS:
        return _(ERRORS[code])
    return _("Não foi possível verificar ou instalar a atualização ({codigo}).").format(codigo=code)


class _Bridge(QObject):
    progress = Signal(int, int)
    done = Signal(str, str)  # caminho baixado, erro


class UpdateDialog(QDialog):
    def __init__(self, parent, release: updater.Release, settings=None):
        super().__init__(parent)
        self.release = release
        self.settings = settings
        self._cancel = threading.Event()
        self._busy = False
        self.setWindowTitle(_("Atualização disponível"))
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        k = QLabel(_("ATUALIZAÇÃO"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(_("PeliculaConverter {nova} está disponível").format(nova=release.tag.lstrip("v")))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        sub = QLabel(_("Você está usando a versão {atual}.").format(atual=__version__))
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setStyleSheet(f"QTextBrowser {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                            f"border-radius: 10px; padding: 10px; }}")
        notes.setMarkdown(release.body or _("Sem notas para esta versão."))
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        skip = QPushButton(_("Pular esta versão"))
        skip.clicked.connect(self._skip)
        row.addWidget(skip)
        page = QPushButton(_("Abrir página da versão"))
        page.clicked.connect(lambda: webbrowser.open(release.url))
        row.addWidget(page)
        row.addStretch(1)
        later = QPushButton(_("Agora não"))
        later.clicked.connect(self.reject)
        row.addWidget(later)
        self.go = QPushButton("  " + _("Atualizar agora"))
        self.go.setObjectName("Primary")
        self.go.setIcon(icons.icon("export", "#1b1205", 16))
        self.go.clicked.connect(self._start)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.done.connect(self._done)
        self.kind = updater.install_info()["kind"]
        self.asset = updater.pick_asset(release, self.kind)
        if not updater.can_auto_install(self.kind) or self.asset is None:
            self.go.setEnabled(False)
            if self.kind == "source":
                self.status.setText(_("Você está rodando pelo código-fonte: atualize com \"git pull\" ou baixe a "
                                      "versão nova pela página."))
            else:
                self.status.setText(_("Não há pacote automático para esta instalação. Baixe pela página da versão."))

    def _skip(self) -> None:
        if self.settings is not None:
            self.settings.setValue("update_skip", self.release.tag)
        self.reject()

    def _start(self) -> None:
        self._busy = True
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(_("Baixando {arquivo}…").format(arquivo=self.asset[0]))

        def run():
            try:
                path = updater.download(self.release, self.asset, lambda d, t: self.bridge.progress.emit(d, t),
                                        self._cancel)
                self.bridge.done.emit(path, "")
            except updater.UpdateError as exc:
                self.bridge.done.emit("", str(exc))
            except Exception as exc:  # noqa: BLE001
                self.bridge.done.emit("", str(exc) or exc.__class__.__name__)

        threading.Thread(target=run, daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setValue(int(done / total * 1000))
            self.status.setText(_("Baixando… {feito} de {total} MB").format(feito=f"{done / 1e6:.0f}",
                                                                            total=f"{total / 1e6:.0f}"))

    def _done(self, path: str, err: str) -> None:
        self._busy = False
        self.bar.setVisible(False)
        if err:
            self.go.setEnabled(True)
            self.status.setText(error_text(err))
            return
        self.status.setText(_("Arquivo conferido. O app vai fechar para instalar a versão nova e abrir de novo sozinho."))
        r = QMessageBox.question(self, _("Instalar atualização"),
                                 _("Tudo pronto. Fechar o PeliculaConverter agora para instalar a versão {versao}?")
                                 .format(versao=self.release.tag.lstrip("v")))
        if r != QMessageBox.StandardButton.Yes:
            self.go.setEnabled(True)
            return
        try:
            updater.install(path, self.kind)
        except updater.UpdateError as exc:
            self.status.setText(error_text(str(exc)))
            self.go.setEnabled(True)
            return
        self.accept()
        win = self.parent()
        if win is not None:
            win.close()
        QApplication.instance().exit(0)

    def reject(self) -> None:
        if self._busy:
            self._cancel.set()
        super().reject()
