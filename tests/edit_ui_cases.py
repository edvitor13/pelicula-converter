"""Casos da interface do modo Edição (rodados por test_edit_ui.py num subprocesso offscreen).

Este arquivo não é coletado sozinho pelo pytest (o nome não começa com test_): os widgets do Qt
precisam de uma QApplication própria, criada antes de qualquer QGuiApplication de outros testes.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import editparams, params, timeline as tl  # noqa: E402
from pelicula.timeline import AUDIO, VIDEO  # noqa: E402
from pelicula.ui import icons, scopes  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector, MediaBin, fmt_seconds  # noqa: E402
from pelicula.ui.scopes import Scopes  # noqa: E402
from pelicula.ui.sequence_dialog import SequenceDialog, fps_label  # noqa: E402
from pelicula.ui.store import ParamStore  # noqa: E402
from pelicula.ui.timeline_view import HEADER_W, MIME_SOURCE, RULER_H, TimelineEditor  # noqa: E402
from pelicula.ui.widgets import ColorWheel, SectionCard, WheelRow, wheel_hue  # noqa: E402

LMB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


def src(path="C:/v/a.mp4", frames=240, audio=True, **kw) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=audio, **kw)


def model_with(*sources) -> TimelineModel:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    for s in sources:
        seq.insert_media(s)
    m.set_sequence(seq)
    return m


def vclip(m, i=0):
    return sorted((c for c in m.seq.clips if c.kind == VIDEO), key=lambda c: c.start)[i]


def aclip(m, i=0):
    return sorted((c for c in m.seq.clips if c.kind == AUDIO), key=lambda c: c.start)[i]


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


# ------------------------------------------------------------------ modelo
def test_model_insert_select_undo_redo():
    m = TimelineModel()
    seen = []
    m.changed.connect(seen.append)
    made = m.insert_media(src())
    assert [c.kind for c in made] == [VIDEO, AUDIO]
    assert m.selection == [c.id for c in made]
    assert m.primary() is made[0]
    assert m.can_undo() and not m.can_redo()
    assert "structure" in seen
    m.undo()
    assert m.seq.clips == [] and m.selection == []
    assert m.can_redo()
    m.redo()
    assert len(m.seq.clips) == 2
    assert seen[-1] == "*"


def test_model_split_at_uses_selection_or_everything():
    m = model_with(src(), src("C:/v/b.mp4"))
    v0 = vclip(m, 0)
    m.select([v0.id])
    made = m.split_at(100)
    assert len(made) == 2  # vídeo e áudio ligados
    assert sorted(c.start for c in m.seq.clips if c.kind == VIDEO) == [0, 100, 240]
    m.select([])
    made = m.split_at(300)
    assert len(made) == 2
    assert sorted(c.start for c in m.seq.clips if c.kind == VIDEO) == [0, 100, 240, 300]


def test_model_delete_and_ripple():
    m = model_with(src(), src("C:/v/b.mp4"))
    first = vclip(m, 0)
    m.select_group(first.id)
    m.delete_selected(ripple=True)
    assert m.selection == []
    assert sorted((c.kind, c.start) for c in m.seq.clips) == [(AUDIO, 0), (VIDEO, 0)]
    m.undo()
    assert len(m.seq.clips) == 4


def test_model_clip_values_debounce_and_commit():
    m = model_with(src())
    v = vclip(m)
    steps = []
    m.historyChanged.connect(lambda: steps.append(1))
    vals = dict(v.values, exposicao=1.0)
    m.set_clip_values(v.id, vals, record=False)
    assert m.seq.find(v.id).values["exposicao"] == 1.0
    assert m.can_undo()
    m.commit()
    m.undo()
    assert m.seq.find(v.id).values["exposicao"] == 0.0
    m.redo()
    assert m.seq.find(v.id).values["exposicao"] == 1.0
    # Velocidade muda a duração (e a do áudio ligado) e o sinal é "structure".
    kinds = []
    m.changed.connect(kinds.append)
    m.set_clip_values(v.id, dict(m.seq.find(v.id).values, velocidade=2.0))
    assert m.seq.find(v.id).dur == 120 and aclip(m).dur == 120
    assert kinds[-1] == "structure"


def test_model_copy_paste_apply_all_look_reset():
    m = model_with(src(), src("C:/v/b.mp4"))
    a, b = vclip(m, 0), vclip(m, 1)
    m.set_clip_values(a.id, dict(a.values, temperatura=30.0, escala=2.0))
    assert m.copy_values(a.id) and m.has_clipboard()
    assert m.paste_values([b.id, aclip(m).id]) == 1
    assert m.seq.find(b.id).values["temperatura"] == 30.0
    assert m.seq.find(b.id).values["escala"] == 1.0  # enquadramento não é copiado
    m.set_clip_values(b.id, dict(m.seq.find(b.id).values, saturacao=0.5))
    assert m.apply_values_to_all(a.id) == 1
    assert m.seq.find(b.id).values["saturacao"] == 0.0
    look = next(v for k, _label, v in editparams.QUICK_LOOKS if k == "pb")
    m.apply_look(a.id, look)
    va = m.seq.find(a.id).values
    assert va["saturacao"] == -1.0 and va["temperatura"] == 0.0 and va["escala"] == 2.0
    m.reset_color(a.id)
    assert m.seq.find(a.id).values["saturacao"] == 0.0
    m.reset_values(a.id)
    assert m.seq.find(a.id).values == editparams.VIDEO.defaults()


def test_model_tracks():
    m = model_with(src())
    assert m.add_track(VIDEO) == 1
    m.set_track(AUDIO, 0, muted=True, volume=99)
    tr = m.seq.track(AUDIO, 0)
    assert tr.muted and tr.volume == 12.0
    with pytest.raises(KeyError):
        m.set_track(AUDIO, 0, bogus=1)
    m.remove_track(VIDEO, 1)
    assert len(m.seq.kind_tracks(VIDEO)) == 1
    m.remove_track(VIDEO, 0)  # a última faixa fica
    assert len(m.seq.kind_tracks(VIDEO)) == 1


def test_model_link_unlink_and_selection_group():
    m = model_with(src())
    v, a = vclip(m), aclip(m)
    m.select_group(v.id)
    assert m.selection == [v.id, a.id] and m.selection_linked()
    m.unlink_selected()
    assert not m.seq.find(v.id).link and not m.seq.find(a.id).link
    m.select_group(v.id)
    assert m.selection == [v.id]
    m.select([v.id, a.id])
    m.link_selected()
    assert m.seq.find(v.id).link and m.seq.find(v.id).link == m.seq.find(a.id).link
    m.select_group(a.id, toggle=True)
    assert m.selection == []


def test_model_settings_keep_time_when_fps_changes():
    m = model_with(src())
    m.set_settings(1280, 720, "48/1", (0.1, 0.2, 0.3))
    s = m.seq
    assert (s.width, s.height, s.fps_str) == (1280, 720, "48/1")
    assert s.background == (0.1, 0.2, 0.3)
    assert vclip(m).dur == 480 and s.duration == 480


# ------------------------------------------------------------------ linha do tempo
def test_editor_frame_x_mapping_and_zoom():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    assert c.frame_to_x(0) == HEADER_W
    for f in (0, 13, 240, 1000):
        assert c.x_to_frame(c.frame_to_x(f)) == pytest.approx(f)
    c.set_scroll(50)
    assert c.frame_to_x(50) == HEADER_W
    c.set_ppf(1000)
    assert c.ppf == 40.0
    ed.zoom_fit()
    assert c.scroll == 0 and c.frame_to_x(240) <= c.width()
    assert c.frame_to_x(240) > c.width() * 0.5


def test_editor_rows_video_above_audio():
    m = model_with(src())
    m.add_track(VIDEO)
    ed = editor(m)
    rows = ed.canvas.rows()
    assert [(k, i) for k, i, _y, _h in rows] == [(VIDEO, 1), (VIDEO, 0), (AUDIO, 0)]
    assert rows[0][2] == RULER_H
    assert ed.canvas.track_at(rows[1][2] + 5) == (VIDEO, 0)
    r = ed.canvas.clip_rect(vclip(m))
    assert ed.canvas.track_rect(VIDEO, 0).contains(r.center())


def test_editor_drag_moves_linked_clips():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    r = c.clip_rect(vclip(m))
    a = pt(r.center().x(), r.center().y())
    drag(c, a, a + QPoint(100, 0))  # 100 px a 2 px/quadro = 50 quadros
    assert vclip(m).start == 50 and aclip(m).start == 50
    assert m.can_undo()
    m.undo()
    assert vclip(m).start == 0


def test_editor_drag_to_another_video_track():
    m = model_with(src())
    m.add_track(VIDEO)
    ed = editor(m)
    c = ed.canvas
    r = c.clip_rect(vclip(m))
    top_row = c.track_rect(VIDEO, 1)
    a = pt(r.center().x(), r.center().y())
    drag(c, a, pt(r.center().x(), top_row.center().y()))
    assert vclip(m).track == 1
    assert aclip(m).track == 0  # o áudio ligado fica na faixa dele


def test_editor_trim_edges():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    c.snap = False
    r = c.clip_rect(vclip(m))
    y = int(r.center().y())
    drag(c, pt(r.left() + 2, y), pt(r.left() + 42, y))   # +20 quadros no começo
    v = vclip(m)
    assert v.start == 20 and v.dur == 220 and v.src_in == pytest.approx(20 / 24)
    r = c.clip_rect(v)
    drag(c, pt(r.right() - 2, y), pt(r.right() - 62, y))  # −30 quadros no fim
    assert vclip(m).end == 210 and aclip(m).end == 210


def test_editor_blade_splits_where_clicked():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    c.snap = False
    c.set_tool("blade")
    r = c.clip_rect(vclip(m))
    QTest.mouseClick(c, LMB, NOMOD, pt(c.frame_to_x(60), r.center().y()))
    assert sorted(x.start for x in m.seq.clips if x.kind == VIDEO) == [0, 60]
    assert sorted(x.start for x in m.seq.clips if x.kind == AUDIO) == [0, 60]


def test_editor_snaps_to_playhead():
    m = model_with(src(), src("C:/v/b.mp4"))
    ed = editor(m)
    c = ed.canvas
    ed.set_playhead(300)
    second = vclip(m, 1)
    r = c.clip_rect(second)
    a = pt(r.left() + 30, r.center().y())
    # 2 px/quadro e ímã de 9 px: soltar 3 quadros depois do cursor gruda nele.
    drag(c, a, a + QPoint(int((300 + 3 - second.start) * 2), 0))
    assert vclip(m, 1).start == 300


def test_editor_ruler_scrub_emits_seek():
    m = model_with(src())
    ed = editor(m)
    got, scrub = [], []
    ed.seekRequested.connect(got.append)
    ed.scrubbing.connect(scrub.append)
    c = ed.canvas
    QTest.mousePress(c, LMB, NOMOD, pt(c.frame_to_x(40), 10))
    QTest.mouseMove(c, pt(c.frame_to_x(80), 10))
    QTest.mouseRelease(c, LMB, NOMOD, pt(c.frame_to_x(80), 10))
    assert got[0] == 40 and got[-1] == 80
    assert scrub == [True, False]


def test_editor_keyboard_shortcuts():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    c.setFocus()
    ed.set_playhead(120)
    QTest.keyClick(c, Qt.Key.Key_S)
    assert len(m.seq.clips) == 4
    QTest.keyClick(c, Qt.Key.Key_B)
    assert c.tool == "blade" and ed.btn_blade.isChecked()
    QTest.keyClick(c, Qt.Key.Key_V)
    assert c.tool == "select"
    snap = c.snap
    QTest.keyClick(c, Qt.Key.Key_N)
    assert c.snap != snap and ed.btn_snap.isChecked() == c.snap
    m.select_group(vclip(m, 1).id)
    QTest.keyClick(c, Qt.Key.Key_Delete)
    assert len(m.seq.clips) == 2
    ppf = c.ppf
    QTest.keyClick(c, Qt.Key.Key_Plus)
    assert c.ppf > ppf


def test_editor_header_buttons_toggle_tracks():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    rows = {(k, i): (y, h) for k, i, y, h in c.rows()}
    y, h = rows[(AUDIO, 0)]
    btns = c.header_buttons(AUDIO, 0, y, h)
    QTest.mouseClick(c, LMB, NOMOD, btns["mute"].center().toPoint())
    assert m.seq.track(AUDIO, 0).muted
    QTest.mouseClick(c, LMB, NOMOD, btns["solo"].center().toPoint())
    assert m.seq.track(AUDIO, 0).solo
    QTest.mouseClick(c, LMB, NOMOD, btns["lock"].center().toPoint())
    assert m.seq.track(AUDIO, 0).locked
    vol = btns["volume"]
    QTest.mouseClick(c, LMB, NOMOD, pt(vol.left() + 1, vol.center().y()))
    assert m.seq.track(AUDIO, 0).volume < -50
    assert c.t_to_volume(c.volume_to_t(-6.0)) == -6.0
    y, h = rows[(VIDEO, 0)]
    QTest.mouseClick(c, LMB, NOMOD, c.header_buttons(VIDEO, 0, y, h)["mute"].center().toPoint())
    assert m.seq.track(VIDEO, 0).muted


def test_editor_drop_emits_target():
    m = model_with(src())
    ed = editor(m)
    c = ed.canvas
    got = []
    ed.filesDropped.connect(lambda paths, f, kind, idx: got.append((paths, f, kind, idx)))
    md = QMimeData()
    md.setData(MIME_SOURCE, "C:/v/x.mp4\nC:/v/y.wav".encode("utf-8"))
    y, h = next((y, h) for k, i, y, h in c.rows() if k == AUDIO)
    ev = QDropEvent(QPointF(c.frame_to_x(500), y + h / 2), Qt.DropAction.CopyAction, md, LMB, NOMOD)
    c.dropEvent(ev)
    assert got == [(["C:/v/x.mp4", "C:/v/y.wav"], 500, AUDIO, 0)]


def test_editor_paints_every_kind_with_waveform():
    m = model_with(src(), src("C:/v/img.png", frames=1, audio=False, is_image=True),
                   tl.Source("C:/m/song.mp3", has_video=False, has_audio=True, duration=20.0))
    v = vclip(m)
    m.set_clip_values(v.id, dict(v.values, entrada_tipo="preto", saida_tipo="branco",
                                 velocidade=1.5))
    a = aclip(m)
    m.set_clip_values(a.id, dict(a.values, fade_in=1.0, fade_out=2.0, volume=-6.0))
    ed = editor(m)
    calls = []

    def peaks(path):
        calls.append(path)
        return np.abs(np.sin(np.linspace(0, 80, 4000))).astype(np.float32)

    ed.set_peaks_provider(peaks)
    ed.set_inout(10, 200)
    for ppf in (0.05, 2.0, 30.0):
        ed.canvas.set_ppf(ppf)
        img = ed.grab()
        assert not img.isNull()
    assert calls
    ed.peaks_ready("C:/m/song.mp3")


def test_editor_link_button_reflects_selection():
    m = model_with(src())
    ed = editor(m)
    assert not ed.btn_delete.isEnabled()
    m.select_group(vclip(m).id)
    assert ed.btn_delete.isEnabled() and ed.btn_link.isEnabled()
    ed.btn_link.click()
    assert not vclip(m).link


# ------------------------------------------------------------------ mídia
def test_media_bin_add_emit_and_mime():
    b = MediaBin()
    assert b.stack.currentWidget() is b.empty
    b.add_source(src())
    b.add_source(tl.Source("C:/m/song.mp3", has_video=False, has_audio=True, duration=125.0))
    b.add_source(src())  # repetido: atualiza, não duplica
    assert b.paths() == ["C:/v/a.mp4", "C:/m/song.mp3"]
    assert b.stack.currentWidget() is b.list
    assert "2:05" in b.list.item(1).text()
    got = []
    b.addRequested.connect(got.append)
    b.list.setCurrentRow(1)
    b.btn_add.click()
    assert got == ["C:/m/song.mp3"]
    md = b.list.mimeData([b.list.item(0)])
    assert bytes(md.data(MIME_SOURCE)).decode() == "C:/v/a.mp4"
    removed = []
    b.removeRequested.connect(removed.append)
    b.btn_remove.click()
    assert removed == ["C:/m/song.mp3"]
    b.remove("C:/m/song.mp3")
    assert b.paths() == ["C:/v/a.mp4"]
    b.clear()
    assert b.paths() == [] and b.stack.currentWidget() is b.empty
    assert fmt_seconds(3725) == "1:02:05" and fmt_seconds(42) == "0:42"


# ------------------------------------------------------------------ inspetor
def test_inspector_binds_and_writes_values():
    m = model_with(src())
    ins = ClipInspector(m)
    assert ins.stack.currentWidget() is ins.empty
    v, a = vclip(m), aclip(m)
    m.select_group(v.id)
    assert ins.clip_id == v.id and ins.stack.currentWidget() is ins.video_page
    assert not ins.kind_seg.isHidden()
    ins.vstore.set("exposicao", 1.5)
    assert m.seq.find(v.id).values["exposicao"] == 1.5
    ins.kind_seg.changed.emit(AUDIO)
    assert ins.clip_id == a.id and ins.stack.currentWidget() is ins.audio_page
    ins.astore.set("volume", -6.0)
    assert m.seq.find(a.id).values["volume"] == -6.0
    # Mudar no modelo (desfazer) atualiza o inspetor sem gerar edição nova.
    m.commit()
    m.undo()
    assert ins.astore.get("volume") == 0.0
    m.select([])
    assert ins.stack.currentWidget() is ins.empty


def test_inspector_quick_looks_auto_and_clipboard():
    m = model_with(src(), src("C:/v/b.mp4"))
    ins = ClipInspector(m)
    v = vclip(m)
    m.select([v.id])
    autos = []
    ins.autoRequested.connect(autos.append)
    ins.chip_auto.click()
    assert autos == [v.id]
    warm = next(b for b in ins.look_chips if b.objectName() == "look_quente")
    warm.click()
    assert m.seq.find(v.id).values["temperatura"] > 0
    assert ins.vstore.get("temperatura") > 0
    ins.copy_values()
    assert ins.btn_paste.isEnabled()
    other = vclip(m, 1)
    m.select([other.id])
    ins.paste_values()
    assert m.seq.find(other.id).values["temperatura"] > 0
    ins.chip_reset.click()
    assert m.seq.find(other.id).values["temperatura"] == 0
    m.select([v.id])
    ins.apply_all()
    assert m.seq.find(other.id).values["temperatura"] > 0


def test_inspector_speed_changes_duration():
    m = model_with(src())
    ins = ClipInspector(m)
    v = vclip(m)
    m.select_group(v.id)
    ins.vstore.set("velocidade", 2.0)
    assert m.seq.find(v.id).dur == 120 and aclip(m).dur == 120
    assert "2×" in ins.info.text()


# ------------------------------------------------------------------ rodas e HSL
def test_wheel_row_clamps_and_resets():
    st = ParamStore(None, schema=editparams.VIDEO)
    row = WheelRow(editparams.VIDEO.params["roda_sombras"], st)
    w = row.wheel
    w.setValue(3.0, 4.0, emit=True)
    x, y = st.get("roda_sombras")
    assert (x * x + y * y) ** 0.5 == pytest.approx(1.0)
    assert x == pytest.approx(0.6) and y == pytest.approx(0.8)
    row.refresh()
    assert "%" in row.text.text()
    w.resetRequested.emit()
    assert st.get("roda_sombras") == [0.0, 0.0]
    assert wheel_hue(1, 0) == 0 and wheel_hue(0, 1) == 90 and wheel_hue(-1, 0) == 180


def test_color_wheel_mouse_and_fine_drag():
    w = ColorWheel(112)
    w.resize(112, 112)
    got = []
    w.valueChanged.connect(lambda x, y: got.append((x, y)))
    c, r = w.center(), w.radius()
    QTest.mousePress(w, LMB, NOMOD, pt(c.x() + r * 0.5, c.y()))
    QTest.mouseRelease(w, LMB, NOMOD, pt(c.x() + r * 0.5, c.y()))
    x, y = w.value()
    assert x == pytest.approx(0.5, abs=0.02) and abs(y) < 0.02
    QTest.mousePress(w, LMB, NOMOD, pt(c.x(), c.y() - r * 3))  # fora: fica na borda
    QTest.mouseRelease(w, LMB, NOMOD, pt(c.x(), c.y() - r * 3))
    x, y = w.value()
    assert y == pytest.approx(1.0, abs=1e-6) and abs(x) < 0.02
    start = w.value()
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.mousePress(w, LMB, shift, pt(c.x(), c.y()))
    QTest.mouseMove(w, pt(c.x() - r, c.y()))
    QTest.mouseRelease(w, LMB, shift, pt(c.x() - r, c.y()))
    x2, y2 = w.value()
    assert x2 == pytest.approx(start[0] - 0.15, abs=0.03)  # ajuste fino: 15% do movimento
    assert got


def test_hsl_card_shows_one_color_at_a_time():
    st = ParamStore(None, schema=editparams.VIDEO)
    sec = next(s for s in editparams.VIDEO_SECTIONS if s.layout == "hsl")
    card = SectionCard(sec, st)
    assert len(card._chips) == len(editparams.HSL_COLORS)
    first = editparams.HSL_COLORS[0][0]
    assert card.hsl_color == first
    visible = [r.param.key for r in card.rows if not r.isHidden()]
    assert visible == [f"hsl_{first}_matiz", f"hsl_{first}_sat", f"hsl_{first}_luz"]
    card.set_hsl_color("azul")
    assert [r.param.key for r in card.rows if not r.isHidden()][0] == "hsl_azul_matiz"
    st.set("hsl_verde_sat", -0.5)
    card.refresh("hsl_verde_sat")
    assert card._chips["verde"].marked and not card._chips["azul"].marked
    card.set_advanced(True)
    assert [r.param.key for r in card.rows if not r.isHidden()][0] == "hsl_azul_matiz"
    card._reset()
    assert st.get("hsl_verde_sat") == 0.0


def test_every_video_and_audio_section_builds():
    st = ParamStore(None, schema=editparams.VIDEO)
    for sec in editparams.VIDEO_SECTIONS:
        assert SectionCard(sec, st).rows
    sta = ParamStore(None, schema=editparams.AUDIO)
    for sec in editparams.AUDIO_SECTIONS:
        assert SectionCard(sec, sta).rows


def test_film_cards_unchanged():
    st = ParamStore(params.defaults())
    for sec in params.SECTIONS:
        card = SectionCard(sec, st)
        assert len(card.rows) == len([p for p in sec.params if p.key != sec.toggle])
        assert not card._chips


# ------------------------------------------------------------------ monitores
def test_scope_functions():
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, (90, 160, 3), dtype=np.uint8)
    wf = scopes.waveform(img[..., 0])
    assert wf.shape == (scopes.WAVE_H, 160) and wf.sum() == 90 * 160
    gray = np.full((10, 10, 3), 128, np.uint8)
    vs = scopes.vectorscope(gray)
    n = scopes.VEC_N
    yy, xx = np.unravel_index(int(vs.argmax()), vs.shape)
    assert abs(xx - (n - 1) / 2) <= 1 and abs(yy - (n - 1) / 2) <= 1
    h = scopes.histogram(img)
    assert h.shape == (3, 64) and 0 <= h.min() and h.max() <= 1


def test_scopes_every_mode_paints():
    sc = Scopes()
    sc.resize(340, 170)
    modes = []
    sc.modeChanged.connect(modes.append)
    img = (np.random.default_rng(1).random((180, 320, 3)) * 65535).astype(np.uint16)
    for key, _label, _tip in scopes.MODES:
        sc.mode = key
        sc.set_image(img)
        assert not sc.grab().isNull()
    assert modes == ["wave", "parade", "vector"]
    sc.set_image(None)
    sc.grab()
    sc.set_mode("nao_existe")
    assert sc.mode == "vector"


# ------------------------------------------------------------------ sequência
def test_sequence_dialog_values_and_presets():
    m = TimelineModel(tl.Sequence.for_source(tl.Source("C:/v/v.mp4", 3840, 1600, 25.0, "25/1", 100, 4.0)))
    d = SequenceDialog(None, m.seq)
    assert d.values()[:3] == (3840, 1600, "25/1")
    assert d.res.currentData() == "primeiro"
    d.res.setCurrentIndex(d.res.findData("vertical"))
    assert d.values()[:2] == (1080, 1920) and not d.w.isEnabled()
    d.res.setCurrentIndex(d.res.findData("custom"))
    assert d.w.isEnabled()
    d.w.setValue(1000)
    d.h.setValue(500)
    d.fps.setCurrentIndex(d.fps.findData("24000/1001"))
    w, h, fps, bg = d.values()
    assert (w, h, fps) == (1000, 500, "24000/1001") and bg == (0.0, 0.0, 0.0)
    assert "23,976" in fps_label("24000/1001") and fps_label("24/1").startswith("24 ")


def test_new_icons_draw_something():
    names = ["scissors", "magnet", "link", "unlink", "track_add", "ripple_delete", "pointer", "wand", "copy",
             "paste", "music", "eye", "eye_off", "lock", "unlock", "headphones", "edit_mode", "film_mode", "speed",
             "davinci"]
    for n in names:
        img = icons.icon(n, "#ffffff", 24).pixmap(24, 24).toImage()
        alpha = sum(img.pixelColor(x, y).alpha() for x in range(24) for y in range(24))
        assert alpha > 0, n


# ------------------------------------------------------------------ layouts que acompanham a largura
def test_flow_layout_wraps_and_stretches():
    from PySide6.QtWidgets import QToolButton, QWidget
    from pelicula.ui.flow import FlowLayout
    box = QWidget()
    lay = FlowLayout(box, 4, 4)
    lay.setContentsMargins(0, 0, 0, 0)
    buttons = []
    for i in range(6):
        b = QToolButton()
        b.setText(f"Botão {i}")
        b.setFixedSize(80, 24)
        lay.addWidget(b)
        buttons.append(b)
        if i == 2:
            lay.add_stretch()
    box.resize(1000, 40)
    box.show()
    APP.processEvents()
    assert len({b.y() for b in buttons}) == 1                  # cabe numa linha
    assert buttons[3].x() + 80 * 3 + 8 > 900                     # o espaçador empurrou o resto para a direita
    assert lay.minimumSize().width() == 80
    h1 = lay.heightForWidth(1000)
    h3 = lay.heightForWidth(180)
    assert h3 > h1 and h3 >= 24 * 3                              # estreito: quebra em várias linhas
    box.resize(180, h3)
    APP.processEvents()
    assert len({b.y() for b in buttons}) >= 3
    assert all(b.x() + b.width() <= 180 for b in buttons)
    box.close()


def test_adaptive_bar_compacts_before_wrapping():
    from PySide6.QtWidgets import QLabel, QToolButton
    from pelicula.ui.flow import AdaptiveBar, FlowLayout
    bar = AdaptiveBar()
    lay = FlowLayout(bar, 4, 4)
    lay.setContentsMargins(0, 0, 0, 0)
    tools = []
    for i in range(5):
        b = QToolButton()
        b.setIcon(icons.icon("film", "#ffffff", 16))
        b.setText(f"Ferramenta {i}")
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        lay.addWidget(b)
        tools.append(b)
    extra = QLabel("100%")
    lay.addWidget(extra)
    bar.set_adaptive(compact=tools, optional=[extra])
    bar.resize(2000, 40)
    bar.show()
    APP.processEvents()
    assert bar.level == 0 and tools[0].toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    icon_w = 5 * 36
    bar.resize(icon_w + 60, 40)
    APP.processEvents()
    assert bar.level >= 1 and tools[0].toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert tools[0].toolTip() == "Ferramenta 0"                    # o texto continua na dica
    bar.resize(2000, 40)
    APP.processEvents()
    assert bar.level == 0 and extra.isVisible()
    bar.close()


def test_looks_panel_reflows_columns():
    from pelicula.ui.looks import LooksPanel
    p = LooksPanel()
    p.rebuild([{"id": f"p{i}", "nome": f"Preset {i}", "grupo": "Cinema 35 mm", "desc": "", "valores": {}}
               for i in range(6)])
    p.resize(560, 700)
    p.show()
    APP.processEvents()
    APP.processEvents()
    thumbs = list(p.thumbs.values())
    wide = len({t.x() for t in thumbs})
    p.resize(p.minimumWidth(), 700)
    APP.processEvents()
    APP.processEvents()
    narrow = len({t.x() for t in thumbs})
    assert wide >= 3 and narrow == 1, (wide, narrow)
    assert all(t.x() + t.width() <= p.scroll.viewport().width() for t in thumbs)
    p.close()
