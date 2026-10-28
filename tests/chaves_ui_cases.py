"""Casos da interface das chaves de animação (losangos no inspetor, no look e na linha do tempo).

Rodados por test_chaves_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Nada aqui precisa de OpenGL.
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
