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


# ------------------------------------------------------------------ zumbido
def test_detect_hum_button(tmp_path):
    _ffmpeg()
    t = np.arange(3 * R) / R
    music = sum(0.05 * np.sin(2 * np.pi * f * t) for f in (220.0, 330.0, 440.0))
    hum = sum(0.03 / k * np.sin(2 * np.pi * 60 * k * t) for k in (1, 2, 3))
    m, c = _model(_wav(tmp_path / "zumbido.wav", music + hum))
    ins = _inspector(m)
    snd = ins.limpeza
    row = snd.rows["zumbido"]
    assert snd.btn_hum.parent() is row   # ao lado da caixa de escolha
    job = snd.detect_hum()
    _wait(job)
    assert m.seq.find(c.id).values["zumbido"] == "60" and "60 Hz" in snd.status.text()
    assert row.combo.currentData() == "60"
    m.undo()
    assert m.seq.find(c.id).values["zumbido"] == "nao" and not m.can_undo()
    m2, c2 = _model(_wav(tmp_path / "musica.wav", music))
    ins2 = _inspector(m2)
    _wait(ins2.limpeza.detect_hum())
    assert m2.seq.find(c2.id).values["zumbido"] == "nao" and not m2.can_undo()
    assert "nada mudou" in ins2.limpeza.status.text()


# ------------------------------------------------------------------ predefinições do "eq"
def test_eq_presets_menu():
    from PySide6.QtGui import QAction
    m, c = _model("C:/v/som.wav")
    m.set_clip_values(c.id, {**m.seq.find(c.id).values, "volume": -4.0})
    ins = _inspector(m)
    snd = ins.limpeza
    eq = next(card for card in ins.acards if card.section.key == "eq")
    assert eq.body.layout().itemAt(0).widget() is snd.btn_presets
    acts = {a.objectName(): a for a in snd.presets_menu.findChildren(QAction) if a.objectName()}
    assert list(acts) == [f"preset_{k}" for k, _l, _v in editparams.AUDIO_PRESETS]
    acts["preset_telefone"].trigger()
    v = m.seq.find(c.id).values
    assert (v["passa_alta"], v["passa_baixa"], v["medios"], v["volume"]) == (300.0, 3400.0, 4.0, -4.0)
    row = next(r for r in eq.rows if r.param.key == "passa_alta")
    assert ins.astore.get("passa_alta") == 300.0 and row.isVisibleTo(eq.body)
    acts["preset_sem_ajustes"].trigger()
    v = m.seq.find(c.id).values
    assert all(v[k] == editparams.AUDIO.defaults()[k] for k in editparams.AUDIO_PRESET_KEYS) and v["volume"] == -4.0
    m.undo()   # cada predefinição é um passo
    assert m.seq.find(c.id).values["passa_baixa"] == 3400.0
    m.undo()
    assert m.seq.find(c.id).values["passa_baixa"] == 0.0 and m.seq.find(c.id).values["volume"] == -4.0
