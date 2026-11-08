"""1.9: recorte por cor ou pelo brilho do clipe (`recorte.py`, ARQUITETURA §50).

Telas verdes e azuis sintéticas (um degradê de luz no fundo, uma pessoa de pele, um cinza e um verde-claro de roupa):
o recorte da GPU == a referência em numpy, o reflexo do fundo não mexe nos cinzas, a luz na borda só perto da borda,
encolher a borda anda em px@1080, desligado = bit a bit, prévia == exportação, JSON e formato 7.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import editparams, recorte, sequence, vfx
from pelicula import timeline as tl

W, H = 96, 54
KIND = "gerador"
STATE = {"fundo": "verde"}


def scene(w=W, h=H, fundo="verde"):
    """Fundo de recorte com luz desigual (60% a 100%), uma pessoa (disco de pele) e um quadrado cinza, em código."""
    base = np.array(recorte.KEY_COLORS[fundo])
    yy, xx = np.mgrid[0:h, 0:w]
    light = 0.6 + 0.4 * (xx / max(1, w - 1))
    img = base[None, None, :] * light[..., None]
    disc = (xx - w * 0.35) ** 2 + (yy - h * 0.5) ** 2 < (h * 0.3) ** 2
    img[disc] = (0.80, 0.60, 0.50)
    square = (np.abs(xx - w * 0.75) < w * 0.08) & (np.abs(yy - h * 0.5) < h * 0.2)
    img[square] = (0.5, 0.5, 0.5)
    return img, disc, square


def gen(seq, clip, frame, w, h, depth):
    src = seq.sources[clip.src]
    if src.data.get("fundo") == "liso":
        img = np.ones((h, w, 3)) * np.array(src.data.get("cor", [0.8, 0.2, 0.1]))
    else:
        img = scene(w, h, src.data.get("fundo", "verde"))[0]
    mx = 255 if depth == 8 else 65535
    return np.rint(np.clip(img, 0, 1) * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def src(fundo="verde", w=W, h=H, **data):
    return tl.Source.virtual(KIND, w, h, "24/1", seconds=2.0, data={"nome": "Tela", "fundo": fundo, **data},
                             alpha=False)


def keyed(fundo="verde", transparent=True, w=W, h=H, **values):
    seq = tl.Sequence(width=w, height=h, fps_str="24/1", transparent=transparent)
    c = seq.insert_media(src(fundo, w, h), at=0)[0]
    seq.set_values(c.id, {**c.values, "chave_tipo": fundo, **values})
    return seq, c


def rgba(engine, seq, t=3, w=W, h=H, depth=16):
    out = engine.compose(sequence.grab(seq, t, w, h, depth), seq, w, h, depth, alpha=True)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


# ------------------------------------------------------------------ sem GPU
def test_params_are_neutral_sparse_and_go_to_format_7():
    v = editparams.VIDEO.defaults()
    assert not recorte.active(v) and not vfx.makes_alpha(v) and vfx.active_effects(v) == []
    assert all(k in editparams.SPARSE_KEYS for k in recorte.KEYS)
    assert editparams.stored_values("video", v) == {k: x for k, x in editparams.stored_values("video", v).items()
                                                   if k not in recorte.KEYS}
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(src(), at=0)[0]
    plain = seq.to_json()
    assert "chave_tipo" not in str(plain) and seq.block_format() < tl.FORMAT
    seq.set_values(c.id, {**c.values, "chave_tipo": "azul", "chave_spill": 0.5})
    assert seq.block_format() == tl.FORMAT
    back = tl.Sequence.from_json(seq.to_json())
    assert back.find(c.id).values["chave_tipo"] == "azul" and back.find(c.id).values["chave_spill"] == 0.5
    assert recorte.MODULE in vfx.modules_used(seq)


def test_plan_has_only_the_passes_it_needs():
    seq, c = keyed("verde")
    layer = seq.layers_at(0)[0]
    ctx = vfx.Ctx(seq, layer, 0, 1920, 1080, 1920, 1080)
    names = [p.name for _e, ps in vfx.plan(ctx) for p in ps]
    assert names == ["recorte", "chave"]
    seq.set_values(c.id, {**c.values, "chave_limpar": 2.0, "chave_luz_borda": 0.5})
    plan = vfx.plan(vfx.Ctx(seq, seq.layers_at(0)[0], 0, 3840, 2160, 3840, 2160))
    by = {p.name: p for _e, ps in plan for p in ps}
    assert list(by) == ["recorte", "recorte_suave", "recorte_limpo", "fundo", "fundo_suave", "borda_suave", "chave"]
    assert by["recorte_suave"].sigma == pytest.approx(4.0)  # 2 px@1080 num clipe de 2160 linhas
    assert by["borda_suave"].sigma == pytest.approx(40.0) and by["fundo_suave"].sigma == pytest.approx(20.0)


def test_numpy_matte_reference():
    v = editparams.VIDEO.defaults() | {"chave_tipo": "verde"}
    img, disc, square = scene()
    m = recorte.matte(img, v)
    fundo = ~(disc | square)
    assert m[fundo].max() < 1e-6 and m[disc].min() == 1.0 and m[square].min() == 1.0
    # O cinza fica a 1,0 de qualquer fundo; a pele, mais longe.
    k = recorte.chroma(recorte.decode(np.array(recorte.KEY_COLORS["verde"])))
    grey = recorte.chroma(recorte.decode(np.array([0.5, 0.5, 0.5])))
    assert np.linalg.norm(grey) < 1e-9 and np.linalg.norm(k) > 0.5
    v["chave_tipo"] = "luma"
    v["chave_luma_min"], v["chave_suavidade"] = 0.5, 0.01
    lum = recorte.brightness(recorte.decode(img))
    m = recorte.matte(img, v)
    assert np.all(m[lum < 0.49] == 0.0) and np.all(m[lum > 0.5] == 1.0)


def test_picked_color_refuses_grey():
    assert recorte.picked_color((0.5, 0.5, 0.52)) is None
    assert recorte.picked_color((0.2, 0.6, 0.3)) == (0.2, 0.6, 0.3)


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.parametrize("fundo", ["verde", "azul"])
def test_gpu_matte_matches_numpy(gl_engine, renderer, fundo):
    seq, c = keyed(fundo, chave_tolerancia=0.3, chave_suavidade=0.4)  # passagem larga: compara a rampa também
    got = rgba(gl_engine, seq)
    code = gen(seq, c, 0, W, H, 16).astype(np.float64) / 65535
    ref = recorte.matte(code, seq.find(c.id).values)
    assert np.abs(got[..., 3] - ref).max() < 2e-3  # recorte em f2
    img, disc, square = scene(fundo=fundo)
    assert got[..., 3][~(disc | square)].max() < 2e-3 and got[..., 3][disc].min() > 0.998
    inside = got[..., 3] > 0.999
    assert np.abs(got[..., :3][inside] - code[inside]).max() < 2e-4  # a cor de quem fica não muda


@pytest.mark.gpu
def test_luma_key_on_the_gpu(gl_engine, renderer):
    seq, c = keyed("verde", chave_tipo="luma", chave_luma_min=0.55, chave_suavidade=0.1)
    got = rgba(gl_engine, seq)[..., 3]
    code = gen(seq, c, 0, W, H, 16).astype(np.float64) / 65535
    assert np.abs(got - recorte.matte(code, seq.find(c.id).values)).max() < 2e-3


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_off_is_bit_exact(gl_engine, renderer, depth):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(src(), at=0)[0]
    plain = gl_engine.compose(sequence.grab(seq, 3, W, H, depth), seq, W, H, depth)
    targets = {k for k in gl_engine._targets if str(k).startswith("fx")}
    seq.set_values(c.id, {**c.values, "chave_spill": 1.0, "chave_luz_borda": 1.0, "chave_limpar": 5.0})  # sem tipo
    got = gl_engine.compose(sequence.grab(seq, 3, W, H, depth), seq, W, H, depth)
    assert np.array_equal(plain, got)
    assert {k for k in gl_engine._targets if str(k).startswith("fx")} == targets


@pytest.mark.gpu
def test_keyed_clip_shows_the_track_below(gl_engine, renderer):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(src("liso", cor=[0.8, 0.2, 0.1]), at=0)
    top = seq.insert_media(src("verde"), at=0, vtrack=1)[0]
    seq.set_values(top.id, {**top.values, "chave_tipo": "verde"})
    got = gl_engine.compose(sequence.grab(seq, 3, W, H, 16), seq, W, H, 16).astype(np.float64) / 65535
    img, disc, square = scene()
    fundo = ~(disc | square)
    assert np.abs(got[fundo] - np.array([0.8, 0.2, 0.1])).max() < 2e-3
    assert np.abs(got[disc] - np.array([0.8, 0.6, 0.5])).max() < 2e-3


@pytest.mark.gpu
def test_spill_leaves_grey_alone_and_pulls_green_down(gl_engine, renderer, monkeypatch):
    def spill(seq, clip, frame, w, h, depth):
        img = np.zeros((h, w, 3))
        img[:, : w // 3] = (0.5, 0.5, 0.5)            # cinza
        img[:, w // 3: 2 * w // 3] = (0.5, 0.62, 0.5)  # cinza com reflexo verde
        img[:, 2 * w // 3:] = (0.9, 0.85, 0.2)         # amarelo (verde abaixo do vermelho: não muda)
        return np.rint(img * 65535).astype(np.uint16) if depth == 16 else np.rint(img * 255).astype(np.uint8)

    monkeypatch.setitem(sequence.RENDERERS, KIND, spill)
    seq, c = keyed("verde", transparent=False, chave_spill=1.0, chave_tolerancia=0.0, chave_suavidade=0.0)
    got = gl_engine.compose(sequence.grab(seq, 3, W, H, 16), seq, W, H, 16).astype(np.float64) / 65535
    ref = spill(seq, c, 0, W, H, 16).astype(np.float64) / 65535
    grey, tinted, yellow = got[:, 2], got[:, W // 2], got[:, -2]
    assert np.abs(grey - ref[:, 2]).max() < 3e-4 and np.abs(yellow - ref[:, -2]).max() < 3e-4
    assert np.abs(tinted[:, 1] - tinted[:, 0]).max() < 2e-3  # o verde desce até o vermelho e o azul
    assert np.abs(tinted[:, [0, 2]] - ref[:, W // 2][:, [0, 2]]).max() < 3e-4


@pytest.mark.gpu
def test_light_wrap_only_near_the_edge(gl_engine, renderer):
    def run(wrap):
        seq = tl.Sequence(width=W, height=H, fps_str="24/1")
        seq.insert_media(src("liso", cor=[1.0, 1.0, 1.0]), at=0)
        top = seq.insert_media(src("verde"), at=0, vtrack=1)[0]
        seq.set_values(top.id, {**top.values, "chave_tipo": "verde", "chave_luz_borda": wrap,
                                "chave_luz_largura": 60.0})
        return gl_engine.compose(sequence.grab(seq, 3, W, H, 16), seq, W, H, 16).astype(np.float64) / 65535

    plain, wrapped = run(0.0), run(1.0)
    img, disc, square = scene()
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - W * 0.35, yy - H * 0.5)
    edge = disc & (r > H * 0.3 - 2)
    core = disc & (r < H * 0.3 - 12)
    assert (wrapped - plain)[edge].mean() > 0.02  # a borda clareia com o branco de baixo
    assert np.abs(wrapped - plain)[core].max() < 3e-3
    assert np.abs(wrapped - plain)[~(disc | square)].max() < 2e-3  # o fundo já era o de baixo


@pytest.mark.gpu
def test_choke_moves_the_edge_in_px1080(gl_engine, renderer):
    """Encolher a borda em 10 px@1080 num clipe de 540 linhas anda ~5 texels; aumentar anda para fora."""
    w, h = 960, 540

    def radius(limpar):
        seq, c = keyed("verde", w=w, h=h, chave_limpar=limpar)
        a = rgba(gl_engine, seq, w=w, h=h)[..., 3]
        row = a[h // 2, : int(w * 0.35)]  # da borda esquerda até o centro do disco
        return w * 0.35 - (np.argmax(row > 0.5) - 0.5)

    r0, r_in, r_out = radius(0.0), radius(10.0), radius(-10.0)
    assert r0 == pytest.approx(h * 0.3, abs=1.0)
    assert r0 - r_in == pytest.approx(5.0, abs=1.5)
    assert r_out - r0 == pytest.approx(5.0, abs=1.5)


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, renderer):
    from pelicula import export, media
    from pelicula.frame import Recipe
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(src("liso", cor=[0.2, 0.3, 0.9]), at=0)
    top = seq.insert_media(src("verde"), at=0, vtrack=1)[0]
    seq.set_values(top.id, {**top.values, "chave_tipo": "verde", "chave_limpar": 3.0, "chave_spill": 0.6,
                            "chave_luz_borda": 0.4})
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(4)]
    finally:
        reader.close()
    for t in range(4):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(W, H))
        prev = r.render(gl_engine, sequence.grab(seq, t, W, H, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), f"quadro {t}"


@pytest.mark.gpu
def test_no_effects_turns_the_key_off(gl_engine, renderer):
    seq, c = keyed("verde", transparent=False)
    on = gl_engine.compose(sequence.grab(seq, 3, W, H, 8), seq, W, H, 8)
    off = gl_engine.compose(sequence.grab(seq, 3, W, H, 8), seq, W, H, 8, neutral=True)
    assert np.array_equal(off, gen(seq, c, 0, W, H, 8))
    assert not np.array_equal(on, off)


@pytest.mark.gpu
def test_nested_twin_with_a_key_inside_is_bit_exact(gl_engine, renderer):
    """O clipe recortado sobre outro, dentro de uma sequência (e, fora, só o clipe dela) = a mesma montagem solta."""
    for depth in (8, 16):
        flat = tl.Sequence(width=W, height=H, fps_str="24/1")
        flat.insert_media(src("liso", cor=[0.2, 0.3, 0.9]), at=0)
        top = flat.insert_media(src("verde"), at=0, vtrack=1)[0]
        flat.set_values(top.id, {**top.values, "chave_tipo": "verde", "chave_spill": 0.5, "chave_limpar": 2.0})
        outer = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.9, 0.0, 0.0))
        inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
        outer.ensure_set().add(inner)
        outer.siblings.sync()
        outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=0)
        for t in (0, 7):
            a = gl_engine.compose(sequence.grab(flat, t, W, H, depth), flat, W, H, depth)
            b = gl_engine.compose(sequence.grab(outer, t, W, H, depth), outer, W, H, depth)
            assert np.array_equal(a, b), f"quadro {t}, {depth} bits"
