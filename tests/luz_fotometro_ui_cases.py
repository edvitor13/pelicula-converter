"""Casos da luz por plano e do fotômetro da película na janela (rodados por test_luz_fotometro_ui.py num subprocesso
offscreen).

O cartão "Luz da copiadora" do inspetor (mostrador 25-25-25, aviso sem Laboratório, ±1 ponto, zerar, copiar para
os selecionados, tudo com desfazer), os atalhos Alt+R/G/B/D e o módulo "laboratorio". Preferências num .ini só
deste arquivo; sem OpenGL 3.3 ou sem ffmpeg os casos da janela se pulam.
"""

from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_luz_fotometro_ui_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import media, modules  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import luz_plano_ui  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402

W, H = 320, 180


def pump(cond, timeout=20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(scope="module")
def png(tmp_path_factory):
    from PySide6.QtGui import QImage
    y, x = np.mgrid[0:H, 0:W]
    arr = np.dstack([x * 255 // W, y * 255 // H, np.full((H, W), 90)]).astype(np.uint8).copy()
    p = tmp_path_factory.mktemp("luz") / "cena.png"
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
    modules.set_enabled(st, "laboratorio", True)
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


def open_two_shots(win, png):
    """Montagem com dois planos da mesma imagem (0–23 e 24–47) no modo Edição; o primeiro selecionado."""
    seq = tl.Sequence(W, H, "24/1")
    src = tl.Source.from_info(media.probe(png))
    seq.insert_media(src, at=0)
    seq.insert_media(src, at=seq.clips[0].end)
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
    vids = sorted((c for c in win.model.seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    win.model.select([vids[0].id])
    APP.processEvents()
    return vids


def values(win, cid):
    return win.model.seq.find(cid).values


def set_module(win, module_id, on):
    modules.set_enabled(win.settings, module_id, on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


# ------------------------------------------------------------------ sem janela
def test_card_sits_after_the_camera_card():
    ins = ClipInspector(TimelineModel())
    keys = [c.section.key for c in ins.vcards]
    assert keys.index("luz_copiadora") == keys.index("camera") + 1


# ------------------------------------------------------------------ janela: luz por plano
def test_card_has_the_classic_display_and_warns_without_the_laboratory(win, png):
    vids = open_two_shots(win, png)
    panel = win.lights_panel
    assert panel is not None and win.lights_card.isAncestorOf(panel)
    win.store.set("lab_on", False)
    APP.processEvents()
    assert panel.display.text() == "25 · 25 · 25"
    assert not panel.warning.isHidden() and "Laboratório" in panel.warning.text()
    win.store.set("lab_on", True)
    win.btn_edit_film.setChecked(True)
    APP.processEvents()
    assert panel.warning.isHidden()
    win.store.set("lab_luz_r", 2.0)
    win.model.update_clip_values({vids[0].id: {"luz_r": 1.0, "luz_densidade": -1.0}})
    APP.processEvents()
    assert panel.display.text() == "27 · 24 · 24"
    assert "R +0" not in panel.detail.text() and "−1" in panel.detail.text()
    win.model.undo()
    win.store.set("lab_luz_r", 0.0)
    win.btn_edit_film.setChecked(False)
    APP.processEvents()


def test_trim_buttons_are_one_undo_step_each(win, png):
    vids = open_two_shots(win, png)
    panel = win.lights_panel
    panel.buttons[("luz_g", 1)].click()
    panel.buttons[("luz_g", 1)].click()
    panel.buttons[("luz_b", -1)].click()
    APP.processEvents()
    assert values(win, vids[0].id)["luz_g"] == 2.0 and values(win, vids[0].id)["luz_b"] == -1.0
    win.model.undo()
    assert values(win, vids[0].id)["luz_b"] == 0.0 and values(win, vids[0].id)["luz_g"] == 2.0
    win.model.undo()
    assert values(win, vids[0].id)["luz_g"] == 1.0
    panel.reset()
    assert values(win, vids[0].id)["luz_g"] == 0.0
    for _ in range(30):
        panel.trim("luz_r", 1)
    assert values(win, vids[0].id)["luz_r"] == 24.0, "dentro da faixa do ajuste"
    panel.reset()


def test_copy_lights_to_the_selected_clips(win, png):
    vids = open_two_shots(win, png)
    win.model.update_clip_values({vids[0].id: {"luz_r": 3.0, "luz_b": -2.0}})
    win.model.select([vids[0].id, vids[1].id])
    APP.processEvents()
    panel = win.lights_panel
    assert panel.btn_copy.isEnabled()
    assert panel.copy_to_selected() == 1
    assert values(win, vids[1].id)["luz_r"] == 3.0 and values(win, vids[1].id)["luz_b"] == -2.0
    win.model.undo()
    assert values(win, vids[1].id)["luz_r"] == 0.0


def test_shortcuts_trim_the_selection_or_the_shot_under_the_playhead(win, png):
    vids = open_two_shots(win, png)
    shortcuts = {s.key().toString(): s for s in win.lights_shortcuts}
    for k in ("Alt+R", "Alt+G", "Alt+B", "Alt+D", "Alt+Shift+R", "Alt+Shift+D"):
        assert k in shortcuts, k
    shortcuts["Alt+R"].activated.emit()
    shortcuts["Alt+R"].activated.emit()
    shortcuts["Alt+Shift+B"].activated.emit()
    assert values(win, vids[0].id)["luz_r"] == 2.0 and values(win, vids[0].id)["luz_b"] == -1.0
    assert "Luzes do plano" in win.statusBar().currentMessage()
    win.model.select([])
    win.seek(vids[1].start + 2)
    APP.processEvents()
    shortcuts["Alt+D"].activated.emit()
    assert values(win, vids[1].id)["luz_densidade"] == 1.0, "sem seleção: o plano da V1 sob o cursor"
    win.set_mode("pelicula")
    shortcuts["Alt+D"].activated.emit()
    assert values(win, vids[1].id)["luz_densidade"] == 1.0, "só no modo Edição"
    win.set_mode("edicao")
    assert "Alt+R" in "".join(str(x) for x in [win.show_shortcuts.__code__.co_consts])


def test_card_and_shortcuts_belong_to_the_laboratory_module(win, png):
    open_two_shots(win, png)
    set_module(win, "laboratorio", False)
    assert win.lights_card.isHidden()
    assert not any(s.isEnabled() for s in win.lights_shortcuts)
    set_module(win, "laboratorio", True)
    assert not win.lights_card.isHidden()
    assert all(s.isEnabled() for s in win.lights_shortcuts)


# ------------------------------------------------------------------ janela: fotômetro da película
def test_meter_is_a_beta_module_off_by_default(win):
    meter = win.film_meter
    assert meter is not None and win._module_tools()["fotometro"] == [meter.btn]
    assert meter.btn.isHidden() and meter.info.isHidden()
    assert meter.btn.parent() is win.viewer_bar, "na barra da prévia, não na da linha do tempo"
    set_module(win, "fotometro", True)
    assert not meter.btn.isHidden()
    assert meter.info.isHidden(), "o texto só com o fotômetro ligado"


def test_meter_layer_shows_the_zones_only_on_screen(win, png):
    set_module(win, "fotometro", True)
    open_two_shots(win, png)
    meter = win.film_meter
    win.store.set("lab_on", False)
    APP.processEvents()
    a = win.frame_recipe().render(win.engine, win.cur_layers, 0)
    meter.btn.setChecked(True)
    APP.processEvents()
    ov = win.viewer.overlay
    assert ov is not None and ov.width() == W and ov.height() == H, win.preview_tools.last_error
    assert not meter.info.isHidden() and "stops" in meter.info.text() and "padrão" in meter.info.text()
    assert meter.last_latitude is not None and meter.last_latitude.default
    # o negativo escolhido muda a latitude mostrada
    win.store.set("lab_on", True)
    win.store.set("lab_negativo", "double_x")
    APP.processEvents()
    win.preview_tools.refresh()
    assert meter.last_latitude.negative == "double_x" and not meter.last_latitude.default
    assert "padrão" not in meter.info.text()
    win.store.set("lab_on", False)
    win.store.set("lab_negativo", "vision3_250d")
    APP.processEvents()
    # a receita do quadro (a da exportação) não muda com a camada da tela
    assert np.array_equal(win.frame_recipe().render(win.engine, win.cur_layers, 0), a)
    meter.btn.setChecked(False)
    APP.processEvents()
    assert win.viewer.overlay is None and meter.info.isHidden()


def test_meter_spot_reading(win, png):
    set_module(win, "fotometro", True)
    open_two_shots(win, png)
    meter = win.film_meter
    assert meter.start_spot()
    assert meter.btn.isChecked() and win.viewer.picking
    win.viewer.pick_at(0.5, 0.5)
    APP.processEvents()
    assert not win.viewer.picking
    r = meter.last_reading
    assert r is not None and r.zone in ("sem_detalhe", "pe", "reta", "ombro", "estourado")
    assert win.statusBar().currentMessage().startswith("Fotômetro:")
    # Esc (cancelar) não deixa a leitura presa
    meter.start_spot()
    win.viewer.cancel_pick()
    assert not meter._picking
    meter.btn.setChecked(False)


def test_meter_hides_and_turns_off_with_the_module(win, png):
    set_module(win, "fotometro", True)
    meter = win.film_meter
    meter.btn.setChecked(True)
    set_module(win, "fotometro", False)
    assert meter.btn.isHidden() and not meter.btn.isChecked() and meter.info.isHidden()
    assert win.viewer.overlay is None
