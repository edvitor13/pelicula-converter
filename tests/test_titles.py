"""Títulos do modo Edição (`pelicula/titles.py`): dados, estilos prontos, desenho e animações.

Os hashes de `HASHES` são o mesmo título desenhado no Windows e no Linux: o texto vem do `textrender` (que tem
os próprios hashes nos dois sistemas) e tudo o que o título faz por cima (pré-multiplicar, opacidade, máscaras,
zoom bilinear) são contas elemento a elemento em float32, sem seno, ângulo nem aleatório. Se um hash mudar sem
querer, o desenho mudou: confira a imagem antes de atualizar.
"""

from __future__ import annotations

import hashlib
import json
import threading

import numpy as np
import pytest

from pelicula import generators, sequence, textrender, titles
from pelicula import timeline as tl
from pelicula.textrender import TextStyle

W, H = 320, 180
FPS = 24.0
TOTAL = 5.0          # s
LAST = TOTAL - 1 / FPS


@pytest.fixture(autouse=True)
def _app(qapp):  # o texto usa as fontes do app (Qt)
    return qapp


def title(enter="nenhuma", leave="nenhuma", dur=1.0, text="Película 1974", **style):
    st = {"fonte": "atkinson", "tamanho": 120.0, **style}
    return titles.title_of({"texto": text, "estilo": TextStyle.from_json(st).to_json(), "entrada": enter,
                            "saida": leave, "dur_entrada": dur, "dur_saida": dur})


def draw(t, el, depth=8, w=W, h=H):
    return titles.draw(t, el, TOTAL, FPS, w, h, depth)


def ink_box(img):
    a = img[..., 3]
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max(), ys.max()


def centroid(img):
    a = img[..., 3].astype(np.float64)
    ys, xs = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    return (xs * a).sum() / a.sum(), (ys * a).sum() / a.sum()


# ------------------------------------------------------------------ fonte e JSON
def test_new_title_source_and_json():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    src = titles.new_source(seq)
    assert src.kind == "texto" and src.has_alpha and src.unbounded and not src.is_file
    assert src.data["texto"] == "Título" and src.name == "Título" and src.data["estilo_pronto"] == "titulo_grande"
    back = tl.Source.from_json(json.loads(json.dumps(src.to_json())))
    assert back.data == src.data and titles.title_of(back.data) == titles.title_of(src.data)
    clip = seq.insert_media(src, at=0)[0]
    assert clip.dur == seq.frames_for(tl.IMAGE_SECONDS)
    assert "gerador" in seq.features() and generators.needs_text(seq)
    assert sequence.RENDERERS["texto"] is titles.render


def test_title_data_is_checked():
    t = titles.title_of({"texto": 5, "estilo": "x", "pos_x": "nada", "pos_y": float("nan"), "entrada": "voar",
                         "saida": "zoom", "dur_entrada": -3, "dur_saida": 99})
    assert t.text == "" and t.style == TextStyle() and (t.pos_x, t.pos_y) == (0.5, 0.5)
    assert t.enter == "nenhuma" and t.leave == "zoom" and t.enter_s == 0.0 and t.leave_s == 30.0
    assert titles.title_of(None) == titles.Title()


def test_names_follow_the_first_line():
    assert titles.display_name("\n  Créditos finais \nsegunda") == "Créditos finais"
    assert titles.display_name("   ") == "Título"
    assert titles.display_name("x" * 60).endswith("…") and len(titles.display_name("x" * 60)) == 40
    data = titles.with_text({"texto": "a", "nome": "a", "estilo": {}}, "Novo nome\nlinha 2")
    assert data["nome"] == "Novo nome" and data["texto"] == "Novo nome\nlinha 2"


def test_presets_and_animations_ids():
    ids = [p.id for p in titles.PRESETS]
    assert len(ids) == len(set(ids)) and all(i.isascii() for i in ids)
    for wanted in ("titulo_grande", "terco_inferior", "cartela_cinema", "creditos", "legenda_filme"):
        assert wanted in ids
    anims = [a for a, _l in titles.ANIMATIONS if a != "nenhuma"]
    assert 6 <= len(anims) <= 8 and all(a.isascii() for a in anims)
    for p in titles.PRESETS:
        d = titles.preset_data(p.id)
        t = titles.title_of(d)
        assert t.text and t.style == p.style.sanitized() and (t.enter, t.enter_s) == p.enter
        img = titles.draw(t, 2.5, TOTAL, FPS, W, H, 8)
        assert img[..., 3].max() > 200, p.id  # aparece no meio do clipe
    assert titles.preset_data("terco_inferior", "Ana")["texto"] == "Ana"


