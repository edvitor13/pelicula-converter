"""1.6, marcação de luz por plano (`luz_plano.py`): os pontos da copiadora de cada clipe da V1 chegam ao plano do look
nos quadros certos (cortes, transições interpoladas, faixas de cima não mudam o plano), com o Laboratório ligado; no
padrão nada muda; 12 pontos = 1 stop da cópia; JSON esparso e formato 4; desfazer; prévia = exportação."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from pelicula import editparams, export, look, luz_plano, modules, params, project
from pelicula import timeline as tl
from pelicula.frame import Recipe

W, H = 320, 180
LAB = dict(lab_on=True, lab_negativo="vision3_250d", lab_copia="2383")


def _src(name, frames=48, fps=24.0):
    return tl.Source(path=f"C:/v/{name}.mp4", width=W, height=H, fps=fps, frames=frames, duration=frames / fps,
                     has_audio=False)


def _seq(fps="24/1"):
    seq = tl.Sequence(width=W, height=H, fps_str=fps)
    for i, at in enumerate((0, 48, 96)):
        seq.insert_media(_src(f"c{i}"), at=at)
    return seq


def _v1(seq, start):
    return next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 0 and c.start == start)


def _set(seq, clip, **kw):
    seq.set_values(clip.id, {**clip.values, **kw})


def _vals(**kw):
    return params.sanitize({**LAB, **kw})


def _plan(values, seq, index, fps=24.0):
    return Recipe.for_source(values, fps, 8, legal=True, seq=seq).plan(W, H, index).uniforms


def _off(values, seq, index, fps=24.0):
    return np.asarray(_plan(values, seq, index, fps)["u_la_off"], dtype=np.float64)


# ------------------------------------------------------------------ esquema e padrão
def test_clip_params_are_appended_neutral_and_sparse():
    keys = [p.key for s in editparams.VIDEO_SECTIONS if s.key == "luz_copiadora" for p in s.params]
    assert keys == list(luz_plano.KEYS)
    assert editparams.VIDEO_SECTIONS[-1].key == "luz_copiadora", "seção nova no fim"
    d = editparams.VIDEO.defaults()
    assert all(d[k] == 0.0 for k in keys)
    assert set(keys) <= editparams.SPARSE_KEYS
    assert not any(editparams.VIDEO.params[k].animatable for k in keys), "luz de plano não anima"
    assert luz_plano.points(d) == (0.0, 0.0, 0.0) and not luz_plano.has_lights(d)


def test_default_montage_keeps_the_plan_bit_identical():
    seq = _seq()
    assert not luz_plano.uses(seq) and luz_plano.shot_lights(seq, 50, 24.0) is None
    for values in (_vals(), params.defaults()):
        for i in (0, 47, 48, 95, 96, 120):
            plain = look.build_plan(values, W, H, i, 24.0, dither=False).uniforms
            assert _plan(values, seq, i) == plain


def test_lights_do_nothing_without_the_laboratory():
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_r=6.0)
    off = params.sanitize({**LAB, "lab_on": False})
    assert _plan(off, seq, 50) == look.build_plan(off, W, H, 50, 24.0, dither=False).uniforms


# ------------------------------------------------------------------ o plano da V1 nos quadros certos
def test_v1_clip_lights_reach_the_plan_on_its_frames_only():
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_r=6.0, luz_g=-2.0, luz_b=3.0, luz_densidade=1.0)
    v = _vals()
    base = _off(v, None, 0)
    for i in (0, 47, 96, 130):
        assert np.allclose(_off(v, seq, i), base), i
    for i in (48, 70, 95):
        d = (_off(v, seq, i) - base) / look.LAB_POINT
        assert np.allclose(d, [7.0, -1.0, 4.0], atol=1e-9), i
    assert luz_plano.shot_lights(seq, 60, 24.0) == (7.0, -1.0, 4.0)
    assert luz_plano.shot_lights(seq, 10, 24.0) == (0.0, 0.0, 0.0)


def test_lights_add_to_the_look_lights_and_follow_the_output_rate():
    seq = _seq()
    _set(seq, _v1(seq, 0), luz_b=-4.0)
    v = _vals(lab_luz_b=2.0, lab_densidade=1.0)
    ref = _vals(lab_luz_b=-2.0, lab_densidade=1.0)  # 2 − 4
    assert np.allclose(_off(v, seq, 10), _off(ref, None, 10))
    # saída a 48 qps: o quadro 95 da saída é o 47 da sequência (ainda o 1º clipe), o 96 é o 48
    assert luz_plano.shot_lights(seq, 95, 48.0) == (0.0, 0.0, -4.0)
    assert luz_plano.shot_lights(seq, 96, 48.0) == (0.0, 0.0, 0.0)


def test_twelve_points_are_one_print_stop():
    assert luz_plano.POINTS_PER_PRINT_STOP * look.LAB_POINT == pytest.approx(math.log10(2.0), abs=0.002)
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_densidade=12.0)
    v = _vals()
    d = _off(v, seq, 60) - _off(v, None, 60)
    assert np.allclose(d, 0.30, atol=1e-12), "12 pontos = 0,30 log E nas três luzes"
    # a cópia vê 1 stop a menos de luz: o cinza do negativo sai como o de uma cena 1 stop mais escura com o
    # negativo "copiado" no mesmo trecho da curva (mesma densidade da cópia que −1 stop de luz da copiadora)
    gray = np.full(3, 0.18)
    a = look.lab_eval({**v, "lab_densidade": 12.0}, gray)
    b = look.lab_eval(luz_plano.apply(v, (12.0, 12.0, 12.0)), gray)
    assert np.allclose(a, b)
    assert a.mean() < look.lab_eval(v, gray).mean(), "mais pontos = cópia mais escura"


def test_stacked_v2_clips_do_not_change_the_shot():
    seq = _seq()
    seq.insert_media(_src("titulo", frames=30), at=10, vtrack=1)
    top = next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 1)
    _set(seq, top, luz_r=10.0)
    _set(seq, _v1(seq, 0), luz_g=2.0)
    assert luz_plano.uses(seq)
    assert luz_plano.shot_lights(seq, 20, 24.0) == (0.0, 2.0, 0.0), "o plano é o da V1"
    v = _vals()
    assert np.allclose((_off(v, seq, 20) - _off(v, None, 20)) / look.LAB_POINT, [0.0, 2.0, 0.0])
    # V1 escondida: nenhum plano, nenhuma luz própria
    seq.track(tl.VIDEO, 0).muted = True
    assert luz_plano.shot_lights(seq, 20, 24.0) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("kind", ["dissolver", "fusao"])
def test_two_clip_transitions_interpolate_the_lights(kind):
    seq = _seq()
    a, b = _v1(seq, 0), _v1(seq, 48)
    _set(seq, a, luz_r=-6.0)
    _set(seq, b, luz_r=6.0, entrada_tipo=kind, entrada_dur=1.0)
    n = 24
    got = []
    for pos in range(n):
        shot = luz_plano.shot_at(seq, 48 + pos)
        assert [c.id for c, _v, _w in shot] == [a.id, b.id], pos
        k = (pos + 1) / (n + 1)
        r = luz_plano.shot_lights(seq, 48 + pos, 24.0)[0]
        assert r == pytest.approx(-6.0 * (1 - k) + 6.0 * k), pos
        got.append(r)
    assert got == sorted(got), "a luz caminha sem voltar"
    assert luz_plano.shot_lights(seq, 47, 24.0)[0] == -6.0 and luz_plano.shot_lights(seq, 48 + n, 24.0)[0] == 6.0
    v = _vals()
    mid = (_off(v, seq, 48 + n // 2) - _off(v, None, 0)) / look.LAB_POINT
    assert mid[0] == pytest.approx(-6.0 + 12.0 * (n // 2 + 1) / (n + 1))


def test_one_clip_transitions_keep_the_cut():
    """Surgir do preto não mostra o plano anterior: a luz troca no corte."""
    seq = _seq()
    a, b = _v1(seq, 0), _v1(seq, 48)
    _set(seq, a, luz_r=-6.0)
    _set(seq, b, luz_r=6.0, entrada_tipo="preto", entrada_dur=1.0)
    assert luz_plano.shot_lights(seq, 47, 24.0)[0] == -6.0
    assert luz_plano.shot_lights(seq, 48, 24.0)[0] == 6.0


def test_plan_is_deterministic():
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_r=3.0, entrada_tipo="dissolver", entrada_dur=0.5)
    v = _vals()
    assert _plan(v, seq, 52) == _plan(v, seq, 52)


# ------------------------------------------------------------------ projeto, desfazer, módulo
def test_json_is_sparse_and_goes_to_format_4():
    seq = _seq()
    plain = seq.to_json()
    assert not any(k in c["valores"] for c in plain["clipes"] for k in luz_plano.KEYS)
    assert "ajustes_clipe_1_6" not in seq.features()
    c = _v1(seq, 48)
    _set(seq, c, luz_r=2.0)
    data = json.loads(json.dumps(seq.to_json()))
    vals = next(x["valores"] for x in data["clipes"] if x["id"] == c.id)
    assert vals["luz_r"] == 2.0 and "luz_g" not in vals and "luz_densidade" not in vals
    back = tl.Sequence.from_json(data)
    assert back.find(c.id).values["luz_r"] == 2.0 and back.to_json() == data
    feats = seq.features()
    assert "ajustes_clipe_1_6" in feats and project.needed_format(feats, True) == project.FORMAT_16 == 4


def test_trivial_file_with_lights_goes_through_the_montage():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    src = tl.Source(path="C:/v/um.png", width=W, height=H, fps=24.0, frames=1, duration=1 / 24.0,
                    has_audio=False, is_image=True)
    seq.insert_media(src, at=0)
    c = seq.clips[0]
    assert seq.is_trivial() is not None
    _set(seq, c, luz_b=1.0)
    assert seq.is_trivial() is None


def test_model_update_is_one_undo_step():
    from pelicula.ui.edit_model import TimelineModel
    m = TimelineModel(_seq())
    a, b = _v1(m.seq, 0), _v1(m.seq, 48)
    n = m.update_clip_values({a.id: {"luz_r": 3.0}, b.id: {"luz_r": 3.0, "luz_b": -2.0}})
    assert n == 2
    assert m.seq.find(a.id).values["luz_r"] == 3.0 and m.seq.find(b.id).values["luz_b"] == -2.0
    assert m.update_clip_values({a.id: {"luz_r": 3.0}}) == 0, "nada mudou: nenhum passo"
    m.undo()
    assert m.seq.find(a.id).values["luz_r"] == 0.0 and m.seq.find(b.id).values["luz_b"] == 0.0
    m.redo()
    assert m.seq.find(b.id).values["luz_r"] == 3.0
    m.seq.track(tl.VIDEO, 0).locked = True
    assert m.update_clip_values({a.id: {"luz_r": 5.0}}) == 0, "faixa travada"


def test_used_by_points_to_the_laboratory():
    seq = _seq()
    assert "laboratorio" not in modules.used_by(params.defaults(), seq)
    _set(seq, _v1(seq, 48), luz_g=1.0)
    assert "laboratorio" in modules.used_by(params.defaults(), seq)


def test_classic_display_is_tape_plus_look_plus_clip():
    look_v = _vals(lab_luz_r=1.0, lab_densidade=-2.0)
    assert luz_plano.classic(look_v, {"luz_r": 3.0, "luz_densidade": 1.0}) == (28.0, 24.0, 24.0)
    assert luz_plano.classic(params.defaults(), {}) == (25.0, 25.0, 25.0)


# ------------------------------------------------------------------ prévia = exportação
def test_export_recipe_gives_the_same_plan(make_info):
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_r=4.0, luz_b=-3.0)
    v = _vals()
    info = make_info(width=W, height=H, frames=144)
    s = export.ExportSettings()
    exp = export.frame_pipeline(info, v, s, seq)
    prev = Recipe.for_source(v, 24.0, exp.depth, legal=exp.legal, seq=seq, dither=exp.dither)
    for i in (10, 50, 100):
        assert exp.plan(W, H, i).uniforms == prev.plan(W, H, i).uniforms


@pytest.mark.gpu
def test_more_red_light_makes_the_shot_cyan(gl_engine):
    seq = _seq()
    _set(seq, _v1(seq, 48), luz_r=8.0)
    rec = Recipe.for_source(_vals(), 24.0, 16, legal=True, seq=seq)
    img = np.full((H, W, 3), 0.5, np.float32)
    img = (img * 65535).astype(np.uint16)
    before = rec.look(gl_engine, img, 10).astype(np.float64).reshape(-1, 3).mean(0)
    shot = rec.look(gl_engine, img, 60).astype(np.float64).reshape(-1, 3).mean(0)
    assert shot[0] < before[0] - 500, "mais luz vermelha = cópia mais ciano"
    assert np.array_equal(rec.look(gl_engine, img, 60), rec.look(gl_engine, img, 60))
