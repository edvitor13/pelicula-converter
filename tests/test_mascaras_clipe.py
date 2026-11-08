"""1.9: máscara de forma do clipe (`mascaras_clipe.py`, ARQUITETURA §50).

Distância com sinal em numpy (retângulo, elipse, polígono), a GPU == numpy, borda e passagem em px@1080 iguais a 540 e
a 1080 linhas, inverter, desfocar e pixelar só dentro, a forma presa ao enquadramento do clipe, os pontos do polígono
no JSON ("efeitos") e no formato 7, desligada = bit a bit, prévia == exportação com o centro animado.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import editparams, mascaras_clipe as mk, sequence, vfx
from pelicula import timeline as tl

W, H = 96, 54
KIND = "gerador"


def gen(seq, clip, frame, w, h, depth):
    """Xadrez de 6 px sobre um degradê: o desfoque e o pixelado mudam a imagem."""
    yy, xx = np.mgrid[0:h, 0:w]
    check = ((xx // 6 + yy // 6) % 2).astype(np.float64)
    img = np.stack([0.2 + 0.6 * check, 0.3 + 0.4 * xx / w, 0.7 - 0.5 * check], axis=-1)
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


def flat(seq, clip, frame, w, h, depth):
    img = np.ones((h, w, 3)) * np.array(seq.sources[clip.src].data.get("cor", [0.1, 0.8, 0.2]))
    mx = 255 if depth == 8 else 65535
    return np.rint(img * mx).astype(np.uint8 if depth == 8 else np.uint16)


def render(seq, clip, frame, w, h, depth):
    fn = flat if seq.sources[clip.src].data.get("liso") else gen
    return fn(seq, clip, frame, w, h, depth)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, render)


def src(w=W, h=H, **data):
    return tl.Source.virtual(KIND, w, h, "24/1", seconds=2.0, data={"nome": "Teste", **data}, alpha=False)


def masked(w=W, h=H, transparent=True, points=None, **values):
    seq = tl.Sequence(width=w, height=h, fps_str="24/1", transparent=transparent)
    c = seq.insert_media(src(w, h), at=0)[0]
    seq.set_values(c.id, {**c.values, **values})
    if points is not None:
        mk.set_points(seq.find(c.id), points)
    return seq, seq.find(c.id)


def rgba(engine, seq, t=3, depth=16, w=W, h=H):
    out = engine.compose(sequence.grab(seq, t, w, h, depth), seq, w, h, depth, alpha=True)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


def opaque(engine, seq, t=3, depth=16, w=W, h=H):
    out = engine.compose(sequence.grab(seq, t, w, h, depth), seq, w, h, depth)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


def V(**kw):
    return editparams.VIDEO.defaults() | kw


# ------------------------------------------------------------------ sem GPU
def test_params_are_neutral_and_sparse():
    v = editparams.VIDEO.defaults()
    assert not mk.active(v) and vfx.active_effects(v) == [] and not vfx.makes_alpha(v)
    assert all(k in editparams.SPARSE_KEYS for k in mk.KEYS)
    assert all(editparams.VIDEO.params[k].animatable for k in ("mascara_x", "mascara_y", "mascara_largura",
                                                               "mascara_altura", "mascara_rotacao"))
    assert vfx.makes_alpha(V(mascara_forma="elipse")) and not vfx.makes_alpha(V(mascara_forma="elipse",
                                                                                 mascara_uso="desfocar"))


def test_signed_distances():
    rect = V(mascara_forma="retangulo", mascara_largura=200, mascara_altura=100)
    assert mk.distance([[0, 0], [100, 0], [150, 0], [130, 90]], rect).tolist() == pytest.approx(
        [-50.0, 0.0, 50.0, 50.0])
    ell = V(mascara_forma="elipse", mascara_largura=200, mascara_altura=100)
    t = np.linspace(0, 2 * np.pi, 13)
    assert np.abs(mk.distance(np.stack([100 * np.cos(t), 50 * np.sin(t)], -1), ell)).max() < 1e-9
    assert mk.distance([[0, 0]], ell)[0] == -50.0 and mk.distance([[110, 0]], ell)[0] == pytest.approx(10.0, abs=0.5)
    square = [(-100, -50), (100, -50), (100, 50), (-100, 50)]
    q = np.random.default_rng(1).uniform(-200, 200, (200, 2))
    assert np.allclose(mk.distance(q, V(mascara_forma="poligono"), square), mk.distance(q, rect))
    tri = [(0, -50), (50, 50), (-50, 50)]
    assert mk.distance([[0, 10]], V(mascara_forma="poligono"), tri)[0] < 0
    assert mk.distance([[0, -60]], V(mascara_forma="poligono"), tri)[0] == pytest.approx(10.0)


def test_local_and_clip_coordinates_round_trip():
    v = V(mascara_forma="retangulo", mascara_x=120, mascara_y=-40, mascara_rotacao=30)
    p = np.array([[10.0, 20.0], [-300.0, 7.0]])
    assert np.allclose(mk.to_clip(mk.to_local(p, v), v), p)
    # Rotação positiva = sentido horário com y para baixo: o eixo x da forma aponta para baixo à direita.
    assert np.allclose(mk.to_clip([[100.0, 0.0]], v) - [120, -40], [[100 * np.cos(np.pi / 6), 50.0]])
    assert np.allclose(mk.clip_uv(mk.clip_px([[0.25, 0.8]], 1920, 1080), 1920, 1080), [[0.25, 0.8]])
    assert np.allclose(mk.clip_px([[1.0, 1.0]], 1280, 720), [[960.0, 540.0]])


def test_polygon_points_in_json_and_format_7():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(src(), at=0)[0]
    plain = seq.block_format()
    seq.set_values(c.id, {**c.values, "mascara_forma": "poligono"})
    mk.set_points(seq.find(c.id), [(1.234, -5.0), (40, 3), (-7, 20.5)])
    js = seq.to_json()
    assert seq.block_format() == tl.FORMAT and plain < tl.FORMAT
    back = tl.Sequence.from_json(js)
    assert mk.points_of(back.find(c.id)) == [(1.23, -5.0), (40.0, 3.0), (-7.0, 20.5)]
    assert back.find(c.id).fx == {"mascara": {"pontos": [[1.23, -5.0], [40.0, 3.0], [-7.0, 20.5]]}}
    mk.set_points(back.find(c.id), [])
    assert "mascara" not in back.find(c.id).fx
    assert len(mk.points_of({"mascara": {"pontos": [[0, 0]] * 40}})) == mk.MAX_POINTS
    assert mk.points_of({"mascara": {"pontos": [[0, "x"], [float("nan"), 1], [2, 3]]}}) == [(2.0, 3.0)]


def test_polygon_without_points_has_no_pass():
    seq, c = masked(mascara_forma="poligono")
    ctx = vfx.Ctx(seq, seq.layers_at(0)[0], 0, W, H, W, H)
    assert vfx.plan(ctx) == []
    mk.set_points(c, [(0, 0), (10, 0), (0, 10)])
    assert [p.name for _e, ps in vfx.plan(ctx) for p in ps] == ["mascara"]


# ------------------------------------------------------------------ na GPU
CASES = [
    dict(mascara_forma="retangulo", mascara_largura=700, mascara_altura=500, mascara_rotacao=20, mascara_x=150,
         mascara_suavidade=60),
    dict(mascara_forma="elipse", mascara_largura=900, mascara_altura=600, mascara_y=-100, mascara_suavidade=0,
         mascara_expandir=40),
    dict(mascara_forma="poligono", mascara_x=-200, mascara_rotacao=-15, mascara_suavidade=30, mascara_inverter=True),
]
POLY = [(-300, -300), (350, -200), (250, 320), (-100, 100), (-380, 260)]


@pytest.mark.gpu
@pytest.mark.parametrize("case", range(len(CASES)))
def test_gpu_mask_matches_numpy(gl_engine, renderer, case):
    values = CASES[case]
    pts = POLY if values["mascara_forma"] == "poligono" else None
    seq, c = masked(points=pts, **values)
    got = rgba(gl_engine, seq)[..., 3]
    ref = mk.mask(c.values, pts or [], W, H)
    assert np.abs(got - ref).max() < 2e-3
    assert got.min() < 0.01 and got.max() > 0.99


@pytest.mark.gpu
def test_edge_and_feather_are_in_px1080(gl_engine, renderer):
    """A mesma máscara a 540 e a 1080 linhas: borda no mesmo lugar e a mesma passagem em px@1080."""
    def profile(w, h):
        seq, c = masked(w, h, mascara_forma="retangulo", mascara_largura=1000, mascara_altura=600,
                        mascara_suavidade=80)
        a = rgba(gl_engine, seq, w=w, h=h)[..., 3][h // 2]
        scale = h / 1080.0
        x = (np.arange(w) + 0.5 - w / 2) / scale  # px@1080 a partir do centro
        right = x > 0
        mid = np.interp(0.5, a[right][::-1], x[right][::-1])
        lo = np.interp(0.9, a[right][::-1], x[right][::-1])
        hi = np.interp(0.1, a[right][::-1], x[right][::-1])
        return mid, hi - lo

    m1, f1 = profile(960, 540)
    m2, f2 = profile(1920, 1080)
    assert m1 == pytest.approx(500.0, abs=2.5) and m2 == pytest.approx(500.0, abs=1.5)
    assert f1 == pytest.approx(f2, abs=3.0) and f2 == pytest.approx(80 * 0.608, rel=0.05)  # 10–90% do smoothstep


@pytest.mark.gpu
def test_invert_swaps_inside_and_outside(gl_engine, renderer):
    base = dict(mascara_forma="elipse", mascara_largura=600, mascara_altura=400, mascara_suavidade=40)
    a = rgba(gl_engine, masked(**base)[0])[..., 3]
    b = rgba(gl_engine, masked(**base, mascara_inverter=True)[0])[..., 3]
    assert np.abs(a + b - 1.0).max() < 2e-3


@pytest.mark.gpu
@pytest.mark.parametrize("use", ["desfocar", "pixelar"])
def test_blur_and_pixelate_only_inside(gl_engine, renderer, use):
    plain = opaque(gl_engine, masked(transparent=False)[0])
    seq, c = masked(transparent=False, mascara_forma="retangulo", mascara_largura=600, mascara_altura=600,
                    mascara_suavidade=0, mascara_uso=use, mascara_forca=60)
    got = opaque(gl_engine, seq)
    m = mk.mask(c.values, [], W, H)
    outside, inside = m < 1e-6, m > 1 - 1e-6
    assert np.abs(got - plain)[outside].max() <= 1.0 / 65535
    assert got[inside].std(axis=0).max() < plain[inside].std(axis=0).max() * 0.6
    if use == "pixelar":  # quadradinhos de 60 px@1080 = 3 texels: blocos iguais
        rows = got[inside.any(axis=1)][:, inside.any(axis=0)]
        assert len({tuple(np.round(px, 4)) for px in rows.reshape(-1, 3)}) <= (rows.shape[0] // 3 + 2) * (
            rows.shape[1] // 3 + 2)


@pytest.mark.gpu
def test_cut_shows_the_track_below_and_follows_the_framing(gl_engine, renderer):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(src(liso=True, cor=[0.9, 0.1, 0.1]), at=0)
    top = seq.insert_media(src(), at=0, vtrack=1)[0]
    seq.set_values(top.id, {**top.values, "mascara_forma": "retangulo", "mascara_largura": 960,
                            "mascara_altura": 540, "mascara_suavidade": 0, "escala": 0.5, "pos_x": 0.25})
    got = opaque(gl_engine, seq)
    # Clipe a meia escala com o centro em 3/4 da largura: a máscara (metade do clipe) cobre 1/4 × 1/4 da tela.
    yy, xx = np.mgrid[0:H, 0:W]
    fx, fy = (xx + 0.5) / W, (yy + 0.5) / H
    inside = (np.abs(fx - 0.75) < 0.125 - 0.02) & (np.abs(fy - 0.5) < 0.125 - 0.03)
    outside = (np.abs(fx - 0.75) > 0.125 + 0.02) | (np.abs(fy - 0.5) > 0.125 + 0.03)
    assert np.abs(got[outside] - np.array([0.9, 0.1, 0.1])).max() < 2e-3
    assert np.abs(got[inside] - np.array([0.9, 0.1, 0.1])).max(axis=-1).min() > 0.05


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_no_shape_is_bit_exact(gl_engine, renderer, depth):
    seq, c = masked(transparent=False)
    plain = opaque(gl_engine, seq, depth=depth)
    targets = {k for k in gl_engine._targets if str(k).startswith("fx")}
    seq.set_values(c.id, {**c.values, "mascara_x": 100.0, "mascara_suavidade": 50.0, "mascara_uso": "pixelar"})
    assert np.array_equal(opaque(gl_engine, seq, depth=depth), plain)
    assert {k for k in gl_engine._targets if str(k).startswith("fx")} == targets


@pytest.mark.gpu
def test_key_then_mask_reads_the_keyed_image(gl_engine, renderer):
    """Recorte e máscara juntos: a máscara desfoca a imagem que saiu do recorte (a entrada "in" do efeito)."""
    seq, c = masked(mascara_forma="retangulo", mascara_largura=400, mascara_altura=400, mascara_uso="desfocar",
                    mascara_forca=20, chave_tipo="luma", chave_luma_min=0.0, chave_luma_max=0.6,
                    chave_suavidade=0.0)
    got = rgba(gl_engine, seq)
    only_key, _ = masked(chave_tipo="luma", chave_luma_min=0.0, chave_luma_max=0.6, chave_suavidade=0.0)
    keyed = rgba(gl_engine, only_key)
    m = mk.mask(c.values, [], W, H)
    pm = lambda x: np.concatenate([x[..., :3] * x[..., 3:], x[..., 3:]], -1)  # noqa: E731 (cor sem cobertura: livre)
    assert np.abs(pm(got) - pm(keyed))[m < 1e-6].max() < 2e-3  # fora: o recorte como estava
    assert keyed[..., 3].min() < 0.01  # o recorte tirou algo


@pytest.mark.gpu
def test_preview_equals_export_with_an_animated_center(gl_engine, renderer):
    from pelicula import export, media
    from pelicula.frame import Recipe
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(src(liso=True, cor=[0.2, 0.3, 0.9]), at=0)
    top = seq.insert_media(src(), at=0, vtrack=1)[0]
    seq.set_values(top.id, {**top.values, "mascara_forma": "elipse", "mascara_largura": 500, "mascara_altura": 400,
                            "mascara_suavidade": 40})
    seq.set_key(top.id, "mascara_x", top.start, -400.0)
    seq.set_key(top.id, "mascara_x", top.start + 5, 400.0)
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(6)]
    finally:
        reader.close()
    for t in range(6):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), f"quadro {t}"
    assert not np.array_equal(exported[0], exported[5])  # a forma andou
