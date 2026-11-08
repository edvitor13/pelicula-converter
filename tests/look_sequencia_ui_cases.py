"""Casos da interface do look próprio de cada sequência (1.8, #67): a troca do look em edição junto com a aba, a
escolha (painel, aba e Mídia), o desfazer de cada look, salvar e reabrir, "alterações não salvas", a exportação de outra
sequência e o aviso no clipe de uma sequência com look próprio.

Rodados por test_look_sequencia_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import presets, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402
from pelicula.ui.sequence_dialog import SequenceDialog  # noqa: E402
from pelicula.ui.sequence_tabs import SequenceTabs, TabInfo  # noqa: E402

OTHER = "lab_technicolor3"


def pump(timeout: float = 0.15) -> None:
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
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w
    w._saved_state = w._state()
    w.close()


def color_seq(color="#336699") -> tl.Sequence:
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": color}))
    return seq


def two_tabs(win, monkeypatch) -> list[str]:
    """Projeto novo com duas sequências (a segunda aberta, com um clipe de cor) e o look do projeto num preset
    conhecido."""
    win.new_project()
    win.set_mode("edicao")
    win._loading = True
    win.model.set_sequence(color_seq())
    win._loading = False
    win.seqs_ui.reset()
    win.seq_look.reset()
    win.apply_preset("vision3_500t")
    monkeypatch.setattr(SequenceDialog, "exec", lambda self: 1)
    win.seqs_ui.new_sequence()
    win.model.seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#aa3300"}))
    win.model.commit()
    pump()
    win._saved_state = win._state()
    return [s.id for s in win.model.sequences()]


def open_tab(win, sid: str) -> None:
    win.seqs_ui.activate(sid)
    pump()


# ------------------------------------------------------------------ escolha e troca
def test_a_new_own_look_starts_as_the_projects_and_the_image_does_not_change(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    before = dict(win.store.values)
    assert not win.seq_look.row.isHidden() and win.seq_look.combo.currentData() == "projeto"
    assert win.seq_look.set_own()
    seq = win.model.seq
    assert seq.look is not None and seq.look.preset_id == "vision3_500t" and seq.look.values == before
    assert win.store.values == before and win.preset_id == "vision3_500t"
    assert win.seq_look.combo.currentData() == "proprio" and win.seq_look.owner == ids[1]
    assert win.is_dirty()  # o projeto mudou (o bloco da sequência ganhou o look)


def test_switching_tabs_swaps_the_look_being_edited(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    win.seq_look.set_own()
    win.apply_preset(OTHER)
    win.store.set("exposicao", 0.7)
    win.store.commit()
    own = win.model.seq.look
    assert own.preset_id == OTHER and own.values["exposicao"] == 0.7  # escrito na hora
    values, _keys, pid = win.seq_look.project_look()
    assert pid == "vision3_500t" and values["exposicao"] != 0.7
    open_tab(win, ids[0])
    assert win.seq_look.owner is None and win.preset_id == "vision3_500t"
    assert win.store.values == values and win.preset_combo.currentData() == "vision3_500t"
    assert win.seq_look.combo.currentData() == "projeto"
    win.store.set("exposicao", -0.3)                    # mexe no look do projeto: a outra não muda
    win.store.commit()
    assert win.model.sequences()[1].look.values["exposicao"] == 0.7
    open_tab(win, ids[1])
    assert win.preset_id == OTHER and win.store.values["exposicao"] == 0.7
    assert win.seq_look.project_look()[0]["exposicao"] == -0.3


def test_each_look_keeps_its_own_undo_and_the_timeline_undo_keeps_the_look(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    win.seq_look.set_own()
    win.store.set("exposicao", 0.4)
    win.store.commit()
    win.model.seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#00ff00"}), 24)
    win.model.commit()
    win.model.undo()                                    # desfaz a montagem, não o look
    pump()
    assert win.model.seq.look.values["exposicao"] == 0.4 and win.store.values["exposicao"] == 0.4
    open_tab(win, ids[0])
    win.store.set("exposicao", -0.2)
    win.store.commit()
    open_tab(win, ids[1])
    assert win.store.can_undo()
    win.store.undo()                                    # o desfazer do look próprio
    assert win.store.values["exposicao"] != 0.4 and win.model.seq.look.values["exposicao"] != 0.4
    open_tab(win, ids[0])
    assert win.store.values["exposicao"] == -0.2        # o do projeto ficou como estava
    win.store.undo()
    assert win.store.values["exposicao"] != -0.2


def test_back_to_the_project_look_asks_only_when_it_changed(win, monkeypatch):
    two_tabs(win, monkeypatch)
    asked = []
    monkeypatch.setattr(win.seq_look, "confirm_discard", lambda seq: asked.append(seq) or False)
    win.seq_look.set_own()
    assert win.seq_look.set_shared() and asked == [] and win.model.seq.look is None  # igual: não pergunta
    win.seq_look.set_own()
    win.store.set("exposicao", 0.5)
    win.store.commit()
    assert not win.seq_look.set_shared() and len(asked) == 1 and win.model.seq.look is not None
    assert win.seq_look.combo.currentData() == "proprio"
    monkeypatch.setattr(win.seq_look, "confirm_discard", lambda seq: True)
    assert win.seq_look.set_shared() and win.model.seq.look is None and win.seq_look.owner is None
    assert win.store.values["exposicao"] != 0.5 and win.preset_id == "vision3_500t"


def test_the_panel_row_only_shows_with_more_than_one_sequence(win, monkeypatch):
    win.new_project()
    win.set_mode("edicao")
    assert win.seq_look.row.isHidden()
    two_tabs(win, monkeypatch)
    assert not win.seq_look.row.isHidden() and "Sequência 2" in win.seq_look.label.toolTip()
    win.seq_look.combo.setCurrentIndex(1)
    win.seq_look.combo.activated.emit(1)
    assert win.model.seq.look is not None


def test_tab_and_media_menus_choose_the_look(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    tabs = win.seqs_ui.tabs
    assert [t.own_look for t in tabs.tabs] == [False, False]
    menu = tabs.menu_for(ids[0])
    sub = next(a.menu() for a in menu.actions() if a.text() == "Look de película")
    acts = {a.text(): a for a in sub.actions()}
    assert acts["Igual ao do projeto"].isChecked() and not acts["Próprio desta sequência"].isChecked()
    acts["Próprio desta sequência"].trigger()
    assert win.model.sequences()[0].look is not None and win.model.seq.id == ids[1]  # a aberta não muda
    assert win.seq_look.owner is None                                                  # nem o look em edição
    assert [t.own_look for t in tabs.tabs] == [True, False] and "Look de película próprio" in tabs.tabs[0].tip
    win.bin.list.clearSelection()
    win.bin.list.media(f"sequencia:{ids[0]}").setSelected(True)
    m = QMenu()
    win.bin.fill_media_menu(m)
    sub = next(a.menu() for a in m.actions() if a.text() == "Look de película")
    acts = {a.text(): a for a in sub.actions()}
    assert acts["Próprio desta sequência"].isChecked()
    acts["Igual ao do projeto"].trigger()
    assert win.model.sequences()[0].look is None and [t.own_look for t in tabs.tabs] == [False, False]


def test_the_tab_with_its_own_look_paints_a_dot():
    t = SequenceTabs()
    t.resize(600, 36)
    t.set_tabs([TabInfo("a", "Sequência 1"), TabInfo("b", "Sequência 2", "", True)], "a")
    t.show()
    APP.processEvents()
    img = t.grab().toImage()
    r = t.tab_rect(1)
    c = img.pixelColor(int(r.right() - 11), int(r.center().y()))
    assert c.red() > c.blue() + 40  # o ponto na cor de destaque
    t.close()


# ------------------------------------------------------------------ projeto
def test_save_and_reopen_keeps_each_look(win, monkeypatch, tmp_path):
    ids = two_tabs(win, monkeypatch)
    win.seq_look.set_own()
    win.apply_preset(OTHER)
    open_tab(win, ids[0])                               # salva com a de cima aberta (o look do projeto em edição)
    path = str(tmp_path / "looks.plc")
    assert win._write_project(path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["formato"] == 6 and "look_proprio" in data["recursos"] and data["preset"] == "vision3_500t"
    assert data["valores"] == win.seq_look.project_look()[0]
    own = data["edicao"]["sequencias"][0]["look"]
    assert own["preset"] == OTHER and own["valores"] == win.model.sequences()[1].look.values
    open_tab(win, ids[1])                               # trocar de aba não suja o projeto
    assert not win.is_dirty()
    assert win._write_project(path)                     # agora com a de look próprio aberta
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["preset"] == "vision3_500t" and data["edicao"]["look"]["preset"] == OTHER
    win.new_project()
    win.open_project(path)
    pump()
    assert win.model.seq.id == ids[1] and win.preset_id == OTHER and win.seq_look.owner == ids[1]
    assert win.seq_look.project_look()[2] == "vision3_500t" and not win.is_dirty()
    open_tab(win, ids[0])
    assert win.preset_id == "vision3_500t" and win.seq_look.owner is None


def test_a_lone_sequence_with_its_own_look_is_saved_with_it(win, monkeypatch, tmp_path):
    ids = two_tabs(win, monkeypatch)
    win.seq_look.set_own()
    win.apply_preset(OTHER)
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda seq, users: True)
    open_tab(win, ids[0])
    win.seqs_ui.delete(ids[0])                          # sobra a de look próprio, sozinha
    pump()
    assert len(win.model.sequences()) == 1 and win.model.seq.look is not None and win.preset_id == OTHER
    path = str(tmp_path / "sozinha.plc")
    assert win._write_project(path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["edicao"]["look"]["preset"] == OTHER and data["preset"] == "vision3_500t"


# ------------------------------------------------------------------ exportação e clipe
def test_export_targets_and_the_dialog_use_each_sequences_look(win, monkeypatch):
    from pelicula.ui import export_dialog as ed
    ids = two_tabs(win, monkeypatch)
    monkeypatch.setattr(win, "edit_film", True)        # o modo Edição com a película ligada
    win.seq_look.set_own()
    win.apply_preset(OTHER)
    open_tab(win, ids[0])
    targets = {t.id: t for t in win.seqs_ui.export_targets()}
    assert targets[ids[1]].look[2] == win.preset_name(OTHER) and targets[ids[1]].look[0]["lab_on"] == \
        presets.builtin_values(OTHER)["lab_on"]
    assert targets[ids[0]].look[2] == win.preset_name("vision3_500t")
    shown = []
    monkeypatch.setattr(ed.ExportDialog, "exec", lambda self: shown.append(self) or 0)
    win.new_export()
    d = shown[0]
    assert d.preset_name == win.preset_name("vision3_500t")
    d.seq_box.setCurrentIndex(d.seq_box.findData(ids[1]))
    assert d.preset_name == win.preset_name(OTHER) and d.values == targets[ids[1]].look[0]
    assert win.preset_name(OTHER) in d.sub_label.text()
    d.seq_box.setCurrentIndex(d.seq_box.findData(ids[0]))
    assert d.preset_name == win.preset_name("vision3_500t")
    d.multi_box.setChecked(True)
    for i in range(d.multi_list.count()):
        d.multi_list.item(i).setCheckState(Qt.CheckState.Checked)
    jobs = {j.sequence.id: j for j in d.jobs()}
    assert jobs[ids[1]].values == targets[ids[1]].look[0] and win.preset_name(OTHER) in jobs[ids[1]].name
    d.done(0)
    win.edit_film = False                               # modo Edição sem película: só a montagem, para todas
    assert all(t.look[2] == "Sem película (só a edição)" for t in win.seqs_ui.export_targets())


def test_a_clip_of_a_sequence_with_its_own_look_warns_that_it_enters_without_it(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    win.seq_look.set_own()
    open_tab(win, ids[0])
    src = win.model.seq.sources[f"sequencia:{ids[1]}"]
    seen = []
    monkeypatch.setattr(win.statusBar(), "showMessage", lambda text, ms=0: seen.append(text))
    clips = win._insert(src, 48)
    assert clips and any("entra sem look" in t for t in seen)
    win.model.selection = [next(c.id for c in win.model.seq.clips if c.src == src.path)]
    win.model.selectionChanged.emit()
    pump()
    assert "entra sem look" in win.inspector.info.text()
    assert win.seq_look.owner is None and win.preset_id == "vision3_500t"  # a de fora segue o projeto


def test_the_look_choice_box_fits_its_longest_item(win, monkeypatch):
    """"Próprio desta sequência" cabia em 14 letras e saía cortado ("Próprio desta sequênci"): a caixa agora tem a
    largura mínima do item mais longo; quem se encurta é o rótulo "Look de …" (o nome inteiro fica na dica)."""
    two_tabs(win, monkeypatch)
    ui = win.seq_look
    ui.refresh()
    combo = ui.combo
    longest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
    assert combo.minimumContentsLength() >= len("Próprio desta sequência")
    assert combo.minimumSizeHint().width() > longest
