"""Janela de dependências: ffmpeg (baixar/atualizar), placa de vídeo e bibliotecas Python."""

from __future__ import annotations

import platform
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout)

from .. import deps, media, system
from ..i18n import _
from . import icons, theme


class _Bridge(QObject):
    progress = Signal(str, int, int)
    finished = Signal(bool, str)
    latest = Signal(str)


class DepsDialog(QDialog):
    def __init__(self, parent, gpu_info: str = "", settings=None, reason: str = ""):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(_("Dependências e atualizações"))
        self.setMinimumWidth(620)
        self._cancel = threading.Event()
        self._busy = False
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.latest.connect(self._on_latest)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        k = QLabel(_("SISTEMA"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(_("Dependências e atualizações"))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        if reason:
            r = QLabel(reason)
            r.setWordWrap(True)
            r.setStyleSheet(f"color: {theme.ACCENT_HI};")
            lay.addWidget(r)

        g = QGroupBox(_("ffmpeg (leitura e gravação de vídeo)"))
        v = QVBoxLayout(g)
        self.ff_status = QLabel()
        self.ff_status.setWordWrap(True)
        self.ff_status.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.ff_status)
        self.ff_source = QLabel()
        self.ff_source.setObjectName("Faint")
        self.ff_source.setWordWrap(True)
        v.addWidget(self.ff_source)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        self.stage = QLabel()
        self.stage.setObjectName("Muted")
        self.stage.setVisible(False)
        v.addWidget(self.stage)
        row = QHBoxLayout()
        self.btn_get = QPushButton("  " + _("Baixar ffmpeg"))
        self.btn_get.setObjectName("Primary")
        self.btn_get.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_get.clicked.connect(self._download)
        row.addWidget(self.btn_get)
        self.btn_cancel = QPushButton(_("Cancelar download"))
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel.set)
        row.addWidget(self.btn_cancel)
        pick = QPushButton(_("Usar outra pasta…"))
        pick.setIcon(icons.icon("folder", theme.TEXT, 16))
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(g)

        g2 = QGroupBox(_("Placa de vídeo e bibliotecas"))
        v2 = QVBoxLayout(g2)
        pk = "  •  ".join(f"{n} {ver}" for n, ver in deps.python_packages())
        total, avail = system.ram()
        frozen = " " + _("(executável)") if getattr(sys, "frozen", False) else ""
        sysinfo = QLabel("<br>".join([
            _("Sistema: {sistema} • Python {python}").format(
                sistema=f"{platform.system()} {platform.release()}", python=platform.python_version()) + frozen,
            _("Processador: {cpu} • {n} núcleos • memória {ram}").format(
                cpu=system.cpu_name(), n=system.cpu_threads(), ram=system.gb(total)),
            _("Efeitos na GPU: {placa}").format(placa=gpu_info or _("não detectada")),
            _("Bibliotecas: {lista}").format(lista=pk),
        ]))
        sysinfo.setTextFormat(Qt.TextFormat.RichText)
        sysinfo.setWordWrap(True)
        sysinfo.setObjectName("Muted")
        v2.addWidget(sysinfo)
        missing = deps.missing_python_modules()
        if missing and not getattr(sys, "frozen", False):
            b = QPushButton(_("Instalar bibliotecas que faltam ({lista})").format(lista=", ".join(missing)))
            b.clicked.connect(lambda: self._pip(missing))
            v2.addWidget(b)
        tip = QLabel(_("Se os efeitos não aparecerem, atualize o driver da placa de vídeo (NVIDIA, AMD ou Intel). "
                       "O app precisa de OpenGL 3.3."))
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        v2.addWidget(tip)
        lay.addWidget(g2)

        close = QPushButton(_("Fechar"))
        close.clicked.connect(self.close)
        bl = QHBoxLayout()
        bl.addStretch(1)
        bl.addWidget(close)
        lay.addLayout(bl)
        self.latest = ""
        self._refresh()
        threading.Thread(target=lambda: self.bridge.latest.emit(deps.latest_version()), daemon=True).start()

    # ------------------------------------------------------------ estado
    def _refresh(self) -> None:
        media.configure(self.settings.value("ffmpeg_dir", "") or None if self.settings else None)
        src = deps.SOURCES.get(deps.platform_key())
        auto = deps.platform_supported() and src is not None
        try:
            path = media.ffmpeg()
            media.ffprobe()
        except RuntimeError:
            path = ""
        if not path:
            self.ff_status.setText(f"<span style='color:{theme.DANGER}'><b>{_('Não encontrado.')}</b></span> "
                                   + _("Sem o ffmpeg o app não consegue abrir nem exportar vídeos."))
            self.btn_get.setText("  " + _("Baixar ffmpeg"))
        else:
            info = deps.inspect(path)
            ver = info.label if info else "?"
            newer = deps.parse_version(self.latest)
            is_old = bool(info and info.outdated)
            if info and info.version and newer and info.version < newer:
                note = " • " + _("versão {versao} disponível").format(versao=self.latest)
            else:
                note = ""
            mine = str(deps.ffmpeg_dir()) in path
            color = theme.ACCENT_HI if is_old else theme.OK
            state = _("Desatualizado") if is_old else _("Ok")
            shown = _("versão {versao}").format(versao=ver) if info and info.version else ver
            by_app = " " + _("(baixado pelo app)") if mine else ""
            self.ff_status.setText(f"<span style='color:{color}'><b>{state}</b></span> — {shown}{note}"
                                   f"<br><span style='color:{theme.FAINT}'>{path}{by_app}</span>")
            self.btn_get.setText("  " + (_("Atualizar ffmpeg") if (is_old or note) else _("Baixar de novo")))
        if auto:
            self.ff_source.setText(_("Fonte: {fonte}. O arquivo é conferido com o SHA-256 publicado e instalado "
                                     "só para o seu usuário em {pasta}.").format(fonte=_(src["name"]),
                                                                                 pasta=deps.ffmpeg_dir()))
        else:
            self.ff_source.setText(_("O download automático ainda não está disponível neste sistema. Instale o ffmpeg "
                                     "pelo gerenciador de pacotes e use \"Usar outra pasta…\" se precisar."))
        self.btn_get.setEnabled(auto and not self._busy)

    def _on_latest(self, ver: str) -> None:
        self.latest = ver
        if not self._busy:
            self._refresh()

    # ------------------------------------------------------------ ações
    def _download(self) -> None:
        self._busy = True
        self._cancel.clear()
        self.btn_get.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.bar.setVisible(True)
        self.stage.setVisible(True)
        self.bar.setValue(0)

        def run():
            try:
                deps.download_ffmpeg(lambda s, d, t: self.bridge.progress.emit(s, d, t), self._cancel)
                self.bridge.finished.emit(True, "")
            except deps.DownloadCancelled:
                self.bridge.finished.emit(False, _("Download cancelado."))
            except Exception as exc:  # noqa: BLE001
                self.bridge.finished.emit(False, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            mb = " " + _("{feito} de {total} MB").format(feito=f"{done / 1e6:.0f}", total=f"{total / 1e6:.0f}") \
                if total > 1 else ""
            self.stage.setText(stage + mb)
        else:
            self.bar.setRange(0, 0)
            self.stage.setText(stage)

    def _on_finished(self, ok: bool, msg: str) -> None:
        self._busy = False
        self.btn_cancel.setVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        self.stage.setVisible(False)
        if ok:
            if self.settings is not None:
                self.settings.remove("ffmpeg_dir")
            media.configure()
            self._refresh()
            QMessageBox.information(self, "ffmpeg",
                                    _("ffmpeg instalado e pronto para uso:\n{caminho}").format(caminho=media.ffmpeg()))
        else:
            self._refresh()
            if msg:
                QMessageBox.warning(self, "ffmpeg", msg)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, _("Pasta que contém o ffmpeg e o ffprobe"), media.tool_dir())
        if not d:
            return
        if media.configure(d):
            if self.settings is not None:
                self.settings.setValue("ffmpeg_dir", d)
            self._refresh()
        else:
            QMessageBox.warning(self, "ffmpeg", _("Não encontrei o ffmpeg e o ffprobe nessa pasta."))

    def _pip(self, pkgs: list[str]) -> None:
        self.setCursor(Qt.CursorShape.WaitCursor)
        ok, out = deps.pip_install(pkgs)
        self.unsetCursor()
        if ok:
            QMessageBox.information(self, _("Bibliotecas"), _("Instaladas. Feche e abra o app de novo."))
        else:
            QMessageBox.warning(self, _("Bibliotecas"), _("Não foi possível instalar.") + "\n\n" + out[-1500:])

    def closeEvent(self, e):
        if self._busy:
            self._cancel.set()
        super().closeEvent(e)
