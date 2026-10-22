"""Casos da interface de marcadores, capítulos, medidor de som e transição de som.

Rodados por test_edicao_som_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do
Qt precisam de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import timeline_view  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.markers import ChaptersDialog, MarkerDialog, youtube_chapters  # noqa: E402
from pelicula.ui.timeline_view import RULER_H, TimelineEditor  # noqa: E402
from pelicula.ui.widgets import Timeline  # noqa: E402

LMB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def src(path="C:/v/a.mp4", frames=240, audio=True, **kw) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=audio, **kw)


def model_with(*sources) -> TimelineModel:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    for s in sources:
        seq.insert_media(s)
    m.set_sequence(seq)
    return m


def editor(m, w=1100, h=320, ppf=2.0) -> TimelineEditor:
    ed = TimelineEditor(m)
    ed.resize(w, h)
    ed.show()
    APP.processEvents()
    ed.canvas.set_ppf(ppf)
    ed.canvas.set_scroll(0)
    return ed


def pt(x, y) -> QPoint:
    return QPoint(int(round(x)), int(round(y)))


def drag(widget, a: QPoint, b: QPoint, mods=NOMOD) -> None:
    QTest.mousePress(widget, LMB, mods, a)
    QTest.mouseMove(widget, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(widget, b)
    QTest.mouseRelease(widget, LMB, mods, b)


# ------------------------------------------------------------------ marcadores na linha do tempo
def test_markers_keys_add_navigate_and_delete():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    seeks = []
    ed.seekRequested.connect(seeks.append)
    c.setFocus()
    ed.set_playhead(48)
    QTest.keyClick(c, Qt.Key.Key_M)
    ed.set_playhead(120)
    QTest.keyClick(c, Qt.Key.Key_M)
    first, second = m.seq.sorted_markers()
    assert (first.frame, second.frame) == (48, 120) and m.marker_sel == second.id
    QTest.keyClick(c, Qt.Key.Key_M)  # já há um marcador aqui: só seleciona, não duplica
    QTest.keyClick(c, Qt.Key.Key_M, SHIFT)  # Shift+M é o som da prévia (fica para a janela)
    assert len(m.seq.markers) == 2
    ed.set_playhead(0)
    QTest.keyClick(c, Qt.Key.Key_Down, SHIFT)
    assert seeks[-1] == 48 and m.marker_sel == first.id
    ed.set_playhead(48)
    QTest.keyClick(c, Qt.Key.Key_Down, SHIFT)
    assert seeks[-1] == 120
    ed.set_playhead(120)
    QTest.keyClick(c, Qt.Key.Key_Up, SHIFT)
    assert seeks[-1] == 48 and m.marker_sel == first.id
    clips = len(m.seq.clips)
    assert ed.btn_delete.isEnabled()
    QTest.keyClick(c, Qt.Key.Key_Delete)  # apaga o marcador selecionado, não os clipes
    assert [mk.frame for mk in m.seq.markers] == [120] and len(m.seq.clips) == clips
    assert not ed.btn_delete.isEnabled()


def test_markers_mouse_click_drag_tooltip_and_paint():
    m = model_with(src())
    mk = m.add_marker(48, name="Abertura", note="Entrar com a música")
    m.update_marker(mk.id, chapter=True)
    ed = editor(m)
    c = ed.canvas
    seeks = []
    ed.seekRequested.connect(seeks.append)
    y = RULER_H - 6
    x = c.frame_to_x(48)
    assert c.marker_at(QPointF(x + 3, y)).id == mk.id
    assert c.marker_at(QPointF(x, RULER_H + 10)) is None and c.marker_at(QPointF(x + 30, y)) is None
    m.select([])
    QTest.mouseClick(c, LMB, NOMOD, pt(x, y))
    assert seeks == [48] and m.marker_sel == mk.id  # clique: seleciona e leva o cursor até ele
    drag(c, pt(x, y), pt(x + 40, y))  # 2 px por quadro: 20 quadros adiante
    assert m.seq.marker(mk.id).frame == 68 and seeks == [48]
    m.undo()
    assert m.seq.marker(mk.id).frame == 48
    c._update_cursor(QPointF(x, y))
    tip = c.toolTip()
    assert "Abertura" in tip and "Entrar com a música" in tip and "capítulo" in tip
    c._update_cursor(QPointF(x + 200, y))
    assert c.toolTip() == ""
    for ppf in (0.05, 2.0, 30.0):
        c.set_ppf(ppf)
        assert not ed.grab().isNull()


def test_marker_double_click_edits_or_removes(monkeypatch):
    m = model_with(src())
    mk = m.add_marker(48)
    ed = editor(m)
    c = ed.canvas

    class Edit:
        removed = False

        def __init__(self, parent, marker, fps):
            assert marker.id == mk.id and fps == 24.0

        def exec(self):
            return 1

        def values(self):
            return {"name": "Abertura", "note": "Nota", "color": "azul", "chapter": True}

    monkeypatch.setattr(timeline_view, "MarkerDialog", Edit)
    QTest.mouseDClick(c, LMB, NOMOD, pt(c.frame_to_x(48), RULER_H - 6))
    got = m.seq.marker(mk.id)
    assert (got.frame, got.name, got.note, got.color, got.chapter) == (48, "Abertura", "Nota", "azul", True)

    class Remove(Edit):
        removed = True

    monkeypatch.setattr(timeline_view, "MarkerDialog", Remove)
    c.edit_marker(mk.id)
    assert m.seq.markers == []
    m.undo()
    assert m.seq.marker(mk.id).name == "Abertura"


def test_marker_and_ruler_menus():
    m = model_with(src())
    mk = m.add_marker(48)
    ed = editor(m)
    c = ed.canvas
    menu = QMenu()
    c.marker_menu(menu, mk)
    acts = {a.text(): a for a in menu.actions() if a.text()}
    acts["Capítulo (YouTube e arquivo exportado)"].trigger()
    assert m.seq.marker(mk.id).chapter
    colors = acts["Cor"].menu()
    assert len(colors.actions()) == len(tl.MARKER_COLORS)
    next(a for a in colors.actions() if a.text() == "Azul").trigger()
    assert m.seq.marker(mk.id).color == "azul"
    acts["Remover marcador"].trigger()
    assert m.seq.markers == []
    menu = QMenu()
    c.ruler_menu(menu, 100)
    acts = {a.text(): a for a in menu.actions() if a.text()}
    assert not acts["Remover todos os marcadores"].isEnabled()
    acts["Adicionar marcador aqui"].trigger()
    ed.set_playhead(30)
    acts["Adicionar marcador no cursor (M)"].trigger()
    assert sorted(x.frame for x in m.seq.markers) == [30, 100]
    m.clear_markers()
    assert m.seq.markers == [] and m.marker_sel is None


def test_toolbar_marker_buttons():
    m = model_with(src())
    ed = editor(m)
    assert not ed.act_next_marker.isEnabled() and not ed.act_edit_marker.isEnabled()
    ed.set_playhead(60)
    ed.btn_marker.click()
    assert [x.frame for x in m.seq.markers] == [60]
    assert ed.act_next_marker.isEnabled() and ed.act_edit_marker.isEnabled()
    ed.act_clear_markers.trigger()
    assert m.seq.markers == [] and not ed.act_clear_markers.isEnabled()


# ------------------------------------------------------------------ diálogos
def test_marker_dialog_values():
    mk = tl.Marker("m1", 48, color="verde", name="A", note="B")
    d = MarkerDialog(None, mk, 24.0)
    assert d.values() == {"name": "A", "note": "B", "color": "verde", "chapter": False}
    assert "00:00:02:00" in d.windowTitle()
    d.name.setText("  Abertura  ")
    d.color_buttons["roxo"].click()
    d.chapter.setChecked(True)
    assert d.values() == {"name": "Abertura", "note": "B", "color": "roxo", "chapter": True}
    d._remove()
    assert d.removed and d.result() == 1


def test_youtube_chapters_dialog_copies_the_text():
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(src(frames=24 * 60))
    for f, name in ((0, "Abertura"), (24 * 20, "Meio"), (24 * 45, "Fim")):
        seq.add_marker(f, name=name, chapter=True)
    seq.add_marker(24 * 30, name="Só uma nota")
    text, problems = youtube_chapters(seq)
    assert text == "00:00 Abertura\n00:20 Meio\n00:45 Fim" and problems == []
    dlg = ChaptersDialog(None, text, problems)
    assert "Tudo certo" in dlg.status.text()
    dlg.copy()
    assert QApplication.clipboard().text() == text and dlg.btn_copy.text() == "Copiado"
    # trecho marcado a partir de 10 s: os tempos contam da entrada, como na exportação do trecho
    text, problems = youtube_chapters(seq, 24 * 10, 24 * 60)
    assert text == "00:00 Abertura\n00:10 Meio\n00:35 Fim" and problems == []
    bad = ChaptersDialog(None, "00:05 X", ["O primeiro capítulo precisa começar em 00:00"])
    assert "00:00" in bad.status.text()


def test_film_timeline_shows_markers_and_clicks_land_on_them():
    t = Timeline()
    t.resize(400, 34)
    t.show()
    t.set_media(240, 24.0)
    t.set_markers([(120, "#5b8def", "Meio")])
    seeks = []
    t.seek.connect(seeks.append)
    x = t._x(120)
    assert t.marker_near(x + 3) == (120, "Meio") and t.marker_near(x + 30) is None
    QTest.mouseClick(t, LMB, NOMOD, pt(x + 2, 17))
    assert seeks and set(seeks) == {120}
    QTest.mouseMove(t, pt(x, 17))
    assert not t.grab().isNull()
    t.set_markers([])
    assert t.marker_near(x) is None


def test_export_dialog_includes_chapters_option(tmp_path, monkeypatch):
    from pelicula import export, media
    try:
        ok = media.configure()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg indisponível: {exc}")
    if not ok:
        pytest.skip("ffmpeg/ffprobe não encontrados")
    monkeypatch.setattr(export, "measure_speed", lambda *a, **k: 0.0)
    from pelicula.ui.export_dialog import ExportDialog
    info = media.MediaInfo(path=str(tmp_path / "entrada.mp4"), width=1920, height=1080, fps=24.0, fps_str="24/1",
                           frames=480, duration=20.0, pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="",
                           bitrate=0, color_space="bt709", color_range="tv", color_transfer="bt709",
                           color_primaries="bt709", has_audio=False, audio_codec="", container="mov,mp4",
                           is_image=False)
    pts = [(0, "Abertura"), (240, "Meio")]
    dlg = ExportDialog(None, info, {}, "Teste", None, last_dir=str(tmp_path), chapters=pts)
    dlg._est_timer.stop()
    box = dlg.chapters_box
    assert not box.isHidden() and box.isChecked() and "(2)" in box.text()
    dlg.codec.setCurrentIndex(dlg.codec.findData("x264"))
    dlg.container.setCurrentIndex(dlg.container.findData("mkv"))
    assert box.isEnabled() and dlg.job().chapters == pts
    box.setChecked(False)
    assert dlg.job().chapters == []
    box.setChecked(True)
    dlg.codec.setCurrentIndex(dlg.codec.findData("gif"))  # GIF não guarda capítulos
    assert not box.isEnabled() and dlg.job().chapters == []
    dlg._est_timer.stop()
    plain = ExportDialog(None, info, {}, "Teste", None, last_dir=str(tmp_path))
    plain._est_timer.stop()
    assert plain.chapters_box.isHidden() and plain.job().chapters == []


# ------------------------------------------------------------------ janela principal (pula sem OpenGL)
@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    prefs.settings().setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def fake_source(path, frames=96, audio=False):
    return tl.Source(path, 640, 360, 24.0, "24/1", frames, frames / 24.0, has_audio=audio)


def with_sequence(win, *sources, mode="edicao") -> None:
    """Montagem com arquivos que não existem (a prévia falha em silêncio; o tempo e os marcadores, não)."""
    win.set_mode("pelicula")
    win.file_info = None
    seq = tl.Sequence(640, 360, "24/1")
    for s in sources:
        seq.insert_media(s)
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.set_mode(mode)
    APP.processEvents()


def pretend_audio(win) -> None:
    win._audio_ok = True
    win.btn_mute.setEnabled(True)
    win._update_mute_tip()


def test_window_m_marks_in_edit_mode_and_shift_m_mutes(win):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"), fake_source("C:/nao_existe/b.mp4"))
    assert win.mode == "edicao" and win.info is not None
    pretend_audio(win)
    assert "Shift+M" in win.btn_mute.toolTip()
    win.request_frame(24)
    muted = win.btn_mute.isChecked()
    QTest.keyClick(win, Qt.Key.Key_M)
    assert [mk.frame for mk in win.model.seq.markers] == [24]
    assert win.btn_mute.isChecked() == muted  # M no modo Edição não mexe no som
    QTest.keyClick(win, Qt.Key.Key_M, SHIFT)
    assert win.btn_mute.isChecked() != muted and len(win.model.seq.markers) == 1
    QTest.keyClick(win, Qt.Key.Key_M, SHIFT)
    assert win.btn_mute.isChecked() == muted
    win.request_frame(60)
    QTest.keyClick(win, Qt.Key.Key_M)
    win.request_frame(0)
    QTest.keyClick(win, Qt.Key.Key_Down, SHIFT)
    assert win.frame_idx == 24
    QTest.keyClick(win, Qt.Key.Key_Down, SHIFT)
    assert win.frame_idx == 60
    QTest.keyClick(win, Qt.Key.Key_Up, SHIFT)
    assert win.frame_idx == 24
    # modo Película: M continua sendo o som; Shift+↑/↓ também pulam entre os marcadores
    win.set_mode("pelicula")
    pretend_audio(win)
    assert "(M liga" in win.btn_mute.toolTip()
    assert [f for f, _c, _n in win.timeline.markers] == [24, 60]
    QTest.keyClick(win, Qt.Key.Key_M)
    assert win.btn_mute.isChecked() != muted and len(win.model.seq.markers) == 2
    QTest.keyClick(win, Qt.Key.Key_M)
    assert win.btn_mute.isChecked() == muted
    win.request_frame(70)
    QTest.keyClick(win, Qt.Key.Key_Up, SHIFT)
    assert win.frame_idx == 60


def test_window_marker_changes_do_not_reload_the_preview(win, monkeypatch):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"), fake_source("C:/nao_existe/b.mp4"))
    calls = []
    monkeypatch.setattr(win, "_refresh_source", lambda *a, **k: calls.append(a))
    mk = win.model.add_marker(30, name="Abertura")
    win.model.update_marker(mk.id, chapter=True, color="azul")
    win.model.move_marker(mk.id, 36)
    assert calls == []
    assert win.timeline.markers == [(36, "#5b8def", "Abertura")]
    assert win._export_chapters() == [(36, "Abertura")]
    assert win.is_dirty() and "marcadores" in win._seq_json()
    win.model.undo()
    assert win.model.seq.marker(mk.id).frame == 30 and calls == []


def test_window_keeps_markers_of_a_plain_file_in_the_project(win):
    from types import SimpleNamespace
    src = fake_source("C:/nao_existe/filme.mp4")
    seq = tl.Sequence.for_source(src)
    win.set_mode("pelicula")
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    old = win.file_info
    win.file_info = SimpleNamespace(path=src.path)
    try:
        assert win._seq_json() is None  # arquivo inteiro sem mudanças: projeto simples (formato 1)
        win.model.seq.add_marker(12, name="Cena 2")
        data = win._seq_json()
        assert data is not None and data["marcadores"][0]["nome"] == "Cena 2"
    finally:
        win.file_info = old
