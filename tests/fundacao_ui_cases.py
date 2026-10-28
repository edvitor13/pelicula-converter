"""Casos da janela principal para a base da 1.5: a receita do quadro, as chaves de animação e a transparência.

Rodados por test_fundacao_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam
de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. A janela precisa de OpenGL 3.3:
sem ele, os casos pulam.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import export, media, presets  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.export import ExportSettings  # noqa: E402


def pump(cond, timeout=20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    st = prefs.settings()
    st.setValue("auto_update", "false")
    st.setValue("language", "pt_BR")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def _open(win, path) -> None:
    win.set_mode("pelicula")
    win.cur = None
    win.load_media(path)
    assert pump(lambda: win.cur is not None), "o quadro não carregou"


def _set_sequence(win, seq, mode="edicao") -> None:
    win._loading = True
    try:
        win.model.set_sequence(seq)
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.set_mode(mode)
    win.cur = None
    win.request_frame(0)
    assert pump(lambda: win.cur is not None), "o quadro da montagem não carregou"


def _export_frame(win, n) -> np.ndarray:
    """O quadro `n` como a exportação (no tamanho original, 16 bits, sem pontilhado) o grava."""
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)
    seq = win.src_seq.copy() if win.src_seq is not None else None
    return export.preview_frame(win.engine, win.info, win._export_look()[0], s, n, seq=seq, depth=16)


# ------------------------------------------------------------------ receita do quadro
def test_save_frame_is_the_exported_frame_in_film_mode(win, sample_video):
    _open(win, sample_video)
    win.apply_preset("vision3_500t")
    win.store.set("grao_forca", 1.5)
    for n in (2, 7):
        assert np.array_equal(win.still_frame(n), _export_frame(win, n)), f"quadro {n}"


def test_preview_recipe_is_the_export_recipe_reduced(win, sample_video):
    _open(win, sample_video)
    win.apply_preset("vision3_500t")
    prev, still = win.frame_recipe(), win.frame_recipe(16, full=True)
    assert (prev.depth, prev.dither, prev.size) == (8, True, win.preview_size())
    assert prev.values is win.store.values and prev.seq is None
    assert (still.depth, still.dither, still.size) == (16, False, (win.info.width, win.info.height))
    assert still.values == win._export_look()[0]
    assert (prev.fps, prev.legal, prev.lut) == (still.fps, still.legal, still.lut)


def test_save_frame_is_the_exported_frame_in_edit_mode(win, sample_video):
    _open(win, sample_video)
    win.apply_preset("vision3_500t")
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    seq.split(10)
    v = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    seq.set_values(v[1].id, {**v[1].values, "exposicao": 0.5, "escala": 0.7, "rotacao": 6.0})
    over, = seq.insert_media(src, at=3, vtrack=1, with_audio=False)
    seq.set_values(over.id, {**over.values, "escala": 0.5, "opacidade": 0.5})
    _set_sequence(win, seq)
    for film in (False, True):
        win._set_edit_film(film)
        r = win.frame_recipe()
        assert (r.values is None) == (not film) and r.seq is win.model.seq
        assert win.frame_recipe(16, full=True).values == win._export_look()[0]
        for n in (4, 12):
            assert np.array_equal(win.still_frame(n), _export_frame(win, n)), f"quadro {n}, película {film}"
    win._set_edit_film(False)
    assert presets.builtin_values("original") == win._export_look()[0]
