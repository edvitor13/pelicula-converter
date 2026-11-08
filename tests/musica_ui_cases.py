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


# ------------------------------------------------------------------ encaixar a música
def _with_video(music_secs=60.0, video_frames=30 * FPS):
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(_music("musica.wav", music_secs))
    seq.add_source(tl.Source("video.mp4", 640, 360, 24.0, "24/1", 2400, 100.0, has_video=True, has_audio=False))
    seq.clips.append(tl.Clip(tl.new_id(), tl.VIDEO, "video.mp4", 0, 0, video_frames, 0.0))
    music = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 0, int(music_secs * FPS), 0.0)
    seq.clips.append(music)
    return seq, music


def test_fit_music_from_the_menu_in_one_undo_step():
    seq, music = _with_video()
    m, ed = _editor(seq)
    ctl = musica_ui.controller_for(ed.canvas)
    ctl.beats["musica.wav"] = _grid(120)
    told, said = [], []
    ctl.inform = told.append
    ctl.message.connect(said.append)
    menu = QMenu()
    musica_ui.add_clip_actions(menu, ed.canvas, music)
    _actions(menu)["fit_music"].trigger()
    parts = sorted((c for c in m.seq.clips if c.kind == tl.AUDIO), key=lambda c: c.start)
    assert not told and len(parts) == 2 and parts[-1].end == 30 * FPS
    assert parts[1].values["transicao"] > 0 and "compassos tirados" in said[-1]
    m.undo()
    assert len([c for c in m.seq.clips if c.kind == tl.AUDIO]) == 1 and not m.can_undo()
    # com In/Out marcado, a música vai do In ao Out
    ed.canvas.inp, ed.canvas.outp = 48, 48 + 40 * FPS - 1
    ctl.fit(music.id)
    parts = sorted((c for c in m.seq.clips if c.kind == tl.AUDIO), key=lambda c: c.start)
    assert parts[0].start == 48 and parts[-1].end == 48 + 40 * FPS
    m.undo()
    ed.canvas.inp = ed.canvas.outp = None


def test_fit_music_refusals_and_the_simple_fade():
    seq, music = _with_video(video_frames=6 * FPS)        # 6 s: menos que a introdução e o final juntos
    m, ed = _editor(seq)
    ctl = musica_ui.controller_for(ed.canvas)
    ctl.beats["musica.wav"] = _grid(120)
    asked, told = [], []
    ctl.inform = told.append
    ctl.ask = lambda text: asked.append(text) or False
    ctl.fit(music.id)
    assert asked and "introdução" in asked[-1] and m.seq.find(music.id).dur == 60 * FPS and not m.can_undo()
    ctl.ask = lambda text: True
    ctl.fit(music.id)
    c = m.seq.find(music.id)
    assert c.end == 6 * FPS and c.values["fade_out"] == 2.0
    m.undo()
    # batidas sem confiança e a música mais curta que o vídeo: só a mensagem
    seq, music = _with_video(music_secs=20.0, video_frames=40 * FPS)
    m.set_sequence(seq)
    shaky = _grid(120, secs=20.0)
    ctl.beats["musica.wav"] = batidas.Beats(shaky.times, 120.0, shaky.downbeats, 0.1)
    ctl.fit(music.id)
    assert told and "confiáveis" in told[-1] and m.seq.find(music.id).dur == 20 * FPS
    # faixa travada: a ação nem fica disponível
    m.seq.ensure_track(tl.AUDIO, 0)
    m.seq.track(tl.AUDIO, 0).locked = True
    menu = QMenu()
    musica_ui.add_clip_actions(menu, ed.canvas, m.seq.find(music.id))
    assert not _actions(menu)["fit_music"].isEnabled()


