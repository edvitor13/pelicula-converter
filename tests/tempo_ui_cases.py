"""Casos da interface do tempo do clipe: rampa de velocidade (presets), reverso e congelar um quadro.

Rodados por test_tempo_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import timemap  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import tempo_ui  # noqa: E402


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


def _actions(menu) -> dict:
    from PySide6.QtGui import QAction
    return {a.objectName(): a for a in menu.findChildren(QAction)}


def _audio(m):
    return next(c for c in m.seq.clips if c.kind == tl.AUDIO)


# ------------------------------------------------------------------ rampa
def test_tempo_panel_lives_in_the_speed_card():
    m, v, insp = _inspector()
    card = next(c for c in insp.vcards if c.section.key == "tempo")
    assert insp.vtempo is not None and insp.vtempo.parent() is card.body
    assert insp.atempo is not None
    p = insp.vtempo
    assert [p.preset.itemData(i) for i in range(p.preset.count())] == list(timemap.PRESET_IDS)
    assert p.btn_apply.isEnabled() and not p.btn_clear.isEnabled()
    assert p.status.text() == "Velocidade constante."


def test_apply_and_clear_a_ramp_is_one_undo_step_each():
    m, v, insp = _inspector()
    p = insp.vtempo
    p.preset.setCurrentIndex(timemap.PRESET_IDS.index("lento_meio"))
    p.amount.setValue(1.0, emit=True)
    p.ramp_s.setValue(1.0, emit=True)
    assert p.amount_text.text() == "100%" and p.ramp_text.text() == "1,0 s"
    p.btn_apply.click()
    c = m.seq.find(v.id)
    assert c.ramp == timemap.clean_ramp(timemap.preset_anchors("lento_meio", 0.0, 10.0, False, 1.0, 1.0))
    assert _audio(m).ramp == c.ramp and c.dur > 240
    assert p.btn_clear.isEnabled() and "0,25×" in p.status.text()
    m.undo()
    assert not m.seq.find(v.id).ramp and m.seq.find(v.id).dur == 240 and not p.btn_clear.isEnabled()
    m.redo()
    assert m.seq.find(v.id).ramp
    p.btn_clear.click()
    assert not m.seq.find(v.id).ramp and m.seq.find(v.id).dur == 240
    m.undo()
    assert m.seq.find(v.id).ramp


def test_frozen_clip_has_no_ramp_controls():
    m, v, insp = _inspector()
    m.set_clip_values(v.id, dict(v.values, congelar=True))
    insp.vtempo.refresh()
    p = insp.vtempo
    assert not p.btn_apply.isEnabled() and not p.preset.isEnabled()
    assert "congelados" in p.status.text()
    assert not p.apply()


def test_clip_menu_ramp_presets():
    from PySide6.QtWidgets import QMenu
    from pelicula.ui.timeline_view import TimelineCanvas
    m, v = _model()
    cv = TimelineCanvas(m)
    menu = QMenu()
    tempo_ui.add_clip_actions(menu, cv, v)
    acts = _actions(menu)
    assert {f"ramp_{pid}" for pid in timemap.PRESET_IDS} <= set(acts) and not acts["ramp_off"].isEnabled()
    acts["ramp_impacto"].trigger()
    c = m.seq.find(v.id)
    assert c.ramp == timemap.clean_ramp(timemap.preset_anchors("impacto", 0.0, 10.0))
    menu2 = QMenu()
    tempo_ui.add_clip_actions(menu2, cv, c)
    acts2 = _actions(menu2)
    assert acts2["ramp_off"].isEnabled()
    acts2["ramp_off"].trigger()
    assert not m.seq.find(v.id).ramp


def test_ramp_summary_text():
    m, v = _model()
    m.apply_ramp_preset(v.id, "acelerar", 0.5)
    assert tempo_ui.ramp_summary(m.seq.find(v.id)) == "rampa de 2,50× a 1,00×"


# ------------------------------------------------------------------ reverso
def test_reverse_checkbox_flips_picture_and_sound_in_one_step():
    m, v, insp = _inspector()
    p = insp.vtempo
    assert not p.reverse.isChecked() and p.reverse.isEnabled()
    before = [m.seq.src_frame(v, t) for t in range(0, 240)]
    p.reverse.setChecked(True)
    c = m.seq.find(v.id)
    assert c.reverse and _audio(m).reverse
    assert [m.seq.src_frame(c, t) for t in range(0, 240)] == before[::-1]
    m.undo()
    assert not m.seq.find(v.id).reverse and not _audio(m).reverse and not p.reverse.isChecked()
    m.redo()
    assert m.seq.find(v.id).reverse and p.reverse.isChecked()


def test_reverse_from_the_clip_menu_and_frozen_clips():
    from PySide6.QtWidgets import QMenu
    from pelicula.ui.timeline_view import TimelineCanvas
    m, v = _model()
    cv = TimelineCanvas(m)
    menu = QMenu()
    tempo_ui.add_clip_actions(menu, cv, v)
    act = _actions(menu)["reverse"]
    assert act.isCheckable() and not act.isChecked()
    act.trigger()
    assert m.seq.find(v.id).reverse
    m.set_clip_values(v.id, dict(m.seq.find(v.id).values, congelar=True))
    menu2 = QMenu()
    tempo_ui.add_clip_actions(menu2, cv, m.seq.find(v.id))
    acts = _actions(menu2)
    assert not acts["reverse"].isEnabled() and not menu2.findChild(QMenu, "ramp_menu").isEnabled()


# ------------------------------------------------------------------ congelar este quadro
def test_freeze_from_the_clip_menu_asks_the_duration_and_follows_insert_mode():
    from PySide6.QtWidgets import QInputDialog, QMenu
    from pelicula.ui.timeline_view import TimelineCanvas
    m, v = _model()
    cv = TimelineCanvas(m)
    cv.playhead = 100
    asked = []

    def fake(*args, **kw):
        asked.append(args[3])
        return 1.5, True
    orig = QInputDialog.getDouble
    QInputDialog.getDouble = staticmethod(fake)
    try:
        menu = QMenu()
        tempo_ui.add_clip_actions(menu, cv, v)
        act = _actions(menu)["freeze_here"]
        assert act.isEnabled() and "Shift+F" in act.text()
        cv.set_insert_mode(True)
        act.trigger()
    finally:
        QInputDialog.getDouble = orig
    assert asked == [2.0] and cv.freeze_seconds == 1.5
    hold = m.seq.find(m.selection[0])
    assert hold.frozen and (hold.start, hold.dur) == (100, 36) and m.seq.duration == 276
    m.undo()
    assert m.seq.duration == 240 and len(m.seq.clips) == 2
    cv.set_insert_mode(False)                          # sobrescrever: a duração da montagem não muda
    assert tempo_ui.freeze_at(cv, v.id)
    assert m.seq.duration == 240 and m.seq.find(m.selection[0]).dur == 36
    cv.playhead = 500                                  # fora do clipe: nada a congelar
    menu2 = QMenu()
    tempo_ui.add_clip_actions(menu2, cv, v)
    assert not _actions(menu2)["freeze_here"].isEnabled() and tempo_ui.freeze_at(cv, v.id) is None


# ------------------------------------------------------------------ na janela (precisa de OpenGL)
import pytest  # noqa: E402


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


def test_shift_f_in_the_window_freezes_the_frame_at_the_playhead(win, sample_video):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pelicula import media
    win.set_mode("pelicula")
    win.cur = None
    win.load_media(sample_video)
    assert _pump(lambda: win.cur is not None)
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.set_mode("edicao")
    win.tl_editor.canvas.set_insert_mode(True)
    win.request_frame(6)
    assert _pump(lambda: win.frame_idx == 6 and win.tl_editor.canvas.playhead == 6)
    want = win.model.seq.src_frame(next(c for c in win.model.seq.clips if c.kind == tl.VIDEO), 6)
    QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    hold = win.model.seq.find(win.model.selection[0]) if win.model.selection else None
    assert hold is not None and hold.frozen and hold.start == 6 and hold.dur == 48
    assert win.model.seq.src_frame(hold, 6) == want and win.model.seq.duration == 24 + 48
    win.undo()
    assert win.model.seq.duration == 24
