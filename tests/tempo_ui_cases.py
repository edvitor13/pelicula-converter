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
