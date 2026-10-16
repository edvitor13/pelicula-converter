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

import numpy as np
from PySide6.QtCore import QObject, QSize, Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, deps, export, look, luts, media, params, presets, system, testimage
from ..engine import Engine, lut_info
from . import icons, theme
from .export_dialog import ExportDialog
from .looks import THUMB_H, THUMB_W, LooksPanel
from .queue_dialog import QueueDialog, open_folder
from .store import ParamStore
from .viewer import Viewer
from .widgets import Histogram, SectionCard, Segmented, Timeline, ToggleSwitch, compact, timecode

MEDIA_FILTER = ("Vídeos e imagens (*.mp4 *.mov *.mkv *.avi *.mxf *.webm *.m4v *.mts *.m2ts *.wmv *.mpg *.ts "
                "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.dpx *.exr);;Todos os arquivos (*)")
PREVIEW_Q = [("540", "Rápida (540p)"), ("720", "Normal (720p)"), ("1080", "Alta (1080p)"),
             ("full", "Máxima (resolução original)")]


def qimage_from(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    if arr.dtype != np.uint8:
        arr = (arr >> 8).astype(np.uint8)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def array_from(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return np.ascontiguousarray(buf[:, : w * 3].reshape(h, w, 3))


class FrameLoader(QObject):
    """Carrega quadros em segundo plano; só o pedido mais recente importa."""

    loaded = Signal(object, int, object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = None
        self._busy = False

    def request(self, info, frame, w, h) -> None:
        with self._lock:
            self._pending = (info, frame, w, h)
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
            info, frame, w, h = job
            try:
                img = media.grab_frame(info, frame, w, h, 8)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))
                continue
            self.loaded.emit(info, frame, img)


class Player:
    """Decodifica em sequência numa thread para a reprodução."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=8)
        self._stop = threading.Event()

    def start(self, info, start, end, w, h, loop, loop_start) -> None:
        self.stop()
        stop = threading.Event()
        q: queue.Queue = queue.Queue(maxsize=8)
        self._stop, self.q = stop, q

        def put(item) -> bool:
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def run():
            f = start
            while not stop.is_set():
                reader = media.FrameReader(info, w, h, 8, f)
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


class _DepsBridge(QObject):
    result = Signal(bool, object, str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
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
        self.frame_idx = 0
        self.cur: np.ndarray | None = None
        self.cur_q: QImage | None = None
        self._uploaded = None
        self.inp: int | None = None
        self.outp: int | None = None
        self.loop = True
        self.playing = False
        self.preview_q = str(self.settings.value("preview_quality", "720"))
        self._seen_done: set[str] = set()
        self._base_cache: tuple[str, dict] | None = None
        self.loader = FrameLoader()
        self.loader.loaded.connect(self._frame_loaded)
        self.loader.failed.connect(lambda m: self.statusBar().showMessage(f"Erro ao ler o quadro: {m}", 8000))
        self.player = Player()

        self._build_ui()
        self.store.changed.connect(self._on_param)
        self.store.historyChanged.connect(self._update_history)

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(0)
        self.render_timer.timeout.connect(self.render_now)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setSingleShot(True)
        self.thumb_timer.setInterval(350)
        self.thumb_timer.timeout.connect(self._render_thumbs)
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.timeout.connect(self._play_tick)
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(500)
        self.queue_timer.timeout.connect(self._queue_tick)
        self.queue_timer.start()
        self._deps_bridge = _DepsBridge()
        self._deps_bridge.result.connect(self._deps_result)
        QTimer.singleShot(1200, self._check_deps)

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

    # ================================================================ interface
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_bar())
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(1)
        self.looks = LooksPanel()
        self.looks.presetChosen.connect(self.apply_preset)
        self.split.addWidget(self.looks)
        self.split.addWidget(self._center())
        self.split.addWidget(self._right_panel())
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([290, 980, 380])
        root.addWidget(self.split, 1)
        self.setCentralWidget(central)
        sb = self.statusBar()
        self.st_file = QLabel("Nenhum arquivo aberto")
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
        bar = QWidget()
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
        self.file_label = QLabel("")
        self.file_label.setObjectName("Muted")
        hl.addWidget(self.file_label, 1)
        self.btn_open = self._flat("open", "Abrir vídeo ou imagem (Ctrl+O)", "Abrir")
        self.btn_open.clicked.connect(self.open_dialog)
        hl.addWidget(self.btn_open)
        self.btn_frame = self._flat("camera", "Salvar o quadro atual em alta qualidade (Ctrl+Shift+S)", "Salvar quadro")
        self.btn_frame.clicked.connect(self.save_frame)
        hl.addWidget(self.btn_frame)
        self.btn_queue = self._flat("queue", "Fila de exportação", "Fila")
        self.btn_queue.clicked.connect(self.show_queue)
        hl.addWidget(self.btn_queue)
        self.btn_export = QPushButton("  Exportar")
        self.btn_export.setObjectName("Primary")
        self.btn_export.setIcon(icons.icon("export", "#1b1205", 16))
        self.btn_export.setToolTip("Exportar com o look atual (Ctrl+E)")
        self.btn_export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_export.clicked.connect(self.export_dialog)
        hl.addWidget(self.btn_export)
        self.btn_settings = self._flat("settings", "Configurações")
        menu = QMenu(self)
        menu.addAction("Dependências e atualizações…", self.show_deps)
        menu.addAction("Pasta do ffmpeg…", self.choose_ffmpeg)
        menu.addAction("Abrir pasta dos meus presets", lambda: system.open_path(presets.user_dir()))
        menu.addAction("Abrir pasta dos meus LUTs", self.open_lut_dir)
        menu.addSeparator()
        menu.addAction("Atalhos do teclado", self.show_shortcuts)
        menu.addAction(f"Sobre o {APP_NAME}", self.about)
        self.btn_settings.setMenu(menu)
        self.btn_settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hl.addWidget(self.btn_settings)
        return bar

    def _center(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("ViewerBar")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(8)
        self.compare = Segmented([
            ("proc", "Película", "Só o resultado"),
            ("split", "Dividido", "Arraste a linha para comparar. Segure o botão direito para ver o original."),
            ("side", "Lado a lado", "Original e resultado lado a lado"),
            ("orig", "Original", "Só o vídeo original"),
        ])
        mode = str(self.settings.value("compare", "split"))
        self.compare.set_current(mode)
        self.compare.changed.connect(self._set_compare)
        hl.addWidget(self.compare)
        hl.addSpacing(10)
        self.btn_fit = self._flat("fit", "Ajustar à janela (F)", "Ajustar")
        self.btn_fit.clicked.connect(lambda: self.viewer.set_zoom(None))
        hl.addWidget(self.btn_fit)
        for z in (1.0, 2.0):
            b = QToolButton()
            b.setObjectName("Flat")
            b.setText(f"{int(z * 100)}%")
            b.setToolTip(f"Zoom {int(z * 100)}% ({int(z)}). Roda do mouse também dá zoom; arraste para mover.")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, zz=z: self.viewer.set_zoom(zz))
            hl.addWidget(b)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("Faint")
        hl.addWidget(self.zoom_label)
        hl.addStretch(1)
        lab = QLabel("Prévia")
        lab.setObjectName("Muted")
        hl.addWidget(lab)
        self.prev_combo = compact(QComboBox(), 12)
        for key, text in PREVIEW_Q:
            self.prev_combo.addItem(text, key)
        self.prev_combo.setCurrentIndex(max(0, self.prev_combo.findData(self.preview_q)))
        self.prev_combo.setToolTip("Resolução da prévia. O grão só aparece fiel na resolução máxima com zoom 100%.")
        self.prev_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_combo.currentIndexChanged.connect(self._preview_changed)
        hl.addWidget(self.prev_combo)
        vl.addWidget(bar)
        self.viewer = Viewer()
        self.viewer.set_mode(mode)
        self.viewer.openRequested.connect(self.open_dialog)
        self.viewer.testRequested.connect(self.open_test_scene)
        self.viewer.filesDropped.connect(self.handle_files)
        self.viewer.zoomChanged.connect(lambda z: self.zoom_label.setText("" if z == "fit" else f"{float(z) * 100:.0f}%"))
        vl.addWidget(self.viewer, 1)
        tr = QWidget()
        tr.setObjectName("Transport")
        th = QHBoxLayout(tr)
        th.setContentsMargins(10, 6, 12, 10)
        th.setSpacing(4)
        self.btn_back = self._flat("step_back", "Quadro anterior (←)")
        self.btn_back.clicked.connect(lambda: self.step(-1))
        self.btn_play = self._flat("play", "Reproduzir / pausar (Espaço)")
        self.btn_play.setIconSize(QSize(22, 22))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_fwd = self._flat("step_fwd", "Próximo quadro (→)")
        self.btn_fwd.clicked.connect(lambda: self.step(1))
        for b in (self.btn_back, self.btn_play, self.btn_fwd):
            th.addWidget(b)
        self.time_label = QLabel("00:00:00:00")
        self.time_label.setObjectName("Time")
        self.time_label.setMinimumWidth(190)
        th.addSpacing(6)
        th.addWidget(self.time_label)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)
        th.addWidget(self.timeline, 1)
        self.btn_in = self._flat("mark_in", "Marcar entrada (I)")
        self.btn_in.clicked.connect(self.mark_in)
        self.btn_out = self._flat("mark_out", "Marcar saída (O)")
        self.btn_out.clicked.connect(self.mark_out)
        self.btn_clear = self._flat("clear", "Limpar entrada e saída (X)")
        self.btn_clear.clicked.connect(self.clear_marks)
        self.btn_loop = self._flat("loop", "Repetir (L)", checkable=True)
        self.btn_loop.setChecked(True)
        self.btn_loop.toggled.connect(lambda on: setattr(self, "loop", on))
        for b in (self.btn_in, self.btn_out, self.btn_clear, self.btn_loop):
            th.addWidget(b)
        vl.addWidget(tr)
        return w

    def _right_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Panel")
        w.setMinimumWidth(340)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 12, 6, 8)
        vl.setSpacing(8)
        k = QLabel("AJUSTES")
        k.setObjectName("Kicker")
        vl.addWidget(k)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.preset_combo = compact(QComboBox(), 14)
        self.preset_combo.setMaxVisibleItems(24)
        self.preset_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preset_combo.activated.connect(self._combo_chosen)
        row.addWidget(self.preset_combo, 1)
        self.btn_save = self._flat("save", "Salvar como novo preset (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_preset_as)
        row.addWidget(self.btn_save)
        self.btn_more = self._flat("more", "Mais opções de preset")
        self.more_menu = QMenu(self)
        self.act_update = self.more_menu.addAction("Atualizar este preset com os ajustes atuais", self.update_user_preset)
        self.act_delete = self.more_menu.addAction("Excluir este preset", self.delete_preset)
        self.more_menu.addAction("Desfazer mudanças (voltar ao preset)", self.revert_preset)
        self.more_menu.addSeparator()
        self.more_menu.addAction("Importar preset (.json)…", self.import_preset)
        self.more_menu.addAction("Exportar preset (.json)…", self.export_preset)
        self.more_menu.addSeparator()
        self.more_menu.addAction("Exportar a cor como LUT .cube (33 pontos)…", lambda: self.export_lut(33))
        self.more_menu.addAction("Exportar a cor como LUT .cube (65 pontos)…", lambda: self.export_lut(65))
        self.more_menu.addAction("Exportar todos os presets como LUTs (pacote)…", self.export_all_luts)
        self.more_menu.aboutToShow.connect(self._menu_state)
        self.btn_more.setMenu(self.more_menu)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.btn_more)
        vl.addLayout(row)
        self.mod_label = QLabel("Modificado — salve como novo preset para usar depois")
        self.mod_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 8.5pt;")
        vl.addWidget(self.mod_label)
        self.hist = Histogram()
        vl.addWidget(self.hist)
        row2 = QHBoxLayout()
        lab = QLabel("Ajustes avançados")
        lab.setObjectName("Muted")
        row2.addWidget(lab)
        self.adv = ToggleSwitch()
        self.adv.setChecked(self.settings.value("advanced", "false") == "true")
        self.adv.toggled.connect(self._set_advanced)
        row2.addWidget(self.adv)
        row2.addStretch(1)
        self.btn_undo = self._flat("undo", "Desfazer (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.store.undo)
        self.btn_redo = self._flat("redo", "Refazer (Ctrl+Y)")
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
        return w

    def _shortcuts(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
        sc("Ctrl+O", self.open_dialog)
        sc("Ctrl+E", self.export_dialog)
        sc("Ctrl+S", self.save_preset_as)
        sc("Ctrl+Shift+S", self.save_frame)
        sc("Ctrl+Z", self.store.undo)
        sc("Ctrl+Y", self.store.redo)
        sc("Ctrl+Shift+Z", self.store.redo)
        sc("F11", lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())

    # ================================================================ arquivos
    def open_dialog(self) -> None:
        d = str(self.settings.value("last_dir", str(Path.home())))
        path, _ = QFileDialog.getOpenFileName(self, "Abrir vídeo ou imagem", d, MEDIA_FILTER)
        if path:
            self.handle_files([path])

    def handle_files(self, paths: list[str]) -> None:
        cubes = [p for p in paths if Path(p).suffix.lower() == ".cube"]
        if cubes:
            self.install_luts(cubes)
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext == ".json":
                self.import_preset(p)
            elif ext != ".cube":
                self.load_media(p)
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
            done, _ = luts.install(paths)
            if done:
                self.cards_lut_set(done[0])

    def cards_lut_set(self, path: str) -> None:
        self.store.set("lut_arquivo", path, record=False)
        self.store.set("lut_entrada", luts.guess_input(path), record=False)
        self.store.set("lut_on", True, record=False)
        self.store.commit()
        self.statusBar().showMessage(f"LUT carregado: {Path(path).name}", 5000)

    def open_test_scene(self) -> None:
        img = testimage.make(1920, 1080)
        path = os.path.join(tempfile.gettempdir(), "pelicula_cena_de_teste.png")
        qimage_from(img).save(path)
        self.load_media(path, label="Cena de teste")

    def load_media(self, path: str, label: str | None = None) -> None:
        try:
            info = media.probe(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Não foi possível abrir o arquivo.\n\n{exc}")
            return
        self.stop_play()
        self.info = info
        self.frame_idx = 0
        self.inp = self.outp = None
        self.cur = None
        self.timeline.set_media(info.frames, info.fps)
        self.file_label.setText(label or Path(path).name)
        self.setWindowTitle(f"{label or Path(path).name} — {APP_NAME}")
        self.st_file.setText(info.summary())
        self._set_media_enabled(True)
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.request_frame(0)

    def _set_media_enabled(self, on: bool) -> None:
        video = on and self.info is not None and not self.info.is_image
        for b in (self.btn_back, self.btn_play, self.btn_fwd, self.btn_in, self.btn_out, self.btn_clear, self.btn_loop):
            b.setEnabled(video)
        self.timeline.setEnabled(video)
        self.btn_export.setEnabled(on)
        self.btn_frame.setEnabled(on)

    def preview_size(self) -> tuple[int, int]:
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
        self.loader.request(self.info, f, w, h)

    def _frame_loaded(self, info, frame: int, img: np.ndarray) -> None:
        if info is not self.info or self.playing:
            return
        self._set_frame(frame, img)
        self.thumb_timer.start()

    def _set_frame(self, frame: int, img: np.ndarray) -> None:
        self.cur = img
        self.cur_q = qimage_from(img)
        self.frame_idx = frame
        self._update_time()
        self.render_now()

    def _update_time(self) -> None:
        if self.info is None:
            return
        self.timeline.set_pos(self.frame_idx)
        self.time_label.setText(f"{timecode(self.frame_idx, self.info.fps)}  /  "
                                f"{timecode(self.info.frames - 1, self.info.fps)}")

    def _preview_changed(self) -> None:
        self.preview_q = self.prev_combo.currentData()
        self.settings.setValue("preview_quality", self.preview_q)
        if self.info is not None:
            if self.playing:
                self.stop_play()
            self.request_frame(self.frame_idx)

    # ================================================================ renderização
    def schedule_render(self) -> None:
        if not self.playing:
            self.render_timer.start()

    def render_now(self) -> None:
        if self.cur is None:
            return
        h, w = self.cur.shape[:2]
        if self._uploaded is not self.cur:
            self.engine.set_input(self.cur)
            self._uploaded = self.cur
        v = self.store.values
        info = lut_info(v["lut_arquivo"]) if v["lut_on"] and v["lut_arquivo"] else None
        t0 = time.perf_counter()
        try:
            plan = look.build_plan(v, w, h, self.frame_idx, self.info.fps if self.info else 24.0, info)
            out = self.engine.render(plan, 8)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Erro na renderização: {exc}", 8000)
            return
        ms = (time.perf_counter() - t0) * 1000
        self.viewer.set_images(qimage_from(out), self.cur_q)
        self.hist.set_image(out)
        self.st_render.setText(f"{ms:.0f} ms")
        self.st_prev.setText(f"Prévia {w}×{h}")
        if v["lut_on"] and v["lut_arquivo"] and info is None:
            self.statusBar().showMessage("O LUT escolhido não pôde ser lido.", 5000)

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
        images = {}
        for item in self._all_presets():
            v = item["valores"]
            info = lut_info(v["lut_arquivo"]) if v.get("lut_on") and v.get("lut_arquivo") else None
            try:
                out = self.thumb_engine.render(look.build_plan(v, tw, th, 3, 24.0, info, dither=False), 8)
            except Exception:  # noqa: BLE001
                continue
            images[item["id"]] = qimage_from(out)
        self.looks.set_images(images)

    def _on_param(self, key: str) -> None:
        for c in self.cards:
            if key == "*" or key in c.keys():
                c.refresh(key)
        self.schedule_render()
        self._update_modified()

    # ================================================================ reprodução
    def toggle_play(self) -> None:
        if self.playing:
            self.stop_play()
        else:
            self.start_play()

    def start_play(self, start: int | None = None) -> None:
        if self.info is None or self.info.is_image:
            return
        loop_start = self.inp or 0
        end = self.outp if self.outp is not None else self.info.frames - 1
        f = self.frame_idx if start is None else start
        if f >= end or f < loop_start and self.inp is not None:
            f = loop_start
        w, h = self.preview_size()
        self.player.start(self.info, f, end, w, h, self.loop, loop_start)
        self._play_t0 = None
        self._play_f0 = f
        self._play_last = f
        self._play_pending = None
        self.playing = True
        self.btn_play.setIcon(icons.icon("pause", theme.TEXT, 18))
        self.play_timer.start(max(5, int(500 / self.info.fps)))

    def stop_play(self) -> None:
        if not self.playing:
            return
        self.player.stop()
        self.play_timer.stop()
        self.playing = False
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
                self._play_t0, self._play_f0 = now, f
            target = self._play_f0 + int((now - self._play_t0) * self.info.fps)
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

    def mark_out(self) -> None:
        if self.info is None or self.info.is_image:
            return
        self.outp = self.frame_idx
        if self.inp is not None and self.inp >= self.outp:
            self.inp = None
        self.timeline.set_inout(self.inp, self.outp)

    def clear_marks(self) -> None:
        self.inp = self.outp = None
        self.timeline.set_inout(None, None)

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

    def preset_name(self, pid: str) -> str:
        for it in self._all_presets():
            if it["id"] == pid:
                return it["nome"]
        return "Personalizado"

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
                combo.addItem(group.upper())
                item = model.item(combo.count() - 1)
                item.setEnabled(False)
                f = theme.font(7.8, theme.QFont.Weight.DemiBold, title=True)
                item.setFont(f)
                item.setForeground(QBrush(QColor(theme.ACCENT)))
            combo.addItem("   " + it["nome"], it["id"])
        i = combo.findData(self.preset_id)
        combo.setCurrentIndex(i if i >= 0 else combo.findData(presets.DEFAULT_ID))
        combo.blockSignals(False)
        self.looks.rebuild(items)
        self.looks.set_selected(self.preset_id)

    def _combo_chosen(self, _i: int) -> None:
        pid = self.preset_combo.currentData()
        if pid:
            self.apply_preset(pid)

    def apply_preset(self, pid: str) -> None:
        vals = self.preset_values(pid)
        if vals is None:
            return
        self.preset_id = pid
        self.store.set_all(vals)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(pid)))
        self.preset_combo.blockSignals(False)
        self.looks.set_selected(pid)
        self._update_modified()

    def _update_modified(self) -> None:
        base = self.preset_values(self.preset_id)
        modified = base is None or base != self.store.values
        self.mod_label.setVisible(modified)

    def _update_history(self) -> None:
        self.btn_undo.setEnabled(self.store.can_undo())
        self.btn_redo.setEnabled(self.store.can_redo())

    def _menu_state(self) -> None:
        user = self.preset_id.startswith("user:")
        self.act_update.setEnabled(user)
        self.act_delete.setEnabled(user)

    def save_preset_as(self) -> None:
        self.store.commit()
        base = self.preset_name(self.preset_id)
        suggestion = base if self.preset_id.startswith("user:") else f"Meu {base}"
        name, ok = QInputDialog.getText(self, "Salvar preset", "Nome do novo preset:", text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        if presets.user_exists(name):
            r = QMessageBox.question(self, "Salvar preset", f"Já existe um preset chamado \"{name}\". Substituir?")
            if r != QMessageBox.StandardButton.Yes:
                return
        pid = presets.save_user(name, self.store.snapshot(), f"Criado a partir de {base}")
        self.preset_id = pid
        self._refresh_presets()
        self._update_modified()
        self.thumb_timer.start()
        self.statusBar().showMessage(f"Preset \"{name}\" salvo em Meus presets.", 5000)

    def update_user_preset(self) -> None:
        if not self.preset_id.startswith("user:"):
            return
        self.store.commit()
        name = self.preset_name(self.preset_id)
        presets.save_user(name, self.store.snapshot())
        self._refresh_presets()
        self._update_modified()
        self.thumb_timer.start()
        self.statusBar().showMessage(f"Preset \"{name}\" atualizado.", 5000)

    def delete_preset(self) -> None:
        if not self.preset_id.startswith("user:"):
            return
        name = self.preset_name(self.preset_id)
        r = QMessageBox.question(self, "Excluir preset", f"Excluir o preset \"{name}\"?")
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
            path, _ = QFileDialog.getOpenFileName(self, "Importar preset", "", "Preset (*.json)")
            if not path:
                return
        try:
            pid = presets.import_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Preset inválido.\n\n{exc}")
            return
        self.preset_id = pid
        self._refresh_presets()
        self.apply_preset(pid)
        self.thumb_timer.start()

    def export_preset(self) -> None:
        name = self.preset_name(self.preset_id)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar preset", f"{name}.json", "Preset (*.json)")
        if path:
            presets.export_file(path, name, self.store.snapshot())
            self.statusBar().showMessage(f"Preset exportado: {path}", 5000)

    def export_lut(self, size: int) -> None:
        name = self.preset_name(self.preset_id)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar LUT", f"{name}.cube", "LUT 3D (*.cube)")
        if not path:
            return
        data = self.engine.bake_lut(self.store.values, size)
        luts.save_cube(path, data, size, name)
        self._uploaded = None
        self.render_now()
        QMessageBox.information(
            self, "LUT exportado",
            f"LUT salvo em:\n{path}\n\nEle guarda só a cor (curva, cópia, tons e saturação). Grão, halação, "
            f"bloom e os outros efeitos de textura não cabem num LUT.\n\nEntrada do LUT: o mesmo perfil escolhido "
            f"em \"Perfil do vídeo\" ({params.PARAMS['entrada'].choices[[c[0] for c in params.PARAMS['entrada'].choices].index(self.store.get('entrada'))][1]}).")

    def export_all_luts(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta onde salvar os LUTs dos presets",
                                             str(self.settings.value("export_dir", str(Path.home()))))
        if not d:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        n = 0
        try:
            for it in self._all_presets():
                if it["id"] == "original":
                    continue
                safe = "".join(ch for ch in it["nome"].replace("•", "-") if ch not in '<>:"/\\|?*').strip()
                data = self.engine.bake_lut(it["valores"], 33)
                luts.save_cube(os.path.join(d, f"{safe}.cube"), data, 33, it["nome"])
                n += 1
        finally:
            QApplication.restoreOverrideCursor()
        self._uploaded = None
        self.render_now()
        QMessageBox.information(self, "LUTs exportados",
                                f"{n} LUTs salvos em:\n{d}\n\nEntrada: vídeo Rec.709 comum. Funcionam no Premiere, "
                                "Resolve, Final Cut, CapCut, OBS e qualquer programa que aceite .cube. "
                                "Eles guardam só a cor; grão e halação ficam no PeliculaConverter.")

    # ================================================================ exportação
    def export_dialog(self) -> None:
        if self.info is None:
            self.open_dialog()
            return
        self.store.commit()
        inout = None
        if self.inp is not None or self.outp is not None:
            inout = (self.inp or 0, self.outp if self.outp is not None else self.info.frames - 1)
        try:
            perf = json.loads(self.settings.value("export_perf", "") or "{}")
        except ValueError:
            perf = {}
        dlg = ExportDialog(self, self.info, self.store.snapshot(), self.preset_name(self.preset_id), inout,
                           str(self.settings.value("export_dir", "")), str(self.settings.value("export_quality", "")),
                           perf, self.engine.renderer.split("/")[0])
        if not dlg.exec():
            return
        job = dlg.job()
        self.settings.setValue("export_dir", str(Path(job.out_path).parent))
        self.settings.setValue("export_quality", dlg.quality.currentData())
        self.settings.setValue("export_perf", json.dumps(dlg.perf_dict()))
        self.queue.add(job)
        self.show_queue()

    def show_queue(self) -> None:
        if self.queue_dialog is None:
            self.queue_dialog = QueueDialog(self, self.queue)
        self.queue_dialog.show()
        self.queue_dialog.raise_()
        self.queue_dialog.activateWindow()

    def _queue_tick(self) -> None:
        active = [j for j in self.queue.jobs if j.status in ("aguardando", "exportando")]
        running = next((j for j in self.queue.jobs if j.status == "exportando"), None)
        if running:
            self.btn_queue.setText(f"Fila • {running.progress * 100:.0f}%")
        elif active:
            self.btn_queue.setText(f"Fila ({len(active)})")
        else:
            self.btn_queue.setText("Fila")
        for j in self.queue.jobs:
            if j.status in ("concluido", "erro") and j.id not in self._seen_done:
                self._seen_done.add(j.id)
                if j.status == "concluido":
                    self.statusBar().showMessage(f"Exportação concluída: {j.out_path}", 10000)
                else:
                    self.statusBar().showMessage("Uma exportação falhou. Veja os detalhes na fila.", 10000)
                    self.show_queue()
                QApplication.alert(self)

    def save_frame(self) -> None:
        if self.info is None:
            return
        stem = Path(self.info.path).stem
        tc = timecode(self.frame_idx, self.info.fps).replace(":", "-")
        d = str(self.settings.value("export_dir", str(Path(self.info.path).parent)))
        path, flt = QFileDialog.getSaveFileName(self, "Salvar quadro", str(Path(d) / f"{stem}_{tc}.png"),
                                                "PNG 16 bits (*.png);;TIFF 16 bits (*.tif);;JPEG (*.jpg)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            w, h = self.info.width, self.info.height
            img = media.grab_frame(self.info, self.frame_idx, w, h, 16, hq=True)
            self.engine.set_input(img)
            self._uploaded = None
            v = self.store.values
            info = lut_info(v["lut_arquivo"]) if v["lut_on"] else None
            out = self.engine.render(look.build_plan(v, w, h, self.frame_idx, self.info.fps, info, dither=False), 16)
            ext = Path(path).suffix.lower()
            pix = {".png": ["-pix_fmt", "rgb48be"], ".tif": ["-pix_fmt", "rgb48le", "-compression_algo", "deflate"],
                   ".tiff": ["-pix_fmt", "rgb48le"], ".jpg": ["-pix_fmt", "yuvj444p", "-q:v", "2"]}.get(ext, [])
            cmd = [media.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
                   "-i", "pipe:0", *pix, "-frames:v", "1", "-update", "1", path]
            res = subprocess.run(cmd, input=out.tobytes(), capture_output=True, creationflags=media.NO_WINDOW)
            if res.returncode != 0:
                raise RuntimeError(res.stderr.decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Não foi possível salvar o quadro.\n\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self.render_now()
        self.statusBar().showMessage(f"Quadro salvo: {path}", 8000)

    # ================================================================ dependências
    def _check_deps(self) -> None:
        folder = self.settings.value("ffmpeg_dir", "") or None

        def run():
            ok = media.configure(folder)
            info = deps.inspect(media.ffmpeg()) if ok else None
            latest = deps.latest_version(timeout=6) if deps.platform_supported() else ""
            self._deps_bridge.result.emit(ok, info, latest)

        threading.Thread(target=run, daemon=True).start()

    def _deps_result(self, ok: bool, info, latest: str) -> None:
        if not ok:
            self.show_deps("O ffmpeg não foi encontrado neste computador. Ele é necessário para abrir e exportar "
                           "vídeos. Clique em \"Baixar ffmpeg\": o download é feito da fonte oficial e conferido.")
            return
        newer = deps.parse_version(latest)
        has_update = bool(info and info.version and newer and info.version[:2] < newer[:2])
        if not info or not (info.outdated or has_update):
            return
        if str(self.settings.value("ffmpeg_skip", "")) == latest:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Atualizar o ffmpeg")
        box.setText(f"O ffmpeg deste computador ({info.label}) está {'desatualizado' if info.outdated else 'numa versão antiga'}."
                    + (f"\n\nA versão {latest} está disponível." if latest else "")
                    + "\n\nVersões novas são mais rápidas e leem mais formatos (o 8.0+ lê ProRes RAW). Atualizar agora?")
        upd = box.addButton("Atualizar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Agora não", QMessageBox.ButtonRole.RejectRole)
        never = box.addButton("Não perguntar de novo", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is upd:
            self.show_deps(auto_download=True)
        elif box.clickedButton() is never:
            self.settings.setValue("ffmpeg_skip", latest or "sempre")

    def show_deps(self, reason: str = "", auto_download: bool = False) -> None:
        from .deps_dialog import DepsDialog
        dlg = DepsDialog(self, f"{self.engine.renderer} • OpenGL {self.engine.ctx.info.get('GL_VERSION', '?')}",
                         self.settings, reason)
        if auto_download and dlg.btn_get.isEnabled():
            QTimer.singleShot(200, dlg._download)
        dlg.exec()
        if self.info is not None:
            self.request_frame(self.frame_idx)

    # ================================================================ configurações
    def choose_ffmpeg(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta que contém ffmpeg.exe e ffprobe.exe", media.tool_dir())
        if not d:
            return
        if media.configure(d):
            self.settings.setValue("ffmpeg_dir", d)
            QMessageBox.information(self, APP_NAME, f"ffmpeg configurado:\n{media.ffmpeg()}")
        else:
            QMessageBox.warning(self, APP_NAME, "Não encontrei ffmpeg.exe e ffprobe.exe nessa pasta.")

    def open_lut_dir(self) -> None:
        system.open_path(luts.user_dir())

    def show_shortcuts(self) -> None:
        QMessageBox.information(self, "Atalhos do teclado", (
            "Espaço — reproduzir / pausar\n← / → — quadro anterior / próximo\nShift + ← / → — 1 segundo\n"
            "Home / End — início / fim\nI / O — marcar entrada / saída\nX — limpar marcas\nL — repetir\n"
            "C — trocar o modo de comparação\nF — ajustar à janela\n1 / 2 — zoom 100% / 200%\n"
            "Botão direito no vídeo (segurar) — ver o original\nDuplo clique no slider — volta ao padrão\n"
            "Shift + arrastar slider — ajuste fino\n\nCtrl+O abrir • Ctrl+E exportar • Ctrl+S salvar preset\n"
            "Ctrl+Shift+S salvar quadro • Ctrl+Z / Ctrl+Y desfazer / refazer • F11 tela cheia"))

    def about(self) -> None:
        try:
            ff = media.ffmpeg()
        except RuntimeError:
            ff = "não encontrado"
        QMessageBox.about(self, f"Sobre o {APP_NAME}", (
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Simula película cinematográfica em vídeos digitais: cor de negativos e cópias, grão, halação, "
            "bloom, bitolas de 8 mm a IMAX, tremor de projetor, desgaste e moldura.</p>"
            f"<p>GPU: {self.engine.renderer}<br>ffmpeg: {ff}</p>"
            "<p>Os presets com nomes de filmes são aproximações artísticas, sem relação com os fabricantes.</p>"))

    # ================================================================ teclado e janela
    def keyPressEvent(self, e):
        k = e.key()
        mod = e.modifiers()
        shift = bool(mod & Qt.KeyboardModifier.ShiftModifier)
        if mod & Qt.KeyboardModifier.ControlModifier:
            return super().keyPressEvent(e)
        fps = int(round(self.info.fps)) if self.info else 24
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
        elif k == Qt.Key.Key_L:
            self.btn_loop.toggle()
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
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.handle_files(paths)

    def closeEvent(self, e):
        if self.queue.busy:
            r = QMessageBox.question(self, APP_NAME, "Há exportações em andamento. Fechar e cancelar todas?")
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
        self.store.commit()
        self.settings.setValue("session_values", json.dumps(self.store.values))
        self.settings.setValue("session_preset", self.preset_id)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.split.saveState())
        super().closeEvent(e)
