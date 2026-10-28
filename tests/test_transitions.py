"""Transições da 1.5 (`transitions.py`, `editshaders.CLIP_TR`): modelo, camadas, uniforms e quadros na GPU.

As transições de antes (corte, dissolver, preto, branco, transparente) são conferidas contra a referência gravada
pela BASE da 1.5 (`tests/transicoes_base.py`): mesmas camadas, mesmos uniforms e, na mesma placa, os mesmos bits.
"""

from __future__ import annotations

import hashlib
import json

import pytest

import transicoes_base as base
from pelicula import editparams, editshaders, project
from pelicula import timeline as tl

REF = json.loads(base.DATA.read_text(encoding="utf-8"))
OLD_IN = ["corte", "dissolver", "preto", "branco"]
OLD_OUT = ["corte", "preto", "branco", "transparente"]


def src(path="a.mp4", frames=96, w=320, h=180, alpha=False):
    return tl.Source(path, w, h, 24.0, "24/1", frames, frames / 24.0, has_audio=False, has_alpha=alpha)


def two_clips(kind="fusao", dur=0.5, **values):
    """A [0, 48) e B [48, 96) colados na V1; B entra com `kind`."""
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    a, = seq.insert_media(src("a.mp4"), at=0)
    seq.trim_end(a.id, 48)
    b, = seq.insert_media(src("b.mp4"), at=48)
    seq.trim_end(b.id, 96)
    seq.set_values(b.id, {**b.values, "entrada_tipo": kind, "entrada_dur": dur, **values})
    return seq, seq.find(a.id), seq.find(b.id)


# ------------------------------------------------------------------ as transições de antes, bit a bit
def test_old_transition_choices_keep_their_order():
    p = editparams.VIDEO.params
    assert [v for v, _l in p["entrada_tipo"].choices][:4] == OLD_IN
    assert [v for v, _l in p["saida_tipo"].choices][:4] == OLD_OUT
    assert [v for v, _l in p["entrada_tipo"].choices][4:] == list(editparams.EXTRA_IN)
    assert [v for v, _l in p["saida_tipo"].choices][4:] == list(editparams.EXTRA_OUT)
    assert set(editparams.EXTRA_TWO_CLIP) <= set(editparams.EXTRA_IN)
    for key in editparams.SPARSE_KEYS:
        assert key.isascii() and key in p


def test_clip_shader_text_is_the_one_of_the_base():
    """O caminho das transições antigas é o mesmo programa de antes, letra por letra (o novo é `CLIP_TR`)."""
    assert hashlib.sha256(editshaders.CLIP.encode("utf-8")).hexdigest() == REF["shader_clip"]
    assert hashlib.sha256(editshaders.OUT.encode("utf-8")).hexdigest() == REF["shader_out"]


def test_old_layers_and_uniforms_are_the_ones_of_the_base():
    seq = base.scenario()
    now = json.loads(json.dumps(base.layers_and_uniforms(seq)))
    old = REF["camadas"]
    assert now["quadros"].keys() == old["quadros"].keys()
    for t, rows in old["quadros"].items():
        assert len(now["quadros"][t]) == len(rows), f"quadro {t}"
        for a, b in zip(rows, now["quadros"][t]):
            strip = lambda d: {k: v for k, v in d.items() if k not in ("uniforms", "neutral")}  # noqa: E731
            assert strip(b) == strip(a), f"quadro {t}"
            assert now["uniforms"][b["uniforms"]] == pytest.approx(old["uniforms"][a["uniforms"]], rel=1e-12), t
            assert now["uniforms"][b["neutral"]] == pytest.approx(old["uniforms"][a["neutral"]], rel=1e-12), t
    for layers in (seq.layers_at(t) for t in base.FRAMES):
        assert all(layer.transitions == () for layer in layers)


# ------------------------------------------------------------------ JSON e formato do projeto
def test_old_clip_json_has_no_new_keys():
    seq = base.scenario()
    for c in seq.to_json()["clipes"]:
        assert not (set(c["valores"]) & editparams.SPARSE_KEYS)
    assert seq.features() == {"alfa"}  # a fonte com transparência; nada das transições novas


def test_new_keys_go_to_json_only_when_used_and_come_back():
    seq, _a, b = two_clips("iris", 0.75, entrada_centro_x=0.2, entrada_anel=12.0)
    d = seq.to_json()
    vals = next(c for c in d["clipes"] if c["id"] == b.id)["valores"]
    assert vals["entrada_tipo"] == "iris" and vals["entrada_centro_x"] == 0.2 and vals["entrada_anel"] == 12.0
    assert "entrada_zoom" not in vals and "saida_anel" not in vals
    again = tl.Sequence.from_json(json.loads(json.dumps(d)))
    assert again.find(b.id).values == b.values
    assert again.to_json() == d


