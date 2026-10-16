"""Ponto de entrada da aplicação."""

from __future__ import annotations

import os
import sys
import tempfile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, deps
from .ui import icons, theme


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PeliculaConverter.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    arrow = os.path.join(tempfile.gettempdir(), "pelicula_seta.png")
    icons.icon("chevron", theme.MUTED, 12).pixmap(24, 24).save(arrow)
    app.setStyleSheet(theme.stylesheet(arrow.replace("\\", "/")))
    app.setFont(theme.font(9.5))
    app.setWindowIcon(icons.app_icon())
    if sys.platform == "darwin" and not os.environ.get("PELICULA_MACOS"):
        QMessageBox.information(None, APP_NAME, "O suporte ao macOS está preparado, mas ainda desativado nesta versão.")
        return 0
    missing = deps.missing_python_modules()
    if missing:
        r = QMessageBox.question(None, APP_NAME, "Faltam bibliotecas para o app funcionar: " + ", ".join(missing)
                                 + ".\n\nInstalar agora com o pip?")
        if r != QMessageBox.StandardButton.Yes:
            return 1
        ok, out = deps.pip_install(missing)
        if not ok:
            QMessageBox.critical(None, APP_NAME, f"Não foi possível instalar.\n\n{out[-1500:]}")
            return 1
    from .ui.main_window import MainWindow
    try:
        win = MainWindow()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, APP_NAME, "Não foi possível iniciar o processamento na placa de vídeo "
                                             f"(é preciso OpenGL 3.3).\n\n{exc}")
        return 1
    win.show()
    files = [a for a in sys.argv[1:] if os.path.exists(a)]
    if files:
        QTimer.singleShot(0, lambda: win.handle_files(files))
    shot = os.environ.get("PELICULA_SCREENSHOT")
    if shot:
        def grab():
            win.grab().save(shot)
            app.exit(0)
        QTimer.singleShot(int(os.environ.get("PELICULA_SCREENSHOT_MS", "3500")), grab)
    return app.exec()
