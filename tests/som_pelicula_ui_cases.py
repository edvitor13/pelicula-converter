"""Casos do som de película na janela (1.8; rodados por test_som_pelicula_ui.py num subprocesso offscreen).

O cartão "Som de película" é do módulo Beta "som_pelicula" (desligado no começo); a prévia toca o som processado pelo
mesmo motor da exportação: o do arquivo no modo Película e o da mixagem no modo Edição. Mudar um ajuste do som de
película refaz só o processamento (a mixagem fica); sem película, com os efeitos desligados ou com a seção desligada, a
prévia volta ao som de sempre. Nenhum som toca de verdade (só arquivos).

As preferências ficam num .ini só deste arquivo (nada de outros testes nem do usuário).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_som_pelicula_ui_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import audiomix, media, modules, somfilme  # noqa: E402
from pelicula.ui import prefs  # noqa: E402


@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = prefs.settings()
    for m in modules.MODULES:
        s.remove(modules.KEY_PREFIX + m.id)
    s.setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


@pytest.fixture(scope="module")
def video():
    ffmpeg = media.ffmpeg()
    if not ffmpeg:
        pytest.skip("sem ffmpeg")
    path = os.path.join(tempfile.mkdtemp(prefix="pelicula_somf_ui_"), "tom.mov")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=160x90:r=24:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", path],
                   check=True, timeout=60)
    return path


def until(cond, seconds: float = 30.0, what: str = "") -> None:
    end = time.time() + seconds
    while time.time() < end:
        APP.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"não chegou: {what}")


def processed(win) -> bool:
    sp = win.som_pelicula
    return bool(sp.path) and win._audio_src == ("seq", sp.path) and not sp.timer.isActive() and not sp.running


def set_module(win, on: bool) -> None:
    modules.set_enabled(win.settings, "som_pelicula", on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def test_card_belongs_to_the_beta_module(win):
    card = next(c for c in win.cards if c.section.key == "som_pelicula")
    assert win._module_tools()["som_pelicula"] == [card]
    assert card.isHidden(), "Beta: começa desligado"
    set_module(win, True)
    assert not card.isHidden()
    set_module(win, False)
    assert card.isHidden()
    assert win.som_pelicula.values() is None or not win.store.get("somf_on")


def test_file_preview_plays_the_processed_sound(win, video):
    win.set_mode("pelicula")
    win.load_media(video)
    APP.processEvents()
    until(lambda: win._audio_src == ("file", video), what="som do arquivo")
    win.store.set("somf_on", True)  # o módulo desligado só esconde o cartão: o som muda igual
    win.store.set("somf_trilha", "otica_16")
    win.store.commit()
    until(lambda: processed(win), what="som processado")
    first = win.som_pelicula.path
    r = audiomix.WavReader(first)
    x = r.read(0, r.frames).astype(np.float64)
    dec = os.path.join(tempfile.mkdtemp(), "ref.wav")
    assert audiomix.decode_wav(video, dec)
    info = win.info
    ref = os.path.join(tempfile.mkdtemp(), "ref_proc.wav")
    v = dict(win.store.values)
    assert somfilme.process_wav(dec, ref, v, info.fps, 0, somfilme.events_for(v, info.fps, info.frames))
    y = audiomix.WavReader(ref).read(0, r.frames).astype(np.float64)
    assert x.shape == y.shape and np.abs(x - y).max() < 1e-6, "a prévia = o motor da exportação"
    win.store.set("somf_sala", 0.6)
    win.store.commit()
    until(lambda: processed(win) and win.som_pelicula.path != first, what="sala")
    win.no_effects = True
    win._update_label_proc()
    until(lambda: win._audio_src == ("file", video), what="sem efeitos")
    win.no_effects = False
    win._update_label_proc()
    until(lambda: processed(win), what="efeitos de volta")
    win.store.set("somf_on", False)
    win.store.commit()
    until(lambda: win._audio_src == ("file", video), what="desligado")


def test_montage_changes_only_reprocess_not_remix(win, video):
    win.set_mode("edicao")
    win.edit_film = True
    win.import_paths([video])
    win.add_to_timeline(video)
    win.add_to_timeline(video)
    until(lambda: win._mix_path and win._mix_key == audiomix.mix_key(win.model.seq.copy()), what="mixagem")
    win.store.set("somf_on", True)
    win.store.set("mfilme_on", True)
    win.store.commit()
    until(lambda: processed(win), what="mixagem processada")
    mix, first = win._mix_path, win.som_pelicula.path
    win.store.set("somf_estalos", 1.0)
    win.store.commit()
    until(lambda: processed(win) and win.som_pelicula.path != first, what="estalos")
    assert win._mix_path == mix, "um ajuste do som de película não refaz a mixagem"
    win.edit_film = False
    win._update_label_proc()
    until(lambda: win._audio_src == ("seq", win._mix_path), what="sem película")
    win.edit_film = True
    win._update_label_proc()
    until(lambda: processed(win), what="com película")
    win.store.set("somf_on", False)
    win.store.commit()
    until(lambda: win._audio_src == ("seq", win._mix_path), what="desligado")