def test_missing_characters():
    ok = titles.preset_data("titulo_grande", "Ação, 1974!")
    assert titles.missing(ok) == ""
    odd = titles.preset_data("titulo_grande", "Москва 東京")
    miss = titles.missing(odd)
    assert "東" in miss and "京" in miss and " " not in miss


# ------------------------------------------------------------------ desenho
@pytest.mark.parametrize("depth", [8, 16])
def test_draw_is_premultiplied_text_render(depth):
    t = title(cor="#ff8040")
    img = draw(t, 1.0, depth)
    peak = 255 if depth == 8 else 65535
    assert img.dtype == (np.uint8 if depth == 8 else np.uint16) and img.shape == (H, W, 4)
    assert (img[..., :3] <= img[..., 3:4]).all()  # pré-multiplicado: cor ≤ alfa
    # o mesmo texto pelo textrender (alfa direto) no mesmo lugar, pré-multiplicado aqui
    st = t.style
    lay = textrender.measure(t.text, st, H)
    bx, by = 0.5 * W - 0.5 * lay.width, 0.5 * H - lay.height / 2
    ix, iy = int(np.floor(bx)), int(np.floor(by))
    ref = textrender.render(t.text, st, H, depth=16, offset=(round(bx - ix, 4), round(by - iy, 4)))
    a = ref.rgba[..., 3:4] / 65535.0
    pm = np.floor(np.concatenate([ref.rgba[..., :3] / 65535.0 * a, a], axis=2) * peak + 0.5)
    ax, ay = ix + ref.left, iy + ref.top
    got = img[ay:ay + ref.height, ax:ax + ref.width].astype(np.float64)
    assert np.abs(got - pm).max() <= 1
    full = img[..., 3].max()
    assert full == peak  # o miolo das letras é opaco


def test_position_and_alignment():
    left = title(alinhamento="esquerda")
    left = titles.Title(**{**left.__dict__, "pos_x": 0.1, "pos_y": 0.2})
    x0, y0, x1, y1 = ink_box(draw(left, 1.0))
    assert abs(x0 - 0.1 * W) <= 3  # a borda esquerda do texto em 10 %
    assert abs((y0 + y1) / 2 - 0.2 * H) <= 6  # o meio do texto em 20 %
    right = titles.Title(**{**title(alinhamento="direita").__dict__, "pos_x": 0.9})
    assert abs(ink_box(draw(right, 1.0))[2] - 0.9 * W) <= 3


def test_empty_text_is_transparent():
    assert not draw(title(text="  \n "), 1.0).any()


# ------------------------------------------------------------------ animações (quadros fixos)
def test_fade_in_and_out():
    t = title("aparecer", "aparecer", dur=1.0)
    still = draw(title(), 2.0)
    assert not draw(t, 0.0).any()                       # primeiro quadro: invisível
    assert not draw(t, LAST).any()                      # último quadro: invisível
    assert np.array_equal(draw(t, 2.0), still)          # no meio: o título inteiro
    half = draw(t, 0.5)
    assert abs(half[..., 3].astype(int).max() - 128) <= 1  # metade da entrada: metade da opacidade
    assert abs(draw(t, LAST - 0.25)[..., 3].astype(int).max() - 64) <= 1


def test_rise_and_slide_move_the_text():
    still = centroid(draw(title(), 2.0))
    s = H / 1080
    e = 1 - 0.5 ** 3  # a curva na metade
    rise = centroid(draw(title("subir"), 0.5))
    assert abs(rise[1] - still[1] - titles.RISE * s * (1 - e)) < 0.35 and abs(rise[0] - still[0]) < 0.2
    slide = centroid(draw(title("deslizar"), 0.5))
    assert abs(slide[0] - still[0] + titles.SLIDE * s * (1 - e)) < 0.35
    out = centroid(draw(title(leave="subir"), LAST - 0.5))
    assert out[1] < still[1] - 0.4  # na saída, sobe


def test_zoom_changes_the_size_around_the_center():
    still = ink_box(draw(title(), 2.0))
    small = ink_box(draw(title("zoom"), 0.25))
    w0, w1 = still[2] - still[0], small[2] - small[0]
    p = 0.25
    scale = titles.ZOOM_IN + (1 - titles.ZOOM_IN) * (1 - (1 - p) ** 3)
    assert abs(w1 / w0 - scale) < 0.03
    assert abs((small[0] + small[2]) / 2 - (still[0] + still[2]) / 2) <= 1.5
    big = ink_box(draw(title(leave="zoom"), LAST - 0.25))
    assert big[2] - big[0] > w0


