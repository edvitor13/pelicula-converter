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


# ------------------------------------------------------------------ geradores ("Novo" da Mídia e inspetor)
def _menu_action(win, item_id):
    menu = win.bin.btn_new.menu()
    assert menu is not None and not win.bin.btn_new.isHidden()
    act = next((a for a in menu.actions() if a.objectName() == f"novo_{item_id}"), None)
    assert act is not None, [a.objectName() for a in menu.actions()]
    return act


def test_new_menu_creates_generators_at_the_playhead(win):
    win.new_project()
    win.set_mode("edicao")
    labels = [a.text() for a in win.bin.btn_new.menu().actions()]
    assert labels[:3] == ["Cor sólida", "Degradê", "Ponta com contagem"]
    _menu_action(win, "contagem").trigger()
    seq = win.model.seq
    leader = next(c for c in seq.clips if seq.sources[c.src].data.get("gerador") == "contagem")
    assert leader.start == 0 and leader.track == 0 and leader.dur == 8 * 24
    assert win.model.selection == [leader.id] and leader.src in win.bin.paths()
    win.seek(48)
    _menu_action(win, "cor").trigger()  # no cursor, na faixa livre de cima (a V1 tem a ponta)
    color = next(c for c in win.model.seq.clips if win.model.seq.sources[c.src].kind == "cor")
    assert color.start == 48 and color.track == 1 and color.dur == 5 * 24
    win.model.undo()
    assert not any(win.model.seq.sources[c.src].kind == "cor" for c in win.model.seq.clips)


def test_generator_fields_in_the_inspector_with_undo(win):
    from pelicula import generators
    win.new_project()
    win.set_mode("edicao")
    _menu_action(win, "degrade").trigger()
    ed = win.gen_editor
    assert not ed.isHidden() and ed.gen is generators.GENERATORS["degrade"]
    store, card = ed._pages["degrade"]
    rows = {r.param.key: r for r in card.rows}
    assert rows["cor3"].isHidden() and not rows["angulo"].isHidden()
    path = ed.path
    before = dict(win.model.seq.sources[path].data)
    store.set("cores", "3")
    assert win.model.seq.sources[path].data["cores"] == "3" and not rows["cor3"].isHidden()
    store.set("cor1", [1.0, 0.0, 0.0])
    assert win.model.seq.sources[path].data["cor1"] == "#ff0000"
    assert win.model.seq.sources[path].data["nome"] == before["nome"]  # o resto fica
    win.model.undo()  # arrastar agrupa: um passo desfaz tudo
    assert win.model.seq.sources[path].data == before
    assert store.get("cores") == "2"
    # faixa travada: o gerador não muda
    clip = next(c for c in win.model.seq.clips if c.src == path)
    win.model.seq.track(tl.VIDEO, clip.track).locked = True
    assert not win.model.set_source_data(path, {**before, "angulo": 10})
    win.model.seq.track(tl.VIDEO, clip.track).locked = False
    # sem clipe escolhido: o painel some
    win.model.selection = []
    win.model.selectionChanged.emit()
    assert ed.isHidden()


def test_bin_follows_the_generator_name_and_thumbnail(win):
    win.new_project()
    win.set_mode("edicao")
    _menu_action(win, "cor").trigger()
    path = win.gen_editor.path
    data = dict(win.model.seq.sources[path].data, nome="Fundo azul", cor="#0000ff")
    assert win.model.set_source_data(path, data)
    assert pump(lambda: "Fundo azul" in win.bin._item(path).text())


# ------------------------------------------------------------------ títulos ("Novo ▸ Título…" e o editor)
def test_new_title_from_the_menu(win):
    win.new_project()
    win.set_mode("edicao")
    labels = [a.text() for a in win.bin.btn_new.menu().actions()]
    assert labels == ["Cor sólida", "Degradê", "Ponta com contagem", "Título…"]
    _menu_action(win, "cor").trigger()
    win.seek(24)
    _menu_action(win, "titulo").trigger()  # por cima da cor (V2), no cursor
    seq = win.model.seq
    clip = next(c for c in seq.clips if seq.sources[c.src].kind == "texto")
    assert clip.start == 24 and clip.track == 1 and clip.dur == 5 * 24
    ed = win.title_editor
    APP.processEvents()
    assert not ed.isHidden() and win.gen_editor.isHidden() and ed.path == clip.src
    assert ed.text.toPlainText() == "Título" and ed.text.textCursor().hasSelection()
    assert clip.src in win.bin.paths()


