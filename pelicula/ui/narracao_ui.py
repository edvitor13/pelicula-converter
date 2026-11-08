"""Gravar narração (1.8, ARQUITETURA §48): o botão do microfone na barra da linha do tempo (ou Ctrl+Shift+R) abre um painel
pequeno, que continua aberto enquanto se trabalha: microfone, medidor de nível, "Contagem antes de gravar", "Tocar a montagem
enquanto grava", compensação do atraso do microfone e Gravar / Parar.

A gravação começa no cursor (ou na entrada, se marcada) e para sozinha na saída. O áudio vem do `QAudioSource` na thread da
interface só até a fila (`readyRead` → `BackgroundRecorder.feed`); a conversão, o resample de 48 kHz e a escrita do WAV ficam
na thread do gravador (`pelicula/narracao.py`). Ao parar, o WAV entra na Mídia e na primeira faixa de áudio livre ali (uma
"Narração" nova se não há) num passo só do desfazer, já selecionado. Erros (sem microfone, acesso negado, microfone que sumiu)
viram uma mensagem clara e nada é inserido.

Arquivos: `<projeto>_narracao/narracao_001.wav` ao lado do projeto salvo; sem projeto salvo, `narracao/` na pasta do app (os
arquivos não se mexem quando o projeto é salvo depois). Os testes trocam o microfone, a lista de dispositivos e o bipe
(`device_factory`, `devices`, `beep`): nenhum dispositivo de verdade é aberto.

Preferências (`prefs.settings()`): `narracao/dispositivo` (id do microfone, em hexadecimal), `narracao/contagem`,
`narracao/tocar` ("true"/"false"; ligados por padrão) e `narracao/atraso_ms` (0 a 500).
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .. import media, narracao
from ..i18n import _, fmt_decimal
from ..timeline import AUDIO
from . import prefs, scrub_ui, theme
from .meter import FLOOR, RED_DB, YELLOW_DB, level_to_t

SHORTCUT = "Ctrl+Shift+R"     # abre o painel; com ele aberto, grava / para (livre em `MainWindow._shortcuts`)
PREF_DEVICE = "narracao/dispositivo"
PREF_COUNT = "narracao/contagem"
PREF_PLAY = "narracao/tocar"
PREF_LATENCY = "narracao/atraso_ms"
COUNT_FROM = 3                # segundos de contagem
POLL_MS = 33
SILENT_S = 1.5                # tanto tempo só de zeros exatos: provável bloqueio do sistema
LATENCY_MAX = 500
CLIP_PEAK, LOW_PEAK = 0.99, 0.01

IDLE, COUNTING, RECORDING = "parado", "contagem", "gravando"


def as_bool(value, default: bool = True) -> bool:
    return default if value is None or str(value) == "" else str(value).lower() not in ("false", "0")


def fmt_clock(seconds: float) -> str:
    """"01:23,4": minutos, segundos e décimos."""
    m, s = divmod(max(0.0, seconds), 60.0)
    return f"{int(m):02d}:{fmt_decimal(s, 1).rjust(4, '0')}"


# ------------------------------------------------------------------ microfones
def input_devices() -> list[tuple[str, str, bool]]:
    """[(id em hexadecimal, nome, é o padrão do sistema)] dos microfones. Sem multimídia ou sem dispositivo: []."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
        default = bytes(QMediaDevices.defaultAudioInput().id())
        return [(bytes(d.id()).hex(), d.description(), bytes(d.id()) == default) for d in QMediaDevices.audioInputs()]
    except Exception:  # noqa: BLE001 — sem QtMultimedia: lista vazia, o painel explica
        return []


_SAMPLE_FORMATS = {"UInt8": "uint8", "Int16": "int16", "Int32": "int32", "Float": "float32"}


