"""Ponto de entrada da aplicação."""

from __future__ import annotations

import os
import sys
import tempfile

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__, deps, i18n
from .i18n import _
from .ui import icons, theme


def choose_language(settings: QSettings) -> tuple[str, bool]:
    """Idioma salvo, ou a escolha do primeiro acesso. Devolve (código, primeiro_acesso)."""
    saved = str(settings.value("language", "") or "")
    if saved in i18n.LANGUAGES:
        return saved, False
    from .ui.language_dialog import LanguageDialog
    dlg = LanguageDialog(None, i18n.system_language())
    dlg.exec()
    settings.setValue("language", dlg.selected)
    return dlg.selected, True


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
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    arrow = os.path.join(tempfile.gettempdir(), "pelicula_seta.png")
    icons.icon("chevron", theme.MUTED, 12).pixmap(24, 24).save(arrow)
    app.setStyleSheet(theme.stylesheet(arrow.replace("\\", "/")))
    app.setFont(theme.font(9.5))
    app.setWindowIcon(icons.app_icon())
    from .ui import prefs
    settings = prefs.settings()
    lang, first_run = choose_language(settings)
    i18n.set_language(lang)
    if sys.platform == "darwin" and not os.environ.get("PELICULA_MACOS"):
        QMessageBox.information(None, APP_NAME, _("O suporte ao macOS está preparado, mas ainda desativado nesta versão."))
        return 0
    missing = deps.missing_python_modules()
    if missing:
        r = QMessageBox.question(None, APP_NAME, _("Faltam bibliotecas para o app funcionar: {lista}.\n\n"
                                                   "Instalar agora com o pip?").format(lista=", ".join(missing)))
        if r != QMessageBox.StandardButton.Yes:
            return 1
        ok, out = deps.pip_install(missing)
        if not ok:
            QMessageBox.critical(None, APP_NAME, _("Não foi possível instalar.\n\n{erro}").format(erro=out[-1500:]))
            return 1
    from .ui.main_window import MainWindow
    try:
        win = MainWindow()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, APP_NAME, _("Não foi possível iniciar o processamento na placa de vídeo "
                                               "(é preciso OpenGL 3.3).\n\n{erro}").format(erro=exc))
        return 1
    win.show()
    files = [a for a in sys.argv[1:] if os.path.exists(a)]
    shot = os.environ.get("PELICULA_SCREENSHOT")
    updated = str(settings.value("last_seen_version", "")) not in ("", __version__)
    settings.setValue("last_seen_version", __version__)
    if files:
        QTimer.singleShot(0, lambda: win.handle_files(files))
    elif not shot and (first_run or str(settings.value("show_welcome", "true")) != "false"):
        QTimer.singleShot(250, win.show_welcome)
    if updated and not shot:
        from .ui.welcome import WhatsNewDialog
        QTimer.singleShot(400, lambda: WhatsNewDialog(win).exec())
    if shot:
        def grab():
            win.grab().save(shot)
            app.exit(0)
        QTimer.singleShot(int(os.environ.get("PELICULA_SCREENSHOT_MS", "3500")), grab)
    return app.exec()
