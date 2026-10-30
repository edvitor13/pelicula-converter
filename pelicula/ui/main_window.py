"""Janela principal do PeliculaConverter."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import dataclasses

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QSize, Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFontMetrics, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import (APP_NAME, __version__, audiomix, chapters, compositor, deps, editparams, export, i18n, look,
               loudness, luts, media, modules, notify, params, presets, project, sequence, system, testimage, textrender,
               timeline, titles, updater)
from ..i18n import N_, _
from ..engine import Engine
from ..frame import Recipe
from . import icons, tempo_ui, theme
from .export_dialog import ExportDialog
from .looks import THUMB_H, THUMB_W, LooksPanel
from .meter import AudioMeter
from .queue_dialog import QueueDialog, open_folder
from .store import ParamStore
from .viewer import SafeAreaButton, Viewer
from .widgets import FilmSlider, SectionCard, Segmented, Timeline, ToggleSwitch, compact, timecode
from .flow import AdaptiveBar, ElideLabel, FlowLayout
from .labcurve import CurveGraph
from .module_notice import ModuleNotice, module_names
from .input_notice import InputNotice, profile_name
from .edit_model import TimelineModel
from .edit_panels import ClipInspector, MediaBin
from .keyframes_ui import KeyRows, KeyStrip
from . import generators_ui, titles_panel
from .scopes import Scopes
from .timeline_view import HEADER_W, ZOOM_PLAYHEAD_KEY, TimelineEditor
from . import notifier, prefs, welcome
from .subtitles_ui import SubtitlesUI
from . import cor_ui, grao_fisico_ui
from . import filme_ui
from . import geometria_ui, luz_fotometro_ui
from . import filtro_ajustes
from . import pastas_ui
from . import sequencias_ui
from . import luz_fotometro_ui
from . import sem_efeitos_ui

MEDIA_PATTERNS = ("*.mp4 *.mov *.mkv *.avi *.mxf *.webm *.m4v *.mts *.m2ts *.wmv *.mpg *.ts "
                  "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.dpx *.exr")
AUDIO_PATTERNS = "*.wav *.mp3 *.aac *.m4a *.flac *.ogg *.opus *.aif *.aiff *.wma"
MODES = ("pelicula", "edicao")
# Rótulos traduzidos com _() na hora de mostrar.
PREVIEW_Q = [("540", N_("Rápida (540p)")), ("720", N_("Normal (720p)")), ("1080", N_("Alta (1080p)")),
             ("full", N_("Máxima (resolução original)"))]


def media_filter() -> str:
    """Filtro de arquivos dos diálogos de abrir (montado na hora, no idioma ativo)."""
    return f"{_('Vídeos e imagens')} ({MEDIA_PATTERNS});;{_('Todos os arquivos')} (*)"


def import_filter() -> str:
    """Filtro do Importar do modo Edição: vídeos, imagens e músicas."""
    return (f"{_('Vídeos, imagens e áudio')} ({MEDIA_PATTERNS} {AUDIO_PATTERNS});;"
            f"{_('Áudio')} ({AUDIO_PATTERNS});;{_('Todos os arquivos')} (*)")


def open_filter() -> str:
    """Filtro do botão Abrir: o primeiro (padrão) mostra vídeos, imagens e projetos .plc juntos."""
    return (f"{_('Vídeos, imagens e projetos')} ({MEDIA_PATTERNS} *{project.EXT});;"
            f"{_('Vídeos e imagens')} ({MEDIA_PATTERNS});;"
            f"{_('Projeto do PeliculaConverter (*.plc)')};;"
            f"{_('Todos os arquivos')} (*)")


def qimage_from(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    if arr.ndim == 3 and arr.shape[2] == 4:  # transparência: sobre o xadrez (só para ver)
        from .alphaview import over_checker
        arr = over_checker(arr)
    if arr.dtype == np.float32:  # leitura de log com super-brancos (`media.float_input`): só para ver
        arr = np.clip(arr * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = (arr >> 8).astype(np.uint8)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def array_from(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return np.ascontiguousarray(buf[:, : w * 3].reshape(h, w, 3))


class FrameLoader(QObject):
    """Carrega quadros em segundo plano; só o pedido mais recente importa.

    A origem é um arquivo (`media.MediaInfo`) ou a sequência do modo Edição (`timeline.Sequence`,
    uma cópia que a interface não altera); no segundo caso chega um `sequence.FrameLayers`.
    """

    loaded = Signal(object, int, object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = None
        self._busy = False

    def request(self, source, frame, w, h, profile: str | None = None, shutter: float = 0.0,
                no_effects: bool = False) -> None:
        """Pede o quadro `frame` de `source` em w × h; `profile`: o perfil de entrada do look (a leitura de um
        arquivo log em faixa legal vem em float32, `media.float_input`); `shutter` (1.6): o ângulo do obturador;
        `no_effects` (1.7): sem o perfil de câmera dos clipes."""
        with self._lock:
            self._pending = (source, frame, w, h, profile, shutter, no_effects)
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            with self._lock:
                job = self._pending
                self._pending = None
                if job is None:
                    self._busy = False
                    return
            source, frame, w, h, profile, shutter, no_effects = job
            try:
                if isinstance(source, timeline.Sequence):
                    img = sequence.grab(source, frame, w, h, 8, shutter=shutter, no_effects=no_effects)
                else:
                    img = media.grab_frame(source, frame, w, h, 8, profile=profile)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))
                continue
            self.loaded.emit(source, frame, img)


class Player:
    """Decodifica em sequência numa thread para a reprodução (arquivo ou sequência da edição)."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=8)
        self._stop = threading.Event()

    def start(self, source, start, end, w, h, loop, loop_start, profile: str | None = None,
              shutter: float = 0.0, no_effects: bool = False) -> None:
        self.stop()
        stop = threading.Event()
        q: queue.Queue = queue.Queue(maxsize=8)
        self._stop, self.q = stop, q
        is_seq = isinstance(source, timeline.Sequence)

        def put(item) -> bool:
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def open_reader(f):
            if is_seq:
                return sequence.SequenceReader(source, w, h, 8, f, end - f + 1, shutter=shutter, no_effects=no_effects)
            return media.FrameReader(source, w, h, 8, f, profile=profile)

        def run():
            f = start
            while not stop.is_set():
                try:
                    reader = open_reader(f)
                except Exception:  # noqa: BLE001
                    put((None, None))
                    return
                try:
                    while not stop.is_set() and f <= end:
                        img = reader.read()
                        if img is None:
                            break
                        if not put((f, img)):
                            break
                        f += 1
                finally:
                    reader.close()
                if stop.is_set():
                    break
                if loop:
                    f = loop_start
                    continue
                put((None, None))
                break

        threading.Thread(target=run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


class _TransportBar(AdaptiveBar):
    """Player: com pouca largura a linha do tempo sobe para uma linha própria, acima dos botões."""

    WRAP = 860  # px abaixo dos quais a linha do tempo não cabe bem ao lado dos botões

    def __init__(self):
        super().__init__()
        self.scrub: QWidget | None = None
        self.top_row: QHBoxLayout | None = None
        self.row: QHBoxLayout | None = None
        self.scrub_index = 0
        self.stacked = False

    def place_scrub(self, width: int) -> None:
        if self.scrub is None:
            return
        stacked = width < self.WRAP
        if stacked == self.stacked:
            return
        self.stacked = stacked
        (self.row if stacked else self.top_row).removeWidget(self.scrub)
        if stacked:
            self.top_row.addWidget(self.scrub, 1)
            self.row.insertStretch(self.scrub_index, 1)
        else:
            stretch = self.row.itemAt(self.scrub_index)
            if stretch is not None and stretch.spacerItem() is not None:
                self.row.takeAt(self.scrub_index)
            self.row.insertWidget(self.scrub_index, self.scrub, 1)
        self.updateGeometry()

    def resizeEvent(self, e) -> None:
        self.place_scrub(e.size().width())
        super().resizeEvent(e)


class _MixBridge(QObject):
    """Som da prévia da sequência renderizado em segundo plano."""

    done = Signal(str, str)  # chave da mixagem, arquivo WAV ("" = sem som)
    peaks = Signal(str)      # forma de onda de um arquivo ficou pronta
    thumb = Signal(str, object)  # miniatura de uma mídia importada (caminho, QImage)
    meter = Signal(int, str)     # pedido do medidor de som, WAV com o som do arquivo ("" = não deu)


class _UpdateBridge(QObject):
    found = Signal(object)


def restart_app() -> None:
    """Fecha e abre o app de novo (para trocar o idioma)."""
    import sys
    if getattr(sys, "frozen", False):
        args = [sys.executable] + sys.argv[1:]
        cwd = os.path.dirname(sys.executable)
    else:
        args = [sys.executable, "-m", "pelicula"] + sys.argv[1:]
        cwd = str(Path(__file__).resolve().parents[2])
    subprocess.Popen(args, cwd=cwd, close_fds=True)
    QApplication.instance().exit(0)


class _DepsBridge(QObject):
    result = Signal(bool, object, str)


class MainWindow(QMainWindow):
    settings_changed = Signal(str)  # uma página de Configurações mudou algo ("modulos", "auto_update"...)

    def __init__(self):
        super().__init__()
        self.settings = prefs.settings()
        media.configure(self.settings.value("ffmpeg_dir", "") or None)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setAcceptDrops(True)
        self.engine = Engine()
        self.thumb_engine = Engine(self.engine.ctx)
        vals = None
        raw = self.settings.value("session_values", "")
        if raw:
            try:
                vals = json.loads(raw)
            except ValueError:
                vals = None
        self.preset_id = self.settings.value("session_preset", presets.DEFAULT_ID) or presets.DEFAULT_ID
        if vals is None:
            self.preset_id = presets.DEFAULT_ID
            vals = presets.builtin_values(self.preset_id)
        self.store = ParamStore(vals)
        self.queue = export.ExportQueue()
        self.queue_dialog: QueueDialog | None = None
        self.info: media.MediaInfo | None = None
        self.frame_idx = 0     # posição do cursor
        self.cur_frame = 0     # quadro da imagem que está na tela (pode estar chegando atrasado)
        self.cur: np.ndarray | None = None
        self.cur_q: QImage | None = None
        self.project_path: str | None = None
        self._saved_state: dict = {}
        self._media_label = ""
        self.audio = None
        self.audio_out = None
        self._audio_ok = False
        self._audio_sync_t = 0.0
        self._uploaded = None
        self.inp: int | None = None
        self.outp: int | None = None
        self.loop = True
        self.playing = False
        self._play_rate = 1      # reprodução para a frente: 1× (com som) ou 2/4/8× (L de novo; sem som)
        self._rev_rate = 0       # reprodução para trás (J): 0 = parada; 1/2/4/8×, sem som
        self._rev_t0 = self._rev_f0 = self._rev_last = 0
        self._k_held = False     # K apertado: J/L andam um quadro
        self.preview_q = str(self.settings.value("preview_quality", "720"))
        self.preview_fullscreen = False
        self._state_before_full = Qt.WindowState.WindowNoState
        self._seen_done: set[str] = set()
        self._base_cache: tuple[str, dict] | None = None
        self.loader = FrameLoader()
        self.loader.loaded.connect(self._frame_loaded)
        self.loader.failed.connect(
            lambda m: self.statusBar().showMessage(_("Erro ao ler o quadro: {erro}").format(erro=m), 8000))
        self.player = Player()
        # Modo Edição: a montagem (sequência) é a fonte da prévia quando tem mudanças em relação ao arquivo.
        self.mode = "pelicula"
        self.model = TimelineModel(timeline.Sequence(micro_fade=True))  # sequência nova: fades nas emendas
        self.file_info: media.MediaInfo | None = None  # arquivo aberto no modo Película
        self.src_seq: timeline.Sequence | None = None   # cópia da sequência que a prévia está mostrando
        self.cur_layers = None
        self.cur_neutral_q: QImage | None = None
        self.edit_film = str(self.settings.value("edit_film", "false")) == "true"
        self.no_effects = False  # 1.7: "Desligar todos os efeitos" (só nesta sessão, `sem_efeitos_ui`)
        self._sources: dict[str, timeline.Source] = {}
        self._file_infos: dict[str, media.MediaInfo] = {}  # 1.6: metadados de câmera (`media.suggest_input`)
        self.model.clip_profile_for = self._clip_profile_for
        self._loading = False
        self._audio_src = ("", "")
        self._mix_key = ""
        self._mix_path = ""
        self._mix_files: list[str] = []
        self._mix_running: dict[str, str] = {}  # chave → WAV das mixagens a caminho (uma por chave)
        self._mix_token = 0
        self._peaks: dict[str, object] = {}
        self._peaks_pending: set[str] = set()
        self._mix_bridge = _MixBridge()
        self._mix_bridge.done.connect(self._mix_done)
        self._mix_bridge.peaks.connect(lambda path: self.tl_editor.peaks_ready(path))
        self._mix_bridge.thumb.connect(lambda path, img: self.bin.set_thumb(path, img))
        self._notice_muted: set[str] = set()  # módulos cujo aviso a pessoa fechou nesta sessão
        # Notificações do sistema (o app.main() liga o backend do sistema; aqui nada aparece de verdade) e
        # recuperação automática (`ui/recovery_ui.attach`, só pelo app.main(): testes não gravam cópias).
        self.notifier = notifier.for_window(self)
        self.recovery = None
        # Medidor de som (módulo medidor_som): lê o mesmo som que está tocando, junto com o relógio da prévia.
        self._meter_enabled = False
        self._meter_for = ("", "")      # (tipo, caminho) do som que o medidor está lendo
        self._meter_reader: audiomix.WavReader | None = None
        self._meter_lm: loudness.LoudnessMeter | None = None
        self._meter_pos: int | None = None  # próxima amostra a medir (None = recomeçar)
        self._meter_token = 0
        self._meter_cancel: threading.Event | None = None
        self._meter_wav: tuple[tuple, str] = ((), "")  # som do arquivo já decodificado: ((caminho, mtime), WAV)
        self._meter_files: list[str] = []
        self._mix_bridge.meter.connect(self._meter_decoded)
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(40)  # 25 vezes por segundo
        self.meter_timer.timeout.connect(self._meter_tick)

        self._build_ui()
        self.subs_ui = SubtitlesUI(self)  # legendas: painel, faixa e menu (antes de ligar o model: limpa o cache)
        cor_ui.install(self)  # 1.6: ferramentas de cor (planos, cor simples, zebra, falsa cor e referência)
        filme_ui.install(self)  # 1.6: câmera, formato e montagem (`ui/filme_ui.py`)
        luz_fotometro_ui.install(self)  # 1.6: luz por plano e fotômetro da película (`ui/luz_fotometro_ui.py`)
        geometria_ui.install(self)  # 1.7: desespremer do clipe e janela útil da sequência (`ui/geometria_ui.py`)
        self.seqs_ui = sequencias_ui.install(self)  # 1.7: abas das sequências do projeto (`ui/sequencias_ui.py`)
        self.store.changed.connect(self._on_param)
        self.store.historyChanged.connect(self._update_history)
        self.model.changed.connect(self._model_changed)
        self.model.historyChanged.connect(self._update_history)
        self.mix_timer = QTimer(self)
        self.mix_timer.setSingleShot(True)
        self.mix_timer.setInterval(700)
        self.mix_timer.timeout.connect(self._start_mix)

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(0)
        self.render_timer.timeout.connect(self.render_now)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setSingleShot(True)
        self.thumb_timer.setInterval(350)
        self.thumb_timer.timeout.connect(self._render_thumbs)
        self.curve_timer = QTimer(self)
        self.curve_timer.setSingleShot(True)
        self.curve_timer.setInterval(80)
        self.curve_timer.timeout.connect(self._update_curve)
        if str(self.settings.value("show_curve", "false")) == "true":
            self.curve_switch.setChecked(True)
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.timeout.connect(self._play_tick)
        self.rev_timer = QTimer(self)   # J: pede ao carregador o quadro do relógio andando para trás
        self.rev_timer.setInterval(40)
        self.rev_timer.timeout.connect(self._reverse_tick)
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(500)
        self.queue_timer.timeout.connect(self._queue_tick)
        self.queue_timer.start()
        self._deps_bridge = _DepsBridge()
        self._deps_bridge.result.connect(self._deps_result)
        QTimer.singleShot(1200, self._check_deps)
        self._saved_state = self._state()
        self._update_bridge = _UpdateBridge()
        self._update_bridge.found.connect(self._update_found)
        self.btn_update = QPushButton()
        self.btn_update.setObjectName("Primary")
        self.btn_update.setVisible(False)
        self.btn_update.clicked.connect(lambda: self.show_update(self._release))
        self.statusBar().addPermanentWidget(self.btn_update)
        self._release = None
        QTimer.singleShot(4000, self._auto_check_update)
        muted = str(self.settings.value("audio_muted", "false")) == "true"
        self.btn_mute.setChecked(muted)
        self._set_muted(muted)
        self.vol.setValue(float(self.settings.value("audio_volume", 0.8) or 0.8))

        self._refresh_presets()
        self._update_modified()
        self._update_history()
        self.thumb_timer.start()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1640, 960)
        st = self.settings.value("splitter")
        if st is not None:
            self.split.restoreState(st)
        # Estados antigos podiam ter um painel recolhido (largura 0): volta ao padrão.
        self.split.setChildrenCollapsible(False)
        if min(self.split.sizes()) <= 0:
            self.split.setSizes([310, 960, 380])
        st = self.settings.value("splitter_edit")
        if st is not None:
            self.center_split.restoreState(st)
        self.center_split.setChildrenCollapsible(False)
        self.apply_modules()

    # ================================================================ interface
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.top_bar = self._top_bar()
        root.addWidget(self.top_bar)
        self.module_notice = ModuleNotice()
        self.module_notice.enableRequested.connect(self.enable_modules)
        self.module_notice.dismissed.connect(lambda ids: self._notice_muted.update(ids))
        root.addWidget(self.module_notice)
        self.input_notice = InputNotice()  # 1.6: perfil sugerido pelos metadados do arquivo
        self.input_notice.accepted.connect(self._accept_input_suggestion)
        root.addWidget(self.input_notice)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(1)
        self.looks = LooksPanel()
        self.looks.presetChosen.connect(self.apply_preset)
        self.bin = MediaBin(model=self.model)
        self.bin.importRequested.connect(self.import_dialog)
        self.bin.addRequested.connect(self.add_to_timeline)
        self.bin.openRequested.connect(self._open_sequence_entry)
        self.bin.removeRequested.connect(self._bin_remove)
        self.bin.filesDropped.connect(self._bin_files)
        self.bin.filesDroppedIn.connect(lambda paths, folder: self._bin_files(paths, folder))
        self.bin.placeRequested.connect(self.place_at_cursor)
        self.bin.set_new_menu(generators_ui.new_menu(self, self.new_generated))
        self._generated_seen: dict[str, str] = {}  # dados de cada clipe sem arquivo na Mídia (para atualizar)
        self._generated_timer = QTimer(self)
        self._generated_timer.setSingleShot(True)
        self._generated_timer.setInterval(250)
        self._generated_timer.timeout.connect(self._sync_generated_sources)
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self.looks)
        self.left_stack.addWidget(self.bin)
        self.split.addWidget(self.left_stack)
        self.center_split = QSplitter(Qt.Orientation.Vertical)
        self.center_split.setHandleWidth(1)
        self.center_split.addWidget(self._center())
        self.tl_editor = TimelineEditor(self.model)
        self.tl_editor.seekRequested.connect(self.seek)
        self.tl_editor.filesDropped.connect(self.drop_on_timeline)
        self.tl_editor.filesInserted.connect(lambda p, f, k, t: self.drop_on_timeline(p, f, k, t, insert=True))
        self.tl_editor.set_peaks_provider(self._peaks_for)
        self.tl_editor.setVisible(False)
        cv = self.tl_editor.canvas  # linha "Look": as chaves do look sobre a montagem, no tempo da montagem
        self.look_lane = KeyStrip(self.store, cv.frame_to_x, cv.x_to_frame, lambda: cv.playhead,
                                  lambda: self.model.seq.fps, _("Look"), HEADER_W)
        self.look_lane.setToolTip(_("Chaves do look (Película sobre a montagem). Clique leva o cursor; arraste para "
                                    "mover; Delete apaga."))
        self.look_lane.seekRequested.connect(self.seek)
        self.look_lane.setVisible(False)
        self.tl_editor.add_lane(self.look_lane)
        self.center_split.addWidget(self.tl_editor)
        self.center_split.setStretchFactor(0, 3)
        self.center_split.setStretchFactor(1, 2)
        self.center_split.setChildrenCollapsible(False)
        self.split.addWidget(self.center_split)
        self.right_panel = QStackedWidget()
        self.right_panel.addWidget(self._right_panel())
        self.right_panel.addWidget(self._edit_panel())
        self.split.addWidget(self.right_panel)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setChildrenCollapsible(False)
        self.split.setSizes([310, 960, 380])
        root.addWidget(self.split, 1)
        self.setCentralWidget(central)
        sb = self.statusBar()
        self.st_file = QLabel(_("Nenhum arquivo aberto"))
        self.st_prev = QLabel("")
        self.st_render = QLabel("")
        self.st_gpu = QLabel(f"GPU: {self.engine.renderer.split('/')[0]}")
        sb.addWidget(self.st_file, 1)
        sb.addPermanentWidget(self.st_prev)
        sb.addPermanentWidget(self.st_render)
        sb.addPermanentWidget(self.st_gpu)
        self._shortcuts()
        self._set_media_enabled(False)

    def _flat(self, icon: str, tip: str, text: str = "", checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(icons.icon(icon, theme.TEXT, 18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCheckable(checkable)
        return b

    def _top_bar(self) -> QWidget:
        bar = AdaptiveBar()
        bar.setObjectName("TopBar")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(30, 30))
        hl.addWidget(logo)
        t = theme.title_font()
        name = QLabel(f"<span style='font-family:\"{t}\"; font-size:14.5pt; font-weight:700; color:{theme.TEXT}'>Película</span>"
                      f"<span style='font-family:\"{t}\"; font-size:14.5pt; font-weight:300; color:{theme.ACCENT}'>Converter</span>")
        hl.addWidget(name)
        hl.addSpacing(18)
        self.mode_switch = Segmented([
            ("pelicula", _("Película"), _("Aplicar o look de película no vídeo ou na montagem (Ctrl+1)")),
            ("edicao", _("Edição"), _("Cortar, juntar clipes e ajustar cor e som antes do look de película (Ctrl+2)")),
        ], name="SegMode", item_icons={"pelicula": "film", "edicao": "scissors"})
        self.mode_switch.set_current("pelicula")
        self.mode_switch.changed.connect(self.set_mode)
        hl.addWidget(self.mode_switch)
        hl.addSpacing(10)
        self.file_label = ElideLabel("")
        self.file_label.setObjectName("Muted")
        hl.addWidget(self.file_label, 1)
        self._brand = name
        self.btn_project = self._flat("save", _("Projeto: salvar e abrir a edição"), _("Projeto"))
        self.project_menu = QMenu(self)
        self.project_menu.aboutToShow.connect(self._fill_project_menu)
        self.btn_project.setMenu(self.project_menu)
        self.btn_project.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hl.addWidget(self.btn_project)
        self.btn_open = self._flat("open", _("Abrir vídeo, imagem ou projeto .plc (Ctrl+O)"), _("Abrir"))
        self.btn_open.clicked.connect(self.open_dialog)
        hl.addWidget(self.btn_open)
        self.btn_frame = self._flat("camera", _("Salvar o quadro atual em alta qualidade (Ctrl+Shift+F)"),
                                    _("Salvar quadro"))
        self.btn_frame.clicked.connect(self.save_frame)
        hl.addWidget(self.btn_frame)
        self.btn_subs = self._flat("captions", _("Legendas: painel, importar e exportar .srt e .vtt (Ctrl+Shift+L)"),
                                   _("Legendas"))  # menu: ui/subtitles_ui.SubtitlesUI
        hl.addWidget(self.btn_subs)
        self.btn_queue = self._flat("queue", _("Fila de exportação"), _("Fila"))
        self.btn_queue.clicked.connect(self.show_queue)
        hl.addWidget(self.btn_queue)
        self.btn_export = QPushButton("  " + _("Exportar"))
        self.btn_export.setObjectName("Primary")
        self.btn_export.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_export.setToolTip(_("Exportar com o look atual (Ctrl+E)"))
        self.btn_export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_export.clicked.connect(self.export_dialog)
        hl.addWidget(self.btn_export)
        self.btn_settings = self._flat("settings", _("Configurações"))
        menu = QMenu(self)
        menu.addAction(icons.icon("settings", theme.TEXT, 16), _("Configurações…"), lambda: self.show_settings("geral"))
        menu.addAction(icons.icon("check", theme.TEXT, 16), _("Recursos…"), lambda: self.show_settings("recursos"))
        menu.addSeparator()
        menu.addAction(_("Idioma…"), self.choose_language)
        menu.addAction(_("Verificar atualizações…"), lambda: self.check_updates(manual=True))
        self.act_auto_update = menu.addAction(_("Procurar atualizações automaticamente"))
        self.act_auto_update.setCheckable(True)
        self.act_auto_update.setChecked(self.auto_update_enabled())
        self.act_auto_update.setToolTip(_("Consulta o GitHub (app) e a fonte do ffmpeg ao abrir; nada é enviado "
                                          "além do pedido de versão"))
        self.act_auto_update.toggled.connect(lambda on: self.settings.setValue("auto_update", "true" if on else "false"))
        self.settings_changed.connect(self._on_settings_changed)
        menu.addAction(_("Novidades desta versão"), lambda: welcome.WhatsNewDialog(self).exec())
        menu.addAction(_("Tela de boas-vindas"), self.show_welcome)
        menu.addSeparator()
        menu.addAction(icons.icon("box", theme.TEXT, 16), _("Componentes…"), lambda: self.show_settings("componentes"))
        menu.addAction(_("Pasta do ffmpeg…"), self.choose_ffmpeg)
        menu.addAction(_("Abrir pasta dos meus presets"), lambda: system.open_path(presets.user_dir()))
        menu.addAction(_("Abrir pasta dos meus LUTs"), self.open_lut_dir)
        self.act_resolve_sep = menu.addSeparator()
        self.act_resolve = menu.addAction(icons.icon("davinci", theme.TEXT, 16), _("Plugin para o DaVinci Resolve…"),
                                          self.show_resolve)
        # Módulo Beta "recorte_ia": só aparece ligado e com o componente instalado (ver apply_modules).
        self.act_corridorkey = menu.addAction(icons.icon("matte", theme.TEXT, 16), _("Recorte por IA (CorridorKey)…"),
                                              self.show_corridorkey)
        menu.aboutToShow.connect(self._sync_corridorkey_action)
        menu.addSeparator()
        menu.addAction(_("Atalhos do teclado"), self.show_shortcuts)
        menu.addAction(_("Sobre o {app}").format(app=APP_NAME), self.about)
        self.btn_settings.setMenu(menu)
        self.btn_settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hl.addWidget(self.btn_settings)
        # Janela estreita: os botões ficam só com o ícone e o nome do app some.
        bar.set_adaptive(compact=[self.btn_project, self.btn_open, self.btn_frame, self.btn_queue, self.btn_subs,
                                  *self.mode_switch.buttons.values()],
                         optional=[self._brand])
        return bar

    def _center(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        bar = AdaptiveBar()
        bar.setObjectName("ViewerBar")
        self.viewer_bar = bar  # a barra da prévia (a da linha do tempo usa o mesmo nome de estilo)
        hl = FlowLayout(bar, 8, 6)
        hl.setContentsMargins(12, 8, 12, 8)
        self.compare = Segmented([
            ("proc", _("Resultado"), _("Só o resultado")),
            ("split", _("Dividido"), _("Arraste a linha para comparar. Segure o botão direito para ver o original.")),
            ("side", _("Lado a lado"), _("Original e resultado lado a lado")),
            ("orig", _("Original"), _("Só o vídeo original")),
        ], name="SegQuiet")  # o âmbar da barra fica para o modo
        mode = str(self.settings.value("compare", "split"))
        self.compare.set_current(mode)
        self.compare.changed.connect(self._set_compare)
        hl.addWidget(self.compare)
        sem_efeitos_ui.install(self, hl)
        hl.add_spacing(2)
        self.btn_zoom_out = self._flat("zoom_out", _("Menos zoom (−). A roda do mouse também dá zoom."))
        self.btn_zoom_out.clicked.connect(lambda: self.viewer.zoom_step(-1))
        hl.addWidget(self.btn_zoom_out)
        self.btn_zoom_in = self._flat("zoom_in", _("Mais zoom (+). A roda do mouse também dá zoom."))
        self.btn_zoom_in.clicked.connect(lambda: self.viewer.zoom_step(1))
        hl.addWidget(self.btn_zoom_in)
        self.btn_fit = self._flat("fit", _("Ajustar à janela (F)"), _("Ajustar"))
        self.btn_fit.clicked.connect(lambda: self.viewer.set_zoom(None))
        hl.addWidget(self.btn_fit)
        zoom_buttons = []
        for z in (1.0, 2.0):
            b = QToolButton()
            b.setObjectName("Flat")
            b.setText(f"{int(z * 100)}%")
            b.setToolTip(_("Zoom {pct}% ({tecla}). Roda do mouse também dá zoom; arraste para mover.").format(
                pct=int(z * 100), tecla=int(z)))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, zz=z: self.viewer.set_zoom(zz))
            hl.addWidget(b)
            zoom_buttons.append(b)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("Faint")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setToolTip(_("Zoom atual (100% = um pixel da prévia por pixel da tela)"))
        hl.addWidget(self.zoom_label)
        self.btn_edit_film = self._flat("film", _("Mostrar a montagem já com o look de película (mais lento). "
                                                  "O que aparece aqui é o que sai na exportação."),
                                        _("Com película"), checkable=True)
        self.btn_edit_film.setChecked(self.edit_film)
        self.btn_edit_film.toggled.connect(self._set_edit_film)
        hl.addWidget(self.btn_edit_film)
        self.btn_seq = self._flat("settings", _("Resolução, quadros por segundo e cor de fundo da sequência"),
                                  _("Sequência"))
        self.btn_seq.clicked.connect(self.sequence_settings)
        hl.addWidget(self.btn_seq)
        self.btn_edit_undo = self._flat("undo", _("Desfazer na edição (Ctrl+Z)"))
        self.btn_edit_undo.clicked.connect(self.undo)
        self.btn_edit_redo = self._flat("redo", _("Refazer na edição (Ctrl+Y)"))
        self.btn_edit_redo.clicked.connect(self.redo)
        hl.addWidget(self.btn_edit_undo)
        hl.addWidget(self.btn_edit_redo)
        self._edit_only = [self.btn_edit_film, self.btn_seq, self.btn_edit_undo, self.btn_edit_redo]
        for wdg in self._edit_only:
            wdg.setVisible(False)
        hl.add_stretch()
        lab = QLabel(_("Prévia"))
        lab.setObjectName("Muted")
        hl.addWidget(lab)
        self.prev_combo = compact(QComboBox(), 12)
        for key, text in PREVIEW_Q:
            self.prev_combo.addItem(_(text), key)
        self.prev_combo.setCurrentIndex(max(0, self.prev_combo.findData(self.preview_q)))
        self.prev_combo.setToolTip(_("Resolução da prévia. O grão só aparece fiel na resolução máxima com zoom 100%."))
        self.prev_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_combo.currentIndexChanged.connect(self._preview_changed)
        hl.addWidget(self.prev_combo)
        self.btn_safe = SafeAreaButton(self.settings)  # área segura das plataformas (só na tela)
        hl.addWidget(self.btn_safe)
        self.btn_full = self._flat("fullscreen", _("Prévia em tela cheia (F11). Esc sai."))
        self.btn_full.clicked.connect(self.toggle_preview_fullscreen)
        hl.addWidget(self.btn_full)
        # Prévia estreita: botões só com ícone, somem os extras e, se ainda faltar espaço, quebra a linha.
        bar.set_adaptive(compact=[self.btn_fit, self.btn_edit_film, self.btn_seq],
                         optional=zoom_buttons + [self.zoom_label, lab])
        vl.addWidget(bar)
        self.viewer_bar = bar
        self.viewer = Viewer()
        self.viewer.set_mode(mode)
        self.viewer.openRequested.connect(self.open_dialog)
        self.viewer.testRequested.connect(self.open_test_scene)
        self.viewer.filesDropped.connect(self.handle_files)
        self.viewer.zoomChanged.connect(self._zoom_changed)
        self.viewer.set_safe_area(self.btn_safe.kind)
        self.btn_safe.changed.connect(self.viewer.set_safe_area)
        self.meter = AudioMeter()
        self.meter.resetRequested.connect(self._meter_reset)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.viewer, 1)
        row.addWidget(self.meter)
        vl.addLayout(row, 1)
        tr = _TransportBar()
        tr.setObjectName("Transport")
        tv = QVBoxLayout(tr)
        tv.setContentsMargins(10, 6, 12, 10)
        tv.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        tv.addLayout(top)
        th = QHBoxLayout()
        th.setSpacing(4)
        tv.addLayout(th)
        self.btn_back = self._flat("step_back", _("Quadro anterior (←)"))
        self.btn_back.clicked.connect(lambda: self.step(-1))
        self.btn_play = self._flat("play", _("Reproduzir / pausar (Espaço)"))
        self.btn_play.setIconSize(QSize(22, 22))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_fwd = self._flat("step_fwd", _("Próximo quadro (→)"))
        self.btn_fwd.clicked.connect(lambda: self.step(1))
        for b in (self.btn_back, self.btn_play, self.btn_fwd):
            th.addWidget(b)
        self.time_label = QLabel("00:00:00:00")
        self.time_label.setObjectName("Time")
        # Largura fixa do texto mais longo (fonte monoespaçada): o rótulo não pula nem corta.
        self.time_label.setMinimumWidth(QFontMetrics(theme.mono_font()).horizontalAdvance("00:00:00:00  /  00:00:00:00") + 8)
        th.addSpacing(6)
        th.addWidget(self.time_label)
        self.shuttle_label = QLabel("")   # J/K/L: velocidade da reprodução rápida ou para trás
        self.shuttle_label.setObjectName("Muted")
        self.shuttle_label.setToolTip(_("Reprodução rápida ou para trás (J/K/L), sem som. K ou Espaço para."))
        self.shuttle_label.setVisible(False)
        th.addWidget(self.shuttle_label)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)
        self.scrub_box = self._scrub_with_keys()
        tr.scrub, tr.top_row, tr.row, tr.scrub_index = self.scrub_box, top, th, th.count()
        th.addWidget(self.scrub_box, 1)
        self.btn_in = self._flat("mark_in", _("Marcar entrada (I)"))
        self.btn_in.clicked.connect(self.mark_in)
        self.btn_out = self._flat("mark_out", _("Marcar saída (O)"))
        self.btn_out.clicked.connect(self.mark_out)
        self.btn_clear = self._flat("clear", _("Limpar entrada e saída (X)"))
        self.btn_clear.clicked.connect(self.clear_marks)
        self.btn_loop = self._flat("loop", _("Repetir (Ctrl+L)"), checkable=True)
        self.btn_loop.setChecked(True)
        self.btn_loop.toggled.connect(lambda on: setattr(self, "loop", on))
        for b in (self.btn_in, self.btn_out, self.btn_clear, self.btn_loop):
            th.addWidget(b)
        th.addSpacing(6)
        self.btn_mute = self._flat("volume", _("Som da prévia (M liga/desliga)"), checkable=True)
        self.btn_mute.toggled.connect(self._set_muted)
        th.addWidget(self.btn_mute)
        self.vol = FilmSlider(0.0, 1.0, 0.01, 0.8)
        self.vol.setFixedWidth(80)
        self.vol.setToolTip(_("Volume da prévia"))
        self.vol.valueChanged.connect(self._set_volume)
        th.addWidget(self.vol)
        tr.set_adaptive(optional=[self.vol])
        vl.addWidget(tr)
        self.transport = tr
        return w

    def _scrub_with_keys(self) -> QWidget:
        """A barra da prévia com a faixa das chaves do look logo abaixo (só aparece quando o look tem chaves)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.timeline)
        tl = self.timeline
        self.look_strip = KeyStrip(self.store, tl._x, lambda x: (x - 10) / max(1, tl.width() - 20) * max(1, tl.total - 1),
                                   lambda: tl.pos, lambda: tl.fps)
        self.look_strip.setVisible(False)
        self.look_strip.seekRequested.connect(self.seek)
        lay.addWidget(self.look_strip)
        return box

    def _sync_look_strips(self) -> None:
        """Mostra a faixa das chaves do look onde ela vale: sob a barra da prévia (Película) ou na linha "Look"
        da linha do tempo (Edição com a película ligada)."""
        if getattr(self, "look_lane", None) is None or getattr(self, "look_strip", None) is None:
            return  # ainda montando a janela
        edit = self.mode == "edicao"
        keys = bool(self.store.keys)
        self.scrub_box.setVisible(not edit)
        self.look_strip.setVisible(keys and not edit)
        self.look_lane.setVisible(keys and edit and self.edit_film)

    def _right_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Panel")
        w.setMinimumWidth(300)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 12, 6, 8)
        vl.setSpacing(8)
        k = QLabel(_("AJUSTES"))
        k.setObjectName("Kicker")
        vl.addWidget(k)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.preset_combo = compact(QComboBox(), 14)
        self.preset_combo.setMaxVisibleItems(24)
        self.preset_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preset_combo.activated.connect(self._combo_chosen)
        row.addWidget(self.preset_combo, 1)
        self.btn_save = self._flat("save", _("Salvar como novo preset (Ctrl+Alt+S)"))
        self.btn_save.clicked.connect(self.save_preset_as)
        row.addWidget(self.btn_save)
        self.btn_more = self._flat("more", _("Mais opções de preset"))
        self.more_menu = QMenu(self)
        self.act_update = self.more_menu.addAction(_("Atualizar este preset com os ajustes atuais"),
                                                   self.update_user_preset)
        self.act_delete = self.more_menu.addAction(_("Excluir este preset"), self.delete_preset)
        self.more_menu.addAction(_("Desfazer mudanças (voltar ao preset)"), self.revert_preset)
        self.more_menu.addSeparator()
        self.more_menu.addAction(_("Importar preset (.json)…"), self.import_preset)
        self.more_menu.addAction(_("Exportar preset (.json)…"), self.export_preset)
        self.act_lut_sep = self.more_menu.addSeparator()
        self.act_luts = [
            self.more_menu.addAction(_("Exportar a cor como LUT .cube ({n} pontos)…").format(n=33),
                                     lambda: self.export_lut(33)),
            self.more_menu.addAction(_("Exportar a cor como LUT .cube ({n} pontos)…").format(n=65),
                                     lambda: self.export_lut(65)),
            self.more_menu.addAction(_("Exportar todos os presets como LUTs (pacote)…"), self.export_all_luts),
        ]
        self.more_menu.aboutToShow.connect(self._menu_state)
        self.btn_more.setMenu(self.more_menu)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.btn_more)
        vl.addLayout(row)
        self.mod_label = QLabel(_("Modificado — salve como novo preset para usar depois"))
        self.mod_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 8.5pt;")
        vl.addWidget(self.mod_label)
        self.hist = Scopes()
        self.hist.mode = str(self.settings.value("scopes", self.hist.mode))
        vl.addWidget(self.hist)
        # "Mostrar curva": a curva de transferência do look (Laboratório + cor + cópia + LUT) em R, G e B.
        self.curve_graph = CurveGraph()
        self.curve_graph.setVisible(False)
        vl.addWidget(self.curve_graph)
        row2 = QHBoxLayout()
        lab = QLabel(_("Ajustes avançados"))
        lab.setObjectName("Muted")
        row2.addWidget(lab)
        self.adv = ToggleSwitch()
        self.adv.setChecked(self.settings.value("advanced", "false") == "true")
        self.adv.toggled.connect(self._set_advanced)
        row2.addWidget(self.adv)
        row2.addSpacing(10)
        lab_c = self.curve_label = QLabel(_("Curva"))
        lab_c.setObjectName("Muted")
        lab_c.setToolTip(_("Mostrar a curva do look em R, G e B (como o \"Show Curve\" dos plugins de película)"))
        row2.addWidget(lab_c)
        self.curve_switch = ToggleSwitch()
        self.curve_switch.setToolTip(lab_c.toolTip())
        self.curve_switch.toggled.connect(self._set_curve_visible)
        row2.addWidget(self.curve_switch)
        row2.addStretch(1)
        self.btn_undo = self._flat("undo", _("Desfazer (Ctrl+Z)"))
        self.btn_undo.clicked.connect(self.store.undo)
        self.btn_redo = self._flat("redo", _("Refazer (Ctrl+Y)"))
        self.btn_redo.clicked.connect(self.store.redo)
        row2.addWidget(self.btn_undo)
        row2.addWidget(self.btn_redo)
        vl.addLayout(row2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 8)
        il.setSpacing(8)
        self.cards: list[SectionCard] = []
        open_default = {"pelicula", "cor", "grao", "halacao"}
        for sec in params.SECTIONS:
            card = SectionCard(sec, self.store, expanded=sec.key in open_default)
            card.set_advanced(self.adv.isChecked())
            self.cards.append(card)
            il.addWidget(card)
        il.addStretch(1)
        scroll.setWidget(inner)
        vl.addWidget(scroll, 1)
        self.look_filter = filtro_ajustes.install(vl, w, [self.cards], index=vl.indexOf(scroll))  # 1.7: "Filtrar ajustes…"
        # Losangos das chaves do look (o alvo é o próprio store; quadros do arquivo ou da montagem).
        self.look_keys = KeyRows(self.store, self.store, self.cards, self)
        self.look_keys.seekRequested.connect(self.seek)
        return w

    def _edit_panel(self) -> QWidget:
        """Painel da direita no modo Edição: medidores de cor e o inspetor do clipe escolhido."""
        w = QWidget()
        w.setObjectName("Panel")
        w.setMinimumWidth(300)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 12, 6, 8)
        vl.setSpacing(8)
        self.edit_scopes = Scopes()
        self.edit_scopes.mode = str(self.settings.value("scopes_edit", self.edit_scopes.mode))
        vl.addWidget(self.edit_scopes)
        self.inspector = ClipInspector(self.model)
        self.inspector.autoRequested.connect(self.auto_adjust_clip)
        self.inspector.autoFrameRequested.connect(lambda cid: self.auto_adjust_clip(cid, whole=False))
        self.inspector.seekRequested.connect(self.seek)
        self.gen_editor = generators_ui.GeneratorEditor(self.model)
        self.inspector.add_source_editor(self.gen_editor)
        self.title_editor = titles_panel.TitleEditor(self.model)
        self.inspector.add_source_editor(self.title_editor)
        vl.addWidget(self.inspector, 1)
        return w

    def _shortcuts(self) -> None:
        def sc(seq, fn) -> QShortcut:
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
            return s
        sc("Ctrl+O", self.open_dialog)
        sc("Ctrl+E", self.export_dialog)
        sc("Ctrl+S", self.save_project)
        sc("Ctrl+Shift+S", self.save_project_as)
        sc("Ctrl+Shift+O", self.open_project_dialog)
        sc("Ctrl+N", self.new_project)
        sc("Ctrl+Alt+S", self.save_preset_as)
        sc("Ctrl+Shift+F", self.save_frame)
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)
        # Atalhos que levam ao modo Edição (desligados junto com o módulo "edicao").
        self._edit_shortcuts = [sc("Ctrl+I", self.import_dialog), sc("Ctrl+2", lambda: self.set_mode("edicao"))]
        sc("Ctrl+1", lambda: self.set_mode("pelicula"))
        sc("Ctrl+Alt+C", lambda: self.mode == "edicao" and self.inspector.copy_values())
        sc("Ctrl+Alt+V", lambda: self.mode == "edicao" and self.inspector.paste_values())
        sc("Ctrl+Shift+N", lambda: self.mode == "edicao" and self.bin.pastas.new_folder())  # pasta na Mídia
        sc("Ctrl+L", lambda: self.btn_loop.toggle())  # o L sozinho é do J/K/L (reproduzir para a frente)
        sc("F11", self.toggle_preview_fullscreen)
        sc("Shift+F11", self.toggle_window_fullscreen)

    # ================================================================ zoom e tela cheia
    def _zoom_changed(self, _z: str) -> None:
        s = self.viewer.scale()
        self.zoom_label.setText("" if s is None else f"{s * 100:.0f}%")

    def toggle_window_fullscreen(self) -> None:
        """Janela inteira (com os painéis) em tela cheia."""
        if self.preview_fullscreen:
            self.toggle_preview_fullscreen()
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def toggle_preview_fullscreen(self) -> None:
        """A prévia ocupa a tela: somem a barra superior, os painéis e a barra de status. A barra da prévia
        (comparação, zoom, resolução) e o player continuam, e a resolução escolhida não muda."""
        entering = not self.preview_fullscreen
        if entering and self.info is None:
            return
        if entering:
            self._state_before_full = self.windowState()
        self.preview_fullscreen = entering
        for wdg in (self.top_bar, self.left_stack, self.right_panel, self.statusBar()):
            wdg.setVisible(not entering)
        self._check_modules()  # o aviso de recurso desligado some na tela cheia e volta ao sair
        self.input_notice.set_suppressed(entering)
        self.tl_editor.setVisible(not entering and self.mode == "edicao")
        self.viewer.set_fullscreen(entering)
        self.btn_full.setIcon(icons.icon("fullscreen_exit" if entering else "fullscreen", theme.TEXT, 18))
        self.btn_full.setText(_("Sair da tela cheia") if entering else "")
        self.btn_full.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if entering
                                         else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_full.setToolTip(_("Sair da tela cheia (Esc ou F11)") if entering
                                 else _("Prévia em tela cheia (F11). Esc sai."))
        if entering:
            self.showFullScreen()
            self.viewer.setFocus()
        else:
            prev = self._state_before_full
            if prev & Qt.WindowState.WindowFullScreen:
                self.showFullScreen()
            elif prev & Qt.WindowState.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()

    # ================================================================ arquivos
    def open_dialog(self) -> None:
        if self.mode == "edicao":
            self.import_dialog()
            return
        d = str(self.settings.value("last_dir", str(Path.home())))
        path, _f = QFileDialog.getOpenFileName(self, _("Abrir vídeo, imagem ou projeto"), d, open_filter())
        if path:
            self.handle_files([path])

    def handle_files(self, paths: list[str]) -> None:
        cubes = [p for p in paths if Path(p).suffix.lower() == ".cube"]
        if cubes:
            self.install_luts(cubes)
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext == project.EXT:
                self.open_project(p)
                break
            if ext == ".json":
                self.import_preset(p)
            elif ext != ".cube":
                if self.mode == "edicao":
                    self.import_paths([q for q in paths if Path(q).suffix.lower() not in (".cube", ".json")])
                    break
                if self.confirm_discard():
                    target, fps = self._film_target(p)
                    if not target:
                        break
                    self.load_media(target, detect=True, fps_str=fps)
                    self.project_path = None
                    self._saved_state = self._state()
                    self._update_title()
                break

    def install_luts(self, paths: list[str]) -> None:
        """Instala LUTs (arrastados para a janela) e usa o primeiro deles."""
        from .widgets import LutRow
        rows = [r for c in self.cards for r in c.rows if isinstance(r, LutRow)]
        if rows:
            rows[0].install(paths)
            for r in rows[1:]:
                r._fill()
                r.refresh()
        else:
            done, _errors = luts.install(paths)
            if done:
                self.cards_lut_set(done[0])
        self._check_modules()

    def cards_lut_set(self, path: str) -> None:
        self.store.set("lut_arquivo", path, record=False)
        self.store.set("lut_entrada", luts.guess_input(path), record=False)
        self.store.set("lut_on", True, record=False)
        self.store.commit()
        self.statusBar().showMessage(_("LUT carregado: {nome}").format(nome=Path(path).name), 5000)

    def open_test_scene(self) -> None:
        img = testimage.make(1920, 1080)
        path = os.path.join(tempfile.gettempdir(), "pelicula_cena_de_teste.png")
        qimage_from(img).save(path)
        self.load_media(path, label=_("Cena de teste"), detect=True)

    def load_media(self, path: str, label: str | None = None, detect: bool = False, fps_str: str = "") -> None:
        """Abre um arquivo no modo Película. A edição recomeça com ele inteiro na linha do tempo.

        `detect`: o usuário abriu um arquivo novo (não um projeto salvo): um vídeo HDR (HLG/PQ) escolhe
        sozinho o perfil de entrada, se ele ainda é o padrão (`_detect_profile`). `fps_str`: velocidade de uma
        sequência de imagens (`path` = padrão plano_%04d.png).
        """
        try:
            info = media.probe(path, fps_str)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, _("Não foi possível abrir o arquivo.\n\n{erro}").format(erro=exc))
            return
        self.stop_play()
        sem_efeitos_ui.reset(self)
        self._file_infos[info.path] = info
        if detect:
            self._detect_profile(info)
            self.store.clear_keys()  # as chaves do look estão no tempo do arquivo anterior
        self._offer_input(info if detect else None)
        self.file_info = info
        self.cur = None
        self._media_label = label or (media.sequence_label(path, info.seq_start, info.frames) if info.is_sequence
                                      else Path(path).name)
        self.settings.setValue("last_dir", str(Path(path).parent))
        src = timeline.Source.from_info(info)
        self._sources = {src.path: src}
        self.bin.clear()
        self.bin.add_source(src)
        self._request_thumb(src)
        self._loading = True
        try:
            self.model.set_sequence(timeline.Sequence.for_source(src))
        finally:
            self._loading = False
        self.seqs_ui.reset()
        self._refresh_source(reset=True)

    def _detect_profile(self, info) -> None:
        """Perfil de entrada pelos metadados do arquivo (`media.auto_profile`): vídeo HDR (HLG/PQ) com o
        perfil no padrão Rec.709 passa para HLG/PQ; um arquivo sem HDR com o perfil em HLG/PQ volta para
        Rec.709. Perfis log escolhidos à mão nunca mudam.

        Só ao abrir um arquivo novo ou pôr o primeiro clipe numa montagem vazia (nunca ao reabrir um
        projeto salvo nem ao aplicar um preset). A troca entra no desfazer.
        """
        prof = media.auto_profile(self.store.get("entrada"), info)
        if prof is None:
            return
        self.store.set("entrada", prof)
        self.store.commit()
        self.statusBar().showMessage(self._profile_message(prof), 8000)

    def _offer_input(self, info) -> None:
        """1.6: os metadados de `info` indicam outro perfil de entrada (`media.suggest_input`)? Mostra o aviso com um
        botão (`InputNotice`); o look nunca muda sozinho. None (projeto reaberto, outro arquivo) esconde o aviso."""
        sug = media.suggest_input(info) if info is not None else None
        cur = self.store.get("entrada")
        self.input_notice.offer(sug if sug in dict(params.ENTRADAS) and sug != cur else None, cur)

    def _accept_input_suggestion(self, prof: str) -> None:
        """"Usar este perfil" do aviso: troca o Perfil do vídeo do look (entra no desfazer)."""
        if prof not in dict(params.ENTRADAS) or prof == self.store.get("entrada"):
            return
        self.store.set("entrada", prof)
        self.store.commit()
        self.statusBar().showMessage(_("Perfil do vídeo ajustado para {perfil}, pelos metadados do arquivo.")
                                     .format(perfil=profile_name(prof)), 8000)

    def _clip_profile_for(self, src: timeline.Source) -> str | None:
        """1.6: perfil de câmera de um clipe novo do modo Edição (`TimelineModel.clip_profile_for`): o sugerido pelos
        metadados quando difere da entrada do look (`camera.prefill`). O primeiro arquivo de uma montagem vazia fica
        em "Igual ao do look": o look é que se ajusta a ele (`_adopt_format`, como ao abrir no modo Película)."""
        from .. import camera
        if not src.is_file or not src.has_video:
            return None
        if all(c.src == src.path for c in self.model.seq.clips if c.kind == timeline.VIDEO):
            return None
        info = self._file_infos.get(src.path)
        return camera.prefill(media.suggest_input(info), self.store.values, info)

    @staticmethod
    def _profile_message(prof: str) -> str:
        name = _(dict(params.PARAMS["entrada"].choices).get(prof, prof))
        if prof in media.HDR_TRANSFERS.values():
            return _("Vídeo HDR detectado: Perfil do vídeo ajustado para {perfil}.").format(perfil=name)
        return _("Arquivo sem HDR: Perfil do vídeo de volta para {perfil}.").format(perfil=name)

    def _source_legal(self) -> bool:
        """A fonte da prévia chega ao look em faixa legal expandida? (`build_plan(..., legal=...)`)"""
        if self.src_seq is not None:
            return sequence.legal_range(self.src_seq)
        return media.legal_range(self.info) if self.info is not None else True

    def _set_media_enabled(self, on: bool) -> None:
        video = on and self.info is not None and not self.info.is_image
        for b in (self.btn_back, self.btn_play, self.btn_fwd, self.btn_in, self.btn_out, self.btn_clear, self.btn_loop):
            b.setEnabled(video)
        self.timeline.setEnabled(video)
        seqs = getattr(self, "seqs_ui", None)  # 1.7: com a aberta vazia, outra sequência ainda pode sair
        self.btn_export.setEnabled(on or (seqs is not None and seqs.can_export_other()))
        self.btn_frame.setEnabled(on)
        for b in (self.btn_zoom_out, self.btn_zoom_in, self.btn_full, self.btn_no_effects):
            b.setEnabled(on)

    def preview_size(self) -> tuple[int, int]:
        if self.src_seq is not None:
            return sequence.canvas_size(self.src_seq, None if self.preview_q == "full" else int(self.preview_q))
        info = self.info
        if self.preview_q == "full":
            h = info.height
        else:
            h = min(int(self.preview_q), info.height)
        w = max(2, int(round(info.width * h / info.height)))
        return w, max(2, h)

    def request_frame(self, f: int) -> None:
        if self.info is None:
            return
        f = int(min(max(f, 0), self.info.frames - 1))
        self.frame_idx = f
        self._update_time()
        w, h = self.preview_size()
        prof = sem_efeitos_ui.read_entrada(self)
        self._float_source = self.src_seq is None and media.float_input(self.info, prof)
        self._shutter_read = self._shutter()
        self.loader.request(self.src_seq if self.src_seq is not None else self.info, f, w, h, prof,
                            self._shutter_read, self.no_effects)

    def _frame_loaded(self, source, frame: int, img) -> None:
        expected = self.src_seq if self.src_seq is not None else self.info
        if source is not expected or self.playing:
            return
        # Arrastando o cursor, quadros de posições anteriores ainda podem chegar: a imagem aparece,
        # mas o cursor continua onde a pessoa deixou (antes ele voltava para trás por um instante).
        self._set_frame(frame, img, move_cursor=frame == self.frame_idx)
        self.thumb_timer.start()

    def _set_frame(self, frame: int, img, move_cursor: bool = True) -> None:
        """Mostra um quadro: imagem do arquivo ou camadas da montagem (compostas aqui, na GPU)."""
        self.cur_frame = frame
        if move_cursor:
            self.frame_idx = frame
        if isinstance(img, sequence.FrameLayers):
            self.cur_layers = img
            if not self._compose_current():
                return
        else:
            self.cur_layers = None
            self.cur_neutral_q = None
            self.cur = img
            self.cur_q = qimage_from(img)
        if move_cursor:
            self._update_time()
        self.render_now()

    def _live_layers(self, fl):
        """As camadas decodificadas com os ajustes atuais dos clipes (a cópia da thread pode estar velha)."""
        seq = self.model.seq
        out = []
        for li in fl.layers:
            clip = seq.find(li.layer.clip.id)
            if clip is not None:  # com as chaves de animação do clipe atual avaliadas neste quadro
                layer = dataclasses.replace(li.layer, clip=clip, values=seq.values_at(clip, fl.frame))
                out.append(dataclasses.replace(li, layer=layer))
        return sequence.FrameLayers(fl.frame, out)

    def frame_recipe(self, depth: int = 8, full: bool = False, alpha: bool | None = None) -> Recipe:
        """A receita do quadro da janela (`frame.Recipe`, a mesma da exportação): a prévia em 8 bits, no tamanho
        reduzido e com o pontilhado do look; `depth=16, full=True` é a do "Salvar quadro" (tamanho do arquivo,
        sem pontilhado e com o look que vai para a exportação). No modo Edição sem película, a prévia é só a
        montagem (`values` None); em 8 bits o look "Original" da exportação devolve a mesma imagem.
        `alpha`: saída RGBA (padrão: na prévia, quando a montagem tem "Fundo transparente"; no quadro cheio, não)."""
        info = self.info
        fps = info.fps if info is not None else 24.0
        seq = self.model.seq if self.src_seq is not None else None
        if full:
            size = (info.width, info.height)
            values = self._export_look()[0]
        else:
            size = self.preview_size() if info is not None else None
            values = None if (self.mode == "edicao" and not self.edit_film) else self.store.values
        if alpha is None:
            alpha = not full and seq is not None and seq.transparent
        return Recipe.for_source(values, fps, depth, legal=self._source_legal(), seq=seq, dither=not full,
                                 size=size, keys=self._export_keys(), burn=self._subtitle_burn(full),
                                 alpha=bool(alpha) and seq is not None, no_effects=self.no_effects)

    def _shutter(self) -> float:
        """1.6: o ângulo do obturador do look da prévia (0 = desligado ou sem película; `tempo_camera`)."""
        from .. import tempo_camera
        if self.no_effects:
            return 0.0
        return tempo_camera.shutter_angle(None if (self.mode == "edicao" and not self.edit_film) else self.store.values)

    def _subtitle_burn(self, full: bool = False):
        """Legendas gravadas da receita (`SubtitlesUI.burn`; nenhuma antes de a interface delas existir)."""
        ui = getattr(self, "subs_ui", None)
        return ui.burn(full) if ui is not None else None

    def _compose_current(self) -> bool:
        """Monta o quadro atual da sequência (com e, no modo Edição, sem os ajustes de cor dos clipes)."""
        if self.cur_layers is None:
            return False
        live = self._live_layers(self.cur_layers)
        recipe = self.frame_recipe()
        try:
            img = recipe.montage(self.engine, live)
            neutral = recipe.montage(self.engine, live, neutral=True) if self.mode == "edicao" else None
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(_("Erro ao montar o quadro: {erro}").format(erro=exc), 8000)
            return False
        self.cur = img
        self.cur_q = qimage_from(img)
        self.cur_neutral_q = qimage_from(neutral) if neutral is not None else None
        return True

    def _update_time(self) -> None:
        if self.info is None:
            return
        self.tl_editor.set_playhead(self.frame_idx)
        self.timeline.set_pos(self.frame_idx)
        self.time_label.setText(f"{timecode(self.frame_idx, self.info.fps)}  /  "
                                f"{timecode(self.info.frames - 1, self.info.fps)}")
        self._keys_follow_playhead()

    def _keys_follow_playhead(self) -> None:
        """Os controles com chaves (look e clipe) mostram o valor do quadro do cursor; mexer neles grava ali."""
        self.look_keys.set_frame(self.frame_idx)
        self.inspector.set_playhead(self.frame_idx)
        for strip in (self.look_strip, self.look_lane):
            if strip.isVisible():
                strip.update()

    def _preview_changed(self) -> None:
        self.preview_q = self.prev_combo.currentData()
        self.settings.setValue("preview_quality", self.preview_q)
        if self.info is not None:
            if self.playing:
                self.stop_play()
            self.request_frame(self.frame_idx)

    # ================================================================ modos Película / Edição
    def set_mode(self, mode: str, force: bool = False) -> None:
        """Troca entre o modo Película (look) e o modo Edição (montagem, cor e som dos clipes).
        `force`: aplica a tela mesmo sem mudar o modo (projeto aberto por cima da mesma tela)."""
        if mode not in MODES:
            return
        if mode == "edicao" and not modules.is_enabled(self.settings, "edicao"):
            mode = "pelicula"  # módulo desligado: a montagem continua sendo a entrada do look
        self.mode_switch.set_current(mode)
        if mode == self.mode and not force:
            return
        if self.preview_fullscreen:
            self.toggle_preview_fullscreen()
        self.stop_play()
        self.mode = mode
        edit = mode == "edicao"
        self.left_stack.setCurrentIndex(1 if edit else 0)
        self.right_panel.setCurrentIndex(1 if edit else 0)
        self.tl_editor.setVisible(edit)
        self.timeline.setVisible(not edit)
        self._sync_look_strips()
        for wdg in self._edit_only:
            wdg.setVisible(edit)
        self.btn_open.setText(_("Importar") if edit else _("Abrir"))
        self.btn_open.setToolTip(_("Importar vídeos, imagens e músicas para a edição (Ctrl+I)") if edit
                                 else _("Abrir vídeo, imagem ou projeto .plc (Ctrl+O)"))
        self._update_label_proc()
        self._update_history()
        self._refresh_source()
        self._update_mute_tip()
        if edit:
            self.tl_editor.setFocus()

    def _update_label_proc(self) -> None:
        self.viewer.label_proc = _("EDIÇÃO") if (self.mode == "edicao" and not self.edit_film) else _("PELÍCULA")
        if self.no_effects:
            self.viewer.label_proc = _("SEM EFEITOS")
        self.viewer.update()

    def _set_edit_film(self, on: bool) -> None:
        self.edit_film = bool(on)
        self._sync_look_strips()
        self.settings.setValue("edit_film", "true" if on else "false")
        self._update_label_proc()
        self.render_now()
        if self.src_seq is not None and not self.playing and self._shutter() != getattr(self, "_shutter_read", 0.0):
            self.request_frame(self.frame_idx)  # 1.6: com o look, o obturador muda os quadros lidos

    def _use_sequence(self) -> bool:
        """A prévia mostra a montagem? (no modo Película só quando ela difere do arquivo aberto)"""
        seq = self.model.seq
        if not seq.clips:
            return False
        if self.mode == "edicao" or self.file_info is None:
            return True
        return seq.direct_file() != self.file_info.path  # arquivo com transparência: sempre pela montagem

    def _film_info(self) -> media.MediaInfo | None:
        """O arquivo que o modo Película mostra quando não há montagem para mostrar. Com várias sequências, a aberta
        estar vazia é uma edição vazia (não o arquivo que estava aberto antes)."""
        if self.mode != "pelicula" or (not self.model.seq.clips and len(self.model.seq.family()) > 1):
            return None
        return self.file_info

    def _refresh_source(self, reset: bool = False) -> None:
        """Escolhe a fonte da prévia (arquivo ou montagem) e atualiza linha do tempo, rótulos e som."""
        was_seq = self.src_seq is not None
        if self._use_sequence():
            self.src_seq = self.model.seq.copy()
            info = sequence.media_info(self.src_seq)
        else:
            self.src_seq = None
            info = self._film_info()
        geometria_ui.sync_safe_window(self)
        if self.playing:
            self.stop_play()
        self.info = info
        if info is None:
            self.cur = None
            self.cur_q = None
            self.cur_layers = None
            self.cur_neutral_q = None
            self.viewer.set_images(None, None)
            self.hist.set_image(None)
            self.edit_scopes.set_image(None)
            self.timeline.set_media(1, 24.0)
            self._sync_film_markers()
            self.tl_editor.set_playhead(0)
            self.file_label.setText("")
            self.time_label.setText("00:00:00:00")   # nada do que estava aberto (outra sequência, por exemplo) fica
            self.st_prev.setText("")
            self.st_render.setText("")
            self.st_file.setText(_("Nenhum arquivo aberto") if self.mode == "pelicula"
                                 else _("Importe vídeos, imagens ou músicas para começar a edição"))
            self._set_media_enabled(False)
            self._set_audio("", "")
            self._update_title()
            return
        if reset:
            self.frame_idx = 0
            self.inp = self.outp = None
        last = max(0, info.frames - 1)
        self.frame_idx = min(self.frame_idx, last)
        if self.inp is not None and self.inp > last:
            self.inp = None
        if self.outp is not None and self.outp > last:
            self.outp = None
        self.timeline.set_media(info.frames, info.fps)
        self.timeline.set_inout(self.inp, self.outp)
        self._sync_film_markers()
        self.tl_editor.set_inout(self.inp, self.outp)
        if self.src_seq is not None:
            seq = self.src_seq
            n = sum(1 for c in seq.clips if c.kind == timeline.VIDEO)
            self.st_file.setText(_("Montagem {w}×{h} • {fps} fps • {n} clipes de imagem • {dur}").format(
                w=seq.width, h=seq.height, fps=i18n.fmt_decimal(seq.fps, 3), n=n,
                dur=timecode(seq.duration, seq.fps)))
            self.file_label.setText(_("Montagem da edição"))
            self._schedule_mix(immediate=not was_seq or reset)
        else:
            self.st_file.setText(info.summary())
            self.file_label.setText(self._media_label)
            self._set_audio("file", info.path if info.has_audio and not info.is_image else "")
        self._set_media_enabled(True)
        self.request_frame(self.frame_idx)
        self._update_title()

    def _model_changed(self, kind: str) -> None:
        """A linha do tempo mudou: ajuste de clipe só remonta o quadro; o resto recarrega a fonte."""
        if self._loading:
            return
        switched = self.seqs_ui.model_changed(kind)  # outra sequência aberta: o estado dela entra antes da prévia
        if kind == "sequencias":
            # Nomes e ordem das sequências: só as abas e a Mídia mudam (nada de recarregar a prévia).
            self._adopt_folder_sources()
        elif kind == "pastas":
            # Pastas da Mídia são só organização: a prévia e o som não mudam (a Mídia se refaz sozinha).
            self._adopt_folder_sources()
        elif kind == "markers":
            # Marcadores não mudam a imagem nem o som: nada de recarregar (nem parar a reprodução).
            self._sync_film_markers()
        elif kind == "subtitles":
            # Legendas também não: só o desenho delas gravado no vídeo muda (`frame.Recipe.burn`).
            self._uploaded = None
            self.render_now()
        elif kind == "values" and self.src_seq is not None and self._use_sequence():
            self.src_seq = self.model.seq.copy()
            if self._compose_current():
                self.render_now()
            if not self.playing:
                self.request_frame(self.frame_idx)
            self._schedule_mix()
        else:
            self._adopt_folder_sources()
            self._refresh_source()
            if switched:
                self._schedule_mix(immediate=True)  # o som da aba nova, sem esperar
        self._update_title()
        self._update_history()
        self._generated_timer.start()  # clipe sem arquivo mudado (ou desfeito): nome e miniatura na Mídia

    def _adopt_folder_sources(self) -> None:
        """Item de pasta que a Mídia ainda não mostra (um desfazer trouxe de volta): entra na lista."""
        seq = self.model.seq
        for path in list(seq.folders.items):
            if path in seq.sources and path not in self._sources:
                self.adopt_source(seq.sources[path])

    # ---------------------------------------------------------------- marcadores e capítulos
    def _sync_film_markers(self) -> None:
        """Marcadores da montagem na barra de tempo do modo Película (só para ver e pular até eles)."""
        seq = self.model.seq
        items = []
        if self.info is not None and seq.markers and abs(self.info.fps - seq.fps) < 1e-3:
            items = [(mk.frame, theme.MARKER_COLORS.get(mk.color, theme.ACCENT), mk.name)
                     for mk in seq.sorted_markers() if mk.frame < self.info.frames]
        self.timeline.set_markers(items)

    def goto_marker(self, step: int) -> None:
        """Shift+↓ / Shift+↑: próximo / anterior marcador (nos dois modos)."""
        if self.info is None:
            return
        seq = self.model.seq
        mk = seq.next_marker(self.frame_idx) if step > 0 else seq.previous_marker(self.frame_idx)
        if mk is None or mk.frame >= self.info.frames:
            return
        if self.mode == "edicao":
            self.model.select_marker(mk.id)
        self.seek(mk.frame)

    def add_marker(self) -> None:
        """M no modo Edição: marcador no cursor (se já há um ali, só o seleciona)."""
        if self.info is not None and self.mode == "edicao":
            self.model.add_marker(self.frame_idx)

    def _export_chapters(self) -> list[tuple[int, str]]:
        """Capítulos (quadro, título) da montagem, nos quadros do que vai ser exportado."""
        seq = self.model.seq
        if self.info is None or not seq.markers or abs(self.info.fps - seq.fps) > 1e-3:
            return []
        return chapters.points(seq)

    # ---------------------------------------------------------------- som da montagem
    def _set_audio(self, kind: str, path: str) -> None:
        """Troca o som da prévia (arquivo original ou mixagem da montagem) sem perder a reprodução."""
        if (kind, path) == self._audio_src:
            return
        self._audio_src = (kind, path)
        self._load_audio(path)
        self._meter_source()
        if self.playing and self._audio_ok and self.audio is not None:
            self._audio_seek(self.frame_idx)
            self.audio.play()

    def _schedule_mix(self, immediate: bool = False) -> None:
        if self.src_seq is None:
            return
        if immediate:
            self.mix_timer.stop()
            QTimer.singleShot(0, self._start_mix)
        else:
            self.mix_timer.start()

    def _start_mix(self) -> None:
        """Mixa o som da montagem num WAV temporário (em segundo plano) para tocar na prévia."""
        if self.src_seq is None:
            return
        seq = self.model.seq.copy()
        key = audiomix.mix_key(seq)
        if key == self._mix_key:
            self._set_audio("seq", self._mix_path)
            return
        if not seq.has_audio:
            self._mix_key, self._mix_path = key, ""
            self._set_audio("seq", "")
            return
        if key in self._mix_running:
            return  # esta mesma mixagem já está a caminho
        self._mix_token += 1
        path = os.path.join(tempfile.gettempdir(), f"pelicula_previa_{os.getpid()}_{self._mix_token}.wav")
        self._mix_files.append(path)
        self._mix_running[key] = path

        def run():
            try:
                ok = audiomix.render_mix(seq, path)
            except Exception:  # noqa: BLE001
                ok = False
            self._mix_bridge.done.emit(key, path if ok else "")

        threading.Thread(target=run, daemon=True, name="mixagem-previa").start()

    def _mix_done(self, key: str, path: str) -> None:
        self._mix_running.pop(key, None)
        if self.src_seq is None or key != audiomix.mix_key(self.model.seq.copy()):  # a mesma forma de `_start_mix`
            return  # já existe uma mixagem mais nova a caminho
        self._mix_key, self._mix_path = key, path
        self._set_audio("seq", path)
        self._clean_mixes(keep=path)

    def _clean_mixes(self, keep: str = "") -> None:
        running = set(self._mix_running.values())  # a mixagem a caminho ainda vai ser entregue
        for f in list(self._mix_files):
            if f == keep or f in running:
                continue
            try:
                if os.path.exists(f):
                    os.remove(f)
                self._mix_files.remove(f)
            except OSError:
                pass  # ainda aberto pelo player; tenta de novo depois

    def audio_stop_and_clean(self) -> None:
        if self.audio is not None:
            from PySide6.QtCore import QUrl
            self.audio.stop()
            self.audio.setSource(QUrl())
        self._mix_running.clear()
        self._clean_mixes()
        self._meter_close()

    def _peaks_for(self, path: str):
        """Forma de onda de um arquivo para a linha do tempo (calculada em segundo plano na 1ª vez)."""
        if path in self._peaks:
            return self._peaks[path]
        src = self.model.seq.sources.get(path)
        if src is not None and not src.is_file:
            return None  # clipe sem arquivo: sem som
        if path not in self._peaks_pending:
            self._peaks_pending.add(path)

            def run():
                try:
                    data = audiomix.peaks(path)
                except Exception:  # noqa: BLE001
                    data = None
                self._peaks[path] = data
                self._mix_bridge.peaks.emit(path)

            threading.Thread(target=run, daemon=True, name="forma-de-onda").start()
        return None

    # ---------------------------------------------------------------- mídia da edição
    def import_dialog(self) -> None:
        d = str(self.settings.value("last_dir", str(Path.home())))
        paths, _f = QFileDialog.getOpenFileNames(self, _("Importar para a edição"), d, import_filter())
        if paths:
            self.import_paths(paths)

    def _probe_source(self, path: str) -> timeline.Source | None:
        src = self._sources.get(path) or self.model.seq.sources.get(path)
        if src is None:
            self._recovery_point()
            try:
                src = media.probe_source(path, self._file_infos)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, APP_NAME, _("Não foi possível abrir {nome}.\n\n{erro}").format(
                    nome=Path(path).name, erro=exc))
                return None
        return self.adopt_source(src)

    def adopt_source(self, src: timeline.Source) -> timeline.Source:
        """Põe uma fonte na Mídia (uma vez só), com miniatura: arquivo aberto ou clipe sem arquivo
        (`timeline.Source.virtual`, desenhado por `sequence.RENDERERS`). Inserir na linha do tempo continua
        sendo `model.insert_media(src, …)` (ou arrastar da Mídia)."""
        if src.path not in self._sources:
            self._sources[src.path] = src
            self.bin.add_source(src)
            self._request_thumb(src)
        return self._sources[src.path]

    # ---------------------------------------------------------------- clipes sem arquivo ("Novo" da Mídia)
    def new_generated(self, kind_id: str) -> None:
        """"Novo ▸" da Mídia: cria o clipe sem arquivo (gerador ou título), põe na Mídia e no cursor, na faixa de
        vídeo mais baixa que está livre ali (por cima do que já aparece), escolhido para ajustar no inspetor."""
        maker = generators_ui.maker_of(kind_id)
        if maker is None:
            return
        if self.mode != "edicao":
            self.set_mode("edicao")
        self.stop_play()
        seq = self.model.seq
        src = maker(seq)
        self.adopt_source(src)
        self._generated_seen[src.path] = json.dumps(src.data, sort_keys=True)
        at = max(0, int(self.frame_idx)) if seq.clips else 0
        track = self._free_video_track(at, seq.default_dur(src))
        self.model.insert_media(src, at=at, vtrack=track)
        self.statusBar().showMessage(_("{nome} na faixa V{faixa}: ajuste no inspetor, à direita.").format(
            nome=src.name, faixa=track + 1), 6000)
        if src.kind == titles.KIND and not self.title_editor.isHidden():
            self.title_editor.focus_text()  # já digitar o texto do título

    def _free_video_track(self, at: int, dur: int) -> int:
        """A faixa de vídeo mais baixa, destravada e sem nada em [at, at + dur) (uma nova acima de todas, se não há)."""
        seq = self.model.seq
        n = len(seq.kind_tracks(timeline.VIDEO))
        for t in range(n):
            tr = seq.track(timeline.VIDEO, t)
            if tr is not None and tr.locked:
                continue
            if all(c.end <= at or c.start >= at + dur for c in seq.clips_on(timeline.VIDEO, t)):
                return t
        return n

    def _sync_generated_sources(self) -> None:
        """Clipes sem arquivo mudados no inspetor (ou num desfazer): a Mídia mostra o nome e a miniatura novos."""
        for path, src in self.model.seq.sources.items():
            if src.is_file or src.is_nested or path not in self._sources:
                continue
            data = json.dumps(src.data, sort_keys=True)
            if self._generated_seen.get(path) == data:
                continue
            self._generated_seen[path] = data
            self._sources[path] = src
            self.bin.add_source(src)
            self._request_thumb(src)

    def _request_thumb(self, src: timeline.Source) -> None:
        if not src.has_video or src.is_nested:  # uma sequência na Mídia mostra o ícone dela
            return

        def run():
            try:
                tw = 192
                th = max(2, int(round(tw * src.height / max(1, src.width))))
                if not src.is_file:  # clipe sem arquivo: o próprio gerador, no começo
                    img = sequence.source_thumbnail(src, tw, th, rgba=src.has_alpha)
                else:
                    f = 0 if src.is_image else min(src.frames - 1, int(src.fps))
                    img = media.grab_frame(src.to_info(), f, tw, th, 8, alpha=src.has_alpha)
                if img.ndim == 3 and img.shape[2] == 4:  # transparência sobre o xadrez (RGBA pré-multiplicado)
                    from .alphaview import over_checker
                    img = over_checker(img, premultiplied=True)
            except Exception:  # noqa: BLE001
                return
            self._mix_bridge.thumb.emit(src.path, qimage_from(img))

        threading.Thread(target=run, daemon=True, name="miniatura-midia").start()

    def _adopt_format(self, src: timeline.Source) -> None:
        """Primeiro arquivo numa montagem vazia: a sequência fica com a resolução e o fps dele (e, se for
        vídeo HDR, o look passa a usar o perfil HLG/PQ, como ao abrir o arquivo no modo Película)."""
        if self.model.seq.clips or not src.has_video:
            return
        ref = timeline.Sequence.for_source(src, with_media=False)
        self.model.set_settings(ref.width, ref.height, ref.fps_str)
        if not src.is_image and src.is_file:  # clipe sem arquivo não tem metadados de câmera
            self._detect_profile(src)
            self._offer_input(self._file_infos.get(src.path))  # 1.6: só sugere (aviso com um botão)

    def _insert(self, src: timeline.Source, at: int | None = None, kind: str = timeline.VIDEO, track: int = 0,
                insert: bool = False):
        """Põe o arquivo na montagem; `insert` (com um ponto `at`) empurra o que vem depois em vez de cobrir."""
        seq = self.model.seq
        if src.is_nested:  # 1.7: uma sequência ainda não entra como clipe pela Mídia (a interface do aninhar vem depois)
            self.statusBar().showMessage(_("Ainda não dá para pôr uma sequência dentro de outra pela Mídia."), 6000)
            return []
        self._adopt_format(src)
        if not src.has_video:
            if at is None:
                # Música: começa no início, na primeira faixa de áudio vazia.
                tracks = seq.kind_tracks(timeline.AUDIO)
                track = next((i for i in range(len(tracks)) if not seq.clips_on(timeline.AUDIO, i)), len(tracks))
                return self.model.insert_media(src, at=0, atrack=track)
            return self.model.insert_media(src, at=at, atrack=track if kind == timeline.AUDIO else 0, insert=insert)
        return self.model.insert_media(src, at=at, vtrack=track if kind == timeline.VIDEO else 0,
                                       atrack=track if kind == timeline.AUDIO else 0, insert=insert)

    def import_paths(self, paths: list[str]) -> None:
        """Importa arquivos para a edição: entram na Mídia e vão para o fim da linha do tempo."""
        paths = [p for p in paths if p and (os.path.isfile(p) or os.path.isdir(p))]
        if not paths:
            return
        if self.mode != "edicao":
            self.set_mode("edicao")
            if self.mode != "edicao":
                return  # modo Edição desligado em Configurações › Recursos
        paths = [p for p in self._offer_sequences(paths) if os.path.isfile(p) or p in self._sources]
        if not paths:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            srcs = [s for s in (self._probe_source(p) for p in paths) if s is not None]
        finally:
            QApplication.restoreOverrideCursor()
        if not srcs:
            return
        self.settings.setValue("last_dir", str(Path(paths[0]).parent))
        before = self.store.get("entrada")
        for src in srcs:
            self._insert(src)
        msg = _("{n} arquivo(s) na linha do tempo.").format(n=len(srcs))
        detected = self.store.get("entrada") != before  # primeiro clipe HDR numa montagem vazia
        if detected:
            msg += " " + self._profile_message(self.store.get("entrada"))
        self.statusBar().showMessage(msg, 8000 if detected else 5000)

    def add_to_timeline(self, path: str) -> None:
        src = self._probe_source(path)
        if src is not None:
            self._insert(src)

    def drop_on_timeline(self, paths: list, frame: int, kind: str, track: int, insert: bool = False) -> int:
        """Arquivos (do sistema ou da Mídia) soltos na linha do tempo: entram no ponto e na faixa do mouse,
        um depois do outro; `insert` empurra o que vem depois (modo inserir ou Ctrl). Devolve o fim do último."""
        pos = max(0, int(frame))
        for path in self._offer_sequences([str(p) for p in paths]):
            src = self._probe_source(str(path))
            if src is None:
                continue
            made = self._insert(src, at=pos, kind=kind, track=max(0, int(track)), insert=insert)
            if made:
                pos = max(c.end for c in made)
        return pos

    def place_at_cursor(self, paths: list, insert: bool) -> None:
        """"Inserir no cursor" (`,`) / "Sobrescrever no cursor" (`.`): os itens escolhidos na Mídia entram no
        cursor, na V1 e na A1 — inserir empurra o que vem depois, sobrescrever cobre — e o cursor vai para o
        fim do que entrou (para o próximo)."""
        if self.mode != "edicao" or not paths:
            return
        self.stop_play()
        end = self.drop_on_timeline(list(paths), self.frame_idx, timeline.VIDEO, 0, insert=insert)
        if self.info is not None:
            self.seek(end)

    def trim_to_playhead(self, side: str) -> None:
        """Q (`side="start"`) / W (`"end"`): apara até o cursor o clipe sob ele e fecha o espaço. Com Q, o cursor
        vai para o novo começo do clipe (o quadro que estava sob ele continua na tela)."""
        self.stop_play()
        n = self.model.trim_to_playhead(self.frame_idx, side)
        if not n:
            self.statusBar().showMessage(_("Q / W: deixe o cursor dentro de um clipe numa faixa destravada."), 4000)
        elif side == "start":
            self.seek(max(0, self.frame_idx - n))

    def _bin_files(self, paths: list, folder: str = "") -> None:
        """Arquivos soltos na Mídia: ficam só na lista (arraste depois para a linha do tempo). `folder`: a pasta da
        Mídia onde eles entram. Uma pasta do sistema vira uma pasta da Mídia com o mesmo nome e os arquivos dela
        (sem descer nas subpastas), a não ser que seja de imagens numeradas (aí vale a pergunta da sequência)."""
        paths = [str(p) for p in paths]
        dirs = [p for p in paths if os.path.isdir(p) and media.find_sequence(p) is None]
        paths = self._offer_sequences([p for p in paths if p not in dirs])
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            adopted = self._probe_all(paths)
            if folder:
                self.model.media_to_folder(adopted, folder, self._sources)
            for d in dirs:
                inside = self._probe_all(pastas_ui.media_in_dir(d))
                self.model.folder_with_media(Path(d).name, folder, inside, self._sources)
        finally:
            QApplication.restoreOverrideCursor()

    def _probe_all(self, paths: list[str]) -> list[str]:
        """Põe os arquivos na Mídia; devolve os caminhos que entraram."""
        out: list[str] = []
        for p in paths:
            if os.path.isfile(str(p)) or p in self._sources:
                src = self._probe_source(str(p))
                if src is not None:
                    out.append(src.path)
        return out

    # ---------------------------------------------------------------- sequências de imagens numeradas
    def _ask_sequence(self, path: str, single: bool = True):
        """Imagem numerada (ou pasta de imagens numeradas): (escolha, sequência, velocidade) ou None se cancelou;
        ("", None, "") se não há sequência ali. A pergunta é `imageseq_dialog.ask`."""
        from . import imageseq_dialog
        if not os.path.isdir(path) and Path(path).suffix.lower() not in media.SEQUENCE_EXT:
            return "", None, ""
        found = media.find_sequence(path)
        if found is None:
            return "", None, ""
        fps = self.model.seq.fps_str if self.model.seq.clips else "24/1"
        ans = imageseq_dialog.ask(self, found, fps, single=single)
        if ans is None:
            return None
        return ans[0], found, ans[1]

    def _sequence_source(self, found, fps: str) -> timeline.Source | None:
        try:
            return self.adopt_source(timeline.Source.from_info(media.probe_sequence(found, fps)))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, _("Não foi possível abrir {nome}.\n\n{erro}").format(
                nome=found.label, erro=exc))
            return None

    def _offer_sequences(self, paths: list[str]) -> list[str]:
        """Imagens numeradas (plano_0001.png…) ou uma pasta delas: pergunta se entram como uma sequência; se sim,
        a fonte vai para a Mídia (na velocidade escolhida) e o caminho dela (o padrão plano_%04d.png) toma o lugar
        dos arquivos. Uma pergunta por sequência, mesmo com vários quadros dela escolhidos."""
        from . import imageseq_dialog
        out: list[str] = []
        done: dict[str, str] = {}
        for p in paths:
            p = str(p)
            if p in self._sources or p in self.model.seq.sources:
                out.append(p)
                continue
            found = media.find_sequence(p) if (os.path.isdir(p) or Path(p).suffix.lower() in media.SEQUENCE_EXT) \
                else None
            if found is not None and found.pattern in done:
                if done[found.pattern] == imageseq_dialog.IMAGE and os.path.isfile(p):
                    out.append(p)
                continue
            ans = self._ask_sequence(p, single=not os.path.isdir(p)) if found is not None else ("", None, "")
            if ans is None:
                done[found.pattern] = ""
                continue
            choice, found, fps = ans
            if found is None or choice != imageseq_dialog.SEQUENCE:
                if found is not None:
                    done[found.pattern] = imageseq_dialog.IMAGE
                    if os.path.isdir(p):  # pasta como imagens separadas: cada quadro do trecho
                        out += [found.file(n) for n in range(found.first, found.last + 1)]
                        continue
                if not os.path.isdir(p):  # o resto segue como antes (quem chama confere o arquivo)
                    out.append(p)
                continue
            done[found.pattern] = choice
            src = self._sequence_source(found, fps)
            if src is not None:
                out.append(src.path)
        return out

    def _film_target(self, path: str) -> tuple[str, str]:
        """Modo Película: o que abrir para `path` — (padrão, velocidade) de uma sequência de imagens, (path, "")
        para um arquivo comum, ("", "") se o usuário cancelou ou a pasta não tem imagens numeradas."""
        from . import imageseq_dialog
        ans = self._ask_sequence(path)
        if ans is None:
            return "", ""
        choice, found, fps = ans
        if found is not None and choice == imageseq_dialog.SEQUENCE:
            return found.pattern, fps
        if os.path.isdir(path):
            if found is None:
                QMessageBox.information(self, APP_NAME, _("A pasta não tem imagens numeradas para abrir como "
                                                          "sequência."))
            return "", ""
        return path, ""

    def _relink(self, seq: timeline.Sequence, path: str, new: str) -> None:
        """Relocaliza um arquivo da montagem; numa sequência de imagens, `new` é um quadro dela na pasta nova."""
        src = seq.sources.get(path)
        if src is not None and src.is_sequence:
            found = media.find_sequence(new)
            if found is None:
                QMessageBox.warning(self, _("Abrir projeto"), _("O arquivo escolhido não faz parte de uma sequência "
                                                                 "de imagens numeradas."))
                return
            seq.relink(path, found.pattern, seq_start=found.first)
            return
        seq.relink(path, new)

    def _open_sequence_entry(self, path: str) -> None:
        """Dois cliques numa sequência da Mídia: abre a aba dela."""
        src = self._sources.get(path)
        if src is not None and src.is_nested:
            self.seqs_ui.activate(src.nested_id)

    def _bin_remove(self, path: str) -> None:
        src = self._sources.get(path)
        if src is not None and src.is_nested:  # 1.7: tirar uma sequência da Mídia é apagá-la (pergunta antes)
            self.seqs_ui.delete(src.nested_id)
            return
        if any(c.src == path for c in self.model.seq.clips):
            QMessageBox.information(self, _("Mídia"), _("Este arquivo está na linha do tempo. Apague os clipes dele "
                                                       "antes de tirá-lo da Mídia."))
            return
        self._sources.pop(path, None)
        self.bin.remove(path)
        self.model.media_forget(path)  # sai também da pasta onde estava

    def sequence_settings(self) -> None:
        from .sequence_dialog import SequenceDialog
        dlg = SequenceDialog(self, self.model.seq)
        if dlg.exec():
            w, h, fps, bg = dlg.values()
            self.model.set_settings(w, h, fps, bg, micro_fade=dlg.micro_fade(), magnetic=dlg.magnetic(),
                                    transparent=dlg.transparent(), window=dlg.window())

    def auto_adjust_clip(self, cid: str, whole: bool = True) -> None:
        """Cor automática: analisa o quadro do clipe (sem os ajustes) e preenche exposição, níveis e balanço.
        `whole`: 1.6, o clipe inteiro (`colorsimple.sample_frames`; vídeo de arquivo) em vez do quadro atual."""
        if whole and cor_ui.auto_whole_clip(self, cid):
            return
        seq = self.model.seq
        clip = seq.find(cid)
        if clip is None or clip.kind != timeline.VIDEO:
            return
        img = None
        if self.cur_layers is not None:
            img = next((li.image for li in self.cur_layers.layers
                        if li.layer.clip.id == cid and not li.layer.extension), None)
        if img is None:
            src = seq.sources[clip.src]
            t = self.frame_idx if clip.start <= self.frame_idx < clip.end else clip.start
            try:
                w = 480
                img = media.grab_frame(src.to_info(), seq.src_frame(clip, t), w,
                                       max(2, int(round(w * src.height / max(1, src.width)))), 8)
            except Exception as exc:  # noqa: BLE001
                self.statusBar().showMessage(_("Erro ao ler o quadro: {erro}").format(erro=exc), 8000)
                return
        vals = dict(clip.values)
        vals.update(compositor.auto_adjust(img))
        self.model.set_clip_values(cid, vals)
        self.statusBar().showMessage(_("Cor automática aplicada em {nome}.").format(nome=clip.name or "-"), 4000)

    # ================================================================ renderização
    def schedule_render(self) -> None:
        if not self.playing:
            self.render_timer.start()

    def render_now(self) -> None:
        if self.cur is None:
            return
        h, w = self.cur.shape[:2]
        recipe = self.frame_recipe()
        if recipe.values is None:
            # Só a edição: o quadro montado já é o resultado (com as legendas gravadas, se houver).
            img = recipe.look(self.engine, self.cur, self.cur_frame) if recipe.burn is not None else self.cur
            self.viewer.set_images(self.cur_q if img is self.cur else qimage_from(img), self.cur_neutral_q or self.cur_q)
            self.hist.set_image(img)
            self.edit_scopes.set_image(img)
            self.st_prev.setText(_("Prévia {w}×{h}").format(w=w, h=h))
            self.st_render.setText("")
            cor_ui.after_render(self, recipe)
            return
        upload = self._uploaded is not self.cur  # só os ajustes mudaram: a imagem já está na GPU
        self._uploaded = self.cur
        v = self.store.values
        t0 = time.perf_counter()
        try:
            out = recipe.look(self.engine, self.cur, self.cur_frame, upload=upload)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(_("Erro na renderização: {erro}").format(erro=exc), 8000)
            return
        ms = (time.perf_counter() - t0) * 1000
        orig = self.cur_neutral_q if (self.mode == "edicao" and self.cur_neutral_q is not None) else self.cur_q
        self.viewer.set_images(qimage_from(out), orig)
        self.hist.set_image(out)
        self.edit_scopes.set_image(out)
        self.st_render.setText(f"{ms:.0f} ms")
        self.st_prev.setText(_("Prévia {w}×{h}").format(w=w, h=h))
        cor_ui.after_render(self, recipe)
        if v["lut_on"] and v["lut_arquivo"] and recipe.lut is None and not recipe.no_effects:
            self.statusBar().showMessage(_("O LUT escolhido não pôde ser lido."), 5000)

    def _render_thumbs(self) -> None:
        tw, th = THUMB_W * 2, THUMB_H * 2
        if self.cur_q is not None:
            img = self.cur_q.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
            x = (img.width() - tw) // 2
            y = (img.height() - th) // 2
            src = array_from(img.copy(x, y, tw, th))
        else:
            src = testimage.make(tw, th)
        self.thumb_engine.set_input(src)
        # Cada miniatura é o preset aplicado ao quadro atual: com o perfil do arquivo (aplicar um preset não
        # muda o perfil, veja presets.SOURCE_KEYS) e a faixa da fonte; sem quadro, a cena de teste é Rec.709.
        current = self.store.values if self.cur_q is not None else None
        legal = self._source_legal() if self.cur_q is not None else False
        self._thumb_entrada = self.store.get("entrada")
        images = {}
        for item in self._all_presets():
            v = presets.with_source(item["valores"], current)
            try:  # a mesma receita do quadro, na imagem já enviada (quadro 3 a 24 quadros/s, sem pontilhado)
                out = Recipe.for_source(v, 24.0, 8, legal=legal).look(self.thumb_engine, src, 3, upload=False)
            except Exception:  # noqa: BLE001
                continue
            images[item["id"]] = qimage_from(out)
        self.looks.set_images(images)

    def _on_param(self, key: str) -> None:
        for c in self.cards:
            if key == "*" or key in c.keys():
                c.refresh(key)
        self._sync_look_strips()
        self.schedule_render()
        notice = getattr(self, "input_notice", None)
        if notice is not None and key in ("entrada", "*"):
            notice.sync(self.store.get("entrada"))  # 1.6: o perfil sugerido já está no look
        timer = getattr(self, "thumb_timer", None)
        if timer is not None and self.store.get("entrada") != getattr(self, "_thumb_entrada", None):
            timer.start()  # as miniaturas dos presets usam o perfil do arquivo
        if (key in ("entrada", "*") and self.info is not None and self.src_seq is None and not self.playing
                and media.float_input(self.info, sem_efeitos_ui.read_entrada(self)) != getattr(self, "_float_source", False)):
            self.request_frame(self.frame_idx)  # log ↔ Rec.709: o quadro é lido de novo (super-brancos em float)
        elif (self.src_seq is not None and not self.playing and key in ("obturador_on", "obturador_angulo", "*")
              and self._shutter() != getattr(self, "_shutter_read", 0.0)):
            self.request_frame(self.frame_idx)  # 1.6: o obturador muda os quadros lidos de cada clipe
        self._update_modified()
        self._update_title()
        if self.curve_graph.isVisible():
            self.curve_timer.start()

    def _set_curve_visible(self, on: bool) -> None:
        self.curve_graph.setVisible(bool(on))
        self.settings.setValue("show_curve", "true" if on else "false")
        if on:
            self._update_curve()

    def _update_curve(self) -> None:
        """Curva do look atual: o eixo dos cinzas de um LUT assado na GPU (mesmo caminho de cor do app)."""
        if not self.curve_graph.isVisible():
            return
        self.curve_graph.update_from(self.engine, self.store.values, legal=self._source_legal())

    # ================================================================ reprodução
    def toggle_play(self) -> None:
        if self.playing or self._rev_rate:
            self.stop_play()
        else:
            self.start_play()

    # ================================================================ som da prévia
    def _ensure_audio(self) -> bool:
        if self.audio is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return False
        self.audio_out = QAudioOutput(self)
        self.audio = QMediaPlayer(self)
        self.audio.setAudioOutput(self.audio_out)
        self.audio_out.setMuted(self.btn_mute.isChecked())
        self.audio_out.setVolume(self.vol.value())
        return True

    def _load_audio(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        self._audio_ok = bool(path) and self._ensure_audio()
        if self.audio is not None:
            self.audio.stop()
            self.audio.setSource(QUrl.fromLocalFile(path) if self._audio_ok else QUrl())
        self.btn_mute.setEnabled(self._audio_ok)
        self.vol.setEnabled(self._audio_ok)
        self._update_mute_tip()

    def _update_mute_tip(self) -> None:
        """No modo Película o M liga/desliga o som; no modo Edição o M põe um marcador e o som fica no Shift+M
        (que vale nos dois modos)."""
        if not self._audio_ok:
            self.btn_mute.setToolTip(_("Este arquivo não tem som"))
        elif self.mode == "edicao":
            self.btn_mute.setToolTip(_("Som da prévia (Shift+M liga/desliga)"))
        else:
            self.btn_mute.setToolTip(_("Som da prévia (M liga/desliga)"))

    def _set_muted(self, on: bool) -> None:
        self.btn_mute.setIcon(icons.icon("mute" if on else "volume", theme.TEXT, 18))
        if self.audio_out is not None:
            self.audio_out.setMuted(on)
        self.settings.setValue("audio_muted", "true" if on else "false")

    def _set_volume(self, v: float) -> None:
        if self.audio_out is not None:
            self.audio_out.setVolume(v)
        self.settings.setValue("audio_volume", v)

    def _audio_seek(self, frame: int) -> None:
        if self._audio_ok and self.audio is not None and self.info is not None:
            self.audio.setPosition(int(frame / self.info.fps * 1000))
            self._audio_sync_t = time.perf_counter()

    def _audio_follow(self, frame: int) -> None:
        """Mantém o som junto do quadro mostrado (corrige se escorregar mais de 0,15 s)."""
        if not self._audio_ok or self.audio is None or not self.playing:
            return
        now = time.perf_counter()
        if now - self._audio_sync_t < 1.0:
            return
        expected = frame / self.info.fps * 1000
        if abs(self.audio.position() - expected) > 150:
            self._audio_seek(frame)

    def start_play(self, start: int | None = None) -> None:
        if self.info is None or self.info.is_image:
            return
        loop_start = self.inp or 0
        end = self.outp if self.outp is not None else self.info.frames - 1
        f = self.frame_idx if start is None else start
        if f >= end or f < loop_start and self.inp is not None:
            f = loop_start
        w, h = self.preview_size()
        self.player.start(self.src_seq if self.src_seq is not None else self.info, f, end, w, h, self.loop,
                          loop_start, sem_efeitos_ui.read_entrada(self), self._shutter(), self.no_effects)
        self._play_t0 = None
        self._play_f0 = f
        self._play_last = f
        self._play_pending = None
        self.playing = True
        if self._play_rate == 1:  # J/K/L: o som e o medidor só valem a 1× para a frente
            if self._audio_ok and self.audio is not None:
                self._audio_seek(f)
                self.audio.play()
            self._meter_start()
        self.btn_play.setIcon(icons.icon("pause", theme.TEXT, 18))
        self.play_timer.start(max(5, int(500 / self.info.fps)))

    def stop_play(self) -> None:
        self._shuttle_halt()
        if not self.playing:
            return
        self.player.stop()
        self.play_timer.stop()
        self.playing = False
        if self.audio is not None:
            self.audio.pause()
        self.meter_timer.stop()
        self._meter_pos = None
        if self._meter_enabled:
            self.meter.idle()
        self.btn_play.setIcon(icons.icon("play", theme.TEXT, 18))
        self.thumb_timer.start()

    def _play_tick(self) -> None:
        """Mostra o quadro certo para o tempo decorrido, pulando quadros se a prévia atrasar."""
        now = time.perf_counter()
        q = self.player.q
        item = self._play_pending
        self._play_pending = None
        while True:
            if item is None:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    return
            f = item[0]
            if f is None:
                self.stop_play()
                return
            if self._play_t0 is None or f < self._play_last:
                if self._play_t0 is not None:
                    self._audio_seek(f)
                self._play_t0, self._play_f0 = now, f
            target = self._play_f0 + int((now - self._play_t0) * self.info.fps * self._play_rate)
            if f > target:
                self._play_pending = item
                return
            if f < target:
                try:
                    item = q.get_nowait()
                    continue
                except queue.Empty:
                    pass
            break
        self._play_last = f
        self._set_frame(f, item[1])
        if self._play_rate == 1:
            self._audio_follow(f)

    # ================================================================ J/K/L (shuttle)
    SHUTTLE_MAX = 8

    def shuttle_rate(self) -> int:
        """Velocidade da reprodução: 0 parada, 1/2/4/8 para a frente, −1/−2/−4/−8 para trás."""
        if self._rev_rate:
            return -self._rev_rate
        return self._play_rate if self.playing else 0

    def shuttle(self, direction: int) -> None:
        """L (`direction` > 0) / J (< 0): reproduz para a frente / para trás; de novo no mesmo sentido dobra a
        velocidade (1, 2, 4, 8×); no outro sentido volta a 1×. Com o K apertado, anda um quadro."""
        if self.info is None or self.info.is_image:
            return
        if self._k_held:
            self.step(1 if direction > 0 else -1)
            return
        r = self.shuttle_rate()
        if r and (r > 0) == (direction > 0):
            new = max(-self.SHUTTLE_MAX, min(self.SHUTTLE_MAX, r * 2))
        else:
            new = 1 if direction > 0 else -1
        self._set_shuttle(new)

    def _set_shuttle(self, rate: int) -> None:
        if rate > 0:
            was = self.playing
            self._shuttle_halt()            # para trás → para a frente
            self._play_rate = int(rate)
            if not was:
                self.start_play()
            else:
                self._play_t0 = None        # o relógio recomeça do quadro atual, na velocidade nova
                if rate != 1:               # sem som fora de 1× para a frente
                    if self.audio is not None:
                        self.audio.pause()
                    self.meter_timer.stop()
                    if self._meter_enabled:
                        self.meter.idle()
        else:
            self.stop_play()
            self._rev_rate = int(-rate)
            self._rev_t0 = time.perf_counter()
            self._rev_f0 = self._rev_last = self.frame_idx
            self.btn_play.setIcon(icons.icon("pause", theme.TEXT, 18))
            self.rev_timer.start()
        self._update_shuttle_label()

    def _shuttle_halt(self) -> None:
        """Para o J (para trás) e volta a velocidade a 1× (o próximo play é normal, com som)."""
        self._play_rate = 1
        if self._rev_rate:
            self._rev_rate = 0
            self.rev_timer.stop()
            self.btn_play.setIcon(icons.icon("play", theme.TEXT, 18))
            self.thumb_timer.start()
        self._update_shuttle_label()

    def _reverse_tick(self) -> None:
        """J: pede o quadro do relógio, andando para trás, ao carregador por busca (`FrameLoader`). Ele só
        decodifica o pedido mais recente: a interface não trava e cada quadro mostrado é o certo (se a busca
        for lenta, pula quadros). Respeita a entrada/saída e o Repetir."""
        if self.info is None or not self._rev_rate:
            self._shuttle_halt()
            return
        now = time.perf_counter()
        if self.frame_idx != self._rev_last:      # o cursor foi mexido: continua dali
            self._rev_t0, self._rev_f0 = now, self.frame_idx
        lo = self.inp or 0
        hi = self.outp if self.outp is not None else self.info.frames - 1
        target = self._rev_f0 - int((now - self._rev_t0) * self.info.fps * self._rev_rate)
        done = False
        if target < lo:
            if self.loop and hi > lo:
                self._rev_t0, self._rev_f0 = now, hi
                target = hi
            else:
                target, done = lo, True
        if target != self.frame_idx:
            self.request_frame(target)
        self._rev_last = self.frame_idx
        if done:
            self._shuttle_halt()

    def _update_shuttle_label(self) -> None:
        lbl = getattr(self, "shuttle_label", None)
        if lbl is None:
            return
        r = self.shuttle_rate()
        lbl.setText("" if r in (0, 1) else (f"◀◀ {-r}×" if r < 0 else f"{r}× ▶▶"))
        lbl.setVisible(r not in (0, 1))

    # ================================================================ medidor de som (módulo medidor_som)
    METER_JUMP_S = 5.0  # o relógio pulou mais que isso para a frente: medição nova

    def _meter_source(self) -> None:
        """Abre o som que o medidor lê, o mesmo que está tocando: a mixagem da montagem (WAV pronto) ou o
        som do arquivo, decodificado uma vez num WAV temporário em segundo plano. Nada disso vai para a
        exportação."""
        kind, path = self._audio_src
        want = (kind, path) if self._meter_enabled and path else ("", "")
        if want == self._meter_for:
            return
        self._meter_close(drop_files=not want[1])
        self._meter_for = want
        self.meter.clear()
        kind, path = want
        if kind == "seq":
            self._meter_open(path)
        elif path:
            key = self._meter_key(path)
            if self._meter_wav[0] == key and os.path.exists(self._meter_wav[1]):
                self._meter_open(self._meter_wav[1])
            else:
                self._meter_decode(path)

    @staticmethod
    def _meter_key(path: str) -> tuple:
        try:
            return path, os.path.getmtime(path)
        except OSError:
            return path, None

    def _meter_decode(self, path: str) -> None:
        self._meter_drop_files()
        token = self._meter_token
        out = os.path.join(tempfile.gettempdir(), f"pelicula_medidor_{os.getpid()}_{token}.wav")
        self._meter_files.append(out)
        cancel = self._meter_cancel = threading.Event()
        self.meter.set_waiting(True)

        def run():
            try:
                ok = audiomix.decode_wav(path, out, cancel)
            except Exception:  # noqa: BLE001
                ok = False
            self._mix_bridge.meter.emit(token, out if ok else "")

        threading.Thread(target=run, daemon=True, name="medidor-som").start()

    def _meter_decoded(self, token: int, wav: str) -> None:
        if token != self._meter_token:  # a fonte mudou enquanto decodificava
            if wav:
                self._meter_remove(wav)
            return
        self._meter_cancel = None
        self.meter.set_waiting(False)
        if wav:
            self._meter_wav = (self._meter_key(self._meter_for[1]), wav)
            self._meter_open(wav)

    def _meter_open(self, path: str) -> None:
        try:
            reader = audiomix.WavReader(path)
        except (OSError, ValueError):
            return
        self._meter_reader = reader
        self._meter_lm = loudness.LoudnessMeter(reader.rate, reader.channels)
        self._meter_pos = None
        if self.playing:
            self._meter_start()

    def _meter_close(self, drop_files: bool = True) -> None:
        """Para de medir (fonte nova, módulo desligado ou janela fechando) e cancela a decodificação."""
        if self._meter_cancel is not None:
            self._meter_cancel.set()
            self._meter_cancel = None
        self._meter_token += 1
        self._meter_for = ("", "")
        self._meter_reader = self._meter_lm = None
        self._meter_pos = None
        self.meter_timer.stop()
        if drop_files:
            self._meter_drop_files()

    def _meter_remove(self, f: str) -> None:
        try:
            if os.path.exists(f):
                os.remove(f)
            self._meter_files.remove(f)
        except (OSError, ValueError):
            pass  # o ffmpeg cancelado ainda está fechando; tenta de novo depois

    def _meter_drop_files(self) -> None:
        for f in list(self._meter_files):
            self._meter_remove(f)
        if self._meter_wav[1] not in self._meter_files:
            self._meter_wav = ((), "")

    def _meter_start(self) -> None:
        """Play (também depois de pular durante a reprodução): a medição recomeça no quadro de partida."""
        self._meter_pos = None
        if self._meter_enabled and self._meter_for[1]:
            if self._meter_reader is not None:
                self.meter.restart()
            self.meter_timer.start()

    def _meter_reset(self) -> None:
        """Clique no medidor: recomeça a integrada e o true peak sem parar a reprodução."""
        if self._meter_lm is not None:
            self._meter_lm.reset()
        if self.playing and self._meter_reader is not None:
            self.meter.restart()

    def _meter_tick(self) -> None:
        """Mede o som tocado desde o último toque, pelo mesmo relógio que escolhe o quadro mostrado."""
        reader, lm = self._meter_reader, self._meter_lm
        if not self.playing or reader is None or lm is None or self._play_t0 is None or self.info is None:
            return
        fps, rate = self.info.fps, reader.rate
        now = int((self._play_f0 / fps + time.perf_counter() - self._play_t0) * rate)
        pos = self._meter_pos
        jump = self.METER_JUMP_S * rate
        if pos is None or now < pos or now - pos > jump:
            lm.reset()  # começo, volta do loop ou salto: mede a partir do quadro de partida (ou de agora)
            self.meter.restart()
            start = int(round(self._play_f0 / fps * rate))
            pos = max(0, start if 0 <= now - start <= jump else now)
        try:
            x = reader.read(pos, now - pos)
        except OSError:
            return  # a mixagem antiga foi apagada; a nova chega por _set_audio
        self._meter_pos = now
        peaks = None
        if len(x):
            lm.add(x)
            peaks = [loudness.db(float(v)) for v in lm.last_peak]
        self.meter.push(peaks, lm.momentary(), lm.short_term(), lm.integrated(),
                        lm.true_peak_db() if lm.samples else None)

    def seek(self, f: int) -> None:
        if self.info is None:
            return
        if self.playing:
            self.frame_idx = f
            self.start_play(f)
        else:
            self.request_frame(f)

    def step(self, n: int) -> None:
        self.stop_play()
        self.request_frame(self.frame_idx + n)

    def mark_in(self) -> None:
        if self.info is None or self.info.is_image:
            return
        self.inp = self.frame_idx
        if self.outp is not None and self.outp <= self.inp:
            self.outp = None
        self.timeline.set_inout(self.inp, self.outp)
        self.tl_editor.set_inout(self.inp, self.outp)
        self._update_title()

    def mark_out(self) -> None:
        if self.info is None or self.info.is_image:
            return
        self.outp = self.frame_idx
        if self.inp is not None and self.inp >= self.outp:
            self.inp = None
        self.timeline.set_inout(self.inp, self.outp)
        self.tl_editor.set_inout(self.inp, self.outp)
        self._update_title()

    def clear_marks(self) -> None:
        self.inp = self.outp = None
        self.timeline.set_inout(None, None)
        self.tl_editor.set_inout(None, None)
        self._update_title()

    def _set_compare(self, mode: str) -> None:
        self.viewer.set_mode(mode)
        self.settings.setValue("compare", mode)

    def _set_advanced(self, on: bool) -> None:
        for c in self.cards:
            c.set_advanced(on)
        self.settings.setValue("advanced", "true" if on else "false")

    # ================================================================ presets
    def _all_presets(self) -> list[dict]:
        items = presets.list_user()
        for p in presets.BUILTIN:
            items.append({"id": p["id"], "nome": p["nome"], "grupo": p["grupo"], "desc": p["desc"],
                          "valores": presets.builtin_values(p["id"])})
        return items

    def preset_values(self, pid: str) -> dict | None:
        if self._base_cache and self._base_cache[0] == pid:
            return self._base_cache[1]
        vals = None
        if pid.startswith("user:"):
            for it in presets.list_user():
                if it["id"] == pid:
                    vals = it["valores"]
        elif pid in presets.BY_ID:
            vals = presets.builtin_values(pid)
        if vals is not None:
            self._base_cache = (pid, vals)
        return vals

    @staticmethod
    def _display_name(it: dict) -> str:
        """Nome mostrado: presets prontos são traduzidos; os do usuário ficam com o nome que ele deu."""
        return it["nome"] if str(it["id"]).startswith("user:") else _(it["nome"])

    def preset_name(self, pid: str) -> str:
        for it in self._all_presets():
            if it["id"] == pid:
                return self._display_name(it)
        return _("Personalizado")

    def _refresh_presets(self) -> None:
        self._base_cache = None
        items = self._all_presets()
        combo = self.preset_combo
        combo.blockSignals(True)
        combo.clear()
        model = combo.model()
        group = None
        for it in items:
            if it["grupo"] != group:
                group = it["grupo"]
                combo.addItem(_(group).upper())
                item = model.item(combo.count() - 1)
                item.setEnabled(False)
                f = theme.font(7.8, theme.QFont.Weight.DemiBold, title=True)
                item.setFont(f)
                item.setForeground(QBrush(QColor(theme.ACCENT)))
            combo.addItem("   " + self._display_name(it), it["id"])
        i = combo.findData(self.preset_id)
        combo.setCurrentIndex(i if i >= 0 else combo.findData(presets.DEFAULT_ID))
        combo.blockSignals(False)
        self.looks.rebuild(items)
        self.looks.set_selected(self.preset_id)

    def _combo_chosen(self, _i: int) -> None:
        pid = self.preset_combo.currentData()
        if pid:
            self.apply_preset(pid)

    def apply_preset(self, pid: str, keep_source: bool = True) -> None:
        vals = self.preset_values(pid)
        if vals is None:
            return
        self.preset_id = pid
        # O preset muda o look; o perfil do vídeo é do arquivo e fica (presets.SOURCE_KEYS), menos num
        # projeto novo, que volta tudo ao padrão.
        self.store.set_all(presets.with_source(vals, self.store.values if keep_source else None))
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(pid)))
        self.preset_combo.blockSignals(False)
        self.looks.set_selected(pid)
        self._update_modified()
        self._check_modules()

    def _update_modified(self) -> None:
        base = self.preset_values(self.preset_id)
        modified = not presets.same_look(base, self.store.values)
        self.mod_label.setVisible(modified)

    def _update_history(self) -> None:
        self.btn_undo.setEnabled(self.store.can_undo())
        self.btn_redo.setEnabled(self.store.can_redo())
        self.btn_edit_undo.setEnabled(self.model.can_undo())
        self.btn_edit_redo.setEnabled(self.model.can_redo())

    def undo(self) -> None:
        """Ctrl+Z: desfaz na linha do tempo (modo Edição ou foco no painel de legendas) ou nos ajustes do look."""
        if self.mode == "edicao" or self.subs_ui.owns_focus():
            self.model.undo()
        else:
            self.store.undo()

    def redo(self) -> None:
        if self.mode == "edicao" or self.subs_ui.owns_focus():
            self.model.redo()
        else:
            self.store.redo()

    def _menu_state(self) -> None:
        user = self.preset_id.startswith("user:")
        self.act_update.setEnabled(user)
        self.act_delete.setEnabled(user)

    def save_preset_as(self) -> None:
        self.store.commit()
        base = self.preset_name(self.preset_id)
        suggestion = base if self.preset_id.startswith("user:") else _("Meu {nome}").format(nome=base)
        name, ok = QInputDialog.getText(self, _("Salvar preset"), _("Nome do novo preset:"), text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        if presets.user_exists(name):
            r = QMessageBox.question(self, _("Salvar preset"),
                                     _("Já existe um preset chamado \"{nome}\". Substituir?").format(nome=name))
            if r != QMessageBox.StandardButton.Yes:
                return
        pid = presets.save_user(name, self.store.snapshot(), _("Criado a partir de {nome}").format(nome=base))
        self.preset_id = pid
        self._refresh_presets()
        self._update_modified()
        self.thumb_timer.start()
        self.statusBar().showMessage(_("Preset \"{nome}\" salvo em Meus presets.").format(nome=name), 5000)

    def update_user_preset(self) -> None:
        if not self.preset_id.startswith("user:"):
            return
        self.store.commit()
        name = self.preset_name(self.preset_id)
        presets.save_user(name, self.store.snapshot())
        self._refresh_presets()
        self._update_modified()
        self.thumb_timer.start()
        self.statusBar().showMessage(_("Preset \"{nome}\" atualizado.").format(nome=name), 5000)

    def delete_preset(self) -> None:
        if not self.preset_id.startswith("user:"):
            return
        name = self.preset_name(self.preset_id)
        r = QMessageBox.question(self, _("Excluir preset"), _("Excluir o preset \"{nome}\"?").format(nome=name))
        if r != QMessageBox.StandardButton.Yes:
            return
        presets.delete_user(self.preset_id)
        self.preset_id = presets.DEFAULT_ID
        self._refresh_presets()
        self._update_modified()

    def revert_preset(self) -> None:
        self.apply_preset(self.preset_id)

    def import_preset(self, path: str | None = None) -> None:
        if not path:
            path, _f = QFileDialog.getOpenFileName(self, _("Importar preset"), "", _("Preset (*.json)"))
            if not path:
                return
        try:
            pid = presets.import_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, _("Preset inválido.\n\n{erro}").format(erro=exc))
            return
        self.preset_id = pid
        self._refresh_presets()
        self.apply_preset(pid)
        self.thumb_timer.start()

    def export_preset(self) -> None:
        name = self.preset_name(self.preset_id)
        path, _f = QFileDialog.getSaveFileName(self, _("Exportar preset"), f"{name}.json", _("Preset (*.json)"))
        if path:
            presets.export_file(path, name, self.store.snapshot())
            self.statusBar().showMessage(_("Preset exportado: {caminho}").format(caminho=path), 5000)

    def export_lut(self, size: int) -> None:
        name = self.preset_name(self.preset_id)
        path, _f = QFileDialog.getSaveFileName(self, _("Exportar LUT"), f"{name}.cube", _("LUT 3D (*.cube)"))
        if not path:
            return
        data = self.engine.bake_lut(self.store.values, size)
        luts.save_cube(path, data, size, name)
        self._uploaded = None
        self.render_now()
        profile = dict(params.PARAMS["entrada"].choices).get(self.store.get("entrada"), "")
        text = _("LUT salvo em:\n{caminho}\n\nEle guarda só a cor (curva, cópia, tons e saturação). Grão, halação, "
                 "bloom e os outros efeitos de textura não cabem num LUT.\n\nEntrada do LUT: o mesmo perfil escolhido "
                 "em \"Perfil do vídeo\" ({perfil}).").format(caminho=path, perfil=_(profile))
        from .. import planes
        if planes.active(self.store.values):  # 1.6: depende do lugar e da cor de cada pixel
            text += "\n\n" + _("A Cor por planos (frente, fundo e pele) também fica fora do LUT.")
        QMessageBox.information(self, _("LUT exportado"), text)

    def export_all_luts(self) -> None:
        d = QFileDialog.getExistingDirectory(self, _("Pasta onde salvar os LUTs dos presets"),
                                             str(self.settings.value("export_dir", str(Path.home()))))
        if not d:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        n = 0
        try:
            for it in self._all_presets():
                if it["id"] == "original":
                    continue
                nome = self._display_name(it)
                safe = "".join(ch for ch in nome.replace("•", "-") if ch not in '<>:"/\\|?*').strip()
                data = self.engine.bake_lut(it["valores"], 33)
                luts.save_cube(os.path.join(d, f"{safe}.cube"), data, 33, nome)
                n += 1
        finally:
            QApplication.restoreOverrideCursor()
        self._uploaded = None
        self.render_now()
        QMessageBox.information(self, _("LUTs exportados"),
                                _("{n} LUTs salvos em:\n{pasta}\n\nEntrada: vídeo Rec.709 comum. Funcionam no "
                                  "Premiere, Resolve, Final Cut, CapCut, OBS e qualquer programa que aceite .cube. "
                                  "Eles guardam só a cor; grão e halação ficam no PeliculaConverter.").format(n=n, pasta=d))

    # ================================================================ exportação
    def export_dialog(self) -> None:
        """Botão Exportar e Ctrl+E. Com exportação em andamento mostra a fila: outra exportação só de propósito,
        por "Adicionar outra exportação…" de lá (`new_export`)."""
        if self.queue.busy:
            self.show_queue()
            return
        self.new_export()

    def new_export(self) -> None:
        # 1.7, várias sequências: a aberta é a que sai, e a janela deixa escolher outra (ou várias, na fila). Com a
        # aberta vazia, abre pela primeira que tem o que exportar.
        targets = self.seqs_ui.export_targets()
        first = targets[0] if (self.info is None and targets) else None
        if self.info is None and first is None:
            self.open_dialog()
            return
        if not sem_efeitos_ui.confirm_export(self):
            return
        self.store.commit()
        inout = None
        if first is not None:
            info, inout, seq, frame, chapters_, subs, cues = (first.info, first.in_out, first.sequence, first.frame,
                                                              first.chapters, first.subtitles, first.cues)
        else:
            info = self.info
            if self.inp is not None or self.outp is not None:
                inout = (self.inp or 0, self.outp if self.outp is not None else self.info.frames - 1)
            seq = self.src_seq.copy() if self.src_seq is not None else None
            frame, chapters_ = self.frame_idx, self._export_chapters()
            subs, cues = self.model.seq.subtitles, self.subs_ui.ctl.cues()
        try:
            perf = json.loads(self.settings.value("export_perf", "") or "{}")
        except ValueError:
            perf = {}
        values, look_name = self._export_look()
        dlg = ExportDialog(self, info, values, look_name, inout,
                           str(self.settings.value("export_dir", "")), str(self.settings.value("export_quality", "")),
                           perf, self.engine.renderer.split("/")[0], sequence=seq, frame=frame,
                           last_platform=str(self.settings.value("export_platform", "")),
                           chapters=chapters_, look_keys=self._export_keys(),
                           subtitles=subs, subtitle_cues=cues,
                           queue_jobs=list(self.queue.jobs), no_effects=self.no_effects, targets=targets,
                           target_id=first.id if first is not None else self.model.seq.id)
        if not dlg.exec():
            return
        jobs = dlg.jobs()
        self.settings.setValue("export_dir", str(Path(jobs[0].out_path).parent))
        self.settings.setValue("export_quality", dlg.quality.currentData())
        self.settings.setValue("export_platform", dlg.platform_id())
        self.settings.setValue("export_perf", json.dumps(dlg.perf_dict()))
        for job in jobs:
            self.queue.add(job)
        self._recovery_point()
        self.show_queue()

    def _export_look(self) -> tuple[dict, str]:
        """O que sai na exportação é o que a prévia mostra: no modo Edição sem película, só a montagem."""
        if self.no_effects:
            return presets.builtin_values("original"), _("Sem efeitos")
        if self.mode == "edicao" and not self.edit_film:
            return presets.builtin_values("original"), _("Sem película (só a edição)")
        return self.store.snapshot(), self.preset_name(self.preset_id)

    def _export_keys(self) -> dict:
        """As chaves de animação do look que vão com `_export_look` ({} no modo Edição sem película)."""
        if self.no_effects or (self.mode == "edicao" and not self.edit_film):
            return {}
        return self.store.keys_json()

    def show_queue(self) -> None:
        if self.queue_dialog is None:
            self.queue_dialog = QueueDialog(self, self.queue, on_add=self.new_export)
        self.queue_dialog.show()
        self.queue_dialog.raise_()
        self.queue_dialog.activateWindow()

    def _recovery_point(self) -> None:
        """Cópia de segurança agora (antes de exportar e de importar; depois de salvar, as cópias saem) e a
        fila guardada, se a recuperação automática está ligada (`ui/recovery_ui.py`)."""
        if self.recovery is not None:
            self.recovery.checkpoint()

    def _queue_tick(self) -> None:
        active = [j for j in self.queue.jobs if j.status in ("aguardando", "exportando")]
        running = next((j for j in self.queue.jobs if j.status == "exportando"), None)
        if running:
            self.btn_queue.setText(_("Fila • {pct}%").format(pct=f"{running.progress * 100:.0f}"))
        elif active:
            self.btn_queue.setText(_("Fila ({n})").format(n=len(active)))
        else:
            self.btn_queue.setText(_("Fila"))
        tip = _("Há uma exportação em andamento: mostra a fila (Ctrl+E)") if active \
            else _("Exportar com o look atual (Ctrl+E)")
        if self.btn_export.toolTip() != tip:
            self.btn_export.setToolTip(tip)
        finished = []
        for j in self.queue.jobs:
            if j.status in ("concluido", "erro") and j.id not in self._seen_done:
                self._seen_done.add(j.id)
                target = export.output_target(j.out_path, j.settings)
                if j.status == "concluido":
                    self.statusBar().showMessage(_("Exportação concluída: {caminho}").format(caminho=target), 10000)
                else:
                    self.statusBar().showMessage(_("Uma exportação falhou. Veja os detalhes na fila."), 10000)
                    self.show_queue()
                finished.append(notify.Finished(j.status, j.name or Path(target).name, target, j.error))
        # Notificação do sistema (ou só piscar o ícone, com o módulo desligado); a fila inteira vira um resumo.
        self.notifier.export_progress(finished, idle=not self.queue.busy)

    def save_frame(self) -> None:
        if self.info is None:
            return
        stem = media.sequence_stem(self.info.path) or "quadro"
        tc = timecode(self.frame_idx, self.info.fps).replace(":", "-")
        d = str(self.settings.value("export_dir", str(Path(self.info.path).parent)))
        path, flt = QFileDialog.getSaveFileName(self, _("Salvar quadro"), str(Path(d) / f"{stem}_{tc}.png"),
                                                _("PNG 16 bits (*.png);;TIFF 16 bits (*.tif);;JPEG (*.jpg)"))
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # "Fundo transparente": PNG e TIFF guardam a transparência; JPEG sai sobre a cor do fundo.
            alpha = (self.src_seq is not None and self.model.seq.transparent
                     and Path(path).suffix.lower() in export.STILL_ALPHA_ARGS)
            out = self.still_frame(self.frame_idx, alpha=alpha)
            export.save_still(out, path)  # grava num parcial e só troca o arquivo no fim
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, _("Não foi possível salvar o quadro.\n\n{erro}").format(erro=exc))
            return
        QApplication.restoreOverrideCursor()
        self.render_now()
        self.statusBar().showMessage(_("Quadro salvo: {caminho}").format(caminho=path), 8000)

    def still_frame(self, frame: int, alpha: bool = False):
        """O quadro `frame` em 16 bits no tamanho do arquivo, como sai na exportação ("Salvar quadro"); `alpha`:
        RGBA com a transparência da montagem (como numa exportação com alfa)."""
        w, h = self.info.width, self.info.height
        recipe = self.frame_recipe(16, full=True, alpha=alpha)
        if self.src_seq is not None:
            img = self._live_layers(sequence.grab(self.src_seq, frame, w, h, 16, hq=True, shutter=recipe.shutter,
                                                  no_effects=recipe.no_effects))
        else:
            img = None
        if img is None:
            img = media.grab_frame(self.info, frame, w, h, 16, hq=True, profile=recipe.profile)
        self._uploaded = None
        return recipe.render(self.engine, img, frame)

    # ================================================================ projetos (.plc)
    def _seq_json(self) -> dict | None:
        """A montagem para o projeto, ou None se ela é só o arquivo inteiro (projeto simples, formato 1).

        Marcadores e legendas contam como edição: com eles a montagem vai para o projeto mesmo sendo trivial."""
        seq = self.model.seq
        if len(seq.family()) > 1:  # 1.7: a sequência aberta pode ser trivial; as outras vão junto
            return seq.to_json()
        subs = seq.subtitles is not None and not seq.subtitles.is_default()
        if (not seq.clips and not seq.folders.has_folders()) or (
                self.file_info is not None and seq.is_trivial() == self.file_info.path and not seq.markers
                and not subs and not seq.folders.has_folders() and not getattr(self.file_info, "is_sequence", False)):
            return None  # sequência de imagens: a montagem guarda a velocidade escolhida ao importar
        return seq.to_json()

    def _state(self) -> dict:
        # Várias sequências: o estado é o do projeto a partir da primeira aba, para trocar de aba não parecer mudança.
        many = len(self.model.seq.family()) > 1
        seq = self.model.seq.family()[0].to_json() if many else self._seq_json()
        return {"media": self.file_info.path if self.file_info else "", "values": dict(self.store.values),
                "keys": self.store.keys_json(), "preset": self.preset_id,
                "in": self.seqs_ui.in_out_state() if many else self.inp, "out": None if many else self.outp,
                "seq": json.dumps(seq, sort_keys=True) if seq else ""}

    def _has_project(self) -> bool:
        """Há o que salvar: algo aberto ou, com várias sequências, mesmo com a aberta vazia."""
        return self.info is not None or len(self.model.seq.family()) > 1

    def is_dirty(self) -> bool:
        if not self._has_project():
            return False
        return self._state() != self._saved_state

    def _update_title(self) -> None:
        if self.project_path:
            name = Path(self.project_path).stem
        elif self.src_seq is not None and (self.file_info is None or self._seq_json() is not None):
            name = _("Edição sem título")
        elif self.info is not None:
            name = getattr(self, "_media_label", Path(self.info.path).name)
        else:
            self.setWindowTitle(APP_NAME)
            return
        dot = " •" if self.is_dirty() else ""
        self.setWindowTitle(f"{name}{dot} — {APP_NAME}")
        if self.project_path:
            self.file_label.setText(_("Projeto: {nome}").format(nome=name) + dot)

    def confirm_discard(self) -> bool:
        """Pergunta se salva as mudanças antes de trocar de projeto ou fechar. False = cancelar."""
        if not self.is_dirty():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(_("Salvar projeto"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(_("Salvar as mudanças da edição atual num projeto (.plc) para continuar depois?"))
        save = box.addButton(_("Salvar"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(_("Não salvar"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save_project()
        return box.clickedButton() is discard

    def _thumbnail(self) -> bytes:
        img = sem_efeitos_ui.thumbnail_image(self) if self.no_effects else self.viewer.proc
        if img is None:
            return b""
        small = img.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        small.save(buf, "JPG", 82)
        buf.close()
        return bytes(ba)

    def _make_project(self, backup: bool = False) -> project.Project:
        """O projeto atual. `backup`: cópia da recuperação automática (sem miniatura e sem fechar o passo de
        desfazer em andamento)."""
        if not backup:
            self.store.commit()
        seq = self._seq_json()
        media_path = self.file_info.path if self.file_info else next(
            (p for p, s in self.model.seq.sources.items() if s.is_file), "")
        return project.Project(
            media_path=media_path, values=self.store.snapshot(), preset_id=self.preset_id,
            frame=self.frame_idx, in_point=self.inp, out_point=self.outp, compare=self.viewer.mode,
            preview=self.preview_q, export_quality=str(self.settings.value("export_quality", "")),
            name=Path(self.project_path).stem if self.project_path else "",
            thumbnail_jpeg=b"" if backup else self._thumbnail(), sequence=seq, mode=self.mode,
            look_keys=self.store.keys_json())

    def save_project(self) -> bool:
        if not self._has_project():
            QMessageBox.information(self, _("Salvar projeto"), _("Abra um vídeo ou uma imagem antes de salvar um projeto."))
            return False
        if not self.project_path:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        if not self._has_project():
            QMessageBox.information(self, _("Salvar projeto"), _("Abra um vídeo ou uma imagem antes de salvar um projeto."))
            return False
        start = self.project_path or str(Path(self.info.path if self.info is not None
                                              else Path.home() / "projeto").with_suffix(project.EXT))
        path, _f = QFileDialog.getSaveFileName(self, _("Salvar projeto"), start,
                                               _("Projeto do PeliculaConverter (*.plc)"))
        if not path:
            return False
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        p = self._make_project()
        try:
            project.save(p, path)
        except OSError as exc:
            QMessageBox.warning(self, _("Salvar projeto"), _("Não foi possível salvar o projeto.\n\n{erro}").format(erro=exc))
            return False
        self.project_path = p.path
        self._saved_state = self._state()
        self._recovery_point()  # salvo: as cópias de segurança desta janela saem
        welcome.add_recent(self.settings, p.path)
        self._update_title()
        self.statusBar().showMessage(_("Projeto salvo: {caminho}").format(caminho=p.path), 6000)
        return True

    def new_project(self) -> None:
        if not self.confirm_discard():
            return
        self.stop_play()
        sem_efeitos_ui.reset(self)
        self.project_path = None
        self.file_info = None
        self.cur = None
        self.cur_q = None
        self.inp = self.outp = None
        self._sources = {}
        self.input_notice.offer(None)
        self.bin.clear()
        self._loading = True
        try:
            self.model.set_sequence(timeline.Sequence(micro_fade=True))
        finally:
            self._loading = False
        self.seqs_ui.reset()
        self._refresh_source(reset=True)
        self.apply_preset(presets.DEFAULT_ID, keep_source=False)
        self._saved_state = self._state()
        self._update_title()

    def open_project_dialog(self) -> None:
        d = str(self.settings.value("last_project_dir", self.settings.value("last_dir", str(Path.home()))))
        path, _f = QFileDialog.getOpenFileName(self, _("Abrir projeto"), d, _("Projeto do PeliculaConverter (*.plc)"))
        if path:
            self.open_project(path)

    def open_project(self, path: str) -> None:
        if not self.confirm_discard():
            return
        try:
            p = project.load(path)
        except project.ProjectError as exc:
            QMessageBox.warning(self, _("Abrir projeto"), _("Este arquivo não é um projeto válido.\n\n{erro}").format(erro=exc))
            return
        self.settings.setValue("last_project_dir", str(Path(path).parent))
        self.show_project(p)

    def show_project(self, p: project.Project, remember: bool = True) -> None:
        """Mostra um projeto já lido (de um .plc ou de uma cópia da recuperação automática, sem `p.path`).
        `remember`: entra nos projetos recentes."""
        self.input_notice.offer(None)  # 1.6: um projeto salvo nunca recebe sugestão de perfil
        sem_efeitos_ui.reset(self)
        if p.sequence:
            self._open_sequence_project(p, remember)
            return
        mediapath = p.media_path
        if mediapath and not media.path_exists(mediapath):
            r = QMessageBox.question(self, _("Abrir projeto"),
                                     _("O vídeo deste projeto não foi encontrado:\n{caminho}\n\nQuer localizá-lo agora?")
                                     .format(caminho=mediapath))
            if r == QMessageBox.StandardButton.Yes:
                new, _f = QFileDialog.getOpenFileName(self, _("Localizar o vídeo"),
                                                      str(Path(p.path or mediapath).parent), media_filter())
                mediapath = new or ""
            else:
                mediapath = ""
        if mediapath:
            self.load_media(mediapath)
        if p.preset_id and self.preset_values(p.preset_id) is not None:
            self.preset_id = p.preset_id
        self.store.set_all(p.values, keys=p.look_keys)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(self.preset_id)))
        self.preset_combo.blockSignals(False)
        self.looks.set_selected(self.preset_id)
        self._update_modified()
        if self.info is not None:
            self.inp, self.outp = p.in_point, p.out_point
            self.timeline.set_inout(self.inp, self.outp)
            if p.preview in [k for k, _l in PREVIEW_Q]:
                self.prev_combo.setCurrentIndex(self.prev_combo.findData(p.preview))
            self.request_frame(min(p.frame, self.info.frames - 1))
        if p.compare in ("proc", "split", "side", "orig"):
            self.compare.set_current(p.compare)
            self._set_compare(p.compare)
        self.project_path = p.path or None
        self._saved_state = self._state() if mediapath == p.media_path else {}
        if remember and p.path:
            welcome.add_recent(self.settings, p.path)
        self.set_mode(p.mode if p.mode in MODES else "pelicula")
        self._update_title()
        self._check_modules()

    def _open_sequence_project(self, p: project.Project, remember: bool = True) -> None:
        """Projeto com montagem do modo Edição: relocaliza arquivos que sumiram e abre a sequência."""
        seq = timeline.Sequence.from_json(p.sequence)
        changed = False
        for path in list(seq.sources):
            if not seq.sources[path].is_file or sequence.present(seq.sources[path]):
                continue  # clipes sem arquivo não têm o que localizar
            r = QMessageBox.question(self, _("Abrir projeto"),
                                     _("Um arquivo da edição não foi encontrado:\n{caminho}\n\nQuer localizá-lo agora?")
                                     .format(caminho=path))
            if r != QMessageBox.StandardButton.Yes:
                continue
            new, _f = QFileDialog.getOpenFileName(self, _("Localizar o arquivo"), str(Path(p.path or path).parent),
                                                  import_filter())
            if new:
                self._relink(seq, path, new)
                changed = True
        self.stop_play()
        self.file_info = None
        if p.media_path and media.path_exists(p.media_path):
            try:
                known = seq.sources.get(p.media_path)  # sequência de imagens: com a velocidade escolhida
                self.file_info = known.to_info() if known is not None and known.is_sequence else \
                    media.probe(p.media_path)
                self._media_label = known.name if known is not None else Path(p.media_path).name
            except Exception:  # noqa: BLE001
                self.file_info = None
        self._sources = dict(seq.sources)
        self.bin.clear()
        for src in seq.sources.values():
            self.bin.add_source(src)
            self._request_thumb(src)
        self._loading = True
        try:
            self.model.set_sequence(seq)
        finally:
            self._loading = False
        self.seqs_ui.reset()
        if p.preset_id and self.preset_values(p.preset_id) is not None:
            self.preset_id = p.preset_id
        self.store.set_all(p.values, keys=p.look_keys)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(self.preset_id)))
        self.preset_combo.blockSignals(False)
        self.looks.set_selected(self.preset_id)
        self._update_modified()
        self.set_mode(p.mode if p.mode in MODES else "edicao", force=True)
        self._refresh_source(reset=True)
        if self.info is not None:
            self.inp, self.outp = p.in_point, p.out_point
            self.timeline.set_inout(self.inp, self.outp)
            self.tl_editor.set_inout(self.inp, self.outp)
            if p.preview in [k for k, _l in PREVIEW_Q]:
                self.prev_combo.setCurrentIndex(self.prev_combo.findData(p.preview))
            self.request_frame(min(p.frame, self.info.frames - 1))
        if p.compare in ("proc", "split", "side", "orig"):
            self.compare.set_current(p.compare)
            self._set_compare(p.compare)
        self.project_path = p.path or None
        self._saved_state = {} if changed else self._state()
        if remember and p.path:
            welcome.add_recent(self.settings, p.path)
        self._update_title()
        self._check_modules()
        self.seqs_ui.problems(p.problems)  # 1.7: o que não coube ao abrir (uma sequência que sumiu ou fecharia um ciclo)

    def _fill_project_menu(self) -> None:
        m = self.project_menu
        m.clear()
        m.addAction(_("Novo projeto"), self.new_project).setShortcut(QKeySequence("Ctrl+N"))
        m.addAction(_("Abrir projeto…"), self.open_project_dialog).setShortcut(QKeySequence("Ctrl+Shift+O"))
        recent = m.addMenu(_("Projetos recentes"))
        items = [p for p in welcome.recent_projects(self.settings) if os.path.isfile(p)]
        for path in items:
            recent.addAction(Path(path).stem, lambda p=path: self.open_project(p)).setToolTip(path)
        if items:
            recent.addSeparator()
            recent.addAction(_("Limpar lista"), lambda: self.settings.setValue("recent_projects", []))
        else:
            recent.setEnabled(False)
        m.addSeparator()
        m.addAction(_("Salvar projeto"), self.save_project).setShortcut(QKeySequence("Ctrl+S"))
        m.addAction(_("Salvar projeto como…"), self.save_project_as).setShortcut(QKeySequence("Ctrl+Shift+S"))
        m.addSeparator()
        m.addAction(_("Tela de boas-vindas"), self.show_welcome)

    # ================================================================ boas-vindas, idioma e atualizações
    def show_welcome(self) -> None:
        dlg = welcome.WelcomeDialog(self, self.settings)
        dlg.exec()
        act = dlg.action
        if not act:
            return
        kind, arg = act
        if kind == "project" and arg:
            self.open_project(arg)
        elif kind == "open_project":
            self.open_project_dialog()
        elif kind == "open_media":
            if self.confirm_discard():
                self.open_dialog()
        elif kind == "test":
            if self.confirm_discard():
                self.open_test_scene()
                self.project_path = None
                self._saved_state = self._state()
                self._update_title()
        elif kind == "update" and arg is not None:
            self.show_update(arg)

    def choose_language(self) -> None:
        from .language_dialog import LanguageDialog
        dlg = LanguageDialog(self, i18n.language())
        if not dlg.exec() or dlg.selected == i18n.language():
            return
        self.settings.setValue("language", dlg.selected)
        r = QMessageBox.question(self, APP_NAME, _("O idioma muda ao abrir o app de novo. Reabrir agora?"))
        if r == QMessageBox.StandardButton.Yes:
            if self.confirm_discard():
                self._saved_state = self._state()
                restart_app()

    def auto_update_enabled(self) -> bool:
        """Busca automática de versões novas (app e ffmpeg); desligável em Configurações."""
        return str(self.settings.value("auto_update", "true")) != "false"

    def _auto_check_update(self) -> None:
        if not self.auto_update_enabled():
            return
        last = float(self.settings.value("update_last_check", 0) or 0)
        if time.time() - last < 20 * 3600:
            return
        self.check_updates(manual=False)

    def check_updates(self, manual: bool = False) -> None:
        def run():
            try:
                rel = updater.check()
                err = ""
            except updater.UpdateError as exc:
                rel, err = None, str(exc)
            self._update_bridge.found.emit((rel, err, manual))

        threading.Thread(target=run, daemon=True).start()

    def _update_found(self, payload) -> None:
        rel, err, manual = payload
        self.settings.setValue("update_last_check", time.time())
        if rel is None:
            if manual:
                from .update_dialog import error_text
                QMessageBox.information(self, _("Atualizações"), error_text(err))
            return
        if not updater.is_newer(rel):
            if manual:
                QMessageBox.information(self, _("Atualizações"),
                                        _("Você já está na versão mais recente ({versao}).").format(versao=__version__))
            return
        self._release = rel
        self.btn_update.setText("  " + _("Atualizar para {versao}").format(versao=rel.tag.lstrip("v")))
        self.btn_update.setIcon(icons.icon("export", "#1b1205", 14))
        self.btn_update.setVisible(True)
        if manual or str(self.settings.value("update_skip", "")) != rel.tag:
            if manual:
                self.show_update(rel)
            else:  # checagem automática: notificação do sistema (clicar abre a janela da atualização)
                self.notifier.notify(notify.update_available(rel.tag.lstrip("v")))

    def show_update(self, rel) -> None:
        if rel is None:
            return
        from .update_dialog import UpdateDialog
        UpdateDialog(self, rel, self.settings).exec()

    # ================================================================ dependências
    def _check_deps(self) -> None:
        folder = self.settings.value("ffmpeg_dir", "") or None
        online = self.auto_update_enabled() and deps.platform_supported()

        def run():
            ok = media.configure(folder)
            info = deps.inspect(media.ffmpeg()) if ok else None
            latest = deps.latest_version(timeout=6) if online else ""
            self._deps_bridge.result.emit(ok, info, latest)

        threading.Thread(target=run, daemon=True).start()

    def _deps_result(self, ok: bool, info, latest: str) -> None:
        if not ok:
            self.show_deps(_("O ffmpeg não foi encontrado neste computador. Ele é necessário para abrir e exportar "
                             "vídeos. Clique em \"Baixar ffmpeg\": o download é feito da fonte oficial e conferido."))
            return
        newer = deps.parse_version(latest)
        has_update = bool(info and info.version and newer and info.version[:2] < newer[:2])
        if not info or not (info.outdated or has_update):
            return
        if str(self.settings.value("ffmpeg_skip", "")) == latest:
            return
        box = QMessageBox(self)
        box.setWindowTitle(_("Atualizar o ffmpeg"))
        if info.outdated:
            text = _("O ffmpeg deste computador ({versao}) está desatualizado.").format(versao=info.label)
        else:
            text = _("O ffmpeg deste computador ({versao}) está numa versão antiga.").format(versao=info.label)
        if latest:
            text += "\n\n" + _("A versão {versao} está disponível.").format(versao=latest)
        text += "\n\n" + _("Versões novas são mais rápidas e leem mais formatos (o 8.0+ lê ProRes RAW). Atualizar agora?")
        box.setText(text)
        upd = box.addButton(_("Atualizar"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Agora não"), QMessageBox.ButtonRole.RejectRole)
        never = box.addButton(_("Não perguntar de novo"), QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is upd:
            self.show_deps(auto_download=True)
        elif box.clickedButton() is never:
            self.settings.setValue("ffmpeg_skip", latest or "sempre")

    def show_deps(self, reason: str = "", auto_download: bool = False) -> None:
        """Configurações › Componentes com um aviso (ffmpeg ausente ou antigo) e, se pedido, já
        baixando o ffmpeg."""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, self.settings, "componentes", main=self)
        dlg.settings_changed.connect(self.settings_changed)
        page = dlg.page("componentes")
        page.set_reason(reason)
        if auto_download:
            QTimer.singleShot(200, lambda: page.download("ffmpeg"))
        dlg.exec()
        if self.info is not None:
            self.request_frame(self.frame_idx)

    def show_resolve(self) -> None:
        """Plugin para o DaVinci Resolve: DCTLs e LUTs do PeliculaConverter."""
        from .resolve_dialog import ResolveDialog
        ResolveDialog(self, engine=self.engine).exec()
        self._uploaded = None
        self.render_now()

    def show_corridorkey(self) -> None:
        """Recorte por IA (módulo Beta): janela não modal; o CorridorKey roda num processo separado, pela fila."""
        from .corridorkey_dialog import open_for
        open_for(self)

    def _sync_corridorkey_action(self) -> None:
        from .. import corridorkey
        self.act_corridorkey.setVisible(modules.is_enabled(self.settings, "recorte_ia") and corridorkey.available())

    # ================================================================ configurações
    def show_settings(self, page: str = "geral") -> None:
        """Janela de Configurações; as mudanças chegam em `settings_changed`."""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, self.settings, page, main=self)
        dlg.settings_changed.connect(self.settings_changed)
        dlg.exec()

    def _on_settings_changed(self, key: str) -> None:
        if key == "auto_update":
            self.act_auto_update.blockSignals(True)
            self.act_auto_update.setChecked(self.auto_update_enabled())
            self.act_auto_update.blockSignals(False)
        elif key == "modulos":
            self.apply_modules()
        elif key == ZOOM_PLAYHEAD_KEY:
            self.tl_editor.canvas.load_zoom_pref()

    # ================================================================ módulos (Configurações › Recursos)
    def _module_tools(self) -> dict[str, list]:
        """Ferramentas de cada módulo na janela (widgets e ações de menu) que somem quando ele é desligado.

        Módulo novo com ferramenta na janela: acrescente-a aqui (casos especiais em `apply_modules`).
        """
        cards = {c.section.key: c for c in self.cards}
        return {
            "edicao": [self.mode_switch],  # sem Edição sobra um modo só: o seletor inteiro some
            "laboratorio": [cards["lab"]],
            "defeitos": [cards["desgaste"]],
            "scan": [cards["scan"]],
            "luts": [cards["lut"]],
            "exportar_lut": [self.act_lut_sep, *self.act_luts],
            "scopes": [self.hist, self.edit_scopes],
            "curva": [self.curve_label, self.curve_switch],
            "medidor_som": [self.meter],
            "davinci": [self.act_resolve_sep, self.act_resolve],
            "legendas": [self.btn_subs],  # e o painel e a faixa (SubtitlesUI.apply_modules)
            "silencios": [self.tl_editor.btn_silences],
            "titulos_geradores": [self.bin.btn_new],  # e os editores no inspetor (`apply_modules`)
            **cor_ui.module_tools(self),  # 1.6: "cor_planos" e "cor_simples" (`ui/cor_ui.py`)
            **grao_fisico_ui.module_tools(self),  # 1.6: "grao_fisico" (`ui/grao_fisico_ui.py`)
            **filme_ui.module_tools(self),  # 1.6: câmera, formato e montagem (`ui/filme_ui.py`)
            **luz_fotometro_ui.module_tools(self),  # 1.6: fotômetro da película (`ui/luz_fotometro_ui.py`)
        }

    def apply_modules(self) -> None:
        """Mostra ou esconde as ferramentas conforme os módulos ligados (ao abrir e quando Recursos muda).

        Só a interface muda: a renderização nunca consulta `modules`, então um projeto ou preset que
        use um módulo desligado sai igual (o aviso de `_check_modules` oferece religar).
        """
        on = modules.enabled_ids(self.settings)
        for module_id, tools in self._module_tools().items():
            for tool in tools:
                tool.setVisible(module_id in on)
        edit = "edicao" in on
        for shortcut in self._edit_shortcuts:
            shortcut.setEnabled(edit)
        if not edit and self.mode == "edicao":
            self.set_mode("pelicula")  # a montagem não muda: continua sendo a entrada do look
        curve = "curva" in on and self.curve_switch.isChecked()
        self.curve_graph.setVisible(curve)  # sem gravar "show_curve": religado, volta como estava
        if curve:
            self.curve_timer.start()
        self._meter_enabled = "medidor_som" in on
        self._meter_source()  # desligado: nem decodifica nem mede
        from . import transitions_ui  # 1.5: tipos novos e o menu "Transição ▸" (módulo "transicoes")
        transitions_ui.apply_module(self, "transicoes" in on)
        cor_ui.apply_modules(self, on)
        filme_ui.apply_modules(self, on)
        luz_fotometro_ui.apply_modules(self, on)
        self._notice_muted -= on  # religado e desligado de novo: volta a avisar
        self._sync_corridorkey_action()  # Beta: fora de _module_tools (ligado só com o componente instalado)
        self.subs_ui.apply_modules(on)
        for editor in (self.gen_editor, self.title_editor):  # aparecem só com um clipe deles escolhido
            editor.set_allowed("titulos_geradores" in on)
        self._check_modules()
        for filtro in (getattr(self, "look_filter", None), getattr(self.inspector, "filtro", None)):
            if filtro is not None:
                filtro.reapply()  # o filtro de ajustes não mostra de volta cartão de módulo desligado

    def _check_modules(self) -> None:
        """Aviso discreto se o look ou a montagem usam módulos desligados (a imagem não muda)."""
        seq = self.model.seq
        edited = bool(seq.clips) and not (self.file_info is not None and seq.is_trivial() == self.file_info.path)
        off = (modules.used_by(self.store.values, seq if edited else None, subtitles=seq.subtitles)
               - modules.enabled_ids(self.settings))
        new = off - self._notice_muted  # fechado nesta sessão: só volta com um módulo novo na lista
        self.module_notice.show_modules(sorted(off) if new and not self.preview_fullscreen else [])

    def enable_modules(self, ids) -> None:
        """Religa módulos (botão "Ligar" do aviso) e atualiza a janela."""
        ids = [m for m in ids if modules.exists(m)]
        if not ids:
            return
        for module_id in ids:
            modules.set_enabled(self.settings, module_id, True)
        self.settings_changed.emit("modulos")
        self.statusBar().showMessage(_("Recursos ligados: {lista}.").format(lista=module_names(ids)), 6000)

    def choose_ffmpeg(self) -> None:
        d = QFileDialog.getExistingDirectory(self, _("Pasta que contém ffmpeg.exe e ffprobe.exe"), media.tool_dir())
        if not d:
            return
        if media.configure(d):
            self.settings.setValue("ffmpeg_dir", d)
            QMessageBox.information(self, APP_NAME, _("ffmpeg configurado:\n{caminho}").format(caminho=media.ffmpeg()))
        else:
            QMessageBox.warning(self, APP_NAME, _("Não encontrei ffmpeg.exe e ffprobe.exe nessa pasta."))

    def open_lut_dir(self) -> None:
        system.open_path(luts.user_dir())

    def show_shortcuts(self) -> None:
        QMessageBox.information(self, _("Atalhos do teclado"), _(
            "Espaço — reproduzir / pausar\n← / → — quadro anterior / próximo\nShift + ← / → — 1 segundo\n"
            "Home / End — início / fim\nI / O — marcar entrada / saída\nX — limpar marcas\n"
            "M — som da prévia (no modo Edição: Shift+M)\nShift + ↑ / ↓ — marcador anterior / próximo\n"
            "C — trocar o modo de comparação\nF — ajustar à janela\n+ / − — mais / menos zoom (de 10% a 1600%)\n"
            "1 / 2 — zoom 100% / 200%\nF11 — prévia em tela cheia (Esc sai) • Shift+F11 — janela em tela cheia\n"
            "Botão direito no vídeo (segurar) — ver o original\nDuplo clique no slider — volta ao padrão\n"
            "Shift + arrastar slider — ajuste fino\n\nCtrl+N novo projeto • Ctrl+Shift+O abrir projeto\n"
            "Ctrl+S salvar projeto • Ctrl+Shift+S salvar projeto como\n"
            "Ctrl+O abrir vídeo • Ctrl+E exportar • Ctrl+Alt+S salvar preset\n"
            "Ctrl+Shift+F salvar quadro • Ctrl+Z / Ctrl+Y desfazer / refazer\n\n"
            "Ctrl+1 modo Película • Ctrl+2 modo Edição • Ctrl+I importar para a edição\n"
            "Edição: S divide no cursor • Delete apaga • Shift+Delete apaga e fecha o espaço\n"
            "M marcador no cursor (dois cliques nele: nome, cor, nota e capítulo)\n"
            "Ctrl+Alt+C / Ctrl+Alt+V copiar / colar os ajustes de cor do clipe\n"
            "B lâmina • V seleção • N ímã • Ctrl + roda do mouse: zoom da linha do tempo") + "\n\n" + _(
            "J / K / L — para trás / pausar / para a frente (de novo: 2×, 4×, 8×; sem som fora de 1× para a frente)\n"
            "K + J / L — um quadro para trás / para a frente • Ctrl+L — repetir\n"
            "Edição: Q / W apara o começo / o fim do clipe até o cursor e fecha o espaço\n"
            ", / . — inserir / sobrescrever no cursor (itens escolhidos na Mídia)\n"
            "Ctrl ao soltar ou mover — inverte inserir / sobrescrever • Alt ao aparar — só a imagem ou só o som "
            "(corte J/L)") + "\n" + _(
            "Edição: Shift+F congela o quadro do cursor (divide o clipe e põe ali 2 s de quadro parado; inserir / "
            "sobrescrever segue o botão da linha do tempo)\n"
            "Losango ao lado de um ajuste — chave no cursor (botão direito: curva, apagar) • setas — chave anterior "
            "/ próxima\nLosangos na linha do tempo: clique vai até a chave, arrastar move, Delete apaga") + "\n\n" + _(
            "Ctrl+Shift+L — painel de legendas (nele: Ctrl+F buscar • Ctrl+Enter aplicar o texto • "
            "Ctrl+Shift+Enter legenda nova)") + "\n\n" + _(
            "Edição: Alt+R / G / B / D — +1 ponto de luz vermelha / verde / azul / densidade da copiadora no "
            "plano (com Shift: −1; clipes selecionados ou o plano da V1 no cursor)") + "\n\n" + _(
            "Ctrl+F (com o foco nos ajustes) ou / — filtrar ajustes (Esc limpa o filtro)") + "\n\n" + _(
            "Edição, Mídia: Ctrl+Shift+N pasta nova • F2 (ou dois cliques no nome) renomeia a pasta • "
            "arrastar leva itens e pastas para dentro e para fora das pastas") + "\n\n" + _(
            "Shift+D — desligar / religar todos os efeitos") + "\n\n" + _(
            "Edição, sequências: Ctrl+Tab / Ctrl+Shift+Tab — próxima / anterior sequência (abas sobre a linha do tempo; "
            "\"+\" cria uma, dois cliques na aba renomeiam, arrastar muda a ordem, botão direito duplica, "
            "configura ou apaga)"))

    def about(self) -> None:
        try:
            ff = media.ffmpeg()
        except RuntimeError:
            ff = _("não encontrado")
        QMessageBox.about(self, _("Sobre o {app}").format(app=APP_NAME), (
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>" + _("Simula película cinematográfica em vídeos digitais: cor de negativos e cópias, grão, halação, "
                      "bloom, bitolas de 8 mm a IMAX, tremor de projetor, desgaste e moldura.") + "</p>"
            f"<p>GPU: {self.engine.renderer}<br>ffmpeg: {ff}</p>"
            "<p>" + _("Os presets com nomes de filmes são aproximações artísticas, sem relação com os fabricantes.")
            + " " + _("O grão no negativo e a diferença de nitidez entre camadas usam números de datasheets públicos da Kodak.") + "</p>"
            "<p>" + _("Fontes dos títulos e legendas ({licenca}): {fontes}.").format(
                licenca="SIL Open Font License 1.1", fontes=", ".join(n for n, _l in textrender.credits())) + "</p>"))

    # ================================================================ teclado e janela
    def keyPressEvent(self, e):
        k = e.key()
        mod = e.modifiers()
        shift = bool(mod & Qt.KeyboardModifier.ShiftModifier)
        if mod & Qt.KeyboardModifier.ControlModifier:
            return super().keyPressEvent(e)
        if (k == Qt.Key.Key_Slash or e.text() == "/") and filtro_ajustes.focus_current(self, QApplication.focusWidget()):
            return  # 1.7: "/" leva ao filtro de ajustes (fora de campos de texto)
        fps = int(round(self.info.fps)) if self.info else 24
        if self.mode == "edicao" and k == Qt.Key.Key_S:
            self.model.split_at(self.frame_idx)
            return
        if self.mode == "edicao" and k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self.tl_editor.canvas.delete_keys():  # chaves selecionadas na linha do tempo vão antes
                self.model.delete_selected(ripple=shift)
            return
        if self.mode == "edicao" and k == Qt.Key.Key_M and not shift:
            self.add_marker()  # no modo Edição o M marca; o som da prévia fica no Shift+M
            return
        if self.mode == "edicao" and k in (Qt.Key.Key_Q, Qt.Key.Key_W) and not shift:
            self.trim_to_playhead("start" if k == Qt.Key.Key_Q else "end")
            return
        if self.mode == "edicao" and k == Qt.Key.Key_F and shift:
            sel = [c for c in self.model.selected_clips() if c.start <= self.frame_idx < c.end]
            tempo_ui.freeze_at(self.tl_editor.canvas, sel[0].id if sel else None)  # congelar este quadro
            return
        if self.mode == "edicao" and k in (Qt.Key.Key_Comma, Qt.Key.Key_Period):
            self.bin.place(k == Qt.Key.Key_Comma)  # inserir / sobrescrever no cursor
            return
        if k == Qt.Key.Key_D and mod == Qt.KeyboardModifier.ShiftModifier:
            sem_efeitos_ui.toggle(self)
            return
        if k in (Qt.Key.Key_J, Qt.Key.Key_K, Qt.Key.Key_L) and not shift:
            if k == Qt.Key.Key_K:
                if not e.isAutoRepeat():
                    self._k_held = True
                    self.stop_play()
            elif not e.isAutoRepeat() or self._k_held:   # segurar K + L: anda quadro a quadro
                self.shuttle(1 if k == Qt.Key.Key_L else -1)
            return
        if shift and k in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.goto_marker(1 if k == Qt.Key.Key_Down else -1)
            return
        if k == Qt.Key.Key_Space:
            self.toggle_play()
        elif k == Qt.Key.Key_Left:
            self.step(-fps if shift else -1)
        elif k == Qt.Key.Key_Right:
            self.step(fps if shift else 1)
        elif k == Qt.Key.Key_Home:
            self.seek(self.inp or 0)
        elif k == Qt.Key.Key_End and self.info:
            self.seek(self.outp if self.outp is not None else self.info.frames - 1)
        elif k == Qt.Key.Key_I:
            self.mark_in()
        elif k == Qt.Key.Key_O:
            self.mark_out()
        elif k == Qt.Key.Key_X:
            self.clear_marks()
        elif k == Qt.Key.Key_M:
            if self.btn_mute.isEnabled():
                self.btn_mute.toggle()
        elif k == Qt.Key.Key_C:
            order = ["proc", "split", "side", "orig"]
            nxt = order[(order.index(self.viewer.mode) + 1) % len(order)]
            self.compare.set_current(nxt)
            self._set_compare(nxt)
        elif k == Qt.Key.Key_F:
            self.viewer.set_zoom(None)
        elif k == Qt.Key.Key_1:
            self.viewer.set_zoom(1.0)
        elif k == Qt.Key.Key_2:
            self.viewer.set_zoom(2.0)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.viewer.zoom_step(1)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.viewer.zoom_step(-1)
        elif k == Qt.Key.Key_Escape and cor_ui.cancel_pick(self):
            pass  # 1.6: Esc cancela o conta-gotas
        elif k == Qt.Key.Key_Escape and self.preview_fullscreen:
            self.toggle_preview_fullscreen()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_K and not e.isAutoRepeat():
            self._k_held = False
        super().keyReleaseEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self._k_held = False  # o K pode ter sido solto em outra janela
        super().changeEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.handle_files(paths)

    def closeEvent(self, e):
        if not self.confirm_discard():
            e.ignore()
            return
        if self.queue.busy:
            r = QMessageBox.question(self, APP_NAME, _("Há exportações em andamento. Fechar e cancelar todas?"))
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            for j in self.queue.jobs:
                j.cancel.set()
            deadline = time.time() + 5
            while self.queue.busy and time.time() < deadline:
                QApplication.processEvents()
                time.sleep(0.05)
        self.stop_play()
        if self.preview_fullscreen:
            self.toggle_preview_fullscreen()  # salva a geometria e os painéis da janela normal
        self.store.commit()
        self.audio_stop_and_clean()
        self.settings.setValue("edit_film", "true" if self.edit_film else "false")
        self.settings.setValue("scopes", self.hist.mode)
        self.settings.setValue("scopes_edit", self.edit_scopes.mode)
        self.settings.setValue("session_values", json.dumps(self.store.values))
        self.settings.setValue("session_preset", self.preset_id)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.split.saveState())
        self.settings.setValue("splitter_edit", self.center_split.saveState())
        super().closeEvent(e)
