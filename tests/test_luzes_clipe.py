"""1.9 F4: desfoque de lente, listra anamórfica, flares e raios de luz (`luzes_clipe.py`; ARQUITETURA §52).

Sem GPU: padrões neutros, ordem na pilha, módulo, a entrada do efeito ("orig" ou a cópia). Na GPU: desligado = nenhum
passo e bit a bit; abaixo do limiar nada muda (bit a bit); direção da listra e dos raios; fantasmas na linha da luz ao
centro; energia somada e conservada no desfoque (na luz linear); máscara pelo degradê e pelo gancho da F2; entrada certa
depois de outro efeito; camada de ajuste, gêmea aninhada e prévia == exportação.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import editparams, luzes_clipe, modules, sequence, vfx
from pelicula import timeline as tl

W, H = 96, 54
KIND = "gerador"
LINEAR = (1, False)  # luz linear: o código é a própria luz (as contas de energia ficam simples)


def gen(seq, clip, frame, w, h, depth):
    """Fundo chapado (ou degradê) com quadrados claros: `pontos` = [(x, y, lado, valor)] em pixels."""
    data = seq.sources[clip.src].data
    flat = data.get("chapada")
    if flat is not None:
        img = np.array(np.broadcast_to(np.array(flat, np.float64), (h, w, 3)))
    else:
        x, y = np.meshgrid(np.linspace(0.05, 0.95, w), np.linspace(0.1, 0.9, h))
        img = np.stack([0.3 + 0.5 * x, 0.2 + 0.6 * y, 0.6 - 0.4 * x * y], axis=2)
    for x, y, side, val in data.get("pontos", []):
        img[y:y + side, x:x + side] = val
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def one_clip(values=None, flat=None, points=()):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    data = {"nome": "Teste", "pontos": [list(p) for p in points]}
    if flat is not None:
        data["chapada"] = list(flat)
    src = tl.Source.virtual(KIND, W, H, "24/1", seconds=2.0, data=data, alpha=False)
    c = seq.insert_media(src, at=0)[0]
    if values:
        seq.set_values(c.id, values)
    return seq, c


def compose(engine, seq, t=3, depth=16, light=None, neutral=False):
    return engine.compose(sequence.grab(seq, t, W, H, depth), seq, W, H, depth, neutral=neutral, light=light)


def added(engine, values, light=LINEAR, **kw):
    """(com o efeito − sem ele) em float, 16 bits."""
    a = compose(engine, one_clip(values, **kw)[0], light=light).astype(np.float64) / 65535
    b = compose(engine, one_clip(None, **kw)[0], light=light).astype(np.float64) / 65535
    return a - b


def fx_targets(engine):
    return {k for k in engine._targets if str(k).startswith("fx")}


STREAK = {"listra_intensidade": 1.0, "listra_limiar": 0.0, "listra_cor": [1.0, 1.0, 1.0],
          "listra_comprimento": 200.0}
RAYS = {"raios_intensidade": 1.0, "raios_limiar": 0.0, "raios_x": 0.0, "raios_y": -540.0, "raios_comprimento": 1.0,
        "raios_cor": [1.0, 1.0, 1.0]}
FLARE = {"flare_intensidade": 1.0, "flare_limiar": 0.0, "flare_fantasmas": 8}
DOF = {"desfoque_lente_raio": 120.0}  # 6 texels numa tela de 54 linhas
DARK = (0.02, 0.02, 0.02)


# ------------------------------------------------------------------ sem GPU
def test_defaults_are_neutral_and_the_order_is_canonical():
    d = editparams.VIDEO.defaults()
    keys = luzes_clipe.DOF_KEYS + luzes_clipe.STREAK_KEYS + luzes_clipe.FLARE_KEYS + luzes_clipe.RAYS_KEYS
    assert all(k in d and k in editparams.SPARSE_KEYS for k in keys)
    assert vfx.active_effects(d) == []
    v = editparams.VIDEO.sanitize({**STREAK, **RAYS, **FLARE, **DOF})
    assert [e.id for e in vfx.active_effects(v)] == ["desfoque_lente", "listra", "flare", "raios"]
    assert vfx.ORDER["desfoque_lente"] < luzes_clipe.STREAK_EFFECT.order < luzes_clipe.RAYS_EFFECT.order \
        < vfx.ORDER["nevoa"]
    assert set(vfx.EFFECT_MODULES["luzes_lente"]) == {"desfoque_lente", "listra", "flare", "raios"}
    m = next(m for m in modules.MODULES if m.id == "luzes_lente")
    assert m.group == "efeitos_visuais" and m.status == modules.BETA and not modules.default_enabled(m.id)
    assert luzes_clipe.threshold(1.0) == pytest.approx(0.36)


def test_entry_is_the_original_only_when_first():
    seq, c = one_clip(STREAK)
    ctx = vfx.Ctx(seq, seq.layers_at(0)[0], 0, W, H, W, H)
    assert luzes_clipe.entry(ctx, "listra") == ("orig", [])
    names = [p.name for p in luzes_clipe.streak_passes(ctx)]
    assert names == ["brilho", "longa", "curta", "soma"]
    seq.set_values(c.id, {**STREAK, **DOF})
    ctx = vfx.Ctx(seq, seq.layers_at(0)[0], 0, W, H, W, H)
    ref, passes = luzes_clipe.entry(ctx, "listra")
    assert ref == "pass:entrada" and [p.name for p in passes] == ["entrada"]
    assert luzes_clipe.entry(ctx, "desfoque_lente") == ("orig", [])


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_off_runs_no_pass_and_is_bit_exact(gl_engine, renderer, depth):
    seq, c = one_clip()
    plain = compose(gl_engine, seq, depth=depth)
    targets = fx_targets(gl_engine)
    seq.set_values(c.id, {"listra_limiar": 0.0, "flare_fonte": "ponto", "raios_comprimento": 1.0,
                          "desfoque_lente_mascara": "degrade", "desfoque_lente_forma": "hexagono"})
    assert np.array_equal(compose(gl_engine, seq, depth=depth), plain)
    assert fx_targets(gl_engine) == targets


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_nothing_changes_below_the_threshold(gl_engine, renderer, depth):
    seq, c = one_clip()
    plain = compose(gl_engine, seq, depth=depth)
    seq.set_values(c.id, {"listra_intensidade": 2.0, "flare_intensidade": 2.0, "raios_intensidade": 2.0,
                          "listra_limiar": 3.0, "flare_limiar": 3.0, "raios_limiar": 3.0})
    assert np.array_equal(compose(gl_engine, seq, depth=depth), plain)
    ran = {t.split("_")[1] for t in fx_targets(gl_engine) if t.startswith("fx0_")}  # os passos rodaram
    assert {"listra", "flare", "raios"} <= ran


@pytest.mark.gpu
def test_streak_goes_in_its_direction_and_adds_the_extracted_energy(gl_engine, renderer):
    dot = [(46, 26, 4, 0.6)]
    d = added(gl_engine, STREAK, flat=DARK, points=dot)
    assert d.min() >= -1e-5
    assert d[27, 46 + 15, 1] > 1e-4 and d[27, 46 - 12, 1] > 1e-4
    assert np.abs(d[:21]).max() == 0 and np.abs(d[34:]).max() == 0
    # Luz somada = a extraída: 4 × 4 pixels de 0,6 com limiar 0 (0,18) e o limite suave de 3 stops acima dele.
    e = 0.6 - 0.18
    e = e / (1 + e / (0.18 * 2 ** luzes_clipe.LIGHT_CLAMP_STOPS))
    assert d[..., 1].sum() == pytest.approx(16 * e, rel=0.05)
    v = added(gl_engine, {**STREAK, "listra_angulo": 90.0}, flat=DARK, points=dot)
    assert v[27 + 12, 47, 1] > 1e-4 and np.abs(v[:, :40]).max() == 0 and np.abs(v[:, 55:]).max() == 0
    tinted = added(gl_engine, {**STREAK, "listra_cor": [0.2, 0.5, 1.0]}, flat=DARK, points=dot)
    s = tinted.sum(axis=(0, 1))
    assert s[0] < s[1] < s[2] and s[2] == pytest.approx(d[..., 2].sum(), rel=0.02)


@pytest.mark.gpu
def test_rays_leave_the_light_away_from_their_origin(gl_engine, renderer):
    d = added(gl_engine, RAYS, flat=DARK, points=[(46, 25, 4, 0.8)])[..., 1]
    assert d.min() >= -1e-5
    assert d[36:50, 46:50].min() > 0  # abaixo da luz (a origem está em cima, no meio)
    assert np.abs(d[:22]).max() == 0
    assert d[40, 47] > d[40, 20]


@pytest.mark.gpu
def test_auto_flare_ghosts_lie_on_the_line_through_the_centre(gl_engine, renderer):
    src = (72, 12)
    d = added(gl_engine, FLARE, flat=DARK, points=[(src[0] - 2, src[1] - 2, 4, 1.0)])[..., 1]
    assert d.min() >= -1e-5
    yy, xx = np.mgrid[0:H, 0:W]
    far = np.hypot(xx - src[0], yy - src[1]) > 12
    w = np.where(far, d, 0.0)
    assert w.sum() > 0
    # Distância de cada pixel à reta luz–centro, ponderada pela luz somada: os fantasmas ficam nela.
    c = np.array([W / 2, H / 2])
    u = (np.array(src, float) - c) / np.hypot(*(np.array(src, float) - c))
    dist = np.abs((xx + 0.5 - c[0]) * u[1] - (yy + 0.5 - c[1]) * u[0])
    assert (w * dist).sum() / w.sum() < 6.0
    # O primeiro fantasma de escala −1,25 cai do outro lado do centro.
    p = c + (np.array(src, float) - c) / -1.25
    assert d[int(p[1]) - 2:int(p[1]) + 3, int(p[0]) - 2:int(p[0]) + 3].max() > 1e-4


@pytest.mark.gpu
def test_point_flare_does_not_read_the_image(gl_engine, renderer):
    values = {"flare_intensidade": 0.3, "flare_fonte": "ponto", "flare_x": 500.0, "flare_y": -300.0}
    a = added(gl_engine, values, flat=(0.1, 0.1, 0.1))
    b = added(gl_engine, values, flat=(0.3, 0.2, 0.1))
    assert np.abs(a - b).max() < 2e-4
    x = int((500 / (W / H * 1080) + 0.5) * W)
    y = int((-300 / 1080 + 0.5) * H)
    assert a[y, x, 1] > 0.5 * a[..., 1].max() and a.min() >= -1e-5


@pytest.mark.gpu
def test_lens_blur_keeps_flat_color_spreads_a_disc_and_conserves_light(gl_engine, renderer):
    d = added(gl_engine, DOF, flat=(0.25, 0.25, 0.25))
    assert np.abs(d).max() <= 2 / 65535
    dot = [(46, 25, 2, 1.0)]
    d = added(gl_engine, DOF, flat=DARK, points=dot)[..., 1]
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx + 0.5 - 47, yy + 0.5 - 26)
    assert d[r < 1].max() < 0 and d[(r > 2) & (r < 5)].min() > 0 and np.abs(d[r > 11]).max() < 1e-4
    assert d.sum() == pytest.approx(0.0, abs=0.02 * 4 * 0.98)  # a luz só muda de lugar
    assert d[r > 4].sum() > 0.5 * 4 * 0.98 * 0.3
    hexa = added(gl_engine, {**DOF, "desfoque_lente_forma": "hexagono"}, flat=DARK, points=dot)[..., 1]
    assert not np.array_equal(hexa, d) and hexa.sum() == pytest.approx(0.0, abs=0.08)


@pytest.mark.gpu
def test_lens_blur_by_the_gradient_keeps_the_other_side_sharp(gl_engine, renderer):
    values = {**DOF, "desfoque_lente_mascara": "degrade", "desfoque_lente_suavidade": 0.0}
    seq, c = one_clip(values)
    plain = compose(gl_engine, one_clip()[0])
    got = compose(gl_engine, seq)
    assert np.array_equal(got[H // 2 + 1:], plain[H // 2 + 1:])  # embaixo (0° = em cima desfoca): nítido
    assert not np.array_equal(got[:H // 2 - 8], plain[:H // 2 - 8])
    seq.set_values(c.id, {**values, "desfoque_lente_inverter": True})
    got = compose(gl_engine, seq)
    assert np.array_equal(got[:H // 2 - 1], plain[:H // 2 - 1])


@pytest.mark.gpu
def test_shape_mask_hook_for_the_masks_front(gl_engine, renderer, monkeypatch):
    """O gancho da F2: um provedor de máscara (passos que deixam a máscara no canal r) decide onde desfocar."""
    left = vfx.Pass("mascara_teste", "void main() { f_out = vec4(v_uv.x < 0.5 ? 1.0 : 0.0, 0.0, 0.0, 1.0); }",
                    dtype="f2")
    monkeypatch.setitem(luzes_clipe.MASK_SOURCES, "degrade", lambda ctx: [left])
    seq, c = one_clip({**DOF, "desfoque_lente_mascara": "degrade"})
    plain = compose(gl_engine, one_clip()[0])
    got = compose(gl_engine, seq)
    assert np.array_equal(got[:, W // 2 + 1:], plain[:, W // 2 + 1:])
    assert not np.array_equal(got[:, :W // 2 - 8], plain[:, :W // 2 - 8])


@pytest.mark.gpu
def test_lens_blur_inside_or_outside_the_clip_shape_mask(gl_engine, renderer):
    """A máscara de forma da F2 ligada ao gancho (integração): um retângulo na metade esquerda com o uso "Nada (só a
    forma)" não recorta nada sozinho; "dentro" desfoca só a esquerda e "fora" só a direita."""
    shape = {"mascara_forma": "retangulo", "mascara_uso": "so_forma", "mascara_x": -2000.0, "mascara_y": 0.0,
             "mascara_largura": 4000.0, "mascara_altura": 4000.0, "mascara_suavidade": 0.0}
    plain = compose(gl_engine, one_clip()[0])
    assert np.array_equal(compose(gl_engine, one_clip(shape)[0]), plain)  # só a forma: nenhum passo
    inside = compose(gl_engine, one_clip({**DOF, **shape, "desfoque_lente_mascara": "dentro_mascara"})[0])
    assert np.array_equal(inside[:, W // 2 + 1:], plain[:, W // 2 + 1:])
    assert not np.array_equal(inside[:, :W // 2 - 8], plain[:, :W // 2 - 8])
    outside = compose(gl_engine, one_clip({**DOF, **shape, "desfoque_lente_mascara": "fora_mascara"})[0])
    assert np.array_equal(outside[:, :W // 2 - 1], plain[:, :W // 2 - 1])
    assert not np.array_equal(outside[:, W // 2 + 8:], plain[:, W // 2 + 8:])
    no_shape = compose(gl_engine, one_clip({**DOF, "desfoque_lente_mascara": "dentro_mascara"})[0])
    assert np.array_equal(no_shape, compose(gl_engine, one_clip(DOF)[0]))  # sem forma: a imagem inteira


INVERT = "void main() { vec4 c = texture(t_prev, v_uv); f_out = vec4(1.0 - c.rgb, c.a); }"


@pytest.mark.gpu
def test_after_another_effect_the_entry_is_that_effects_output(gl_engine, renderer):
    """Com um efeito antes (inverte as cores), a listra soma sobre a imagem invertida, não sobre a original."""
    eff = vfx.register(vfx.Effect("teste_inverte", "efeitos_visuais", vfx.ORDER["recorte"],
                                  active=lambda v: v.get("listra_intensidade", 0) > 0,
                                  passes=lambda ctx: [vfx.Pass("inv", INVERT)]))
    try:
        got = compose(gl_engine, one_clip(STREAK, flat=(0.98, 0.98, 0.98), points=[(46, 26, 4, 0.4)])[0], light=LINEAR)
    finally:
        vfx.unregister(eff.id)
    ref = compose(gl_engine, one_clip(STREAK, flat=(0.02, 0.02, 0.02), points=[(46, 26, 4, 0.6)])[0], light=LINEAR)
    assert int(np.abs(got.astype(np.int64) - ref.astype(np.int64)).max()) <= 2


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_adjustment_layer_equals_the_effect_on_a_full_frame_clip(gl_engine, renderer, depth):
    values = {**DOF, **STREAK, "flare_intensidade": 0.5}
    seq, low = one_clip(points=[(30, 10, 4, 1.0)])
    adj = seq.insert_media(vfx.new_adjustment(seq), at=0, vtrack=1)[0]
    seq.set_values(adj.id, values)
    got = compose(gl_engine, seq, depth=depth)
    ref = compose(gl_engine, one_clip(values, points=[(30, 10, 4, 1.0)])[0], depth=depth)
    assert int(np.abs(got.astype(np.int64) - ref.astype(np.int64)).max()) <= 1


ALL = {**DOF, **STREAK, **RAYS, "flare_intensidade": 0.6}


@pytest.mark.gpu
def test_nested_twin_is_bit_exact(gl_engine, renderer):
    flat, c = one_clip(ALL, points=[(60, 8, 4, 1.0)])
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
    outer.ensure_set().add(inner)
    outer.siblings.sync()
    outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=0)
    for depth in (8, 16):
        assert np.array_equal(compose(gl_engine, flat, depth=depth), compose(gl_engine, outer, depth=depth)), depth


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, renderer):
    from pelicula import export, media
    from pelicula.frame import Recipe
    seq, c = one_clip(ALL, points=[(60, 8, 4, 1.0)])
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(3)]
    finally:
        reader.close()
    for t in range(3):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), t
