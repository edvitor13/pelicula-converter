"""Casos da frente E da 1.6 na janela (rodados por test_filme_ui.py num subprocesso offscreen).

Os módulos novos escondem e devolvem os cartões e o botão; a máquina do tempo mostra o que muda, aplica num passo
só de desfazer e avisa; o cartão da manivela fica no inspetor logo depois da velocidade.

As preferências ficam num .ini só deste arquivo (nada de outros testes nem do usuário).
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_filme_ui_")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import maquina, modules, presets  # noqa: E402
from pelicula.ui import prefs  # noqa: E402

NEW = ("camera_cinema", "anamorfico", "data_impressa", "montagem_pelicula", "maquina_tempo")


@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = prefs.settings()
    for m in modules.MODULES:
        s.remove(modules.KEY_PREFIX + m.id)
    s.setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w
    w.close()


def set_module(win, module_id, on):
    modules.set_enabled(win.settings, module_id, on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def test_new_modules_hide_and_show_their_tools(win):
    tools = win._module_tools()
    for mid in NEW:
        items = tools[mid]
        assert items, mid
        stable = modules.get(mid).status == modules.ESTAVEL
        assert all(not t.isHidden() for t in items) == stable, mid
        set_module(win, mid, True)
        assert all(not t.isHidden() for t in items), mid
        set_module(win, mid, False)
        assert all(t.isHidden() for t in items), mid
    set_module(win, "maquina_tempo", True)
    for mid in NEW[:4]:
        win.settings.remove(modules.KEY_PREFIX + mid)
    win.settings_changed.emit("modulos")


def test_look_cards_exist_for_the_new_sections(win):
    keys = [c.section.key for c in win.cards]
    for k in ("obturador", "anamorfico", "data"):
        assert k in keys
    vkeys = [c.section.key for c in win.inspector.vcards]
    assert "manivela" in vkeys


def test_time_machine_applies_in_one_undo_step(win, monkeypatch):
    from pelicula.ui import maquina_ui
    win.apply_preset(presets.DEFAULT_ID)
    APP.processEvents()
    before = dict(win.store.values)
    dlg = maquina_ui.TimeMachineDialog(win, 1972, "caseiro")
    assert "Super 8" in dlg.title.text() and dlg.btn_apply.isEnabled()
    assert "→" in dlg.diff.text(), "mostra o que vai mudar antes de aplicar"
    dlg.year.setValue(1925)
    dlg.venue.setCurrentIndex(dlg.venue.findData("cinema"))
    assert "18" in dlg.reason.text(), "a cadência fica como sugestão"
    dlg.close()

    def fake_exec(self):
        self.year.setValue(1972)
        self.venue.setCurrentIndex(self.venue.findData("caseiro"))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(maquina_ui.TimeMachineDialog, "exec", fake_exec)
    assert maquina_ui.open_dialog(win)
    APP.processEvents()
    want = maquina.apply(before, 1972, "caseiro")
    assert win.store.values == want and win.store.values["bitola"] == "super8"
    assert "Máquina do tempo" in win.statusBar().currentMessage()
    win.store.undo()
    APP.processEvents()
    assert win.store.values == before, "um passo só de desfazer"


def test_crank_card_comes_after_speed(win):
    order = [c.section.key for c in win.inspector.vcards]
    lay = win.inspector.vcards[0].parentWidget().layout()
    pos = {c.section.key: lay.indexOf(c) for c in win.inspector.vcards}
    assert "tempo" in order and pos["manivela"] == pos["tempo"] + 1