def test_title_editor_text_style_preset_and_undo(win):
    win.new_project()
    win.set_mode("edicao")
    _menu_action(win, "titulo").trigger()
    ed = win.title_editor
    path = ed.path
    before = dict(win.model.seq.sources[path].data)
    ed.text.setPlainText("Abertura\nsegunda linha")
    assert pump(lambda: win.model.seq.sources[path].data["texto"] == "Abertura\nsegunda linha")
    assert win.model.seq.sources[path].data["nome"] == "Abertura"
    assert pump(lambda: "Abertura" in win.bin._item(path).text())  # a Mídia acompanha a primeira linha
    ed.store.set("tamanho", 90.0)
    ed.store.set("cor", [1.0, 0.0, 0.0])
    style = win.model.seq.sources[path].data["estilo"]
    assert style["tamanho"] == 90.0 and style["cor"] == "#ff0000" and style["fonte"] == "bebas"
    ed.store.set("entrada", "subir")
    assert win.model.seq.sources[path].data["entrada"] == "subir"
    win.model.undo()  # digitar e arrastar agrupam: volta ao título novo
    assert pump(lambda: win.model.seq.sources[path].data == before)
    assert ed.text.toPlainText() == "Título" and ed.store.get("tamanho") == 170.0
    # estilo pronto: troca letra, posição e animações, o texto fica
    ed.text.setPlainText("Ana Lima")
    i = ed.preset.findData("terco_inferior")
    ed.preset.setCurrentIndex(i)
    ed.preset.activated.emit(i)
    data = win.model.seq.sources[path].data
    assert data["texto"] == "Ana Lima" and data["estilo_pronto"] == "terco_inferior" and data["pos_x"] == 0.07
    assert ed.store.get("alinhamento") == "esquerda" and ed.preset.currentIndex() == 0
    win.model.undo()
    assert win.model.seq.sources[path].data["estilo_pronto"] == "titulo_grande"


def test_title_warns_about_characters_the_font_lacks(win):
    win.new_project()
    win.set_mode("edicao")
    _menu_action(win, "titulo").trigger()
    ed = win.title_editor
    assert ed.warn.isHidden()
    ed.text.setPlainText("Tóquio 東京")
    assert pump(lambda: not ed.warn.isHidden())
    assert "東" in ed.warn.text() and "Bebas Neue" in ed.warn.text()
    ed.store.set("fonte", "atkinson")
    ed.text.setPlainText("Tóquio")
    assert pump(lambda: ed.warn.isHidden())


def test_about_lists_the_font_licenses(win, monkeypatch):
    from pelicula.ui import main_window
    seen = []
    monkeypatch.setattr(main_window.QMessageBox, "about", lambda parent, title, text: seen.append(text))
    win.about()
    assert seen and "SIL Open Font License 1.1" in seen[0] and "Atkinson Hyperlegible" in seen[0]


# ------------------------------------------------------------------ módulo "Títulos e geradores"
def test_module_off_hides_the_tools_but_not_the_picture(win):
    from pelicula import modules, sequence
    win.new_project()
    win.set_mode("edicao")
    _menu_action(win, "titulo").trigger()
    seq = win.model.seq
    clip = next(c for c in seq.clips if seq.sources[c.src].kind == "texto")
    before = sequence.grab(seq, clip.start + 30, 96, 54, 8).layers[0].image
    assert not win.title_editor.isHidden()
    try:
        modules.set_enabled(win.settings, "titulos_geradores", False)
        win.settings_changed.emit("modulos")
        APP.processEvents()
        assert win.bin.btn_new.isHidden() and win.title_editor.isHidden() and win.gen_editor.isHidden()
        win.model.selection = [clip.id]
        win.model.selectionChanged.emit()
        assert win.title_editor.isHidden()  # o clipe escolhido não traz o editor de volta
        assert "titulos_geradores" in modules.used_by(None, seq)  # o aviso oferece religar
        after = sequence.grab(win.model.seq, clip.start + 30, 96, 54, 8).layers[0].image
        assert np.array_equal(before, after)  # a imagem não muda
    finally:
        modules.set_enabled(win.settings, "titulos_geradores", True)
        win.settings_changed.emit("modulos")
        APP.processEvents()
    assert not win.bin.btn_new.isHidden() and not win.title_editor.isHidden()
