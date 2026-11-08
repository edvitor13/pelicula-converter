"""Casos da interface da estabilização e do rastreio da 1.9 (F3, ARQUITETURA §51.4): os cartões "Estabilizar" e
"Rastrear ponto" seguem o módulo "movimento", o Analisar grava a análise na fonte e liga a estabilização, o rastreio
vira um passo do desfazer e o "Aplicar a…" assa as chaves num passo só; a marca do ponto na prévia.

Rodados por test_movimento_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado
sozinho.
"""

from __future__ import annotations

import os
import subprocess
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import movimento_sinteticos as ms  # noqa: E402
from pelicula import estabilizacao, modules, rastreio, vfx, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402


def pump(timeout: float = 0.1) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        time.sleep(0.01)


def wait_job(ui, timeout: float = 90.0) -> None:
    t0 = time.time()
    while ui.job is not None and time.time() - t0 < timeout:
        APP.processEvents()
        time.sleep(0.02)
    assert ui.job is None, "o trabalho não terminou"
    pump()


@pytest.fixture(scope="module")
def win():
    prefs.settings().setValue("auto_update", "false")
    try:
        w = mw.MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1500, 900)
    w.show()
    APP.processEvents()
    yield w
    w._saved_state = w._state()
    w.close()


@pytest.fixture(scope="module")
def video(ffmpeg_ok, tmp_path_factory):
    """Um vídeo de 12 quadros (320 × 180) com textura tremendo."""
    mot = np.zeros((12, 4))
    mot[1:, 0] = [9, -7, 5, -8, 6, -4, 8, -6, 7, -5, 4]
    mot[1:, 1] = [-4, 5, -3, 4, -5, 3, -4, 5, -3, 4, -2]
    frames = ms.shaken(mot, 320, 180, seed=5, margin=60)
    raw = (np.clip(np.stack(frames), 0, 1) * 255).round().astype(np.uint8)
    out = tmp_path_factory.mktemp("movimento_ui") / "tremido.mkv"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "320x180", "-r", "24",
                    "-i", "-", "-c:v", "ffv1", str(out)], input=raw.tobytes(), check=True, capture_output=True)
    return str(out)


def set_module(win, mid: str, on: bool) -> None:
    modules.set_enabled(win.settings, mid, on)
    win.apply_modules()
    pump()


def fresh(win, path: str) -> tl.Clip:
    """Projeto novo no modo Edição com o vídeo em V1, escolhido, e o cursor no quadro 4."""
    from pelicula import media
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    src = tl.Source.from_info(media.probe(path))
    c = seq.insert_media(src, with_audio=False)[0]
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    win.model.select([c.id])
    win.seek(4)
    pump()
    return win.model.seq.find(c.id)


def test_cards_follow_the_module(win):
    ui = win.vfx_ui.fronts["movimento_ui"]
    assert not modules.is_enabled(win.settings, "movimento")
    assert ui.card_estab.isHidden() and ui.card_track.isHidden()
    set_module(win, "movimento", True)
    assert not ui.card_estab.isHidden() and not ui.card_track.isHidden()
    assert win.vfx_ui.module_tools()["movimento"] == [ui.card_estab, ui.card_track]
    lay = ui.card_estab.parentWidget().layout()   # a ordem na tela: logo depois de Transformar
    assert lay.indexOf(ui.card_estab) == lay.indexOf(win.vfx_ui.card("transformar")) + 1
    assert lay.indexOf(ui.card_track) == lay.indexOf(ui.card_estab) + 1


def test_a_generated_clip_cannot_be_analyzed(win):
    set_module(win, "movimento", True)
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1")
    c = seq.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))[0]
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    win.model.select([c.id])
    pump()
    ui = win.vfx_ui.fronts["movimento_ui"]
    assert not ui.btn_analyze.isEnabled() and not ui.btn_track.isEnabled() and not ui.btn_apply.isEnabled()


def test_analyze_stores_the_analysis_and_turns_it_on(win, video):
    set_module(win, "movimento", True)
    c = fresh(win, video)
    ui = win.vfx_ui.fronts["movimento_ui"]
    assert ui.btn_analyze.isEnabled() and "sem análise" in ui.lbl_estab.text()
    ui.btn_analyze.click()
    assert ui.bar.isVisibleTo(win) or ui.job is None
    wait_job(ui)
    src = win.model.seq.sources[c.src]
    entry = estabilizacao.entry_of(src)
    assert entry is not None and entry["quadros"] == 12
    c = win.model.seq.find(c.id)
    assert c.values["estab_on"] is True and "Analisado" in ui.lbl_estab.text()
    assert win.is_dirty() and not ui.bar.isVisibleTo(win)
    win.model.undo()      # desfaz o "ligar"; a análise fica (fora do desfazer)
    pump()
    assert win.model.seq.find(c.id).values["estab_on"] is False
    assert estabilizacao.entry_of(win.model.seq.sources[c.src]) is not None


def test_track_apply_and_undo(win, video):
    set_module(win, "movimento", True)
    c = fresh(win, video)
    ui = win.vfx_ui.fronts["movimento_ui"]
    assert not ui.btn_apply.isEnabled() and not ui.btn_reapply.isEnabled()
    ui._picked(c.id, 0.5, 0.5)
    wait_job(ui)
    c = win.model.seq.find(c.id)
    tr = rastreio.track_of(c)
    assert tr is not None and tr.first == 0 and tr.last == 11 and tr.ref == 4, ui.lbl_track.text()
    assert "12 quadros" in ui.lbl_track.text() and ui.btn_apply.isEnabled()
    ui._fill_apply_menu()
    acts = {a.objectName(): a for a in ui.apply_menu.actions()}
    acts[f"rastreio_alvo_proprio_{c.id}"].trigger()
    pump()
    c = win.model.seq.find(c.id)
    assert "pos_x" in c.keys and rastreio.track_of(c).target["tipo"] == "proprio" and ui.btn_reapply.isEnabled()
    win.model.undo()      # o aplicar é um passo só
    pump()
    c = win.model.seq.find(c.id)
    assert not c.keys and rastreio.track_of(c) is not None
    win.model.undo()      # e o rastreio é outro
    pump()
    assert rastreio.track_of(win.model.seq.find(c.id)) is None


def test_overlay_marks_the_point(win):
    set_module(win, "movimento", True)
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1")
    src = tl.Source(path="C:/naoexiste/v.mp4", width=320, height=180, fps=24.0, fps_str="24/1", frames=24,
                    duration=1.0, has_video=True)
    seq.sources[src.path] = src
    c = seq.insert_media(src, at=0, with_audio=False)[0]
    rastreio.store(c, rastreio.Track(ref=0, first=0, uv=np.tile([0.25, 0.5], (24, 1)), score=np.ones(24)))
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.select([c.id])
    pump()
    ui = win.vfx_ui.fronts["movimento_ui"]

    class Ctx:
        frame = 3
        size = (160, 90)

    img = ui.overlay(Ctx())
    assert img is not None and img.shape == (90, 160, 4)
    assert img[45, 40, 3] == 1.0 and img[10, 150, 3] == 0.0
    Ctx.frame = 40
    assert ui.overlay(Ctx()) is None
    assert not vfx.is_adjustment(win.model.seq, c)