class QtCapture(QObject):
    """Um `QAudioSource` no formato que o próprio microfone prefere. `data(bytes)` a cada pedaço, `failed(texto)` se o
    dispositivo falhar. `rate`, `channels` e `fmt` dizem como são os bytes (para `narracao.Recorder`)."""

    data = Signal(bytes)
    failed = Signal(str)

    def __init__(self, device_id: str, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        want = bytes.fromhex(device_id) if device_id else b""
        dev = next((d for d in QMediaDevices.audioInputs() if bytes(d.id()) == want), QMediaDevices.defaultAudioInput())
        if dev.isNull():
            raise RuntimeError(_("Nenhum microfone encontrado."))
        fmt = dev.preferredFormat()
        name = _SAMPLE_FORMATS.get(fmt.sampleFormat().name)
        if name is None or fmt.channelCount() < 1 or fmt.sampleRate() < 8000:   # formato que não dá para ler: pede um simples
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            name = "int16"
            if not dev.isFormatSupported(fmt):
                raise RuntimeError(_("Este microfone não entrega um formato de som que o app consiga ler."))
        self.rate, self.channels, self.fmt = fmt.sampleRate(), fmt.channelCount(), name
        self.source = QAudioSource(dev, fmt, self)
        self.source.stateChanged.connect(self._state)
        self.io = None

    def start(self) -> None:
        self.io = self.source.start()
        if self.io is None:
            self.failed.emit(_("Não foi possível abrir o microfone."))
            return
        self.io.readyRead.connect(self._ready)

    def _ready(self) -> None:
        chunk = bytes(self.io.readAll())
        if chunk:
            self.data.emit(chunk)

    def _state(self, _state) -> None:
        """O dispositivo parou sozinho com erro (desconectado, tomado por outro programa)?"""
        from PySide6.QtMultimedia import QAudio
        if self.io is not None and self.source.error() != QAudio.Error.NoError:
            self.failed.emit(_("O microfone parou de responder."))

    def stop(self) -> None:
        try:
            self.source.stateChanged.disconnect(self._state)
        except (RuntimeError, TypeError):
            pass
        self.source.stop()
        self.io = None


def microphone_denied(app) -> bool | None:
    """True se o sistema recusou o microfone ao app; None (ainda não decidido) pede a permissão; False se pode usar. Windows e
    Linux costumam responder "pode"; a pergunta existe para os sistemas que perguntam."""
    try:
        from PySide6.QtCore import QMicrophonePermission
        status = app.checkPermission(QMicrophonePermission())
    except Exception:  # noqa: BLE001 — sem a API de permissões: tenta abrir mesmo assim
        return False
    if status == Qt.PermissionStatus.Denied:
        return True
    return None if status == Qt.PermissionStatus.Undetermined else False


class Beeper:
    """Os bipes da contagem, por um `QAudioSink` (o mesmo cuidado do scrub: sem tela, nada toca)."""

    def __init__(self, parent):
        self.parent = parent
        self._sink = None

    def __call__(self) -> None:
        if self._sink is None:
            try:
                self._sink = scrub_ui._qt_sink(self.parent) or False
            except Exception:  # noqa: BLE001
                self._sink = False
        if not self._sink:
            return
        t = np.arange(int(0.06 * scrub_ui.RATE)) / scrub_ui.RATE
        tone = 0.25 * np.sin(2 * np.pi * 880.0 * t)
        self._sink[1].write(scrub_ui.to_pcm16(scrub_ui.make_grain(np.stack([tone, tone], axis=1))))


# ------------------------------------------------------------------ painel
class LevelBar(QWidget):
    """Barra horizontal do nível do microfone (dBFS, retenção do pico, vermelho perto do estouro)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.level_db = FLOOR
        self.hold_db = FLOOR
        self._hold_t = 0.0

    def set_level(self, peak_db: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        peak_db = max(FLOOR, peak_db)
        self.level_db = max(peak_db, self.level_db - 1.2)    # cai devagar (a barra não treme)
        if peak_db >= self.hold_db or now - self._hold_t > 1.5:
            self.hold_db, self._hold_t = peak_db, now
        self.update()

    def reset(self) -> None:
        self.level_db = self.hold_db = FLOOR
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        t = level_to_t(self.level_db)
        color = theme.METER_HIGH if self.level_db >= RED_DB else theme.METER_MID if self.level_db >= YELLOW_DB else theme.METER_LOW
        p.fillRect(QRectF(0, 0, w * t, h), QColor(color))
        x = w * level_to_t(self.hold_db)
        p.fillRect(QRectF(max(0.0, x - 2), 0, 2, h), QColor(theme.TEXT))
        p.setPen(QColor(theme.BORDER))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class NarrationPanel(QDialog):
    """Só os controles; `NarrationUI` liga tudo."""

    toggled = Signal()
    closing = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle(_("Gravar narração"))
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setModal(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        kicker = QLabel(_("GRAVAR NARRAÇÃO"))
        kicker.setObjectName("Kicker")
        lay.addWidget(kicker)
        form = QFormLayout()
        form.setSpacing(6)
        self.device = QComboBox()
        self.device.setToolTip(_("O microfone que grava. Fica lembrado para a próxima vez."))
        form.addRow(_("Microfone:"), self.device)
        row = QHBoxLayout()
        self.level = LevelBar()
        self.level_text = QLabel("−∞ dB")
        self.level_text.setObjectName("Muted")
        self.level_text.setMinimumWidth(56)
        row.addWidget(self.level, 1)
        row.addWidget(self.level_text)
        form.addRow(_("Nível:"), row)
        lay.addLayout(form)
        self.count = QCheckBox(_("Contagem antes de gravar"))
        self.count.setToolTip(_("3, 2, 1 antes de começar: dá tempo de respirar e de pôr os fones."))
        self.play = QCheckBox(_("Tocar a montagem enquanto grava"))
        self.play.setToolTip(_("A prévia toca a partir de onde a gravação começa, para você falar em cima das imagens."))
        tip = QLabel(_("Use fones de ouvido: o som da montagem nos alto-falantes entra no microfone."))
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        lay.addWidget(self.count)
        lay.addWidget(self.play)
        lay.addWidget(tip)
        self.latency = QSpinBox()
        self.latency.setRange(0, LATENCY_MAX)
        self.latency.setSuffix(" ms")
        self.latency.setToolTip(_(
            "O som do microfone chega alguns milissegundos depois de acontecer, e a prévia também demora a começar: a fala "
            "grava atrasada em relação às imagens. Para medir, ponha o cursor num bipe (Novo ▸ Contagem tem um) ou numa "
            "batida, grave uma palma junto com ele, e veja na forma de onda quantos milissegundos a palma ficou depois. "
            "Digite esse valor aqui: o começo da gravação é cortado por ele, ao milésimo de segundo."))
        lat_row = QFormLayout()
        lat_row.addRow(_("Compensar o atraso do microfone:"), self.latency)
        lay.addLayout(lat_row)
        self.big = QLabel("")
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setStyleSheet("font-size: 22pt; font-weight: 600;")
        self.big.setMinimumHeight(48)
        lay.addWidget(self.big)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)
        buttons = QHBoxLayout()
        self.btn_record = QPushButton(_("Gravar"))
        self.btn_record.setDefault(True)
        self.btn_record.clicked.connect(self.toggled)
        self.btn_close = QPushButton(_("Fechar"))
        self.btn_close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_record)
        buttons.addWidget(self.btn_close)
        lay.addLayout(buttons)
        self.setMinimumWidth(380)
        self.closing_ok = True

    def sizeHint(self) -> QSize:
        return QSize(420, 360)

    def closeEvent(self, e):
        self.closing_ok = True
        self.closing.emit()     # quem controla pode recusar (gravação em andamento): `closing_ok = False`
        e.accept() if self.closing_ok else e.ignore()


# ------------------------------------------------------------------ o controle
class NarrationUI(QObject):
    """O botão, o atalho e a gravação. `device_factory(id_hex, parent)` → objeto com `rate`, `channels`, `fmt`, `data`, `failed`,
    `start()`, `stop()` (levanta RuntimeError com a mensagem se não abre); `devices()` → [(id, nome, padrão)]; `beep()`.
    Os testes trocam os três."""

    def __init__(self, win, device_factory=QtCapture, devices=input_devices, beep=None):
        super().__init__(win)
        self.win = win
        self.device_factory = device_factory
        self.devices = devices
        self.beep = beep or Beeper(self)
        self.panel = NarrationPanel(win)
        self.button = win.tl_editor.btn_narrar
        self.button.clicked.connect(self.open_panel)
        self.state = IDLE
        self.capture = None
        self.rec: narracao.BackgroundRecorder | None = None
        self.take: str = ""
        self.start_frame = 0
        self.seq_id = ""
        self.counter = 0
        self.notes: list[str] = []
        self._loop = None
        self.last_message = ""
        self.max_s = None
        self._monitor = narracao.Level()
        self._monitor_t = 0.0
        self.last_take: narracao.Take | None = None

        s = prefs.settings()
        self.panel.count.setChecked(as_bool(s.value(PREF_COUNT)))
        self.panel.play.setChecked(as_bool(s.value(PREF_PLAY)))
        try:
            self.panel.latency.setValue(min(max(int(float(s.value(PREF_LATENCY, 0))), 0), LATENCY_MAX))
        except (TypeError, ValueError):
            self.panel.latency.setValue(0)
        self.panel.count.toggled.connect(lambda on: prefs.settings().setValue(PREF_COUNT, "true" if on else "false"))
        self.panel.play.toggled.connect(lambda on: prefs.settings().setValue(PREF_PLAY, "true" if on else "false"))
        self.panel.latency.valueChanged.connect(lambda v: prefs.settings().setValue(PREF_LATENCY, int(v)))
        self.panel.device.activated.connect(self._device_chosen)
        self.panel.toggled.connect(self.toggle)
        self.panel.closing.connect(self._panel_closing)

        sc = QShortcut(QKeySequence(SHORTCUT), win)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self._shortcut)
        self.shortcut = sc

        self.poll = QTimer(self)
        self.poll.setInterval(POLL_MS)
        self.poll.timeout.connect(self._tick)
        self.count_timer = QTimer(self)
        self.count_timer.setInterval(1000)
        self.count_timer.timeout.connect(self._count_tick)
        try:
            from PySide6.QtMultimedia import QMediaDevices
            self._media_devices = QMediaDevices(self)
            self._media_devices.audioInputsChanged.connect(self.devices_changed)
        except Exception:  # noqa: BLE001
            self._media_devices = None
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    # ------------------------------------------------------------ painel e microfone
    @property
    def recording(self) -> bool:
        return self.state != IDLE

    def _shortcut(self) -> None:
        if self.win.mode != "edicao":
            return
        if self.panel.isVisible():
            self.toggle()
        else:
            self.open_panel()

    def open_panel(self) -> None:
        self._fill_devices()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self._open_capture()

    def _fill_devices(self) -> None:
        combo = self.panel.device
        saved = str(prefs.settings().value(PREF_DEVICE, "") or "")
        found = self.devices()
        combo.blockSignals(True)
        combo.clear()
        for ident, name, is_default in found:
            combo.addItem(name + (_(" (padrão)") if is_default else ""), ident)
        pick = next((i for i, (ident, _n, _d) in enumerate(found) if ident == saved), None)
        if pick is None:
            pick = next((i for i, (_i, _n, d) in enumerate(found) if d), 0)
        if found:
            combo.setCurrentIndex(pick)
        combo.blockSignals(False)
        combo.setEnabled(bool(found))

    def current_device(self) -> str:
        return str(self.panel.device.currentData() or "")

    def _device_chosen(self, _index: int = 0) -> None:
        prefs.settings().setValue(PREF_DEVICE, self.current_device())
        if self.recording:
            return
        self._open_capture()

    def _close_capture(self) -> None:
        if self.capture is not None:
            try:
                self.capture.data.disconnect(self._on_data)
                self.capture.failed.disconnect(self._on_failed)
            except (RuntimeError, TypeError):
                pass
            self.capture.stop()
            self.capture.deleteLater()
            self.capture = None
        self.poll.stop()

    def _open_capture(self) -> bool:
        """Abre o microfone escolhido (o medidor anda desde já). False, com a mensagem no painel, se não deu."""
        self._close_capture()
        self.panel.level.reset()
        if self.panel.device.count() == 0:
            self._say(_("Nenhum microfone encontrado. Conecte um e abra o painel de novo."), error=True)
            self.panel.btn_record.setEnabled(False)
            return False
        denied = microphone_denied(QApplication.instance())
        if denied:
            self._say(_("O sistema não deixou o app usar o microfone. Libere o acesso nas configurações de privacidade do "
                        "sistema e tente de novo."), error=True)
            self.panel.btn_record.setEnabled(False)
            return False
        try:
            cap = self.device_factory(self.current_device(), self)
            cap.data.connect(self._on_data)
            cap.failed.connect(self._on_failed)
            cap.start()
        except Exception as exc:  # noqa: BLE001 — dispositivo ocupado, formato estranho, sem multimídia…
            self._say(str(exc) or _("Não foi possível abrir o microfone."), error=True)
            self.panel.btn_record.setEnabled(False)
            return False
        self.capture = cap
        self.panel.btn_record.setEnabled(True)
        self._say(_("Pronto. A gravação começa no cursor da linha do tempo."))
        self.poll.start()
        return True

    def devices_changed(self) -> None:
        """Microfone ligado ou desligado com o painel aberto."""
        if not self.panel.isVisible():
            return
        gone = self.current_device()
        self._fill_devices()
        if self.recording:
            if gone and self.current_device() != gone:
                self.fail_recording(_("O microfone foi desconectado. A gravação foi descartada e nada foi inserido."))
            return
        self._open_capture()

    # ------------------------------------------------------------ o som que chega
    def _on_data(self, data: bytes) -> None:
        cap = self.capture
        self._monitor = narracao.block_level(data, cap.fmt, cap.channels)
        self._monitor_t = time.monotonic()
        if self.rec is not None:
            self.rec.feed(data)

    def _on_failed(self, why: str) -> None:
        if self.recording:
            self.fail_recording(_("{erro} A gravação foi descartada e nada foi inserido.").format(erro=why))
        else:
            self._say(why, error=True)
            self.panel.btn_record.setEnabled(False)

    def _tick(self) -> None:
        """A cada 33 ms: o medidor, o relógio, o fim na saída e os avisos."""
        lv = self._monitor if time.monotonic() - self._monitor_t < 0.15 else narracao.Level()
        self.panel.level.set_level(lv.peak_db)
        shown = self.panel.level.level_db
        self.panel.level_text.setText(("−∞" if shown <= FLOOR else fmt_decimal(shown, 1).replace("-", "−")) + " dB")
        rec = self.rec
        if rec is None:
            return
        if rec.error:
            self.fail_recording(_("Não foi possível gravar o arquivo: {erro}").format(erro=rec.error))
        elif rec.full:
            self.stop_recording()
        else:
            self.panel.big.setText(fmt_clock(rec.seconds))
            if self.capture is not None and rec.silent_run > SILENT_S * self.capture.rate:
                self.panel.status.setText(_("O microfone só está mandando silêncio. Veja se ele está mudo no sistema ou "
                                            "se o acesso ao microfone está liberado."))

    def _say(self, text: str, error: bool = False) -> None:
        self.last_message = text
        self.panel.status.setText(text)
        self.panel.status.setStyleSheet(f"color: {theme.DANGER};" if error else "")

    # ------------------------------------------------------------ gravar
    def toggle(self) -> None:
        if self.state == IDLE:
            self.start_recording()
        elif self.state == COUNTING:
            self.cancel_count()
        else:
            self.stop_recording()

    def _target(self) -> Path | None:
        """O arquivo da gravação: ao lado do projeto salvo, ou na pasta do app (sem projeto, ou se a pasta do projeto não
        deixa gravar)."""
        project = getattr(self.win, "project_path", None)
        folder, beside = narracao.take_folder(project)
        self.notes = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = narracao.next_take_path(folder)
            probe.with_suffix(".tmp").touch()
            probe.with_suffix(".tmp").unlink()
        except OSError:
            if not beside:
                self._say(_("Não foi possível criar a pasta das gravações."), error=True)
                return None
            folder, beside = narracao.take_folder(None)
            self.notes.append(_("A pasta do projeto não aceitou a gravação."))
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._say(_("Não foi possível criar a pasta das gravações."), error=True)
                return None
        if not beside:
            self.notes.append(_("Projeto sem salvar: a gravação ficou em {pasta}.").format(pasta=folder))
        return narracao.next_take_path(folder)

    def start_recording(self) -> bool:
        """Gravar: escolhe o ponto de partida, a contagem (se ligada) e, no fim dela, abre o arquivo e toca a montagem."""
        w = self.win
        if self.state != IDLE or w.mode != "edicao":
            return False
        if self.capture is None and not self._open_capture():
            return False
        seq = w.model.seq
        w.stop_play()
        self.start_frame, self.max_s = narracao.plan_span(w.frame_idx, w.inp, w.outp, seq.fps)
        path = self._target()
        if path is None:
            return False
        self.take = str(path)
        self.seq_id = seq.id
        if self.start_frame != w.frame_idx and w.info is not None:
            w.seek(self.start_frame)
        self.panel.device.setEnabled(False)
        self.panel.btn_record.setText(_("Parar"))
        if self.panel.count.isChecked():
            self.state = COUNTING
            self.counter = COUNT_FROM
            self._show_count()
            self.count_timer.start()
        else:
            self._begin()
        return True

    def _show_count(self) -> None:
        self.panel.big.setText(str(self.counter))
        self._say(_("Gravando em {n}… (o botão cancela)").format(n=self.counter))
        self.beep()

    def _count_tick(self) -> None:
        self.counter -= 1
        if self.counter > 0:
            self._show_count()
        else:
            self.count_timer.stop()
            self._begin()

    def cancel_count(self) -> None:
        self.count_timer.stop()
        self._idle(_("Contagem cancelada."))

    def _begin(self) -> None:
        """Abre o arquivo e começa: a gravação e a prévia partem juntas, do mesmo ponto."""
        w, cap = self.win, self.capture
        if cap is None:
            self._idle(_("O microfone não está aberto."), error=True)
            return
        try:
            self.rec = narracao.BackgroundRecorder(self.take, cap.rate, cap.channels, cap.fmt,
                                                   skip_s=self.panel.latency.value() / 1000.0, max_s=self.max_s)
        except OSError as exc:
            self._idle(_("Não foi possível gravar o arquivo: {erro}").format(erro=exc), error=True)
            return
        self.state = RECORDING
        self._loop = w.btn_loop.isChecked()
        if self._loop:
            w.btn_loop.setChecked(False)    # a prévia não volta ao começo no meio da fala
        if self.panel.play.isChecked() and w.info is not None:
            w.start_play(self.start_frame)
        self._say(_("Gravando a partir do quadro {n}. Parar termina e insere na linha do tempo.").format(n=self.start_frame))

    def _restore_loop(self) -> None:
        if self._loop is not None:
            self.win.btn_loop.setChecked(self._loop)
            self._loop = None

    def _idle(self, text: str = "", error: bool = False) -> None:
        self.state = IDLE
        self.count_timer.stop()
        self.panel.device.setEnabled(self.panel.device.count() > 0)
        self.panel.btn_record.setText(_("Gravar"))
        self.panel.big.setText("")
        if text:
            self._say(text, error)

    def fail_recording(self, why: str) -> None:
        """A gravação não pode continuar (microfone sumiu, disco): descarta tudo e avisa. Nada é inserido."""
        rec, self.rec = self.rec, None
        self.win.stop_play()
        self._restore_loop()
        if rec is not None:
            rec.cancel()
        self._idle(why, error=True)
        self.win.statusBar().showMessage(why, 10000)

    def discard(self) -> None:
        """Descarta a gravação em andamento (ou a contagem) sem inserir nada."""
        if self.state == COUNTING:
            self.cancel_count()
            return
        rec, self.rec = self.rec, None
        if self.state == RECORDING:
            self.win.stop_play()
            self._restore_loop()
        if rec is not None:
            rec.cancel()
        self._idle(_("Gravação descartada."))

    def stop_recording(self) -> narracao.Take | None:
        """Parar: fecha o WAV, põe na Mídia e na linha do tempo (um passo do desfazer) e leva o cursor ao começo dela."""
        if self.state != RECORDING or self.rec is None:
            return None
        rec, self.rec = self.rec, None
        w = self.win
        w.stop_play()
        self._restore_loop()
        try:
            take = rec.finish()
        except OSError as exc:
            self._idle(_("Não foi possível gravar o arquivo: {erro}").format(erro=exc), error=True)
            return None
        self._idle()
        if take is None:
            self._say(_("Nada foi gravado."), error=True)
            return None
        self.last_take = take
        self._insert(take)
        return take

    def _insert(self, take: narracao.Take) -> None:
        w = self.win
        try:
            src = w.adopt_source(media.probe_source(take.path))
        except Exception as exc:  # noqa: BLE001
            self._say(_("A gravação ficou em {caminho}, mas não deu para abri-la: {erro}").format(caminho=take.path,
                                                                                                erro=exc), error=True)
            return
        model = w.model
        if model.seq.id != self.seq_id:     # outro projeto ou sequência abriu durante a gravação: só fica na Mídia
            self._say(_("A montagem mudou durante a gravação. O arquivo está na Mídia: {caminho}").format(
                caminho=take.path), error=True)
            return
        model.commit()    # o que estava pendente não entra no passo da gravação
        track, new = narracao.place_take(model.seq, src, self.start_frame)
        made = model.insert_media(src, at=self.start_frame, atrack=track)
        if not made:
            self._say(_("Não foi possível pôr a gravação na linha do tempo."), error=True)
            return
        w.seek(self.start_frame)
        extra = ""
        if take.peak >= CLIP_PEAK:
            extra = " " + _("O som estourou: diminua o volume do microfone nas configurações do sistema e grave de novo.")
        elif take.peak < LOW_PEAK:
            extra = " " + _("A gravação saiu muito baixa: aproxime o microfone ou aumente o volume dele no sistema.")
        name = model.seq.track(AUDIO, track).name
        text = _("Narração de {tempo} na faixa {faixa}.").format(tempo=fmt_clock(take.seconds), faixa=name) + extra
        self._say(text, error=bool(extra))
        w.statusBar().showMessage(" ".join([text, *self.notes]), 12000)

    # ------------------------------------------------------------ fechar
    def _panel_closing(self) -> None:
        if self.recording:
            r = QMessageBox.question(self.panel, _("Gravar narração"), _("Descartar a gravação em andamento?"))
            if r != QMessageBox.StandardButton.Yes:
                self.panel.closing_ok = False
                return
            self.discard()
        self._close_capture()

    def shutdown(self) -> None:
        """Ao sair do app: descarta o que estiver gravando e solta o microfone."""
        if self.recording:
            self.discard()
        self._close_capture()


def install(win) -> NarrationUI:
    return NarrationUI(win)
