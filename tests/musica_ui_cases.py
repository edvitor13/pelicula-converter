"""Casos da interface da música (1.8, `ui/musica_ui.py`): detectar batidas pelo menu e sozinho, marcas das batidas,
ímã nas batidas, encaixar a música na duração do vídeo e abaixar a música sob a voz.

Rodados por test_musica_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Os sons são gerados em numpy.
"""

from __future__ import annotations

import os
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import batidas, media  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import musica_ui, prefs  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.timeline_view import TimelineEditor  # noqa: E402

R = 48000
FPS = 24


def _ffmpeg() -> None:
    try:
        media.ffmpeg()
    except RuntimeError as exc:
        pytest.skip(f"ffmpeg indisponível: {exc}")


def _wav(path, x, rate=R) -> str:
    x = np.asarray(x, np.float64)
    if x.ndim == 1:
        x = np.repeat(x[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def _clicks(bpm, secs, rate=R, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.zeros(int(secs * rate))
    k = np.arange(int(0.03 * rate))
    burst = np.exp(-k / (0.005 * rate)) * rng.standard_normal(len(k))
    t, i = 0.5, 0
    while t < secs - 0.1:
        s = int(round(t * rate))
        x[s:s + len(burst)] += (0.8 if i % 4 == 0 else 0.4) * burst[:len(x) - s]
        t += 60.0 / bpm
        i += 1
    return x


def _grid(bpm=120.0, secs=60.0, first=0.0) -> batidas.Beats:
    per = 60.0 / bpm
    times = tuple(first + i * per for i in range(int((secs - first) / per) + 1))
    return batidas.Beats(times, bpm, times[::4], 1.0, (bpm / 2, bpm * 2), 1.0, secs)


def _music(path, secs) -> tl.Source:
    return tl.Source(path, fps=float(FPS), frames=int(secs * FPS), duration=secs, has_video=False, has_audio=True)


def _wait(job, secs=60.0) -> None:
    end = time.monotonic() + secs
    while job is not None and job.active and time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)
    for _i in range(20):
        APP.processEvents()
        time.sleep(0.005)


def _actions(menu) -> dict[str, QAction]:
    return {a.objectName(): a for a in menu.findChildren(QAction) if a.objectName()}


def _editor(seq) -> tuple[TimelineModel, TimelineEditor]:
    m = TimelineModel(seq)
    ed = TimelineEditor(m)
    ed.resize(1200, 300)
    return m, ed


# ------------------------------------------------------------------ batidas
def test_detect_beats_from_the_menu_and_cache(tmp_path):
    _ffmpeg()
    path = _wav(tmp_path / "musica.wav", _clicks(120, 8.0))
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    (clip,) = seq.insert_media(_music(path, 8.0), at=0, atrack=0)
    m, ed = _editor(seq)
    ctl = musica_ui.controller_for(ed.canvas)
    assert not ctl.auto and ctl.beats_for(path) is None
    menu = QMenu()
    musica_ui.add_clip_actions(menu, ed.canvas, clip)
    acts = _actions(menu)
    assert "detect_beats" in acts and "beats_info" not in acts
    said = []
    ctl.message.connect(said.append)
    acts["detect_beats"].trigger()
    assert ctl.busy(path) and not ctl.bar.isHidden()
    _wait(ctl.jobs.get(path))
    assert ctl.bar.isHidden() and not ctl.busy()
    b = ctl.beats_for(path)
    assert b is not None and abs(b.bpm - 120) < 1.2 and said and "BPM" in said[-1]
    menu = QMenu()
    musica_ui.add_clip_actions(menu, ed.canvas, clip)
    acts = _actions(menu)
    assert "detect_beats" not in acts and not acts["beats_info"].isEnabled()
    # outro controlador (o projeto reaberto) acha no cache, sem analisar
    other = musica_ui.MusicUI(m, ed.canvas, auto=False)
    assert other.beats_for(path) == b and not other.busy()


def test_long_music_is_analyzed_by_itself_with_the_preference(tmp_path):
    _ffmpeg()
    path = _wav(tmp_path / "longa.wav", _clicks(100, 22.0, rate=16000), rate=16000)
    short = _wav(tmp_path / "curta.wav", _clicks(100, 5.0, rate=16000), rate=16000)
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    m, ed = _editor(seq)
    ctl = musica_ui.MusicUI(m, ed.canvas, auto=True)
    prefs.settings().setValue(musica_ui.PREF_AUTO, "false")
    m.insert_media(_music(path, 22.0), at=0)
    assert not ctl.busy()                           # preferência desligada: nada sozinho
    prefs.settings().setValue(musica_ui.PREF_AUTO, "true")
    m.insert_media(_music(short, 5.0), at=600)
    assert not ctl.busy(short)                       # curta (< 20 s): só pelo menu
    assert ctl.busy(path)                            # a longa entra na análise na próxima mudança
    _wait(ctl.jobs.get(path))
    assert ctl.beats_for(path) is not None and ctl.beats_for(short) is None
    prefs.settings().remove(musica_ui.PREF_AUTO)


# ------------------------------------------------------------------ marcas e ímã
def test_beat_ticks_follow_the_clip_and_the_zoom():
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(_music("musica.wav", 60.0))
    c = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 48, 120, 2.0)
    seq.clips.append(c)
    m, ed = _editor(seq)
    canvas = ed.canvas
    ctl = musica_ui.controller_for(canvas)
    ctl.beats["musica.wav"] = _grid(120)
    canvas.set_ppf(4.0)
    marks = musica_ui.tick_marks(canvas, c)
    assert [x for x, _d in marks] == pytest.approx([canvas.frame_to_x(48 + 12 * k) for k in range(10)])
    assert [d for _x, d in marks] == [k % 4 == 0 for k in range(10)]
    seq.set_speed(c.id, 2.0)
    marks = musica_ui.tick_marks(canvas, seq.find(c.id))
    assert np.allclose(np.diff([x for x, _d in marks]), 6 * canvas.ppf)
    canvas.set_ppf(0.5)                              # batidas a 3 px: só os compassos
    assert all(d for _x, d in musica_ui.tick_marks(canvas, seq.find(c.id)))
    canvas.set_ppf(0.1)                              # nem os compassos cabem
    assert musica_ui.tick_marks(canvas, seq.find(c.id)) == []
    canvas.grab()                                    # desenha sem erro


def test_snap_to_beats_of_other_music_clips():
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(_music("musica.wav", 60.0))
    music = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 0, 480, 0.0)
    seq.clips.append(music)
    m, ed = _editor(seq)
    canvas = ed.canvas
    musica_ui.controller_for(canvas).beats["musica.wav"] = _grid(120, first=0.25)   # batidas em 6, 18, 30…
    canvas.set_ppf(4.0)
    prefs.settings().setValue(musica_ui.PREF_SNAP, "true")
    btn = ed.btn_beat_snap
    assert btn.isChecked() and btn.isEnabled()
    assert canvas.snap_frame(29.0, set()) == (30, 30)          # grudou na batida
    assert canvas.snap_frame(29.0, {music.id}) == (29, None)   # a batida do clipe arrastado não conta
    btn.setChecked(False)
    assert canvas.snap_frame(29.0, set()) == (29, None)
    assert str(prefs.settings().value(musica_ui.PREF_SNAP)) == "false"
    btn.setChecked(True)
    ed.btn_snap.setChecked(False)                               # sem o ímã, o botão das batidas não vale
    assert not btn.isEnabled() and canvas.snap_frame(29.0, set()) == (29, None)
    ed.btn_snap.setChecked(True)
    assert btn.isEnabled()
    prefs.settings().remove(musica_ui.PREF_SNAP)
