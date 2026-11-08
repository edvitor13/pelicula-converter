"""Casos da interface do tempo da imagem da 1.9 (frente F5, ARQUITETURA §53): o cartão "Tempo da imagem" do inspetor
segue o módulo Beta "tempo_imagem", fica depois dos cartões Velocidade e Manivela, e o botão Analisar do deflicker roda na fila,
guarda a análise na fonte (fora do desfazer) e a linha diz o estado (sem arquivo, sem análise, pronta, arquivo mudado).

Rodados por test_tempo_imagem_ui.py num subprocesso offscreen (via `uicases.run_cases`). Este arquivo não é coletado
sozinho.
"""

from __future__ import annotations

import os
import subprocess
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import media, modules, tempo_imagem as ti, timeline as tl  # noqa: E402
from pelicula.ui import main_window as mw, prefs  # noqa: E402


def pump(timeout: float = 0.1) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        time.sleep(0.01)


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


def set_module(win, mid: str, on: bool) -> None:
    modules.set_enabled(win.settings, mid, on)
    win.apply_modules()
    pump()


def load(win, src: tl.Source) -> tl.Sequence:
    """Projeto novo no modo Edição com um clipe desta fonte em V1, escolhido."""
    win.new_project()
    win.set_mode("edicao")
    seq = tl.Sequence(320, 180, "24/1", micro_fade=True)
    c = seq.insert_media(src, at=0, with_audio=False)[0]
    win._loading = True
    win.model.set_sequence(seq)
    win._loading = False
    win.model.changed.emit("*")
    win.model.select([c.id])
    pump()
    return win.model.seq


def video(ffmpeg: str, path) -> str:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def ui(win):
    return win.vfx_ui.fronts["tempo_imagem_ui"]


def test_the_card_follows_the_module_and_comes_after_speed_and_crank(win):
    assert not modules.is_enabled(win.settings, ti.MODULE)
    card = ui(win).card
    assert card.section.key == ti.SECTION and card.isHidden()
    set_module(win, ti.MODULE, True)
    load(win, tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))
    assert card.isVisibleTo(win.inspector)
    lay = card.parentWidget().layout()
    crank = win.vfx_ui.card("manivela")  # Velocidade, Manivela (1.6, logo depois) e este
    assert lay.indexOf(card) == lay.indexOf(crank) + 1 == lay.indexOf(win.vfx_ui.card("tempo")) + 2
    assert win.vfx_ui.module_tools()[ti.MODULE] == [card]
    keys = [r.param.key for r in card.rows]
    assert keys == ["deflicker", "deflicker_janela", "ruido_temporal", "ruido_temporal_quadros", "mistura_quadros"]
    set_module(win, ti.MODULE, False)
    assert not card.isVisibleTo(win.inspector)


def test_without_a_video_file_the_button_is_off(win):
    set_module(win, ti.MODULE, True)
    load(win, tl.Source.virtual("cor", 320, 180, "24/1", data={"cor": "#336699"}))
    t = ui(win)
    assert not t.btn.isEnabled()
    assert "arquivo" in t.status.text()


def test_analyze_stores_the_analysis_out_of_undo(win, ffmpeg_ok, tmp_path):
    set_module(win, ti.MODULE, True)
    seq = load(win, media.probe_source(video(ffmpeg_ok, tmp_path / "v.mp4")))
    t = ui(win)
    src = next(iter(s for s in seq.sources.values() if s.is_file))
    assert t.btn.isEnabled() and "Analisar" in t.status.text()
    steps = win.model.history._pos
    job = t.analyze()
    assert job is not None and not t.btn.isEnabled()
    t0 = time.time()
    while ti.DEFLICKER not in (win.model.seq.sources[src.path].analysis or {}) and time.time() - t0 < 30:
        pump(0.05)
    entry = win.model.seq.sources[src.path].analysis[ti.DEFLICKER]
    assert entry["quadros"] == 24 and ti.means_of(entry).shape == (24,)
    pump()
    assert t.btn.isEnabled() and "24" in t.status.text()
    assert win.model.history._pos == steps, "a análise não é passo do desfazer"
    st = os.stat(src.path)
    os.utime(src.path, (st.st_atime, st.st_mtime + 10))
    t.refresh()
    assert "mudou" in t.status.text()
