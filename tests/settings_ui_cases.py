"""Casos da janela de Configurações (rodados por test_settings_ui.py num subprocesso offscreen)."""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A página Recuperação lê a pasta do app (cópias e relatórios): uma pasta temporária, nunca a do usuário.
_DATA = tempfile.mkdtemp(prefix="pelicula_settings_data_")
os.environ["LOCALAPPDATA"] = os.environ["XDG_DATA_HOME"] = _DATA

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula.ui import prefs  # noqa: E402
from pelicula.ui.settings_dialog import PAGES, SettingsDialog  # noqa: E402


def dialog(page: str = "geral") -> SettingsDialog:
    return SettingsDialog(None, prefs.settings(), page, main=None)


def test_every_page_opens():
    dlg = dialog()
    for pid, *_rest in PAGES:
        dlg.show_page(pid)
        assert dlg.stack.currentWidget() is dlg.page(pid)
    assert dlg.nav.count() == len(PAGES)


def test_opens_on_requested_page_and_falls_back():
    assert dialog("componentes").nav.currentRow() == [p[0] for p in PAGES].index("componentes")
    assert dialog("nao_existe").nav.currentRow() == 0


def test_general_page_writes_preferences():
    s = prefs.settings()
    s.setValue("auto_update", "true")
    s.setValue("show_welcome", "true")
    dlg = dialog("geral")
    seen = []
    dlg.settings_changed.connect(seen.append)
    page = dlg.page("geral")
    page.chk_update.setChecked(False)
    page.chk_welcome.setChecked(False)
    assert s.value("auto_update") == "false" and s.value("show_welcome") == "false"
    assert seen == ["auto_update"]
    page.chk_update.setChecked(True)
    assert s.value("auto_update") == "true"
