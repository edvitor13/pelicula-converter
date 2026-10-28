"""Casos da interface das legendas (1.5): controle, faixa "Legendas" da linha do tempo, painel e janela.

Rodados por test_legendas_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt
precisam de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. As preferências ficam
num .ini só deste arquivo.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_legendas_ui_")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import modules, subedit as se, subtitles as sb, timeline as tl  # noqa: E402
from pelicula.subtitles import Cue, Word  # noqa: E402
from pelicula.timeline import AUDIO, VIDEO  # noqa: E402
from pelicula.ui import prefs  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.subtitle_lane import SubtitleLane  # noqa: E402
from pelicula.ui.subtitles_panel import SubtitlesPanel  # noqa: E402
from pelicula.ui.subtitles_ui import SubtitleController, anchor_choices, default_anchor  # noqa: E402
from pelicula.ui.timeline_view import HEADER_W, TimelineEditor  # noqa: E402

LMB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
PATH = "C:/v/fala.mp4"


def src(path=PATH, frames=480, audio=True) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=audio)


def model_with(*cues, seq_cues=()) -> TimelineModel:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(src())
    if cues or seq_cues:
        seq.subtitles = sb.Subtitles(sources={PATH: list(cues)} if cues else {}, cues=list(seq_cues))
    m.set_sequence(seq)
    return m


def sentence(a: float, text: str, step: float = 0.5) -> Cue:
    toks = text.split()
    return Cue(a, a + len(toks) * step, text, tuple(Word(a + i * step, a + (i + 1) * step, t)
                                                   for i, t in enumerate(toks)))


def texts(ctl):
    return [it.cue.text for it in ctl.items()]


def pt(x, y) -> QPoint:
    return QPoint(int(round(x)), int(round(y)))


def lane_editor(m, ppf=4.0):
    ed = TimelineEditor(m)
    ed.resize(1100, 360)
    ctl = SubtitleController(m)
    lane = SubtitleLane(ed.canvas, ctl)
    ed.show()
    APP.processEvents()
    ed.canvas.set_ppf(ppf)
    ed.canvas.set_scroll(0)
    return ed, ctl, lane


def x_of(c, seconds):
    return c.frame_to_x(seconds * 24)


def lane_y(lane):
    return lane.rect().center().y()


def drag(widget, a: QPoint, b: QPoint, mods=NOMOD) -> None:
    QTest.mousePress(widget, LMB, mods, a)
    QTest.mouseMove(widget, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(widget, b)
    QTest.mouseRelease(widget, LMB, mods, b)


# ------------------------------------------------------------------ modelo e controle
def test_model_edit_subtitles_is_one_undo_step_and_emits_subtitles():
    m = model_with()
    kinds = []
    m.changed.connect(kinds.append)
    assert not m.edit_subtitles(lambda s: None)            # nada mudou: sem passo de desfazer
    assert not m.can_undo()
    assert m.edit_subtitles(lambda s: s.cues.append(Cue(1, 2, "oi")))
    assert kinds == ["subtitles"] and m.can_undo()
    m.undo()
    assert m.seq.subtitles is None and kinds[-1] == "subtitles"
    m.redo()
    assert [c.text for c in m.seq.subtitles.cues] == ["oi"]
    assert not m.edit_subtitles(lambda s: False)           # desistiu


def test_controller_add_at_playhead_anchors_to_the_file_and_selects_it():
    m = model_with()
    ctl = SubtitleController(m)
    ctl.clock = lambda: 48
    assert ctl.add_at(text="no arquivo")
    assert list(m.seq.subtitles.sources) == [PATH] and m.seq.subtitles.cues == []
    it = ctl.current()
    assert it is not None and it.cue.text == "no arquivo" and it.cue.start == 2.0 and not it.fixed
    assert it.cue.end == 2.0 + se.NEW_DUR
    m.seq.clips.clear()                                    # sem clipe no cursor: tempo da sequência
    m.changed.emit("*")
    assert ctl.add_at(text="na sequência") and ctl.current().fixed


def test_controller_edits_keep_the_selection_and_undo():
    m = model_with(sentence(1.0, "um dois três quatro"), Cue(5, 6, "seguinte"))
    ctl = SubtitleController(m)
    first = ctl.items()[0]
    ctl.select([first.ref])
    assert ctl.set_text(first, "Um dois três quatro")
    assert ctl.current().cue.text == "Um dois três quatro" and len(ctl.current().cue.words) == 4
    ctl.clock = lambda: 48                                 # 2 s: no meio da primeira
    assert ctl.split()
    assert texts(ctl) == ["Um dois", "três quatro", "seguinte"] and ctl.current().cue.text == "três quatro"
    assert ctl.merge_next(ctl.items()[0])
    assert texts(ctl) == ["Um dois três quatro", "seguinte"]
    assert ctl.set_flags(ctl.items()[1], italic=True) and ctl.source_cue(ctl.items()[1]).italic
    assert ctl.replace_all("seguinte", "próxima") == 1 and texts(ctl)[-1] == "próxima"
    ctl.select([ctl.items()[1].ref])
    assert ctl.delete_selected() == 1 and texts(ctl) == ["Um dois três quatro"] and ctl.selection == []
    for _ in range(6):
        m.undo()
    assert texts(ctl) == ["um dois três quatro", "seguinte"]


def test_controller_items_follow_cuts():
    m = model_with(Cue(2, 3, "antes"), Cue(6, 7, "depois"))
    ctl = SubtitleController(m)
    m.split_at(24 * 5)
    right = sorted((c for c in m.seq.clips if c.kind == AUDIO), key=lambda c: c.start)[1]
    m.move_clip(right.id, 24 * 8)
    assert [(it.cue.text, it.cue.start) for it in ctl.items()] == [("antes", 2.0), ("depois", 9.0)]


def test_import_anchor_choices():
    m = model_with()
    choices = anchor_choices(m.seq)
    assert [k for k, _l in choices] == [None, PATH]
    assert default_anchor(m.seq) == PATH                   # arquivo inteiro sem mudanças: o .srt é dele
    m.split_at(24 * 5)
    assert default_anchor(m.seq) is None


# ------------------------------------------------------------------ faixa "Legendas"
def test_lane_adds_height_only_when_visible_and_keeps_rows():
    m = model_with(Cue(2, 3, "oi"))
    ed, ctl, lane = lane_editor(m)
    c = ed.canvas
    rows = c.rows()
    lane.set_visible(False)
    h0 = c.content_height()
    lane.set_visible(True)
    assert c.content_height() > h0 and c.rows() == rows
    r = lane.rect()
    _k, _i, y, h = rows[-1]
    assert r.top() >= y + h and r.left() == HEADER_W
    img = c.grab()                                          # desenha sem erro
    assert not img.isNull()
    c.lane = None
    assert c.content_height() == h0                         # sem faixa: a linha do tempo de sempre


def test_lane_click_selects_and_seeks_drag_moves_and_trims():
    m = model_with(Cue(2, 3, "oi"), Cue(6, 7, "tchau"))
    ed, ctl, lane = lane_editor(m)
    c = ed.canvas
    seeks = []
    ctl.seekRequested.connect(seeks.append)
    y = lane_y(lane)
    QTest.mouseClick(c, LMB, NOMOD, pt(x_of(c, 2.5), y))
    assert ctl.current().cue.text == "oi" and seeks == [48]
    assert lane.hit(pt(x_of(c, 2.5), y))[1] == "body"
    drag(c, pt(x_of(c, 2.5), y), pt(x_of(c, 3.5), y), SHIFT)   # Shift: sem ímã
    it = ctl.items()[0]
    assert it.cue.text == "oi" and it.cue.start == pytest.approx(3.0, abs=0.02)
    assert ctl.current().cue.text == "oi"
    m.undo()
    assert ctl.items()[0].cue.start == 2.0
    drag(c, pt(x_of(c, 3.0) - 1, y), pt(x_of(c, 4.0), y), SHIFT)  # ponta direita
    it = ctl.items()[0]
    assert it.cue.start == 2.0 and it.cue.end == pytest.approx(4.0, abs=0.02)
    QTest.mouseClick(c, LMB, NOMOD, pt(x_of(c, 10), y))    # lugar vazio: tira a escolha
    assert ctl.selection == []


def test_lane_double_click_creates_and_delete_key_removes():
    m = model_with(Cue(2, 3, "oi"))
    ed, ctl, lane = lane_editor(m)
    c = ed.canvas
    asked = []
    ctl.textRequested.connect(lambda: asked.append(1))
    y = lane_y(lane)
    QTest.mouseDClick(c, LMB, NOMOD, pt(x_of(c, 8), y))
    assert len(ctl.items()) == 2 and asked and ctl.current().cue.start == pytest.approx(8.0, abs=0.02)
    QTest.mouseClick(c, LMB, NOMOD, pt(x_of(c, 2.5), y))
    QTest.keyClick(c, Qt.Key.Key_Delete)
    assert texts(ctl) == [ctl.items()[0].cue.text] and len(ctl.items()) == 1
    assert len(m.seq.clips) == 2                            # Delete na faixa não apaga clipe
    vy = next(yy + hh / 2 for k, i, yy, hh in c.rows() if (k, i) == (VIDEO, 0))
    QTest.mouseClick(c, LMB, NOMOD, pt(x_of(c, 1), vy))      # clicou num clipe: a faixa sai de cena
    assert not lane.active


def test_lane_snaps_to_the_playhead():
    m = model_with(Cue(2, 3, "oi"))
    ed, ctl, lane = lane_editor(m)
    c = ed.canvas
    c.set_playhead(24 * 4)
    y = lane_y(lane)
    drag(c, pt(x_of(c, 2.5), y), pt(x_of(c, 3.45), y))    # o fim chega perto de 4 s (o cursor) e gruda
    assert ctl.items()[0].cue.end == pytest.approx(4.0, abs=1e-6)
    assert ctl.items()[0].cue.start == pytest.approx(3.0, abs=1e-6)


# ------------------------------------------------------------------ painel
def panel_for(m):
    ctl = SubtitleController(m)
    p = SubtitlesPanel(ctl)
    p.resize(420, 640)
    p.show()
    APP.processEvents()
    return ctl, p


def test_panel_lists_and_selects_both_ways():
    m = model_with(sentence(1.0, "olá mundo"), Cue(5, 6, "outra"), seq_cues=[Cue(8, 9, "fixa")])
    ctl, p = panel_for(m)
    assert p.table.rowCount() == 3
    assert p.table.item(0, 2).text() == "olá mundo" and p.table.item(0, 0).text().startswith("00:00:01")
    seeks = []
    ctl.seekRequested.connect(seeks.append)
    p.table.selectRow(1)
    assert ctl.current().cue.text == "outra" and seeks == [120]
    ctl.select([ctl.items()[0].ref])
    assert [i.row() for i in p.table.selectionModel().selectedRows()] == [0]
    assert p.text.toPlainText() == "olá mundo" and p.words.isVisibleTo(p) and "mundo" in p.words.text()
    ctl.select([ctl.items()[2].ref])
    assert "fixo" in p.where.text() and not p.words.isVisibleTo(p)


def test_panel_edits_text_times_and_flags():
    m = model_with(sentence(1.0, "olá mundo"), Cue(5, 6, "outra"))
    ctl, p = panel_for(m)
    ctl.select([ctl.items()[1].ref])
    p.text.setFocus()
    p.text.setPlainText("outra fala")
    p.text.committed.emit()
    assert texts(ctl)[1] == "outra fala" and ctl.current().cue.text == "outra fala"
    p.end.setValue(7.5)
    p.end.editingFinished.emit()
    assert ctl.current().cue.end == pytest.approx(7.5)
    p.btn_bold.setChecked(True)
    assert ctl.source_cue(ctl.current()).bold
    p.btn_undo.click()
    assert not ctl.source_cue(ctl.items()[1]).bold
    p.btn_redo.click()
    assert ctl.source_cue(ctl.items()[1]).bold


def test_panel_search_replace_add_delete():
    m = model_with(sentence(1.0, "olá mundo"), Cue(5, 6, "outra coisa"))
    ctl, p = panel_for(m)
    p.find.setText("MUNDO")
    assert not p.table.isRowHidden(0) and p.table.isRowHidden(1) and p.find_info.isVisibleTo(p)
    p.repl.setText("planeta")
    p.btn_repl.click()
    assert texts(ctl) == ["olá planeta", "outra coisa"]
    p.find.setText("")
    ctl.clock = lambda: 24 * 10
    p.btn_add.click()
    assert len(ctl.items()) == 3 and ctl.current().cue.start == 10.0
    p.btn_delete.click()
    assert len(ctl.items()) == 2
    p.burn.setCurrentIndex(p.burn.findData("digital"))
    assert m.seq.subtitles.burn == "digital"


def test_panel_follows_undo_of_the_model():
    m = model_with(Cue(5, 6, "outra"))
    ctl, p = panel_for(m)
    ctl.clock = lambda: 0
    ctl.add_at(text="nova")
    assert p.table.rowCount() == 2
    m.undo()
    assert p.table.rowCount() == 1 and ctl.selection == []


# ------------------------------------------------------------------ estilos
def test_style_presets_and_edits_are_undo_steps():
    m = model_with(Cue(1, 2, "oi"))
    ctl, p = panel_for(m)
    ed = p.style_tab
    assert ed.preset.currentData() == "youtube" and not ed.btn_reset.isEnabled()
    ed.preset.setCurrentIndex(ed.preset.findData("reels"))
    ed.preset.activated.emit(ed.preset.currentIndex())
    assert m.seq.subtitles.style == sb.STYLES["reels"]
    ed.size.setValue(80)
    st = m.seq.subtitles.style
    assert st.id == "reels" and st.text.size == 80.0 and ed.btn_reset.isEnabled()
    ed.color.picked.emit(QColor("#ff0000"))
    assert m.seq.subtitles.style.text.color == (1.0, 0.0, 0.0)
    ed.position.setCurrentIndex(ed.position.findData("cima"))
    ed.position.activated.emit(ed.position.currentIndex())
    ed.margin.setValue(90)
    assert m.seq.subtitles.style.position == "cima" and m.seq.subtitles.style.margin == 90.0
    ed.btn_reset.click()
    assert m.seq.subtitles.style == sb.STYLES["reels"] and ed.size.value() == 62
    m.undo()
    assert m.seq.subtitles.style.margin == 90.0 and ed.margin.value() == 90


def test_style_family_weight_box_and_highlight_round_trip():
    m = model_with(Cue(1, 2, "oi"))
    ctl, p = panel_for(m)
    ed = p.style_tab
    ed.family.setCurrentIndex(ed.family.findData("courier_prime"))
    ed.family.activated.emit(ed.family.currentIndex())
    ed.weight.setCurrentIndex(1)
    ed.weight.activated.emit(1)
    ed.box.setValue(0)
    ed.outline.setValue(4)
    ed.upper.setChecked(True)
    t = m.seq.subtitles.style.text
    assert (t.family, t.weight, t.box, t.outline, t.uppercase) == ("courier_prime", 700, 0.0, 4.0, True)
    ctl.set_options(style=sb.STYLES["reels"])
    assert ed.highlight.isChecked()
    ed.highlight.setChecked(False)                         # desligar o destaque do estilo pronto fica gravado
    assert m.seq.subtitles.style.highlight is None
    again = tl.Sequence.from_json(m.seq.to_json()).subtitles
    assert again.style.highlight is None and again.style == m.seq.subtitles.style
    ed.highlight.setChecked(True)
    ed.highlight_color.picked.emit(QColor("#00ff00"))
    assert m.seq.subtitles.style.highlight.color == (0.0, 1.0, 0.0)


def test_missing_characters_warning():
    m = model_with(Cue(1, 2, "日本語"))
    ctl, p = panel_for(m)
    assert p.warn.isVisibleTo(p) and "日" in p.warn.text()
    assert ctl.set_text(ctl.items()[0], "tudo certo: ação, ñ, ü")
    assert not p.warn.isVisibleTo(p)


# ------------------------------------------------------------------ janela de exportação
def export_info(seconds=10.0):
    from pelicula import media
    return media.MediaInfo(path=os.path.join(os.getcwd(), "entrada.mp4"), width=1920, height=1080, fps=24.0,
                           fps_str="24/1", frames=int(seconds * 24), duration=seconds, pix_fmt="yuv420p", bit_depth=8,
                           codec="h264", profile="", bitrate=0, color_space="bt709", color_range="tv",
                           color_transfer="bt709", color_primaries="bt709", has_audio=False, audio_codec="",
                           container="mov,mp4", is_image=False)


def export_dialog(doc=None, cues=(), quality="mp4"):
    from pelicula import export
    export.measure_speed = lambda *a, **k: 0.0
    from pelicula.ui.export_dialog import ExportDialog
    dlg = ExportDialog(None, export_info(), {}, "Teste", None, last_dir=os.getcwd(), last_quality=quality,
                       subtitles=doc, subtitle_cues=list(cues))
    dlg._est_timer.stop()
    dlg._preview_timer.stop()
    return dlg


def test_export_dialog_subtitle_options(ffmpeg_ok):
    dlg = export_dialog()
    assert dlg.subs_row.isHidden() and dlg.subtitle_choice() == "nao" and dlg.burn() is None
    job = dlg.job()
    assert job.subtitles == {} and job.burn == {} and job.subtitle_file == {}
    dlg.reject()
    cues = [Cue(1, 2, "oi"), Cue(3, 4, "tchau")]
    doc = sb.Subtitles(sources={PATH: list(cues)}, language="pt")
    dlg = export_dialog(doc, cues)
    assert not dlg.subs_row.isHidden() and dlg.subtitle_choice() == "faixa"   # o MP4 guarda a faixa
    assert dlg.job().subtitles["idioma"] == "pt" and dlg.burn() is None
    for choice, field in (("copia", "burn"), ("digital", "burn"), ("srt", "subtitle_file"), ("vtt", "subtitle_file")):
        dlg.subs_box.setCurrentIndex(dlg.subs_box.findData(choice))
        job = dlg.job()
        assert getattr(job, field), choice
        assert [f for f in ("subtitles", "burn", "subtitle_file") if getattr(job, f)] == [field], choice
    dlg.subs_box.setCurrentIndex(dlg.subs_box.findData("digital"))
    assert dlg.burn() == sb.Burn.make("digital", doc.style, cues) and dlg._preview_args()[-1] == dlg.burn()
    dlg.subs_box.setCurrentIndex(dlg.subs_box.findData("faixa"))
    i = dlg.quality.findData("xvid")
    if i >= 0:                                              # AVI não guarda faixa: vira o .srt ao lado
        dlg.quality.setCurrentIndex(i)
        assert dlg.container.currentData() == "avi" and dlg.subtitle_choice() == "srt"
        assert not dlg.subs_box.model().item(dlg.subs_box.findData("faixa")).isEnabled()
    dlg.reject()
    doc.burn = "copia"
    dlg = export_dialog(doc, cues)
    assert dlg.subtitle_choice() == "copia" and dlg.burn().mode == "copia"
    dlg.reject()


# ------------------------------------------------------------------ janela principal
@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = prefs.settings()
    for mod in modules.MODULES:
        s.remove(modules.KEY_PREFIX + mod.id)
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


def set_module(win, module_id, on):
    modules.set_enabled(win.settings, module_id, on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def load(win, m):
    win._loading = True
    try:
        win.model.set_sequence(m.seq)
    finally:
        win._loading = False
    APP.processEvents()


def test_window_button_panel_and_lane(win):
    ui = win.subs_ui
    assert win.btn_subs in win._module_tools()["legendas"] and not win.btn_subs.isHidden()
    load(win, model_with())
    assert ui.dock.isHidden() and not ui.lane.visible        # sem legendas: nada de faixa
    ui.toggle_panel()
    APP.processEvents()
    assert not ui.dock.isHidden() and ui.lane.visible
    ui.toggle_panel()
    APP.processEvents()
    assert ui.dock.isHidden() and not ui.lane.visible
    load(win, model_with(Cue(1, 2, "oi")))
    assert ui.lane.visible                                   # há legendas: a faixa aparece
    assert ui.ctl.items()[0].cue.text == "oi"


def test_window_module_off_hides_everything(win):
    ui = win.subs_ui
    load(win, model_with(Cue(1, 2, "oi")))
    ui.show_panel(True)
    set_module(win, "legendas", False)
    assert win.btn_subs.isHidden() and ui.dock.isHidden() and not ui.lane.visible
    ui.toggle_panel()                                        # o atalho não abre com o módulo desligado
    assert ui.dock.isHidden()
    assert win.model.seq.subtitles.sources[PATH][0].text == "oi"   # o projeto não muda
    set_module(win, "legendas", True)
    assert not win.btn_subs.isHidden() and ui.lane.visible
    assert not ui.panel.btn_generate.isVisibleTo(ui.panel)   # Beta "legendas_auto" começa desligado


def test_window_recipe_carries_the_burn(win):
    ui = win.subs_ui
    m = model_with(Cue(1, 2, "oi"))
    load(win, m)
    ui.panel.chk_preview.setChecked(False)
    assert win.frame_recipe().burn is None                    # sem gravar e sem "Ver na prévia"
    ui.panel.chk_preview.setChecked(True)
    assert win.frame_recipe().burn.mode == "digital"         # na prévia, por cima (como num player)
    assert ui.burn(full=True) is None                         # "Salvar quadro" sai como a exportação
    ui.ctl.set_options(burn="copia")
    full = ui.burn(full=True)
    assert full.mode == "copia" and [c.text for c in full.cues] == ["oi"]
    assert win.frame_recipe().burn == full and ui.burn() is ui.burn()   # guardada até as legendas mudarem
    set_module(win, "legendas", False)                        # desligar o módulo não muda o que sai
    assert ui.burn(full=True) == full and win.frame_recipe().burn == full
    set_module(win, "legendas", True)


@pytest.fixture
def fake_whisper(tmp_path, monkeypatch):
    """O whisper-cli falso (tests/whisper_falso.py) instalado e um som de mentira no lugar do ffmpeg."""
    import sys
    from pathlib import Path
    from pelicula import transcribe as tc
    model, vad = tmp_path / "modelo.bin", tmp_path / "vad.bin"
    model.write_bytes(b"m")
    vad.write_bytes(b"v")
    monkeypatch.delenv("PCTEST_WHISPER_MODO", raising=False)
    monkeypatch.delenv("PCTEST_WHISPER_LOG", raising=False)
    eng = tc.Engine((sys.executable, str(Path(__file__).with_name("whisper_falso.py"))), model, vad)
    monkeypatch.setattr(tc, "missing", lambda model="small", root=None: [])
    monkeypatch.setattr(tc, "engine", lambda model="small", root=None: eng)
    monkeypatch.setattr(tc, "vulkan_available", lambda: False)
    monkeypatch.setattr(tc, "temp_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(tc, "extract_audio", lambda path, out, *a, **k: Path(out).write_bytes(b"RIFF"))
    return tc


def wait_job(dlg, timeout=30.0):
    import time
    job = dlg.job
    assert job is not None and job.wait(timeout), "a transcrição não terminou"
    end = time.monotonic() + 5
    while dlg.progress_row.isVisible() or dlg.busy or not dlg.message.text():
        APP.processEvents()                     # o fim chega pela ponte da fila (thread principal)
        if time.monotonic() > end:
            break
    return job


def test_generate_is_hidden_without_the_beta_module(win):
    ui = win.subs_ui
    set_module(win, "legendas_auto", False)
    assert ui.panel.btn_generate.isHidden() and not ui.act_generate.isVisible() and ui.generate_dialog() is None
    set_module(win, "legendas_auto", True)
    assert not ui.panel.btn_generate.isHidden() and ui.act_generate.isVisible()


def test_generate_offers_the_components_page_when_something_is_missing(win, monkeypatch):
    from pelicula import tools, transcribe as tc
    set_module(win, "legendas_auto", True)
    load(win, model_with())
    monkeypatch.setattr(tc, "missing", lambda model="small", root=None: [tools.get(tc.MODELS[model])])
    pages = []
    monkeypatch.setattr(win, "show_settings", lambda page="geral": pages.append(page))
    dlg = win.subs_ui.generate_dialog()
    try:
        assert not dlg.missing_row.isHidden() and "Componentes" in dlg.missing.text()
        assert not dlg.btn_run.isEnabled() and dlg.start() is None and dlg.job is None   # nada baixa sozinho
        dlg.btn_components.click()
        assert pages == ["componentes"]
    finally:
        dlg.hide()


def test_generate_runs_in_the_queue_and_is_one_undo_step(win, fake_whisper):
    tc = fake_whisper
    set_module(win, "legendas_auto", True)
    win.set_mode("edicao")
    m = model_with(Cue(0.6, 0.9, "velha"), Cue(30, 31, "fora do trecho"))
    load(win, m)
    seq = win.model.seq
    a = [c for c in seq.clips if c.kind == AUDIO][0]
    win.model.select([a.id])
    dlg = win.subs_ui.generate_dialog()
    try:
        assert dlg.missing_row.isHidden() and dlg.scope.currentData() == "montagem"
        assert dlg.scope.findData("selecao") >= 0 and "20 s" in dlg.where.text()
        dlg.language.setCurrentIndex(dlg.language.findData("pt"))
        dlg.max_chars.setValue(16)
        dlg.max_lines.setValue(1)
        assert dlg.options() == tc.Options(model=dlg.model_box.currentData(), language="pt", gpu=dlg.gpu.isChecked(),
                                           max_chars=16, max_lines=1)
        undo_before = win.model.history._pos
        job = dlg.start()
        assert job.key == tc.JOB_KEY and job.kind == "cpu" and dlg.busy and not dlg.btn_run.isEnabled()
        wait_job(dlg)
        assert job.state == "concluido", job.error
        cues = win.model.seq.subtitles.sources[PATH]
        assert [c.text for c in cues] == ["Olá, pessoal.", "Tudo bem?", "fora do trecho"]   # 16 caracteres, 1 linha
        assert dlg.applied == 2 and "2 legendas geradas" in dlg.message.text()
        assert win.model.seq.subtitles.language == "pt" and not win.subs_ui.dock.isHidden()
        assert win.model.history._pos == undo_before + 1
        win.model.undo()                                      # um passo só: volta tudo
        assert [c.text for c in win.model.seq.subtitles.sources[PATH]] == ["velha", "fora do trecho"]
        win.model.redo()
        assert len(win.model.seq.subtitles.sources[PATH]) == 3
    finally:
        dlg.hide()
        win.set_mode("pelicula")


def test_generate_reports_errors_and_cancel(win, fake_whisper, monkeypatch):
    set_module(win, "legendas_auto", True)
    load(win, model_with())
    dlg = win.subs_ui.generate_dialog()
    try:
        monkeypatch.setenv("PCTEST_WHISPER_MODO", "falha")
        dlg.start()
        job = wait_job(dlg)
        assert job.state == "erro" and dlg.message.text() and win.model.seq.subtitles is None
        monkeypatch.setenv("PCTEST_WHISPER_MODO", "mudo")
        dlg.start()
        wait_job(dlg)
        assert "Nenhuma fala" in dlg.message.text() and win.model.seq.subtitles is None
        monkeypatch.setenv("PCTEST_WHISPER_MODO", "lento")
        dlg.start()
        dlg.cancel()
        job = wait_job(dlg)
        assert job.state == "cancelado" and "cancelada" in dlg.message.text()
    finally:
        dlg.hide()


def test_generate_does_not_touch_another_project(win, fake_whisper, monkeypatch):
    set_module(win, "legendas_auto", True)
    load(win, model_with())
    dlg = win.subs_ui.generate_dialog()
    try:
        monkeypatch.setenv("PCTEST_WHISPER_MODO", "lento")
        job = dlg.start()
        other = TimelineModel()
        seq = tl.Sequence(1920, 1080, "24/1")
        seq.insert_media(src("C:/v/outro.mp4"))
        other.set_sequence(seq)
        load(win, other)                                      # abriu outro projeto no meio da transcrição
        monkeypatch.setenv("PCTEST_WHISPER_MODO", "ok")
        wait_job(dlg, 60)
        assert job.state == "concluido" and win.model.seq.subtitles is None
        assert "projeto mudou" in dlg.message.text()
    finally:
        dlg.hide()


def test_window_undo_goes_to_the_subtitles_with_the_panel_focused(win):
    ui = win.subs_ui
    win.set_mode("pelicula")
    load(win, model_with(Cue(1, 2, "oi")))
    ui.show_panel(True)
    ui.ctl.set_text(ui.ctl.items()[0], "olá")
    win.activateWindow()                          # outra janela (Gerar legendas) pode ter ficado ativa
    APP.processEvents()
    ui.panel.table.setFocus()
    APP.processEvents()
    assert ui.owns_focus()
    win.undo()
    assert ui.ctl.items()[0].cue.text == "oi"
    win.redo()
    assert ui.ctl.items()[0].cue.text == "olá"
    ui.show_panel(False)
