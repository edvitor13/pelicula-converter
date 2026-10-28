"""Casos da interface das chaves de animação (losangos no inspetor, no look e na linha do tempo).

Rodados por test_chaves_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Só os casos da janela (no fim)
precisam de OpenGL 3.3: sem ele, pulam.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import keyframes, params  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import keyframes_ui as kui  # noqa: E402


def _model():
    from pelicula.ui.edit_model import TimelineModel
    src = tl.Source("C:/v/a.mp4", 320, 180, 24.0, "24/1", 240, 10.0, has_audio=True)
    m = TimelineModel(tl.Sequence.for_source(src))
    v = next(c for c in m.seq.clips if c.kind == tl.VIDEO)
    return m, v


def _inspector():
    from pelicula.ui.edit_panels import ClipInspector
    m, v = _model()
    insp = ClipInspector(m)
    m.select([v.id])
    return m, v, insp


def _row(cards, key):
    return next(r for card in cards for r in card.rows if r.param.key == key)


def _actions(menu) -> dict:
    from PySide6.QtGui import QAction
    return {a.objectName(): a for a in menu.findChildren(QAction)}


def _look():
    from pelicula.ui.store import ParamStore
    from pelicula.ui.widgets import SectionCard
    st = ParamStore()
    cards = [SectionCard(sec, st) for sec in params.SECTIONS]
    st.changed.connect(lambda key: [c.refresh(key) for c in cards if key == "*" or key in c.keys()])
    return st, cards, kui.KeyRows(st, st, cards)


# ------------------------------------------------------------------ inspetor do clipe
def test_every_animatable_clip_param_has_a_diamond():
    m, v, insp = _inspector()
    video = set(keyframes.animatable(insp.vstore.schema))
    assert set(insp.vkeys.controls) == video and "velocidade" not in video
    assert set(insp.akeys.controls) == {"volume"}
    for card in insp.vcards:
        for r in card.rows:
            assert (r.param.key in insp.vkeys.controls) == (r.param.key in video)


def test_diamond_states_add_and_update_at_the_playhead():
    m, v, insp = _inspector()
    ctl = insp.vkeys.controls["exposicao"]
    insp.set_playhead(10)
    assert insp.vstore.view_frame == 10 and ctl.button.state == kui.NONE and ctl.button.isEnabled()
    assert not ctl.prev.isVisibleTo(ctl) and not ctl.next.isVisibleTo(ctl)
    ctl.button.click()                                   # primeira chave: o valor atual
    assert m.keys_of(v.id, "exposicao") == [(10.0, 0.0, "linear")]
    assert ctl.button.state == kui.ON and ctl.prev.isVisibleTo(ctl)
    insp.set_playhead(30)
    assert ctl.button.state == kui.ANIMATED
    assert ctl.prev.isEnabled() and not ctl.next.isEnabled()
    _row(insp.vcards, "exposicao").slider.valueChanged.emit(1.0)  # fora de uma chave: grava outra
    m.commit()
    assert m.keys_of(v.id, "exposicao") == [(10.0, 0.0, "linear"), (30.0, 1.0, "linear")]
    assert v.values["exposicao"] == 0.0, "o valor fixo não muda com o ajuste animado"
    assert ctl.button.state == kui.ON
    insp.set_playhead(20)
    assert insp.vstore.shown("exposicao") == pytest.approx(0.5)
    row = _row(insp.vcards, "exposicao")
    assert row.slider.value() == pytest.approx(0.5), "o controle mostra o valor no cursor"
    insp.set_playhead(10)
    row.slider.valueChanged.emit(-0.5)                   # em cima da chave: troca o valor dela
    m.commit()
    assert m.keys_of(v.id, "exposicao")[0] == (10.0, -0.5, "linear")
    # um ajuste sem chaves continua trocando o valor fixo
    _row(insp.vcards, "contraste").slider.valueChanged.emit(0.3)
    m.commit()
    assert v.values["contraste"] == pytest.approx(0.3) and "contraste" not in v.keys


def test_slider_drag_on_an_animated_param_is_one_undo_step():
    m, v, insp = _inspector()
    insp.set_playhead(0)
    insp.vkeys.add_key("saturacao")
    insp.set_playhead(24)
    row = _row(insp.vcards, "saturacao")
    for x in (0.1, 0.2, 0.3, 0.4):
        row.slider.valueChanged.emit(x)
    m.commit()
    assert m.keys_of(v.id, "saturacao")[-1] == (24.0, pytest.approx(0.4), "linear")
    m.undo()
    assert len(m.keys_of(v.id, "saturacao")) == 1, "arrastar o slider é um passo só"


def test_prev_next_arrows_ask_to_seek():
    m, v, insp = _inspector()
    for t in (5, 40, 90):
        m.add_key(v.id, "escala", t, 1.0)
    seen = []
    insp.seekRequested.connect(seen.append)
    insp.set_playhead(40)
    ctl = insp.vkeys.controls["escala"]
    assert ctl.prev.isEnabled() and ctl.next.isEnabled()
    ctl.prev.click()
    ctl.next.click()
    insp.set_playhead(95)
    assert not ctl.next.isEnabled()
    ctl.prev.click()
    assert seen == [5, 90, 90]


def test_curve_menu_remove_and_clear():
    m, v, insp = _inspector()
    m.add_key(v.id, "opacidade", 0, 1.0)
    m.add_key(v.id, "opacidade", 48, 0.0)
    insp.set_playhead(20)                                 # no meio: a curva é a da chave da esquerda
    menu = insp.vkeys.menu_for("opacidade")
    acts = _actions(menu)
    labels = [a.text() for a in menu.findChild(type(menu), "key_curve").actions()]
    assert labels == [kui._(keyframes.EASING_LABELS[e]) for e in keyframes.EASINGS]
    assert acts["curve_linear"].isChecked() and not acts["key_remove"].isEnabled()
    acts["curve_suavizar"].trigger()
    assert m.keys_of(v.id, "opacidade")[0] == (0.0, 1.0, "suavizar")
    insp.set_playhead(48)
    menu = insp.vkeys.menu_for("opacidade")
    acts = _actions(menu)
    assert acts["key_remove"].isEnabled()
    acts["key_remove"].trigger()
    assert [k[0] for k in m.keys_of(v.id, "opacidade")] == [0.0]
    menu = insp.vkeys.menu_for("opacidade")
    _actions(menu)["key_clear"].trigger()
    assert m.keys_of(v.id, "opacidade") == [] and insp.vkeys.controls["opacidade"].button.state == kui.NONE
    m.undo()
    assert len(m.keys_of(v.id, "opacidade")) == 1 and insp.vkeys.controls["opacidade"].button.state != kui.NONE


def test_playhead_outside_the_clip_keys_its_nearest_end():
    m, v, insp = _inspector()
    insp.set_playhead(10_000)
    assert insp.vstore.view_frame == v.end - 1
    insp.vkeys.add_key("rotacao")
    assert m.keys_of(v.id, "rotacao")[0][0] == v.end - 1
    m.select([])
    assert insp.vstore.view_frame is None and not insp.vkeys.can_key()


def test_wheel_and_audio_volume_keys():
    m, v, insp = _inspector()
    insp.set_playhead(12)
    insp.vkeys.add_key("roda_meios")
    insp.set_playhead(36)
    _row(insp.vcards, "roda_meios").wheel.valueChanged.emit(0.2, -0.1)
    m.commit()
    assert [k[1] for k in m.keys_of(v.id, "roda_meios")] == [[0.0, 0.0], [pytest.approx(0.2), pytest.approx(-0.1)]]
    a = next(c for c in m.seq.clips if c.kind == tl.AUDIO)
    m.select([a.id])
    insp.set_playhead(0)
    ctl = insp.akeys.controls["volume"]
    ctl.button.click()
    insp.set_playhead(48)
    _row(insp.acards, "volume").slider.valueChanged.emit(-12.0)
    m.commit()
    assert [k[:2] for k in m.keys_of(a.id, "volume")] == [(0.0, 0.0), (48.0, -12.0)]


# ------------------------------------------------------------------ painel do look
def test_look_diamonds_bound_to_the_param_store():
    st, cards, rows = _look()
    assert set(rows.controls) == set(keyframes.animatable(params.FILM))
    assert not rows.can_key()                             # sem mídia (sem cursor) nada a gravar
    st.set("exposicao", 0.25)
    assert st.values["exposicao"] == 0.25
    rows.set_frame(0)
    rows.controls["exposicao"].button.click()
    assert st.keys_of("exposicao") == [(0.0, 0.25, "linear")]
    rows.set_frame(48)
    st.set("exposicao", 1.25)                             # chave automática
    st.commit()
    assert st.keys_of("exposicao")[-1] == (48.0, 1.25, "linear") and st.values["exposicao"] == 0.25
    rows.set_frame(24)
    row = _row(cards, "exposicao")
    assert row.slider.value() == pytest.approx(0.75)
    rows.set_curve("exposicao", "suavizar_saida")
    assert st.keys_of("exposicao")[0][2] == "suavizar_saida"
    rows.set_frame(48)
    assert rows.remove_key("exposicao") and len(st.keys_of("exposicao")) == 1
    st.undo()
    assert len(st.keys_of("exposicao")) == 2
    assert rows.clear("exposicao") and st.keys == {}
    rows.set_frame(None)
    st.set("exposicao", 0.0)                              # sem cursor: o valor fixo, como sempre
    assert st.values["exposicao"] == 0.0


def test_look_color_param_keys():
    st, cards, rows = _look()
    color = next(k for k, p in keyframes.animatable(params.FILM).items() if p.kind == "color")
    rows.set_frame(0)
    rows.add_key(color)
    rows.set_frame(10)
    st.set(color, [1.0, 0.0, 0.0])
    assert st.keys_of(color)[-1][1] == [1.0, 0.0, 0.0]
    rows.set_frame(5)
    assert _row(cards, color).btn.color.redF() > 0.4


# ------------------------------------------------------------------ losangos na linha do tempo
def _canvas():
    from pelicula.ui.timeline_view import TimelineCanvas
    m, v = _model()
    cv = TimelineCanvas(m)
    cv.resize(1400, 260)
    cv.show()
    APP.processEvents()
    seen = []
    cv.seekRequested.connect(seen.append)
    return m, v, cv, seen


def _key_point(cv, clip, frame):
    from PySide6.QtCore import QPoint
    r = cv.clip_rect(clip)
    return QPoint(int(round(cv.frame_to_x(frame))), int(round(cv.key_y(r))))


def _click(cv, pt, mods=None, to=None):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    mods = mods if mods is not None else Qt.KeyboardModifier.NoModifier
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, mods, pt)
    if to is not None:
        QTest.mouseMove(cv, QPoint((pt.x() + to.x()) // 2, pt.y()))
        QTest.mouseMove(cv, to)
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, mods, to if to is not None else pt)


def test_timeline_shows_the_selected_clip_keys_merged():
    m, v, cv, _seen = _canvas()
    m.add_key(v.id, "exposicao", 20, 0.0)
    m.add_key(v.id, "escala", 20, 1.0)
    m.add_key(v.id, "escala", 60, 0.5)
    assert cv.key_clips() == []                           # nada selecionado: nenhum losango
    m.select([v.id])
    assert [f for f, _n in cv.key_marks(v)] == [20.0, 60.0]
    assert sorted(dict(cv.key_marks(v))[20.0]) == ["escala", "exposicao"]
    tip = cv.key_tooltip(_key_point(cv, v, 20))
    assert tip and kui._("Exposição") in tip and kui._("Escala") in tip
    assert cv.key_at(_key_point(cv, v, 40)) is None
    cv.grab()                                             # desenha sem erro


def test_timeline_key_click_seeks_and_drag_moves_in_one_undo_step():
    from PySide6.QtCore import QPoint
    m, v, cv, seen = _canvas()
    m.add_key(v.id, "exposicao", 20, 0.0)
    m.add_key(v.id, "escala", 20, 1.0)
    m.add_key(v.id, "escala", 60, 0.5)
    m.select([v.id])
    _click(cv, _key_point(cv, v, 60))
    assert seen[-1] == 60 and cv.key_sel == {60.0} and m.keys_of(v.id, "escala")[1][0] == 60.0
    cv.snap = False
    a = _key_point(cv, v, 20)
    _click(cv, a, to=a + QPoint(int(10 * cv.ppf), 0))      # 10 quadros para a direita
    assert [k[0] for k in m.keys_of(v.id, "escala")] == [30.0, 60.0]
    assert [k[0] for k in m.keys_of(v.id, "exposicao")] == [30.0]
    assert seen[-1] == 30 and cv.key_sel == {30.0}
    m.undo()
    assert [k[0] for k in m.keys_of(v.id, "escala")] == [20.0, 60.0] and m.keys_of(v.id, "exposicao")[0][0] == 20.0


def test_timeline_key_multi_select_delete_and_undo():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    m, v, cv, _seen = _canvas()
    for t in (10, 30, 50):
        m.add_key(v.id, "opacidade", t, 1.0)
    m.add_key(v.id, "rotacao", 30, 5.0)
    m.select([v.id])
    _click(cv, _key_point(cv, v, 10))
    _click(cv, _key_point(cv, v, 30), Qt.KeyboardModifier.ShiftModifier)
    assert cv.key_sel == {10.0, 30.0}
    QTest.keyClick(cv, Qt.Key.Key_Delete)
    assert [k[0] for k in m.keys_of(v.id, "opacidade")] == [50.0] and m.keys_of(v.id, "rotacao") == []
    assert m.seq.find(v.id) is not None, "Delete com chaves selecionadas não apaga o clipe"
    m.undo()
    assert len(m.keys_of(v.id, "opacidade")) == 3 and len(m.keys_of(v.id, "rotacao")) == 1
    QTest.keyClick(cv, Qt.Key.Key_Delete)                  # sem chaves selecionadas: o clipe vai embora
    assert m.seq.find(v.id) is None


def test_timeline_key_drag_snaps_and_stays_inside_the_clip():
    from PySide6.QtCore import QPoint
    m, v, cv, _seen = _canvas()
    m.add_key(v.id, "brilho", 5, 0.0)
    m.add_key(v.id, "brilho", 100, 1.0)
    m.select([v.id])
    cv.set_playhead(120)
    a = _key_point(cv, v, 100)
    _click(cv, a, to=a + QPoint(int(19 * cv.ppf) + 2, 0))  # perto do cursor (120): o ímã gruda nele
    assert [k[0] for k in m.keys_of(v.id, "brilho")] == [5.0, 120.0]
    b = _key_point(cv, v, 5)
    _click(cv, b, to=b - QPoint(int(40 * cv.ppf), 0))      # não sai pela esquerda do clipe
    assert m.keys_of(v.id, "brilho")[0][0] == float(v.start)


# ------------------------------------------------------------------ faixa das chaves do look
def _strip(playhead=0):
    from pelicula.ui.store import ParamStore
    st = ParamStore()
    pos = {"f": playhead}
    strip = kui.KeyStrip(st, lambda f: 20 + 4 * f, lambda x: (x - 20) / 4, lambda: pos["f"], lambda: 24.0,
                         "Look", 20)
    strip.resize(900, 18)
    strip.show()
    seen = []
    strip.seekRequested.connect(seen.append)
    return st, strip, seen, pos


def _strip_click(strip, frame, mods=None, to_frame=None):
    from PySide6.QtCore import QPoint
    _click(strip, QPoint(20 + 4 * frame, 9), mods, None if to_frame is None else QPoint(20 + 4 * to_frame, 9))


def test_look_strip_click_drag_delete():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    st, strip, seen, _pos = _strip()
    st.add_key("exposicao", 10, 0.0)
    st.add_key("grao_forca", 10, 1.0)
    st.add_key("exposicao", 50, 1.0)
    assert strip.has_keys() and [f for f, _n in strip.marks()] == [10.0, 50.0]
    assert kui._("Exposição") in strip.tooltip_at(20 + 40)
    _strip_click(strip, 50)
    assert seen == [50] and strip.selected == {50.0}
    _strip_click(strip, 10, to_frame=30)                  # arrasta as duas chaves do quadro 10
    assert [k[0] for k in st.keys_of("exposicao")] == [30.0, 50.0] and st.keys_of("grao_forca")[0][0] == 30.0
    assert seen[-1] == 30 and strip.selected == {30.0}
    st.undo()
    assert st.keys_of("grao_forca")[0][0] == 10.0, "mover é um passo só do desfazer"
    _strip_click(strip, 10)
    _strip_click(strip, 50, Qt.KeyboardModifier.ShiftModifier)
    assert strip.selected == {10.0, 50.0}
    strip.setFocus()
    QTest.keyClick(strip, Qt.Key.Key_Delete)
    assert st.keys == {}
    st.undo()
    assert len(st.keys_of("exposicao")) == 2 and len(st.keys_of("grao_forca")) == 1
    strip.grab()


def test_look_strip_drag_snaps_to_the_playhead_and_stops_at_zero():
    st, strip, _seen, _pos = _strip(playhead=40)
    st.add_key("exposicao", 20, 0.0)
    _strip_click(strip, 20, to_frame=39)
    assert st.keys_of("exposicao")[0][0] == 40.0
    _strip_click(strip, 40, to_frame=-30)
    assert st.keys_of("exposicao")[0][0] == 0.0


# ------------------------------------------------------------------ na janela (precisa de OpenGL)
@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    st = prefs.settings()
    st.setValue("auto_update", "false")
    st.setValue("language", "pt_BR")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def _pump(cond, timeout=20.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_look_keys_in_the_window_follow_the_playhead(win, sample_video):
    win.set_mode("pelicula")
    win.cur = None
    win.load_media(sample_video)
    assert _pump(lambda: win.cur is not None)
    win.store.clear_keys()
    assert not win.look_strip.isVisible()
    win.request_frame(0)
    assert win.store.view_frame == 0
    win.look_keys.controls["exposicao"].button.click()    # o losango do painel do look
    assert win.store.keys_of("exposicao") == [(0.0, win.store.values["exposicao"], "linear")]
    assert win.look_strip.isVisible(), "a faixa das chaves aparece sob a barra da prévia"
    win.request_frame(20)
    assert win.store.view_frame == 20
    win.store.set("exposicao", 1.0)                       # chave automática no cursor
    assert [k[0] for k in win.store.keys_of("exposicao")] == [0.0, 20.0]
    win.request_frame(10)
    row = next(r for c in win.cards for r in c.rows if r.param.key == "exposicao")
    assert row.slider.value() == pytest.approx(win.store.value_at("exposicao", 10))
    win.set_mode("edicao")
    win._set_edit_film(True)
    assert win.look_lane.isVisible() and not win.look_strip.isVisible()
    win._set_edit_film(False)
    assert not win.look_lane.isVisible()
    win.set_mode("pelicula")
    win.store.clear_keys()
    assert not win.look_strip.isVisible()


def test_clip_inspector_in_the_window_follows_the_playhead(win, sample_video):
    from pelicula import media
    win.set_mode("pelicula")
    win.cur = None
    win.load_media(sample_video)
    assert _pump(lambda: win.cur is not None)
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.set_key(v.id, "opacidade", 0, 1.0)
    seq.set_key(v.id, "opacidade", 10, 0.0)
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.set_mode("edicao")
    win.model.select([v.id])
    win.request_frame(5)
    assert _pump(lambda: win.inspector.vstore.view_frame == 5)
    assert win.inspector.vstore.shown("opacidade") == pytest.approx(0.5)
    seen = []
    win.inspector.seekRequested.connect(seen.append)
    win.inspector.vkeys.controls["opacidade"].next.click()
    assert seen == [10] and _pump(lambda: win.frame_idx == 10)
    win.set_mode("pelicula")
