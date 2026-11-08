"""Casos da interface dos efeitos sonoros (1.8, ARQUITETURA §47): o submenu "Novo ▸ Efeito sonoro", o clipe na faixa de
som livre, o editor no inspetor (um passo do desfazer), o módulo Beta e o botão "Novo" dividido com os geradores.

Rodados por test_sfx_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado sozinho.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, sfx, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402


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
    """Projeto novo no modo Edição com um clipe de cor de 4 s em V1 e uma faixa de som."""
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


def test_the_module_starts_off_and_hides_the_submenu_and_the_editor(win):
    assert not modules.is_enabled(win.settings, "efeitos_sonoros")
    assert not win.sfx.sub_action.isVisible()
    assert not win.sfx.editor.allowed
    set_module(win, "efeitos_sonoros", True)
    assert win.sfx.sub_action.isVisible() and win.sfx.editor.allowed
    names = [a.objectName() for a in win.sfx.submenu.actions()]
    assert names == [f"novo_efeito_{e}" for e in sfx.MENU_ORDER]


def test_new_effect_goes_to_a_free_audio_track_at_the_cursor(win):
    set_module(win, "efeitos_sonoros", True)
    seq = fresh(win)
    win.seek(24)
    pump()
    win.sfx.new_effect("whoosh")
    pump()
    seq = win.model.seq
    (c,) = [c for c in seq.clips if c.kind == tl.AUDIO]
    src = seq.sources[c.src]
    assert src.kind == sfx.KIND and src.data["efeito"] == "whoosh"
    assert c.start == 24 and c.dur == 24 and c.track == 0  # 1 s a 24 qps
    assert win.model.selection == [c.id]
    # um segundo efeito no mesmo ponto vai para a faixa de baixo (sem cobrir o primeiro)
    win.sfx.new_effect("riser")
    pump()
    riser = [x for x in win.model.seq.clips if x.kind == tl.AUDIO and x.id != c.id]
    assert len(riser) == 1 and riser[0].track == 1 and riser[0].dur == 72


def test_the_editor_changes_the_source_in_one_undo_step(win):
    set_module(win, "efeitos_sonoros", True)
    fresh(win)
    win.sfx.new_effect("impacto")
    pump()
    ed = win.sfx.editor
    assert ed.isVisible() and ed.eff is sfx.EFFECTS["impacto"]
    store, card = ed._pages["impacto"]
    assert card.isVisible()
    path = ed.path
    steps = win.model.history._pos
    store.set("grave", 0.2)
    pump(0.6)  # o histórico agrupa em 400 ms
    assert win.model.seq.sources[path].data["grave"] == 0.2
    assert win.model.history._pos == steps + 1
    win.model.undo()
    pump()
    assert win.model.seq.sources[path].data["grave"] == 0.7
    assert store.values["grave"] == 0.7


def test_typewriter_with_title_hits_hides_the_rate(win):
    set_module(win, "efeitos_sonoros", True)
    fresh(win)
    win.sfx.new_effect("maquina")
    pump()
    ed = win.sfx.editor
    rows = {r.param.key: r for r in ed._pages["maquina"][1].rows}
    assert rows["ritmo"].isVisibleTo(ed)
    data = dict(win.model.seq.sources[ed.path].data, toques=[0.1, 0.2])
    win.model.set_source_data(ed.path, data)
    pump()
    assert not rows["ritmo"].isVisibleTo(ed)


def test_new_button_is_shared_with_titles_and_generators(win):
    set_module(win, "efeitos_sonoros", True)
    set_module(win, "titulos_geradores", False)
    try:
        assert win.bin.btn_new.isVisibleTo(win.bin)
        assert all(not a.isVisible() for a in win.sfx.gen_actions)
        assert win.sfx.sub_action.isVisible()
        set_module(win, "efeitos_sonoros", False)
        assert not win.bin.btn_new.isVisibleTo(win.bin)
    finally:
        set_module(win, "titulos_geradores", True)
        set_module(win, "efeitos_sonoros", True)
    assert win.bin.btn_new.isVisibleTo(win.bin)
    assert all(a.isVisible() for a in win.sfx.gen_actions if not a.isSeparator())


# ------------------------------------------------------------------ "Pôr efeitos sonoros…"
def auto_seq(win) -> tl.Sequence:
    """Cor em V1 (0–96), cor com "Surgir do preto" de 0,5 s (96–192) e um marcador "Agora!" no quadro 150."""
    seq = fresh(win).copy()
    b = seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#993311"}), at=96)[0]
    b.dur = 96
    seq.set_values(b.id, {**b.values, "entrada_tipo": "preto", "entrada_dur": 0.5})
    seq.markers.append(tl.Marker("m1", 150, "laranja", "Agora!"))
    win.model.set_sequence(seq)
    pump()
    return win.model.seq


def test_place_is_one_undo_step_on_an_effects_track_and_does_not_repeat(win):
    set_module(win, "efeitos_sonoros", True)
    auto_seq(win)
    win.model.history.reset(win.model.seq)
    steps = win.model.history._pos
    n_audio = len(win.model.seq.kind_tracks(tl.AUDIO))
    made = win.sfx.place()
    pump()
    assert len(made) == 2   # whoosh na transição e riser antes do marcador
    seq = win.model.seq
    assert win.model.history._pos == steps + 1
    assert {seq.kind_tracks(tl.AUDIO)[c.track].name for c in made} == {"Efeitos"}
    assert win.sfx.place() == []   # de novo: nada repete
    assert win.model.history._pos == steps + 1
    win.model.undo()
    pump()
    seq = win.model.seq
    assert not [c for c in seq.clips if c.kind == tl.AUDIO]
    assert len(seq.kind_tracks(tl.AUDIO)) == n_audio


def test_the_dialog_counts_what_it_will_place_and_follows_the_boxes(win):
    from pelicula.ui.sfx_ui import AutoDialog
    set_module(win, "efeitos_sonoros", True)
    seq = auto_seq(win)
    dlg = AutoDialog(seq, win)
    try:
        assert not dlg.boxes["impactos"].isChecked() and dlg.boxes["transicoes"].isChecked()
        assert dlg.ok.isEnabled() and "Whoosh" in dlg.summary.text() and "Riser" in dlg.summary.text()
        dlg.boxes["transicoes"].setChecked(False)
        dlg.boxes["marcadores"].setChecked(False)
        assert not dlg.ok.isEnabled()
        dlg.boxes["marcadores"].setChecked(True)
        o = dlg.options()
        assert o.marcadores and not o.transicoes and o.tecla == "maquina" and o.cor_marcador == ""
    finally:
        dlg.deleteLater()


def test_the_button_sits_after_silences_and_the_shortcut_is_unique(win):
    from PySide6.QtGui import QShortcut
    set_module(win, "efeitos_sonoros", True)
    ed = win.tl_editor
    lay = ed.btn_silences.parentWidget().layout()
    assert lay.indexOf(win.sfx.button) == lay.indexOf(ed.btn_silences) + 1
    assert lay.indexOf(ed.btn_mixer) == lay.indexOf(win.sfx.button) + 1
    assert win.sfx.button.isVisibleTo(ed)
    keys = [s.key().toString() for s in win.findChildren(QShortcut)]
    assert keys.count("Ctrl+Alt+E") == 1
    set_module(win, "efeitos_sonoros", False)
    assert not win.sfx.button.isVisibleTo(ed) and not win.sfx.shortcut.isEnabled()
    set_module(win, "efeitos_sonoros", True)
