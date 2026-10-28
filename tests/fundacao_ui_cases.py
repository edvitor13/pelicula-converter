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
    return export.preview_frame(win.engine, win.info, win._export_look()[0], s, n, seq=seq, depth=16,
                                keys=win._export_keys())


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


# ------------------------------------------------------------------ chaves de animação (sem GPU)
def _model_seq():
    from pelicula.ui.edit_model import TimelineModel
    src = tl.Source("C:/v/a.mp4", 320, 180, 24.0, "24/1", 240, 10.0, has_audio=True)
    m = TimelineModel(tl.Sequence.for_source(src))
    v = next(c for c in m.seq.clips if c.kind == tl.VIDEO)
    return m, v.id


def test_timeline_model_key_api_with_history():
    m, vid = _model_seq()
    seen = []
    m.changed.connect(seen.append)
    assert m.add_key(vid, "opacidade", 10, 0.0)
    assert m.add_key(vid, "opacidade", 40, 1.0, "suavizar")
    assert m.keys_of(vid, "opacidade") == [(10.0, 0.0, "linear"), (40.0, 1.0, "suavizar")]
    assert m.value_at(vid, "opacidade", 25) == 0.5 and m.value_at(vid, "opacidade", 0) == 0.0
    assert seen == ["values", "values"]
    assert m.move_key(vid, "opacidade", 40, 30)
    assert m.keys_of(vid, "opacidade")[1][0] == 30.0
    assert not m.move_key(vid, "opacidade", 99, 31) and not m.remove_key(vid, "opacidade", 77)
    assert m.remove_key(vid, "opacidade", 10) and len(m.keys_of(vid, "opacidade")) == 1
    m.undo()
    assert len(m.keys_of(vid, "opacidade")) == 2
    m.undo()
    assert m.keys_of(vid, "opacidade")[1][0] == 40.0
    m.redo()
    m.redo()
    assert m.keys_of(vid, "opacidade") == [(30.0, 1.0, "suavizar")]
    assert m.clear_keys(vid) and m.keys_of(vid, "opacidade") == [] and not m.clear_keys(vid)
    m.undo()
    assert m.keys_of(vid, "opacidade") == [(30.0, 1.0, "suavizar")]
    with pytest.raises(KeyError):
        m.add_key(vid, "mesclagem", 0, "tela")


def test_timeline_model_edits_keep_the_animation():
    m, vid = _model_seq()
    m.add_key(vid, "exposicao", 0, -1.0)
    m.add_key(vid, "exposicao", 100, 1.0, "suavizar")
    before = {t: m.value_at(vid, "exposicao", t) for t in range(0, 200)}
    m.split_clip(vid, 50)
    m.commit()
    halves = sorted((c for c in m.seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    assert len(halves) == 2
    for t in range(0, 200):
        c = halves[0] if t < halves[1].start else halves[1]
        assert m.value_at(c.id, "exposicao", t) == before[t]
    # copiar a cor (com a animação) para o outro clipe, preso ao começo dele
    assert m.copy_values(halves[0].id) and m.paste_values([halves[1].id]) == 1
    for k in range(0, 40):
        assert m.value_at(halves[1].id, "exposicao", 50 + k) == before[k]
    m.undo()
    for t in range(50, 200):
        assert m.value_at(halves[1].id, "exposicao", t) == before[t]
    # fps novo: as chaves acompanham o tempo em segundos
    c0 = halves[0]
    m.set_settings(m.seq.width, m.seq.height, "48/1")
    c0 = m.seq.find(c0.id)
    assert m.value_at(c0.id, "exposicao", 50) == pytest.approx(before[25])
    m.undo()
    assert m.value_at(c0.id, "exposicao", 25) == before[25]


def test_param_store_look_keys_with_history():
    from pelicula.ui.store import ParamStore
    st = ParamStore()
    assert st.keys == {} and st.keys_json() == {}
    st.set("exposicao", 0.5)
    assert st.add_key("exposicao", 0)          # o valor atual
    assert st.add_key("exposicao", 24, 1.5, "suavizar_entrada")
    assert st.keys_of("exposicao") == [(0.0, 0.5, "linear"), (24.0, 1.5, "suavizar_entrada")]
    assert st.value_at("exposicao", 12) == pytest.approx(1.0)  # curva da chave da esquerda (linear)
    assert st.values_at(12)["exposicao"] == pytest.approx(1.0) and st.values["exposicao"] == 0.5
    st.undo()
    assert st.keys_of("exposicao") == [(0.0, 0.5, "linear")]
    st.redo()
    assert len(st.keys_of("exposicao")) == 2
    assert st.move_key("exposicao", 24, 48) and st.keys_of("exposicao")[1][0] == 48.0
    st.set_all(presets.builtin_values("vision3_500t"))  # um preset troca os valores; as chaves ficam
    assert len(st.keys_of("exposicao")) == 2
    st.set_all(st.values, keys={})
    assert st.keys == {}
    st.undo()
    assert len(st.keys_of("exposicao")) == 2
    with pytest.raises(KeyError):
        st.add_key("bitola", 0, "8mm")


# ------------------------------------------------------------------ chaves de animação na janela
def test_look_keys_reach_preview_save_frame_project_and_export(win, sample_video):
    from pelicula import project
    _open(win, sample_video)
    win.apply_preset("vision3_500t")
    win.store.add_key("exposicao", 0, -1.0)
    win.store.add_key("exposicao", 20, 1.5, "suavizar")
    assert win.frame_recipe().keys == win.store.keys and win._export_keys() == win.store.keys_json()
    for n in (2, 15):
        assert np.array_equal(win.still_frame(n), _export_frame(win, n)), f"quadro {n}"
    a, b = win.still_frame(2), win.still_frame(15)
    assert not np.array_equal(a, b)
    p = win._make_project(backup=True)
    assert p.look_keys == win.store.keys_json() and "chaves_look" in p.features()
    win._saved_state = win._state()
    win.store.remove_key("exposicao", 20)
    assert win.is_dirty()
    win.store.clear_keys()
    win.show_project(project.from_json(p.to_json()), remember=False)
    assert win.store.keys_json() == p.look_keys
    win.store.clear_keys()


def test_animated_clip_in_edit_mode_is_the_exported_frame(win, sample_video):
    _open(win, sample_video)
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.set_key(v.id, "escala", 0, 1.0)
    seq.set_key(v.id, "escala", 20, 0.5, "suavizar")
    seq.set_key(v.id, "exposicao", 0, 0.0)
    seq.set_key(v.id, "exposicao", 20, 1.0)
    _set_sequence(win, seq)
    win._set_edit_film(False)
    shots = [win.still_frame(n) for n in (3, 18)]
    for n, img in zip((3, 18), shots):
        assert np.array_equal(img, _export_frame(win, n)), f"quadro {n}"
    assert not np.array_equal(shots[0], shots[1])
    live = win._live_layers(win.cur_layers) if win.cur_layers is not None else None
    if live is not None and live.layers:
        layer = live.layers[0].layer
        assert layer.values == win.model.seq.values_at(layer.clip, live.frame)
