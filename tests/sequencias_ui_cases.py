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
        for src in seq.sources.values():    # a Mídia mostra os arquivos da montagem, como ao abrir um projeto
            win.adopt_source(src)
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


def test_in_and_out_points_do_not_make_switching_tabs_a_change(win, monkeypatch):
    fresh(win, seq=color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    first, second = win.model.sequences()
    win.seqs_ui.activate(first.id)
    pump()
    win.inp, win.outp = 5, 30
    win._saved_state = win._state()
    for sid in (second.id, first.id, second.id):
        win.seqs_ui.activate(sid)
        pump()
        assert not win.is_dirty()
    win.inp = 3   # marcar na outra aba é mudança
    assert win.is_dirty()
    win.inp = None
    assert not win.is_dirty()
    win.seqs_ui.activate(first.id)
    pump()
    win.outp = 31  # mudar a da aba de volta também
    assert win.is_dirty()


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


# ------------------------------------------------------------------ a Mídia
def media_paths(win) -> list[str]:
    return win.bin.paths()


def seq_paths(win) -> list[str]:
    return [p for p in win.bin.paths() if p.startswith("sequencia:")]


def two_tabs(win, monkeypatch, seq=None):
    fresh(win, seq=seq or color_seq())
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    pump()
    return [s.id for s in win.model.sequences()]


def test_media_lists_sequences_only_with_two_or_more(win, monkeypatch):
    fresh(win, seq=color_seq())
    assert seq_paths(win) == []                        # uma sequência só: a Mídia é a de sempre
    ids = two_tabs(win, monkeypatch)
    assert seq_paths(win) == [f"sequencia:{i}" for i in ids]
    item = win.bin.list.media(f"sequencia:{ids[1]}")
    assert item.kind == "sequencia" and "Sequência 2" in item.text(0) and "sequência" in item.text(0)
    assert not item.icon(0).isNull() and "320 × 180" in item.toolTip(0)
    win.model.remove_sequence(ids[1])
    pump()
    assert seq_paths(win) == []                        # voltou a uma só: some da Mídia
    win.model.undo()
    pump()
    assert len(seq_paths(win)) == 2


def test_media_entry_follows_the_name_and_the_duration(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    item = win.bin.list.media(f"sequencia:{ids[1]}")
    win.seqs_ui.rename(ids[1], "Abertura")
    pump()
    assert "Abertura" in item.text(0)
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#115577"}, seconds=2.0), at=0)
    pump()
    assert "0:02" in win.bin.list.media(f"sequencia:{ids[1]}").text(0)


def test_media_double_click_opens_the_tab(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    win.seqs_ui.activate(ids[0])
    pump()
    item = win.bin.list.media(f"sequencia:{ids[1]}")
    win.bin.pastas._double_click(item, 0)
    pump()
    assert win.model.seq.id == ids[1] and win.seqs_ui.tabs.active == ids[1]
    clip_item = win.bin.list.media(win.model.sequences()[0].clips[0].src)
    n = len(win.model.sequences()[0].clips)
    win.bin.pastas._double_click(clip_item, 0)         # um clipe da Mídia continua entrando na linha do tempo
    pump()
    assert len(win.model.seq.clips) == 1 and len(win.model.sequences()[0].clips) == n


def test_media_sequences_go_into_folders_and_come_back_with_undo(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    key = f"sequencia:{ids[1]}"
    fid = win.model.folder_create("Cenas")
    assert win.model.media_to_folder([key], fid, win._sources)
    pump()
    assert win.model.seq.folders.folder_of(key) == fid
    assert win.bin.list.media(key).parent() is win.bin.list.folder_item(fid)
    win.model.undo()
    pump()
    assert win.model.seq.folders.folder_of(key) == "" and win.bin.list.media(key) is not None
    win.model.redo()
    pump()
    assert win.model.seq.folders.folder_of(key) == fid
    win.model.remove_sequence(ids[1])               # apagar a sequência tira o item da pasta
    pump()
    assert key not in win.model.seq.folders.items and win.bin.list.media(key) is None


def test_media_refuses_to_place_a_sequence_inside_itself_with_a_short_message(win, monkeypatch):
    # (pôr uma sequência dentro de outra funciona desde a frente "aninhar": `tests/aninhar_ui_cases.py`)
    ids = two_tabs(win, monkeypatch)
    win.seqs_ui.activate(ids[0])
    pump()
    n = len(win.model.seq.clips)
    key = f"sequencia:{ids[0]}"
    for call in (lambda: win.add_to_timeline(key), lambda: win.place_at_cursor([key], True),
                 lambda: win.drop_on_timeline([key], 10, tl.VIDEO, 0)):
        call()
        assert len(win.model.seq.clips) == n
    win.statusBar().clearMessage()
    win.add_to_timeline(key)
    assert "nela mesma" in win.statusBar().currentMessage()
    assert len(win.model.seq.clips) == n and win.model.sequence_users(ids[0]) == []


def test_media_trash_on_a_sequence_asks_to_delete_it(win, monkeypatch):
    ids = two_tabs(win, monkeypatch)
    asked = []
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda s, users: asked.append(s.id) or False)
    win._bin_remove(f"sequencia:{ids[1]}")
    assert asked == [ids[1]] and len(win.model.sequences()) == 2
    monkeypatch.setattr(win.seqs_ui, "confirm_delete", lambda s, users: True)
    win._bin_remove(f"sequencia:{ids[1]}")
    pump()
    assert len(win.model.sequences()) == 1


def select_in_bin(win, *paths):
    win.bin.list.clearSelection()
    for p in paths:
        win.bin.list.media(p).setSelected(True)


def menu_texts(win) -> list[str]:
    from PySide6.QtWidgets import QMenu
    m = QMenu()
    win.bin.fill_media_menu(m)
    return [a.text() for a in m.actions() if a.text()]


def test_media_menu_of_a_sequence_and_of_a_video(win, monkeypatch, tmp_path):
    ids = two_tabs(win, monkeypatch)
    key = f"sequencia:{ids[1]}"
    select_in_bin(win, key)
    texts = menu_texts(win)
    assert texts == ["Abrir a sequência", "Adicionar ao fim da linha do tempo", "Inserir no cursor (,)",
                     "Sobrescrever no cursor (.)", "Duplicar", "Apagar a sequência…"]
    src = win.model.sequences()[0].clips[0].src
    select_in_bin(win, src)
    texts = menu_texts(win)
    assert "Nova sequência a partir deste vídeo" in texts and "Inserir no cursor (,)" in texts
    select_in_bin(win, key, src)       # mistura: o menu dos arquivos
    assert "Abrir a sequência" not in menu_texts(win)


def test_new_sequence_from_the_video_menu_uses_the_first_video_of_the_selection(win, monkeypatch, tmp_path):
    v1 = tone_video(tmp_path, "m1.mp4", "192x108", 30, 440)
    fresh(win, seq=color_seq())
    audio = tl.Source("C:/v/musica.wav", 0, 0, 0.0, "24/1", 1, 5.0, has_video=False, has_audio=True)
    win.adopt_source(audio)
    video = win.adopt_source(media_source(v1))
    seen = accepting(monkeypatch)
    select_in_bin(win, audio.path, video.path)
    from PySide6.QtWidgets import QMenu
    m = QMenu()
    win.bin.fill_media_menu(m)
    [a for a in m.actions() if a.text() == "Nova sequência a partir deste vídeo"][0].trigger()
    pump()
    assert (seen[0].w.value(), seen[0].h.value(), seen[0].fps.currentData()) == (192, 108, "30/1")
    assert [c.src for c in win.model.seq.clips if c.kind == tl.VIDEO] == [v1]
    assert win.model.seq.id and len(win.model.sequences()) == 2


def test_new_sequence_from_an_image_keeps_its_size_with_24_fps(win, monkeypatch, tmp_path):
    from pelicula import testimage
    from PySide6.QtGui import QImage
    png = str(tmp_path / "foto.png")
    img = testimage.make(200, 120)
    QImage(img.data, 200, 120, 600, QImage.Format.Format_RGB888).save(png)
    fresh(win, seq=color_seq(320, 180, "30/1"))
    src = win.adopt_source(media_source(png))
    seen = accepting(monkeypatch)
    win.seqs_ui.new_sequence(src)
    assert (seen[0].w.value(), seen[0].h.value(), seen[0].fps.currentData()) == (200, 120, "24/1")
    assert (win.model.seq.width, win.model.seq.height, win.model.seq.fps_str) == (200, 120, "24/1")


# ------------------------------------------------------------------ exportação
def target(tid, name, frames=48, fps=24.0, fps_str="24/1", size=(320, 180), cues=None, chapters=None,
           in_out=None, transparent=False):
    from pelicula.ui.export_dialog import ExportTarget
    seq = tl.Sequence(size[0], size[1], fps_str, name=name, micro_fade=True, transparent=transparent)
    seq.insert_media(tl.Source(f"C:/v/{tid}.mp4", size[0], size[1], fps, fps_str, frames, frames / fps,
                               pix_fmt="yuv420p", has_audio=True), 0)
    from pelicula import sequence as seqmod
    return ExportTarget(tid, name, seqmod.media_info(seq), seq, in_out, chapters or [], None, cues or [], 0)


def export_dialog(targets, active="a", in_out=None, queue_jobs=()):
    from pelicula import params
    from pelicula.ui.export_dialog import ExportDialog
    t = next(x for x in targets if x.id == active)
    d = ExportDialog(None, t.info, params.defaults(), "Look", in_out if in_out is not None else t.in_out, sequence=t.sequence,
                     chapters=t.chapters, subtitles=t.subtitles, subtitle_cues=t.cues, targets=targets,
                     target_id=active, queue_jobs=queue_jobs)
    return d


def test_export_has_no_sequence_row_with_a_lone_sequence_and_keeps_the_name():
    t = target("a", "", frames=24)
    d = export_dialog([t])
    try:
        assert d.seq_group.isHidden() and not d.targets
        assert Path(d.path.text()).stem == "a_edicao_pelicula"          # o nome de sempre: <arquivo>_edicao_pelicula
        assert [j.out_path for j in d.jobs()] == [d.path.text()]
    finally:
        d.done(0)


def test_export_sequence_row_defaults_to_the_open_one_and_lists_every_sequence():
    ts = [target("a", "Sequência 1"), target("b", "Sequência 2", frames=96)]
    d = export_dialog(ts, active="b")
    try:
        assert not d.seq_group.isHidden() and d.seq_box.count() == 2 and d.seq_box.currentData() == "b"
        assert d.title_label.text() == "Sequência 2" and "Sequência 2_pelicula" in d.path.text()
        assert "320 × 180" in d.seq_info.text() and not d.multi_box.isChecked() and d.multi_list.isHidden()
    finally:
        d.done(0)


def test_choosing_another_sequence_rebuilds_what_depends_on_it():
    from pelicula.subtitles import Cue, Subtitles
    subs = Subtitles()
    a = target("a", "Sequência 1", frames=48, in_out=(5, 20), chapters=[(0, "Início"), (24, "Meio")])
    b = target("b", "Sequência 2", frames=120, fps=30.0, fps_str="30/1", size=(640, 360), transparent=True)
    b.subtitles, b.cues = subs, [Cue(0.0, 1.0, "Oi")]
    d = export_dialog([a, b], active="a")
    try:
        assert d.r_sel.isEnabled() and "–" in d.r_sel.text() and d.chapters_box.isVisibleTo(d) is True
        assert "(2)" in d.chapters_box.text() and d.subs_row.isHidden() and not d.alpha_box.isChecked()
        d.r_sel.setChecked(True)
        assert d._range() == (5, 20)
        d._preview_key = ("x",)
        d.seq_box.setCurrentIndex(d.seq_box.findData("b"))
        assert d.info is b.info and d.sequence is b.sequence and d._target_id == "b"
        assert not d.r_sel.isEnabled() and d.r_all.isChecked() and d._range() == (0, -1)       # volta à sequência inteira
        assert d.chapters_box.isHidden() and d.chapter_points() == []
        assert not d.subs_row.isHidden() and d.alpha_box.isChecked()
        assert d.title_label.text() == "Sequência 2" and "640 × 360" in d.seq_info.text()
        assert Path(d.path.text()).stem == "Sequência 2_pelicula"                               # o nome acompanha
        assert d._preview_key is None or d._preview_key != ("x",)
        assert abs(d._duration() - 4.0) < 1e-6                                                  # 120 quadros a 30/s
        d.seq_box.setCurrentIndex(d.seq_box.findData("a"))
        assert d.r_sel.isEnabled() and abs(d._duration(trim=False) - 2.0) < 1e-6 and d.chapters_box.isVisibleTo(d)
    finally:
        d.done(0)


def test_a_name_the_person_typed_survives_changing_the_sequence():
    ts = [target("a", "Sequência 1"), target("b", "Sequência 2")]
    d = export_dialog(ts, active="a")
    try:
        d.path.setText("C:/saida/meu_filme.mp4")
        d.seq_box.setCurrentIndex(d.seq_box.findData("b"))
        assert d.path.text() == "C:/saida/meu_filme.mp4"
    finally:
        d.done(0)


def test_export_several_sequences_in_the_queue_with_unique_names_and_the_same_settings(tmp_path):
    from pelicula.subtitles import Cue, Subtitles
    ts = [target("a", "Sequência 1"), target("b", "Abertura", frames=96, fps=25.0, fps_str="25/1", size=(640, 360)),
          target("c", "Abertura (cópia)", frames=24)]
    d = export_dialog(ts, active="a")
    try:
        d.out_dir = str(tmp_path)
        d.path.setText(str(tmp_path / "saida.mp4"))
        d.multi_box.setChecked(True)
        assert not d.multi_list.isHidden() and d.checked_ids() == ["a"] and "Pôr 1 na fila" in d.ok_button.text()
        d.multi_list.item(1).setCheckState(Qt.CheckState.Checked)
        d.multi_list.item(2).setCheckState(Qt.CheckState.Checked)
        assert "Pôr 3 na fila" in d.ok_button.text()
        jobs = d.jobs()
        assert [Path(j.out_path).name for j in jobs] == ["saida.mp4", "Abertura_pelicula.mp4",
                                                         "Abertura (cópia)_pelicula.mp4"]
        assert len({j.out_path for j in jobs}) == 3 and all(Path(j.out_path).parent == tmp_path for j in jobs)
        assert [j.sequence for j in jobs] == [t.sequence for t in ts] and [j.info for j in jobs] == [t.info for t in ts]
        assert jobs[1].info.fps == 25.0 and (jobs[1].info.width, jobs[1].info.height) == (640, 360)
        assert all(j.settings.to_dict() == jobs[0].settings.to_dict() for j in jobs)
        assert all(j.start_frame == 0 and j.end_frame == -1 for j in jobs)
        # o mesmo destino já na fila ou no disco: o nome ganha _2, nada é sobrescrito
        (tmp_path / "Abertura_pelicula.mp4").write_bytes(b"x")
        again = d.jobs()
        assert Path(again[1].out_path).name == "Abertura_pelicula_2.mp4"
        # desmarcar tira da fila; a escolhida na caixa sempre entra ao trocar
        d.multi_list.item(2).setCheckState(Qt.CheckState.Unchecked)
        assert [Path(j.out_path).name for j in d.jobs()][-1] == "Abertura_pelicula_2.mp4" and len(d.jobs()) == 2
        d.seq_box.setCurrentIndex(d.seq_box.findData("c"))
        assert "c" in d.checked_ids()
        d.multi_box.setChecked(False)
        assert len(d.jobs()) == 1 and d.ok_button.text().strip().startswith("Adicionar")
    finally:
        d.done(0)


def test_the_queue_of_several_sequences_does_not_keep_the_transparency_of_an_opaque_one(tmp_path):
    ts = [target("a", "Sequência 1", transparent=True), target("b", "Sequência 2", transparent=False)]
    d = export_dialog(ts, active="a")
    try:
        d.path.setText(str(tmp_path / "x.mov"))
        d._set_combo(d.quality, "prores_xq")
        d._quality_changed()
        d.alpha_box.setChecked(True)
        d.multi_box.setChecked(True)
        d.multi_list.item(1).setCheckState(Qt.CheckState.Checked)
        jobs = d.jobs()
        from pelicula import export
        assert export.wants_alpha(jobs[0].settings) and not export.wants_alpha(jobs[1].settings)
    finally:
        d.done(0)


def test_the_window_puts_one_job_per_sequence_in_the_queue_with_copies(win, monkeypatch, tmp_path):
    from pelicula.ui import export_dialog as ed
    ids = two_tabs(win, monkeypatch)
    win.model.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#115577"}, seconds=1.0), at=0)
    pump(lambda: win.cur is not None)
    added = []
    monkeypatch.setattr(win.queue, "add", added.append)
    monkeypatch.setattr(win, "show_queue", lambda: None)
    shown = []

    def fake_exec(self):
        shown.append(self)
        self.path.setText(str(tmp_path / "x.mp4"))
        self.multi_box.setChecked(True)
        for i in range(self.multi_list.count()):
            self.multi_list.item(i).setCheckState(Qt.CheckState.Checked)
        return 1

    monkeypatch.setattr(ed.ExportDialog, "exec", fake_exec)
    win.new_export()
    d = shown[0]
    assert d._target_id == ids[1] and [t for t in d.targets] == ids               # a aberta é a padrão
    assert len(added) == 2 and {Path(j.out_path).name for j in added} == {"x.mp4", "Sequência 1_pelicula.mp4"}
    assert all(j.sequence is not win.model.seq and j.sequence is not win.src_seq for j in added)
    assert [j.sequence.id for j in added] == [ids[1], ids[0]] or {j.sequence.id for j in added} == set(ids)
    assert all(len(j.sequence.family()) == 2 for j in added)                       # as irmãs vão junto (cópia completa)


def test_export_works_with_the_open_sequence_empty_when_another_has_clips(win, monkeypatch):
    from pelicula.ui import export_dialog as ed
    ids = two_tabs(win, monkeypatch)                 # a aberta é a nova, vazia; a primeira tem um clipe
    assert win.info is None and win.seqs_ui.can_export_other() and win.btn_export.isEnabled()
    shown = []

    def fake_exec(self):
        shown.append((self._target_id, self.info, self.sequence, list(self.targets)))
        return 0

    monkeypatch.setattr(ed.ExportDialog, "exec", fake_exec)
    win.new_export()
    assert len(shown) == 1 and shown[0][0] == ids[0] and shown[0][1].width == 320 and shown[0][2] is not None
    assert shown[0][3] == []          # só uma sequência tem o que sair: sem a linha da escolha
    win.model.undo()                  # volta a uma só, e a vazia some com o resto
    pump()


def test_a_real_export_of_two_sequences_through_the_dialog(win, monkeypatch, tmp_path):
    from pelicula import export
    from pelicula.engine import Engine
    from pelicula.ui import export_dialog as ed
    v1 = tone_video(tmp_path, "r1.mp4", "160x90", 24, 440, 1)
    v2 = tone_video(tmp_path, "r2.mp4", "192x108", 30, 880, 1)
    fresh(win)
    win.import_paths([v1])
    pump(lambda: win.cur is not None)
    accepting(monkeypatch, fps="30/1", size=(192, 108))
    win.seqs_ui.new_sequence()
    win.import_paths([v2])
    pump(lambda: win.cur is not None)
    added = []
    monkeypatch.setattr(win.queue, "add", added.append)
    monkeypatch.setattr(win, "show_queue", lambda: None)

    def fake_exec(self):
        self.path.setText(str(tmp_path / "saida.mp4"))
        self._set_combo(self.quality, "leve")
        self._quality_changed()
        self._set_combo(self.speed, "ultrafast")
        self.res.setCurrentIndex(self.res.findData("original"))
        self.multi_box.setChecked(True)
        for i in range(self.multi_list.count()):
            self.multi_list.item(i).setCheckState(Qt.CheckState.Checked)
        return 1

    monkeypatch.setattr(ed.ExportDialog, "exec", fake_exec)
    win.new_export()
    assert len(added) == 2
    engine = Engine()
    try:
        for job in added:
            export.run_job(job, engine)
            assert job.status == "concluido", job.error
    finally:
        engine.release()
    outs = {Path(j.out_path).name: media.probe(j.out_path) for j in added}
    assert sorted(outs) == ["Sequência 1_pelicula.mp4", "saida.mp4"]
    second, first = outs["saida.mp4"], outs["Sequência 1_pelicula.mp4"]          # a aberta (a 2ª) saiu em "saida.mp4"
    assert (second.width, second.height, second.frames) == (192, 108, 30) and abs(second.fps - 30) < 0.01
    assert (first.width, first.height, first.frames) == (160, 90, 24) and abs(first.fps - 24) < 0.01
    assert first.has_audio and second.has_audio
