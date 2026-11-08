"""Casos da interface dos efeitos visuais da 1.9 (ARQUITETURA §49.10): o "Novo ▸ Camada de ajuste" (módulo Beta
"efeitos_clipe"), o inspetor da camada de ajuste e a API dos cartões e camadas de prévia das frentes (`ui/vfx_ui.py`).

Rodados por test_vfx_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado sozinho.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, vfx, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs, vfx_ui  # noqa: E402


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
    """Projeto novo no modo Edição com um clipe de cor de 4 s em V1."""
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    c = seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))[0]
    c.dur = 96
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    pump()
    return win.model.seq


def test_the_module_starts_off_and_hides_the_menu_item(win):
    assert not modules.is_enabled(win.settings, "efeitos_clipe")
    assert not win.vfx_ui.adj_action.isVisible()
    set_module(win, "efeitos_clipe", True)
    assert win.vfx_ui.adj_action.isVisible()
    set_module(win, "titulos_geradores", False)
    set_module(win, "efeitos_sonoros", False)
    try:
        assert win.bin.btn_new.isVisibleTo(win.bin)  # só com a camada de ajuste, o "Novo" continua
    finally:
        set_module(win, "titulos_geradores", True)


def test_new_adjustment_layer_goes_over_the_clip_in_one_undo_step(win):
    set_module(win, "efeitos_clipe", True)
    fresh(win)
    win.seek(10)
    pump()
    steps = win.model.history._pos
    win.vfx_ui.adj_action.trigger()
    pump()
    seq = win.model.seq
    adj = [c for c in seq.clips if vfx.is_adjustment(seq, c)]
    assert len(adj) == 1 and adj[0].track == 1 and adj[0].start == 10
    assert win.model.history._pos == steps + 1
    win.model.undo()
    pump()
    assert not any(vfx.is_adjustment(win.model.seq, c) for c in win.model.seq.clips)


def test_inspector_hides_the_framing_of_an_adjustment_layer(win):
    set_module(win, "efeitos_clipe", True)
    fresh(win)
    win.vfx_ui.adj_action.trigger()
    pump()
    insp = win.inspector
    cards = {c.section.key: c for c in insp.vcards}
    rows = {r.param.key: r for r in cards["transformar"].rows}
    assert insp.current_clip() is not None and vfx.is_adjustment(win.model.seq, insp.current_clip())
    assert not rows["escala"].isVisibleTo(insp) and not rows["pos_x"].isVisibleTo(insp)
    cards["transformar"].set_expanded(True)
    pump()
    assert rows["opacidade"].isVisibleTo(cards["transformar"]) and rows["mesclagem"].isVisibleTo(cards["transformar"])
    assert not cards["camera"].isVisibleTo(insp)
    plain = next(c for c in win.model.seq.clips if not vfx.is_adjustment(win.model.seq, c))
    win.model.select([plain.id])
    pump()
    assert rows["escala"].isVisibleTo(cards["transformar"]) and cards["camera"].isVisibleTo(insp)


def test_a_front_card_follows_its_module(win):
    card = win.vfx_ui.add_section("luz_copiadora", "efeitos_clipe", after="luz")
    try:
        set_module(win, "efeitos_clipe", False)
        assert not card.isVisibleTo(win.inspector)
        set_module(win, "efeitos_clipe", True)
        assert card.isVisibleTo(win.inspector)
        assert win.vfx_ui.module_tools()["efeitos_clipe"] == [card]
    finally:
        win.vfx_ui.sections.pop("luz_copiadora", None)
        card.setVisible(True)


def test_an_overlay_only_draws_with_its_module(win):
    calls = []

    def provider(ctx):
        calls.append(1)
        return None

    win.vfx_ui.add_overlay("teste", "efeitos_clipe", provider)
    set_module(win, "efeitos_clipe", False)
    win.preview_tools.refresh()
    assert calls == []
    set_module(win, "efeitos_clipe", True)
    fresh(win)
    win.render_now() if hasattr(win, "render_now") else None
    pump()
    win.preview_tools.refresh()
    assert calls
    img = vfx_ui.VfxUI.points_overlay((40, 20), [(0.5, 0.5)], radius=3)
    assert img.shape == (20, 40, 4) and img[10, 20, 3] == 1.0 and img[0, 0, 3] == 0.0
