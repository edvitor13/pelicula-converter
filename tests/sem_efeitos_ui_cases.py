"""Casos da janela para "Desligar todos os efeitos" (1.7, `ui/sem_efeitos_ui.py`) e os seletores da barra.

Rodados por test_sem_efeitos_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. A janela precisa de OpenGL 3.3: sem ele,
os casos pulam.
"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QIcon, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import export, media, presets, project  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.export import ExportSettings  # noqa: E402
from pelicula.ui import main_window, theme  # noqa: E402

KEYS = {"grao_forca": [[0.0, 0.5, "linear"], [20.0, 2.0, "linear"]]}


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


@pytest.fixture(autouse=True)
def effects_on(win):
    """Todo caso começa e termina com os efeitos ligados."""
    win.btn_no_effects.setChecked(False)
    yield
    win.stop_play()
    win.btn_no_effects.setChecked(False)


def _open(win, path) -> None:
    win.set_mode("pelicula")
    win.cur = None
    win.load_media(path)
    assert pump(lambda: win.cur is not None), "o quadro não carregou"


def _look(win) -> None:
    win.apply_preset("vision3_500t")
    win.store.set_all(dict(win.store.values, grao_forca=1.4), keys=KEYS)
    win.store.commit()


def _montage(win, path, mode="edicao", **picture) -> None:
    """Uma montagem com corte, enquadramento e os ajustes de imagem pedidos no primeiro clipe."""
    src = media.probe_source(path)
    seq = tl.Sequence.for_source(src)
    seq.split(10)
    a, b = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    seq.set_values(a.id, {**a.values, "escala": 0.8, "exposicao": 0.8, "saturacao": -0.5, "nitidez": 0.8, **picture})
    seq.set_values(b.id, {**b.values, "rotacao": 5.0})
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


def _switch(win, off: bool, read_again: bool = False) -> None:
    """Liga ou desliga; `read_again`: espera o quadro lido de novo."""
    old = win.cur
    win.btn_no_effects.setChecked(off)
    if read_again:
        assert pump(lambda: win.cur is not old), "o quadro não foi lido de novo"
    APP.processEvents()


def _shown(win):
    return win.viewer.proc.copy()


def _state(win) -> tuple:
    return (json.dumps(win.store.values, sort_keys=True), json.dumps(win.store.keys_json(), sort_keys=True),
            json.dumps(win.model.seq.to_json(), sort_keys=True), win.store.can_undo(), win.store.can_redo(),
            win.model.can_undo(), win.model.can_redo(), win.is_dirty(), win.windowTitle())


def _key(win, key, mod=Qt.KeyboardModifier.NoModifier) -> None:
    win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mod))


# ------------------------------------------------------------------ o botão
def test_button_label_and_shortcut_in_both_modes(win, sample_video, monkeypatch):
    _open(win, sample_video)
    for mode, normal in (("pelicula", "PELÍCULA"), ("edicao", "EDIÇÃO")):
        win.set_mode(mode)
        APP.processEvents()
        assert win.btn_no_effects.isVisibleTo(win) and win.btn_no_effects.isEnabled()
        assert win.btn_no_effects.isCheckable() and "Shift+D" in win.btn_no_effects.toolTip()
        assert win.viewer.label_proc == normal and not win.no_effects
        _key(win, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
        assert win.btn_no_effects.isChecked() and win.no_effects
        assert win.viewer.label_proc == "SEM EFEITOS"
        win.set_mode("pelicula" if mode == "edicao" else "edicao")   # trocar de modo não religa
        assert win.no_effects and win.viewer.label_proc == "SEM EFEITOS"
        win.set_mode(mode)
        _key(win, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
        assert not win.btn_no_effects.isChecked() and not win.no_effects
        assert win.viewer.label_proc == normal
        _key(win, Qt.Key.Key_D)                                                  # só o D não faz nada
        assert not win.no_effects
    win.set_mode("pelicula")
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda _w, _t, text: seen.append(text))
    win.show_shortcuts()
    assert "Shift+D" in seen[0]


def test_disabled_with_nothing_open(win):
    win.new_project()
    assert not win.btn_no_effects.isEnabled()
    _key(win, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
    assert not win.no_effects


# ------------------------------------------------------------------ nada muda
def test_off_then_on_is_exactly_as_before(win, sample_video):
    for mode in ("edicao", "pelicula"):
        _open(win, sample_video)
        _look(win)
        _montage(win, sample_video, mode)
        win.render_now()
        before, state = _shown(win), _state(win)
        _switch(win, True)
        assert _shown(win) != before, mode
        assert win.frame_recipe().no_effects and not win.frame_recipe().keys
        assert win.frame_recipe(16, full=True).no_effects
        assert _state(win) == state, mode
        _switch(win, False)
        assert _shown(win) == before, mode
        assert _state(win) == state, mode


def test_file_in_film_mode_shows_the_original_preset(win, sample_video):
    _open(win, sample_video)
    _look(win)
    _switch(win, True)
    off = _shown(win)
    still = win.still_frame(3)
    _switch(win, False)
    win.apply_preset("original")
    win.render_now()
    assert _shown(win) == off
    np.testing.assert_array_equal(still, win.still_frame(3))


def test_slider_moved_while_off_shows_when_back_on(win, sample_video):
    _open(win, sample_video)
    _look(win)
    before = _shown(win)
    _switch(win, True)
    off = _shown(win)
    win.store.set("exposicao", 1.5)
    win.store.commit()
    win.render_now()
    assert _shown(win) == off                     # guardado, sem aparecer
    assert win.store.get("exposicao") == 1.5
    _switch(win, False)
    assert _shown(win) not in (before, off)       # o valor novo é o que está valendo
    win.apply_preset("vision3_500t")


def test_log_file_and_clip_profile_are_read_again(win, sample_video):
    if not media.has_zscale():
        pytest.skip("ffmpeg sem zscale")
    _open(win, sample_video)
    win.store.set("entrada", "slog3")
    win.store.commit()
    assert pump(lambda: win.cur is not None and win.cur.dtype == np.float32)
    _switch(win, True, read_again=True)
    assert win.cur.dtype == np.uint8
    _switch(win, False, read_again=True)
    assert win.cur.dtype == np.float32
    win.store.set("entrada", "rec709")
    win.store.commit()
    # perfil de câmera de um clipe: a leitura volta ao de sempre (sem float32)
    _montage(win, sample_video, camera_entrada="slog3")
    assert any(li.image.dtype == np.float32 for li in win.cur_layers.layers)
    _switch(win, True, read_again=True)
    assert all(li.image.dtype == np.uint8 for li in win.cur_layers.layers)
    _switch(win, False, read_again=True)
    assert any(li.image.dtype == np.float32 for li in win.cur_layers.layers)


def test_shutter_is_not_read_while_off(win, sample_video):
    _open(win, sample_video)
    _montage(win, sample_video, "pelicula")
    win.store.set_all(dict(win.store.values, obturador_on=True, obturador_angulo="180"))
    win.store.commit()
    assert win._shutter() == 180.0
    assert pump(lambda: win.cur_layers is not None and win._shutter_read == 180.0)
    old = win.cur
    _switch(win, True)
    assert win._shutter() == 0.0 and win.frame_recipe().shutter == 0.0
    assert pump(lambda: win.cur is not old and win._shutter_read == 0.0)
    win.store.set_all(dict(win.store.values, obturador_on=False))
    win.store.commit()


def test_playing_reader_follows(win, sample_video, monkeypatch):
    _open(win, sample_video)
    win.store.set("entrada", "slog3")
    win.store.commit()
    seen = []
    monkeypatch.setattr(win.player, "start", lambda *a, **k: seen.append(a))
    monkeypatch.setattr(win.player, "stop", lambda: None)
    win.start_play()
    assert seen[-1][7] == "slog3" and seen[-1][9] is False
    if media.float_input(win.info, "slog3"):
        n = len(seen)
        _switch(win, True)
        assert win.playing and len(seen) == n + 1
        assert seen[-1][7] == "rec709" and seen[-1][9] is True
    win.stop_play()
    win.store.set("entrada", "rec709")
    win.store.commit()


def test_preset_thumbnails_keep_their_looks(win, sample_video, monkeypatch):
    _open(win, sample_video)
    _switch(win, True)
    got = {}
    monkeypatch.setattr(win.looks, "set_images", lambda images: got.update(images))
    win._render_thumbs()
    assert got["vision3_500t"] != got["original"]


# ------------------------------------------------------------------ abrir e salvar
def test_opening_a_file_or_project_turns_effects_back_on(win, sample_video, tmp_path):
    _open(win, sample_video)
    _switch(win, True)
    _open(win, sample_video)
    assert not win.no_effects and not win.btn_no_effects.isChecked() and win.viewer.label_proc == "PELÍCULA"

    plc = str(tmp_path / "um.plc")
    win._write_project(plc)
    _switch(win, True)
    win.open_project(plc)
    assert not win.no_effects and win.viewer.label_proc == "PELÍCULA"

    _montage(win, sample_video)
    plc = str(tmp_path / "montagem.plc")
    win._write_project(plc)
    _switch(win, True)
    win.open_project(plc)
    assert not win.no_effects and win.viewer.label_proc == "EDIÇÃO"

    _switch(win, True)
    win.new_project()
    assert not win.no_effects


def test_project_saved_while_off_is_the_same(win, sample_video, tmp_path):
    for mode in ("edicao", "pelicula"):
        _open(win, sample_video)
        _look(win)
        _montage(win, sample_video, mode)
        on, off = str(tmp_path / f"ligado_{mode}.plc"), str(tmp_path / f"desligado_{mode}.plc")
        win._write_project(on)
        _switch(win, True)
        win._write_project(off)
        assert win.no_effects                     # salvar não religa
        _switch(win, False)
        with open(on, encoding="utf-8") as fa, open(off, encoding="utf-8") as fb:
            a, b = json.load(fa), json.load(fb)
        a.pop("nome"), b.pop("nome")              # o nome do arquivo
        assert a["miniatura_jpeg"] and a == b, mode   # a miniatura também: é a do quadro com os efeitos
        assert "no_effects" not in json.dumps(a)
        assert a["valores"]["grao_forca"] == 1.4
        assert project.load(off).values == win.store.values


# ------------------------------------------------------------------ exportar
class _Dialog:
    """A janela de exportação sem janela: guarda os argumentos e diz não (ou entrega um trabalho)."""
    calls: list = []
    answer = False

    def __init__(self, *a, **k):
        _Dialog.calls.append((a, k))
        self.quality = type("Q", (), {"currentData": staticmethod(lambda: "mp4")})
        self.args, self.kw = a, k

    def exec(self):
        return _Dialog.answer

    def platform_id(self):
        return ""

    def perf_dict(self):
        return {}

    def job(self):
        info, values = self.args[1], self.args[2]
        return export.ExportJob(info=info, values=dict(values), out_path="saida.mp4",
                                settings=ExportSettings(no_effects=self.kw["no_effects"]),
                                look_keys=self.kw["look_keys"])

    def jobs(self):   # 1.7: a janela principal pede a lista (uma por sequência marcada)
        return [self.job()]


def _answer(monkeypatch, text: str | None) -> list:
    """A pergunta responde com o botão de texto `text`; devolve as perguntas feitas. None: nenhuma pode aparecer."""
    asked = []

    def exec_(box):
        asked.append((box.text(), [b.text() for b in box.buttons()]))
        assert text is not None, "não devia perguntar"
        next(b for b in box.buttons() if b.text() == text).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return asked


def test_export_question_three_answers(win, sample_video, monkeypatch):
    _open(win, sample_video)
    _look(win)
    monkeypatch.setattr(main_window, "ExportDialog", _Dialog)
    _Dialog.answer = False
    original = presets.builtin_values("original")

    # ligado: nem pergunta, e vai o look de verdade
    _Dialog.calls.clear()
    asked = _answer(monkeypatch, None)
    win.new_export()
    assert not asked and _Dialog.calls[-1][1]["no_effects"] is False
    assert _Dialog.calls[-1][0][2]["grao_forca"] == 1.4 and _Dialog.calls[-1][1]["look_keys"]

    # Cancelar: nada abre e continua desligado
    _switch(win, True)
    _Dialog.calls.clear()
    asked = _answer(monkeypatch, "Cancelar")
    win.new_export()
    assert asked[0][0] == ("Os efeitos estão desligados. O vídeo vai sair sem o look e sem os ajustes de imagem "
                           "dos clipes.")
    assert set(asked[0][1]) == {"Exportar sem efeitos", "Religar e exportar", "Cancelar"}
    assert not _Dialog.calls and win.no_effects

    # Exportar sem efeitos
    _answer(monkeypatch, "Exportar sem efeitos")
    win.new_export()
    (args, kw), = _Dialog.calls
    assert kw["no_effects"] is True and args[2] == original and args[3] == "Sem efeitos" and kw["look_keys"] == {}
    assert win.no_effects

    # Religar e exportar
    _Dialog.calls.clear()
    _answer(monkeypatch, "Religar e exportar")
    win.new_export()
    (args, kw), = _Dialog.calls
    assert kw["no_effects"] is False and args[2]["grao_forca"] == 1.4 and kw["look_keys"]
    assert not win.no_effects and not win.btn_no_effects.isChecked() and win.viewer.label_proc == "PELÍCULA"


def test_real_dialog_carries_the_flag(sample_video):
    from pelicula.ui.export_dialog import ExportDialog
    info = media.probe(sample_video)
    for flag in (True, False):
        dlg = ExportDialog(None, info, presets.builtin_values("original"), "Sem efeitos", None, last_dir=os.getcwd(),
                           last_quality="mp4", no_effects=flag)
        dlg._est_timer.stop()
        dlg._preview_timer.stop()
        assert dlg.settings().no_effects is flag
        assert dlg.job().settings.no_effects is flag
        dlg.done(0)
    plain = ExportDialog(None, info, {}, "Teste", None, last_dir=os.getcwd(), last_quality="mp4")
    plain._est_timer.stop()
    plain._preview_timer.stop()
    assert plain.settings().no_effects is False
    plain.done(0)


def test_job_keeps_the_flag_after_turning_on(win, sample_video, monkeypatch):
    _open(win, sample_video)
    _look(win)
    monkeypatch.setattr(main_window, "ExportDialog", _Dialog)
    _Dialog.answer = True
    added = []
    monkeypatch.setattr(win.queue, "add", added.append)
    monkeypatch.setattr(win, "show_queue", lambda: None)
    monkeypatch.setattr(win, "_recovery_point", lambda: None)
    _switch(win, True)
    _answer(monkeypatch, "Exportar sem efeitos")
    win.new_export()
    job, = added
    assert job.settings.no_effects is True
    _switch(win, False)
    assert job.settings.no_effects is True
    assert export.ExportJob.from_dict(job.to_dict()).settings.no_effects is True
    r = export.frame_pipeline(job.info, job.values, job.settings, keys=job.look_keys)
    assert r.no_effects and r.values == presets.builtin_values("original")
    _Dialog.answer = False


def test_export_frames_follow_the_preview(win, sample_video):
    _open(win, sample_video)
    _look(win)
    _montage(win, sample_video, exposicao=1.0)
    _switch(win, True)
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False, no_effects=True)
    seq = win.src_seq.copy()
    for n in (3, 12):
        np.testing.assert_array_equal(win.still_frame(n),
                                      export.preview_frame(win.engine, win.info, win._export_look()[0], s, n, seq=seq,
                                                           depth=16, keys=win._export_keys()))


# ------------------------------------------------------------------ modo × comparação
def _pixels_of(icon, state) -> set:
    img = icon.pixmap(16, 16, QIcon.Mode.Normal, state).toImage()
    return {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255}


def test_labels_of_the_two_selectors(win):
    labels = {k: b.text() for k, b in win.compare.buttons.items()}
    assert labels == {"proc": "Resultado", "split": "Dividido", "side": "Lado a lado", "orig": "Original"}
    assert win.compare.buttons["proc"].toolTip() == "Só o resultado"
    assert {k: b.text() for k, b in win.mode_switch.buttons.items()} == {"pelicula": "Película", "edicao": "Edição"}


def test_mode_switch_icons_follow_the_text(win):
    for b in win.mode_switch.buttons.values():
        assert not b.icon().isNull()
        assert _pixels_of(b.icon(), QIcon.State.Off) == {theme.MUTED}
        assert _pixels_of(b.icon(), QIcon.State.On) == {"#1b1205"}
    # com largura, ícone e texto; janela estreita: só o ícone, como os outros botões do topo
    bar = win.top_bar
    for level, style in ((0, Qt.ToolButtonStyle.ToolButtonTextBesideIcon), (1, Qt.ToolButtonStyle.ToolButtonIconOnly)):
        bar._apply(level)
        assert {b.toolButtonStyle() for b in win.mode_switch.buttons.values()} == {style}
    bar._adapt(bar.width())
    for b in win.compare.buttons.values():
        assert b.icon().isNull()


def test_object_names_and_other_selectors_keep_their_look(win):
    assert {b.objectName() for b in win.mode_switch.buttons.values()} == {"SegMode"}
    assert {b.objectName() for b in win.compare.buttons.values()} == {"SegQuiet"}
    assert {b.objectName() for b in win.inspector.kind_seg.buttons.values()} == {"Seg"}
    assert all(b.icon().isNull() for b in win.inspector.kind_seg.buttons.values())
    # sem âmbar na comparação: só o modo e os demais seletores usam a pílula
    qss = theme.stylesheet()
    quiet = next(line for line in qss.splitlines() if line.startswith("QToolButton#SegQuiet:checked"))
    assert theme.ACCENT not in quiet and theme.PANEL3 in quiet and theme.TEXT in quiet
    mode = next(line for line in qss.splitlines() if line.startswith("QToolButton#SegMode:checked"))
    assert theme.ACCENT in mode and "#1b1205" in mode
    seg = next(line for line in qss.splitlines() if line.startswith("QToolButton#Seg:checked"))
    assert theme.ACCENT in seg


def test_compare_shortcut_and_keys_still_work(win, sample_video):
    _open(win, sample_video)
    order = ["proc", "split", "side", "orig"]
    for key in order:
        win.compare.set_current(key)
        win._set_compare(key)
        assert win.viewer.mode == key and win.compare.buttons[key].isChecked()
    win.compare.buttons["proc"].click()
    assert win.viewer.mode == "proc"
    for i in range(1, 5):
        _key(win, Qt.Key.Key_C)
        assert win.viewer.mode == order[i % 4] and win.compare.buttons[order[i % 4]].isChecked()
    win.mode_switch.buttons["edicao"].click()
    assert win.mode == "edicao" and win.mode_switch.buttons["edicao"].isChecked()
    win.mode_switch.buttons["pelicula"].click()
    assert win.mode == "pelicula"
    win.compare.set_current("split")
    win._set_compare("split")
