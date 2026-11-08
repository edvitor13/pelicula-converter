"""Casos da interface da limpeza do som (1.8, `ui/somlimpo_ui.py`): aprender o ruído, detectar o zumbido,
predefinições do "eq" e sincronizar pelo som.

Rodados por test_somlimpo_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de
uma QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Os sons são gerados em numpy (≤ 3 s).
"""

from __future__ import annotations

import math
import os
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import editparams, media, somlimpo  # noqa: E402
from pelicula import timeline as tl  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402

R = 48000


def _ffmpeg() -> None:
    try:
        media.ffmpeg()
    except RuntimeError as exc:
        pytest.skip(f"ffmpeg indisponível: {exc}")


def _wav(path, x) -> str:
    x = np.asarray(x, np.float64)
    if x.ndim == 1:
        x = np.repeat(x[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(R)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def _source(path, secs) -> tl.Source:
    return tl.Source(path, fps=24.0, frames=int(secs * 24), duration=secs, has_video=False, has_audio=True)


def _model(path, secs=3.0, src_in=0.0, start=0, dur=72) -> tuple[TimelineModel, tl.Clip]:
    seq = tl.Sequence(640, 360, "24/1")
    seq.add_source(_source(path, secs))
    c = tl.Clip(tl.new_id(), tl.AUDIO, path, 0, start, dur, src_in)
    seq.clips.append(c)
    m = TimelineModel(seq)
    m.select([c.id])
    return m, c


def _wait(job, secs=30.0) -> None:
    end = time.monotonic() + secs
    while job.active and time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)
    for _i in range(20):
        APP.processEvents()
        time.sleep(0.005)


def _inspector(m):
    from pelicula.ui.edit_panels import ClipInspector
    return ClipInspector(m)


# ------------------------------------------------------------------ aprender o ruído
def test_learn_noise_button_rules(tmp_path):
    _ffmpeg()
    rng = np.random.default_rng(3)
    x = rng.standard_normal(3 * R) * 0.01
    x[int(2.0 * R):] = 0.0     # o fim do arquivo é mudo
    path = _wav(tmp_path / "ruido.wav", x)
    m, c = _model(path)
    ins = _inspector(m)
    snd = ins.limpeza
    body = snd.clean_card.body
    assert not snd.rows["ruido_ini"].isVisibleTo(body) and not snd.rows["ruido_fim"].isVisibleTo(body)
    assert snd.btn_learn.isVisibleTo(body) and snd.rows["ruido_perfil"].isVisibleTo(body)
    # cursor fora do clipe: recusa sem tocar no clipe
    ins.set_playhead(200)
    assert snd.learn() is None and "cursor" in snd.status.text()
    # 1 s a partir do cursor (quadro 12 = 0,5 s)
    ins.set_playhead(12)
    job = snd.learn()
    assert job is not None
    _wait(job)
    v = m.seq.find(c.id).values
    assert (v["ruido_ini"], v["ruido_fim"]) == pytest.approx((0.5, 1.5))
    assert v["ruido_perfil"] == pytest.approx(somlimpo_ui().LEARN_STRENGTH)
    assert "aprendido" in snd.learned.text().lower()
    m.undo()   # um passo só
    v = m.seq.find(c.id).values
    assert (v["ruido_ini"], v["ruido_fim"], v["ruido_perfil"]) == (0.0, 0.0, 0.0)
    # trecho mudo: o trabalho recusa com a explicação e nada muda
    ins.set_playhead(50)
    job = snd.learn()
    _wait(job)
    assert "não tem som" in snd.status.text() and m.seq.find(c.id).values["ruido_fim"] == 0.0
    # a entrada e a saída da janela valem quando caem dentro do clipe
    win = ins.window()
    win.inp, win.outp = 24, 36
    ins.set_playhead(60)
    job = snd.learn()
    _wait(job)
    v = m.seq.find(c.id).values
    assert (v["ruido_ini"], v["ruido_fim"]) == pytest.approx((1.0, 1.5))
    # curto demais (entrada/saída de 4 quadros)
    win.inp, win.outp = 24, 28
    assert snd.learn() is None and "curto" in snd.status.text()


def somlimpo_ui():
    from pelicula.ui import somlimpo_ui as mod
    return mod
