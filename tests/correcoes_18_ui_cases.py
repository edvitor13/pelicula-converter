"""Casos das correções da 1.8 na interface: importar só põe na Mídia (#64).

Rodados por test_correcoes_18_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. O arrasto da seleção inteira (#63) está em
`edit_ui_cases.py` e `test_timeline.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402

from sequencias_ui_cases import fresh, pump, tone_video  # noqa: E402


@pytest.fixture(scope="module")
def win():
    prefs.settings().setValue("auto_update", "false")
    try:
        w = mw.MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def test_import_only_puts_the_files_in_the_media_bin_and_selects_them(win, tmp_path):
    a = tone_video(tmp_path, "a.mp4", "160x90", 24, 440)
    b = tone_video(tmp_path, "b.mp4", "192x108", 30, 880)
    fresh(win)
    win.import_paths([a, b])
    pump()
    assert not win.model.seq.clips                         # nada na linha do tempo
    assert win.bin.selected_paths() == [a, b]              # já escolhidos na Mídia, para , / .
    assert "Mídia" in win.statusBar().currentMessage()
    assert (win.model.seq.width, win.model.seq.height) != (192, 108)  # o formato só muda quando um clipe entra
    win.place_at_cursor(win.bin.selected_paths(), insert=False)
    pump()
    vids = sorted((c for c in win.model.seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    assert [c.src for c in vids] == [a, b] and vids[1].start == vids[0].end
    assert (win.model.seq.width, win.model.seq.height) == (160, 90)  # o primeiro que entrou define o formato


def test_dropping_on_the_timeline_still_inserts_where_the_mouse_is(win, tmp_path):
    a = tone_video(tmp_path, "c.mp4", "160x90", 24, 440)
    fresh(win)
    end = win.drop_on_timeline([a], 12, tl.VIDEO, 0)
    vids = [c for c in win.model.seq.clips if c.kind == tl.VIDEO]
    assert len(vids) == 1 and vids[0].start == 12 and end == vids[0].end
