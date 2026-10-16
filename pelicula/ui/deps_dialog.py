"""Janela de dependências: ffmpeg (baixar/atualizar), placa de vídeo e bibliotecas Python."""

from __future__ import annotations

import platform
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout)

from .. import deps, media, system
from . import icons, theme


class _Bridge(QObject):
    progress = Signal(str, int, int)
    finished = Signal(bool, str)
    latest = Signal(str)


class DepsDialog(QDialog):
    def __init__(self, parent, gpu_info: str = "", settings=None, reason: str = ""):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Dependências e atualizações")
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
        k = QLabel("SISTEMA")
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel("Dependências e atualizações")
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        if reason:
            r = QLabel(reason)
            r.setWordWrap(True)
            r.setStyleSheet(f"color: {theme.ACCENT_HI};")
            lay.addWidget(r)

        g = QGroupBox("ffmpeg (leitura e gravação de vídeo)")
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
        self.btn_get = QPushButton("  Baixar ffmpeg")
        self.btn_get.setObjectName("Primary")
        self.btn_get.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_get.clicked.connect(self._download)
        row.addWidget(self.btn_get)
        self.btn_cancel = QPushButton("Cancelar download")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel.set)
        row.addWidget(self.btn_cancel)
        pick = QPushButton("Usar outra pasta…")
        pick.setIcon(icons.icon("folder", theme.TEXT, 16))
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(g)

        g2 = QGroupBox("Placa de vídeo e bibliotecas")
        v2 = QVBoxLayout(g2)
        pk = "  •  ".join(f"{n} {ver}" for n, ver in deps.python_packages())
        total, avail = system.ram()
        sysinfo = QLabel(
            f"Sistema: {platform.system()} {platform.release()} • Python {platform.python_version()}"
            f"{' (executável)' if getattr(sys, 'frozen', False) else ''}<br>"
            f"Processador: {system.cpu_name()} • {system.cpu_threads()} núcleos • memória {system.gb(total)}<br>"
            f"Efeitos na GPU: {gpu_info or 'não detectada'}<br>Bibliotecas: {pk}")
        sysinfo.setTextFormat(Qt.TextFormat.RichText)
        sysinfo.setWordWrap(True)
        sysinfo.setObjectName("Muted")
        v2.addWidget(sysinfo)
        missing = deps.missing_python_modules()
        if missing and not getattr(sys, "frozen", False):
            b = QPushButton(f"Instalar bibliotecas que faltam ({', '.join(missing)})")
            b.clicked.connect(lambda: self._pip(missing))
            v2.addWidget(b)
        tip = QLabel("Se os efeitos não aparecerem, atualize o driver da placa de vídeo (NVIDIA, AMD ou Intel). "
                     "O app precisa de OpenGL 3.3.")
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        v2.addWidget(tip)
        lay.addWidget(g2)

        close = QPushButton("Fechar")
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
            self.ff_status.setText(f"<span style='color:{theme.DANGER}'><b>Não encontrado.</b></span> "
                                   "Sem o ffmpeg o app não consegue abrir nem exportar vídeos.")
            self.btn_get.setText("  Baixar ffmpeg")
        else:
            info = deps.inspect(path)
            ver = info.label if info else "?"
            newer = deps.parse_version(self.latest)
            is_old = bool(info and info.outdated)
            if info and info.version and newer and info.version < newer:
                note = f" • versão {self.latest} disponível"
            else:
                note = ""
            mine = str(deps.ffmpeg_dir()) in path
            color = theme.ACCENT_HI if is_old else theme.OK
            state = "desatualizado" if is_old else "ok"
            self.ff_status.setText(f"<span style='color:{color}'><b>{state.capitalize()}</b></span> — {'versão ' if info and info.version else ''}{ver}{note}"
                                   f"<br><span style='color:{theme.FAINT}'>{path}"
                                   f"{' (baixado pelo app)' if mine else ''}</span>")
            self.btn_get.setText("  Atualizar ffmpeg" if (is_old or note) else "  Baixar de novo")
        if auto:
            self.ff_source.setText(f"Fonte: {src['name']}. O arquivo é conferido com o SHA-256 publicado e instalado "
                                   f"só para o seu usuário em {deps.ffmpeg_dir()}.")
        else:
            self.ff_source.setText("O download automático ainda não está disponível neste sistema. Instale o ffmpeg "
                                   "pelo gerenciador de pacotes e use \"Usar outra pasta…\" se precisar.")
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
                self.bridge.finished.emit(False, "Download cancelado.")
            except Exception as exc:  # noqa: BLE001
                self.bridge.finished.emit(False, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            mb = f" {done / 1e6:.0f} de {total / 1e6:.0f} MB" if total > 1 else ""
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
            QMessageBox.information(self, "ffmpeg", f"ffmpeg instalado e pronto para uso:\n{media.ffmpeg()}")
        else:
            self._refresh()
            if msg:
                QMessageBox.warning(self, "ffmpeg", msg)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta que contém o ffmpeg e o ffprobe", media.tool_dir())
        if not d:
            return
        if media.configure(d):
            if self.settings is not None:
                self.settings.setValue("ffmpeg_dir", d)
            self._refresh()
        else:
            QMessageBox.warning(self, "ffmpeg", "Não encontrei o ffmpeg e o ffprobe nessa pasta.")

    def _pip(self, pkgs: list[str]) -> None:
        self.setCursor(Qt.CursorShape.WaitCursor)
        ok, out = deps.pip_install(pkgs)
        self.unsetCursor()
        if ok:
            QMessageBox.information(self, "Bibliotecas", "Instaladas. Feche e abra o app de novo.")
        else:
            QMessageBox.warning(self, "Bibliotecas", f"Não foi possível instalar.\n\n{out[-1500:]}")

    def closeEvent(self, e):
        if self._busy:
            self._cancel.set()
        super().closeEvent(e)
