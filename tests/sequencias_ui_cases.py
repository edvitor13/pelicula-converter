"""Casos da interface das várias sequências (1.7, #57): as abas, a janela de criar, a troca de uma sequência para outra
(vazia, só o arquivo, montagem, fps e tamanho diferentes, nos dois modos), o estado de cada aba, desfazer entre abas,
"alterações não salvas", reabrir o projeto, a Mídia, a exportação em fila e o terminal.

Rodados por test_sequencias_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QShortcut  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import audiomix, media, project, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.sequence_dialog import SequenceDialog  # noqa: E402
from pelicula.ui.sequence_tabs import SequenceTabs, TabInfo  # noqa: E402

LMB = Qt.MouseButton.LeftButton


def pump(cond=None, timeout: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.time() - t0 > 0.15:
            return True
        time.sleep(0.01)
    return False


def tone_video(folder: Path, name: str, size: str, fps: int, freq: int, secs: int = 2) -> str:
    """Vídeo curto com som, para as trocas de aba lerem de verdade."""
    try:
        ff = media.ffmpeg()
    except RuntimeError:
        pytest.skip("ffmpeg indisponível")
    path = str(folder / name)
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={secs}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={secs}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                   check=True, timeout=60)
    return path


# ------------------------------------------------------------------ as abas sozinhas
def click(w, pos, button=LMB, double=False):
    t = QEvent.Type.MouseButtonDblClick if double else QEvent.Type.MouseButtonPress
    p = QPointF(pos)
    ev = QMouseEvent(t, p, w.mapToGlobal(p), button, button, Qt.KeyboardModifier.NoModifier)
    if double:
        w.mouseDoubleClickEvent(ev)
    else:
        w.mousePressEvent(ev)
        up = QMouseEvent(QEvent.Type.MouseButtonRelease, p, w.mapToGlobal(p), button, Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        w.mouseReleaseEvent(up)


def tabs_widget(names=("Sequência 1", "Sequência 2", "Sequência 3"), active=1, width=900) -> SequenceTabs:
    t = SequenceTabs()
    t.resize(width, 36)
    t.set_tabs([TabInfo(f"id{i}", n, f"{n}\n1920 × 1080") for i, n in enumerate(names)], f"id{active}")
    t.show()
    APP.processEvents()
    return t


def test_tabs_click_opens_and_plus_asks_for_a_new_sequence():
    t = tabs_widget()
    seen, added = [], []
    t.activated.connect(seen.append)
    t.addRequested.connect(lambda: added.append(1))
    try:
        click(t, t.tab_rect(0).center())
        assert seen == ["id0"]
        click(t, t.tab_rect(1).center())     # a aberta não pede de novo
        assert seen == ["id0"]
        click(t, t.tab_rect(len(t.tabs)).center())
        assert added == [1] and t.index_of("id2") == 2
    finally:
        t.close()


def test_tabs_are_there_with_one_sequence_and_a_plus_at_the_end():
    t = tabs_widget(("Sequência 1",), 0)
    try:
        assert len(t.tabs) == 1 and t.height() >= 30
        plus = t.tab_rect(1)
        assert plus.left() > t.tab_rect(0).right() and plus.right() <= t.width()
        added = []
        t.addRequested.connect(lambda: added.append(1))
        click(t, plus.center())
        assert added == [1]
    finally:
        t.close()


def test_tabs_double_click_renames_in_place_and_escape_cancels():
    t = tabs_widget()
    got = []
    t.renamed.connect(lambda sid, name: got.append((sid, name)))
    try:
        click(t, t.tab_rect(2).center(), double=True)
        APP.processEvents()
        assert t._editor is not None and t._editor.text() == "Sequência 3"
        t._editor.setText("Créditos")
        t._editor.editingFinished.emit()
        APP.processEvents()
        assert got == [("id2", "Créditos")] and t._editor is None
        click(t, t.tab_rect(0).center(), double=True)
        APP.processEvents()
        t._editor.setText("Outro")
        QTest.keyClick(t._editor, Qt.Key.Key_Escape)
        APP.processEvents()
        assert t._editor is None and got == [("id2", "Créditos")]    # Esc desiste
        t.rename("id1")
        t._editor.setText("   ")      # nome vazio não renomeia
        t._editor.editingFinished.emit()
        t.rename("id1")
        t._editor.editingFinished.emit()   # nome igual também não
        assert got == [("id2", "Créditos")]
    finally:
        t.close()


def test_tabs_long_names_are_elided_with_the_full_name_in_the_tip():
    long = "Entrevista com a diretora de fotografia na locação externa — corte final"
    t = tabs_widget(("Curta", long), 0, width=500)
    try:
        r = t.tab_rect(1)
        assert r.width() <= 190 and t.tabs[1].tip.startswith(long)
        img = t.grab()
        assert not img.isNull()
        t.setMouseTracking(True)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(r.center()), t.mapToGlobal(QPointF(r.center())),
                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        t.mouseMoveEvent(move)
        assert t.toolTip().startswith(long) and "1920 × 1080" in t.toolTip()
    finally:
        t.close()


def test_tabs_overflow_scrolls_and_keeps_the_open_tab_visible():
    names = [f"Sequência {n}" for n in range(1, 21)]
    t = tabs_widget(names, 0, width=700)
    try:
        assert t._content_w() > t._avail() and t.tab_rect(0).left() >= 0
        t.set_tabs(t.tabs, "id19")           # abrir a última leva a fileira até ela
        r = t.tab_rect(19)
        assert r.right() <= t.width() - 30 and r.left() >= 0
        plus = t._plus_rect()
        assert plus.right() <= t.width()    # o "+" fica sempre à vista
    finally:
        t.close()


def drag(w, a, b):
    pa, pb = QPointF(a), QPointF(b)
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pa, w.mapToGlobal(pa), LMB, LMB,
                                  Qt.KeyboardModifier.NoModifier))
    for k in range(1, 6):
        p = QPointF(pa.x() + (pb.x() - pa.x()) * k / 5, pa.y())
        w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, p, w.mapToGlobal(p), Qt.MouseButton.NoButton, LMB,
                                     Qt.KeyboardModifier.NoModifier))
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, pb, w.mapToGlobal(pb), LMB,
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_tabs_drag_moves_a_tab_and_a_short_move_is_just_a_click():
    t = tabs_widget()
    moved, seen = [], []
    t.moved.connect(lambda sid, to: moved.append((sid, to)))
    t.activated.connect(seen.append)
    try:
        drag(t, t.tab_rect(0).center(), t.tab_rect(2).center())
        assert moved == [("id0", 2)]
        moved.clear()
        drag(t, t.tab_rect(2).center(), t.tab_rect(0).center())
        assert moved == [("id2", 0)]
        moved.clear()
        c = t.tab_rect(1).center()
        drag(t, c, QPointF(c.x() + 2, c.y()))      # quase parado: clique
        assert moved == []
    finally:
        t.close()


def test_tabs_context_menu_has_the_four_actions_and_delete_is_off_for_the_last_one():
    t = tabs_widget(("Sequência 1",), 0)
    try:
        acts = [(x.text(), x.isEnabled()) for x in t.menu_for("id0").actions() if x.text()]
        assert [n for n, _e in acts] == ["Renomear", "Duplicar", "Configurar…", "Apagar"]
        assert dict(acts)["Apagar"] is False
        t.set_tabs([TabInfo("a", "A"), TabInfo("b", "B")], "a")
        assert dict((x.text(), x.isEnabled()) for x in t.menu_for("a").actions())["Apagar"] is True
        got = []
        t.deleteRequested.connect(got.append)
        [x for x in t.menu_for("b").actions() if x.text() == "Apagar"][0].trigger()
        assert got == ["b"]
    finally:
        t.close()


# ------------------------------------------------------------------ a janela de criar
def base_seq(w=1280, h=720, fps="25/1") -> tl.Sequence:
    return tl.Sequence(w, h, fps, background=(0.2, 0.1, 0.0), transparent=True, magnetic=True, micro_fade=True)


def test_dialog_creating_has_a_name_and_starts_from_the_given_settings():
    d = SequenceDialog(None, base_seq(), name="Sequência 2")
    try:
        assert d.creating and d.windowTitle() == "Nova sequência" and d.name_edit.text() == "Sequência 2"
        assert (d.w.value(), d.h.value(), d.fps.currentData()) == (1280, 720, "25/1")
        assert d.transparent() and d.magnetic() and d.micro_fade() and d.name_value() == "Sequência 2"
        assert d.values()[:3] == (1280, 720, "25/1")
        assert [d.res.itemData(i) for i in range(d.res.count())].count("primeiro") == 0   # sem clipes para citar
        ok = d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        assert any(b.text() == "Criar" for b in ok)
    finally:
        d.close()


def test_dialog_from_a_video_offers_the_video_size_and_its_fps():
    base = tl.Sequence.for_source(tl.Source("C:/v/a.mp4", 1080, 1920, 29.97, "30000/1001", 60, 2.0), with_media=False)
    d = SequenceDialog(None, base, name="Sequência 2", reference=(1080, 1920))
    try:
        assert (d.w.value(), d.h.value(), d.fps.currentData()) == (1080, 1920, "30000/1001")
        assert d.res.currentText().startswith("Vertical") or d.res.currentData() in ("vertical", "primeiro")
        d.fps.setCurrentIndex(d.fps.findData("24/1"))                # dá para mudar antes de confirmar
        d.res.setCurrentIndex(d.res.findData("1080"))
        assert d.values()[:3] == (1920, 1080, "24/1")
    finally:
        d.close()
    odd = tl.Source("C:/v/b.mp4", 1000, 600, 24.0, "24/1", 24, 1.0)
    d = SequenceDialog(None, tl.Sequence.for_source(odd, with_media=False), name="X", reference=(1000, 600))
    try:
        assert d.res.currentData() == "primeiro" and "1000 × 600" in d.res.currentText() and "vídeo" in d.res.currentText()
    finally:
        d.close()


def test_dialog_refuses_a_name_that_another_sequence_already_has(monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[-1]))
    d = SequenceDialog(None, base_seq(), name="Sequência 3", taken=["Sequência 1", "sequência 2"])
    accepted = []
    d.accepted.connect(lambda: accepted.append(1))
    try:
        d.name_edit.setText("SEQUÊNCIA 2")
        d._ok()
        assert warned and not accepted
        d.name_edit.setText("Cena nova")
        d._ok()
        assert accepted == [1] and d.name_value() == "Cena nova"
    finally:
        d.close()


def test_dialog_to_configure_an_existing_sequence_is_as_before():
    seq = tl.Sequence(640, 360, "24/1")
    seq.insert_media(tl.Source("C:/v/a.mp4", 640, 360, 24.0, "24/1", 24, 1.0), 0)
    d = SequenceDialog(None, seq)
    try:
        assert not d.creating and d.windowTitle() == "Configurar a sequência" and not hasattr(d, "name_edit")
        assert d.name_value() == "" and "primeiro" in [d.res.itemData(i) for i in range(d.res.count())]
    finally:
        d.close()


# ------------------------------------------------------------------ a janela
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


def color_seq(w=320, h=180, fps="24/1", color="#336699") -> tl.Sequence:
    """Montagem só com clipes sem arquivo: abre sem perguntar por arquivos que faltam."""
    seq = tl.Sequence(w, h, fps, micro_fade=True)
    seq.insert_media(tl.Source.virtual("cor", w, h, fps, data={"cor": color}))
    return seq


def fresh(win, mode="edicao", seq=None):
    """Projeto novo (ou com a montagem dada) no modo pedido."""
    win.new_project()
    win.set_mode(mode)
    if seq is not None:
        win._loading = True
        win.model.set_sequence(seq)
        win._loading = False
        win.seqs_ui.reset()
        win._refresh_source(reset=True)
    win._saved_state = win._state()
    pump()


def accepting(monkeypatch, **fields):
    """A janela de criar aceita na hora (com os campos mudados); devolve a lista das janelas vistas."""
    seen = []

    def fake_exec(self):
        seen.append(self)
        if "name" in fields:
            self.name_edit.setText(fields["name"])
        if "fps" in fields:
            self.fps.setCurrentIndex(self.fps.findData(fields["fps"]))
        if "size" in fields:
            self.res.setCurrentIndex(self.res.findData("custom"))
            self.w.setValue(fields["size"][0])
            self.h.setValue(fields["size"][1])
        return 1

    monkeypatch.setattr(SequenceDialog, "exec", fake_exec)
    return seen


def names(win) -> list[str]:
    return [t.name for t in win.seqs_ui.tabs.tabs]


def test_tabs_show_in_edit_mode_even_with_one_sequence_and_not_in_film_mode(win):
    fresh(win)
    tabs = win.seqs_ui.tabs
    assert not win.tl_editor.isHidden() and tabs.isVisible() and names(win) == ["Sequência 1"]
    assert tabs.geometry().top() <= 1 and tabs.geometry().bottom() < win.tl_editor.canvas.geometry().top()
    win.set_mode("pelicula")
    assert not tabs.isVisible()
    win.set_mode("edicao")
    assert tabs.isVisible()


def test_plus_creates_a_sequence_with_the_settings_of_the_open_one(win, monkeypatch):
    fresh(win, seq=color_seq(640, 360, "30/1"))
    seen = accepting(monkeypatch)
    sid = win.seqs_ui.new_sequence()
    assert sid and names(win) == ["Sequência 1", "Sequência 2"] and win.model.seq.id == sid
    d = seen[0]
    assert d.name_edit.text() == "Sequência 2" and (d.w.value(), d.h.value(), d.fps.currentData()) == (640, 360, "30/1")
    assert (win.model.seq.width, win.model.seq.height, win.model.seq.fps_str) == (640, 360, "30/1")
    assert not win.model.seq.clips and win.info is None and win.src_seq is None
    assert win.seqs_ui.tabs.active == sid and win.st_file.text()


def test_plus_with_a_cancelled_dialog_changes_nothing(win, monkeypatch):
    fresh(win, seq=color_seq())
    monkeypatch.setattr(SequenceDialog, "exec", lambda self: 0)
    n = len(win.model.history._states)
    assert win.seqs_ui.new_sequence() == ""
    assert names(win) == ["Sequência 1"] and len(win.model.history._states) == n and win.info is not None
    assert not win.is_dirty()


def test_new_sequence_from_a_video_starts_from_the_video_and_places_it(win, monkeypatch, tmp_path):
    v = tone_video(tmp_path, "v.mp4", "192x108", 30, 880)
    fresh(win, seq=color_seq(320, 180, "24/1"))
    src = win.adopt_source(media_source(v))
    seen = accepting(monkeypatch)
    sid = win.seqs_ui.new_sequence(src)
    d = seen[0]
    assert (d.w.value(), d.h.value(), d.fps.currentData()) == (192, 108, "30/1")
    s = win.model.seq
    assert s.id == sid and [c.src for c in s.clips if c.kind == tl.VIDEO] == [v] and (s.width, s.height) == (192, 108)
    assert win.info is not None and win.src_seq is not None and abs(win.info.fps - 30) < 1e-6


def media_source(path) -> tl.Source:
    return tl.Source.from_info(media.probe(path))


def test_the_video_choice_can_be_changed_before_confirming(win, monkeypatch, tmp_path):
    v = tone_video(tmp_path, "v2.mp4", "192x108", 30, 440)
    fresh(win, seq=color_seq())
    src = win.adopt_source(media_source(v))
    accepting(monkeypatch, fps="24/1", size=(640, 360), name="Entrevista")
    win.seqs_ui.new_sequence(src)
    s = win.model.seq
    assert (s.width, s.height, s.fps_str, s.name) == (640, 360, "24/1", "Entrevista")
    assert names(win) == ["Sequência 1", "Entrevista"]


def test_switching_between_empty_montage_and_other_fps_and_size_works_in_both_modes(win, monkeypatch, tmp_path):
    v1 = tone_video(tmp_path, "um.mp4", "160x90", 24, 440)
    v2 = tone_video(tmp_path, "dois.mp4", "192x108", 30, 880)
    fresh(win)
    win.import_paths([v1])
    pump(lambda: win.cur is not None)
    a = win.model.seq.id or win.model.seq.ensure_set().items[0].id
    accepting(monkeypatch, fps="30/1", size=(192, 108))
    b = win.seqs_ui.new_sequence()
    assert win.info is None and win.cur is None and win._audio_src == ("", "") and not win.src_seq
    for mode in ("edicao", "pelicula", "edicao"):       # a vazia aberta, em cada modo
        win.set_mode(mode)
        pump()
        assert win.info is None and win.src_seq is None and win._audio_src == ("", "")
        assert not win.btn_play.isEnabled() and win.edit_scopes is not None
    win.import_paths([v2])                              # a vazia ganha um vídeo de 30 quadros/s
    pump(lambda: win.cur is not None)
    assert abs(win.info.fps - 30) < 1e-6 and (win.info.width, win.info.height) == (192, 108)
    win.seqs_ui.activate(a)
    pump(lambda: win.cur is not None)
    assert abs(win.info.fps - 24) < 1e-6 and (win.info.width, win.info.height) == (160, 90) and win.src_seq is not None
    assert pump(lambda: win._audio_src[0] == "seq" and win._audio_src[1] == win._mix_path and win._mix_path)
    win.seqs_ui.activate(b)
    pump(lambda: win.cur is not None)
    assert abs(win.info.fps - 30) < 1e-6 and pump(lambda: win._audio_src[0] == "seq" and bool(win._audio_src[1]))
    win.set_mode("pelicula")
    pump()
    assert win.src_seq is not None and win.info is not None       # sem arquivo aberto: a montagem é a entrada do look
    win.seqs_ui.activate(a)
    pump(lambda: win.cur is not None)
    assert abs(win.info.fps - 24) < 1e-6 and win.cur is not None


def test_film_mode_reads_the_file_directly_for_a_trivial_sequence_and_nothing_for_an_empty_one(win, monkeypatch, tmp_path):
    v = tone_video(tmp_path, "arq.mp4", "160x90", 24, 440)
    win.new_project()
    win.load_media(v)
    pump(lambda: win.cur is not None)
    assert win.mode == "pelicula" and win.src_seq is None and win._audio_src == ("file", v)
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()                  # leva ao modo Edição, com a vazia aberta
    win.set_mode("pelicula")
    pump()
    assert win.info is None and win.src_seq is None and win._audio_src == ("", "") and win.cur is None
    first = win.model.sequences()[0].id
    win.seqs_ui.activate(first)
    pump(lambda: win.cur is not None)
    assert win.src_seq is None and win.info.path == v and win._audio_src == ("file", v)   # trivial: o arquivo direto
    win.seqs_ui.activate(win.model.sequences()[1].id)
    pump()
    assert win.info is None and win._audio_src == ("", "")


def test_every_tab_keeps_its_playhead_in_out_and_zoom(win, monkeypatch):
    fresh(win, seq=color_seq())
    a = win.model.seq
    win.model.set_clip_values(a.clips[0].id, a.clips[0].values)
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#aa3322"}), at=100)
    pump(lambda: win.cur is not None)
    accepting(monkeypatch)
    cv = win.tl_editor.canvas
    win.request_frame(30)
    pump(lambda: win.cur_frame == 30)
    win.mark_in()
    win.request_frame(60)
    pump(lambda: win.cur_frame == 60)
    win.mark_out()
    cv.ppf, cv.scroll = 2.5, 12.0
    b = win.seqs_ui.new_sequence()
    first = win.model.sequences()[0].id
    assert (win.frame_idx, win.inp, win.outp) == (0, None, None)      # a aba nova começa no quadro 0
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#115577"}), at=0)
    pump(lambda: win.cur is not None)
    win.request_frame(10)
    pump(lambda: win.cur_frame == 10)
    win.mark_in()
    cv.ppf, cv.scroll = 6.0, 3.0
    win.seqs_ui.activate(first)
    pump(lambda: win.cur is not None)
    assert (win.frame_idx, win.inp, win.outp) == (60, 30, 60) and cv.ppf == 2.5 and cv.scroll == 12.0
    assert win.timeline.inp == 30 and win.timeline.out == 60 and cv.playhead == 60
    win.seqs_ui.activate(b)
    pump(lambda: win.cur is not None)
    assert (win.frame_idx, win.inp, win.outp) == (10, 10, None) and cv.ppf == 6.0 and cv.scroll == 3.0


def test_undo_in_another_tab_goes_back_to_that_tab_with_its_state(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    first, second = (s.id for s in win.model.sequences())
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#115577"}), at=0)
    pump(lambda: win.cur is not None)
    win.request_frame(7)
    pump(lambda: win.cur_frame == 7)
    win.seqs_ui.activate(first)
    pump(lambda: win.cur is not None)
    assert win.model.seq.id == first
    win.undo()                                            # a última edição foi na segunda aba
    pump()
    assert win.model.seq.id == second and not win.model.seq.clips and win.info is None
    assert win.seqs_ui.tabs.active == second
    win.redo()
    pump(lambda: win.cur is not None)
    assert win.model.seq.id == second and win.model.seq.clips and win.frame_idx == 7   # volta com o quadro dela
    win.undo()
    win.undo()                                            # desfaz também a criação
    pump()
    assert names(win) == ["Sequência 1"] and win.info is not None


def test_switching_tabs_is_not_a_change_but_a_rename_is(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    win._saved_state = win._state()
    win._update_title()
    assert not win.is_dirty()
    for sid in (win.model.sequences()[0].id, win.model.sequences()[1].id):
        win.seqs_ui.activate(sid)
        pump()
        assert not win.is_dirty() and "•" not in win.windowTitle()
    win.seqs_ui.rename(win.model.seq.id, "Final")
    pump()
    assert win.is_dirty() and names(win)[1] == "Final"
    win.model.undo()
    pump()
    assert not win.is_dirty()


def test_a_rename_does_not_reload_the_preview(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    win.seqs_ui.activate(win.model.sequences()[0].id)
    pump(lambda: win.cur is not None)
    calls = []
    real = win._refresh_source
    win._refresh_source = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        win.seqs_ui.rename(win.model.sequences()[1].id, "Abertura")
        win.model.undo()
        win.model.redo()
        pump()
        assert calls == [] and names(win)[1] == "Abertura"
    finally:
        win._refresh_source = real


def test_an_empty_open_sequence_can_still_be_saved_and_reopened(win, monkeypatch, tmp_path):
    fresh(win, seq=color_seq(320, 180, "24/1"))
    accepting(monkeypatch, name="Vazia", fps="25/1")
    win.seqs_ui.new_sequence()
    assert win.info is None and win._has_project() and win.is_dirty()
    path = str(tmp_path / "duas.plc")
    assert win._write_project(path)
    saved = project.load(path)
    assert saved.to_json()["formato"] == 5
    win.new_project()
    assert names(win) == ["Sequência 1"] and win.info is None
    win.open_project(path)
    pump(lambda: win.cur is not None or True)
    assert names(win) == ["Sequência 1", "Vazia"] and win.model.seq.display_name == "Vazia"    # a aba aberta ao salvar
    assert win.info is None and not win.is_dirty()
    win.seqs_ui.activate(win.model.sequences()[0].id)
    pump(lambda: win.cur is not None)
    assert win.info is not None and not win.is_dirty()


def test_opening_a_project_with_a_broken_sequence_warns_once(win, monkeypatch, tmp_path):
    a = color_seq()
    group = a.ensure_set()
    group.create(320, 180, "24/1")
    c = group.create(320, 180, "24/1")
    a.insert_media(a.sources[f"sequencia:{c.id}"], 200)
    raw = a.to_json()
    raw["sequencias"] = [x for x in raw["sequencias"] if x["id"] != c.id]       # arquivo mexido: a usa uma que sumiu
    path = str(tmp_path / "ciclo.plc")
    project.save(project.Project(media_path="", sequence=raw, mode="edicao"), path)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **k: warned.append(args[-1]))
    win.open_project(path)
    pump()
    assert len(warned) == 1 and "não pode ser aberta" in warned[0]
    assert names(win) == ["Sequência 1", "Sequência 2"]
    win.seqs_ui.problems()                  # só uma vez por abertura
    assert len(warned) == 1


def test_delete_asks_says_what_leaves_and_is_one_undo_step(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    inner = win.seqs_ui.new_sequence()
    first = win.model.sequences()[0].id
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#115577"}), at=0)
    win.seqs_ui.activate(first)
    pump()
    made = win.model.seq.insert_media(win.model.seq.sources[f"sequencia:{inner}"], 100)   # um clipe da segunda na primeira
    win.model.commit()
    asked = []
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda s, users: asked.append((s.display_name, [
        (u.display_name, n) for u, n in users])) or False)
    assert win.seqs_ui.delete(inner) == -1 and names(win) == ["Sequência 1", "Sequência 2"]    # "Cancelar"
    assert asked == [("Sequência 2", [("Sequência 1", len(made))])]
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda s, users: True)
    n = len(win.model.history._states)
    assert win.seqs_ui.delete(inner) == len(made)
    pump()
    assert names(win) == ["Sequência 1"] and len(win.model.history._states) == n + 1
    assert not any(c.src.startswith("sequencia:") for c in win.model.seq.clips)
    win.undo()
    pump()
    assert names(win) == ["Sequência 1", "Sequência 2"] and len(win.model.sequence_users(inner)) == 1


def test_the_last_sequence_cannot_be_deleted(win, monkeypatch):
    fresh(win, seq=color_seq())
    asked = []
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda s, users: asked.append(1) or True)
    assert win.seqs_ui.delete() == -1 and asked == [] and names(win) == ["Sequência 1"]


def test_confirmation_text_names_the_sequences_and_the_clip_counts(win, monkeypatch):
    fresh(win, seq=color_seq())
    s2 = win.model.seq.ensure_set().create(320, 180, "24/1", name="Abertura")
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append((self.text(), self.informativeText())) or 0)
    win.seqs_ui.confirm_delete(s2, [(win.model.seq, 3)])
    text, info = shown[0]
    assert "Abertura" in text and "Sequência 1: 3 clipe(s)" in info and "Ctrl+Z" in info
    win.seqs_ui.confirm_delete(s2, [])
    assert "Ctrl+Z" in shown[1][1] and "clipe(s)" not in shown[1][1]


def test_ctrl_tab_cycles_through_the_tabs_only_in_edit_mode(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    win.seqs_ui.new_sequence()
    ids = [s.id for s in win.model.sequences()]
    nxt = [s for s in win.findChildren(QShortcut) if s.key().toString() == "Ctrl+Tab"]
    prev = [s for s in win.findChildren(QShortcut) if s.key().toString() == "Ctrl+Shift+Tab"]
    assert len(nxt) == 1 and len(prev) == 1
    nxt[0].activated.emit()
    pump()
    assert win.model.seq.id == ids[0]                  # da última volta para a primeira
    nxt[0].activated.emit()
    prev[0].activated.emit()
    pump()
    assert win.model.seq.id == ids[0]
    prev[0].activated.emit()
    pump()
    assert win.model.seq.id == ids[2]
    win.set_mode("pelicula")
    nxt[0].activated.emit()
    pump()
    assert win.model.seq.id == ids[2]


def test_duplicate_and_settings_from_the_tab_menu(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    first = win.model.sequences()[0].id
    dup = win.seqs_ui.duplicate(first)
    pump()
    assert names(win) == ["Sequência 1", "Sequência 1 (cópia)", "Sequência 2"] and win.model.seq.id == dup
    opened = []
    monkeypatch.setattr(win, "sequence_settings", lambda: opened.append(win.model.seq.id))
    win.seqs_ui.settings(first)
    assert opened == [first] and win.model.seq.id == first


def test_moving_a_tab_reorders_without_reloading_and_keeps_the_open_one(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    pump()
    ids = [s.id for s in win.model.sequences()]
    open_id = win.model.seq.id
    win.seqs_ui.move(ids[1], 0)
    pump()
    assert [s.id for s in win.model.sequences()] == [ids[1], ids[0]] and win.model.seq.id == open_id
    assert [t.id for t in win.seqs_ui.tabs.tabs] == [ids[1], ids[0]]
    win.model.undo()
    pump()
    assert [t.id for t in win.seqs_ui.tabs.tabs] == ids
