"""Fontes que acompanham o app e o desenho de texto (`fontfile`, `textrender`).

Os hashes de `HASHES` são o mesmo texto desenhado no Windows e no Linux: o CI roda nos dois (com o Qt
*offscreen*, que usa o FreeType) e aqui, no Windows com a plataforma normal do Qt, o motor de fontes é o
DirectWrite. O mesmo hash nos três prova que o resultado não depende do sistema. Se um hash mudar,
descubra o porquê (versão do Qt, mudança no desenho) antes de atualizar o valor.
"""

from __future__ import annotations

import hashlib
import struct
import threading

import numpy as np
import pytest

from pelicula import fontfile, textrender as tr

ACCENTS = "ÁÉÍÓÚáéíóúÂÊÔâêôÃÕãõÀàÇçÑñÜü¿¡“”‘’–—…«»ºª"


# ------------------------------------------------------------------ arquivos (sem Qt)
def test_font_files_match_source_manifest():
    manifest = tr.source_manifest()
    files = sorted(p.relative_to(tr.FONTS_DIR).as_posix() for p in tr.FONTS_DIR.rglob("*")
                   if p.is_file() and p.name != "SOURCE.txt")
    assert files == sorted(manifest), "arquivo sem SHA-256 no SOURCE.txt (ou listado e ausente)"
    total = 0
    for rel, digest in manifest.items():
        data = (tr.FONTS_DIR / rel).read_bytes()
        total += len(data)
        assert hashlib.sha256(data).hexdigest() == digest, rel
    assert total <= 8 * 1024 * 1024
    text = tr.SOURCE_FILE.read_text(encoding="utf-8")
    assert "github.com/google/fonts" in text and "ddf386ba1b9fbc6b2c818f1ddcd9148f54ced94b" in text


def test_fonts_go_into_the_packages():
    # O PyInstaller leva pelicula/data inteiro para _internal (o .msi e o .deb levam _internal inteiro).
    spec = (tr.FONTS_DIR.parents[2] / "PeliculaConverter.spec").read_text(encoding="utf-8")
    assert '"data"' in spec and 'os.path.join("pelicula", _sub)' in spec
    attrs = (tr.FONTS_DIR.parents[2] / ".gitattributes").read_text(encoding="utf-8")
    assert "pelicula/data/fontes/** binary" in attrs  # bytes exatos (o OFL.txt do Google tem CRLF)


def test_catalog_is_consistent():
    ids = [f.id for f in tr.FAMILIES]
    assert len(ids) == len(set(ids)) and 8 <= len(ids) <= 12
    assert tr.DEFAULT_FAMILY in ids
    for fam in tr.FAMILIES:
        assert fam.id.isascii() and fam.id == fam.id.lower() and " " not in fam.id
        assert fam.category in tr.CATEGORIES
        folder = fam.faces[0].file.split("/")[0]
        assert (tr.FONTS_DIR / folder / "OFL.txt").is_file()
        assert "SIL OPEN FONT LICENSE" in (tr.FONTS_DIR / folder / "OFL.txt").read_text(encoding="utf-8").upper()
        for face in fam.faces:
            ff = tr.font_file(face)
            assert ff.weight == face.weight or (fam.id == "archivo_black" and face.weight == 900)
            assert ff.italic == face.italic, face.file
            assert ff.missing(ACCENTS) == "", (face.file, ff.missing(ACCENTS))
    cats = {f.category for f in tr.FAMILIES}
    assert {"sans", "condensada", "geometrica", "serifa", "maquina", "manuscrita"} <= cats
    assert any(f.weight >= 700 for f in tr.family("atkinson").faces)


def test_face_choice():
    assert tr.face_for("poppins", 900).weight == 900
    assert tr.face_for("poppins", 800).weight == 900   # o mais perto
    assert tr.face_for("poppins", 700, True).italic
    assert tr.face_for("bebas", 700, True).file.endswith("BebasNeue-Regular.ttf")  # só tem um
    assert tr.family("nao_existe").id == tr.DEFAULT_FAMILY


def test_fontfile_outlines_and_composites():
    ff = tr.font_file(tr.face_for("atkinson"))
    a, a_tilde = ff.glyph_index("A"), ff.glyph_index("Ã")
    assert a and a_tilde and a != a_tilde
    base = ff.outline(a)
    composed = ff.outline(a_tilde)
    assert len(composed) > len(base)                                 # o A e o til
    top = max(y for c in composed for _x, y, _on in c)
    assert top > max(y for c in base for _x, y, _on in c)            # o til fica acima do A
    assert ff.outline(ff.glyph_index(" ")) == ()
    assert ff.advance(a) > 0
    with pytest.raises(fontfile.FontError):
        fontfile.FontFile(b"OTTO" + b"\0" * 64)


