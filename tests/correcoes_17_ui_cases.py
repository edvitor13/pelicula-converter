"""Casos das correções da 1.7 na interface: modo e Ctrl+Z (#50), som da prévia (#51), âncora do zoom (#53) e o botão
Exportar durante uma exportação (#59).

Rodados por test_correcoes_17_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import audiomix, export, media, project, timeline as tl  # noqa: E402
from pelicula.i18n import _  # noqa: E402
from pelicula.ui import prefs  # noqa: E402
from pelicula.ui import main_window as mw  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.export_dialog import ExportDialog  # noqa: E402
from pelicula.ui.queue_dialog import QueueDialog  # noqa: E402
from pelicula.ui.settings_dialog import SettingsDialog  # noqa: E402
from pelicula.ui.timeline_view import HEADER_W, ZOOM_PLAYHEAD_KEY, TimelineEditor  # noqa: E402


# ------------------------------------------------------------------ janela principal (pula sem OpenGL)
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


def color_seq() -> tl.Sequence:
    """Montagem só com clipes sem arquivo: abre sem perguntar por arquivos que faltam."""
    seq = tl.Sequence(320, 180, "24/1")
    seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))
    return seq


def saved_project(mode: str) -> project.Project:
    return project.Project(media_path="", values={}, sequence=color_seq().to_json(), mode=mode)


def assert_mode(win, mode: str) -> None:
    """O botão, as telas e `self.mode` dizem a mesma coisa."""
    edit = mode == "edicao"
    assert win.mode == mode
    assert win.mode_switch.buttons[mode].isChecked()
    assert win.left_stack.currentIndex() == win.right_panel.currentIndex() == (1 if edit else 0)
    assert win.tl_editor.isHidden() == (not edit)
    assert win.timeline.isHidden() == edit


def go_to(win, mode: str) -> None:
    win.set_mode(mode)
    APP.processEvents()
    assert_mode(win, mode)


# ------------------------------------------------------------------ #50 modo e Ctrl+Z
def test_opening_a_project_keeps_button_screens_and_mode_together(win):
    for start, saved in (("edicao", "pelicula"), ("pelicula", "edicao"), ("edicao", "edicao"), ("pelicula", "pelicula")):
        go_to(win, start)
        win.show_project(saved_project(saved), remember=False)
        APP.processEvents()
        assert_mode(win, saved)


def test_ctrl_z_after_opening_goes_to_the_history_of_the_mode_on_screen(win):
    go_to(win, "edicao")  # a Edição na tela e o projeto salvo na Película: antes, as telas ficavam na Edição
    win.show_project(saved_project("pelicula"), remember=False)
    assert_mode(win, "pelicula")
    calls = []
    real = win.store.undo, win.model.undo
    win.store.undo, win.model.undo = (lambda: calls.append("look")), (lambda: calls.append("montagem"))
    try:
        win.undo()
        assert calls == ["look"]
        go_to(win, "edicao")
        win.undo()
        assert calls == ["look", "montagem"]
    finally:
        win.store.undo, win.model.undo = real


def test_ctrl_z_in_edit_mode_undoes_the_clip_and_keeps_the_look(win):
    go_to(win, "pelicula")
    win.show_project(saved_project("edicao"), remember=False)
    assert_mode(win, "edicao")
    key = "grao_forca"
    look_value = float(win.store.get(key)) + 0.1
    win.store.set(key, look_value)
    win.store.commit()
    clip = win.model.seq.clips[0]
    win.model.move_clip(clip.id, 12)
    assert win.model.seq.find(clip.id).start == 12
    win.undo()
    assert win.model.seq.find(clip.id).start == 0
    assert float(win.store.get(key)) == pytest.approx(look_value)


# ------------------------------------------------------------------ #51 som da prévia
def tone_video(ffmpeg: str, folder: str, name: str, freq: int, secs: int) -> str:
    path = os.path.join(folder, name)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=gray:s=160x90:r=24:d={secs}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={secs}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                   check=True, timeout=60)
    return path


def wait_for_mix(win, seconds: float = 30.0) -> None:
    """Até o som da prévia ser a mixagem da montagem de agora."""
    end = time.time() + seconds
    while time.time() < end:
        APP.processEvents()
        if not win.mix_timer.isActive() and win._mix_key == audiomix.mix_key(win.model.seq.copy()):
            APP.processEvents()
            if win._audio_src == ("seq", win._mix_path):
                return
        time.sleep(0.02)
    raise AssertionError("a mixagem da prévia não chegou")


def heard(win, t0: float = 0.2, t1: float = 0.8) -> tuple[float, float]:
    """(frequência dominante, nível RMS) do que a prévia toca no trecho."""
    reader = audiomix.WavReader(win._audio_src[1])
    x = reader.read(int(t0 * reader.rate), int((t1 - t0) * reader.rate))
    x = x[:, 0] if x.ndim > 1 else x
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spectrum) * reader.rate / len(x)), float(np.sqrt(np.mean(x ** 2)))


@pytest.fixture(scope="module")
def two_tones():
    ffmpeg = media.ffmpeg()
    if not ffmpeg:
        pytest.skip("sem ffmpeg")
    folder = tempfile.mkdtemp(prefix="pelicula_som_")
    return tone_video(ffmpeg, folder, "a.mp4", 440, 2), tone_video(ffmpeg, folder, "b.mp4", 1000, 3)


def only(seq: tl.Sequence, path: str, kind: str) -> tl.Clip:
    return next(c for c in seq.clips if c.src == path and c.kind == kind)


def test_the_preview_follows_the_clip_that_stayed(win, two_tones):
    """Apagar o 1º clipe, mover o 2º para o começo, mudar o volume e a faixa: a prévia sempre toca o que ficou."""
    a, b = two_tones
    go_to(win, "pelicula")
    win.show_project(saved_project("edicao"), remember=False)
    m = win.model
    m.delete_clips([c.id for c in m.seq.clips])
    win.import_paths([a, b])
    wait_for_mix(win)
    assert heard(win)[0] == pytest.approx(440, abs=5)

    m.select_group(only(m.seq, a, tl.VIDEO).id)
    m.delete_selected()  # a fonte fica na montagem sem clipe: é ela que separava a chave do modelo da chave da cópia
    assert a in m.seq.sources and a not in m.seq.copy().sources
    wait_for_mix(win)
    m.move_clip(only(m.seq, b, tl.VIDEO).id, 0)
    wait_for_mix(win)
    freq, level = heard(win)
    assert freq == pytest.approx(1000, abs=5) and level > 0.01
    assert win.vol.isEnabled() and win.btn_mute.isEnabled()

    au = only(m.seq, b, tl.AUDIO)
    m.set_clip_values(au.id, {**au.values, "volume": -6.0})
    wait_for_mix(win)
    freq, quieter = heard(win)
    assert freq == pytest.approx(1000, abs=5)
    assert 20 * np.log10(quieter / level) == pytest.approx(-6.0, abs=0.3)

    m.move_clip(only(m.seq, b, tl.AUDIO).id, 0, 1)  # para a A2
    assert only(m.seq, b, tl.AUDIO).track == 1
    wait_for_mix(win)
    freq, moved = heard(win)
    assert freq == pytest.approx(1000, abs=5) and moved == pytest.approx(quieter, rel=0.02)
    assert win.vol.isEnabled() and win.btn_mute.isEnabled()

    win.undo()  # volta para a A1, com o mesmo som
    wait_for_mix(win)
    assert only(m.seq, b, tl.AUDIO).track == 0
    assert heard(win)[0] == pytest.approx(1000, abs=5)


def test_the_preview_comes_back_after_a_silent_moment(win, two_tones):
    """Sem som nenhum por um momento o volume da prévia se desliga; com a mixagem nova recusada, era para sempre."""
    a, b = two_tones
    go_to(win, "pelicula")
    win.show_project(saved_project("edicao"), remember=False)
    m = win.model
    m.delete_clips([c.id for c in m.seq.clips])
    win.import_paths([a, b])
    wait_for_mix(win)
    m.delete_clips([only(m.seq, a, tl.VIDEO).id])
    wait_for_mix(win)
    au = only(m.seq, b, tl.AUDIO)
    m.set_clip_values(au.id, {**au.values, "mudo": True})
    wait_for_mix(win)
    assert win._audio_src == ("seq", "") and not win.vol.isEnabled()
    au = only(m.seq, b, tl.AUDIO)
    m.set_clip_values(au.id, {**au.values, "mudo": False})
    wait_for_mix(win)
    assert win.vol.isEnabled() and win.btn_mute.isEnabled()
    assert heard(win, 2.2, 2.8)[0] == pytest.approx(1000, abs=5)


def test_only_one_mix_per_key_and_the_file_in_use_stays(win, two_tones, monkeypatch):
    """Duas mixagens iguais a caminho: a primeira a chegar apagava o WAV da segunda, que era aceita em seguida. O
    player ficava com um arquivo que não existe: prévia muda e exportação com som."""
    a, b = two_tones
    go_to(win, "pelicula")
    win.show_project(saved_project("edicao"), remember=False)
    m = win.model
    m.delete_clips([c.id for c in m.seq.clips])
    win.import_paths([a, b])
    wait_for_mix(win)
    gate, calls, real = threading.Event(), [], audiomix.render_mix

    def slow(seq, path, *args, **kw):
        calls.append(path)
        assert gate.wait(30)
        return real(seq, path, *args, **kw)

    monkeypatch.setattr(audiomix, "render_mix", slow)
    au = only(m.seq, b, tl.AUDIO)
    m.set_clip_values(au.id, {**au.values, "volume": -3.0})
    win._start_mix()
    win._start_mix()  # a segunda vez (o temporizador da mesma edição) não mixa de novo
    assert len(calls) == 1 and len(win._mix_running) == 1
    gate.set()
    wait_for_mix(win)
    assert win._mix_running == {} and win._audio_src[1] == calls[0] and os.path.exists(calls[0])


def test_cleaning_keeps_a_mix_that_is_still_on_the_way(win, tmp_path):
    busy, old = tmp_path / "a_caminho.wav", tmp_path / "antiga.wav"
    busy.write_bytes(b"x")
    old.write_bytes(b"x")
    win._mix_files += [str(busy), str(old)]
    win._mix_running["outra"] = str(busy)
    try:
        win._clean_mixes()
        assert busy.exists() and not old.exists() and str(busy) in win._mix_files
    finally:
        win._mix_running.pop("outra")
        win._mix_files.remove(str(busy))


def test_the_preview_hears_a_clip_dragged_before_another(win, two_tones):
    """Mudar a ordem dos clipes na faixa também separava as chaves (a cópia grava em ordem de tempo)."""
    a, b = two_tones
    go_to(win, "pelicula")
    win.show_project(saved_project("edicao"), remember=False)
    m = win.model
    m.delete_clips([c.id for c in m.seq.clips])
    win.import_paths([a, b])
    wait_for_mix(win)
    m.move_clip(only(m.seq, b, tl.VIDEO).id, 200)
    wait_for_mix(win)
    m.move_clip(only(m.seq, a, tl.VIDEO).id, 400)
    wait_for_mix(win)
    m.move_clip(only(m.seq, b, tl.VIDEO).id, 0)
    wait_for_mix(win)
    assert heard(win)[0] == pytest.approx(1000, abs=5)


# ------------------------------------------------------------------ #53 âncora do zoom
def long_editor(playhead: int = 2000) -> TimelineEditor:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(tl.Source("C:/v/longo.mp4", 1920, 1080, 24.0, "24/1", 6000, 250.0, has_audio=True))
    m.set_sequence(seq)
    ed = TimelineEditor(m)
    ed.resize(1100, 320)
    ed.show()
    APP.processEvents()
    c = ed.canvas
    c.ppf = 1.0
    c.scroll = playhead - 400.0  # o marcador fora do centro, dentro da vista
    c.playhead = playhead
    return ed


def wheel(c, x: float, up: bool = True) -> None:
    pos = QPointF(x, 100)
    e = QWheelEvent(pos, QPointF(c.mapToGlobal(QPoint(int(x), 100))), QPoint(0, 0), QPoint(0, 120 if up else -120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    c.wheelEvent(e)


ZOOM_ROUTES = ("aproximar", "afastar", "controle", "tecla +", "tecla -", "roda")


def routes(ed: TimelineEditor) -> dict:
    """Os caminhos do zoom: dois botões, o controle, o teclado e Ctrl + roda do mouse."""
    c = ed.canvas
    return {
        "aproximar": ed.btn_zoom_in.click,
        "afastar": ed.btn_zoom_out.click,
        "controle": lambda: ed.zoom.setValue(ed.zoom.value() + 0.05, emit=True),
        "tecla +": lambda: QTest.keyClick(c, Qt.Key.Key_Plus),
        "tecla -": lambda: QTest.keyClick(c, Qt.Key.Key_Minus),
        "roda": lambda: wheel(c, 700.0),
    }


def test_zoom_keeps_the_playhead_still():
    for name in ZOOM_ROUTES:
        ed = long_editor()
        c = ed.canvas
        assert c.zoom_on_playhead  # padrão: marcado
        x0, ppf0 = c.frame_to_x(c.playhead), c.ppf
        routes(ed)[name]()
        assert c.ppf != ppf0, name
        assert abs(c.frame_to_x(c.playhead) - x0) < 1.0, name


def test_playhead_out_of_view_comes_to_the_center():
    """Antes, a âncora fora da vista jogava a rolagem para longe (o "pula para o final")."""
    for name in ZOOM_ROUTES:
        for scroll in (0.0, 4500.0):
            ed = long_editor()
            c = ed.canvas
            c.scroll = scroll
            routes(ed)[name]()
            assert abs(c.frame_to_x(c.playhead) - (HEADER_W + c.lanes_width() / 2)) < 1.0, (name, scroll)


def test_unchecked_wheel_keeps_the_pointer_still():
    ed = long_editor()
    c = ed.canvas
    c.zoom_on_playhead = False
    x = 700.0
    frame = c.x_to_frame(x)
    wheel(c, x)
    assert abs(c.frame_to_x(frame) - x) < 1.0


def test_unchecked_controls_keep_the_center_still():
    for name in ZOOM_ROUTES[:-1]:
        ed = long_editor()
        c = ed.canvas
        c.zoom_on_playhead = False
        mid_x = HEADER_W + c.lanes_width() / 2
        frame = c.x_to_frame(mid_x)
        routes(ed)[name]()
        assert abs(c.frame_to_x(frame) - mid_x) < 1.0, name


def test_scrollbar_keeps_up_with_a_scroll_past_the_end():
    ed = long_editor(playhead=5990)
    c = ed.canvas
    c.scroll = c.seq.duration - 10.0
    ed.btn_zoom_out.click()
    assert ed.hbar.value() == int(round(c.scroll))


def test_zoom_option_is_saved_and_new_timelines_read_it():
    ed = long_editor()
    menu = ed.zoom_menu()
    act = menu.actions()[0]
    assert act.isCheckable() and act.isChecked()
    try:
        act.setChecked(False)
        assert str(prefs.settings().value(ZOOM_PLAYHEAD_KEY)) == "false" and not ed.canvas.zoom_on_playhead
        assert not long_editor().canvas.zoom_on_playhead and not ed.zoom_menu().actions()[0].isChecked()
    finally:
        prefs.settings().remove(ZOOM_PLAYHEAD_KEY)
    assert long_editor().canvas.zoom_on_playhead


def test_settings_page_changes_the_open_timeline(win):
    dlg = SettingsDialog(win, win.settings, "geral", main=win)
    dlg.settings_changed.connect(win.settings_changed)  # como em `MainWindow.show_settings`
    box = next(b for b in dlg.findChildren(QCheckBox) if b.text() == _("Zoom pelo marcador de reprodução"))
    assert box.isChecked() and win.tl_editor.canvas.zoom_on_playhead
    try:
        box.setChecked(False)
        assert not win.tl_editor.canvas.zoom_on_playhead
    finally:
        box.setChecked(True)
    assert win.tl_editor.canvas.zoom_on_playhead
    dlg.deleteLater()


# ------------------------------------------------------------------ #59 Exportar durante uma exportação
def make_info(path: str) -> media.MediaInfo:
    return media.MediaInfo(path=path, width=320, height=180, fps=24.0, fps_str="24/1", frames=24, duration=1.0,
                           pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="", bitrate=0, color_space="bt709",
                           color_range="tv", color_transfer="bt709", color_primaries="bt709", has_audio=False,
                           audio_codec="", container="mp4", is_image=False)


def running_job(out: str, status: str = "exportando") -> export.ExportJob:
    job = export.ExportJob(info=make_info(out + ".fonte.mp4"), values={}, settings=export.ExportSettings(),
                           out_path=out, name=Path(out).name)
    job.status = status
    return job


@pytest.fixture
def forbid_dialog(monkeypatch):
    opened = []

    class Fake:
        def __init__(self, *a, **k):
            opened.append(k)

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "ExportDialog", Fake)
    return opened


def test_export_button_during_an_export_shows_the_queue(win, forbid_dialog):
    go_to(win, "pelicula")
    win.show_project(saved_project("pelicula"), remember=False)
    job = running_job(os.path.join(tempfile.gettempdir(), "saida.mp4"))
    win.queue.jobs.append(job)
    try:
        win.btn_export.click()
        APP.processEvents()
        assert forbid_dialog == []
        assert win.queue_dialog is not None and win.queue_dialog.isVisible()
        assert job.status == "exportando" and not job.cancel.is_set()
        win._queue_tick()
        assert "fila" in win.btn_export.toolTip().lower()
        win.queue_dialog.btn_add.click()  # de propósito: agora sim abre a exportação, sabendo o que está na fila
        assert len(forbid_dialog) == 1 and forbid_dialog[0]["queue_jobs"] == [job]
    finally:
        win.queue.jobs.clear()
        win.queue_dialog.close()
    win._queue_tick()
    assert "fila" not in win.btn_export.toolTip().lower()
    win.btn_export.click()  # sem nada rodando, o botão abre a exportação como sempre
    assert len(forbid_dialog) == 2


def test_add_button_only_with_a_callback():
    q = export.ExportQueue()
    assert QueueDialog(None, q).btn_add.isHidden()
    assert not QueueDialog(None, q, on_add=lambda: None).btn_add.isHidden()


def same_target_dialog(folder: str, jobs) -> ExportDialog:
    src = os.path.join(folder, "fonte.mp4")
    Path(src).write_bytes(b"x")
    dlg = ExportDialog(None, make_info(src), {}, "Teste", None, last_dir=folder, last_quality="mp4", queue_jobs=jobs)
    dlg._est_timer.stop()
    dlg._preview_timer.stop()
    return dlg


def test_same_destination_in_the_queue_asks_for_another_name(monkeypatch):
    folder = tempfile.mkdtemp(prefix="pelicula_fila_")
    out = os.path.join(folder, "video.mp4")
    Path(os.path.join(folder, "video_2.mp4")).write_bytes(b"x")  # já existe no disco: pula para o _3
    dlg = same_target_dialog(folder, [running_job(out)])
    dlg.path.setText(out)
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    asked = []

    def question(_parent, _title, text, *a, **k):
        asked.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)
    dlg._accept()  # não: continua na janela, com o nome como estava
    assert dlg.path.text() == out and dlg.result() == 0
    dlg._accept()
    assert Path(dlg.path.text()).name == "video_3.mp4" and dlg.result() == 1
    assert dlg.job().out_path.endswith("video_3.mp4") and "video_3.mp4" in dlg.job().name
    assert out in asked[0] and "video_3.mp4" in asked[0]


def test_other_destination_or_finished_job_asks_nothing(monkeypatch):
    folder = tempfile.mkdtemp(prefix="pelicula_fila_")
    out = os.path.join(folder, "video.mp4")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("não devia perguntar"))
    dlg = same_target_dialog(folder, [running_job(os.path.join(folder, "outro.mp4")), running_job(out, "concluido")])
    dlg.path.setText(out)
    dlg._accept()
    assert dlg.path.text() == out and dlg.result() == 1
