"""Casos da interface da luz e atmosfera da 1.9 (F4, ARQUITETURA §52.6): os cartões seguem os módulos Beta
"atmosfera" e "luzes_lente", ficam depois do cartão "Efeitos", o ponto do flare e a origem dos raios escolhidos na
prévia (um passo do desfazer) e a camada de prévia com os pontos.

Rodados por test_atmosfera_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado
sozinho.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, timeline as tl  # noqa: E402
from pelicula.ui import atmosfera_ui, main_window as mw, prefs  # noqa: E402


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


def fresh(win) -> tl.Sequence:
    """Projeto novo no modo Edição com um clipe de cor de 4 s em V1, selecionado."""
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    c = seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))[0]
    c.dur = 96
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    win.model.select([c.id])
    win.seek(10)
    pump()
    return win.model.seq


def ui(win) -> atmosfera_ui.AtmosferaUI:
    return win.vfx_ui.fronts["atmosfera_ui"]


def test_cards_follow_their_modules_and_come_after_effects(win):
    fresh(win)  # um clipe de vídeo selecionado: o inspetor mostra os cartões de vídeo
    insp = win.inspector
    a = ui(win)
    assert not modules.default_enabled("atmosfera") and not modules.default_enabled("luzes_lente")
    set_module(win, "atmosfera", False)
    set_module(win, "luzes_lente", False)
    for card in a.cards.values():
        assert not card.isVisibleTo(insp)
    set_module(win, "atmosfera", True)
    assert a.cards["nevoa"].isVisibleTo(insp) and a.cards["particulas"].isVisibleTo(insp)
    assert not a.cards["luzes"].isVisibleTo(insp) and not a.cards["desfoque_lente"].isVisibleTo(insp)
    set_module(win, "luzes_lente", True)
    assert all(card.isVisibleTo(insp) for card in a.cards.values())
    lay = a.cards["luzes"].parentWidget().layout()
    ref = win.vfx_ui.card("efeitos")
    order = [lay.indexOf(a.cards[k]) for k, _m in atmosfera_ui.SECTIONS]
    assert order == list(range(lay.indexOf(ref) + 1, lay.indexOf(ref) + 5))
    tools = win.vfx_ui.module_tools()
    assert set(tools["atmosfera"]) == {a.cards["nevoa"], a.cards["particulas"]}
    assert set(tools["luzes_lente"]) == {a.cards["luzes"], a.cards["desfoque_lente"]}


def test_pick_the_flare_point_and_the_rays_origin_on_the_preview(win):
    set_module(win, "luzes_lente", True)
    seq = fresh(win)
    c = seq.clips[0]
    a = ui(win)
    steps = win.model.history._pos
    a.buttons["flare"].click()
    pump()
    win.viewer.picked.emit(0.75, 0.25)
    pump()
    v = win.model.seq.find(c.id).values
    assert v["flare_fonte"] == "ponto"
    assert v["flare_x"] == pytest.approx(0.25 * 16 / 9 * 1080, abs=1) and v["flare_y"] == pytest.approx(-270, abs=1)
    assert win.model.history._pos == steps + 1
    a.buttons["raios"].click()
    pump()
    win.viewer.picked.emit(0.5, 0.0)
    pump()
    v = win.model.seq.find(c.id).values
    assert v["raios_x"] == pytest.approx(0, abs=1) and v["raios_y"] == pytest.approx(-540, abs=1)
    win.model.undo()
    win.model.undo()
    pump()
    v = win.model.seq.find(c.id).values
    assert v["flare_fonte"] == "auto" and v["flare_x"] == 0.0


def test_overlay_shows_the_points_in_use(win):
    set_module(win, "luzes_lente", True)
    seq = fresh(win)
    c = seq.clips[0]
    a = ui(win)

    class Ctx:
        size = (320, 180)

    assert a.overlay(Ctx()) is None  # nada em uso
    win.model.set_clip_values(c.id, {**c.values, "flare_intensidade": 1.0, "flare_fonte": "ponto",
                                     "flare_x": 480.0, "flare_y": -270.0})
    pump()
    img = a.overlay(Ctx())
    assert img is not None and img.shape == (180, 320, 4)
    ys, xs = (img[..., 3] > 0.5).nonzero()
    assert abs(xs.mean() - (480 / (16 / 9 * 1080) + 0.5) * 320) < 2 and abs(ys.mean() - 0.25 * 180) < 2
    set_module(win, "luzes_lente", False)
    win.preview_tools.refresh()  # com o módulo desligado, a camada não desenha (o VfxUI filtra)
    set_module(win, "luzes_lente", True)


def test_a_slider_changes_the_clip_in_one_step(win):
    set_module(win, "atmosfera", True)
    seq = fresh(win)
    c = seq.clips[0]
    card = ui(win).cards["particulas"]
    rows = {r.param.key: r for r in card.rows}
    steps = win.model.history._pos
    win.inspector.vstore.set("part_tipo", "neve")
    pump(0.6)
    assert win.model.seq.find(c.id).values["part_tipo"] == "neve"
    assert win.model.history._pos == steps + 1
    assert "part_semente" in rows and rows["part_semente"].param.advanced
