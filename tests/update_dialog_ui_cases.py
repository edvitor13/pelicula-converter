"""Casos da janela de atualização (rodados por test_update_dialog_ui.py num subprocesso offscreen)."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import updater  # noqa: E402
from pelicula.ui import update_dialog  # noqa: E402

RELEASE = updater.Release(tag="v9.9.9", version=(9, 9, 9), name="9.9.9", body="", url="", published="",
                          assets={"PeliculaConverter-9.9.9-windows-x64.zip": ("https://exemplo/pacote.zip", 10)})


class Window(QWidget):
    """Janela principal falsa: aceita ou recusa o fechamento, como o closeEvent de verdade."""

    def __init__(self, accept: bool):
        super().__init__()
        self.accept_close = accept
        self.closes = 0

    def closeEvent(self, e):
        self.closes += 1
        if self.accept_close:
            e.accept()
        else:
            e.ignore()


class FakeApp:
    exits: list[int] = []

    @staticmethod
    def instance():
        return FakeApp

    @staticmethod
    def exit(code: int) -> None:
        FakeApp.exits.append(code)


def setup(monkeypatch, accept: bool, install_error: str = ""):
    calls = {"install": [], "download": 0}
    monkeypatch.setattr(updater, "install_info", lambda: {"kind": "zip"})
    monkeypatch.setattr(updater, "can_auto_install", lambda kind=None: True)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(update_dialog, "QApplication", FakeApp)
    FakeApp.exits = []

    def install(path, kind=None):
        calls["install"].append(path)
        if install_error:
            raise updater.UpdateError(install_error)

    monkeypatch.setattr(updater, "install", install)

    def download(release, asset, progress, cancel):
        calls["download"] += 1
        return "C:/pacote.zip"

    monkeypatch.setattr(updater, "download", download)
    win = Window(accept)
    win.show()
    return win, update_dialog.UpdateDialog(win, RELEASE), calls


def click(dlg) -> None:
    """Clica em "Atualizar agora" e espera o download (numa thread) voltar pelo sinal."""
    dlg._start()
    deadline = time.time() + 5
    while dlg._busy and time.time() < deadline:
        APP.processEvents()
        time.sleep(0.01)
    APP.processEvents()


def test_cancelled_close_installs_nothing_and_keeps_app_open(monkeypatch):
    win, dlg, calls = setup(monkeypatch, accept=False)
    click(dlg)
    assert win.closes == 1
    assert calls["install"] == []
    assert FakeApp.exits == []
    assert win.isVisible()
    assert dlg.go.isEnabled()
    assert "continua aberto" in dlg.status.text()


def test_second_click_after_postponing_does_not_download_again(monkeypatch):
    win, dlg, calls = setup(monkeypatch, accept=False)
    click(dlg)
    win.accept_close = True
    click(dlg)
    assert calls["download"] == 1
    assert calls["install"] == ["C:/pacote.zip"]
    assert FakeApp.exits == [0]


def test_accepted_close_installs_and_exits(monkeypatch):
    win, dlg, calls = setup(monkeypatch, accept=True)
    click(dlg)
    assert calls["install"] == ["C:/pacote.zip"]
    assert FakeApp.exits == [0]
    assert not win.isVisible()


def test_install_failure_brings_the_window_back(monkeypatch):
    win, dlg, calls = setup(monkeypatch, accept=True, install_error="bad-archive")
    click(dlg)
    assert calls["install"] == ["C:/pacote.zip"]
    assert FakeApp.exits == []
    assert win.isVisible()
    assert dlg.go.isEnabled()
    assert dlg.status.text() == update_dialog.error_text("bad-archive")
