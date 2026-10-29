"""1.6, a montagem comanda a película (`montagem_filme.py`): os cortes secos da V1 viram emendas nos quadros certos,
os rolos de Super 8 têm o comprimento certo, tudo é determinístico e, sem montagem ou com a seção desligada, o plano
é o de sempre."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import look, modules, montagem_filme as mf, params
from pelicula import timeline as tl
from pelicula.frame import Recipe

W, H = 320, 180


def _src(name, frames=48, fps=24.0):
    return tl.Source(path=f"C:/v/{name}.mp4", width=W, height=H, fps=fps, frames=frames, duration=frames / fps,
                     has_audio=False)


def _seq(fps="24/1"):
    seq = tl.Sequence(width=W, height=H, fps_str=fps)
    for i, at in enumerate((0, 48, 96)):
        seq.insert_media(_src(f"c{i}"), at=at)
    return seq


def _vals(**kw):
    return params.sanitize({"mfilme_on": True, "mfilme_emenda": 1.0, "mfilme_clarao": 1.0, "mfilme_salto": 1.0,
                            **kw})


def _plan(values, seq, index, fps=24.0):
    return Recipe.for_source(values, fps, 8, legal=True, seq=seq).plan(W, H, index).uniforms


def test_cut_times_are_the_dry_cuts_of_v1():
    seq = _seq()
    assert mf.cut_times(seq) == [2.0, 4.0]
    third = next(c for c in seq.clips if c.kind == tl.VIDEO and c.start == 96)
    seq.set_values(third.id, {**third.values, "entrada_tipo": "dissolver"})
    assert mf.cut_times(seq) == [2.0], "o corte com transição não é emenda"


def test_edit_info_counts_output_frames_since_the_cut():
    seq = _seq()
    assert mf.edit_info(seq, 47, 24.0) == mf.EditInfo(None)
    assert mf.edit_info(seq, 48, 24.0) == mf.EditInfo(0, 0)
    assert mf.edit_info(seq, 49, 24.0) == mf.EditInfo(1, 0)
    assert mf.edit_info(seq, 96, 24.0) == mf.EditInfo(0, 1)
    assert mf.edit_info(seq, 96, 48.0) == mf.EditInfo(0, 0), "outra taxa na saída: o instante decide"
    assert mf.edit_info(seq, 97, 48.0) == mf.EditInfo(1, 0)
    assert mf.edit_info(None, 48, 24.0) == mf.EditInfo(None)


def test_defects_land_on_the_cut_frames_only():
    seq = _seq()
    v = _vals()
    base = {i: _plan(params.defaults(), seq, i) for i in (46, 47, 48, 49, 50, 96)}
    for i in (46, 47, 50):
        u = _plan(v, seq, i)
        assert u["u_splice"][0] == 0 and u["u_gain"] == base[i]["u_gain"] and u["u_shift"] == base[i]["u_shift"]
    u48, u49, u96 = _plan(v, seq, 48), _plan(v, seq, 49), _plan(v, seq, 96)
    assert u48["u_splice"][0] == 1.0 and u48["u_dmg_on"] == 1 and u96["u_splice"][0] == 1.0
    assert u49["u_splice"][0] == 0.0, "a fita só no primeiro quadro"
    assert u48["u_gain"][0] == pytest.approx(base[48]["u_gain"][0] + mf.FLASH_STOPS)
    assert base[49]["u_gain"][0] < u49["u_gain"][0] < u48["u_gain"][0]
    assert abs(u48["u_shift"][1] - base[48]["u_shift"][1]) == pytest.approx(mf.JUMP_PX * H / 1080)
    assert u48 == _plan(v, seq, 48), "determinístico"


def test_splice_probability_and_seed():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    for i in range(40):
        seq.insert_media(_src(f"k{i}", frames=6), at=i * 6)
    v = _vals(mfilme_emenda=0.5, mfilme_clarao=0.0, mfilme_salto=0.0)
    shown = [_plan(v, seq, i * 6)["u_splice"][0] > 0 for i in range(1, 40)]
    assert 8 < sum(shown) < 31
    other = [_plan({**v, "mfilme_semente": 8}, seq, i * 6)["u_splice"][0] > 0 for i in range(1, 40)]
    assert shown != other


def test_off_and_without_montage_the_plan_is_unchanged():
    seq = _seq()
    d = params.defaults()
    for i in (0, 48, 49, 96):
        plain = look.build_plan(d, W, H, i, 24.0, dither=False).uniforms
        assert _plan(d, seq, i) == plain, "seção desligada"
        assert _plan({**d, "mfilme_on": True}, None, i) == plain or i == 0, "sem montagem, sem cortes"
    assert _plan(_vals(), None, 48)["u_splice"][0] == 0.0


@pytest.mark.parametrize("cad,seconds", [("18", 200.0), ("24", 150.0)])
def test_roll_lengths(cad, seconds):
    v = _vals(rolo_on=True, rolo_cadencia=cad, mfilme_emenda=0.0, mfilme_clarao=0.0, mfilme_salto=0.0)
    assert mf.roll_length_s(v) == seconds == mf.ROLL_FRAMES / int(cad)
    fps = 24.0
    mid = _plan(v, None, int(seconds * fps / 2), fps)
    assert mid["u_leak_on"] == 0, "no meio do rolo, nada"
    near = [_plan(v, None, int((seconds - s) * fps), fps) for s in (2.0, 1.0, 0.1)]
    amts = [u["u_leak_amt"] for u in near]
    assert all(u["u_leak_on"] == 1 for u in near) and amts == sorted(amts), "o velamento cresce até o fim do rolo"
    change = _plan(v, None, int(round(seconds * fps)), fps)
    before = _plan(v, None, int(round(seconds * fps)) + 1, fps)
    assert change["u_shift"][1] - before["u_shift"][1] > 10 * H / 1080, "a troca de rolo pula"
    assert change["u_leak_on"] == 1, "a ponta do rolo novo veio velada"


@pytest.mark.gpu
def test_render_is_deterministic_and_marks_the_cut(gl_engine, test_rgb):
    seq = _seq()
    rec = Recipe.for_source(_vals(), 24.0, 8, legal=True, seq=seq)
    img = test_rgb[:H, :W] if test_rgb.shape[0] >= H else test_rgb
    a = rec.look(gl_engine, img, 48)
    assert np.array_equal(a, rec.look(gl_engine, img, 48))
    assert a.astype(int).mean() > rec.look(gl_engine, img, 50).astype(int).mean() + 5, "o clarão do corte"


def test_module_is_beta_and_detected():
    assert modules.get("montagem_pelicula").status == modules.BETA
    assert "montagem_pelicula" in modules.used_by(_vals())
    assert "montagem_pelicula" not in modules.used_by(params.defaults())
