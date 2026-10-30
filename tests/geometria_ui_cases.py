"""Casos de interface da geometria (1.7): desespremer no inspetor e a janela "Configurar a sequência".

Rodados por `test_geometria_ui.py` num subprocesso offscreen com QApplication própria.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import params  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import geometria_ui  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402
from pelicula.ui.sequence_dialog import RATIOS, SequenceDialog  # noqa: E402


def one_clip():
    s = tl.Source("v.mp4", 1920, 1080, 24.0, "24/1", 48, 2.0, has_audio=False)
    m = TimelineModel()
    m.set_sequence(tl.Sequence.for_source(s))
    m.select([m.seq.clips[0].id])
    return m


def inspector():
    m = one_clip()
    look = dict(params.FILM.defaults())
    insp = ClipInspector(m)
    insp.geometry.look_values = lambda: look
    insp.geometry.update()
    return m, insp, look


# ------------------------------------------------------------------ #52: desespremer
def test_manual_rate_row_only_with_the_manual_choice():
    m, insp, _look = inspector()
    row = insp.geometry.rows["desespremer_taxa"]
    assert row.isHidden()
    insp.vstore.set("desespremer", "2.0")
    assert row.isHidden()
    insp.vstore.set("desespremer", "manual")
    assert not row.isHidden()
    assert m.seq.clips[0].values["desespremer"] == "manual"
    insp.vstore.set("desespremer", "nao")
    assert row.isHidden()


def test_warning_shows_and_hides_with_the_clip_and_the_look():
    m, insp, look = inspector()
    geo = insp.geometry
    assert geo.warning.isHidden() and geo.warning_text() == ""
    insp.vstore.set("desespremer", "1.5")  # só o clipe
    assert geo.warning.isHidden()
    look.update(anam_on=True, anam_compressao="1.33")  # os dois
    geo.update()
    assert not geo.warning.isHidden() and "1,33" in geo.warning.text()
    look["anam_compressao"] = "nenhuma"  # lente ligada sem compressão
    geo.update()
    assert geo.warning.isHidden()
    look.update(anam_on=False, anam_compressao="2.0")  # lente desligada
    geo.update()
    assert geo.warning.isHidden()
    look["anam_on"] = True
    geo.update()
    assert not geo.warning.isHidden()
    insp.vstore.set("desespremer", "nao")  # o clipe volta ao padrão: o aviso some sozinho
    assert geo.warning.isHidden()


def test_warning_sits_in_the_framing_card():
    _m, insp, _look = inspector()
    card = insp.geometry.card
    assert card.section.key == "transformar" and insp.geometry.warning.parent() is card.body


def test_warning_follows_the_look_store_of_the_window():
    from pelicula.ui.store import ParamStore
    m, insp, _look = inspector()

    class Win:
        inspector = insp
        store = ParamStore(None)

    win = Win()
    win.store.set_all(dict(params.FILM.defaults()), record=False)
    geometria_ui.install(win)
    insp.vstore.set("desespremer", "2.0")
    assert insp.geometry.warning.isHidden()
    win.store.set("anam_on", True)
    win.store.set("anam_compressao", "1.5")
    assert not insp.geometry.warning.isHidden()
    win.store.set("anam_on", False)
    assert insp.geometry.warning.isHidden()


# ------------------------------------------------------------------ #55: "Configurar a sequência"
def dialog(w=1920, h=1080, window=0.0):
    seq = tl.Sequence(width=w, height=h, window=window)
    return seq, SequenceDialog(None, seq)


def choose(dlg, key, how=None):
    dlg.ratio.setCurrentIndex(dlg.ratio.findData(key))
    if how:
        dlg.apply_as.setCurrentIndex(dlg.apply_as.findData(how))


def test_ratio_default_is_neutral():
    _seq, dlg = dialog()
    assert dlg.ratio.currentData() == "" and dlg.chosen_ratio() == 0.0 and not dlg.apply_as.isEnabled()
    assert dlg.ratio_value.isHidden() and dlg.result.isHidden()
    assert dlg.values()[:2] == (1920, 1080) and dlg.window() == 0.0


def test_ratio_menu_has_the_labels_of_the_look():
    _seq, dlg = dialog()
    items = [dlg.ratio.itemData(i) for i in range(dlg.ratio.count())]
    assert items == ["", *RATIOS, "custom"]
    assert dlg.ratio.itemText(items.index("2.39")) == "2,39 (Scope)"


def test_real_frame_only_fills_width_and_height():
    _seq, dlg = dialog()
    choose(dlg, "2.39", "real")
    assert dlg.apply_as.isEnabled() and dlg.values()[:2] == (1920, 804) and dlg.window() == 0.0
    assert "1920 × 804" in dlg.result.text()
    choose(dlg, "1.33")  # mais estreita: a altura fica e a largura muda
    assert dlg.values()[:2] == (1436, 1080)
    assert "1436 × 1080" in dlg.result.text()


def test_bars_store_the_window_and_keep_the_size():
    _seq, dlg = dialog()
    choose(dlg, "2.39", "faixas")
    assert dlg.values()[:2] == (1920, 1080) and dlg.window() == 2.39
    assert "1920 × 804" in dlg.result.text() and "em cima" in dlg.result.text()
    choose(dlg, "1.33")
    assert dlg.window() == 1.33 and "laterais" in dlg.result.text()
    choose(dlg, "1.78")  # a proporção do quadro: nada a gravar
    assert dlg.window() == 0.0 and "sem faixas" in dlg.result.text()


def test_custom_ratio_is_a_free_number():
    _seq, dlg = dialog()
    choose(dlg, "custom", "faixas")
    assert not dlg.ratio_value.isHidden()
    dlg.ratio_value.setValue(2.10)
    assert dlg.window() == 2.1 and "1920 × 914" in dlg.result.text()
    assert (dlg.ratio_value.minimum(), dlg.ratio_value.maximum(), dlg.ratio_value.decimals()) == (1.0, 4.0, 2)
    dlg.apply_as.setCurrentIndex(dlg.apply_as.findData("real"))
    assert dlg.values()[:2] == (1920, 914) and dlg.window() == 0.0


def test_result_follows_the_resolution():
    _seq, dlg = dialog()
    choose(dlg, "2.39", "real")
    dlg.res.setCurrentIndex(dlg.res.findData("720"))
    assert dlg.values()[:2] == (1280, 536) and "1280 × 536" in dlg.result.text()


def test_dialog_reopens_with_the_window_of_the_sequence():
    _seq, dlg = dialog(window=2.39)
    assert dlg.ratio.currentData() == "2.39" and dlg.apply_as.currentData() == "faixas" and dlg.window() == 2.39
    _seq, dlg = dialog(window=2.1)
    assert dlg.ratio.currentData() == "custom" and dlg.ratio_value.value() == 2.1 and dlg.window() == 2.1


def test_set_settings_window_with_undo():
    m = one_clip()
    before = m.seq.to_json()
    m.set_settings(1920, 1080, "24/1", window=2.39)
    assert m.seq.window == 2.39 and m.seq.to_json()["janela"] == 2.39
    m.undo()
    assert m.seq.window == 0.0 and m.seq.to_json() == before
    m.redo()
    assert m.seq.window == 2.39
    m.set_settings(1920, 1080, "24/1", micro_fade=False)  # None = como está
    assert m.seq.window == 2.39
    m.set_settings(1920, 1080, "24/1", window=0.0)
    assert m.seq.window == 0.0 and "janela" not in m.seq.to_json()


def test_safe_area_stays_in_the_window():
    from PySide6.QtCore import QRectF
    from pelicula.ui.viewer import Viewer
    v = Viewer()
    seq = tl.Sequence(width=1920, height=1080, window=2.39)
    frac = geometria_ui.safe_window(seq)
    assert frac[0] == 0.0 and frac[1] == pytest.approx(138 / 1080) and frac[3] == pytest.approx(804 / 1080)
    assert geometria_ui.safe_window(tl.Sequence(width=1920, height=1080)) is None and geometria_ui.safe_window(None) is None
    from pelicula import platforms
    kind = next(a.id for a in platforms.SAFE_AREAS if not a.aspect)
    v.set_safe_area(kind)
    whole, rects = v.safe_geometry(QRectF(0, 0, 1920, 1080))
    assert whole == QRectF(0, 0, 1920, 1080)
    v.set_safe_window(frac)
    f, inside = v.safe_geometry(QRectF(0, 0, 1920, 1080))
    assert f.top() == pytest.approx(138) and f.height() == pytest.approx(804)
    assert all(r.top() >= 138 and r.bottom() <= 138 + 804 + 1e-6 for r in inside)
    v.set_safe_window(None)
    assert v.safe_geometry(QRectF(0, 0, 1920, 1080))[0] == whole
