""""Congelar este quadro" (`Sequence.freeze_frame`, `TimelineModel.freeze_frame`). Sem ffmpeg."""

from __future__ import annotations

import json

import pytest

from pelicula import timemap
from pelicula import timeline as tl


def _seq(frames=240, fps=24.0):
    src = tl.Source("C:/v/a.mp4", 320, 180, fps, f"{int(fps)}/1", frames, frames / fps, has_audio=True)
    seq = tl.Sequence.for_source(src)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    a = next(c for c in seq.clips if c.kind == tl.AUDIO)
    return seq, v, a


def _shown(seq, t):
    """(quadro do arquivo, congelado?) do vídeo de cima no quadro t; None se não há vídeo."""
    lay = [layer for layer in seq.layers_at(t) if layer.clip.kind == tl.VIDEO]
    return (lay[-1].src_frame, lay[-1].clip.frozen) if lay else None


def _heard(seq, t):
    """Segundo do arquivo que o som toca no quadro t (None = silêncio)."""
    cs = seq.clips_at(t, tl.AUDIO)
    return round(seq.src_time(cs[0], t), 6) if cs else None


def test_insert_freeze_pushes_the_rest_and_leaves_a_silent_gap():
    seq, v, a = _seq()
    before = {t: _shown(seq, t) for t in range(240)}
    heard = {t: _heard(seq, t) for t in range(240)}
    hold = seq.freeze_frame(v.id, 100, 48, insert=True)
    assert hold is not None and (hold.start, hold.dur, hold.frozen, hold.link) == (100, 48, True, "")
    assert not hold.keys and not hold.ramp and not hold.reverse and hold.values["velocidade"] == 1.0
    assert seq.duration == 288
    for t in range(100):
        assert _shown(seq, t) == before[t] and _heard(seq, t) == heard[t]
    for t in range(100, 148):
        assert _shown(seq, t) == (before[100][0], True), "exatamente o quadro do cursor"
        assert _heard(seq, t) is None, "o som fica em silêncio enquanto a imagem está parada"
    for t in range(148, 288):
        assert _shown(seq, t) == before[t - 48] and _heard(seq, t) == heard[t - 48], "depois, tudo em sincronia"
    right_v = next(c for c in seq.clips if c.kind == tl.VIDEO and c.start == 148)
    right_a = next(c for c in seq.clips if c.kind == tl.AUDIO and c.start == 148)
    assert right_v.link and right_v.link == right_a.link


def test_overwrite_freeze_covers_the_clip_and_keeps_the_rest_in_place():
    seq, v, a = _seq()
    before = {t: _shown(seq, t) for t in range(240)}
    heard = {t: _heard(seq, t) for t in range(240)}
    seq.freeze_frame(v.id, 100, 48, insert=False)
    assert seq.duration == 240
    for t in range(240):
        if 100 <= t < 148:
            assert _shown(seq, t) == (before[100][0], True) and _heard(seq, t) is None
        else:
            assert _shown(seq, t) == before[t] and _heard(seq, t) == heard[t]
    right_v = next(c for c in seq.clips if c.kind == tl.VIDEO and c.start == 148)
    right_a = next(c for c in seq.clips if c.kind == tl.AUDIO and c.start == 148)
    assert right_v.link and right_v.link == right_a.link


def test_freeze_takes_the_look_of_that_instant_and_the_retimed_frame():
    seq, v, _a = _seq()
    seq.set_key(v.id, "exposicao", 0, -1.0)
    seq.set_key(v.id, "exposicao", 200, 1.0)
    seq.retime(v.id, reverse=True)
    seq.retime(v.id, ramp=timemap.preset_anchors("lento_meio", 0.0, 10.0))
    t = 150
    want_frame, want_exp = seq.src_frame(v, t), seq.values_at(v, t)["exposicao"]
    hold = seq.freeze_frame(v.id, t, 24)
    assert seq.src_frame(hold, t) == want_frame and hold.values["exposicao"] == pytest.approx(want_exp)
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    hb = back.find(hold.id)
    assert {back.src_frame(hb, x) for x in range(hb.start, hb.end)} == {want_frame}, "o JSON guarda o mesmo quadro"


def test_freeze_targets_and_refusals():
    seq, v, a = _seq()
    assert seq.freeze_target(a.id, 10) is v, "pelo som, congela o vídeo ligado"
    assert seq.freeze_target(None, 10) is v
    assert seq.freeze_target(v.id, 240) is None and seq.freeze_target(v.id, -1) is None
    img = tl.Source("C:/v/foto.png", 320, 180, 24.0, "24/1", 1, 0.0, is_image=True)
    pic, = seq.insert_media(img, at=300)
    assert seq.freeze_frame(pic.id, 310, 24) is None
    seq.set_values(v.id, dict(v.values, congelar=True))
    assert seq.freeze_frame(v.id, 10, 24) is None, "um clipe já congelado não congela de novo"
    seq2, v2, _a2 = _seq()
    tr = seq2.track(tl.VIDEO, 0)
    tr.locked = True
    assert seq2.freeze_frame(v2.id, 10, 24) is None


def test_freeze_at_the_first_frame_does_not_split():
    seq, v, a = _seq()
    hold = seq.freeze_frame(v.id, 0, 24)
    assert hold.start == 0 and v.start == 24 and a.start == 24 and v.dur == 240
    assert seq.src_frame(hold, 0) == 0


def test_model_freeze_is_one_undo_step_and_selects_the_hold():
    from pelicula.ui.edit_model import FREEZE_SECONDS, TimelineModel
    seq, v, _a = _seq()
    m = TimelineModel(seq)
    plain = m.seq.to_json()
    hid = m.freeze_frame(v.id, 60)
    assert hid and m.selection == [hid] and m.seq.find(hid).dur == int(FREEZE_SECONDS * 24)
    m.undo()
    assert m.seq.to_json() == plain
    m.redo()
    assert m.seq.find(hid) is not None
    assert m.freeze_frame(v.id, 100000) is None


def test_magnetic_main_track_insert_freeze_keeps_v1_without_gaps():
    from pelicula.ui.edit_model import TimelineModel
    seq, v, _a = _seq()
    seq.insert_media(seq.sources[v.src], at=240)
    m = TimelineModel(seq)
    m.seq.magnetic = True
    second = next(c for c in m.seq.clips if c.kind == tl.VIDEO and c.start == 240)
    m.freeze_frame(v.id, 100, 1.0, insert=True)
    main = m.seq.clips_on(tl.VIDEO, 0)
    assert [c.start for c in main] == [0, 100, 124, 264] and m.seq.find(second.id).start == 264
    assert all(a.end == b.start for a, b in zip(main, main[1:]))