# ------------------------------------------------------------------ abaixar a música sob a voz
def _voice(secs, bursts, rate=R):
    t = np.arange(int(secs * rate)) / rate
    ph = 2 * np.pi * np.cumsum(140 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / rate
    vowel = sum(np.sin(k * ph) / k for k in range(1, 12))
    x = 0.002 * np.random.default_rng(4).standard_normal(len(t))
    for a, b in bursts:
        m = (t >= a) & (t < b)
        x[m] += 0.25 * vowel[m]
    return x


def test_duck_music_under_the_voice_in_one_undo_step(tmp_path):
    _ffmpeg()
    t = np.arange(3 * R) / R
    song = _wav(tmp_path / "musica.wav", 0.3 * np.sin(2 * np.pi * 440 * t))
    speech = _wav(tmp_path / "voz.wav", _voice(3.0, [(1.0, 2.0)]))
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(_music(song, 3.0))
    seq.add_source(_music(speech, 3.0))
    seq.ensure_track(tl.AUDIO, 1)
    music = tl.Clip(tl.new_id(), tl.AUDIO, song, 0, 0, 72, 0.0)
    talk = tl.Clip(tl.new_id(), tl.AUDIO, speech, 1, 0, 72, 0.0)
    seq.clips += [music, talk]
    m, ed = _editor(seq)
    ctl = musica_ui.controller_for(ed.canvas)
    seen, asked, said = [], [], []
    ctl.duck_dialog = lambda tracks, checked: seen.append((tracks, checked)) or (-12.0, 0.3, 0.4, checked)
    ctl.ask = lambda text: asked.append(text) or False
    ctl.inform = said.append
    menu = QMenu()
    musica_ui.add_clip_actions(menu, ed.canvas, music)
    _actions(menu)["duck_music"].trigger()
    assert seen == [([1], [1])] and ctl.busy_duck() and not ctl.bar.isHidden()
    _wait(ctl.duck_job)
    assert not ctl.busy_duck() and not said
    keys = m.seq.keys_of(m.seq.find(music.id), "volume")
    assert len(keys) == 4 and abs(keys[1][0] - 24) <= 1 and keys[1][1] == -12.0 and keys[0][1] == 0.0
    assert keys[0][0] == keys[1][0] - round(0.3 * FPS)
    m.undo()
    assert m.seq.keys_of(m.seq.find(music.id), "volume") == [] and not m.can_undo()
    # chave que já estava dentro da descida: pergunta; "não" deixa tudo como estava
    m.seq.set_key(music.id, "volume", 36, -3.0)
    m.commit()
    _wait(ctl.duck(music.id))
    assert asked and m.seq.keys_of(m.seq.find(music.id), "volume")[0][:2] == (36, -3.0)
    ctl.ask = lambda text: True
    _wait(ctl.duck(music.id))
    frames = [f for f, _v, _e in m.seq.keys_of(m.seq.find(music.id), "volume")]
    assert 36 not in frames and len(frames) == 4
    # sem faixa de voz (só a música na sequência): mensagem, nada a fazer
    m.seq.clips.remove(m.seq.find(talk.id))
    ctl.duck_dialog = lambda tracks, checked: (-12.0, 0.3, 0.4, tracks)
    _wait(ctl.duck(music.id))
    assert said and "Nenhuma fala" in said[-1]


def test_duck_dialog_remembers_the_numbers():
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(_music("musica.wav", 60.0))
    seq.ensure_track(tl.AUDIO, 2)
    music = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 0, 480, 0.0)
    seq.clips.append(music)
    m, ed = _editor(seq)
    ctl = musica_ui.controller_for(ed.canvas)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QDoubleSpinBox

    def fill():
        dlg = next(w for w in APP.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible())
        spins = dlg.findChildren(QDoubleSpinBox)
        assert spins[0].value() == -12.0 and spins[1].value() == 0.3 and spins[2].value() == 0.6
        spins[0].setValue(-18.0)
        spins[2].setValue(1.0)
        dlg.accept()

    QTimer.singleShot(50, fill)
    got = ctl.duck_dialog([1, 2], [2])
    assert got == (-18.0, 0.3, 1.0, [2])
    assert float(prefs.settings().value(musica_ui.PREF_DUCK_DB)) == -18.0

    def check():
        dlg = next(w for w in APP.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible())
        spins = dlg.findChildren(QDoubleSpinBox)
        assert spins[0].value() == -18.0 and spins[2].value() == 1.0
        dlg.reject()

    QTimer.singleShot(50, check)
    assert ctl.duck_dialog([1, 2], [2]) is None
    for k in (musica_ui.PREF_DUCK_DB, musica_ui.PREF_DUCK_ATTACK, musica_ui.PREF_DUCK_RELEASE):
        prefs.settings().remove(k)