def test_typewriter_and_letters_reveal_in_reading_order():
    t = title("maquina", dur=1.0, text="ABCDEFGH")
    rights = [ink_box(draw(t, k / 8 + 1e-6))[2] if draw(t, k / 8 + 1e-6).any() else -1 for k in range(1, 9)]
    assert all(b > a for a, b in zip(rights, rights[1:]))  # uma letra a mais a cada 1/8 da entrada
    assert np.array_equal(draw(t, 1.0), draw(title(text="ABCDEFGH"), 1.0))
    lt = title("letra", dur=1.0, text="ABCDEFGH")
    sums = [int(draw(lt, k / 10)[..., 3].astype(np.int64).sum()) for k in range(11)]
    assert sums[0] == 0 and all(b >= a for a, b in zip(sums, sums[1:]))
    mid = draw(lt, 0.5)
    box = ink_box(draw(title(text="ABCDEFGH"), 1.0))  # o texto inteiro
    left_half = mid[:, :(box[0] + box[2]) // 2, 3].astype(np.int64).sum()
    right_half = mid[:, (box[0] + box[2]) // 2:, 3].astype(np.int64).sum()
    assert left_half > 2 * right_half  # o começo do texto aparece antes


def test_reveal_mask_sweeps_left_to_right():
    still = ink_box(draw(title(), 2.0))
    half = ink_box(draw(title("revelar"), 0.3))
    assert half[0] <= still[0] + 1 and half[2] < still[2] - 10
    gone = ink_box(draw(title(leave="revelar"), LAST - 0.3))
    assert gone[0] > still[0] + 10 and gone[2] >= still[2] - 1


def test_credits_roll_from_bottom_to_top():
    t = title("creditos", text="Direção\nAna\n\nFotografia\nBia")
    assert not draw(t, 0.0).any() and not draw(t, LAST).any()  # começa abaixo e termina acima do quadro
    ys = [centroid(draw(t, el))[1] for el in (1.5, 2.5, 3.5)]
    assert ys[0] > ys[1] > ys[2]
    assert abs(ys[1] - H / 2) < 8  # no meio do clipe, o bloco no meio do quadro


# ------------------------------------------------------------------ na montagem
def seq_with_title(fps="24/1", **data):
    seq = tl.Sequence(width=W, height=H, fps_str=fps)
    src = titles.new_source(seq, "titulo_grande", "Película")
    src.data.update(data)
    clip = seq.insert_media(src, at=10)[0]
    return seq, src, clip


def test_clip_time_follows_trim_and_speed():
    seq, src, clip = seq_with_title(entrada="aparecer", dur_entrada=0.5, saida="aparecer", dur_saida=0.5)
    first = sequence.render_source(seq, clip, seq.src_frame(clip, clip.start), W, H, 8)
    last = sequence.render_source(seq, clip, seq.src_frame(clip, clip.end - 1), W, H, 8)
    mid = sequence.render_source(seq, clip, seq.src_frame(clip, clip.start + 50), W, H, 8)
    assert not first.any() and not last.any() and mid[..., 3].max() == 255
    clip.src_in = 1.0  # aparado no começo: a entrada começa no primeiro quadro que o clipe mostra
    assert not sequence.render_source(seq, clip, seq.src_frame(clip, clip.start), W, H, 8).any()
    clip.values["velocidade"] = 2.0
    assert not sequence.render_source(seq, clip, seq.src_frame(clip, clip.end - 1), W, H, 8).any()
    clip.values.update(velocidade=1.0, congelar=True)  # quadro congelado: o título inteiro
    assert sequence.render_source(seq, clip, seq.src_frame(clip, clip.start), W, H, 8)[..., 3].max() == 255


def test_grab_equals_sequence_reader_in_8_and_16_bits():
    seq, src, clip = seq_with_title(entrada="letra", dur_entrada=0.5, saida="zoom", dur_saida=0.5)
    for depth, t0 in ((8, 12), (16, clip.end - 8)):
        reader = sequence.SequenceReader(seq, W, H, depth, t0, 6)
        try:
            for t in range(t0, t0 + 6):
                a = sequence.grab(seq, t, W, H, depth).layers[0].image
                b = reader.read().layers[0].image
                assert a.dtype == (np.uint8 if depth == 8 else np.uint16) and a.shape == (H, W, 4)
                assert np.array_equal(a, b), (depth, t)
        finally:
            reader.close()


def test_worker_thread_matches_main():
    seq, src, clip = seq_with_title(entrada="maquina", dur_entrada=1.0)
    f = seq.src_frame(clip, clip.start + 12)
    main = sequence.render_source(seq, clip, f, W, H, 16)
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("img", sequence.render_source(seq, clip, f, W, H, 16)))
    th.start()
    th.join()
    assert np.array_equal(main, out["img"])


def test_thumbnail_shows_the_whole_title():
    seq, src, clip = seq_with_title(entrada="aparecer", dur_entrada=1.0)
    thumb = sequence.source_thumbnail(src, 160, 90, rgba=True)
    assert thumb.shape == (90, 160, 4) and thumb[..., 3].max() == 255
    credits = titles.new_source(seq, "creditos")
    assert sequence.source_thumbnail(credits, 160, 90, rgba=True)[..., 3].max() > 100  # letra fina e pequena


def test_text_change_redraws():
    seq, src, clip = seq_with_title()
    f = seq.src_frame(clip, clip.start + 40)
    a = sequence.render_source(seq, clip, f, W, H, 8)
    src.data = titles.with_text(src.data, "Outro texto")
    b = sequence.render_source(seq, clip, f, W, H, 8)
    assert not np.array_equal(a, b)


# ------------------------------------------------------------------ hashes (Windows e Linux)
def _hash_cases():
    base = {"cor": "#ffd27a", "contorno": 3.0, "sombra": 0.6, "sombra_desfoque": 5.0, "caixa": 0.4,
            "caixa_margem": 12.0, "entrelinha": 1.1}
    two = "Película\nde 1974"
    return {
        "parado8": (title(text=two, **base), 2.0, 8),
        "parado16": (title(text=two, **base), 2.0, 16),
        "aparecer": (title("aparecer", text=two, **base), 0.4, 8),
        "subir": (title("subir", text=two, **base), 0.3, 8),
        "deslizar": (title(leave="deslizar", text=two, **base), LAST - 0.3, 16),
        "maquina": (title("maquina", text=two, **base), 0.55, 8),
        "letra": (title("letra", text=two, **base), 0.45, 8),
        "zoom": (title("zoom", text=two, **base), 0.35, 16),
        "creditos": (title("creditos", text=two, **base), 2.0, 8),
        "revelar": (title("revelar", text=two, **base), 0.5, 8),
    }


HASHES = {
    "parado8": "a36ffe3895e775b9d42f",
    "parado16": "a830d0e78dc229fff628",
    "aparecer": "382062124c026276f03c",
    "subir": "cfbc752401899ba9622f",
    "deslizar": "2efddd53a96187764473",
    "maquina": "caa7fd63a005308b8275",
    "letra": "6bfeb1d2fb0e28a19729",
    "zoom": "e141f982ff732f23a63e",
    "creditos": "2b834d4d594b8f54bcbf",
    "revelar": "42407378a2f08b75b258",
}


def test_title_hashes():
    got = {}
    for name, (t, el, depth) in _hash_cases().items():
        img = titles.draw(t, el, TOTAL, FPS, W, H, depth)
        got[name] = hashlib.sha256(img.tobytes()).hexdigest()[:20]
        assert np.array_equal(img, titles.draw(t, el, TOTAL, FPS, W, H, depth))  # mesmo pedido, mesma imagem
    assert got == HASHES, f"hashes novos: {got}"


# ------------------------------------------------------------------ módulo "Títulos e geradores"
def test_module_is_stable_in_creator_cinema_and_all():
    from pelicula import modules
    m = modules.get("titulos_geradores")
    assert m.status == modules.ESTAVEL and m.group == "edicao"
    sets = {pid: ids for pid, _n, _d, ids in modules.PROFILES}
    assert "titulos_geradores" not in sets["simples"]
    assert all("titulos_geradores" in sets[p] for p in ("criador", "cinema", "tudo"))


def test_used_by_sees_titles_and_generators():
    from pelicula import modules
    seq, src, clip = seq_with_title()
    assert {"edicao", "titulos_geradores"} <= modules.used_by(None, seq)
    plain = tl.Sequence(width=W, height=H, fps_str="24/1")
    video = tl.Source("C:/v/a.mp4", W, H, 24.0, "24/1", 48, 2.0, has_audio=False)
    plain.insert_media(video, at=0)
    plain.split(12)
    assert "titulos_geradores" not in modules.used_by(None, plain)
    plain.insert_media(generators.new_source("cor", plain), at=48)
    assert "titulos_geradores" in modules.used_by(None, plain)


def test_thumbnail_with_long_animations_is_not_empty():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    src = titles.new_source(seq, "titulo_grande", "Película")
    src.data.update(entrada="aparecer", dur_entrada=4.0, saida="aparecer", dur_saida=4.0)
    assert sequence.source_thumbnail(src, 160, 90, rgba=True)[..., 3].max() > 0
