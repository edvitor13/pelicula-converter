"""Casos da cor simples no inspetor do modo Edição (rodados por test_color_tools_ui.py num subprocesso offscreen).

A barra "Cor simples" (conta-gotas do balanço e da cor, igualar, grupos), o "Automático" com o menu do quadro
atual, a ordem dos cartões novos e o módulo "cor_simples". Preferências num .ini só deste arquivo; sem OpenGL 3.3
ou sem ffmpeg os casos da janela se pulam.
"""

from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_cor_simples_ui_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import colorsimple, editparams, media, modules  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import edit_panels  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402

W, H = 320, 180
WARM = (0.62, 0.5, 0.36)     # um "cinza" com dominante quente (código)
BLUE = (0.15, 0.3, 0.85)


def pump(cond, timeout=20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def q(c):
    """A cor como o PNG de 8 bits a guarda."""
    return np.rint(np.asarray(c) * 255) / 255


def scene() -> np.ndarray:
    img = np.zeros((H, W, 3))
    img[:, :160] = WARM
    img[:, 160:] = BLUE
    return np.rint(img * 255).astype(np.uint8)


@pytest.fixture(scope="module")
def png(tmp_path_factory):
    from PySide6.QtGui import QImage
    arr = scene()
    p = tmp_path_factory.mktemp("cor") / "cena.png"
    QImage(arr.data, W, H, 3 * W, QImage.Format.Format_RGB888).copy().save(str(p))
    return str(p)


@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    st = prefs.settings()
    st.setValue("auto_update", "false")
    st.setValue("language", "pt_BR")
    for m in modules.MODULES:
        st.remove(modules.KEY_PREFIX + m.id)
    if not media.configure():
        pytest.skip("ffmpeg indisponível")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def open_clip(win, png):
    seq = tl.Sequence(W, H, "24/1")
    seq.insert_media(tl.Source.from_info(media.probe(png)), at=0)
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
    assert pump(lambda: win.cur is not None and win.cur_layers is not None), "o quadro da montagem não carregou"
    v = next(c for c in win.model.seq.clips if c.kind == tl.VIDEO)
    win.model.select([v.id])
    APP.processEvents()
    return v


def set_module(win, on):
    modules.set_enabled(win.settings, "cor_simples", on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def values(win, cid):
    return win.model.seq.find(cid).values


# ------------------------------------------------------------------ sem janela
def test_new_cards_sit_next_to_the_similar_ones():
    m = TimelineModel()
    ins = ClipInspector(m)
    keys = [c.section.key for c in ins.vcards]
    assert keys.index("pele") == keys.index("cor") + 1
    assert keys.index("alvo") == keys.index("hsl") + 1
    assert keys.index("degrade") == keys.index("efeitos") + 1
    assert [s.key for s in editparams.VIDEO_SECTIONS][-3:] == ["pele", "alvo", "degrade"]
    assert [s.key for s in edit_panels.display_order(editparams.VIDEO_SECTIONS)
            if s.key not in edit_panels.DISPLAY_AFTER] == [s.key for s in editparams.VIDEO_SECTIONS[:-3]]


# ------------------------------------------------------------------ janela
def test_bar_and_cards_belong_to_the_module(win):
    tools = win._module_tools()["cor_simples"]
    assert win.color_tools.bar in tools and len(tools) == 4
    assert modules.is_enabled(win.settings, "cor_simples")
    set_module(win, False)
    assert all(t.isHidden() for t in tools)
    set_module(win, True)
    assert not any(t.isHidden() for t in tools)


def test_white_balance_eyedropper_neutralizes_the_clicked_gray(win, png):
    v = open_clip(win, png)
    ct = win.color_tools
    ct.btn_wb.setChecked(True)
    assert win.viewer.picking
    win.viewer.pick_at(0.25, 0.5)  # o "cinza" quente
    APP.processEvents()
    assert not win.viewer.picking and not ct.btn_wb.isChecked()
    vals = values(win, v.id)
    want = colorsimple.white_balance_from(q(WARM))
    assert abs(vals["temperatura"] - want["temperatura"]) <= 1 and want["temperatura"] < 0
    assert abs(vals["tonalidade"] - want["tonalidade"]) <= 1
    win.model.undo()
    assert values(win, v.id)["temperatura"] == 0.0


def test_color_eyedropper_sets_the_chosen_color_and_the_hsl_band(win, png):
    v = open_clip(win, png)
    ct = win.color_tools
    ct.btn_color.setChecked(True)
    win.viewer.pick_at(0.75, 0.5)  # o azul
    APP.processEvents()
    vals = values(win, v.id)
    assert abs(vals["alvo_matiz"] - colorsimple.pick_target(q(BLUE))["alvo_matiz"]) <= 0.5
    cards = {c.section.key: c for c in win.inspector.vcards}
    assert cards["alvo"].expanded and cards["hsl"].hsl_color == "azul"
    # Esc cancela um conta-gotas ligado
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    ct.btn_wb.setChecked(True)
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not win.viewer.picking and not ct.btn_wb.isChecked()


def test_match_to_an_image_writes_editable_clip_values(win, png, tmp_path):
    from PySide6.QtGui import QImage
    v = open_clip(win, png)
    darker = (scene().astype(np.float64) * 0.6).astype(np.uint8).copy()
    p = tmp_path / "ref.png"
    QImage(darker.data, W, H, 3 * W, QImage.Format.Format_RGB888).copy().save(str(p))
    assert win.color_tools.match_image(str(p))
    vals = values(win, v.id)
    assert vals["exposicao"] < -0.5 and vals["pele_natural"] == 0.5
    win.model.undo()
    assert values(win, v.id)["exposicao"] == 0.0


def test_auto_menu_keeps_the_one_frame_analysis(win, png):
    v = open_clip(win, png)
    chip = win.inspector.chip_auto
    assert chip.menu() is not None and chip.menu().actions()
    chip.menu().actions()[0].trigger()  # "Só o quadro atual"
    APP.processEvents()
    assert values(win, v.id)["temperatura"] != 0.0
    win.model.undo()
    # imagem parada: o clique também cai no quadro atual (não há o que amostrar)
    assert not win.color_tools.auto_whole_clip(v.id)


def test_groups_from_the_bar(win, png):
    v = open_clip(win, png)
    m = win.model
    seq = m.seq
    s2, = seq.insert_media(seq.sources[v.src], at=v.end)
    m.set_sequence(seq, reset_history=False)
    m.select([v.id, s2.id])
    ct = win.color_tools
    gid = ct.group_selected()
    assert gid and ct.group_label.text()
    m.select([v.id])
    APP.processEvents()
    m.set_clip_values(v.id, {**values(win, v.id), "saturacao": -0.4})
    assert values(win, s2.id)["saturacao"] == -0.4
    ct.select_group()
    assert set(m.selection) == {v.id, s2.id}
    ct.ungroup()
    assert not m.seq.find(v.id).color_group and not m.seq.find(s2.id).color_group
