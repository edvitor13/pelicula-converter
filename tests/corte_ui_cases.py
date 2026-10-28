"""Casos da interface das ferramentas de corte (1.5): inserir × sobrescrever, faixa principal magnética,
Q/W, cortes J/L e J/K/L.

Rodados por test_corte_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt
precisam de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent, QShortcut  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import timeline as tl  # noqa: E402
from pelicula.timeline import AUDIO, VIDEO  # noqa: E402
from pelicula.ui import icons  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import MediaBin  # noqa: E402
from pelicula.ui.sequence_dialog import SequenceDialog  # noqa: E402
from pelicula.ui.timeline_view import MIME_SOURCE, TimelineEditor  # noqa: E402

LMB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier


def src(path, frames=100, audio=True) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=audio)


def model_with(*sources) -> TimelineModel:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    for s in sources:
        seq.insert_media(s)
    m.set_sequence(seq)
    return m


def abc(frames=100) -> TimelineModel:
    return model_with(src("A", frames), src("B", frames), src("C", frames))


def handles() -> TimelineModel:
    """A, B, C usando o meio de arquivos de 200 quadros (sobra antes e depois de cada clipe)."""
    m = abc(200)
    seq = m.seq
    for n in "ABC":
        v = named(seq, n)[0]
        seq.trim_start(v.id, v.start + 50)
        seq.trim_end(v.id, v.start + 100)
    seq.close_gaps(VIDEO, 0)
    seq.close_gaps(AUDIO, 0)
    m.set_sequence(seq)
    return m


def named(seq, name, kind=VIDEO):
    return sorted((c for c in seq.clips if c.name == name and c.kind == kind), key=lambda c: c.start)


def spans(clips):
    return [(c.start, c.end) for c in clips]


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


def row_y(c, kind, idx=0) -> float:
    return next(y + h / 2 for k, i, y, h in c.rows() if (k, i) == (kind, idx))


def drag(widget, a: QPoint, b: QPoint, release_mods=NOMOD) -> None:
    QTest.mousePress(widget, LMB, NOMOD, a)
    QTest.mouseMove(widget, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(widget, b)
    QTest.mouseRelease(widget, LMB, release_mods, b)


# ------------------------------------------------------------------ modelo (desfazer/refazer)
def test_model_insert_and_overwrite_with_undo():
    m = abc()
    m.insert_media(src("X", 50), at=150, insert=True)
    assert spans(named(m.seq, "C")) == [(250, 350)] and spans(named(m.seq, "X")) == [(150, 200)]
    m.undo()
    assert spans(named(m.seq, "C")) == [(200, 300)] and named(m.seq, "X") == []
    m.redo()
    assert spans(named(m.seq, "C")) == [(250, 350)]
    m.undo()
    m.insert_media(src("X", 50), at=150)
    assert spans(named(m.seq, "C")) == [(200, 300)] and spans(named(m.seq, "B")) == [(100, 150)]


def test_model_q_w_trim_to_the_playhead_and_undo():
    m = abc()
    assert m.trim_to_playhead(130, "start") == 30
    assert spans(named(m.seq, "B")) == spans(named(m.seq, "B", AUDIO)) == [(100, 170)]
    assert spans(named(m.seq, "C")) == [(170, 270)]
    m.undo()
    assert spans(named(m.seq, "B")) == [(100, 200)]
    assert m.trim_to_playhead(130, "end") == 70
    assert spans(named(m.seq, "C", AUDIO)) == [(130, 230)]
    assert m.trim_to_playhead(100, "end") == 0  # num corte não há o que aparar
    m.seq.track(VIDEO, 0).locked = True
    m.seq.track(AUDIO, 0).locked = True
    assert m.trim_to_playhead(50, "start") == 0  # faixas travadas


def test_model_q_w_prefer_the_selected_track():
    m = abc()
    m.insert_media(tl.Source("T.png", 100, 100, is_image=True), at=110, vtrack=1)
    t = named(m.seq, "T.png")[0]
    m.select([named(m.seq, "B", AUDIO)[0].id])
    assert m.trim_to_playhead(150, "end") == 50  # o selecionado manda: apara B, não o título por cima
    assert spans(named(m.seq, "B")) == [(100, 150)] and t.end == 230
    m.select([])
    assert m.trim_to_playhead(150, "end") == 80  # sem seleção: a faixa mais de cima (o título)


def test_model_split_edit_solo_trim_and_undo():
    m = handles()
    b = named(m.seq, "B")[0]
    assert m.split_edit(b.id, True, -24) == -24
    assert spans(named(m.seq, "B", AUDIO)) == [(76, 200)]
    m.undo()
    assert spans(named(m.seq, "B", AUDIO)) == [(100, 200)]
    assert m.split_edit(named(m.seq, "A")[0].id, True, -10) is None  # A não tem nada antes
    m.trim_end(b.id, 180, solo=True)
    assert spans(named(m.seq, "B")) == [(100, 180)] and spans(named(m.seq, "B", AUDIO)) == [(100, 200)]
    m.undo()
    m.trim_end(b.id, 180)
    assert spans(named(m.seq, "B")) == spans(named(m.seq, "B", AUDIO)) == [(100, 180)]


def test_model_magnetic_setting_closes_gaps_and_undoes():
    m = abc()
    kinds = []
    m.changed.connect(kinds.append)
    m.delete_clips([named(m.seq, "B")[0].id])
    assert spans(named(m.seq, "C")) == [(200, 300)]
    seq = m.seq
    m.set_settings(seq.width, seq.height, seq.fps_str, magnetic=True)
    assert m.seq.magnetic and kinds[-1] == "settings"
    assert spans(named(m.seq, "C")) == spans(named(m.seq, "C", AUDIO)) == [(100, 200)]
    m.delete_clips([named(m.seq, "A")[0].id], ripple=False)  # V1 magnética: fecha mesmo sem "fechar o espaço"
    assert spans(named(m.seq, "C")) == [(0, 100)]
    m.undo()
    m.undo()
    assert not m.seq.magnetic and spans(named(m.seq, "C")) == [(200, 300)]
    m.set_settings(seq.width, seq.height, seq.fps_str)  # sem dizer nada, fica como está
    assert not m.seq.magnetic


def test_model_magnetic_move_and_trim():
    m = handles()
    seq = m.seq
    m.set_settings(seq.width, seq.height, seq.fps_str, magnetic=True)
    a = named(m.seq, "A")[0]
    m.move_clip(a.id, 300)  # para depois do fim: a V1 se fecha
    assert [c.name for c in m.seq.clips_on(VIDEO, 0)] == ["B", "C", "A"]
    assert spans(m.seq.clips_on(VIDEO, 0)) == [(0, 100), (100, 200), (200, 300)]
    b = named(m.seq, "B")[0]
    m.trim_end(b.id, 130)  # alongar empurra (sem cobrir C)
    assert spans(named(m.seq, "B")) == [(0, 130)] and spans(named(m.seq, "C")) == [(130, 230)]
    m.undo()
    assert spans(named(m.seq, "B")) == [(0, 100)]


# ------------------------------------------------------------------ linha do tempo
def test_insert_toggle_and_ctrl_move():
    m = abc()
    ed = editor(m)
    c = ed.canvas
    assert not c.insert_mode and not ed.btn_insert.isChecked()
    assert "Ctrl" in ed.btn_insert.toolTip()
    y = row_y(c, VIDEO)
    clip_c = named(m.seq, "C")[0]
    # Ctrl ao soltar: inverte o modo (sobrescrever → inserir)
    drag(c, pt(c.frame_to_x(250), y), pt(c.frame_to_x(100), y), CTRL)
    assert spans(named(m.seq, "C")) == [(50, 150)]
    assert spans(named(m.seq, "A")) == [(0, 50), (150, 200)] and spans(named(m.seq, "B")) == [(200, 300)]
    m.undo()
    assert spans(named(m.seq, "C")) == [(200, 300)] and clip_c.id in {x.id for x in m.seq.clips}
    ed.btn_insert.click()
    assert c.insert_mode
    drag(c, pt(c.frame_to_x(250), y), pt(c.frame_to_x(100), y), CTRL)  # no modo inserir, Ctrl sobrescreve
    assert spans(named(m.seq, "A")) == [(0, 50)] and spans(named(m.seq, "B")) == [(150, 200)]
    m.undo()
    c.set_insert_mode(False)
    assert not ed.btn_insert.isChecked()


def test_drop_in_insert_mode_emits_files_inserted():
    m = abc()
    ed = editor(m)
    c = ed.canvas
    dropped, inserted = [], []
    ed.filesDropped.connect(lambda *a: dropped.append(a))
    ed.filesInserted.connect(lambda *a: inserted.append(a))
    md = QMimeData()
    md.setData(MIME_SOURCE, "C:/v/x.mp4".encode("utf-8"))
    pos = QPointF(c.frame_to_x(150), row_y(c, VIDEO))
    c.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD))
    c.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, CTRL))
    assert dropped == [(["C:/v/x.mp4"], 150, VIDEO, 0)] and inserted == [(["C:/v/x.mp4"], 150, VIDEO, 0)]
    c.set_insert_mode(True)
    c.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD))
    assert len(inserted) == 2 and len(dropped) == 1
    c.dragMoveEvent(QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD))
    assert c._drop is not None and c._drop[3] is True
    assert not c.grab().isNull()  # desenha a marca de inserir


def test_alt_drag_trims_only_one_side():
    m = handles()
    ed = editor(m)
    c = ed.canvas
    b = named(m.seq, "B")[0]
    r = c.clip_rect(b)
    a = pt(r.right() - 2, r.center().y())
    drag(c, a, pt(r.right() - 2 - 40, r.center().y()), ALT)  # 20 quadros a menos só na imagem
    assert spans(named(m.seq, "B")) == [(100, 180)] and spans(named(m.seq, "B", AUDIO)) == [(100, 200)]
    m.undo()
    drag(c, a, pt(r.right() - 2 - 40, r.center().y()))
    assert spans(named(m.seq, "B")) == spans(named(m.seq, "B", AUDIO)) == [(100, 180)]


def test_context_menu_j_and_l_cuts():
    m = handles()
    ed = editor(m)
    c = ed.canvas
    b = named(m.seq, "B")[0]
    r = c.clip_rect(b)
    menu = QMenu()
    acts = c.split_edit_actions(menu, b, r.left() + 5)  # metade da esquerda: o corte A|B
    texts = [a.text() for a in acts]
    assert texts[0].startswith("Corte J") and texts[1].startswith("Corte L") and not acts[2].isEnabled()
    acts[0].trigger()
    assert spans(named(m.seq, "B", AUDIO)) == [(76, 200)]  # 1 s (24 quadros) antes da imagem
    menu = QMenu()
    acts = c.split_edit_actions(menu, b, r.left() + 5)
    assert acts[0].isChecked() and acts[2].isEnabled()
    acts[2].trigger()
    assert spans(named(m.seq, "B", AUDIO)) == [(100, 200)]
    menu = QMenu()
    acts = c.split_edit_actions(menu, b, r.right() - 5)  # metade da direita: o corte B|C
    acts[1].trigger()
    assert spans(named(m.seq, "B", AUDIO)) == [(100, 224)] and spans(named(m.seq, "C", AUDIO)) == [(224, 300)]
    a = named(m.seq, "A")[0]
    assert c.split_edit_actions(QMenu(), a, c.clip_rect(a).left() + 2) != []  # A só tem o corte da direita
    m.seq.unlink(a.id)
    assert c.split_edit_actions(QMenu(), a, c.clip_rect(a).left() + 2) == []


def test_magnetic_v1_header_shows_the_magnet():
    m = abc()
    ed = editor(m)
    before = ed.canvas.grab().toImage()
    seq = m.seq
    m.set_settings(seq.width, seq.height, seq.fps_str, magnetic=True)
    APP.processEvents()
    assert ed.canvas.grab().toImage() != before


def test_sequence_dialog_magnetic_checkbox():
    seq = tl.Sequence(1920, 1080, "24/1")
    dlg = SequenceDialog(None, seq)
    assert not dlg.magnetic() and "V1" in dlg.magnet.toolTip()
    dlg.magnet.setChecked(True)
    assert dlg.magnetic()
    seq.magnetic = True
    assert SequenceDialog(None, seq).magnetic()


def test_media_bin_place_actions():
    b = MediaBin()
    got = []
    b.placeRequested.connect(lambda paths, ins: got.append((paths, ins)))
    for p in ("C:/v/a.mp4", "C:/v/b.mp4"):
        b.add_source(src(p))
    b.place(True)
    assert got == []  # nada escolhido
    b.list.item(1).setSelected(True)
    b.list.item(0).setSelected(True)
    assert b.selected_paths() == ["C:/v/a.mp4", "C:/v/b.mp4"]
    b.place(True)
    b.place(False)
    assert got == [(["C:/v/a.mp4", "C:/v/b.mp4"], True), (["C:/v/a.mp4", "C:/v/b.mp4"], False)]


def test_insert_icon_draws_something():
    img = icons.icon("insert_mode", "#ffffff", 24).pixmap(24, 24).toImage()
    assert sum(img.pixelColor(x, y).alpha() for x in range(24) for y in range(24)) > 0


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


def fake_source(path, frames=96, audio=True):
    return tl.Source(path, 640, 360, 24.0, "24/1", frames, frames / 24.0, has_audio=audio)


def with_sequence(win, *sources, mode="edicao") -> None:
    """Montagem com arquivos que não existem (a prévia falha em silêncio; o tempo e a montagem, não)."""
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


@pytest.fixture
def no_player(win, monkeypatch):
    """A reprodução não decodifica nada (os arquivos não existem): só o estado do J/K/L importa."""
    calls = []
    monkeypatch.setattr(win.player, "start", lambda *a, **k: calls.append(a))
    yield calls
    win.stop_play()


def test_window_jkl_shuttle(win, no_player):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"), fake_source("C:/nao_existe/b.mp4"))
    win.request_frame(48)
    QTest.keyClick(win, Qt.Key.Key_L)
    assert win.playing and win.shuttle_rate() == 1 and not win.shuttle_label.isVisible()
    QTest.keyClick(win, Qt.Key.Key_L)
    assert win.shuttle_rate() == 2 and win.shuttle_label.text() == "2× ▶▶"
    for _ in range(4):
        QTest.keyClick(win, Qt.Key.Key_L)
    assert win.shuttle_rate() == 8  # para em 8×
    QTest.keyClick(win, Qt.Key.Key_K)
    assert not win.playing and win.shuttle_rate() == 0 and win._play_rate == 1
    QTest.keyRelease(win, Qt.Key.Key_K)
    win.request_frame(48)
    QTest.keyClick(win, Qt.Key.Key_J)
    assert win.shuttle_rate() == -1 and win.rev_timer.isActive() and not win.playing
    win._rev_t0 -= 1.0  # um segundo depois…
    win._reverse_tick()
    assert win.frame_idx == 24  # …24 quadros para trás (buscando cada quadro)
    QTest.keyClick(win, Qt.Key.Key_J)
    assert win.shuttle_rate() == -2 and win.shuttle_label.text() == "◀◀ 2×"
    QTest.keyClick(win, Qt.Key.Key_L)  # o outro sentido volta a 1×
    assert win.shuttle_rate() == 1 and win.playing and not win.rev_timer.isActive()
    QTest.keyClick(win, Qt.Key.Key_Space)
    assert win.shuttle_rate() == 0
    QTest.keyClick(win, Qt.Key.Key_J)
    QTest.keyClick(win, Qt.Key.Key_Space)  # Espaço também para o J
    assert win.shuttle_rate() == 0 and not win.rev_timer.isActive()


def test_window_reverse_stops_or_wraps_at_the_start(win, no_player):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"))
    win.loop = False
    win.request_frame(5)
    win.shuttle(-1)
    win._rev_t0 -= 2.0
    win._reverse_tick()
    assert win.frame_idx == 0 and win.shuttle_rate() == 0
    win.loop = True
    win.request_frame(5)
    win.shuttle(-1)
    win._rev_t0 -= 1.0
    win._reverse_tick()
    assert win.frame_idx == win.info.frames - 1 and win.shuttle_rate() == -1  # Repetir: volta do fim
    win.stop_play()


def test_window_k_held_steps_one_frame(win, no_player):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"))
    win.request_frame(30)
    QTest.keyPress(win, Qt.Key.Key_K)
    QTest.keyClick(win, Qt.Key.Key_L)
    assert win.frame_idx == 31 and not win.playing
    QTest.keyClick(win, Qt.Key.Key_J)
    QTest.keyClick(win, Qt.Key.Key_J)
    assert win.frame_idx == 29 and win.shuttle_rate() == 0
    QTest.keyRelease(win, Qt.Key.Key_K)
    assert not win._k_held


def test_window_loop_moved_to_ctrl_l(win, no_player):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"))
    assert "Ctrl+L" in win.btn_loop.toolTip()
    loop = win.btn_loop.isChecked()
    QTest.keyClick(win, Qt.Key.Key_L)
    assert win.btn_loop.isChecked() == loop  # o L agora reproduz
    win.stop_play()
    sc = [s for s in win.findChildren(QShortcut) if s.key().toString() == "Ctrl+L"]
    assert len(sc) == 1
    sc[0].activated.emit()
    assert win.btn_loop.isChecked() != loop
    sc[0].activated.emit()


def test_window_q_w_and_place_at_cursor(win, no_player, monkeypatch):
    with_sequence(win, fake_source("C:/nao_existe/a.mp4"), fake_source("C:/nao_existe/b.mp4"))
    m = win.model
    win.request_frame(120)
    QTest.keyClick(win, Qt.Key.Key_Q)
    b = named(m.seq, "b.mp4")[0]
    assert spans([b]) == [(96, 168)] and win.frame_idx == 96
    m.undo()
    win.request_frame(30)
    QTest.keyClick(win, Qt.Key.Key_W)
    assert spans(named(m.seq, "a.mp4")) == [(0, 30)] and spans(named(m.seq, "b.mp4")) == [(30, 126)]
    m.undo()
    # , / . com o item escolhido na Mídia
    x = fake_source("C:/nao_existe/x.mp4", frames=24)
    monkeypatch.setattr(win, "_probe_source", lambda p: x if p == x.path else None)
    win.bin.add_source(x)
    win.bin.list.clearSelection()
    win.bin.list.item(win.bin.list.count() - 1).setSelected(True)
    win.request_frame(48)
    QTest.keyClick(win, Qt.Key.Key_Comma)
    assert spans(named(m.seq, "x.mp4")) == [(48, 72)] and spans(named(m.seq, "b.mp4")) == [(120, 216)]
    assert win.frame_idx == 72  # o cursor vai para o fim do que entrou
    m.undo()
    win.request_frame(48)
    QTest.keyClick(win, Qt.Key.Key_Period)
    assert spans(named(m.seq, "x.mp4")) == [(48, 72)] and spans(named(m.seq, "b.mp4")) == [(96, 192)]
    assert spans(named(m.seq, "a.mp4")) == [(0, 48), (72, 96)]
    m.undo()
    # no modo Película, Q/W e , / . não mexem na montagem
    win.set_mode("pelicula")
    before = m.seq.to_json()
    for k in (Qt.Key.Key_Q, Qt.Key.Key_W, Qt.Key.Key_Comma, Qt.Key.Key_Period):
        QTest.keyClick(win, k)
    assert m.seq.to_json() == before


def test_window_shortcuts_help_lists_the_new_keys(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    win.show_shortcuts()
    text = shown[0]
    for key in ("J / K / L", "Ctrl+L", "Q / W", ", / .", "Alt"):
        assert key in text, key
    assert "\nL — repetir" not in text
