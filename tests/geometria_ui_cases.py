"""Casos de interface da geometria (1.7): desespremer no inspetor e a janela "Configurar a sequência".

Rodados por `test_geometria_ui.py` num subprocesso offscreen com QApplication própria.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import params  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import geometria_ui  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402


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
