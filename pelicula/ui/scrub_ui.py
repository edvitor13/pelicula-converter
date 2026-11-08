"""Som ao arrastar o cursor (1.8, ARQUITETURA §43.5): arrastando o cursor na régua da linha do tempo ou andando quadro a
quadro (← →, K + J/L), toca um grão curto da mixagem no quadro novo.

O grão sai do WAV da mixagem da prévia que já existe (`MainWindow._mix_path`, lido com `audiomix.WavReader`): nada é
mixado na interface. Sem mixagem pronta (ainda mixando, ou o arquivo aberto no modo Película), nada toca. Ele vai por um
`QAudioSink` próprio, de latência baixa, separado do player da prévia, e respeita o mudo e o volume da prévia. Um grão
novo só sai depois que o anterior acabou de tocar (`Throttle`): arrastar rápido não enfileira som.

Sem módulo: é parte da linha do tempo, como o próprio cursor, e tem o botão para desligar (preferência `PREF_KEY`).
"""

from __future__ import annotations

import os
import time

import numpy as np
from PySide6.QtCore import QObject

from .. import audiomix
from . import prefs

PREF_KEY = "som_ao_arrastar"   # "true"/"false"; sem valor = ligado
GRAIN_MIN_S = 0.040            # um quadro, mas nunca menos que isto
FADE_S = 0.005                 # entrada e saída do grão (sem estalo)
RATE = audiomix.RATE


def grain_span(frame: int, fps: float, rate: int = RATE) -> tuple[int, int]:
    """(primeira amostra, quantas) do grão do quadro: um quadro, no mínimo `GRAIN_MIN_S`."""
    start = int(round(frame / fps * rate))
    return start, max(int(round(rate / fps)), int(round(GRAIN_MIN_S * rate)))


def make_grain(x: np.ndarray, rate: int = RATE) -> np.ndarray:
    """O grão com fades de `FADE_S` nas duas pontas (float32, n × canais). Puro: os testes conferem sem tocar nada."""
    x = np.array(x, np.float32, copy=True).reshape(len(x), -1)
    n = len(x)
    k = min(int(round(FADE_S * rate)), n // 2)
    if k > 0:
        ramp = (np.arange(k, dtype=np.float32) + 0.5) / k
        x[:k] *= ramp[:, None]
        x[n - k:] *= ramp[::-1, None]
    return x


def to_pcm16(x: np.ndarray, volume: float = 1.0) -> bytes:
    """Inteiros de 16 bits intercalados para o `QAudioSink`."""
    return (np.clip(np.asarray(x, np.float32) * float(volume), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


class Throttle:
    """Deixa sair um grão novo só quando o anterior acabou de tocar."""

    def __init__(self):
        self.busy_until = 0.0

    def ready(self, now: float) -> bool:
        return now >= self.busy_until

    def played(self, now: float, seconds: float) -> None:
        self.busy_until = now + seconds


def _qt_sink(parent):
    """(sink, dispositivo de escrita) num `QAudioSink` de 48 kHz estéreo em 16 bits; None sem saída de som. Sem tela
    (`QT_QPA_PLATFORM=offscreen`: testes e automações) também None: ali nada toca nos alto-falantes."""
    if os.environ.get("QT_QPA_PLATFORM", "") == "offscreen":
        return None
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    dev = QMediaDevices.defaultAudioOutput()
    if dev.isNull():
        return None
    fmt = QAudioFormat()
    fmt.setSampleRate(RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    if not dev.isFormatSupported(fmt):
        return None
    sink = QAudioSink(dev, fmt, parent)
    sink.setBufferSize(RATE * 4 // 5)   # 200 ms: cabe um grão com folga, sem atrasar o próximo
    io = sink.start()
    return (sink, io) if io is not None else None


class ScrubUI(QObject):
    """O botão "Som ao arrastar o cursor" e os grãos. `sink_factory(parent)` → (sink, io) ou None (os testes trocam)."""

    def __init__(self, win, sink_factory=_qt_sink):
        super().__init__(win)
        self.win = win
        self.sink_factory = sink_factory
        self.throttle = Throttle()
        self.dragging = False
        self._sink = None
        self._reader: tuple[str, audiomix.WavReader | None] = ("", None)
        self.button = win.tl_editor.btn_scrub
        self.button.setChecked(str(prefs.settings().value(PREF_KEY, "true")) != "false")
        self.button.toggled.connect(self._toggled)
        win.tl_editor.scrubbing.connect(self._scrubbing)

    @property
    def enabled(self) -> bool:
        return self.button.isChecked()

    def _toggled(self, on: bool) -> None:
        prefs.settings().setValue(PREF_KEY, "true" if on else "false")

    def _scrubbing(self, on: bool) -> None:
        self.dragging = bool(on)

    # ------------------------------------------------------------ ganchos da janela
    def on_seek(self, frame: int) -> None:
        """`MainWindow.seek`: só toca arrastando o cursor na régua (um clique num marcador não faz som)."""
        if self.dragging:
            self.play(frame)

    def on_step(self, frame: int) -> None:
        """`MainWindow.step`: andar quadro a quadro."""
        self.play(frame)

    # ------------------------------------------------------------ o grão
    def _path(self) -> str:
        w = self.win
        return w._mix_path if w._audio_src[0] == "seq" else ""

    def _wav(self, path: str) -> audiomix.WavReader | None:
        if self._reader[0] != path:
            try:
                self._reader = (path, audiomix.WavReader(path))
            except (OSError, ValueError):
                self._reader = (path, None)
        return self._reader[1]

    def grain_for(self, frame: int) -> np.ndarray | None:
        """O grão do quadro, lido da mixagem da prévia (None sem mixagem pronta)."""
        w = self.win
        path = self._path()
        if not path or w.info is None:
            return None
        reader = self._wav(path)
        if reader is None:
            return None
        start, count = grain_span(frame, w.info.fps, reader.rate)
        try:
            x = reader.read(start, count)
        except OSError:
            return None
        return make_grain(x, reader.rate) if len(x) else None

    def play(self, frame: int, now: float | None = None) -> bool:
        """Toca o grão do quadro se der (ligado, parado, com som e sem outro grão tocando). True se tocou."""
        w = self.win
        if not self.enabled or w.playing or w.btn_mute.isChecked():
            return False
        now = time.monotonic() if now is None else now
        if not self.throttle.ready(now):
            return False
        x = self.grain_for(frame)
        if x is None:
            return False
        if self._sink is None:
            try:
                self._sink = self.sink_factory(self) or False
            except Exception:  # noqa: BLE001 — sem saída de som: o scrub fica mudo, nada mais muda
                self._sink = False
        if not self._sink:
            return False
        _sink, io = self._sink
        io.write(to_pcm16(x, w.vol.value()))
        self.throttle.played(now, len(x) / RATE)
        return True


def install(win) -> ScrubUI:
    return ScrubUI(win)
