"""1.9 F4: partículas e névoa (`atmosfera.py`; ARQUITETURA §52).

Sem GPU: padrões neutros e esparsos, formato 7, ordem na pilha, módulo, deslocamentos no período. Na GPU: desligado =
nenhum passo e bit a bit; determinismo pelo tempo do clipe (o mesmo quadro sempre, dividir no meio não muda nada),
px@1080 em duas resoluções, limites de energia, névoa pelo degradê e pela cor, camada de ajuste == clipe de tela cheia,
gêmea aninhada e prévia == exportação.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pelicula import atmosfera, editparams, modules, sequence, vfx
from pelicula import timeline as tl

W, H = 96, 54
KIND = "gerador"
FLAT = {"cor": None}  # cor chapada (0 a 1) ou None = degradê


def gen(seq, clip, frame, w, h, depth):
    """Degradê (ou cor chapada) que não muda com o quadro: só os efeitos mudam no tempo."""
    src = seq.sources[clip.src]
    flat = src.data.get("chapada")
    if flat is not None:
        img = np.broadcast_to(np.array(flat, np.float64), (h, w, 3))
    else:
        x, y = np.meshgrid(np.linspace(0.05, 0.95, w), np.linspace(0.1, 0.9, h))
        img = np.stack([0.3 + 0.5 * x, 0.2 + 0.6 * y, 0.6 - 0.4 * x * y], axis=2)
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def vsrc(w=W, h=H, flat=None, seconds=4.0):
    data = {"nome": "Teste"}
    if flat is not None:
        data["chapada"] = list(flat)
    return tl.Source.virtual(KIND, w, h, "24/1", seconds=seconds, data=data, alpha=False)


def one_clip(values=None, w=W, h=H, flat=None):
    seq = tl.Sequence(width=w, height=h, fps_str="24/1")
    c = seq.insert_media(vsrc(w, h, flat), at=0)[0]
    if values:
        seq.set_values(c.id, values)
    return seq, c


def setv(seq, c, **values):
    """Muda só estes ajustes (`Sequence.set_values` troca todos)."""
    seq.set_values(c.id, {**c.values, **values})


def compose(engine, seq, t=5, depth=16, w=None, h=None, neutral=False, light=None):
    w, h = w or seq.width, h or seq.height
    return engine.compose(sequence.grab(seq, t, w, h, depth), seq, w, h, depth, neutral=neutral, light=light)


def fx_targets(engine):
    return {k for k in engine._targets if str(k).startswith("fx")}


RAIN = {"part_tipo": "chuva", "part_quantidade": 0.8}
SNOW = {"part_tipo": "neve", "part_quantidade": 0.8, "part_tamanho": 20.0}
EMBERS = {"part_tipo": "brasas", "part_quantidade": 1.0, "part_tamanho": 16.0}
FOG = {"nevoa_densidade": 0.7}


# ------------------------------------------------------------------ sem GPU
def test_defaults_are_neutral_sparse_and_off():
    d = editparams.VIDEO.defaults()
    keys = atmosfera.PARTICLE_KEYS + atmosfera.FOG_KEYS
    assert all(k in d and k in editparams.SPARSE_KEYS for k in keys)
    assert not atmosfera.particles_active(d) and not atmosfera.fog_active(d)
    assert vfx.active_effects(d) == []
    seq, c = one_clip()
    assert not set(keys) & set(editparams.stored_values("video", c.values))
    assert "ajustes_clipe_1_9" not in seq.features()
    seq.set_values(c.id, {"part_tipo": "neve"})
    assert "ajustes_clipe_1_9" in seq.features() and seq.block_format() == tl.FORMAT


def test_effects_order_and_module():
    v = editparams.VIDEO.sanitize({**RAIN, **FOG})
    assert [e.id for e in vfx.active_effects(v)] == ["nevoa", "particulas"]
    assert vfx.ORDER["nevoa"] == atmosfera.FOG_EFFECT.order < atmosfera.PARTICLES_EFFECT.order
    assert set(vfx.EFFECT_MODULES["atmosfera"]) == {"nevoa", "particulas"}
    m = next(m for m in modules.MODULES if m.id == "atmosfera")
    assert m.group == "efeitos_visuais" and m.status == modules.BETA
    assert not modules.default_enabled("atmosfera")
    seq, c = one_clip(RAIN)
    assert "atmosfera" in vfx.modules_used(seq)
    seq2, c2 = one_clip()
    assert seq2.set_key(c2.id, "nevoa_densidade", 0, 0.0)  # uma chave (mesmo em 0) já conta para o aviso
    assert "atmosfera" in vfx.modules_used(seq2)


def test_layer_offsets_stay_in_the_period_for_long_clips():
    v = editparams.VIDEO.sanitize(RAIN)
    near = atmosfera.particle_layers(v, 10.0, 24.0)
    assert near["dir"] == (0.0, 1.0) and near["off"][0] == pytest.approx(1600.0 * 10.0)
    far = atmosfera.particle_layers(v, 7 * 3600.0, 24.0)
    for off, cb in zip(far["off"], far["cb"]):
        assert 0.0 <= off < atmosfera.GRID_PERIOD * cb
    # O mundo anda velocidade × tempo: a diferença entre dois instantes não perde precisão em horas de clipe.
    a = atmosfera.particle_layers(v, 7 * 3600.0, 24.0)["off"][0]
    b = atmosfera.particle_layers(v, 7 * 3600.0 + 1 / 24, 24.0)["off"][0]
    assert math.isclose((b - a) % (atmosfera.GRID_PERIOD * far["cb"][0]), 1600.0 / 24, rel_tol=1e-6)
    wind = atmosfera.particle_layers(editparams.VIDEO.sanitize({**RAIN, "part_vento": 1.0}), 0.0, 24.0)
    assert wind["dir"][0] > 0.4 and wind["dir"][1] > 0.0
    deep = atmosfera.particle_layers(editparams.VIDEO.sanitize({**RAIN, "part_profundidade": 1.0}), 0.0, 24.0)
    assert deep["scale"][0] == 1.0 and deep["scale"][2] == pytest.approx(1 - atmosfera.DEPTH_SCALE)
    assert deep["alpha"][2] < deep["alpha"][0]
    o1, o2 = atmosfera.fog_offsets(editparams.VIDEO.sanitize({**FOG, "nevoa_movimento": 100.0}), 9 * 3600.0)
    assert 0 <= o1[0] < atmosfera.NOISE_PERIOD and 0 <= o2[0] < atmosfera.NOISE_PERIOD


def test_cell_layout_does_not_follow_animated_params():
    """Só quantidade, opacidade e cor das partículas animam: tamanho, rastro e velocidade mudam a grade."""
    anim = {k for k, p in editparams.VIDEO.params.items() if p.animatable}
    assert {"part_quantidade", "part_opacidade", "part_cor", "nevoa_densidade", "nevoa_cor"} <= anim
    assert not anim & {"part_tamanho", "part_desfoque", "part_velocidade", "part_vento", "part_profundidade",
                       "nevoa_movimento", "nevoa_escala", "part_tipo", "part_semente"}


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_off_runs_no_pass_and_is_bit_exact(gl_engine, renderer, depth):
    seq, c = one_clip()
    plain = compose(gl_engine, seq, depth=depth)
    targets = fx_targets(gl_engine)
    seq.set_values(c.id, {"part_quantidade": 1.0, "part_tamanho": 30.0, "nevoa_textura": 1.0, "nevoa_cor": [1, 0, 0]})
    assert np.array_equal(compose(gl_engine, seq, depth=depth), plain)
    assert fx_targets(gl_engine) == targets


@pytest.mark.gpu
def test_particles_are_deterministic_and_follow_the_clip_time(gl_engine, renderer):
    seq, c = one_clip(SNOW)
    plain = compose(gl_engine, one_clip()[0])
    a = compose(gl_engine, seq, t=7)
    assert not np.array_equal(a, plain)
    assert np.array_equal(compose(gl_engine, seq, t=7), a)
    assert not np.array_equal(compose(gl_engine, seq, t=8), a)
    setv(seq, c, part_semente=2)
    assert not np.array_equal(compose(gl_engine, seq, t=7), a)
    setv(seq, c, part_semente=1)
    # Dividir o clipe no meio não muda nenhum quadro (o tempo do clipe das chaves continua).
    whole = [compose(gl_engine, seq, t=t) for t in (3, 20, 21, 40)]
    seq.split(20, [c.id])
    assert len(seq.clips) == 2
    assert all(np.array_equal(compose(gl_engine, seq, t=t), ref) for t, ref in zip((3, 20, 21, 40), whole))


@pytest.mark.gpu
def test_particles_keep_their_size_in_px_at_1080(gl_engine, renderer):
    """A mesma neve em 384 × 216 e em 576 × 324: as mesmas manchas no mesmo lugar, do mesmo tamanho relativo."""
    got = []
    for w, h in ((384, 216), (576, 324)):
        seq, c = one_clip({**SNOW, "part_desfoque": 0.0, "part_profundidade": 0.0, "part_tamanho": 40.0},
                          w, h, flat=(0.2, 0.2, 0.2))
        img = compose(gl_engine, seq, t=6).astype(np.float64)[..., 1] / 65535
        cover = img - 0.2
        k = w // 48  # blocos até 48 × 27
        got.append(cover.reshape(27, h // 27, 48, k).mean(axis=(1, 3)))
    a, b = got
    assert a.mean() > 0.01
    assert abs(a.mean() - b.mean()) < 0.06 * a.mean()
    assert np.corrcoef(a.ravel(), b.ravel())[0, 1] > 0.95


@pytest.mark.gpu
def test_energy_bounds(gl_engine, renderer):
    lin = (1, False)  # luz linear: o código é a própria luz
    # Neve cobre: cada pixel fica entre o fundo e a luz da neve.
    seq, c = one_clip({**SNOW, "part_opacidade": 1.0}, flat=(0.3, 0.3, 0.3))
    img = compose(gl_engine, seq, light=lin).astype(np.float64) / 65535
    snow = np.array(atmosfera.TYPES["neve"]["light"])
    assert img.min() >= 0.3 - 1e-4 and (img <= np.maximum(0.3, snow) + 1e-4).all()
    assert (img > 0.31).mean() > 0.005
    # Brasas somam luz: nunca escurecem, e somam no máximo a luz delas por pixel (cada uma uma vez).
    seq, c = one_clip({**EMBERS, "part_opacidade": 1.0}, flat=(0.05, 0.05, 0.05))
    img = compose(gl_engine, seq, light=lin, depth=16).astype(np.float64) / 65535
    assert img.min() >= 0.05 - 1e-4 and (img > 0.06).any()
    added = (img - 0.05).mean(axis=(0, 1))
    assert added[0] >= added[1] >= added[2] and added[0] < 0.5


@pytest.mark.gpu
def test_fog_by_gradient_color_and_motion(gl_engine, renderer):
    seq, c = one_clip({"nevoa_densidade": 1.0, "nevoa_textura": 0.0, "nevoa_forma": "uniforme",
                       "nevoa_cor": [0.7, 0.4, 0.2]}, flat=(0.1, 0.5, 0.9))
    img = compose(gl_engine, seq, depth=8).astype(np.int64)
    assert np.abs(img - np.array([0.7 * 255, 0.4 * 255, 0.2 * 255])).max() <= 1  # a cor do vídeo Rec.709
    # Degradê no chão (180°): embaixo mais névoa que em cima; nada na ponta de cima com pouca suavidade.
    seq, c = one_clip({"nevoa_densidade": 0.8, "nevoa_textura": 0.0, "nevoa_suavidade": 200.0})
    plain = compose(gl_engine, one_clip()[0])
    img = compose(gl_engine, seq)
    diff = np.abs(img.astype(np.int64) - plain.astype(np.int64)).sum(axis=2)
    assert diff[:5].max() == 0 and diff[-5:].min() > 1000
    # Com textura, as nuvens andam com o movimento; paradas sem ele.
    setv(seq, c, nevoa_textura=1.0, nevoa_movimento=0.0)
    assert np.array_equal(compose(gl_engine, seq, t=2), compose(gl_engine, seq, t=30))
    setv(seq, c, nevoa_movimento=200.0)
    assert not np.array_equal(compose(gl_engine, seq, t=2), compose(gl_engine, seq, t=30))
    assert np.array_equal(compose(gl_engine, seq, t=30), compose(gl_engine, seq, t=30))


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_adjustment_layer_equals_the_effect_on_a_full_frame_clip(gl_engine, renderer, depth):
    values = {**RAIN, **FOG, "nevoa_textura": 0.8}
    seq, low = one_clip()
    adj = seq.insert_media(vfx.new_adjustment(seq), at=0, vtrack=1)[0]
    seq.set_values(adj.id, values)
    got = compose(gl_engine, seq, t=9, depth=depth)
    ref = compose(gl_engine, one_clip(values)[0], t=9, depth=depth)
    assert int(np.abs(got.astype(np.int64) - ref.astype(np.int64)).max()) <= 1


@pytest.mark.gpu
def test_nested_twin_with_particles_is_bit_exact(gl_engine, renderer):
    flat, c = one_clip({**SNOW, **FOG})
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
    outer.ensure_set().add(inner)
    outer.siblings.sync()
    outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=0)
    for t in (0, 11):
        assert np.array_equal(compose(gl_engine, flat, t), compose(gl_engine, outer, t)), t


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, renderer):
    from pelicula import export, media
    from pelicula.frame import Recipe
    seq, c = one_clip({**RAIN, **FOG, "nevoa_textura": 1.0, "nevoa_movimento": 80.0})
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(5)]
    finally:
        reader.close()
    for t in range(5):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), t
