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


# ------------------------------------------------------------------ máscara e alças
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from pelicula import mascaras_clipe as mk  # noqa: E402
from pelicula.ui import alcas  # noqa: E402


def with_mask(win, **values) -> tl.Clip:
    set_module(win, MODULE, True)
    c = fresh(win)
    win.model.set_clip_values(c.id, {**c.values, "mascara_forma": "retangulo", "mascara_largura": 600,
                                     "mascara_altura": 400, **values})
    win.render_now()
    pump(0.2)
    return win.model.seq.find(c.id)


def handles(win):
    return win.vfx_ui.fronts["mascaras_ui"].handles


def view(win):
    return alcas.View(win.viewer.proc_rect())


def at(pt) -> QPoint:
    return QPoint(int(round(pt.x())), int(round(pt.y())))


def drag(win, a, b, mods=Qt.KeyboardModifier.NoModifier) -> None:
    vw = win.viewer
    QTest.mousePress(vw, Qt.MouseButton.LeftButton, mods, at(a))
    for k in (0.3, 0.7, 1.0):
        QTest.mouseMove(vw, at(a + (b - a) * k))
    QTest.mouseRelease(vw, Qt.MouseButton.LeftButton, mods, at(b))
    pump(0.1)


def test_mask_card_and_handles_follow_the_module(win):
    c = with_mask(win)
    assert card(win, "mascara").isVisibleTo(win.inspector)
    lay = card(win, "mascara").parentWidget().layout()
    assert lay.indexOf(card(win, "mascara")) == lay.indexOf(card(win, "recorte")) + 1
    assert win.viewer.handles.visible() and win.viewer._handles_on()
    set_module(win, MODULE, False)
    assert not win.viewer.handles.visible() and not card(win, "mascara").isVisibleTo(win.inspector)
    set_module(win, MODULE, True)
    win.model.set_clip_values(c.id, {**win.model.seq.find(c.id).values, "mascara_forma": "nenhuma"})
    pump()
    assert not win.viewer.handles.visible()


def test_drag_center_moves_the_mask_in_one_undo_step(win):
    c = with_mask(win)
    h = handles(win)
    st = h.state()
    r = view(win)
    center = h._points(st, r)["centro"]
    steps = win.model.history._pos
    target = center + QPointF(r.rect.width() * 0.1, r.rect.height() * 0.1)
    drag(win, center, target)
    v = win.model.seq.find(c.id).values
    want = st.clip_px(*r.to_frac(QPointF(at(target))))
    assert abs(v["mascara_x"] - want[0]) < 3 and abs(v["mascara_y"] - want[1]) < 3
    assert v["mascara_x"] > 20 and v["mascara_y"] > 20
    assert win.model.history._pos == steps + 1
    win.model.undo()
    pump()
    assert win.model.seq.find(c.id).values["mascara_x"] == 0.0


def test_corner_and_rotation_handles(win):
    c = with_mask(win)
    h = handles(win)
    hp = h._points(h.state(), view(win))
    corner = hp["cantos"][2]  # embaixo à direita
    drag(win, corner, corner + (corner - hp["centro"]) * 0.5)
    v = win.model.seq.find(c.id).values
    assert v["mascara_largura"] == pytest.approx(900, abs=15) and v["mascara_altura"] == pytest.approx(600, abs=15)
    hp = h._points(h.state(), view(win))
    knob = hp["girar"]
    right = QPointF(hp["centro"].x() + abs(knob.y() - hp["centro"].y()), hp["centro"].y())
    drag(win, knob, right, Qt.KeyboardModifier.ShiftModifier)
    assert win.model.seq.find(c.id).values["mascara_rotacao"] == pytest.approx(90.0, abs=0.01)


def test_drag_on_an_animated_center_sets_a_key_at_the_playhead(win):
    c = with_mask(win)
    win.model.add_key(c.id, "mascara_x", c.start, -200.0)
    win.model.add_key(c.id, "mascara_x", c.start + 40, 200.0)
    win.seek(c.start + 20)
    win.render_now()
    pump(0.2)
    h = handles(win)
    r = view(win)
    center = h._points(h.state(), r)["centro"]
    drag(win, center, center + QPointF(r.rect.width() * 0.1, 0.0))
    keys = win.model.keys_of(c.id, "mascara_x")
    assert [round(k[0]) for k in keys] == [c.start, c.start + 20, c.start + 40]
    assert keys[1][1] > 20 and keys[0][1] == -200.0 and keys[2][1] == 200.0


def test_draw_a_polygon_with_clicks_and_close_with_a_double_click(win):
    c = with_mask(win)
    ui = win.vfx_ui.fronts["mascaras_ui"]
    ui.btn_draw.click()
    pump()
    assert win.model.seq.find(c.id).values["mascara_forma"] == "poligono" and ui.handles.draft == []
    steps = win.model.history._pos
    vw, r = win.viewer, view(win)
    fracs = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)]
    for f in fracs:  # o último é o primeiro clique de um duplo: o segundo chega como "dois cliques" e fecha
        QTest.mouseClick(vw, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(r.to_widget(*f)))
    QTest.mouseDClick(vw, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(r.to_widget(*fracs[3])))
    pump(0.2)
    clip = win.model.seq.find(c.id)
    pts = mk.points_of(clip)
    assert len(pts) == 4 and ui.handles.draft is None
    assert win.model.history._pos == steps + 1
    # Os pontos ficam em volta do centro (o meio do polígono) e voltam ao lugar clicado.
    st = ui.handles.state()
    assert abs(sum(p[0] for p in pts)) < 1 and abs(sum(p[1] for p in pts)) < 1
    back = [st.frac(p) for p in mk.to_clip(pts, st.values)]
    for (fx, fy), (bx, by) in zip(fracs, back):
        assert abs(fx - bx) < 0.01 and abs(fy - by) < 0.01
    # Arrastar um ponto: um passo do desfazer.
    hp = ui.handles._points(st, r)
    drag(win, hp["pontos"][0], hp["pontos"][0] - (hp["centro"] - hp["pontos"][0]) * 0.3)
    assert mk.points_of(win.model.seq.find(c.id))[0] != pts[0]
    assert win.model.history._pos == steps + 2
    win.model.undo()
    pump()
    assert mk.points_of(win.model.seq.find(c.id)) == pts


def test_esc_cancels_a_half_drawn_polygon(win):
    c = with_mask(win)
    ui = win.vfx_ui.fronts["mascaras_ui"]
    ui.btn_draw.click()
    pump()
    r = view(win)
    for f in ((0.2, 0.2), (0.6, 0.3)):
        QTest.mouseClick(win.viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(r.to_widget(*f)))
    assert len(ui.handles.draft) == 2
    QTest.keyClick(win, Qt.Key.Key_Escape)
    pump()
    assert ui.handles.draft is None and mk.points_of(win.model.seq.find(c.id)) == []
    # Polígono sem pontos: um clique na prévia já começa a desenhar.
    QTest.mouseClick(win.viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(r.to_widget(0.5, 0.5)))
    assert ui.handles.draft is not None and len(ui.handles.draft) == 1
    ui.handles.escape()


def test_handles_are_screen_only(win):
    """As alças só se desenham no widget: o quadro renderizado é o mesmo com e sem elas."""
    with_mask(win, mascara_uso="desfocar")
    a = win.cur.copy()
    win.viewer.set_handles(None)
    try:
        win.render_now()
        pump(0.2)
        assert (win.cur == a).all()
    finally:
        win.viewer.set_handles(win.vfx_ui.handles)