def test_using_a_new_type_needs_format_3():
    seq, _a, b = two_clips("corte")
    p = project.Project(media_path="C:/v/a.mp4", sequence=seq.to_json(), mode="edicao")
    assert p.to_json()["formato"] == 2
    for side, kind in [("entrada_tipo", k) for k in editparams.EXTRA_IN] + [("saida_tipo", k)
                                                                           for k in editparams.EXTRA_OUT]:
        seq.set_values(b.id, {**editparams.VIDEO.defaults(), side: kind})
        assert "transicoes" in seq.features(), kind
        p = project.Project(media_path="C:/v/a.mp4", sequence=seq.to_json(), mode="edicao")
        data = p.to_json()
        assert data["formato"] == 3 and "transicoes" in data["recursos"], kind
        assert seq.to_json()["formato"] == tl.FORMAT
    # um ajuste novo fora do padrão com um tipo antigo não precisa da 1.5 (a 1.4 o ignora e desenha igual)
    seq.set_values(b.id, {**editparams.VIDEO.defaults(), "entrada_tipo": "dissolver", "entrada_anel": 30.0})
    assert "transicoes" not in seq.features()


# ------------------------------------------------------------------ camadas (sem GPU)
def test_two_clip_transition_shows_the_previous_clip_with_the_same_progress():
    seq, a, b = two_clips("fusao", 0.5)  # 12 quadros
    assert [len(seq.layers_at(t)) for t in (47, 48, 59, 60)] == [1, 2, 2, 1]
    for t in range(48, 60):
        under, top = seq.layers_at(t)
        assert under.clip.id == a.id and under.extension and under.src_frame == t and top.clip.id == b.id
        (tb,), (tt,) = under.transitions, top.transitions
        assert (tb.kind, tb.role, tt.role, tt.side) == ("fusao", "base", "entra", "entrada")
        assert tb.progress == tt.progress == pytest.approx((t - 48 + 1) / 13)
        assert tt.index == t - 48 and tt.frames == 12 and tt.owner == b.id == tb.owner
        assert top.alpha == 1.0 and top.fade == 0.0  # a mistura é do shader de transições
    assert seq.layers_at(47)[0].transitions == () and seq.layers_at(60)[0].transitions == ()


@pytest.mark.parametrize("kind", editparams.EXTRA_IN)
def test_every_entry_type_progress_and_which_clips(kind):
    seq, a, b = two_clips(kind, 0.25)  # 6 quadros (a emenda conta quadros: 2)
    n = 2 if kind == "emenda" else 6
    assert seq.transition_frames(b, "entrada") == n
    for t in range(48, 48 + n):
        layers = seq.layers_at(t)
        assert [l.clip.id for l in layers] == ([a.id, b.id] if kind in editparams.EXTRA_TWO_CLIP else [b.id])
        tr = layers[-1].transitions[0]
        assert (tr.kind, tr.index, tr.frames) == (kind, t - 48, n)
        assert 0 < tr.progress < 1
    assert seq.layers_at(48 + n)[-1].transitions == ()


def test_two_clip_type_without_a_previous_clip_draws_only_the_clip():
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    c, = seq.insert_media(src(), at=10)
    seq.set_values(c.id, {**c.values, "entrada_tipo": "cortina", "entrada_dur": 0.5})
    layers = seq.layers_at(12)
    assert len(layers) == 1 and layers[0].transitions[0].role == "entra"


@pytest.mark.parametrize("kind", editparams.EXTRA_OUT)
def test_exit_types_progress_runs_to_one_at_the_end(kind):
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    c, = seq.insert_media(src(), at=0)
    seq.set_values(c.id, {**c.values, "saida_tipo": kind, "saida_dur": 0.5})
    trs = [seq.layers_at(t)[0].transitions for t in range(84, 96)]
    assert all(len(x) == 1 and x[0].role == "sai" and x[0].side == "saida" for x in trs)
    prog = [x[0].progress for x in trs]
    assert all(p < q for p, q in zip(prog, prog[1:])) and 0 < prog[0] and prog[-1] < 1
    assert [x[0].index for x in trs] == list(range(12))
    assert seq.layers_at(83)[0].transitions == ()


def test_entry_and_exit_together_and_with_old_types():
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    c, = seq.insert_media(src(), at=0)
    seq.trim_end(c.id, 12)
    seq.set_values(c.id, {**c.values, "entrada_tipo": "iris", "entrada_dur": 0.5, "saida_tipo": "queima",
                          "saida_dur": 0.5})
    layer = seq.layers_at(5)[0]
    assert [(t.kind, t.side) for t in layer.transitions] == [("iris", "entrada"), ("queima", "saida")]
    # tipo antigo de um lado e novo do outro: o antigo continua no alpha/fade
    seq.set_values(c.id, {**c.values, "entrada_tipo": "preto", "saida_tipo": "exposicao"})
    layer = seq.layers_at(5)[0]
    assert 0 < layer.fade < 1 and [t.kind for t in layer.transitions] == ["exposicao"]


def test_split_keeps_entry_left_and_exit_right():
    seq = tl.Sequence(width=320, height=180, fps_str="24/1")
    c, = seq.insert_media(src(), at=0)
    seq.set_values(c.id, {**c.values, "entrada_tipo": "queima", "saida_tipo": "iris", "saida_anel": 20.0})
    right = seq.find(seq.split(40)[0])
    left = seq.find(c.id)
    assert (left.values["entrada_tipo"], left.values["saida_tipo"]) == ("queima", "corte")
    assert (right.values["entrada_tipo"], right.values["saida_tipo"]) == ("corte", "iris")