def test_renamed_copy_keeps_glyphs_and_has_valid_checksums():
    ff = tr.font_file(tr.face_for("crimson", 700, True))
    data = ff.renamed("PeliculaTexto Teste")
    copy = fontfile.FontFile(data)
    assert copy.family == "PeliculaTexto Teste" and copy.subfamily == ff.subfamily
    for tag in ff.tables:
        if tag != "name":
            assert copy.table(tag)[:8] == ff.table(tag)[:8] or tag == "head"
    for g in (ff.glyph_index("ç"), ff.glyph_index("Q"), 5):
        assert copy.outline(g) == ff.outline(g)
    # soma de conferência do arquivo inteiro = 0xB1B0AFBA (regra do formato sfnt)
    padded = data + b"\0" * (-len(data) % 4)
    assert sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF == 0xB1B0AFBA


def test_style_json_roundtrip_and_sanitize():
    st = tr.TextStyle(family="poppins", weight=900, size=80, color=(1, 0.5, 0), outline=4, shadow=0.5,
                      box=0.6, box_mode="bloco", align="esquerda", uppercase=True)
    d = st.to_json()
    assert all(k.isascii() for k in d)
    assert tr.TextStyle.from_json(d) == tr.TextStyle.from_json(tr.TextStyle.from_json(d).to_json())
    back = tr.TextStyle.from_json(d)
    assert back.family == "poppins" and back.weight == 900 and back.uppercase and back.box_mode == "bloco"
    bad = tr.TextStyle.from_json({"fonte": "Comic Sans", "tamanho": "x", "cor": "#zzz", "contorno": 1e9,
                                  "alinhamento": "meio", "opacidade": float("nan")})
    assert bad.family == tr.DEFAULT_FAMILY and bad.size == 54.0 and bad.color == (1.0, 1.0, 1.0)
    assert bad.outline == 40.0 and bad.align == "centro" and bad.opacity == 1.0
    assert tr.parse_color("#f80") == (1.0, 136 / 255, 0.0)
    assert tr.color_hex((1.0, 0.5, 0.0)) == "#ff8000"


# ------------------------------------------------------------------ desenho (Qt)
def _hash(img) -> str:
    return hashlib.sha256(img.rgba.tobytes() + f"{img.left},{img.top}".encode()).hexdigest()[:20]


CASES = {
    "simples": ("Ação, coração e pão — ¿Qué tal? ¡Olé!", tr.TextStyle()),
    "efeitos": ("Legenda com contorno, sombra e caixa", tr.TextStyle(size=60, wrap=700, outline=3, shadow=0.8,
                                                                   shadow_blur=6, box=0.5)),
    "reels": ("isso aqui muda tudo", tr.TextStyle(family="poppins", weight=900, size=90, uppercase=True, outline=7)),
    "serifa": ("“Cinema” — ñandú, fi", tr.TextStyle(family="crimson", italic=True, size=48, shadow=0.6)),
    "script": ("Pacifico: Ação", tr.TextStyle(family="pacifico", size=64, color=(1, 0.8, 0.2))),
}
# Conferidos no Windows (DirectWrite e offscreen) e no CI (Windows e Linux, offscreen).
HASHES = {
    "simples": "a98559fbd455a0d13250",
    "efeitos": "9b75a7a5f6cf5224d560",
    "reels": "7798fe6c60c70bcdc24b",
    "serifa": "aaa3973b374cd9237300",
    "script": "357758f39dc5a6385b7c",
    "destaque": "550a6c1b7100cad343a2",
    "4k16": "f9098a9081eba8449ca2",
}


def _case_images():
    out = {k: tr.render(t, s, 1080) for k, (t, s) in CASES.items()}
    out["destaque"] = tr.render("isso aqui muda tudo", CASES["reels"][1], 1080,
                                overrides={2: tr.WordOverride(color=(1.0, 0.85, 0.1), scale=1.1,
                                                              box_color=(0.8, 0.1, 0.1))})
    out["4k16"] = tr.render(*CASES["efeitos"], 2160, depth=16)
    return out


def test_same_text_same_pixels_on_every_system(qapp):
    got = {k: _hash(img) for k, img in _case_images().items()}
    assert got == HASHES, f"hashes novos: {got}"


def test_render_is_cached_read_only_and_deterministic(qapp):
    a = tr.render("Mesmo texto", tr.TextStyle(outline=2))
    b = tr.render("Mesmo texto", tr.TextStyle(outline=2))
    assert a is b
    assert not a.rgba.flags.writeable
    tr._render.cache_clear()
    c = tr.render("Mesmo texto", tr.TextStyle(outline=2))
    assert c is not a and np.array_equal(c.rgba, a.rgba)


