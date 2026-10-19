"""Janela "Plugin para o DaVinci Resolve": instala os DCTLs e LUTs do PeliculaConverter no Resolve."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import __version__, resolve, system
from ..i18n import _
from . import icons, theme


class _Bridge(QObject):
    done = Signal(str, str)  # pasta gerada, erro


class ResolveDialog(QDialog):
    """Explica o plugin, mostra onde o Resolve guarda os LUTs e instala, salva ou abre a pasta.

    `engine` é opcional: sem ele os LUTs são gerados numa thread com contexto OpenGL próprio
    (o motor da janela principal nunca é usado fora da thread dele).
    """

    def __init__(self, parent=None, engine=None):
        super().__init__(parent)
        self.engine = engine
        self._busy = False
        self._bridge = _Bridge()
        self._bridge.done.connect(self._finished)
        self.setWindowTitle(_("Plugin para o DaVinci Resolve"))
        self.resize(660, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        k = QLabel(_("DAVINCI RESOLVE"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(_("O look do PeliculaConverter dentro do Resolve"))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setStyleSheet(f"QTextBrowser {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                           f"border-radius: 10px; padding: 10px; }}")
        text.setHtml(self._help_html())
        lay.addWidget(text, 1)
        self.where = QLabel()
        self.where.setObjectName("Muted")
        self.where.setWordWrap(True)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.where)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.btn_install = QPushButton("  " + _("Instalar no DaVinci Resolve"))
        self.btn_install.setObjectName("Primary")
        self.btn_install.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_install.clicked.connect(self.install)
        row.addWidget(self.btn_install)
        self.btn_save = QPushButton(_("Salvar o pacote numa pasta…"))
        self.btn_save.setIcon(icons.icon("save", theme.TEXT, 16))
        self.btn_save.clicked.connect(self.save_to_folder)
        row.addWidget(self.btn_save)
        self.btn_open = QPushButton(_("Abrir a pasta"))
        self.btn_open.setIcon(icons.icon("folder", theme.TEXT, 16))
        self.btn_open.clicked.connect(self.open_folder)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        close = QPushButton(_("Fechar"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    # ------------------------------------------------------------ textos
    @staticmethod
    def _help_html() -> str:
        steps = [
            _("Clique em <b>Instalar no DaVinci Resolve</b> (com o Resolve fechado, ou clique depois em "
              "<i>Refresh</i> na lista de LUTs)."),
            _("Na página <b>Color</b>, crie três nós em série (Alt+S)."),
            _("Em cada nó, arraste <b>OpenFX › ResolveFX Color › DCTL</b> e escolha, em ordem: "
              "<b>PeliculaConverter Cor</b>, <b>PeliculaConverter Textura</b> e <b>PeliculaConverter Projetor</b>."),
            _("No nó Cor, escolha em <b>Perfil do video</b> a curva da câmera (S-Log3, LogC3, V-Log…). Se a linha "
              "do tempo já está em Rec.709, deixe Rec.709."),
            _("Na pasta <b>Presets</b> há os nós prontos de cada preset do app; na pasta <b>LUTs</b>, um .cube por "
              "preset."),
        ]
        items = "".join(f"<li style='margin-bottom:4px'>{s}</li>" for s in steps)
        return (
            "<p>" + _("O pacote tem três nós, na ordem de um laboratório de cinema:") + "</p><ul>"
            + "<li>" + _("<b>Cor</b> — perfil do vídeo, exposição, laboratório (negativo e cópia), look de película e "
                         "cópia. É a mesma conta do app: o resultado é igual.") + "</li>"
            + "<li>" + _("<b>Textura</b> — grão, halação, bloom, névoa, maciez, aberração e vinheta.") + "</li>"
            + "<li>" + _("<b>Projetor</b> — tremor, cintilação, poeira, riscos, fio de cabelo, manchas, vazamento de "
                         "luz e moldura.") + "</li></ul>"
            + "<p><b>" + _("Como usar") + "</b></p><ol>" + items + "</ol>"
            + "<p>" + _("O efeito DCTL é do <b>DaVinci Resolve Studio</b>. No Resolve gratuito use os LUTs .cube da "
                        "pasta LUTs (botão direito no nó › LUT): eles têm só a cor. O grão e os defeitos mudam a "
                        "cada quadro a partir do Resolve 19.1.") + "</p>"
            + "<p style='color:%s'>" % theme.FAINT
            + _("Os nomes de filmes são aproximações artísticas, sem relação com os fabricantes.") + "</p>"
        )

    def refresh(self) -> None:
        target = resolve.default_install_dir()
        if target is None:
            self.where.setText(_("Pasta de LUTs do DaVinci Resolve não encontrada neste computador. Você pode salvar "
                                 "o pacote numa pasta e copiar para o Resolve depois."))
        else:
            self.where.setText(_("Pasta de LUTs do DaVinci Resolve: {pasta}").format(pasta=target))
        ver = resolve.installed_version(target) if target is not None else None
        if ver is None:
            self.status.setText(_("Plugin ainda não instalado."))
            self.status.setStyleSheet(f"color: {theme.MUTED};")
        elif ver == __version__:
            self.status.setText(_("Plugin instalado (versão {versao}).").format(versao=ver))
            self.status.setStyleSheet(f"color: {theme.OK};")
        else:
            self.status.setText(_("Plugin instalado na versão {antiga}; instale de novo para atualizar para a "
                                  "{nova}.").format(antiga=ver, nova=__version__))
            self.status.setStyleSheet(f"color: {theme.ACCENT};")
        self.btn_install.setEnabled(target is not None and not self._busy)
        self.btn_install.setText("  " + (_("Atualizar o plugin no DaVinci Resolve") if ver else
                                         _("Instalar no DaVinci Resolve")))
        self.btn_open.setEnabled(target is not None)
        self.btn_save.setEnabled(not self._busy)

    # ------------------------------------------------------------ ações
    def _run(self, work, message: str) -> None:
        """Gera o pacote numa thread (os LUTs pedem um contexto OpenGL próprio) sem travar a janela."""
        self._busy = True
        self.refresh()
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def run():
            try:
                folder = str(work())
                self._bridge.done.emit(folder, "")
            except Exception as exc:  # noqa: BLE001
                self._bridge.done.emit("", str(exc))

        threading.Thread(target=run, daemon=True, name="resolve-plugin").start()

    def _finished(self, folder: str, error: str) -> None:
        QApplication.restoreOverrideCursor()
        self._busy = False
        self.refresh()
        if error:
            QMessageBox.warning(self, _("Plugin para o DaVinci Resolve"), error)
            return
        self._last = folder
        QMessageBox.information(self, _("Plugin para o DaVinci Resolve"),
                                _("Pronto! O pacote está em:\n{pasta}\n\nNo Resolve, clique em Refresh na lista de "
                                  "LUTs ou reabra o programa.").format(pasta=folder))

    def install(self) -> None:
        if self._busy:
            return
        self._run(lambda: resolve.install(), _("Instalando… (gerando os DCTLs e os LUTs dos presets)"))

    def save_to_folder(self) -> None:
        if self._busy:
            return
        d = QFileDialog.getExistingDirectory(self, _("Pasta onde salvar o pacote do DaVinci Resolve"),
                                             str(Path.home()))
        if not d:
            return

        def work():
            resolve.build_package(d)
            return Path(d) / resolve.PACKAGE_NAME

        self._run(work, _("Gerando o pacote…"))

    def open_folder(self) -> None:
        target = resolve.default_install_dir()
        if target is None:
            return
        inst = target / resolve.PACKAGE_NAME
        system.open_path(inst if inst.is_dir() else target)
