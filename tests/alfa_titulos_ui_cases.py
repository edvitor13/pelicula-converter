"""Casos da interface da 1.5 (frente alfa-títulos): sequências de imagens, fundo transparente, geradores e títulos.

Rodados por test_alfa_titulos_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt
precisam de uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Os casos da janela
principal precisam de OpenGL 3.3: sem ele, pulam.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from helpers import write_png  # noqa: E402
from pelicula import media  # noqa: E402
from pelicula import timeline as tl  # noqa: E402


def pump(cond, timeout=20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def frames_dir(n=6, first=1, prefix="cena_") -> Path:
    d = Path(tempfile.mkdtemp(prefix="pelicula_seq_ui_"))
    for k in range(first, first + n):
        img = np.zeros((36, 64, 3), np.uint8)
        img[:] = (20 * k, 100, 50)
        write_png(d / f"{prefix}{k:04d}.png", img)
    return d


@pytest.fixture(scope="module")
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    st = prefs.settings()
    st.setValue("auto_update", "false")
    st.setValue("language", "pt_BR")
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


@pytest.fixture
def answer(monkeypatch):
    """Responde a pergunta das imagens numeradas sem abrir a janela: `answer.set(escolha, fps)`."""
    from pelicula.ui import imageseq_dialog
    seen = []

    class Answer:
        value = (imageseq_dialog.SEQUENCE, "25/1")

        def set(self, choice, fps="25/1"):
            self.value = None if choice is None else (choice, fps)

    a = Answer()

    def ask(parent, found, fps_default="24/1", single=True):
        seen.append((found, fps_default, single))
        return a.value

    monkeypatch.setattr(imageseq_dialog, "ask", ask)
    a.seen = seen
    return a


# ------------------------------------------------------------------ sequências de imagens
def test_sequence_dialog_shows_the_gaps():
    from pelicula.ui.imageseq_dialog import ImageSequenceDialog
    d = frames_dir(8)
    os.remove(d / "cena_0004.png")
    found = media.find_sequence(str(d / "cena_0002.png"))
    dlg = ImageSequenceDialog(None, found, "30000/1001")
    assert not dlg.warn.isHidden() and "4" in dlg.warn.text()
    assert dlg.fps_str() == "30000/1001" and dlg.btn_image.text() == "Só esta imagem"
    dlg.btn_seq.click()
    assert dlg.choice == "sequencia"
    full = media.find_sequence(str(frames_dir(3)))
    assert ImageSequenceDialog(None, full, "24/1", single=False).warn.isHidden()


def test_import_numbered_images_as_a_sequence(win, answer):
    from pelicula.ui import imageseq_dialog
    win.new_project()
    win.set_mode("edicao")
    d = frames_dir(6)
    files = [str(d / f"cena_{k:04d}.png") for k in (1, 2, 3)]
    win.import_paths(files)  # três quadros da mesma sequência: uma pergunta só
    assert len(answer.seen) == 1 and answer.seen[0][2] is True
    pattern = answer.seen[0][0].pattern
    src = win.model.seq.sources[pattern]
    assert src.is_sequence and src.frames == 6 and src.fps_str == "25/1"
    assert pattern in win._sources and sum(1 for c in win.model.seq.clips if c.src == pattern) == 1
    # como imagens separadas: cada arquivo vira uma imagem parada
    answer.set(imageseq_dialog.IMAGE)
    other = frames_dir(4, prefix="outra_")
    win.import_paths([str(other / "outra_0002.png")])
    assert str(other / "outra_0002.png") in win.model.seq.sources
    # cancelar não importa nada
    answer.set(None)
    n = len(win.model.seq.clips)
    win.import_paths([str(frames_dir(3, prefix="nada_"))])
    assert len(win.model.seq.clips) == n


def test_film_mode_opens_a_sequence_through_the_montage(win, answer):
    from pelicula.ui import imageseq_dialog
    answer.set(imageseq_dialog.SEQUENCE, "24/1")
    win.set_mode("pelicula")
    d = frames_dir(5)
    win.cur = None
    win.handle_files([str(d)])  # uma pasta de quadros numerados
    assert pump(lambda: win.cur is not None), "o quadro não carregou"
    assert win.file_info is not None and win.file_info.is_sequence and win.info.frames == 5
    assert win.src_seq is not None  # pela montagem (a velocidade fica na fonte)
    assert win._seq_json() is not None and "sequencia_imagens" in win.model.seq.features()
    assert "cena_[0001-0005].png" in win._media_label
