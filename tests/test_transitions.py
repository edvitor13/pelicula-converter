"""Transições da 1.5 (`transitions.py`, `editshaders.CLIP_TR`): modelo, camadas, uniforms e quadros na GPU.

As transições de antes (corte, dissolver, preto, branco, transparente) são conferidas contra a referência gravada
pela BASE da 1.5 (`tests/transicoes_base.py`): mesmas camadas, mesmos uniforms e, na mesma placa, os mesmos bits.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import zlib
from dataclasses import replace

import numpy as np
import pytest

import transicoes_base as base
from pelicula import (compositor, editparams, editshaders, look, media, modules, presets, project, sequence,
                      transitions)
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


def _flat(u: dict) -> dict:
    """Uniforms com listas (u_canvas, matrizes) desdobrados em números: o `pytest.approx` 9.2 não compara
    dicionários com listas dentro."""
    out = {}
    for k, v in u.items():
        if isinstance(v, (list, tuple)):
            vals = list(np.ravel(np.asarray(v, dtype=float)))
            out.update({f"{k}[{i}]": x for i, x in enumerate(vals)})
            out[f"{k}#"] = len(vals)
        else:
            out[k] = v
    return out


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
            assert _flat(now["uniforms"][b["uniforms"]]) == pytest.approx(_flat(old["uniforms"][a["uniforms"]]),
                                                                          rel=1e-12), t
            assert _flat(now["uniforms"][b["neutral"]]) == pytest.approx(_flat(old["uniforms"][a["neutral"]]),
                                                                         rel=1e-12), t
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
        assert seq.to_json()["formato"] == tl.FORMAT_15
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


# ------------------------------------------------------------------ uniforms do CLIP_TR (sem GPU)
_SIZES = {"int": 1, "float": 1, "vec2": 2, "vec3": 3, "vec4": 4, "mat3": 9}


def _declared(src: str) -> dict[str, tuple[str, int]]:
    return {name: (typ, int(arr) if arr else 1)
            for typ, name, arr in re.findall(r"uniform\s+(\w+)\s+(u_\w+)\s*(?:\[(\d+)\])?\s*;", src)}


TR_DECLARED = _declared(editshaders.CLIP_TR)
SIDES = [("entrada", k) for k in editparams.EXTRA_IN] + [("saida", k) for k in editparams.EXTRA_OUT]


def pair(side: str, kind: str, n: int = 12, **values):
    """A [0, 48) e B [48, 96); a transição `kind` na entrada de B ou na saída de A, com `n` quadros.
    Devolve (seq, quadros da transição)."""
    seq, a, b = two_clips("corte")
    if side == "entrada":
        seq.set_values(b.id, {**b.values, "entrada_tipo": kind, "entrada_dur": n / 24.0, **values})
        frames = list(range(48, 48 + seq.transition_frames(seq.find(b.id), "entrada")))
    else:
        seq.set_values(a.id, {**a.values, "saida_tipo": kind, "saida_dur": n / 24.0, **values})
        frames = list(range(48 - n, 48))
    return seq, frames


@pytest.mark.parametrize("side,kind", SIDES)
def test_transition_uniforms_fill_the_shader(side, kind):
    seq, frames = pair(side, kind)
    t = frames[len(frames) // 2]
    for layer in seq.layers_at(t):
        U, _mip = compositor.clip_uniforms(seq, layer, 320, 180, 320, 180, light=(3, True))
        declared = TR_DECLARED if "u_tr_kind" in U else _declared(editshaders.CLIP)
        assert set(U) == set(declared), set(U) ^ set(declared)
        for k, val in U.items():
            typ, n = declared[k]
            flat = []
            for x in (val if isinstance(val, tuple) else (val,)):
                flat.extend(x if isinstance(x, tuple) else (x,))
            assert len(flat) == _SIZES[typ] * n, f"{k}: {typ}[{n}] recebeu {val!r}"
            assert all(isinstance(x, int) if typ == "int" else math.isfinite(x) for x in flat), k
        if "u_tr_kind" in U:
            assert U["u_tr_input"] == 3 and U["u_tr_cv"] == 1 and U["u_tr_scale"] == pytest.approx(180 / 1080)
            assert transitions.KIND_IDS[kind] in U["u_tr_kind"]


def test_plain_layers_keep_the_old_program_and_endpoints_drop_the_transition():
    seq, frames = pair("entrada", "iris")
    t = frames[3]
    under, top = seq.layers_at(t)
    assert "u_tr_kind" not in compositor.clip_uniforms(seq, under, 320, 180, 320, 180)[0]  # base da íris: parada
    assert "u_tr_kind" in compositor.clip_uniforms(seq, top, 320, 180, 320, 180)[0]
    done = replace(top, transitions=tuple(replace(tr, progress=1.0) for tr in top.transitions))
    plain = replace(top, transitions=())
    assert compositor.clip_uniforms(seq, done, 320, 180, 320, 180) == compositor.clip_uniforms(seq, plain, 320,
                                                                                                  180, 320, 180)
    seq, frames = pair("saida", "queima")
    layer = seq.layers_at(frames[0])[0]
    start = replace(layer, transitions=tuple(replace(tr, progress=0.0) for tr in layer.transitions))
    assert "u_tr_kind" not in compositor.clip_uniforms(seq, start, 320, 180, 320, 180)[0]


def test_geometry_of_push_zoom_and_splice_jump():
    seq, frames = pair("entrada", "empurrar", entrada_direcao="esquerda")
    under, top = seq.layers_at(frames[5])
    Ut, _ = compositor.clip_uniforms(seq, top, 320, 180, 320, 180)
    Ub, _ = compositor.clip_uniforms(seq, under, 320, 180, 320, 180)
    e = transitions.ease(top.transitions[0].progress)
    m = np.array(Ut["u_xf"]).reshape(3, 3).T  # GLSL guarda por coluna
    # vem da esquerda: o clipe novo está (1 − e)·largura à esquerda; o anterior, e·largura à direita
    assert m @ np.array([-(1 - e) * 320 + 0.5, 0.5, 1.0]) == pytest.approx([0.5 / 320, 0.5 / 180, 1.0])
    mb = np.array(Ub["u_xf"]).reshape(3, 3).T
    assert mb @ np.array([e * 320 + 0.5, 0.5, 1.0]) == pytest.approx([0.5 / 320, 0.5 / 180, 1.0])
    assert Ut["u_exact"] == 0 and Ut["u_tr_blur"][0] == 1.0 and Ut["u_tr_blur"][1] < 0
    seq, frames = pair("entrada", "zoom", entrada_zoom=2.0)
    _under, top = seq.layers_at(frames[0])
    Ut, _ = compositor.clip_uniforms(seq, top, 320, 180, 320, 180)
    s = 2.0 ** (1 - transitions.ease(top.transitions[0].progress))
    assert Ut["u_px_per_uv"] == pytest.approx((320 * s, 180 * s))
    seq, frames = pair("entrada", "emenda")
    jumps = []
    for t in frames + [frames[-1] + 1]:
        U, _ = compositor.clip_uniforms(seq, seq.layers_at(t)[-1], 1920, 1080, 1920, 1080)
        jumps.append(round(-np.array(U["u_xf"]).reshape(3, 3).T[1, 2] * 1080, 6) + 0.0)
    assert jumps == [8.0, 3.0, 0.0]  # px@1080 que a imagem desce na emenda (2 quadros) e depois nada


def test_light_follows_the_film_input():
    assert transitions.light_of(None) == transitions.REC709
    assert transitions.light_of(presets.builtin_values("original"), True) == transitions.REC709
    v = presets.builtin_values("original")
    v.update(entrada="slog3")
    assert transitions.light_of(v, True) == (look.INPUT_IDS["slog3"], True)
    assert transitions.light_of(v, False) == (look.INPUT_IDS["slog3"], False)
    v.update(log_reescalado=True)
    assert transitions.light_of(v, True) == (look.INPUT_IDS["slog3"], False)
    v.update(entrada="logc3", log_reescalado=False)
    assert transitions.light_of(v, True) == (look.INPUT_IDS["logc3"], look.code_value_curve("logc3"))


def test_seed_is_stable_and_params_are_known():
    assert transitions.seed_of("abc") == transitions.seed_of("abc") == zlib.crc32(b"abc") & 0x7FFFFFFF
    assert set(transitions.EXTRA_KEYS) <= editparams.SPARSE_KEYS
    for (side, kind), keys in transitions.PARAMS.items():
        assert kind in (editparams.EXTRA_IN if side == "entrada" else editparams.EXTRA_OUT)
        assert all(k.startswith(side + "_") and k in editparams.VIDEO.params for k in keys)
    assert set(transitions.KIND_IDS) == set(editparams.EXTRA_IN) | set(editparams.EXTRA_OUT)
    assert transitions.TWO_CLIP == editparams.EXTRA_TWO_CLIP
    assert transitions.uses_duration("entrada", "fusao") and not transitions.uses_duration("entrada", "emenda")


def test_module_is_stable_on_in_creator_and_detected_in_a_montage():
    m = modules.get("transicoes")
    assert m.status == modules.ESTAVEL and m.group == "edicao" and modules.default_enabled("transicoes")
    sets = {pid: ids for pid, _n, _d, ids in modules.PROFILES}
    assert "transicoes" not in sets["simples"]
    assert all("transicoes" in sets[p] for p in ("criador", "cinema", "tudo"))
    seq, _a, b = two_clips("dissolver")
    assert "transicoes" not in modules.used_by(None, seq)
    seq.set_values(b.id, {**b.values, "entrada_tipo": "ponta"})
    assert "transicoes" in modules.used_by(None, seq)


# ------------------------------------------------------------------ GPU
W, H = 320, 180


def _img(path: str, depth: int, gray: bool = False) -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    if path == "a.mp4":
        g = x / (W - 1)
        rgb = np.stack([g, g, g], -1) if gray else np.stack([g, 0.3 + 0.4 * (y / (H - 1)), 1 - g], -1)
    else:
        g = 0.1 + 0.8 * y / (H - 1)
        rgb = np.stack([g, g, g], -1) if gray else np.stack([0.2 + 0.6 * ((x // 20) % 2), g, 0.5 * g], -1)
    mx = 255 if depth == 8 else 65535
    return np.rint(rgb * mx).astype(np.uint8 if depth == 8 else np.uint16)


def _frame(seq, t, depth, progress=None, gray=False, only=None):
    layers = seq.layers_at(t)
    if progress is not None:
        layers = [replace(l, transitions=tuple(replace(tr, progress=progress) for tr in l.transitions))
                  for l in layers]
    if only is not None:
        layers = [replace(l, transitions=()) for l in layers if seq.sources[l.clip.src].path == only][:1]
    return sequence.FrameLayers(t, [sequence.LayerImage(l, _img(seq.sources[l.clip.src].path, depth, gray))
                                    for l in layers])


def _compose(engine, seq, fl, depth, light=None):
    return engine.compose(fl, seq, W, H, depth, light=light)


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("side,kind", SIDES)
def test_endpoints_are_the_plain_clips(gl_engine, side, kind, depth):
    seq, frames = pair(side, kind)
    t = frames[len(frames) // 2]
    a_only = _compose(gl_engine, seq, _frame(seq, t, depth, only="a.mp4"), depth)
    b_only = _compose(gl_engine, seq, _frame(seq, t, depth, only="b.mp4"), depth)
    black = np.zeros_like(a_only)
    start = _compose(gl_engine, seq, _frame(seq, t, depth, progress=0.0), depth)
    end = _compose(gl_engine, seq, _frame(seq, t, depth, progress=1.0), depth)
    mid = _compose(gl_engine, seq, _frame(seq, t, depth), depth)
    if side == "entrada":
        assert np.array_equal(end, b_only), "andamento 1: o clipe que entra puro"
        if kind in editparams.EXTRA_TWO_CLIP:
            assert np.array_equal(start, a_only), "andamento 0: só o clipe anterior"
        elif kind == "exposicao":
            assert np.array_equal(start, black), "andamento 0: preto"
        assert not np.array_equal(mid, b_only)
        if kind not in ("emenda", "ponta"):
            assert not np.array_equal(mid, start)
        after = frames[-1] + 1
        assert np.array_equal(_compose(gl_engine, seq, _frame(seq, after, depth), depth),
                              _compose(gl_engine, seq, _frame(seq, after, depth, only="b.mp4"), depth))
    else:
        assert np.array_equal(start, a_only), "andamento 0: o clipe que sai puro"
        assert np.array_equal(end, black), "andamento 1: preto (ou a faixa de baixo, vazia)"
        assert not np.array_equal(mid, a_only) and not np.array_equal(mid, black)


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["iris", "cortina"])
def test_new_transitions_over_a_transparent_background_keep_the_coverage(gl_engine, kind):
    """"Fundo transparente" (frente de alfa): o que a transição ainda não mostrou fica transparente, como no CLIP."""
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    b, = seq.insert_media(src("b.mp4"), at=0)
    seq.trim_end(b.id, 48)
    seq.set_values(b.id, {**b.values, "entrada_tipo": kind, "entrada_dur": 1.0})
    seq.transparent = True
    fl = _frame(seq, 12, 8)
    assert fl.layers[0].layer.transitions
    out = gl_engine.compose(fl, seq, W, H, 8, alpha=True)
    alpha = out[..., 3]
    assert alpha.min() == 0 and alpha.max() == 255           # parte mostrada e parte ainda transparente
    full = gl_engine.compose(_frame(seq, 12, 8, progress=1.0), seq, W, H, 8, alpha=True)
    assert (full[..., 3] == 255).all()                       # andamento 1: o clipe inteiro, opaco
    shown = alpha == 255
    assert np.array_equal(out[..., :3][shown], full[..., :3][shown])


@pytest.mark.gpu
def test_leader_hides_the_clip(gl_engine):
    seq, frames = pair("entrada", "ponta", entrada_ponta="clara")
    t = frames[2]
    one = _compose(gl_engine, seq, _frame(seq, t, 8), 8)
    assert np.array_equal(one, _compose(gl_engine, seq, _frame(seq, t, 8, gray=True), 8))
    assert one.mean() > 150  # ponta clara
    hole = [_compose(gl_engine, seq, _frame(seq, f, 8), 8).max(axis=2).astype(int) for f in frames]
    # o furo de perfuração (luz do projetor, mais clara que a ponta) só no quadro do meio
    assert [int((h >= 235).sum() > 150) for h in hole] == [int(i == len(frames) // 2) for i in range(len(frames))]


@pytest.mark.gpu
@pytest.mark.parametrize("side,kind", SIDES)
def test_mid_frames_are_deterministic(gl_engine, side, kind):
    seq, frames = pair(side, kind)
    again = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    for t in frames[:: max(1, len(frames) // 4)]:
        one = _compose(gl_engine, seq, _frame(seq, t, 16), 16)
        assert np.array_equal(one, _compose(gl_engine, seq, _frame(seq, t, 16), 16))
        assert np.array_equal(one, _compose(gl_engine, again, _frame(again, t, 16), 16)), "projeto reaberto"
    # mais tarde na linha do tempo, o mesmo quadro (a semente é do clipe e o quadro é o da transição)
    late = seq.copy()
    a, b = sorted((c for c in late.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    late.move(b.id, 58)
    late.move(a.id, 10)
    t = frames[len(frames) // 2]
    assert np.array_equal(_compose(gl_engine, seq, _frame(seq, t, 8), 8),
                          _compose(gl_engine, late, _frame(late, t + 10, 8), 8))


@pytest.mark.gpu
@pytest.mark.parametrize("light", [transitions.REC709, (look.INPUT_IDS["slog3"], True),
                                   (look.INPUT_IDS["logc3"], False)])
@pytest.mark.parametrize("side,kind", [s for s in SIDES if s[1] != "queima"])
def test_gray_stays_neutral_at_every_step(gl_engine, side, kind, light):
    """Rampas cinza (no código da curva) continuam cinza em todo quadro: a luz é misturada canal a canal. A
    queima fica de fora de propósito (o brilho dela é laranja)."""
    seq, frames = pair(side, kind, n=6)
    for depth in (8, 16):
        for t in frames:
            out = _compose(gl_engine, seq, _frame(seq, t, depth, gray=True), depth, light)
            assert np.array_equal(out[..., 0], out[..., 1]) and np.array_equal(out[..., 1], out[..., 2]), t


def _slog3_dec(y):
    c = np.asarray(y, dtype=np.float64) * 1023.0
    return np.where(c >= 171.2102946929, 10.0 ** ((c - 420.0) / 261.5) * 0.19 - 0.01,
                    (c - 95.0) * 0.01125 / (171.2102946929 - 95.0))


def _slog3_enc(x):
    x = np.asarray(x, dtype=np.float64)
    return np.where(x >= 0.01125, (420.0 + np.log10(np.maximum(x + 0.01, 1e-10) / 0.19) * 261.5) / 1023.0,
                    (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0)


@pytest.mark.gpu
def test_optical_dissolve_adds_the_light(gl_engine):
    seq, frames = pair("entrada", "fusao", n=3)  # andamentos 1/4, 2/4, 3/4
    a = _img("a.mp4", 16, gray=True)[..., 0] / 65535.0
    b = _img("b.mp4", 16, gray=True)[..., 0] / 65535.0
    for t in frames:
        w = (t - 48 + 1) / 4
        # vídeo comum: a curva de exibição do look
        lin = (1 - w) * 0.18 * 2 ** look._disp_to_stops(a) + w * 0.18 * 2 ** look._disp_to_stops(b)
        want = look._stops_to_disp(np.clip(np.log2(np.maximum(lin, 1e-7) / 0.18), -12, 12))
        got = _compose(gl_engine, seq, _frame(seq, t, 16, gray=True), 16)[..., 0] / 65535.0
        assert np.abs(got - want).max() < 2e-3
        assert (got - ((1 - w) * a + w * b)).mean() > 0.01  # mais claro que a mistura no código
        # S-Log3 (sem faixa legal): a soma das luzes no código da curva
        want = _slog3_enc((1 - w) * _slog3_dec(a) + w * _slog3_dec(b))
        got = _compose(gl_engine, seq, _frame(seq, t, 16, gray=True), 16, (look.INPUT_IDS["slog3"], False))
        assert np.abs(got[..., 0] / 65535.0 - want).max() < 2e-3


@pytest.mark.gpu
def test_exposure_fade_is_a_gain_in_light(gl_engine):
    seq, frames = pair("saida", "exposicao", n=3)
    a = _img("a.mp4", 16, gray=True)[..., 0] / 65535.0
    light = (look.INPUT_IDS["slog3"], True)
    for t in frames:
        g = (48 - t) / 4  # andamento p = 1 − (resto + 1)/(n + 1); a luz fica com 1 − p
        cv = (a * 876 + 64) / 1023  # faixa legal expandida → código de 10 bits
        want = (_slog3_enc(g * _slog3_dec(cv)) * 1023 - 64) / 876
        got = _compose(gl_engine, seq, _frame(seq, t, 16, gray=True), 16, light)[..., 0] / 65535.0
        keep = want > 0.0  # o OUT corta abaixo de 0
        assert np.abs(got[keep] - want[keep]).max() < 2e-3


def _film_sequence(sample_video) -> tl.Sequence:
    """O vídeo de amostra cortado em 8 (queima) e 16 (íris com anel), uma sobreposição na V2 que entra empurrando e
    sai na exposição; chega por JSON, como no app."""
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    seq.split(8)
    seq.split(16)
    v = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    seq.set_values(v[1].id, {**v[1].values, "entrada_tipo": "queima", "entrada_dur": 0.25, "exposicao": 0.3})
    seq.set_values(v[2].id, {**v[2].values, "entrada_tipo": "iris", "entrada_dur": 0.2, "entrada_anel": 20.0})
    over, = seq.insert_media(src, at=3, vtrack=1, with_audio=False)
    seq.trim_end(over.id, 14)
    seq.set_values(over.id, {**over.values, "escala": 0.5, "pos_x": 0.2, "opacidade": 0.8, "entrada_tipo": "empurrar",
                             "entrada_dur": 0.2, "saida_tipo": "exposicao", "saida_dur": 0.2})
    return tl.Sequence.from_json(seq.to_json())


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_preview_and_export_give_the_same_frames(gl_engine, ffmpeg_ok, sample_video, tmp_path):
    from helpers import read_all
    from pelicula import export, frame
    from pelicula.export import ExportJob, ExportSettings
    seq = _film_sequence(sample_video)
    assert "transicoes" in seq.features()
    film = presets.builtin_values("vision3_500t")
    info = sequence.media_info(seq)
    w, h = sequence.canvas_size(seq)
    settings = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)
    job = ExportJob(info=info, values=film, settings=settings, out_path=str(tmp_path / "t.mkv"), start_frame=2,
                    end_frame=19, sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(tmp_path / "t.mkv"))
    exported = read_all(media.FrameReader(o, o.width, o.height, 16))
    recipe = frame.Recipe.for_source(film, info.fps, 16, legal=sequence.legal_range(seq), seq=seq, size=(w, h))
    for n in (3, 5, 9, 12, 16, 17, 19):
        ref = exported[n - 2]
        assert np.array_equal(export.preview_frame(gl_engine, info, film, settings, n, seq=seq, depth=16), ref), n
        assert np.array_equal(recipe.render(gl_engine, sequence.grab(seq, n, w, h, 16, hq=True), n), ref), n
    # 8 bits (a prévia do modo Edição sem película): a leitura em sequência dá a montagem do quadro avulso
    only = frame.Recipe.for_source(None, info.fps, 8, legal=True, seq=seq, size=(w, h))
    reader = sequence.SequenceReader(seq, w, h, 8, start=2, count=18)
    try:
        while (fl := reader.read()) is not None:
            assert np.array_equal(only.montage(gl_engine, fl), only.montage(gl_engine, sequence.grab(seq, fl.frame,
                                                                                                    w, h, 8))), fl.frame
    finally:
        reader.close()
    # a mesma montagem em 16 bits sem película é a do look "Original" (a mesma luz, rec709)
    layers = sequence.grab(seq, 10, w, h, 16)
    assert np.array_equal(only.with_(depth=16).montage(gl_engine, layers),
                          only.with_(depth=16, values=presets.builtin_values("original")).montage(gl_engine, layers))


@pytest.mark.gpu
def test_old_transitions_render_the_same_bits_as_the_base(gl_engine):
    """Na mesma placa e driver em que a referência foi gravada, os quadros das transições antigas são os da
    BASE bit a bit (em outra placa, as camadas, os uniforms e o texto do shader acima já garantem)."""
    if gl_engine.renderer != REF["renderer"]:
        pytest.skip(f"referência gravada em {REF['renderer']}")
    assert base.frame_hashes(gl_engine, base.scenario()) == REF["quadros"]
