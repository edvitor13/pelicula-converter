"""Zoom livre do visualizador (lupas, roda, teclas) e prévia em tela cheia.

Rodam num subprocesso com QT_QPA_PLATFORM=offscreen: nenhuma janela aparece na tela e a tela cheia
não toma o monitor de quem roda os testes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_VIEWER_SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula.ui.viewer import MAX_ZOOM, MIN_ZOOM, ZOOM_STEP, Viewer

out = {}
v = Viewer()
v.resize(828, 628)  # área útil 800x600 com a borda de 14 px
img = QImage(1920, 1080, QImage.Format.Format_RGB888)
img.fill(0x404040)
v.set_images(img, img)
fit = v.fit_scale()
out["fit"] = fit
seen = []
v.zoomChanged.connect(seen.append)

v.zoom_step(1)
out["in1"] = v.zoom
v.zoom_step(-1)
out["back_to_fit"] = v.zoom  # cruzou o "ajustar": para nele (None)
v.zoom_step(-1)
out["below_fit"] = v.zoom
r = v._image_rect(img, v._area())
out["small_centered"] = [round(r.center().x(), 3), round(r.center().y(), 3), round(v._area().center().x(), 3),
                         round(v._area().center().y(), 3)]
out["pannable_small"] = v._pannable()
for _ in range(40):
    v.zoom_step(-1)
out["min"] = v.zoom
for _ in range(80):
    v.zoom_step(1)
out["max"] = v.zoom
out["pannable_big"] = v._pannable()
v.set_zoom(None)
out["signals"] = len(seen)

v.set_fullscreen(True)
out["fs_margin"] = v.margin
out["fs_hint"] = v._hint
out["fs_fit"] = v.fit_scale()
v.set_fullscreen(False)
out["normal_margin"] = v.margin
out["normal_hint"] = v._hint
out["limits"] = [MIN_ZOOM, MAX_ZOOM, ZOOM_STEP]
print(json.dumps(out))
app.exit(0)
'''

_MAIN_SCRIPT = r'''
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
app = QApplication([])
out = {}
try:
    from pelicula.ui.main_window import MainWindow
    win = MainWindow()
except Exception as exc:
    print(json.dumps({"skip": str(exc)[:300]}))
    sys.exit(0)
from pelicula import media, testimage
from pelicula.ui.main_window import qimage_from

calls = []
win.showFullScreen = lambda: calls.append("full")
win.showNormal = lambda: calls.append("normal")
win.showMaximized = lambda: calls.append("max")

out["no_media_blocked"] = (win.toggle_preview_fullscreen(), win.preview_fullscreen)[1]
path = os.path.join(tempfile.mkdtemp(), "cena.png")
qimage_from(testimage.make(1920, 1080)).save(path)
if not media.configure():
    print(json.dumps({"skip": "ffmpeg indisponível"}))
    sys.exit(0)
import time


def wait_width(w):
    """O quadro chega de uma thread; espera a prévia renderizada ter a largura esperada."""
    end = time.time() + 30
    while time.time() < end:
        app.processEvents()
        if win.viewer.proc is not None and win.viewer.proc.width() == w:
            return w
        time.sleep(0.02)
    return None if win.viewer.proc is None else win.viewer.proc.width()


win.load_media(path)
win.prev_combo.setCurrentIndex(win.prev_combo.findData("540"))
out["normal_size"] = list(win.preview_size())
out["normal_rendered"] = wait_width(960)
win.toggle_preview_fullscreen()
out["fs"] = win.preview_fullscreen
out["fs_size"] = list(win.preview_size())
out["fs_rendered"] = wait_width(960)
out["hidden"] = [w.isHidden() for w in (win.top_bar, win.looks, win.right_panel, win.statusBar())]
out["kept"] = [w.isHidden() for w in (win.viewer_bar, win.transport, win.prev_combo, win.btn_play, win.timeline)]
out["btn_text"] = win.btn_full.text()
out["viewer_fs"] = win.viewer.fullscreen
win.prev_combo.setCurrentIndex(win.prev_combo.findData("full"))
out["fs_full_rendered"] = wait_width(1920)
win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier, "+"))
out["plus_zoom"] = win.viewer.zoom
win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Minus, Qt.KeyboardModifier.NoModifier, "-"))
out["minus_back_to_fit"] = win.viewer.zoom
win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
out["after_esc"] = win.preview_fullscreen
out["shown_again"] = [w.isHidden() for w in (win.top_bar, win.looks, win.right_panel, win.viewer_bar, win.transport,
                                             win.statusBar())]
out["btn_text_after"] = win.btn_full.text()
out["size_after"] = list(win.preview_size())
out["calls"] = calls
out["quality_kept"] = win.preview_q
print(json.dumps(out))
app.exit(0)
'''


def _run(tmp_path, script: str) -> dict:
    f = tmp_path / "script.py"
    f.write_text(script, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=str(tmp_path / "appdata"),
               PELICULA_SETTINGS_DIR=str(tmp_path / "settings"), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    res = subprocess.run([sys.executable, str(f), str(ROOT)], capture_output=True, env=env, timeout=150, cwd=str(tmp_path))
    lines = res.stdout.decode("utf-8", "replace").strip().splitlines()
    assert res.returncode == 0 and lines, res.stderr.decode("utf-8", "replace")[-3000:]
    return json.loads(lines[-1])


def test_free_zoom_steps_limits_and_fullscreen(tmp_path):
    d = _run(tmp_path, _VIEWER_SCRIPT)
    lo, hi, step = d["limits"]
    fit = d["fit"]
    assert abs(fit - min(800 / 1920, 600 / 1080)) < 1e-6
    assert abs(d["in1"] - fit * step) < 1e-6
    assert d["back_to_fit"] is None
    assert abs(d["below_fit"] - fit / step) < 1e-6
    x, y, ax, ay = d["small_centered"]
    assert (x, y) == (ax, ay) and d["pannable_small"] is False
    assert d["min"] == lo and d["max"] == hi and d["pannable_big"] is True
    assert d["signals"] >= 4
    assert d["fs_margin"] == 0 and d["fs_hint"]
    assert d["fs_fit"] > fit  # sem borda, a imagem fica maior
    assert d["normal_margin"] == 14 and d["normal_hint"] is False


def test_main_window_preview_fullscreen(tmp_path):
    d = _run(tmp_path, _MAIN_SCRIPT)
    if "skip" in d:
        import pytest
        pytest.skip(d["skip"])
    assert d["no_media_blocked"] is False
    assert d["normal_size"] == [960, 540] and d["normal_rendered"] == 960
    assert d["fs"] is True and d["viewer_fs"] is True
    assert d["fs_size"] == [960, 540] and d["fs_rendered"] == 960  # a resolução escolhida continua
    assert all(d["hidden"]) and not any(d["kept"])  # barra da prévia e player continuam na tela cheia
    assert d["btn_text"] == "Sair da tela cheia" and d["btn_text_after"] == ""
    assert d["fs_full_rendered"] == 1920  # dá para escolher a máxima na própria tela cheia
    assert d["plus_zoom"] is not None and d["minus_back_to_fit"] is None
    assert d["after_esc"] is False and not any(d["shown_again"])
    assert d["size_after"] == [1920, 1080] and d["quality_kept"] == "full"  # vale a escolha feita
    assert d["calls"] == ["full", "normal"]
