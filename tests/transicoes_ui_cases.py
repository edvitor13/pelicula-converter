"""Casos da interface das transições de película (rodados por test_transicoes_ui.py num subprocesso offscreen).

Inspetor (tipos com ícone e dica, só os ajustes do tipo escolhido, tipos novos escondidos com o módulo
desligado), menu "Transição ▸" do corte (um passo só do desfazer, a última duração usada, faixa travada) e o
desenho na linha do tempo. As preferências ficam num .ini só deste arquivo; os casos da janela principal se
pulam sem OpenGL 3.3.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_transicoes_ui_")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import editparams, modules, transitions, timeline as tl  # noqa: E402
from pelicula.timeline import VIDEO  # noqa: E402
from pelicula.ui import transitions_ui  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402
from pelicula.ui.timeline_view import TimelineEditor  # noqa: E402

OLD_IN = ["corte", "dissolver", "preto", "branco"]
OLD_OUT = ["corte", "preto", "branco", "transparente"]


def src(path, frames=96):
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=False)


def model_ab() -> TimelineModel:
    """A [0, 48) e B [48, 96) colados na V1."""
    seq = tl.Sequence(1920, 1080, "24/1")
    a, = seq.insert_media(src("C:/v/a.mp4"), at=0)
    seq.trim_end(a.id, 48)
    b, = seq.insert_media(src("C:/v/b.mp4"), at=48)
    seq.trim_end(b.id, 96)
    m = TimelineModel()
    m.set_sequence(seq)
    return m


def vclips(m):
    return sorted((c for c in m.seq.clips if c.kind == VIDEO), key=lambda c: c.start)


def inspector_on(m, clip) -> ClipInspector:
    ins = ClipInspector(m)
    ins.resize(320, 900)
    m.select([clip.id])
    APP.processEvents()
    return ins


def editor(m, w=1100, h=320, ppf=8.0) -> TimelineEditor:
    ed = TimelineEditor(m)
    ed.resize(w, h)
    ed.show()
    APP.processEvents()
    ed.canvas.set_ppf(ppf)
    ed.canvas.set_scroll(0)
    return ed


def shown_rows(ins) -> set[str]:
    return {k for k, r in ins.transitions.rows.items() if not r.isHidden()}


# ------------------------------------------------------------------ inspetor
def test_inspector_lists_every_type_with_icon_and_tip():
    m = model_ab()
    _a, b = vclips(m)
    ins = inspector_on(m, b)
    for side, old, new in (("entrada", OLD_IN, editparams.EXTRA_IN), ("saida", OLD_OUT, editparams.EXTRA_OUT)):
        combo = ins.transitions.rows[f"{side}_tipo"].combo
        assert [combo.itemData(i) for i in range(combo.count())] == old + list(new)
        assert all(not combo.itemIcon(i).isNull() for i in range(combo.count()))
        for i in range(combo.count()):
            if combo.itemData(i) in new:
                assert combo.itemData(i, 3), combo.itemData(i)  # Qt.ToolTipRole
        assert ins.transitions.visible_choices(side) == old + list(new)


def test_inspector_shows_only_the_settings_of_the_chosen_type():
    m = model_ab()
    _a, b = vclips(m)
    ins = inspector_on(m, b)
    base = {"entrada_tipo", "entrada_dur", "saida_tipo", "saida_dur"}
    assert shown_rows(ins) == base
    for kind in editparams.EXTRA_IN:
        ins.vstore.set("entrada_tipo", kind)
        APP.processEvents()
        want = base | set(transitions.params_for("entrada", kind))
        if kind == "emenda":
            want -= {"entrada_dur"}  # a emenda conta quadros
        assert shown_rows(ins) == want, kind
        assert m.seq.find(b.id).values["entrada_tipo"] == kind  # foi para o clipe
    ins.vstore.set("entrada_tipo", "corte")
    for kind in editparams.EXTRA_OUT:
        ins.vstore.set("saida_tipo", kind)
        assert shown_rows(ins) == base | set(transitions.params_for("saida", kind)), kind
    ins.vstore.set("saida_tipo", "preto")
    assert shown_rows(ins) == base


def test_inspector_module_off_hides_the_new_types_but_keeps_the_current():
    m = model_ab()
    _a, b = vclips(m)
    ins = inspector_on(m, b)
    ins.transitions.set_enabled(False)
    assert ins.transitions.visible_choices("entrada") == OLD_IN
    assert ins.transitions.visible_choices("saida") == OLD_OUT
    m.set_transition(b.id, "entrada", "queima")
    APP.processEvents()
    assert ins.transitions.visible_choices("entrada") == OLD_IN + ["queima"]  # o do clipe continua lá
    assert ins.vstore.get("entrada_tipo") == "queima"
    combo = ins.transitions.rows["entrada_tipo"].combo
    assert combo.currentData() == "queima"
    ins.transitions.set_enabled(True)
    assert ins.transitions.visible_choices("entrada") == OLD_IN + list(editparams.EXTRA_IN)


def test_inspector_duration_becomes_the_last_used():
    m = model_ab()
    _a, b = vclips(m)
    ins = inspector_on(m, b)
    ins.vstore.set("entrada_tipo", "iris")
    ins.vstore.set("entrada_dur", 0.5)
    assert m.last_transition_s == 0.5


# ------------------------------------------------------------------ menu do corte
def _actions(sub: QMenu) -> dict:
    return {a.data()[2]: a for a in sub.actions() if a.data()}


def test_cut_menu_targets_the_nearest_cut():
    m = model_ab()
    a, b = vclips(m)
    ed = editor(m)
    c = ed.canvas
    ra, rb = c.clip_rect(a), c.clip_rect(b)
    assert transitions_ui.cut_near(c, a, ra.right() - 4) == (b, "entrada")  # direita de A: entrada de B
    assert transitions_ui.cut_near(c, b, rb.left() + 4) == (b, "entrada")
    assert transitions_ui.cut_near(c, b, rb.right() - 4) == (b, "saida")   # sem clipe depois: saída de B
    assert transitions_ui.cut_near(c, a, ra.left() + 4) == (a, "entrada")
    menu1 = QMenu()
    sub = transitions_ui.add_menu(c, menu1, b, rb.right() - 4)
    assert list(_actions(sub)) == OLD_OUT + list(editparams.EXTRA_OUT)
    menu2 = QMenu()
    sub = transitions_ui.add_menu(c, menu2, a, ra.right() - 4)
    acts = _actions(sub)
    assert list(acts) == OLD_IN + list(editparams.EXTRA_IN)
    assert acts["corte"].isChecked() and not acts["queima"].isChecked()
    assert all(not a.icon().isNull() for a in acts.values())


def test_cut_menu_sets_type_and_duration_in_one_undo_step():
    m = model_ab()
    a, b = vclips(m)
    ed = editor(m)
    c = ed.canvas
    before = m.seq.to_json()
    menu3 = QMenu()
    sub = transitions_ui.add_menu(c, menu3, a, c.clip_rect(a).right() - 4)
    _actions(sub)["queima"].trigger()
    got = m.seq.find(b.id).values
    assert (got["entrada_tipo"], got["entrada_dur"]) == ("queima", 1.0)
    assert m.can_undo()
    m.undo()
    assert m.seq.to_json() == before  # um passo só
    m.redo()
    assert m.seq.find(b.id).values["entrada_tipo"] == "queima"
    # a duração que o lado já tinha fica; um corte novo usa a última
    m.set_transition(b.id, "entrada", "iris", 0.5)
    assert m.seq.find(b.id).values["entrada_dur"] == 0.5
    m.set_transition(b.id, "entrada", "cortina")
    assert m.seq.find(b.id).values["entrada_dur"] == 0.5
    m.set_transition(a.id, "saida", "exposicao")
    assert m.seq.find(a.id).values["saida_dur"] == 0.5
    m.set_transition(a.id, "saida", "corte")
    assert m.seq.find(a.id).values["saida_tipo"] == "corte"
    assert not m.set_transition(a.id, "saida", "fusao")  # a fusão é só de entrada
    assert not m.set_transition(a.id, "entrada", "nada")


def test_cut_menu_respects_locked_tracks_and_the_module():
    m = model_ab()
    a, _b = vclips(m)
    ed = editor(m)
    c = ed.canvas
    m.set_track(VIDEO, 0, locked=True)
    menu4 = QMenu()
    sub = transitions_ui.add_menu(c, menu4, a, c.clip_rect(a).right() - 4)
    assert not sub.isEnabled()
    assert not m.set_transition(a.id, "saida", "iris")
    m.set_track(VIDEO, 0, locked=False)
    c.film_transitions = False
    menu = QMenu()
    assert transitions_ui.add_menu(c, menu, a, 10) is None and menu.isEmpty()


# ------------------------------------------------------------------ linha do tempo
def test_timeline_draws_the_new_transitions_over_the_cut():
    m = model_ab()
    a, b = vclips(m)
    ed = editor(m)
    c = ed.canvas
    plain = c.grab().toImage()
    m.set_transition(b.id, "entrada", "queima", 0.5)
    APP.processEvents()
    drawn = c.grab().toImage()
    rb = c.clip_rect(b)
    x = int(rb.left() + 6 * c.ppf)  # dentro dos 12 quadros da transição
    y = int(rb.center().y())
    assert plain.pixelColor(x, y) != drawn.pixelColor(x, y)
    far = int(rb.left() + 30 * c.ppf)  # depois dela, nada muda
    assert plain.pixelColor(far, y) == drawn.pixelColor(far, y)
    m.set_transition(a.id, "saida", "iris", 0.5)
    APP.processEvents()
    c.grab()  # a saída também desenha (sem erro)


# ------------------------------------------------------------------ janela principal
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


def _set_module(win, on):
    modules.set_enabled(win.settings, "transicoes", on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def test_window_module_switch_hides_types_and_menu(win):
    _set_module(win, True)
    assert win.inspector.transitions.enabled and win.tl_editor.canvas.film_transitions
    _set_module(win, False)
    assert not win.inspector.transitions.enabled and not win.tl_editor.canvas.film_transitions
    assert win.inspector.transitions.visible_choices("entrada") == OLD_IN
    _set_module(win, True)
    assert win.inspector.transitions.visible_choices("entrada") == OLD_IN + list(editparams.EXTRA_IN)


def test_window_warns_about_a_project_that_uses_the_module_off(win):
    _set_module(win, True)
    win.model.set_sequence(model_ab().seq)  # arquivos que não existem: a prévia fica vazia
    _a, b = vclips(win.model)
    win.model.set_transition(b.id, "entrada", "fusao")
    assert "transicoes" in modules.used_by(None, win.model.seq)
    values_before = dict(win.store.values)
    _set_module(win, False)
    assert "transicoes" in win.module_notice.ids and not win.module_notice.isHidden()
    assert win.model.seq.find(b.id).values["entrada_tipo"] == "fusao"  # o projeto não muda
    assert dict(win.store.values) == values_before
    _set_module(win, True)