def test_render_from_worker_thread_matches_main(qapp):
    st = tr.TextStyle(family="courier_prime", weight=700, size=40, shadow=0.7)
    main = tr.render("Máquina de escrever", st)
    tr._render.cache_clear()
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("img", tr.render("Máquina de escrever", st)))
    th.start()
    th.join(30)
    assert np.array_equal(out["img"].rgba, main.rgba)


def test_straight_alpha_convention(qapp):
    img = tr.render("Branco puro", tr.TextStyle(size=80, color=(1.0, 1.0, 1.0)))
    a = img.rgba
    assert a.dtype == np.uint8 and a.shape[2] == 4
    assert (a[a[..., 3] == 0][:, :3] == 0).all()
    edge = (a[..., 3] > 0) & (a[..., 3] < 255)
    assert edge.any()
    assert (a[edge][:, :3] == 255).all()       # alfa direto: a borda tem a cor cheia, não escurecida
    img16 = tr.render("Branco puro", tr.TextStyle(size=80), depth=16)
    assert img16.rgba.dtype == np.uint16 and img16.rgba.shape == a.shape
    assert np.abs(img16.rgba[..., 3].astype(int) // 257 - a[..., 3].astype(int)).max() <= 1


def test_accents_render(qapp):
    st = tr.TextStyle(size=100)
    plain = tr.render("A", st)
    for ch in "ÃÁÂÀÉÊÍÓÔÕÚÇÑ":
        img = tr.render(ch, st)
        assert img.rgba[..., 3].sum() > 0
        assert not (img.rgba.shape == plain.rgba.shape and np.array_equal(img.rgba, plain.rgba))
    lay_a, lay_at = tr.measure("A", st), tr.measure("Ã", st)
    assert lay_at.ink[1] < lay_a.ink[1] - 5           # o til sobe acima do A
    lay_c, lay_cc = tr.measure("C", st), tr.measure("Ç", st)
    assert lay_cc.ink[3] > lay_c.ink[3] + 5           # a cedilha desce abaixo da linha
    assert tr.missing_chars("Ação ¿Qué? ñ — “x”", "atkinson") == ""
    assert tr.missing_chars("日本", "atkinson") == "日本"


def test_wrap_and_alignment_geometry(qapp):
    text = "uma frase comprida que precisa quebrar em várias linhas"
    st = tr.TextStyle(size=50, wrap=500)
    lay = tr.measure(text, st, 1080)
    assert len(lay.lines) >= 3
    assert all(ln.w <= 500 + 1e-6 for ln in lay.lines)
    assert lay.width == pytest.approx(max(ln.w for ln in lay.lines))
    assert [w.text for w in lay.words] == text.split()
    assert [w.index for w in lay.words] == list(range(len(text.split())))
    # Alinhamento: a linha mais curta encosta à esquerda, fica no meio ou encosta à direita.
    short = min(lay.lines, key=lambda ln: ln.w)
    for align, expect in (("esquerda", 0.0), ("centro", (lay.width - short.w) / 2), ("direita", lay.width - short.w)):
        la = tr.measure(text, tr.TextStyle(size=50, wrap=500, align=align), 1080)
        assert la.lines[short.index].x == pytest.approx(expect)
    # Distâncias em px@1080: em 2160 linhas tudo dobra (e as quebras ficam iguais).
    big = tr.measure(text, st, 2160)
    assert [len(ln.words) for ln in big.lines] == [len(ln.words) for ln in lay.lines]
    assert big.width == pytest.approx(lay.width * 2) and big.height == pytest.approx(lay.height * 2)
    # Quebra de linha do próprio texto e entrelinha.
    two = tr.measure("linha um\nlinha dois", tr.TextStyle(size=50))
    spaced = tr.measure("linha um\nlinha dois", tr.TextStyle(size=50, line_spacing=1.5))
    assert len(two.lines) == 2 and spaced.height == pytest.approx(two.height * 1.5)
    tracked = tr.measure("letras", tr.TextStyle(size=50, letter_spacing=10))
    plain = tr.measure("letras", tr.TextStyle(size=50))
    assert tracked.width == pytest.approx(plain.width + 10 * 5)


def _mask(img, color, tol=8):
    a = img.rgba.astype(int)
    return (np.abs(a[..., :3] - np.array(color)).max(axis=2) <= tol) & (a[..., 3] > 200)


def test_outline_shadow_and_box_are_drawn(qapp):
    text = "Teste"
    plain = tr.render(text, tr.TextStyle(size=80, color=(1, 1, 1)))
    outlined = tr.render(text, tr.TextStyle(size=80, color=(1, 1, 1), outline=4, outline_color=(1, 0, 0)))
    assert not _mask(plain, (255, 0, 0)).any()
    assert _mask(outlined, (255, 0, 0)).sum() > 500
    assert outlined.width > plain.width and outlined.left < plain.left
    shadow = tr.render(text, tr.TextStyle(size=80, shadow=1.0, shadow_x=10, shadow_y=10, shadow_blur=0,
                                          shadow_color=(0, 0, 1)))
    blue = _mask(shadow, (0, 0, 255))
    assert blue.sum() > 500
    ys, xs = np.nonzero(blue)
    wys, wxs = np.nonzero(_mask(shadow, (255, 255, 255)))
    assert ys.mean() > wys.mean() + 5 and xs.mean() > wxs.mean() + 5   # para baixo e para a direita
    blurred = tr.render(text, tr.TextStyle(size=80, shadow=1.0, shadow_blur=12, shadow_color=(0, 0, 1)))
    alpha = blurred.rgba[..., 3]
    assert ((alpha > 0) & (alpha < 100)).sum() > ((shadow.rgba[..., 3] > 0) & (shadow.rgba[..., 3] < 100)).sum()
    boxed = tr.render(text, tr.TextStyle(size=80, box=1.0, box_color=(0, 1, 0), box_padding=20))
    green = _mask(boxed, (0, 255, 0))
    assert green.sum() > 2000
    assert green[boxed.height // 2, 5]                                  # margem da caixa à esquerda do texto
    two = tr.measure("um\ndois", tr.TextStyle(size=80))
    per_line = tr.render("um\ndois", tr.TextStyle(size=80, box=1.0, box_mode="linha", box_padding=4))
    block = tr.render("um\ndois", tr.TextStyle(size=80, box=1.0, box_mode="bloco", box_padding=4))
    assert len(two.lines) == 2
    assert (per_line.rgba[..., 3] > 0).sum() < (block.rgba[..., 3] > 0).sum()  # "um" é mais curto que "dois"
    faded = tr.render(text, tr.TextStyle(size=80, opacity=0.5))
    assert faded.rgba[..., 3].max() == 128


def test_word_override_highlight(qapp):
    text = "uma duas três"
    st = tr.TextStyle(size=80, color=(1, 1, 1))
    base = tr.render(text, st)
    hl = tr.render(text, st, overrides={1: tr.WordOverride(color=(1, 1, 0))})
    yellow = _mask(hl, (255, 255, 0))
    assert yellow.sum() > 300 and not _mask(base, (255, 255, 0)).any()
    lay = base.layout
    w1 = lay.words[1]
    xs = np.nonzero(yellow)[1] + hl.left
    assert xs.min() >= w1.x - 2 and xs.max() <= w1.x + w1.w + 2         # só a segunda palavra
    big = tr.render(text, st, overrides={1: tr.WordOverride(scale=1.3)})
    assert big.layout == base.layout                                    # a escala não mexe no layout
    assert big.rgba[..., 3].astype(int).sum() > base.rgba[..., 3].astype(int).sum()
    pill = tr.render(text, st, overrides={2: tr.WordOverride(box_color=(0, 0, 1))})
    assert _mask(pill, (0, 0, 255)).sum() > 1000
    # dict e lista de pares dão o mesmo resultado (e a mesma entrada no cache)
    assert tr.render(text, st, overrides=[(1, tr.WordOverride(color=(1, 1, 0)))]) is hl


def test_subpixel_offset_and_paste(qapp):
    st = tr.TextStyle(size=60)
    a = tr.render("Posição", st)
    b = tr.render("Posição", st, offset=(0.5, 0.0))
    assert not np.array_equal(a.rgba, b.rgba) or a.left != b.left
    frame = np.zeros((300, 800, 4), np.uint8)
    tr.paste(frame, a, 50, 100)
    assert frame[..., 3].sum() == a.rgba[..., 3].astype(int).sum()
    ys, xs = np.nonzero(frame[..., 3])
    assert xs.min() >= 50 + a.left and ys.min() >= 100 + a.top
    tr.paste(frame, a, 50, 100)                                         # por cima de si mesmo: alfa só sobe
    assert (frame[..., 3] >= 0).all()
    tr.paste(frame, a, 10_000, 10_000)                                  # fora do quadro: nada muda


def test_installed_font_with_same_name_is_never_used(qapp):
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QFontDatabase
    st = tr.TextStyle(family="crimson", size=70)
    before = tr.render("AVATAR fi Tô", st).rgba.copy()
    # Uma "Crimson Text" diferente no banco de fontes (como uma fonte instalada no computador): a Poppins
    # registrada com o nome da Crimson não pode entrar no lugar da fonte do app.
    fake = tr.font_file(tr.face_for("poppins")).renamed("Crimson Text")
    QFontDatabase.addApplicationFontFromData(QByteArray(fake))
    tr._render.cache_clear()
    tr.layout.cache_clear()
    tr.shape.cache_clear()
    assert np.array_equal(tr.render("AVATAR fi Tô", st).rgba, before)
