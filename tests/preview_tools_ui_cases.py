"""Casos das ferramentas da prévia da 1.6 (rodados por test_preview_tools_ui.py num subprocesso offscreen).

Zebra, falsa cor e quadro de referência nos dois modos, sempre só na tela: a receita do quadro (a da exportação e
do "Salvar quadro") sai igual com e sem as camadas. Preferências num .ini só deste arquivo; sem OpenGL 3.3 os casos
se pulam.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_previa_ui_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import exposure, modules, params  # noqa: E402


@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = prefs.settings()
    for m in modules.MODULES:
        s.remove(modules.KEY_PREFIX + m.id)
    s.setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def load_frame(win):
    """Um quadro na prévia sem passar pelo ffmpeg: metade escura, metade estourada."""
    from pelicula.ui.main_window import qimage_from
    h, w = 180, 320
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :160] = 30
    img[:, 160:] = 255
    win.set_mode("pelicula")
    win.store.set_all(params.defaults())
    win.cur = img
    win.cur_q = qimage_from(img)
    win.cur_frame = 0
    win._uploaded = None
    win.render_now()
    APP.processEvents()
    return img


def export_bits(win):
    """O quadro como a receita o grava (a mesma do "Salvar quadro"/exportação, no tamanho da prévia)."""
    return win.frame_recipe(depth=16).render(win.engine, win.cur, 0)


def bar(win):
    return win.preview_bar


def test_buttons_live_in_the_viewer_bar_and_follow_the_scopes_module(win):
    b = bar(win)
    assert all(x.parent() is win.viewer_bar for x in b.buttons()), "na barra da prévia, não na da linha do tempo"
    assert all(not x.isHidden() for x in b.buttons())
    modules.set_enabled(win.settings, "scopes", False)
    win.settings_changed.emit("modulos")
    APP.processEvents()
    assert all(x.isHidden() for x in b.buttons())
    modules.set_enabled(win.settings, "scopes", True)
    win.settings_changed.emit("modulos")
    APP.processEvents()
    assert all(not x.isHidden() for x in b.buttons())


def test_false_color_and_zebra_are_only_on_screen(win):
    load_frame(win)
    before = export_bits(win)
    b = bar(win)
    assert win.viewer.overlay is None
    b.btn_false.setChecked(True)
    APP.processEvents()
    ov = win.viewer.overlay
    assert ov is not None, win.preview_tools.last_error
    assert np.array_equal(export_bits(win), before)
    b.btn_false.setChecked(False)
    b.btn_zebra.setChecked(True)
    APP.processEvents()
    assert win.viewer.overlay is not None, win.preview_tools.last_error
    assert np.array_equal(export_bits(win), before)
    # o lado estourado tem listras, o escuro não
    from PySide6.QtGui import QImage
    q = win.viewer.overlay.convertToFormat(QImage.Format.Format_RGBA8888)
    arr = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * q.height()).reshape(q.height(), -1)
    alpha = arr[:, :q.width() * 4].reshape(q.height(), q.width(), 4)[..., 3]
    assert alpha[:, :150].max() == 0 and alpha[:, 170:].max() > 0
    b.set_zebra_level(6.0)
    assert b.btn_zebra.isChecked() and b.zebra_level == 6.0
    b.btn_zebra.setChecked(False)
    APP.processEvents()
    assert win.viewer.overlay is None


def test_reference_pins_the_frame_and_switches_the_comparison(win, tmp_path):
    load_frame(win)
    b = bar(win)
    before = export_bits(win)
    assert b.pin_frame()
    v = win.viewer
    assert v.reference is not None and v.compare_reference and v.mode in ("split", "side")
    assert v._other()[0] is v.reference
    assert np.array_equal(export_bits(win), before)
    b.clear_reference()
    assert v.reference is None and not v.compare_reference
    from PySide6.QtGui import QImage
    p = tmp_path / "ref.png"
    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    img.save(str(p))
    assert b.open_image(str(p))
    assert v.reference.width() == 64 and v.compare_reference
    assert not b.open_image(str(tmp_path / "nada.png"))
    b.clear_reference()


def test_tools_work_in_edit_mode_without_film(win, tmp_path):
    import time

    from PySide6.QtGui import QImage

    from pelicula import media
    from pelicula import timeline as tl
    if not media.configure():
        pytest.skip("ffmpeg indisponível")
    img = np.zeros((180, 320, 3), np.uint8)
    img[:, 160:] = 255
    p = tmp_path / "cena.png"
    QImage(img.data, 320, 180, 960, QImage.Format.Format_RGB888).copy().save(str(p))
    seq = tl.Sequence(320, 180, "24/1")
    seq.insert_media(tl.Source.from_info(media.probe(str(p))), at=0)
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.set_mode("edicao")
    win._set_edit_film(False)
    win.cur = None
    win.request_frame(0)
    t0 = time.time()
    while win.cur is None and time.time() - t0 < 20:
        APP.processEvents()
        time.sleep(0.01)
    assert win.cur is not None, "o quadro da montagem não carregou"
    before = win.frame_recipe(depth=16).render(win.engine, win.cur, 0) if win.frame_recipe().values else None
    b = bar(win)
    b.btn_zebra.setChecked(True)
    APP.processEvents()
    q = win.viewer.overlay
    assert q is not None and not win.preview_tools.last_error, win.preview_tools.last_error
    b.btn_false.setChecked(True)  # a falsa cor cobre a imagem inteira
    APP.processEvents()
    assert win.viewer.overlay.pixelColor(10, 10).alpha() == 255 and not win.preview_tools.last_error
    b.btn_false.setChecked(False)
    assert before is None or np.array_equal(win.frame_recipe(depth=16).render(win.engine, win.cur, 0), before)
    b.btn_zebra.setChecked(False)
    win.set_mode("pelicula")


def test_bands_are_listed_in_the_tooltip(win):
    tip = bar(win).btn_false.toolTip()
    assert "18%" in tip and all(name.split(" (")[0] in tip for _lo, _hi, _c, name in exposure.BANDS)
