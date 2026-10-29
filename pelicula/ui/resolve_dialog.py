"""Janela "Plugin para o DaVinci Resolve": o plugin OpenFX (Resolve gratuito e Studio) e os DCTLs/LUTs (Studio)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTextBrowser, QVBoxLayout)

from .. import __version__, resolve, system
from ..i18n import _
from . import icons, theme


class _Bridge(QObject):
    done = Signal(str, str, str)  # pasta gerada, erro, mensagem de sucesso


class ResolveDialog(QDialog):
    """Instala o plugin OpenFX (que funciona no Resolve gratuito) e, para o Studio, os DCTLs e LUTs.

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
        self.resize(700, 780)
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

        # ---- plugin OpenFX: o caminho para o Resolve gratuito
        box = QFrame()
        box.setObjectName("OfxBox")
        box.setStyleSheet(f"QFrame#OfxBox {{ background: {theme.PANEL}; border: 1px solid {theme.ACCENT_DIM}; "
                          f"border-radius: 10px; }}")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(8)
        ot = QLabel(_("Plugin OpenFX — funciona no DaVinci Resolve gratuito"))
        ot.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.ACCENT_HI};")
        ot.setWordWrap(True)
        bl.addWidget(ot)
        info = QLabel(self._ofx_html())
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        bl.addWidget(info)
        self.ofx_status = QLabel()
        self.ofx_status.setWordWrap(True)
        self.ofx_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(self.ofx_status)
        orow = QHBoxLayout()
        self.btn_ofx_install = QPushButton("  " + _("Instalar o plugin OpenFX"))
        self.btn_ofx_install.setObjectName("Primary")
        self.btn_ofx_install.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_ofx_install.clicked.connect(self.install_ofx)
        orow.addWidget(self.btn_ofx_install)
        self.btn_ofx_open = QPushButton(_("Abrir a pasta do plugin"))
        self.btn_ofx_open.setIcon(icons.icon("folder", theme.TEXT, 16))
        self.btn_ofx_open.clicked.connect(self.open_ofx_folder)
        orow.addWidget(self.btn_ofx_open)
        orow.addStretch(1)
        bl.addLayout(orow)
        lay.addWidget(box)

        # ---- DCTLs e LUTs (Studio)
        st = QLabel(_("DCTLs e LUTs (DaVinci Resolve Studio)"))
        st.setStyleSheet("font-size: 11pt; font-weight: 600; margin-top: 6px;")
        lay.addWidget(st)
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
        self.btn_install.setIcon(icons.icon("export", theme.TEXT, 16))
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
    def _ofx_html() -> str:
        steps = [
            _("Feche o DaVinci Resolve e clique em <b>Instalar o plugin OpenFX</b> (o sistema pede permissão de "
              "administrador, porque a pasta do OpenFX é do sistema)."),
            _("Página <b>Color</b>: abra <b>OpenFX</b> e arraste <b>PeliculaConverter</b> para um nó. Página "
              "<b>Edit</b>: <b>Effects › OpenFX › PeliculaConverter</b> sobre o clipe."),
            _("Escolha um <b>Preset</b> ou carregue um look <b>.json</b> exportado pelo app; todos os ajustes do "
              "app estão nos grupos do efeito (Laboratório, Grão, Halação, Projetor…)."),
        ]
        items = "".join(f"<li style='margin-bottom:3px'>{s}</li>" for s in steps)
        return ("<p style='margin:0'>" + _("Um efeito só com o look inteiro — cor, laboratório, grão, halação, "
                                           "bloom, lente, tremor, defeitos e moldura —, a mesma conta do app, "
                                           "calculada na CPU.") + "</p><ol style='margin-top:4px'>" + items + "</ol>")

    @staticmethod
    def _help_html() -> str:
        steps = [
            _("Clique em <b>Instalar no DaVinci Resolve</b> (com o Resolve fechado, ou clique depois em "
              "<i>Refresh</i> na lista de LUTs)."),
            _("Na página <b>Color</b>, crie três nós em série (Alt+S)."),
            _("Em cada nó, arraste <b>OpenFX › ResolveFX Color › DCTL</b> e escolha, em ordem: "
              "<b>PeliculaConverter Cor</b>, <b>PeliculaConverter Textura</b> e <b>PeliculaConverter Projetor</b>."),
            _("No nó Cor, escolha em <b>Perfil do video</b> a curva da câmera (S-Log3, LogC3, V-Log…) ou HLG/PQ "
              "para vídeo HDR. Se a linha do tempo já está em Rec.709, deixe Rec.709. Em S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log, "
              "<b>Faixa do video</b> fica em <i>Video</i> com o clipe em Data Levels Auto/Video e em <i>Cheia</i> "
              "com o clipe em Full."),
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
            + "<p>" + _("O efeito DCTL é do <b>DaVinci Resolve Studio</b>. No Resolve gratuito use o plugin OpenFX "
                        "acima ou os LUTs .cube da pasta LUTs (botão direito no nó › LUT): eles têm só a cor.")
            + "</p>"
            + "<p style='color:%s'>" % theme.FAINT
            + _("Os nomes de filmes são aproximações artísticas, sem relação com os fabricantes.") + "</p>"
        )

    def refresh(self) -> None:
        self._refresh_ofx()
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

    def _refresh_ofx(self) -> None:
        shipped = resolve.ofx_bundle_version()
        folder = resolve.ofx_install_dir()
        installed = resolve.ofx_installed_version(folder)
        if resolve.ofx_bundle_path() is None:
            # rodando do código-fonte sem ter compilado o plugin: explica em vez de falhar
            self.ofx_status.setText(_("Este PeliculaConverter não traz o plugin OpenFX compilado. Nas versões "
                                      "instaladas ele já vem pronto; rodando do código-fonte, compile com "
                                      "plugins/ofx/build_windows.bat (Windows) ou plugins/ofx/build_linux.sh "
                                      "(Linux) e abra esta janela de novo."))
            self.ofx_status.setStyleSheet(f"color: {theme.MUTED};")
        elif installed is None:
            self.ofx_status.setText(_("Plugin OpenFX ainda não instalado (pasta: {pasta}).").format(pasta=folder))
            self.ofx_status.setStyleSheet(f"color: {theme.MUTED};")
        elif installed == shipped:
            self.ofx_status.setText(_("Plugin OpenFX instalado (versão {versao}) em {pasta}.").format(
                versao=installed, pasta=folder))
            self.ofx_status.setStyleSheet(f"color: {theme.OK};")
        else:
            self.ofx_status.setText(_("Plugin OpenFX instalado na versão {antiga}; atualize para a {nova}.").format(
                antiga=installed, nova=shipped))
            self.ofx_status.setStyleSheet(f"color: {theme.ACCENT};")
        self.btn_ofx_install.setEnabled(resolve.ofx_bundle_path() is not None and not self._busy)
        self.btn_ofx_install.setText("  " + (_("Atualizar o plugin OpenFX") if installed else
                                             _("Instalar o plugin OpenFX")))
        self.btn_ofx_open.setEnabled((folder / resolve.OFX_BUNDLE_NAME).is_dir() or folder.is_dir())

    # ------------------------------------------------------------ ações
    def _run(self, work, message: str, done_text: str, label: QLabel | None = None) -> None:
        """Roda numa thread (LUTs pedem um contexto OpenGL próprio; o OpenFX espera o administrador)."""
        self._busy = True
        self.refresh()
        label = label or self.status
        label.setText(message)
        label.setStyleSheet(f"color: {theme.MUTED};")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def run():
            try:
                folder = str(work())
                self._bridge.done.emit(folder, "", done_text)
            except Exception as exc:  # noqa: BLE001
                self._bridge.done.emit("", str(exc), done_text)

        threading.Thread(target=run, daemon=True, name="resolve-plugin").start()

    def _finished(self, folder: str, error: str, done_text: str) -> None:
        QApplication.restoreOverrideCursor()
        self._busy = False
        self.refresh()
        if error:
            QMessageBox.warning(self, _("Plugin para o DaVinci Resolve"), error)
            return
        self._last = folder
        QMessageBox.information(self, _("Plugin para o DaVinci Resolve"), done_text.format(pasta=folder))

    def install_ofx(self) -> None:
        if self._busy:
            return
        self._run(lambda: resolve.ofx_install(), _("Instalando o plugin OpenFX… (confirme o pedido de administrador)"),
                  _("Pronto! O plugin OpenFX está em:\n{pasta}\n\nReabra o DaVinci Resolve e use Color › OpenFX › "
                    "PeliculaConverter."), self.ofx_status)

    def open_ofx_folder(self) -> None:
        folder = resolve.ofx_install_dir()
        inst = folder / resolve.OFX_BUNDLE_NAME
        system.open_path(inst if inst.is_dir() else folder)

    def install(self) -> None:
        if self._busy:
            return
        self._run(lambda: resolve.install(), _("Instalando… (gerando os DCTLs e os LUTs dos presets)"),
                  _("Pronto! O pacote está em:\n{pasta}\n\nNo Resolve, clique em Refresh na lista de "
                    "LUTs ou reabra o programa."))

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

        self._run(work, _("Gerando o pacote…"), _("Pronto! O pacote está em:\n{pasta}\n\nNo Resolve, clique em "
                                                  "Refresh na lista de LUTs ou reabra o programa."))

    def open_folder(self) -> None:
        target = resolve.default_install_dir()
        if target is None:
            return
        inst = target / resolve.PACKAGE_NAME
        system.open_path(inst if inst.is_dir() else target)
