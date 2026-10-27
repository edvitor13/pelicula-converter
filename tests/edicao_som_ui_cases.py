"""Casos da interface de marcadores, capítulos, medidor de som e transição de som.

Rodados por test_edicao_som_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do
Qt precisam de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import math
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


# ------------------------------------------------------------------ medidor de som
def test_audio_meter_widget_peaks_hold_idle_and_click():
    from pelicula.ui.meter import FLOOR, HOLD_S, AudioMeter, fmt_level, level_to_t
    assert level_to_t(0.0) == 1.0 and level_to_t(FLOOR) == 0.0 and level_to_t(None) == 0.0
    assert 0 < level_to_t(-40) < level_to_t(-20) < level_to_t(-6) < 1
    assert fmt_level(None) == "—" and fmt_level(float("-inf")) == "−∞"
    assert fmt_level(-23.04).replace(".", ",") == "−23,0"
    m = AudioMeter()
    m.resize(88, 320)
    m.show()
    assert not m.active and m.integrated is None and not m.grab().isNull()
    m.restart()
    m.push([-6.0, -12.0], -20.0, None, -21.5, -5.5, now=10.0)
    assert m.active and m.level == [-6.0, -12.0] and m.hold == [-6.0, -12.0]
    assert (m.momentary, m.short_term, m.integrated, m.true_peak) == (-20.0, None, -21.5, -5.5)
    m.push([-30.0, -30.0], now=10.5)  # a barra cai 24 dB/s e o traço do pico fica
    assert m.level[0] == pytest.approx(-18.0) and m.hold[0] == -6.0
    m.push([-30.0, -30.0], now=10.5 + HOLD_S + 0.1)  # passou a retenção
    assert m.hold[0] == pytest.approx(-30.0) and m.level[0] == pytest.approx(-30.0)
    m.push([float("-inf")], now=14.0)  # mono vai para as duas barras; silêncio é a base
    assert m.level == [FLOOR, FLOOR]
    m.push([0.0, -40.0], now=14.5)
    assert m.clip == [True, False]
    m.set_waiting(True)
    assert not m.grab().isNull()
    resets = []
    m.resetRequested.connect(lambda: resets.append(1))
    QTest.mouseClick(m, LMB, NOMOD, pt(40, 100))
    assert resets == [1] and m.clip == [False, False]
    m.idle()  # parou: as barras descem e as leituras ficam
    assert not m.active and m.level == [FLOOR, FLOOR] and m.integrated is None and m.momentary is None
    m.push([-10.0, -10.0], -15.0, -16.0, -17.0, -3.0, now=20.0)
    m.idle()
    assert m.integrated == -17.0 and m.true_peak == -3.0 and not m.grab().isNull()
    m.clear()
    assert m.integrated is None and not m.waiting


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


def tone_wav(path, secs=8.0, dbfs=-23.0, rate=48000) -> str:
    """WAV estéreo de 24 bits com um seno de 1 kHz (como a mixagem da prévia)."""
    import struct

    import numpy as np
    t = np.arange(int(secs * rate)) / rate
    x = 10 ** (dbfs / 20) * np.sin(2 * np.pi * 1000 * t)
    v = np.round(np.repeat(x[:, None], 2, axis=1) * 8388607).astype(np.int64) & 0xFFFFFF
    data = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=-1).astype(np.uint8).tobytes()
    fmt = struct.pack("<HHIIHH", 1, 2, rate, rate * 6, 6, 24)
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE")
        fh.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data)
    return str(path)


def meter_on(win, on: bool) -> None:
    from pelicula import modules
    modules.set_enabled(win.settings, "medidor_som", on)
    win.apply_modules()


def meter_source(win, kind, path) -> None:
    """Troca o som que o medidor lê sem passar pelo QMediaPlayer (o resto de `_set_audio`)."""
    win._audio_src = (kind, path)
    win._meter_source()


def test_window_meter_follows_the_playback_clock(win, tmp_path, monkeypatch):
    import time
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"))
    meter_on(win, True)
    assert win.meter.isVisible() and win.meter.parent() is win.viewer.parent()
    wav = tone_wav(tmp_path / "mix.wav")
    meter_source(win, "seq", wav)
    assert win._meter_reader is not None and win._meter_reader.rate == 48000
    monkeypatch.setattr(win.player, "start", lambda *a, **k: None)  # sem decodificar quadros de verdade
    win.start_play(0)
    try:
        assert win.meter_timer.isActive() and win.meter.active and win._meter_pos is None
        win._meter_tick()  # antes do primeiro quadro chegar o relógio não começou: nada a medir
        assert win._meter_lm.samples == 0
        # 2 s tocados a partir do quadro 24 (1 s): mede o trecho 1 s → 3 s do WAV
        win._play_f0, win._play_t0 = 24, time.perf_counter() - 2.0
        win._meter_tick()
        lm = win._meter_lm
        assert lm.samples == pytest.approx(2 * 48000, abs=4800)
        assert win._meter_pos == pytest.approx(3 * 48000, abs=4800)
        assert win.meter.momentary == pytest.approx(-23.0, abs=0.1)
        assert win.meter.integrated == pytest.approx(-23.0, abs=0.1)
        assert win.meter.true_peak == pytest.approx(-23.0, abs=0.2)  # o seno tem pico de −23 dBFS
        assert win.meter.level[0] == pytest.approx(-23.0, abs=0.2) and win.meter.level[1] == win.meter.level[0]
        # mais 1 s: continua somando
        win._play_t0 -= 1.0
        win._meter_tick()
        assert lm.samples == pytest.approx(3 * 48000, abs=4800) and win.meter.short_term is not None
        # volta do loop (o tempo anda para trás): medição nova a partir do quadro de partida
        win._play_f0, win._play_t0 = 0, time.perf_counter() - 0.5
        win._meter_tick()
        assert lm.samples == pytest.approx(0.5 * 48000, abs=4800) and win.meter.short_term is None
        # salto para a frente maior que 5 s (a janela travou): recomeça de agora
        win._play_t0 -= 6.0
        win._meter_tick()
        assert lm.samples == 0 and win._meter_pos == pytest.approx(6.5 * 48000, abs=4800)
        # clique no medidor: recomeça sem parar
        win.meter.resetRequested.emit()
        assert lm.samples == 0 and win.meter.integrated is None
        # pular durante a reprodução passa por start_play: recomeça
        win._play_t0 -= 1.0
        win._meter_tick()
        assert lm.samples > 0
        win.start_play(48)
        assert win._meter_pos is None and win.meter.integrated is None
        win._play_f0, win._play_t0 = 48, time.perf_counter() - 1.0
        win._meter_tick()
        assert win.meter.integrated == pytest.approx(-23.0, abs=0.1)
    finally:
        win.stop_play()
    assert not win.meter_timer.isActive() and not win.meter.active
    assert win.meter.integrated == pytest.approx(-23.0, abs=0.1)  # a leitura fica (apagada) depois do stop
    # fonte nova: o medidor zera; arquivo apagado no meio da leitura não derruba nada
    meter_source(win, "seq", "")
    assert win._meter_reader is None and win.meter.integrated is None
    meter_source(win, "seq", wav)
    os.remove(wav)
    win.playing, win._play_f0, win._play_t0 = True, 0, time.perf_counter() - 1.0
    try:
        win._meter_tick()
    finally:
        win.playing = False


def test_window_meter_hides_and_stops_when_the_module_is_off(win, tmp_path):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"))
    meter_on(win, True)
    wav = tone_wav(tmp_path / "mix.wav", secs=1.0)
    meter_source(win, "seq", wav)
    assert win._meter_reader is not None
    meter_on(win, False)
    try:
        assert not win.meter.isVisible() and win._meter_reader is None and win._meter_for == ("", "")
        win._meter_start()
        assert not win.meter_timer.isActive()
        meter_source(win, "file", wav)  # desligado: nem decodifica
        assert win._meter_files == [] and not win.meter.waiting and win._meter_reader is None
        meter_source(win, "seq", wav)
        assert win._meter_reader is None
    finally:
        meter_on(win, True)
    assert win.meter.isVisible() and win._meter_for == ("seq", wav) and win._meter_reader is not None


def test_window_meter_decodes_the_file_sound_once(win, tmp_path):
    import time

    from pelicula import media
    try:
        ok = media.configure()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg indisponível: {exc}")
    if not ok:
        pytest.skip("ffmpeg/ffprobe não encontrados")
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"), mode="pelicula")
    meter_on(win, True)
    src = tone_wav(tmp_path / "filme.wav", secs=2.0)

    def wait_reader():
        deadline = time.monotonic() + 30
        while win._meter_reader is None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.02)
        assert win._meter_reader is not None

    meter_source(win, "", "")
    meter_source(win, "file", src)
    assert win.meter.waiting and len(win._meter_files) == 1
    decoded = win._meter_files[0]
    assert os.path.basename(decoded).startswith("pelicula_medidor_")
    wait_reader()
    assert not win.meter.waiting and win._meter_reader.path == decoded
    assert (win._meter_reader.rate, win._meter_reader.channels) == (48000, 2)
    # Edição e volta: o som decodificado é reaproveitado
    meter_source(win, "seq", src)
    assert os.path.exists(decoded) and win._meter_reader.path == src
    meter_source(win, "file", src)
    assert win._meter_reader.path == decoded and not win.meter.waiting
    # fonte trocada no meio da decodificação: o pedido antigo é cancelado e o arquivo dele não fica
    other = tone_wav(tmp_path / "outro.wav", secs=2.0)
    meter_source(win, "file", other)
    assert not os.path.exists(decoded) and win.meter.waiting
    cancelled = win._meter_files[-1]
    meter_source(win, "file", src)
    wait_reader()
    deadline = time.monotonic() + 10
    while os.path.exists(cancelled) and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.05)
    assert not os.path.exists(cancelled) and win._meter_reader.path in win._meter_files
    # fechar a janela (audio_stop_and_clean) apaga o que foi decodificado
    current = win._meter_reader.path
    win._meter_close()
    assert not os.path.exists(current) and win._meter_reader is None
    win._meter_source()  # volta a ler o mesmo som (decodifica de novo)
    wait_reader()
    meter_source(win, "", "")
    assert win._meter_files == []
