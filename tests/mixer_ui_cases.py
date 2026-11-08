"""Casos da interface do mixer e do som ao arrastar o cursor (1.8, #39): o painel no lugar do inspetor, uma tira por faixa
de som, o fader e o balanço num passo só do desfazer, mudo e solo, o cabeçalho e o mixer juntos, os medidores lidos dos
picos gravados ao lado da mixagem, e o grão do scrub (com um sink falso: nada toca nos alto-falantes).

Rodados por test_mixer_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado sozinho.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import audiomix, somcache, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, mixer_ui, prefs, scrub_ui  # noqa: E402


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


def fresh(win) -> tl.Sequence:
    """Projeto novo no modo Edição com uma faixa de vídeo e três de som (com um clipe de cor, para ter duração)."""
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))
    while len(seq.kind_tracks(tl.AUDIO)) < 3:
        seq.tracks.append(tl.Track(tl.AUDIO, name=f"A{len(seq.kind_tracks(tl.AUDIO)) + 1}"))
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")   # a prévia carrega a montagem (`MainWindow.info`)
    win.mixer.show_mixer(True)
    pump()
    return win.model.seq


def drag(widget, p0: QPoint, p1: QPoint) -> None:
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for k in range(1, 6):
        QTest.mouseMove(widget, p0 + (p1 - p0) * (k / 5))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    APP.processEvents()


def test_the_button_and_the_shortcut_swap_the_inspector_for_the_mixer(win):
    fresh(win)
    m = win.mixer
    assert m.visible and not win.inspector.isVisible() and win.tl_editor.btn_mixer.isChecked()
    win.tl_editor.btn_mixer.click()
    pump()
    assert not m.visible and win.inspector.isVisible() and not m.timer.isActive()
    m.shortcut.activated.emit()
    pump()
    assert m.visible and m.timer.isActive()
    assert mixer_ui.SHORTCUT == "Ctrl+Alt+M"
    keys = {s.key().toString() for s in win.findChildren(type(m.shortcut)) if s is not m.shortcut}
    assert "Ctrl+Alt+M" not in keys   # nenhum outro atalho da janela usa


def test_one_strip_per_audio_track_and_new_tracks_appear(win):
    seq = fresh(win)
    names = [s.name.text() for s in win.mixer.panel.strips]
    assert names == [t.name for t in seq.kind_tracks(tl.AUDIO)] and len(names) == 3
    win.model.add_track(tl.AUDIO)
    pump()
    assert len(win.mixer.panel.strips) == 4
    win.model.undo()
    pump()
    assert len(win.mixer.panel.strips) == 3


def test_dragging_the_fader_is_one_undo_step_and_the_header_follows(win):
    seq = fresh(win)
    strip = win.mixer.panel.strips[1]
    f = strip.fader
    steps = win.model.history._pos
    top, bottom = f._span()
    y0 = int(bottom - (bottom - top) * mixer_ui.db_to_t(0.0))
    y1 = int(bottom - (bottom - top) * mixer_ui.db_to_t(-18.0))
    x = f.width() // 2
    drag(f, QPoint(x, y0), QPoint(x, y1))
    vol = win.model.seq.track(tl.AUDIO, 1).volume
    assert -21.0 < vol < -15.0 and strip.db_label.text().startswith("−")
    assert win.model.history._pos == steps + 1   # o arraste inteiro: um passo do desfazer
    win.model.undo()
    pump()
    assert win.model.seq.track(tl.AUDIO, 1).volume == 0.0 and f.value == 0.0
    # o cabeçalho (o mesmo `set_track`) muda o mixer
    win.model.set_track(tl.AUDIO, 2, volume=-6.0)
    pump()
    assert win.mixer.panel.strips[2].fader.value == -6.0
    assert seq is not None


def test_double_click_resets_the_fader_and_the_pan(win):
    fresh(win)
    win.model.set_track(tl.AUDIO, 0, volume=-9.0, pan=0.5)
    pump()
    strip = win.mixer.panel.strips[0]
    assert strip.pan_label.text() == "D 50"
    QTest.mouseDClick(strip.fader, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      QPoint(strip.fader.width() // 2, 30))
    QTest.mouseDClick(strip.pan, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 7))
    pump()
    tr = win.model.seq.track(tl.AUDIO, 0)
    assert tr.volume == 0.0 and tr.pan == 0.0 and strip.pan_label.text() == "C"


def test_dragging_the_pan_writes_the_track_and_the_json(win):
    fresh(win)
    p = win.mixer.panel.strips[2].pan
    drag(p, QPoint(p.width() // 2, 7), QPoint(4, 7))
    tr = win.model.seq.track(tl.AUDIO, 2)
    assert tr.pan == -1.0
    assert win.model.seq.to_json()["faixas"][3]["balanco"] == -1.0
    assert "balanco_faixa" in win.model.seq.features()
    win.model.undo()
    pump()
    assert win.model.seq.track(tl.AUDIO, 2).pan == 0.0


def test_mute_and_solo_buttons(win):
    fresh(win)
    s = win.mixer.panel.strips[1]
    s.mute.click()
    s.solo.click()
    pump()
    tr = win.model.seq.track(tl.AUDIO, 1)
    assert tr.muted and tr.solo
    win.model.set_track(tl.AUDIO, 1, muted=False)
    pump()
    assert not s.mute.isChecked() and s.solo.isChecked()
    win.model.set_track(tl.AUDIO, 1, locked=True)
    pump()
    assert not s.fader.isEnabled() and not s.pan.isEnabled()


def test_meters_index_the_peaks_saved_next_to_the_mix(win, tmp_path):
    fresh(win)
    wav = tmp_path / "mix.wav"
    with somcache.WavWriter(str(wav), 4800) as w:
        w.write(np.zeros((4800, 2)))
    peaks = np.zeros((300, 2), np.float32)
    peaks[:, 0] = 0.5      # faixa A1: −6 dBFS
    peaks[:, 1] = 0.01     # faixa A2: −40 dBFS
    res = somcache.Mix(str(wav), 4800, [], peaks, [0, 1], np.full(300, 0.6, np.float32))
    somcache.save_peaks(res)
    m = win.mixer
    m.timer.stop()
    old = (win._mix_path, win._audio_src, win.playing, getattr(win, "_play_t0", None), getattr(win, "_play_f0", 0))
    try:
        win._mix_path, win._audio_src = str(wav), ("seq", str(wav))
        win.playing, win._play_t0, win._play_f0 = True, time.perf_counter() - 1.0, 0
        m._tick()
        lv = [s.meter.level for s in m.panel.strips]
        assert lv[0] == pytest.approx(-6.02, abs=0.05) and lv[1] == pytest.approx(-40.0, abs=0.05)
        assert lv[2] == mixer_ui.FLOOR
        assert m.panel.master.meter.level == pytest.approx(-4.44, abs=0.05)
        win.playing = False
        m._tick()
        assert all(s.meter.level == mixer_ui.FLOOR for s in m.panel.strips)
    finally:
        win._mix_path, win._audio_src, win.playing, win._play_t0, win._play_f0 = old
        m.timer.start()


def test_the_preview_mix_writes_the_track_peaks_and_cleaning_removes_them(win, tmp_path):
    seq = fresh(win)
    wav = tmp_path / "tom.wav"
    with somcache.WavWriter(str(wav), 48000) as w:
        w.write(np.full((48000, 2), 0.25))
    seq.add_source(tl.Source(str(wav), fps=24.0, frames=24, duration=1.0, has_video=False, has_audio=True))
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, str(wav), 1, 0, 24, 0.0))
    win.model.commit()
    win.model.changed.emit("structure")
    win._start_mix()
    t0 = time.time()
    while time.time() - t0 < 20 and not win._mix_path:
        pump(0.05)
    assert win._mix_path
    got = somcache.load_peaks(win._mix_path)
    assert got is not None and got[0] == [1] and got[1].max() == pytest.approx(0.25, abs=1e-3)
    f = tmp_path / "x.wav"
    f.write_bytes(b"x")
    (tmp_path / ("x.wav" + somcache.PEAKS_SUFFIX)).write_bytes(b"x")
    win._mix_files.append(str(f))
    win._clean_mixes()
    assert not f.exists() and not (tmp_path / ("x.wav" + somcache.PEAKS_SUFFIX)).exists()


# ------------------------------------------------------------------ som ao arrastar o cursor
class FakeIO:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(bytes(data))
        return len(data)


def scrub_ready(win, tmp_path):
    fresh(win)
    wav = tmp_path / "scrub.wav"
    t = np.arange(48000) / 48000.0
    x = (0.5 * np.sin(2 * np.pi * 440 * t))[:, None].repeat(2, axis=1)
    with somcache.WavWriter(str(wav), len(x)) as w:
        w.write(x)
    io = FakeIO()
    sc = win.scrub
    sc.sink_factory = lambda parent: (object(), io)
    sc._sink = None
    sc.throttle = scrub_ui.Throttle()
    win._mix_path, win._audio_src = str(wav), ("seq", str(wav))
    win.btn_mute.setChecked(False)
    sc.button.setChecked(True)
    return sc, io


def test_scrub_plays_a_grain_on_frame_steps_and_ruler_drags_only(win, tmp_path):
    sc, io = scrub_ready(win, tmp_path)
    old = (win._mix_path, win._audio_src)
    try:
        win.step(1)
        assert len(io.chunks) == 1
        n = len(io.chunks[0]) // 4
        assert n == scrub_ui.grain_span(1, win.info.fps)[1] and n >= int(0.040 * 48000)
        win.step(1)                         # o grão anterior ainda está tocando
        assert len(io.chunks) == 1
        sc.throttle = scrub_ui.Throttle()
        win.seek(5)                         # um clique (sem arrastar o cursor na régua): sem som
        assert len(io.chunks) == 1
        win.tl_editor.scrubbing.emit(True)
        win.seek(7)
        win.tl_editor.scrubbing.emit(False)
        assert len(io.chunks) == 2
        sc.throttle = scrub_ui.Throttle()
        win.btn_mute.setChecked(True)       # o mudo da prévia vale para o scrub
        win.step(1)
        win.btn_mute.setChecked(False)
        assert len(io.chunks) == 2
    finally:
        win._mix_path, win._audio_src = old


def test_scrub_toggle_is_saved_in_the_prefs(win, tmp_path):
    sc, io = scrub_ready(win, tmp_path)
    old = (win._mix_path, win._audio_src)
    try:
        assert scrub_ui.PREF_KEY == "som_ao_arrastar"
        sc.button.click()
        assert not sc.enabled and prefs.settings().value(scrub_ui.PREF_KEY) == "false"
        win.step(1)
        assert io.chunks == []
        sc.button.click()
        assert sc.enabled and prefs.settings().value(scrub_ui.PREF_KEY) == "true"
    finally:
        win._mix_path, win._audio_src = old


def test_the_real_sink_stays_silent_offscreen():
    assert scrub_ui._qt_sink(None) is None

