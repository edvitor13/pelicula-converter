"""Sequência aninhada (#57): um clipe cuja fonte é outra sequência aparece e soa como a montagem de dentro.

O coração daqui é a montagem "gêmea": os mesmos clipes dentro de uma sequência interna, e a de fora só com o clipe dela,
sem nenhum ajuste, tem que dar os mesmos quadros (bit a bit) e o mesmo som que a montagem sem aninhar.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import audiomix, camera, export, media, modules, sequence
from pelicula import timeline as tl

W, H = 320, 180
KIND = "gerador"


def gen(seq, clip, frame, w, h, depth):
    """Gerador de teste: cor pela fonte, brilho pelo quadro da fonte, uma barra que anda (para ver o quadro e o tamanho)."""
    src = seq.sources[clip.src]
    r, g, b = src.data.get("cor", [1.0, 0.5, 0.0])
    k = 0.2 + 0.03 * (frame % 25)
    img = np.ones((h, w, 3), np.float64) * [r * k, g * k, b * k]
    img[:, (frame * 3) % w] = 1.0
    mx = 255 if depth == 8 else 65535
    return np.rint(img * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def vsrc(cor=(1.0, 0.5, 0.0), seconds=4.0, fps="24/1"):
    return tl.Source.virtual(KIND, W, H, fps, seconds=seconds, data={"nome": "Barra", "cor": list(cor)}, alpha=False)


def fsrc(path="C:/nao/existe.mp4", frames=240, **kw):
    kw.setdefault("has_audio", True)
    kw.setdefault("color_range", "tv")
    return tl.Source(path, W, H, 24.0, "24/1", frames, frames / 24.0, pix_fmt="yuv420p", **kw)


def inner_of(outer, cor=(0.2, 0.8, 0.4), seconds=4.0, fps="24/1", width=W, height=H):
    """Uma sequência nova no projeto de `outer`, com um clipe gerado."""
    inner = outer.ensure_set().create(width, height, fps)
    inner.insert_media(vsrc(cor, seconds, fps), at=0)
    return inner


def nested_src(outer, inner):
    outer.siblings.sync()
    return outer.sources[f"sequencia:{inner.id}"]


def put(outer, inner, at=0, vtrack=0):
    """Um clipe de `inner` em `outer`."""
    return outer.insert_media(nested_src(outer, inner), at=at, vtrack=vtrack)[0]


def pair(**kw):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, **kw)
    return outer, inner, put(outer, inner)


def same_layers(a: sequence.FrameLayers, b: sequence.FrameLayers, where="") -> None:
    assert a.frame == b.frame, where
    assert len(a.layers) == len(b.layers), where
    for x, y in zip(a.layers, b.layers):
        assert x.layer.clip.id == y.layer.clip.id and x.layer.src_frame == y.layer.src_frame, where
        assert (x.nested is None) == (y.nested is None), where
        if x.nested is not None:
            assert x.nested.size == y.nested.size and x.nested.seq.id == y.nested.seq.id, where
            same_layers(x.nested.layers, y.nested.layers, f"{where} > {x.layer.clip.id}")
        else:
            assert np.array_equal(x.image, y.image), where


def agree(seq, frames=None, w=W, h=H, depth=8, **kw) -> None:
    """`SequenceReader` = `grab`, quadro a quadro."""
    n = seq.duration if frames is None else frames
    reader = sequence.SequenceReader(seq, w, h, depth, 0, n, **kw)
    try:
        for t in range(n):
            same_layers(sequence.grab(seq, t, w, h, depth, **kw), reader.read(), f"quadro {t}")
        assert reader.read() is None and reader.error == ""
    finally:
        reader.close()


def nested_frames(seq, frames) -> list[int]:
    """Quadros da sequência interna que o primeiro clipe de sequência mostra."""
    out = []
    for t in frames:
        li = next(x for x in sequence.grab(seq, t, W, H).layers if x.nested is not None)
        out.append(li.nested.layers.frame)
    return out


# ------------------------------------------------------------------ tempo e leitura
def test_grab_gives_the_inner_layers_at_the_inner_frame(renderer):
    outer, inner, clip = pair()
    fl = sequence.grab(outer, 7, W, H)
    assert len(fl.layers) == 1 and fl.layers[0].stack is None
    n = fl.layers[0].nested
    assert n.seq is inner and n.size == (W, H) and n.layers.frame == 7
    assert np.array_equal(n.layers.layers[0].image, gen(inner, inner.clips[0], 7, W, H, 8))
    assert fl.layers[0].image.shape == (2, 2, 3)  # sem imagem própria: quem amostra vê preto, ninguém quebra


def test_reader_agrees_with_grab_on_a_plain_nested_clip(renderer):
    outer, inner, clip = pair()
    agree(outer)
    agree(outer, depth=16)


def test_reader_agrees_at_every_speed_and_entrance(renderer):
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 2.0)
    assert nested_frames(outer, [0, 1, 2]) == [0, 2, 4]
    agree(outer)
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 0.4)
    assert nested_frames(outer, [0, 1, 2, 3, 4, 5]) == [0, 0, 0, 1, 1, 2]
    agree(outer)
    outer, inner, clip = pair()
    outer.trim_start(clip.id, 24)  # a entrada: o clipe começa 1 s depois na interna
    outer.move(clip.id, 6)
    assert clip.start == 6 and nested_frames(outer, [6, 7]) == [24, 25]
    agree(outer)


def test_reader_agrees_in_reverse_and_frozen(renderer):
    outer, inner, clip = pair()
    outer.retime(clip.id, reverse=True)
    assert nested_frames(outer, [0, 1]) == [95, 94]
    agree(outer)
    outer, inner, clip = pair()
    outer.freeze_frame(clip.id, 10, 12)
    agree(outer)


def test_reader_agrees_with_a_different_frame_rate(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, fps="25/1")
    put(outer, inner)
    assert nested_frames(outer, [0, 24, 48]) == [0, 25, 50]
    agree(outer)
    outer = tl.Sequence(width=W, height=H, fps_str="30/1")
    inner = inner_of(outer, fps="24/1")
    put(outer, inner)
    agree(outer)


def test_reader_agrees_with_two_levels(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    middle = inner_of(outer, (0.9, 0.1, 0.1))
    deep = inner_of(outer, (0.1, 0.1, 0.9), seconds=2.0)
    c = put(middle, deep, 0, vtrack=1)
    middle.set_speed(c.id, 0.5)
    put(outer, middle)
    li = sequence.grab(outer, 5, W, H).layers[0]
    below, top = li.nested.layers.layers
    assert below.nested is None and top.nested.seq is deep and top.nested.layers.frame == 2
    agree(outer)


def test_reader_agrees_with_two_nested_clips_at_once_and_the_same_one_twice(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    a = inner_of(outer, (0.9, 0.1, 0.1), seconds=2.0)
    b = inner_of(outer, (0.1, 0.1, 0.9), seconds=2.0)
    put(outer, a)
    c = put(outer, b, 0, vtrack=1)
    outer.trim_end(c.id, 24)
    twice = put(outer, a, 0, vtrack=2)
    outer.set_speed(twice.id, 0.5)
    assert len(sequence.grab(outer, 10, W, H).layers) == 3
    agree(outer)


def test_reader_of_real_files_inside(renderer, sample_video, sample_image):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    vid = inner.insert_media(media.probe_source(sample_video), at=0)[0]
    inner.trim_start(vid.id, 6)
    inner.move(vid.id, 0)
    pic = inner.insert_media(media.probe_source(sample_image), at=4, vtrack=1)[0]
    inner.trim_end(pic.id, 12)
    c = put(outer, inner)
    outer.set_speed(c.id, 1.5)
    agree(outer)
    c2 = put(outer, inner, 0, vtrack=1)
    outer.retime(c2.id, reverse=True)
    agree(outer)


def test_cut_and_gap_between_nested_clips_reopen_nothing_wrong(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, seconds=3.0)
    a = put(outer, inner)
    outer.trim_end(a.id, 12)
    b = put(outer, inner, at=30)
    outer.trim_start(b.id, 60)  # salto para a frente: o leitor interno reabre
    agree(outer)
    # os mesmos quadros lendo a partir do meio
    reader = sequence.SequenceReader(outer, W, H, 8, 40, 5)
    try:
        for t in range(40, 45):
            same_layers(sequence.grab(outer, t, W, H), reader.read(), f"quadro {t}")
    finally:
        reader.close()


def test_slow_motion_returns_the_same_object_only_for_the_same_frame(renderer):
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 0.5)
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 6)
    try:
        got = [reader.read().layers[0].nested.layers for _t in range(6)]
    finally:
        reader.close()
    assert [f.frame for f in got] == [0, 0, 1, 1, 2, 2]
    assert got[0] is got[1] and got[2] is got[3] and got[1] is not got[2]


def test_empty_inner_sequence_and_empty_inner_frame(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    empty = outer.ensure_set().create(W, H, "24/1")
    c = put(outer, empty)
    assert c.dur == 1
    assert sequence.grab(outer, 0, W, H).layers[0].nested.layers.layers == []
    agree(outer)
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, seconds=1.0)
    inner.move(inner.clips[0].id, 12)  # buraco nos 12 primeiros quadros
    put(outer, inner)
    assert sequence.grab(outer, 3, W, H).layers[0].nested.layers.layers == []
    agree(outer)


def test_close_closes_the_inner_reader_and_the_errors_go_up(renderer, monkeypatch):
    outer, inner, clip = pair()
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 5)
    reader.read()
    stream = reader._streams[clip.id]
    assert isinstance(stream, sequence._NestedStream)
    closed = stream.reader
    reader.close()
    assert stream.reader is None and closed._closed and reader.read() is None

    def bad(*a):
        raise ValueError("gerador quebrado")

    outer, inner, clip = pair()
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 3)
    monkeypatch.setitem(sequence.RENDERERS, KIND, bad)
    try:
        assert reader.read().layers[0].nested.layers.layers[0].image.shape == (H, W, 4)  # camada transparente
        assert "gerador quebrado" in reader.error
    finally:
        reader.close()


# ------------------------------------------------------------------ tamanhos
def test_inner_canvas_follows_the_decode_size():
    outer = tl.Sequence(width=1920, height=1080, fps_str="24/1")
    inner = outer.ensure_set().create(1920, 1080, "24/1")
    clip = outer.insert_media(nested_src(outer, inner), at=0)[0]
    size = lambda s=outer, cw=1920, ch=1080: sequence.nested_canvas(inner, *sequence.decode_size(s, clip, cw, ch))
    assert size() == (1920, 1080)
    assert size(cw=640, ch=360) == (640, 360)  # prévia reduzida: tela reduzida
    assert size(cw=3840, ch=2160) == (1920, 1080)  # nunca maior que a sequência
    outer.set_values(clip.id, {"escala": 0.5})
    assert size(cw=640, ch=360) == (640, 360)  # escala menor não reduz (decode_size só amplia)
    outer.set_values(clip.id, {"escala": 2.0})
    assert size(cw=640, ch=360) == (1280, 720)  # ampliado: mais resolução
    assert size(cw=1920, ch=1080) == (1920, 1080)  # até o tamanho dela
    outer.set_values(clip.id, {"escala": 1.0, "encaixe": "esticar"})
    tall = tl.Sequence(width=1080, height=1920, fps_str="24/1", sources=outer.sources)
    tall.clips, tall.siblings = [clip], outer.siblings
    assert sequence.decode_size(tall, clip, 1080, 1920) == (1080, 1080)
    # "Esticar": a proporção da interna, com a maior medida: estica a imagem, não reencaixa lá dentro
    assert sequence.nested_canvas(inner, 1080, 1080) == (1920, 1080)
    assert sequence.nested_canvas(inner, 641, 361) == (642, 360)  # lados pares
    assert sequence.nested_canvas(tl.Sequence(width=1921, height=1081), 5000, 5000) == (1921, 1081)  # o tamanho dela


def test_a_nested_clip_keeps_its_proportion_in_the_window_unlike_a_generated_one():
    from pelicula import compositor
    outer = tl.Sequence(width=1920, height=1080, fps_str="24/1", window=2.39)
    inner = outer.ensure_set().create(1920, 1080, "24/1")
    clip = outer.insert_media(nested_src(outer, inner), at=0)[0]
    _x, _y, aw, ah = outer.window_rect(1920, 1080)
    bw, bh = compositor.fit_box(outer, clip, 1920, 1080)
    assert (bw, bh) != (aw, ah) and bw / bh == pytest.approx(16 / 9) and bh == ah  # mostra inteira, dentro da janela
    gen_clip = outer.insert_media(vsrc(), at=0, vtrack=1)[0]
    assert compositor.fit_box(outer, gen_clip, 1920, 1080) == (aw, ah)
    w, h = sequence.decode_size(outer, clip, 1920, 1080)
    assert w / h == pytest.approx(16 / 9, abs=0.01)


# ------------------------------------------------------------------ quem olha a montagem inteira
def _flat_and_twin(sources):
    """(montagem sem aninhar, a gêmea de fora, a de dentro) com os mesmos arquivos."""
    flat = tl.Sequence(width=W, height=H, fps_str="24/1")
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    for s in (flat, inner):
        at = 0
        for src in sources:
            c = s.insert_media(src, at=at)[0]
            at = c.end
    put(outer, inner)
    return flat, outer, inner


def test_legal_range_counts_the_clips_inside_as_if_not_nested():
    legal = lambda p: fsrc(p, frames=48)
    full = lambda p: fsrc(p, frames=48, color_range="pc")
    for mix in ([full("a"), legal("b"), legal("c")], [legal("a"), full("b"), full("c")], [full("a"), legal("b")],
                [legal("a"), full("b")]):
        flat, outer, _inner = _flat_and_twin(mix)
        assert sequence.legal_range(outer) == sequence.legal_range(flat), mix
    # um clipe de vídeo de fora mais os de dentro: a maioria é contada por clipe, não por "um clipe de sequência"
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    at = 0
    for p in "ab":
        at = inner.insert_media(full(p), at=at)[0].end
    c = put(outer, inner)
    outer.insert_media(legal("c"), at=c.end)
    assert sequence.legal_range(outer) is False
    # o mesmo clipe de sequência duas vezes pesa duas vezes
    outer2 = tl.Sequence(width=W, height=H, fps_str="24/1")
    one = outer2.ensure_set().create(W, H, "24/1")
    one.insert_media(full("x"), at=0)
    a = put(outer2, one)
    b = put(outer2, one, at=a.end)
    outer2.insert_media(legal("y"), at=b.end)
    assert sequence.legal_range(outer2) is False


def test_helpers_see_inside_and_only_what_is_used():
    a, b, c = fsrc("C:/m/a.mp4"), fsrc("C:/m/b.mp4", bit_depth=10, codec="hevc"), fsrc("C:/m/solta.mp4")
    outer = tl.Sequence(width=W, height=H, fps_str="24/1", name="Filme")
    middle = outer.ensure_set().create(W, H, "24/1")
    deep = outer.siblings.create(W, H, "24/1")
    other = outer.siblings.create(W, H, "24/1")
    deep.insert_media(a, at=0)
    middle.insert_media(b, at=0, vtrack=1)
    put(middle, deep)
    put(outer, middle)
    other.insert_media(c, at=0)  # noutra sequência do projeto: esta montagem não lê
    assert sequence.first_video_source(outer).path == a.path  # o primeiro, de baixo para cima, em qualquer nível
    assert sorted(export.job_inputs(sequence.media_info(outer), outer)) == [a.path, b.path]
    assert sequence.missing_sources(outer) == [a.path, b.path]
    assert sequence.missing_sources(other) == [c.path]
    assert sorted(s.path for s in outer.deep_sources()) == [a.path, b.path]
    info = sequence.media_info(outer)
    assert info.has_audio and info.width == W and info.path.replace("\\", "/").endswith("m/Filme.mp4")
    unnamed = sequence.media_info(deep)
    assert unnamed.path.endswith(".mp4")


def test_media_info_of_a_nested_sequence_with_only_sound_and_of_generated_clips(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    snd = tl.Source("C:/m/musica.wav", 0, 0, 24.0, "24/1", 1, 4.0, has_video=False, has_audio=True, audio_codec="pcm")
    inner.insert_media(snd, at=0)
    src = nested_src(outer, inner)
    assert not src.has_video and src.has_audio
    clips = outer.insert_media(src, at=0)
    assert [c.kind for c in clips] == [tl.AUDIO]
    assert sequence.media_info(outer).path.replace("\\", "/").startswith("C:/m/") and sequence.first_video_source(outer) is None
    assert export.job_inputs(sequence.media_info(outer), outer) == ["C:/m/musica.wav"]
    outer, inner, _c = pair()  # só clipes gerados dentro: como uma montagem de gerados
    assert sequence.first_video_source(outer) is None and sequence.legal_range(outer) is False
    assert sequence.missing_sources(outer) == []


def test_a_missing_file_inside_is_a_skipped_layer_and_a_notice(renderer):
    outer, inner, _c = pair()
    gone = fsrc()
    inner.insert_media(gone, at=0, vtrack=1)
    assert sequence.missing_sources(outer) == [gone.path]
    fl = sequence.grab(outer, 3, W, H)
    assert len(fl.layers[0].nested.layers.layers) == 1  # só o gerador; o arquivo que falta some, como fora
    agree(outer, frames=8)


def test_thumbnail_of_a_nested_source_is_empty_and_the_clip_is_not_generated(renderer):
    outer, inner, clip = pair()
    src = nested_src(outer, inner)
    assert sequence.source_thumbnail(src, 32, 18).shape == (18, 32, 3)
    assert sequence.source_thumbnail(src, 32, 18, rgba=True).shape == (18, 32, 4)
    assert not sequence.source_thumbnail(src, 32, 18).any()


def test_used_by_looks_at_the_whole_project():
    a = tl.Sequence(width=W, height=H, fps_str="24/1")
    a.insert_media(fsrc(), at=0)
    assert "titulos_geradores" not in modules.used_by(None, a)
    b = a.ensure_set().create(W, H, "24/1")
    b.insert_media(vsrc(), at=0)
    used = modules.used_by(None, a)
    assert "titulos_geradores" in used and "edicao" in used


def test_camera_profile_is_seen_inside_and_ignored_on_the_nested_clip_itself():
    outer, inner, clip = pair()
    assert not camera.uses_profiles(outer)
    clip.values["camera_entrada"] = "slog3"
    assert not camera.uses_profiles(outer)  # no próprio clipe de sequência não faz nada
    assert camera.uniforms(clip.values, outer.sources[clip.src], camera.Target()) is None
    inner.clips[0].values["camera_entrada"] = "slog3"
    assert camera.uses_profiles(outer) and camera.uses_profiles(inner)
    other = outer.siblings.create(W, H, "24/1")
    assert not camera.uses_profiles(other)


def test_nested_sequence_with_only_a_beep_says_it_has_sound(renderer):
    from pelicula import generators
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    assert not nested_src(outer, inner).has_audio
    inner.insert_media(generators.new_source(generators.LEADER, inner), at=0)
    assert not inner.has_audio and nested_src(outer, inner).has_audio
    assert [c.kind for c in outer.insert_media(nested_src(outer, inner), at=0)] == [tl.VIDEO, tl.AUDIO]
    assert audiomix.has_audio(inner)
