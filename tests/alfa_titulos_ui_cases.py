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


# ------------------------------------------------------------------ fundo transparente
def test_sequence_dialog_has_the_transparent_background():
    from pelicula.ui.sequence_dialog import SequenceDialog
    seq = tl.Sequence(width=64, height=36)
    dlg = SequenceDialog(None, seq)
    assert dlg.transp.text() == "Fundo transparente" and not dlg.transparent()
    dlg.transp.setChecked(True)
    assert dlg.transparent()
    seq.transparent = True
    assert SequenceDialog(None, seq).transparent()


def _export_dialog(seq):
    from pelicula.ui.export_dialog import ExportDialog
    info = media.MediaInfo(path=os.path.join(tempfile.gettempdir(), "montagem.mov"), width=64, height=36, fps=24.0,
                           fps_str="24/1", frames=48, duration=2.0, pix_fmt="rgb48le", bit_depth=16, codec="rawvideo",
                           profile="", bitrate=0, color_space="bt709", color_range="pc", color_transfer="bt709",
                           color_primaries="bt709", has_audio=False, audio_codec="", container="mov", is_image=False)
    dlg = ExportDialog(None, info, {}, "Teste", None, last_dir=tempfile.gettempdir(), sequence=seq)
    dlg._est_timer.stop()
    dlg._preview_timer.stop()
    return dlg


def _pick_codec(dlg, codec):
    i = dlg.codec.findData(codec)
    assert i >= 0, codec
    dlg.codec.setCurrentIndex(i)


def test_export_dialog_keeps_alpha_only_where_it_can():
    if not media.configure():
        pytest.skip("ffmpeg indisponível")
    seq = tl.Sequence(width=64, height=36, transparent=True)
    dlg = _export_dialog(seq)
    _pick_codec(dlg, "prores")
    assert dlg.alpha_box.isEnabled() and dlg.alpha_box.isChecked() and dlg.keeps_alpha()
    assert all(not media.pix_has_alpha(dlg.pix.itemData(i)) for i in range(dlg.pix.count()))
    s = dlg.settings()
    assert s.pix == "yuva444p10le" and s.profile in ("4", "5")
    assert "com transparência" in dlg.summary.text()
    if dlg.codec.findData("png_seq") >= 0:
        _pick_codec(dlg, "png_seq")
        assert dlg.settings().pix in ("rgba64be", "rgba")
    _pick_codec(dlg, "x264")
    assert not dlg.alpha_box.isEnabled() and not dlg.keeps_alpha()
    assert "ProRes 4444" in dlg.alpha_note.text() and dlg.settings().pix == "yuv420p"
    dlg.alpha_box.setChecked(False)
    _pick_codec(dlg, "prores")
    assert dlg.settings().pix == "yuv422p10le"  # desmarcado: o ProRes de sempre
    opaque = _export_dialog(tl.Sequence(width=64, height=36))
    _pick_codec(opaque, "prores")
    assert not opaque.alpha_box.isEnabled() and "Fundo transparente" in opaque.alpha_note.text()
    assert not media.pix_has_alpha(opaque.settings().pix)


def test_preview_shows_the_transparency_over_a_checkerboard(win):
    from pelicula.ui import alphaview
    win.new_project()
    win.set_mode("edicao")
    d = Path(tempfile.mkdtemp(prefix="pelicula_alfa_ui_"))
    write_png(d / "quadrado.png", np.full((36, 36, 3), 200, np.uint8))
    win.import_paths([str(d / "quadrado.png")])
    assert pump(lambda: bool(win.model.seq.clips))
    seq = win.model.seq
    win.model.set_settings(64, 36, seq.fps_str, (1.0, 0.0, 0.0), transparent=True)
    assert win.model.seq.transparent and "fundo_transparente" in win.model.seq.features()
    win.cur = None
    win.request_frame(0)
    assert pump(lambda: win.cur is not None and win.cur.shape[2] == 4), "a prévia não ficou RGBA"
    APP.processEvents()
    win.render_now()
    img = win.viewer.proc
    assert img is not None and img.width() == 64
    left = img.pixelColor(2, 18)  # barra do "Mostrar inteiro": transparente → xadrez, não o vermelho do fundo
    assert (left.red(), left.green(), left.blue()) in ((alphaview.LIGHT,) * 3, (alphaview.DARK,) * 3)
    mid = img.pixelColor(32, 18)
    assert mid.red() == mid.green() == mid.blue() and mid.red() > 150
    win.model.undo()  # desfazer volta ao fundo opaco
    assert not win.model.seq.transparent
