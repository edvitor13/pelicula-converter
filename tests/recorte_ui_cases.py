"""Casos da interface do recorte e das máscaras da 1.9 (ARQUITETURA §50): os cartões do módulo Beta "recorte_mascaras",
o conta-gotas da cor do fundo e as alças da máscara na prévia (`ui/alcas.py`, `ui/mascaras_ui.py`).

Rodados por test_recorte_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado sozinho.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402

MODULE = "recorte_mascaras"


def pump(timeout: float = 0.1) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        time.sleep(0.01)


@pytest.fixture(scope="module")
def win():
    prefs.settings().setValue("auto_update", "false")
    try:
        w = mw.MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1500, 900)
    w.show()
    APP.processEvents()
    yield w
    w._saved_state = w._state()
    w.close()


def set_module(win, mid: str, on: bool) -> None:
    modules.set_enabled(win.settings, mid, on)
    win.apply_modules()
    pump()


def fresh(win, color: str = "#22aa44") -> tl.Clip:
    """Projeto novo no modo Edição com um clipe de cor de 4 s em V1, selecionado, e o cursor no quadro 10."""
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    c = seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": color}))[0]
    c.dur = 96
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    win.model.select([c.id])
    win.seek(10)
    win.render_now()
    pump(0.3)
    return win.model.seq.find(c.id)


def card(win, key):
    return next(c for c in win.inspector.vcards if c.section.key == key)


# ------------------------------------------------------------------ recorte
def test_the_key_card_follows_the_module(win):
    assert not modules.is_enabled(win.settings, MODULE)
    fresh(win)
    rec = card(win, "recorte")
    assert not rec.isVisibleTo(win.inspector)
    set_module(win, MODULE, True)
    assert rec.isVisibleTo(win.inspector)
    cards = win.inspector.vcards
    lay = rec.parentWidget().layout()
    assert lay.indexOf(rec) == lay.indexOf(card(win, "transformar")) + 1
    assert rec in win.vfx_ui.module_tools()[MODULE]
    set_module(win, MODULE, False)
    assert not rec.isVisibleTo(win.inspector) and cards


def test_eyedropper_picks_the_background_color_in_one_undo_step(win):
    set_module(win, MODULE, True)
    c = fresh(win, "#22aa44")
    ui = win.vfx_ui.fronts["recorte_ui"]
    steps = win.model.history._pos
    ui.btn_pick.click()
    assert win.viewer.picking
    win.viewer.pick_at(0.5, 0.5)
    pump(0.2)
    v = win.model.seq.find(c.id).values
    assert v["chave_tipo"] == "cor"
    assert [round(x * 255) for x in v["chave_cor"]] == [0x22, 0xAA, 0x44]
    assert win.model.history._pos == steps + 1
    win.model.undo()
    pump()
    assert win.model.seq.find(c.id).values["chave_tipo"] == "nenhuma"


def test_eyedropper_refuses_grey_and_esc_cancels(win):
    set_module(win, MODULE, True)
    c = fresh(win, "#808080")
    ui = win.vfx_ui.fronts["recorte_ui"]
    ui.btn_pick.click()
    win.viewer.pick_at(0.5, 0.5)
    pump(0.2)
    assert win.model.seq.find(c.id).values["chave_tipo"] == "nenhuma"
    assert "cinza" in win.statusBar().currentMessage()
    ui.btn_pick.click()
    assert win.viewer.picking
    win.viewer.cancel_pick()
    assert not win.viewer.picking
    win.viewer.picked.emit(0.5, 0.5)  # um clique de outro conta-gotas depois do Esc não é do recorte
    pump(0.2)
    assert win.model.seq.find(c.id).values["chave_tipo"] == "nenhuma"
