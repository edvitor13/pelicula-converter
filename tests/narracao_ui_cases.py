"""Casos da interface de gravar narração (1.8, #39): o botão e o painel, o microfone escolhido e lembrado, a gravação do
cursor ou da entrada até a saída, a contagem, tocar a montagem junto, a faixa "Narração" e o passo único do desfazer, as
pastas (ao lado do projeto salvo ou na do app), o atraso do microfone e os erros (sem microfone, acesso negado, microfone
que some). O microfone, a lista de dispositivos e o bipe são falsos: nenhum dispositivo de verdade é aberto e nada toca.

Rodados por test_narracao_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado sozinho.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

# A pasta do app (gravações de um projeto sem salvar) vai para um lugar temporário, antes de importar o app.
_APP = tempfile.mkdtemp(prefix="narracao_app_")
os.environ["LOCALAPPDATA"] = _APP
os.environ["XDG_DATA_HOME"] = _APP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import audiomix, narracao, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, narracao_ui, prefs  # noqa: E402

DEVICES = [("aa01", "Microfone embutido", True), ("bb02", "Interface USB", False)]


class FakeCapture(QObject):
    """O microfone: os testes empurram bytes com `push`."""
    data = Signal(bytes)
    failed = Signal(str)
    made: list = []

    def __init__(self, device_id="", parent=None, rate=44100, channels=1, fmt="int16"):
        super().__init__(parent)
        self.device_id, self.rate, self.channels, self.fmt = device_id, rate, channels, fmt
        self.running = False
        FakeCapture.made.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def push(self, seconds: float, amp: float = 0.4, freq: float = 440.0, chunk: float = 0.02):
        n = int(round(seconds * self.rate))
        x = amp * np.sin(2 * np.pi * freq * np.arange(n) / self.rate)
        raw = np.rint(x * 32767).astype("<i2").tobytes()
        step = int(chunk * self.rate) * 2
        for i in range(0, len(raw), step):
            self.data.emit(raw[i:i + step])


def pump(timeout: float = 0.1) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        time.sleep(0.01)


def wait_for(cond, timeout: float = 5.0) -> bool:
    """Espera a thread do gravador (o resample de 44,1 kHz é ~5× mais rápido que o tempo real)."""
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        pump(0.02)
    return bool(cond())


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


class Rig:
    """O que cada caso precisa: a janela com uma montagem de 10 s, o controle com os falsos e os registros."""

    def __init__(self, win):
        self.win = win
        win.new_project()
        win.set_mode("edicao")
        seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
        seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))
        seq.clips[0].dur = 240
        win._loading = True
        win.model.set_sequence(seq)
        win._loading = False
        win.model.changed.emit("*")
        pump()
        ui = win.narracao
        ui.panel.close()
        ui._close_capture()
        FakeCapture.made.clear()
        self.beeps = 0
        self.played: list[int] = []
        ui.device_factory = lambda ident, parent: FakeCapture(ident, parent)
        ui.devices = lambda: list(DEVICES)
        ui.beep = self._beep
        win.start_play = lambda start=None: (self.played.append(start), setattr(win, "playing", True))[0]
        win.stop_play = lambda: setattr(win, "playing", False)
        shutil.rmtree(Path(_APP) / "PeliculaConverter", ignore_errors=True)   # as gravações de um caso anterior
        win.project_path = None
        win.inp = win.outp = None
        win.frame_idx = 0
        s = prefs.settings()
        for key in (narracao_ui.PREF_COUNT, narracao_ui.PREF_PLAY, narracao_ui.PREF_LATENCY, narracao_ui.PREF_DEVICE):
            s.remove(key)
        ui.panel.count.setChecked(False)
        ui.panel.play.setChecked(False)
        ui.panel.latency.setValue(0)
        self.ui = ui

    def _beep(self):
        self.beeps += 1

    def open(self) -> FakeCapture:
        self.ui.open_panel()
        pump()
        return FakeCapture.made[-1]

    @property
    def seq(self) -> tl.Sequence:
        return self.win.model.seq

    def audio_clips(self):
        return [c for c in self.seq.clips if c.kind == tl.AUDIO]


@pytest.fixture
def rig(win):
    r = Rig(win)
    yield r
    r.ui.shutdown()
    r.ui.panel.close()
    del win.start_play, win.stop_play


def read_wav(path) -> np.ndarray:
    r = audiomix.WavReader(str(path))
    return r.read(0, r.frames)


def test_the_button_opens_the_panel_with_the_default_microphone(rig, ffmpeg_ok):
    ui = rig.ui
    assert ui.button.isEnabled() and not ui.panel.isVisible()
    rig.win.tl_editor.btn_narrar.click()
    pump()
    assert ui.panel.isVisible() and ui.panel.device.count() == 2
    assert ui.panel.device.currentData() == "aa01" and "padrão" in ui.panel.device.itemText(0)
    assert FakeCapture.made[-1].device_id == "aa01" and FakeCapture.made[-1].running
    assert ui.panel.count.isEnabled() and ui.panel.btn_record.isEnabled()


def test_the_shortcut_is_free_and_opens_then_toggles(rig, ffmpeg_ok):
    ui = rig.ui
    assert narracao_ui.SHORTCUT == "Ctrl+Shift+R"
    others = [s for s in rig.win.findChildren(type(ui.shortcut)) if s is not ui.shortcut]
    assert narracao_ui.SHORTCUT not in {s.key().toString() for s in others}
    ui.shortcut.activated.emit()
    pump()
    assert ui.panel.isVisible() and ui.state == narracao_ui.IDLE
    ui.shortcut.activated.emit()
    assert ui.state == narracao_ui.RECORDING
    FakeCapture.made[-1].push(0.3)
    ui.shortcut.activated.emit()
    assert ui.state == narracao_ui.IDLE and len(rig.audio_clips()) == 1


def test_the_chosen_microphone_and_the_options_are_remembered(rig):
    ui = rig.ui
    rig.open()
    ui.panel.device.setCurrentIndex(1)
    ui.panel.device.activated.emit(1)
    assert FakeCapture.made[-1].device_id == "bb02"
    ui.panel.count.setChecked(True)
    ui.panel.play.setChecked(True)
    ui.panel.latency.setValue(80)
    s = prefs.settings()
    assert s.value(narracao_ui.PREF_DEVICE) == "bb02" and s.value(narracao_ui.PREF_COUNT) == "true"
    assert s.value(narracao_ui.PREF_PLAY) == "true" and int(s.value(narracao_ui.PREF_LATENCY)) == 80
    ui.panel.close()
    rig.open()
    assert ui.panel.device.currentData() == "bb02"
    assert FakeCapture.made[-1].device_id == "bb02"
    # sem nada gravado nas preferências: contagem e tocar ligados, atraso 0
    for key in (narracao_ui.PREF_COUNT, narracao_ui.PREF_PLAY, narracao_ui.PREF_LATENCY):
        s.remove(key)
    assert narracao_ui.as_bool(s.value(narracao_ui.PREF_COUNT)) and narracao_ui.as_bool(s.value(narracao_ui.PREF_PLAY))


def music(rig, seconds: float = 10.0):
    """Uma música na A1 (sem arquivo de verdade: só ocupa a faixa), para a narração não caber ali."""
    src = tl.Source(path="/x/musica.wav", width=0, height=0, fps=24.0, fps_str="24/1", frames=1, duration=seconds,
                    is_image=False, has_video=False, has_audio=True, codec="")
    rig.win.model.insert_media(src, at=0, atrack=0)
    rig.win.model.commit()


def test_recording_from_the_playhead_uses_the_free_track_in_one_selected_clip(rig, ffmpeg_ok):
    ui, w = rig.ui, rig.win
    cap = rig.open()
    w.frame_idx = 24
    steps = w.model.history._pos
    tracks = len(rig.seq.kind_tracks(tl.AUDIO))
    assert ui.start_recording() and ui.state == narracao_ui.RECORDING
    cap.push(2.0)
    pump(0.2)
    assert "00:" in ui.panel.big.text()
    take = ui.stop_recording()
    assert take is not None and take.frames == 96000
    (clip,) = rig.audio_clips()
    assert clip.start == 24 and clip.dur == 48 and w.model.selection == [clip.id]
    assert clip.src in rig.seq.sources and clip.src in w._sources       # na Mídia também
    assert clip.track == 0 and len(rig.seq.kind_tracks(tl.AUDIO)) == tracks   # a A1 estava livre: sem faixa nova
    assert w.model.history._pos == steps + 1
    y = read_wav(take.path)
    assert y.shape == (96000, 2) and abs(float(np.abs(y).max()) - 0.4) < 0.01
    assert ui.panel.btn_record.text() == "Gravar" and not ui.panel.big.text()


def test_without_a_free_track_a_narration_track_is_made_in_the_same_undo_step(rig, ffmpeg_ok):
    ui, w = rig.ui, rig.win
    music(rig)
    cap = rig.open()
    w.frame_idx = 24
    steps = w.model.history._pos
    tracks = len(rig.seq.kind_tracks(tl.AUDIO))
    ui.start_recording()
    cap.push(1.0)
    ui.stop_recording()
    (clip,) = [c for c in rig.audio_clips() if c.src != "/x/musica.wav"]
    assert clip.track == tracks and rig.seq.track(tl.AUDIO, clip.track).name == "Narração"
    assert w.model.selection == [clip.id] and w.model.history._pos == steps + 1    # a faixa e o clipe: um passo só
    w.model.undo()
    pump()
    assert len(rig.audio_clips()) == 1 and len(rig.seq.kind_tracks(tl.AUDIO)) == tracks
    w.model.redo()
    pump()
    assert len(rig.audio_clips()) == 2 and len(rig.seq.kind_tracks(tl.AUDIO)) == tracks + 1
    assert w.frame_idx == 24


def test_the_second_take_goes_to_the_same_narration_track_and_the_files_are_numbered(rig, ffmpeg_ok, tmp_path):
    ui, w = rig.ui, rig.win
    project = tmp_path / "filme.plc"
    w.project_path = str(project)
    music(rig)
    cap = rig.open()
    for start in (0, 100):
        w.frame_idx = start
        ui.start_recording()
        cap.push(1.0)
        ui.stop_recording()
    a, b = sorted((c for c in rig.audio_clips() if c.src != "/x/musica.wav"), key=lambda c: c.start)
    assert a.track == b.track == 1 and a.start == 0 and b.start == 100
    assert len(rig.seq.kind_tracks(tl.AUDIO)) == 2
    folder = tmp_path / "filme_narracao"
    assert sorted(p.name for p in folder.iterdir()) == ["narracao_001.wav", "narracao_002.wav"]
    assert Path(rig.seq.sources[a.src].path) == folder / "narracao_001.wav"
    assert "sem salvar" not in w.statusBar().currentMessage()


def test_without_a_saved_project_the_take_goes_to_the_app_folder_with_a_note(rig, ffmpeg_ok):
    ui, w = rig.ui, rig.win
    cap = rig.open()
    ui.start_recording()
    cap.push(0.5)
    take = ui.stop_recording()
    assert Path(take.path).parent == Path(_APP) / "PeliculaConverter" / "narracao" and Path(take.path).exists()
    assert "Projeto sem salvar" in w.statusBar().currentMessage()


def test_in_and_out_set_the_start_and_stop_by_themselves(rig, ffmpeg_ok):
    ui, w = rig.ui, rig.win
    cap = rig.open()
    w.frame_idx = 100
    w.inp, w.outp = 24, 72            # 2 s
    ui.start_recording()
    assert ui.start_frame == 24 and ui.max_s == pytest.approx(2.0)
    cap.push(1.0)
    pump(0.1)
    assert ui.state == narracao_ui.RECORDING
    cap.push(3.0)                      # passa da saída
    assert wait_for(lambda: ui.state == narracao_ui.IDLE)
    assert ui.state == narracao_ui.IDLE and ui.last_take.frames == 96000
    (clip,) = rig.audio_clips()
    assert clip.start == 24 and clip.dur == 48


def test_the_countdown_beeps_three_times_and_cancelling_it_leaves_nothing(rig):
    ui = rig.ui
    ui.panel.count.setChecked(True)
    cap = rig.open()
    assert ui.start_recording() and ui.state == narracao_ui.COUNTING and ui.panel.big.text() == "3"
    ui._count_tick()
    assert ui.panel.big.text() == "2"
    ui._count_tick()
    assert ui.panel.big.text() == "1" and rig.beeps == 3
    ui.toggle()                        # o botão cancela a contagem
    assert ui.state == narracao_ui.IDLE and ui.rec is None and not rig.audio_clips()
    assert not [p for p in Path(_APP).rglob("*.wav")]
    assert ui.start_recording()
    for _i in range(3):
        ui._count_tick()
    assert ui.state == narracao_ui.RECORDING and ui.rec is not None
    cap.push(0.3)
    ui.stop_recording()
    assert len(rig.audio_clips()) == 1


def test_playing_the_montage_along_starts_at_the_same_point_and_restores_the_loop(rig, ffmpeg_ok):
    ui, w = rig.ui, rig.win
    ui.panel.play.setChecked(True)
    cap = rig.open()
    w.frame_idx = 48
    w.btn_loop.setChecked(True)
    ui.start_recording()
    assert rig.played == [48] and not w.btn_loop.isChecked() and w.playing
    cap.push(0.5)
    ui.stop_recording()
    assert not w.playing and w.btn_loop.isChecked()
    ui.panel.play.setChecked(False)
    rig.played.clear()
    ui.start_recording()
    assert rig.played == []
    ui.discard()


def test_the_microphone_delay_cuts_the_start_to_the_sample(rig, ffmpeg_ok):
    ui = rig.ui
    ui.panel.latency.setValue(100)
    cap = rig.open()
    ui.start_recording()
    cap.push(1.0)
    take = ui.stop_recording()
    assert take.frames == 48000 - 4800


def test_the_level_meter_follows_the_microphone_before_and_during_the_recording(rig):
    ui = rig.ui
    cap = rig.open()
    cap.push(0.1, amp=0.5)
    ui._tick()
    assert -6.5 < ui.panel.level.level_db < -5.5 and ui.panel.level_text.text().startswith("−6")
    ui.start_recording()
    cap.push(0.1, amp=0.1)
    ui._tick()
    assert ui.panel.level.level_db < -5.5
    ui.discard()


def test_no_microphone_gives_a_clear_message_and_nothing_is_inserted(rig):
    ui = rig.ui
    ui.devices = lambda: []
    ui.open_panel()
    pump()
    assert not ui.panel.btn_record.isEnabled() and "Nenhum microfone" in ui.panel.status.text()
    assert not ui.start_recording() and not rig.audio_clips()


def test_a_microphone_that_fails_to_open_or_is_denied(rig, monkeypatch):
    ui = rig.ui

    def boom(ident, parent):
        raise RuntimeError("O microfone está em uso por outro programa.")
    ui.device_factory = boom
    ui.open_panel()
    assert "em uso" in ui.panel.status.text() and not ui.panel.btn_record.isEnabled()
    assert not ui.start_recording() and not rig.audio_clips()
    ui.device_factory = lambda ident, parent: FakeCapture(ident, parent)
    monkeypatch.setattr(narracao_ui, "microphone_denied", lambda app: True)
    ui.open_panel()
    assert "não deixou" in ui.panel.status.text() and not ui.panel.btn_record.isEnabled()
    assert not ui.start_recording() and not rig.audio_clips()


def test_the_microphone_dropping_out_discards_the_recording(rig, ffmpeg_ok):
    ui = rig.ui
    cap = rig.open()
    ui.start_recording()
    cap.push(0.5)
    partial = ui.rec.rec.partial
    assert os.path.exists(partial)
    steps = rig.win.model.history._pos
    cap.failed.emit("O microfone parou de responder.")
    assert ui.state == narracao_ui.IDLE and "descartada" in ui.panel.status.text() and not os.path.exists(partial)
    assert not rig.audio_clips() and rig.win.model.history._pos == steps and ui.rec is None
    assert not [p for p in Path(_APP).rglob("narracao_*")]


def test_unplugging_the_microphone_while_recording_discards_it(rig, ffmpeg_ok):
    ui = rig.ui
    ui.panel.device.blockSignals(True)
    cap = rig.open()
    ui.panel.device.setCurrentIndex(1)
    ui.panel.device.activated.emit(1)
    cap = FakeCapture.made[-1]
    ui.start_recording()
    cap.push(0.3)
    ui.devices = lambda: [DEVICES[0]]       # só o embutido: o USB saiu
    ui.devices_changed()
    assert ui.state == narracao_ui.IDLE and "desconectado" in ui.panel.status.text() and not rig.audio_clips()


def test_stopping_without_any_sound_inserts_nothing(rig):
    ui = rig.ui
    rig.open()
    ui.start_recording()
    assert ui.stop_recording() is None
    assert "Nada foi gravado" in ui.panel.status.text() and not rig.audio_clips()
    assert not [p for p in Path(_APP).rglob("narracao_*")]


def test_loud_and_quiet_takes_are_flagged(rig, ffmpeg_ok):
    ui = rig.ui
    cap = rig.open()
    ui.start_recording()
    cap.push(0.3, amp=1.0)
    ui.stop_recording()
    assert "estourou" in ui.panel.status.text()
    ui.start_recording()
    cap.push(0.3, amp=0.003)
    ui.stop_recording()
    assert "muito baixa" in ui.panel.status.text()


def test_a_silent_microphone_is_pointed_out(rig):
    ui = rig.ui
    cap = rig.open()
    ui.start_recording()
    cap.push(2.0, amp=0.0)
    assert wait_for(lambda: ui.rec.silent_run > 80000)    # a thread do gravador conta os zeros
    ui._tick()
    assert "só está mandando silêncio" in ui.panel.status.text()
    ui.discard()


def test_closing_the_panel_while_recording_asks_and_discarding_leaves_nothing(rig, monkeypatch):
    ui = rig.ui
    cap = rig.open()
    ui.start_recording()
    cap.push(0.3)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    ui.panel.close()
    assert ui.panel.isVisible() and ui.state == narracao_ui.RECORDING
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    ui.panel.close()
    assert not ui.panel.isVisible() and ui.state == narracao_ui.IDLE and not rig.audio_clips()
    assert not cap.running                  # o microfone foi solto
    assert not [p for p in Path(_APP).rglob("narracao_*")]


def test_the_recording_is_a_normal_audio_clip_with_no_new_json_field(rig, ffmpeg_ok):
    ui = rig.ui
    cap = rig.open()
    ui.start_recording()
    cap.push(0.5)
    ui.stop_recording()
    js = rig.seq.to_json()
    assert not any(k for k in js if "narr" in k.lower())
    assert all("narr" not in str(f).lower() for f in rig.seq.features())


def test_the_real_capture_watches_the_device_without_the_state_signal():
    """O `QtCapture` de verdade não liga o `stateChanged` (o PySide6 6.12 não converte `QAudio::State` e cada mudança de
    estado virava um relatório de erro ao começar a gravar): a falha do microfone é vista pela checagem de `error()`, e
    avisa uma vez só. Sem dispositivo: a fonte é falsa."""
    import inspect
    assert ".stateChanged.connect" not in inspect.getsource(narracao_ui.QtCapture)
    from PySide6.QtCore import QTimer
    from PySide6.QtMultimedia import QAudio

    class Source:
        err = QAudio.Error.NoError

        def error(self):
            return self.err

        def stop(self):
            pass

    cap = narracao_ui.QtCapture.__new__(narracao_ui.QtCapture)
    QObject.__init__(cap)
    cap.source, cap.io = Source(), object()
    cap._watch = QTimer(cap)
    got = []
    cap.failed.connect(got.append)
    cap._watch.start(250)
    cap._check()
    assert got == [] and cap._watch.isActive()        # tudo bem: nada
    cap.source.err = QAudio.Error.OpenError
    cap._check()
    assert got == ["O microfone parou de responder."] and not cap._watch.isActive()
    cap.stop()
    assert cap.io is None
