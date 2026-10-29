"""Casos da interface da Cor por planos (rodados por test_planes_ui.py num subprocesso offscreen).

O cartão com Frente, Fundo e Pele, os prontos, o conta-gotas da pele, "Ver planos" e o módulo Beta. As
preferências ficam num .ini só deste arquivo; sem OpenGL 3.3 os casos se pulam.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_planos_ui_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, params, planes  # noqa: E402


@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
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


def set_module(win, on):
    modules.set_enabled(win.settings, "cor_planos", on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def card(win):
    return {c.section.key: c for c in win.cards}["planos"]


def load_frame(win):
    """Um quadro na prévia sem passar pelo ffmpeg: pele (escala Monk) no meio, céu em cima, verde embaixo."""
    from pelicula.ui.main_window import qimage_from
    from test_masks import MONK, code
    h, w = 180, 320
    img = np.zeros((h, w, 3))
    img[:60] = (0.45, 0.62, 0.85)
    img[60:120] = (0.5, 0.5, 0.5)
    img[120:] = (0.25, 0.5, 0.2)
    for i, t in enumerate(code(MONK)):
        img[70:110, 10 + i * 30:34 + i * 30] = t
    arr = np.rint(img * 255).astype(np.uint8)
    win.set_mode("pelicula")
    win.cur = arr
    win.cur_q = qimage_from(arr)
    win.cur_frame = 0
    win._uploaded = None
    win.render_now()
    APP.processEvents()
    return arr


def test_beta_module_starts_off_and_only_hides_the_card(win):
    assert not modules.is_enabled(win.settings, "cor_planos")
    assert card(win).isHidden()
    set_module(win, True)
    assert not card(win).isHidden()
    win.store.set("planos_on", True)
    win.store.set("planos_fundo_exposicao", -1.0)
    before = dict(win.store.values)
    set_module(win, False)
    assert card(win).isHidden() and dict(win.store.values) == before  # desligar não muda o look
    assert "cor_planos" in modules.used_by(win.store.values)
    set_module(win, True)
    win.store.set_all(params.defaults())


def test_card_groups_front_back_and_skin(win):
    set_module(win, True)
    ui = win.planes_ui
    assert set(ui.groups) == {"frente", "fundo", "pele"}
    for gid in ("frente", "fundo"):
        keys = {r.param.key for r in ui.groups[gid].findChildren(type(card(win).rows[0]).__mro__[1])
                if hasattr(r, "param")}
        assert set(planes.plane_keys(gid)) <= keys, gid
    skin = {r.param.key for r in ui.groups["pele"].findChildren(type(card(win).rows[0]).__mro__[1])
            if hasattr(r, "param")}
    assert set(planes.skin_keys()) <= skin and "planos_proteger_pele" in skin
    # cinco ajustes por plano
    assert len(planes.plane_keys("frente")) == len(planes.plane_keys("fundo")) == 5


def test_pronto_fills_the_controls_with_one_undo_step(win):
    set_module(win, True)
    win.store.set_all(params.defaults())
    win.planes_ui.apply_pronto("destacar")
    v = win.store.values
    assert v["planos_on"] and v["planos_tipo"] == "radial" and v["planos_fundo_exposicao"] == -0.5
    win.store.undo()
    assert not win.store.values["planos_on"]
    win.store.set_all(params.defaults())


def test_view_planes_draws_an_overlay_only_on_screen(win):
    set_module(win, True)
    win.store.set_all(params.defaults())
    load_frame(win)
    assert win.viewer.overlay is None
    win.planes_ui.btn_view.setChecked(True)
    APP.processEvents()
    ov = win.viewer.overlay
    assert ov is not None and ov.width() == 320 and ov.height() == 180, win.preview_tools.last_error
    # a receita do quadro (a da exportação) não muda com a camada da tela
    a = win.frame_recipe().render(win.engine, win.cur, 0)
    win.planes_ui.btn_view.setChecked(False)
    APP.processEvents()
    assert win.viewer.overlay is None
    assert np.array_equal(win.frame_recipe().render(win.engine, win.cur, 0), a)
    # módulo desligado: a camada some
    win.planes_ui.btn_view.setChecked(True)
    set_module(win, False)
    assert not win.planes_ui.view_on and win.viewer.overlay is None
    set_module(win, True)


def test_skin_eyedropper_sets_the_skin_center(win):
    set_module(win, True)
    win.store.set_all(params.defaults())
    load_frame(win)
    win.planes_ui.btn_pick.setChecked(True)
    assert win.viewer.picking
    # clique no 6º tom da escala (x ≈ 172 de 320, y ≈ 90 de 180)
    win.viewer.pick_at(172 / 320, 90 / 180)
    APP.processEvents()
    assert not win.viewer.picking and not win.planes_ui.btn_pick.isChecked()
    hue = win.store.values["planos_pele_centro"]
    assert hue != params.PARAMS["planos_pele_centro"].default and 30.0 < hue < 100.0
    # no cinza não acerta nada (avisa e deixa como estava)
    win.planes_ui.btn_pick.setChecked(True)
    win.viewer.pick_at(5 / 320, 90 / 180)
    APP.processEvents()
    assert win.store.values["planos_pele_centro"] == hue
    # Esc cancela
    win.planes_ui.btn_pick.setChecked(True)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not win.viewer.picking and not win.planes_ui.btn_pick.isChecked()
    win.store.set_all(params.defaults())
